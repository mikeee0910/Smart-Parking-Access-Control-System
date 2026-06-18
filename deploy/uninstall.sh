#!/usr/bin/env bash
#
# Smart Parking — 移除三支 systemd 服務
# 用法： sudo bash deploy/uninstall.sh
#
set -euo pipefail

# 反向順序停止：先停 ngrok，再 app，最後 stm32
SERVICES=(parking-ngrok parking-app parking-stm32)

if [[ $EUID -ne 0 ]]; then
  echo "請用 sudo 執行： sudo bash $0" >&2
  exit 1
fi

systemctl disable --now "${SERVICES[@]}" 2>/dev/null || true

for svc in "${SERVICES[@]}"; do
  rm -f "/etc/systemd/system/$svc.service"
  echo "已移除 /etc/systemd/system/$svc.service"
done

systemctl daemon-reload
echo "完成，三支服務已移除。"
