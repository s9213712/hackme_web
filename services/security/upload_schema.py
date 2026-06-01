import json
import threading
from dataclasses import dataclass
from datetime import datetime

from services.core.sqlite_safe import table_columns as safe_table_columns


UPLOAD_PRIVACY_MODES = {
    "standard_plain",
    "server_encrypted",
    "e2ee",
}
RISK_LEVELS = {"low", "medium", "high", "blocked", "unknown_encrypted"}
ADMIN_DISK_QUOTA_RATIO = 0.9
ADMIN_DISK_WARNING_RATIO = 0.8
MANAGER_CLOUD_DRIVE_QUOTA_BYTES = 1024 * 1024 * 1024
SUPERWEAK_CLOUD_DRIVE_QUOTA_BYTES = 10 * 1024 * 1024
_UPLOAD_SCHEMA_LOCK = threading.Lock()
_UPLOAD_SCHEMA_READY_PATHS = set()
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
        "server_readable_allowed": False,
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
        "server_readable_allowed": True,
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
        "server_readable_allowed": True,
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
        "server_readable_allowed": True,
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
        "server_readable_allowed": True,
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
ALLOWED_CLAMAV_COMMANDS = {"clamdscan", "clamscan"}
ALLOWED_YARA_COMMANDS = {"yara"}

SAFE_PUBLIC_MIME_TYPES = {
    "application/octet-stream",
    "application/ogg",
    "application/pdf",
    "application/zip",
    "audio/aac",
    "audio/aiff",
    "audio/flac",
    "audio/m4a",
    "audio/midi",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/webm",
    "audio/x-aiff",
    "audio/x-m4a",
    "audio/x-midi",
    "audio/x-wav",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/plain",
}

UNSAFE_PUBLIC_MIME_TYPES = {
    "application/javascript",
    "application/json",
    "application/xhtml+xml",
    "application/xml",
    "image/svg+xml",
    "text/css",
    "text/html",
    "text/javascript",
    "text/xml",
}

MIME_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"\x1f\x8b", "application/gzip"),
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
    ".gz": ("application/gzip", "application/x-gzip"),
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
    db_path = _connection_path(conn)
    if db_path and db_path in _UPLOAD_SCHEMA_READY_PATHS:
        return
    with _UPLOAD_SCHEMA_LOCK:
        if db_path and db_path in _UPLOAD_SCHEMA_READY_PATHS:
            return
        was_valid = _upload_schema_cache_valid(conn) if db_path else False
        if db_path and was_valid and not getattr(conn, "in_transaction", False):
            _UPLOAD_SCHEMA_READY_PATHS.add(db_path)
            return
        _ensure_upload_security_schema_uncached(conn)


