#!/usr/bin/env python3
"""Stress long-video upload, HLS preparation, and quality variant serving.

This probe is intentionally external to the app. It can:

1. Log in with multiple accounts and concurrently upload the same long video.
2. Confirm overloaded upload slots return an explicit `server_busy` response.
3. Wait for HLS background jobs to finish.
4. Measure each generated quality variant by fetching playlists and HLS
   segments while sampling `/api/version` latency.

Example:

    python3 scripts/testing/video_hls_quality_stress.py \
      --base-url http://127.0.0.1:5017 \
      --video /tmp/hackme_video_quality_sample.mp4 \
      --accounts test:test test2:test2 test3:test3 test4:test4 \
      --db /tmp/hackme_video_quality_direct_5017/runtime/database/database.db \
      --runtime-marker /tmp/hackme_video_quality_direct_5017 \
      --upload --wait --measure

The script does not start or stop the server. Run it only against an isolated QA
runtime unless you intentionally want to stress a shared environment.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import mimetypes
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests
import urllib3


TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "expired"}
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class StreamingMultipartBody:
    """Small multipart/form-data stream that does not buffer large files."""

    def __init__(
        self,
        *,
        fields: dict[str, str],
        file_field: str,
        file_path: Path,
        content_type: str,
    ) -> None:
        self.boundary = f"----hackme-probe-{uuid.uuid4().hex}"
        self.content_type = f"multipart/form-data; boundary={self.boundary}"
        self._file_path = file_path
        self._file = None
        prefix_parts: list[bytes] = []
        boundary = self.boundary
        for name, value in fields.items():
            prefix_parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{_quote_header(name)}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        filename = _quote_header(file_path.name)
        prefix_parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{_quote_header(file_field)}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        self._prefix = b"".join(prefix_parts)
        self._suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
        self._prefix_offset = 0
        self._suffix_offset = 0
        self._phase = "prefix"
        self._length = len(self._prefix) + file_path.stat().st_size + len(self._suffix)

    def __len__(self) -> int:
        return self._length

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _read_prefix(self, limit: int) -> bytes:
        chunk = self._prefix[self._prefix_offset : self._prefix_offset + limit]
        self._prefix_offset += len(chunk)
        if self._prefix_offset >= len(self._prefix):
            self._phase = "file"
        return chunk

    def _read_file(self, limit: int) -> bytes:
        if self._file is None:
            self._file = self._file_path.open("rb")
        chunk = self._file.read(limit)
        if not chunk:
            self.close()
            self._phase = "suffix"
            return b""
        return chunk

    def _read_suffix(self, limit: int) -> bytes:
        chunk = self._suffix[self._suffix_offset : self._suffix_offset + limit]
        self._suffix_offset += len(chunk)
        if self._suffix_offset >= len(self._suffix):
            self._phase = "done"
        return chunk

    def read(self, size: int = -1) -> bytes:
        if self._phase == "done":
            return b""
        if size is None or size < 0:
            size = 1024 * 1024
        remaining = size
        chunks: list[bytes] = []
        while remaining > 0 and self._phase != "done":
            if self._phase == "prefix":
                chunk = self._read_prefix(remaining)
            elif self._phase == "file":
                chunk = self._read_file(remaining)
                if not chunk:
                    continue
            else:
                chunk = self._read_suffix(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _quote_header(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def utc_ms() -> int:
    return int(time.time() * 1000)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    index = min(len(data) - 1, max(0, int(math.ceil(len(data) * pct) - 1)))
    return round(data[index], 2)


def summarize_latencies(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"samples": 0, "min": None, "p50": None, "p95": None, "max": None}
    return {
        "samples": len(values),
        "min": round(min(values), 2),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": round(max(values), 2),
        "mean": round(statistics.mean(values), 2),
    }


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    **kwargs: Any,
) -> tuple[int, Any, float]:
    started = time.perf_counter()
    try:
        response = session.request(method, url, **kwargs)
        elapsed = time.perf_counter() - started
        try:
            payload: Any = response.json()
        except Exception:
            payload = response.text[:1000]
        return response.status_code, payload, elapsed
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return 0, {"exception": exc.__class__.__name__, "message": str(exc)}, elapsed


def login(base_url: str, username: str, password: str) -> dict[str, Any]:
    session = requests.Session()
    if base_url.startswith("https://"):
        session.verify = False
    csrf_status, csrf_payload, csrf_elapsed = request_json(
        session,
        "GET",
        f"{base_url}/api/csrf-token",
        timeout=10,
    )
    token = ""
    if isinstance(csrf_payload, dict):
        token = str(csrf_payload.get("csrf_token") or csrf_payload.get("token") or "")
    login_status, login_payload, login_elapsed = request_json(
        session,
        "POST",
        f"{base_url}/api/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": token},
        timeout=20,
    )
    # Direct-gunicorn HTTP QA runs still receive cookies configured for the
    # normal HTTPS deployment. Loosen only the local requests session so this
    # probe can exercise authenticated routes without changing app behavior.
    if base_url.startswith("http://"):
        for cookie in session.cookies:
            cookie.secure = False
    token = str(session.cookies.get("csrf_token") or token)
    return {
        "session": session,
        "token": token,
        "ok": csrf_status == 200 and login_status == 200 and bool(token),
        "username": username,
        "csrf": {"status": csrf_status, "elapsed_s": csrf_elapsed, "payload": csrf_payload},
        "login": {"status": login_status, "elapsed_s": login_elapsed, "payload": login_payload},
    }


def upload_video(
    *,
    base_url: str,
    username: str,
    password: str,
    video_path: Path,
    privacy_mode: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    auth = login(base_url, username, password)
    result: dict[str, Any] = {
        "username": username,
        "ok": False,
        "status": 0,
        "elapsed_s": 0.0,
        "csrf": auth["csrf"],
        "login": auth["login"],
    }
    if not auth["ok"]:
        result["error"] = "login_failed"
        return result
    title = f"stress-{username}-{utc_ms()}"
    started = time.perf_counter()
    mime_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
    body = StreamingMultipartBody(
        fields={
            "title": title,
            "description": "Long video quality stress probe",
            "visibility": "public",
            "privacy_mode": privacy_mode,
        },
        file_field="video",
        file_path=video_path,
        content_type=mime_type,
    )
    try:
        response = auth["session"].post(
            f"{base_url}/api/videos/upload",
            data=body,
            headers={
                "Content-Type": body.content_type,
                "Content-Length": str(len(body)),
                "X-CSRF-Token": auth["token"],
            },
            timeout=timeout_seconds,
        )
        elapsed = time.perf_counter() - started
        try:
            payload: Any = response.json()
        except Exception:
            payload = response.text[:1000]
        result.update({
            "ok": response.status_code == 200 and isinstance(payload, dict) and bool(payload.get("ok")),
            "status": response.status_code,
            "elapsed_s": elapsed,
            "payload": payload,
        })
        if isinstance(payload, dict):
            video = payload.get("video") or {}
            file_info = payload.get("file") or {}
            stream_asset = payload.get("stream_asset") or {}
            result.update({
                "video_id": video.get("id"),
                "file_id": file_info.get("file_id") or video.get("cloud_file_id"),
                "stream_status": stream_asset.get("status"),
                "stream_warning": payload.get("stream_warning") or "",
            })
        return result
    except Exception as exc:
        result.update({
            "elapsed_s": time.perf_counter() - started,
            "error": exc.__class__.__name__,
            "message": str(exc),
        })
        return result
    finally:
        body.close()


def ps_snapshot(runtime_marker: str) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,pcpu,pmem,rss,nlwp,stat,comm,args"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        pid, ppid, pcpu, pmem, rss, nlwp, stat, comm, args = parts
        if (
            runtime_marker not in args
            and "hls_prepare_worker.py" not in args
            and comm != "ffmpeg"
        ):
            continue
        try:
            rows.append({
                "pid": int(pid),
                "ppid": int(ppid),
                "cpu_percent": float(pcpu),
                "mem_percent": float(pmem),
                "rss_kb": int(rss),
                "threads": int(nlwp),
                "stat": stat,
                "comm": comm,
                "args": args[:500],
            })
        except Exception:
            continue
    return rows


def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def db_state(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"error": "db_missing", "db_path": str(db_path)}
    conn = db_connect(db_path)
    try:
        state: dict[str, Any] = {}
        for table in (
            "uploaded_files",
            "videos",
            "job_center_jobs",
            "media_stream_assets",
            "media_stream_variants",
            "media_stream_subtitles",
        ):
            try:
                state[f"{table}_count"] = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            except Exception as exc:
                state[f"{table}_error"] = str(exc)
        try:
            state["videos"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, owner_user_id, title, cloud_file_id, status,
                           duration_seconds, created_at, updated_at
                    FROM videos
                    WHERE title LIKE 'stress-%'
                    ORDER BY id
                    """
                ).fetchall()
            ]
        except Exception as exc:
            state["videos_error"] = str(exc)
        try:
            state["jobs"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, job_uuid, owner_user_id, status, progress_percent,
                           stage, stage_detail, source_module, source_ref,
                           updated_at, error_message
                    FROM job_center_jobs
                    WHERE source_module='media_hls_prepare'
                    ORDER BY id
                    """
                ).fetchall()
            ]
        except Exception as exc:
            state["jobs_error"] = str(exc)
        try:
            state["assets"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, uploaded_file_id, status, master_manifest_path,
                           duration_seconds, error_message, updated_at
                    FROM media_stream_assets
                    ORDER BY id
                    """
                ).fetchall()
            ]
        except Exception as exc:
            state["assets_error"] = str(exc)
        try:
            state["variants"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT v.asset_id, a.uploaded_file_id, v.name, v.width,
                           v.height, v.bitrate, v.codec, COUNT(s.id) AS segments,
                           COALESCE(SUM(s.byte_size), 0) AS bytes
                    FROM media_stream_variants v
                    JOIN media_stream_assets a ON a.id=v.asset_id
                    LEFT JOIN media_stream_segments s ON s.variant_id=v.id
                    GROUP BY v.id
                    ORDER BY v.asset_id, v.id
                    """
                ).fetchall()
            ]
        except Exception as exc:
            state["variants_error"] = str(exc)
        try:
            state["subtitles"] = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT st.asset_id, a.uploaded_file_id, st.name, st.label,
                           st.language, st.codec, st.path, st.is_default
                    FROM media_stream_subtitles st
                    JOIN media_stream_assets a ON a.id=st.asset_id
                    ORDER BY st.asset_id, st.id
                    """
                ).fetchall()
            ]
        except Exception as exc:
            state["subtitles_error"] = str(exc)
        return state
    finally:
        conn.close()


