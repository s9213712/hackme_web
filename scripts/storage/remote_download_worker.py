#!/usr/bin/env python3
"""External remote-download worker for cloud drive tasks.

The Flask process owns authorization, quota checks, and final storage writes.
This worker owns the long-running network transfer and reports JSON lines to
stdout so the parent can update task progress without downloading in-process.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.storage.remote_downloads import (  # noqa: E402
    RemoteDownloadError,
    download_remote_url,
    download_torrent_file_with_aria2,
    download_torrent_url_with_aria2,
)


def _emit(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _progress(event):
    _emit({"type": "progress", "event": event or {}})


def _positive_int_or_none(value):
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one cloud-drive remote download")
    parser.add_argument("--source-type", required=True, choices=["direct", "magnet", "torrent_url", "torrent_file"])
    parser.add_argument("--url", default="")
    parser.add_argument("--torrent-path", default="")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-bytes", type=int, default=0)
    parser.add_argument("--rate-limit-kb-per-sec", type=int, default=0)
    args = parser.parse_args(argv)

    max_bytes = _positive_int_or_none(args.max_bytes)
    rate_limit = _positive_int_or_none(args.rate_limit_kb_per_sec)

    try:
        if args.source_type == "torrent_file":
            downloaded = download_torrent_file_with_aria2(
                args.torrent_path,
                display_name=args.display_name or "BT 檔案",
                timeout_seconds=args.timeout_seconds,
                max_bytes=max_bytes,
                progress_callback=_progress,
                rate_limit_kb_per_sec=rate_limit,
            )
        elif args.source_type == "torrent_url":
            downloaded = download_torrent_url_with_aria2(
                args.url,
                timeout_seconds=args.timeout_seconds,
                max_bytes=max_bytes,
                progress_callback=_progress,
                rate_limit_kb_per_sec=rate_limit,
            )
        else:
            downloaded = download_remote_url(
                args.url,
                timeout_seconds=args.timeout_seconds,
                max_bytes=max_bytes,
                progress_callback=_progress,
                rate_limit_kb_per_sec=rate_limit,
                treat_torrent_as_bt=args.source_type != "direct",
            )
        _emit({
            "type": "result",
            "path": downloaded.path,
            "filename": downloaded.filename,
            "mimetype": downloaded.mimetype,
            "cleanup_dir": downloaded.cleanup_dir,
        })
        return 0
    except RemoteDownloadError as exc:
        _emit({"type": "error", "message": str(exc)})
        return 2
    except Exception as exc:
        _emit({"type": "error", "message": f"遠端下載 worker 失敗：{exc.__class__.__name__}"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
