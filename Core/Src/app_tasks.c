#include "app_tasks.h"
#include "app_events.h"
#include "rc522.h"
#include "button.h"
#include "servo.h"
#include "wifi_http.h"
#include <stdio.h>
#include <string.h>

osMessageQueueId_t wifiEventQueueHandle;
osMutexId_t        doorMutexHandle;
uint8_t            door_locked = 1;

void RFIDTask_Entry(void *argument)
{
    uint8_t tagType[2], uid[5];
    printf("[RFIDTask] started\r\n");

    for (;;) {
        if (RC522_Request(PICC_REQIDL, tagType) == MI_OK &&
            RC522_Anticoll(uid) == MI_OK) {
            printf("UID: %02X %02X %02X %02X\r\n",
                   uid[0], uid[1], uid[2], uid[3]);

            AppEvent_t e = { .type = EVT_RFID };
            memcpy(e.uid, uid, 5);
            osMessageQueuePut(wifiEventQueueHandle, &e, 0, 0);
            osDelay(1000);
        }
        osDelay(200);
    }
}

void ButtonTask_Entry(void *argument)
{
    printf("[ButtonTask] started\r\n");
    int prev_pos = -1;

    for (;;) {
        if (Button_WasPressed()) {
            printf("Doorbell pressed\r\n");
            AppEvent_t e = { .type = EVT_DOORBELL };
            osMessageQueuePut(wifiEventQueueHandle, &e, 0, 0);
        }

        int pos = Servo_IsLocked();
        if (pos != prev_pos) {
            printf("[LockPos] %s\r\n", pos ? "HIGH (locked)" : "LOW (unlocked)");
            prev_pos = pos;
        }

        osDelay(50);
    }
}

void WiFiTask_Entry(void *argument)
{
    printf("[WiFiTask] started\r\n");

    if (WiFi_HTTP_Init() != 0) {
        printf("WiFi init failed\r\n");
        osThreadExit();
    }
    printf("[WiFiTask] WiFi ready\r\n");

    for (;;) {
        AppEvent_t e;
        if (osMessageQueueGet(wifiEventQueueHandle, &e, NULL, 100) == osOK) {
            if (e.type == EVT_RFID) {
                uint8_t unlock = 0;
                if (WiFi_HTTP_PostRFID(e.uid, &unlock) == 0 && unlock) {
                    printf("Server: UNLOCK\r\n");
                    /* 開 → 等3秒 → 關(刷卡也自動關) */
                    Servo_UnlockSequence();
                    osMutexAcquire(doorMutexHandle, osWaitForever);
                    door_locked = Servo_IsLocked();
                    osMutexRelease(doorMutexHandle);
                } else {
                    printf("Server: DENY\r\n");
                }
            } else if (e.type == EVT_DOORBELL) {
                /* 門鈴:伺服器回應裡會帶開門指令(像 RFID 一樣,不走 poll/ack) */
                uint8_t unlock = 0;
                if (WiFi_HTTP_PostDoorbell(&unlock) == 0 && unlock) {
                    printf("Doorbell: UNLOCK (plate matched)\r\n");
                    /* 開 → 等3秒 → 關(車過後自動關;只想開不關改成 Servo_UnlockOnly()) */
                    Servo_UnlockSequence();
                    osMutexAcquire(doorMutexHandle, osWaitForever);
                    door_locked = Servo_IsLocked();
                    osMutexRelease(doorMutexHandle);
                }
            }
            continue;
        }

        char cmd[16] = {0};
        if (WiFi_HTTP_Poll(cmd, sizeof(cmd), wifiEventQueueHandle) == 0) {
            if (strcmp(cmd, "UNLOCK") == 0) {
                printf("LINE: UNLOCK\r\n");
                /* 開 → 等3秒 → 關(LINE 開門也自動關) */
                Servo_UnlockSequence();
                osMutexAcquire(doorMutexHandle, osWaitForever);
                door_locked = Servo_IsLocked();
                osMutexRelease(doorMutexHandle);
                WiFi_HTTP_PostAck("OK_UNLOCKED");
            } else if (strcmp(cmd, "LOCK") == 0) {
                printf("LINE: LOCK\r\n");
                if (Servo_LockOnly() == 0 && Servo_IsLocked()) {
                    osMutexAcquire(doorMutexHandle, osWaitForever);
                    door_locked = 1;
                    osMutexRelease(doorMutexHandle);
                    WiFi_HTTP_PostAck("OK_LOCKED");
                } else {
                    printf("LINE: lock FAILED (pos=%d)\r\n", Servo_IsLocked());
                    WiFi_HTTP_PostAck("FAIL_LOCK");
                }
            } else if (strcmp(cmd, "STATUS") == 0) {
                uint8_t hw_locked = Servo_IsLocked();
                osMutexAcquire(doorMutexHandle, osWaitForever);
                door_locked = hw_locked;
                osMutexRelease(doorMutexHandle);
                WiFi_HTTP_PostAck(hw_locked ? "LOCKED" : "UNLOCKED");
            }
        }
    }
}
