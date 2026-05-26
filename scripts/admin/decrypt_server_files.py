#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.server.runtime import default_runtime_root_path
from services.storage.cloud_drive import decrypt_server_encrypted_bytes
from services.storage.paths import resolve_storage_path


SERVER_ENCRYPTED_MODE = "server_encrypted"
E2EE_MODE = "e2ee"
ALL_PRIVACY_MODES = {SERVER_ENCRYPTED_MODE, E2EE_MODE}
DEFAULT_KEY_ENV = "SERVER_FILE_ENCRYPTION_KEY"
DEFAULT_E2EE_PASSPHRASE_ENV = "HACKME_E2EE_PASSPHRASE"
E2EE_PASSPHRASE_WRAPPER = "browser_passphrase_pbkdf2_v2"
E2EE_MIN_PBKDF2_ITERATIONS = 100_000
PRIVACY_LEGAL_WARNING = (
    "警告：解密伺服器端加密或 E2EE 檔案可能會破壞與網頁使用者間的信任，"
    "或觸犯隱私相關法律。請確認具備合法授權、必要性與審計紀錄；"
    "操作後果請自行負責。"
)


def _env_path(env: dict[str, str], name: str, default_path: Path) -> Path:
    raw = str(env.get(name) or "").strip()
    if not raw:
        return default_path
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def default_runtime_dir(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    return _env_path(env, "HACKME_RUNTIME_DIR", default_runtime_root_path()).resolve()


def default_db_path(runtime_dir: Path, env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    db_dir = _env_path(env, "HTML_LEARNING_DB_DIR", runtime_dir / "database")
    return (db_dir / "database.db").resolve()


def default_key_path(runtime_dir: Path, env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    secret_root = _env_path(env, "HTML_LEARNING_RUNTIME_SECRETS_DIR", runtime_dir)
    return _env_path(env, "HTML_LEARNING_SERVER_FILE_KEY_FILE", secret_root / ".filekey").resolve()


def _db_setting(db_path: Path, key: str) -> str:
    if not db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
            return str(row[0] or "").strip() if row else ""
        finally:
            conn.close()
    except sqlite3.Error:
        return ""


def default_storage_root(runtime_dir: Path, db_path: Path, env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    root = _env_path(env, "HTML_LEARNING_STORAGE_DIR", runtime_dir / "storage")
    configured = _db_setting(db_path, "cloud_drive_storage_root")
    if configured:
        configured_path = Path(configured).expanduser()
        root = configured_path if configured_path.is_absolute() else (Path.cwd() / configured_path)
    return root.resolve()


def build_fernet(secret: str | bytes) -> Fernet:
    if isinstance(secret, bytes):
        secret = secret.decode("utf-8", errors="ignore")
    secret = str(secret).strip()
    try:
        return Fernet(secret.encode("utf-8"))
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        return Fernet(derived)


def load_server_file_secret(*, key_env: str, key_file: Path, env: dict[str, str] | None = None) -> tuple[str, str]:
    env = env or os.environ
    env_value = str(env.get(key_env) or "").strip()
    if env_value:
        return env_value, f"env:{key_env}"
    if key_file.exists():
        value = key_file.read_text(encoding="utf-8").strip()
        if value:
            return value, f"file:{key_file}"
    raise FileNotFoundError(
        f"server file encryption key not found; set {key_env} or provide --key-file"
    )


def load_e2ee_passphrase(
    *,
    passphrase: str | None,
    passphrase_file: Path | None,
    passphrase_env: str,
    prompt: bool,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    env = env or os.environ
    if passphrase is not None:
        return str(passphrase), "arg:--e2ee-passphrase"
    env_name = str(passphrase_env or "").strip()
    if env_name:
        env_value = str(env.get(env_name) or "")
        if env_value:
            return env_value, f"env:{env_name}"
    if passphrase_file:
        value = passphrase_file.expanduser().read_text(encoding="utf-8").rstrip("\r\n")
        if value:
            return value, f"file:{passphrase_file.expanduser().resolve()}"
    if prompt:
        return getpass.getpass("E2EE passphrase: "), "prompt"
    return "", ""


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_output_filename(value: str | None, fallback: str) -> str:
    raw = str(value or "").strip() or fallback
    name = Path(raw).name.strip() or fallback
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name)
    name = name.strip(". ") or fallback
    return name[:180]


def _row_value(row: sqlite3.Row | dict, key: str, default=None):
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
    except Exception:
        pass
    try:
        return row[key]
    except Exception:
        return row.get(key, default) if isinstance(row, dict) else default


def select_file_rows(
    conn: sqlite3.Connection,
    *,
    file_ids: list[str] | None = None,
    owner_user_id: int | None = None,
    privacy_modes: set[str] | None = None,
    storage_folder_ids: list[str] | None = None,
    storage_folder_paths: list[str] | None = None,
    storage_share_tokens: list[str] | None = None,
    include_deleted: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    privacy_modes = set(privacy_modes or {SERVER_ENCRYPTED_MODE})
    folder_filters = _storage_folder_filters(
        conn,
        owner_user_id=owner_user_id,
        folder_ids=storage_folder_ids,
        folder_paths=storage_folder_paths,
    )
    has_encrypted_keys = _table_exists(conn, "encrypted_file_keys")
    has_storage_files = _table_exists(conn, "storage_files")
    has_storage_share_links = _table_exists(conn, "storage_share_links")
    if folder_filters and not has_storage_files:
        raise ValueError("storage_files table is not available")
    if storage_share_tokens and not has_storage_share_links:
        raise ValueError("storage_share_links table is not available")
    select = [
        "f.*",
        (
            "ek.encrypted_file_key AS e2ee_encrypted_file_key"
            if has_encrypted_keys else "NULL AS e2ee_encrypted_file_key"
        ),
        "ek.wrapped_by AS e2ee_wrapped_by" if has_encrypted_keys else "NULL AS e2ee_wrapped_by",
        "ek.key_version AS e2ee_key_version" if has_encrypted_keys else "NULL AS e2ee_key_version",
    ]
    if has_storage_files:
        select.extend([
            """
            (
                SELECT sf.id
                FROM storage_files sf
                WHERE sf.file_id=f.id
                  AND sf.owner_user_id=f.owner_user_id
                  AND sf.deleted_at IS NULL
                ORDER BY sf.created_at DESC
                LIMIT 1
            ) AS storage_file_id
            """,
            """
            (
                SELECT sf.virtual_path
                FROM storage_files sf
                WHERE sf.file_id=f.id
                  AND sf.owner_user_id=f.owner_user_id
                  AND sf.deleted_at IS NULL
                ORDER BY sf.created_at DESC
                LIMIT 1
            ) AS storage_virtual_path
            """,
        ])
    else:
        select.extend(["NULL AS storage_file_id", "NULL AS storage_virtual_path"])
    query = [
        "SELECT",
        ", ".join(select),
        "FROM uploaded_files f",
        "WHERE 1=1",
    ]
    if has_encrypted_keys:
        query.insert(
            3,
            """
            LEFT JOIN encrypted_file_keys ek
              ON ek.file_id=f.id
             AND ek.recipient_user_id=f.owner_user_id
             AND ek.revoked_at IS NULL
            """,
        )
    params: list[object] = []
    if file_ids:
        placeholders = ",".join("?" for _ in file_ids)
        query.append(f"AND f.id IN ({placeholders})")
        params.extend(file_ids)
    else:
        placeholders = ",".join("?" for _ in privacy_modes)
        query.append(f"AND f.privacy_mode IN ({placeholders})")
        params.extend(sorted(privacy_modes))
    if owner_user_id is not None:
        query.append("AND f.owner_user_id=?")
        params.append(int(owner_user_id))
    if not include_deleted:
        query.append("AND f.deleted_at IS NULL")
    if folder_filters:
        folder_clauses = []
        for filter_owner_id, folder_path in folder_filters:
            owner_clause = ""
            owner_params: list[object] = []
            if filter_owner_id is not None:
                owner_clause = " AND sf_filter.owner_user_id=?"
                owner_params.append(int(filter_owner_id))
            if folder_path == "/":
                clause = f"""
                    EXISTS (
                        SELECT 1
                        FROM storage_files sf_filter
                        WHERE sf_filter.file_id=f.id
                          AND sf_filter.owner_user_id=f.owner_user_id
                          {owner_clause}
                          AND sf_filter.deleted_at IS NULL
                          AND sf_filter.is_trashed=0
                    )
                """
                params.extend(owner_params)
            else:
                clause = f"""
                    EXISTS (
                        SELECT 1
                        FROM storage_files sf_filter
                        WHERE sf_filter.file_id=f.id
                          AND sf_filter.owner_user_id=f.owner_user_id
                          {owner_clause}
                          AND sf_filter.deleted_at IS NULL
                          AND sf_filter.is_trashed=0
                          AND (sf_filter.virtual_path=? OR sf_filter.virtual_path LIKE ?)
                    )
                """
                params.extend([*owner_params, folder_path, f"{folder_path}/%"])
            folder_clauses.append(clause)
        query.append("AND (" + " OR ".join(folder_clauses) + ")")
    if storage_share_tokens:
        token_clauses = []
        for token in storage_share_tokens:
            token_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM storage_share_links sl_filter
                    WHERE sl_filter.file_id=f.id
                      AND (sl_filter.token=? OR sl_filter.token_hash=?)
                      AND sl_filter.revoked_at IS NULL
                )
                """
            )
            params.extend([str(token), _hash_share_token(str(token))])
        query.append("AND (" + " OR ".join(token_clauses) + ")")
    query.append("ORDER BY f.owner_user_id, f.created_at, f.id")
    if limit is not None:
        query.append("LIMIT ?")
        params.append(int(limit))
    return conn.execute(" ".join(query), params).fetchall()


def _output_path_for_row(output_dir: Path, row: sqlite3.Row) -> Path:
    file_id = str(row["id"])
    owner = int(row["owner_user_id"])
    filename = _safe_output_filename(
        _row_value(row, "original_filename_plain_for_public"),
        f"{file_id}.bin",
    )
    return output_dir / f"user_{owner}" / file_id / filename


def _write_bytes_atomic(path: Path, data: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"output exists: {path}")
    handle = tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False)
    tmp_name = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_name.replace(path)
    except Exception:
        try:
            tmp_name.unlink()
        except FileNotFoundError:
            pass
        raise


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _hash_share_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _normalize_storage_folder_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        raise ValueError("storage folder path is required")
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/+", "/", text).rstrip("/")
    return text or "/"


def _storage_folder_filters(
    conn: sqlite3.Connection,
    *,
    owner_user_id: int | None,
    folder_ids: list[str] | None,
    folder_paths: list[str] | None,
) -> list[tuple[int | None, str]]:
    filters: list[tuple[int | None, str]] = []
    for raw in folder_paths or []:
        filters.append((owner_user_id, _normalize_storage_folder_path(raw)))
    for folder_id in folder_ids or []:
        if not _table_exists(conn, "storage_folders"):
            raise ValueError("storage_folders table is not available")
        params: list[object] = [str(folder_id)]
        owner_clause = ""
        if owner_user_id is not None:
            owner_clause = " AND owner_user_id=?"
            params.append(int(owner_user_id))
        row = conn.execute(
            f"""
            SELECT owner_user_id, virtual_path
            FROM storage_folders
            WHERE id=? AND deleted_at IS NULL{owner_clause}
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if not row:
            raise ValueError(f"storage folder not found: {folder_id}")
        filters.append((int(row["owner_user_id"]), _normalize_storage_folder_path(row["virtual_path"])))
    return filters


def _privacy_modes_from_option(value: str) -> set[str]:
    value = str(value or SERVER_ENCRYPTED_MODE).strip().lower()
    if value == "all":
        return set(ALL_PRIVACY_MODES)
    if value not in ALL_PRIVACY_MODES:
        raise ValueError(f"unsupported privacy mode: {value}")
    return {value}


def _b64decode(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="strict")
    else:
        text = str(value or "")
    text = text.strip()
    if not text:
        return b""
    text = text.replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    try:
        return base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 payload") from exc


def _json_envelope(value: str, *, label: str) -> dict:
    try:
        payload = json.loads(str(value or "{}"))
    except Exception as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def decrypt_e2ee_wrapped_file_key(encrypted_file_key: str, passphrase: str) -> bytes:
    envelope = _json_envelope(encrypted_file_key, label="encrypted_file_key")
    if str(envelope.get("wrapped_by") or "") != E2EE_PASSPHRASE_WRAPPER:
        raise ValueError("unsupported E2EE key wrapper; only browser_passphrase_pbkdf2_v2 is supported")
    if str(envelope.get("alg") or "") != "AES-GCM" or int(envelope.get("v") or 0) != 2:
        raise ValueError("unsupported E2EE key envelope version")
    if str(envelope.get("kdf") or "") not in {"", "PBKDF2-SHA256"}:
        raise ValueError("unsupported E2EE key derivation")
    iterations = max(E2EE_MIN_PBKDF2_ITERATIONS, int(envelope.get("iterations") or 0))
    salt = _b64decode(envelope.get("salt") or "")
    nonce = _b64decode(envelope.get("nonce") or "")
    ciphertext = _b64decode(envelope.get("ciphertext") or "")
    wrapping_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    ).derive(str(passphrase or "").encode("utf-8"))
    raw_key = AESGCM(wrapping_key).decrypt(nonce, ciphertext, None)
    if len(raw_key) != 32:
        raise ValueError("E2EE file key has invalid length")
    return raw_key


def decrypt_e2ee_json_metadata(encrypted_metadata: str, raw_file_key: bytes) -> dict:
    if not str(encrypted_metadata or "").strip():
        return {}
    envelope = _json_envelope(encrypted_metadata, label="encrypted_metadata")
    if str(envelope.get("alg") or "") not in {"", "AES-GCM"}:
        raise ValueError("unsupported E2EE metadata algorithm")
    nonce = _b64decode(envelope.get("nonce") or "")
    ciphertext = _b64decode(envelope.get("ciphertext") or "")
    plaintext = AESGCM(raw_file_key).decrypt(nonce, ciphertext, None)
    data = json.loads(plaintext.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def decrypt_e2ee_ciphertext(ciphertext: bytes, *, raw_file_key: bytes, nonce: str) -> bytes:
    return AESGCM(raw_file_key).decrypt(_b64decode(nonce), ciphertext, None)


def decrypt_rows(
    rows: list[sqlite3.Row],
    *,
    storage_root: Path,
    fernet: Fernet | None,
    privacy_modes: set[str] | None = None,
    e2ee_passphrase: str | None = None,
    output_dir: Path | None,
    dry_run: bool,
    overwrite: bool = False,
) -> list[dict]:
    results: list[dict] = []
    privacy_modes = set(privacy_modes or {SERVER_ENCRYPTED_MODE})
    for row in rows:
        item = {
            "file_id": str(row["id"]),
            "owner_user_id": int(row["owner_user_id"]),
            "privacy_mode": str(row["privacy_mode"] or ""),
            "storage_path": str(row["storage_path"] or ""),
            "status": "pending",
        }
        if item["privacy_mode"] not in privacy_modes:
            item["status"] = (
                "skipped_not_server_encrypted"
                if privacy_modes == {SERVER_ENCRYPTED_MODE}
                else "skipped_not_selected_privacy_mode"
            )
            results.append(item)
            continue
        try:
            source_path = resolve_storage_path(storage_root, item["storage_path"], create_parent=False)
            item["source_path"] = str(source_path)
            if not source_path.exists():
                raise FileNotFoundError(f"storage object missing: {source_path}")
            recorded_ciphertext_sha = str(_row_value(row, "ciphertext_sha256") or "")
            actual_ciphertext_sha = _sha256_path(source_path)
            item["ciphertext_sha256"] = actual_ciphertext_sha
            if recorded_ciphertext_sha and recorded_ciphertext_sha != actual_ciphertext_sha:
                item["ciphertext_sha256_mismatch"] = True
            encrypted_metadata = str(_row_value(row, "original_filename_encrypted") or "")
            output_filename = str(_row_value(row, "original_filename_plain_for_public") or "")
            stored_size = int(_row_value(row, "size_bytes", 0) or 0)
            expected_plaintext_size = stored_size
            if item["privacy_mode"] == SERVER_ENCRYPTED_MODE:
                if fernet is None:
                    raise ValueError("server file encryption key is required for server_encrypted files")
                plaintext = decrypt_server_encrypted_bytes(source_path, fernet)
                item["decryption_key_source"] = "server_file_key"
            elif item["privacy_mode"] == E2EE_MODE:
                if not e2ee_passphrase:
                    raise ValueError("E2EE passphrase is required for e2ee files")
                encrypted_file_key = str(_row_value(row, "e2ee_encrypted_file_key") or "")
                if not encrypted_file_key:
                    raise ValueError("missing owner E2EE encrypted_file_key")
                raw_file_key = decrypt_e2ee_wrapped_file_key(encrypted_file_key, e2ee_passphrase)
                plaintext = decrypt_e2ee_ciphertext(
                    source_path.read_bytes(),
                    raw_file_key=raw_file_key,
                    nonce=str(_row_value(row, "nonce") or ""),
                )
                metadata = decrypt_e2ee_json_metadata(encrypted_metadata, raw_file_key)
                if metadata:
                    item["e2ee_metadata"] = {
                        key: metadata.get(key)
                        for key in ("filename", "mime_type", "size_bytes", "encrypted_at")
                        if metadata.get(key) is not None
                    }
                    try:
                        expected_plaintext_size = int(metadata.get("size_bytes") or stored_size)
                    except (TypeError, ValueError):
                        expected_plaintext_size = stored_size
                output_filename = str(metadata.get("filename") or output_filename or "")
                item["decryption_key_source"] = "e2ee_passphrase"
                item["ciphertext_size_bytes"] = stored_size
            else:
                raise ValueError(f"unsupported privacy_mode: {item['privacy_mode']}")
            plaintext_sha = _sha256_bytes(plaintext)
            item["plaintext_sha256"] = plaintext_sha
            item["plaintext_size_bytes"] = len(plaintext)
            item["expected_size_bytes"] = expected_plaintext_size
            if expected_plaintext_size and expected_plaintext_size != len(plaintext):
                item["size_mismatch"] = True
            recorded_plaintext_sha = str(_row_value(row, "plaintext_sha256") or "")
            if recorded_plaintext_sha and recorded_plaintext_sha != plaintext_sha:
                item["plaintext_sha256_mismatch"] = True
            if dry_run:
                item["status"] = "verified"
            else:
                assert output_dir is not None
                destination = _output_path_for_row(output_dir, {**dict(row), "original_filename_plain_for_public": output_filename})
                _write_bytes_atomic(destination, plaintext, overwrite=overwrite)
                item["output_path"] = str(destination)
                item["status"] = "decrypted"
        except InvalidToken as exc:
            item["status"] = "failed"
            item["error"] = "invalid_or_wrong_server_file_key"
            item["detail"] = str(exc)
        except InvalidTag as exc:
            item["status"] = "failed"
            item["error"] = "invalid_or_wrong_e2ee_passphrase"
            item["detail"] = str(exc)
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = exc.__class__.__name__
            item["detail"] = str(exc)
        results.append(item)
    return results


def build_manifest(
    *,
    db_path: Path,
    storage_root: Path,
    output_dir: Path | None,
    key_source: str,
    e2ee_passphrase_source: str = "",
    privacy_modes: set[str] | None = None,
    dry_run: bool,
    results: list[dict],
) -> dict:
    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy_legal_warning": PRIVACY_LEGAL_WARNING,
        "db_path": str(db_path),
        "storage_root": str(storage_root),
        "output_dir": str(output_dir) if output_dir else "",
        "key_source": key_source,
        "server_key_source": key_source if key_source else "",
        "e2ee_passphrase_source": e2ee_passphrase_source,
        "privacy_modes": sorted(privacy_modes or {SERVER_ENCRYPTED_MODE}),
        "dry_run": bool(dry_run),
        "counts": counts,
        "files": results,
    }


def write_manifest(path: Path, manifest: dict, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"manifest exists: {path}")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def _validate_output_dir(output_dir: Path, *, storage_root: Path) -> Path:
    resolved = output_dir.expanduser().resolve()
    storage = storage_root.resolve()
    if resolved == storage or storage in resolved.parents:
        raise ValueError("output directory must not be inside the live storage root")
    public_dir = (ROOT / "public").resolve()
    if resolved == public_dir or public_dir in resolved.parents:
        raise ValueError("output directory must not be inside public web assets")
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Decrypt server_encrypted uploaded_files with the server Fernet key, "
            "or e2ee uploaded_files when the user-provided E2EE passphrase is available."
        ),
        epilog=PRIVACY_LEGAL_WARNING,
    )
    parser.add_argument("--db", type=Path, help="Path to database.db. Defaults to $HTML_LEARNING_DB_DIR/database.db.")
    parser.add_argument("--storage-root", type=Path, help="Storage root. Defaults to runtime storage or cloud_drive_storage_root setting.")
    parser.add_argument("--privacy-mode", choices=["server_encrypted", "e2ee", "all"], default=SERVER_ENCRYPTED_MODE, help="Which privacy mode to process. Default: server_encrypted.")
    parser.add_argument("--key-file", type=Path, help="Server file key file. Defaults to $HTML_LEARNING_SERVER_FILE_KEY_FILE or runtime/.filekey.")
    parser.add_argument("--key-env", default=DEFAULT_KEY_ENV, help=f"Environment variable containing the server file key. Default: {DEFAULT_KEY_ENV}.")
    parser.add_argument("--e2ee-passphrase", help="E2EE file passphrase. Prefer --e2ee-passphrase-file or --e2ee-passphrase-env to avoid shell history.")
    parser.add_argument("--e2ee-passphrase-file", type=Path, help="Read the E2EE passphrase from a local text file.")
    parser.add_argument("--e2ee-passphrase-env", default=DEFAULT_E2EE_PASSPHRASE_ENV, help=f"Environment variable containing the E2EE passphrase. Default: {DEFAULT_E2EE_PASSPHRASE_ENV}.")
    parser.add_argument("--prompt-e2ee-passphrase", action="store_true", help="Prompt interactively for the E2EE passphrase.")
    parser.add_argument("--output-dir", type=Path, help="Destination directory for plaintext files.")
    parser.add_argument("--manifest", type=Path, help="Write JSON manifest to this path.")
    parser.add_argument("--file-id", action="append", default=[], help="Decrypt a specific uploaded_files.id. Can be repeated.")
    parser.add_argument("--owner-user-id", type=int, help="Limit to one owner_user_id.")
    parser.add_argument("--storage-folder-id", action="append", default=[], help="Decrypt files contained in this storage_folders.id. Can be repeated.")
    parser.add_argument("--storage-folder-path", action="append", default=[], help="Decrypt files recursively under this storage folder path, e.g. /photos/2026. Can be repeated.")
    parser.add_argument("--storage-share-token", action="append", default=[], help="Select files referenced by a storage share token. Can be repeated.")
    parser.add_argument("--include-deleted", action="store_true", help="Include rows with deleted_at set.")
    parser.add_argument("--limit", type=int, help="Maximum rows to process.")
    parser.add_argument("--dry-run", action="store_true", help="Verify decryptability and hashes without writing plaintext.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing plaintext output files.")
    parser.add_argument("--confirm-plaintext-output", action="store_true", help="Required when writing decrypted plaintext.")
    parser.add_argument("--json", action="store_true", help="Print the full manifest JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(PRIVACY_LEGAL_WARNING, file=sys.stderr)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    runtime_dir = default_runtime_dir()
    db_path = (args.db or default_db_path(runtime_dir)).expanduser().resolve()
    storage_root = (args.storage_root or default_storage_root(runtime_dir, db_path)).expanduser().resolve()
    key_file = (args.key_file or default_key_path(runtime_dir)).expanduser().resolve()
    privacy_modes = _privacy_modes_from_option(args.privacy_mode)
    output_dir = None
    if not args.dry_run:
        if not args.output_dir:
            parser.error("--output-dir is required unless --dry-run is used")
        if not args.confirm_plaintext_output:
            parser.error("--confirm-plaintext-output is required before writing plaintext")
        output_dir = _validate_output_dir(args.output_dir, storage_root=storage_root)
    elif args.output_dir:
        output_dir = _validate_output_dir(args.output_dir, storage_root=storage_root)

    try:
        secret = ""
        key_source = ""
        fernet = None
        if SERVER_ENCRYPTED_MODE in privacy_modes:
            secret, key_source = load_server_file_secret(key_env=args.key_env, key_file=key_file)
            fernet = build_fernet(secret)
        e2ee_passphrase = ""
        e2ee_passphrase_source = ""
        if E2EE_MODE in privacy_modes:
            e2ee_passphrase, e2ee_passphrase_source = load_e2ee_passphrase(
                passphrase=args.e2ee_passphrase,
                passphrase_file=args.e2ee_passphrase_file,
                passphrase_env=args.e2ee_passphrase_env,
                prompt=bool(args.prompt_e2ee_passphrase),
            )
            if not e2ee_passphrase:
                parser.error(
                    "--privacy-mode e2ee/all requires an E2EE passphrase via "
                    "--e2ee-passphrase-file, --e2ee-passphrase-env, --e2ee-passphrase, "
                    "or --prompt-e2ee-passphrase"
                )
        conn = open_db(db_path)
        try:
            rows = select_file_rows(
                conn,
                file_ids=[str(file_id) for file_id in args.file_id] or None,
                owner_user_id=args.owner_user_id,
                privacy_modes=privacy_modes,
                storage_folder_ids=[str(item) for item in args.storage_folder_id] or None,
                storage_folder_paths=[str(item) for item in args.storage_folder_path] or None,
                storage_share_tokens=[str(item) for item in args.storage_share_token] or None,
                include_deleted=bool(args.include_deleted),
                limit=args.limit,
            )
        finally:
            conn.close()
        results = decrypt_rows(
            rows,
            storage_root=storage_root,
            fernet=fernet,
            privacy_modes=privacy_modes,
            e2ee_passphrase=e2ee_passphrase,
            output_dir=output_dir,
            dry_run=bool(args.dry_run),
            overwrite=bool(args.overwrite),
        )
        manifest = build_manifest(
            db_path=db_path,
            storage_root=storage_root,
            output_dir=output_dir,
            key_source=key_source,
            e2ee_passphrase_source=e2ee_passphrase_source,
            privacy_modes=privacy_modes,
            dry_run=bool(args.dry_run),
            results=results,
        )
        manifest_path = args.manifest.expanduser().resolve() if args.manifest else None
        if manifest_path is None and output_dir:
            manifest_path = output_dir / "decryption_manifest.json"
        if manifest_path:
            write_manifest(manifest_path, manifest, overwrite=args.overwrite)
        if args.json:
            print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            counts = manifest["counts"]
            print(
                "server file decrypt summary: "
                f"decrypted={counts.get('decrypted', 0)} "
                f"verified={counts.get('verified', 0)} "
                f"failed={counts.get('failed', 0)} "
                f"skipped={counts.get('skipped_not_server_encrypted', 0) + counts.get('skipped_not_selected_privacy_mode', 0)}"
            )
            if manifest_path:
                print(f"manifest: {manifest_path}")
            if output_dir:
                print(f"output_dir: {output_dir}")
        return 1 if manifest["counts"].get("failed", 0) else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
