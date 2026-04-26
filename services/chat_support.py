import json
import os
import threading
from datetime import datetime

_STATE = {
    "chat_dir": None,
    "official_chat_room_name": None,
    "encrypt_field": None,
}

_json_locks = {}


def configure_chat_support_service(*, chat_dir, official_chat_room_name, encrypt_field):
    _STATE.update({
        "chat_dir": chat_dir,
        "official_chat_room_name": official_chat_room_name,
        "encrypt_field": encrypt_field,
    })
    migrate_plaintext_chat_transcripts()


def _get_json_lock(path):
    if path not in _json_locks:
        _json_locks[path] = threading.Lock()
    return _json_locks[path]


def _seal_chat_entry(entry):
    payload = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    return {"v": 1, "ciphertext": _STATE["encrypt_field"](payload)}


def migrate_plaintext_chat_transcripts():
    chat_dir = _STATE.get("chat_dir")
    encrypt_field = _STATE.get("encrypt_field")
    if not chat_dir or not encrypt_field or not os.path.isdir(chat_dir):
        return
    for name in os.listdir(chat_dir):
        if not name.startswith("room_") or not name.endswith(".jsonl"):
            continue
        path = os.path.join(chat_dir, name)
        try:
            with _get_json_lock(path):
                with open(path, "r", encoding="utf-8") as f:
                    raw_lines = f.readlines()
                changed = False
                sealed_lines = []
                for raw in raw_lines:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        sealed_lines.append(json.dumps(_seal_chat_entry({"raw": line}), ensure_ascii=False))
                        changed = True
                        continue
                    if isinstance(obj, dict) and "ciphertext" in obj:
                        sealed_lines.append(json.dumps(obj, ensure_ascii=False))
                        continue
                    sealed_lines.append(json.dumps(_seal_chat_entry(obj), ensure_ascii=False))
                    changed = True
                if changed:
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        for sealed in sealed_lines:
                            f.write(sealed + "\n")
                    os.replace(tmp, path)
        except Exception:
            continue


def append_chat_record(room_id, message_id, sender, content, created_at):
    try:
        safe_room_id = int(room_id)
        path = os.path.join(_STATE["chat_dir"], f"room_{safe_room_id}.jsonl")
        entry = _seal_chat_entry({
            "message_id": message_id,
            "room_id": safe_room_id,
            "sender": sender,
            "content": content,
            "created_at": created_at,
        })
        with _get_json_lock(path):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def ensure_official_chat_room(conn):
    row = conn.execute(
        "SELECT id FROM chat_rooms WHERE name=? ORDER BY id ASC LIMIT 1",
        (_STATE["official_chat_room_name"],)
    ).fetchone()
    if row:
        return row["id"]

    now = datetime.now().isoformat()
    root_row = conn.execute(
        "SELECT id FROM users WHERE username='root' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    owner_user_id = root_row["id"] if root_row else 1
    cur = conn.execute(
        "INSERT INTO chat_rooms (name, owner_user_id, created_at) VALUES (?, ?, ?)",
        (_STATE["official_chat_room_name"], owner_user_id, now)
    )
    room_id = cur.lastrowid

    active_users = conn.execute(
        "SELECT id FROM users WHERE status='active'"
    ).fetchall()
    for u in active_users:
        conn.execute(
            "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
            (room_id, u["id"], now)
        )
    return room_id


def ensure_user_official_room_membership(conn, user_id):
    room_id = ensure_official_chat_room(conn)
    conn.execute(
        "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
        (room_id, user_id, datetime.now().isoformat())
    )
    return room_id
