import csv
import hashlib
import io
import json
import time

from flask import Response, request

from services.points_chain import (
    DISPLAY_CURRENCY,
    award_signup_bonus_after_wallet_onboarding,
    bind_self_custody_wallet,
    create_multisig_wallet,
    create_official_hot_wallet,
    delete_cold_wallet,
    delete_primary_cold_wallet,
    ensure_system_wallets,
    list_wallet_identities,
    wallet_onboarding_status,
)
from services.governance.sanction_notices import record_admin_sanction_notice


def register_economy_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_db = deps.get("get_db")
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))
    points_service = deps["points_service"]
    server_mode_service = deps.get("server_mode_service")
    get_system_settings = deps.get("get_system_settings", lambda: {})

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
            return None, json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}, 400)
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "請求內容格式錯誤"}, 400)
        return data, None

    def parse_positive_int(value, *, default=1, maximum=1_000_000_000):
        try:
            number = int(value if value not in (None, "") else default)
        except Exception:
            return None
        if number < 1 or number > maximum:
            return None
        return number

    def parse_required_user_id(value):
        if value in (None, ""):
            return None
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            return None
        return user_id if user_id > 0 else None

    def active_user_wallet_rows(conn, user_id):
        return list_wallet_identities(conn, int(user_id))

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
            return json_resp({"ok": False, "msg": "點數不足，無法扣除；本次交易未寫入帳本", "code": "insufficient_balance"}), status
        return json_resp({"ok": False, "msg": msg}), status

    def setting_bool(key, *, default=False):
        try:
            value = (get_system_settings() or {}).get(key, default)
        except Exception:
            value = default
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    def points_chain_enabled():
        return setting_bool("feature_points_chain_enabled", default=True)

    def points_chain_disabled_response():
        return json_resp({
            "ok": False,
            "code": "points_chain_disabled",
            "feature": "feature_points_chain_enabled",
            "msg": "PointsChain 私有鏈目前已關閉；基本積分錢包、帳本、服務價格與一般扣點仍可使用。",
        }, 503)

    def csv_download_response(filename, fieldnames, rows):
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        return Response(
            "\ufeff" + buffer.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def load_user_ledger_for_export(user_id, *, max_rows=10000):
        rows = []
        offset = 0
        while len(rows) < max_rows:
            batch = points_service.list_ledger(user_id=user_id, limit=200, offset=offset)
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < 200:
                break
            offset += len(batch)
        return rows[:max_rows]

    def notify_member_points_action(*, actor, user_id, action_label, reason, points_ledger_uuid=None, appealable=False):
        if not get_db:
            return
        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role, status, member_level, base_level, effective_level, sanction_status, sanction_until FROM users WHERE id=?",
                (int(user_id),),
            ).fetchone()
            if not target or target["username"] == "root":
                return
            previous = {key: target[key] for key in target.keys()}
            record_admin_sanction_notice(
                conn,
                actor=actor,
                target=target,
                previous=previous,
                action_label=action_label,
                reason=reason or "會員點數權益變更",
                points_ledger_uuid=points_ledger_uuid,
                appealable=appealable,
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

    @app.route("/api/points/wallet/onboarding", methods=["GET"])
    @require_csrf_safe
    def points_wallet_onboarding():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        conn = points_service.get_db()
        try:
            points_service.ensure_schema(conn)
            status = wallet_onboarding_status(conn, points_service=points_service, user_id=actor["id"])
            conn.commit()
            return json_resp({"ok": True, "onboarding": status})
        finally:
            conn.close()

    @app.route("/api/points/wallet/onboarding", methods=["POST"])
    @require_csrf
    def points_wallet_onboarding_update():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        mode = str(data.get("mode") or "").strip().lower()
        if mode not in {"official_hot", "self_custody_cold", "imported_cold", "multisig"}:
            return json_resp({"ok": False, "msg": "wallet mode 不支援"}, 400)
        conn = points_service.get_db()
        try:
            points_service.ensure_schema(conn)
            before_wallets = active_user_wallet_rows(conn, actor["id"])
            before_wallet_ids = {int(row["id"]) for row in before_wallets}
            before_wallet_addresses = {str(row["address"] or "").strip().lower() for row in before_wallets}
            wallet_count_before = len(before_wallet_ids)
            if mode == "official_hot":
                identity = create_official_hot_wallet(
                    conn,
                    user_id=actor["id"],
                    chain_secret=getattr(points_service, "chain_secret", ""),
                )
            elif mode in {"self_custody_cold", "imported_cold"}:
                identity = bind_self_custody_wallet(
                    conn,
                    user_id=actor["id"],
                    wallet_type=mode,
                    public_key_jwk=data.get("public_key_jwk") or {},
                    address=data.get("address") or "",
                    signature=data.get("signature") or "",
                    backup_confirmed=bool(data.get("backup_confirmed")),
                    label=data.get("label") or "",
                )
            else:
                identity = create_multisig_wallet(
                    conn,
                    user_id=actor["id"],
                    threshold=data.get("threshold"),
                    signer_addresses=data.get("signer_addresses") or [],
                    label=data.get("label") or "",
                )
            created_new_wallet = bool(identity and int(identity.get("id") or 0) not in before_wallet_ids)
            creation_fee = {"charged": False, "amount_points": 0}
            if created_new_wallet and wallet_count_before > 0:
                fee_source = str(data.get("fee_source_wallet_address") or "").strip().lower()
                if fee_source not in before_wallet_addresses:
                    raise ValueError("wallet creation fee must be paid from an existing active wallet")
                creation_fee = points_service.charge_wallet_creation_fee_locked(
                    conn,
                    user_id=actor["id"],
                    source_wallet_address=fee_source,
                    request_uuid=data.get("fee_request_uuid") or data.get("request_uuid") or "",
                    signature=data.get("fee_signature") or data.get("wallet_signature") or "",
                    wallet_count_before=wallet_count_before,
                    amount_points=data.get("fee_quote_amount") if data.get("fee_quote_amount") not in (None, "") else None,
                    mode=mode,
                    actor={"id": actor["id"], "username": actor["username"], "role": actor["role"]},
                )
            points_service._rebuild_wallets_from_ledger(conn)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return service_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        bonus = None
        initial_grants = None
        if actor_value(actor, "username") != "root":
            try:
                initial_grants = points_service.award_initial_grants_after_wallet_onboarding(
                    user_id=actor["id"],
                    actor={"id": actor["id"], "username": actor["username"], "role": actor["role"]},
                )
            except Exception as exc:
                audit("POINTS_WALLET_ONBOARDING_INITIAL_GRANT_FAILED", get_client_ip(), user=actor_value(actor, "username"), success=False, ua=get_ua(), detail=str(exc))
                initial_grants = {"created_count": 0, "error": str(exc)}
            try:
                bonus = award_signup_bonus_after_wallet_onboarding(
                    points_service=points_service,
                    user_id=actor["id"],
                    actor={"id": actor["id"], "username": actor["username"], "role": actor["role"]},
                )
            except Exception as exc:
                audit("POINTS_WALLET_ONBOARDING_BONUS_FAILED", get_client_ip(), user=actor_value(actor, "username"), success=False, ua=get_ua(), detail=str(exc))
                bonus = {"created": False, "error": str(exc)}
        conn = points_service.get_db()
        try:
            points_service.ensure_schema(conn)
            status = wallet_onboarding_status(conn, points_service=points_service, user_id=actor["id"])
            conn.commit()
        finally:
            conn.close()
        audit("POINTS_WALLET_ONBOARDING_COMPLETED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"mode={mode},address={(identity or {}).get('address')}")
        return json_resp({"ok": True, "wallet_identity": identity, "creation_fee": creation_fee, "initial_grants": initial_grants, "signup_bonus": bonus, "onboarding": status})

    @app.route("/api/points/wallet/onboarding", methods=["DELETE"])
    @require_csrf
    def points_wallet_onboarding_delete():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            data = {}
        conn = points_service.get_db()
        try:
            points_service.ensure_schema(conn)
            identity = delete_cold_wallet(
                conn,
                user_id=actor["id"],
                address=data.get("address") or "",
                reason=data.get("reason") or "user_deleted_cold_wallet",
            )
            points_service._rebuild_wallets_from_ledger(conn)
            status = wallet_onboarding_status(conn, points_service=points_service, user_id=actor["id"])
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return service_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        audit(
            "POINTS_WALLET_COLD_DELETED",
            get_client_ip(),
            user=actor_value(actor, "username"),
            success=True,
            ua=get_ua(),
            detail=f"address={(identity or {}).get('address')}",
        )
        return json_resp({"ok": True, "wallet_identity": identity, "onboarding": status})

    @app.route("/api/root/points/system-wallets", methods=["GET"])
    @require_csrf_safe
    def root_points_system_wallets():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        conn = points_service.get_db()
        try:
            points_service.ensure_schema(conn)
            wallets = ensure_system_wallets(conn, chain_secret=getattr(points_service, "chain_secret", ""))
            conn.commit()
            return json_resp({"ok": True, "system_wallets": wallets})
        finally:
            conn.close()

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

    @app.route("/api/points/explorer/search", methods=["GET"])
    def points_explorer_search():
        if not points_chain_enabled():
            return points_chain_disabled_response()
        query = str(request.args.get("q") or "").strip()
        if not query:
            return json_resp({"ok": False, "msg": "請輸入交易 hash、Ledger UUID、錢包地址或區塊"}, 400)
        limit = parse_positive_int(request.args.get("limit"), default=25, maximum=100) or 25
        try:
            result = points_service.explorer_lookup(query, limit=limit)
        except Exception as exc:
            return service_error(exc)
        if not result:
            return json_resp({"ok": False, "msg": "查無鏈上資料"}), 404
        return json_resp({"ok": True, "result": result})

    @app.route("/api/points/explorer/tx/<path:ledger_ref>", methods=["GET"])
    def points_explorer_tx(ledger_ref):
        if not points_chain_enabled():
            return points_chain_disabled_response()
        result = points_service.explorer_transaction(ledger_ref)
        if not result:
            return json_resp({"ok": False, "msg": "找不到交易"}), 404
        return json_resp({"ok": True, "result": result})

    @app.route("/api/points/explorer/wallet/<path:address>", methods=["GET"])
    def points_explorer_wallet(address):
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=25, maximum=100) or 25
        try:
            result = points_service.explorer_wallet(address, limit=limit)
        except Exception as exc:
            return service_error(exc)
        return json_resp({"ok": True, "result": result})

    @app.route("/api/points/explorer/block/<path:block_ref>", methods=["GET"])
    def points_explorer_block(block_ref):
        if not points_chain_enabled():
            return points_chain_disabled_response()
        result = points_service.explorer_block(block_ref)
        if not result:
            return json_resp({"ok": False, "msg": "找不到區塊"}), 404
        return json_resp({"ok": True, "result": result})

    @app.route("/api/points/explorer/fee-estimate", methods=["GET"])
    def points_explorer_fee_estimate():
        if not points_chain_enabled():
            return points_chain_disabled_response()
        try:
            fee_points = int(request.args.get("fee_points") or 0)
        except Exception:
            fee_points = 0
        fee_points = max(0, min(10000, fee_points))
        try:
            return json_resp({"ok": True, "estimate": points_service.explorer_fee_estimate(fee_points=fee_points)})
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/explorer/accelerate", methods=["POST"])
    @require_csrf
    def points_explorer_accelerate():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        ledger_ref = str(data.get("ledger_ref") or data.get("ledger_uuid") or data.get("ledger_hash") or "").strip()
        fee_points = parse_positive_int(data.get("fee_points"), default=None, maximum=10000)
        request_uuid = str(data.get("request_uuid") or "").strip()
        if not ledger_ref:
            return json_resp({"ok": False, "msg": "ledger_ref required"}), 400
        if fee_points is None:
            return json_resp({"ok": False, "msg": "fee_points must be 1-10000"}), 400
        try:
            result = points_service.accelerate_explorer_transaction(
                actor=actor,
                ledger_ref=ledger_ref,
                fee_points=fee_points,
                request_uuid=request_uuid,
            )
            audit(
                "POINTS_CHAIN_TX_ACCELERATED",
                get_client_ip(),
                user=actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"ledger_ref={ledger_ref},fee={fee_points}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/transactions/submit", methods=["POST"])
    @require_csrf
    def points_submit_transaction():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.submit_wallet_transaction(
                actor=actor,
                source_wallet_address=data.get("source_wallet_address") or data.get("from") or "",
                destination_wallet_address=data.get("destination_wallet_address") or data.get("to") or "",
                amount_points=data.get("amount_points") or data.get("value") or 0,
                fee_points=data.get("fee_points"),
                request_uuid=str(data.get("request_uuid") or "").strip() or None,
                memo=str(data.get("memo") or ""),
                signature=data.get("signature") or data.get("wallet_signature") or "",
            )
            audit(
                "POINTS_CHAIN_TX_SUBMITTED",
                get_client_ip(),
                user=actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"tx_group_hash={result.get('tx_group_hash')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/wallet/export.csv", methods=["GET"])
    @require_csrf_safe
    def points_wallet_export_csv():
        actor, err = actor_or_401()
        if err:
            return err
        user_id = int(actor["id"])
        wallet = points_service.get_wallet(user_id) or {}
        ledger_rows = load_user_ledger_for_export(user_id)
        rows = [{
            "record_type": "wallet_summary",
            "user_id": wallet.get("user_id", user_id),
            "public_account_id": wallet.get("public_account_id", ""),
            "currency_type": wallet.get("currency_type", DISPLAY_CURRENCY),
            "points_balance": wallet.get("points_balance", 0),
            "points_frozen": wallet.get("points_frozen", 0),
            "total_points_earned": wallet.get("total_points_earned", 0),
            "total_points_spent": wallet.get("total_points_spent", 0),
            "wallet_status": wallet.get("wallet_status", ""),
            "risk_level": wallet.get("risk_level", ""),
            "wallet_created_at": wallet.get("created_at", ""),
            "wallet_updated_at": wallet.get("updated_at", ""),
        }]
        for row in ledger_rows:
            rows.append({
                "record_type": "ledger",
                "user_id": user_id,
                "public_account_id": row.get("public_account_id", ""),
                "currency_type": row.get("currency_type", DISPLAY_CURRENCY),
                "ledger_uuid": row.get("ledger_uuid", ""),
                "direction": row.get("direction", ""),
                "amount": row.get("amount", ""),
                "balance_before": row.get("balance_before", ""),
                "balance_after": row.get("balance_after", ""),
                "action_type": row.get("action_type", ""),
                "reference_type": row.get("reference_type", ""),
                "reference_id": row.get("reference_id", ""),
                "reason": row.get("reason", ""),
                "ledger_hash": row.get("ledger_hash", ""),
                "previous_ledger_hash": row.get("previous_ledger_hash", ""),
                "chain_block_id": row.get("chain_block_id", ""),
                "status": row.get("status", ""),
                "created_at": row.get("created_at", ""),
            })
        fieldnames = [
            "record_type",
            "user_id",
            "public_account_id",
            "currency_type",
            "points_balance",
            "points_frozen",
            "total_points_earned",
            "total_points_spent",
            "wallet_status",
            "risk_level",
            "wallet_created_at",
            "wallet_updated_at",
            "ledger_uuid",
            "direction",
            "amount",
            "balance_before",
            "balance_after",
            "action_type",
            "reference_type",
            "reference_id",
            "reason",
            "ledger_hash",
            "previous_ledger_hash",
            "chain_block_id",
            "status",
            "created_at",
        ]
        audit("POINTS_WALLET_CSV_EXPORTED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"user_id={user_id},rows={len(rows)}")
        return csv_download_response(f"points_wallet_{actor['username']}.csv", fieldnames, rows)

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

    @app.route("/api/points/transactions", methods=["GET"])
    @require_csrf_safe
    def points_transactions():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=100) or 50
        try:
            result = points_service.list_wallet_transactions(
                user_id=actor["id"],
                limit=limit,
                actor={"id": actor["id"], "username": actor["username"], "role": actor["role"]},
            )
            return json_resp(result)
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/governance/proposals", methods=["GET"])
    @require_csrf_safe
    def points_governance_proposals():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=100) or 50
        try:
            return json_resp(points_service.list_governance_proposals(actor=actor, limit=limit))
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/treasury-signer-center", methods=["GET"])
    @require_csrf_safe
    def admin_points_governance_treasury_signer_center():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=100) or 50
        try:
            return json_resp(points_service.official_treasury_signer_center(actor=actor, limit=limit))
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/governance/proposals/<path:proposal_uuid>/vote", methods=["POST"])
    @require_csrf
    def points_governance_vote(proposal_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.cast_governance_vote(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
                vote=data.get("vote"),
                reason=data.get("reason") or "",
                recovery_choice=data.get("recovery_choice") or data.get("recovery_strategy") or "",
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_VOTE",
                get_client_ip(),
                user=actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid},vote={data.get('vote')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/transactions/disputes", methods=["GET"])
    @require_csrf_safe
    def points_transaction_disputes():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=50, maximum=100) or 50
        try:
            return json_resp(points_service.list_transaction_disputes(actor=actor, limit=limit))
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/transactions/disputes", methods=["POST"])
    @require_csrf
    def points_transaction_dispute_create():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        try:
            result = points_service.create_transaction_dispute(
                actor=actor,
                tx_hash=data.get("tx_hash") or data.get("transaction_hash") or data.get("ledger_ref") or "",
                statement=data.get("statement") or data.get("reason") or "",
                victim_wallet_address=data.get("victim_wallet_address") or data.get("wallet_address") or "",
                claimed_amount_points=data.get("claimed_amount_points") or data.get("amount_points") or 0,
                loss_cause=data.get("loss_cause") or "unknown",
                evidence=evidence or [],
                public_key_jwk=data.get("public_key_jwk"),
                signature=data.get("signature") or "",
                signature_nonce=data.get("signature_nonce") or data.get("nonce") or "",
                from_wallet_address=data.get("from_wallet_address") or data.get("from") or "",
                to_wallet_address=data.get("to_wallet_address") or data.get("to") or "",
                chain_branch=data.get("chain_branch") or "",
                account_bound_proof=bool(data.get("account_bound_proof")),
            )
            audit(
                "POINTS_CHAIN_TX_DISPUTE_CREATED",
                "",
                user="address_proven_anonymous",
                success=True,
                ua=get_ua(),
                detail=f"dispute_uuid={result.get('dispute', {}).get('dispute_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/transactions/disputes/<path:dispute_uuid>/reply", methods=["POST"])
    @require_csrf
    def points_transaction_dispute_reply(dispute_uuid):
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        try:
            result = points_service.reply_transaction_dispute(
                actor=actor,
                dispute_uuid=str(dispute_uuid or "").strip(),
                statement=data.get("statement") or data.get("reason") or "",
                evidence=evidence or [],
                public_key_jwk=data.get("public_key_jwk"),
                signature=data.get("signature") or "",
                signature_nonce=data.get("signature_nonce") or data.get("nonce") or "",
                account_bound_proof=bool(data.get("account_bound_proof")),
            )
            audit(
                "POINTS_CHAIN_TX_DISPUTE_REPLY",
                "",
                user="address_proven_anonymous",
                success=True,
                ua=get_ua(),
                detail=f"dispute_uuid={result.get('dispute', {}).get('dispute_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/governance/public-proposal", methods=["POST"])
    @require_csrf
    def points_governance_public_proposal():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        try:
            result = points_service.create_public_governance_proposal(
                actor=actor,
                action_type=data.get("action_type") or "",
                title=data.get("title") or "",
                reason=data.get("reason") or "",
                target_address=data.get("target_address") or data.get("wallet_address") or data.get("address") or "",
                incident_tx_hash=data.get("incident_tx_hash") or "",
                reference=data.get("reference") or "",
                evidence=evidence or [],
                proposal_severity=data.get("proposal_severity") or "NORMAL",
                description=data.get("description") or "",
                impact_scope=data.get("impact_scope") or "",
                risk_summary=data.get("risk_summary") or "",
                payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            )
            audit(
                "POINTS_CHAIN_PUBLIC_GOVERNANCE_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')},action={data.get('action_type')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/governance/address-risk", methods=["POST"])
    @require_csrf
    def points_governance_address_risk():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        try:
            result = points_service.create_address_risk_proposal(
                actor=actor,
                wallet_address=data.get("wallet_address") or data.get("address") or "",
                reason=data.get("reason") or "",
                evidence=evidence,
                reference=data.get("reference") or "",
            )
            audit(
                "POINTS_CHAIN_ADDRESS_RISK_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/points/governance/wallet-freeze", methods=["POST"])
    @require_csrf
    def points_governance_wallet_freeze():
        actor, err = actor_or_401()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        action = str(data.get("action") or "freeze").strip().lower()
        try:
            result = points_service.create_wallet_freeze_proposal(
                actor=actor,
                wallet_address=data.get("wallet_address") or data.get("address") or "",
                reason=data.get("reason") or "",
                evidence=evidence,
                reference=data.get("reference") or "",
                release=action in {"release", "unfreeze"},
            )
            audit(
                "POINTS_CHAIN_WALLET_FREEZE_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')},action={action}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

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
            result = points_service.rc1_facade().spend_service_fee(
                user_id=actor["id"],
                item_key=item_key,
                quantity=quantity,
                reference_type="price_catalog",
                reference_id=f"catalog:{item_key}",
                idempotency_key=_stable_spend_key(user_id=actor["id"], item_key=item_key, quantity=quantity),
                metadata={},
                actor=actor,
                source_wallet_address=data.get("source_wallet_address") or "",
                request_uuid=data.get("request_uuid") or data.get("charge_uuid") or "",
                signature=data.get("signature") or data.get("wallet_signature") or "",
                chain_enabled=points_chain_enabled(),
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
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
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式已停用依帳號查詢用戶錢包；請改用公開 Explorer 查交易 hash 或錢包地址。",
        }, 410)

    @app.route("/api/root/points/wallets/<int:user_id>/sanction", methods=["POST"])
    @require_csrf
    def root_points_wallet_sanction(user_id):
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式不允許 root 直接處分用戶錢包；請改用治理投票的地址凍結、詐騙標記或緊急分支流程。",
        }, 410)

    @app.route("/api/admin/points/ledger", methods=["GET"])
    @require_csrf_safe
    def admin_points_ledger():
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式已停用後台依會員列帳；請用公開 Explorer 以交易 hash、地址或區塊查詢。",
        }, 410)

    @app.route("/api/admin/points/adjust", methods=["POST"])
    @require_csrf
    def admin_points_adjust():
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式已停用手動加減積分；官方撥款需改走治理提案與官方多簽，用戶扣款需由用戶授權交易觸發。",
        }, 410)

    @app.route("/api/root/points/official-wallet/grant", methods=["POST"])
    @require_csrf
    def root_points_official_wallet_grant():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.create_treasury_transfer_proposal(
                actor=actor,
                destination_wallet_address=data.get("destination_wallet_address") or data.get("to") or "",
                amount=data.get("amount") or data.get("amount_points") or 0,
                reason=data.get("reason") or "",
                reference=str(data.get("reference") or data.get("request_uuid") or "").strip(),
                action_type=data.get("action_type") or "TREASURY_TRANSFER",
                memo=data.get("memo") or data.get("reason") or "",
            )
            audit(
                "OFFICIAL_WALLET_GRANT_PROPOSAL_SUBMITTED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "code": "blockchain_permission_model", "msg": str(exc)}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/treasury-transfer", methods=["POST"])
    @require_csrf
    def admin_points_governance_treasury_transfer():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.create_treasury_transfer_proposal(
                actor=actor,
                destination_wallet_address=data.get("destination_wallet_address") or data.get("to") or "",
                amount=data.get("amount") or data.get("amount_points") or 0,
                reason=data.get("reason") or "",
                reference=data.get("reference") or "",
                action_type=data.get("action_type") or "TREASURY_TRANSFER",
                memo=data.get("memo") or "",
            )
            audit(
                "POINTS_CHAIN_TREASURY_TRANSFER_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/mint-request", methods=["POST"])
    @require_csrf
    def admin_points_governance_mint_request():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.create_mint_request_proposal(
                actor=actor,
                amount=data.get("amount") or data.get("amount_points") or 0,
                reason=data.get("reason") or "",
                destination_fund_key=data.get("destination_fund_key") or "official_treasury",
                reference=data.get("reference") or "",
            )
            audit(
                "POINTS_CHAIN_MINT_REQUEST_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/supply-expansion", methods=["POST"])
    @require_csrf
    def admin_points_governance_supply_expansion():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.create_supply_expansion_request_proposal(
                actor=actor,
                requested_delta=data.get("requested_delta") or data.get("amount") or data.get("amount_points") or 0,
                reason=data.get("reason") or "",
                destination_fund_key=data.get("destination_fund_key") or "official_treasury",
                reference=data.get("reference") or "",
                financial_report=data.get("financial_report") or "",
                risk_disclosure=data.get("risk_disclosure") or "",
            )
            audit(
                "POINTS_CHAIN_SUPPLY_EXPANSION_REQUEST_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/policy", methods=["POST"])
    @require_csrf
    def admin_points_governance_policy():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = {
                "parameter_key": data.get("parameter_key") or "",
                "parameter_value": data.get("parameter_value") or "",
                "feature_key": data.get("feature_key") or "",
                "burn_policy": data.get("burn_policy") or "",
                "lockdown_scope": data.get("lockdown_scope") or "",
                "description": data.get("description") or "",
            }
        try:
            result = points_service.create_policy_governance_proposal(
                actor=actor,
                action_type=data.get("action_type") or "",
                title=data.get("title") or "",
                reason=data.get("reason") or "",
                payload=payload,
                reference=data.get("reference") or "",
                proposal_severity=data.get("proposal_severity") or "NORMAL",
                impact_scope=data.get("impact_scope") or "",
                risk_summary=data.get("risk_summary") or "",
            )
            audit(
                "POINTS_CHAIN_POLICY_GOVERNANCE_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')},action={data.get('action_type')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/governance/address-risk", methods=["POST"])
    @require_csrf
    def root_points_governance_address_risk():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        try:
            result = points_service.create_address_risk_proposal(
                actor=actor,
                wallet_address=data.get("wallet_address") or data.get("address") or "",
                reason=data.get("reason") or "",
                evidence=evidence,
                reference=data.get("reference") or "",
            )
            audit(
                "POINTS_CHAIN_ADDRESS_RISK_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/governance/recovery-branch", methods=["POST"])
    @require_csrf
    def root_points_governance_recovery_branch():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        excluded = data.get("excluded_tx_hashes")
        if isinstance(excluded, str):
            excluded = [item.strip() for item in excluded.splitlines() if item.strip()]
        incident_refs = data.get("incident_tx_hashes")
        if isinstance(incident_refs, str):
            incident_refs = [item.strip() for item in incident_refs.splitlines() if item.strip()]
        try:
            result = points_service.create_emergency_recovery_branch_proposal(
                actor=actor,
                incident_tx_hash=data.get("incident_tx_hash") or "",
                reason=data.get("reason") or "",
                base_block_number=data.get("base_block_number") or None,
                base_block_hash=data.get("base_block_hash") or "",
                excluded_tx_hashes=excluded or [],
                recovery_strategy=data.get("recovery_strategy") or data.get("strategy") or "treasury_compensation",
                loss_cause=data.get("loss_cause") or "protocol_fault",
                compensation_rate_per_10000=data.get("compensation_rate_per_10000"),
                victim_statement=data.get("victim_statement") or "",
                victim_evidence_refs=data.get("victim_evidence_refs") or data.get("evidence_refs") or [],
                victim_claims=data.get("victim_claims") or [],
                incident_tx_hashes=incident_refs or [],
                reference=data.get("reference") or "",
            )
            audit(
                "POINTS_CHAIN_RECOVERY_BRANCH_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/recovery-branch", methods=["POST"])
    @require_csrf
    def admin_points_governance_recovery_branch():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        excluded = data.get("excluded_tx_hashes")
        if isinstance(excluded, str):
            excluded = [item.strip() for item in excluded.splitlines() if item.strip()]
        incident_refs = data.get("incident_tx_hashes")
        if isinstance(incident_refs, str):
            incident_refs = [item.strip() for item in incident_refs.splitlines() if item.strip()]
        try:
            result = points_service.create_emergency_recovery_branch_proposal(
                actor=actor,
                incident_tx_hash=data.get("incident_tx_hash") or "",
                reason=data.get("reason") or "",
                base_block_number=data.get("base_block_number") or None,
                base_block_hash=data.get("base_block_hash") or "",
                excluded_tx_hashes=excluded or [],
                recovery_strategy=data.get("recovery_strategy") or data.get("strategy") or "treasury_compensation",
                loss_cause=data.get("loss_cause") or "protocol_fault",
                compensation_rate_per_10000=data.get("compensation_rate_per_10000"),
                victim_statement=data.get("victim_statement") or "",
                victim_evidence_refs=data.get("victim_evidence_refs") or data.get("evidence_refs") or [],
                victim_claims=data.get("victim_claims") or [],
                incident_tx_hashes=incident_refs or [],
                reference=data.get("reference") or "",
            )
            audit(
                "POINTS_CHAIN_RECOVERY_BRANCH_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/transactions/disputes/<path:dispute_uuid>/review", methods=["POST"])
    @require_csrf
    def admin_points_transaction_dispute_review(dispute_uuid):
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.review_transaction_dispute(
                actor=actor,
                dispute_uuid=str(dispute_uuid or "").strip(),
                status=data.get("status") or "",
                review_note=data.get("review_note") or data.get("reason") or "",
                recommended_strategy=data.get("recommended_strategy") or "tainted_remainder_return",
                create_proposal=bool(data.get("create_proposal")),
            )
            audit(
                "POINTS_CHAIN_TX_DISPUTE_REVIEWED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"dispute_uuid={dispute_uuid},status={data.get('status')},proposal={(result.get('proposal') or {}).get('proposal_uuid')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/governance/wallet-freeze", methods=["POST"])
    @require_csrf
    def root_points_governance_wallet_freeze():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        evidence = data.get("evidence")
        if isinstance(evidence, str):
            evidence = [item.strip() for item in evidence.splitlines() if item.strip()]
        action = str(data.get("action") or "freeze").strip().lower()
        try:
            result = points_service.create_wallet_freeze_proposal(
                actor=actor,
                wallet_address=data.get("wallet_address") or data.get("address") or "",
                reason=data.get("reason") or "",
                evidence=evidence,
                reference=data.get("reference") or "",
                release=action in {"release", "unfreeze"},
            )
            audit(
                "POINTS_CHAIN_WALLET_FREEZE_PROPOSAL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={result.get('proposal', {}).get('proposal_uuid')},action={action}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/governance/proposals/<path:proposal_uuid>/execute", methods=["POST"])
    @require_csrf
    def root_points_governance_execute(proposal_uuid):
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        try:
            result = points_service.execute_governance_proposal(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_EXECUTE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid},action={result.get('result', {}).get('action')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/proposals/<path:proposal_uuid>/execute", methods=["POST"])
    @require_csrf
    def admin_points_governance_execute(proposal_uuid):
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        try:
            result = points_service.execute_governance_proposal(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_EXECUTE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid},action={result.get('result', {}).get('action')}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/proposals/<path:proposal_uuid>/sponsor", methods=["POST"])
    @require_csrf
    def admin_points_governance_sponsor(proposal_uuid):
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        try:
            result = points_service.sponsor_governance_proposal(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_SPONSOR",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/proposals/<path:proposal_uuid>/cancel", methods=["POST"])
    @require_csrf
    def admin_points_governance_cancel(proposal_uuid):
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.cancel_governance_proposal(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
                reason=data.get("reason") or "",
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_CANCEL",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/governance/proposals/<path:proposal_uuid>/multisig-sign", methods=["POST"])
    @require_csrf
    def admin_points_governance_multisig_sign(proposal_uuid):
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.sign_governance_multisig(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
                signer_wallet_address=data.get("signer_wallet_address") or data.get("wallet_address") or "",
                signature=data.get("signature") or "",
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_MULTISIG_SIGN",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/root/points/governance/proposals/<path:proposal_uuid>/veto", methods=["POST"])
    @require_csrf
    def root_points_governance_veto(proposal_uuid):
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        try:
            result = points_service.veto_governance_proposal(
                actor=actor,
                proposal_uuid=str(proposal_uuid or "").strip(),
                reason=data.get("reason") or "",
            )
            audit(
                "POINTS_CHAIN_GOVERNANCE_VETO",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"proposal_uuid={proposal_uuid}",
            )
            return json_resp(result)
        except PermissionError as exc:
            return json_resp({"ok": False, "msg": str(exc) or "權限不足"}), 403
        except Exception as exc:
            return service_error(exc)

    @app.route("/api/admin/points/pending-rewards", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_points_pending_rewards():
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式已停用後台待審加點；官方撥款需改走治理提案與官方多簽。",
        }, 410)

    @app.route("/api/admin/points/pending-rewards/<int:pending_reward_id>/review", methods=["POST"])
    @require_csrf
    def admin_points_pending_reward_review(pending_reward_id):
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式已停用後台待審加點；官方撥款需改走治理提案與官方多簽。",
        }, 410)

    @app.route("/api/root/points/chain/seal", methods=["POST"])
    @require_csrf
    def root_points_chain_seal():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
        result = points_service.verify_chain()
        incident = None
        if not result.get("ok") and server_mode_service and hasattr(server_mode_service, "enter_incident_lockdown"):
            try:
                incident = server_mode_service.enter_incident_lockdown(
                    actor=actor,
                    trigger_type="points_chain_verify_failed",
                    reason="PointsChain verification failed",
                    verification=result,
                )
            except Exception as exc:
                incident = {"ok": False, "msg": str(exc)}
        return json_resp({"ok": result["ok"], "verification": result, "incident": incident})

    @app.route("/api/root/points/chain/recovery", methods=["GET"])
    @require_csrf_safe
    def root_points_chain_recovery():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
        data, err = parse_json_body()
        if err:
            return err
        if str(data.get("confirm") or "") != "AUTO HANDLE POINTSCHAIN":
            return json_resp({"ok": False, "msg": "confirm 欄位必須為 AUTO HANDLE POINTSCHAIN"}, 400)
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
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
        if not points_chain_enabled():
            return points_chain_disabled_response()
        return json_resp({"ok": True, "report": points_service.root_report()})

    @app.route("/api/root/points/audit", methods=["GET"])
    @require_csrf_safe
    def root_points_audit():
        actor, err = root_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        limit = parse_positive_int(request.args.get("limit"), default=100, maximum=200) or 100
        return json_resp({"ok": True, "audit_logs": points_service.list_chain_audit_logs(limit=limit)})

    @app.route("/api/root/points/ledger/<ledger_uuid>/rollback", methods=["POST"])
    @require_csrf
    def root_points_ledger_rollback(ledger_uuid):
        return json_resp({
            "ok": False,
            "code": "blockchain_permission_model",
            "msg": "私有鏈模式不允許 rollback 既有交易；修正必須以新的鏈上補償交易追加。",
        }, 410)

    @app.route("/api/admin/points/economy/stats", methods=["GET"])
    @require_csrf_safe
    def admin_points_economy_stats():
        actor, err = manager_or_403()
        if err:
            return err
        if not points_chain_enabled():
            return points_chain_disabled_response()
        return json_resp({"ok": True, "stats": points_service.economy_stats()})
