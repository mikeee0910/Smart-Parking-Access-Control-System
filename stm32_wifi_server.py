from flask import Flask, jsonify, request

import os
import queue
import sqlite3
import sys
import threading
import time

import requests

import plate_utils


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "door_logs.db")

LINE_BRIDGE_URL = "http://127.0.0.1:5000/test_doorbell"


# 一次只允許一筆指令 in-flight，避免狀態混亂
command_lock = threading.Lock()
pending_command_queue = queue.Queue()  # STM32 long-poll 從這裡拿
inflight_result_queue = None           # 等 STM32 ack 完寫回結果

POLL_HOLD_SECONDS = 25  # long polling server 最長 hang 多久（秒）


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def normalize_uid(uid):
    if uid is None:
        return ""

    return str(uid).strip().replace(" ", "").replace(":", "").upper()


def init_db():
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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS authorized_uids (
                uid TEXT PRIMARY KEY,
                name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS stm32_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                uid TEXT,
                allowed INTEGER,
                detail TEXT
            )
        """)

        conn.commit()

    # 車牌白名單表(與 app.py 共用同一個 DB,由 plate_utils 統一管理)
    plate_utils.ensure_plate_table(DB_PATH)


def add_history(action, source="STM32 WiFi", detail=None):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO history_logs (created_at, action, source, detail)
            VALUES (?, ?, ?, ?)
            """,
            (now_text(), action, source, detail)
        )
        conn.commit()


def add_event(event_type, uid=None, allowed=None, detail=None):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO stm32_events (created_at, event_type, uid, allowed, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now_text(), event_type, uid, allowed, detail)
        )
        conn.commit()


def get_authorized_uid(uid):
    init_db()

    normalized_uid = normalize_uid(uid)

    if normalized_uid == "":
        return None

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT uid, name
            FROM authorized_uids
            WHERE uid = ? AND enabled = 1
            """,
            (normalized_uid,)
        ).fetchone()

    return row


def read_payload():
    data = request.get_json(silent=True) or {}

    if not data:
        data = request.form.to_dict()

    if not data:
        data = request.args.to_dict()

    return data


def respond(payload, status=200):
    if request.args.get("plain") == "1":
        return payload.get("command", "OK"), status, {
            "Content-Type": "text/plain; charset=utf-8"
        }

    return jsonify(payload), status


@app.route("/stm32/doorbell", methods=["GET", "POST"])
def stm32_doorbell():
    add_event("DOORBELL")
    add_history("門鈴觸發", "STM32 WiFi")

    # 同步呼叫 app.py 做「拍照 + 車牌辨識」,把要給 STM32 的指令拿回來:
    #   白名單車牌 → "UNLOCK";其他 → "OK"。
    # STM32 直接在這個門鈴請求的回應裡拿到指令去開門(作法跟 RFID 一樣,不走 poll/ack)。
    command = "OK"
    try:
        r = requests.get(LINE_BRIDGE_URL, timeout=12)
        command = (r.text or "OK").strip().upper()
        if command not in ("UNLOCK", "OK", "DENY"):
            command = "OK"
    except Exception as e:
        print("doorbell recognize call failed:", e)
        command = "OK"

    return respond({
        "ok": True,
        "event": "DOORBELL",
        "command": command
    })


@app.route("/stm32/rfid", methods=["GET", "POST"])
def stm32_rfid():
    data = read_payload()
    uid = normalize_uid(data.get("uid"))

    if uid == "":
        add_event("RFID", detail="missing uid")

        return respond({
            "ok": False,
            "error": "missing uid",
            "command": "DENY"
        }, 400)

    authorized_uid = get_authorized_uid(uid)
    allowed = authorized_uid is not None
    add_event("RFID", uid=uid, allowed=int(allowed))

    if allowed:
        name = authorized_uid["name"] or uid
        add_history(f"{name} RFID 開門成功", "STM32 WiFi", detail=uid)

        return respond({
            "ok": True,
            "uid": uid,
            "name": authorized_uid["name"],
            "authorized": True,
            "command": "UNLOCK"
        })

    add_history("RFID 驗證失敗", "STM32 WiFi", detail=uid)

    return respond({
        "ok": True,
        "uid": uid,
        "authorized": False,
        "command": "DENY"
    })


@app.route("/stm32/poll", methods=["GET", "POST"])
def stm32_poll():
    """Long polling: 沒指令時 hang 住到有指令或 timeout"""
    try:
        cmd = pending_command_queue.get(timeout=POLL_HOLD_SECONDS)
    except queue.Empty:
        return respond({"command": "NONE"})

    print("STM32 poll → 送出指令:", cmd)
    return respond({"command": cmd})


@app.route("/stm32/ack", methods=["GET", "POST"])
def stm32_ack():
    global inflight_result_queue

    data = read_payload()
    result = str(data.get("result", "")).strip().upper()

    if not result:
        return respond({"ok": False, "error": "missing result", "command": "OK"}, 400)

    print("STM32 ack:", result)

    with command_lock:
        rq = inflight_result_queue
        inflight_result_queue = None

    if rq is not None:
        rq.put(result)

    return respond({"ok": True, "command": "OK"})


@app.route("/api/command", methods=["POST"])
def api_command():
    """LINE bot (app.py) 呼叫這支，把 UNLOCK/LOCK/STATUS 丟給 STM32"""
    global inflight_result_queue

    data = read_payload()
    command = str(data.get("command", "")).strip().upper()
    timeout_sec = float(data.get("timeout", 5.0))
    wait_ack = data.get("wait_ack", True)
    if isinstance(wait_ack, str):
        wait_ack = wait_ack.strip().lower() not in ("0", "false", "no", "off")
    else:
        wait_ack = bool(wait_ack)

    if command not in ("UNLOCK", "LOCK", "STATUS"):
        return respond({"ok": False, "error": "unknown command"}, 400)

    rq = queue.Queue()

    with command_lock:
        if not wait_ack:
            pending_command_queue.put(command)
            print("API command queued without ack wait:", command)
            return respond({"ok": True, "result": "QUEUED"})

        if inflight_result_queue is not None:
            return respond({"ok": False, "error": "busy", "result": "BUSY"}, 503)
        inflight_result_queue = rq
        pending_command_queue.put(command)

    try:
        result = rq.get(timeout=timeout_sec)
    except queue.Empty:
        with command_lock:
            inflight_result_queue = None
        return respond({"ok": False, "error": "timeout", "result": "NO_RESPONSE"})

    return respond({"ok": True, "result": result})


@app.route("/stm32/event", methods=["GET", "POST"])
def stm32_event():
    data = read_payload()
    event_type = str(data.get("event", "")).strip().upper()

    if event_type == "DOORBELL":
        return stm32_doorbell()

    if event_type == "RFID":
        return stm32_rfid()

    return respond({
        "ok": False,
        "error": "unknown event",
        "command": "DENY"
    }, 400)


def add_uid(uid, name=None):
    init_db()

    normalized_uid = normalize_uid(uid)

    if normalized_uid == "":
        print("UID 不可為空")
        return 1

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO authorized_uids (uid, name, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(uid) DO UPDATE SET
                name = excluded.name,
                enabled = 1
            """,
            (normalized_uid, name, now_text())
        )
        conn.commit()

    print(f"已新增/啟用 UID: {normalized_uid}")
    return 0


