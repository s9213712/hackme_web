import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from services.bootstrap import CURRENT_SCHEMA_VERSION
from services.release_info import APP_RELEASE_ID
from services.settings import MANAGEMENT_ONLY_RESET_SETTINGS

SNAPSHOT_ID_RE = re.compile(r"^snap_\d{8}_\d{6}_[a-f0-9]{6}$")
SHA256_REPORT_HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
SERVER_BOOT_ID = os.environ.get("SERVER_BOOT_ID") or secrets.token_hex(16)
SNAPSHOT_TYPES = {"manual", "before_superweak", "mode_checkpoint", "scheduled", "pre_restore", "pre_reset", "pre_migration", "emergency"}
RESTORE_MODES = {"full", "db_only", "files_only", "config_only", "dry_run"}
SERVER_MODES = {"production", "preprod", "dev_ready", "internal_test", "test", "superweak", "maintenance", "incident_lockdown"}
MODE_CONFIRM_PHRASES = {
    "superweak": "ENABLE_SUPERWEAK",
    "test": "SWITCH_TO_TEST",
    "internal_test": "SWITCH_TO_INTERNAL_TEST",
    "dev_ready": "SWITCH_TO_DEV_READY",
    "preprod": "SWITCH_TO_DEV_READY",
    "production": "GO_LIVE",
    "maintenance": "ENTER_MAINTENANCE",
    "incident_lockdown": "ENTER_INCIDENT_LOCKDOWN",
}
PRODUCTION_REQUIRED_REPORT_TYPES = (
    "clean_smoke",
    "adversarial",
    "redteam_l2",
    "pytest",
    "log_chain_verify",
    "integrity_guard",
    "stress",
    "permission",
    "functional",
    "pentest",
    "snapshot_restore",
    "points_chain_consistency",
    "cloud_drive_quota_permission",
)
PORTABLE_SNAPSHOT_FILES = ("metadata.json", "checksums.sha256", "db.sqlite3.backup", "uploads.tar.gz", "config.tar.gz", "manifest.json")
DEFAULT_ACCOUNT_NAMES = ("root", "admin", "test")
TEST_ACCOUNT_NAMES = ("test",)


def _json_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mode_switch_log_payload(row, prev_hash):
    get = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
    return {
        "id": get("id", ""),
        "from_mode": get("from_mode", ""),
        "to_mode": get("to_mode", ""),
        "actor_user_id": get("actor_user_id", None),
        "reason": get("reason", ""),
        "checkpoint_id": get("checkpoint_id", ""),
        "snapshot_id": get("snapshot_id", ""),
        "success": int(get("success", 0) or 0),
        "error_message": get("error_message", ""),
        "config_diff_json": get("config_diff_json", "{}") or "{}",
        "restore_result_json": get("restore_result_json", "{}") or "{}",
        "created_at": get("created_at", ""),
        "prev_hash": prev_hash or "",
        "event_uuid": get("event_uuid", ""),
        "actor_id": get("actor_id", get("actor_user_id", None)),
        "actor_role": get("actor_role", ""),
        "source_ip": get("source_ip", ""),
        "user_agent": get("user_agent", ""),
        "request_id": get("request_id", ""),
        "server_boot_id": get("server_boot_id", ""),
        "key_version": get("key_version", ""),
    }


def _mode_switch_log_hash(row, prev_hash):
    return _json_hash(_mode_switch_log_payload(row, prev_hash))


def _mode_switch_signature_payload(row):
    get = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
    return {
        "id": get("id", ""),
        "event_uuid": get("event_uuid", ""),
        "prev_hash": get("prev_hash", ""),
        "row_hash": get("row_hash", ""),
        "from_mode": get("from_mode", ""),
        "to_mode": get("to_mode", ""),
        "actor_id": get("actor_id", get("actor_user_id", None)),
        "actor_role": get("actor_role", ""),
        "source_ip": get("source_ip", ""),
        "request_id": get("request_id", ""),
        "server_boot_id": get("server_boot_id", ""),
        "created_at": get("created_at", ""),
        "key_version": get("key_version", ""),
    }


def _hmac_sha256(secret, payload):
    return hmac.new(
        secret.encode("utf-8"),
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _tester_token_signature_payload(row):
    get = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
    return {
        "id": get("id", ""),
        "token_hash": get("token_hash", ""),
        "tester_user_id": get("tester_user_id", None),
        "mode_scope_json": get("mode_scope_json", "[]") or "[]",
        "route_scope_json": get("route_scope_json", get("allowed_routes_json", "[]")) or "[]",
        "method_scope_json": get("method_scope_json", "[]") or "[]",
        "expires_at": get("expires_at", ""),
        "issued_at": get("issued_at", get("created_at", "")),
        "nonce": get("nonce", ""),
        "max_requests_per_minute": int(get("max_requests_per_minute", 0) or 0),
        "key_version": get("key_version", ""),
    }


def _backfill_mode_switch_log_hashes(conn):
    try:
        rows = conn.execute(
            """
            SELECT * FROM mode_switch_logs
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
    except Exception:
        return
    prev_hash = ""
    for row in rows:
        row_dict = dict(row)
        expected_hash = _mode_switch_log_hash(row_dict, prev_hash)
        if row_dict.get("prev_hash") != prev_hash or row_dict.get("row_hash") != expected_hash:
            conn.execute(
                "UPDATE mode_switch_logs SET prev_hash=?, row_hash=? WHERE id=?",
                (prev_hash, expected_hash, row_dict["id"]),
            )
        prev_hash = expected_hash


def verify_mode_switch_log_hash_chain(conn):
    try:
        rows = conn.execute(
            """
            SELECT * FROM mode_switch_logs
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()
    except Exception as exc:
        return {"ok": False, "msg": "mode_switch_logs unavailable", "error": str(exc), "count": 0}
    prev_hash = ""
    mismatches = []
    for index, row in enumerate(rows):
        row_dict = dict(row)
        expected_hash = _mode_switch_log_hash(row_dict, prev_hash)
        if row_dict.get("prev_hash") != prev_hash or row_dict.get("row_hash") != expected_hash:
            mismatches.append({
                "index": index,
                "id": row_dict.get("id"),
                "expected_prev_hash": prev_hash,
                "actual_prev_hash": row_dict.get("prev_hash", ""),
                "expected_row_hash": expected_hash,
                "actual_row_hash": row_dict.get("row_hash", ""),
            })
        prev_hash = row_dict.get("row_hash") or expected_hash
    return {
        "ok": not mismatches,
        "count": len(rows),
        "latest_hash": prev_hash,
        "mismatches": mismatches,
    }


def _normalize_mode_route(route):
    raw = str(route or "")
    decoded = urllib.parse.unquote(raw)
    lowered = raw.lower()
    if ";" in raw or "\\" in decoded or ".." in decoded or any(marker in lowered for marker in ("%2f", "%5c", "%2e")):
        return None, "route contains traversal, encoded slash/backslash/dot, or semicolon params"
    collapsed = re.sub(r"/+", "/", decoded.split("?", 1)[0])
    if not collapsed.startswith("/"):
        collapsed = "/" + collapsed
    return collapsed.rstrip("/") or "/", ""

BUILTIN_SECURITY_PROFILES = {
    "production": {
        "label": "production（上線）",
        "description": "正式上線設定檔：安全機制全開、停用測試帳戶，並要求預設帳戶重新設定強密碼。",
        "settings": {
            "maintenance_mode": False,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": True,
            "production_single_ip_account_lock_enabled": False,
            "production_single_account_ip_lock_enabled": False,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_account_security_enabled": True,
            "feature_advanced_security_enabled": True,
            "feature_identity_governance_enabled": True,
            "feature_member_governance_enabled": True,
            "feature_server_modes_enabled": True,
            "feature_snapshot_restore_enabled": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
            "feature_violation_center_enabled": True,
            "feature_health_center_enabled": True,
            "captcha_mode": "math",
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 5,
            "security_pending_appeals_threshold": 5,
            "security_pending_moderation_proposals_threshold": 5,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 0,
        },
    },
    "preprod": {
        "label": "preprod（準上線）",
        "description": "舊版準上線別名；新名稱為 dev_ready。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": False,
            "ip_blocking_enabled": False,
            "login_violation_enabled": False,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": False,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": False,
            "feature_trading_enabled": False,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 50,
        },
        "color": "blue",
    },
    "dev_ready": {
        "label": "dev ready（準上線 / 開發就緒）",
        "description": "平時開發與準上線驗證模式；保留基本登入、root 權限與 CSRF，但暫停 production audit chain 與 integrity guard。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": False,
            "ip_blocking_enabled": False,
            "login_violation_enabled": False,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": False,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": False,
            "feature_trading_enabled": False,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 50,
        },
        "color": "blue",
    },
    "internal_test": {
        "label": "internal test（內測）",
        "description": "內測模式：只有 root 可直接登入；其他帳號必須提供 root 發出的內測登入 token。",
        "settings": {
            "maintenance_mode": False,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_account_security_enabled": True,
            "feature_server_modes_enabled": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 25,
        },
        "color": "orange",
    },
    "test": {
        "label": "test（測試）",
        "description": "一般測試設定檔，保留主要安全紀錄但降低啟動阻擋。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
            "feature_trading_enabled": False,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 20,
            "security_pending_appeals_threshold": 20,
            "security_pending_moderation_proposals_threshold": 20,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 100,
        },
        "color": "orange",
    },
    "superweak": {
        "label": "superweak（弱化測試）",
        "description": "高風險弱化測試模式，進入前會建立 before_superweak snapshot，並關閉主要安全機制。",
        "settings": {
            "maintenance_mode": False,
            "server_ssl_enabled": False,
            "audit_chain_enabled": False,
            "ip_blocking_enabled": False,
            "login_violation_enabled": False,
            "rate_limit_violation_enabled": False,
            "root_ip_whitelist_enabled": False,
            "root_ip_whitelist": "",
            "browser_only_mode_enabled": False,
            "integrity_guard_enabled": False,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": False,
            "feature_economy_enabled": False,
            "feature_trading_enabled": False,
            "captcha_mode": "none",
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 50,
            "security_pending_appeals_threshold": 50,
            "security_pending_moderation_proposals_threshold": 50,
            "security_quarantined_files_threshold": 10,
            "security_unknown_encrypted_files_threshold": 250,
        },
        "color": "red",
    },
    "maintenance": {
        "label": "maintenance（維護）",
        "description": "更新、修復、migration、備份與 PointsChain 維護用模式；普通使用者不可正常操作。",
        "settings": {
            "maintenance_mode": True,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": False,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
            "feature_trading_enabled": False,
            "feature_comfyui_enabled": False,
            "feature_games_enabled": False,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 10,
            "security_pending_appeals_threshold": 10,
            "security_pending_moderation_proposals_threshold": 10,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 25,
        },
        "color": "purple",
    },
    "incident_lockdown": {
        "label": "incident lockdown（事故封鎖）",
        "description": "疑似入侵、restore 失敗、PointsChain 或 integrity 異常時的強制封鎖模式。",
        "settings": {
            "maintenance_mode": True,
            "allow_register": False,
            "server_ssl_enabled": True,
            "audit_chain_enabled": True,
            "ip_blocking_enabled": True,
            "login_violation_enabled": True,
            "rate_limit_violation_enabled": True,
            "integrity_guard_enabled": True,
            "integrity_guard_strict_mode": True,
            "feature_audit_log_enabled": True,
            "feature_economy_enabled": True,
            "feature_trading_enabled": False,
            "feature_comfyui_enabled": False,
            "feature_games_enabled": False,
        },
        "thresholds": {
            "security_pending_chat_reports_threshold": 1,
            "security_pending_appeals_threshold": 1,
            "security_pending_moderation_proposals_threshold": 1,
            "security_quarantined_files_threshold": 0,
            "security_unknown_encrypted_files_threshold": 0,
        },
        "color": "black_red",
    },
}
PROFILE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
RESETTABLE_TABLES = {
    "appeals",
    "chat_message_reports",
    "chat_messages",
    "comments",
    "direct_messages",
    "dm_threads",
    "encrypted_file_keys",
    "file_access_logs",
    "file_scan_results",
    "cloud_file_refs",
    "file_access_grants",
    "forum_boards",
    "forum_categories",
    "forum_post_reactions",
    "forum_thread_reactions",
    "forum_posts",
    "forum_threads",
    "announcements",
    "announcement_attachment_requests",
    "album_files",
    "albums",
    "messages",
    "moderation_proposals",
    "moderation_votes",
    "notifications",
    "posts",
    "reports",
    "storage_folders",
    "storage_files",
    "storage_quota_log",
    "storage_share_links",
    "trading_audit_events",
    "trading_bot_runs",
    "trading_bots",
    "trading_fills",
    "trading_futures_positions",
    "trading_margin_positions",
    "trading_markets",
    "trading_orders",
    "trading_pending_profit",
    "trading_reserve_pool",
    "trading_reserve_pool_events",
    "trading_state",
    "trading_spot_realized_pnl",
    "trading_spot_positions",
    "uploaded_files",
    "user_storage",
    "video_comments",
    "video_likes",
    "video_tips",
    "video_views",
    "videos",
    "user_mod_notes",
    "violations",
}


@dataclass
class SnapshotResult:
    ok: bool
    snapshot_id: str = ""
    status: str = ""
    error: str = ""
    metadata: dict | None = None


