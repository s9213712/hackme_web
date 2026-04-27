import hashlib
import json
import os
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
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
}
CLOUD_DRIVE_POLICY_INT_FIELDS = {
    "max_archive_files",
    "max_archive_uncompressed_bytes",
    "max_daily_downloads",
}
CLOUD_DRIVE_POLICY_TEXT_FIELDS = {"notes"}


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
            max_archive_files INTEGER NOT NULL,
            max_archive_uncompressed_bytes INTEGER NOT NULL,
            max_daily_downloads INTEGER NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_owner ON uploaded_files(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_risk ON uploaded_files(risk_level, scan_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_encrypted_file_keys_file_recipient ON encrypted_file_keys(file_id, recipient_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_scan_results_file ON file_scan_results(file_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_logs_file ON file_access_logs(file_id, created_at)")
    seed_default_file_type_policies(conn)
    seed_default_cloud_drive_security_policy(conn)


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
            max_archive_files, max_archive_uncompressed_bytes, max_daily_downloads,
            notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy["scope"],
            1 if policy["require_scan_before_download"] else 0,
            1 if policy["block_unclean_downloads"] else 0,
            1 if policy["warn_high_risk_downloads"] else 0,
            1 if policy["allow_inline_preview_for_high_risk"] else 0,
            1 if policy["e2ee_server_scan_claim_allowed"] else 0,
            1 if policy["revoke_shares_on_suspension"] else 0,
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
    ):
        data[key] = bool(data.get(key))
    for key in ("max_archive_files", "max_archive_uncompressed_bytes", "max_daily_downloads"):
        data[key] = int(data.get(key) or 0)
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
            updates.append(f"{key}=?")
            params.append(value)
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
    can_upload = bool(rule.get("can_upload_attachment")) and sanction_status not in {"restricted", "suspended"}

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

    effective_level = str((user or {}).get("effective_level") or (user or {}).get("member_level") or "newbie")
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


def check_zip_archive_safety(path, *, max_files=200, max_uncompressed_bytes=50 * 1024 * 1024):
    result = {"ok": True, "reason": "ok", "file_count": 0, "uncompressed_bytes": 0}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            result["file_count"] = len(infos)
            if len(infos) > max_files:
                return {**result, "ok": False, "reason": "too_many_files"}
            total = 0
            for info in infos:
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    return {**result, "ok": False, "reason": "path_traversal"}
                total += int(info.file_size or 0)
                if total > max_uncompressed_bytes:
                    return {**result, "ok": False, "reason": "zip_bomb"}
            result["uncompressed_bytes"] = total
            return result
    except zipfile.BadZipFile:
        return {**result, "ok": False, "reason": "bad_zip"}


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
    return {"file_id": file_id, **decision.as_dict()}


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
