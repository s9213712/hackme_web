from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_community_combo_mutation_routes_dispatch_to_single_use_csrf():
    community = (ROOT / "routes" / "community.py").read_text(encoding="utf-8")

    assert "def require_csrf_by_method(fn):" in community
    assert "strict = require_csrf(fn)" in community
    assert 'if request.method in {"GET", "HEAD", "OPTIONS"}:' in community
    assert community.count("@require_csrf_by_method") >= 6
    assert '@app.route("/api/community/announcements", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/categories", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards/<int:board_id>/moderators", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/boards/<int:board_id>/threads", methods=["GET", "POST"])\n    @require_csrf_by_method' in community
    assert '@app.route("/api/community/threads/<int:thread_id>", methods=["GET", "PUT", "DELETE"])\n    @require_csrf_by_method' in community