def monitor_loop(
    *,
    base_url: str,
    db_path: Path,
    runtime_marker: str,
    interval: float,
    stop_event: threading.Event,
    samples: list[dict[str, Any]],
) -> None:
    session = requests.Session()
    if base_url.startswith("https://"):
        session.verify = False
    while not stop_event.is_set():
        sample: dict[str, Any] = {"t_ms": utc_ms()}
        started = time.perf_counter()
        try:
            response = session.get(f"{base_url}/api/version", timeout=5)
            sample["version_status"] = response.status_code
            sample["version_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        except Exception as exc:
            sample["version_status"] = 0
            sample["version_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            sample["version_error"] = f"{exc.__class__.__name__}: {exc}"
        sample["db"] = db_state(db_path)
        sample["processes"] = ps_snapshot(runtime_marker)
        samples.append(sample)
        stop_event.wait(interval)


def summarize_monitor(samples: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(s["version_elapsed_ms"]) for s in samples if s.get("version_status") == 200]
    failures = [s for s in samples if s.get("version_status") != 200]
    max_rss_kb = 0
    max_threads = 0
    ffmpeg_sample_count = 0
    worker_sample_count = 0
    for sample in samples:
        for proc in sample.get("processes") or []:
            max_rss_kb = max(max_rss_kb, int(proc.get("rss_kb") or 0))
            max_threads = max(max_threads, int(proc.get("threads") or 0))
            if proc.get("comm") == "ffmpeg":
                ffmpeg_sample_count += 1
            if "hls_prepare_worker.py" in str(proc.get("args") or ""):
                worker_sample_count += 1
    return {
        "samples": len(samples),
        "version_latency_ms": summarize_latencies(latencies),
        "version_failures": len(failures),
        "version_failure_samples": failures[:5],
        "max_rss_kb_seen_per_process": max_rss_kb,
        "max_threads_seen_per_process": max_threads,
        "ffmpeg_process_sample_count": ffmpeg_sample_count,
        "hls_worker_process_sample_count": worker_sample_count,
        "last_db": samples[-1].get("db") if samples else {},
    }


def run_upload_phase(args: argparse.Namespace) -> dict[str, Any]:
    video_path = Path(args.video)
    accounts = parse_accounts(args.accounts)
    if not video_path.exists():
        raise SystemExit(f"video not found: {video_path}")
    samples: list[dict[str, Any]] = []
    stop_event = threading.Event()
    monitor = threading.Thread(
        target=monitor_loop,
        kwargs={
            "base_url": args.base_url,
            "db_path": Path(args.db),
            "runtime_marker": args.runtime_marker,
            "interval": args.monitor_interval,
            "stop_event": stop_event,
            "samples": samples,
        },
        daemon=True,
    )
    monitor.start()
    started_ms = utc_ms()
    uploads: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(accounts))) as executor:
        futures = [
            executor.submit(
                upload_video,
                base_url=args.base_url,
                username=username,
                password=password,
                video_path=video_path,
                privacy_mode=args.privacy_mode,
                timeout_seconds=args.upload_timeout_seconds,
            )
            for username, password in accounts
        ]
        for future in concurrent.futures.as_completed(futures, timeout=args.upload_timeout_seconds + 60):
            try:
                uploads.append(future.result())
            except Exception as exc:
                uploads.append({"ok": False, "error": exc.__class__.__name__, "message": str(exc)})
    if args.post_upload_observe_seconds > 0:
        time.sleep(args.post_upload_observe_seconds)
    stop_event.set()
    monitor.join(timeout=5)
    result = {
        "phase": "upload",
        "ok": any(bool(item.get("ok")) for item in uploads),
        "base_url": args.base_url,
        "video": str(video_path),
        "video_size_bytes": video_path.stat().st_size,
        "privacy_mode": args.privacy_mode,
        "accounts": [username for username, _ in accounts],
        "started_at_ms": started_ms,
        "finished_at_ms": utc_ms(),
        "uploads": uploads,
        "monitor_summary": summarize_monitor(samples),
        "monitor_samples_tail": samples[-8:],
    }
    return result


