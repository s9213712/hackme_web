"""Release bundle and QA artifact indexing helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_EXTENSIONS = {
    ".json",
    ".md",
    ".txt",
    ".log",
    ".out",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".zip",
}
QA_RUNS_INDEX = "runs_index.json"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _safe_slug(value: str, fallback: str = "qa") -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value or "").strip())
    text = text.strip("._-")
    return text[:80] or fallback


def git_meta(repo_dir: str | os.PathLike[str]) -> dict[str, str]:
    root = str(repo_dir or "")

    def run(*args: str) -> str:
        if not root:
            return ""
        try:
            return subprocess.check_output(
                ["git", "-C", root, *args],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            ).strip()
        except Exception:
            return ""

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": run("status", "--short"),
    }


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    text = str(path).lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "screenshot"
    if "playwright" in text:
        return "playwright"
    if "member_probe" in text:
        return "member_probe"
    if "server" in text and suffix in {".log", ".out", ".txt"}:
        return "server_log"
    if suffix == ".md":
        return "markdown_report"
    if suffix == ".json":
        return "json_report"
    return "artifact"


def _artifact_record(path: Path, *, source: str, base_dir: Path, reports_dir: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.suffix.lower() not in ARTIFACT_EXTENSIONS:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "source": source,
        "kind": _artifact_kind(path),
        "path": _public_path(path, base_dir=base_dir, reports_dir=reports_dir),
        "absolute_path": str(path.resolve()),
        "name": path.name,
        "size_bytes": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _public_path(path: Path, *, base_dir: Path, reports_dir: Path) -> str:
    resolved = path.resolve()
    for root, prefix in ((reports_dir.resolve(), "reports"), (base_dir.resolve(), "repo")):
        try:
            return f"{prefix}/{resolved.relative_to(root).as_posix()}"
        except ValueError:
            pass
    return str(resolved)


def _iter_artifact_roots(base_dir: Path, reports_dir: Path, tmp_root: Path) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    qa_runs = reports_dir / "qa_runs"
    if qa_runs.exists():
        roots.append(("qa_run", qa_runs))
    if reports_dir.exists():
        roots.append(("runtime_reports", reports_dir))
    docs_reports = base_dir / "docs" / "AGENTS" / "reports"
    if docs_reports.exists():
        roots.append(("docs_agent_reports", docs_reports))
    if tmp_root.exists():
        tmp_candidates = []
        for item in tmp_root.glob("hackme_web*"):
            if not item.is_dir():
                continue
            try:
                tmp_candidates.append((item.stat().st_mtime, item))
            except OSError:
                continue
        for _, item in sorted(tmp_candidates, reverse=True)[:20]:
            roots.append(("tmp_run", item))
    return roots


def _runs_index_path(reports_dir: Path) -> Path:
    return reports_dir / "qa_artifacts" / QA_RUNS_INDEX


def _load_qa_runs(reports_dir: Path) -> list[dict[str, Any]]:
    payload = safe_read_json(_runs_index_path(reports_dir))
    runs = payload.get("runs") if isinstance(payload, dict) else []
    runs = runs if isinstance(runs, list) else []
    return [run for run in runs if isinstance(run, dict)]


def _write_qa_runs(reports_dir: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = sorted(runs, key=lambda item: str(item.get("created_at") or ""), reverse=True)[:200]
    by_status = Counter(str(item.get("status") or "unknown") for item in normalized)
    payload = {
        "ok": True,
        "generated_at": utc_iso(),
        "summary": {
            "run_count": len(normalized),
            "by_status": dict(sorted(by_status.items())),
            "latest_status": str(normalized[0].get("status") or "") if normalized else "",
            "latest_run_id": str(normalized[0].get("run_id") or "") if normalized else "",
        },
        "runs": normalized,
    }
    write_json(_runs_index_path(reports_dir), payload)
    return payload


def _iter_source_artifact_paths(paths: list[str | os.PathLike[str]], *, limit: int) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths or []:
        path = Path(raw).expanduser()
        candidates = []
        if path.is_dir():
            try:
                candidates = sorted(path.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                candidates = []
        else:
            candidates = [path]
        for candidate in candidates:
            if len(found) >= max(1, int(limit or 100)):
                return found
            if not candidate.is_file() or candidate.suffix.lower() not in ARTIFACT_EXTENSIONS:
                continue
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(candidate)
    return found


def register_qa_run(
    *,
    base_dir: str | os.PathLike[str],
    reports_dir: str | os.PathLike[str],
    git_repo_dir: str | os.PathLike[str] | None = None,
    suite: str,
    status: str,
    artifact_paths: list[str | os.PathLike[str]] | None = None,
    command: str = "",
    summary: dict[str, Any] | None = None,
    run_id: str | None = None,
    max_artifacts: int = 100,
    max_copy_bytes: int = 25 * 1024 * 1024,
) -> dict[str, Any]:
    base = Path(base_dir).resolve()
    reports = Path(reports_dir).resolve()
    created_at = utc_iso()
    clean_suite = _safe_slug(suite or "qa")
    normalized_status = str(status or "unknown").strip().lower() or "unknown"
    if normalized_status in {"ok", "passed", "green"}:
        normalized_status = "pass"
    elif normalized_status in {"failed", "red"}:
        normalized_status = "fail"
    clean_run_id = _safe_slug(run_id or f"{utc_stamp()}_{clean_suite}", clean_suite)
    run_dir = reports / "qa_runs" / clean_run_id
    archived: list[dict[str, Any]] = []
    for source_path in _iter_source_artifact_paths(list(artifact_paths or []), limit=max_artifacts):
        try:
            if source_path.stat().st_size > max_copy_bytes:
                record = _artifact_record(source_path, source="external_reference", base_dir=base, reports_dir=reports)
                if record:
                    record["archived"] = False
                    record["reason"] = "file exceeds max_copy_bytes"
                    archived.append(record)
                continue
            kind = _artifact_kind(source_path)
            target_dir = run_dir / kind
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source_path.name
            if target.exists():
                target = target_dir / f"{source_path.stem}_{len(archived) + 1}{source_path.suffix}"
            shutil.copy2(source_path, target)
            record = _artifact_record(target, source="qa_run", base_dir=base, reports_dir=reports)
            if record:
                record["archived"] = True
                record["source_absolute_path"] = str(source_path.resolve())
                archived.append(record)
        except OSError:
            continue
    manifest = {
        "ok": True,
        "run_id": clean_run_id,
        "suite": str(suite or "qa"),
        "status": normalized_status,
        "passed": normalized_status == "pass",
        "created_at": created_at,
        "command": str(command or ""),
        "git": git_meta(git_repo_dir or base),
        "summary": summary if isinstance(summary, dict) else {},
        "artifact_count": len(archived),
        "artifacts": archived,
    }
    manifest_path = run_dir / "manifest.json"
    write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    runs = [run for run in _load_qa_runs(reports) if run.get("run_id") != clean_run_id]
    runs.insert(0, {
        "run_id": clean_run_id,
        "suite": manifest["suite"],
        "status": manifest["status"],
        "passed": manifest["passed"],
        "created_at": created_at,
        "command": manifest["command"],
        "commit": manifest["git"].get("commit", ""),
        "branch": manifest["git"].get("branch", ""),
        "artifact_count": len(archived),
        "manifest_path": str(manifest_path),
    })
    manifest["runs_index"] = _write_qa_runs(reports, runs)
    return manifest


def build_qa_artifact_index(
    *,
    base_dir: str | os.PathLike[str],
    reports_dir: str | os.PathLike[str],
    git_repo_dir: str | os.PathLike[str] | None = None,
    tmp_root: str | os.PathLike[str] = "/tmp",
    limit: int = 300,
    persist: bool = True,
) -> dict[str, Any]:
    base = Path(base_dir).resolve()
    reports = Path(reports_dir).resolve()
    tmp = Path(tmp_root).resolve()
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    roots = _iter_artifact_roots(base, reports, tmp)

    for source, root in roots:
        try:
            candidates = sorted(root.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for path in candidates:
            if len(artifacts) >= max(1, int(limit or 300)):
                break
            if not path.is_file() or path.suffix.lower() not in ARTIFACT_EXTENSIONS:
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                stat = path.stat()
            except OSError:
                continue
            artifacts.append(
                {
                    "source": source,
                    "kind": _artifact_kind(path),
                    "path": _public_path(path, base_dir=base, reports_dir=reports),
                    "absolute_path": resolved,
                    "name": path.name,
                    "size_bytes": int(stat.st_size),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )

    by_kind = Counter(item["kind"] for item in artifacts)
    by_source = Counter(item["source"] for item in artifacts)
    qa_runs = _load_qa_runs(reports)
    run_status_counts = Counter(str(item.get("status") or "unknown") for item in qa_runs)
    payload = {
        "ok": True,
        "generated_at": utc_iso(),
        "git": git_meta(git_repo_dir or base),
        "summary": {
            "artifact_count": len(artifacts),
            "by_kind": dict(sorted(by_kind.items())),
            "by_source": dict(sorted(by_source.items())),
            "qa_run_count": len(qa_runs),
            "qa_runs_by_status": dict(sorted(run_status_counts.items())),
        },
        "qa_runs": qa_runs[:20],
        "artifacts": artifacts,
    }
    if persist:
        out = reports / "qa_artifacts" / "index.json"
        write_json(out, payload)
        payload["index_path"] = str(out)
    return payload


def _latest_release_bundle(reports_dir: Path) -> dict[str, Any] | None:
    bundle_dir = reports_dir / "release_bundles"
    if not bundle_dir.exists():
        return None
    bundles = sorted(bundle_dir.glob("release_bundle_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not bundles:
        return None
    payload = safe_read_json(bundles[0])
    if payload:
        payload.setdefault("bundle_path", str(bundles[0]))
        return payload
    return None


def release_bundle_status(*, reports_dir: str | os.PathLike[str]) -> dict[str, Any]:
    reports = Path(reports_dir).resolve()
    marker_path = reports / "security" / "production_gate" / "production_ready_marker.json"
    marker = safe_read_json(marker_path) if marker_path.exists() else {}
    latest = _latest_release_bundle(reports)
    return {
        "ok": True,
        "ready": bool(marker.get("ready")),
        "marker": marker,
        "marker_path": str(marker_path) if marker_path.exists() else "",
        "latest_bundle": latest,
    }


def render_release_bundle_markdown(bundle: dict[str, Any]) -> str:
    req = bundle.get("production_requirements") or {}
    qa = bundle.get("qa_artifacts") or {}
    git = bundle.get("git") or {}
    lines = [
        "# Production Release Bundle",
        "",
        f"- Created at: `{bundle.get('created_at') or '-'}`",
        f"- Created by: `{bundle.get('created_by') or '-'}`",
        f"- Status: `{bundle.get('status') or '-'}`",
        f"- Branch: `{git.get('branch') or '-'}`",
        f"- Commit: `{git.get('commit') or '-'}`",
        f"- Production gate: `{'pass' if req.get('ok') else 'blocked'}`",
        f"- Required reports: `{len(req.get('required') or [])}`",
        f"- Missing reports: `{', '.join(req.get('missing') or []) or 'none'}`",
        f"- Failed reports: `{', '.join(req.get('failed') or []) or 'none'}`",
        f"- QA artifacts indexed: `{(qa.get('summary') or {}).get('artifact_count', 0)}`",
        "",
        "## Report Rollup",
        "",
    ]
    reports = req.get("reports") if isinstance(req.get("reports"), dict) else {}
    for report_type in req.get("required") or []:
        row = reports.get(report_type) or {}
        state = "PASS" if row and report_type not in set(req.get("missing") or []) and report_type not in set(req.get("failed") or []) else "BLOCKED"
        lines.append(
            f"- `{report_type}`: {state}"
            f" commit `{str(row.get('target_commit') or '')[:8] or '-'}`"
            f" source `{row.get('report_source') or row.get('trust_level') or '-'}`"
        )
    return "\n".join(lines)


def create_release_bundle(
    *,
    base_dir: str | os.PathLike[str],
    reports_dir: str | os.PathLike[str],
    git_repo_dir: str | os.PathLike[str] | None,
    created_by: str,
    production_requirements: dict[str, Any],
    qa_artifacts: dict[str, Any],
    mark_ready: bool = True,
) -> dict[str, Any]:
    reports = Path(reports_dir).resolve()
    ready = bool(production_requirements.get("ok"))
    stamp = utc_stamp()
    bundle = {
        "ok": True,
        "created_at": utc_iso(),
        "created_by": str(created_by or "root"),
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "git": git_meta(git_repo_dir or base_dir),
        "production_requirements": production_requirements,
        "qa_artifacts": {
            "generated_at": qa_artifacts.get("generated_at"),
            "summary": qa_artifacts.get("summary") or {},
            "index_path": qa_artifacts.get("index_path") or "",
        },
    }
    bundle_path = reports / "release_bundles" / f"release_bundle_{stamp}.json"
    md_path = reports / "release_bundles" / f"release_bundle_{stamp}.md"
    write_json(bundle_path, bundle)
    write_text(md_path, render_release_bundle_markdown(bundle))
    bundle["bundle_path"] = str(bundle_path)
    bundle["markdown_path"] = str(md_path)
    if mark_ready and ready:
        marker = {
            "ready": True,
            "marked_at": utc_iso(),
            "marked_by": str(created_by or "root"),
            "bundle_path": str(bundle_path),
            "target_commit": (bundle.get("git") or {}).get("commit") or "",
            "target_branch": (bundle.get("git") or {}).get("branch") or "",
        }
        write_json(reports / "security" / "production_gate" / "production_ready_marker.json", marker)
        bundle["ready_marker"] = marker
    elif mark_ready:
        bundle["ready_marker"] = {
            "ready": False,
            "reason": "production gate requirements are not all green",
        }
    return bundle
