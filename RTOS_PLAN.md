# STM32 改 FreeRTOS 步驟整理

目標：把現在阻塞式的 main loop（RFID polling + Button + WiFi long poll）拆成多個 task，
讓 long poll hang 住時 RFID/Button 仍能即時反應。

---

## 一、CubeMX 設定（在 STM32CubeIDE 裡開 `Project.ioc`）

1. **Middleware → FREERTOS**
   - Interface: **CMSIS_V2**（CubeMX 預設新版）
2. **Configuration → Tasks and Queues**
   - 預設那個 `defaultTask` 留著當作 idle/監控用，或改名 `MainTask`
   - 新增三個 task：
     | 名稱        | Priority      | Stack (Words) | 用途              |
     |-------------|---------------|---------------|-------------------|
     | `RFIDTask`  | osPriorityNormal | 512        | 每 200ms 掃 RC522 |
     | `ButtonTask`| osPriorityNormal | 256        | 偵測按鈕          |
     | `WiFiTask`  | osPriorityBelowNormal | 1024 | 長連線 + 所有 HTTP |
3. **Queues**（Tasks and Queues → Queues）
   - `wifiEventQueue`：item count 8，item size 16（傳事件給 WiFiTask）
4. **Mutexes**（Tasks and Queues → Mutexes）
   - `doorMutex`：保護 `door_locked` 狀態
5. **System Core → SYS**
   - **Timebase Source 一定要從 SysTick 改成 TIM6 或 TIM7**（FreeRTOS 會接管 SysTick）
6. **Heap**
   - Project Manager → Advanced → 看一下 `configTOTAL_HEAP_SIZE`，調到 **15360 (15KB)** 比較保險
7. 按 **GENERATE CODE**

⚠️ 重要：generate 前先 git commit 當前 stm32 branch，方便之後 diff 對照。
CubeMX 只會保留 `USER CODE BEGIN/END` 中間的東西，其它會被覆蓋。

---

## 二、Task 切割 & 通訊模型

```
┌──────────────┐  wifiEventQueue   ┌────────────┐
│  RFIDTask    │ ───── RFID UID ─▶ │            │
└──────────────┘                   │            │  long poll
┌──────────────┐                   │  WiFiTask  │ ◀══════════ Pi server
│  ButtonTask  │ ───── DOORBELL ─▶ │            │  POST RFID/doorbell/ack
└──────────────┘                   └────────────┘
                                          │
                                  doorMutex ▼
                                  door_locked
```

**關鍵原則：所有 `WiFi_HTTP_*` 只能由 WiFiTask 呼叫**，因為 ISM43362 走 SPI 不可重入。
其他 task 把事件丟進 `wifiEventQueue`，由 WiFiTask 序列化處理。

事件結構（放 `wifi_http.h` 或新檔 `app_events.h`）：
```c
typedef enum {
    EVT_RFID,
    EVT_DOORBELL
} EventType_t;

typedef struct {
    EventType_t type;
    uint8_t     uid[5];   /* RFID 用 */
} AppEvent_t;
```

---

## 三、各 task 程式骨架

### RFIDTask
```c
void RFIDTask_Entry(void *argument)
{
    uint8_t tagType[2], uid[5];
    for (;;) {
        if (RC522_Request(PICC_REQIDL, tagType) == MI_OK &&
            RC522_Anticoll(uid) == MI_OK) {
            AppEvent_t e = { .type = EVT_RFID };
            memcpy(e.uid, uid, 5);
            osMessageQueuePut(wifiEventQueueHandle, &e, 0, 0);
            osDelay(1000);  /* debounce */
        }
        osDelay(200);
    }
}
```

### ButtonTask
```c
void ButtonTask_Entry(void *argument)
{
    for (;;) {
        if (Button_WasPressed()) {
            AppEvent_t e = { .type = EVT_DOORBELL };
            osMessageQueuePut(wifiEventQueueHandle, &e, 0, 0);
            Servo_UnlockSequence();   /* 本地立刻動 servo */
        }
        osDelay(50);
    }
}
```

