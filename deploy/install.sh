#!/usr/bin/env bash
#
# Smart Parking — 安裝三支 systemd 服務（開機連上網路後自動啟動，掛掉自動重啟）
#   parking-stm32 (Flask :5001) / parking-app (Flask :5000) / parking-ngrok
#
# 用法：
#   cd ~/Smart-Parking-Access-Control-System
#   sudo bash deploy/install.sh
#
set -euo pipefail

SERVICES=(parking-stm32 parking-app parking-ngrok)

# --- 1. 必須 root（要寫入 /etc/systemd/system/）---
if [[ $EUID -ne 0 ]]; then
  echo "請用 sudo 執行： sudo bash $0" >&2
  exit 1
fi

# --- 2. 自動偵測 路徑 / 使用者 / ngrok（不寫死）---
DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
NGROK_BIN="$(command -v ngrok || true)"
PYTHON_BIN="/usr/bin/python3"

echo "APP_DIR   = $APP_DIR"
echo "RUN_USER  = $RUN_USER"
echo "NGROK_BIN = ${NGROK_BIN:-(找不到)}"
echo

# --- 3. 前置檢查 ---
fail=0
[[ -x "$PYTHON_BIN" ]]                    || { echo "✗ 找不到 $PYTHON_BIN"; fail=1; }
[[ -n "$NGROK_BIN" ]]                     || { echo "✗ 找不到 ngrok，請先安裝並執行 ngrok config add-authtoken <你的token>"; fail=1; }
[[ -f "$APP_DIR/app.py" ]]               || { echo "✗ 在 $APP_DIR 找不到 app.py"; fail=1; }
[[ -f "$APP_DIR/stm32_wifi_server.py" ]] || { echo "✗ 在 $APP_DIR 找不到 stm32_wifi_server.py"; fail=1; }
[[ $fail -eq 0 ]] || { echo; echo "前置檢查未通過，已中止。"; exit 1; }

if [[ ! -f "$APP_DIR/line_config.py" ]]; then
  echo "⚠  警告：$APP_DIR/line_config.py 不存在 → app.py 會因 import 失敗而不斷重啟。"
  echo "    請先把密鑰檔放上 Pi 再啟用，或之後補上後執行： sudo systemctl restart parking-app"
  echo
fi

# --- 4. 把使用者加進 dialout(serial) 與 video(相機) 群組（重開機後生效）---
usermod -aG dialout,video "$RUN_USER" || true

# --- 5. 由模板產生並安裝 unit 檔（順便清掉可能的 CRLF）---
for svc in "${SERVICES[@]}"; do
  src="$DEPLOY_DIR/$svc.service"
  dst="/etc/systemd/system/$svc.service"
  sed -e 's/\r$//' \
      -e "s|__RUN_USER__|$RUN_USER|g" \
      -e "s|__APP_DIR__|$APP_DIR|g" \
      -e "s|__NGROK_BIN__|$NGROK_BIN|g" \
      "$src" > "$dst"
  echo "已安裝 $dst"
done

# --- 6. 重新載入 + 開機啟用 + 立即啟動 ---
systemctl daemon-reload
systemctl enable --now "${SERVICES[@]}" || true

# --- 7. 顯示狀態 ---
echo
systemctl --no-pager --lines=0 status "${SERVICES[@]}" || true
echo
echo "完成。即時看 log： journalctl -u parking-app -f"
echo "若要驗證開機自動啟動： sudo reboot"
