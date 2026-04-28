from flask import request

from services.points_chain import CURRENCIES


def register_economy_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))
    points_service = deps["points_service"]

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}, 401)
        return actor, None

    def manager_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        role = "super_admin" if actor.get("username") == "root" else actor.get("role", "user")
        if role_rank(role) < role_rank("manager"):
            return None, json_resp({"ok": False, "msg": "需要管理員權限"}, 403)
        return actor, None

    def root_or_403():
        actor, err = actor_or_401()
        if err:
            return None, err
        if actor.get("username") != "root":
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

    def service_error(exc):
        msg = str(exc) or exc.__class__.__name__
        status = 400
        if "insufficient balance" in msg:
            status = 409
        return json_resp({"ok": False, "msg": msg}), status

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
                reference_type=str(data.get("reference_type") or "manual_spend"),
                reference_id=str(data.get("reference_id") or ""),
                idempotency_key=str(data.get("idempotency_key") or "") or None,
                metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
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
        if proof_account and proof_account != points_service.get_wallet(actor["id"])["public_account_id"]:
            admin_role = "super_admin" if actor.get("username") == "root" else actor.get("role", "user")
            if role_rank(admin_role) < role_rank("manager"):
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
        actor, err = manager_or_403()
        if err:
            return err
        data, err = parse_json_body()
        if err:
            return err
        amount = parse_positive_int(data.get("amount"), maximum=1_000_000_000)
        if amount is None:
            return json_resp({"ok": False, "msg": "amount must be positive"}), 400
        currency_type = str(data.get("currency_type") or "").strip()
        if currency_type not in CURRENCIES:
            return json_resp({"ok": False, "msg": "currency_type must be soft or hard"}), 400
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
            )
            audit("POINTS_ADMIN_ADJUST", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"user_id={user_id}, currency={currency_type}, direction={direction}, amount={amount}")
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
        currency_type = str(data.get("currency_type") or "").strip()
        if currency_type not in CURRENCIES:
            return json_resp({"ok": False, "msg": "currency_type must be soft or hard"}), 400
        try:
            reward = points_service.create_pending_reward(
                actor=actor,
                user_id=int(data.get("user_id")),
                currency_type=currency_type,
                amount=amount,
                action_type=str(data.get("action_type") or "manual_pending_reward"),
                reference_type=str(data.get("reference_type") or "admin_review"),
                reference_id=str(data.get("reference_id") or ""),
                metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
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

    @app.route("/api/admin/points/economy/stats", methods=["GET"])
    @require_csrf_safe
    def admin_points_economy_stats():
        actor, err = manager_or_403()
        if err:
            return err
        return json_resp({"ok": True, "stats": points_service.economy_stats()})
