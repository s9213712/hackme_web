from __future__ import annotations

import base64
import hashlib
import json
import sqlite3

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from scripts.admin import decrypt_server_files


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _make_e2ee_payload(plaintext, passphrase, *, filename="vault.txt", mime_type="text/plain"):
    file_key = AESGCM.generate_key(bit_length=256)
    file_aead = AESGCM(file_key)
    file_nonce = b"\x01" * 12
    ciphertext = file_aead.encrypt(file_nonce, plaintext, None)
    meta_nonce = b"\x02" * 12
    metadata = {
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(plaintext),
        "encrypted_at": "2026-05-14T00:00:00",
    }
    encrypted_metadata = {
        "alg": "AES-GCM",
        "v": 1,
        "nonce": _b64(meta_nonce),
        "ciphertext": _b64(file_aead.encrypt(meta_nonce, json.dumps(metadata).encode("utf-8"), None)),
    }
    salt = b"\x03" * 16
    wrap_nonce = b"\x04" * 12
    iterations = 100_000
    wrapping_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    ).derive(passphrase.encode("utf-8"))
    encrypted_file_key = {
        "alg": "AES-GCM",
        "v": 2,
        "wrapped_by": "browser_passphrase_pbkdf2_v2",
        "kdf": "PBKDF2-SHA256",
        "iterations": iterations,
        "salt": _b64(salt),
        "nonce": _b64(wrap_nonce),
        "ciphertext": _b64(AESGCM(wrapping_key).encrypt(wrap_nonce, file_key, None)),
    }
    return {
        "ciphertext": ciphertext,
        "nonce": _b64(file_nonce),
        "encrypted_metadata": json.dumps(encrypted_metadata),
        "encrypted_file_key": json.dumps(encrypted_file_key),
        "wrapped_by": "browser_passphrase_pbkdf2_v2",
    }


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
            original_filename_encrypted TEXT,
            original_filename_plain_for_public TEXT,
            ciphertext_sha256 TEXT,
            plaintext_sha256 TEXT,
            encryption_algorithm TEXT,
            encryption_version TEXT,
            nonce TEXT,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE encrypted_file_keys (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            recipient_user_id INTEGER NOT NULL,
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
        CREATE TABLE storage_files (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            virtual_path TEXT NOT NULL,
            is_trashed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE storage_folders (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            virtual_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE storage_share_links (
            id TEXT PRIMARY KEY,
            storage_file_id TEXT NOT NULL,
            file_id TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            token TEXT,
            token_hash TEXT NOT NULL,
            revoked_at TEXT
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
    nonce=None,
    encrypted_metadata=None,
    encrypted_file_key=None,
    wrapped_by="browser_passphrase_pbkdf2_v2",
    encryption_algorithm=None,
    encryption_version=None,
    size_bytes=None,
):
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, size_bytes,
            original_filename_encrypted, original_filename_plain_for_public,
            ciphertext_sha256, plaintext_sha256, encryption_algorithm, encryption_version,
            nonce, created_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            file_id,
            owner_user_id,
            storage_path,
            privacy_mode,
            len(plaintext) if size_bytes is None else size_bytes,
            encrypted_metadata,
            filename,
            hashlib.sha256(stored_payload).hexdigest(),
            None,
            encryption_algorithm,
            encryption_version,
            nonce,
            "2026-05-14T00:00:00",
        ),
    )
    if encrypted_file_key:
        conn.execute(
            """
            INSERT INTO encrypted_file_keys (
                id, file_id, recipient_user_id, encrypted_file_key, wrapped_by, key_version, created_at, revoked_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, NULL)
            """,
            (f"key-{file_id}", file_id, owner_user_id, encrypted_file_key, wrapped_by, "2026-05-14T00:00:00"),
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


def test_decrypt_server_files_writes_e2ee_plaintext_with_passphrase(tmp_path):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    storage_path = "users/4/e2ee/blob.bin"
    source_path = storage_root / storage_path
    source_path.parent.mkdir(parents=True)
    passphrase = "correct horse battery staple"
    plaintext = b"E2EE browser encrypted plaintext"
    e2ee = _make_e2ee_payload(plaintext, passphrase, filename="private-note.txt")
    source_path.write_bytes(e2ee["ciphertext"])
    conn = _create_db(db_path)
    try:
        _insert_file(
            conn,
            file_id="e2ee-a",
            owner_user_id=4,
            storage_path=storage_path,
            privacy_mode="e2ee",
            plaintext=plaintext,
            stored_payload=e2ee["ciphertext"],
            filename="fallback.bin",
            nonce=e2ee["nonce"],
            encrypted_metadata=e2ee["encrypted_metadata"],
            encrypted_file_key=e2ee["encrypted_file_key"],
            encryption_algorithm="AES-GCM",
            encryption_version="browser-passphrase-v2",
            size_bytes=len(e2ee["ciphertext"]),
        )
        conn.commit()
    finally:
        conn.close()
    passphrase_file = tmp_path / "e2ee-passphrase.txt"
    passphrase_file.write_text(passphrase, encoding="utf-8")
    output_dir = tmp_path / "plain-out"

    code = decrypt_server_files.main(
        [
            "--db",
            str(db_path),
            "--storage-root",
            str(storage_root),
            "--privacy-mode",
            "e2ee",
            "--e2ee-passphrase-file",
            str(passphrase_file),
            "--output-dir",
            str(output_dir),
            "--confirm-plaintext-output",
        ]
    )

    assert code == 0
    output_file = output_dir / "user_4" / "e2ee-a" / "private-note.txt"
    assert output_file.read_bytes() == plaintext
    manifest = json.loads((output_dir / "decryption_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {"decrypted": 1}
    assert manifest["privacy_modes"] == ["e2ee"]
    assert manifest["e2ee_passphrase_source"].startswith("file:")
    assert manifest["files"][0]["decryption_key_source"] == "e2ee_passphrase"
    assert manifest["files"][0]["e2ee_metadata"]["filename"] == "private-note.txt"
    assert manifest["files"][0]["ciphertext_size_bytes"] == len(e2ee["ciphertext"])
    assert manifest["files"][0]["expected_size_bytes"] == len(plaintext)
    assert manifest["files"][0]["plaintext_size_bytes"] == len(plaintext)
    assert "size_mismatch" not in manifest["files"][0]


def test_decrypt_server_files_can_select_e2ee_files_under_storage_folder(tmp_path):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    passphrase = "folder passphrase"
    target_plaintext = b"inside folder"
    outside_plaintext = b"outside folder"
    target_e2ee = _make_e2ee_payload(target_plaintext, passphrase, filename="inside.txt")
    outside_e2ee = _make_e2ee_payload(outside_plaintext, passphrase, filename="outside.txt")
    target_path = "users/5/folder-target/blob.bin"
    outside_path = "users/5/outside/blob.bin"
    (storage_root / target_path).parent.mkdir(parents=True)
    (storage_root / outside_path).parent.mkdir(parents=True)
    (storage_root / target_path).write_bytes(target_e2ee["ciphertext"])
    (storage_root / outside_path).write_bytes(outside_e2ee["ciphertext"])
    conn = _create_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO storage_folders (id, owner_user_id, display_name, virtual_path, created_at, updated_at, deleted_at)
            VALUES ('folder-a', 5, 'docs', '/docs', '2026-05-14T00:00:00', '2026-05-14T00:00:00', NULL)
            """
        )
        _insert_file(
            conn,
            file_id="folder-file",
            owner_user_id=5,
            storage_path=target_path,
            privacy_mode="e2ee",
            plaintext=target_plaintext,
            stored_payload=target_e2ee["ciphertext"],
            filename="fallback-inside.bin",
            nonce=target_e2ee["nonce"],
            encrypted_metadata=target_e2ee["encrypted_metadata"],
            encrypted_file_key=target_e2ee["encrypted_file_key"],
            encryption_algorithm="AES-GCM",
            encryption_version="browser-passphrase-v2",
        )
        _insert_file(
            conn,
            file_id="outside-file",
            owner_user_id=5,
            storage_path=outside_path,
            privacy_mode="e2ee",
            plaintext=outside_plaintext,
            stored_payload=outside_e2ee["ciphertext"],
            filename="fallback-outside.bin",
            nonce=outside_e2ee["nonce"],
            encrypted_metadata=outside_e2ee["encrypted_metadata"],
            encrypted_file_key=outside_e2ee["encrypted_file_key"],
            encryption_algorithm="AES-GCM",
            encryption_version="browser-passphrase-v2",
        )
        conn.execute(
            """
            INSERT INTO storage_files (id, file_id, owner_user_id, display_name, virtual_path, is_trashed, created_at, deleted_at)
            VALUES ('sf-folder', 'folder-file', 5, 'inside.txt', '/docs/inside.txt', 0, '2026-05-14T00:00:00', NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO storage_files (id, file_id, owner_user_id, display_name, virtual_path, is_trashed, created_at, deleted_at)
            VALUES ('sf-outside', 'outside-file', 5, 'outside.txt', '/outside.txt', 0, '2026-05-14T00:00:00', NULL)
            """
        )
        conn.commit()

        rows = decrypt_server_files.select_file_rows(
            conn,
            owner_user_id=5,
            privacy_modes={"e2ee"},
            storage_folder_paths=["/docs"],
        )
    finally:
        conn.close()

    assert [row["id"] for row in rows] == ["folder-file"]
    results = decrypt_server_files.decrypt_rows(
        rows,
        storage_root=storage_root,
        fernet=None,
        privacy_modes={"e2ee"},
        e2ee_passphrase=passphrase,
        output_dir=None,
        dry_run=True,
    )
    assert results[0]["status"] == "verified"
    assert results[0]["plaintext_sha256"] == hashlib.sha256(target_plaintext).hexdigest()


def test_decrypt_server_files_can_select_file_by_storage_share_token(tmp_path):
    db_path = tmp_path / "database.db"
    storage_root = tmp_path / "storage"
    storage_path = "users/6/share/blob.bin"
    source_path = storage_root / storage_path
    source_path.parent.mkdir(parents=True)
    passphrase = "share passphrase"
    plaintext = b"shared e2ee file"
    e2ee = _make_e2ee_payload(plaintext, passphrase, filename="shared-e2ee.txt")
    source_path.write_bytes(e2ee["ciphertext"])
    conn = _create_db(db_path)
    try:
        _insert_file(
            conn,
            file_id="shared-file",
            owner_user_id=6,
            storage_path=storage_path,
            privacy_mode="e2ee",
            plaintext=plaintext,
            stored_payload=e2ee["ciphertext"],
            filename="fallback-shared.bin",
            nonce=e2ee["nonce"],
            encrypted_metadata=e2ee["encrypted_metadata"],
            encrypted_file_key=e2ee["encrypted_file_key"],
            encryption_algorithm="AES-GCM",
            encryption_version="browser-passphrase-v2",
        )
        conn.execute(
            """
            INSERT INTO storage_files (id, file_id, owner_user_id, display_name, virtual_path, is_trashed, created_at, deleted_at)
            VALUES ('sf-share', 'shared-file', 6, 'shared-e2ee.txt', '/shared-e2ee.txt', 0, '2026-05-14T00:00:00', NULL)
            """
        )
        token = "share-token-abc"
        conn.execute(
            """
            INSERT INTO storage_share_links (id, storage_file_id, file_id, owner_user_id, token, token_hash, revoked_at)
            VALUES ('share-a', 'sf-share', 'shared-file', 6, ?, ?, NULL)
            """,
            (token, decrypt_server_files._hash_share_token(token)),
        )
        conn.commit()
        rows = decrypt_server_files.select_file_rows(
            conn,
            privacy_modes={"e2ee"},
            storage_share_tokens=[token],
        )
    finally:
        conn.close()

    assert [row["id"] for row in rows] == ["shared-file"]


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
