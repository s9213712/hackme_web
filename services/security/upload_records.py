import json
import uuid
from datetime import datetime

from services.security.upload_policy import (
    evaluate_upload_policy,
    is_e2ee_privacy_mode,
    safe_public_filename,
    safe_public_mime_type,
)
from services.security.upload_scanning import scan_uploaded_file


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
    system_asset_type=None,
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
    is_e2ee = is_e2ee_privacy_mode(decision.privacy_mode)
    if is_e2ee and not encrypted_file_key:
        raise ValueError("encrypted_file_key is required for e2ee uploads")
    asset_type = str(system_asset_type or "").strip().lower()[:40] or None
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            original_filename_encrypted, original_filename_plain_for_public,
            mime_type_encrypted, mime_type_plain_for_public, size_bytes,
            ciphertext_sha256, plaintext_sha256, encryption_algorithm, encryption_version,
            nonce, client_scan_report_json, system_asset_type, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            int(owner_user_id),
            str(storage_path),
            decision.privacy_mode,
            decision.risk_level,
            decision.scan_status,
            encrypted_metadata if is_e2ee else None,
            safe_public_filename(original_filename),
            encrypted_metadata if is_e2ee else None,
            None if is_e2ee else safe_public_mime_type(original_filename, mime_type),
            int(size_bytes or 0),
            ciphertext_sha256,
            plaintext_sha256 if not is_e2ee else None,
            encryption_algorithm,
            encryption_version,
            nonce,
            json.dumps(client_scan_report, ensure_ascii=False) if isinstance(client_scan_report, dict) else None,
            asset_type,
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
    result = {"file_id": file_id, **decision.as_dict(), "system_asset_type": asset_type or ""}
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
