# 智慧停車場門禁系統 — Smart Parking Access Control System

基於 **STM32L475 IoT Discovery Kit** 與 **Raspberry Pi** 的智慧停車場門禁系統。提供 **RFID 刷卡**與**車牌辨識**兩種驗證方式,任一通過即自動開啟柵欄;並透過 **LINE Bot** 遠端控制柵欄、接收門口通知與查詢通行紀錄。

### 🎥 Demo 影片:[在 Google Drive 觀看](https://drive.google.com/file/d/1l3SzO02aXFCdFAMt_Jgk-UK2qNksE8ms/view)

### 📑 期末報告:[Final_Report.pdf](Final_Report.pdf)

### 📑 簡報:[ESLAB_Final.pdf](ESLAB_Final.pdf)

### 📂 Code: STM32 在 [`stm32`](../../tree/stm32) branch、Raspberry Pi 在 [`rpi`](../../tree/rpi) branch

### 👥 組員:R13921015 潘思翰 · R13921071 孟繁宇

---

## 一、動機

- 現今許多停車場已有車牌辨識,但多數系統仍以**單一辨識方式**為主。
- 同一位使用者可能會更換不同車輛,若只依賴車牌辨識,未登錄車牌可能無法通行。
- 若只依賴 RFID 感應卡,當使用者忘記帶卡、卡片遺失,或訪客沒有 ID 卡時,通行會受到限制;臨時訪客若沒有 RFID 或已登錄車牌,傳統系統較難即時處理。

因此本系統採 **RFID + 車牌辨識雙重驗證**:任一方式通過即放行,並以 LINE Bot 處理例外情況(管理員人工放行)與遠端管理,提升門禁系統的彈性。

---

## 二、系統總覽

![系統總覽](docs/overview.png)

系統由三個裝置協同運作,提供兩條開門路徑與一條遠端控制路徑:

1. **RFID 路徑**(STM32 主導)
   刷卡 → STM32 讀取 UID → 經 WiFi/HTTP 上傳 Raspberry Pi → 比對白名單 → `ALLOW` 則驅動柵欄開啟、`DENY` 則維持並寫入紀錄。

2. **車牌辨識路徑**(門鈴觸發)
   車輛抵達按下門鈴 → Raspberry Pi 拍照 → `fast-alpr` 辨識車牌 → 在白名單則**自動開柵欄**;未認出或不在白名單則把照片(含辨識結果)推播給管理員人工判斷。

3. **LINE Bot 遠端控制**
   管理員可隨時傳指令:`開柵欄` / `關柵欄` / 查詢狀態 / 查看歷史紀錄,並即時收到門口通知。

---

## 三、系統架構

![系統架構](docs/architecture.png)

| 裝置 | 角色 | 主要職責 |
|------|------|----------|
| **STM32L475**(IoT Discovery Kit) | 邊緣節點 | RFID 讀卡、門鈴按鈕、柵欄伺服馬達、WiFi/HTTP 通訊,FreeRTOS 多工 |
| **Raspberry Pi** | 伺服器 | Flask 伺服器、車牌辨識、LINE Bot、SQLite 資料庫、Webcam 拍照 |
| **LINE Bot** | 使用者介面 | 通知推播與遠端指令 |

---

## 四、作法

### 4.1 硬體

| 元件 | 介面 | 腳位 | 用途 |
|------|------|------|------|
| RC522 RFID Reader | SPI1 | CS=PA3, RST=PA4 | 讀取使用者感應卡 UID |
| SG90 360° 連續旋轉伺服馬達 | TIM2 CH1 PWM | PA15 | 驅動柵欄起降 |
| 簧片開關 | GPIO Input | PD14 | 柵欄到位偵測(旋轉計數) |
| 門鈴按鈕 | GPIO EXTI | PC13 | 訪客呼叫 / 觸發車牌辨識 |
| ISM43362 WiFi 模組 | SPI3 | (板載) | STM32 ↔ Raspberry Pi 無線通訊 |
| USB Webcam | USB | Raspberry Pi | 車牌辨識取像 |

### 4.2 STM32 韌體(`stm32` branch)

- **STM32CubeIDE / STM32 HAL** 開發
- **FreeRTOS(CMSIS-RTOS v2)**,三個使用者任務:
  - `RFIDTask` — 輪詢 RC522,讀到卡片即上傳 UID
  - `ButtonTask` — 處理門鈴按鈕(EXTI 中斷)事件
  - `WiFiTask` — 維護 WiFi 連線、HTTP 通訊與指令 Long Polling
- 模組:`rc522.c`(RFID 驅動)、`servo.c`(柵欄 PWM 控制 + 簧片開關計數)、`button.c`、`wifi_http.c`(WiFi + HTTP Client)
- 透過 **Long Polling** 即時接收 LINE 下達的指令,延遲約 **350 ms** 以內

