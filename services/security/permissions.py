from services.security.identity import is_admin_role, role_rank
from services.governance.violation_fines import assert_user_feature_allowed
from services.users.member_levels import get_member_level_rule, refresh_user_effective_level

ACTIVE_STATUS = "active"
ACTION_RULE_FIELDS = {
    "chat_dm_create": "can_send_dm",
    "chat_send": "can_comment",
    "community_thread_create": "can_post",
    "community_reply": "can_comment",
    "community_reaction": None,
    "report_create": "can_report",
    "upload_attachment": "can_upload_attachment",
}
ACTION_RATE_LIMIT_FIELDS = {
    "community_thread_create": "post_rate_limit_per_hour",
    "community_reply": "comment_rate_limit_per_hour",
    "chat_send": "comment_rate_limit_per_hour",
    "chat_dm_create": "dm_rate_limit_per_day",
    "upload_attachment": "upload_rate_limit_per_day",
}
ACTION_RESTRICTION_FEATURES = {
    "chat_dm_create": "chat_dm",
    "chat_send": "chat_send",
    "community_thread_create": "community_post",
    "community_reply": "community_comment",
    "upload_attachment": "cloud_upload",
}


def _actor_dict(actor):
    return dict(actor or {})


def actor_role(actor):
    data = _actor_dict(actor)
    if data.get("username") == "root":
        return "super_admin"
    return data.get("role") or "user"


def actor_is_admin(actor):
    return is_admin_role(actor_role(actor))


def actor_status(actor):
    return _actor_dict(actor).get("status") or ACTIVE_STATUS


def actor_base_level(actor):
    data = _actor_dict(actor)
    return data.get("base_level") or data.get("member_level") or "normal"


def actor_effective_level(actor):
    return _actor_dict(actor).get("effective_level") or actor_base_level(actor)


def require_active_actor(actor):
    if not actor:
        return False, "未登入", 401
    if actor_status(actor) != ACTIVE_STATUS:
        return False, "帳號狀態不可執行此操作", 403
    return True, "", 200


def require_role(actor, min_role):
    ok, msg, status = require_active_actor(actor)
    if not ok:
        return ok, msg, status
    if role_rank(actor_role(actor)) < role_rank(min_role):
        return False, "權限不足", 403
    return True, "", 200


def get_permission_rule(conn, actor):
    data = _actor_dict(actor)
    if actor_is_admin(actor):
        return None
    has_explicit_sanction_level = (
        not data.get("base_level")
        and not data.get("effective_level")
        and data.get("member_level") in {"restricted", "suspended"}
    )
    if conn is not None and data.get("id") and not has_explicit_sanction_level:
        refreshed = refresh_user_effective_level(conn, data["id"], reason="permission check")
        if refreshed:
            actor = {**data, **refreshed}
    return get_member_level_rule(conn, actor_effective_level(actor)) if conn is not None else None


def _provided_or_loaded_rule(actor, rule=None, conn=None):
    if rule:
        return rule
    if conn is None:
        return None
    return get_permission_rule(conn, actor)


def _rule_allows(actor, permission, rule=None, conn=None, target=None):
    if actor_is_admin(actor):
        return True
    if actor_effective_level(actor) == "suspended":
        return False
    if permission is None:
        return True
    loaded_rule = _provided_or_loaded_rule(actor, rule=rule, conn=conn)
    if not loaded_rule:
        return actor_effective_level(actor) not in {"restricted", "suspended"}
    return bool(loaded_rule.get(permission))


def can_post(user, conn=None):
    return _rule_allows(user, "can_post", conn=conn)


def can_comment(user, conn=None):
    return _rule_allows(user, "can_comment", conn=conn)


def can_upload(user, conn=None):
    return _rule_allows(user, "can_upload_attachment", conn=conn)


def can_dm(user, target=None, conn=None):
    user_data = _actor_dict(user)
    target_data = _actor_dict(target) if target else None
    if target_data and target_data.get("id") == user_data.get("id"):
        return False
    return _rule_allows(user, "can_send_dm", conn=conn, target=target)


def can_report(user, conn=None):
    return _rule_allows(user, "can_report", conn=conn)


def get_rate_limit(user, action, conn=None, rule=None):
    if actor_is_admin(user):
        return None
    loaded_rule = _provided_or_loaded_rule(user, rule=rule, conn=conn)
    if not loaded_rule:
        return None
    field = ACTION_RATE_LIMIT_FIELDS.get(action)
    if not field:
        return None
    return int(loaded_rule.get(field) or 0)


def require_member_action(actor, action, rule=None, conn=None, target=None):
    ok, msg, status = require_active_actor(actor)
    if not ok:
        return ok, msg, status
    feature_key = ACTION_RESTRICTION_FEATURES.get(action)
    actor_data = _actor_dict(actor)
    if conn is not None and actor_data.get("id") and actor_data.get("username") != "root" and feature_key:
        allowed, restriction_msg, _restrictions = assert_user_feature_allowed(
            conn,
            user_id=actor_data["id"],
            feature_key=feature_key,
        )
        if not allowed:
            return False, restriction_msg, 423
    if actor_is_admin(actor):
        return True, "", 200
    effective_level = actor_effective_level(actor)
    if effective_level == "suspended":
        return False, "會員等級已停權，僅可登入、查看通知與申訴", 403
    rule_field = ACTION_RULE_FIELDS.get(action)
    if not _rule_allows(actor, rule_field, rule=rule, conn=conn, target=target):
        if effective_level == "restricted":
            return False, "會員等級受限，僅可閱讀不可互動", 403
        return False, "會員等級規則不允許此操作", 403
    return True, "", 200
