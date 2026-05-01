from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_server_update_routes_are_root_only_and_use_safe_git_flow():
    system_admin = (ROOT / "routes" / "system_admin.py").read_text(encoding="utf-8")

    assert '@app.route("/api/root/server-update/status", methods=["GET"])' in system_admin
    assert '@app.route("/api/root/server-update/preview", methods=["POST"])' in system_admin
    assert '@app.route("/api/root/server-update/apply", methods=["POST"])' in system_admin
    assert "require_root_actor()" in system_admin
    assert "validate_git_branch_name" in system_admin
    assert '["fetch", "--prune", "origin"]' in system_admin
    assert '["diff", "--name-status", "HEAD", remote_ref, "--"]' in system_admin
    assert '["merge", "--ff-only", f"origin/{branch}"]' in system_admin
    assert "APPLY_UNVERIFIED_UPDATE" in system_admin
    assert "run_integrity_scan_after_update(actor)" in system_admin
    assert "SERVER_UPDATE_WARNING" in system_admin
    assert "git reset --hard" not in system_admin
    assert "checkout -B" not in system_admin

