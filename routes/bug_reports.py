import html
import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import request

from services.points_chain import DISPLAY_CURRENCY


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


def _actor_value(actor, key, default=None):
    if not actor:
        return default
    try:
        return actor[key]
    except Exception:
        return actor.get(key, default) if hasattr(actor, "get") else default


def _bug_report_payload(data, actor, ip, ua):
    now = datetime.now().isoformat()
    report_id = f"bug_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"
    severity = _clean_text(data.get("severity"), 20).lower() or "medium"
    if severity not in BUG_REPORT_SEVERITIES:
        severity = "medium"
    title = _clean_text(data.get("title"), 120)
    description = _clean_text(data.get("description"), 4000)
    reporter_id = _actor_value(actor, "id")
    content_hash = hashlib.sha256(
        f"{reporter_id or '-'}\n{title}\n{description}".encode("utf-8")
    ).hexdigest()
    return {
        "id": report_id,
        "status": "new",
        "severity": severity,
        "title": title,
        "description": description,
        "steps": _clean_text(data.get("steps"), 4000),
        "expected": _clean_text(data.get("expected"), 2000),
        "actual": _clean_text(data.get("actual"), 2000),
        "page": _clean_text(data.get("page"), 500),
        "created_at": now,
        "reward_points": BUG_REPORT_REWARD_POINTS.get(severity, BUG_REPORT_REWARD_POINTS["medium"]),
        "reward_status": "pending_review",
        "content_hash": content_hash,
        "reporter": {
            "id": reporter_id,
            "username": _actor_value(actor, "username"),
            "role": "super_admin" if _actor_value(actor, "username") == "root" else _actor_value(actor, "role", "user"),
            "effective_level": _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"),
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
    check_user_rate_limit = deps.get("check_user_rate_limit", lambda *args, **kwargs: (False, {}))
    points_service = deps.get("points_service")
    reports_dir = Path(deps.get("REPORTS_DIR", "reports")).resolve()
    bug_dir = reports_dir / "bugs"

    def _is_root(actor):
        return actor and _actor_value(actor, "username") == "root"

    def _bug_report_path(report_id):
        text = str(report_id or "").strip()
        if not re.fullmatch(r"bug_[0-9]{8}_[0-9]{6}_[a-f0-9]{10}", text):
            return None
        return bug_dir / f"{text}.json"

    def _find_duplicate_report(payload):
        bug_dir.mkdir(parents=True, exist_ok=True)
        content_hash = payload.get("content_hash")
        reporter_id = payload.get("reporter", {}).get("id")
        if not content_hash or not reporter_id:
            return None
        for path in bug_dir.glob("bug_*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if item.get("content_hash") != content_hash:
                continue
            if item.get("reporter", {}).get("id") != reporter_id:
                continue
            if item.get("status") != "rejected":
                return item
        return None

    def _award_reviewed_bug_report(actor, payload, review_note=""):
        if not points_service:
            raise RuntimeError("points service unavailable")
        reporter_id = payload.get("reporter", {}).get("id")
        reward = int(payload.get("reward_points") or 0)
        if not reporter_id or reward <= 0:
            raise ValueError("bug report has no reward target")
        return points_service.record_transaction(
            user_id=int(reporter_id),
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=reward,
            action_type=f"valid_bug_report_{payload.get('severity') or 'medium'}",
            reference_type="bug_report",
            reference_id=payload["id"],
            idempotency_key=f"bug_report_reward:{payload['id']}",
            reason=review_note or f"valid bug report {payload.get('severity') or 'medium'}",
            public_metadata={
                "bug_report_id": payload["id"],
                "severity": payload.get("severity"),
                "reviewed_reward": True,
            },
            actor=actor,
        )

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

        blocked, info = check_user_rate_limit(actor["id"], "bug_report_submit", max_req=5, window_sec=3600)
        if blocked:
            retry_after = int(info.get("retry_after", 3600)) if isinstance(info, dict) else 3600
            return json_resp({"ok": False, "msg": "Bug 回報過於頻繁，請稍後再提交", "retry_after": retry_after}), 429

        payload = _bug_report_payload(data, dict(actor), get_client_ip(), get_ua())
        if not payload["title"] or not payload["description"]:
            return json_resp({"ok": False, "msg": "請填寫 bug 標題與問題描述"}), 400
        duplicate = _find_duplicate_report(payload)
        if duplicate:
            return json_resp({
                "ok": False,
                "msg": "相同內容的 bug 回報已存在，請等待審核或補充不同資訊",
                "duplicate_report_id": duplicate.get("id"),
            }), 409

        bug_dir.mkdir(parents=True, exist_ok=True)
        target = bug_dir / f"{payload['id']}.json"
        tmp = bug_dir / f".{payload['id']}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        audit("BUG_REPORT_CREATED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"{payload['id']}, reward_pending={payload['reward_points']}")
        return json_resp({
            "ok": True,
            "msg": f"Bug 回報已建立，若審核有效將發放 {payload['reward_points']} 點獎勵",
            "report_id": payload["id"],
            "reward_points": 0,
            "potential_reward_points": payload["reward_points"],
            "reward_status": "pending_review",
        })

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
                    "reward_status": item.get("reward_status", "pending_review"),
                    "reporter": item.get("reporter", {}).get("username"),
                    "file": str(path.relative_to(reports_dir.parent)),
                })
            return json_resp({"ok": True, "reports": reports})
        except Exception as exc:
            import sys
            sys.stderr.write(f"[BUG_REPORTS LIST ERROR] {exc}\n")
            return json_resp({"ok": False, "msg": "讀取失敗，請稍後再試"}), 500

    @app.route("/api/admin/bug-reports/<report_id>/review", methods=["POST"])
    @require_csrf
    def review_bug_report(report_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not _is_root(actor):
            return json_resp({"ok": False, "msg": "只有 root 可審核 bug 回報"}, 403)
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            data = {}
        decision = str(data.get("decision") or "").strip().lower()
        if decision not in {"approve", "reject"}:
            return json_resp({"ok": False, "msg": "decision must be approve or reject"}), 400
        path = _bug_report_path(report_id)
        if not path or not path.exists():
            return json_resp({"ok": False, "msg": "bug report not found"}), 404
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("reward_status") in {"awarded", "rejected"} or payload.get("status") in {"approved", "rejected"}:
            return json_resp({"ok": False, "msg": "bug report already reviewed"}), 409
        review_note = _clean_text(data.get("review_note"), 500)
        payload["reviewed_at"] = datetime.now().isoformat()
        payload["reviewed_by"] = _actor_value(actor, "username")
        payload["review_note"] = review_note
        ledger = None
        if decision == "approve":
            result = _award_reviewed_bug_report(dict(actor), payload, review_note=review_note)
            ledger = result.get("ledger")
            payload["status"] = "approved"
            payload["reward_status"] = "awarded"
            payload["ledger_uuid"] = ledger.get("ledger_uuid") if ledger else None
        else:
            payload["status"] = "rejected"
            payload["reward_status"] = "rejected"
        tmp = bug_dir / f".{payload['id']}.review.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        audit("BUG_REPORT_REVIEWED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"{payload['id']}, decision={decision}, ledger={payload.get('ledger_uuid')}")
        return json_resp({"ok": True, "report": payload, "ledger": ledger})
