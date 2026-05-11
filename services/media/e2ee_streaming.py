import hashlib
import json
from datetime import datetime
from pathlib import Path

from services.storage.cloud_drive import is_e2ee_file
from services.storage.paths import resolve_storage_path


E2EE_STREAM_V2_VERSION = 2
E2EE_STREAM_V2_CHUNK_ALGORITHM = "AES-GCM"
E2EE_STREAM_V2_ALLOWED_MEDIA_PREFIXES = ("video/", "audio/")
E2EE_STREAM_V2_MAX_CHUNKS = 4096
E2EE_STREAM_V2_MAX_CHUNK_SIZE = 4 * 1024 * 1024
E2EE_STREAM_V2_MAX_BUNDLE_SIZE = 2 * 1024 * 1024 * 1024
E2EE_STREAM_V2_FORBIDDEN_FIELDS = {
    "raw_file_key",
    "e2ee_password",
    "vk",
    "share_key",
    "share_key_bytes",
}


def _stream_v2_capabilities():
    return {
        "segment_integrity_sha256": True,
        "client_memory_cache": True,
        "chunk_retry": True,
        "seek_recovery": "sequential_segment_resume",
    }


def _now():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _table_columns(conn, table):
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_columns(conn, table, definitions):
    columns = _table_columns(conn, table)
    for column, ddl in definitions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_e2ee_stream_v2_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_e2ee_stream_v2_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uploaded_file_id TEXT NOT NULL UNIQUE REFERENCES uploaded_files(id) ON DELETE CASCADE,
            stream_version INTEGER NOT NULL DEFAULT 2,
            chunk_size INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            manifest_path TEXT NOT NULL,
            bundle_path TEXT NOT NULL,
            content_type TEXT NOT NULL,
            duration_hint REAL NOT NULL DEFAULT 0,
            byte_range_hint_json TEXT NOT NULL DEFAULT '{}',
            source_size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    _ensure_columns(
        conn,
        "media_e2ee_stream_v2_assets",
        {
            "stream_version": "INTEGER NOT NULL DEFAULT 2",
            "chunk_size": "INTEGER NOT NULL DEFAULT 0",
            "chunk_count": "INTEGER NOT NULL DEFAULT 0",
            "manifest_path": "TEXT NOT NULL DEFAULT ''",
            "bundle_path": "TEXT NOT NULL DEFAULT ''",
            "content_type": "TEXT NOT NULL DEFAULT 'application/octet-stream'",
            "duration_hint": "REAL NOT NULL DEFAULT 0",
            "byte_range_hint_json": "TEXT NOT NULL DEFAULT '{}'",
            "source_size_bytes": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_e2ee_stream_v2_updated ON media_e2ee_stream_v2_assets(updated_at)"
    )


def _asset_row(conn, uploaded_file_id):
    return conn.execute(
        "SELECT * FROM media_e2ee_stream_v2_assets WHERE uploaded_file_id=?",
        (str(uploaded_file_id or ""),),
    ).fetchone()


def _coerce_int(value, field):
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"{field} 必須是整數") from exc


def _coerce_float(value, field):
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"{field} 必須是數字") from exc


