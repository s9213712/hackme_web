#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testing.realtime_proxy_stress_probe import generate_multiaudio_fixture  # noqa: E402
from services.job_center import ensure_job_center_schema  # noqa: E402
from services.media.streaming import ensure_media_stream_schema  # noqa: E402
from services.media.videos import ensure_video_schema  # noqa: E402
from services.security.upload_security import ensure_upload_security_schema  # noqa: E402


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db_connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                nickname TEXT,
                role TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, username, nickname, role)
            VALUES (1, 'alice', 'Alice', 'user')
            """
        )
        ensure_upload_security_schema(conn)
        ensure_video_schema(conn)
        ensure_media_stream_schema(conn)
        ensure_job_center_schema(conn)
        conn.commit()
    finally:
        conn.close()


def seed_video(conn: sqlite3.Connection, storage_root: Path, *, file_id: str, filename: str, source_path: Path, owner_user_id: int = 1) -> int:
    rel = f"users/{owner_user_id}/{file_id}/{filename}"
    target = storage_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)
    now = "2026-05-28T00:00:00"
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            original_filename_plain_for_public, mime_type_plain_for_public,
            size_bytes, created_at
        ) VALUES (?, ?, ?, 'standard_plain', 'low', 'clean', ?, 'video/x-matroska', ?, ?)
        """,
        (file_id, owner_user_id, rel, filename, target.stat().st_size, now),
    )
    cur = conn.execute(
        """
        INSERT INTO videos (
            video_uuid, owner_user_id, cloud_file_id, title, description,
            visibility, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, '', 'unlisted', 'processing', ?, ?)
        """,
        (uuid.uuid4().hex, owner_user_id, file_id, filename, now, now),
    )
    return int(cur.lastrowid)


def load_job(db_path: Path, file_id: str) -> dict[str, Any] | None:
    conn = db_connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM job_center_jobs
            WHERE source_module='media_hls_prepare' AND source_ref=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (f"media_stream:{file_id}",),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("metadata_json", "result_json"):
            try:
                data[key.replace("_json", "")] = json.loads(data.get(key) or "{}")
            except Exception:
                data[key.replace("_json", "")] = {}
        events = conn.execute(
            """
            SELECT event_type, stage, message, progress_percent, payload_json, created_at
            FROM job_center_events
            WHERE job_uuid=?
            ORDER BY id ASC
            """,
            (data["job_uuid"],),
        ).fetchall()
        data["events"] = [dict(event) for event in events]
        return data
    finally:
        conn.close()


def wait_for_stage(db_path: Path, file_id: str, stages: set[str], *, timeout_seconds: float) -> dict[str, Any] | None:
    deadline = time.time() + float(timeout_seconds)
    latest = None
    while time.time() < deadline:
        latest = load_job(db_path, file_id)
        if latest and str(latest.get("stage") or "") in stages:
            return latest
        time.sleep(0.2)
    return latest


