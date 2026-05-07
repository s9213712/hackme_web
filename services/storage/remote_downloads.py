import ipaddress
import http.client
import mimetypes
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from services.security.upload_security import safe_public_filename


MAX_BDECODE_DEPTH = 64


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


def _ip_is_public(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_is_public(hostname):
    if not hostname:
        return False
    try:
        _resolve_public_endpoint(hostname, 80)
    except RemoteDownloadError:
        return False
    return True


def _resolve_public_endpoint(hostname, port):
    if not hostname:
        raise RemoteDownloadError("下載網址缺少主機名稱")
    # If hostname is a literal IP address, block private ones directly
    try:
        literal_ip = ipaddress.ip_address(hostname)
        if not _ip_is_public(str(literal_ip)):
            raise RemoteDownloadError(f"下載網址不可指向 localhost、內網或保留位址（{hostname}）")
        family = socket.AF_INET6 if isinstance(literal_ip, ipaddress.IPv6Address) else socket.AF_INET
        return (family, socket.SOCK_STREAM, 0, (hostname, port))
    except RemoteDownloadError:
        raise
    except ValueError:
        pass  # Not a literal IP — it's a domain name, proceed with DNS
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RemoteDownloadError("下載網址無法解析") from exc
    if not infos:
        raise RemoteDownloadError("下載網址無法解析")
    candidates = []
    blocked = []
    for family, socktype, proto, _, sockaddr in infos:
        address = sockaddr[0]
        if not _ip_is_public(address):
            blocked.append(address)
            continue
        candidates.append((family, socktype, proto, sockaddr))
    if not candidates:
        suffix = ""
        if blocked:
            suffix = f"（{hostname} -> {', '.join(sorted(set(blocked)))}）"
        raise RemoteDownloadError(f"下載網址不可指向 localhost、內網或保留位址{suffix}")
    return candidates[0]


def _validate_tracker_url(tracker_url):
    parsed = urllib.parse.urlparse(str(tracker_url or "").strip())
    if parsed.scheme not in {"http", "https", "udp"} or not parsed.hostname:
        raise RemoteDownloadError("BT tracker URL 格式不支援")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _resolve_public_endpoint(parsed.hostname, port)


def validate_magnet_trackers(url):
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    for tracker in params.get("tr", []):
        _validate_tracker_url(tracker)


def _bdecode(data, index=0, depth=0):
    if depth > MAX_BDECODE_DEPTH:
        raise ValueError("bencode nesting depth exceeded")
    if index >= len(data):
        raise ValueError("unexpected end of bencode data")
    marker = data[index:index + 1]
    if marker == b"i":
        end = data.index(b"e", index)
        return int(data[index + 1:end]), end + 1
    if marker == b"l":
        index += 1
        out = []
        while data[index:index + 1] != b"e":
            item, index = _bdecode(data, index, depth + 1)
            out.append(item)
        return out, index + 1
    if marker == b"d":
        index += 1
        out = {}
        while data[index:index + 1] != b"e":
            key, index = _bdecode(data, index, depth + 1)
            value, index = _bdecode(data, index, depth + 1)
            out[key] = value
        return out, index + 1
    if marker.isdigit():
        colon = data.index(b":", index)
        length = int(data[index:colon])
        start = colon + 1
        end = start + length
        return data[start:end], end
    raise ValueError("invalid bencode")


def _decode_tracker_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _torrent_file_trackers(torrent_path):
    try:
        with open(torrent_path, "rb") as fh:
            data = fh.read(2 * 1024 * 1024 + 1)
        decoded, _ = _bdecode(data)
    except Exception as exc:
        raise RemoteDownloadError("BT 種子檔格式無法解析") from exc
    if not isinstance(decoded, dict):
        raise RemoteDownloadError("BT 種子檔格式無效")
    trackers = []
    announce = decoded.get(b"announce")
    if announce:
        trackers.append(_decode_tracker_value(announce))
    announce_list = decoded.get(b"announce-list")
    if isinstance(announce_list, list):
        for tier in announce_list:
            if isinstance(tier, list):
                trackers.extend(_decode_tracker_value(item) for item in tier)
            else:
                trackers.append(_decode_tracker_value(tier))
    return [tracker for tracker in trackers if str(tracker or "").strip()]


def inspect_torrent_file_trackers(torrent_path):
    trackers = _torrent_file_trackers(torrent_path)
    blocked = []
    for tracker in trackers:
        try:
            _validate_tracker_url(tracker)
        except RemoteDownloadError as exc:
            blocked.append({"url": tracker, "reason": str(exc)})
    return {"trackers": trackers, "blocked": blocked}


def validate_torrent_file_trackers(torrent_path):
    report = inspect_torrent_file_trackers(torrent_path)
    if report["blocked"]:
        first = report["blocked"][0]
        raise RemoteDownloadError(f"BT 種子檔包含不安全 tracker，已阻擋（{first['url']}：{first['reason']}）")
    return report


def validate_remote_url(raw_url):
    url = str(raw_url or "").strip()
    if not url:
        raise RemoteDownloadError("請輸入下載網址")
    if url.startswith("magnet:?"):
        validate_magnet_trackers(url)
        return {"kind": "magnet", "url": url}
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteDownloadError("只支援 http、https direct link 或 magnet link")
    _resolve_public_endpoint(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if parsed.path.lower().endswith(".torrent"):
        return {"kind": "torrent_url", "url": url}
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


def _http_response_once(url, *, timeout_seconds=60):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteDownloadError("只支援 http 或 https direct link")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    family, socktype, proto, sockaddr = _resolve_public_endpoint(parsed.hostname, port)
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(timeout_seconds)
    try:
        sock.connect(sockaddr)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            sock.settimeout(timeout_seconds)
        path = urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
        host_header = parsed.hostname or ""
        if parsed.port and parsed.port not in {80, 443}:
            host_header = f"{host_header}:{parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: hackme_web-remote-downloader/1.0\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", "ignore")
        sock.sendall(request)
        response = http.client.HTTPResponse(sock)
        response.begin()
        return response, sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _open_http_response(url, *, timeout_seconds=60, redirects=0):
    response, sock = _http_response_once(url, timeout_seconds=timeout_seconds)
    if response.status in {301, 302, 303, 307, 308}:
        location = response.getheader("Location")
        response.close()
        sock.close()
        if redirects >= 3 or not location:
            raise RemoteDownloadError("遠端下載重新導向次數過多")
        next_url = urllib.parse.urljoin(url, location)
        validate_remote_url(next_url)
        return _open_http_response(next_url, timeout_seconds=timeout_seconds, redirects=redirects + 1)
    if response.status >= 400:
        response.close()
        sock.close()
        raise RemoteDownloadError(f"遠端伺服器回應 HTTP {response.status}")
    return response, sock


def download_direct_link(url, *, timeout_seconds=60, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None):
    tmpdir = tempfile.mkdtemp(prefix="hackme_remote_")
    response = None
    sock = None
    try:
        response, sock = _open_http_response(url, timeout_seconds=timeout_seconds)
        filename = _filename_from_response(url, response.headers)
        mimetype = response.headers.get_content_type() or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        total_bytes = None
        try:
            length = response.headers.get("Content-Length")
            total_bytes = int(length) if length else None
        except Exception:
            total_bytes = None
        if max_bytes is not None and total_bytes is not None and total_bytes > int(max_bytes):
            raise RemoteDownloadError("遠端檔案超過容量限制")
        target = os.path.join(tmpdir, filename)
        total = 0
        _emit_progress(progress_callback, phase="downloading", filename=filename, loaded_bytes=0, total_bytes=total_bytes)
        started = time.monotonic()
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
                if rate_limit_kb_per_sec:
                    expected_elapsed = total / max(1, int(rate_limit_kb_per_sec) * 1024)
                    elapsed = time.monotonic() - started
                    if expected_elapsed > elapsed:
                        time.sleep(min(1.0, expected_elapsed - elapsed))
        _emit_progress(progress_callback, phase="downloaded", filename=filename, loaded_bytes=total, total_bytes=total_bytes)
        return DownloadedFile(path=target, filename=filename, mimetype=mimetype, cleanup_dir=tmpdir)
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RemoteDownloadError(f"遠端下載失敗：{exc}") from exc
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        if response:
            response.close()
        if sock:
            sock.close()


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
    combined = "\n".join([log_tail, output_tail])
    if "failed to bind" in combined or "Errors occurred while binding port" in combined:
        return "BT/magnet 下載失敗：aria2c 無法綁定 BT/DHT 連接埠。請確認 server 不是在受限沙盒中執行，並允許 aria2c 開啟 TCP/UDP BT 連接埠。"
    if "Stop downloading torrent due to --bt-stop-timeout option" in combined or "[METADATA]" in combined:
        return "BT/magnet 下載失敗：指定時間內抓不到 torrent metadata。常見原因是做種/節點太少、tracker 無回應、DHT 被網路或防火牆阻擋，或該 magnet 已失效。請換其他 magnet、補充 tracker，或稍後再試。"
    candidates = []
    for text in (log_tail, output_tail):
        filtered_lines = []
        for line in str(text or "").splitlines():
            if generic in line:
                continue
            if "NOTICE" in line and "error" not in line.lower() and "failure" not in line.lower():
                continue
            filtered_lines.append(line)
        filtered = "\n".join(filtered_lines).strip()
        if filtered:
            candidates.append(filtered)
    detail = candidates[0] if candidates else ""
    if not detail:
        return "BT/magnet 下載失敗：aria2c 未提供錯誤細節"
    return f"BT/magnet 下載失敗：{detail}"


def _download_bt_with_aria2(source, *, source_label="BT/magnet", timeout_seconds=300, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None, exclude_trackers=None):
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise RemoteDownloadError("BT 下載需要先安裝 aria2c")
    tmpdir = tempfile.mkdtemp(prefix="hackme_bt_")
    log_path = os.path.join(tmpdir, "aria2.log")
    # Public trackers to supplement DHT for better magnet-link peer discovery
    _PUBLIC_TRACKERS = ",".join([
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.demonii.com:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "udp://exodus.desync.com:6969/announce",
        "udp://tracker.torrent.eu.org:451/announce",
    ])
    cmd = [
        aria2c,
        "--dir", tmpdir,
        "--log", log_path,
        "--log-level=notice",
        "--seed-time=0",
        "--bt-stop-timeout=600",
        "--bt-enable-lpd=false",
        "--enable-dht=true",
        "--enable-peer-exchange=true",
        f"--bt-tracker={_PUBLIC_TRACKERS}",
        "--max-tries=2",
        "--max-file-not-found=2",
        "--file-allocation=none",
        "--follow-torrent=mem",
        "--allow-overwrite=false",
        "--auto-file-renaming=true",
        "--summary-interval=0",
        "--console-log-level=warn",
        source,
    ]
    if rate_limit_kb_per_sec:
        cmd[1:1] = ["--max-download-limit", f"{int(rate_limit_kb_per_sec)}K"]
    safe_excludes = [str(item or "").strip() for item in (exclude_trackers or []) if str(item or "").strip()]
    if safe_excludes:
        cmd[1:1] = ["--bt-exclude-tracker", ",".join(safe_excludes)]
    try:
        _emit_progress(progress_callback, phase="downloading", filename=source_label, loaded_bytes=None, total_bytes=None)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started = time.monotonic()
        while proc.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                proc.kill()
                proc.communicate(timeout=5)
                raise RemoteDownloadError("BT 下載逾時")
            if max_bytes is not None:
                total_downloaded = sum(os.path.getsize(path) for path in Path(tmpdir).rglob("*") if path.is_file())
                if total_downloaded > int(max_bytes):
                    proc.kill()
                    proc.communicate(timeout=5)
                    raise RemoteDownloadError("BT 下載內容超過容量限制")
                _emit_progress(progress_callback, phase="downloading", filename=source_label, loaded_bytes=total_downloaded, total_bytes=int(max_bytes))
            time.sleep(0.5)
        stdout, stderr = proc.communicate()
        proc = subprocess.CompletedProcess(cmd, proc.returncode, stdout=stdout, stderr=stderr)
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


def download_magnet_with_aria2(url, *, timeout_seconds=300, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None):
    return _download_bt_with_aria2(
        url,
        source_label="BT/magnet",
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        progress_callback=progress_callback,
        rate_limit_kb_per_sec=rate_limit_kb_per_sec,
    )


def download_torrent_file_with_aria2(torrent_path, *, display_name="BT 檔案", timeout_seconds=300, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None):
    if not os.path.isfile(torrent_path):
        raise RemoteDownloadError("找不到 BT 種子檔")
    tracker_report = inspect_torrent_file_trackers(torrent_path)
    excluded_trackers = [item["url"] for item in tracker_report.get("blocked", [])]
    return _download_bt_with_aria2(
        torrent_path,
        source_label=display_name or "BT 檔案",
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        progress_callback=progress_callback,
        rate_limit_kb_per_sec=rate_limit_kb_per_sec,
        exclude_trackers=excluded_trackers,
    )


def download_torrent_url_with_aria2(url, *, timeout_seconds=300, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None):
    parsed = validate_remote_url(url)
    if parsed["kind"] != "torrent_url":
        raise RemoteDownloadError("BT/torrent URL 必須指向 .torrent 種子檔")
    torrent_limit = 2 * 1024 * 1024
    torrent_file = download_direct_link(
        parsed["url"],
        timeout_seconds=min(int(timeout_seconds or 120), 120),
        max_bytes=torrent_limit,
        progress_callback=progress_callback,
        rate_limit_kb_per_sec=rate_limit_kb_per_sec,
    )
    try:
        return download_torrent_file_with_aria2(
            torrent_file.path,
            display_name=torrent_file.filename,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            progress_callback=progress_callback,
            rate_limit_kb_per_sec=rate_limit_kb_per_sec,
        )
    finally:
        if torrent_file.cleanup_dir:
            shutil.rmtree(torrent_file.cleanup_dir, ignore_errors=True)


def download_remote_url(url, *, timeout_seconds=120, max_bytes=None, progress_callback=None, rate_limit_kb_per_sec=None, treat_torrent_as_bt=True):
    parsed = validate_remote_url(url)
    if parsed["kind"] == "magnet":
        return download_magnet_with_aria2(parsed["url"], timeout_seconds=timeout_seconds, max_bytes=max_bytes, progress_callback=progress_callback, rate_limit_kb_per_sec=rate_limit_kb_per_sec)
    if parsed["kind"] == "torrent_url" and treat_torrent_as_bt:
        return download_torrent_url_with_aria2(parsed["url"], timeout_seconds=timeout_seconds, max_bytes=max_bytes, progress_callback=progress_callback, rate_limit_kb_per_sec=rate_limit_kb_per_sec)
    return download_direct_link(parsed["url"], timeout_seconds=timeout_seconds, max_bytes=max_bytes, progress_callback=progress_callback, rate_limit_kb_per_sec=rate_limit_kb_per_sec)
