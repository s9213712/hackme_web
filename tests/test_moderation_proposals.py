import sqlite3

from flask import Flask, jsonify

from routes.moderation import register_moderation_routes


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
            must_change_password INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            updated_at TEXT,
            violation_count INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO users (id, username, role, status, member_level) VALUES
            (1, 'root', 'super_admin', 'active', 'vip'),
            (2, 'admin1', 'manager', 'active', 'trusted'),
            (3, 'admin2', 'manager', 'active', 'trusted'),
            (4, 'alice', 'user', 'active', 'normal');
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
        json={"target_user_id": 4, "action_type": "suspend", "reason": "嚴重違規", "required_votes": 2},
    )
    assert create.status_code == 200
    proposal_id = create.get_json()["proposal"]["id"]

    first_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert first_vote.status_code == 200
    assert first_vote.get_json()["proposal"]["status"] == "pending"

    duplicate_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert duplicate_vote.status_code == 409

    actor_box["actor"] = {"id": 3, "username": "admin2", "role": "manager"}
    second_vote = client.post(f"/api/admin/moderation/proposals/{proposal_id}/vote", json={"vote": "approve"})
    assert second_vote.status_code == 200
    assert second_vote.get_json()["proposal"]["status"] == "approved"

    execute = client.post(f"/api/admin/moderation/proposals/{proposal_id}/execute")
    assert execute.status_code == 200

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, member_level FROM users WHERE id=4").fetchone()
    proposal_status = conn.execute("SELECT status FROM moderation_proposals WHERE id=?", (proposal_id,)).fetchone()[0]
    conn.close()

    assert row == ("suspended", "suspended")
    assert proposal_status == "executed"
    assert revoked == [4]


def test_root_override_executes_pending_proposal(tmp_path):
    db_path = tmp_path / "moderation.db"
    _seed_users(db_path)
    revoked = []
    actor_box = {"actor": {"id": 2, "username": "admin1", "role": "manager"}}
    client = _build_app(str(db_path), actor_box, revoked).test_client()

    create = client.post(
        "/api/admin/moderation/proposals",
        json={"target_user_id": 4, "action_type": "restrict", "reason": "洗版", "required_votes": 3},
    )
    proposal_id = create.get_json()["proposal"]["id"]

    actor_box["actor"] = {"id": 1, "username": "root", "role": "super_admin"}
    override = client.post(f"/api/root/moderation/proposals/{proposal_id}/override")
    assert override.status_code == 200

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status, member_level FROM users WHERE id=4").fetchone()
    conn.close()
    assert row == ("limited", "restricted")
