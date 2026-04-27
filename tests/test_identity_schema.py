import sqlite3

from services.identity import ensure_user_identity_columns, role_rank
from services.permissions import require_member_action, require_role


def test_ensure_user_identity_columns_repairs_legacy_users(tmp_path):
    db_path = tmp_path / "identity.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            status TEXT
        );
        INSERT INTO users (id, username, status) VALUES (1, 'alice', NULL);
        """
    )

    ensure_user_identity_columns(conn)
    conn.commit()

    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    user = conn.execute(
        "SELECT role, member_level, status, trust_score, points, reputation, failed_login_count "
        "FROM users WHERE username='alice'"
    ).fetchone()
    conn.close()

    assert {"role", "member_level", "trust_score", "points", "reputation", "deleted_at"} <= cols
    assert user["role"] == "user"
    assert user["member_level"] == "normal"
    assert user["status"] == "active"
    assert user["trust_score"] == 0
    assert user["points"] == 0
    assert user["reputation"] == 0
    assert user["failed_login_count"] == 0


def test_role_rank_supports_governance_role_aliases():
    assert role_rank("root") == role_rank("super_admin")
    assert role_rank("admin") == role_rank("manager")
    assert role_rank("security_admin") > role_rank("moderator")
    assert role_rank("moderator") > role_rank("user")


def test_permission_helpers_check_role_status_and_member_level():
    manager = {"username": "admin", "role": "manager", "status": "active", "member_level": "normal"}
    inactive = {"username": "bob", "role": "manager", "status": "inactive", "member_level": "normal"}
    restricted = {"username": "alice", "role": "user", "status": "active", "member_level": "restricted"}
    suspended = {"username": "eve", "role": "user", "status": "active", "member_level": "suspended"}

    assert require_role(manager, "manager")[0] is True
    assert require_role(manager, "super_admin") == (False, "權限不足", 403)
    assert require_role(inactive, "user") == (False, "帳號狀態不可執行此操作", 403)
    assert require_member_action(restricted, "community_thread_create") == (False, "會員等級受限，暫停發文、留言與聊天", 403)
    assert require_member_action(restricted, "community_reaction")[0] is True
    assert require_member_action(suspended, "community_reaction") == (False, "會員等級已停權，暫停互動功能", 403)
