import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path


UPLOAD_PRIVACY_MODES = {
    "public_attachment",
    "private_scannable",
    "e2ee_vault",
    "e2ee_vault_with_client_scan",
}
RISK_LEVELS = {"low", "medium", "high", "blocked", "unknown_encrypted"}
SCAN_STATUSES = {
    "not_required",
    "pending",
    "scanning",
    "clean",
    "infected",
    "failed",
    "skipped_e2ee",
    "unknown_encrypted",
    "quarantined",
}

EXECUTABLE_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".ps1", ".scr", ".msi", ".vbs",
    ".js", ".jar", ".apk", ".ipa", ".reg", ".lnk",
}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".xlsm", ".docm", ".pptm"}
MACRO_OFFICE_EXTENSIONS = {".xlsm", ".docm", ".pptm"}
REENCODABLE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}

DEFAULT_FILE_TYPE_POLICIES = {
    "executable": {
        "extensions": sorted(EXECUTABLE_EXTENSIONS),
        "public_allowed": False,
        "private_scannable_allowed": False,
        "e2ee_allowed": True,
        "default_risk_level": "high",
        "allow_public_share": False,
        "requires_scan": True,
        "warn_on_download": True,
        "notes": "Executable-like files are blocked from public/private scannable uploads by default.",
    },
    "archive": {
        "extensions": sorted(ARCHIVE_EXTENSIONS),
        "public_allowed": True,
        "private_scannable_allowed": True,
        "e2ee_allowed": True,
        "default_risk_level": "medium",
        "allow_public_share": False,
        "requires_scan": True,
        "warn_on_download": True,
        "notes": "Archives require bomb and path traversal checks before release.",
    },
    "office": {
        "extensions": sorted(OFFICE_EXTENSIONS - MACRO_OFFICE_EXTENSIONS),
        "public_allowed": True,
        "private_scannable_allowed": True,
        "e2ee_allowed": True,
        "default_risk_level": "medium",
        "allow_public_share": True,
        "requires_scan": True,
        "warn_on_download": False,
        "notes": "Office documents require content scanning before download.",
    },
    "office_macro": {
        "extensions": sorted(MACRO_OFFICE_EXTENSIONS),
        "public_allowed": True,
        "private_scannable_allowed": True,
        "e2ee_allowed": True,
        "default_risk_level": "high",
        "allow_public_share": False,
        "requires_scan": True,
        "warn_on_download": True,
        "notes": "Macro-enabled Office documents are high risk.",
    },
    "default": {
        "extensions": [],
        "public_allowed": True,
        "private_scannable_allowed": True,
        "e2ee_allowed": True,
        "default_risk_level": "low",
        "allow_public_share": True,
        "requires_scan": True,
        "warn_on_download": False,
        "notes": "Default policy for unknown non-executable file extensions.",
    },
}

DEFAULT_CLOUD_DRIVE_SECURITY_POLICY = {
    "scope": "default",
    "require_scan_before_download": True,
    "block_unclean_downloads": True,
    "warn_high_risk_downloads": True,
    "allow_inline_preview_for_high_risk": False,
    "e2ee_server_scan_claim_allowed": False,
    "revoke_shares_on_suspension": True,
    "scanner_enabled": True,
    "scanner_backend": "clamav",
    "scanner_command": "",
    "scanner_timeout_seconds": 60,
    "fail_closed_on_scanner_error": True,
    "quarantine_on_infected": True,
    "validate_magic_mime": True,
    "deep_archive_scan_enabled": True,
    "max_archive_depth": 2,
    "office_macro_scan_enabled": True,
    "image_reencode_enabled": True,
    "image_reencode_max_pixels": 25_000_000,
    "yara_enabled": False,
    "yara_command": "",
    "yara_rules_path": "",
    "max_archive_files": 200,
    "max_archive_uncompressed_bytes": 50 * 1024 * 1024,
    "max_daily_downloads": 500,
    "notes": (
        "Cloud drive files are governed by privacy mode, scan status, risk level, "
        "member level quota, and share/download restrictions."
    ),
}

CLOUD_DRIVE_POLICY_BOOL_FIELDS = {
    "require_scan_before_download",
    "block_unclean_downloads",
    "warn_high_risk_downloads",
    "allow_inline_preview_for_high_risk",
    "e2ee_server_scan_claim_allowed",
    "revoke_shares_on_suspension",
    "scanner_enabled",
    "fail_closed_on_scanner_error",
    "quarantine_on_infected",
    "validate_magic_mime",
    "deep_archive_scan_enabled",
    "office_macro_scan_enabled",
    "image_reencode_enabled",
    "yara_enabled",
}
CLOUD_DRIVE_POLICY_INT_FIELDS = {
    "scanner_timeout_seconds",
    "max_archive_depth",
    "image_reencode_max_pixels",
    "max_archive_files",
    "max_archive_uncompressed_bytes",
    "max_daily_downloads",
}
CLOUD_DRIVE_POLICY_TEXT_FIELDS = {"scanner_backend", "scanner_command", "yara_command", "yara_rules_path", "notes"}

ALLOWED_SCANNER_BACKENDS = {"disabled", "clamav"}

MIME_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"PK\x05\x06", "application/zip"),
    (b"PK\x07\x08", "application/zip"),
    (b"MZ", "application/x-dosexec"),
    (b"\x7fELF", "application/x-elf"),
)

EXTENSION_MIME_PREFIXES = {
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".gif": ("image/gif",),
    ".pdf": ("application/pdf",),
    ".zip": ("application/zip",),
}

HIGH_RISK_MAGIC_MIMES = {"application/x-dosexec", "application/x-elf"}


