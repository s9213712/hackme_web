#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testing.hls_premium_sizing_probe import parse_args as parse_sizing_args  # noqa: E402
from scripts.testing.hls_premium_sizing_probe import run_probe as run_sizing_probe  # noqa: E402
from scripts.testing.realtime_proxy_stress_probe import generate_multiaudio_fixture  # noqa: E402


PROFILE_DEFAULTS = {
    "full": {
        "hls_profile": "full",
        "hls_quality_heights": "480,720",
        "hls_original_variant_mode": "always",
        "hls_audio_bitrate": "160k",
    },
    "storage_saver": {
        "hls_profile": "storage_saver",
        "hls_quality_heights": "480,720",
        "hls_original_variant_mode": "never",
        "hls_audio_bitrate": "160k",
    },
    "mobile_saver": {
        "hls_profile": "mobile_saver",
        "hls_quality_heights": "480",
        "hls_original_variant_mode": "never",
        "hls_audio_bitrate": "128k",
    },
}


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def ensure_source_fixture(args: argparse.Namespace, *, runtime_root: Path, ffmpeg_bin: str) -> dict[str, Any]:
    fixture_dir = runtime_root / "reports" / "qa" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    source_video = str(args.source_video or "").strip()
    if source_video:
        source_path = Path(source_video).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"source video not found: {source_path}")
        trim_seconds = max(0.0, float(args.source_trim_seconds or 0.0))
        if trim_seconds <= 0:
            return {
                "path": str(source_path),
                "bytes": source_path.stat().st_size,
                "source": "source_video",
                "trim_seconds": 0.0,
            }
        target = fixture_dir / f"profile-matrix-source-{int(trim_seconds)}s.mkv"
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-t",
            f"{trim_seconds:.3f}",
            "-i",
            str(source_path),
            "-map",
            "0",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(target),
        ]
        started = time.monotonic()
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=max(60, int(trim_seconds) + 30))
        return {
            "path": str(target),
            "bytes": target.stat().st_size,
            "source": "source_video_trim",
            "source_path": str(source_path),
            "trim_seconds": trim_seconds,
            "generate_ms": round((time.monotonic() - started) * 1000, 3),
        }
    target = fixture_dir / "profile-matrix-source.mkv"
    return generate_multiaudio_fixture(
        target,
        ffmpeg_bin=ffmpeg_bin,
        duration=float(args.duration),
        size=str(args.fixture_size),
        rate=int(args.fixture_rate),
        video_bitrate=str(args.video_bitrate or ""),
    )


def profile_list(raw: str) -> list[str]:
    rows: list[str] = []
    for part in str(raw or "").replace(";", ",").split(","):
        profile = part.strip().lower().replace("-", "_")
        if profile in PROFILE_DEFAULTS and profile not in rows:
            rows.append(profile)
    return rows or ["full", "storage_saver", "mobile_saver"]


def summarize_profile(profile: str, result: dict[str, Any]) -> dict[str, Any]:
    recommendation = result.get("sizing_recommendation") or {}
    resources = result.get("resource_summary") or {}
    workers = result.get("workers") or []
    wall_values = [
        float(worker.get("wall_ms") or 0.0)
        for worker in workers
        if float(worker.get("wall_ms") or 0.0) > 0
    ]
    first_result = (((workers[0] if workers else {}).get("job") or {}).get("result") or {}) if workers else {}
    variants = [
        {
            "name": item.get("name"),
            "height": item.get("height"),
            "segments": item.get("segment_count"),
        }
        for item in (first_result.get("variants") or [])
        if isinstance(item, dict)
    ]
    return {
        "profile": profile,
        "ok": bool(result.get("ok")),
        "json": result.get("json"),
        "md": result.get("md"),
        "derivative_bytes": int(recommendation.get("derivative_bytes") or 0),
        "source_bytes": int(recommendation.get("source_bytes") or 0),
        "derivative_to_source_multiplier": float(recommendation.get("derivative_to_source_multiplier") or 0.0),
        "suggested_hls_max_concurrent": recommendation.get("suggested_hls_max_concurrent"),
        "cpu_peak_percent": resources.get("total_cpu_peak_percent"),
        "cpu_avg_percent": resources.get("total_cpu_avg_percent"),
        "rss_peak_mb": resources.get("total_rss_peak_mb"),
        "ffmpeg_process_peak": resources.get("ffmpeg_process_peak"),
        "worker_wall_ms_avg": round(sum(wall_values) / len(wall_values), 3) if wall_values else 0.0,
        "worker_wall_ms_max": round(max(wall_values or [0.0]), 3),
        "variants": variants,
        "checks": result.get("checks") or {},
    }


