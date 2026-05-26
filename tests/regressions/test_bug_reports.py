import json
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.bug_reports import register_bug_report_routes


def _build_app(reports_dir, actor_box, db_path=None, points_service=None, rate_limit=None):
    app = Flask(__name__)
    app.testing = True

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    deps = {
        "REPORTS_DIR": str(reports_dir),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_ua": lambda: "pytest",
        "json_resp": json_resp,
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
        "check_user_rate_limit": rate_limit or (lambda *args, **kwargs: (False, {})),
    }
    if points_service:
        deps["points_service"] = points_service
    if db_path:
        def get_db():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
        deps["get_db"] = get_db
    register_bug_report_routes(app, deps)
    return app


def test_logged_in_user_can_create_bug_report_file(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    client = _build_app(reports_dir, actor_box).test_client()

    res = client.post("/api/bug-reports", json={
        "severity": "high",
        "device": "mobile",
        "feature": "games",
        "title": "root cannot delete post",
        "description": "Delete failed from UI",
        "steps": "login root, delete post",
        "expected": "post deleted",
        "actual": "error",
        "page": "/#community",
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    report_path = reports_dir / "bugs" / f"{body['report_id']}.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["severity"] == "high"
    assert payload["device"] == "mobile"
    assert payload["feature"] == "games"
    assert payload["reward_points"] == 5
    assert payload["reward_status"] == "pending_review"
    assert payload["title"] == "root cannot delete post"
    assert payload["reporter"]["username"] == "alice"
    assert body["reward_points"] == 0
    assert body["potential_reward_points"] == 5


def test_root_can_list_bug_reports_but_manager_cannot(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(reports_dir, actor_box).test_client()
    created = client.post("/api/bug-reports", json={"title": "bug", "description": "details"})
    assert created.status_code == 200

    listed = client.get("/api/admin/bug-reports")
    assert listed.status_code == 200
    assert listed.get_json()["reports"][0]["title"] == "bug"
    assert listed.get_json()["reports"][0]["device"] == "unknown"
    assert listed.get_json()["reports"][0]["feature"] == "other"

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    denied = client.get("/api/admin/bug-reports")
    assert denied.status_code == 403


def test_bug_report_requires_title_and_description(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(reports_dir, actor_box).test_client()

    res = client.post("/api/bug-reports", json={"title": ""})

    assert res.status_code == 400
    assert not list((reports_dir / "bugs").glob("*.json")) if (reports_dir / "bugs").exists() else True


def test_bug_report_does_not_award_points_until_root_review(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    calls = []

    class FakePointsService:
        def rc1_facade(self):
            return self

        def grant_reward(self, **kwargs):
            return self.record_transaction(**kwargs)

        def record_transaction(self, **kwargs):
            calls.append(kwargs)
            return {
                "ok": True,
                "ledger": {
                    "ledger_uuid": "ledger-bug-1",
                    "amount": kwargs["amount"],
                    "action_type": kwargs["action_type"],
                },
            }

    client = _build_app(reports_dir, actor_box, points_service=FakePointsService()).test_client()

    res = client.post("/api/bug-reports", json={"severity": "critical", "title": "critical bug", "description": "details"})

    assert res.status_code == 200
    assert res.get_json()["reward_points"] == 0
    assert res.get_json()["potential_reward_points"] == 10
    assert calls == []

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    review = client.post(
        f"/api/admin/bug-reports/{res.get_json()['report_id']}/review",
        json={"decision": "approve", "review_note": "valid", "reward_points": 4},
    )

    assert review.status_code == 200
    body = review.get_json()
    assert body["report"]["reward_status"] == "awarded"
    assert body["report"]["reward_points"] == 4
    assert body["report"]["suggested_reward_points"] == 10
    assert body["report"]["ledger_uuid"] == "ledger-bug-1"
    assert calls[0]["user_id"] == 3
    assert calls[0]["amount"] == 4
    assert calls[0]["action_type"] == "valid_bug_report_critical"
    assert calls[0]["reference_type"] == "bug_report"


def test_root_can_approve_bug_report_with_zero_reward(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    calls = []

    class FakePointsService:
        def rc1_facade(self):
            return self

        def grant_reward(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "ledger": {"ledger_uuid": "ledger-bug-zero"}}

    client = _build_app(reports_dir, actor_box, points_service=FakePointsService()).test_client()
    res = client.post("/api/bug-reports", json={"severity": "high", "title": "ui bug", "description": "details"})
    assert res.status_code == 200

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    review = client.post(
        f"/api/admin/bug-reports/{res.get_json()['report_id']}/review",
        json={"decision": "approve", "review_note": "valid but no reward", "reward_points": 0},
    )

    assert review.status_code == 200
    body = review.get_json()
    assert body["report"]["status"] == "approved"
    assert body["report"]["reward_status"] == "waived"
    assert body["report"]["reward_points"] == 0
    assert body["report"]["suggested_reward_points"] == 5
    assert body["ledger"] is None
    assert calls == []


def test_root_approve_bug_report_requires_explicit_reward_points(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    calls = []

    class FakePointsService:
        def rc1_facade(self):
            return self

        def grant_reward(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "ledger": {"ledger_uuid": "ledger-should-not-run"}}

    client = _build_app(reports_dir, actor_box, points_service=FakePointsService()).test_client()
    res = client.post("/api/bug-reports", json={"severity": "critical", "title": "critical bug", "description": "details"})
    assert res.status_code == 200

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    review = client.post(
        f"/api/admin/bug-reports/{res.get_json()['report_id']}/review",
        json={"decision": "approve", "review_note": "valid"},
    )

    assert review.status_code == 400
    assert "必須由 root 手動設定獎勵點數" in review.get_json()["msg"]
    assert calls == []


def test_bug_report_rate_limit_and_duplicate_detection(tmp_path):
    reports_dir = tmp_path / "reports"
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "effective_level": "normal"}}
    client = _build_app(reports_dir, actor_box).test_client()

    first = client.post("/api/bug-reports", json={"severity": "low", "title": "same bug", "description": "details"})
    duplicate = client.post("/api/bug-reports", json={"severity": "low", "title": "same bug", "description": "details"})

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.get_json()["duplicate_report_id"] == first.get_json()["report_id"]

    limited_client = _build_app(
        tmp_path / "limited_reports",
        actor_box,
        rate_limit=lambda *args, **kwargs: (True, {"retry_after": 123}),
    ).test_client()
    limited = limited_client.post("/api/bug-reports", json={"title": "x", "description": "y"})
    assert limited.status_code == 429
    assert limited.get_json()["retry_after"] == 123
