"""GitHub Actions CI status helpers for the admin health center."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


FetchJson = Callable[[str, dict[str, str], float], dict[str, Any]]


def _git_output(repo_dir: str | os.PathLike[str], *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_dir), *args],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return ""


def parse_github_repo(remote_url: str) -> tuple[str, str] | None:
    text = str(remote_url or "").strip()
    if not text:
        return None
    patterns = [
        r"github\.com[:/](?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group("owner"), match.group("repo")
    return None


def github_repo_from_git(repo_dir: str | os.PathLike[str]) -> tuple[str, str] | None:
    remote = _git_output(repo_dir, "remote", "get-url", "origin")
    return parse_github_repo(remote)


def _default_fetch_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(1024 * 1024)
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _run_payload(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run.get("id"),
        "name": run.get("name") or "",
        "display_title": run.get("display_title") or "",
        "event": run.get("event") or "",
        "status": run.get("status") or "",
        "conclusion": run.get("conclusion") or "",
        "head_branch": run.get("head_branch") or "",
        "head_sha": run.get("head_sha") or "",
        "html_url": run.get("html_url") or "",
        "created_at": run.get("created_at") or "",
        "updated_at": run.get("updated_at") or "",
        "run_attempt": run.get("run_attempt") or 0,
    }


def playwright_ci_status(
    *,
    repo_dir: str | os.PathLike[str],
    workflow_file: str = "playwright-qa.yml",
    branch: str | None = None,
    token: str | None = None,
    timeout: float = 4.0,
    fetch_json: FetchJson | None = None,
) -> dict[str, Any]:
    repo = github_repo_from_git(repo_dir)
    current_branch = branch or _git_output(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    workflow_path = Path(repo_dir) / ".github" / "workflows" / workflow_file
    if not repo:
        return {
            "ok": False,
            "configured": False,
            "status": "unknown",
            "msg": "GitHub origin remote is not configured",
            "workflow_file": workflow_file,
            "workflow_present": workflow_path.exists(),
        }
    owner, name = repo
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hackme-web-health-center",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    auth_token = (token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    params = {"per_page": "8"}
    if current_branch:
        params["branch"] = current_branch
    query = urllib.parse.urlencode(params)
    url = f"https://api.github.com/repos/{owner}/{name}/actions/workflows/{urllib.parse.quote(workflow_file)}/runs?{query}"
    fetcher = fetch_json or _default_fetch_json
    try:
        payload = fetcher(url, headers, float(timeout))
    except Exception as exc:
        return {
            "ok": False,
            "configured": True,
            "status": "unreachable",
            "msg": f"GitHub Actions status unavailable: {exc}",
            "repo": f"{owner}/{name}",
            "branch": current_branch,
            "workflow_file": workflow_file,
            "workflow_present": workflow_path.exists(),
            "api_url": url,
            "auth_configured": bool(auth_token),
        }
    runs = [_run_payload(run) for run in payload.get("workflow_runs") or [] if isinstance(run, dict)]
    latest = runs[0] if runs else None
    if not latest:
        status = "empty"
    elif latest.get("status") != "completed":
        status = str(latest.get("status") or "in_progress")
    elif latest.get("conclusion") == "success":
        status = "success"
    else:
        status = str(latest.get("conclusion") or "failed")
    return {
        "ok": status == "success",
        "configured": True,
        "status": status,
        "repo": f"{owner}/{name}",
        "branch": current_branch,
        "workflow_file": workflow_file,
        "workflow_present": workflow_path.exists(),
        "api_url": url,
        "auth_configured": bool(auth_token),
        "latest": latest,
        "runs": runs,
        "msg": "latest Playwright CI succeeded" if status == "success" else "latest Playwright CI is not green",
    }
