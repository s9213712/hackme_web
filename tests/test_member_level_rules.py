import sqlite3

from services.member_levels import (
    DEFAULT_MEMBER_LEVEL_RULES,
    ensure_member_level_rules_schema,
    get_member_level_rule,
    update_member_level_rule,
)
from services.permissions import require_member_action


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_member_level_rules_schema_seeds_defaults(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        ensure_member_level_rules_schema(conn)
        rows = conn.execute("SELECT level FROM member_level_rules ORDER BY level").fetchall()
        levels = {row["level"] for row in rows}
        assert levels == set(DEFAULT_MEMBER_LEVEL_RULES)
        normal = get_member_level_rule(conn, "normal")
        assert normal["can_post"] is True
        assert normal["daily_post_limit"] == DEFAULT_MEMBER_LEVEL_RULES["normal"]["daily_post_limit"]
    finally:
        conn.close()


def test_update_member_level_rule_validates_and_serializes(tmp_path):
    conn = _conn(tmp_path / "levels.db")
    try:
        rule, err = update_member_level_rule(
            conn,
            "normal",
            {"can_post": False, "daily_post_limit": 3, "max_attachment_size_mb": 8},
        )
        assert err is None
        assert rule["can_post"] is False
        assert rule["daily_post_limit"] == 3
        assert rule["max_attachment_size_mb"] == 8

        rule, err = update_member_level_rule(conn, "normal", {"daily_dm_limit": -1})
        assert rule is None
        assert err == "daily_dm_limit 不可小於 0"
    finally:
        conn.close()


def test_member_action_uses_governance_rule_when_provided():
    actor = {
        "id": 3,
        "username": "alice",
        "role": "user",
        "status": "active",
        "member_level": "normal",
    }

    assert require_member_action(actor, "community_thread_create")[0] is True
    assert require_member_action(actor, "community_thread_create", {"can_post": False}) == (
        False,
        "會員等級規則不允許此操作",
        403,
    )
    assert require_member_action(actor, "chat_dm_create", {"can_send_dm": False}) == (
        False,
        "會員等級規則不允許此操作",
        403,
    )