def list_uids():
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT uid, name, enabled, created_at
            FROM authorized_uids
            ORDER BY created_at DESC
            """
        ).fetchall()

    if not rows:
        print("目前沒有合法 UID")
        return 0

    for uid, name, enabled, created_at in rows:
        status = "啟用" if enabled else "停用"
        display_name = name or "-"
        print(f"{uid} | {display_name} | {status} | {created_at}")

    return 0


def disable_uid(uid):
    init_db()

    normalized_uid = normalize_uid(uid)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE authorized_uids SET enabled = 0 WHERE uid = ?",
            (normalized_uid,)
        )
        conn.commit()

    print(f"已停用 UID: {normalized_uid}")
    return 0


def add_plate_cli(plate, name=None):
    norm = plate_utils.add_plate(DB_PATH, plate, name)
    if norm:
        print(f"已新增/啟用車牌：{norm}")
        return 0
    print("車牌格式錯誤(正規化後為空)")
    return 1


def list_plates_cli():
    rows = plate_utils.list_plates(DB_PATH)
    if not rows:
        print("目前沒有合法車牌")
        return 0
    for plate, name, enabled, created_at in rows:
        status = "啟用" if enabled else "停用"
        print(f"{plate} | {name or '-'} | {status} | {created_at}")
    return 0


def disable_plate_cli(plate):
    norm = plate_utils.disable_plate(DB_PATH, plate)
    print(f"已停用車牌：{norm}")
    return 0


def print_usage():
    print("用法：")
    print("  python3 stm32_wifi_server.py")
    print("  python3 stm32_wifi_server.py add-uid <UID> [名稱]")
    print("  python3 stm32_wifi_server.py list-uids")
    print("  python3 stm32_wifi_server.py disable-uid <UID>")
    print("  python3 stm32_wifi_server.py add-plate <車牌> [名稱]")
    print("  python3 stm32_wifi_server.py list-plates")
    print("  python3 stm32_wifi_server.py disable-plate <車牌>")


if __name__ == "__main__":
    init_db()

    if len(sys.argv) >= 2:
        command = sys.argv[1]

        if command == "add-uid" and len(sys.argv) >= 3:
            name = sys.argv[3] if len(sys.argv) >= 4 else None
            raise SystemExit(add_uid(sys.argv[2], name))

        if command == "list-uids":
            raise SystemExit(list_uids())

        if command == "disable-uid" and len(sys.argv) >= 3:
            raise SystemExit(disable_uid(sys.argv[2]))

        if command == "add-plate" and len(sys.argv) >= 3:
            name = sys.argv[3] if len(sys.argv) >= 4 else None
            raise SystemExit(add_plate_cli(sys.argv[2], name))

        if command == "list-plates":
            raise SystemExit(list_plates_cli())

        if command == "disable-plate" and len(sys.argv) >= 3:
            raise SystemExit(disable_plate_cli(sys.argv[2]))

        print_usage()
        raise SystemExit(1)

    app.run(host="0.0.0.0", port=5001)
