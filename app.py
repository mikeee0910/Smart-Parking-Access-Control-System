from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    ImageMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

from line_config import (
    CHANNEL_ACCESS_TOKEN,
    CHANNEL_SECRET,
    NGROK_URL,
    ADMIN_USER_ID
)

import cv2
import os
import time
import threading
import queue
import sqlite3

import plate_recognition
import plate_utils

try:
    import serial
except ImportError:
    serial = None


app = Flask(__name__)

# =========================
# Basic Settings
# =========================

IMAGE_DIR = "static"           # 拍照存放資料夾
MAX_IMAGES = 50                # static/ 最多保留幾張(避免無限長大)
CAMERA_ID = 0
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "door_logs.db")

STM32_PORT = "/dev/ttyACM0"
BAUDRATE = 115200

# 車牌辨識 / 柵欄設定
PLATE_CONF_THRESHOLD = 0.5      # OCR 信心值門檻,低於此視為「沒認出車牌」
BARRIER_AUTO_CLOSE_SEC = 0      # 車牌自動開柵欄後幾秒自動關;設 0 表示不自動關

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# =========================
# System State
# =========================

door_locked = True

MAX_HISTORY = 10

# 從 line_config.py 讀取
admin_user_id = ADMIN_USER_ID or None

# STM32 指令佇列：Flask 不直接讀 UART，避免跟背景監聽搶資料
stm32_command_queue = queue.Queue()

# STM32 連線狀態
stm32_connected = False


# =========================
# History Functions
# =========================

def init_db():
    """
    建立 SQLite log 資料表。
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                source TEXT NOT NULL,
                detail TEXT
            )
        """)
        conn.commit()


def add_history(action, source="LINE", detail=None):
    """
    action: 顯示在 LINE 歷史紀錄上的簡短動作
    source: 來源，例如 LINE 指令 / STM32 / 自動推播
    detail: debug 用細節，不顯示在 LINE 歷史紀錄
    """
    init_db()

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO history_logs (created_at, action, source, detail)
            VALUES (?, ?, ?, ?)
            """,
            (timestamp, action, source, detail)
        )

        conn.execute(
            """
            DELETE FROM history_logs
            WHERE id NOT IN (
                SELECT id
                FROM history_logs
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (MAX_HISTORY,)
        )

        conn.commit()


def get_history_text():
    """
    LINE 上簡短顯示：
    時間在上
    指令 / 動作在下
    不顯示 detail，不顯示 STM32 錯誤原因
    """
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, action, detail
            FROM history_logs
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()

    if not rows:
        return "目前尚無紀錄"

    text = "最近紀錄：\n"

    for i, row in enumerate(rows, start=1):
        text += f"{i}. {row['created_at']}\n"
        line = row['action']
        if row['detail'] and 'RFID' in row['action']:
            line += f"（UID: {row['detail']}）"
        text += f"   {line}\n\n"

    return text.strip()


# =========================
# Camera Functions
# =========================

def capture_photo_once():
    """
    拍照時才開啟 USB Webcam，拍完立即關閉。
    每張存成不重複的檔名(時間戳)，回傳存檔路徑;失敗回傳 None。
    這樣 LINE 連續傳多張時，每張會指到各自的檔案，不會被覆蓋成同一張。
    """
    cap = cv2.VideoCapture(CAMERA_ID)

    if not cap.isOpened():
        print("Cannot open USB webcam")
        return None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    frame = None
    ret = False

    # 丟掉前幾張，避免曝光不穩或舊畫面
    for _ in range(5):
        ret, frame = cap.read()
        time.sleep(0.05)

    cap.release()

    if not ret or frame is None:
        print("Failed to capture image")
        return None

    os.makedirs(IMAGE_DIR, exist_ok=True)

    # 檔名用「年月日_時分秒_毫秒」，確保每張都不同
    ms = int((time.time() % 1) * 1000)
    filename = time.strftime("%Y%m%d_%H%M%S") + f"_{ms:03d}.jpg"
    path = os.path.join(IMAGE_DIR, filename)

    cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print("Photo saved:", path)

    prune_old_images()

    return path


def prune_old_images(keep=MAX_IMAGES):
    """
    只保留最新的 keep 張照片，避免 static/ 無限長大。
    keep 設大一點，確保 LINE 來得及抓圖前不會被刪掉。
    """
    try:
        files = [
            os.path.join(IMAGE_DIR, f)
            for f in os.listdir(IMAGE_DIR)
            if f.lower().endswith(".jpg")
        ]
        files.sort(key=os.path.getmtime, reverse=True)

        for old in files[keep:]:
            os.remove(old)
    except Exception as e:
        print("Prune old images error:", e)


