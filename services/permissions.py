from services.identity import role_rank

ACTIVE_STATUS = "active"
RESTRICTED_WRITE_ACTIONS = {
    "chat_dm_create",
    "chat_send",
    "community_thread_create",
    "community_reply",
}
ACTION_RULE_FIELDS = {
    "chat_dm_create": "can_send_dm",
    "chat_send": "can_comment",
    "community_thread_create": "can_post",
    "community_reply": "can_comment",
}


def actor_role(actor):
    if actor and actor.get("username") == "root":
        return "super_admin"
    return (actor or {}).get("role") or "user"


def actor_status(actor):
    return (actor or {}).get("status") or ACTIVE_STATUS


def actor_member_level(actor):
    return (actor or {}).get("member_level") or "normal"


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


def require_member_action(actor, action, rule=None):
    ok, msg, status = require_active_actor(actor)
    if not ok:
        return ok, msg, status
    member_level = actor_member_level(actor)
    if member_level == "suspended":
        return False, "會員等級已停權，暫停互動功能", 403
    if member_level == "restricted" and action in RESTRICTED_WRITE_ACTIONS:
        return False, "會員等級受限，暫停發文、留言與聊天", 403
    if rule:
        rule_field = ACTION_RULE_FIELDS.get(action)
        if rule_field and not bool(rule.get(rule_field)):
            return False, "會員等級規則不允許此操作", 403
    return True, "", 200