def format_wait_status(state: dict[str, Any], processes: list[dict[str, Any]], elapsed_s: int) -> str:
    jobs = [
        f"job#{job.get('id')} {job.get('status')} {job.get('progress_percent')}% {job.get('stage')}"
        for job in state.get("jobs") or []
    ]
    variants = [
        f"{str(item.get('uploaded_file_id') or '')[:6]}:{item.get('name')} {item.get('height')}p "
        f"{round(int(item.get('bytes') or 0) / 1024 / 1024, 1)}MB"
        for item in state.get("variants") or []
    ]
    ffmpeg = [
        {
            "pid": proc["pid"],
            "cpu_percent": proc["cpu_percent"],
            "rss_mb": round(proc["rss_kb"] / 1024, 1),
            "threads": proc["threads"],
        }
        for proc in processes
        if proc.get("comm") == "ffmpeg"
    ]
    return json.dumps({"elapsed_s": elapsed_s, "jobs": jobs, "variants": variants, "ffmpeg": ffmpeg}, ensure_ascii=False)


def wait_for_hls(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    history: list[dict[str, Any]] = []
    last_signature = ""
    last_change_at = time.time()
    while True:
        state = db_state(Path(args.db))
        processes = ps_snapshot(args.runtime_marker)
        elapsed_s = int(time.time() - started)
        history.append({"t_ms": utc_ms(), "state": state, "processes": processes})
        if args.print_wait_status:
            print(format_wait_status(state, processes, elapsed_s), flush=True)
        jobs = state.get("jobs") or []
        if not jobs:
            return {
                "phase": "wait",
                "ok": False,
                "error": "no_hls_jobs",
                "elapsed_s": elapsed_s,
                "final_state": state,
                "final_processes": processes,
                "history_tail": history[-10:],
            }
        if jobs and all(str(job.get("status") or "") in TERMINAL_JOB_STATUSES for job in jobs):
            return {
                "phase": "wait",
                "ok": True,
                "elapsed_s": elapsed_s,
                "final_state": state,
                "final_processes": processes,
                "history_tail": history[-10:],
            }
        active_jobs = [
            job for job in jobs
            if str(job.get("status") or "") not in TERMINAL_JOB_STATUSES
        ]
        signature = json.dumps(
            [
                {
                    "id": job.get("id"),
                    "status": job.get("status"),
                    "progress_percent": job.get("progress_percent"),
                    "stage": job.get("stage"),
                    "updated_at": job.get("updated_at"),
                }
                for job in active_jobs
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature != last_signature:
            last_signature = signature
            last_change_at = time.time()
        active_processes = [
            proc for proc in processes
            if proc.get("comm") == "ffmpeg" or "hls_prepare_worker.py" in str(proc.get("args") or "")
        ]
        if (
            active_jobs
            and not active_processes
            and time.time() - last_change_at >= max(60, int(args.orphan_grace_seconds))
        ):
            return {
                "phase": "wait",
                "ok": False,
                "error": "orphaned_hls_job",
                "elapsed_s": elapsed_s,
                "final_state": state,
                "final_processes": processes,
                "history_tail": history[-10:],
            }
        if elapsed_s >= args.wait_timeout_seconds:
            return {
                "phase": "wait",
                "ok": False,
                "error": "timeout",
                "elapsed_s": elapsed_s,
                "final_state": state,
                "final_processes": processes,
                "history_tail": history[-10:],
            }
        time.sleep(args.wait_interval_seconds)


def parse_playlist(text: str) -> list[str]:
    paths: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', line)
            if match:
                paths.append(match.group(1))
            continue
        if line.startswith("#"):
            continue
        paths.append(line)
    return paths


def timed_get(session: requests.Session, url: str, token: str, timeout: int = 30) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = session.get(url, headers={"X-CSRF-Token": token}, timeout=timeout)
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "ok": response.status_code == 200,
            "status": response.status_code,
            "elapsed_ms": round(elapsed, 2),
            "bytes": len(response.content),
            "text": response.text[:300] if response.status_code != 200 else "",
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status": 0,
            "elapsed_ms": round(elapsed, 2),
            "bytes": 0,
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def sample_version_latency(base_url: str, stop_time: float, samples: list[float], errors: list[str]) -> None:
    session = requests.Session()
    if base_url.startswith("https://"):
        session.verify = False
    while time.time() < stop_time:
        started = time.perf_counter()
        try:
            response = session.get(f"{base_url}/api/version", timeout=5)
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code == 200:
                samples.append(elapsed)
            else:
                errors.append(f"status:{response.status_code}")
        except Exception as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
        time.sleep(0.25)


def choose_segment_paths(paths: list[str], max_segments: int) -> list[str]:
    media_paths = [path for path in paths if path != "init.mp4"]
    chosen: list[str] = []
    if "init.mp4" in paths:
        chosen.append("init.mp4")
    if media_paths:
        indexes = sorted({0, len(media_paths) // 2, max(0, len(media_paths) - 1)})
        chosen.extend(media_paths[index] for index in indexes)
        for path in media_paths:
            if len(chosen) >= max_segments:
                break
            if path not in chosen:
                chosen.append(path)
    return chosen[:max_segments]


def measure_variant_burst(
    *,
    base_url: str,
    session: requests.Session,
    token: str,
    video_id: int,
    variant_name: str,
    paths: list[str],
    concurrency: int,
    max_segments: int,
) -> dict[str, Any]:
    chosen_paths = choose_segment_paths(paths, max_segments)
    urls = [f"{base_url}/api/videos/{video_id}/hls/{variant_name}/{path}" for path in chosen_paths]
    version_samples: list[float] = []
    version_errors: list[str] = []
    stop_time = time.time() + 15
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as monitor_pool:
        monitor_pool.submit(sample_version_latency, base_url, stop_time, version_samples, version_errors)
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            segment_results = list(pool.map(lambda url: timed_get(session, url, token, timeout=60), urls))
        elapsed_ms = (time.perf_counter() - started) * 1000
    successful_latencies = [float(item["elapsed_ms"]) for item in segment_results if item.get("status") == 200]
    return {
        "requested_segments": len(urls),
        "ok_segments": sum(1 for item in segment_results if item.get("status") == 200),
        "bytes_total": sum(int(item.get("bytes") or 0) for item in segment_results),
        "burst_elapsed_ms": round(elapsed_ms, 2),
        "segment_latency_ms": summarize_latencies(successful_latencies),
        "version_latency_during_burst_ms": {
            **summarize_latencies(version_samples),
            "errors": version_errors[:5],
        },
        "segment_samples": segment_results,
    }


def measure_subtitle_tracks(
    *,
    base_url: str,
    session: requests.Session,
    token: str,
    tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for track in tracks:
        url = str(track.get("url") or "")
        item = {
            "name": track.get("name"),
            "label": track.get("label"),
            "language": track.get("language"),
            "is_default": bool(track.get("is_default")),
            "url": url,
        }
        if not url:
            item.update({"ok": False, "error": "missing_url"})
            results.append(item)
            continue
        started = time.perf_counter()
        try:
            response = session.get(f"{base_url}{url}", headers={"X-CSRF-Token": token}, timeout=30)
            elapsed_ms = (time.perf_counter() - started) * 1000
            content = response.content
            preview = content[:256].decode("utf-8", errors="replace")
            looks_like_webvtt = preview.lstrip("\ufeff\r\n\t ").startswith("WEBVTT")
            item.update({
                "ok": response.status_code == 200 and looks_like_webvtt,
                "status": response.status_code,
                "elapsed_ms": round(elapsed_ms, 2),
                "bytes": len(content),
                "looks_like_webvtt": looks_like_webvtt,
                "preview": preview[:120],
            })
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            item.update({
                "ok": False,
                "status": 0,
                "elapsed_ms": round(elapsed_ms, 2),
                "bytes": 0,
                "looks_like_webvtt": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            })
        if not item["ok"]:
            item.setdefault("error", "subtitle_fetch_or_format_failed")
        results.append(item)
    return results


def measure_hls_variants(args: argparse.Namespace) -> dict[str, Any]:
    auth = login(args.base_url, args.measure_username, args.measure_password)
    if not auth["ok"]:
        return {"phase": "measure", "ok": False, "error": "login_failed", "login": auth["login"]}
    session = auth["session"]
    token = auth["token"]
    state = db_state(Path(args.db))
    measurements: list[dict[str, Any]] = []
    phase_ok = True
    videos = state.get("videos") or []
    if not videos:
        phase_ok = False
    for video in videos:
        video_id = int(video["id"])
        playback = timed_get(session, f"{args.base_url}/api/videos/{video_id}/playback", token, timeout=20)
        entry: dict[str, Any] = {
            "video_id": video_id,
            "title": video.get("title"),
            "playback": playback,
            "variants": [],
            "subtitles": [],
        }
        variants: list[dict[str, Any]] = []
        if playback.get("status") != 200:
            entry["error"] = "playback_not_available"
            phase_ok = False
        else:
            status, payload, elapsed = request_json(
                session,
                "GET",
                f"{args.base_url}/api/videos/{video_id}/playback",
                headers={"X-CSRF-Token": token},
                timeout=20,
            )
            entry["playback_json"] = {
                "status": status,
                "elapsed_ms": round(elapsed * 1000, 2),
                "payload": {
                    "mode": payload.get("mode") if isinstance(payload, dict) else None,
                    "streaming_ready": payload.get("streaming_ready") if isinstance(payload, dict) else None,
                    "variants": payload.get("variants") if isinstance(payload, dict) else [],
                    "subtitles": payload.get("subtitles") if isinstance(payload, dict) else [],
                },
            }
            if isinstance(payload, dict):
                variants = list(payload.get("variants") or [])
                subtitle_tracks = list(payload.get("subtitles") or [])
                if not payload.get("streaming_ready") or not variants:
                    entry["stream_error"] = "streaming_not_ready_or_variants_missing"
                    phase_ok = False
                entry["subtitles"] = measure_subtitle_tracks(
                    base_url=args.base_url,
                    session=session,
                    token=token,
                    tracks=subtitle_tracks,
                )
                if args.expect_subtitles and not entry["subtitles"]:
                    entry["subtitle_error"] = "expected_subtitles_missing"
                    phase_ok = False
                if any(not item.get("ok") or not item.get("looks_like_webvtt") for item in entry["subtitles"]):
                    phase_ok = False
        for variant in variants:
            name = str(variant.get("name") or "")
            playlist_url = str(variant.get("playlist_url") or "")
            playlist = timed_get(session, f"{args.base_url}{playlist_url}", token, timeout=20)
            variant_entry: dict[str, Any] = {
                "name": name,
                "label": variant.get("label"),
                "height": variant.get("height"),
                "declared_bitrate": variant.get("bitrate"),
                "playlist": playlist,
            }
            if playlist.get("status") == 200:
                response = session.get(f"{args.base_url}{playlist_url}", headers={"X-CSRF-Token": token}, timeout=20)
                paths = parse_playlist(response.text)
                variant_entry["playlist_paths"] = len(paths)
                variant_entry["burst"] = measure_variant_burst(
                    base_url=args.base_url,
                    session=session,
                    token=token,
                    video_id=video_id,
                    variant_name=name,
                    paths=paths,
                    concurrency=args.segment_concurrency,
                    max_segments=args.max_segments_per_variant,
                )
                burst = variant_entry["burst"]
                if int(burst.get("ok_segments") or 0) < int(burst.get("requested_segments") or 0):
                    phase_ok = False
            else:
                phase_ok = False
            entry["variants"].append(variant_entry)
        measurements.append(entry)
    return {
        "phase": "measure",
        "ok": phase_ok,
        "state": state,
        "measurements": measurements,
        "processes_after_measure": ps_snapshot(args.runtime_marker),
    }


def parse_accounts(raw_accounts: list[str]) -> list[tuple[str, str]]:
    accounts: list[tuple[str, str]] = []
    for raw in raw_accounts:
        username, sep, password = raw.partition(":")
        username = username.strip()
        if not username:
            continue
        accounts.append((username, password if sep else username))
    return accounts


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5017")
    parser.add_argument("--video", default="/tmp/hackme_video_quality_sample.mp4")
    parser.add_argument("--db", default="/tmp/hackme_video_quality_direct_5017/runtime/database/database.db")
    parser.add_argument("--runtime-marker", default="/tmp/hackme_video_quality_direct_5017")
    parser.add_argument("--out", default="/tmp/hackme_video_hls_quality_stress_result.json")
    parser.add_argument("--accounts", nargs="*", default=["test:test", "test2:test2", "test3:test3", "test4:test4"])
    parser.add_argument("--privacy-mode", default="server_encrypted", choices=["standard_plain", "server_encrypted"])
    parser.add_argument("--upload-timeout-seconds", type=int, default=900)
    parser.add_argument("--post-upload-observe-seconds", type=int, default=180)
    parser.add_argument("--monitor-interval", type=float, default=2.0)
    parser.add_argument("--wait-timeout-seconds", type=int, default=10800)
    parser.add_argument("--wait-interval-seconds", type=int, default=30)
    parser.add_argument("--orphan-grace-seconds", type=int, default=600)
    parser.add_argument("--print-wait-status", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--measure-username", default="root")
    parser.add_argument("--measure-password", default="root")
    parser.add_argument("--segment-concurrency", type=int, default=4)
    parser.add_argument("--max-segments-per-variant", type=int, default=12)
    parser.add_argument("--expect-subtitles", action="store_true", help="Fail measure phase when playback has no usable subtitle tracks.")
    parser.add_argument("--upload", action="store_true", help="Run concurrent upload phase.")
    parser.add_argument("--wait", action="store_true", help="Wait for HLS jobs to finish.")
    parser.add_argument("--measure", action="store_true", help="Measure generated HLS quality variants.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.upload and not args.wait and not args.measure:
        args.upload = True
        args.wait = True
        args.measure = True
    phases: list[dict[str, Any]] = []
    if args.upload:
        phases.append(run_upload_phase(args))
    if args.wait:
        phases.append(wait_for_hls(args))
    if args.measure:
        phases.append(measure_hls_variants(args))
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": args.base_url,
        "db": args.db,
        "runtime_marker": args.runtime_marker,
        "phases": phases,
    }
    write_result(Path(args.out), result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if all(bool(phase.get("ok", True)) for phase in phases) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