def get_image_url(filename):
    """
    LINE ImageMessage 需要 HTTPS URL。
    filename 為 static/ 下的檔名，每張不同，所以 LINE 連續多張會各自顯示。
    """
    image_url = f"{NGROK_URL}/static/{filename}"
    print("Image URL:", image_url)
    return image_url


# =========================
# LINE Push Function
# =========================

def _push_to_admin(messages):
    """把 messages 推播給管理員。集中處理 ApiClient 與例外。"""
    if admin_user_id is None:
        return

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=admin_user_id,
                    messages=messages
                )
            )
        print("Push message sent")

    except Exception as e:
        print("LINE push error:", e)


def _auto_close_barrier():
    """自動關柵欄(送 LOCK)。由 schedule_barrier_auto_close 在背景計時後呼叫。"""
    result = send_command_to_stm32("LOCK")

    if result == "OK_LOCKED":
        add_history("柵欄自動關閉", "自動")
    else:
        add_history("柵欄自動關閉失敗", "自動", detail=result)
        print("Auto close barrier failed, STM32 response:", result)


def schedule_barrier_auto_close():
    """開柵欄後排程 N 秒自動關。BARRIER_AUTO_CLOSE_SEC=0 則不自動關。"""
    if BARRIER_AUTO_CLOSE_SEC and BARRIER_AUTO_CLOSE_SEC > 0:
        threading.Timer(BARRIER_AUTO_CLOSE_SEC, _auto_close_barrier).start()


def push_doorbell_photo():
    """
    門鈴觸發:拍照 → 車牌辨識,推 LINE 通知,並「回傳要給 STM32 的指令字串」:
      白名單車牌    → "UNLOCK"  (STM32 會在門鈴請求的回應裡拿到並直接開門,作法跟 RFID 一樣,
                                 不走會卡住的 poll/ack 通道)
      陌生 / 沒認出 → "OK"      (只推照片給管理員人工判斷)
    """
    add_history("門鈴觸發", "STM32")

    image_path = capture_photo_once()

    if not image_path:
        add_history("門鈴拍照失敗", "自動推播")
        print("Doorbell photo capture failed")
        _push_to_admin([TextMessage(text="有人按門鈴，但拍照失敗")])
        return "OK"

    add_history("門鈴拍照成功", "自動推播")
    image_url = get_image_url(os.path.basename(image_path))

    # ---- 車牌辨識 ----
    plate, conf = plate_recognition.recognize_plate(image_path)
    norm = plate_utils.normalize_plate(plate) if plate else ""
    recognized = bool(norm) and conf >= PLATE_CONF_THRESHOLD

    print(f"Plate recognize: text={plate!r} norm={norm!r} conf={conf:.3f} ok={recognized}")

    matched = plate_utils.get_authorized_plate(DB_PATH, norm) if recognized else None

    # ---- 白名單車牌 → 回 UNLOCK,STM32 收到回應後自己開(像 RFID) ----
    if matched:
        name = matched["name"] or norm
        add_history(f"{name} 車牌開柵欄", "車牌辨識", detail=norm)
        _push_to_admin([
            TextMessage(text=f"車牌 {norm}（{name}）已開柵欄"),
            ImageMessage(original_content_url=image_url, preview_image_url=image_url),
        ])
        return "UNLOCK"

    # ---- 沒認出 or 不在白名單 → 只推照片給管理員 ----
    if recognized:
        add_history("車牌不在白名單", "車牌辨識", detail=norm)
        head = f"有車輛按門鈴，車牌：{norm}（不在白名單）"
    else:
        head = "有人按門鈴"

    _push_to_admin([
        TextMessage(text=head + "，照片如下："),
        ImageMessage(original_content_url=image_url, preview_image_url=image_url),
    ])
    return "OK"


# =========================
# STM32 Serial Worker
# =========================

