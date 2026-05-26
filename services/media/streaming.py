import json
import mimetypes
import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from services.storage.cloud_drive import (
    is_e2ee_file,
    is_server_encrypted_file,
    resolve_file_storage_path,
    write_decrypted_server_encrypted_file,
)
from services.storage.paths import resolve_storage_path


MEDIA_STREAM_ASSET_STATUSES = {"pending", "processing", "ready", "failed", "unavailable"}
MEDIA_STREAM_STORAGE_MODE = "acl_protected_plain"
HLS_JS_URL = "/js/hls.light.min.js?v=20260505-hlsjs"
DEFAULT_HLS_SEGMENT_SECONDS = 4
DEFAULT_STREAM_AUTO_PREPARE_AUDIO_MIN_BYTES = 25 * 1024 * 1024
DEFAULT_FFMPEG_THREADS = 1
DEFAULT_FFMPEG_TIMEOUT_SECONDS = 60 * 60
DEFAULT_FFMPEG_PRESET = "ultrafast"
DEFAULT_FFMPEG_MAX_VIDEO_HEIGHT = 0
DEFAULT_HLS_QUALITY_HEIGHTS = "480,720"
HLS_DERIVATIVES_QUOTA_EXEMPT = True
STRICT_E2EE_SERVER_TRANSCODE_DISABLED_REASON = (
    "strict E2EE files cannot generate server-side HLS or server-side transcode derivatives"
)


