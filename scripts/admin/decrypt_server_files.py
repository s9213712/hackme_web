#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.server.runtime import default_runtime_root_path
from services.storage.paths import resolve_storage_path


SERVER_ENCRYPTED_MODE = "server_encrypted"
DEFAULT_KEY_ENV = "SERVER_FILE_ENCRYPTION_KEY"
PRIVACY_LEGAL_WARNING = (
    "警告：解密伺服器端加密檔案可能會破壞與網頁使用者間的信任，"
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
    include_deleted: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    query = ["SELECT * FROM uploaded_files WHERE 1=1"]
    params: list[object] = []
    if file_ids:
        placeholders = ",".join("?" for _ in file_ids)
        query.append(f"AND id IN ({placeholders})")
        params.extend(file_ids)
    else:
        query.append("AND privacy_mode=?")
        params.append(SERVER_ENCRYPTED_MODE)
    if owner_user_id is not None:
        query.append("AND owner_user_id=?")
        params.append(int(owner_user_id))
    if not include_deleted:
        query.append("AND deleted_at IS NULL")
    query.append("ORDER BY owner_user_id, created_at, id")
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


def decrypt_rows(
    rows: list[sqlite3.Row],
    *,
    storage_root: Path,
    fernet: Fernet,
    output_dir: Path | None,
    dry_run: bool,
    overwrite: bool = False,
) -> list[dict]:
    results: list[dict] = []
    for row in rows:
        item = {
            "file_id": str(row["id"]),
            "owner_user_id": int(row["owner_user_id"]),
            "privacy_mode": str(row["privacy_mode"] or ""),
            "storage_path": str(row["storage_path"] or ""),
            "status": "pending",
        }
        if item["privacy_mode"] != SERVER_ENCRYPTED_MODE:
            item["status"] = "skipped_not_server_encrypted"
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
            plaintext = fernet.decrypt(source_path.read_bytes())
            plaintext_sha = _sha256_bytes(plaintext)
            item["plaintext_sha256"] = plaintext_sha
            item["plaintext_size_bytes"] = len(plaintext)
            expected_size = int(_row_value(row, "size_bytes", 0) or 0)
            item["expected_size_bytes"] = expected_size
            if expected_size and expected_size != len(plaintext):
                item["size_mismatch"] = True
            recorded_plaintext_sha = str(_row_value(row, "plaintext_sha256") or "")
            if recorded_plaintext_sha and recorded_plaintext_sha != plaintext_sha:
                item["plaintext_sha256_mismatch"] = True
            if dry_run:
                item["status"] = "verified"
            else:
                assert output_dir is not None
                destination = _output_path_for_row(output_dir, row)
                _write_bytes_atomic(destination, plaintext, overwrite=overwrite)
                item["output_path"] = str(destination)
                item["status"] = "decrypted"
        except InvalidToken as exc:
            item["status"] = "failed"
            item["error"] = "invalid_or_wrong_server_file_key"
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
        description="Decrypt server_encrypted uploaded_files while the server-side Fernet key is still available.",
        epilog=PRIVACY_LEGAL_WARNING,
    )
    parser.add_argument("--db", type=Path, help="Path to database.db. Defaults to $HTML_LEARNING_DB_DIR/database.db.")
    parser.add_argument("--storage-root", type=Path, help="Storage root. Defaults to runtime storage or cloud_drive_storage_root setting.")
    parser.add_argument("--key-file", type=Path, help="Server file key file. Defaults to $HTML_LEARNING_SERVER_FILE_KEY_FILE or runtime/.filekey.")
    parser.add_argument("--key-env", default=DEFAULT_KEY_ENV, help=f"Environment variable containing the server file key. Default: {DEFAULT_KEY_ENV}.")
    parser.add_argument("--output-dir", type=Path, help="Destination directory for plaintext files.")
    parser.add_argument("--manifest", type=Path, help="Write JSON manifest to this path.")
    parser.add_argument("--file-id", action="append", default=[], help="Decrypt a specific uploaded_files.id. Can be repeated.")
    parser.add_argument("--owner-user-id", type=int, help="Limit to one owner_user_id.")
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
        secret, key_source = load_server_file_secret(key_env=args.key_env, key_file=key_file)
        fernet = build_fernet(secret)
        conn = open_db(db_path)
        try:
            rows = select_file_rows(
                conn,
                file_ids=[str(file_id) for file_id in args.file_id] or None,
                owner_user_id=args.owner_user_id,
                include_deleted=bool(args.include_deleted),
                limit=args.limit,
            )
        finally:
            conn.close()
        results = decrypt_rows(
            rows,
            storage_root=storage_root,
            fernet=fernet,
            output_dir=output_dir,
            dry_run=bool(args.dry_run),
            overwrite=bool(args.overwrite),
        )
        manifest = build_manifest(
            db_path=db_path,
            storage_root=storage_root,
            output_dir=output_dir,
            key_source=key_source,
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
                f"skipped={counts.get('skipped_not_server_encrypted', 0)}"
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
