import html
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import request


BUG_REPORT_REWARD_POINTS = {
    "low": 1,
    "medium": 3,
    "high": 5,
    "critical": 10,
}
BUG_REPORT_SEVERITIES = set(BUG_REPORT_REWARD_POINTS)


def _clean_text(value, limit):
    if not isinstance(value, str):
        return ""
    # Strip null bytes, trim, then HTML-escape to prevent XSS (Bug: XSS test)
    cleaned = html.escape(value.replace("\x00", "").strip(), quote=True)
    return cleaned[:limit]


def _bug_report_payload(data, actor, ip, ua):
    now = datetime.now().isoformat()
    report_id = f"bug_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"
    severity = _clean_text(data.get("severity"), 20).lower() or "medium"
    if severity not in BUG_REPORT_SEVERITIES:
        severity = "medium"
    return {
        "id": report_id,
        "status": "new",
        "severity": severity,
        "title": _clean_text(data.get("title"), 120),
        "description": _clean_text(data.get("description"), 4000),
        "steps": _clean_text(data.get("steps"), 4000),
        "expected": _clean_text(data.get("expected"), 2000),
        "actual": _clean_text(data.get("actual"), 2000),
        "page": _clean_text(data.get("page"), 500),
        "created_at": now,
        "reward_points": BUG_REPORT_REWARD_POINTS.get(severity, BUG_REPORT_REWARD_POINTS["medium"]),
        "reporter": {
            "id": actor.get("id"),
            "username": actor.get("username"),
            "role": "super_admin" if actor.get("username") == "root" else actor.get("role", "user"),
            "effective_level": actor.get("effective_level") or actor.get("member_level"),
        },
        "request": {
            "ip": ip,
            "user_agent": (ua or "")[:300],
        },
    }


def register_bug_report_routes(app, deps):
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps.get("get_db")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    reports_dir = Path(deps.get("REPORTS_DIR", "reports")).resolve()
    bug_dir = reports_dir / "bugs"

    def _is_root(actor):
        return actor and actor.get("username") == "root"

    def _award_bug_report_points(actor, payload):
        if not get_db or not actor.get("id"):
            return 0
        reward = int(payload.get("reward_points") or 0)
        if reward <= 0:
            return 0
        conn = get_db()
        try:
            conn.execute(
                "UPDATE users SET points=COALESCE(points, 0)+?, updated_at=? WHERE id=?",
                (reward, datetime.now().isoformat(), int(actor["id"])),
            )
            try:
                conn.execute(
                    "INSERT INTO reputation_events (user_id, delta, reason, source_user_id, source_post_id, created_at) "
                    "VALUES (?, ?, ?, ?, NULL, ?)",
                    (
                        int(actor["id"]),
                        reward,
                        f"bug_report:{payload['severity']}",
                        int(actor["id"]),
                        datetime.now().isoformat(),
                    ),
                )
            except Exception:
                pass
            conn.commit()
            return reward
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()

    @app.route("/api/bug-reports", methods=["POST"])
    @require_csrf
    def create_bug_report():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "請先登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400

        payload = _bug_report_payload(data, dict(actor), get_client_ip(), get_ua())
        if not payload["title"] or not payload["description"]:
            return json_resp({"ok": False, "msg": "請填寫 bug 標題與問題描述"}), 400

        bug_dir.mkdir(parents=True, exist_ok=True)
        target = bug_dir / f"{payload['id']}.json"
        tmp = bug_dir / f".{payload['id']}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        reward = _award_bug_report_points(dict(actor), payload)
        audit("BUG_REPORT_CREATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"{payload['id']}, reward_points={reward}")
        msg = f"Bug 回報已建立，獲得 {reward} 點獎勵" if reward else "Bug 回報已建立"
        return json_resp({"ok": True, "msg": msg, "report_id": payload["id"], "reward_points": reward})

    @app.route("/api/admin/bug-reports", methods=["GET"])
    @require_csrf_safe
    def list_bug_reports():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not _is_root(actor):
            return json_resp({"ok": False, "msg": "只有 root 可查看 bug 回報檔"}), 403
        try:
            bug_dir.mkdir(parents=True, exist_ok=True)
            reports = []
            for path in sorted(bug_dir.glob("bug_*.json"), reverse=True)[:100]:
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                reports.append({
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "severity": item.get("severity"),
                    "title": item.get("title"),
                    "created_at": item.get("created_at"),
                    "reward_points": item.get("reward_points"),
                    "reporter": item.get("reporter", {}).get("username"),
                    "file": str(path.relative_to(reports_dir.parent)),
                })
            return json_resp({"ok": True, "reports": reports})
        except Exception as exc:
            import sys
            sys.stderr.write(f"[BUG_REPORTS LIST ERROR] {exc}\n")
            return json_resp({"ok": False, "msg": "讀取失敗，請稍後再試"}), 500
