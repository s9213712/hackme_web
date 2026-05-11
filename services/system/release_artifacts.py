"""Release bundle and QA artifact indexing helpers."""

from __future__ import annotations

import json
import os
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
    payload = {
        "ok": True,
        "generated_at": utc_iso(),
        "git": git_meta(git_repo_dir or base),
        "summary": {
            "artifact_count": len(artifacts),
            "by_kind": dict(sorted(by_kind.items())),
            "by_source": dict(sorted(by_source.items())),
        },
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