def _normalize_manifest(manifest_payload, *, bundle_size):
    if not isinstance(manifest_payload, dict):
        raise ValueError("E2EE Streaming v2 manifest 格式不正確")
    extra_forbidden = [key for key in E2EE_STREAM_V2_FORBIDDEN_FIELDS if manifest_payload.get(key) not in (None, "", [], {})]
    if extra_forbidden:
        raise ValueError(f"禁止提交敏感串流欄位：{extra_forbidden[0]}")
    stream_version = _coerce_int(manifest_payload.get("e2ee_stream_version") or manifest_payload.get("stream_version"), "e2ee_stream_version")
    if stream_version != E2EE_STREAM_V2_VERSION:
        raise ValueError("E2EE Streaming v2 版本不支援")
    chunk_size = _coerce_int(manifest_payload.get("chunk_size") or 0, "chunk_size")
    if chunk_size <= 0 or chunk_size > E2EE_STREAM_V2_MAX_CHUNK_SIZE:
        raise ValueError("chunk_size 超出允許範圍")
    chunk_count = _coerce_int(manifest_payload.get("chunk_count") or 0, "chunk_count")
    chunks = manifest_payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("E2EE Streaming v2 manifest 缺少 chunks")
    if len(chunks) != chunk_count:
        raise ValueError("chunk_count 與 chunks 數量不一致")
    if chunk_count > E2EE_STREAM_V2_MAX_CHUNKS:
        raise ValueError("chunk 數量超出允許上限")
    content_type = str(manifest_payload.get("content_type") or "").strip().lower()
    if not any(content_type.startswith(prefix) for prefix in E2EE_STREAM_V2_ALLOWED_MEDIA_PREFIXES):
        raise ValueError("E2EE Streaming v2 只支援影音 content_type")
    duration_hint = _coerce_float(manifest_payload.get("duration_hint") or 0, "duration_hint")
    byte_range_hint = manifest_payload.get("byte_range_hint") or {}
    if not isinstance(byte_range_hint, dict):
        raise ValueError("byte_range_hint 格式不正確")
    normalized_chunks = []
    expected_index = 0
    expected_cipher_offset = 0
    expected_plain_offset = 0
    for item in chunks:
        if not isinstance(item, dict):
            raise ValueError("chunk metadata 格式不正確")
        index = _coerce_int(item.get("chunk_index", item.get("index")), "chunk_index")
        if index != expected_index:
            raise ValueError("chunk_index 必須連續且從 0 開始")
        nonce = str(item.get("nonce") or item.get("iv") or "").strip()
        if not nonce:
            raise ValueError("chunk 缺少 nonce")
        cipher_offset = _coerce_int(item.get("ciphertext_offset"), "ciphertext_offset")
        cipher_size = _coerce_int(item.get("ciphertext_size"), "ciphertext_size")
        plain_offset = _coerce_int(item.get("plaintext_offset"), "plaintext_offset")
        plain_size = _coerce_int(item.get("plaintext_size"), "plaintext_size")
        if cipher_offset != expected_cipher_offset or plain_offset != expected_plain_offset:
            raise ValueError("chunk offset 不連續")
        if cipher_size <= 0 or plain_size <= 0:
            raise ValueError("chunk size 必須大於 0")
        if cipher_size > chunk_size + 64:
            raise ValueError("ciphertext chunk size 異常")
        ciphertext_sha256 = str(item.get("ciphertext_sha256") or "").strip()
        normalized_chunks.append(
            {
                "chunk_index": index,
                "nonce": nonce,
                "ciphertext_offset": cipher_offset,
                "ciphertext_size": cipher_size,
                "plaintext_offset": plain_offset,
                "plaintext_size": plain_size,
                "ciphertext_sha256": ciphertext_sha256,
            }
        )
        expected_index += 1
        expected_cipher_offset += cipher_size
        expected_plain_offset += plain_size
    if expected_cipher_offset != bundle_size:
        raise ValueError("bundle 大小與 chunk metadata 不一致")
    return {
        "e2ee_stream_version": E2EE_STREAM_V2_VERSION,
        "algorithm": E2EE_STREAM_V2_CHUNK_ALGORITHM,
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "content_type": content_type,
        "duration_hint": max(0.0, duration_hint),
        "byte_range_hint": byte_range_hint,
        "source_size_bytes": expected_plain_offset,
        "chunks": normalized_chunks,
        "created_at": str(manifest_payload.get("created_at") or _now()),
    }


def _asset_relroot(uploaded_file_id):
    return f"e2ee_stream_v2/{uploaded_file_id}"


