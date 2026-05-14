"""Trading funding and simulated-contract orchestration helpers.

This module keeps funding-rate snapshot routing plus the root simulated
contract/funding world in one place. The legacy trading engine remains the
public façade and delegates into these helpers.
"""

import uuid
from decimal import Decimal, ROUND_HALF_UP

from services.server_mode.context import SmV2Context
from services.trading.accounting.core import notional_points, quantity_to_units, units_to_quantity
from services.trading.accounting.trial_credit import trial_credit_payload
from services.trading.constants import ASSET_SCALE
from services.trading.payloads import futures_position_payload
from services.trading.validators import _to_decimal, _to_int
from services.trading._clock import now_text as _now_text
from services.trading.mode_gate import assert_same_world, funding_channel_key


def funding_snapshot_ctx(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("funding snapshot is invalid")
    return SmV2Context(
        mode=str(snapshot.get("mode") or "").strip(),
        tester_id=snapshot.get("tester_id"),
        actor_role="system",
        request_id=f"funding-{snapshot.get('mode') or 'unknown'}-{snapshot.get('tester_id') or 'prod'}",
    )


def publish_funding_rate_snapshot(
    service,
    *,
    market_symbol,
    rate_percent,
    actor=None,
    ctx=None,
    provider_count=1,
    confidence="medium",
    stale=False,
    degraded=False,
    exclusion_reason="",
):
    route_ctx = service._resolve_trading_ctx(ctx, action="funding_publish")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, market_symbol)
        settings = service._settings_payload(conn)
        if route_ctx.mode == "internal_test" and not settings.get("shadow_funding_publish_enabled"):
            return {
                "ok": True,
                "enabled": False,
                "reason": "shadow_funding_publish_disabled",
                "market_symbol": market["symbol"],
                "mode": route_ctx.mode,
                "tester_id": route_ctx.tester_id,
            }
        channel_key = funding_channel_key(market["symbol"], route_ctx)
        snapshot = {
            "channel_key": channel_key,
            "market_symbol": market["symbol"],
            "mode": route_ctx.mode,
            "tester_id": route_ctx.tester_id,
            "rate_percent": float(rate_percent or 0),
            "provider_count": max(0, int(provider_count or 0)),
            "confidence": str(confidence or "medium").strip() or "medium",
            "stale": bool(stale),
            "degraded": bool(degraded),
            "exclusion_reason": str(exclusion_reason or "").strip(),
            "last_update_at": _now_text(),
            "published_by": service._actor_id(actor),
        }
        service._funding_channels[channel_key] = snapshot
        return {"ok": True, "snapshot": dict(snapshot)}
    finally:
        conn.close()


def get_funding_rate_snapshot(service, *, market_symbol, ctx=None):
    route_ctx = service._resolve_trading_ctx(ctx, action="funding_read")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        market = service._market(conn, market_symbol)
        channel_key = funding_channel_key(market["symbol"], route_ctx)
        snapshot = service._funding_channels.get(channel_key)
        if not snapshot:
            return {
                "ok": True,
                "channel_key": channel_key,
                "snapshot": None,
                "market_symbol": market["symbol"],
                "mode": route_ctx.mode,
                "tester_id": route_ctx.tester_id,
            }
        return {"ok": True, "channel_key": channel_key, "snapshot": dict(snapshot)}
    finally:
        conn.close()


