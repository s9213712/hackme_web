import mimetypes
import tarfile
import zipfile
from pathlib import Path

TEXT_EXTENSIONS = {
    ".css", ".csv", ".htm", ".html", ".ini", ".js", ".json", ".log", ".md",
    ".py", ".sql", ".text", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
AUDIO_EXTENSIONS = {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"}
VIDEO_EXTENSIONS = {".m4v", ".mov", ".mp4", ".ogv", ".webm"}
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
PDF_EXTENSIONS = {".pdf"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}


def _filename(row):
    return row["original_filename_plain_for_public"] or Path(str(row["storage_path"] or "download.bin")).name


def _extension(filename):
    lower = str(filename or "").lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lower.endswith(ext):
            return ext
    return Path(lower).suffix


def _mime(row, filename):
    value = row["mime_type_plain_for_public"] if "mime_type_plain_for_public" in row.keys() else None
    if value:
        return value
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _display_mime(mime, filename):
    if mime and mime != "application/octet-stream":
        return mime
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or mime or "application/octet-stream"


def preview_category(row):
    filename = _filename(row)
    ext = _extension(filename)
    mime = _mime(row, filename)
    if mime.startswith("audio/") or ext in AUDIO_EXTENSIONS:
        return "audio", _display_mime(mime, filename)
    if mime.startswith("video/") or ext in VIDEO_EXTENSIONS:
        return "video", _display_mime(mime, filename)
    if mime.startswith("image/") or ext in IMAGE_EXTENSIONS:
        return "image", _display_mime(mime, filename)
    if mime == "application/pdf" or ext in PDF_EXTENSIONS:
        return "pdf", "application/pdf"
    if mime.startswith("text/") or ext in TEXT_EXTENSIONS:
        return "text", mime if mime != "application/octet-stream" else "text/plain"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive", mime
    return "metadata", mime


def build_preview_metadata(row, path, *, max_text_bytes=65536, max_archive_entries=100):
    filename = _filename(row)
    category, mime = preview_category(row)
    payload = {
        "file_id": row["id"],
        "filename": filename,
        "size_bytes": int(row["size_bytes"] or 0),
        "privacy_mode": row["privacy_mode"],
        "risk_level": row["risk_level"],
        "scan_status": row["scan_status"],
        "category": category,
        "mime_type": mime,
        "render_mode": "metadata",
        "previewable": category in {"audio", "video", "image", "pdf", "text", "archive"},
    }
    if category in {"audio", "video", "image", "pdf"}:
        payload["render_mode"] = "media"
        return payload
    if category == "text":
        payload["render_mode"] = "text"
        payload["truncated"] = int(row["size_bytes"] or 0) > max_text_bytes
        with open(path, "rb") as handle:
            raw = handle.read(max_text_bytes)
        payload["text"] = raw.decode("utf-8", errors="replace")
        return payload
    if category == "archive":
        payload["render_mode"] = "archive"
        payload["entries"] = _archive_entries(path, max_entries=max_archive_entries)
        payload["truncated"] = len(payload["entries"]) >= max_archive_entries
        return payload
    return payload


def _archive_entries(path, *, max_entries):
    entries = []
    lower = str(path).lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist()[:max_entries]:
                    entries.append({
                        "name": info.filename,
                        "size": int(info.file_size or 0),
                        "compressed_size": int(info.compress_size or 0),
                        "is_dir": info.is_dir(),
                    })
        elif any(lower.endswith(ext) for ext in (".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
            with tarfile.open(path) as archive:
                for member in archive.getmembers()[:max_entries]:
                    entries.append({
                        "name": member.name,
                        "size": int(member.size or 0),
                        "compressed_size": None,
                        "is_dir": member.isdir(),
                    })
    except Exception as exc:
        return [{"name": f"archive_preview_error: {exc}", "size": 0, "compressed_size": None, "is_dir": False}]
    return entries