### WiFiTask（核心）
```c
void WiFiTask_Entry(void *argument)
{
    if (WiFi_HTTP_Init() != 0) {
        printf("WiFi init failed\r\n");
        osThreadExit();
    }

    for (;;) {
        AppEvent_t e;
        /* 等事件最多 100ms，沒事件就去 long poll */
        if (osMessageQueueGet(wifiEventQueueHandle, &e, NULL, 100) == osOK) {
            if (e.type == EVT_RFID) {
                uint8_t unlock = 0;
                if (WiFi_HTTP_PostRFID(e.uid, &unlock) == 0 && unlock) {
                    Servo_UnlockOnly();
                    osMutexAcquire(doorMutexHandle, osWaitForever);
                    door_locked = 0;
                    osMutexRelease(doorMutexHandle);
                }
            } else if (e.type == EVT_DOORBELL) {
                WiFi_HTTP_PostDoorbell();
            }
            continue;
        }

        /* 沒事件 → long poll */
        char cmd[16] = {0};
        if (WiFi_HTTP_Poll(cmd, sizeof(cmd)) == 0) {
            if (strcmp(cmd, "UNLOCK") == 0) {
                Servo_UnlockOnly();
                osMutexAcquire(doorMutexHandle, osWaitForever);
                door_locked = 0;
                osMutexRelease(doorMutexHandle);
                WiFi_HTTP_PostAck("OK_UNLOCKED");
            } else if (strcmp(cmd, "LOCK") == 0) {
                Servo_LockOnly();
                osMutexAcquire(doorMutexHandle, osWaitForever);
                door_locked = 1;
                osMutexRelease(doorMutexHandle);
                WiFi_HTTP_PostAck("OK_LOCKED");
            } else if (strcmp(cmd, "STATUS") == 0) {
                osMutexAcquire(doorMutexHandle, osWaitForever);
                uint8_t locked = door_locked;
                osMutexRelease(doorMutexHandle);
                WiFi_HTTP_PostAck(locked ? "LOCKED" : "UNLOCKED");
            }
        }
    }
}
```

---

## 四、main.c 要做的事

CubeMX generate 後：

1. **刪掉舊的 `while(1)` 內容**（RFID/Button/Poll 那一坨），改成空 loop 或留 `osDelay`
2. 在 `MX_FREERTOS_Init` 或 `main` 裡加：
   - `Servo_Init();`
   - `Button_Init();`（如果原本有）
   - `RC522_Init();`
3. Task entry function 寫在哪：
   - 如果用 CubeMX 自動生成的 task，它會在 `freertos.c` 或 `app_freertos.c` 給你空殼，把上面的程式貼進去
4. 把 `wifi_http.c` / `wifi_http.h` 留著不動（已經有 `Poll`/`PostAck`）
5. `door_locked` 移成 file-scope global 在 freertos.c，或包進新檔 `door_state.c`

---

## 五、踩雷檢查清單

- [ ] Timebase 改成 TIM6/TIM7（不然 HAL_Delay 跟 RTOS 打架）
- [x] 所有 `HAL_Delay` 在 task 裡改用 `osDelay`（毫秒一致，可直接替換）
- [ ] 不要從 ISR 呼叫 `osMessageQueuePut`，要用 `osMessageQueuePutFromISR` 版本
- [ ] WiFi SPI 中斷優先級要 ≥ `configMAX_SYSCALL_INTERRUPT_PRIORITY`（NVIC 數字要夠大）
- [ ] Servo 用 PWM timer（TIM2），不受 RTOS 影響
- [ ] Stack overflow：CubeMX 啟用 `Check For Stack Overflow → Option 2`，跑時若死機就先看這個
- [ ] `printf` 在多 task 同時用會交錯，必要時加 mutex 或只在一個 task 用

---

## 六、驗證順序（燒錄後）

1. 開機看 UART：`WiFi: connected OK` + 各 task 都有印出存活訊息
2. LINE 按「狀態」→ 應 < 1 秒回應（long poll task 接到指令）
3. 同時刷 RFID → RFID task 不被 long poll 阻塞，照樣讀到
4. 按門鈴 → ButtonTask 偵測 → WiFiTask POST → LINE 收到照片
5. 連續測 10 次 LINE 開/關門，檢查有沒有 BUSY / NO_RESPONSE

---

## 七、回退方案

如果搞壞：
```
git checkout stm32
git reset --hard bc453d9    # 回到 long poll 但無 RTOS 的版本
```
