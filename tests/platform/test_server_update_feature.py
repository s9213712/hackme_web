from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_update_routes_are_root_only_and_use_safe_git_flow():
    system_admin = (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")
    server_py = (ROOT / "server.py").read_text(encoding="utf-8")

    assert '@app.route("/api/root/server-update/status", methods=["GET"])' in system_admin
    assert '@app.route("/api/root/server-update/preview", methods=["POST"])' in system_admin
    assert '@app.route("/api/root/server-update/apply", methods=["POST"])' in system_admin
    assert 'HTML_LEARNING_GIT_REPO_DIR' in server_py
    assert '"GIT_REPO_DIR": GIT_REPO_DIR' in server_py
    assert 'GIT_REPO_DIR = deps.get("GIT_REPO_DIR") or BASE_DIR' in system_admin
    assert "require_root_actor()" in system_admin
    assert "validate_git_branch_name" in system_admin
    assert '["rev-parse", "--show-toplevel"]' in system_admin
    assert '["fetch", "--prune", "origin"]' in system_admin
    assert '["diff", "--name-status", "HEAD", remote_ref, "--"]' in system_admin
    assert '["show", f"{ref}:docs/UPDATE_SUMMARY.md"]' in system_admin
    assert '["merge", "--ff-only", f"origin/{branch}"]' in system_admin
    assert "APPLY_UNVERIFIED_UPDATE" in system_admin
    assert "release_summary" in system_admin
    assert "read_update_summary_from_ref(remote_ref)" in system_admin
    assert "prepare_server_update_recovery_points(actor, branch)" in system_admin
    assert 'snapshot_type="pre_update"' in system_admin
    assert 'kind="pre_server_update"' in system_admin
    assert "schedule_server_restart(reason=f\"server update from origin/{branch}\"" in system_admin
    assert "rebuild_integrity_baseline_after_update(actor, branch, preview)" in system_admin
    assert "integrity_guard.rebaseline_paths(" in system_admin
    assert 'Integrity Guard baseline 已依本次更新檔案重建' in system_admin
    assert "SERVER_UPDATE_WARNING" in system_admin
    assert "git reset --hard" not in system_admin
    assert "checkout -B" not in system_admin


def test_server_update_frontend_displays_update_summary():
    index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (
        (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "public" / "js" / "51-admin-server-mode-launch-check.js").read_text(encoding="utf-8")
    )

    assert 'id="server-update-summary"' in index
    assert "function renderServerUpdateSummary" in admin_js
    assert "docs/UPDATE_SUMMARY.md" in admin_js
    assert "preview.release_summary" in admin_js
    assert "PointsChain backup" in admin_js
    assert "伺服器將自動重啟" in admin_js