### 4.3 Raspberry Pi 伺服器(`rpi` branch)

- **Python 3 / Flask**:接收 STM32 的 RFID/門鈴事件,提供 HTTP API
- **LINE Messaging API v3**:通知推播與管理員指令
- **車牌辨識**:`fast-alpr`(ONNX Runtime,免 PyTorch/TensorFlow)
  - 偵測模型:`yolo-v9-t-384-license-plate-end2end`
  - OCR 模型:`cct-xs-v2-global-model`(純英數,適合台灣車牌)
- **OpenCV**:Webcam 拍照
- **SQLite**(`door_logs.db`):`authorized_plates` 白名單 + 通行歷史紀錄
- **ngrok**:對外 HTTPS 通道(供 LINE Webhook)

### 4.4 車牌辨識流程

```
按門鈴(STM32 DOORBELL,沿用門鈴事件流程)
        │
        ▼
push_doorbell_photo()  [app.py]
  ├─ capture_photo_once()                  拍照
  ├─ plate_recognition.recognize_plate()   辨識車牌
  └─ plate_utils.get_authorized_plate()    查白名單
        │
   ┌────┴───────────────────────────┐
 在白名單                         不在 / 沒認出 / 信心不足
   │                                 │
 送 STM32「UNLOCK」抬桿            推照片 + 車牌給管理員
 + 推播通知                        (管理員可手動「開柵欄」)
   │
 (BARRIER_AUTO_CLOSE_SEC 秒後自動送「LOCK」放桿)
```

可調參數(`app.py`):`PLATE_CONF_THRESHOLD`(OCR 信心門檻,預設 0.5)、`BARRIER_AUTO_CLOSE_SEC`(自動關柵欄秒數,預設 8)。

### 4.5 對應課程技術

| 課程重點技術 | 本專案實作 |
|--------------|------------|
| **無線通訊** | STM32 透過 ISM43362(es-wifi, SPI3)連上 WiFi,以 HTTP Client 與 Raspberry Pi 雙向通訊;並以 **Long Polling** 即時接收 LINE 指令 |
| **即時作業系統 API** | FreeRTOS(CMSIS-RTOS v2);以事件旗標 / 佇列(`app_events.h`)在 `RFIDTask`、`ButtonTask`、`WiFiTask` 間同步 |
| **輸入 / 輸出裝置** | 輸入:RC522 RFID(SPI)、門鈴按鈕(EXTI)、簧片開關;輸出:SG90 伺服馬達柵欄(TIM2 PWM);Raspberry Pi 端 USB Webcam |
| **多工** | 三個 FreeRTOS 任務並行,event-driven 架構,WiFi long-poll 與 RFID 刷卡、門鈴中斷互不阻塞 |

---

## 五、成果

- **雙重驗證門禁**:RFID 刷卡與車牌辨識任一通過即自動開啟柵欄,實測可運作。
- **即時遠端控制**:STM32 以 Long Polling 接收 LINE 指令,端到端延遲約 350 ms 以內。
- **車牌辨識**:於 Raspberry Pi 端以 ONNX 模型即時辨識,信心門檻 0.5,開柵欄後 8 秒自動關閉。
- **完整紀錄**:所有通行事件寫入 SQLite,可透過 LINE 查詢歷史。

---

## 六、專案結構(Branch)

| Branch | 內容 | 說明 |
|--------|------|------|
| **`main`** | 專案報告 | 本 README、架構圖、簡報 |
| **`stm32`** | STM32 韌體 | STM32CubeIDE 專案、FreeRTOS 任務、RFID / 伺服馬達 / WiFi 驅動 |
| **`rpi`** | Raspberry Pi 伺服器 | Flask 伺服器、LINE Bot、車牌辨識、Webcam、SQLite |

> 車牌辨識的安裝、白名單管理與調校細節見 `rpi` branch 的 [`PLATE_README.md`](../../blob/rpi/PLATE_README.md)。

---

## 七、參考文獻 / 資料

1. STMicroelectronics — *B-L475E-IOT01A Discovery kit (STM32L475)*. <https://www.st.com/en/evaluation-tools/b-l475e-iot01a.html>
2. FreeRTOS / CMSIS-RTOS v2. <https://www.freertos.org/>
3. LINE — *Messaging API*. <https://developers.line.biz/en/docs/messaging-api/>
4. fast-alpr — *ONNX 車牌偵測 + OCR 套件*. <https://pypi.org/project/fast-alpr/>
5. ONNX Runtime. <https://onnxruntime.ai/>
6. OpenCV. <https://opencv.org/>
7. Flask. <https://flask.palletsprojects.com/>
8. ngrok. <https://ngrok.com/>
