from __future__ import annotations

import hashlib
import json
import sqlite3

from cryptography.fernet import Fernet

from scripts.admin import decrypt_server_files


def _create_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            original_filename_plain_for_public TEXT,
            ciphertext_sha256 TEXT,
            plaintext_sha256 TEXT,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    return conn


def _insert_file(
    conn,
    *,
    file_id,
    owner_user_id,
    storage_path,
    privacy_mode,
    plaintext,
    stored_payload,
    filename=None,
):
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, size_bytes,
            original_filename_plain_for_public, ciphertext_sha256, plaintext_sha256,
            created_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            file_id,
            owner_user_id,
            storage_path,
            privacy_mode,
            len(plaintext),
            filename,
            hashlib.sha256(stored_payload).hexdigest(),
            None,
            "2026-05-14T00:00:00",
        ),
    )


def test_decrypt_server_files_writes_plaintext_and_manifest(tmp_path):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    storage_path = "users/1/file-a/blob.bin"
    source_path = storage_root / storage_path
    source_path.parent.mkdir(parents=True)
    key = Fernet.generate_key()
    fernet = Fernet(key)
    plaintext = b"server-side backup plaintext"
    ciphertext = fernet.encrypt(plaintext)
    source_path.write_bytes(ciphertext)
    conn = _create_db(db_path)
    try:
        _insert_file(
            conn,
            file_id="file-a",
            owner_user_id=1,
            storage_path=storage_path,
            privacy_mode="server_encrypted",
            plaintext=plaintext,
            stored_payload=ciphertext,
            filename="report.txt",
        )
        conn.commit()
    finally:
        conn.close()
    key_file = tmp_path / ".filekey"
    key_file.write_text(key.decode("utf-8"), encoding="utf-8")
    output_dir = tmp_path / "plain-out"
    manifest_path = tmp_path / "manifest.json"

    code = decrypt_server_files.main(
        [
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
            "--key-file",
            str(key_file),
            "--output-dir",
            str(output_dir),
            "--manifest",
            str(manifest_path),
            "--confirm-plaintext-output",
        ]
    )

    assert code == 0
    output_file = output_dir / "user_1" / "file-a" / "report.txt"
    assert output_file.read_bytes() == plaintext
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "破壞與網頁使用者間的信任" in manifest["privacy_legal_warning"]
    assert "請自行負責" in manifest["privacy_legal_warning"]
    assert manifest["counts"] == {"decrypted": 1}
    assert manifest["files"][0]["plaintext_sha256"] == hashlib.sha256(plaintext).hexdigest()
    assert manifest["files"][0]["output_path"] == str(output_file)


def test_decrypt_server_files_dry_run_verifies_without_plaintext_output(tmp_path, capsys):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    source_path = storage_root / "users/2/file-b/blob.bin"
    source_path.parent.mkdir(parents=True)
    key = Fernet.generate_key()
    fernet = Fernet(key)
    plaintext = b"dry-run only"
    ciphertext = fernet.encrypt(plaintext)
    source_path.write_bytes(ciphertext)
    conn = _create_db(db_path)
    try:
        _insert_file(
            conn,
            file_id="file-b",
            owner_user_id=2,
            storage_path="users/2/file-b/blob.bin",
            privacy_mode="server_encrypted",
            plaintext=plaintext,
            stored_payload=ciphertext,
            filename="secret.bin",
        )
        conn.commit()
    finally:
        conn.close()
    key_file = tmp_path / ".filekey"
    key_file.write_text(key.decode("utf-8"), encoding="utf-8")
    code = decrypt_server_files.main(
        [
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
            "--key-file",
            str(key_file),
            "--dry-run",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "破壞與網頁使用者間的信任" in captured.err
    assert "請自行負責" in captured.err
    assert not (tmp_path / "plain-out").exists()


def test_decrypt_server_files_skips_non_server_encrypted_file_id(tmp_path):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    source_path = storage_root / "users/3/file-c/blob.bin"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"client ciphertext")
    conn = _create_db(db_path)
    try:
        _insert_file(
            conn,
            file_id="file-c",
            owner_user_id=3,
            storage_path="users/3/file-c/blob.bin",
            privacy_mode="e2ee",
            plaintext=b"client ciphertext",
            stored_payload=b"client ciphertext",
            filename="e2ee.bin",
        )
        conn.commit()
    finally:
        conn.close()
    key = Fernet.generate_key()
    key_file = tmp_path / ".filekey"
    key_file.write_text(key.decode("utf-8"), encoding="utf-8")
    conn = decrypt_server_files.open_db(db_path)
    try:
        rows = decrypt_server_files.select_file_rows(conn, file_ids=["file-c"])
    finally:
        conn.close()
    results = decrypt_server_files.decrypt_rows(
        rows,
        storage_root=storage_root,
        fernet=Fernet(key),
        output_dir=None,
        dry_run=True,
    )

    assert results[0]["status"] == "skipped_not_server_encrypted"


def test_decrypt_server_files_help_includes_privacy_warning():
    help_text = decrypt_server_files.build_parser().format_help()

    assert "破壞與網頁使用者間的信任" in help_text
    assert "隱私相關法律" in help_text
    assert "請自行負責" in help_text
