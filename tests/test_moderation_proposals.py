import sqlite3

from flask import Flask, jsonify

from routes.moderation import register_moderation_routes
from services.governance_records import add_reputation_event, ensure_governance_records_schema


def _role_rank(role):
    return {"user": 0, "manager": 3, "super_admin": 4}.get(role or "user", 0)


def _build_app(db_path, actor_box, revoked):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def passthrough(fn):
        return fn

    register_moderation_routes(app, {
        "AUDIT_LOG_PATH": "missing.log",
        "activate_emergency_lockdown": lambda reason: None,
        "add_violation": lambda *args, **kwargs: None,
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "is_audit_chain_enabled": lambda: False,
        "is_feature_enabled": lambda key: key == "feature_member_governance_enabled",
        "json_resp": lambda payload: jsonify(payload),
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_positive_int": lambda value, default=None, min_value=None, max_value=None: int(value or default or 0),
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "revoke_user_sessions": lambda user_id: revoked.append(user_id),
        "role_rank": _role_rank,
        "secure_add_violation": lambda *args, **kwargs: None,
        "verify_audit_integrity": lambda: (True, None, "ok"),
        "verify_violation_integrity": lambda user_id: (True, None, "ok"),
    })
    return app


def _seed_users(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal',
            reputation INTEGER NOT NULL DEFAULT 0,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            updated_at TEXT,
            violation_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO users (id, username, role, status, member_level) VALUES
            (1, 'root', 'super_admin', 'active', 'normal'),
            (2, 'admin1', 'manager', 'active', 'normal'),
            (3, 'admin2', 'manager', 'active', 'normal'),
            (4, 'alice', 'user', 'active', 'normal'),
            (5, 'admin3', 'manager', 'active', 'normal');
        """
    )
    conn.commit()
    conn.close()


def test_moderation_proposal_vote_and_execute(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "warn", "reason": "輕微違規", "required_votes": 10},
    )
    assert create.status_code == 200
    proposal = create.get_json()["proposal"]
    assert proposal["risk_level"] == "normal"
    assert proposal["required_votes"] == 1
    proposal_id = proposal["id"]

    proposer_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert proposer_vote.status_code == 403
    assert proposer_vote.get_json()["msg"] == "提案者不可投票"

    actor_box["actor"] = {"id": 3, "username": "admin2", "role": "manager"}
    first_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert first_vote.status_code == 200
    assert first_vote.get_json()["proposal"]["status"] == "approved"

    duplicate_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert duplicate_vote.status_code == 409

    execute = client.post(f"/api/admin/moderation/proposals/{proposal_id}/execute")
    assert execute.status_code == 200

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, member_level FROM users WHERE id=4").fetchone()
    proposal_status = conn.execute("SELECT status FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()[0]
    action = conn.execute("SELECT action_type, target_type, target_id FROM moderation_actions LIMIT 1").fetchone()
    conn.close()

    assert row == ("active", "normal")
    assert proposal_status == "executed"
    assert action == ("warn", "user", 4)
    assert revoked == []


def test_governance_cannot_target_self_or_be_voted_by_target(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    self_create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 2, "action_type": "warn", "reason": "self governance"},
    )
    assert self_create.status_code == 403
    assert self_create.get_json()["msg"] == "不可對自己建立治理提案"

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "warn", "reason": "target should not vote"},
    )
    assert create.status_code == 200
    proposal_id = create.get_json()["proposal"]["id"]

    actor_box["actor"] = {"id": 4, "username": "alice", "role": "manager"}
    target_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert target_vote.status_code == 403
    assert target_vote.get_json()["msg"] == "治理對象不可投票"


def test_high_risk_governance_requires_root_and_two_managers(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "suspend", "reason": "嚴重違規", "required_votes": 1},
    )
    proposal = create.get_json()["proposal"]
    assert proposal["risk_level"] == "high"
    assert proposal["required_root_approval"] is True
    assert proposal["required_manager_approvals"] == 2
    assert proposal["required_votes"] == 3
    proposal_id = proposal["id"]

    proposer_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert proposer_vote.status_code == 403
    assert proposer_vote.get_json()["msg"] == "提案者不可投票"

    actor_box["actor"] = {"id": 3, "username": "admin2", "role": "manager"}
    first_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert first_vote.status_code == 200
    assert first_vote.get_json()["proposal"]["status"] == "pending"

    actor_box["actor"] = {"id": 5, "username": "admin3", "role": "manager"}
    second_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert second_vote.status_code == 200
    assert second_vote.get_json()["proposal"]["status"] == "pending"

    execute_too_early = client.post(f"/api/admin/moderation/proposals/{proposal_id}/execute")
    assert execute_too_early.status_code == 409

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    root_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert root_vote.status_code == 200
    root_payload = root_vote.get_json()["proposal"]
    assert root_payload["status"] == "approved"
    assert root_payload["root_requirement_met"] is True
    assert root_payload["manager_requirement_met"] is True

    actor_box["actor"] = {"id": 3, "username": "admin2", "role": "manager"}
    manager_execute = client.post(f"/api/admin/moderation/proposals/{proposal_id}/execute")
    assert manager_execute.status_code == 403

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    execute = client.post(f"/api/admin/moderation/proposals/{proposal_id}/execute")
    assert execute.status_code == 200

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, member_level FROM users WHERE id=4").fetchone()
    conn.close()
    assert row == ("active", "suspended")
    assert revoked == [4]


def test_root_proposer_does_not_auto_vote_on_high_risk_proposal(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "suspend", "reason": "嚴重違規"},
    )
    assert create.status_code == 200
    proposal = create.get_json()["proposal"]
    assert proposal["required_root_approval"] is True
    assert proposal["approve_count"] == 0
    assert proposal["status"] == "pending"

    root_vote = client.post(f"/api/admin/moderation/proposals/{proposal['id']}/vote", json={"vote": "approve"})
    assert root_vote.status_code == 403
    assert root_vote.get_json()["msg"] == "提案者不可投票"


def test_root_override_is_blocked(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "restrict", "reason": "洗版"},
    )
    proposal_id = create.get_json()["proposal"]["id"]

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    override = client.post(f"/api/root/moderation/proposals/{proposal_id}/override")
    assert override.status_code == 403


def test_mod_notes_and_reputation_account_api(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    note = client.post("/api/admin/mod-notes/4", json={"note": "需要觀察留言品質"})
    assert note.status_code == 200

    notes = client.get("/api/admin/mod-notes/4")
    assert notes.status_code == 200
    assert notes.get_json()["notes"][0]["note"] == "需要觀察留言品質"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_governance_records_schema(conn)
    add_reputation_event(conn, user_id=4, delta=10, reason="post_upvoted", source_user_id=2)
    conn.commit()
    conn.close()

    actor_box["actor"] = {"id": 4, "username": "alice", "role": "user"}
    summary = client.get("/api/account/reputation/summary")
    history = client.get("/api/account/reputation/history")

    assert summary.status_code == 200
    assert summary.get_json()["summary"]["current_reputation"] == 10
    assert summary.get_json()["summary"]["total_delta"] == 10
    assert history.status_code == 200
    assert history.get_json()["events"][0]["delta"] == 10