@dataclass(frozen=True)
class UploadPolicyDecision:
    allowed: bool
    privacy_mode: str
    risk_level: str
    scan_status: str
    category: str
    reason: str
    warnings: tuple

    def as_dict(self):
        return {
            "allowed": self.allowed,
            "privacy_mode": self.privacy_mode,
            "risk_level": self.risk_level,
            "scan_status": self.scan_status,
            "category": self.category,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


def ensure_upload_security_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            original_filename_encrypted TEXT,
            original_filename_plain_for_public TEXT,
            mime_type_encrypted TEXT,
            mime_type_plain_for_public TEXT,
            size_bytes INTEGER NOT NULL,
            ciphertext_sha256 TEXT,
            plaintext_sha256 TEXT,
            encryption_algorithm TEXT,
            encryption_version TEXT,
            nonce TEXT,
            client_scan_report_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS encrypted_file_keys (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            encrypted_file_key TEXT NOT NULL,
            wrapped_by TEXT NOT NULL,
            key_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_scan_results (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            scanner_name TEXT NOT NULL,
            scanner_version TEXT,
            scan_started_at TEXT,
            scan_completed_at TEXT,
            result TEXT NOT NULL,
            malware_name TEXT,
            details_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_access_logs (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            actor_user_id INTEGER,
            action TEXT NOT NULL,
            ip TEXT,
            user_agent TEXT,
            result TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_type_policies (
            category TEXT PRIMARY KEY,
            extensions_json TEXT NOT NULL,
            public_allowed INTEGER NOT NULL,
            private_scannable_allowed INTEGER NOT NULL,
            e2ee_allowed INTEGER NOT NULL,
            default_risk_level TEXT NOT NULL,
            allow_public_share INTEGER NOT NULL,
            requires_scan INTEGER NOT NULL,
            warn_on_download INTEGER NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_drive_security_policies (
            scope TEXT PRIMARY KEY,
            require_scan_before_download INTEGER NOT NULL,
            block_unclean_downloads INTEGER NOT NULL,
            warn_high_risk_downloads INTEGER NOT NULL,
            allow_inline_preview_for_high_risk INTEGER NOT NULL,
            e2ee_server_scan_claim_allowed INTEGER NOT NULL,
            revoke_shares_on_suspension INTEGER NOT NULL,
            scanner_enabled INTEGER NOT NULL,
            scanner_backend TEXT NOT NULL,
            scanner_command TEXT,
            scanner_timeout_seconds INTEGER NOT NULL,
            fail_closed_on_scanner_error INTEGER NOT NULL,
            quarantine_on_infected INTEGER NOT NULL,
            validate_magic_mime INTEGER NOT NULL,
            deep_archive_scan_enabled INTEGER NOT NULL DEFAULT 1,
            max_archive_depth INTEGER NOT NULL DEFAULT 2,
            office_macro_scan_enabled INTEGER NOT NULL DEFAULT 1,
            image_reencode_enabled INTEGER NOT NULL DEFAULT 1,
            image_reencode_max_pixels INTEGER NOT NULL DEFAULT 25000000,
            yara_enabled INTEGER NOT NULL DEFAULT 0,
            yara_command TEXT,
            yara_rules_path TEXT,
            max_archive_files INTEGER NOT NULL,
            max_archive_uncompressed_bytes INTEGER NOT NULL,
            max_daily_downloads INTEGER NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    _ensure_cloud_drive_policy_columns(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_owner ON uploaded_files(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_risk ON uploaded_files(risk_level, scan_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_encrypted_file_keys_file_recipient ON encrypted_file_keys(file_id, recipient_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_scan_results_file ON file_scan_results(file_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_logs_file ON file_access_logs(file_id, created_at)")
    seed_default_file_type_policies(conn)
    seed_default_cloud_drive_security_policy(conn)


def _table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_cloud_drive_policy_columns(conn):
    columns = _table_columns(conn, "cloud_drive_security_policies")
    definitions = {
        "scanner_enabled": "INTEGER NOT NULL DEFAULT 1",
        "scanner_backend": "TEXT NOT NULL DEFAULT 'clamav'",
        "scanner_command": "TEXT",
        "scanner_timeout_seconds": "INTEGER NOT NULL DEFAULT 60",
        "fail_closed_on_scanner_error": "INTEGER NOT NULL DEFAULT 1",
        "quarantine_on_infected": "INTEGER NOT NULL DEFAULT 1",
        "validate_magic_mime": "INTEGER NOT NULL DEFAULT 1",
        "deep_archive_scan_enabled": "INTEGER NOT NULL DEFAULT 1",
        "max_archive_depth": "INTEGER NOT NULL DEFAULT 2",
        "office_macro_scan_enabled": "INTEGER NOT NULL DEFAULT 1",
        "image_reencode_enabled": "INTEGER NOT NULL DEFAULT 1",
        "image_reencode_max_pixels": "INTEGER NOT NULL DEFAULT 25000000",
        "yara_enabled": "INTEGER NOT NULL DEFAULT 0",
        "yara_command": "TEXT",
        "yara_rules_path": "TEXT",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE cloud_drive_security_policies ADD COLUMN {column} {definition}")


def seed_default_file_type_policies(conn):
    now = datetime.now().isoformat()
    existing = {row["category"] for row in conn.execute("SELECT category FROM file_type_policies").fetchall()}
    for category, policy in DEFAULT_FILE_TYPE_POLICIES.items():
        if category in existing:
            continue
        conn.execute(
            """
            INSERT INTO file_type_policies (
                category, extensions_json, public_allowed, private_scannable_allowed, e2ee_allowed,
                default_risk_level, allow_public_share, requires_scan, warn_on_download,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category,
                json.dumps(policy["extensions"], ensure_ascii=False),
                1 if policy["public_allowed"] else 0,
                1 if policy["private_scannable_allowed"] else 0,
                1 if policy["e2ee_allowed"] else 0,
                policy["default_risk_level"],
                1 if policy["allow_public_share"] else 0,
                1 if policy["requires_scan"] else 0,
                1 if policy["warn_on_download"] else 0,
                policy["notes"],
                now,
                now,
            ),
        )


def seed_default_cloud_drive_security_policy(conn):
    now = datetime.now().isoformat()
    policy = DEFAULT_CLOUD_DRIVE_SECURITY_POLICY
    conn.execute(
        """
        INSERT OR IGNORE INTO cloud_drive_security_policies (
            scope, require_scan_before_download, block_unclean_downloads,
            warn_high_risk_downloads, allow_inline_preview_for_high_risk,
            e2ee_server_scan_claim_allowed, revoke_shares_on_suspension,
            scanner_enabled, scanner_backend, scanner_command,
            scanner_timeout_seconds, fail_closed_on_scanner_error,
            quarantine_on_infected, validate_magic_mime,
            deep_archive_scan_enabled, max_archive_depth,
            office_macro_scan_enabled, image_reencode_enabled, image_reencode_max_pixels,
            yara_enabled, yara_command, yara_rules_path,
            max_archive_files, max_archive_uncompressed_bytes, max_daily_downloads,
            notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy["scope"],
            1 if policy["require_scan_before_download"] else 0,
            1 if policy["block_unclean_downloads"] else 0,
            1 if policy["warn_high_risk_downloads"] else 0,
            1 if policy["allow_inline_preview_for_high_risk"] else 0,
            1 if policy["e2ee_server_scan_claim_allowed"] else 0,
            1 if policy["revoke_shares_on_suspension"] else 0,
            1 if policy["scanner_enabled"] else 0,
            policy["scanner_backend"],
            policy["scanner_command"],
            int(policy["scanner_timeout_seconds"]),
            1 if policy["fail_closed_on_scanner_error"] else 0,
            1 if policy["quarantine_on_infected"] else 0,
            1 if policy["validate_magic_mime"] else 0,
            1 if policy["deep_archive_scan_enabled"] else 0,
            int(policy["max_archive_depth"]),
            1 if policy["office_macro_scan_enabled"] else 0,
            1 if policy["image_reencode_enabled"] else 0,
            int(policy["image_reencode_max_pixels"]),
            1 if policy["yara_enabled"] else 0,
            policy["yara_command"],
            policy["yara_rules_path"],
            int(policy["max_archive_files"]),
            int(policy["max_archive_uncompressed_bytes"]),
            int(policy["max_daily_downloads"]),
            policy["notes"],
            now,
            now,
        ),
    )


def normalize_privacy_mode(value):
    mode = str(value or "").strip()
    if mode not in UPLOAD_PRIVACY_MODES:
        raise ValueError("unsupported upload privacy mode")
    return mode


def normalize_scan_status(value):
    status = str(value or "").strip()
    if status not in SCAN_STATUSES:
        raise ValueError("unsupported scan status")
    return status


def safe_public_filename(filename):
    name = os.path.basename(str(filename or "")).strip()
    name = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in name)
    return name[:160] or "upload.bin"


def file_extension(filename):
    return Path(str(filename or "")).suffix.lower()


def policy_category_for_extension(extension):
    ext = str(extension or "").lower()
    if ext in EXECUTABLE_EXTENSIONS:
        return "executable"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in MACRO_OFFICE_EXTENSIONS:
        return "office_macro"
    if ext in OFFICE_EXTENSIONS:
        return "office"
    return "default"


def get_file_type_policy(conn, category):
    row = conn.execute("SELECT * FROM file_type_policies WHERE category=?", (category,)).fetchone()
    if row:
        return dict(row)
    fallback = DEFAULT_FILE_TYPE_POLICIES["default"]
    now = datetime.now().isoformat()
    return {
        "category": "default",
        "extensions_json": json.dumps(fallback["extensions"], ensure_ascii=False),
        "public_allowed": 1,
        "private_scannable_allowed": 1,
        "e2ee_allowed": 1,
        "default_risk_level": fallback["default_risk_level"],
        "allow_public_share": 1,
        "requires_scan": 1,
        "warn_on_download": 0,
        "notes": fallback["notes"],
        "created_at": now,
        "updated_at": now,
    }


def serialize_cloud_drive_security_policy(row):
    if not row:
        row = DEFAULT_CLOUD_DRIVE_SECURITY_POLICY
        return {
            "scope": row["scope"],
            "require_scan_before_download": bool(row["require_scan_before_download"]),
            "block_unclean_downloads": bool(row["block_unclean_downloads"]),
            "warn_high_risk_downloads": bool(row["warn_high_risk_downloads"]),
            "allow_inline_preview_for_high_risk": bool(row["allow_inline_preview_for_high_risk"]),
            "e2ee_server_scan_claim_allowed": bool(row["e2ee_server_scan_claim_allowed"]),
            "revoke_shares_on_suspension": bool(row["revoke_shares_on_suspension"]),
            "scanner_enabled": bool(row["scanner_enabled"]),
            "scanner_backend": row["scanner_backend"],
            "scanner_command": row["scanner_command"],
            "scanner_timeout_seconds": int(row["scanner_timeout_seconds"]),
            "fail_closed_on_scanner_error": bool(row["fail_closed_on_scanner_error"]),
            "quarantine_on_infected": bool(row["quarantine_on_infected"]),
            "validate_magic_mime": bool(row["validate_magic_mime"]),
            "deep_archive_scan_enabled": bool(row["deep_archive_scan_enabled"]),
            "max_archive_depth": int(row["max_archive_depth"]),
            "office_macro_scan_enabled": bool(row["office_macro_scan_enabled"]),
            "image_reencode_enabled": bool(row["image_reencode_enabled"]),
            "image_reencode_max_pixels": int(row["image_reencode_max_pixels"]),
            "yara_enabled": bool(row["yara_enabled"]),
            "yara_command": row["yara_command"],
            "yara_rules_path": row["yara_rules_path"],
            "max_archive_files": int(row["max_archive_files"]),
            "max_archive_uncompressed_bytes": int(row["max_archive_uncompressed_bytes"]),
            "max_daily_downloads": int(row["max_daily_downloads"]),
            "notes": row["notes"],
        }
    data = dict(row)
    for key in (
        "require_scan_before_download",
        "block_unclean_downloads",
        "warn_high_risk_downloads",
        "allow_inline_preview_for_high_risk",
        "e2ee_server_scan_claim_allowed",
        "revoke_shares_on_suspension",
        "scanner_enabled",
        "fail_closed_on_scanner_error",
        "quarantine_on_infected",
        "validate_magic_mime",
        "deep_archive_scan_enabled",
        "office_macro_scan_enabled",
        "image_reencode_enabled",
        "yara_enabled",
    ):
        data[key] = bool(data.get(key))
    for key in ("scanner_timeout_seconds", "max_archive_depth", "image_reencode_max_pixels", "max_archive_files", "max_archive_uncompressed_bytes", "max_daily_downloads"):
        data[key] = int(data.get(key) or 0)
    data["scanner_backend"] = str(data.get("scanner_backend") or "disabled")
    data["scanner_command"] = str(data.get("scanner_command") or "")
    data["yara_command"] = str(data.get("yara_command") or "")
    data["yara_rules_path"] = str(data.get("yara_rules_path") or "")
    return data


def get_cloud_drive_security_policy(conn, scope="default"):
    ensure_upload_security_schema(conn)
    row = conn.execute(
        "SELECT * FROM cloud_drive_security_policies WHERE scope=?",
        (scope or "default",),
    ).fetchone()
    return serialize_cloud_drive_security_policy(row)


def update_cloud_drive_security_policy(conn, data, scope="default"):
    ensure_upload_security_schema(conn)
    if not isinstance(data, dict):
        return None, "Invalid request"
    updates = []
    params = []
    for key in CLOUD_DRIVE_POLICY_BOOL_FIELDS:
        if key in data:
            updates.append(f"{key}=?")
            params.append(1 if bool(data[key]) else 0)
    for key in CLOUD_DRIVE_POLICY_INT_FIELDS:
        if key in data:
            try:
                value = int(data[key])
            except Exception:
                return None, f"{key} 格式錯誤"
            if value < 0:
                return None, f"{key} 不可小於 0"
            if key == "scanner_timeout_seconds" and value < 1:
                return None, "scanner_timeout_seconds 必須至少 1 秒"
            if key == "max_archive_depth" and value > 5:
                return None, "max_archive_depth 不可大於 5"
            if key == "image_reencode_max_pixels" and value > 100_000_000:
                return None, "image_reencode_max_pixels 不可大於 100000000"
            updates.append(f"{key}=?")
            params.append(value)
    if "scanner_backend" in data:
        value = str(data.get("scanner_backend") or "").strip().lower()
        if value not in ALLOWED_SCANNER_BACKENDS:
            return None, "scanner_backend 僅支援 disabled 或 clamav"
        updates.append("scanner_backend=?")
        params.append(value)
    if "scanner_command" in data:
        updates.append("scanner_command=?")
        params.append(str(data.get("scanner_command") or "").strip()[:500])
    if "yara_command" in data:
        updates.append("yara_command=?")
        params.append(str(data.get("yara_command") or "").strip()[:500])
    if "yara_rules_path" in data:
        updates.append("yara_rules_path=?")
        params.append(str(data.get("yara_rules_path") or "").strip()[:500])
    if "notes" in data:
        updates.append("notes=?")
        params.append(str(data.get("notes") or "")[:1000])
    if not updates:
        return None, "未提供可更新欄位"
    updates.append("updated_at=?")
    params.append(datetime.now().isoformat())
    params.append(scope or "default")
    conn.execute(f"UPDATE cloud_drive_security_policies SET {', '.join(updates)} WHERE scope=?", tuple(params))
    row = conn.execute("SELECT * FROM cloud_drive_security_policies WHERE scope=?", (scope or "default",)).fetchone()
    return serialize_cloud_drive_security_policy(row), None


def _sum_uploaded_file_bytes(conn, owner_user_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS used_bytes, COUNT(*) AS file_count "
        "FROM uploaded_files WHERE owner_user_id=? AND deleted_at IS NULL",
        (int(owner_user_id),),
    ).fetchone()
    return int(row["used_bytes"] or 0), int(row["file_count"] or 0)


def _count_grouped(conn, owner_user_id, field):
    if field not in {"privacy_mode", "risk_level", "scan_status"}:
        raise ValueError("unsupported usage grouping")
    rows = conn.execute(
        f"SELECT {field} AS name, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes "
        "FROM uploaded_files WHERE owner_user_id=? AND deleted_at IS NULL GROUP BY "
        f"{field}",
        (int(owner_user_id),),
    ).fetchall()
    return {row["name"]: {"count": int(row["count"] or 0), "bytes": int(row["bytes"] or 0)} for row in rows}


def get_user_cloud_drive_usage(conn, user, member_rule=None):
    ensure_upload_security_schema(conn)
    data = dict(user or {})
    user_id = int(data.get("id") or 0)
    role = data.get("role") or "user"
    effective_level = data.get("effective_level") or data.get("member_level") or "newbie"
    sanction_status = data.get("sanction_status") or "none"
    rule = member_rule or {}
    quota_mb = int(rule.get("attachment_quota_mb") or 0)
    max_file_size_mb = int(rule.get("max_attachment_size_mb") or 0)
    upload_rate_limit_per_day = int(rule.get("upload_rate_limit_per_day") or 0)
    can_upload = (role == "super_admin" or bool(rule.get("can_upload_attachment"))) and sanction_status not in {"restricted", "suspended"}

    used_bytes, file_count = _sum_uploaded_file_bytes(conn, user_id)
    total_bytes = None if role == "super_admin" else quota_mb * 1024 * 1024
    remaining_bytes = None if total_bytes is None else max(0, total_bytes - used_bytes)
    percent_used = 0.0
    if total_bytes and total_bytes > 0:
        percent_used = min(100.0, round((used_bytes / total_bytes) * 100, 2))
    elif total_bytes == 0 and used_bytes > 0:
        percent_used = 100.0

    return {
        "user_id": user_id,
        "effective_level": effective_level,
        "can_upload": can_upload,
        "quota_source": "super_admin_unlimited" if role == "super_admin" else "member_level_rules.attachment_quota_mb",
        "used_bytes": used_bytes,
        "total_bytes": total_bytes,
        "remaining_bytes": remaining_bytes,
        "percent_used": percent_used,
        "file_count": file_count,
        "max_file_size_bytes": None if role == "super_admin" else max_file_size_mb * 1024 * 1024,
        "upload_rate_limit_per_day": None if role == "super_admin" else upload_rate_limit_per_day,
        "by_privacy_mode": _count_grouped(conn, user_id, "privacy_mode"),
        "by_risk_level": _count_grouped(conn, user_id, "risk_level"),
        "by_scan_status": _count_grouped(conn, user_id, "scan_status"),
    }


def get_cloud_drive_safety_summary(conn, user, member_rule=None):
    policy = get_cloud_drive_security_policy(conn)
    usage = get_user_cloud_drive_usage(conn, user, member_rule=member_rule)
    effective_level = usage["effective_level"]
    restrictions = []
    if not usage["can_upload"]:
        restrictions.append("目前會員等級或處分狀態不可上傳")
    if policy["block_unclean_downloads"]:
        restrictions.append("public/private 檔案需掃描為 clean 才能下載")
    if policy["warn_high_risk_downloads"]:
        restrictions.append("high / unknown_encrypted 下載前必須顯示風險警告")
    if not policy["allow_inline_preview_for_high_risk"]:
        restrictions.append("高風險檔案不提供 inline preview")
    if not policy["e2ee_server_scan_claim_allowed"]:
        restrictions.append("E2EE 檔案不可宣稱已完成伺服器完整掃毒")
    if effective_level in {"restricted", "suspended"}:
        restrictions.append("restricted/suspended 不可新增上傳或分享")

    modes = {
        "public_attachment": "可掃毒、可預覽、站方可處理明文",
        "private_scannable": "可掃毒、掃描後伺服器端加密保存",
        "e2ee_vault": "端到端加密，server/root/admin 不可讀，掃毒能力受限",
        "e2ee_vault_with_client_scan": "端到端加密加本機掃描回報，回報不可完全信任",
    }
    return {
        "policy": policy,
        "usage": usage,
        "modes": modes,
        "restrictions": restrictions,
    }


def _mapping_value(mapping, key, default=None):
    if not mapping:
        return default
    try:
        return mapping[key]
    except Exception:
        return mapping.get(key, default) if hasattr(mapping, "get") else default


def evaluate_upload_policy(conn, *, filename, privacy_mode, user=None, size_bytes=0):
    mode = normalize_privacy_mode(privacy_mode)
    ext = file_extension(filename)
    category = policy_category_for_extension(ext)
    policy = get_file_type_policy(conn, category)
    warnings = []
    reason = "allowed"
    risk_level = policy["default_risk_level"] if policy["default_risk_level"] in RISK_LEVELS else "medium"

    if mode == "public_attachment" and not policy["public_allowed"]:
        return UploadPolicyDecision(False, mode, "blocked", "quarantined", category, "file type is blocked for public uploads", tuple(warnings))
    if mode == "private_scannable" and not policy["private_scannable_allowed"]:
        return UploadPolicyDecision(False, mode, "blocked", "quarantined", category, "file type is blocked for private scannable uploads", tuple(warnings))
    if mode.startswith("e2ee") and not policy["e2ee_allowed"]:
        return UploadPolicyDecision(False, mode, "blocked", "quarantined", category, "file type is blocked for encrypted vault uploads", tuple(warnings))

    effective_level = str(_mapping_value(user, "effective_level") or _mapping_value(user, "member_level") or "newbie")
    if effective_level in {"restricted", "suspended"}:
        return UploadPolicyDecision(False, mode, "blocked", "quarantined", category, f"{effective_level} users cannot upload", tuple(warnings))
    if effective_level == "newbie" and category in {"executable", "archive", "office_macro"}:
        return UploadPolicyDecision(False, mode, "blocked", "quarantined", category, "newbie users cannot upload this high-risk file type", tuple(warnings))

    if mode.startswith("e2ee"):
        risk_level = "unknown_encrypted" if category != "executable" else "high"
        scan_status = "unknown_encrypted" if mode == "e2ee_vault" else "skipped_e2ee"
        warnings.append("server cannot fully scan end-to-end encrypted content")
        if category in {"archive", "office_macro", "executable"}:
            warnings.append("download must show high-risk warning")
        return UploadPolicyDecision(True, mode, risk_level, scan_status, category, reason, tuple(warnings))

    scan_status = "pending" if policy["requires_scan"] else "not_required"
    if category in {"archive", "office_macro", "executable"}:
        warnings.append("requires strict scan before download")
    if size_bytes and int(size_bytes) > 50 * 1024 * 1024:
        risk_level = "medium" if risk_level == "low" else risk_level
        warnings.append("large file requires quota and rate-limit checks")
    return UploadPolicyDecision(True, mode, risk_level, scan_status, category, reason, tuple(warnings))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_zip_archive_safety(path, *, max_files=200, max_uncompressed_bytes=50 * 1024 * 1024, recursive=False, max_depth=2):
    result = {"ok": True, "reason": "ok", "file_count": 0, "uncompressed_bytes": 0, "max_depth_seen": 0}

    def walk_zip(blob, depth):
        with zipfile.ZipFile(blob) as archive:
            infos = archive.infolist()
            for info in infos:
                if info.is_dir():
                    continue
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    return False, "path_traversal"
                result["file_count"] += 1
                result["max_depth_seen"] = max(result["max_depth_seen"], depth)
                if result["file_count"] > max_files:
                    return False, "too_many_files"
                result["uncompressed_bytes"] += int(info.file_size or 0)
                if result["uncompressed_bytes"] > max_uncompressed_bytes:
                    return False, "zip_bomb"
                if recursive and depth < max_depth and file_extension(info.filename) == ".zip":
                    nested = archive.read(info)
                    ok, reason = walk_zip(BytesIO(nested), depth + 1)
                    if not ok:
                        return False, reason
        return True, "ok"

    try:
        ok, reason = walk_zip(path, 0)
        return {**result, "ok": ok, "reason": reason}
    except zipfile.BadZipFile:
        return {**result, "ok": False, "reason": "bad_zip"}


def check_office_macro_safety(path, filename=None):
    ext = file_extension(filename or path)
    result = {"ok": True, "reason": "ok", "extension": ext, "macro_indicators": []}
    if ext not in OFFICE_EXTENSIONS:
        return {**result, "reason": "not_office"}
    if ext in MACRO_OFFICE_EXTENSIONS:
        result["macro_indicators"].append("macro_enabled_extension")
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                names = [name.lower() for name in archive.namelist()]
            for marker in ("vbaproject.bin", "macrosheets/", "xl4macrosheets/"):
                if any(marker in name for name in names):
                    result["macro_indicators"].append(marker.rstrip("/"))
        else:
            with open(path, "rb") as f:
                sample = f.read(1024 * 1024).lower()
            for marker in (b"vba", b"macros", b"attribut vb_"):
                if marker in sample:
                    result["macro_indicators"].append(marker.decode("ascii", errors="ignore"))
    except Exception as exc:
        return {**result, "ok": False, "reason": "office_macro_scan_failed", "error": exc.__class__.__name__}
    if result["macro_indicators"]:
        return {**result, "ok": False, "reason": "macro_detected"}
    return result


def detect_magic_mime(path):
    with open(path, "rb") as f:
        header = f.read(16)
    for signature, mime in MIME_SIGNATURES:
        if header.startswith(signature):
            return mime
    if not header:
        return "application/x-empty"
    if b"\x00" not in header:
        return "text/plain"
    return "application/octet-stream"


def check_magic_mime_safety(path, filename=None, declared_mime=None):
    actual = detect_magic_mime(path)
    ext = file_extension(filename or path)
    expected = EXTENSION_MIME_PREFIXES.get(ext)
    result = {
        "ok": True,
        "reason": "ok",
        "extension": ext,
        "declared_mime": declared_mime or "",
        "detected_mime": actual,
    }
    if actual in HIGH_RISK_MAGIC_MIMES and ext not in EXECUTABLE_EXTENSIONS:
        return {**result, "ok": False, "reason": "executable_magic_mismatch"}
    if expected and actual not in expected and actual != "application/x-empty":
        return {**result, "ok": False, "reason": "extension_mime_mismatch"}
    return result


def reencode_image_strip_metadata(path, *, filename=None, max_pixels=25_000_000):
    ext = file_extension(filename or path)
    if ext not in REENCODABLE_IMAGE_EXTENSIONS:
        return {"ok": True, "result": "not_required", "reason": "not_reencodable_image"}
    try:
        from PIL import Image, ImageOps
    except Exception:
        return {"ok": True, "result": "skipped", "reason": "pillow_not_installed"}

    target = Path(path)
    before_size = target.stat().st_size
    try:
        with Image.open(target) as img:
            frames = getattr(img, "n_frames", 1)
            if frames and frames > 1:
                return {"ok": True, "result": "skipped", "reason": "animated_image"}
            width, height = img.size
            pixels = int(width or 0) * int(height or 0)
            if pixels <= 0:
                return {"ok": False, "result": "failed", "reason": "invalid_dimensions"}
            if pixels > int(max_pixels or 25_000_000):
                return {"ok": True, "result": "skipped", "reason": "image_too_large", "pixels": pixels}

            clean = ImageOps.exif_transpose(img)
            fmt = (img.format or "").upper()
            save_kwargs = {}
            if ext in {".jpg", ".jpeg"}:
                fmt = "JPEG"
                if clean.mode not in {"RGB", "L"}:
                    clean = clean.convert("RGB")
                save_kwargs = {"quality": 92, "optimize": True}
            elif ext == ".png":
                fmt = "PNG"
                save_kwargs = {"optimize": True}
            elif ext == ".gif":
                fmt = "GIF"
            else:
                return {"ok": True, "result": "not_required", "reason": "unsupported_extension"}

            tmp = target.with_suffix(target.suffix + ".reencode.tmp")
            clean.save(tmp, format=fmt, **save_kwargs)
            os.replace(tmp, target)
            after_size = target.stat().st_size
            return {
                "ok": True,
                "result": "clean",
                "reason": "metadata_stripped",
                "format": fmt,
                "pixels": pixels,
                "old_size": before_size,
                "new_size": after_size,
            }
    except Exception as exc:
        try:
            tmp = target.with_suffix(target.suffix + ".reencode.tmp")
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return {"ok": False, "result": "failed", "reason": "image_reencode_failed", "error": exc.__class__.__name__}


def _record_scan_result(conn, *, file_id, scanner_name, result, scanner_version=None, started_at=None, malware_name=None, details=None):
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO file_scan_results (
            id, file_id, scanner_name, scanner_version, scan_started_at,
            scan_completed_at, result, malware_name, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            file_id,
            scanner_name,
            scanner_version,
            started_at or now,
            now,
            result,
            malware_name,
            json.dumps(details or {}, ensure_ascii=False),
            now,
        ),
    )


def _update_file_scan_state(conn, file_id, *, scan_status, risk_level=None):
    fields = ["scan_status=?", "updated_at=?"]
    params = [normalize_scan_status(scan_status), datetime.now().isoformat()]
    if risk_level:
        fields.append("risk_level=?")
        params.append(risk_level)
    params.append(file_id)
    conn.execute(f"UPDATE uploaded_files SET {', '.join(fields)} WHERE id=?", tuple(params))


def _resolve_clamav_command(policy):
    configured = str(policy.get("scanner_command") or "").strip()
    if configured:
        return configured
    return shutil.which("clamdscan") or shutil.which("clamscan")


def _parse_clamav_output(output):
    for line in output.splitlines():
        if " FOUND" in line:
            part = line.rsplit(":", 1)[-1].strip()
            return part.replace(" FOUND", "").strip() or "malware"
    return None


def _resolve_yara_command(policy):
    configured = str(policy.get("yara_command") or "").strip()
    if configured:
        return configured
    return shutil.which("yara")


def run_yara_scan(path, *, policy):
    if not policy.get("yara_enabled"):
        return {"result": "not_required", "malware_name": None, "details": {"reason": "yara_disabled"}}
    rules_path = str(policy.get("yara_rules_path") or "").strip()
    if not rules_path:
        return {"result": "not_required", "malware_name": None, "details": {"reason": "yara_rules_not_configured"}}
    command = _resolve_yara_command(policy)
    if not command:
        return {"result": "not_required", "malware_name": None, "details": {"reason": "yara_command_not_found"}}
    started_at = datetime.now().isoformat()
    timeout = int(policy.get("scanner_timeout_seconds") or 60)
    command_parts = shlex.split(command)
    if not command_parts:
        return {"result": "not_required", "malware_name": None, "scan_started_at": started_at, "details": {"reason": "empty_yara_command"}}
    try:
        completed = subprocess.run(
            [*command_parts, "-r", rules_path, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "result": "failed",
            "malware_name": None,
            "scan_started_at": started_at,
            "details": {"reason": "timeout", "timeout_seconds": timeout, "command": os.path.basename(command_parts[0])},
        }
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    details = {
        "returncode": completed.returncode,
        "command": os.path.basename(command_parts[0]),
        "rules_path": rules_path,
        "output_tail": output[-1000:],
    }
    if completed.returncode not in {0, 1} and not output:
        return {"result": "failed", "malware_name": None, "scan_started_at": started_at, "details": details}
    if completed.stdout.strip():
        rule_name = completed.stdout.strip().split()[0]
        return {"result": "infected", "malware_name": rule_name, "scan_started_at": started_at, "details": details}
    if completed.returncode not in {0, 1}:
        return {"result": "failed", "malware_name": None, "scan_started_at": started_at, "details": details}
    return {"result": "clean", "malware_name": None, "scan_started_at": started_at, "details": details}


def run_clamav_scan(path, *, policy):
    command = _resolve_clamav_command(policy)
    if not command:
        return {
            "result": "not_required",
            "malware_name": None,
            "details": {"reason": "clamav_command_not_found"},
        }
    started_at = datetime.now().isoformat()
    timeout = int(policy.get("scanner_timeout_seconds") or 60)
    command_parts = shlex.split(command)
    if not command_parts:
        return {
            "result": "failed",
            "malware_name": None,
            "scan_started_at": started_at,
            "details": {"reason": "empty_clamav_command"},
        }
    try:
        completed = subprocess.run(
            [*command_parts, "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "result": "failed",
            "malware_name": None,
            "scan_started_at": started_at,
            "details": {"reason": "timeout", "timeout_seconds": timeout, "command": os.path.basename(command_parts[0])},
        }
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    details = {
        "returncode": completed.returncode,
        "command": os.path.basename(command_parts[0]),
        "output_tail": output[-1000:],
    }
    if completed.returncode == 0:
        return {"result": "clean", "malware_name": None, "scan_started_at": started_at, "details": details}
    if completed.returncode == 1:
        return {"result": "infected", "malware_name": _parse_clamav_output(output), "scan_started_at": started_at, "details": details}
    return {"result": "failed", "malware_name": None, "scan_started_at": started_at, "details": details}


def scan_archive_members(path, *, policy):
    if not policy.get("deep_archive_scan_enabled"):
        return {"ok": True, "reason": "disabled", "files_scanned": 0, "results": []}
    if not zipfile.is_zipfile(path):
        return {"ok": True, "reason": "not_zip", "files_scanned": 0, "results": []}

    max_files = int(policy.get("max_archive_files") or 200)
    max_bytes = int(policy.get("max_archive_uncompressed_bytes") or 50 * 1024 * 1024)
    max_depth = int(policy.get("max_archive_depth") or 2)
    state = {"files": 0, "bytes": 0, "results": []}

    def scan_one_file(file_path, member_name):
        magic = check_magic_mime_safety(file_path, filename=member_name)
        state["results"].append({"scanner": "archive-member-magic", "member": member_name, **magic})
        if not magic["ok"]:
            return False, "member_magic_mismatch"
        yara = run_yara_scan(file_path, policy=policy)
        if yara["result"] not in {"not_required"}:
            state["results"].append({"scanner": "archive-member-yara", "member": member_name, **yara})
        if yara["result"] == "infected":
            return False, "member_yara_match"
        if yara["result"] == "failed" and policy.get("fail_closed_on_scanner_error"):
            return False, "member_yara_failed"
        if policy.get("scanner_enabled") and policy.get("scanner_backend") == "clamav":
            clamav = run_clamav_scan(file_path, policy=policy)
            if clamav["result"] not in {"not_required"}:
                state["results"].append({"scanner": "archive-member-clamav", "member": member_name, **clamav})
            if clamav["result"] == "infected":
                return False, "member_clamav_infected"
            if clamav["result"] == "failed" and policy.get("fail_closed_on_scanner_error"):
                return False, "member_clamav_failed"
        return True, "ok"

    def walk_zip(zip_blob, depth, base, temp_root):
        with zipfile.ZipFile(zip_blob) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    return False, "path_traversal"
                state["files"] += 1
                state["bytes"] += int(info.file_size or 0)
                if state["files"] > max_files:
                    return False, "too_many_files"
                if state["bytes"] > max_bytes:
                    return False, "zip_bomb"
                member_name = f"{base}{info.filename}"
                data = archive.read(info)
                if depth < max_depth and file_extension(info.filename) == ".zip":
                    ok, reason = walk_zip(BytesIO(data), depth + 1, f"{member_name}!", temp_root)
                    if not ok:
                        return False, reason
                    continue
                safe_name = uuid.uuid4().hex
                target = Path(temp_root) / safe_name
                target.write_bytes(data)
                ok, reason = scan_one_file(target, member_name)
                if not ok:
                    return False, reason
        return True, "ok"

    try:
        with tempfile.TemporaryDirectory(prefix="upload-scan-") as temp_root:
            ok, reason = walk_zip(path, 0, "", temp_root)
        return {"ok": ok, "reason": reason, "files_scanned": state["files"], "uncompressed_bytes": state["bytes"], "results": state["results"]}
    except zipfile.BadZipFile:
        return {"ok": False, "reason": "bad_zip", "files_scanned": state["files"], "results": state["results"]}
    except Exception as exc:
        return {"ok": False, "reason": "archive_member_scan_failed", "error": exc.__class__.__name__, "files_scanned": state["files"], "results": state["results"]}


def scan_uploaded_file(conn, *, file_id, file_path, filename=None, declared_mime=None):
    ensure_upload_security_schema(conn)
    row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
    if not row:
        raise ValueError("uploaded file not found")
    policy = get_cloud_drive_security_policy(conn)
    privacy_mode = row["privacy_mode"]
    if privacy_mode.startswith("e2ee"):
        _record_scan_result(
            conn,
            file_id=file_id,
            scanner_name="server-policy",
            result=row["scan_status"],
            details={"reason": "e2ee_content_not_server_scannable"},
        )
        return {"scan_status": row["scan_status"], "risk_level": row["risk_level"], "results": []}

    path = Path(file_path)
    results = []
    if not path.exists() or not path.is_file():
        _record_scan_result(conn, file_id=file_id, scanner_name="file-presence", result="failed", details={"reason": "missing_file"})
        _update_file_scan_state(conn, file_id, scan_status="failed", risk_level="high" if policy["fail_closed_on_scanner_error"] else None)
        return {"scan_status": "failed", "risk_level": "high" if policy["fail_closed_on_scanner_error"] else row["risk_level"], "results": results}

    if policy["validate_magic_mime"]:
        magic_result = check_magic_mime_safety(path, filename=filename or row["original_filename_plain_for_public"], declared_mime=declared_mime or row["mime_type_plain_for_public"])
        result_name = "clean" if magic_result["ok"] else "infected"
        _record_scan_result(conn, file_id=file_id, scanner_name="magic-mime", result=result_name, details=magic_result)
        results.append({"scanner": "magic-mime", **magic_result})
        if not magic_result["ok"]:
            status = "quarantined" if policy["quarantine_on_infected"] else "infected"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}

    if policy.get("image_reencode_enabled"):
        image_result = reencode_image_strip_metadata(
            path,
            filename=filename or row["original_filename_plain_for_public"],
            max_pixels=policy.get("image_reencode_max_pixels") or 25_000_000,
        )
        scan_result_name = "clean" if image_result.get("ok") else "failed"
        if image_result.get("result") in {"skipped", "not_required"}:
            scan_result_name = "not_required"
        _record_scan_result(conn, file_id=file_id, scanner_name="image-reencode", result=scan_result_name, details=image_result)
        results.append({"scanner": "image-reencode", **image_result})
        if image_result.get("result") == "clean":
            conn.execute(
                "UPDATE uploaded_files SET size_bytes=?, plaintext_sha256=?, updated_at=? WHERE id=?",
                (int(image_result.get("new_size") or path.stat().st_size), sha256_file(path), datetime.now().isoformat(), file_id),
            )

    if policy.get("office_macro_scan_enabled") and file_extension(filename or row["original_filename_plain_for_public"] or path) in OFFICE_EXTENSIONS:
        office_result = check_office_macro_safety(path, filename=filename or row["original_filename_plain_for_public"])
        result_name = "clean" if office_result["ok"] else "infected"
        _record_scan_result(conn, file_id=file_id, scanner_name="office-macro", result=result_name, details=office_result)
        results.append({"scanner": "office-macro", **office_result})
        if not office_result["ok"]:
            status = "quarantined" if policy["quarantine_on_infected"] else "infected"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}

    if file_extension(filename or row["original_filename_plain_for_public"] or path) in ARCHIVE_EXTENSIONS:
        archive_result = check_zip_archive_safety(
            path,
            max_files=policy["max_archive_files"],
            max_uncompressed_bytes=policy["max_archive_uncompressed_bytes"],
            recursive=policy.get("deep_archive_scan_enabled"),
            max_depth=policy.get("max_archive_depth"),
        )
        result_name = "clean" if archive_result["ok"] else "infected"
        _record_scan_result(conn, file_id=file_id, scanner_name="archive-safety", result=result_name, details=archive_result)
        results.append({"scanner": "archive-safety", **archive_result})
        if not archive_result["ok"]:
            status = "quarantined" if policy["quarantine_on_infected"] else "infected"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}
        archive_member_result = scan_archive_members(path, policy=policy)
        member_result_name = "clean" if archive_member_result["ok"] else "infected"
        _record_scan_result(conn, file_id=file_id, scanner_name="archive-member-scan", result=member_result_name, details=archive_member_result)
        results.append({"scanner": "archive-member-scan", **archive_member_result})
        if not archive_member_result["ok"]:
            status = "quarantined" if policy["quarantine_on_infected"] else "infected"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}

    yara = run_yara_scan(path, policy=policy)
    if yara["result"] != "not_required":
        _record_scan_result(
            conn,
            file_id=file_id,
            scanner_name="yara",
            started_at=yara.get("scan_started_at"),
            result=yara["result"],
            malware_name=yara.get("malware_name"),
            details=yara.get("details") or {},
        )
        results.append({"scanner": "yara", **yara})
        if yara["result"] == "infected":
            status = "quarantined" if policy["quarantine_on_infected"] else "infected"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}
        if yara["result"] == "failed" and policy["fail_closed_on_scanner_error"]:
            status = "quarantined"
            _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
            return {"scan_status": status, "risk_level": "high", "results": results}

    if not policy["scanner_enabled"] or policy["scanner_backend"] == "disabled":
        _record_scan_result(conn, file_id=file_id, scanner_name="server-policy", result="not_required", details={"reason": "scanner_disabled"})
        _update_file_scan_state(conn, file_id, scan_status="not_required")
        return {"scan_status": "not_required", "risk_level": row["risk_level"], "results": results}

    if policy["scanner_backend"] != "clamav":
        _record_scan_result(conn, file_id=file_id, scanner_name="server-policy", result="failed", details={"reason": "unsupported_scanner_backend", "backend": policy["scanner_backend"]})
        _update_file_scan_state(conn, file_id, scan_status="failed", risk_level="high" if policy["fail_closed_on_scanner_error"] else None)
        return {"scan_status": "failed", "risk_level": "high" if policy["fail_closed_on_scanner_error"] else row["risk_level"], "results": results}

    _update_file_scan_state(conn, file_id, scan_status="scanning")
    clamav = run_clamav_scan(path, policy=policy)
    _record_scan_result(
        conn,
        file_id=file_id,
        scanner_name="clamav",
        scanner_version=None,
        started_at=clamav.get("scan_started_at"),
        result=clamav["result"],
        malware_name=clamav.get("malware_name"),
        details=clamav.get("details") or {},
    )
    results.append({"scanner": "clamav", **clamav})
    if clamav["result"] == "clean":
        _update_file_scan_state(conn, file_id, scan_status="clean")
        return {"scan_status": "clean", "risk_level": row["risk_level"], "results": results}
    if clamav["result"] == "infected":
        status = "quarantined" if policy["quarantine_on_infected"] else "infected"
        _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high")
        return {"scan_status": status, "risk_level": "high", "results": results}
    if clamav["result"] == "not_required":
        _update_file_scan_state(conn, file_id, scan_status="not_required")
        return {"scan_status": "not_required", "risk_level": row["risk_level"], "results": results}

    status = "quarantined" if policy["fail_closed_on_scanner_error"] else "failed"
    _update_file_scan_state(conn, file_id, scan_status=status, risk_level="high" if policy["fail_closed_on_scanner_error"] else None)
    return {"scan_status": status, "risk_level": "high" if policy["fail_closed_on_scanner_error"] else row["risk_level"], "results": results}


def create_uploaded_file_record(
    conn,
    *,
    owner_user_id,
    storage_path,
    privacy_mode,
    size_bytes,
    original_filename=None,
    encrypted_metadata=None,
    encrypted_file_key=None,
    wrapped_by="user_public_key",
    mime_type=None,
    ciphertext_sha256=None,
    plaintext_sha256=None,
    encryption_algorithm=None,
    encryption_version=None,
    nonce=None,
    client_scan_report=None,
    user=None,
    scan_now=False,
):
    decision = evaluate_upload_policy(
        conn,
        filename=original_filename,
        privacy_mode=privacy_mode,
        user=user,
        size_bytes=size_bytes,
    )
    file_id = uuid.uuid4().hex
    now = datetime.now().isoformat()
    is_e2ee = decision.privacy_mode.startswith("e2ee")
    if is_e2ee and not encrypted_file_key:
        raise ValueError("encrypted_file_key is required for e2ee uploads")
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            original_filename_encrypted, original_filename_plain_for_public,
            mime_type_encrypted, mime_type_plain_for_public, size_bytes,
            ciphertext_sha256, plaintext_sha256, encryption_algorithm, encryption_version,
            nonce, client_scan_report_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            int(owner_user_id),
            str(storage_path),
            decision.privacy_mode,
            decision.risk_level,
            decision.scan_status,
            encrypted_metadata if is_e2ee else None,
            None if is_e2ee else safe_public_filename(original_filename),
            encrypted_metadata if is_e2ee else None,
            None if is_e2ee else (mime_type or None),
            int(size_bytes or 0),
            ciphertext_sha256,
            plaintext_sha256 if not is_e2ee else None,
            encryption_algorithm,
            encryption_version,
            nonce,
            json.dumps(client_scan_report, ensure_ascii=False) if isinstance(client_scan_report, dict) else None,
            now,
            now,
        ),
    )
    if is_e2ee:
        conn.execute(
            """
            INSERT INTO encrypted_file_keys (
                id, file_id, recipient_user_id, encrypted_file_key, wrapped_by, key_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, file_id, int(owner_user_id), encrypted_file_key, wrapped_by, 1, now),
        )
    result = {"file_id": file_id, **decision.as_dict()}
    if scan_now and decision.allowed and decision.scan_status == "pending":
        scan_result = scan_uploaded_file(
            conn,
            file_id=file_id,
            file_path=storage_path,
            filename=original_filename,
            declared_mime=mime_type,
        )
        result["scan_status"] = scan_result["scan_status"]
        result["risk_level"] = scan_result["risk_level"]
        result["scan_result"] = scan_result
    return result


def log_file_access(conn, *, file_id, actor_user_id, action, result, ip=None, user_agent=None, reason=None):
    conn.execute(
        """
        INSERT INTO file_access_logs (
            id, file_id, actor_user_id, action, ip, user_agent, result, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            file_id,
            actor_user_id,
            str(action),
            ip,
            (user_agent or "")[:200] if user_agent else None,
            str(result),
            reason,
            datetime.now().isoformat(),
        ),
    )