def _now():
    return datetime.now().replace(microsecond=0).isoformat()


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
        CREATE TABLE IF NOT EXISTS media_stream_subtitles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES media_stream_assets(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            label TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'und',
            codec TEXT,
            path TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_media_stream_subtitles_asset ON media_stream_subtitles(asset_id, name)")
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


def _safe_commit(conn):
    try:
        conn.commit()
    except Exception:
        pass


def _bounded_env_int(name, default, *, min_value, max_value):
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None else int(default)
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _ffmpeg_thread_count():
    return _bounded_env_int("HACKME_MEDIA_FFMPEG_THREADS", DEFAULT_FFMPEG_THREADS, min_value=1, max_value=4)


def _ffmpeg_preset():
    allowed = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium"}
    value = str(os.environ.get("HACKME_MEDIA_FFMPEG_PRESET") or DEFAULT_FFMPEG_PRESET).strip().lower()
    return value if value in allowed else DEFAULT_FFMPEG_PRESET


def _ffmpeg_copy_first_enabled():
    raw = os.environ.get("HACKME_MEDIA_HLS_COPY_FIRST", "1")
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _ffmpeg_max_video_height():
    return _bounded_env_int(
        "HACKME_MEDIA_FFMPEG_MAX_VIDEO_HEIGHT",
        DEFAULT_FFMPEG_MAX_VIDEO_HEIGHT,
        min_value=0,
        max_value=2160,
    )


def _hls_quality_heights():
    raw = str(os.environ.get("HACKME_MEDIA_HLS_QUALITY_HEIGHTS") or DEFAULT_HLS_QUALITY_HEIGHTS)
    values = []
    for part in raw.replace(";", ",").split(","):
        try:
            height = int(str(part or "").strip().lower().replace("p", ""))
        except Exception:
            continue
        if height in {2160, 1440, 1080, 720, 480, 360} and height not in values:
            values.append(height)
    return values


def _ffmpeg_maxrate_multiplier():
    raw = os.environ.get("HACKME_MEDIA_HLS_MAXRATE_MULTIPLIER")
    try:
        value = float(raw) if raw is not None else 1.15
    except Exception:
        value = 1.15
    return max(1.0, min(2.0, value))


def _ffmpeg_bufsize_multiplier():
    raw = os.environ.get("HACKME_MEDIA_HLS_BUFSIZE_MULTIPLIER")
    try:
        value = float(raw) if raw is not None else 2.0
    except Exception:
        value = 2.0
    return max(1.0, min(4.0, value))


def _ffmpeg_timeout_seconds():
    return _bounded_env_int(
        "HACKME_MEDIA_FFMPEG_TIMEOUT_SECONDS",
        DEFAULT_FFMPEG_TIMEOUT_SECONDS,
        min_value=60,
        max_value=24 * 60 * 60,
    )


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


def should_auto_prepare_stream(file_row, *, visibility="public"):
    if not file_row or _row_value(file_row, "deleted_at") or is_e2ee_file(file_row):
        return {"enabled": False, "reason": "unavailable"}
    media_type = _file_media_type(file_row)
    privacy_mode = str(_row_value(file_row, "privacy_mode", "standard_plain") or "standard_plain")
    visibility = str(visibility or "public").strip().lower() or "public"
    size_bytes = _safe_int(_row_value(file_row, "size_bytes"), 0)
    if privacy_mode == "server_encrypted":
        return {
            "enabled": True,
            "reason": "server_encrypted_media",
            "media_type": media_type,
        }
    if media_type == "video" and visibility in {"public", "unlisted"}:
        return {
            "enabled": True,
            "reason": "published_video",
            "media_type": media_type,
        }
    if media_type == "audio" and visibility in {"public", "unlisted"} and size_bytes >= DEFAULT_STREAM_AUTO_PREPARE_AUDIO_MIN_BYTES:
        return {
            "enabled": True,
            "reason": "large_published_audio",
            "media_type": media_type,
        }
    return {
        "enabled": False,
        "reason": "manual_prepare_only",
        "media_type": media_type,
    }


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


def _subtitle_rows(conn, asset_id):
    return conn.execute(
        "SELECT * FROM media_stream_subtitles WHERE asset_id=? ORDER BY is_default DESC, id ASC",
        (int(asset_id),),
    ).fetchall()


def _segment_summary(conn, variant_id):
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS segment_count,
            COALESCE(SUM(byte_size), 0) AS segments_total_bytes,
            COALESCE(SUM(duration_seconds), 0) AS segments_total_duration_seconds
        FROM media_stream_segments
        WHERE variant_id=?
        """,
        (int(variant_id),),
    ).fetchone()
    return {
        "segment_count": _safe_int(row["segment_count"] if row else 0, 0),
        "segments_total_bytes": _safe_int(row["segments_total_bytes"] if row else 0, 0),
        "segments_total_duration_seconds": _safe_float(row["segments_total_duration_seconds"] if row else 0.0, 0.0),
    }


def serialize_stream_asset(conn, uploaded_file_id, *, include_segments=True):
    ensure_media_stream_schema(conn)
    asset = _asset_row(conn, uploaded_file_id)
    if not asset:
        return None
    data = _row_dict(asset)
    data["source_size_bytes"] = _safe_int(data.get("source_size_bytes"), 0)
    data["duration_seconds"] = _safe_float(data.get("duration_seconds"), 0.0)
    data["variants"] = []
    data["subtitles"] = []
    for variant in _variant_rows(conn, asset["id"]):
        item = _row_dict(variant)
        item["width"] = _safe_int(item.get("width"), 0)
        item["height"] = _safe_int(item.get("height"), 0)
        item["bitrate"] = _safe_int(item.get("bitrate"), 0)
        item["segment_count"] = 0
        item["segments_total_bytes"] = 0
        item["segments_total_duration_seconds"] = 0.0
        item["segments"] = []
        if include_segments:
            segment_rows = _segment_rows(conn, variant["id"])
            item["segment_count"] = len(segment_rows)
            for segment in segment_rows:
                byte_size = _safe_int(segment["byte_size"], 0)
                duration_seconds = _safe_float(segment["duration_seconds"], 0.0)
                item["segments_total_bytes"] += byte_size
                item["segments_total_duration_seconds"] += duration_seconds
                seg = _row_dict(segment)
                seg["sequence_number"] = _safe_int(seg.get("sequence_number"), 0)
                seg["byte_size"] = byte_size
                seg["duration_seconds"] = duration_seconds
                item["segments"].append(seg)
        else:
            item.update(_segment_summary(conn, variant["id"]))
        data["variants"].append(item)
    for subtitle in _subtitle_rows(conn, asset["id"]):
        item = _row_dict(subtitle)
        item["is_default"] = bool(_safe_int(item.get("is_default"), 0))
        data["subtitles"].append(item)
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


def mark_stream_asset_processing(conn, *, file_row, error_message=""):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        raise ValueError("file not found")
    if is_e2ee_file(file_row):
        return _mark_asset_unavailable(conn, file_row=file_row, reason=STRICT_E2EE_SERVER_TRANSCODE_DISABLED_REASON)
    asset = _upsert_asset_row(conn, file_row=file_row, status="processing", error_message=error_message)
    return serialize_stream_asset(conn, asset["uploaded_file_id"])


def _set_asset_ready(conn, *, file_row, master_manifest_path, duration_seconds, warning_message=""):
    now = _now()
    conn.execute(
        """
        UPDATE media_stream_assets
        SET status='ready', master_manifest_path=?, duration_seconds=?, error_message=?, updated_at=?
        WHERE uploaded_file_id=?
        """,
        (master_manifest_path, float(duration_seconds or 0.0), str(warning_message or ""), now, file_row["id"]),
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


def _record_job(conn, *, asset_id, status, error_message=None, started_at=None, job_type="prepare_hls"):
    now = _now()
    conn.execute(
        """
        INSERT INTO media_stream_jobs (
            asset_id, job_type, status, started_at, finished_at, error_message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(asset_id),
            str(job_type or "prepare_hls"),
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
    codec_tag = (video_stream or audio_stream or {}).get("codec_tag_string") or ""
    audio_codec = (audio_stream or {}).get("codec_name") or ""
    audio_codec_tag = (audio_stream or {}).get("codec_tag_string") or ""
    media_type = "audio" if video_stream is None and audio_stream is not None else "video"
    subtitle_streams = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
        subtitle_streams.append({
            "index": _safe_int(stream.get("index"), -1),
            "codec": str(stream.get("codec_name") or ""),
            "language": str(tags.get("language") or "und").strip()[:16] or "und",
            "title": str(tags.get("title") or "").strip()[:80],
            "is_default": bool(_safe_int(disposition.get("default"), 0)),
        })
    return {
        "duration_seconds": duration_seconds,
        "bitrate": bitrate,
        "width": width,
        "height": height,
        "codec": str(codec),
        "codec_tag": str(codec_tag),
        "audio_codec": str(audio_codec),
        "audio_codec_tag": str(audio_codec_tag),
        "media_type": media_type,
        "subtitle_streams": subtitle_streams,
    }


def _subtitle_language(value):
    text = str(value or "und").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "", text)[:16]
    return text or "und"


def _subtitle_label(stream, index):
    title = str((stream or {}).get("title") or "").strip()
    language = _subtitle_language((stream or {}).get("language"))
    if title:
        return title[:80]
    if language != "und":
        return f"字幕 {index} ({language})"
    return f"字幕 {index}"


def _subtitle_codec_supported(codec):
    return str(codec or "").strip().lower() in {
        "ass",
        "ssa",
        "subrip",
        "srt",
        "mov_text",
        "webvtt",
        "text",
    }


def _extract_subtitles_to_webvtt(source_path, *, derivative_dir, derivative_root_rel, metadata, ffmpeg_bin="ffmpeg"):
    subtitle_streams = list((metadata or {}).get("subtitle_streams") or [])
    subtitle_dir = Path(derivative_dir) / "subtitles"
    rows = []
    errors = []
    supported_index = 0
    for stream in subtitle_streams[:20]:
        codec = str(stream.get("codec") or "").strip().lower()
        stream_index = _safe_int(stream.get("index"), -1)
        if stream_index < 0:
            continue
        if not _subtitle_codec_supported(codec):
            errors.append(f"subtitle stream {stream_index}: unsupported codec {codec or 'unknown'}")
            continue
        supported_index += 1
        language = _subtitle_language(stream.get("language"))
        name = f"sub{supported_index:02d}_{language}"
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        output_path = subtitle_dir / f"{name}.vtt"
        cmd = [
            str(ffmpeg_bin),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-map",
            f"0:{stream_index}",
            "-vn",
            "-an",
            "-c:s",
            "webvtt",
            str(output_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=_ffmpeg_timeout_seconds())
        except Exception as exc:
            errors.append(f"subtitle stream {stream_index}: {str(exc)[:180]}")
            continue
        if not output_path.exists() or output_path.stat().st_size <= 0:
            errors.append(f"subtitle stream {stream_index}: empty WebVTT output")
            continue
        rows.append({
            "name": name,
            "label": _subtitle_label(stream, supported_index),
            "language": language,
            "codec": codec,
            "path": f"{derivative_root_rel}/subtitles/{name}.vtt",
            "is_default": bool(stream.get("is_default")) or supported_index == 1,
            "absolute_path": output_path,
        })
    return rows, errors


def _srt_text_to_webvtt(text):
    lines = ["WEBVTT", ""]
    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw
        if "-->" in line:
            line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def parse_subtitle_shift_ms(value, *, min_ms=-60 * 60 * 1000, max_ms=60 * 60 * 1000):
    try:
        if value is None or value == "":
            return 0
        parsed = int(round(float(value)))
    except Exception:
        return 0
    return max(int(min_ms), min(int(max_ms), parsed))


def _format_webvtt_timestamp(total_ms):
    total = max(0, int(round(total_ms or 0)))
    hours, remainder = divmod(total, 60 * 60 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _webvtt_timestamp_to_ms(match):
    hours = _safe_int(match.group("hours"), 0)
    minutes = _safe_int(match.group("minutes"), 0)
    seconds = _safe_int(match.group("seconds"), 0)
    millis = _safe_int(match.group("millis"), 0)
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


WEBVTT_TIMESTAMP_RE = re.compile(
    r"(?:(?P<hours>\d{2,}):)?(?P<minutes>\d{2}):(?P<seconds>\d{2})\.(?P<millis>\d{3})"
)


def shift_webvtt_text(text, shift_ms):
    offset = parse_subtitle_shift_ms(shift_ms)
    if not offset:
        return str(text or "")
    shifted = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if "-->" not in raw_line:
            shifted.append(raw_line)
            continue
        shifted.append(WEBVTT_TIMESTAMP_RE.sub(lambda match: _format_webvtt_timestamp(_webvtt_timestamp_to_ms(match) + offset), raw_line))
    return "\n".join(shifted)


def _normalize_uploaded_subtitle_to_webvtt(source_path, output_path, *, original_filename="", ffmpeg_bin="ffmpeg"):
    suffix = Path(original_filename or source_path).suffix.lower()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".vtt":
        text = Path(source_path).read_text(encoding="utf-8", errors="replace")
        if not text.lstrip().upper().startswith("WEBVTT"):
            text = "WEBVTT\n\n" + text
        output_path.write_text(text, encoding="utf-8")
        return
    if suffix == ".srt":
        text = Path(source_path).read_text(encoding="utf-8", errors="replace")
        output_path.write_text(_srt_text_to_webvtt(text), encoding="utf-8")
        return
    if suffix in {".ass", ".ssa"}:
        cmd = [
            str(ffmpeg_bin),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-c:s",
            "webvtt",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=_ffmpeg_timeout_seconds())
        return
    raise ValueError("unsupported subtitle format; use .srt, .vtt, .ass, or .ssa")


def add_stream_subtitle(
    conn,
    *,
    file_row,
    storage_root,
    subtitle_file_path,
    original_filename="",
    label="",
    language="und",
    ffmpeg_bin="ffmpeg",
):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        raise ValueError("file not found")
    if is_e2ee_file(file_row):
        raise ValueError("strict E2EE media subtitles must be prepared by the browser-side E2EE package")
    existing = _asset_row(conn, file_row["id"])
    asset = _upsert_asset_row(
        conn,
        file_row=file_row,
        status=str(existing["status"] if existing else "pending"),
        error_message=(existing["error_message"] if existing else None),
    )
    derivative_root_rel = _derivative_root_relpath(file_row["id"])
    derivative_root = resolve_storage_path(storage_root, derivative_root_rel, create_parent=True)
    subtitle_dir = derivative_root / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    language = _subtitle_language(language)
    name = f"user_{uuid.uuid4().hex[:12]}_{language}"
    output_path = subtitle_dir / f"{name}.vtt"
    _normalize_uploaded_subtitle_to_webvtt(
        subtitle_file_path,
        output_path,
        original_filename=original_filename,
        ffmpeg_bin=ffmpeg_bin,
    )
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise ValueError("subtitle conversion produced an empty file")
    now = _now()
    has_existing = conn.execute(
        "SELECT 1 FROM media_stream_subtitles WHERE asset_id=? LIMIT 1",
        (int(asset["id"]),),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO media_stream_subtitles (
            asset_id, name, label, language, codec, path, is_default, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(asset["id"]),
            name,
            str(label or Path(original_filename or "").stem or language or "字幕")[:80],
            language,
            Path(original_filename or "").suffix.lower().lstrip(".") or "webvtt",
            f"{derivative_root_rel}/subtitles/{name}.vtt",
            0 if has_existing else 1,
            now,
        ),
    )
    return serialize_stream_asset(conn, file_row["id"], include_segments=False)


def refresh_stream_subtitles(
    conn,
    *,
    file_row,
    storage_root,
    server_file_fernet=None,
    source_path_override=None,
    force=False,
    ffprobe_bin="ffprobe",
    ffmpeg_bin="ffmpeg",
    progress_callback=None,
):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        raise ValueError("file not found")
    if is_e2ee_file(file_row):
        raise ValueError("strict E2EE media subtitles must be prepared by the browser-side E2EE package")
    asset = _asset_row(conn, file_row["id"])
    if not asset or str(asset["status"] or "") != "ready":
        raise ValueError("HLS asset must be ready before refreshing subtitles")
    existing = _subtitle_rows(conn, asset["id"])
    if existing and not force:
        return serialize_stream_asset(conn, file_row["id"], include_segments=False)

    derivative_root_rel = _derivative_root_relpath(file_row["id"])
    derivative_root = resolve_storage_path(storage_root, derivative_root_rel, create_parent=True)
    derivative_root.mkdir(parents=True, exist_ok=True)
    started_at = _now()
    try:
        with tempfile.TemporaryDirectory(prefix=f"hackme_stream_subtitles_{file_row['id']}_") as temp_dir:
            prepared_source = Path(source_path_override) if source_path_override else resolve_file_storage_path(storage_root, file_row)
            if source_path_override is None and is_server_encrypted_file(file_row):
                if progress_callback:
                    progress_callback(10, "decrypting", "正在解密伺服器端加密影音以抽取字幕。")
                source_path = resolve_file_storage_path(storage_root, file_row)
                temp_source = Path(temp_dir) / (str(file_row["original_filename_plain_for_public"] or file_row["id"]) or "media.bin")
                write_decrypted_server_encrypted_file(
                    source_path,
                    temp_source,
                    server_file_fernet,
                    progress_callback=(
                        (lambda written, total: progress_callback(
                            10 + int((max(0, min(int(written or 0), int(total or 0))) / max(1, int(total or 0))) * 45),
                            "decrypting",
                            f"正在解密伺服器端加密影音以抽取字幕：{_format_bytes_short(written)} / {_format_bytes_short(total)}。",
                        ))
                        if progress_callback else None
                    ),
                )
                prepared_source = temp_source
            if progress_callback:
                progress_callback(60, "probing", "正在讀取字幕軌資訊。")
            probe_payload = _run_probe(prepared_source, ffprobe_bin=ffprobe_bin)
            metadata = _parse_probe_metadata(probe_payload)
            if progress_callback:
                progress_callback(75, "extracting", "正在轉換字幕為 WebVTT。")
            subtitle_rows, subtitle_errors = _extract_subtitles_to_webvtt(
                prepared_source,
                derivative_dir=derivative_root,
                derivative_root_rel=derivative_root_rel,
                metadata=metadata,
                ffmpeg_bin=ffmpeg_bin,
            )
        now = _now()
        conn.execute(
            "DELETE FROM media_stream_subtitles WHERE asset_id=?",
            (int(asset["id"]),),
        )
        for subtitle in subtitle_rows:
            conn.execute(
                """
                INSERT INTO media_stream_subtitles (
                    asset_id, name, label, language, codec, path, is_default, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(asset["id"]),
                    str(subtitle.get("name") or ""),
                    str(subtitle.get("label") or ""),
                    str(subtitle.get("language") or "und"),
                    str(subtitle.get("codec") or ""),
                    str(subtitle.get("path") or ""),
                    1 if subtitle.get("is_default") else 0,
                    now,
                ),
            )
        warning = "; ".join(subtitle_errors or [])[:800]
        conn.execute(
            """
            UPDATE media_stream_assets
            SET error_message=?, updated_at=?
            WHERE id=?
            """,
            (warning, now, int(asset["id"])),
        )
        _record_job(
            conn,
            asset_id=asset["id"],
            status="ready" if subtitle_rows else "failed",
            error_message=warning,
            started_at=started_at,
            job_type="refresh_subtitles",
        )
        _safe_commit(conn)
        if progress_callback:
            progress_callback(100, "ready" if subtitle_rows else "failed", "字幕抽取完成。" if subtitle_rows else "沒有可用的文字字幕軌。")
        return serialize_stream_asset(conn, file_row["id"], include_segments=False)
    except Exception as exc:
        _record_job(
            conn,
            asset_id=asset["id"],
            status="failed",
            error_message=str(exc),
            started_at=started_at,
            job_type="refresh_subtitles",
        )
        _safe_commit(conn)
        raise


def hls_codec_string(*, width=0, height=0, codec=""):
    raw = str(codec or "").strip().lower()
    if raw.startswith(("avc1.", "avc3.", "mp4a.")):
        return str(codec).strip()
    if raw in {"mp4a", "aac"}:
        return "mp4a.40.2"
    if raw in {"av1", "av01"} or "av01" in raw:
        return "av01.0.12M.08,mp4a.40.2" if width or height else "av01.0.12M.08"
    if not width and not height:
        return "mp4a.40.2"
    return "avc1.64001f,mp4a.40.2"


def repair_hls_master_manifest_text(text):
    repaired = []
    for raw_line in str(text or "").splitlines():
        line = raw_line
        if line.startswith("#EXT-X-STREAM-INF:"):
            if 'CODECS="' in line:
                start = line.find('CODECS="') + len('CODECS="')
                end = line.find('"', start)
                codec_value = line[start:end] if end > start else ""
                normalized = hls_codec_string(width=1, height=1, codec=codec_value)
                if normalized != codec_value and end > start:
                    line = line[:start] + normalized + line[end:]
            elif "RESOLUTION=" in line:
                line = f'{line},CODECS="{hls_codec_string(width=1, height=1)}"'
            else:
                line = f'{line},CODECS="{hls_codec_string(width=0, height=0)}"'
        repaired.append(line)
    return "\n".join(repaired) + ("\n" if repaired else "")


def _write_master_manifest(target, *, variant_name, playlist_name="playlist.m3u8", bitrate=0, width=0, height=0, codec=""):
    _write_master_manifest_variants(
        target,
        [{
            "name": variant_name,
            "playlist_name": playlist_name,
            "bitrate": bitrate,
            "width": width,
            "height": height,
            "codec": codec,
        }],
    )


def _write_master_manifest_variants(target, variants):
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
    ]
    for variant in variants or []:
        name = str(variant.get("name") or "source").strip() or "source"
        playlist_name = str(variant.get("playlist_name") or "playlist.m3u8")
        width = _safe_int(variant.get("width"), 0)
        height = _safe_int(variant.get("height"), 0)
        codecs = hls_codec_string(width=width, height=height, codec=variant.get("codec") or "")
        bandwidth = max(int(variant.get("bitrate") or 0), 128000)
        attrs = [f"BANDWIDTH={bandwidth}"]
        if width and height:
            attrs.append(f"RESOLUTION={int(width)}x{int(height)}")
        if codecs:
            attrs.append(f'CODECS="{codecs}"')
        lines.append("#EXT-X-STREAM-INF:" + ",".join(attrs))
        lines.append(f"{name}/{playlist_name}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _metadata_supports_stream_copy(metadata):
    if not _ffmpeg_copy_first_enabled():
        return False
    media_type = str((metadata or {}).get("media_type") or "")
    codec = str((metadata or {}).get("codec") or "").lower()
    codec_tag = str((metadata or {}).get("codec_tag") or "").lower()
    audio_codec = str((metadata or {}).get("audio_codec") or "").lower()
    audio_codec_tag = str((metadata or {}).get("audio_codec_tag") or "").lower()
    if media_type == "audio":
        return codec in {"aac", "mp3", "alac", "flac"} or codec_tag in {"mp4a", "mp3"}
    if codec not in {"h264", "avc1", "av1", "hevc", "h265"} and codec_tag not in {"avc1", "av01", "hvc1", "hev1"}:
        return False
    if audio_codec and audio_codec not in {"aac", "mp3"} and audio_codec_tag not in {"mp4a", "mp3"}:
        return False
    return True


def _target_bitrate_for_height(height, source_bitrate=0):
    targets = {
        2160: 12_000_000,
        1440: 8_000_000,
        1080: 5_000_000,
        720: 2_800_000,
        480: 1_400_000,
        360: 800_000,
    }
    target = targets.get(int(height or 0), 2_800_000)
    source = int(source_bitrate or 0)
    if source > 0:
        return max(320_000, min(target, source))
    return target


def _ffmpeg_bitrate_args(target_bitrate):
    target = _safe_int(target_bitrate, 0)
    if target <= 0:
        return []
    maxrate = max(target, int(round(target * _ffmpeg_maxrate_multiplier())))
    bufsize = max(target, int(round(target * _ffmpeg_bufsize_multiplier())))
    return [
        "-b:v",
        str(target),
        "-maxrate",
        str(maxrate),
        "-bufsize",
        str(bufsize),
    ]


def _scaled_width(source_width, source_height, target_height):
    try:
        width = int(round(float(source_width or 0) * float(target_height or 0) / float(source_height or 1)))
    except Exception:
        width = 0
    if width <= 0:
        return 0
    return max(2, width - (width % 2))


def _hls_variant_specs(metadata):
    media_type = str((metadata or {}).get("media_type") or "")
    source_width = _safe_int((metadata or {}).get("width"), 0)
    source_height = _safe_int((metadata or {}).get("height"), 0)
    source_bitrate = _safe_int((metadata or {}).get("bitrate"), 0)
    if media_type == "audio":
        return [{
            "name": "audio",
            "label": "原音質",
            "width": 0,
            "height": 0,
            "bitrate": source_bitrate,
            "codec": metadata.get("codec_tag") or metadata.get("codec") or "",
            "copy_codecs": _metadata_supports_stream_copy(metadata),
            "target_height": 0,
        }]
    specs = [{
        "name": "original",
        "label": f"原畫質 {source_height}p" if source_height else "原畫質",
        "width": source_width,
        "height": source_height,
        "bitrate": source_bitrate,
        "codec": metadata.get("codec_tag") or metadata.get("codec") or "",
        "copy_codecs": _metadata_supports_stream_copy(metadata),
        "target_height": 0,
    }]
    for height in _hls_quality_heights():
        if source_height and source_height <= height:
            continue
        specs.append({
            "name": f"q{height}",
            "label": f"{height}p",
            "width": _scaled_width(source_width, source_height, height),
            "height": height,
            "bitrate": _target_bitrate_for_height(height, source_bitrate),
            "codec": "h264",
            "copy_codecs": False,
            "target_height": height,
        })
    return specs


def _run_ffmpeg_hls(
    source_path,
    *,
    derivative_dir,
    media_type,
    variant_name=None,
    ffmpeg_bin="ffmpeg",
    segment_seconds=DEFAULT_HLS_SEGMENT_SECONDS,
    duration_seconds=0,
    source_height=0,
    target_height=0,
    target_bitrate=0,
    copy_codecs=False,
    progress_callback=None,
):
    variant_name = str(variant_name or ("audio" if media_type == "audio" else "source")).strip() or "source"
    variant_dir = Path(derivative_dir) / variant_name
    variant_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = variant_dir / "playlist.m3u8"
    segment_pattern = str(variant_dir / "seg_%05d.m4s")
    cmd = [
        str(ffmpeg_bin),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
        "-i",
        str(source_path),
    ]
    if media_type == "audio":
        cmd.extend(["-map", "0:a:0?", "-sn", "-dn"])
    else:
        cmd.extend(["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"])
    if copy_codecs:
        cmd.extend(["-c", "copy"])
    elif media_type == "audio":
        cmd.extend(["-vn", "-c:a", "aac", "-b:a", "128k"])
    else:
        max_height = _ffmpeg_max_video_height()
        scale_height = int(target_height or 0)
        if not scale_height and max_height and int(source_height or 0) > max_height:
            scale_height = int(max_height)
        cmd.extend([
            "-c:v",
            "libx264",
            "-threads",
            str(_ffmpeg_thread_count()),
            "-preset",
            _ffmpeg_preset(),
        ])
        bitrate_args = _ffmpeg_bitrate_args(target_bitrate)
        if bitrate_args:
            cmd.extend(bitrate_args)
        else:
            cmd.extend(["-crf", "23"])
        if scale_height and int(source_height or 0) > scale_height:
            cmd.extend(["-vf", f"scale=-2:{int(scale_height)}"])
        cmd.extend([
            "-c:a",
            "aac",
            "-b:a",
            "160k",
        ])
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
    timeout_seconds = _ffmpeg_timeout_seconds()
    started_at = time.monotonic()
    def run_hls_command(command):
        process = None
        stderr_chunks = []
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            last_progress = 0.0
            duration = max(0.0, float(duration_seconds or 0))
            while True:
                if timeout_seconds > 0 and time.monotonic() - started_at > timeout_seconds:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                ready, _, _ = select.select([process.stdout], [], [], 0.5) if process.stdout else ([], [], [])
                if ready:
                    line = process.stdout.readline()
                    if not line:
                        if process.poll() is not None:
                            break
                        continue
                    key, _, value = line.strip().partition("=")
                    if key == "out_time_ms" and duration > 0:
                        try:
                            current = max(0.0, min(1.0, float(value or 0) / 1_000_000.0 / duration))
                        except Exception:
                            current = 0.0
                        if current >= last_progress + 0.01:
                            last_progress = current
                            if progress_callback:
                                progress_callback(current)
                    elif key == "progress" and value == "end" and progress_callback:
                        progress_callback(1.0)
                    continue
                if process.poll() is not None:
                    break
            if process.stderr:
                stderr_chunks.append(process.stderr.read() or "")
            return_code = process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command, output="", stderr="".join(stderr_chunks))
        finally:
            if process is not None and process.poll() is None:
                process.kill()

    try:
        run_hls_command(cmd)
    except subprocess.CalledProcessError:
        if copy_codecs:
            shutil.rmtree(variant_dir, ignore_errors=True)
            return _run_ffmpeg_hls(
                source_path,
                derivative_dir=derivative_dir,
                media_type=media_type,
                variant_name=variant_name,
                ffmpeg_bin=ffmpeg_bin,
                segment_seconds=segment_seconds,
                duration_seconds=duration_seconds,
                source_height=source_height,
                target_height=target_height,
                target_bitrate=target_bitrate,
                copy_codecs=False,
                progress_callback=progress_callback,
            )
        raise
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


def _directory_total_bytes(path):
    total = 0
    try:
        for item in Path(path).rglob("*"):
            if item.is_file():
                total += int(item.stat().st_size)
    except Exception:
        return 0
    return total


def _format_bytes_short(value):
    num = _safe_int(value, 0)
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    if num < 1024 * 1024 * 1024:
        return f"{num / 1024 / 1024:.1f} MB"
    return f"{num / 1024 / 1024 / 1024:.2f} GB"


def _preferred_playback_quality_name(variants):
    rows = [variant for variant in (variants or []) if isinstance(variant, dict) and variant.get("name")]
    if not rows:
        return ""
    for height in (720, 480):
        match = next((variant for variant in rows if _safe_int(variant.get("height"), 0) == height), None)
        if match:
            return str(match.get("name") or "")
    non_original = [
        variant for variant in rows
        if str(variant.get("name") or "") not in {"original", "audio"} and _safe_int(variant.get("height"), 0) > 0
    ]
    if non_original:
        non_original.sort(key=lambda item: abs(_safe_int(item.get("height"), 0) - 720))
        return str(non_original[0].get("name") or "")
    return str(rows[0].get("name") or "")


def _fallback_playback_quality_name(variants):
    rows = [variant for variant in (variants or []) if isinstance(variant, dict) and variant.get("name")]
    match = next((variant for variant in rows if _safe_int(variant.get("height"), 0) == 480), None)
    return str(match.get("name") or "") if match else ""


def prepare_stream_asset(
    conn,
    *,
    file_row,
    storage_root,
    server_file_fernet=None,
    ffprobe_bin="ffprobe",
    ffmpeg_bin="ffmpeg",
    progress_callback=None,
):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        raise ValueError("file not found")
    if is_e2ee_file(file_row):
        return _mark_asset_unavailable(conn, file_row=file_row, reason=STRICT_E2EE_SERVER_TRANSCODE_DISABLED_REASON)
    asset = _upsert_asset_row(conn, file_row=file_row, status="processing")
    started_at = _now()
    derivative_root_rel = _derivative_root_relpath(file_row["id"])
    derivative_root = resolve_storage_path(storage_root, derivative_root_rel, create_parent=True)
    conn.execute("DELETE FROM media_stream_segments WHERE variant_id IN (SELECT id FROM media_stream_variants WHERE asset_id=?)", (int(asset["id"]),))
    conn.execute("DELETE FROM media_stream_variants WHERE asset_id=?", (int(asset["id"]),))
    conn.execute("DELETE FROM media_stream_subtitles WHERE asset_id=?", (int(asset["id"]),))
    _safe_commit(conn)
    if derivative_root.exists():
        shutil.rmtree(derivative_root)
    derivative_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"hackme_stream_{file_row['id']}_") as temp_dir:
        source_path = resolve_file_storage_path(storage_root, file_row)
        prepared_source = source_path
        if is_server_encrypted_file(file_row):
            if progress_callback:
                progress_callback(20, "decrypting", "正在以外部程序解密伺服器端加密影音，主站可繼續操作。")
            temp_source = Path(temp_dir) / (str(file_row["original_filename_plain_for_public"] or file_row["id"]) or "media.bin")
            write_decrypted_server_encrypted_file(
                source_path,
                temp_source,
                server_file_fernet,
                progress_callback=(
                    (lambda written, total: progress_callback(
                        20 + int((max(0, min(int(written or 0), int(total or 0))) / max(1, int(total or 0))) * 9),
                        "decrypting",
                        f"正在解密伺服器端加密影音：{_format_bytes_short(written)} / {_format_bytes_short(total)}。",
                    ))
                    if progress_callback else None
                ),
            )
            prepared_source = temp_source
        try:
            if progress_callback:
                progress_callback(30, "probing", "正在讀取影音格式與長度。")
            probe_payload = _run_probe(prepared_source, ffprobe_bin=ffprobe_bin)
            metadata = _parse_probe_metadata(probe_payload)
            copy_codecs = _metadata_supports_stream_copy(metadata)
            subtitle_rows, subtitle_errors = _extract_subtitles_to_webvtt(
                prepared_source,
                derivative_dir=derivative_root,
                derivative_root_rel=derivative_root_rel,
                metadata=metadata,
                ffmpeg_bin=ffmpeg_bin,
            )
            if progress_callback:
                detail = "正在以低負載快速封裝建立 HLS；進度會顯示在任務中心。" if copy_codecs else "正在建立 HLS 播放清單與片段，進度會顯示在任務中心。"
                progress_callback(40, "transcoding", detail)
            variant_specs = _hls_variant_specs(metadata)
            if progress_callback:
                progress_callback(42, "transcoding", f"正在建立 {len(variant_specs)} 組 HLS 畫質。")
            master_manifest_path = derivative_root / "master.m3u8"
            now = _now()
            manifest_rows = []
            variant_errors = list(subtitle_errors or [])
            original_variant_total_bytes = 0
            total_specs = max(1, len(variant_specs))
            for spec_index, spec in enumerate(variant_specs):
                start_percent = 42 + int((spec_index / total_specs) * 48)
                end_percent = 42 + int(((spec_index + 1) / total_specs) * 48)
                if progress_callback:
                    action = "封裝" if spec.get("copy_codecs") else "轉碼"
                    progress_callback(start_percent, "transcoding", f"正在{action} HLS 畫質：{spec.get('label') or spec.get('name')}。")
                try:
                    variant_name, playlist_path, init_segment_path = _run_ffmpeg_hls(
                        prepared_source,
                        derivative_dir=derivative_root,
                        media_type=metadata["media_type"],
                        variant_name=spec["name"],
                        ffmpeg_bin=ffmpeg_bin,
                        duration_seconds=metadata["duration_seconds"],
                        source_height=metadata["height"],
                        target_height=spec.get("target_height") or 0,
                        target_bitrate=spec.get("bitrate") or 0,
                        copy_codecs=bool(spec.get("copy_codecs")),
                        progress_callback=(
                            (lambda ratio, low=start_percent, high=end_percent, label=spec.get("label"), copied=bool(spec.get("copy_codecs")): progress_callback(
                                low + int(max(0.0, min(1.0, float(ratio or 0))) * max(1, high - low)),
                                "transcoding",
                                (f"HLS 外部程序正在低負載封裝 {label}；你可以先做別的事，完成後會通知。"
                                 if copied else
                                 f"HLS 外部程序正在轉碼 {label}；你可以先做別的事，完成後會通知。")
                            ))
                            if progress_callback else None
                        ),
                    )
                except Exception as exc:
                    label = str(spec.get("label") or spec.get("name") or "unknown")
                    if manifest_rows and spec.get("name") not in {"original", "audio"}:
                        variant_errors.append(f"{label}: {str(exc)[:180]}")
                        if progress_callback:
                            progress_callback(
                                end_percent,
                                "transcoding",
                                f"HLS 畫質 {label} 建立失敗，已保留其他可用畫質。",
                            )
                        continue
                    raise
                init_name, segments = _parse_variant_playlist(playlist_path)
                variant_total_bytes = _directory_total_bytes(Path(playlist_path).parent)
                if variant_name == "original":
                    original_variant_total_bytes = variant_total_bytes
                if (
                    variant_name not in {"original", "audio"}
                    and original_variant_total_bytes > 0
                    and variant_total_bytes > original_variant_total_bytes
                ):
                    label = str(spec.get("label") or spec.get("name") or variant_name)
                    variant_errors.append(
                        f"{label}: 衍生檔 {_format_bytes_short(variant_total_bytes)} 大於原畫質 "
                        f"{_format_bytes_short(original_variant_total_bytes)}，已刪除並隱藏"
                    )
                    shutil.rmtree(Path(playlist_path).parent, ignore_errors=True)
                    if progress_callback:
                        progress_callback(
                            end_percent,
                            "transcoding",
                            f"HLS 畫質 {label} 比原畫質更大，已刪除並隱藏該畫質選項。",
                        )
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO media_stream_variants (
                        asset_id, name, width, height, bitrate, codec, playlist_path, init_segment_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(asset["id"]),
                        variant_name,
                        int(spec.get("width") or 0),
                        int(spec.get("height") or 0),
                        int(spec.get("bitrate") or 0),
                        str(spec.get("codec") or metadata["codec"] or ""),
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
                _safe_commit(conn)
                manifest_rows.append({
                    "name": variant_name,
                    "playlist_name": "playlist.m3u8",
                    "bitrate": int(spec.get("bitrate") or 0),
                    "width": int(spec.get("width") or 0),
                    "height": int(spec.get("height") or 0),
                    "codec": spec.get("codec") or metadata.get("codec_tag") or metadata["codec"],
                })
            if progress_callback:
                progress_callback(92, "finalizing", "HLS 片段已產生，正在寫入播放索引。")
            if not manifest_rows:
                raise RuntimeError("HLS 沒有成功產生任何可播放畫質")
            for subtitle in subtitle_rows:
                conn.execute(
                    """
                    INSERT INTO media_stream_subtitles (
                        asset_id, name, label, language, codec, path, is_default, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(asset["id"]),
                        str(subtitle.get("name") or ""),
                        str(subtitle.get("label") or ""),
                        str(subtitle.get("language") or "und"),
                        str(subtitle.get("codec") or ""),
                        str(subtitle.get("path") or ""),
                        1 if subtitle.get("is_default") else 0,
                        now,
                    ),
                )
            _write_master_manifest_variants(master_manifest_path, manifest_rows)
            asset = _set_asset_ready(
                conn,
                file_row=file_row,
                master_manifest_path=f"{derivative_root_rel}/master.m3u8",
                duration_seconds=metadata["duration_seconds"],
                warning_message="; ".join(variant_errors)[:800],
            )
            if progress_callback:
                progress_callback(98, "finalizing", "HLS 索引已寫入，正在完成任務紀錄。")
            _record_job(conn, asset_id=asset["id"], status="ready", started_at=started_at)
            _safe_commit(conn)
            return serialize_stream_asset(conn, file_row["id"])
        except Exception as exc:
            asset = _set_asset_failed(conn, file_row=file_row, reason=str(exc))
            _record_job(conn, asset_id=asset["id"], status="failed", error_message=str(exc), started_at=started_at)
            _safe_commit(conn)
            raise


def get_stream_status(conn, *, file_row, include_segments=True):
    ensure_media_stream_schema(conn)
    if not file_row or _row_value(file_row, "deleted_at"):
        return None
    asset = serialize_stream_asset(conn, file_row["id"], include_segments=include_segments)
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
            "error_message": STRICT_E2EE_SERVER_TRANSCODE_DISABLED_REASON,
            "variants": [],
            "subtitles": [],
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
        "subtitles": [],
    }


def cleanup_stream_asset(conn, *, uploaded_file_id, storage_root):
    ensure_media_stream_schema(conn)
    file_id = str(uploaded_file_id or "").strip()
    if not file_id:
        return {"file_id": file_id, "removed": False}
    asset_rows = conn.execute(
        "SELECT id FROM media_stream_assets WHERE uploaded_file_id=?",
        (file_id,),
    ).fetchall()
    asset_ids = [int(row["id"]) for row in asset_rows]
    variant_count = 0
    segment_count = 0
    subtitle_count = 0
    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        variant_rows = conn.execute(
            f"SELECT id FROM media_stream_variants WHERE asset_id IN ({placeholders})",
            asset_ids,
        ).fetchall()
        variant_ids = [int(row["id"]) for row in variant_rows]
        variant_count = len(variant_ids)
        subtitle_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM media_stream_subtitles WHERE asset_id IN ({placeholders})",
            asset_ids,
        ).fetchone()["c"]
        if variant_ids:
            variant_placeholders = ",".join("?" for _ in variant_ids)
            segment_count = conn.execute(
                f"SELECT COUNT(*) AS c FROM media_stream_segments WHERE variant_id IN ({variant_placeholders})",
                variant_ids,
            ).fetchone()["c"]
            conn.execute(
                f"DELETE FROM media_stream_segments WHERE variant_id IN ({variant_placeholders})",
                variant_ids,
            )
        conn.execute(f"DELETE FROM media_stream_subtitles WHERE asset_id IN ({placeholders})", asset_ids)
        conn.execute(f"DELETE FROM media_stream_variants WHERE asset_id IN ({placeholders})", asset_ids)
        conn.execute(f"DELETE FROM media_stream_jobs WHERE asset_id IN ({placeholders})", asset_ids)
        conn.execute(f"DELETE FROM media_stream_assets WHERE id IN ({placeholders})", asset_ids)
    try:
        root = resolve_storage_path(storage_root, _derivative_root_relpath(file_id))
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    except Exception:
        pass
    return {
        "file_id": file_id,
        "removed": bool(asset_ids),
        "assets_removed": len(asset_ids),
        "variants_removed": int(variant_count or 0),
        "segments_removed": int(segment_count or 0),
        "subtitles_removed": int(subtitle_count or 0),
    }


def stream_playback_payload(conn, *, file_row, video_id):
    status = get_stream_status(conn, file_row=file_row, include_segments=False)
    media_type = _file_media_type(file_row)
    direct_url = f"/api/videos/{int(video_id)}/stream"
    direct_fallback_allowed = not is_server_encrypted_file(file_row)
    payload = {
        "mode": "direct",
        "media_type": media_type,
        "source_mode": str(file_row["privacy_mode"] or "standard_plain"),
        "fallback_url": direct_url if direct_fallback_allowed else "",
        "stream_url": direct_url if direct_fallback_allowed else "",
        "master_url": "",
        "hls_js_url": HLS_JS_URL,
        "player_strategy": "direct_only",
        "stream_warning": "目前使用直接串流。" if direct_fallback_allowed else "伺服端加密影音不提供主程序直接解密串流，請等待 HLS 處理完成。",
        "status": status,
        "variants": [],
        "subtitles": [],
        "streaming_ready": False,
        "direct_fallback_allowed": direct_fallback_allowed,
    }
    if status and status.get("subtitles"):
        payload["subtitles"] = [
            {
                "name": str(item.get("name") or ""),
                "label": str(item.get("label") or item.get("language") or "字幕"),
                "language": str(item.get("language") or "und"),
                "is_default": bool(item.get("is_default")),
                "url": f"/api/videos/{int(video_id)}/hls/subtitles/{item.get('name')}.vtt",
            }
            for item in (status.get("subtitles") or [])
            if item.get("name")
        ]
    if status and status.get("status") == "ready" and status.get("master_manifest_path"):
        variants = []
        for variant in status.get("variants") or []:
            name = str(variant.get("name") or "").strip()
            if not name:
                continue
            height = _safe_int(variant.get("height"), 0)
            label = "原畫質" if name == "original" else (f"{height}p" if height else name)
            if name == "original" and height:
                label = f"原畫質 {height}p"
            variants.append({
                "name": name,
                "label": label,
                "width": _safe_int(variant.get("width"), 0),
                "height": height,
                "bitrate": _safe_int(variant.get("bitrate"), 0),
                "codec": str(variant.get("codec") or ""),
                "size_bytes": _safe_int(variant.get("segments_total_bytes"), 0),
                "segments_total_bytes": _safe_int(variant.get("segments_total_bytes"), 0),
                "source_size_bytes": _safe_int(status.get("source_size_bytes"), 0),
                "playlist_url": f"/api/videos/{int(video_id)}/hls/{name}/playlist.m3u8",
            })
        default_quality = _preferred_playback_quality_name(variants)
        fallback_quality = _fallback_playback_quality_name(variants)
        payload["mode"] = "hls"
        payload["master_url"] = f"/api/videos/{int(video_id)}/hls/master.m3u8"
        payload["player_strategy"] = "native_hls_or_hlsjs"
        payload["stream_warning"] = ""
        payload["streaming_ready"] = True
        payload["variants"] = variants
        payload["default_quality"] = default_quality
        payload["fallback_quality"] = fallback_quality
        payload["quality_policy"] = {
            "default_height": 720,
            "fallback_height": 480,
            "default_quality": default_quality,
            "fallback_quality": fallback_quality,
            "derivatives_quota_exempt": HLS_DERIVATIVES_QUOTA_EXEMPT,
            "larger_derivatives_hidden": True,
            "note": "480p/720p/1080p HLS 衍生檔是服務端串流快取，不計入上傳者雲端硬碟配額；若衍生檔比原畫質更大會自動刪除並隱藏。",
        }
    return payload
