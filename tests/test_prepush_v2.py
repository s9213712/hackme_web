import os
import time
from pathlib import Path

from scripts.prepush import utils
from scripts.prepush.checks import (
    cleanup_check,
    forbidden_paths_check,
    frontend_check,
    local_path_check,
    pytest_quick_check,
    release_check,
    secrets_check,
)
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import FAIL, SKIP


ROOT = Path(__file__).resolve().parents[1]


def make_ctx(tmp_path, **kwargs):
    return PrepushContext.build(repo_root=tmp_path, mode=kwargs.pop("mode", "quick"), is_ci=kwargs.pop("is_ci", False), **kwargs)


def test_path_sanitizer_does_not_output_local_home():
    sanitized = utils.sanitize_path("/home/s92137/hackme_web/runtime/database.db")
    assert "/home/s92137" not in sanitized
    assert "<LOCAL_HOME_PATH>" in sanitized


def test_local_path_leak_reports_pattern_not_raw_line(tmp_path):
    path = tmp_path / "docs.md"
    path.write_text("dev path: /mnt/d/share/ComfyUI\n", encoding="utf-8")
    findings = local_path_check.scan_line("docs.md", path.read_text(encoding="utf-8"), 1)
    assert findings == [{"file": "docs.md", "line": 1, "pattern": "WSL_DRIVE_PATH"}]


def test_gitkeep_is_not_forbidden_runtime_artifact():
    assert forbidden_paths_check.is_forbidden("storage/.gitkeep") is False
    assert forbidden_paths_check.is_forbidden("reports/bugs/.gitkeep") is False


def test_db_log_storage_report_artifacts_are_forbidden():
    assert forbidden_paths_check.is_forbidden("database/database.db")
    assert forbidden_paths_check.is_forbidden("logs/server.log")
    assert forbidden_paths_check.is_forbidden("storage/u1/file.bin")
    assert forbidden_paths_check.is_forbidden("reports/bugs/bug.md")


def test_secret_scanner_allows_fake_examples_and_redacts_real_secret():
    fake = 'password="fake example changeme"'
    real = "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"
    assert not secrets_check.scan_text("docs/example.md", fake)
    findings = secrets_check.scan_text("config.py", real)
    assert findings
    evidence = findings[0]["evidence"]
    assert "REDACTED" in evidence
    assert "abcdefghijklmnopqrstuvwxyz" not in evidence