def stm32_worker():
    """
    只讓這個 thread 負責讀寫 STM32 UART。
    避免 LINE 指令和背景監聽同時讀 UART，造成 OK_UNLOCKED 被讀走。
    """
    global stm32_connected

    if serial is None:
        print("pyserial is not installed. Run: pip install pyserial")
        return

    try:
        ser = serial.Serial(STM32_PORT, BAUDRATE, timeout=0.2)
        time.sleep(2)
        stm32_connected = True
        print("STM32 serial connected:", STM32_PORT)

    except Exception as e:
        stm32_connected = False
        print("STM32 serial connection failed:", e)
        print("If STM32 is not connected yet, you can ignore this message.")
        return

    while True:
        try:
            # 優先處理 LINE 指令，例如 UNLOCK / LOCK / STATUS
            try:
                command, response_queue = stm32_command_queue.get_nowait()

                print("Send to STM32:", command)

                ser.reset_input_buffer()
                ser.write((command + "\n").encode())
                ser.flush()

                response = ""

                start_time = time.time()
                timeout_sec = 2.0

                while time.time() - start_time < timeout_sec:
                    line = ser.readline().decode(errors="ignore").strip()

                    if line:
                        print("STM32 response:", line)
                        response = line
                        break

                if response == "":
                    response = "NO_RESPONSE"

                response_queue.put(response)

            except queue.Empty:
                # 沒有 LINE 指令時，才讀 STM32 主動事件，例如 DOORBELL
                line = ser.readline().decode(errors="ignore").strip()

                if line:
                    print("STM32:", line)

                if line == "DOORBELL":
                    print("Doorbell pressed")
                    threading.Thread(target=push_doorbell_photo, daemon=True).start()

        except Exception as e:
            stm32_connected = False
            print("STM32 worker error:", e)
            time.sleep(1)


STM32_WIFI_API = "http://127.0.0.1:5001/api/command"


def send_command_to_stm32(command, timeout_sec=6.0, wait_ack=True):
    """
    透過 stm32_wifi_server 把指令丟給 STM32（polling 架構）。
    """
    try:
        import requests as _r
        resp = _r.post(
            STM32_WIFI_API,
            json={"command": command, "timeout": timeout_sec - 1, "wait_ack": wait_ack},
            timeout=timeout_sec
        )
        data = resp.json()
        return data.get("result") or ("OK" if data.get("ok") else "NO_RESPONSE")
    except Exception as e:
        print("send_command_to_stm32 error:", e)
        return "NO_RESPONSE"


# =========================
# Flask Routes
# =========================

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)

    except InvalidSignatureError:
        print("Invalid signature. Check Channel secret.")
        abort(400)

    except Exception as e:
        print("Webhook error:", e)
        abort(500)

    return "OK", 200


@app.route("/test_doorbell", methods=["GET"])
def test_doorbell():
    """
    門鈴入口:STM32 經由 5001 /stm32/doorbell 同步呼叫這支(也可手動開網址測試)。
    會「同步」拍照 + 辨識,並把要給 STM32 的指令(UNLOCK / OK)當作純文字回傳。
    """
    command = push_doorbell_photo()
    return command, 200, {"Content-Type": "text/plain; charset=utf-8"}


