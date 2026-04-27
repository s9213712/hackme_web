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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_owner ON uploaded_files(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uploaded_files_risk ON uploaded_files(risk_level, scan_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_encrypted_file_keys_file_recipient ON encrypted_file_keys(file_id, recipient_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_scan_results_file ON file_scan_results(file_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_logs_file ON file_access_logs(file_id, created_at)")
    seed_default_file_type_policies(conn)


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
