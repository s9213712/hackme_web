from services.system.ci_status import parse_github_repo, playwright_ci_status


def test_parse_github_repo_supports_https_and_ssh():
    assert parse_github_repo("https://github.com/s9213712/hackme_web.git") == ("s9213712", "hackme_web")
    assert parse_github_repo("git@github.com:s9213712/hackme_web.git") == ("s9213712", "hackme_web")


def test_playwright_ci_status_summarizes_latest_success(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "playwright-qa.yml").write_text("name: playwright-qa\n", encoding="utf-8")

    def fake_fetch(url, headers, timeout):
        assert "actions/workflows/playwright-qa.yml/runs" in url
        return {
            "workflow_runs": [
                {
                    "id": 123,
                    "name": "playwright-qa",
                    "display_title": "CI smoke",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "03b.Comfyui",
                    "head_sha": "abc",
                    "html_url": "https://github.com/s9213712/hackme_web/actions/runs/123",
                    "created_at": "2026-05-11T00:00:00Z",
                    "updated_at": "2026-05-11T00:01:00Z",
                    "run_attempt": 1,
                }
            ]
        }

    # No .git remote exists in the tmp repo, so pass a fetcher after monkeypatching
    # the parser surface through a real git origin.
    import subprocess

    subprocess.run(["git", "-C", str(repo), "init"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/s9213712/hackme_web.git"], check=True)
    result = playwright_ci_status(repo_dir=repo, branch="03b.Comfyui", fetch_json=fake_fetch)

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["latest"]["id"] == 123
    assert result["workflow_present"] is True


def test_playwright_ci_status_degrades_when_api_unreachable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "-C", str(repo), "init"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:s9213712/hackme_web.git"], check=True)

    def failing_fetch(url, headers, timeout):
        raise TimeoutError("network blocked")

    result = playwright_ci_status(repo_dir=repo, branch="03b.Comfyui", fetch_json=failing_fetch)

    assert result["ok"] is False
    assert result["status"] == "unreachable"
    assert "network blocked" in result["msg"]
