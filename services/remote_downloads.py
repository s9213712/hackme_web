import ipaddress
import mimetypes
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from services.upload_security import safe_public_filename


class RemoteDownloadError(RuntimeError):
    pass


@dataclass
class DownloadedFile:
    path: str
    filename: str
    mimetype: str
    cleanup_dir: str | None = None

    @property
    def stream(self):
        return open(self.path, "rb")


def remote_download_capabilities():
    aria2c = shutil.which("aria2c")
    return {
        "direct_link": True,
        "bt_magnet": bool(aria2c),
        "bt_file": bool(aria2c),
        "aria2c_path": aria2c or "",
    }


def _host_is_public(hostname):
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def validate_remote_url(raw_url):
    url = str(raw_url or "").strip()
    if not url:
        raise RemoteDownloadError("請輸入下載網址")
    if url.startswith("magnet:?"):
        return {"kind": "magnet", "url": url}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteDownloadError("只支援 http、https direct link 或 magnet link")
    if not _host_is_public(parsed.hostname):
        raise RemoteDownloadError("下載網址不可指向 localhost、內網或保留位址")
    return {"kind": "direct", "url": url}


def _filename_from_response(url, headers):
    disposition = headers.get("Content-Disposition") or ""
    _, params = urllib.request.parse_http_list(disposition), {}
    for item in urllib.request.parse_http_list(disposition):
        if "=" in item:
            key, value = item.split("=", 1)
            params[key.strip().lower()] = value.strip().strip('"')
    filename = params.get("filename*") or params.get("filename")
    if filename and "''" in filename:
        filename = urllib.parse.unquote(filename.split("''", 1)[1])
    if not filename:
        filename = Path(urllib.parse.urlparse(url).path).name
    return safe_public_filename(filename or "remote-download.bin")


def _emit_progress(progress_callback, **payload):
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        pass


def download_direct_link(url, *, timeout_seconds=60, max_bytes=None, progress_callback=None):
    request = urllib.request.Request(url, headers={"User-Agent": "hackme_web-remote-downloader/1.0"})
    tmpdir = tempfile.mkdtemp(prefix="hackme_remote_")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            filename = _filename_from_response(url, response.headers)
            mimetype = response.headers.get_content_type() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            total_bytes = None
            try:
                length = response.headers.get("Content-Length")
                total_bytes = int(length) if length else None
            except Exception:
                total_bytes = None
            target = os.path.join(tmpdir, filename)
            total = 0
            _emit_progress(progress_callback, phase="downloading", filename=filename, loaded_bytes=0, total_bytes=total_bytes)
            with open(target, "wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes is not None and total > int(max_bytes):
                        raise RemoteDownloadError("遠端檔案超過容量限制")
                    out.write(chunk)
                    _emit_progress(progress_callback, phase="downloading", filename=filename, loaded_bytes=total, total_bytes=total_bytes)
            _emit_progress(progress_callback, phase="downloaded", filename=filename, loaded_bytes=total, total_bytes=total_bytes)
        return DownloadedFile(path=target, filename=filename, mimetype=mimetype, cleanup_dir=tmpdir)
    except urllib.error.URLError as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RemoteDownloadError(f"遠端下載失敗：{getattr(exc, 'reason', exc)}") from exc
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def _zip_download_dir(tmpdir, files):
    archive = os.path.join(tmpdir, "bt-download.zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_out:
        for path in files:
            zip_out.write(path, arcname=os.path.relpath(path, tmpdir))
    return archive


def _tail_lines(text, *, max_lines=8, max_chars=800):
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])[-max_chars:]


def _read_tail(path, *, max_lines=12, max_chars=1200):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return _tail_lines(fh.read(), max_lines=max_lines, max_chars=max_chars)
    except OSError:
        return ""


def _aria2_failure_message(proc, log_path):
    log_tail = _read_tail(log_path)
    output_tail = _tail_lines((proc.stderr or "") + "\n" + (proc.stdout or ""))
    generic = "If there are any errors, then see the log file"
    candidates = []
    for text in (log_tail, output_tail):
        filtered = "\n".join(line for line in str(text or "").splitlines() if generic not in line).strip()
        if filtered:
            candidates.append(filtered)
    detail = candidates[0] if candidates else ""
    if not detail:
        return "BT/magnet 下載失敗：aria2c 未提供錯誤細節"
    return f"BT/magnet 下載失敗：{detail}"


def _download_bt_with_aria2(source, *, source_label="BT/magnet", timeout_seconds=300, max_bytes=None, progress_callback=None):
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise RemoteDownloadError("BT 下載需要先安裝 aria2c")
    tmpdir = tempfile.mkdtemp(prefix="hackme_bt_")
    log_path = os.path.join(tmpdir, "aria2.log")
    cmd = [
        aria2c,
        "--dir", tmpdir,
        "--log", log_path,
        "--log-level=notice",
        "--seed-time=0",
        "--bt-stop-timeout=120",
        "--follow-torrent=mem",
        "--allow-overwrite=false",
        "--auto-file-renaming=true",
        "--summary-interval=0",
        "--console-log-level=warn",
        source,
    ]
    try:
        _emit_progress(progress_callback, phase="downloading", filename=source_label, loaded_bytes=None, total_bytes=None)
        proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds)
        if proc.returncode != 0:
            raise RemoteDownloadError(_aria2_failure_message(proc, log_path))
        files = [
            str(path)
            for path in Path(tmpdir).rglob("*")
            if path.is_file() and not path.name.endswith(".aria2") and path.name != "aria2.log"
        ]
        if not files:
            raise RemoteDownloadError("BT 下載沒有產生可保存的檔案")
        if max_bytes is not None:
            total_downloaded = sum(os.path.getsize(path) for path in files)
            if total_downloaded > int(max_bytes):
                raise RemoteDownloadError("BT 下載內容超過容量限制")
        if len(files) == 1:
            target = files[0]
            filename = safe_public_filename(Path(target).name)
            mimetype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        else:
            target = _zip_download_dir(tmpdir, files)
            filename = "bt-download.zip"
            mimetype = "application/zip"
        try:
            total = os.path.getsize(target)
        except OSError:
            total = None
        _emit_progress(progress_callback, phase="downloaded", filename=filename, loaded_bytes=total, total_bytes=total)
        return DownloadedFile(path=target, filename=filename, mimetype=mimetype, cleanup_dir=tmpdir)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RemoteDownloadError("BT 下載逾時") from exc
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def download_magnet_with_aria2(url, *, timeout_seconds=300, max_bytes=None, progress_callback=None):
    return _download_bt_with_aria2(
        url,
        source_label="BT/magnet",
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        progress_callback=progress_callback,
    )


def download_torrent_file_with_aria2(torrent_path, *, display_name="BT 檔案", timeout_seconds=300, max_bytes=None, progress_callback=None):
    if not os.path.isfile(torrent_path):
        raise RemoteDownloadError("找不到 BT 種子檔")
    return _download_bt_with_aria2(
        torrent_path,
        source_label=display_name or "BT 檔案",
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        progress_callback=progress_callback,
    )


def download_remote_url(url, *, timeout_seconds=120, max_bytes=None, progress_callback=None):
    parsed = validate_remote_url(url)
    if parsed["kind"] == "magnet":
        return download_magnet_with_aria2(parsed["url"], timeout_seconds=timeout_seconds, max_bytes=max_bytes, progress_callback=progress_callback)
    return download_direct_link(parsed["url"], timeout_seconds=timeout_seconds, max_bytes=max_bytes, progress_callback=progress_callback)