def ensure_snapshot_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id                  TEXT PRIMARY KEY,
            type                TEXT NOT NULL,
            status              TEXT NOT NULL,
            created_by          INTEGER NOT NULL,
            created_at          TEXT NOT NULL,
            completed_at        TEXT,
            app_version         TEXT,
            schema_version      TEXT,
            source_mode         TEXT,
            includes_json       TEXT NOT NULL,
            storage_path        TEXT NOT NULL,
            db_dump_path        TEXT,
            files_archive_path  TEXT,
            config_archive_path TEXT,
            checksum            TEXT,
            size_bytes          INTEGER,
            notes               TEXT,
            error_message       TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS snapshot_restore_events (
            id                      TEXT PRIMARY KEY,
            snapshot_id             TEXT NOT NULL,
            restored_by             INTEGER NOT NULL,
            started_at              TEXT NOT NULL,
            completed_at            TEXT,
            status                  TEXT NOT NULL,
            restore_mode            TEXT NOT NULL,
            pre_restore_snapshot_id TEXT,
            checksum_verified       INTEGER NOT NULL DEFAULT 0,
            dry_run                 INTEGER NOT NULL DEFAULT 0,
            error_message           TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_modes (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            current_mode       TEXT NOT NULL,
            previous_mode      TEXT,
            active_snapshot_id TEXT,
            checkpoint_id      TEXT,
            mode_changed_by    INTEGER,
            mode_changed_at    TEXT,
            notes              TEXT,
            reason             TEXT,
            config_json        TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    server_mode_cols = {row["name"] for row in conn.execute("PRAGMA table_info(server_modes)").fetchall()}
    for col, ddl in (
        ("previous_mode", "ALTER TABLE server_modes ADD COLUMN previous_mode TEXT"),
        ("active_snapshot_id", "ALTER TABLE server_modes ADD COLUMN active_snapshot_id TEXT"),
        ("checkpoint_id", "ALTER TABLE server_modes ADD COLUMN checkpoint_id TEXT"),
        ("mode_changed_by", "ALTER TABLE server_modes ADD COLUMN mode_changed_by INTEGER"),
        ("mode_changed_at", "ALTER TABLE server_modes ADD COLUMN mode_changed_at TEXT"),
        ("notes", "ALTER TABLE server_modes ADD COLUMN notes TEXT"),
        ("reason", "ALTER TABLE server_modes ADD COLUMN reason TEXT"),
        ("config_json", "ALTER TABLE server_modes ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'"),
    ):
        if col not in server_mode_cols:
            conn.execute(ddl)
    conn.execute(
        "INSERT OR IGNORE INTO server_modes "
        "(id, current_mode, previous_mode, active_snapshot_id, checkpoint_id, mode_changed_by, mode_changed_at, notes, reason, config_json) "
        "VALUES (1, 'test', NULL, NULL, NULL, NULL, ?, '', '', '{}')",
        (datetime.now().isoformat(),),
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_checkpoints (
            id                         TEXT PRIMARY KEY,
            snapshot_id                TEXT NOT NULL,
            checkpoint_type            TEXT NOT NULL,
            from_mode                  TEXT,
            target_mode                TEXT NOT NULL,
            created_by                 INTEGER NOT NULL,
            created_at                 TEXT NOT NULL,
            status                     TEXT NOT NULL,
            db_snapshot_hash           TEXT,
            config_hash                TEXT,
            security_settings_hash     TEXT,
            points_chain_hash          TEXT,
            cloud_drive_metadata_hash  TEXT,
            integrity_manifest_hash    TEXT,
            components_json            TEXT NOT NULL DEFAULT '{}',
            error_message              TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mode_switch_logs (
            id                 TEXT PRIMARY KEY,
            event_uuid         TEXT,
            from_mode          TEXT,
            to_mode            TEXT NOT NULL,
            actor_user_id      INTEGER,
            actor_id           INTEGER,
            actor_role         TEXT,
            source_ip          TEXT,
            user_agent         TEXT,
            request_id         TEXT,
            reason             TEXT,
            checkpoint_id      TEXT,
            snapshot_id        TEXT,
            success            INTEGER NOT NULL DEFAULT 0,
            error_message      TEXT,
            config_diff_json   TEXT NOT NULL DEFAULT '{}',
            restore_result_json TEXT NOT NULL DEFAULT '{}',
            created_at         TEXT NOT NULL,
            prev_hash          TEXT NOT NULL DEFAULT '',
            row_hash           TEXT NOT NULL DEFAULT '',
            server_boot_id     TEXT,
            hmac_signature     TEXT,
            key_version        TEXT
        )
        """
    )
    mode_log_cols = {row["name"] for row in conn.execute("PRAGMA table_info(mode_switch_logs)").fetchall()}
    for col, ddl in (
        ("event_uuid", "ALTER TABLE mode_switch_logs ADD COLUMN event_uuid TEXT"),
        ("actor_id", "ALTER TABLE mode_switch_logs ADD COLUMN actor_id INTEGER"),
        ("actor_role", "ALTER TABLE mode_switch_logs ADD COLUMN actor_role TEXT"),
        ("source_ip", "ALTER TABLE mode_switch_logs ADD COLUMN source_ip TEXT"),
        ("user_agent", "ALTER TABLE mode_switch_logs ADD COLUMN user_agent TEXT"),
        ("request_id", "ALTER TABLE mode_switch_logs ADD COLUMN request_id TEXT"),
        ("prev_hash", "ALTER TABLE mode_switch_logs ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''"),
        ("row_hash", "ALTER TABLE mode_switch_logs ADD COLUMN row_hash TEXT NOT NULL DEFAULT ''"),
        ("server_boot_id", "ALTER TABLE mode_switch_logs ADD COLUMN server_boot_id TEXT"),
        ("hmac_signature", "ALTER TABLE mode_switch_logs ADD COLUMN hmac_signature TEXT"),
        ("key_version", "ALTER TABLE mode_switch_logs ADD COLUMN key_version TEXT"),
    ):
        if col not in mode_log_cols:
            conn.execute(ddl)
    conn.execute("UPDATE mode_switch_logs SET event_uuid=id WHERE event_uuid IS NULL OR event_uuid=''")
    conn.execute("UPDATE mode_switch_logs SET actor_id=actor_user_id WHERE actor_id IS NULL")
    conn.execute("UPDATE mode_switch_logs SET actor_role='' WHERE actor_role IS NULL")
    conn.execute("UPDATE mode_switch_logs SET source_ip='' WHERE source_ip IS NULL")
    conn.execute("UPDATE mode_switch_logs SET user_agent='' WHERE user_agent IS NULL")
    conn.execute("UPDATE mode_switch_logs SET request_id='' WHERE request_id IS NULL")
    conn.execute("UPDATE mode_switch_logs SET server_boot_id='' WHERE server_boot_id IS NULL")
    conn.execute("UPDATE mode_switch_logs SET key_version='' WHERE key_version IS NULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purpose TEXT NOT NULL,
            key_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            rotated_at TEXT,
            disabled_at TEXT,
            status TEXT NOT NULL,
            UNIQUE(purpose, key_version)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tester_token_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id TEXT,
            route TEXT,
            normalized_route TEXT,
            method TEXT,
            allowed INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            source_ip TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS superweak_dirty_writes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sandbox_epoch TEXT NOT NULL,
            table_name TEXT,
            operation TEXT,
            row_ref TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("DROP TRIGGER IF EXISTS trg_mode_switch_logs_no_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_mode_switch_logs_no_delete")
    _backfill_mode_switch_log_hashes(conn)
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_mode_switch_logs_no_update
        BEFORE UPDATE ON mode_switch_logs
        BEGIN
            SELECT RAISE(ABORT, 'mode_switch_logs append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_mode_switch_logs_no_delete
        BEFORE DELETE ON mode_switch_logs
        BEGIN
            SELECT RAISE(ABORT, 'mode_switch_logs append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tester_tokens (
            id                       TEXT PRIMARY KEY,
            token_hash               TEXT NOT NULL,
            tester_user_id           INTEGER,
            mode_scope_json          TEXT NOT NULL DEFAULT '["test","internal_test"]',
            route_scope_json         TEXT NOT NULL DEFAULT '[]',
            method_scope_json        TEXT NOT NULL DEFAULT '["GET","POST","PUT","PATCH","DELETE"]',
            allowed_features_json    TEXT NOT NULL DEFAULT '[]',
            allowed_routes_json      TEXT NOT NULL DEFAULT '[]',
            expires_at               TEXT NOT NULL,
            issued_at                TEXT,
            nonce                    TEXT,
            max_requests_per_minute  INTEGER NOT NULL DEFAULT 60,
            can_modify_own_role      INTEGER NOT NULL DEFAULT 0,
            can_modify_own_points    INTEGER NOT NULL DEFAULT 0,
            can_run_security_tests   INTEGER NOT NULL DEFAULT 0,
            created_by               INTEGER NOT NULL,
            created_at               TEXT NOT NULL,
            revoked_at               TEXT,
            hmac_signature           TEXT,
            key_version              TEXT
        )
        """
    )
    tester_token_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tester_tokens)").fetchall()}
    for col, ddl in (
        ("mode_scope_json", "ALTER TABLE tester_tokens ADD COLUMN mode_scope_json TEXT NOT NULL DEFAULT '[\"test\",\"internal_test\"]'"),
        ("route_scope_json", "ALTER TABLE tester_tokens ADD COLUMN route_scope_json TEXT NOT NULL DEFAULT '[]'"),
        ("method_scope_json", "ALTER TABLE tester_tokens ADD COLUMN method_scope_json TEXT NOT NULL DEFAULT '[\"GET\",\"POST\",\"PUT\",\"PATCH\",\"DELETE\"]'"),
        ("issued_at", "ALTER TABLE tester_tokens ADD COLUMN issued_at TEXT"),
        ("nonce", "ALTER TABLE tester_tokens ADD COLUMN nonce TEXT"),
        ("hmac_signature", "ALTER TABLE tester_tokens ADD COLUMN hmac_signature TEXT"),
        ("key_version", "ALTER TABLE tester_tokens ADD COLUMN key_version TEXT"),
    ):
        if col not in tester_token_cols:
            conn.execute(ddl)
    conn.execute("UPDATE tester_tokens SET route_scope_json=allowed_routes_json WHERE route_scope_json IS NULL OR route_scope_json='' OR route_scope_json='[]'")
    conn.execute("UPDATE tester_tokens SET issued_at=created_at WHERE issued_at IS NULL OR issued_at=''")
    conn.execute("UPDATE tester_tokens SET nonce=id WHERE nonce IS NULL OR nonce=''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tester_token_request_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id     TEXT NOT NULL,
            route        TEXT NOT NULL,
            ip_address   TEXT,
            created_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_shadow_roles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tester_user_id  INTEGER NOT NULL,
            original_role   TEXT,
            shadow_role     TEXT NOT NULL,
            token_id        TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_shadow_wallets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tester_user_id  INTEGER NOT NULL,
            balance_points  INTEGER NOT NULL DEFAULT 0,
            token_id        TEXT,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_shadow_transactions (
            id              TEXT PRIMARY KEY,
            tester_user_id  INTEGER NOT NULL,
            delta_points    INTEGER NOT NULL,
            reason          TEXT,
            token_id        TEXT,
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_chain_blocks (
            id              TEXT PRIMARY KEY,
            prev_hash       TEXT,
            block_hash      TEXT NOT NULL,
            transactions_json TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS production_entry_reports (
            id                      TEXT PRIMARY KEY,
            report_type             TEXT NOT NULL,
            report_hash             TEXT NOT NULL,
            target_commit           TEXT,
            target_branch           TEXT,
            server_mode             TEXT,
            test_result             TEXT,
            pass                    INTEGER NOT NULL DEFAULT 0,
            critical_findings_count INTEGER NOT NULL DEFAULT 0,
            high_findings_count     INTEGER NOT NULL DEFAULT 0,
            unresolved_findings_json TEXT NOT NULL DEFAULT '[]',
            tester                  TEXT,
            signature               TEXT,
            created_at              TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_reports (
            id                  TEXT PRIMARY KEY,
            status              TEXT NOT NULL,
            trigger_type        TEXT NOT NULL,
            reason              TEXT,
            entered_by          INTEGER,
            entered_at          TEXT NOT NULL,
            resolved_by         INTEGER,
            resolved_at         TEXT,
            resolution_notes    TEXT,
            verification_json   TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_profiles (
            name            TEXT PRIMARY KEY,
            label           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            settings_json   TEXT NOT NULL DEFAULT '{}',
            thresholds_json TEXT NOT NULL DEFAULT '{}',
            is_builtin      INTEGER NOT NULL DEFAULT 0,
            created_by      INTEGER,
            updated_by      INTEGER,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    now = datetime.now().isoformat()
    for name, profile in BUILTIN_SECURITY_PROFILES.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO security_profiles
            (name, label, description, settings_json, thresholds_json, is_builtin, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, NULL, NULL, ?, ?)
            """,
            (
                name,
                profile["label"],
                profile["description"],
                json.dumps(profile["settings"], ensure_ascii=False, sort_keys=True),
                json.dumps(profile["thresholds"], ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE security_profiles
            SET label=?,
                description=?,
                settings_json=?,
                thresholds_json=?,
                is_builtin=1,
                updated_at=?
            WHERE name=? AND is_builtin=1
            """,
            (
                profile["label"],
                profile["description"],
                json.dumps(profile["settings"], ensure_ascii=False, sort_keys=True),
                json.dumps(profile["thresholds"], ensure_ascii=False, sort_keys=True),
                now,
                name,
            ),
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_type_status ON snapshots(type, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_restore_events_snapshot ON snapshot_restore_events(snapshot_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mode_switch_logs_created ON mode_switch_logs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mode_switch_logs_hash ON mode_switch_logs(row_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tester_token_audit_token_time ON tester_token_audit(token_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_security_keys_purpose_status ON security_keys(purpose, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_server_checkpoints_target ON server_checkpoints(target_mode, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_production_reports_type ON production_entry_reports(report_type, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tester_token_request_log_token_time ON tester_token_request_log(token_id, created_at)")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_snapshot_id(snapshot_id):
    return isinstance(snapshot_id, str) and SNAPSHOT_ID_RE.fullmatch(snapshot_id) is not None


def _safe_relative_tarinfo(tarinfo):
    name = tarinfo.name
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return False
    if tarinfo.issym() or tarinfo.islnk() or tarinfo.isdev():
        return False
    return True


def _safe_extract_tar(archive_path, target_dir):
    target = Path(target_dir).resolve()
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not _safe_relative_tarinfo(member):
                raise ValueError(f"unsafe archive member: {member.name}")
            final = (target / member.name).resolve()
            if target not in final.parents and final != target:
                raise ValueError(f"archive member escapes target: {member.name}")
        tar.extractall(target)


def _parse_daily_snapshot_time(value):
    text = str(value or "03:00").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return 3, 0, "03:00"
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return 3, 0, "03:00"
    return hour, minute, f"{hour:02d}:{minute:02d}"


class SnapshotService:
    def __init__(
        self,
        *,
        get_db,
        db_path,
        base_dir,
        storage_root,
        audit,
        file_roots=None,
        config_files=None,
        runtime_secret_files=None,
        reset_points_chain=None,
        reset_audit_chain=None,
        post_restore_validators=None,
    ):
        self.get_db = get_db
        self.db_path = Path(db_path)
        self.base_dir = Path(base_dir)
        self.storage_root = Path(storage_root)
        self.snapshots_root = self.storage_root / "snapshots"
        self.imports_root = self.snapshots_root / ".imports"
        self.audit = audit
        self.reset_points_chain = reset_points_chain
        self.reset_audit_chain = reset_audit_chain
        self.post_restore_validators = list(post_restore_validators or [])
        self.file_roots = [Path(p) for p in (file_roots or []) if p]
        self.config_files = [Path(p) for p in (config_files or []) if p]
        self.runtime_secret_files = [Path(p) for p in (runtime_secret_files or []) if p]

    def set_post_restore_validators(self, validators):
        self.post_restore_validators = list(validators or [])

    def _run_post_restore_validators(self):
        results = []
        errors = []
        for name, validator in self.post_restore_validators:
            try:
                result = validator()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if not isinstance(result, dict):
                result = {"ok": bool(result), "result": result}
            item = {"name": name, **result}
            results.append(item)
            if item.get("ok") is not True:
                errors.append(item)
        return {"ok": not errors, "results": results, "errors": errors}

    def ensure_schema(self, conn):
        ensure_snapshot_schema(conn)

    def _snapshot_id(self):
        return f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"

    def _snapshot_dir(self, snapshot_id):
        if not _safe_snapshot_id(snapshot_id):
            raise ValueError("snapshot_id 格式錯誤")
        root = self.snapshots_root.resolve()
        path = (root / snapshot_id).resolve()
        if root not in path.parents:
            raise ValueError("snapshot path traversal blocked")
        return path

    def _portable_archive_path(self, snapshot_id):
        return self._snapshot_dir(snapshot_id) / f"{snapshot_id}.snapshot.tar.gz"

    def _local_snapshot_record(self, snapshot_id, *, actor_id=0, notes=None):
        snapshot_dir = self._snapshot_dir(snapshot_id)
        metadata_path = snapshot_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        size_bytes = sum(p.stat().st_size for p in snapshot_dir.rglob("*") if p.is_file())
        snapshot_type = metadata.get("type") if metadata.get("type") in SNAPSHOT_TYPES else "manual"
        includes = metadata.get("includes") if isinstance(metadata.get("includes"), dict) else {"database": True, "uploads": True, "config": True}
        now = datetime.now().isoformat()
        return {
            "id": snapshot_id,
            "type": snapshot_type,
            "status": "ready",
            "created_by": int(actor_id or 0),
            "created_at": metadata.get("created_at") or now,
            "completed_at": now,
            "app_version": metadata.get("app_version") or "",
            "schema_version": str(metadata.get("schema_version") or ""),
            "source_mode": metadata.get("source_mode") or "imported",
            "includes_json": json.dumps(includes, ensure_ascii=False, sort_keys=True),
            "storage_path": str(snapshot_dir),
            "db_dump_path": str(snapshot_dir / "db.sqlite3.backup"),
            "files_archive_path": str(snapshot_dir / "uploads.tar.gz"),
            "config_archive_path": str(snapshot_dir / "config.tar.gz"),
            "checksum": metadata.get("checksum") or "",
            "size_bytes": size_bytes,
            "notes": notes if notes is not None else metadata.get("notes", ""),
        }

    def _upsert_local_snapshot_record(self, conn, snapshot_id, *, actor_id=0, notes=None):
        self.ensure_schema(conn)
        record = self._local_snapshot_record(snapshot_id, actor_id=actor_id, notes=notes)
        current = conn.execute("SELECT id FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if current:
            conn.execute(
                "UPDATE snapshots SET status=?, storage_path=?, db_dump_path=?, files_archive_path=?, "
                "config_archive_path=?, checksum=?, size_bytes=?, completed_at=? WHERE id=?",
                (
                    record["status"],
                    record["storage_path"],
                    record["db_dump_path"],
                    record["files_archive_path"],
                    record["config_archive_path"],
                    record["checksum"],
                    record["size_bytes"],
                    record["completed_at"],
                    snapshot_id,
                ),
            )
            return record
        conn.execute(
            "INSERT INTO snapshots "
            "(id, type, status, created_by, created_at, completed_at, app_version, schema_version, source_mode, "
            "includes_json, storage_path, db_dump_path, files_archive_path, config_archive_path, checksum, size_bytes, notes) "
            "VALUES (:id, :type, :status, :created_by, :created_at, :completed_at, :app_version, :schema_version, "
            ":source_mode, :includes_json, :storage_path, :db_dump_path, :files_archive_path, :config_archive_path, "
            ":checksum, :size_bytes, :notes)",
            record,
        )
        return record

    def _current_mode(self, conn):
        self.ensure_schema(conn)
        row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        return row["current_mode"] if row else "test"

    def _actor_id(self, actor):
        return int(dict(actor or {}).get("id") or 0)

    def _actor_name(self, actor):
        return dict(actor or {}).get("username") or "system"

    def _write_db_backup(self, dest):
        src = sqlite3.connect(str(self.db_path))
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _iter_files(self):
        snapshot_root = self.snapshots_root.resolve()
        for root in self.file_roots:
            if not root.exists() or not root.is_dir():
                continue
            root_resolved = root.resolve()
            if snapshot_root == root_resolved or snapshot_root in root_resolved.parents:
                continue
            for path in root_resolved.rglob("*"):
                if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                    rel = path.relative_to(self.base_dir.resolve()) if self.base_dir.resolve() in path.resolve().parents else Path(root.name) / path.relative_to(root_resolved)
                    yield path, rel

    def _write_files_archive(self, archive_path):
        manifest = {"files": []}
        with tarfile.open(archive_path, "w:gz") as tar:
            for path, rel in self._iter_files():
                rel_text = str(rel)
                tar.add(path, arcname=rel_text)
                manifest["files"].append({"path": rel_text, "size": path.stat().st_size, "sha256": _sha256_file(path)})
        return manifest

    def _write_config_archive(self, archive_path):
        with tarfile.open(archive_path, "w:gz") as tar:
            for cfg in self.config_files:
                if not cfg.exists() or not cfg.is_file():
                    continue
                if cfg.name == ".env":
                    redacted = cfg.parent / ".env.snapshot.redacted"
                    with open(cfg, "r", encoding="utf-8", errors="ignore") as src, open(redacted, "w", encoding="utf-8") as out:
                        for line in src:
                            key = line.split("=", 1)[0].strip()
                            if key and not key.startswith("#"):
                                out.write(f"{key}=<redacted>\n")
                    tar.add(redacted, arcname=".env.snapshot.redacted")
                    try:
                        redacted.unlink()
                    except Exception:
                        pass
                    continue
                arcname = str(cfg.relative_to(self.base_dir)) if self.base_dir in cfg.resolve().parents else cfg.name
                tar.add(cfg, arcname=arcname)

    def create_snapshot(self, *, snapshot_type, actor, notes=None):
        if snapshot_type not in SNAPSHOT_TYPES:
            return SnapshotResult(False, error="snapshot type 錯誤")
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        snapshot_id = self._snapshot_id()
        snapshot_dir = self._snapshot_dir(snapshot_id)
        created_at = datetime.now().isoformat()
        includes = {"database": True, "uploads": True, "config": True, "audit_checkpoint": True}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            source_mode = self._current_mode(conn)
            snapshot_dir.mkdir(parents=True, exist_ok=False)
            conn.execute(
                "INSERT INTO snapshots "
                "(id, type, status, created_by, created_at, app_version, schema_version, source_mode, includes_json, storage_path, notes) "
                "VALUES (?, ?, 'creating', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    snapshot_type,
                    actor_id,
                    created_at,
                    APP_RELEASE_ID,
                    str(CURRENT_SCHEMA_VERSION),
                    source_mode,
                    json.dumps(includes, sort_keys=True),
                    str(snapshot_dir),
                    notes or "",
                ),
            )
            conn.commit()
            self.audit("SNAPSHOT_CREATE_STARTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},type={snapshot_type}")

            db_dump = snapshot_dir / "db.sqlite3.backup"
            files_archive = snapshot_dir / "uploads.tar.gz"
            config_archive = snapshot_dir / "config.tar.gz"
            manifest_path = snapshot_dir / "manifest.json"
            checksums_path = snapshot_dir / "checksums.sha256"
            metadata_path = snapshot_dir / "metadata.json"

            self._write_db_backup(db_dump)
            manifest = self._write_files_archive(files_archive)
            self._write_config_archive(config_archive)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

            checksums = {}
            for path in (db_dump, files_archive, config_archive, manifest_path):
                checksums[path.name] = _sha256_file(path)
            checksums_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items()))
            checksums_path.write_text(checksums_text, encoding="utf-8")
            overall_checksum = hashlib.sha256(checksums_text.encode("utf-8")).hexdigest()
            metadata = {
                "snapshot_id": snapshot_id,
                "type": snapshot_type,
                "created_by": actor_name,
                "created_at": created_at,
                "app_version": APP_RELEASE_ID,
                "schema_version": str(CURRENT_SCHEMA_VERSION),
                "source_mode": source_mode,
                "includes": includes,
                "secrets_excluded": True,
                "checksum_algorithm": "sha256",
                "checksum": overall_checksum,
                "notes": notes or "",
            }
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            size_bytes = sum(p.stat().st_size for p in snapshot_dir.rglob("*") if p.is_file())
            conn.execute(
                "UPDATE snapshots SET status='ready', completed_at=?, db_dump_path=?, files_archive_path=?, "
                "config_archive_path=?, checksum=?, size_bytes=? WHERE id=?",
                (datetime.now().isoformat(), str(db_dump), str(files_archive), str(config_archive), overall_checksum, size_bytes, snapshot_id),
            )
            conn.commit()
            self.audit("SNAPSHOT_CREATE_READY", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={size_bytes}")
            return SnapshotResult(True, snapshot_id=snapshot_id, status="ready", metadata=metadata)
        except Exception as exc:
            try:
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
                conn.execute("UPDATE snapshots SET status='failed', error_message=? WHERE id=?", (str(exc), snapshot_id))
                conn.commit()
            except Exception:
                pass
            self.audit("SNAPSHOT_CREATE_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},error={exc}")
            return SnapshotResult(False, snapshot_id=snapshot_id, status="failed", error=str(exc))
        finally:
            conn.close()

    def list_snapshots(self, *, actor):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT s.id, s.type, s.status, s.created_at, u.username AS created_by, s.size_bytes, s.source_mode, s.notes, s.checksum "
                "FROM snapshots s LEFT JOIN users u ON u.id=s.created_by ORDER BY s.created_at DESC LIMIT 100"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_snapshot(self, *, snapshot_id, actor=None):
        path = self._snapshot_dir(snapshot_id)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            metadata_path = path / "metadata.json"
            data["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
            return data
        finally:
            conn.close()

    def _verify_snapshot_dir(self, path):
        path = Path(path)
        metadata_path = path / "metadata.json"
        checksums_path = path / "checksums.sha256"
        required = [path / name for name in PORTABLE_SNAPSHOT_FILES]
        missing = [p.name for p in required if not p.exists()]
        if missing:
            return {"ok": False, "msg": "snapshot 檔案缺失", "missing": missing}
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        checksums = {}
        for line in checksums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, name = line.split(None, 1)
            checksums[name.strip()] = digest
        for name, digest in checksums.items():
            target = path / name
            if not target.exists() or _sha256_file(target) != digest:
                return {"ok": False, "msg": "checksum mismatch", "file": name}
        overall = hashlib.sha256(checksums_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if metadata.get("checksum") != overall:
            return {"ok": False, "msg": "metadata checksum mismatch"}
        conn = sqlite3.connect(str(path / "db.sqlite3.backup"))
        try:
            conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        for archive in (path / "uploads.tar.gz", path / "config.tar.gz"):
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    if not _safe_relative_tarinfo(member):
                        return {"ok": False, "msg": "unsafe tar member", "file": member.name}
        return {"ok": True, "msg": "snapshot verified", "metadata": metadata}

    def verify_snapshot(self, *, snapshot_id):
        return self._verify_snapshot_dir(self._snapshot_dir(snapshot_id))

    def export_snapshot_archive(self, *, snapshot_id, actor=None):
        actor_name = self._actor_name(actor)
        snapshot = self.get_snapshot(snapshot_id=snapshot_id, actor=actor)
        if not snapshot:
            return {"ok": False, "msg": "找不到 snapshot"}
        if snapshot.get("status") != "ready":
            return {"ok": False, "msg": "snapshot 尚未 ready"}
        verification = self.verify_snapshot(snapshot_id=snapshot_id)
        if not verification["ok"]:
            self.audit("SNAPSHOT_EXPORT_VERIFY_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},reason={verification}")
            return {"ok": False, "msg": verification["msg"], "verification": verification}

        snapshot_dir = self._snapshot_dir(snapshot_id)
        archive_path = self._portable_archive_path(snapshot_id)
        tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")
        with tarfile.open(tmp_path, "w:gz") as tar:
            for name in PORTABLE_SNAPSHOT_FILES:
                tar.add(snapshot_dir / name, arcname=f"{snapshot_id}/{name}")
        os.replace(tmp_path, archive_path)
        size_bytes = archive_path.stat().st_size
        self.audit("SNAPSHOT_EXPORTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={size_bytes}")
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "path": str(archive_path),
            "filename": archive_path.name,
            "size_bytes": size_bytes,
            "verification": verification,
        }

    def _copy_archive_input(self, *, archive_path=None, file_storage=None, dest=None):
        if archive_path:
            shutil.copyfile(archive_path, dest)
            return
        stream = getattr(file_storage, "stream", file_storage)
        if hasattr(stream, "seek"):
            stream.seek(0)
        with open(dest, "wb") as out:
            shutil.copyfileobj(stream, out)

    def _locate_imported_snapshot_dir(self, import_dir):
        direct = [import_dir / name for name in PORTABLE_SNAPSHOT_FILES]
        if all(path.exists() for path in direct):
            return import_dir
        children = [path for path in import_dir.iterdir() if path.is_dir()]
        matches = [path for path in children if all((path / name).exists() for name in PORTABLE_SNAPSHOT_FILES)]
        if len(matches) != 1:
            raise ValueError("snapshot 封包格式錯誤")
        return matches[0]

    def import_snapshot_archive(self, *, actor, archive_path=None, file_storage=None, notes=None):
        if not archive_path and file_storage is None:
            return {"ok": False, "msg": "缺少 snapshot 檔案"}
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        self.imports_root.mkdir(parents=True, exist_ok=True)
        import_id = f"import_{secrets.token_hex(8)}"
        import_dir = self.imports_root / import_id
        package_path = self.imports_root / f"{import_id}.tar.gz"
        try:
            import_dir.mkdir(parents=True, exist_ok=False)
            self._copy_archive_input(archive_path=archive_path, file_storage=file_storage, dest=package_path)
            if not package_path.exists() or package_path.stat().st_size <= 0:
                raise ValueError("snapshot 檔案為空")
            _safe_extract_tar(package_path, import_dir)
            imported_dir = self._locate_imported_snapshot_dir(import_dir)
            verification = self._verify_snapshot_dir(imported_dir)
            if not verification["ok"]:
                return {"ok": False, "msg": verification["msg"], "verification": verification}
            metadata = verification.get("metadata") or {}
            snapshot_id = metadata.get("snapshot_id")
            if not _safe_snapshot_id(snapshot_id):
                return {"ok": False, "msg": "snapshot metadata id 格式錯誤"}
            target_dir = self._snapshot_dir(snapshot_id)
            if target_dir.exists():
                return {"ok": False, "msg": "本機已存在相同 snapshot_id", "snapshot_id": snapshot_id}
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(imported_dir), str(target_dir))
            conn = self.get_db()
            try:
                record = self._upsert_local_snapshot_record(
                    conn,
                    snapshot_id,
                    actor_id=actor_id,
                    notes=f"imported portable snapshot; {notes or ''}".strip(),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SNAPSHOT_IMPORTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},size={record['size_bytes']}")
            return {"ok": True, "snapshot_id": snapshot_id, "snapshot": self.get_snapshot(snapshot_id=snapshot_id, actor=actor), "verification": verification}
        except Exception as exc:
            self.audit("SNAPSHOT_IMPORT_FAILED", "-", user=actor_name, success=False, detail=f"error={exc}")
            return {"ok": False, "msg": "snapshot 匯入失敗", "error": str(exc)}
        finally:
            try:
                if import_dir.exists():
                    shutil.rmtree(import_dir)
                if package_path.exists():
                    package_path.unlink()
            except Exception:
                pass

    def restore_snapshot_archive(self, *, actor, archive_path=None, file_storage=None, reason="", dry_run=False):
        imported = self.import_snapshot_archive(actor=actor, archive_path=archive_path, file_storage=file_storage, notes=reason)
        if not imported.get("ok"):
            return imported
        result = self.restore_snapshot(
            snapshot_id=imported["snapshot_id"],
            actor=actor,
            reason=reason or "restore from uploaded portable snapshot",
            dry_run=dry_run,
        )
        return {**result, "imported_snapshot_id": imported["snapshot_id"], "import": imported}

    def _restore_db(self, snapshot_dir):
        src = sqlite3.connect(str(snapshot_dir / "db.sqlite3.backup"))
        dst = sqlite3.connect(str(self.db_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _export_mode_switch_logs(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT * FROM mode_switch_logs
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def _merge_mode_switch_logs(self, rows):
        if not rows:
            return {"ok": True, "inserted": 0, "preserved": 0, "chain": {"ok": True, "count": 0}}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            inserted = 0
            for row in rows:
                exists = conn.execute("SELECT 1 FROM mode_switch_logs WHERE id=?", (row.get("id"),)).fetchone()
                if exists:
                    continue
                conn.execute(
                    """
                    INSERT INTO mode_switch_logs
                    (id, event_uuid, from_mode, to_mode, actor_user_id, actor_id, actor_role, source_ip, user_agent, request_id,
                     reason, checkpoint_id, snapshot_id, success, error_message, config_diff_json, restore_result_json,
                     created_at, prev_hash, row_hash, server_boot_id, hmac_signature, key_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("id"),
                        row.get("event_uuid") or row.get("id"),
                        row.get("from_mode"),
                        row.get("to_mode"),
                        row.get("actor_user_id"),
                        row.get("actor_id") if row.get("actor_id") is not None else row.get("actor_user_id"),
                        row.get("actor_role") or "",
                        row.get("source_ip") or "",
                        row.get("user_agent") or "",
                        row.get("request_id") or "",
                        row.get("reason") or "",
                        row.get("checkpoint_id"),
                        row.get("snapshot_id"),
                        int(row.get("success") or 0),
                        row.get("error_message") or "",
                        row.get("config_diff_json") or "{}",
                        row.get("restore_result_json") or "{}",
                        row.get("created_at") or datetime.now().isoformat(),
                        row.get("prev_hash") or "",
                        row.get("row_hash") or "",
                        row.get("server_boot_id") or "",
                        row.get("hmac_signature") or "",
                        row.get("key_version") or "",
                    ),
                )
                inserted += 1
            chain = verify_mode_switch_log_hash_chain(conn)
            conn.commit()
            return {"ok": bool(chain.get("ok")), "inserted": inserted, "preserved": len(rows), "chain": chain}
        except Exception as exc:
            conn.rollback()
            return {"ok": False, "inserted": 0, "preserved": len(rows), "error": str(exc)}
        finally:
            conn.close()

    def _clear_file_roots(self):
        for root in self.file_roots:
            if root.exists() and root.is_dir():
                for child in root.iterdir():
                    if child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            root.mkdir(parents=True, exist_ok=True)

    def _rel_to_base_text(self, path):
        try:
            return str(Path(path).resolve(strict=False).relative_to(self.base_dir.resolve(strict=False)))
        except Exception:
            return str(path)

    def _remove_runtime_secret_files(self):
        removed = []
        skipped = []
        base = self.base_dir.resolve(strict=False)
        for raw_path in self.runtime_secret_files:
            path = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
            rel_text = self._rel_to_base_text(path)
            try:
                resolved = path.resolve(strict=False)
                if resolved != base and base not in resolved.parents:
                    skipped.append({"path": str(path), "reason": "outside_base_dir"})
                    continue
                if not path.exists() and not path.is_symlink():
                    continue
                if path.is_dir():
                    skipped.append({"path": rel_text, "reason": "is_directory"})
                    continue
                path.unlink()
                removed.append(rel_text)
            except Exception as exc:
                skipped.append({"path": rel_text, "reason": str(exc)})
        return {"removed": removed, "skipped": skipped}

    def _existing_resettable_tables(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        existing = {row["name"] if isinstance(row, sqlite3.Row) else row[0] for row in rows}
        reset_tables = existing & RESETTABLE_TABLES
        priority = {
            "forum_post_reactions": 10,
            "forum_thread_reactions": 11,
            "forum_posts": 12,
            "forum_threads": 13,
            "forum_boards": 14,
            "forum_categories": 15,
            "album_files": 20,
            "albums": 21,
            "storage_share_links": 30,
            "file_access_grants": 31,
            "encrypted_file_keys": 32,
            "cloud_file_refs": 33,
            "storage_files": 34,
            "storage_folders": 35,
            "uploaded_files": 36,
            "direct_messages": 40,
            "dm_threads": 41,
            "chat_message_reports": 42,
            "chat_messages": 43,
            "trading_spot_realized_pnl": 50,
            "trading_fills": 51,
            "trading_orders": 52,
            "trading_spot_positions": 53,
            "trading_futures_positions": 54,
            "trading_margin_positions": 55,
            "trading_pending_profit": 56,
            "trading_reserve_pool_events": 57,
            "trading_audit_events": 58,
            "trading_reserve_pool": 59,
            "trading_state": 60,
            "trading_markets": 61,
        }
        return sorted(reset_tables, key=lambda name: (priority.get(name, 100), name))

    def _apply_management_only_settings(self, conn, *, actor_name, reset_at):
        applied = {}
        for key, value in MANAGEMENT_ONLY_RESET_SETTINGS.items():
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (key, str(bool(value)), reset_at, actor_name or "system_reset"),
            )
            applied[key] = bool(value)
        row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        previous_mode = row["current_mode"] if row else None
        conn.execute(
            """
            INSERT INTO server_modes
            (id, current_mode, previous_mode, active_snapshot_id, mode_changed_by, mode_changed_at, notes)
            VALUES (1, 'test', ?, NULL, NULL, ?, 'runtime reset default')
            ON CONFLICT(id) DO UPDATE SET
                previous_mode=excluded.previous_mode,
                current_mode='test',
                active_snapshot_id=NULL,
                mode_changed_by=NULL,
                mode_changed_at=excluded.mode_changed_at,
                notes=excluded.notes
            """,
            (previous_mode, reset_at),
        )
        return applied

    def daily_snapshot_status(self, *, settings, now=None):
        now = now or datetime.now()
        settings = dict(settings or {})
        enabled_raw = settings.get("snapshot_daily_auto_enabled", False)
        enabled = enabled_raw if isinstance(enabled_raw, bool) else str(enabled_raw).strip().lower() in {"1", "true", "yes", "on"}
        hour, minute, normalized_time = _parse_daily_snapshot_time(settings.get("snapshot_daily_time"))
        today = now.date().isoformat()
        last_date = str(settings.get("snapshot_daily_last_date") or "")
        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        due = enabled and last_date != today and now >= due_at
        reason = "due"
        if not enabled:
            reason = "disabled"
        elif last_date == today:
            reason = "already_created_today"
        elif now < due_at:
            reason = "before_scheduled_time"
        return {
            "enabled": enabled,
            "configured_time": normalized_time,
            "today": today,
            "last_date": last_date,
            "due": due,
            "reason": reason,
            "due_at": due_at.isoformat(),
            "checked_at": now.isoformat(),
        }

    def create_daily_snapshot_if_due(self, *, actor, settings, save_settings=None, now=None, force=False, notes=None):
        now = now or datetime.now()
        status = self.daily_snapshot_status(settings=settings, now=now)
        if not force and not status["due"]:
            return {"ok": True, "created": False, "status": status}

        result = self.create_snapshot(
            snapshot_type="scheduled",
            actor=actor,
            notes=notes or f"daily auto snapshot {status['today']}",
        )
        if not result.ok:
            return {
                "ok": False,
                "created": False,
                "msg": "daily snapshot 建立失敗",
                "error": result.error,
                "status": status,
            }
        if save_settings:
            save_settings({"snapshot_daily_last_date": status["today"]})
        return {
            "ok": True,
            "created": True,
            "snapshot_id": result.snapshot_id,
            "status": {**status, "last_date": status["today"], "due": False, "reason": "created"},
        }

    def reset_runtime_state(self, *, actor, confirm, reason):
        if confirm != "RESET_RUNTIME_STATE":
            return {"ok": False, "msg": "confirm 必須等於 RESET_RUNTIME_STATE"}

        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        pre = self.create_snapshot(snapshot_type="pre_reset", actor=actor, notes=f"Before runtime reset: {reason or ''}")
        if not pre.ok:
            return {"ok": False, "msg": "pre_reset snapshot failed", "error": pre.error}

        reset_at = datetime.now().isoformat()
        conn = self.get_db()
        cleared_tables = []
        try:
            self.ensure_schema(conn)
            for table in self._existing_resettable_tables(conn):
                conn.execute(f"DELETE FROM {table}")
                cleared_tables.append(table)
            if cleared_tables:
                try:
                    placeholders = ",".join("?" for _ in cleared_tables)
                    conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", cleared_tables)
                except Exception:
                    pass
            management_settings = self._apply_management_only_settings(conn, actor_name=actor_name, reset_at=reset_at)
            conn.commit()
        finally:
            conn.close()

        self._clear_file_roots()
        points_result = None
        if self.reset_points_chain:
            points_result = self.reset_points_chain(
                actor=actor,
                reason=reason or "",
                pre_reset_snapshot_id=pre.snapshot_id,
            )
        secret_result = self._remove_runtime_secret_files()
        audit_detail = (
            f"actor_id={actor_id},pre_reset_snapshot={pre.snapshot_id},tables={','.join(cleared_tables)},"
            f"points_chain_reset={bool(points_result and points_result.get('ok'))},"
            f"server_mode=test,"
            f"runtime_secret_files_removed={','.join(secret_result['removed'])},"
            f"runtime_secret_files_skipped={json.dumps(secret_result['skipped'], ensure_ascii=False, sort_keys=True)},"
            f"management_only_settings={','.join(k for k, v in management_settings.items() if v)},"
            f"disabled_settings={','.join(k for k, v in management_settings.items() if not v)},"
            f"reason={reason or ''},reset_at={reset_at}"
        )
        audit_result = None
        if self.reset_audit_chain:
            try:
                audit_result = self.reset_audit_chain(
                    "SYSTEM_RUNTIME_RESET",
                    "-",
                    user=actor_name,
                    success=True,
                    detail=audit_detail,
                    write_event=False,
                )
            except TypeError:
                audit_result = self.reset_audit_chain(
                    "SYSTEM_RUNTIME_RESET",
                    "-",
                    user=actor_name,
                    success=True,
                    detail=audit_detail,
                )
        else:
            self.audit("SYSTEM_RUNTIME_RESET", "-", user=actor_name, success=True, detail=audit_detail)
        return {
            "ok": True,
            "msg": "runtime state reset",
            "pre_reset_snapshot_id": pre.snapshot_id,
            "cleared_tables": cleared_tables,
            "points_chain_reset": points_result,
            "audit_chain_reset": audit_result,
            "server_mode": "test",
            "management_only_settings": management_settings,
            "runtime_secret_files_removed": secret_result["removed"],
            "runtime_secret_files_skipped": secret_result["skipped"],
            "requires_restart": True,
            "reset_at": reset_at,
        }

    def restore_snapshot(self, *, snapshot_id, actor, reason, dry_run=False):
        actor_id = self._actor_id(actor)
        actor_name = self._actor_name(actor)
        verification = self.verify_snapshot(snapshot_id=snapshot_id)
        if not verification["ok"]:
            self.audit("SNAPSHOT_VERIFY_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},reason={verification}")
            return {"ok": False, "msg": verification["msg"], "verification": verification}
        self.audit("SNAPSHOT_VERIFY_OK", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id}")
        if dry_run:
            event_id = f"restore_{secrets.token_hex(8)}"
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "INSERT INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, checksum_verified, dry_run, error_message) "
                    "VALUES (?, ?, ?, ?, ?, 'verified', 'dry_run', 1, 1, NULL)",
                    (event_id, snapshot_id, actor_id, datetime.now().isoformat(), datetime.now().isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": True, "msg": "dry-run verified", "event_id": event_id, "verification": verification}

        pre = self.create_snapshot(snapshot_type="pre_restore", actor=actor, notes=f"Before restore {snapshot_id}: {reason}")
        if not pre.ok:
            return {"ok": False, "msg": "pre_restore snapshot failed", "error": pre.error}
        preserved_mode_switch_logs = self._export_mode_switch_logs()
        event_id = f"restore_{secrets.token_hex(8)}"
        started_at = datetime.now().isoformat()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            try:
                conn.execute("UPDATE system_settings SET value='true', value_type='bool', updated_at=? WHERE key='maintenance_mode'", (started_at,))
            except Exception:
                pass
            conn.execute(
                "INSERT INTO snapshot_restore_events "
                "(id, snapshot_id, restored_by, started_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run) "
                "VALUES (?, ?, ?, ?, 'restoring', 'full', ?, 1, 0)",
                (event_id, snapshot_id, actor_id, started_at, pre.snapshot_id),
            )
            conn.commit()
        finally:
            conn.close()

        try:
            snapshot_dir = self._snapshot_dir(snapshot_id)
            self.audit("SNAPSHOT_RESTORE_STARTED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},pre_restore={pre.snapshot_id},reason={reason}")
            self._restore_db(snapshot_dir)
            self._clear_file_roots()
            _safe_extract_tar(snapshot_dir / "uploads.tar.gz", self.base_dir)
            completed_at = datetime.now().isoformat()
            mode_log_merge = self._merge_mode_switch_logs(preserved_mode_switch_logs)
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._upsert_local_snapshot_record(conn, snapshot_id, actor_id=actor_id)
                conn.execute(
                    "INSERT OR REPLACE INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run) "
                    "VALUES (?, ?, ?, ?, ?, 'completed', 'full', ?, 1, 0)",
                    (event_id, snapshot_id, actor_id, started_at, completed_at, pre.snapshot_id),
                )
                conn.commit()
            finally:
                conn.close()
            if not mode_log_merge.get("ok"):
                self.audit("MODE_SWITCH_LOG_RESTORE_PRESERVE_FAILED", "-", user=actor_name, success=False, detail=json.dumps(mode_log_merge, ensure_ascii=False, sort_keys=True))
                return {
                    "ok": False,
                    "msg": "mode switch log preservation failed after restore",
                    "event_id": event_id,
                    "pre_restore_snapshot_id": pre.snapshot_id,
                    "mode_switch_log_merge": mode_log_merge,
                }
            post_restore_validation = self._run_post_restore_validators()
            if not post_restore_validation["ok"]:
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO snapshot_restore_events "
                        "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run, error_message) "
                        "VALUES (?, ?, ?, ?, ?, 'failed', 'full', ?, 1, 0, ?)",
                        (
                            event_id,
                            snapshot_id,
                            actor_id,
                            started_at,
                            datetime.now().isoformat(),
                            pre.snapshot_id,
                            json.dumps(post_restore_validation, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self.audit("SNAPSHOT_RESTORE_VALIDATION_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},validation={post_restore_validation}")
                return {
                    "ok": False,
                    "msg": "post-restore validation failed",
                    "event_id": event_id,
                    "pre_restore_snapshot_id": pre.snapshot_id,
                    "post_restore_validation": post_restore_validation,
                }
            self.audit("SNAPSHOT_RESTORE_COMPLETED", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},pre_restore={pre.snapshot_id},reason={reason}")
            return {"ok": True, "msg": "snapshot restored", "event_id": event_id, "pre_restore_snapshot_id": pre.snapshot_id, "post_restore_validation": post_restore_validation}
        except Exception as exc:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO snapshot_restore_events "
                    "(id, snapshot_id, restored_by, started_at, completed_at, status, restore_mode, pre_restore_snapshot_id, checksum_verified, dry_run, error_message) "
                    "VALUES (?, ?, ?, ?, ?, 'failed', 'full', ?, 1, 0, ?)",
                    (event_id, snapshot_id, actor_id, started_at, datetime.now().isoformat(), pre.snapshot_id, str(exc)),
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SNAPSHOT_RESTORE_FAILED", "-", user=actor_name, success=False, detail=f"snapshot_id={snapshot_id},error={exc}")
            return {"ok": False, "msg": "restore failed", "error": str(exc), "pre_restore_snapshot_id": pre.snapshot_id}

    def delete_snapshot(self, *, snapshot_id, actor, reason):
        path = self._snapshot_dir(snapshot_id)
        actor_name = self._actor_name(actor)
        if path.exists():
            shutil.rmtree(path)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute("UPDATE snapshots SET status='deleted', error_message=? WHERE id=?", (reason or "", snapshot_id))
            conn.commit()
        finally:
            conn.close()
        self.audit("SNAPSHOT_DELETE", "-", user=actor_name, success=True, detail=f"snapshot_id={snapshot_id},reason={reason}")
        return {"ok": True, "msg": "snapshot deleted"}


class ServerModeService:
    def __init__(self, *, snapshot_service, get_db, audit, integrity_guard=None, save_settings=None):
        self.snapshot_service = snapshot_service
        self.get_db = get_db
        self.audit = audit
        self.integrity_guard = integrity_guard
        self.save_settings = save_settings
        base_dir = Path(snapshot_service.base_dir) if snapshot_service else Path.cwd()
        self.audit_export_dir = base_dir / "security" / "audit_exports" / "server_mode"

    def ensure_schema(self, conn):
        ensure_snapshot_schema(conn)

    def _decode_profile(self, row):
        if not row:
            return None
        data = dict(row)
        for key in ("settings_json", "thresholds_json"):
            try:
                data[key.replace("_json", "")] = json.loads(data.get(key) or "{}")
            except Exception:
                data[key.replace("_json", "")] = {}
            data.pop(key, None)
        data["is_builtin"] = bool(data.get("is_builtin"))
        data["color"] = BUILTIN_SECURITY_PROFILES.get(data.get("name"), {}).get("color", "")
        return data

    def _normalize_mode(self, mode):
        value = str(mode or "").strip().lower()
        if value == "preprod":
            return "dev_ready"
        return value

    def _actor_id(self, actor):
        try:
            return int(actor.get("id") if hasattr(actor, "get") else actor["id"])
        except Exception:
            return 0

    def _actor_name(self, actor):
        try:
            return str(actor.get("username") if hasattr(actor, "get") else actor["username"])
        except Exception:
            return "unknown"

    def _actor_role(self, actor):
        try:
            return str(actor.get("role") if hasattr(actor, "get") else actor["role"])
        except Exception:
            return "unknown"

    def _current_mode_for_keys(self):
        try:
            return self._normalize_mode(self.get_current_mode().get("current_mode"))
        except Exception:
            return "test"

    def _record_security_key(self, *, purpose, key_version, status):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO security_keys (purpose, key_version, created_at, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(purpose, key_version) DO UPDATE SET status=excluded.status
                """,
                (purpose, key_version, datetime.now().isoformat(), status),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    def _record_security_key_on_conn(self, conn, *, purpose, key_version, status):
        conn.execute(
            """
            INSERT INTO security_keys (purpose, key_version, created_at, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(purpose, key_version) DO UPDATE SET status=excluded.status
            """,
            (purpose, key_version, datetime.now().isoformat(), status),
        )

    def _local_hmac_key_path(self, purpose):
        filename = ".server_mode_log_hmac_key" if purpose == "server_mode_log" else f".{purpose}_hmac_key"
        base_dir = Path(self.snapshot_service.base_dir) if self.snapshot_service else Path.cwd()
        return base_dir / filename

    def _hmac_key(self, purpose="server_mode_log", current_mode=None):
        env_name = "SERVER_MODE_LOG_HMAC_KEY" if purpose == "server_mode_log" else "SERVER_MODE_TOKEN_HMAC_KEY"
        version_env = "SERVER_MODE_LOG_HMAC_KEY_VERSION" if purpose == "server_mode_log" else "SERVER_MODE_TOKEN_HMAC_KEY_VERSION"
        key = os.environ.get(env_name, "").strip()
        version = os.environ.get(version_env, "env-v1").strip() or "env-v1"
        if key:
            return key, version
        mode_for_key_policy = self._normalize_mode(current_mode) if current_mode else self._current_mode_for_keys()
        production_key_required = (
            os.environ.get("HTML_LEARNING_REQUIRE_EXTERNAL_HMAC_KEYS")
            or os.environ.get("HTML_LEARNING_ENV", "").lower() in {"prod", "production"}
        )
        if mode_for_key_policy == "production" and production_key_required and not os.environ.get("HTML_LEARNING_ALLOW_LOCAL_SERVER_MODE_KEYS"):
            raise RuntimeError(f"{env_name} is required in production")
        path = self._local_hmac_key_path(purpose)
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
        else:
            key = secrets.token_urlsafe(48)
            path.write_text(key + "\n", encoding="utf-8")
            try:
                path.chmod(0o600)
            except Exception:
                pass
        version = "local-dev-v1"
        return key, version

    def _sign_mode_log(self, row):
        key, version = self._hmac_key("server_mode_log")
        payload = {**row, "key_version": version}
        return _hmac_sha256(key, _mode_switch_signature_payload(payload)), version

    def _verify_mode_log_signature(self, row):
        signature = str(row.get("hmac_signature") or "")
        if not signature:
            return {"ok": False, "reason": "missing_signature", "key_version": row.get("key_version") or ""}
        try:
            key, _ = self._hmac_key("server_mode_log")
        except Exception as exc:
            return {"ok": False, "reason": str(exc), "key_version": row.get("key_version") or ""}
        expected = _hmac_sha256(key, _mode_switch_signature_payload(row))
        ok = hmac.compare_digest(signature, expected)
        return {"ok": ok, "reason": "" if ok else "signature_mismatch", "key_version": row.get("key_version") or ""}

    def _export_mode_log_event(self, row):
        self.audit_export_dir.mkdir(parents=True, exist_ok=True)
        event_uuid = row.get("event_uuid") or row.get("id")
        timestamp = str(row.get("created_at") or datetime.now().isoformat()).replace(":", "").replace("-", "")
        payload = {
            "event": row,
            "row_hash": row.get("row_hash"),
            "prev_hash": row.get("prev_hash"),
            "hmac_signature": row.get("hmac_signature"),
            "key_version": row.get("key_version"),
        }
        event_path = self.audit_export_dir / f"{timestamp}_{event_uuid}.json"
        event_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        day = datetime.now().strftime("%Y%m%d")
        bundle = self.audit_export_dir / f"server_mode_audit_{day}.jsonl"
        with bundle.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        (self.audit_export_dir / f"server_mode_audit_{day}.sha256").write_text(f"{digest}  {bundle.name}\n", encoding="utf-8")
        return {"event_path": str(event_path), "bundle": str(bundle), "sha256": digest}

    def _stable_hash(self, payload):
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def _table_exists(self, conn, table):
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return bool(row)

    def _settings_snapshot(self, conn):
        if not self._table_exists(conn, "system_settings"):
            return {}
        rows = conn.execute("SELECT key, value FROM system_settings ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _points_chain_checkpoint(self, conn):
        payload = {"ledger_count": 0, "block_count": 0, "latest_block_hash": "", "latest_ledger_hash": ""}
        if self._table_exists(conn, "points_ledger"):
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM points_ledger").fetchone()
                payload["ledger_count"] = int(row["c"] or 0)
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(points_ledger)").fetchall()}
                if "entry_hash" in cols:
                    latest = conn.execute("SELECT entry_hash FROM points_ledger ORDER BY id DESC LIMIT 1").fetchone()
                    payload["latest_ledger_hash"] = latest["entry_hash"] if latest else ""
            except Exception as exc:
                payload["ledger_error"] = str(exc)
        if self._table_exists(conn, "points_chain_blocks"):
            try:
                row = conn.execute("SELECT COUNT(*) AS c FROM points_chain_blocks").fetchone()
                payload["block_count"] = int(row["c"] or 0)
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(points_chain_blocks)").fetchall()}
                hash_col = "block_hash" if "block_hash" in cols else ("hash" if "hash" in cols else "")
                if hash_col:
                    latest = conn.execute(f"SELECT {hash_col} AS h FROM points_chain_blocks ORDER BY id DESC LIMIT 1").fetchone()
                    payload["latest_block_hash"] = latest["h"] if latest else ""
            except Exception as exc:
                payload["block_error"] = str(exc)
        payload["hash"] = self._stable_hash(payload)
        return payload

    def _cloud_drive_metadata_checkpoint(self, conn):
        tables = ["storage_files", "storage_folders", "storage_share_links", "cloud_file_refs", "uploaded_files", "videos"]
        payload = {}
        for table in tables:
            if not self._table_exists(conn, table):
                payload[table] = {"exists": False, "count": 0}
                continue
            try:
                count = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                payload[table] = {"exists": True, "count": int(count or 0)}
            except Exception as exc:
                payload[table] = {"exists": True, "error": str(exc)}
        payload["hash"] = self._stable_hash(payload)
        return payload

    def _integrity_manifest_hash(self):
        path = getattr(self.integrity_guard, "manifest_path", None) if self.integrity_guard else None
        if not path:
            return ""
        try:
            path_obj = Path(path)
            return _sha256_file(path_obj) if path_obj.is_file() else ""
        except Exception:
            return ""

    def _config_diff(self, current_settings, target_settings):
        diff = {}
        for key, after in (target_settings or {}).items():
            before = current_settings.get(key)
            if str(before) != str(after):
                diff[key] = {"before": before, "after": after}
        return diff

    def _record_mode_switch(
        self,
        conn,
        *,
        from_mode,
        to_mode,
        actor,
        reason="",
        checkpoint_id=None,
        snapshot_id=None,
        success=False,
        error_message="",
        config_diff=None,
        restore_result=None,
        source_ip="",
        user_agent="",
        request_id="",
    ):
        log_id = f"mode_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        event_uuid = secrets.token_hex(16)
        created_at = datetime.now().isoformat()
        prev_row = conn.execute(
            "SELECT row_hash FROM mode_switch_logs ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        prev_hash = (prev_row["row_hash"] if prev_row and prev_row["row_hash"] else "") if prev_row else ""
        row_payload = {
            "id": log_id,
            "event_uuid": event_uuid,
            "from_mode": from_mode,
            "to_mode": to_mode,
            "actor_user_id": self._actor_id(actor),
            "actor_id": self._actor_id(actor),
            "actor_role": self._actor_role(actor),
            "source_ip": source_ip or "",
            "user_agent": user_agent or "",
            "request_id": request_id or "",
            "reason": reason or "",
            "checkpoint_id": checkpoint_id,
            "snapshot_id": snapshot_id,
            "success": 1 if success else 0,
            "error_message": error_message or "",
            "config_diff_json": json.dumps(config_diff or {}, ensure_ascii=False, sort_keys=True),
            "restore_result_json": json.dumps(restore_result or {}, ensure_ascii=False, sort_keys=True),
            "created_at": created_at,
            "server_boot_id": SERVER_BOOT_ID,
        }
        hmac_key, key_version = self._hmac_key("server_mode_log", current_mode=to_mode)
        row_payload["key_version"] = key_version
        row_hash = _mode_switch_log_hash(row_payload, prev_hash)
        row_payload["prev_hash"] = prev_hash
        row_payload["row_hash"] = row_hash
        hmac_signature = _hmac_sha256(hmac_key, _mode_switch_signature_payload(row_payload))
        row_payload["hmac_signature"] = hmac_signature
        self._record_security_key_on_conn(
            conn,
            purpose="server_mode_log",
            key_version=key_version,
            status="active",
        )
        conn.execute(
            """
            INSERT INTO mode_switch_logs
            (id, event_uuid, from_mode, to_mode, actor_user_id, actor_id, actor_role, source_ip, user_agent, request_id,
             reason, checkpoint_id, snapshot_id, success, error_message, config_diff_json, restore_result_json,
             created_at, prev_hash, row_hash, server_boot_id, hmac_signature, key_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                event_uuid,
                from_mode,
                to_mode,
                row_payload["actor_user_id"],
                row_payload["actor_id"],
                row_payload["actor_role"],
                row_payload["source_ip"],
                row_payload["user_agent"],
                row_payload["request_id"],
                reason or "",
                checkpoint_id,
                snapshot_id,
                1 if success else 0,
                error_message or "",
                row_payload["config_diff_json"],
                row_payload["restore_result_json"],
                created_at,
                prev_hash,
                row_hash,
                SERVER_BOOT_ID,
                hmac_signature,
                key_version,
            ),
        )
        try:
            export = self._export_mode_log_event(row_payload)
            if not export.get("event_path"):
                raise RuntimeError("empty export path")
        except Exception as exc:
            if self._normalize_mode(to_mode) in {"production", "dev_ready"}:
                raise RuntimeError(f"mode switch audit export failed: {exc}") from exc
        return log_id

    def _enter_incident_lockdown_on_conn(self, conn, *, actor, trigger_type, reason, verification=None):
        now = datetime.now().isoformat()
        current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        current = current_row["current_mode"] if current_row else None
        incident_id = f"incident_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn.execute(
            """
            INSERT INTO incident_reports
            (id, status, trigger_type, reason, entered_by, entered_at, verification_json)
            VALUES (?, 'open', ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                str(trigger_type or "manual"),
                str(reason or ""),
                self._actor_id(actor),
                now,
                json.dumps(verification or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        profile = BUILTIN_SECURITY_PROFILES["incident_lockdown"]
        now_updated_by = f"server_mode:{self._actor_name(actor)}"
        if self._table_exists(conn, "system_settings"):
            try:
                epoch_row = conn.execute("SELECT value FROM system_settings WHERE key='server_security_epoch'").fetchone()
                next_epoch = int((epoch_row["value"] if epoch_row else 0) or 0) + 1
            except Exception:
                next_epoch = 1
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                ("server_security_epoch", str(next_epoch), now, now_updated_by),
            )
            for key, value in (profile.get("settings") or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (key, str(value), now, now_updated_by),
                )
        if self._table_exists(conn, "tester_tokens"):
            conn.execute(
                "UPDATE tester_tokens SET revoked_at=? WHERE revoked_at IS NULL",
                (now,),
            )
        conn.execute(
            """
            UPDATE server_modes
            SET previous_mode=?, current_mode='incident_lockdown', checkpoint_id=NULL, active_snapshot_id=NULL,
                mode_changed_by=?, mode_changed_at=?, notes=?, reason=?, config_json=?
            WHERE id=1
            """,
            (
                current,
                self._actor_id(actor),
                now,
                reason or "",
                reason or "",
                json.dumps(profile, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._record_mode_switch(
            conn,
            from_mode=current,
            to_mode="incident_lockdown",
            actor=actor,
            reason=reason or trigger_type or "",
            success=True,
            config_diff={"trigger_type": trigger_type, "verification": verification or {}},
        )
        return incident_id

    def create_mode_checkpoint(self, *, actor, target_mode, reason="", snapshot_type="mode_checkpoint", from_mode=None):
        target_mode = self._normalize_mode(target_mode)
        if target_mode not in SERVER_MODES and not self.get_profile(target_mode):
            return {"ok": False, "msg": "server mode 錯誤"}
        if not self.snapshot_service:
            return {"ok": False, "msg": "snapshot service unavailable"}
        snapshot = self.snapshot_service.create_snapshot(
            snapshot_type=snapshot_type,
            actor=actor,
            notes=f"server mode checkpoint before {target_mode}: {reason or ''}",
        )
        checkpoint_id = f"chk_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            current_settings = self._settings_snapshot(conn)
            security_settings = {
                key: current_settings.get(key)
                for key in sorted(current_settings)
                if key.startswith("feature_")
                or key in {
                    "audit_chain_enabled",
                    "ip_blocking_enabled",
                    "login_violation_enabled",
                    "rate_limit_violation_enabled",
                    "integrity_guard_enabled",
                    "integrity_guard_strict_mode",
                    "maintenance_mode",
                    "captcha_mode",
                }
            }
            points = self._points_chain_checkpoint(conn)
            cloud = self._cloud_drive_metadata_checkpoint(conn)
            integrity_hash = self._integrity_manifest_hash()
            db_hash = ""
            try:
                if snapshot.ok and snapshot.snapshot_id:
                    snapshot_row = conn.execute(
                        "SELECT db_dump_path FROM snapshots WHERE id=?",
                        (snapshot.snapshot_id,),
                    ).fetchone()
                    db_dump_path = Path(snapshot_row["db_dump_path"] if snapshot_row else "")
                    if db_dump_path.is_file():
                        db_hash = _sha256_file(db_dump_path)
            except Exception:
                db_hash = ""
            components = {
                "db_snapshot": {"snapshot_id": snapshot.snapshot_id, "hash": db_hash},
                "config": current_settings,
                "security_settings": security_settings,
                "points_chain": points,
                "cloud_drive_metadata": cloud,
                "integrity_manifest": {"hash": integrity_hash},
            }
            conn.execute(
                """
                INSERT INTO server_checkpoints
                (id, snapshot_id, checkpoint_type, from_mode, target_mode, created_by, created_at, status,
                 db_snapshot_hash, config_hash, security_settings_hash, points_chain_hash,
                 cloud_drive_metadata_hash, integrity_manifest_hash, components_json, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    snapshot.snapshot_id,
                    snapshot_type,
                    from_mode,
                    target_mode,
                    self._actor_id(actor),
                    datetime.now().isoformat(),
                    "ready" if snapshot.ok else "failed",
                    db_hash,
                    self._stable_hash(current_settings),
                    self._stable_hash(security_settings),
                    points.get("hash", ""),
                    cloud.get("hash", ""),
                    integrity_hash,
                    json.dumps(components, ensure_ascii=False, sort_keys=True),
                    snapshot.error if not snapshot.ok else "",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        if not snapshot.ok:
            return {"ok": False, "msg": "mode checkpoint snapshot 建立失敗", "checkpoint_id": checkpoint_id, "error": snapshot.error}
        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "snapshot_id": snapshot.snapshot_id,
            "components": components,
        }

    def _checkpoint_record(self, conn, checkpoint_id):
        row = conn.execute("SELECT * FROM server_checkpoints WHERE id=?", (checkpoint_id,)).fetchone()
        return dict(row) if row else None

    def validate_checkpoint_restore(self, *, checkpoint_id, expected_checkpoint=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            checkpoint = expected_checkpoint or self._checkpoint_record(conn, checkpoint_id)
            if not checkpoint:
                return {"ok": False, "msg": "找不到 checkpoint", "checkpoint_id": checkpoint_id}
            try:
                components = json.loads(checkpoint.get("components_json") or "{}")
            except Exception:
                components = {}
            snapshot_id = checkpoint.get("snapshot_id")
            snapshot_verification = {"ok": False, "msg": "snapshot unavailable"}
            if snapshot_id:
                try:
                    snapshot_verification = self.snapshot_service.verify_snapshot(snapshot_id=snapshot_id)
                except Exception as exc:
                    snapshot_verification = {"ok": False, "msg": str(exc)}

            current_settings = self._settings_snapshot(conn)
            security_settings = {
                key: current_settings.get(key)
                for key in sorted(current_settings)
                if key.startswith("feature_")
                or key in {
                    "audit_chain_enabled",
                    "ip_blocking_enabled",
                    "login_violation_enabled",
                    "rate_limit_violation_enabled",
                    "integrity_guard_enabled",
                    "integrity_guard_strict_mode",
                    "maintenance_mode",
                    "captcha_mode",
                }
            }
            current = {
                "config_hash": self._stable_hash(current_settings),
                "security_settings_hash": self._stable_hash(security_settings),
                "points_chain_hash": self._points_chain_checkpoint(conn).get("hash", ""),
                "cloud_drive_metadata_hash": self._cloud_drive_metadata_checkpoint(conn).get("hash", ""),
                "integrity_manifest_hash": self._integrity_manifest_hash(),
            }
            checks = {
                "snapshot_verified": bool(snapshot_verification.get("ok")),
                "config": current["config_hash"] == checkpoint.get("config_hash"),
                "security_settings": current["security_settings_hash"] == checkpoint.get("security_settings_hash"),
                "points_chain": current["points_chain_hash"] == checkpoint.get("points_chain_hash"),
                "cloud_drive_metadata": current["cloud_drive_metadata_hash"] == checkpoint.get("cloud_drive_metadata_hash"),
                "integrity_manifest": current["integrity_manifest_hash"] == (checkpoint.get("integrity_manifest_hash") or ""),
            }
            mismatches = [name for name, ok in checks.items() if not ok]
            return {
                "ok": not mismatches,
                "checkpoint_id": checkpoint_id,
                "snapshot_id": snapshot_id,
                "checks": checks,
                "mismatches": mismatches,
                "snapshot_verification": snapshot_verification,
                "expected": {
                    "config_hash": checkpoint.get("config_hash"),
                    "security_settings_hash": checkpoint.get("security_settings_hash"),
                    "points_chain_hash": checkpoint.get("points_chain_hash"),
                    "cloud_drive_metadata_hash": checkpoint.get("cloud_drive_metadata_hash"),
                    "integrity_manifest_hash": checkpoint.get("integrity_manifest_hash"),
                    "components": components,
                },
                "current": current,
            }
        finally:
            conn.close()

    def list_profiles(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM security_profiles ORDER BY is_builtin DESC, name"
            ).fetchall()
            return [self._decode_profile(row) for row in rows]
        finally:
            conn.close()

    def get_profile(self, name):
        profile_name = self._normalize_mode(name)
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM security_profiles WHERE name=?", (profile_name,)).fetchone()
            return self._decode_profile(row)
        finally:
            conn.close()

    def save_profile(self, *, name, label, description="", settings=None, thresholds=None, actor=None):
        profile_name = str(name or "").strip().lower()
        if not PROFILE_NAME_RE.fullmatch(profile_name):
            return {"ok": False, "msg": "profile name 必須是 2-32 字元的小寫英數、底線或連字號，且以英文字母開頭"}
        if profile_name in SERVER_MODES:
            return {"ok": False, "msg": "內建模式不可覆寫，請使用自定義名稱"}
        settings = settings if isinstance(settings, dict) else {}
        thresholds = thresholds if isinstance(thresholds, dict) else {}
        try:
            actor_id = int(actor["id"] if actor else 0)
        except Exception:
            actor_id = int(actor.get("id") or 0) if hasattr(actor, "get") else 0
        now = datetime.now().isoformat()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO security_profiles
                (name, label, description, settings_json, thresholds_json, is_builtin, created_by, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    label=excluded.label,
                    description=excluded.description,
                    settings_json=excluded.settings_json,
                    thresholds_json=excluded.thresholds_json,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    profile_name,
                    str(label or profile_name)[:80],
                    str(description or "")[:500],
                    json.dumps(settings, ensure_ascii=False, sort_keys=True),
                    json.dumps(thresholds, ensure_ascii=False, sort_keys=True),
                    actor_id,
                    actor_id,
                    now,
                    now,
                ),
            )
            conn.commit()
            profile = conn.execute("SELECT * FROM security_profiles WHERE name=?", (profile_name,)).fetchone()
            return {"ok": True, "profile": self._decode_profile(profile)}
        finally:
            conn.close()

    def get_current_mode(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM server_modes WHERE id=1").fetchone()
            return dict(row)
        finally:
            conn.close()

    def mode_switch_logs(self, *, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                "SELECT * FROM mode_switch_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def verify_mode_switch_logs(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            chain = verify_mode_switch_log_hash_chain(conn)
            rows = conn.execute(
                "SELECT * FROM mode_switch_logs ORDER BY created_at ASC, id ASC"
            ).fetchall()
            invalid = []
            for row in rows:
                item = dict(row)
                sig = self._verify_mode_log_signature(item)
                if not sig.get("ok"):
                    invalid.append({"id": item.get("id"), "event_uuid": item.get("event_uuid"), **sig})
            return {
                **chain,
                "chain_length": chain.get("count", 0),
                "broken_links": len(chain.get("mismatches") or []),
                "invalid_signatures": invalid,
                "first_hash": rows[0]["row_hash"] if rows else "",
                "last_hash": chain.get("latest_hash") or "",
                "result": "PASS" if chain.get("ok") and not invalid else "FAIL",
                "ok": bool(chain.get("ok") and not invalid),
            }
        finally:
            conn.close()

    def production_requirements(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            reports = {}
            for report_type in PRODUCTION_REQUIRED_REPORT_TYPES:
                row = conn.execute(
                    """
                    SELECT * FROM production_entry_reports
                    WHERE report_type=?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (report_type,),
                ).fetchone()
                reports[report_type] = dict(row) if row else None
            missing = [key for key, row in reports.items() if not row]
            failed = [
                key
                for key, row in reports.items()
                if row
                and (
                    not bool(row["pass"])
                    or int(row["critical_findings_count"] or 0) > 0
                    or int(row["high_findings_count"] or 0) > 0
                    or not row["report_hash"]
                )
            ]
            return {
                "ok": not missing and not failed,
                "required": list(PRODUCTION_REQUIRED_REPORT_TYPES),
                "missing": missing,
                "failed": failed,
                "reports": reports,
            }
        finally:
            conn.close()

    def upload_production_report(
        self,
        *,
        actor,
        report_type,
        report_hash,
        target_commit="",
        target_branch="",
        server_mode="",
        test_result="",
        passed=False,
        critical_findings_count=0,
        high_findings_count=0,
        unresolved_findings=None,
        tester="",
        signature="",
    ):
        report_type = str(report_type or "").strip()
        if report_type not in PRODUCTION_REQUIRED_REPORT_TYPES:
            return {"ok": False, "msg": "report_type 不在 production gate 清單"}
        report_hash = str(report_hash or "").strip()
        target_commit = str(target_commit or "").strip()
        target_branch = str(target_branch or "").strip()
        server_mode = str(server_mode or "").strip()
        test_result = str(test_result or "").strip().lower()
        tester = str(tester or self._actor_name(actor) or "").strip()
        signature = str(signature or "").strip()
        if not SHA256_REPORT_HASH_RE.fullmatch(report_hash):
            return {"ok": False, "msg": "report_hash 必須是 sha256:<64 hex>"}
        if not target_commit or not target_branch or not server_mode or not test_result or not tester or not signature:
            return {"ok": False, "msg": "production report 缺少 target_commit/target_branch/server_mode/test_result/tester/signature"}
        if test_result not in {"pass", "passed"} or not passed:
            return {"ok": False, "msg": "production report 必須明確 pass"}
        if int(critical_findings_count or 0) != 0 or int(high_findings_count or 0) != 0:
            return {"ok": False, "msg": "production report 不允許 critical/high finding"}
        if unresolved_findings:
            return {"ok": False, "msg": "production report 不允許 unresolved finding"}
        report_id = f"prodrep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            replay = conn.execute(
                """
                SELECT id FROM production_entry_reports
                WHERE report_type=? AND report_hash=? AND target_commit=?
                LIMIT 1
                """,
                (report_type, report_hash, target_commit),
            ).fetchone()
            if replay:
                return {"ok": False, "msg": "production report replay detected", "existing_report_id": replay["id"]}
            conn.execute(
                """
                INSERT INTO production_entry_reports
                (id, report_type, report_hash, target_commit, target_branch, server_mode, test_result,
                 pass, critical_findings_count, high_findings_count, unresolved_findings_json, tester, signature, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    report_type,
                    report_hash,
                    target_commit,
                    target_branch,
                    server_mode,
                    test_result,
                    1 if passed else 0,
                    int(critical_findings_count or 0),
                    int(high_findings_count or 0),
                    json.dumps(unresolved_findings or [], ensure_ascii=False, sort_keys=True),
                    tester,
                    signature,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return {"ok": True, "report_id": report_id, "requirements": self.production_requirements()}
        finally:
            conn.close()

    def create_tester_token(
        self,
        *,
        actor,
        tester_user_id,
        allowed_features=None,
        allowed_routes=None,
        expires_at,
        max_requests_per_minute=60,
        can_modify_own_role=False,
        can_modify_own_points=False,
        can_run_security_tests=False,
    ):
        try:
            tester_user_id = int(tester_user_id)
        except Exception:
            return {"ok": False, "msg": "tester_user_id 必須是數字"}
        expires_at = str(expires_at or "").strip()
        if not expires_at:
            return {"ok": False, "msg": "expires_at 必填"}
        token = f"hmt_{secrets.token_urlsafe(32)}"
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token_id = f"tester_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        rpm = max(1, min(int(max_requests_per_minute or 60), 600))
        issued_at = datetime.now().isoformat()
        nonce = secrets.token_urlsafe(18)
        mode_scope = ["test", "internal_test"]
        method_scope = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        route_scope = allowed_routes or []
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            key, key_version = self._hmac_key("server_mode_token")
            token_payload = {
                "id": token_id,
                "token_hash": token_hash,
                "tester_user_id": tester_user_id,
                "mode_scope_json": json.dumps(mode_scope, ensure_ascii=False, sort_keys=True),
                "route_scope_json": json.dumps(route_scope, ensure_ascii=False, sort_keys=True),
                "method_scope_json": json.dumps(method_scope, ensure_ascii=False, sort_keys=True),
                "expires_at": expires_at,
                "issued_at": issued_at,
                "nonce": nonce,
                "max_requests_per_minute": rpm,
                "key_version": key_version,
            }
            signature = _hmac_sha256(key, _tester_token_signature_payload(token_payload))
            self._record_security_key_on_conn(
                conn,
                purpose="server_mode_token",
                key_version=key_version,
                status="active",
            )
            conn.execute(
                """
                INSERT INTO tester_tokens
                (id, token_hash, tester_user_id, mode_scope_json, route_scope_json, method_scope_json,
                 allowed_features_json, allowed_routes_json, expires_at, issued_at, nonce,
                 max_requests_per_minute, can_modify_own_role, can_modify_own_points, can_run_security_tests,
                 created_by, created_at, hmac_signature, key_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_id,
                    token_hash,
                    tester_user_id,
                    token_payload["mode_scope_json"],
                    token_payload["route_scope_json"],
                    token_payload["method_scope_json"],
                    json.dumps(allowed_features or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(route_scope, ensure_ascii=False, sort_keys=True),
                    expires_at,
                    issued_at,
                    nonce,
                    rpm,
                    1 if can_modify_own_role else 0,
                    1 if can_modify_own_points else 0,
                    1 if can_run_security_tests else 0,
                    self._actor_id(actor),
                    issued_at,
                    signature,
                    key_version,
                ),
            )
            conn.commit()
            return {
                "ok": True,
                "token_id": token_id,
                "token": token,
                "expires_at": expires_at,
                "max_requests_per_minute": rpm,
                "warning": "token 只會回傳一次，請交給測試員後妥善保存",
            }
        finally:
            conn.close()

    def revoke_tester_token(self, *, actor, token_id, reason=""):
        token_id = str(token_id or "").strip()
        if not token_id:
            return {"ok": False, "msg": "token_id 必填"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            cur = conn.execute(
                "UPDATE tester_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (datetime.now().isoformat(), token_id),
            )
            conn.commit()
            return {"ok": bool(cur.rowcount), "token_id": token_id, "reason": reason or ""}
        finally:
            conn.close()

    def list_tester_tokens(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT id, tester_user_id, mode_scope_json, route_scope_json, method_scope_json,
                       allowed_features_json, allowed_routes_json, expires_at,
                       max_requests_per_minute, can_modify_own_role, can_modify_own_points,
                       can_run_security_tests, created_by, created_at, issued_at, nonce, revoked_at,
                       key_version
                FROM tester_tokens
                ORDER BY created_at DESC
                LIMIT 200
                """
            ).fetchall()
            tokens = []
            for row in rows:
                item = dict(row)
                for key in ("allowed_features_json", "allowed_routes_json", "mode_scope_json", "route_scope_json", "method_scope_json"):
                    try:
                        item[key.replace("_json", "")] = json.loads(item.pop(key) or "[]")
                    except Exception:
                        item[key.replace("_json", "")] = []
                for key in ("can_modify_own_role", "can_modify_own_points", "can_run_security_tests"):
                    item[key] = bool(item.get(key))
                tokens.append(item)
            return tokens
        finally:
            conn.close()

    def _write_tester_token_audit(self, conn, *, token_id="", route="", normalized_route="", method="", allowed=False, reason="", ip_address=""):
        try:
            conn.execute(
                """
                INSERT INTO tester_token_audit
                (token_id, route, normalized_route, method, allowed, reason, source_ip, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (token_id or "", route or "", normalized_route or "", method or "", 1 if allowed else 0, reason or "", ip_address or "", datetime.now().isoformat()),
            )
        except Exception:
            pass

    def active_tester_token(self, *, token, route="", ip_address="", method="", log_request=False):
        token = str(token or "").strip()
        if not token:
            return {"ok": False, "msg": "tester token required"}
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            method = str(method or "GET").upper()
            mode_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
            current_mode = self._normalize_mode(mode_row["current_mode"] if mode_row else "test")
            if current_mode not in {"test", "internal_test"}:
                self._write_tester_token_audit(conn, route=route, method=method, allowed=False, reason="mode_not_allowed", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 只能在 test / internal_test 模式使用"}
            row = conn.execute(
                """
                SELECT t.*, u.username, u.role, u.status
                FROM tester_tokens t
                JOIN users u ON u.id=t.tester_user_id
                WHERE t.token_hash=?
                  AND t.revoked_at IS NULL
                  AND t.expires_at>?
                  AND u.status='active'
                LIMIT 1
                """,
                (token_hash, datetime.now().isoformat()),
            ).fetchone()
            if not row:
                self._write_tester_token_audit(conn, route=route, method=method, allowed=False, reason="invalid_expired_or_revoked", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 無效、過期或已撤銷"}
            token_row = dict(row)
            try:
                mode_scope = json.loads(token_row.get("mode_scope_json") or '["test","internal_test"]')
            except Exception:
                mode_scope = ["test", "internal_test"]
            if current_mode not in {self._normalize_mode(item) for item in mode_scope}:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="mode_scope_denied", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許在目前 server mode 使用"}
            try:
                method_scope = {str(item).upper() for item in json.loads(token_row.get("method_scope_json") or "[]")}
            except Exception:
                method_scope = set()
            if method_scope and method not in method_scope:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="method_scope_denied", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許使用此 HTTP method"}
            signature = token_row.get("hmac_signature") or ""
            if not signature:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="missing_token_signature", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 缺少簽章，請重新發行"}
            try:
                key, _ = self._hmac_key("server_mode_token", current_mode=current_mode)
                expected_signature = _hmac_sha256(key, _tester_token_signature_payload(token_row))
                signature_ok = hmac.compare_digest(signature, expected_signature)
            except Exception:
                signature_ok = False
            if not signature_ok:
                self._write_tester_token_audit(conn, token_id=row["id"], route=route, method=method, allowed=False, reason="invalid_token_signature", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 簽章無效"}
            path = str(route or "")
            normalized_path, route_error = _normalize_mode_route(path)
            if route_error:
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path or "", method=method, allowed=False, reason=route_error, ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 路由包含可疑 traversal 或 encoded bypass"}
            forbidden_prefixes = ("/api/root", "/api/admin", "/api/server-mode", "/api/admin/server-mode", "/api/admin/snapshots", "/api/admin/integrity", "/api/audit")
            if any(normalized_path == prefix or normalized_path.startswith(prefix.rstrip("/") + "/") for prefix in forbidden_prefixes):
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="forbidden_sensitive_api", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許操作 root API"}
            try:
                allowed_routes = json.loads(row["route_scope_json"] or row["allowed_routes_json"] or "[]")
            except Exception:
                allowed_routes = []
            normalized_allowed = []
            for allowed_route in allowed_routes:
                norm, err = _normalize_mode_route(str(allowed_route))
                if norm and not err:
                    normalized_allowed.append(norm)
            if normalized_allowed and normalized_path and not any(normalized_path == route or normalized_path.startswith(str(route).rstrip("/") + "/") for route in normalized_allowed):
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="route_not_allowed", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 不允許操作此路由"}
            window_start = (datetime.now().replace(microsecond=0)).isoformat()
            # keep the window simple and deterministic: compare to one minute ago
            try:
                from datetime import timedelta
                window_start = (datetime.now() - timedelta(seconds=60)).isoformat()
            except Exception:
                pass
            recent = conn.execute(
                "SELECT COUNT(*) AS c FROM tester_token_request_log WHERE token_id=? AND created_at>?",
                (row["id"], window_start),
            ).fetchone()
            max_rpm = max(1, int(row["max_requests_per_minute"] or 60))
            if int(recent["c"] or 0) >= max_rpm:
                self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=False, reason="rate_limited", ip_address=ip_address)
                conn.commit()
                return {"ok": False, "msg": "tester token 已超過每分鐘請求上限"}
            if log_request and path:
                conn.execute(
                    "INSERT INTO tester_token_request_log (token_id, route, ip_address, created_at) VALUES (?, ?, ?, ?)",
                    (row["id"], path, ip_address or "", datetime.now().isoformat()),
                )
            self._write_tester_token_audit(conn, token_id=row["id"], route=path, normalized_route=normalized_path, method=method, allowed=True, reason="allowed", ip_address=ip_address)
            conn.commit()
            item = dict(row)
            for key in ("allowed_features_json", "allowed_routes_json", "mode_scope_json", "route_scope_json", "method_scope_json"):
                try:
                    item[key.replace("_json", "")] = json.loads(item.pop(key) or "[]")
                except Exception:
                    item[key.replace("_json", "")] = []
            for key in ("can_modify_own_role", "can_modify_own_points", "can_run_security_tests"):
                item[key] = bool(item.get(key))
            item.pop("token_hash", None)
            return {"ok": True, "token": item, "mode": current_mode}
        finally:
            conn.close()

    def tester_shadow_state(self, *, actor, token, route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            role_row = conn.execute(
                "SELECT * FROM test_shadow_roles WHERE tester_user_id=? ORDER BY id DESC LIMIT 1",
                (tester_user_id,),
            ).fetchone()
            wallet_row = conn.execute(
                "SELECT * FROM test_shadow_wallets WHERE tester_user_id=?",
                (tester_user_id,),
            ).fetchone()
            tx_rows = conn.execute(
                "SELECT * FROM test_shadow_transactions WHERE tester_user_id=? ORDER BY created_at DESC LIMIT 100",
                (tester_user_id,),
            ).fetchall()
            chain_rows = conn.execute(
                "SELECT id, prev_hash, block_hash, created_at FROM test_chain_blocks ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            return {
                "ok": True,
                "mode": token_result.get("mode"),
                "token": {
                    "id": token_row["id"],
                    "expires_at": token_row["expires_at"],
                    "can_modify_own_role": bool(token_row["can_modify_own_role"]),
                    "can_modify_own_points": bool(token_row["can_modify_own_points"]),
                    "can_run_security_tests": bool(token_row["can_run_security_tests"]),
                },
                "shadow_role": dict(role_row) if role_row else None,
                "shadow_wallet": dict(wallet_row) if wallet_row else {"tester_user_id": tester_user_id, "balance_points": 0},
                "shadow_transactions": [dict(row) for row in tx_rows],
                "test_chain": [dict(row) for row in chain_rows],
            }
        finally:
            conn.close()

    def set_tester_shadow_role(self, *, actor, token, shadow_role, route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        if not token_row.get("can_modify_own_role"):
            return {"ok": False, "msg": "此 tester token 未允許修改自己的 shadow role"}
        shadow_role = str(shadow_role or "").strip()
        if shadow_role not in {"user", "manager"}:
            return {"ok": False, "msg": "shadow_role 只能是 user 或 manager；tester 不可升成 root"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            user = conn.execute("SELECT role FROM users WHERE id=?", (tester_user_id,)).fetchone()
            if not user:
                return {"ok": False, "msg": "找不到 tester user"}
            conn.execute(
                """
                INSERT INTO test_shadow_roles
                (tester_user_id, original_role, shadow_role, token_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tester_user_id, user["role"], shadow_role, token_row["id"], datetime.now().isoformat()),
            )
            conn.commit()
            return {"ok": True, "shadow_role": shadow_role, "original_role": user["role"], "formal_users_table_changed": False}
        finally:
            conn.close()

    def adjust_tester_shadow_wallet(self, *, actor, token, delta_points, reason="", route="", ip_address=""):
        token_result = self.active_tester_token(token=token, route=route, ip_address=ip_address, log_request=True)
        if not token_result.get("ok"):
            return token_result
        token_row = token_result["token"]
        tester_user_id = int(token_row["tester_user_id"])
        if tester_user_id != self._actor_id(actor):
            return {"ok": False, "msg": "tester token 與目前帳號不一致"}
        if not token_row.get("can_modify_own_points"):
            return {"ok": False, "msg": "此 tester token 未允許修改自己的 shadow points"}
        try:
            delta = int(delta_points)
        except Exception:
            return {"ok": False, "msg": "delta_points 必須是整數"}
        if delta == 0:
            return {"ok": False, "msg": "delta_points 不可為 0"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM test_shadow_wallets WHERE tester_user_id=?",
                (tester_user_id,),
            ).fetchone()
            current = int(row["balance_points"] or 0) if row else 0
            next_balance = current + delta
            if next_balance < 0:
                return {"ok": False, "msg": "shadow wallet 不可變成負數"}
            now = datetime.now().isoformat()
            if row:
                conn.execute(
                    "UPDATE test_shadow_wallets SET balance_points=?, token_id=?, updated_at=? WHERE tester_user_id=?",
                    (next_balance, token_row["id"], now, tester_user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO test_shadow_wallets (tester_user_id, balance_points, token_id, updated_at) VALUES (?, ?, ?, ?)",
                    (tester_user_id, next_balance, token_row["id"], now),
                )
            tx_id = f"shadow_tx_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
            conn.execute(
                """
                INSERT INTO test_shadow_transactions
                (id, tester_user_id, delta_points, reason, token_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tx_id, tester_user_id, delta, str(reason or "")[:500], token_row["id"], now),
            )
            prev = conn.execute(
                "SELECT block_hash FROM test_chain_blocks ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev["block_hash"] if prev else "GENESIS"
            block_id = f"testblk_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
            tx_payload = {
                "tx_id": tx_id,
                "tester_user_id": tester_user_id,
                "delta_points": delta,
                "balance_after": next_balance,
                "reason": reason or "",
            }
            block_hash = self._stable_hash({"id": block_id, "prev_hash": prev_hash, "tx": tx_payload, "created_at": now})
            conn.execute(
                """
                INSERT INTO test_chain_blocks
                (id, prev_hash, block_hash, transactions_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (block_id, prev_hash, block_hash, json.dumps([tx_payload], ensure_ascii=False, sort_keys=True), now),
            )
            conn.commit()
            return {
                "ok": True,
                "transaction_id": tx_id,
                "test_block_id": block_id,
                "balance_points": next_balance,
                "formal_points_chain_changed": False,
            }
        finally:
            conn.close()

    def enter_incident_lockdown(self, *, actor, trigger_type, reason, verification=None):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            incident_id = self._enter_incident_lockdown_on_conn(
                conn,
                actor=actor,
                trigger_type=trigger_type,
                reason=reason,
                verification=verification or {},
            )
            conn.commit()
            self.audit("SERVER_MODE_INCIDENT_LOCKDOWN_ENTER", "-", user=self._actor_name(actor), success=True, detail=f"incident_id={incident_id},trigger={trigger_type},reason={reason}")
            return {"ok": True, "incident_id": incident_id, "mode": self.get_current_mode()}
        finally:
            conn.close()

    def incident_status(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM incident_reports WHERE status='open' ORDER BY entered_at DESC LIMIT 1").fetchone()
            mode_row = conn.execute("SELECT * FROM server_modes WHERE id=1").fetchone()
            return {"ok": True, "incident": dict(row) if row else None, "mode": dict(mode_row) if mode_row else None}
        finally:
            conn.close()

    def resolve_incident(self, *, actor, confirm, notes="", verification=None):
        if confirm != "RESOLVE_INCIDENT":
            return {"ok": False, "msg": "confirm 必須等於 RESOLVE_INCIDENT"}
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            row = conn.execute("SELECT * FROM incident_reports WHERE status='open' ORDER BY entered_at DESC LIMIT 1").fetchone()
            if not row:
                return {"ok": False, "msg": "目前沒有 open incident"}
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE incident_reports
                SET status='resolved', resolved_by=?, resolved_at=?, resolution_notes=?, verification_json=?
                WHERE id=?
                """,
                (
                    self._actor_id(actor),
                    now,
                    notes or "",
                    json.dumps(verification or {}, ensure_ascii=False, sort_keys=True),
                    row["id"],
                ),
            )
            conn.commit()
            return {"ok": True, "incident_id": row["id"], "resolved_at": now}
        finally:
            conn.close()

    def _apply_production_upload_policy(self, conn):
        try:
            from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
        except Exception:
            return {"ok": False, "msg": "upload security policy unavailable"}
        ensure_upload_security_schema(conn)
        policy, msg = update_cloud_drive_security_policy(conn, {
            "require_scan_before_download": True,
            "block_unclean_downloads": True,
            "warn_high_risk_downloads": True,
            "allow_inline_preview_for_high_risk": False,
            "e2ee_server_scan_claim_allowed": False,
            "revoke_shares_on_suspension": True,
            "scanner_enabled": True,
            "scanner_backend": "clamav",
            "scanner_timeout_seconds": 60,
            "fail_closed_on_scanner_error": True,
            "quarantine_on_infected": True,
            "validate_magic_mime": True,
            "deep_archive_scan_enabled": True,
            "max_archive_depth": 2,
            "office_macro_scan_enabled": True,
            "image_reencode_enabled": True,
            "image_reencode_max_pixels": 25_000_000,
            "yara_enabled": True,
            "max_archive_files": 200,
            "max_archive_uncompressed_bytes": 50 * 1024 * 1024,
            "max_daily_downloads": 500,
            "notes": "production mode: strict scan, fail-closed download, quarantine and content validation enabled",
        })
        if msg:
            return {"ok": False, "msg": msg}
        return {"ok": True, "policy": policy}

    def _apply_production_account_policy(self, conn, *, actor):
        user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "username" not in user_cols or "id" not in user_cols:
            return {"default_password_reset_required": 0, "test_accounts_disabled": 0, "sessions_revoked": 0}
        now = datetime.now().isoformat()

        default_where = ["username IN ({})".format(",".join("?" for _ in DEFAULT_ACCOUNT_NAMES))]
        default_params = list(DEFAULT_ACCOUNT_NAMES)
        if "is_default_password" in user_cols:
            default_where.append("COALESCE(is_default_password, 0)=1")
        default_rows = conn.execute(
            f"SELECT id FROM users WHERE {' OR '.join(default_where)}",
            tuple(default_params),
        ).fetchall()
        default_ids = [int(row["id"]) for row in default_rows]
        default_updates = []
        if "must_change_password" in user_cols:
            default_updates.append("must_change_password=1")
        if "is_default_password" in user_cols:
            default_updates.append("is_default_password=1")
        if "updated_at" in user_cols:
            default_updates.append("updated_at=?")
        if default_ids and default_updates:
            params = []
            if "updated_at" in user_cols:
                params.append(now)
            placeholders = ",".join("?" for _ in default_ids)
            conn.execute(
                f"UPDATE users SET {', '.join(default_updates)} WHERE id IN ({placeholders})",
                tuple(params + default_ids),
            )

        test_rows = conn.execute(
            "SELECT id FROM users WHERE username IN ({})".format(",".join("?" for _ in TEST_ACCOUNT_NAMES)),
            tuple(TEST_ACCOUNT_NAMES),
        ).fetchall()
        test_ids = [int(row["id"]) for row in test_rows]
        if test_ids and "status" in user_cols:
            updates = ["status='inactive'"]
            if "updated_at" in user_cols:
                updates.append("updated_at=?")
            params = [now] if "updated_at" in user_cols else []
            placeholders = ",".join("?" for _ in test_ids)
            conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id IN ({placeholders})",
                tuple(params + test_ids),
            )

        sessions_revoked = 0
        session_cols = set()
        try:
            session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        except Exception:
            session_cols = set()
        if test_ids and {"user_id", "is_revoked"}.issubset(session_cols):
            placeholders = ",".join("?" for _ in test_ids)
            updates = ["is_revoked=1"]
            params = []
            if "revoked_at" in session_cols:
                updates.append("revoked_at=?")
                params.append(now)
            cur = conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE user_id IN ({placeholders}) AND COALESCE(is_revoked, 0)=0",
                tuple(params + test_ids),
            )
            sessions_revoked = int(cur.rowcount or 0)

        return {
            "default_password_reset_required": len(default_ids),
            "test_accounts_disabled": len(test_ids),
            "sessions_revoked": sessions_revoked,
            "password_policy": "forced reset uses the account password-strength policy",
            "actor": actor.get("username") if hasattr(actor, "get") else None,
        }

    def _apply_production_hardening(self, *, actor):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            account_result = self._apply_production_account_policy(conn, actor=actor)
            upload_policy = self._apply_production_upload_policy(conn)
            if not upload_policy.get("ok"):
                conn.rollback()
                return {"ok": False, "msg": upload_policy.get("msg") or "production upload policy failed"}
            conn.commit()
            return {"ok": True, "accounts": account_result, "cloud_drive_policy": upload_policy.get("policy")}
        finally:
            conn.close()

    def _apply_internal_test_hardening(self):
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            now = datetime.now().isoformat()
            session_cols = set()
            try:
                session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
            except Exception:
                session_cols = set()
            revoked = 0
            if {"user_id", "is_revoked"}.issubset(session_cols):
                updates = ["is_revoked=1"]
                params = []
                if "revoked_at" in session_cols:
                    updates.append("revoked_at=?")
                    params.append(now)
                cur = conn.execute(
                    f"""
                    UPDATE sessions
                    SET {', '.join(updates)}
                    WHERE COALESCE(is_revoked, 0)=0
                          AND user_id IN (
                              SELECT id FROM users
                              WHERE username<>'root'
                          )
                    """,
                    tuple(params),
                )
                revoked = int(cur.rowcount or 0)
            conn.commit()
            return {"ok": True, "sessions_revoked": revoked}
        finally:
            conn.close()

    def switch_mode(self, *, target_mode, actor, confirm, notes=None):
        original_target = str(target_mode or "").strip().lower()
        target_mode = self._normalize_mode(original_target)
        profile = self.get_profile(target_mode)
        if not profile:
            return {"ok": False, "msg": "server mode 錯誤"}
        expected_confirm = MODE_CONFIRM_PHRASES.get(target_mode, "SWITCH_CUSTOM_MODE")
        if confirm != expected_confirm:
            return {"ok": False, "msg": f"confirm 必須等於 {expected_confirm}"}
        if target_mode == "production":
            requirements = self.production_requirements()
            if not requirements.get("ok"):
                return {
                    "ok": False,
                    "msg": "production gate 未通過，缺少報告或仍有 critical/high finding",
                    "requirements": requirements,
                }
            if self.integrity_guard:
                try:
                    allowed, high_risk_count = self.integrity_guard.can_enter_preprod()
                except Exception:
                    allowed, high_risk_count = False, 1
                if not allowed:
                    conn = self.get_db()
                    try:
                        self.ensure_schema(conn)
                        current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
                        self._record_mode_switch(
                            conn,
                            from_mode=(current_row["current_mode"] if current_row else "test"),
                            to_mode="production",
                            actor=actor,
                            reason=notes or "",
                            success=False,
                            error_message="integrity guard high risk finding",
                            config_diff={"high_risk_count": high_risk_count},
                        )
                        self._enter_incident_lockdown_on_conn(
                            conn,
                            actor=actor,
                            trigger_type="integrity_high_risk",
                            reason="production entry blocked by high risk Integrity Guard finding",
                            verification={"high_risk_count": high_risk_count},
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    return {
                        "ok": False,
                        "msg": "Integrity Guard 存在高風險異常，不允許進入 production，已進入 incident_lockdown",
                        "high_risk_count": high_risk_count,
                        "incident_lockdown": True,
                    }
        applied_settings = {}
        production_result = None
        internal_test_result = None
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            current_row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
            current = self._normalize_mode(current_row["current_mode"] if current_row else "test")
            if current == "incident_lockdown" and target_mode == "superweak":
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    success=False,
                    error_message="incident_lockdown 不允許切換到 superweak",
                )
                conn.commit()
                return {"ok": False, "msg": "incident_lockdown 不允許切換到 superweak"}
            current_settings = self._settings_snapshot(conn)
            config_diff = self._config_diff(current_settings, {**(profile.get("settings") or {}), **(profile.get("thresholds") or {})})
        finally:
            conn.close()

        checkpoint = self.create_mode_checkpoint(
            actor=actor,
            target_mode=target_mode,
            reason=notes or "",
            snapshot_type="before_superweak" if target_mode == "superweak" else "mode_checkpoint",
            from_mode=current,
        )
        if not checkpoint.get("ok"):
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    success=False,
                    error_message=checkpoint.get("msg") or checkpoint.get("error") or "checkpoint failed",
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_failed",
                    reason=f"checkpoint before {target_mode} failed",
                    verification=checkpoint,
                )
                conn.commit()
            finally:
                conn.close()
            return {**checkpoint, "msg": checkpoint.get("msg") or "checkpoint 建立失敗，已進入 incident_lockdown", "incident_lockdown": True}

        try:
            if self.save_settings:
                updates = {}
                updates.update(profile.get("settings") or {})
                updates.update(profile.get("thresholds") or {})
                applied_settings = self.save_settings(updates) if updates else {}
            if target_mode == "production":
                production_result = self._apply_production_hardening(actor=actor)
                if not production_result.get("ok"):
                    raise RuntimeError(production_result.get("msg") or "production hardening failed")
            if target_mode == "internal_test":
                internal_test_result = self._apply_internal_test_hardening()
        except Exception as exc:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode=current,
                    to_mode=target_mode,
                    actor=actor,
                    reason=notes or "",
                    checkpoint_id=checkpoint.get("checkpoint_id"),
                    snapshot_id=checkpoint.get("snapshot_id"),
                    success=False,
                    error_message=str(exc),
                    config_diff=config_diff,
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_failed",
                    reason=f"mode switch to {target_mode} failed: {exc}",
                    verification={"checkpoint": checkpoint, "target_mode": target_mode},
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": False, "msg": "模式切換套用設定失敗，已進入 incident_lockdown", "error": str(exc), "checkpoint": checkpoint}

        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE server_modes
                SET previous_mode=?, current_mode=?, active_snapshot_id=?, checkpoint_id=?,
                    mode_changed_by=?, mode_changed_at=?, notes=?, reason=?, config_json=?
                WHERE id=1
                """,
                (
                    current,
                    target_mode,
                    checkpoint.get("snapshot_id") if target_mode == "superweak" else None,
                    checkpoint.get("checkpoint_id"),
                    self._actor_id(actor),
                    now,
                    notes or "",
                    notes or "",
                    json.dumps(profile, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._record_mode_switch(
                conn,
                from_mode=current,
                to_mode=target_mode,
                actor=actor,
                reason=notes or "",
                checkpoint_id=checkpoint.get("checkpoint_id"),
                snapshot_id=checkpoint.get("snapshot_id"),
                success=True,
                config_diff=config_diff,
                restore_result={},
            )
            chain = verify_mode_switch_log_hash_chain(conn)
            if not chain.get("ok"):
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="mode_switch_log_chain_broken",
                    reason=f"mode switch log hash chain failed after switching to {target_mode}",
                    verification=chain,
                )
                conn.commit()
                return {"ok": False, "msg": "mode switch log chain broken; incident_lockdown entered", "chain": chain, "incident_lockdown": True}
            conn.commit()
            event = "SUPERWEAK_ENTER" if target_mode == "superweak" else "SERVER_MODE_CHANGE"
            self.audit(event, "-", user=self._actor_name(actor), success=True, detail=f"old_value={current},new_value={target_mode},profile={profile['name']},checkpoint={checkpoint.get('checkpoint_id')},snapshot={checkpoint.get('snapshot_id')},settings={applied_settings},production={production_result or {}},internal_test={internal_test_result or {}},reason={notes or ''}")
            return {"ok": True, "mode": self.get_current_mode(), "profile": profile, "applied_settings": applied_settings, "production": production_result, "internal_test": internal_test_result, "checkpoint": checkpoint}
        finally:
            conn.close()

    def enter_superweak(self, *, actor, confirm, notes=None):
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) == "superweak":
            return {"ok": False, "msg": "目前已是 superweak 模式"}
        return self.switch_mode(target_mode="superweak", actor=actor, confirm=confirm, notes=notes)

    def exit_superweak(self, *, actor, action, confirm, reason):
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) != "superweak":
            return {"ok": False, "msg": "目前不是 superweak 模式"}
        if action == "keep_dirty_state":
            return {"ok": False, "msg": "Server Mode v2 禁止保留 superweak dirty state；離開 superweak 必須還原 checkpoint"}
        if action == "restore":
            if confirm != "RESTORE_BEFORE_SUPERWEAK":
                return {"ok": False, "msg": "confirm 必須等於 RESTORE_BEFORE_SUPERWEAK"}
            snapshot_id = current["active_snapshot_id"]
            checkpoint_id = current.get("checkpoint_id")
            expected_checkpoint = None
            if checkpoint_id:
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    expected_checkpoint = self._checkpoint_record(conn, checkpoint_id)
                finally:
                    conn.close()
            result = self.snapshot_service.restore_snapshot(snapshot_id=snapshot_id, actor=actor, reason=reason or "exit superweak", dry_run=False)
            if not result.get("ok"):
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    self._record_mode_switch(
                        conn,
                        from_mode="superweak",
                        to_mode=current["previous_mode"] or "test",
                        actor=actor,
                        reason=reason or "",
                        checkpoint_id=checkpoint_id,
                        snapshot_id=snapshot_id,
                        success=False,
                        error_message=result.get("msg") or result.get("error") or "restore failed",
                        restore_result=result,
                    )
                    self._enter_incident_lockdown_on_conn(
                        conn,
                        actor=actor,
                        trigger_type="restore_validation_failed",
                        reason="exit superweak restore failed",
                        verification=result,
                    )
                    conn.commit()
                finally:
                    conn.close()
                return {**result, "incident_lockdown": True}
            validation = self.validate_checkpoint_restore(checkpoint_id=checkpoint_id, expected_checkpoint=expected_checkpoint) if checkpoint_id else {"ok": False, "msg": "missing checkpoint_id"}
            if not validation.get("ok"):
                conn = self.get_db()
                try:
                    self.ensure_schema(conn)
                    self._record_mode_switch(
                        conn,
                        from_mode="superweak",
                        to_mode=current["previous_mode"] or "test",
                        actor=actor,
                        reason=reason or "",
                        checkpoint_id=checkpoint_id,
                        snapshot_id=snapshot_id,
                        success=False,
                        error_message="checkpoint restore validation failed",
                        restore_result=validation,
                    )
                    self._enter_incident_lockdown_on_conn(
                        conn,
                        actor=actor,
                        trigger_type="restore_validation_failed",
                        reason="superweak checkpoint restore validation failed",
                        verification=validation,
                    )
                    conn.commit()
                finally:
                    conn.close()
                return {"ok": False, "msg": "superweak 還原驗證失敗，已進入 incident_lockdown", "restore": result, "validation": validation, "incident_lockdown": True}
            previous = self._normalize_mode(current["previous_mode"] or "test")
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                conn.execute(
                    """
                    UPDATE server_modes
                    SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, checkpoint_id=NULL,
                        mode_changed_by=?, mode_changed_at=?, notes=?, reason=?
                    WHERE id=1
                    """,
                    (previous, self._actor_id(actor), datetime.now().isoformat(), reason or "", reason or ""),
                )
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode=previous,
                    actor=actor,
                    reason=reason or "",
                    checkpoint_id=checkpoint_id,
                    snapshot_id=snapshot_id,
                    success=True,
                    restore_result={"restore": result, "validation": validation},
                )
                conn.commit()
            finally:
                conn.close()
            self.audit("SUPERWEAK_EXIT_RESTORE", "-", user=self._actor_name(actor), success=True, detail=f"restored_snapshot={snapshot_id},checkpoint={checkpoint_id},new_value={previous},reason={reason}")
            return {"ok": True, "mode": self.get_current_mode(), "validation": validation, **result}
        return {"ok": False, "msg": "action 錯誤"}

    def recover_superweak_on_startup(self, *, actor=None):
        actor = actor or {"id": 0, "username": "system-startup", "role": "system"}
        current = self.get_current_mode()
        if self._normalize_mode(current.get("current_mode")) != "superweak":
            return {"ok": True, "recovered": False, "mode": current}
        snapshot_id = current.get("active_snapshot_id")
        checkpoint_id = current.get("checkpoint_id")
        if not snapshot_id or not checkpoint_id:
            conn = self.get_db()
            try:
                self.ensure_schema(conn)
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode="incident_lockdown",
                    actor=actor,
                    reason="startup superweak recovery failed: missing checkpoint/snapshot",
                    success=False,
                    error_message="missing active_snapshot_id or checkpoint_id",
                )
                self._enter_incident_lockdown_on_conn(
                    conn,
                    actor=actor,
                    trigger_type="superweak_recovery_failed",
                    reason="startup found superweak without active checkpoint",
                    verification={"mode": current},
                )
                conn.commit()
            finally:
                conn.close()
            return {"ok": False, "recovered": False, "incident_lockdown": True, "msg": "superweak startup recovery missing checkpoint"}
        expected_checkpoint = None
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            expected_checkpoint = self._checkpoint_record(conn, checkpoint_id)
        finally:
            conn.close()
        result = self.snapshot_service.restore_snapshot(
            snapshot_id=snapshot_id,
            actor=actor,
            reason="startup recovery after superweak crash",
            dry_run=False,
        )
        validation = self.validate_checkpoint_restore(checkpoint_id=checkpoint_id, expected_checkpoint=expected_checkpoint)
        previous = self._normalize_mode(current.get("previous_mode") or "test")
        conn = self.get_db()
        try:
            self.ensure_schema(conn)
            if result.get("ok") and validation.get("ok"):
                conn.execute(
                    """
                    UPDATE server_modes
                    SET current_mode=?, previous_mode='superweak', active_snapshot_id=NULL, checkpoint_id=NULL,
                        mode_changed_by=?, mode_changed_at=?, notes=?, reason=?
                    WHERE id=1
                    """,
                    (
                        previous,
                        self._actor_id(actor),
                        datetime.now().isoformat(),
                        "startup recovered superweak dirty state",
                        "startup recovered superweak dirty state",
                    ),
                )
                self._record_mode_switch(
                    conn,
                    from_mode="superweak",
                    to_mode=previous,
                    actor=actor,
                    reason="startup recovered superweak dirty state",
                    checkpoint_id=checkpoint_id,
                    snapshot_id=snapshot_id,
                    success=True,
                    restore_result={"restore": result, "validation": validation},
                )
                conn.commit()
                self.audit("SUPERWEAK_STARTUP_RECOVERY", "-", user=self._actor_name(actor), success=True, detail=f"snapshot={snapshot_id},checkpoint={checkpoint_id},new_value={previous}")
                return {"ok": True, "recovered": True, "mode": self.get_current_mode(), "restore": result, "validation": validation}
            self._record_mode_switch(
                conn,
                from_mode="superweak",
                to_mode="incident_lockdown",
                actor=actor,
                reason="startup superweak recovery validation failed",
                checkpoint_id=checkpoint_id,
                snapshot_id=snapshot_id,
                success=False,
                error_message="restore or validation failed",
                restore_result={"restore": result, "validation": validation},
            )
            self._enter_incident_lockdown_on_conn(
                conn,
                actor=actor,
                trigger_type="superweak_recovery_failed",
                reason="startup superweak restore validation failed",
                verification={"restore": result, "validation": validation},
            )
            conn.commit()
            return {"ok": False, "recovered": False, "incident_lockdown": True, "restore": result, "validation": validation}
        finally:
            conn.close()