# =========================
# LINE Message Handler
# =========================

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    global door_locked
    global admin_user_id

    user_text = event.message.text.strip()

    # 沒在 config 設定時，用第一次收到的 user_id（僅限本次執行）
    if admin_user_id is None:
        admin_user_id = event.source.user_id
        print("Admin user ID registered (from message):", admin_user_id)

    print("User ID:", event.source.user_id)
    print("User text:", user_text)

    # 權限檢查：非管理員回「無權限」
    if event.source.user_id != admin_user_id:
        print("Unauthorized message from:", event.source.user_id)
        if event.reply_token.startswith("00000000000000000000000000000000"):
            return
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="無權限")]
                    )
                )
        except Exception as e:
            print("LINE reply error:", e)
        return

    # -------------------------
    # 開門
    # -------------------------
    if user_text in ("開門", "開柵欄"):
        result = send_command_to_stm32("UNLOCK")

        if result == "OK_UNLOCKED":
            door_locked = False
            add_history("開柵欄成功", "LINE 指令")

            messages = [
                TextMessage(text="柵欄已開")
            ]
        else:
            add_history("開柵欄失敗", "LINE 指令", detail=result)
            print("Open barrier failed, STM32 response:", result)

            messages = [
                TextMessage(text="開柵欄失敗，請確認柵欄狀態")
            ]

    # -------------------------
    # 關門
    # -------------------------
    elif user_text in ("關門", "關柵欄"):
        result = send_command_to_stm32("LOCK")

        if result == "OK_LOCKED":
            door_locked = True
            add_history("關柵欄成功", "LINE 指令")

            messages = [
                TextMessage(text="柵欄已關")
            ]
        else:
            add_history("關柵欄失敗", "LINE 指令", detail=result)
            print("Close barrier failed, STM32 response:", result)

            messages = [
                TextMessage(text="關柵欄失敗，請確認柵欄狀態")
            ]

    # -------------------------
    # 狀態
    # -------------------------
    elif user_text == "狀態":
        result = send_command_to_stm32("STATUS")

        if result == "LOCKED":
            door_locked = True
            add_history("狀態查詢：已鎖定", "LINE 指令")

            messages = [
                TextMessage(text="目前狀態：柵欄已關")
            ]

        elif result == "UNLOCKED":
            door_locked = False
            add_history("狀態查詢：已開鎖", "LINE 指令")

            messages = [
                TextMessage(text="目前狀態：柵欄已開")
            ]

        else:
            print("Status check failed, STM32 response:", result)
            add_history("狀態查詢失敗", "LINE 指令", detail=result)

            # LINE 上顯示簡化狀態，不顯示 debug 細節
            if door_locked:
                status_text = "目前狀態：柵欄已關"
            else:
                status_text = "目前狀態：柵欄已開"

            messages = [
                TextMessage(text=status_text)
            ]

    # -------------------------
    # 歷史紀錄
    # -------------------------
    elif user_text == "歷史紀錄" or user_text == "歷史狀態":
        messages = [
            TextMessage(text=get_history_text())
        ]

    # -------------------------
    # 拍照
    # -------------------------
    elif user_text == "拍照":
        image_path = capture_photo_once()

        if image_path:
            add_history("拍照成功", "LINE 指令")
            image_url = get_image_url(os.path.basename(image_path))

            messages = [
                TextMessage(text="已拍照，照片如下："),
                ImageMessage(
                    original_content_url=image_url,
                    preview_image_url=image_url
                )
            ]
        else:
            add_history("拍照失敗", "LINE 指令")
            print("Capture photo failed")

            messages = [
                TextMessage(text="拍照失敗，請確認攝影機")
            ]

    # -------------------------
    # 車牌白名單管理
    # -------------------------
    elif user_text == "車牌清單":
        rows = plate_utils.list_plates(DB_PATH)

        if not rows:
            messages = [TextMessage(text="目前白名單沒有車牌")]
        else:
            lines = ["車牌白名單："]
            for plate, name, enabled, created_at in rows:
                status = "啟用" if enabled else "停用"
                lines.append(f"{plate}（{name or '-'}）{status}")
            messages = [TextMessage(text="\n".join(lines))]

    elif user_text.startswith("新增車牌"):
        parts = user_text.split()

        if len(parts) >= 2:
            name = " ".join(parts[2:]) if len(parts) >= 3 else None
            norm = plate_utils.add_plate(DB_PATH, parts[1], name)

            if norm:
                add_history(f"新增車牌 {norm}", "LINE 指令", detail=norm)
                suffix = f"（{name}）" if name else ""
                messages = [TextMessage(text=f"已新增車牌：{norm}{suffix}")]
            else:
                messages = [TextMessage(text="車牌格式錯誤，範例：新增車牌 ABC-1234 小明")]
        else:
            messages = [TextMessage(text="用法：新增車牌 ABC-1234 小明")]

    elif user_text.startswith("刪除車牌") or user_text.startswith("移除車牌"):
        parts = user_text.split()

        if len(parts) >= 2:
            norm = plate_utils.disable_plate(DB_PATH, parts[1])
            add_history(f"刪除車牌 {norm}", "LINE 指令", detail=norm)
            messages = [TextMessage(text=f"已移除車牌：{norm}")]
        else:
            messages = [TextMessage(text="用法：刪除車牌 ABC-1234")]

    # -------------------------
    # 其他訊息
    # -------------------------
    else:
        messages = [
            TextMessage(text=(
                "可用指令：\n"
                "開柵欄、關柵欄、拍照、歷史紀錄\n"
                "車牌清單\n"
                "新增車牌 ABC-1234 小明\n"
                "刪除車牌 ABC-1234"
            ))
        ]

    # 避免 LINE Developers Verify 的 dummy reply token 造成錯誤
    if event.reply_token.startswith("00000000000000000000000000000000"):
        return

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages
                )
            )

    except Exception as e:
        print("LINE reply error:", e)


# =========================
# Main
# =========================

if __name__ == "__main__":
    init_db()

    if admin_user_id:
        print("Admin user ID from config:", admin_user_id)
    else:
        print("ADMIN_USER_ID not set in line_config.py. Send any message to the bot first.")

    stm32_thread = threading.Thread(target=stm32_worker, daemon=True)
    stm32_thread.start()

    # 背景預載車牌辨識模型,避免第一次門鈴才下載/載入而逾時
    threading.Thread(target=plate_recognition.load_model, daemon=True).start()

    app.run(host="0.0.0.0", port=5000)
