# 開機自動啟動（Raspberry Pi / systemd）

開機 → 等網路就緒 → 自動拉起三支長駐程式，任何一支掛掉自動重啟：

| 服務 | 指令 | Port |
|------|------|------|
| `parking-stm32` | `python3 stm32_wifi_server.py` | 5001（STM32 WiFi 橋接 / RFID / 門鈴） |
| `parking-app`   | `python3 app.py` | 5000（LINE bot + 相機 + 車牌辨識） |
| `parking-ngrok` | `ngrok http --url=…ngrok-free.dev 5000` | 對外開 5000，LINE webhook 才進得來 |

三者開機後等 `network-online.target`（連上網路）才啟動；`Restart=always` 確保掛掉自動重來。

## 前提

- 64-bit Raspberry Pi OS，已用 `pip install -r requirements.txt` 裝好套件（系統 `python3`）。
- `line_config.py`（密鑰，gitignore）已放在專案根目錄。
- `ngrok` 已安裝且已 `ngrok config add-authtoken <你的 token>`。

## 安裝

```bash
cd ~/Smart-Parking-Access-Control-System
sudo bash deploy/install.sh
```

> 用 `bash` 執行，不依賴檔案的執行位元（從 Windows 經 git 過來常會掉 +x）。

腳本會自動偵測專案路徑、登入帳號、ngrok 路徑填進 unit 檔，再 `enable --now` 三支。
（會把你的帳號加入 `dialout`/`video` 群組以存取 serial 與相機，**重開機後生效**。）

## 驗證

```bash
# 三支都要 active (running)
systemctl status parking-stm32 parking-app parking-ngrok

# 兩個 port 都在 listen
ss -ltnp | grep -E '5000|5001'

# Flask 活著就回 400（簽章錯誤）
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:5000/callback

# ngrok 隧道
curl -s http://127.0.0.1:4040/api/tunnels
# 或直接開： https://nonatheistical-dissidently-shameka.ngrok-free.dev/

# 最終：重開機後三支應自動起來
sudo reboot
```

## 日常操作

```bash
journalctl -u parking-app -f          # 即時看 app log（-stm32 / -ngrok 同理）
journalctl -u parking-app -b          # 看本次開機以來的 log
sudo systemctl restart parking-app    # 改完程式或補上 line_config.py 後重啟
sudo systemctl stop parking-ngrok     # 暫時關掉某一支
```

## 移除

```bash
sudo bash deploy/uninstall.sh
```

## 常見問題

- **ngrok 報 `1 simultaneous session`**：別處（或 SSH 視窗）還開著另一個 ngrok。Free tier 只能一個 agent，先把它關掉。
- **`parking-app` 一直重啟**：多半是 `line_config.py` 沒放上 Pi，或套件沒裝齊（`fast-alpr[onnx]`、`opencv-python`）。看 `journalctl -u parking-app -b` 找 Traceback。
- **開機時 WiFi 太慢**：確認 `systemctl is-enabled NetworkManager-wait-online.service` 為 enabled（Bookworm 預設有）。就算 ngrok 比網路早起，也會因 `Restart=always` 自己重試到通。
- **serial 權限 (`/dev/ttyACM0`)**：install.sh 已把帳號加進 `dialout`，但**要重開機才生效**。
- **改了 `.service` 內容**：重新 `sudo bash deploy/install.sh` 或手動 `sudo systemctl daemon-reload && sudo systemctl restart <服務>`。
