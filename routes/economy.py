import hashlib
import json
import time

from flask import request

from services.points_chain import DISPLAY_CURRENCY
from services.sanction_notices import record_admin_sanction_notice


def register_economy_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    add_violation = deps.get("add_violation")
    get_db = deps.get("get_db")
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))
    points_service = deps["points_service"]

    def actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}, 401)
        return actor, None

    def manager_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
        if role_rank(role) < role_rank("manager"):
            return None, json_resp({"ok": False, "msg": "需要管理員權限"}, 403)
        return actor, None

    def root_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        if actor_value(actor, "username") != "root":
            return None, json_resp({"ok": False, "msg": "只有 root 可執行此操作"}, 403)
        return actor, None

    def parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON"}, 400)
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request"}, 400)
        return data, None

    def parse_positive_int(value, *, default=1, maximum=1_000_000_000):
        try:
            number = int(value if value not in (None, "") else default)
        except Exception:
            return None
        if number < 1 or number > maximum:
            return None
        return number

    def _stable_spend_key(*, user_id, item_key, quantity):
        payload = json.dumps(
            {
                "user_id": int(user_id),
                "item_key": str(item_key),
                "quantity": int(quantity),
                "minute_bucket": int(time.time() // 60),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return "spend:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def service_error(exc):
        msg = str(exc) or exc.__class__.__name__
        status = 400
        if "insufficient balance" in msg:
            status = 409
            return json_resp({"ok": False, "msg": "點數不足，無法扣除；本次調整未寫入帳本", "code": "insufficient_balance"}), status
        return json_resp({"ok": False, "msg": msg}), status

    def notify_member_points_action(*, actor, user_id, action_label, reason, points_ledger_uuid=None):
        if not add_violation or not get_db:
            return
        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role, status, member_level, base_level, effective_level, sanction_status, sanction_until FROM users WHERE id=?",
                (int(user_id),),
            ).fetchone()
            if not target or target["username"] == "root":
                return
            actor_role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
            _action, _msg, _new_count, violation_id = add_violation(
                target["id"],
                target["username"],
                target["role"],
                points=0,
                reason=f"會員點數權益變更：{action_label}；原因：{reason or '未填寫'}",
                triggered_by=actor_role,
                actor_username=actor_value(actor, "username", "admin"),
                return_violation_id=True,
            )
            if not violation_id:
                return
            previous = {key: target[key] for key in target.keys()}
            record_admin_sanction_notice(
                conn,
                actor=actor,
                target=target,
                previous=previous,
                violation_id=violation_id,
                action_label=action_label,
                reason=reason or "會員點數權益變更",
                points_ledger_uuid=points_ledger_uuid,
            )
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            audit(
                "MEMBER_POINTS_NOTICE_FAILED",
                get_client_ip(),
                user=actor_value(actor, "username", "admin"),
                success=False,
                ua=get_ua(),
                detail=f"user_id={user_id}, error={exc}",
            )
        finally:
            conn.close()

    @app.route("/api/points/wallet", methods=["GET"])
    @require_csrf_safe
    def points_wallet():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "wallet": points_service.get_wallet(actor["id"])})

    @app.route("/api/points/ledger", methods=["GET"])
    @require_csrf_safe
    def points_ledger():
        actor, err = actor_or_401()
        if err:
            return err
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=200) or 50
        offset = max(0, int(request.args.get("offset") or 0))
        return json_resp({
            "ok": True,
            "ledger": points_service.list_ledger(user_id=actor["id"], limit=limit, offset=offset),
        })

    @app.route("/api/points/catalog", methods=["GET"])
    @require_csrf_safe
    def points_catalog():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "catalog": points_service.list_catalog()})

    @app.route("/api/root/economy/catalog", methods=["GET"])
    @require_csrf_safe
    def root_economy_catalog():
        actor, err = root_or_403()
        if err:
            return err
        category = str(request.args.get("category") or "").strip() or None
        return json_resp({
            "ok": True,
            "catalog": points_service.list_catalog(include_disabled=True, category=category),
        })

    @app.route("/api/root/economy/catalog", methods=["POST"])
    @require_csrf
    def root_economy_catalog_save():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        try:
            item = points_service.upsert_catalog_item(
                actor=actor,
                item_key=data.get("item_key"),
                item_name=data.get("item_name"),
                category=data.get("category"),
                base_price=data.get("base_price"),
                dynamic_pricing=bool(data.get("dynamic_pricing")),
                min_price=data.get("min_price"),
                max_price=data.get("max_price"),
                enabled=data.get("enabled", True),
                metadata=metadata,
            )
            audit(
                "ECONOMY_PRICE_CATALOG_CHANGED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"item_key={item.get('item_key')}, category={item.get('category')}, price={item.get('base_price')}, enabled={item.get('enabled')}",
            )
            return json_resp({"ok": True, "item": item, "catalog": points_service.list_catalog(include_disabled=True)})
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/rules", methods=["GET"])
    @require_csrf_safe
    def points_rules():
        actor, err = actor_or_401()
        if err:
            return err
        rules = points_service.list_rules()
        return json_resp({"ok": True, "rules": [row for row in rules if row.get("enabled")]})

    @app.route("/api/points/spend", methods=["POST"])
    @require_csrf
    def points_spend():
        actor, err = actor_or_401()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        item_key = str(data.get("item_key") or "").strip()
        if not item_key:
            return json_resp({"ok": False, "msg": "item_key required"}), 400
        quantity = parse_positive_int(data.get("quantity"), default=1, maximum=1000)
        if quantity is None:
            return json_resp({"ok": False, "msg": "quantity must be 1-1000"}), 400
        try:
            result = points_service.spend_points(
                user_id=actor["id"],
                item_key=item_key,
                quantity=quantity,
                reference_type="price_catalog",
                reference_id=f"catalog:{item_key}",
                idempotency_key=_stable_spend_key(user_id=actor["id"], item_key=item_key, quantity=quantity),
                metadata={},
                actor=actor,
            )
            audit("POINTS_SPEND", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"item_key={item_key}, quantity={quantity}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/ledger/<ledger_uuid>/proof", methods=["GET"])
    @require_csrf_safe
    def points_ledger_proof(ledger_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        proof = points_service.ledger_proof(ledger_uuid)
        if not proof:
            return json_resp({"ok": False, "msg": "找不到 ledger"}), 404
        proof_account = proof.get("public_account_id") or (proof.get("ledger") or {}).get("public_account_id")
        admin_role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
        is_manager = role_rank(admin_role) >= role_rank("manager")
        if not proof_account and not is_manager:
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        if proof_account and proof_account != points_service.get_wallet(actor["id"])["public_account_id"] and not is_manager:
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        return json_resp({"ok": True, "proof": proof})

    @app.route("/api/admin/points/wallets/<int:user_id>", methods=["GET"])
    @require_csrf_safe
    def admin_points_wallet(user_id):
        actor, err = manager_or_403()
        if err:
            return err
        return json_resp({
            "ok": True,
            "wallet": points_service.get_wallet(user_id),
            "ledger": points_service.list_ledger(user_id=user_id, limit=50, include_user_id=True),
        })

    @app.route("/api/root/points/wallets/<int:user_id>/sanction", methods=["POST"])
    @require_csrf
    def root_points_wallet_sanction(user_id):
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.sanction_wallet(
                actor=actor,
                user_id=user_id,
                wallet_status=str(data.get("wallet_status") or ""),
                risk_level=str(data.get("risk_level") or ""),
                reason=str(data.get("reason") or ""),
                freeze_amount=int(data.get("freeze_amount") or 0),
                unfreeze_amount=int(data.get("unfreeze_amount") or 0),
            )
            audit(
                "POINTS_WALLET_SANCTION",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"user_id={user_id}, status={result['wallet'].get('wallet_status')}, risk={result['wallet'].get('risk_level')}",
            )
            changes = []
            if data.get("wallet_status"):
                changes.append(f"錢包狀態 {result['wallet'].get('wallet_status')}")
            if data.get("risk_level"):
                changes.append(f"風險等級 {result['wallet'].get('risk_level')}")
            if int(data.get("freeze_amount") or 0):
                changes.append(f"凍結 {int(data.get('freeze_amount') or 0)} 點")
            if int(data.get("unfreeze_amount") or 0):
                changes.append(f"解凍 {int(data.get('unfreeze_amount') or 0)} 點")
            notify_member_points_action(
                actor=actor,
                user_id=user_id,
                action_label="；".join(changes) or "錢包處分",
                reason=str(data.get("reason") or "錢包處分"),
                points_ledger_uuid=(result.get("ledgers") or [{}])[0].get("ledger_uuid") if result.get("ledgers") else None,
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/ledger", methods=["GET"])
    @require_csrf_safe
    def admin_points_ledger():
        actor, err = manager_or_403()
        if err:
            return err
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=200) or 50
        offset = max(0, int(request.args.get("offset") or 0))
        return json_resp({"ok": True, "ledger": points_service.list_ledger(limit=limit, offset=offset, include_user_id=True)})

    @app.route("/api/admin/points/adjust", methods=["POST"])
    @require_csrf
    def admin_points_adjust():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        amount = parse_positive_int(data.get("amount"), maximum=1_000_000_000)
        if amount is None:
            return json_resp({"ok": False, "msg": "amount must be positive"}), 400
        currency_type = DISPLAY_CURRENCY
        direction = str(data.get("direction") or "").strip()
        reason = str(data.get("reason") or "").strip()
        try:
            user_id = int(data.get("user_id"))
        except Exception:
            return json_resp({"ok": False, "msg": "user_id required"}), 400
        try:
            result = points_service.admin_adjust(
                actor=actor,
                user_id=user_id,
                currency_type=currency_type,
                direction=direction,
                amount=amount,
                reason=reason,
                reference_id=str(data.get("reference_id") or "") or None,
                idempotency_key=str(data.get("idempotency_key") or request.headers.get("Idempotency-Key") or "").strip() or None,
            )
            audit("POINTS_ADMIN_ADJUST", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"user_id={user_id}, currency=points, direction={direction}, amount={amount}")
            notify_member_points_action(
                actor=actor,
                user_id=user_id,
                action_label=f"{'加點' if direction == 'credit' else '扣點'} {amount} 點",
                reason=reason,
                points_ledger_uuid=(result.get("ledger") or {}).get("ledger_uuid"),
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/pending-rewards", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_points_pending_rewards():
        actor, err = manager_or_403()
        if err:
            return err
        if request.method == "GET":
            status = str(request.args.get("status") or "pending").strip()
            return json_resp({"ok": True, "pending_rewards": points_service.list_pending_rewards(status=status)})
        data, err = parse_json_body()
        if err:
            return err
        amount = parse_positive_int(data.get("amount"), maximum=1_000_000_000)
        if amount is None:
            return json_resp({"ok": False, "msg": "amount must be positive"}), 400
        currency_type = DISPLAY_CURRENCY
        action_type = str(data.get("action_type") or "manual_pending_reward").strip()[:80]
        reference_id = str(data.get("reference_id") or "").strip()[:120]
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        metadata = {k: metadata[k] for k in ("reason", "source", "moderation_case_id") if k in metadata}
        try:
            reward = points_service.create_pending_reward(
                actor=actor,
                user_id=int(data.get("user_id")),
                currency_type=currency_type,
                amount=amount,
                action_type=action_type,
                reference_type="admin_review",
                reference_id=reference_id,
                metadata=metadata,
            )
            return json_resp({"ok": True, "pending_reward": reward})
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/pending-rewards/<int:pending_reward_id>/review", methods=["POST"])
    @require_csrf
    def admin_points_pending_reward_review(pending_reward_id):
        actor, err = manager_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.review_pending_reward(
                actor=actor,
                pending_reward_id=pending_reward_id,
                decision=str(data.get("decision") or ""),
                review_note=str(data.get("review_note") or ""),
            )
            audit("POINTS_PENDING_REWARD_REVIEW", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"pending_reward_id={pending_reward_id}, decision={data.get('decision')}")
            reward = result.get("pending_reward") or {}
            if result.get("ledger"):
                notify_member_points_action(
                    actor=actor,
                    user_id=reward.get("user_id"),
                    action_label=f"審核通過加點 {reward.get('amount')} 點",
                    reason=str(data.get("review_note") or "待審核獎勵通過"),
                    points_ledger_uuid=(result.get("ledger") or {}).get("ledger_uuid"),
                )
            return json_resp({"ok": True, **result})
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/chain/seal", methods=["POST"])
    @require_csrf
    def root_points_chain_seal():
        actor, err = root_or_403()
        if err:
            return err
        data = {}
        if request.is_json:
            data = request.get_json(silent=True) or {}
        limit = parse_positive_int(data.get("limit"), default=100, maximum=500) or 100
        try:
            result = points_service.seal_block(actor=actor, limit=limit)
            audit("POINTS_CHAIN_SEAL", get_client_ip(), user=actor["username"], success=bool(result.get("ok")), ua=get_ua(), detail=str(result.get("block") or result.get("msg")))
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/chain/verify", methods=["GET"])
    @require_csrf_safe
    def root_points_chain_verify():
        actor, err = root_or_403()
        if err:
            return err
        result = points_service.verify_chain()
        return json_resp({"ok": result["ok"], "verification": result})

    @app.route("/api/root/points/chain/recovery", methods=["GET"])
    @require_csrf_safe
    def root_points_chain_recovery():
        actor, err = root_or_403()
        if err:
            return err
        return json_resp({
            "ok": True,
            "recovery": points_service.safe_mode_status(),
            "backups": points_service.list_ledger_backups(limit=100),
        })

    @app.route("/api/root/points/chain/recovery/auto-handle", methods=["POST"])
    @require_csrf
    def root_points_chain_recovery_auto_handle():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        if str(data.get("confirm") or "") != "AUTO HANDLE POINTSCHAIN":
            return json_resp({"ok": False, "msg": "confirm must be AUTO HANDLE POINTSCHAIN"}, 400)
        try:
            audit(
                "POINTS_CHAIN_AUTO_HANDLE_START",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail="root requested one-click PointsChain anomaly handling",
            )
            verification = points_service.verify_chain()
            recovery = points_service.safe_mode_status()
            if verification.get("ok") and not recovery.get("safe_mode"):
                audit(
                    "POINTS_CHAIN_AUTO_HANDLE_CLEAN",
                    get_client_ip(),
                    user=actor["username"],
                    success=True,
                    ua=get_ua(),
                    detail="PointsChain verification passed; no recovery needed",
                )
                return json_resp({
                    "ok": True,
                    "action": "verified_clean",
                    "msg": "PointsChain 驗證正常，無需恢復",
                    "verification": verification,
                    "recovery": recovery,
                })
            plan = recovery.get("restore_plan") if isinstance(recovery, dict) else {}
            if not isinstance(plan, dict):
                plan = {}
            backup_id = str(plan.get("recommended_backup_id") or "")
            if not recovery.get("safe_mode") or not backup_id:
                audit(
                    "POINTS_CHAIN_AUTO_HANDLE_MANUAL_REQUIRED",
                    get_client_ip(),
                    user=actor["username"],
                    success=False,
                    ua=get_ua(),
                    detail=f"safe_mode={bool(recovery.get('safe_mode'))}, backup_id={backup_id or '-'}",
                )
                return json_resp({
                    "ok": False,
                    "action": "manual_required",
                    "msg": "PointsChain 異常，但目前沒有可自動套用的健康備份，請檢查 forensic bundle 後手動處理",
                    "verification": verification,
                    "recovery": recovery,
                    "backups": points_service.list_ledger_backups(limit=100),
                }, 409)
            result = points_service.restore_from_backup(
                actor=actor,
                backup_id=backup_id,
                confirm="RESTORE POINTSCHAIN",
            )
            audit(
                "POINTS_CHAIN_AUTO_HANDLE_RESTORE",
                get_client_ip(),
                user=actor["username"],
                success=bool(result.get("ok")),
                ua=get_ua(),
                detail=f"backup_id={backup_id}, verification_ok={bool((result.get('verification') or {}).get('ok'))}",
            )
            return json_resp({
                "ok": True,
                "action": "restored_from_backup",
                "msg": "已使用建議備份恢復 PointsChain，wallet 已由 ledger 重建",
                "initial_verification": verification,
                **result,
            })
        except Exception as exc:
            audit(
                "POINTS_CHAIN_AUTO_HANDLE_FAILED",
                get_client_ip(),
                user=actor["username"],
                success=False,
                ua=get_ua(),
                detail=str(exc),
            )
            return service_error(exc)

    @app.route("/api/root/points/chain/backups", methods=["POST"])
    @require_csrf
    def root_points_chain_backup():
        actor, err = root_or_403()
        if err:
            return err
        try:
            result = points_service.create_ledger_backup(reason="root_manual", kind="manual")
            audit("POINTS_CHAIN_BACKUP", get_client_ip(), user=actor["username"], success=bool(result.get("ok")), ua=get_ua(), detail=result.get("backup_id"))
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/chain/recovery/approve", methods=["POST"])
    @require_csrf
    def root_points_chain_recovery_approve():
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.restore_from_backup(
                actor=actor,
                backup_id=str(data.get("backup_id") or ""),
                confirm=str(data.get("confirm") or ""),
            )
            audit(
                "POINTS_CHAIN_RECOVERY_APPLY",
                get_client_ip(),
                user=actor["username"],
                success=bool(result.get("ok")),
                ua=get_ua(),
                detail=f"backup_id={data.get('backup_id')},verification_ok={bool((result.get('verification') or {}).get('ok'))}",
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/report", methods=["GET"])
    @require_csrf_safe
    def root_points_report():
        actor, err = root_or_403()
        if err:
            return err
        return json_resp({"ok": True, "report": points_service.root_report()})

    @app.route("/api/root/points/audit", methods=["GET"])
    @require_csrf_safe
    def root_points_audit():
        actor, err = root_or_403()
        if err:
            return err
        limit = parse_positive_int(request.args.get("limit"), default=100, maximum=200) or 100
        return json_resp({"ok": True, "audit_logs": points_service.list_chain_audit_logs(limit=limit)})

    @app.route("/api/root/points/ledger/<ledger_uuid>/rollback", methods=["POST"])
    @require_csrf
    def root_points_ledger_rollback(ledger_uuid):
        actor, err = root_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.rollback_ledger(
                actor=actor,
                ledger_uuid=ledger_uuid,
                reason=str(data.get("reason") or ""),
            )
            audit("POINTS_LEDGER_ROLLBACK", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"ledger_uuid={ledger_uuid}")
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/economy/stats", methods=["GET"])
    @require_csrf_safe
    def admin_points_economy_stats():
        actor, err = manager_or_403()
        if err:
            return err
        return json_resp({"ok": True, "stats": points_service.economy_stats()})
