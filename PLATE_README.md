# 車牌辨識 → 自動開柵欄

把原本「門鈴拍照推播」升級成:**按門鈴 → 拍照 → 辨識車牌**
- 車牌**在白名單** → 自動開柵欄(送 STM32 `UNLOCK`),可設定 N 秒後自動關
- 車牌**不在白名單 / 沒認出** → 維持原本行為,推照片(+ 辨識到的車牌)給管理員人工判斷

辨識完全在 Raspberry Pi 上跑,沿用現有的 `DOORBELL` 事件流程,不需新增感測器。

---

## 一、新增/修改的檔案

| 檔案 | 說明 |
|------|------|
| `plate_recognition.py`(新增) | 車牌辨識封裝(fast-alpr / ONNX),`recognize_plate(影像) → (車牌, 信心值)` |
| `plate_utils.py`(新增) | 車牌正規化 + `authorized_plates` 白名單資料存取(無重量級相依,app 與 server 共用) |
| `app.py`(修改) | `push_doorbell_photo()` 加辨識+開柵欄分支;LINE 車牌管理指令;柵欄用語 |
| `stm32_wifi_server.py`(修改) | 新增車牌白名單的 CLI 管理指令 |
| `requirements.txt`(新增) | 套件清單,含 `fast-alpr[onnx]` |

---

## 二、安裝(在 Raspberry Pi 4 上)

> ⚠️ 請用 **64-bit Raspberry Pi OS（aarch64）**,onnxruntime 才有預編譯 wheel。

```bash
pip install -r requirements.txt
# 或只裝辨識套件:
pip install "fast-alpr[onnx]"
```

第一次辨識時會**自動下載模型權重**(偵測 + OCR,約數十 MB),之後可離線使用。
- 偵測模型:`yolo-v9-t-384-license-plate-end2end`
- OCR 模型:`cct-xs-v2-global-model`(global 純英數,適合台灣車牌)

兩者都可在 `plate_recognition.py` 最上方的 `DETECTOR_MODEL` / `OCR_MODEL` 換掉。

---

## 三、先驗準度(最重要,別跳過)

整套最大的風險是「台灣車牌讀不讀得準」。先單獨測:

```bash
python plate_recognition.py 一張你家車牌的照片.jpg
# 會印出:辨識結果:'ABC1234'  信心值:0.xxx
```

拿幾張不同角度/光線的照片測。準度可接受再往下整合;若常讀錯,參考下面「提升準度」。

---

## 四、管理車牌白名單

兩種方式,操作的是同一張 `authorized_plates` 表(存在 `door_logs.db`)。
車牌會自動正規化(全大寫、去掉 `-` 與空白),所以 `ABC-1234` 和 `abc 1234` 視為同一台。

**A. 命令列(在 Pi 上):**
```bash
python3 stm32_wifi_server.py add-plate ABC-1234 小明
python3 stm32_wifi_server.py list-plates
python3 stm32_wifi_server.py disable-plate ABC-1234
```

**B. LINE(傳給 bot,限管理員):**
```
新增車牌 ABC-1234 小明
車牌清單
刪除車牌 ABC-1234
```

---

## 五、可調參數(`app.py` 最上方)

| 參數 | 預設 | 說明 |
|------|------|------|
| `PLATE_CONF_THRESHOLD` | `0.5` | OCR 信心值門檻,低於此視為沒認出 → 走門鈴流程。誤開太多就調高 |
| `BARRIER_AUTO_CLOSE_SEC` | `8` | 自動開柵欄後幾秒自動關;設 `0` 表示不自動關(改由管理員手動關) |

LINE 手動控制(白名單以外的情況):`開柵欄` / `關柵欄`(也接受舊的 `開門` / `關門`)。

---

## 六、STM32 韌體要改的地方

Pi 端送的指令**名稱不變**(`UNLOCK` / `LOCK`),你只要把 STM32 收到指令後驅動的東西從「門鎖」換成「柵欄」:

- 收到 `UNLOCK` → **抬桿**(伺服馬達轉到開的角度,例如 90°;或繼電器驅動柵欄馬達上升),回 `OK_UNLOCKED`
- 收到 `LOCK` → **放桿**(伺服馬達回 0°),回 `OK_LOCKED`
- `STATUS` → 回 `LOCKED` / `UNLOCKED`(目前桿子是放下/抬起)

自動關有兩種做法,擇一:
1. **Pi 端**(本專案預設):開柵欄後由 `BARRIER_AUTO_CLOSE_SEC` 計時送 `LOCK`,韌體保持單純
2. **STM32 端**:收到 `UNLOCK` 後內部計時自動放桿(這時把 `BARRIER_AUTO_CLOSE_SEC` 設 0)
> 安全建議:加一個「車輛已通過」感測器(地感/紅外),通過後才放桿,避免壓到車。

---

## 七、提升台灣車牌準度(若預設模型不夠準)

1. 換 OCR 模型:試 `cct-s-v2-global-model`(較大、較準,RPi4 仍可跑)
2. 蒐集幾百張台灣車牌 fine-tune `fast-plate-ocr`(在 PC/Colab 的 GPU 上訓練,**不要在 Pi 上訓練**),匯出 ONNX 後丟回 Pi,用 `ALPR(..., ocr_model_path=..., ocr_config_path=...)` 載入
3. 或直接找 GitHub 上別人 train 好的台灣車牌權重

---

## 八、運作流程圖

```
按門鈴(STM32 DOORBELL,沿用現有路徑)
        │
        ▼
push_doorbell_photo()  [app.py]
  ├─ capture_photo_once()             拍照
  ├─ plate_recognition.recognize_plate()  辨識
  └─ plate_utils.get_authorized_plate()   查白名單
        │
   ┌────┴────────────────────────┐
 在白名單                      不在 / 沒認出 / 信心不足
   │                              │
 send_command_to_stm32("UNLOCK")  推照片 + 車牌給管理員
 抬桿 + 推播通知                  (管理員可手動「開柵欄」)
   │
 (BARRIER_AUTO_CLOSE_SEC 秒後自動 LOCK)
```