def compact_job(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {}
    events = job.get("events") if isinstance(job.get("events"), list) else []
    return {
        "status": job.get("status"),
        "progress_percent": job.get("progress_percent"),
        "stage": job.get("stage"),
        "stage_detail": job.get("stage_detail"),
        "metadata": job.get("metadata"),
        "result": job.get("result"),
        "events": [
            {
                "event_type": event.get("event_type"),
                "stage": event.get("stage"),
                "progress_percent": event.get("progress_percent"),
            }
            for event in events
        ],
    }


def start_worker(args: argparse.Namespace, *, db_path: Path, storage_root: Path, file_id: str, video_id: int, title: str, log_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(ROOT),
        "HACKME_MEDIA_HLS_SERIALIZE_ALL": "1",
        "HACKME_MEDIA_HLS_MAX_CONCURRENT": str(int(args.max_concurrent)),
        "HACKME_MEDIA_HLS_LOCK_DIR": str(Path(args.runtime_root).resolve() / "locks" / "hls_prepare"),
        "HACKME_MEDIA_HLS_DEBUG_HOLD_SLOT_SECONDS": str(float(args.hold_seconds)),
        "HACKME_MEDIA_HLS_QUALITY_HEIGHTS": str(args.hls_quality_heights),
    })
    original_mode = str(getattr(args, "hls_original_variant_mode", "") or "").strip()
    if original_mode:
        env["HACKME_MEDIA_HLS_ORIGINAL_VARIANT_MODE"] = original_mode
    hls_profile = str(getattr(args, "hls_profile", "") or "").strip()
    if hls_profile:
        env["HACKME_MEDIA_HLS_PROFILE"] = hls_profile
    hls_audio_bitrate = str(getattr(args, "hls_audio_bitrate", "") or "").strip()
    if hls_audio_bitrate:
        env["HACKME_MEDIA_HLS_AUDIO_BITRATE"] = hls_audio_bitrate
    command = [
        sys.executable,
        str(ROOT / "scripts" / "media" / "hls_prepare_worker.py"),
        "--db-path",
        str(db_path),
        "--storage-root",
        str(storage_root),
        "--file-id",
        file_id,
        "--video-id",
        str(int(video_id)),
        "--owner-user-id",
        "1",
        "--title",
        title,
        "--ffmpeg-bin",
        args.ffmpeg_bin,
        "--ffprobe-bin",
        args.ffprobe_bin,
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    proc._hackme_log_handle = handle  # type: ignore[attr-defined]
    return proc


def close_proc_log(proc: subprocess.Popen[str] | None) -> None:
    if not proc:
        return
    handle = getattr(proc, "_hackme_log_handle", None)
    if handle:
        try:
            handle.close()
        except Exception:
            pass


def wait_proc(proc: subprocess.Popen[str], timeout_seconds: float) -> int:
    try:
        return proc.wait(timeout=float(timeout_seconds))
    finally:
        close_proc_log(proc)


def write_reports(result: dict[str, Any], json_path: Path) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    first = compact_job(result.get("first_job"))
    second = compact_job(result.get("second_job"))
    lines = [
        "# HLS Worker Slot Probe",
        "",
        f"- OK: `{result.get('ok')}`",
        f"- Runtime root: `{result.get('runtime_root')}`",
        f"- Max concurrent: `{result.get('max_concurrent')}`",
        f"- Hold seconds: `{result.get('hold_seconds')}`",
        "",
        "## Checks",
        "",
    ]
    for key, value in (result.get("checks") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend([
        "",
        "## Jobs",
        "",
        f"- First job: `{first}`",
        f"- Second job: `{second}`",
        "",
        "## Artifacts",
        "",
        f"- First worker log: `{result.get('first_log')}`",
        f"- Second worker log: `{result.get('second_log')}`",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = Path(args.runtime_root).resolve()
    report_dir = runtime_root / "reports" / "qa"
    storage_root = runtime_root / "storage"
    db_path = runtime_root / "database" / "database.db"
    fixture_dir = report_dir / "fixtures"
    report_dir.mkdir(parents=True, exist_ok=True)
    storage_root.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    ffmpeg_bin = shutil.which(args.ffmpeg_bin) or args.ffmpeg_bin
    ffprobe_bin = shutil.which(args.ffprobe_bin) or args.ffprobe_bin
    if not ffmpeg_bin or not ffprobe_bin:
        result = {
            "ok": False,
            "error": "ffmpeg_or_ffprobe_missing",
            "runtime_root": str(runtime_root),
        }
        write_reports(result, Path(args.json_out).resolve() if args.json_out else report_dir / "hls_worker_slot_probe.json")
        return result
    fixture_a = fixture_dir / "premium-hls-a.mkv"
    fixture_b = fixture_dir / "premium-hls-b.mkv"
    fixture_meta_a = generate_multiaudio_fixture(fixture_a, ffmpeg_bin=ffmpeg_bin, duration=float(args.duration), size=args.fixture_size, rate=int(args.fixture_rate))
    fixture_meta_b = generate_multiaudio_fixture(fixture_b, ffmpeg_bin=ffmpeg_bin, duration=float(args.duration), size=args.fixture_size, rate=int(args.fixture_rate))
    conn = db_connect(db_path)
    try:
        first_video_id = seed_video(conn, storage_root, file_id="premium-hls-a", filename="premium-a.mkv", source_path=fixture_a)
        second_video_id = seed_video(conn, storage_root, file_id="premium-hls-b", filename="premium-b.mkv", source_path=fixture_b)
        conn.commit()
    finally:
        conn.close()

    json_path = Path(args.json_out).resolve() if args.json_out else report_dir / "hls_worker_slot_probe.json"
    result: dict[str, Any] = {
        "ok": False,
        "created_at": utc_now(),
        "runtime_root": str(runtime_root),
        "db_path": str(db_path),
        "storage_root": str(storage_root),
        "max_concurrent": int(args.max_concurrent),
        "hold_seconds": float(args.hold_seconds),
        "fixtures": [fixture_meta_a, fixture_meta_b],
        "checks": {},
    }
    first_proc = second_proc = None
    try:
        first_log = report_dir / "hls_worker_slot_first.log"
        second_log = report_dir / "hls_worker_slot_second.log"
        result["first_log"] = str(first_log)
        result["second_log"] = str(second_log)
        first_proc = start_worker(args, db_path=db_path, storage_root=storage_root, file_id="premium-hls-a", video_id=first_video_id, title="Premium HLS A", log_path=first_log)
        first_acquired = wait_for_stage(db_path, "premium-hls-a", {"worker_slot_hold", "transcoding", "ready"}, timeout_seconds=float(args.stage_timeout))
        second_proc = start_worker(args, db_path=db_path, storage_root=storage_root, file_id="premium-hls-b", video_id=second_video_id, title="Premium HLS B", log_path=second_log)
        second_waiting = wait_for_stage(db_path, "premium-hls-b", {"waiting_worker_slot"}, timeout_seconds=float(args.stage_timeout))
        first_rc = wait_proc(first_proc, float(args.worker_timeout))
        second_acquired = wait_for_stage(db_path, "premium-hls-b", {"worker_slot_acquired", "worker_slot_hold", "transcoding", "ready"}, timeout_seconds=float(args.stage_timeout))
        second_rc = wait_proc(second_proc, float(args.worker_timeout))
        first_job = load_job(db_path, "premium-hls-a")
        second_job = load_job(db_path, "premium-hls-b")
        first_events = [event.get("stage") for event in ((first_job or {}).get("events") or [])]
        second_events = [event.get("stage") for event in ((second_job or {}).get("events") or [])]
        result.update({
            "first_rc": first_rc,
            "second_rc": second_rc,
            "first_acquired_sample": compact_job(first_acquired),
            "second_waiting_sample": compact_job(second_waiting),
            "second_acquired_sample": compact_job(second_acquired),
            "first_job": first_job,
            "second_job": second_job,
        })
        checks = {
            "first_worker_succeeded": first_rc == 0 and (first_job or {}).get("status") == "succeeded",
            "second_worker_succeeded": second_rc == 0 and (second_job or {}).get("status") == "succeeded",
            "first_acquired_global_slot": bool(((first_acquired or {}).get("metadata") or {}).get("worker_slot", {}).get("scope") == "global"),
            "second_waited_for_slot": bool(second_waiting and second_waiting.get("stage") == "waiting_worker_slot"),
            "second_acquired_after_wait": "waiting_worker_slot" in second_events and any(stage in second_events for stage in ("worker_slot_acquired", "worker_slot_hold", "transcoding", "ready")),
            "second_result_has_slot": bool(((second_job or {}).get("result") or {}).get("worker_slot", {}).get("scope") == "global"),
            "slot_limit_one": bool(((second_waiting or {}).get("metadata") or {}).get("worker_slot", {}).get("limit") == 1),
        }
        result["checks"] = checks
        result["ok"] = all(checks.values())
        return result
    except Exception as exc:
        result["error"] = exc.__class__.__name__
        result["message"] = str(exc)
        return result
    finally:
        for proc in (first_proc, second_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            close_proc_log(proc)
        json_report, md_report = write_reports(result, json_path)
        result["json"] = str(json_report)
        result["md"] = str(md_report)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a live dual-worker Premium HLS slot probe.")
    parser.add_argument("--runtime-root", default="/tmp/hackme_web_hls_worker_slot_probe")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--fixture-size", default="320x180")
    parser.add_argument("--fixture-rate", type=int, default=24)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--hold-seconds", type=float, default=4.0)
    parser.add_argument("--stage-timeout", type=float, default=15.0)
    parser.add_argument("--worker-timeout", type=float, default=90.0)
    parser.add_argument("--hls-quality-heights", default="480")
    parser.add_argument("--hls-original-variant-mode", default="")
    parser.add_argument("--hls-profile", default="")
    parser.add_argument("--hls-audio-bitrate", default="")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--ffprobe-bin", default="ffprobe")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = run_probe(args)
    print(json.dumps({"ok": result.get("ok"), "json": result.get("json"), "md": result.get("md")}, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