def upsert_e2ee_stream_v2_asset(conn, *, file_row, storage_root, manifest_payload, bundle_bytes):
    ensure_e2ee_stream_v2_schema(conn)
    if not file_row or not is_e2ee_file(file_row):
        raise ValueError("只有 strict E2EE 影音可建立 E2EE Streaming v2")
    if not isinstance(bundle_bytes, (bytes, bytearray)):
        raise ValueError("缺少 E2EE Streaming v2 bundle")
    bundle_size = len(bundle_bytes)
    if bundle_size <= 0 or bundle_size > E2EE_STREAM_V2_MAX_BUNDLE_SIZE:
        raise ValueError("E2EE Streaming v2 bundle 大小超出允許範圍")
    normalized_manifest = _normalize_manifest(manifest_payload, bundle_size=bundle_size)
    relroot = _asset_relroot(file_row["id"])
    manifest_rel = f"{relroot}/manifest.json"
    bundle_rel = f"{relroot}/bundle.bin"
    manifest_path = resolve_storage_path(storage_root, manifest_rel, create_parent=True)
    bundle_path = resolve_storage_path(storage_root, bundle_rel, create_parent=True)
    manifest_path.write_text(json.dumps(normalized_manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    bundle_path.write_bytes(bytes(bundle_bytes))
    now = _now()
    existing = _asset_row(conn, file_row["id"])
    params = (
        int(normalized_manifest["e2ee_stream_version"]),
        int(normalized_manifest["chunk_size"]),
        int(normalized_manifest["chunk_count"]),
        manifest_rel,
        bundle_rel,
        normalized_manifest["content_type"],
        float(normalized_manifest["duration_hint"]),
        json.dumps(normalized_manifest.get("byte_range_hint") or {}, ensure_ascii=False, sort_keys=True),
        int(normalized_manifest["source_size_bytes"]),
        now,
        file_row["id"],
    )
    if existing:
        conn.execute(
            """
            UPDATE media_e2ee_stream_v2_assets
            SET stream_version=?, chunk_size=?, chunk_count=?, manifest_path=?, bundle_path=?,
                content_type=?, duration_hint=?, byte_range_hint_json=?, source_size_bytes=?, updated_at=?
            WHERE uploaded_file_id=?
            """,
            params,
        )
    else:
        conn.execute(
            """
            INSERT INTO media_e2ee_stream_v2_assets (
                uploaded_file_id, stream_version, chunk_size, chunk_count, manifest_path, bundle_path,
                content_type, duration_hint, byte_range_hint_json, source_size_bytes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_row["id"],
                int(normalized_manifest["e2ee_stream_version"]),
                int(normalized_manifest["chunk_size"]),
                int(normalized_manifest["chunk_count"]),
                manifest_rel,
                bundle_rel,
                normalized_manifest["content_type"],
                float(normalized_manifest["duration_hint"]),
                json.dumps(normalized_manifest.get("byte_range_hint") or {}, ensure_ascii=False, sort_keys=True),
                int(normalized_manifest["source_size_bytes"]),
                now,
                now,
            ),
        )
    return get_e2ee_stream_v2_status(conn, file_row=file_row, storage_root=storage_root)


def load_e2ee_stream_v2_manifest(conn, *, file_row, storage_root):
    ensure_e2ee_stream_v2_schema(conn)
    asset = _asset_row(conn, file_row["id"]) if file_row else None
    if not asset:
        return None, {
            "ok": True,
            "available": False,
            "player_strategy": "browser_e2ee_full_fallback",
            "fallback_mode": "browser_e2ee_full_fallback",
            "reason": "manifest_missing",
            "msg": "此 strict E2EE 影音尚未建立 Streaming v2 manifest，將退回舊版完整解密播放。",
        }
    manifest_path = resolve_storage_path(storage_root, asset["manifest_path"])
    if not manifest_path.exists():
        return None, {
            "ok": True,
            "available": False,
            "player_strategy": "browser_e2ee_full_fallback",
            "fallback_mode": "browser_e2ee_full_fallback",
            "reason": "manifest_missing",
            "msg": "此 strict E2EE 影音尚未建立 Streaming v2 manifest，將退回舊版完整解密播放。",
        }
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload, None


def get_e2ee_stream_v2_status(conn, *, file_row, storage_root):
    manifest, fallback = load_e2ee_stream_v2_manifest(conn, file_row=file_row, storage_root=storage_root)
    if not manifest:
        return fallback
    asset = _asset_row(conn, file_row["id"])
    return {
        "ok": True,
        "available": True,
        "player_strategy": "browser_e2ee_stream_v2",
        "fallback_mode": "browser_e2ee_full_fallback",
        "uploaded_file_id": file_row["id"],
        "e2ee_stream_version": int(asset["stream_version"]),
        "chunk_size": int(asset["chunk_size"]),
        "chunk_count": int(asset["chunk_count"]),
        "content_type": str(asset["content_type"] or manifest.get("content_type") or "application/octet-stream"),
        "duration_hint": float(asset["duration_hint"] or manifest.get("duration_hint") or 0.0),
        "byte_range_hint": json.loads(asset["byte_range_hint_json"] or "{}"),
        "source_size_bytes": int(asset["source_size_bytes"] or manifest.get("source_size_bytes") or 0),
        "created_at": str(manifest.get("created_at") or asset["created_at"]),
        "manifest_path": str(asset["manifest_path"]),
        "bundle_path": str(asset["bundle_path"]),
        "capabilities": _stream_v2_capabilities(),
    }


def serialize_manifest_for_client(conn, *, file_row, storage_root):
    manifest, fallback = load_e2ee_stream_v2_manifest(conn, file_row=file_row, storage_root=storage_root)
    if not manifest:
        return fallback
    return {
        "ok": True,
        "available": True,
        "player_strategy": "browser_e2ee_stream_v2",
        "fallback_mode": "browser_e2ee_full_fallback",
        "e2ee_stream_version": int(manifest["e2ee_stream_version"]),
        "algorithm": str(manifest.get("algorithm") or E2EE_STREAM_V2_CHUNK_ALGORITHM),
        "chunk_size": int(manifest["chunk_size"]),
        "chunk_count": int(manifest["chunk_count"]),
        "content_type": str(manifest["content_type"]),
        "duration_hint": float(manifest.get("duration_hint") or 0.0),
        "byte_range_hint": manifest.get("byte_range_hint") or {},
        "source_size_bytes": int(manifest.get("source_size_bytes") or 0),
        "created_at": str(manifest.get("created_at") or ""),
        "capabilities": _stream_v2_capabilities(),
        "chunks": [
            {
                "chunk_index": int(item["chunk_index"]),
                "nonce": str(item["nonce"]),
                "ciphertext_size": int(item["ciphertext_size"]),
                "plaintext_offset": int(item["plaintext_offset"]),
                "plaintext_size": int(item["plaintext_size"]),
                "ciphertext_sha256": str(item.get("ciphertext_sha256") or ""),
            }
            for item in (manifest.get("chunks") or [])
        ],
    }


def resolve_e2ee_chunk_response(conn, *, file_row, storage_root, chunk_index):
    manifest, fallback = load_e2ee_stream_v2_manifest(conn, file_row=file_row, storage_root=storage_root)
    if not manifest:
        return None, fallback
    index = _coerce_int(chunk_index, "chunk_index")
    chunks = manifest.get("chunks") or []
    if index < 0 or index >= len(chunks):
        return None, {"ok": False, "error": "chunk_not_found", "msg": "找不到指定的 E2EE 串流分段"}
    asset = _asset_row(conn, file_row["id"])
    bundle_path = resolve_storage_path(storage_root, asset["bundle_path"])
    if not bundle_path.exists():
        return None, {"ok": False, "error": "bundle_missing", "msg": "E2EE 串流密文資料不存在"}
    chunk = chunks[index]
    start = int(chunk["ciphertext_offset"])
    size = int(chunk["ciphertext_size"])
    with bundle_path.open("rb") as fh:
        fh.seek(start)
        payload = fh.read(size)
    if len(payload) != size:
        return None, {"ok": False, "error": "bundle_truncated", "msg": "E2EE 串流密文資料不完整"}
    expected_sha256 = str(chunk.get("ciphertext_sha256") or "").strip().lower()
    if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
        return None, {"ok": False, "error": "bundle_corrupt", "msg": "E2EE 串流密文分段完整性驗證失敗"}
    return {
        "payload": payload,
        "chunk": chunk,
        "content_type": "application/octet-stream",
    }, None