def build_comparison(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile = {str(item.get("profile")): item for item in summaries}
    full = by_profile.get("full") or (summaries[0] if summaries else {})
    full_bytes = max(1, int(full.get("derivative_bytes") or 0))
    comparison_rows = []
    for item in summaries:
        derivative_bytes = int(item.get("derivative_bytes") or 0)
        comparison_rows.append({
            "profile": item.get("profile"),
            "derivative_bytes": derivative_bytes,
            "derivative_to_source_multiplier": item.get("derivative_to_source_multiplier"),
            "storage_reduction_vs_full_percent": round(max(0.0, (1.0 - derivative_bytes / full_bytes) * 100.0), 2),
            "cpu_peak_percent": item.get("cpu_peak_percent"),
            "rss_peak_mb": item.get("rss_peak_mb"),
            "worker_wall_ms_avg": item.get("worker_wall_ms_avg"),
            "variants": item.get("variants"),
        })
    ok_rows = [item for item in summaries if item.get("ok")]
    smallest = min(ok_rows, key=lambda item: int(item.get("derivative_bytes") or 0), default={})
    fastest = min(ok_rows, key=lambda item: float(item.get("worker_wall_ms_avg") or 0.0), default={})
    return {
        "baseline_profile": full.get("profile"),
        "rows": comparison_rows,
        "smallest_storage_profile": smallest.get("profile"),
        "fastest_profile": fastest.get("profile"),
    }


def run_profile(args: argparse.Namespace, *, profile: str, source_fixture: dict[str, Any], runtime_root: Path) -> dict[str, Any]:
    defaults = PROFILE_DEFAULTS[profile]
    profile_root = runtime_root / "profiles" / profile
    sizing_argv = [
        "--runtime-root",
        str(profile_root),
        "--jobs",
        str(int(args.jobs)),
        "--max-concurrent",
        str(int(args.max_concurrent)),
        "--source-video",
        str(source_fixture["path"]),
        "--source-trim-seconds",
        "0",
        "--hls-profile",
        defaults["hls_profile"],
        "--hls-quality-heights",
        defaults["hls_quality_heights"],
        "--hls-original-variant-mode",
        defaults["hls_original_variant_mode"],
        "--hls-audio-bitrate",
        defaults["hls_audio_bitrate"],
        "--sample-interval",
        str(float(args.sample_interval)),
        "--worker-timeout",
        str(float(args.worker_timeout)),
        "--ffmpeg-bin",
        str(args.ffmpeg_bin),
        "--ffprobe-bin",
        str(args.ffprobe_bin),
    ]
    if float(args.launch_gap) > 0:
        sizing_argv.extend(["--launch-gap", str(float(args.launch_gap))])
    sizing_args = parse_sizing_args(sizing_argv)
    return run_sizing_probe(sizing_args)


def write_reports(result: dict[str, Any], json_path: Path) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path = json_path.with_suffix(".md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Premium HLS Profile Matrix Probe",
        "",
        f"- OK: `{result.get('ok')}`",
        f"- Runtime root: `{result.get('runtime_root')}`",
        f"- Source fixture: `{(result.get('source_fixture') or {}).get('path')}`",
        f"- Jobs: `{result.get('jobs')}`",
        f"- Max concurrent: `{result.get('max_concurrent')}`",
        "",
        "## Matrix",
        "",
        "| Profile | OK | Derivative MB | Multiplier | Reduction vs full | CPU peak | RSS peak | Avg wall ms | Variants |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in (result.get("comparison") or {}).get("rows") or []:
        derivative_mb = int(row.get("derivative_bytes") or 0) / 1024 / 1024
        variants = ", ".join(
            str(item.get("name") or "")
            for item in (row.get("variants") or [])
            if isinstance(item, dict)
        )
        summary = next((item for item in result.get("profiles", []) if item.get("profile") == row.get("profile")), {})
        lines.append(
            "| "
            f"{row.get('profile')} | "
            f"{summary.get('ok')} | "
            f"{derivative_mb:.3f} | "
            f"{row.get('derivative_to_source_multiplier')} | "
            f"{row.get('storage_reduction_vs_full_percent')}% | "
            f"{row.get('cpu_peak_percent')} | "
            f"{row.get('rss_peak_mb')} | "
            f"{row.get('worker_wall_ms_avg')} | "
            f"{variants} |"
        )
    lines.extend([
        "",
        "## Recommendation",
        "",
        f"- Smallest storage profile: `{(result.get('comparison') or {}).get('smallest_storage_profile')}`",
        f"- Fastest profile: `{(result.get('comparison') or {}).get('fastest_profile')}`",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = Path(args.runtime_root).resolve()
    report_dir = runtime_root / "reports" / "qa"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.json_out).resolve() if args.json_out else report_dir / "hls_premium_profile_matrix_probe.json"
    ffmpeg_bin = shutil.which(args.ffmpeg_bin) or args.ffmpeg_bin
    ffprobe_bin = shutil.which(args.ffprobe_bin) or args.ffprobe_bin
    if not ffmpeg_bin or not ffprobe_bin:
        result = {
            "ok": False,
            "error": "ffmpeg_or_ffprobe_missing",
            "runtime_root": str(runtime_root),
        }
        write_reports(result, json_path)
        return result
    profiles = profile_list(args.profiles)
    result: dict[str, Any] = {
        "ok": False,
        "created_at": utc_now(),
        "runtime_root": str(runtime_root),
        "jobs": int(args.jobs),
        "max_concurrent": int(args.max_concurrent),
        "profiles_requested": profiles,
        "profiles": [],
    }
    try:
        source_fixture = ensure_source_fixture(args, runtime_root=runtime_root, ffmpeg_bin=ffmpeg_bin)
        result["source_fixture"] = source_fixture
        for profile in profiles:
            profile_result = run_profile(args, profile=profile, source_fixture=source_fixture, runtime_root=runtime_root)
            result["profiles"].append(summarize_profile(profile, profile_result))
        result["comparison"] = build_comparison(result["profiles"])
        result["ok"] = all(bool(item.get("ok")) for item in result["profiles"])
    except Exception as exc:
        result["error"] = exc.__class__.__name__
        result["message"] = str(exc)
    json_report, md_report = write_reports(result, json_path)
    result["json"] = str(json_report)
    result["md"] = str(md_report)
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Premium HLS profile costs on the same source fixture.")
    parser.add_argument("--runtime-root", default="/tmp/hackme_web_hls_premium_profile_matrix")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--profiles", default="full,storage_saver,mobile_saver")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--fixture-size", default="1280x720")
    parser.add_argument("--fixture-rate", type=int, default=24)
    parser.add_argument("--video-bitrate", default="")
    parser.add_argument("--source-video", default="")
    parser.add_argument("--source-trim-seconds", type=float, default=0.0)
    parser.add_argument("--launch-gap", type=float, default=0.0)
    parser.add_argument("--sample-interval", type=float, default=0.25)
    parser.add_argument("--worker-timeout", type=float, default=300.0)
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
