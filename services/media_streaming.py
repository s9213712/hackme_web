import json
import mimetypes
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from services.cloud_drive import (
    decrypt_server_encrypted_bytes,
    is_e2ee_file,
    is_server_encrypted_file,
    resolve_file_storage_path,
)
from services.storage_paths import resolve_storage_path


MEDIA_STREAM_ASSET_STATUSES = {"pending", "processing", "ready", "failed", "unavailable"}
MEDIA_STREAM_STORAGE_MODE = "acl_protected_plain"
DEFAULT_HLS_SEGMENT_SECONDS = 4


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


def ensure_media_stream_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_stream_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uploaded_file_id TEXT NOT NULL UNIQUE REFERENCES uploaded_files(id) ON DELETE CASCADE,
            source_mode TEXT NOT NULL,
            media_type TEXT NOT NULL DEFAULT 'video',
            status TEXT NOT NULL DEFAULT 'pending',
            storage_mode TEXT NOT NULL DEFAULT 'acl_protected_plain',
            master_manifest_path TEXT,
            duration_seconds REAL NOT NULL DEFAULT 0,
            source_mime_type TEXT,
            source_size_bytes INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (status IN ('pending', 'processing', 'ready', 'failed', 'unavailable'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_stream_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES media_stream_assets(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            bitrate INTEGER NOT NULL DEFAULT 0,
            codec TEXT,
            playlist_path TEXT NOT NULL,
            init_segment_path TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_stream_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL REFERENCES media_stream_variants(id) ON DELETE CASCADE,
            sequence_number INTEGER NOT NULL DEFAULT 0,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            duration_seconds REAL NOT NULL DEFAULT 0,
            byte_size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_stream_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES media_stream_assets(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    _ensure_columns(conn, "media_stream_assets", {"media_type": "TEXT NOT NULL DEFAULT 'video'"})
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_stream_assets_status ON media_stream_assets(status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_stream_variants_asset ON media_stream_variants(asset_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_stream_segments_variant_seq ON media_stream_segments(variant_id, sequence_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_stream_jobs_asset ON media_stream_jobs(asset_id, created_at)")


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _row_dict(row):
    return dict(row) if row is not None else None


def _row_value(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except Exception:
        return default


def _file_media_type(file_row):
    mime = str(file_row["mime_type_plain_for_public"] or "").lower()
    filename = str(file_row["original_filename_plain_for_public"] or "").lower()
    if mime.startswith("audio/") or any(filename.endswith(ext) for ext in (".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg")):
        return "audio"
    return "video"


def _derivative_root_relpath(uploaded_file_id):
    return f"media_derivatives/{uploaded_file_id}"


def _asset_row(conn, uploaded_file_id):
    return conn.execute("SELECT * FROM media_stream_assets WHERE uploaded_file_id=?", (str(uploaded_file_id),)).fetchone()


def _variant_rows(conn, asset_id):
    return conn.execute(
        "SELECT * FROM media_stream_variants WHERE asset_id=? ORDER BY id ASC",
        (int(asset_id),),
    ).fetchall()


def _segment_rows(conn, variant_id):
    return conn.execute(
        "SELECT * FROM media_stream_segments WHERE variant_id=? ORDER BY sequence_number ASC, id ASC",
        (int(variant_id),),
    ).fetchall()


def serialize_stream_asset(conn, uploaded_file_id):
    ensure_media_stream_schema(conn)
    asset = _asset_row(conn, uploaded_file_id)
    if not asset:
        return None
    data = _row_dict(asset)
    data["source_size_bytes"] = _safe_int(data.get("source_size_bytes"), 0)
    data["duration_seconds"] = _safe_float(data.get("duration_seconds"), 0.0)
    data["variants"] = []
    for variant in _variant_rows(conn, asset["id"]):
        item = _row_dict(variant)
        item["width"] = _safe_int(item.get("width"), 0)
        item["height"] = _safe_int(item.get("height"), 0)
        item["bitrate"] = _safe_int(item.get("bitrate"), 0)
        item["segments"] = []
        for segment in _segment_rows(conn, variant["id"]):
            seg = _row_dict(segment)
            seg["sequence_number"] = _safe_int(seg.get("sequence_number"), 0)
            seg["byte_size"] = _safe_int(seg.get("byte_size"), 0)
            seg["duration_seconds"] = _safe_float(seg.get("duration_seconds"), 0.0)
            item["segments"].append(seg)
        data["variants"].append(item)
    return data


def _upsert_asset_row(conn, *, file_row, status, error_message=None):
    now = _now()
    media_type = _file_media_type(file_row)
    existing = _asset_row(conn, file_row["id"])
    if existing:
        conn.execute(
            """
            UPDATE media_stream_assets
            SET source_mode=?, media_type=?, status=?, storage_mode=?, source_mime_type=?, source_size_bytes=?,
                error_message=?, updated_at=?
            WHERE uploaded_file_id=?
            """,
            (
                str(file_row["privacy_mode"] or "standard_plain"),
                media_type,
                status,
                MEDIA_STREAM_STORAGE_MODE,
                str(file_row["mime_type_plain_for_public"] or ""),
                _safe_int(file_row["size_bytes"], 0),
                str(error_message or ""),
                now,
                file_row["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO media_stream_assets (
                uploaded_file_id, source_mode, media_type, status, storage_mode, source_mime_type,
                source_size_bytes, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_row["id"],
                str(file_row["privacy_mode"] or "standard_plain"),
                media_type,
                status,
                MEDIA_STREAM_STORAGE_MODE,
                str(file_row["mime_type_plain_for_public"] or ""),
                _safe_int(file_row["size_bytes"], 0),
                str(error_message or ""),
                now,
                now,
            ),
        )
    return _asset_row(conn, file_row["id"])


def _mark_asset_unavailable(conn, *, file_row, reason):
    asset = _upsert_asset_row(conn, file_row=file_row, status="unavailable", error_message=reason)
    return serialize_stream_asset(conn, asset["uploaded_file_id"])


def _set_asset_ready(conn, *, file_row, master_manifest_path, duration_seconds):
    now = _now()
    conn.execute(
        """
        UPDATE media_stream_assets
        SET status='ready', master_manifest_path=?, duration_seconds=?, error_message='', updated_at=?
        WHERE uploaded_file_id=?
        """,
        (master_manifest_path, float(duration_seconds or 0.0), now, file_row["id"]),
    )
    return _asset_row(conn, file_row["id"])


def _set_asset_failed(conn, *, file_row, reason):
    now = _now()
    conn.execute(
        """
        UPDATE media_stream_assets
        SET status='failed', error_message=?, updated_at=?
        WHERE uploaded_file_id=?
        """,
        (str(reason or "stream build failed"), now, file_row["id"]),
    )
    return _asset_row(conn, file_row["id"])


def _record_job(conn, *, asset_id, status, error_message=None, started_at=None):
    now = _now()
    conn.execute(
        """
        INSERT INTO media_stream_jobs (
            asset_id, job_type, status, started_at, finished_at, error_message, created_at
        ) VALUES (?, 'prepare_hls', ?, ?, ?, ?, ?)
        """,
        (
            int(asset_id),
            str(status),
            str(started_at or now),
            now if status in {"ready", "failed", "unavailable"} else None,
            str(error_message or ""),
            now,
        ),
    )


def _run_probe(source_path, *, ffprobe_bin="ffprobe"):
    cmd = [
        str(ffprobe_bin),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source_path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "{}")


def _parse_probe_metadata(payload):
    streams = payload.get("streams") if isinstance(payload, dict) else []
    fmt = payload.get("format") if isinstance(payload, dict) else {}
    video_stream = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio_stream = next((row for row in streams if row.get("codec_type") == "audio"), None)
    duration_seconds = _safe_float((fmt or {}).get("duration") or (video_stream or {}).get("duration") or (audio_stream or {}).get("duration"), 0.0)
    bitrate = _safe_int((fmt or {}).get("bit_rate") or (video_stream or {}).get("bit_rate") or (audio_stream or {}).get("bit_rate"), 0)
    width = _safe_int((video_stream or {}).get("width"), 0)
    height = _safe_int((video_stream or {}).get("height"), 0)
    codec = (video_stream or audio_stream or {}).get("codec_name") or ""
    media_type = "audio" if video_stream is None and audio_stream is not None else "video"
    return {
        "duration_seconds": duration_seconds,
        "bitrate": bitrate,
        "width": width,
        "height": height,
        "codec": str(codec),
        "media_type": media_type,
    }


def _write_master_manifest(target, *, variant_name, playlist_name="playlist.m3u8", bitrate=0, width=0, height=0, codec=""):
    codecs = codec or ("mp4a.40.2" if not width and not height else "avc1.64001f,mp4a.40.2")
    bandwidth = max(int(bitrate or 0), 128000)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
    ]
    attrs = [f"BANDWIDTH={bandwidth}"]
    if width and height:
        attrs.append(f"RESOLUTION={int(width)}x{int(height)}")
    if codecs:
        attrs.append(f'CODECS="{codecs}"')
    lines.append("#EXT-X-STREAM-INF:" + ",".join(attrs))
    lines.append(f"{variant_name}/{playlist_name}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_ffmpeg_hls(source_path, *, derivative_dir, media_type, ffmpeg_bin="ffmpeg", segment_seconds=DEFAULT_HLS_SEGMENT_SECONDS):
    variant_name = "audio" if media_type == "audio" else "source"
    variant_dir = Path(derivative_dir) / variant_name
    variant_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = variant_dir / "playlist.m3u8"
    segment_pattern = str(variant_dir / "seg_%05d.m4s")
    cmd = [
        str(ffmpeg_bin),
        "-y",
        "-i",
        str(source_path),
    ]
    if media_type == "audio":
        cmd.extend(["-vn", "-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "160k"])
    cmd.extend([
        "-f",
        "hls",
        "-hls_time",
        str(int(segment_seconds)),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_type",
        "fmp4",
        "-hls_fmp4_init_filename",
        "init.mp4",
        "-hls_flags",
        "independent_segments",
        "-hls_segment_filename",
        segment_pattern,
        str(playlist_path),
    ])
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return variant_name, playlist_path, variant_dir / "init.mp4"


def _parse_variant_playlist(playlist_path):
    rows = []
    current_duration = 0.0
    init_name = ""
    for raw_line in Path(playlist_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            marker = 'URI="'
            start = line.find(marker)
            if start >= 0:
                start += len(marker)
                end = line.find('"', start)
                if end > start:
                    init_name = line[start:end]
        elif line.startswith("#EXTINF:"):
            value = line.split(":", 1)[1].split(",", 1)[0].strip()
            current_duration = _safe_float(value, 0.0)
        elif not line.startswith("#"):
            rows.append({
                "filename": line,
                "duration_seconds": current_duration,
            })
            current_duration = 0.0
    return init_name, rows


def prepare_stream_asset(
    conn,
    *,
    file_row,
    storage_root,
    server_file_fernet=None,
    ffprobe_bin="ffprobe",
    ffmpeg_bin="ffmpeg",
):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        raise ValueError("file not found")
    if is_e2ee_file(file_row):
        return _mark_asset_unavailable(conn, file_row=file_row, reason="strict E2EE files cannot generate server-side HLS")
    asset = _upsert_asset_row(conn, file_row=file_row, status="processing")
    started_at = _now()
    derivative_root_rel = _derivative_root_relpath(file_row["id"])
    derivative_root = resolve_storage_path(storage_root, derivative_root_rel, create_parent=True)
    if derivative_root.exists():
        shutil.rmtree(derivative_root)
    derivative_root.mkdir(parents=True, exist_ok=True)
    conn.execute("DELETE FROM media_stream_segments WHERE variant_id IN (SELECT id FROM media_stream_variants WHERE asset_id=?)", (int(asset["id"]),))
    conn.execute("DELETE FROM media_stream_variants WHERE asset_id=?", (int(asset["id"]),))
    with tempfile.TemporaryDirectory(prefix=f"hackme_stream_{file_row['id']}_") as temp_dir:
        source_path = resolve_file_storage_path(storage_root, file_row)
        prepared_source = source_path
        if is_server_encrypted_file(file_row):
            payload = decrypt_server_encrypted_bytes(source_path, server_file_fernet)
            temp_source = Path(temp_dir) / (str(file_row["original_filename_plain_for_public"] or file_row["id"]) or "media.bin")
            temp_source.write_bytes(payload)
            prepared_source = temp_source
        try:
            probe_payload = _run_probe(prepared_source, ffprobe_bin=ffprobe_bin)
            metadata = _parse_probe_metadata(probe_payload)
            variant_name, playlist_path, init_segment_path = _run_ffmpeg_hls(
                prepared_source,
                derivative_dir=derivative_root,
                media_type=metadata["media_type"],
                ffmpeg_bin=ffmpeg_bin,
            )
            master_manifest_path = derivative_root / "master.m3u8"
            _write_master_manifest(
                master_manifest_path,
                variant_name=variant_name,
                bitrate=metadata["bitrate"],
                width=metadata["width"],
                height=metadata["height"],
                codec=metadata["codec"],
            )
            init_name, segments = _parse_variant_playlist(playlist_path)
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO media_stream_variants (
                    asset_id, name, width, height, bitrate, codec, playlist_path, init_segment_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(asset["id"]),
                    variant_name,
                    int(metadata["width"] or 0),
                    int(metadata["height"] or 0),
                    int(metadata["bitrate"] or 0),
                    str(metadata["codec"] or ""),
                    f"{derivative_root_rel}/{variant_name}/playlist.m3u8",
                    f"{derivative_root_rel}/{variant_name}/{init_name}" if init_name else "",
                    now,
                ),
            )
            variant_id = cur.lastrowid
            for index, segment in enumerate(segments, start=1):
                segment_rel = f"{derivative_root_rel}/{variant_name}/{segment['filename']}"
                segment_file = resolve_storage_path(storage_root, segment_rel)
                conn.execute(
                    """
                    INSERT INTO media_stream_segments (
                        variant_id, sequence_number, filename, path, duration_seconds, byte_size, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(variant_id),
                        index,
                        str(segment["filename"]),
                        segment_rel,
                        float(segment["duration_seconds"] or 0.0),
                        int(segment_file.stat().st_size if segment_file.exists() else 0),
                        now,
                    ),
                )
            asset = _set_asset_ready(
                conn,
                file_row=file_row,
                master_manifest_path=f"{derivative_root_rel}/master.m3u8",
                duration_seconds=metadata["duration_seconds"],
            )
            _record_job(conn, asset_id=asset["id"], status="ready", started_at=started_at)
            return serialize_stream_asset(conn, file_row["id"])
        except Exception as exc:
            asset = _set_asset_failed(conn, file_row=file_row, reason=str(exc))
            _record_job(conn, asset_id=asset["id"], status="failed", error_message=str(exc), started_at=started_at)
            raise


def get_stream_status(conn, *, file_row):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        return None
    asset = serialize_stream_asset(conn, file_row["id"])
    if asset:
        return asset
    if is_e2ee_file(file_row):
        return {
            "uploaded_file_id": file_row["id"],
            "source_mode": str(file_row["privacy_mode"] or "e2ee"),
            "media_type": _file_media_type(file_row),
            "status": "unavailable",
            "storage_mode": MEDIA_STREAM_STORAGE_MODE,
            "master_manifest_path": "",
            "duration_seconds": 0.0,
            "source_mime_type": str(file_row["mime_type_plain_for_public"] or mimetypes.guess_type(str(file_row["original_filename_plain_for_public"] or ""))[0] or ""),
            "source_size_bytes": _safe_int(file_row["size_bytes"], 0),
            "error_message": "strict E2EE files cannot generate server-side HLS",
            "variants": [],
        }
    return {
        "uploaded_file_id": file_row["id"],
        "source_mode": str(file_row["privacy_mode"] or "standard_plain"),
        "media_type": _file_media_type(file_row),
        "status": "pending",
        "storage_mode": MEDIA_STREAM_STORAGE_MODE,
        "master_manifest_path": "",
        "duration_seconds": 0.0,
        "source_mime_type": str(file_row["mime_type_plain_for_public"] or mimetypes.guess_type(str(file_row["original_filename_plain_for_public"] or ""))[0] or ""),
        "source_size_bytes": _safe_int(file_row["size_bytes"], 0),
        "error_message": "",
        "variants": [],
    }


def stream_playback_payload(conn, *, file_row, video_id):
    status = get_stream_status(conn, file_row=file_row)
    media_type = _file_media_type(file_row)
    direct_url = f"/api/videos/{int(video_id)}/stream"
    payload = {
        "mode": "direct",
        "media_type": media_type,
        "source_mode": str(file_row["privacy_mode"] or "standard_plain"),
        "fallback_url": direct_url,
        "stream_url": direct_url,
        "master_url": "",
        "status": status,
    }
    if status and status.get("status") == "ready" and status.get("master_manifest_path"):
        payload["mode"] = "hls"
        payload["master_url"] = f"/api/videos/{int(video_id)}/hls/master.m3u8"
    return payload