def test_release_id_missing_from_docs_fails(tmp_path):
    service = tmp_path / "services"
    docs = tmp_path / "docs"
    service.mkdir()
    docs.mkdir()
    (service / "release_info.py").write_text('APP_RELEASE_ID = "2026.01.01-test"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("old", encoding="utf-8")
    (docs / "README.zh-TW.md").write_text("old", encoding="utf-8")
    (docs / "For_developer.md").write_text("old", encoding="utf-8")
    (docs / "UPDATE_SUMMARY.md").write_text("old", encoding="utf-8")
    ctx = make_ctx(tmp_path)
    result = release_check.run(ctx)
    assert result.status == FAIL


def test_update_summary_has_explicit_release_id_line_for_hook_bump():
    summary = (ROOT / "docs" / "UPDATE_SUMMARY.md").read_text(encoding="utf-8")
    assert "Release ID: `" in summary


def test_quick_pytest_targets_cover_new_feature_regressions():
    expected = {
        "tests/test_prepush_v2.py",
        "tests/test_frontend_account_admin.py",
        "tests/test_account_sessions.py",
        "tests/test_sanction_notices.py",
        "tests/test_trading_engine.py",
        "tests/test_security_issue_regressions.py",
    }
    assert expected.issubset(set(pytest_quick_check.QUICK_TESTS))


def test_ci_context_is_noninteractive_for_clean(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"cache")
    removed, candidates = cleanup_check.clean_repo_caches(yes=False, root=tmp_path, tracked=set(), is_ci=True)
    assert removed == 0
    assert candidates
    assert cache.exists()


def test_clean_keeps_gitkeep_while_removing_cache_file(tmp_path):
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    gitkeep = cache_dir / ".gitkeep"
    gitkeep.write_text("", encoding="utf-8")
    pyc = cache_dir / "module.pyc"
    pyc.write_bytes(b"cache")

    removed, _ = cleanup_check.clean_repo_caches(yes=True, root=tmp_path, tracked=set())

    assert removed == 1
    assert gitkeep.exists()
    assert cache_dir.exists()
    assert not pyc.exists()


def test_clean_does_not_delete_runtime_or_user_data_dirs(tmp_path):
    protected_paths = [
        tmp_path / "database" / "database.db",
        tmp_path / "logs" / "server.log",
        tmp_path / "storage" / "user.bin",
        tmp_path / "reports" / "summary.md",
        tmp_path / "security" / "reports" / "scan.json",
        tmp_path / "reports" / "bugs" / "bug.md",
        tmp_path / "cert.pem",
        tmp_path / "key.pem",
        tmp_path / ".csrfkey",
        tmp_path / ".integrity_key",
        tmp_path / ".chain_seed",
        tmp_path / "integrity_manifest.json",
    ]
    for path in protected_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("do not delete", encoding="utf-8")
    protected_cache = tmp_path / "storage" / "__pycache__" / "x.pyc"
    protected_cache.parent.mkdir(parents=True, exist_ok=True)
    protected_cache.write_bytes(b"cache")

    cleanup_check.clean_repo_caches(yes=True, root=tmp_path, tracked=set())

    for path in protected_paths:
        assert path.exists(), path
    assert protected_cache.exists()


def test_clean_does_not_delete_tracked_files_except_untracked_cache(tmp_path):
    tracked_file = tmp_path / "build" / "artifact.txt"
    tracked_file.parent.mkdir()
    tracked_file.write_text("tracked", encoding="utf-8")
    cache_file = tmp_path / "build" / "artifact.pyc"
    cache_file.write_bytes(b"cache")

    candidates = cleanup_check.collect_repo_cache_candidates(root=tmp_path, tracked={"build/artifact.txt"})
    assert tracked_file not in candidates
    assert cache_file in candidates


def test_clean_temp_keeps_latest_two_temp_roots(tmp_path):
    roots = []
    for index in range(5):
        path = tmp_path / f"html_learning_prepush_{index}"
        path.mkdir()
        stamp = time.time() + index
        os.utime(path, (stamp, stamp))
        roots.append(path)

    removed, _ = cleanup_check.clean_temp_roots(tmp_root=tmp_path, keep_latest=2, yes=True)

    assert removed == 3
    assert roots[3].exists()
    assert roots[4].exists()
    assert not roots[0].exists()
    assert not roots[1].exists()
    assert not roots[2].exists()


def test_ci_runtime_cleanup_success_removes_failure_keeps(tmp_path):
    success_root = tmp_path / "html_learning_prepush_success"
    failure_root = tmp_path / "html_learning_prepush_failure"
    success_root.mkdir()
    failure_root.mkdir()

    assert cleanup_check.cleanup_current_runtime(success_root, success=True, ci=True, keep_temp=False) == "removed"
    assert not success_root.exists()

    assert cleanup_check.cleanup_current_runtime(failure_root, success=False, ci=True, keep_temp=False) == "kept"
    assert failure_root.exists()


def test_frontend_node_missing_local_skip(monkeypatch):
    monkeypatch.setattr(utils, "tool_exists", lambda name: False)
    ctx = PrepushContext.build(repo_root=ROOT, mode="quick", is_ci=False)
    result = frontend_check.run(ctx)
    assert result.status == SKIP


def test_gitleaks_missing_ci_fails(monkeypatch):
    monkeypatch.delenv("ALLOW_MISSING_GITLEAKS", raising=False)
    monkeypatch.setattr(utils, "tool_exists", lambda name: False)
    ctx = PrepushContext.build(repo_root=ROOT, mode="quick", is_ci=True)
    result = secrets_check.run(ctx)
    assert result.status == FAIL


def test_subprocess_timeout_is_reported():
    try:
        utils.run_command(["python3", "-c", "import time; time.sleep(2)"], cwd=ROOT, timeout=1)
    except Exception as exc:
        assert "timed out" in str(exc).lower()
    else:
        raise AssertionError("timeout was not enforced")
