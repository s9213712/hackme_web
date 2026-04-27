import sqlite3
import zipfile

import pytest

from services.upload_security import (
    check_zip_archive_safety,
    create_uploaded_file_record,
    ensure_upload_security_schema,
    evaluate_upload_policy,
    safe_public_filename,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice'), (2, 'bob')")
    ensure_upload_security_schema(conn)
    return conn


def test_upload_security_schema_seeds_file_type_policies():
    conn = _conn()
    try:
        rows = conn.execute("SELECT category, default_risk_level FROM file_type_policies").fetchall()
        policies = {row["category"]: row["default_risk_level"] for row in rows}
        assert policies["executable"] == "high"
        assert policies["archive"] == "medium"
        assert policies["default"] == "low"
    finally:
        conn.close()


def test_executable_public_upload_is_blocked():
    conn = _conn()
    try:
        decision = evaluate_upload_policy(
            conn,
            filename="tool.exe",
            privacy_mode="public_attachment",
            user={"effective_level": "vip"},
        )
        assert decision.allowed is False
        assert decision.risk_level == "blocked"
        assert decision.scan_status == "quarantined"
    finally:
        conn.close()


def test_newbie_cannot_upload_archive_even_when_archive_policy_allows_others():
    conn = _conn()
    try:
        decision = evaluate_upload_policy(
            conn,
            filename="backup.zip",
            privacy_mode="public_attachment",
            user={"effective_level": "newbie"},
        )
        assert decision.allowed is False
        assert "newbie" in decision.reason
    finally:
        conn.close()


def test_e2ee_record_does_not_store_plaintext_filename_or_file_key():
    conn = _conn()
    try:
        result = create_uploaded_file_record(
            conn,
            owner_user_id=1,
            storage_path="storage/e2ee/blob.bin",
            privacy_mode="e2ee_vault",
            size_bytes=12,
            original_filename="secret-tax.pdf",
            encrypted_metadata="sealed:metadata",
            encrypted_file_key="sealed:file-key",
            ciphertext_sha256="c" * 64,
            user={"effective_level": "vip"},
        )
        row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (result["file_id"],)).fetchone()
        key_row = conn.execute("SELECT * FROM encrypted_file_keys WHERE file_id=?", (result["file_id"],)).fetchone()
        assert row["risk_level"] == "unknown_encrypted"
        assert row["scan_status"] == "unknown_encrypted"
        assert row["original_filename_plain_for_public"] is None
        assert row["plaintext_sha256"] is None
        assert key_row["encrypted_file_key"] == "sealed:file-key"
        assert "secret-tax.pdf" not in str(dict(row))
    finally:
        conn.close()


def test_e2ee_upload_requires_encrypted_file_key():
    conn = _conn()
    try:
        with pytest.raises(ValueError):
            create_uploaded_file_record(
                conn,
                owner_user_id=1,
                storage_path="storage/e2ee/blob.bin",
                privacy_mode="e2ee_vault",
                size_bytes=12,
                encrypted_metadata="sealed:metadata",
                user={"effective_level": "vip"},
            )
    finally:
        conn.close()


def test_zip_archive_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")

    result = check_zip_archive_safety(archive)
    assert result["ok"] is False
    assert result["reason"] == "path_traversal"


def test_safe_public_filename_strips_paths_and_control_chars():
    assert safe_public_filename("../../a/bad<script>.png") == "bad_script_.png"