def settle_funding_adjustment(
    service,
    *,
    actor,
    user_id,
    market_symbol,
    delta_points,
    published_snapshot=None,
    ctx=None,
    idempotency_key=None,
):
    route_ctx = service._resolve_trading_ctx(ctx, action="funding_settlement")
    amount = int(delta_points or 0)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        if route_ctx.mode == "internal_test":
            from services.snapshots import ensure_snapshot_schema

            ensure_snapshot_schema(conn)
        settings = service._settings_payload(conn)
        if route_ctx.mode == "internal_test" and not settings.get("shadow_funding_publish_enabled"):
            raise ValueError("shadow funding publish is disabled")
        market = service._market(conn, market_symbol)
        if published_snapshot is None:
            published_snapshot = service.get_funding_rate_snapshot(
                market_symbol=market["symbol"],
                ctx=route_ctx,
            ).get("snapshot")
        if not published_snapshot:
            raise ValueError("funding snapshot not found")
        source_ctx = funding_snapshot_ctx(published_snapshot)
        assert_same_world(source_ctx, route_ctx, "funding_settlement")
        if amount == 0:
            return {
                "ok": True,
                "no_op": True,
                "wallet": service._wallet_payload(conn, user_id, ctx=route_ctx),
                "channel_key": funding_channel_key(market["symbol"], route_ctx),
            }
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        direction = "credit" if amount > 0 else "debit"
        ledger = service._ledger(
            conn,
            ctx=route_ctx,
            user_id=int(user_id),
            currency_type="points",
            direction=direction,
            amount=abs(amount),
            action_type="trading_funding_settlement",
            reference_type="trading_market",
            reference_id=market["symbol"],
            idempotency_key=idempotency_key or f"trading:funding:settle:{market['symbol']}:{user_id}:{uuid.uuid4()}",
            reason="TRADING_FUNDING_SETTLEMENT",
            public_metadata={
                "market_symbol": market["symbol"],
                "funding_rate_percent": float(published_snapshot.get("rate_percent") or 0),
                "funding_channel_key": str(published_snapshot.get("channel_key") or ""),
                "mode": route_ctx.mode,
                "tester_id": route_ctx.tester_id,
            },
            actor=actor,
        )
        conn.commit()
        return {
            "ok": True,
            "wallet": service._wallet_payload(conn, user_id, ctx=route_ctx),
            "ledger_uuid": str(ledger["ledger_uuid"]),
            "channel_key": str(published_snapshot.get("channel_key") or ""),
            "mode": route_ctx.mode,
            "tester_id": route_ctx.tester_id,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def root_sim_account(service, conn, user_id, *, actor=None, root_simulated_initial_points):
    del actor
    user_id = int(user_id)
    now = _now_text()
    conn.execute(
        """
        INSERT OR IGNORE INTO trading_sim_accounts (
            user_id, balance_points, locked_points, initial_balance_points, updated_at
        ) VALUES (?, ?, 0, ?, ?)
        """,
        (user_id, root_simulated_initial_points, root_simulated_initial_points, now),
    )
    return conn.execute("SELECT * FROM trading_sim_accounts WHERE user_id=?", (user_id,)).fetchone()


def sim_delta(
    service,
    conn,
    user_id,
    *,
    balance_delta=0,
    locked_delta=0,
    root_simulated_initial_points,
):
    account = root_sim_account(
        service,
        conn,
        user_id,
        root_simulated_initial_points=root_simulated_initial_points,
    )
    next_balance = int(account["balance_points"] or 0) + int(balance_delta)
    next_locked = int(account["locked_points"] or 0) + int(locked_delta)
    if next_balance < 0:
        raise ValueError("root simulated trading points are insufficient")
    if next_locked < 0:
        raise ValueError("root simulated locked points are inconsistent")
    conn.execute(
        "UPDATE trading_sim_accounts SET balance_points=?, locked_points=?, updated_at=? WHERE user_id=?",
        (next_balance, next_locked, _now_text(), int(user_id)),
    )
    return conn.execute("SELECT * FROM trading_sim_accounts WHERE user_id=?", (int(user_id),)).fetchone()


def funding_payload(
    service,
    conn,
    user_id,
    *,
    root_simulated_initial_points,
    trial_credit_days,
):
    user = conn.execute("SELECT username FROM users WHERE id=?", (int(user_id),)).fetchone()
    if user and user["username"] == "root":
        account = root_sim_account(
            service,
            conn,
            user_id,
            root_simulated_initial_points=root_simulated_initial_points,
        )
        return {
            "mode": "root_simulated",
            "available_points": int(account["balance_points"] or 0),
            "locked_points": int(account["locked_points"] or 0),
            "initial_balance_points": int(account["initial_balance_points"] or root_simulated_initial_points),
            "note": "root 模擬交易資金不寫入 PointsChain，也不影響帳戶積分",
        }
    trial = service._ensure_trial_credit(conn, user_id)
    payload = service._wallet_payload(conn, user_id)
    wallet_available = int(payload.get("points_balance") or 0)
    wallet_locked = int(payload.get("points_frozen") or 0)
    trial_payload = None
    if trial:
        trial_payload = trial_credit_payload(trial, days_valid=trial_credit_days)
    return {
        "mode": "points_chain",
        "available_points": wallet_available + int(trial["available_points"] or 0) if trial else wallet_available,
        "locked_points": wallet_locked + int(trial["locked_points"] or 0) if trial else wallet_locked,
        "wallet_available_points": wallet_available,
        "wallet_locked_points": wallet_locked,
        "trial_credit": trial_payload,
        "note": "一般用戶交易會優先使用交易所體驗金，體驗金到期或賠光後停止使用；已實現獲利保留給用戶",
    }


def open_root_contract_position(
    service,
    *,
    actor,
    market_symbol,
    side,
    quantity,
    leverage,
    margin_points,
    root_simulated_initial_points,
    trial_credit_days,
):
    if not service._is_root_actor(actor):
        raise ValueError("only root can use contract trading")
    user_id = service._actor_id(actor)
    side = str(side or "").strip().lower()
    if side not in {"long", "short"}:
        raise ValueError("contract side must be long or short")
    quantity_units = quantity_to_units(quantity)
    leverage = _to_int(leverage, name="leverage", minimum=1, maximum=20)
    margin_points = _to_int(
        margin_points,
        name="margin_points",
        minimum=1,
        maximum=root_simulated_initial_points,
    )
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        market = service._market(conn, market_symbol)
        settings = service._settings_payload(conn)
        if not settings.get("futures_enabled") or not int(market["futures_enabled"] or 0):
            raise ValueError("contract trading is disabled")
        service._assert_market_boot_ready(market, usage="contract position open", conn=conn)
        price, price_source, price_meta = service._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
        service._assert_price_meta_allows_high_risk_use(
            conn,
            actor=actor,
            market_symbol=market["symbol"],
            usage="contract position open",
            price_meta=price_meta,
        )
        exposure = notional_points(quantity_units, price)
        if exposure > margin_points * leverage:
            raise ValueError("contract exposure exceeds margin and leverage")
        sim_delta(
            service,
            conn,
            user_id,
            balance_delta=-margin_points,
            root_simulated_initial_points=root_simulated_initial_points,
        )
        position_uuid = str(uuid.uuid4())
        now = _now_text()
        if side == "long":
            liquidation_price = max(
                0.00000001,
                float(
                    (
                        Decimal(str(price))
                        - (Decimal(margin_points) * Decimal(ASSET_SCALE) / Decimal(quantity_units))
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                ),
            )
        else:
            liquidation_price = float(
                (
                    Decimal(str(price))
                    + (Decimal(margin_points) * Decimal(ASSET_SCALE) / Decimal(quantity_units))
                ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
            )
        cur = conn.execute(
            """
            INSERT INTO trading_futures_positions (
                position_uuid, user_id, market_symbol, side, quantity_units,
                entry_price_points, leverage, margin_points, liquidation_price_points,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                position_uuid,
                user_id,
                market["symbol"],
                side,
                quantity_units,
                price,
                leverage,
                margin_points,
                liquidation_price,
                now,
                now,
            ),
        )
        service._audit_event(
            conn,
            "TRADING_ROOT_CONTRACT_OPENED",
            "root opened simulated contract position",
            actor=actor,
            market_symbol=market["symbol"],
            severity="warning",
            metadata={
                "position_id": cur.lastrowid,
                "side": side,
                "quantity": units_to_quantity(quantity_units),
                "entry_price_points": price,
                "price_source": price_source,
                "leverage": leverage,
                "margin_points": margin_points,
            },
        )
        conn.commit()
        row = conn.execute("SELECT * FROM trading_futures_positions WHERE id=?", (cur.lastrowid,)).fetchone()
        return {
            "ok": True,
            "position": futures_position_payload(row, units_to_quantity=units_to_quantity),
            "funding": funding_payload(
                service,
                conn,
                user_id,
                root_simulated_initial_points=root_simulated_initial_points,
                trial_credit_days=trial_credit_days,
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_root_contract_position(
    service,
    *,
    actor,
    position_uuid,
    root_simulated_initial_points,
    trial_credit_days,
):
    if not service._is_root_actor(actor):
        raise ValueError("only root can use contract trading")
    user_id = service._actor_id(actor)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        position = conn.execute(
            "SELECT * FROM trading_futures_positions WHERE position_uuid=?",
            (str(position_uuid or ""),),
        ).fetchone()
        if not position:
            raise ValueError("contract position not found")
        if int(position["user_id"]) != int(user_id):
            raise ValueError("cannot close another user's contract position")
        if position["status"] != "open":
            raise ValueError("contract position is not open")
        market = service._market(conn, position["market_symbol"])
        service._assert_market_boot_ready(market, usage="contract position close", conn=conn)
        current_price, price_source, price_meta = service._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
        service._assert_price_meta_allows_high_risk_use(
            conn,
            actor=actor,
            market_symbol=market["symbol"],
            usage="contract position close",
            price_meta=price_meta,
        )
        entry_price = float(_to_decimal(position["entry_price_points"], name="entry_price_points", minimum=0.00000001))
        quantity_units = int(position["quantity_units"])
        price_delta = notional_points(quantity_units, abs(current_price - entry_price))
        pnl = price_delta if current_price >= entry_price else -price_delta
        if position["side"] == "short":
            pnl = -pnl
        margin = int(position["margin_points"])
        credit = max(0, margin + pnl)
        sim_delta(
            service,
            conn,
            user_id,
            balance_delta=credit,
            root_simulated_initial_points=root_simulated_initial_points,
        )
        now = _now_text()
        conn.execute(
            "UPDATE trading_futures_positions SET status='closed', updated_at=? WHERE id=?",
            (now, position["id"]),
        )
        service._audit_event(
            conn,
            "TRADING_ROOT_CONTRACT_CLOSED",
            "root closed simulated contract position",
            actor=actor,
            market_symbol=position["market_symbol"],
            severity="warning",
            metadata={
                "position_id": position["id"],
                "position_uuid": position["position_uuid"],
                "entry_price_points": entry_price,
                "exit_price_points": current_price,
                "price_source": price_source,
                "pnl_points": pnl,
                "credited_points": credit,
            },
        )
        conn.commit()
        row = conn.execute("SELECT * FROM trading_futures_positions WHERE id=?", (position["id"],)).fetchone()
        return {
            "ok": True,
            "position": futures_position_payload(row, units_to_quantity=units_to_quantity),
            "pnl_points": pnl,
            "credited_points": credit,
            "funding": funding_payload(
                service,
                conn,
                user_id,
                root_simulated_initial_points=root_simulated_initial_points,
                trial_credit_days=trial_credit_days,
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_root_simulated_balance(service, *, actor, root_simulated_initial_points):
    if not service._is_root_actor(actor):
        raise ValueError("only root can reset simulated trading points")
    user_id = service._actor_id(actor)
    tables, _route_ctx = service._sql_tables(for_write=True, action="root_simulated_reset")
    orders_table = tables["orders"]
    positions_table = tables["positions"]
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        root_sim_account(
            service,
            conn,
            user_id,
            actor=actor,
            root_simulated_initial_points=root_simulated_initial_points,
        )
        now = _now_text()
        deleted_counts = {
            "orders": int(conn.execute(f"SELECT COUNT(*) FROM {orders_table} WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "fills": int(conn.execute("SELECT COUNT(*) FROM trading_fills WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "spot_positions": int(conn.execute(f"SELECT COUNT(*) FROM {positions_table} WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "futures_positions": int(conn.execute("SELECT COUNT(*) FROM trading_futures_positions WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "margin_positions": int(conn.execute("SELECT COUNT(*) FROM trading_margin_positions WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "pending_profit": int(conn.execute("SELECT COUNT(*) FROM trading_pending_profit WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "spot_realized_pnl": int(conn.execute("SELECT COUNT(*) FROM trading_spot_realized_pnl WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
            "bots": int(conn.execute("SELECT COUNT(*) FROM trading_bots WHERE user_id=?", (user_id,)).fetchone()[0] or 0),
        }
        conn.execute("DELETE FROM trading_bot_runs WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_bots WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_spot_realized_pnl WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_fills WHERE user_id=?", (user_id,))
        conn.execute(f"DELETE FROM {orders_table} WHERE user_id=?", (user_id,))
        conn.execute(f"DELETE FROM {positions_table} WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_futures_positions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_margin_positions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM trading_pending_profit WHERE user_id=?", (user_id,))
        conn.execute(
            """
            UPDATE trading_sim_accounts
            SET balance_points=?, locked_points=0, initial_balance_points=?, updated_at=?, reset_at=?, reset_by=?
            WHERE user_id=?
            """,
            (root_simulated_initial_points, root_simulated_initial_points, now, now, user_id, user_id),
        )
        service._audit_event(
            conn,
            "TRADING_ROOT_SIM_BALANCE_RESET",
            "root reset simulated trading state",
            actor=actor,
            severity="warning",
            metadata={"balance_points": root_simulated_initial_points, "deleted": deleted_counts},
        )
        conn.commit()
        account = root_sim_account(
            service,
            conn,
            user_id,
            root_simulated_initial_points=root_simulated_initial_points,
        )
        return {
            "ok": True,
            "funding": {
                "mode": "root_simulated",
                "available_points": int(account["balance_points"] or 0),
                "locked_points": int(account["locked_points"] or 0),
                "initial_balance_points": int(account["initial_balance_points"] or root_simulated_initial_points),
            },
            "deleted": deleted_counts,
            "cancelled_open_orders": deleted_counts["orders"],
            "closed_open_contracts": deleted_counts["futures_positions"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
