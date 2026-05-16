#!/usr/bin/env python3
"""Build HLS derivatives outside the Flask server process."""

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.media.streaming import ensure_media_stream_schema, prepare_stream_asset  # noqa: E402
from services.media.videos import ensure_video_schema  # noqa: E402
from services.job_center import (  # noqa: E402
    add_job_event,
    create_job,
    get_job_by_source,
    update_job,
)
from services.server.database import get_db as open_db  # noqa: E402
from services.system.notifications import create_notification_if_enabled  # noqa: E402

HLS_JOB_SOURCE_MODULE = "media_hls_prepare"


def _now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _build_fernet(secret):
    secret = str(secret or "").strip()
    if not secret:
        return None
    try:
        return Fernet(secret.encode("utf-8"))
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        return Fernet(derived)


def _load_server_file_fernet(*, key_path="", env_name="SERVER_FILE_ENCRYPTION_KEY"):
    secret = ""
    if key_path:
        try:
            secret = Path(key_path).read_text(encoding="utf-8").strip()
        except Exception:
            secret = ""
    if not secret and env_name:
        secret = os.environ.get(env_name, "").strip()
    return _build_fernet(secret)


def _load_stream_file(conn, file_id):
    row = conn.execute(
        "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
        (str(file_id or ""),),
    ).fetchone()
    if not row:
        raise ValueError("找不到影音檔案")
    return row


def _hls_job_source_ref(file_id):
    return f"media_stream:{str(file_id or '').strip()}"


