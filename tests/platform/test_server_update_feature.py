from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_server_update_routes_are_root_only_and_use_safe_git_flow():
    system_admin = (
        (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "routes" / "system_admin_sections" / "security_routes.py").read_text(encoding="utf-8")
    )
    server_py = (ROOT / "server.py").read_text(encoding="utf-8")
    container_py = (ROOT / "services" / "server" / "container.py").read_text(encoding="utf-8")
    runtime_routes = (ROOT / "routes" / "system_admin_sections" / "runtime_routes.py").read_text(encoding="utf-8")

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
    assert '["merge", "--ff-only", f"origin/{branch}"]' not in system_admin
    assert "APPLY_UNVERIFIED_UPDATE" not in system_admin
    assert "release_summary" in system_admin
    assert "read_update_summary_from_ref(remote_ref)" in system_admin
    assert "verification = points_service.verify_chain_bounded_snapshot()" in system_admin
    assert "verification = points_service.verify_chain()" not in system_admin
    assert '("points_chain", lambda: points_service.verify_chain_bounded_snapshot())' in container_py
    assert '("points_chain", lambda: points_service.verify_chain())' not in container_py
    assert "points_service.operations_control_snapshot(recent_limit=20)" in runtime_routes
    assert "points_service.economy_stats() or {}" not in runtime_routes
    assert "線上套用 GitHub 更新已停用" in system_admin
    assert "SERVER_UPDATE_APPLY_DISABLED" in system_admin
    assert "schedule_server_restart(reason=f\"server update from origin/{branch}\"" not in system_admin
    assert 'Integrity Guard baseline 已依本次更新檔案重建' not in system_admin
    assert "SERVER_UPDATE_WARNING" in system_admin
    assert "git reset --hard" not in system_admin
    assert "checkout -B" not in system_admin
    # Status endpoint returns 200 on success, 500 on git/state failure so
    # the frontend can distinguish "git is healthy" from "we couldn't even
    # read the state". Earlier shape was always-200.
    assert 'return json_resp({"ok": bool(state.get("ok")), "update": state, "warning": SERVER_UPDATE_WARNING}), (200 if state.get("ok") else 500)' in system_admin
    assert 'app.logger.exception("Unhandled exception while serving %s %s", request.method, request.path)' in server_py


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
    assert "版本檢查" in index
    assert "server-update-apply-btn" not in index
    assert "applyServerUpdate" not in admin_js
    assert "此頁不提供線上套用" in admin_js
