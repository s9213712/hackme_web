#!/usr/bin/env python3
import argparse
import json
import statistics
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_PATHS = ["/", "/api/version", "/api/site-config", "/api/captcha/challenge"]


def request_once(base_url, path, timeout):
    started = time.perf_counter()
    url = base_url.rstrip("/") + path
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "hackme-web-stress/1.0"})
        context = ssl._create_unverified_context() if url.startswith("https://") else None
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            resp.read(2048)
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except Exception:
        status = 0
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {"path": path, "status": status, "elapsed_ms": elapsed_ms}


def percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((pct / 100) * (len(values) - 1)))))
    return values[idx]


def run(args):
    paths = [item.strip() for item in args.paths.split(",") if item.strip()] if args.paths else DEFAULT_PATHS
    total = max(1, args.requests)
    concurrency = max(1, args.concurrency)
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for idx in range(total):
            path = paths[idx % len(paths)]
            futures.append(pool.submit(request_once, args.target, path, args.timeout))
        for fut in as_completed(futures):
            results.append(fut.result())
    duration = max(time.perf_counter() - started, 0.001)
    latencies = [item["elapsed_ms"] for item in results if item["status"] > 0]
    ok_count = sum(1 for item in results if 200 <= item["status"] < 400)
    server_errors = sum(1 for item in results if item["status"] in {500, 502, 503})
    failed = sum(1 for item in results if item["status"] == 0 or item["status"] >= 400)
    by_status = {}
    for item in results:
        by_status[str(item["status"])] = by_status.get(str(item["status"]), 0) + 1
    summary = {
        "target": args.target,
        "paths": paths,
        "requests": total,
        "concurrency": concurrency,
        "duration_seconds": round(duration, 3),
        "approx_requests_per_second": round(total / duration, 2),
        "ok_count": ok_count,
        "failed_count": failed,
        "server_error_count": server_errors,
        "status_counts": by_status,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "avg": round(statistics.mean(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 50), 2) if latencies else None,
            "p95": round(percentile(latencies, 95), 2) if latencies else None,
            "p99": round(percentile(latencies, 99), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
    }
    return summary


def write_report(summary, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    json_path = out / f"stress_{stamp}.json"
    md_path = out / f"stress_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(
        "\n".join(
            [
                "# Hackme Web Stress Test",
                "",
                f"- target: `{summary['target']}`",
                f"- requests: `{summary['requests']}`",
                f"- concurrency: `{summary['concurrency']}`",
                f"- approximate RPS: `{summary['approx_requests_per_second']}`",
                f"- failed: `{summary['failed_count']}`",
                f"- server errors: `{summary['server_error_count']}`",
                f"- latency avg/p95/p99 ms: `{summary['latency_ms']['avg']}` / `{summary['latency_ms']['p95']}` / `{summary['latency_ms']['p99']}`",
                "",
                "## Status Counts",
                "",
                "```json",
                json.dumps(summary["status_counts"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Estimate Hackme Web HTTP traffic capacity.")
    parser.add_argument("--target", default="http://127.0.0.1:5000", help="Base URL to test.")
    parser.add_argument("--requests", type=int, default=200, help="Total requests.")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent workers.")
    parser.add_argument("--paths", default=",".join(DEFAULT_PATHS), help="Comma-separated GET paths.")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-request timeout seconds.")
    parser.add_argument("--out", default="security/reports", help="Report output directory.")
    args = parser.parse_args()
    summary = run(args)
    json_path, md_path = write_report(summary, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"reports: {json_path} {md_path}")
    raise SystemExit(1 if summary["server_error_count"] else 0)


if __name__ == "__main__":
    main()
