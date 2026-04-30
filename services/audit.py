import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from datetime import datetime

_STATE = {
    "get_db": None,
    "chain_seed": None,
    "integrity_key": None,
    "audit_log_path": None,
    "audit_anchor_path": None,
    "audit_anchor_latest_path": None,
    "audit_anchor_interval_seconds": 60,
}

_audit_lock = threading.Lock()
_audit_db_lock = threading.Lock()
_anchor_lock = threading.Lock()
_last_audit_anchor_at = 0.0


def configure_audit_service(
    *,
    get_db,
    chain_seed,
    integrity_key,
    audit_log_path,
    audit_anchor_path,
    audit_anchor_latest_path,
    audit_anchor_interval_seconds,
):
    _STATE.update({
        "get_db": get_db,
        "chain_seed": chain_seed,
        "integrity_key": integrity_key,
        "audit_log_path": audit_log_path,
        "audit_anchor_path": audit_anchor_path,
        "audit_anchor_latest_path": audit_anchor_latest_path,
        "audit_anchor_interval_seconds": audit_anchor_interval_seconds,
    })


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_hash(entry_json):
    return hashlib.sha256(entry_json.encode("utf-8")).hexdigest()


def _chain_hash(prev_hash, entry_hash):
    material = f"{prev_hash}:{entry_hash}".encode("utf-8")
    return hmac.new(_STATE["integrity_key"], material, "sha256").hexdigest()


def _legacy_chain_hash(prev_hash, entry_json):
    return hmac.new(_STATE["integrity_key"], (prev_hash + entry_json).encode(), "sha256").hexdigest()