def _upload_schema_cache_valid(conn):
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cloud_drive_security_policies'"
        ).fetchone()
        if not table:
            return False
        row = conn.execute(
            "SELECT 1 FROM cloud_drive_security_policies WHERE scope='default'"
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _connection_path(conn):
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return str(row["file"] if hasattr(row, "keys") else row[2])
    except Exception:
        return ""


def _ensure_upload_security_schema_uncached(conn):
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
            system_asset_type TEXT,
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
            server_readable_allowed INTEGER NOT NULL,
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
    _ensure_uploaded_files_columns(conn)
    _ensure_encrypted_file_keys_columns(conn)
    _ensure_file_scan_results_columns(conn)
    _ensure_file_access_logs_columns(conn)
    _ensure_file_type_policy_columns(conn)
    _ensure_cloud_drive_policy_columns(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_owner ON uploaded_files(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_risk ON uploaded_files(risk_level, scan_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_system_asset ON uploaded_files(system_asset_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_encrypted_file_keys_file_recipient ON encrypted_file_keys(file_id, recipient_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_scan_results_file ON file_scan_results(file_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_logs_file ON file_access_logs(file_id, created_at)")
    seed_default_file_type_policies(conn)
    seed_default_cloud_drive_security_policy(conn)


def _table_columns(conn, table):
    return safe_table_columns(conn, table)


def _ensure_uploaded_files_columns(conn):
    columns = _table_columns(conn, "uploaded_files")
    definitions = {
        "owner_user_id": "INTEGER NOT NULL DEFAULT 0",
        "storage_path": "TEXT NOT NULL DEFAULT ''",
        "privacy_mode": "TEXT NOT NULL DEFAULT 'standard_plain'",
        "risk_level": "TEXT NOT NULL DEFAULT 'medium'",
        "scan_status": "TEXT NOT NULL DEFAULT 'pending'",
        "original_filename_encrypted": "TEXT",
        "original_filename_plain_for_public": "TEXT",
        "mime_type_encrypted": "TEXT",
        "mime_type_plain_for_public": "TEXT",
        "size_bytes": "INTEGER NOT NULL DEFAULT 0",
        "ciphertext_sha256": "TEXT",
        "plaintext_sha256": "TEXT",
        "encryption_algorithm": "TEXT",
        "encryption_version": "TEXT",
        "nonce": "TEXT",
        "client_scan_report_json": "TEXT",
        "system_asset_type": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
        "updated_at": "TEXT",
        "deleted_at": "TEXT",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE uploaded_files ADD COLUMN {column} {definition}")
    _mark_existing_avatar_files(conn)


def _table_exists(conn, table):
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table or ""),),
        ).fetchone())
    except Exception:
        return False


def _mark_existing_avatar_files(conn):
    try:
        if _table_exists(conn, "users") and "avatar_file_id" in _table_columns(conn, "users"):
            conn.execute(
                """
                UPDATE uploaded_files
                SET system_asset_type='avatar'
                WHERE COALESCE(system_asset_type, '')=''
                  AND id IN (
                      SELECT avatar_file_id
                      FROM users
                      WHERE avatar_file_id IS NOT NULL AND avatar_file_id<>''
                  )
                """
            )
        if _table_exists(conn, "cloud_file_refs"):
            conn.execute(
                """
                UPDATE uploaded_files
                SET system_asset_type='avatar'
                WHERE COALESCE(system_asset_type, '')=''
                  AND id IN (
                      SELECT file_id
                      FROM cloud_file_refs
                      WHERE context_type='avatar'
                  )
                """
            )
    except Exception:
        pass


def _ensure_encrypted_file_keys_columns(conn):
    columns = _table_columns(conn, "encrypted_file_keys")
    definitions = {
        "file_id": "TEXT NOT NULL DEFAULT ''",
        "recipient_user_id": "INTEGER NOT NULL DEFAULT 0",
        "encrypted_file_key": "TEXT NOT NULL DEFAULT ''",
        "wrapped_by": "TEXT NOT NULL DEFAULT 'user_public_key'",
        "key_version": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
        "revoked_at": "TEXT",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE encrypted_file_keys ADD COLUMN {column} {definition}")


def _ensure_file_scan_results_columns(conn):
    columns = _table_columns(conn, "file_scan_results")
    definitions = {
        "file_id": "TEXT NOT NULL DEFAULT ''",
        "scanner_name": "TEXT NOT NULL DEFAULT 'unknown'",
        "scanner_version": "TEXT",
        "scan_started_at": "TEXT",
        "scan_completed_at": "TEXT",
        "result": "TEXT NOT NULL DEFAULT 'unknown'",
        "malware_name": "TEXT",
        "details_json": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE file_scan_results ADD COLUMN {column} {definition}")


def _ensure_file_type_policy_columns(conn):
    columns = _table_columns(conn, "file_type_policies")
    definitions = {
        "extensions_json": "TEXT NOT NULL DEFAULT '[]'",
        "public_allowed": "INTEGER NOT NULL DEFAULT 1",
        "server_readable_allowed": "INTEGER NOT NULL DEFAULT 1",
        "e2ee_allowed": "INTEGER NOT NULL DEFAULT 1",
        "default_risk_level": "TEXT NOT NULL DEFAULT 'medium'",
        "allow_public_share": "INTEGER NOT NULL DEFAULT 1",
        "requires_scan": "INTEGER NOT NULL DEFAULT 1",
        "warn_on_download": "INTEGER NOT NULL DEFAULT 0",
        "notes": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
        "updated_at": "TEXT",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE file_type_policies ADD COLUMN {column} {definition}")
    columns = _table_columns(conn, "file_type_policies")
    if "private_scannable_allowed" in columns:
        conn.execute(
            """
            UPDATE file_type_policies
            SET server_readable_allowed=COALESCE(private_scannable_allowed, server_readable_allowed, 1),
                updated_at=COALESCE(updated_at, ?)
            """,
            (datetime.now().isoformat(),),
        )


def _ensure_file_access_logs_columns(conn):
    columns = _table_columns(conn, "file_access_logs")
    definitions = {
        "file_id": "TEXT NOT NULL DEFAULT ''",
        "actor_user_id": "INTEGER",
        "action": "TEXT NOT NULL DEFAULT 'unknown'",
        "ip": "TEXT",
        "user_agent": "TEXT",
        "result": "TEXT NOT NULL DEFAULT 'unknown'",
        "reason": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT '1970-01-01T00:00:00'",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE file_access_logs ADD COLUMN {column} {definition}")


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
    columns = _table_columns(conn, "file_type_policies")
    for category, policy in DEFAULT_FILE_TYPE_POLICIES.items():
        if category in existing:
            continue
        legacy_columns = ""
        legacy_placeholders = ""
        legacy_values = ()
        if "private_scannable_allowed" in columns:
            legacy_columns = ", private_scannable_allowed"
            legacy_placeholders = ", ?"
            legacy_values = (1 if policy["server_readable_allowed"] else 0,)
        conn.execute(
            f"""
            INSERT INTO file_type_policies (
                category, extensions_json, public_allowed, server_readable_allowed, e2ee_allowed,
                default_risk_level, allow_public_share, requires_scan, warn_on_download,
                notes, created_at, updated_at{legacy_columns}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{legacy_placeholders})
            """,
            (
                category,
                json.dumps(policy["extensions"], ensure_ascii=False),
                1 if policy["public_allowed"] else 0,
                1 if policy["server_readable_allowed"] else 0,
                1 if policy["e2ee_allowed"] else 0,
                policy["default_risk_level"],
                1 if policy["allow_public_share"] else 0,
                1 if policy["requires_scan"] else 0,
                1 if policy["warn_on_download"] else 0,
                policy["notes"],
                now,
                now,
                *legacy_values,
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