def _row_value(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except Exception:
        return default


def _sync_hls_platform_job(
    conn,
    *,
    args,
    file_row=None,
    status="running",
    progress_percent=0,
    stage="processing",
    stage_detail="",
    error_message="",
    result=None,
):
    try:
        file_id = str(args.file_id or _row_value(file_row, "id", ""))
        source_ref = _hls_job_source_ref(file_id)
        existing = get_job_by_source(conn, HLS_JOB_SOURCE_MODULE, source_ref)
        owner_user_id = int(args.owner_user_id or _row_value(file_row, "owner_user_id", 0) or 0)
        title = str(args.title or _row_value(file_row, "original_filename_plain_for_public", "") or "影音").strip() or "影音"
        metadata = {
            "file_id": file_id,
            "video_id": int(args.video_id or 0),
            "privacy_mode": str(_row_value(file_row, "privacy_mode", "") or ""),
            "source_process": "hls_prepare_worker",
        }
        if existing:
            updates = {
                "status": status,
                "progress_percent": progress_percent,
                "stage": stage,
                "stage_detail": stage_detail,
                "metadata_json": metadata,
            }
            if status == "running" and not existing.get("started_at"):
                updates["started_at"] = _now_iso()
            if status in {"succeeded", "failed", "cancelled", "expired"}:
                updates["finished_at"] = _now_iso()
            if result is not None:
                updates["result_json"] = result
            if error_message:
                updates["error_message"] = error_message
                updates["error_stage"] = stage
            defer_progress = status not in {"succeeded", "failed", "cancelled", "expired"}
            job = update_job(conn, existing["job_uuid"], defer_progress=defer_progress, **updates)
            add_job_event(
                conn,
                job["job_uuid"],
                event_type="failed" if status == "failed" else "progress",
                stage=stage,
                message=stage_detail or error_message or "HLS 任務狀態更新",
                progress_percent=progress_percent,
                payload=metadata,
                defer_progress=defer_progress,
            )
            return job
        return create_job(
            conn,
            owner_user_id=owner_user_id or None,
            created_by_user_id=owner_user_id or None,
            job_type="video.hls.prepare",
            title=f"HLS 處理：{title[:96]}",
            description="影音 HLS 衍生檔建立、轉封裝與可播放狀態追蹤",
            source_module=HLS_JOB_SOURCE_MODULE,
            source_ref=source_ref,
            status=status,
            progress_percent=progress_percent,
            stage=stage,
            stage_detail=stage_detail,
            metadata=metadata,
        )
    except Exception:
        return None


def _mark_video_ready(conn, *, file_id, video_id=0, duration_seconds=0):
    now = _now_iso()
    duration = int(float(duration_seconds or 0))
    if int(video_id or 0) > 0:
        conn.execute(
            """
            UPDATE videos
            SET status='ready', duration_seconds=?, updated_at=?
            WHERE id=? AND cloud_file_id=? AND deleted_at IS NULL
            """,
            (duration, now, int(video_id), str(file_id)),
        )
        return
    conn.execute(
        """
        UPDATE videos
        SET status='ready', duration_seconds=?, updated_at=?
        WHERE cloud_file_id=? AND deleted_at IS NULL
        """,
        (duration, now, str(file_id)),
    )


def _notify(conn, *, owner_user_id=0, video_id=0, title="", ok=True, error_message=""):
    if int(owner_user_id or 0) <= 0:
        return
    safe_title = str(title or "影音").strip() or "影音"
    if ok:
        create_notification_if_enabled(
            conn,
            user_id=int(owner_user_id),
            type="video_hls_ready",
            title="影音處理完成",
            body=f"「{safe_title}」已完成 HLS 處理，現在可以在影音頁播放與分享。",
            link=f"/#videos/{int(video_id)}" if int(video_id or 0) > 0 else "/#videos",
        )
        return
    create_notification_if_enabled(
        conn,
        user_id=int(owner_user_id),
        type="video_hls_failed",
        title="影音處理失敗",
        body=f"「{safe_title}」的 HLS 處理失敗：{str(error_message or '請稍後重試')[:220]}",
        link="/#shares",
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Prepare one media file as an HLS derivative asset.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--storage-root", required=True)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--video-id", type=int, default=0)
    parser.add_argument("--owner-user-id", type=int, default=0)
    parser.add_argument("--title", default="")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    parser.add_argument("--ffprobe-bin", default="ffprobe")
    parser.add_argument("--server-file-key-path", default="")
    parser.add_argument("--server-file-key-env", default="SERVER_FILE_ENCRYPTION_KEY")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    conn = open_db(args.db_path)
    try:
        ensure_video_schema(conn)
        ensure_media_stream_schema(conn)
        file_row = _load_stream_file(conn, args.file_id)
        _sync_hls_platform_job(
            conn,
            args=args,
            file_row=file_row,
            status="running",
            progress_percent=15,
            stage="transcoding",
            stage_detail="HLS 外部程序正在轉封裝與產生播放清單。",
        )
        conn.commit()
        server_file_fernet = _load_server_file_fernet(
            key_path=args.server_file_key_path,
            env_name=args.server_file_key_env,
        )
        asset = prepare_stream_asset(
            conn,
            file_row=file_row,
            storage_root=args.storage_root,
            server_file_fernet=server_file_fernet,
            ffprobe_bin=args.ffprobe_bin,
            ffmpeg_bin=args.ffmpeg_bin,
        )
        if asset and asset.get("status") == "ready":
            _mark_video_ready(
                conn,
                file_id=args.file_id,
                video_id=args.video_id,
                duration_seconds=asset.get("duration_seconds", 0),
            )
            _notify(
                conn,
                owner_user_id=args.owner_user_id or int(file_row["owner_user_id"]),
                video_id=args.video_id,
                title=args.title,
                ok=True,
            )
            _sync_hls_platform_job(
                conn,
                args=args,
                file_row=file_row,
                status="succeeded",
                progress_percent=100,
                stage="ready",
                stage_detail="HLS 處理完成，影音可以播放與分享。",
                result=asset,
            )
            conn.commit()
            print(json.dumps({"ok": True, "asset": asset}, ensure_ascii=False), flush=True)
            return 0
        _sync_hls_platform_job(
            conn,
            args=args,
            file_row=file_row,
            status="failed",
            progress_percent=100,
            stage="not_ready",
            stage_detail="HLS 處理結束但未產生可播放串流。",
            error_message="stream_not_ready",
            result=asset or {},
        )
        conn.commit()
        print(json.dumps({"ok": False, "asset": asset, "error": "stream_not_ready"}, ensure_ascii=False), flush=True)
        return 1
    except sqlite3.Error as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        try:
            try:
                file_row = _load_stream_file(conn, args.file_id)
            except Exception:
                file_row = None
            _sync_hls_platform_job(
                conn,
                args=args,
                file_row=file_row,
                status="failed",
                progress_percent=100,
                stage="failed",
                stage_detail=f"HLS 處理失敗：{message[:220]}",
                error_message=message,
            )
            _notify(
                conn,
                owner_user_id=args.owner_user_id,
                video_id=args.video_id,
                title=args.title,
                ok=False,
                error_message=message,
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
