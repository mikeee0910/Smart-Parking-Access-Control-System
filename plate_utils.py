"""
車牌白名單資料存取 + 正規化。

這個模組「不含任何重量級相依」(只用標準庫 re / sqlite3 / time),
所以 app.py(門鈴辨識端)和 stm32_wifi_server.py(CLI 管理端)都能直接 import,
確保「車牌正規化規則」只有一份,避免新增/查詢時對不起來。

authorized_plates 表設計沿用 authorized_uids 的模式:
    plate      正規化後的車牌(全大寫、去掉 '-' 與空白),當主鍵
    name       車主名稱
    enabled    1=啟用 0=停用(停用不刪資料,保留紀錄)
    created_at 建立/更新時間
"""

import re
import sqlite3
import time


def normalize_plate(plate):
    """
    台灣車牌正規化:全大寫,只保留 A-Z0-9。

    OCR 可能讀成 'ABC-1234'、'abc 1234'、'ABC1234',正規化後都會變成 'ABC1234',
    存進資料庫和查詢時都用同一套規則,才不會比對不到。
    """
    if plate is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(plate).upper())


def ensure_plate_table(db_path):
    """建立 authorized_plates 表(若不存在)。所有存取函式都會先呼叫它。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS authorized_plates (
                plate      TEXT PRIMARY KEY,
                name       TEXT,
                enabled    INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_authorized_plate(db_path, plate):
    """
    查白名單。車牌存在且 enabled=1 時回傳 sqlite3.Row(含 plate, name),否則 None。
    """
    ensure_plate_table(db_path)

    norm = normalize_plate(plate)
    if norm == "":
        return None

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT plate, name
            FROM authorized_plates
            WHERE plate = ? AND enabled = 1
            """,
            (norm,),
        ).fetchone()

    return row


def add_plate(db_path, plate, name=None):
    """新增或重新啟用一個車牌。回傳正規化後的車牌字串;格式不合(空字串)回傳 None。"""
    ensure_plate_table(db_path)

    norm = normalize_plate(plate)
    if norm == "":
        return None

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO authorized_plates (plate, name, enabled, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(plate) DO UPDATE SET
                name = excluded.name,
                enabled = 1
            """,
            (norm, name, timestamp),
        )
        conn.commit()

    return norm


def disable_plate(db_path, plate):
    """停用一個車牌(不刪資料)。回傳正規化後的車牌字串。"""
    ensure_plate_table(db_path)

    norm = normalize_plate(plate)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE authorized_plates SET enabled = 0 WHERE plate = ?",
            (norm,),
        )
        conn.commit()

    return norm


def list_plates(db_path):
    """回傳所有車牌的 list,每筆為 (plate, name, enabled, created_at)。"""
    ensure_plate_table(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT plate, name, enabled, created_at
            FROM authorized_plates
            ORDER BY created_at DESC
            """
        ).fetchall()

    return rows