def _write_audit_anchor(audit_id, chain_hash, entry_hash, reason="interval"):
    payload = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "audit_id": int(audit_id),
        "entry_hash": entry_hash,
        "chain_hash": chain_hash,
        "reason": reason,
    }
    line = canonical_json(payload)
    with _anchor_lock:
        with open(_STATE["audit_anchor_path"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
        tmp = _STATE["audit_anchor_latest_path"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        os.replace(tmp, _STATE["audit_anchor_latest_path"])


def _maybe_anchor_audit_head(audit_id, chain_hash, entry_hash, reason="interval"):
    global _last_audit_anchor_at
    now = time.time()
    if _last_audit_anchor_at and now - _last_audit_anchor_at < _STATE["audit_anchor_interval_seconds"]:
        return
    _write_audit_anchor(audit_id, chain_hash, entry_hash, reason)
    _last_audit_anchor_at = now


def reset_audit_chain_with_event(action, ip, user="-", success=True, ua="-", detail="-"):
    """Clear the audit runtime chain and write a fresh first event.

    Server reset keeps a pre-reset snapshot for recovery, but the live runtime
    audit chain should start from a new genesis-equivalent entry after reset.
    """
    global _last_audit_anchor_at
    with _audit_db_lock:
        conn = _STATE["get_db"]()
        try:
            conn.execute("DELETE FROM secure_audit")
            try:
                conn.execute("DELETE FROM sqlite_sequence WHERE name='secure_audit'")
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()

    with _audit_lock:
        log_path = _STATE.get("audit_log_path")
        if log_path:
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8"):
                pass
    with _anchor_lock:
        _last_audit_anchor_at = 0.0
        for path in (_STATE.get("audit_anchor_path"), _STATE.get("audit_anchor_latest_path")):
            if not path:
                continue
            anchor_dir = os.path.dirname(path)
            if anchor_dir:
                os.makedirs(anchor_dir, exist_ok=True)
            try:
                with open(path, "w", encoding="utf-8"):
                    pass
            except Exception:
                pass

    audit(action, ip, user=user, success=success, ua=ua, detail=detail)
    return {"ok": True, "reset": True, "event": action}


def _verify_latest_audit_anchor(rows_by_id):
    latest_path = _STATE["audit_anchor_latest_path"]
    if not os.path.exists(latest_path):
        return True, "no anchor yet"
    try:
        with open(latest_path, encoding="utf-8") as f:
            anchor = json.loads(f.read())
        audit_id = int(anchor.get("audit_id", 0))
        row = rows_by_id.get(audit_id)
        if not row:
            return False, f"latest anchor points to missing audit id={audit_id}"
        if row["chain_hash"] != anchor.get("chain_hash"):
            return False, f"latest anchor mismatch at audit id={audit_id}"
        return True, f"latest anchor OK at audit id={audit_id}"
    except Exception as exc:
        return False, f"anchor unreadable: {exc}"


def audit(action, ip, user="-", success=False, ua="-", detail="-"):
    ts = datetime.now().isoformat(timespec="milliseconds")
    entry = {
        "ts": ts,
        "action": action,
        "ip": ip,
        "user": user,
        "success": success,
        "ua": ua[:200],
        "detail": detail,
    }
    entry_json = canonical_json(entry)
    entry_hash = _entry_hash(entry_json)

    audit_id = None
    with _audit_db_lock:
        conn = _STATE["get_db"]()
        try:
            prev_row = conn.execute(
                "SELECT chain_hash FROM secure_audit ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev_row["chain_hash"] if prev_row else _STATE["chain_seed"]
            chain_hash = _chain_hash(prev_hash, entry_hash)
            try:
                cur = conn.execute(
                    "INSERT INTO secure_audit (ts, action, ip, user, success, ua, detail, prev_hash, entry_hash, chain_hash) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, action, ip, user, 1 if success else 0, ua, detail, prev_hash, entry_hash, chain_hash)
                )
            except sqlite3.OperationalError:
                cur = conn.execute(
                    "INSERT INTO secure_audit (ts, action, ip, user, success, ua, detail, chain_hash) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ts, action, ip, user, 1 if success else 0, ua, detail, chain_hash)
                )
            audit_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

    file_entry = dict(entry)
    file_entry["_entry_hash"] = entry_hash
    file_entry["_chain_hash"] = chain_hash
    with _audit_lock:
        with open(_STATE["audit_log_path"], "a", encoding="utf-8") as f:
            f.write(canonical_json(file_entry) + "\n")
    if audit_id:
        _maybe_anchor_audit_head(audit_id, chain_hash, entry_hash)


def verify_audit_integrity(start_id=None, end_id=None):
    conn = _STATE["get_db"]()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(secure_audit)").fetchall()}
        has_extended = {"prev_hash", "entry_hash"}.issubset(cols)
        col_list = "id, ts, action, ip, user, success, ua, detail, chain_hash"
        if has_extended:
            col_list = "id, ts, action, ip, user, success, ua, detail, prev_hash, entry_hash, chain_hash"
        if start_id is None:
            rows = conn.execute(
                f"SELECT {col_list} FROM secure_audit ORDER BY id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {col_list} FROM secure_audit WHERE id>=? AND id<=? ORDER BY id ASC",
                (start_id, end_id or start_id)
            ).fetchall()

        if not rows:
            return True, None, "no entries"

        prev_hash = _STATE["chain_seed"]
        for r in rows:
            base_entry = {
                "ts": r["ts"],
                "action": r["action"],
                "ip": r["ip"],
                "user": r["user"],
                "success": bool(r["success"]),
                "ua": r["ua"],
                "detail": r["detail"],
            }
            stored_entry_hash = r["entry_hash"] if has_extended else None
            stored_prev_hash = r["prev_hash"] if has_extended else None
            if stored_entry_hash:
                if stored_prev_hash != prev_hash:
                    return False, r["id"], f"prev_hash mismatch at id={r['id']} (篡改或刪除偵測)"
                entry_json = canonical_json(base_entry)
                recomputed_entry_hash = _entry_hash(entry_json)
                if recomputed_entry_hash != stored_entry_hash:
                    return False, r["id"], f"entry_hash mismatch at id={r['id']} (內容篡改偵測)"
                recomputed = _chain_hash(prev_hash, recomputed_entry_hash)
            else:
                legacy_json = json.dumps(base_entry, ensure_ascii=False)
                recomputed = _legacy_chain_hash(prev_hash, legacy_json)
            if recomputed != r["chain_hash"]:
                return False, r["id"], f"hash mismatch at id={r['id']} (篡改偵測)"
            prev_hash = r["chain_hash"]
        anchor_ok, anchor_details = _verify_latest_audit_anchor({r["id"]: r for r in rows})
        if not anchor_ok:
            return False, None, anchor_details
        return True, None, f"integrity OK ({len(rows)} entries verified); {anchor_details}"
    finally:
        conn.close()


def repair_audit_chain(reason="manual reseal"):
    """Recompute audit hash-chain metadata from the current stored entries."""
    with _audit_db_lock:
        conn = _STATE["get_db"]()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(secure_audit)").fetchall()}
            has_extended = {"prev_hash", "entry_hash"}.issubset(cols)
            col_list = "id, ts, action, ip, user, success, ua, detail, chain_hash"
            if has_extended:
                col_list = "id, ts, action, ip, user, success, ua, detail, prev_hash, entry_hash, chain_hash"
            rows = conn.execute(f"SELECT {col_list} FROM secure_audit ORDER BY id ASC").fetchall()
            if not rows:
                return {"entries_resealed": 0, "head_id": None}

            prev_hash = _STATE["chain_seed"]
            head = None
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                entry = {
                    "ts": r["ts"],
                    "action": r["action"],
                    "ip": r["ip"],
                    "user": r["user"],
                    "success": bool(r["success"]),
                    "ua": r["ua"],
                    "detail": r["detail"],
                }
                entry_hash = _entry_hash(canonical_json(entry))
                chain_hash = _chain_hash(prev_hash, entry_hash)
                if has_extended:
                    conn.execute(
                        "UPDATE secure_audit SET prev_hash=?, entry_hash=?, chain_hash=? WHERE id=?",
                        (prev_hash, entry_hash, chain_hash, r["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE secure_audit SET chain_hash=? WHERE id=?",
                        (chain_hash, r["id"]),
                    )
                prev_hash = chain_hash
                head = {"id": r["id"], "entry_hash": entry_hash, "chain_hash": chain_hash}
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    if head:
        _write_audit_anchor(head["id"], head["chain_hash"], head["entry_hash"], reason=reason)
    return {"entries_resealed": len(rows), "head_id": head["id"] if head else None}
