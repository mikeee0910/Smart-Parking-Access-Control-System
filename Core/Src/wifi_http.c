#include "wifi_http.h"
#include "wifi.h"
#include "cmsis_os.h"
#include <stdio.h>
#include <string.h>

#define SOCKET_ID          0
#define SEND_TIMEOUT       5000
#define RECV_TIMEOUT       5000
#define CONNECT_RETRIES    3
#define SOCKET_REUSE_DELAY 200

static uint8_t ServerIP[4] = {SERVER_IP_0, SERVER_IP_1, SERVER_IP_2, SERVER_IP_3};
static uint8_t TxBuf[512];
static uint8_t RxBuf[512];

int WiFi_HTTP_Init(void)
{
    uint8_t mac[6];
    uint8_t ip[4];

    printf("WiFi: initializing module...\r\n");
    if (WIFI_Init() != WIFI_STATUS_OK) {
        printf("WiFi: init FAILED\r\n");
        return -1;
    }
    printf("WiFi: module ready\r\n");

    if (WIFI_GetMAC_Address(mac, sizeof(mac)) == WIFI_STATUS_OK) {
        printf("WiFi: MAC %02X:%02X:%02X:%02X:%02X:%02X\r\n",
               mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    }

    printf("WiFi: connecting to \"%s\"...\r\n", WIFI_SSID);
    if (WIFI_Connect(WIFI_SSID, WIFI_PASSWORD, WIFI_ECN_WPA2_PSK) != WIFI_STATUS_OK) {
        printf("WiFi: connect FAILED\r\n");
        return -2;
    }

    if (WIFI_GetIP_Address(ip, sizeof(ip)) == WIFI_STATUS_OK) {
        printf("WiFi: IP %d.%d.%d.%d\r\n", ip[0], ip[1], ip[2], ip[3]);
    }

    printf("WiFi: connected OK\r\n");
    return 0;
}

static int http_post_ex(const char *path, const char *body, uint8_t *resp,
                        uint16_t resp_size, uint32_t recv_timeout_ms,
                        osMessageQueueId_t abort_queue)
{
    uint16_t sent, received;
    int body_len = body ? (int)strlen(body) : 0;
    int len;

    for (int attempt = 1; attempt <= CONNECT_RETRIES; attempt++) {
        if (attempt > 1) {
            osDelay(SOCKET_REUSE_DELAY);
        }

        if (WIFI_OpenClientConnection(SOCKET_ID, WIFI_TCP_PROTOCOL, "TCP",
                                      ServerIP, SERVER_PORT, 0) == WIFI_STATUS_OK) {
            break;
        }

        printf("HTTP: TCP connect failed (%d/%d)\r\n", attempt, CONNECT_RETRIES);
        WIFI_CloseClientConnection(SOCKET_ID);

        if (attempt == CONNECT_RETRIES) {
            return -1;
        }
    }

    len = snprintf((char *)TxBuf, sizeof(TxBuf),
                   "POST %s HTTP/1.1\r\n"
                   "Host: %d.%d.%d.%d:%d\r\n"
                   "Content-Type: application/x-www-form-urlencoded\r\n"
                   "Content-Length: %d\r\n"
                   "Connection: close\r\n"
                   "\r\n%s",
                   path,
                   ServerIP[0], ServerIP[1], ServerIP[2], ServerIP[3], SERVER_PORT,
                   body_len,
                   body ? body : "");

    if (WIFI_SendData(SOCKET_ID, TxBuf, (uint16_t)len, &sent, SEND_TIMEOUT) != WIFI_STATUS_OK) {
        printf("HTTP: send failed\r\n");
        WIFI_CloseClientConnection(SOCKET_ID);
        return -2;
    }

    osDelay(200);

    received = 0;
    uint32_t deadline = HAL_GetTick() + recv_timeout_ms;
    uint16_t cap = (resp_size < sizeof(RxBuf)) ? (uint16_t)(resp_size - 1)
                                               : (uint16_t)(sizeof(RxBuf) - 1);
    while (HAL_GetTick() < deadline && received < cap) {
        uint16_t got = 0;
        WIFI_ReceiveData(SOCKET_ID, RxBuf + received,
                         cap - received, &got, 300);
        if (got == 0) {
            if (abort_queue && osMessageQueueGetCount(abort_queue) > 0) {
                printf("HTTP: poll aborted, event pending\r\n");
                WIFI_CloseClientConnection(SOCKET_ID);
                return -3;
            }
            osDelay(50);
            continue;
        }
        received += got;
        if (strstr((char *)RxBuf, "\r\n\r\n") != NULL) {
            uint32_t body_deadline = HAL_GetTick() + 400;
            while (HAL_GetTick() < body_deadline && received < cap) {
                got = 0;
                WIFI_ReceiveData(SOCKET_ID, RxBuf + received,
                                 cap - received, &got, 200);
                if (got == 0) break;
                received += got;
            }
            break;
        }
    }
    RxBuf[received] = '\0';

    WIFI_CloseClientConnection(SOCKET_ID);
    osDelay(SOCKET_REUSE_DELAY);

    if (resp && received > 0) {
        memcpy(resp, RxBuf, received + 1);
    }

    return (int)received;
}

static int http_post(const char *path, const char *body, uint8_t *resp, uint16_t resp_size)
{
    return http_post_ex(path, body, resp, resp_size, 1500, NULL);
}

int WiFi_HTTP_PostRFID(const uint8_t uid[4], uint8_t *unlock)
{
    char path[64];
    uint8_t resp[256];
    int ret;

    snprintf(path, sizeof(path), "/stm32/rfid?uid=%02X%02X%02X%02X&plain=1",
             uid[0], uid[1], uid[2], uid[3]);

    printf("HTTP POST %s\r\n", path);

    ret = http_post(path, NULL, resp, sizeof(resp));
    if (ret < 0)
        return ret;

    printf("HTTP resp: %s\r\n", resp);

    if (unlock) {
        *unlock = (strstr((char *)resp, "UNLOCK") != NULL) ? 1 : 0;
    }

    return 0;
}

int WiFi_HTTP_PostDoorbell(uint8_t *unlock)
{
    uint8_t resp[256];
    int ret;

    if (unlock) *unlock = 0;

    printf("HTTP POST /stm32/doorbell\r\n");

    /* 伺服器要先拍照 + 車牌辨識才回應(約 2~3 秒),recv timeout 拉到 15 秒 */
    ret = http_post_ex("/stm32/doorbell?plain=1", NULL, resp, sizeof(resp), 15000, NULL);
    if (ret < 0)
        return ret;

    printf("HTTP resp: %s\r\n", resp);

    /* 回應 body 是 "UNLOCK"(白名單車牌)或 "OK"(其他) */
    if (unlock)
        *unlock = (strstr((char *)resp, "UNLOCK") != NULL) ? 1 : 0;

    return 0;
}

int WiFi_HTTP_Poll(char *cmd_out, int cmd_out_size, osMessageQueueId_t abort_queue)
{
    uint8_t resp[256];
    int ret;

    if (cmd_out == NULL || cmd_out_size <= 0) return -1;
    cmd_out[0] = '\0';

    ret = http_post_ex("/stm32/poll?plain=1", NULL, resp, sizeof(resp), 30000, abort_queue);
    if (ret < 0) return ret;

    char *body = strstr((char *)resp, "\r\n\r\n");
    body = body ? body + 4 : (char *)resp;

    if (strstr(body, "UNLOCK"))      snprintf(cmd_out, cmd_out_size, "UNLOCK");
    else if (strstr(body, "LOCK"))   snprintf(cmd_out, cmd_out_size, "LOCK");
    else if (strstr(body, "STATUS")) snprintf(cmd_out, cmd_out_size, "STATUS");
    else                              snprintf(cmd_out, cmd_out_size, "NONE");

    return 0;
}

int WiFi_HTTP_PostAck(const char *result)
{
    char path[96];
    uint8_t resp[128];
    int ret;

    if (result == NULL) return -1;

    snprintf(path, sizeof(path), "/stm32/ack?result=%s&plain=1", result);
    printf("HTTP POST %s\r\n", path);

    ret = http_post(path, NULL, resp, sizeof(resp));
    if (ret < 0) {
        printf("HTTP ack failed (%d)\r\n", ret);
    }
    return ret;
}
