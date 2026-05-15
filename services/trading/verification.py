"""Trading verification and reconciliation orchestration."""

import json

from services.server_mode.routing import resolve_table
from services.trading._clock import now_text as _now_text
from services.trading.constants import OPEN_ORDER_STATUSES
from services.trading.validators import _to_decimal


def _json_dumps(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def replay_positions(service, conn):
    totals = {}
    fills = conn.execute(
        """
        SELECT user_id, market_symbol, side, quantity_units
        FROM trading_fills
        ORDER BY id ASC
        """
    ).fetchall()
    for row in fills:
        key = (int(row["user_id"]), row["market_symbol"])
        totals.setdefault(key, 0)
        if row["side"] == "buy":
            totals[key] += int(row["quantity_units"])
        else:
            totals[key] -= int(row["quantity_units"])
    return totals


def ledger_row(service, conn, ledger_uuid):
    ledger_table, _route_ctx = service._resolve_table("points_ledger", action="ledger-read")
    return conn.execute(f"SELECT * FROM {ledger_table} WHERE ledger_uuid=?", (str(ledger_uuid or ""),)).fetchone()


def verify_fill_ledgers(service, conn, errors):
    orders_table, route_ctx = service._resolve_table("orders", action="verify_fill_ledgers")
    ledger_table = resolve_table("points_ledger", route_ctx)
    fills = conn.execute(
        f"""
        SELECT f.*, o.order_uuid, o.chain_frozen_points
        FROM trading_fills f
        JOIN {orders_table} o ON o.id=f.order_id
        ORDER BY f.id ASC
        """
    ).fetchall()
    ledger_by_uuid = {
        row["ledger_uuid"]: row
        for row in conn.execute(
            f"""
            SELECT *
            FROM {ledger_table}
            WHERE reference_type='trading_order'
              AND action_type IN (
                'trading_unfreeze',
                'trading_spot_buy',
                'trading_spot_sell',
                'trading_fee'
              )
            """
        ).fetchall()
    }
    for fill in fills:
        funding_mode = fill["funding_mode"] if "funding_mode" in fill.keys() else "points_chain"
        if funding_mode == "root_simulated":
            continue
        ledger_uuids = _json_loads(fill["points_ledger_uuids_json"], [])
        if not isinstance(ledger_uuids, list) or not ledger_uuids:
            if funding_mode != "trial_mixed":
                errors.append({
                    "type": "fill_ledger_refs_missing",
                    "fill_id": fill["id"],
                    "fill_uuid": fill["fill_uuid"],
                    "order_id": fill["order_id"],
                })
            continue
        ledgers = []
        for ledger_uuid in ledger_uuids:
            ledger = ledger_by_uuid.get(str(ledger_uuid or ""))
            if not ledger:
                errors.append({
                    "type": "fill_ledger_ref_not_found",
                    "fill_id": fill["id"],
                    "fill_uuid": fill["fill_uuid"],
                    "ledger_uuid": ledger_uuid,
                })
                continue
            ledgers.append(ledger)
            if int(ledger["user_id"]) != int(fill["user_id"]) or ledger["reference_id"] != fill["order_uuid"]:
                errors.append({
                    "type": "fill_ledger_ref_mismatch",
                    "fill_id": fill["id"],
                    "ledger_uuid": ledger_uuid,
                    "expected_user_id": int(fill["user_id"]),
                    "actual_user_id": int(ledger["user_id"]),
                    "expected_reference_id": fill["order_uuid"],
                    "actual_reference_id": ledger["reference_id"],
                })
        actions = {row["action_type"] for row in ledgers}
        if fill["side"] == "buy":
            required = {"trading_unfreeze", "trading_spot_buy"} if int(fill["chain_frozen_points"] or 0) > 0 else set()
        else:
            required = {"trading_spot_sell"} if ledgers else set()
        missing = sorted(required - actions)
        if missing:
            errors.append({
                "type": "fill_ledger_actions_missing",
                "fill_id": fill["id"],
                "fill_uuid": fill["fill_uuid"],
                "missing_actions": missing,
                "actual_actions": sorted(actions),
            })


def verify_open_order_locks(service, conn, errors):
    orders_table, route_ctx = service._resolve_table("orders", action="verify_open_order_locks")
    positions_table = resolve_table("positions", route_ctx)
    ledger_table = resolve_table("points_ledger", route_ctx)
    ledger_net = {}
    for row in conn.execute(
        f"""
        SELECT reference_id, direction, amount
        FROM {ledger_table}
        WHERE reference_type='trading_order'
          AND action_type IN ('trading_freeze', 'trading_unfreeze')
        ORDER BY id ASC
        """
    ).fetchall():
        reference_id = row["reference_id"]
        if not reference_id:
            continue
        ledger_net.setdefault(reference_id, 0)
        if row["direction"] == "freeze":
            ledger_net[reference_id] += int(row["amount"])
        elif row["direction"] == "unfreeze":
            ledger_net[reference_id] -= int(row["amount"])
    order_rows = conn.execute(f"SELECT * FROM {orders_table} ORDER BY id ASC").fetchall()
    for order in order_rows:
        funding_mode = order["funding_mode"] if "funding_mode" in order.keys() else "points_chain"
        if funding_mode == "root_simulated":
            continue
        if order["status"] in OPEN_ORDER_STATUSES and int(order["frozen_points"] or 0) > 0:
            expected_total = int(order["trial_frozen_points"] or 0) + int(order["chain_frozen_points"] or 0)
            actual_total = int(order["frozen_points"] or 0) if order["status"] in OPEN_ORDER_STATUSES else 0
            if order["status"] in OPEN_ORDER_STATUSES and expected_total != actual_total:
                errors.append({
                    "type": "open_order_total_frozen_points_mismatch",
                    "order_id": order["id"],
                    "order_uuid": order["order_uuid"],
                    "status": order["status"],
                    "expected_frozen_points": expected_total,
                    "actual_frozen_points": actual_total,
                })
        expected = (
            int(order["chain_frozen_points"] or 0)
            if order["status"] in OPEN_ORDER_STATUSES and "chain_frozen_points" in order.keys()
            else (int(order["frozen_points"] or 0) if order["status"] in OPEN_ORDER_STATUSES else 0)
        )
        actual = ledger_net.get(order["order_uuid"], 0)
        if expected != actual:
            errors.append({
                "type": "open_order_frozen_points_mismatch",
                "order_id": order["id"],
                "order_uuid": order["order_uuid"],
                "status": order["status"],
                "expected_frozen_points": expected,
                "actual_frozen_points": actual,
            })
    locked_expected = {}
    for order in order_rows:
        if order["side"] == "sell" and order["status"] in OPEN_ORDER_STATUSES:
            key = (int(order["user_id"]), order["market_symbol"])
            locked_expected[key] = locked_expected.get(key, 0) + int(order["quantity_units"])
    grid_reserved_expected = {}
    grid_rows = conn.execute(
        f"""
        SELECT gb.user_id,
               gb.market_symbol,
               go.side,
               go.status AS grid_status,
               COALESCE(go.filled_quantity_units, 0) AS grid_filled_units,
               COALESCE(o.filled_quantity_units, 0) AS order_filled_units,
               o.status AS order_status
        FROM trading_grid_orders go
        JOIN trading_grid_bots gb ON gb.id = go.grid_bot_id
        LEFT JOIN {orders_table} o ON o.order_uuid = go.trading_order_uuid
        WHERE go.status='filled' OR o.status='filled'
        ORDER BY go.id ASC
        """
    ).fetchall()
    grid_filled = {}
    for row in grid_rows:
        key = (int(row["user_id"]), row["market_symbol"])
        side = str(row["side"])
        filled_units = int(row["grid_filled_units"] or 0) or int(row["order_filled_units"] or 0)
        grid_filled.setdefault(key, {"buy": 0, "sell": 0})
        grid_filled[key][side] = grid_filled[key].get(side, 0) + filled_units
    open_grid_sells = {}
    for order in order_rows:
        if order["side"] == "sell" and order["status"] in OPEN_ORDER_STATUSES and str(order["reason"] or "") == "GRID_ORDER":
            key = (int(order["user_id"]), order["market_symbol"])
            open_grid_sells[key] = open_grid_sells.get(key, 0) + int(order["quantity_units"] or 0)
    for key, totals in grid_filled.items():
        reserved = max(0, int(totals.get("buy", 0)) - int(totals.get("sell", 0)) - int(open_grid_sells.get(key, 0)))
        if reserved:
            grid_reserved_expected[key] = reserved
            locked_expected[key] = locked_expected.get(key, 0) + reserved
    for row in conn.execute(
        f"SELECT user_id, market_symbol, locked_quantity_units FROM {positions_table} ORDER BY user_id, market_symbol"
    ).fetchall():
        key = (int(row["user_id"]), row["market_symbol"])
        expected = locked_expected.pop(key, 0)
        actual = int(row["locked_quantity_units"] or 0)
        if expected != actual:
            errors.append({
                "type": "open_sell_locked_quantity_mismatch",
                "user_id": key[0],
                "market_symbol": key[1],
                "expected_locked_quantity_units": expected,
                "actual_locked_quantity_units": actual,
                "grid_reserved_quantity_units": grid_reserved_expected.get(key, 0),
            })
    for key, expected in locked_expected.items():
        if expected:
            errors.append({
                "type": "open_sell_locked_position_missing",
                "user_id": key[0],
                "market_symbol": key[1],
                "expected_locked_quantity_units": expected,
                "actual_locked_quantity_units": 0,
            })


def verify_reserve_pool(service, conn, errors):
    ledger_table, _route_ctx = service._resolve_table("points_ledger", action="verify_reserve_pool")
    fill_delta = int(conn.execute("SELECT COALESCE(SUM(reserve_delta_points), 0) FROM trading_fills").fetchone()[0] or 0)
    trade_event_delta = int(conn.execute(
        """
        SELECT COALESCE(SUM(delta_points), 0)
        FROM trading_reserve_pool_events
        WHERE event_type = 'fee_retained'
        """
    ).fetchone()[0] or 0)
    if fill_delta != trade_event_delta:
        errors.append({
            "type": "reserve_trade_event_replay_mismatch",
            "expected_trade_delta_points": fill_delta,
            "actual_trade_event_delta_points": trade_event_delta,
        })
    margin_delta = int(conn.execute(
        """
        SELECT COALESCE(SUM(delta_points), 0)
        FROM trading_reserve_pool_events
        WHERE event_type IN (
            'margin_fee_retained',
            'margin_interest_retained',
            'margin_principal_lent',
            'margin_principal_repaid',
            'margin_profit_paid'
        )
        """
    ).fetchone()[0] or 0)
    allocation_delta = 0
    running_balance = 0
    for event in conn.execute("SELECT * FROM trading_reserve_pool_events ORDER BY id ASC").fetchall():
        running_balance += int(event["delta_points"] or 0)
        if running_balance != int(event["balance_after"] or 0):
            errors.append({
                "type": "reserve_event_balance_after_mismatch",
                "event_id": event["id"],
                "event_uuid": event["event_uuid"],
                "expected_balance_after": running_balance,
                "actual_balance_after": int(event["balance_after"] or 0),
            })
    allocation_ledgers = {
        row["ledger_uuid"]: row
        for row in conn.execute(
            f"SELECT * FROM {ledger_table} WHERE action_type='trading_reserve_allocation' ORDER BY id ASC"
        ).fetchall()
    }
    for event in conn.execute("SELECT * FROM trading_reserve_pool_events WHERE event_type='root_reserve_allocation' ORDER BY id ASC").fetchall():
        ledger = allocation_ledgers.get(str(event["points_ledger_uuid"] or ""))
        if not ledger:
            errors.append({
                "type": "reserve_allocation_ledger_missing",
                "event_id": event["id"],
                "event_uuid": event["event_uuid"],
                "ledger_uuid": event["points_ledger_uuid"],
            })
            continue
        if ledger["action_type"] != "trading_reserve_allocation" or ledger["direction"] != "debit":
            errors.append({
                "type": "reserve_allocation_ledger_mismatch",
                "event_id": event["id"],
                "event_uuid": event["event_uuid"],
                "ledger_uuid": ledger["ledger_uuid"],
                "actual_action_type": ledger["action_type"],
                "actual_direction": ledger["direction"],
            })
        if int(event["delta_points"]) != int(ledger["amount"]):
            errors.append({
                "type": "reserve_allocation_amount_mismatch",
                "event_id": event["id"],
                "event_uuid": event["event_uuid"],
                "expected_delta_points": int(ledger["amount"]),
                "actual_delta_points": int(event["delta_points"]),
            })
        allocation_delta += int(event["delta_points"] or 0)
    event_delta = int(conn.execute("SELECT COALESCE(SUM(delta_points), 0) FROM trading_reserve_pool_events").fetchone()[0] or 0)
    expected_balance = event_delta
    reserve = service._reserve(conn)
    actual_balance = int(reserve["balance_points"] or 0)
    if expected_balance != actual_balance:
        errors.append({
            "type": "reserve_pool_replay_mismatch",
            "expected_balance_points": expected_balance,
            "actual_balance_points": actual_balance,
            "fill_delta_points": fill_delta,
            "margin_delta_points": margin_delta,
            "allocation_delta_points": allocation_delta,
            "event_delta_points": event_delta,
        })


def verify_sim_accounts(service, conn, errors):
    orders_table, _route_ctx = service._resolve_table("orders", action="verify_sim_accounts")
    expected_locked = {}
    for order in conn.execute(
        f"""
        SELECT user_id, frozen_points
        FROM {orders_table}
        WHERE funding_mode='root_simulated'
          AND status IN ('open', 'partially_filled')
          AND frozen_points > 0
        """
    ).fetchall():
        user_id = int(order["user_id"])
        expected_locked[user_id] = expected_locked.get(user_id, 0) + int(order["frozen_points"] or 0)
    for position in conn.execute(
        """
        SELECT p.user_id, p.collateral_points
        FROM trading_margin_positions p
        JOIN users u ON u.id=p.user_id
        WHERE u.username='root'
          AND p.status='open'
        """
    ).fetchall():
        user_id = int(position["user_id"])
        expected_locked[user_id] = expected_locked.get(user_id, 0) + int(position["collateral_points"] or 0)
    for account in conn.execute("SELECT * FROM trading_sim_accounts ORDER BY user_id").fetchall():
        user_id = int(account["user_id"])
        expected = expected_locked.pop(user_id, 0)
        actual = int(account["locked_points"] or 0)
        if expected != actual:
            errors.append({
                "type": "root_simulated_locked_points_mismatch",
                "user_id": user_id,
                "expected_locked_points": expected,
                "actual_locked_points": actual,
            })
    for user_id, expected in expected_locked.items():
        if expected:
            errors.append({
                "type": "root_simulated_account_missing",
                "user_id": user_id,
                "expected_locked_points": expected,
            })


def verify_margin_position_locks(service, conn, errors):
    ledger_table, _route_ctx = service._resolve_table("points_ledger", action="verify_margin_position_locks")
    root_user_ids = {int(row["id"]) for row in conn.execute("SELECT id FROM users WHERE username='root'").fetchall()}
    ledger_net = {}
    for row in conn.execute(
        f"""
        SELECT reference_id, direction, amount
        FROM {ledger_table}
        WHERE reference_type='trading_margin_position'
          AND action_type IN ('trading_margin_collateral_freeze', 'trading_margin_collateral_unfreeze')
        ORDER BY id ASC
        """
    ).fetchall():
        reference_id = row["reference_id"]
        if not reference_id:
            continue
        ledger_net.setdefault(reference_id, 0)
        if row["direction"] == "freeze":
            ledger_net[reference_id] += int(row["amount"] or 0)
        elif row["direction"] == "unfreeze":
            ledger_net[reference_id] -= int(row["amount"] or 0)
    for position in conn.execute("SELECT * FROM trading_margin_positions ORDER BY id ASC").fetchall():
        position_uuid = position["position_uuid"]
        user_id = int(position["user_id"])
        is_root_simulated = user_id in root_user_ids
        collateral_points = int(position["collateral_points"] or 0)
        collateral_trial = int(position["collateral_trial_points"] or 0) if "collateral_trial_points" in position.keys() else 0
        collateral_chain = int(position["collateral_chain_points"] or 0) if "collateral_chain_points" in position.keys() else collateral_points
        split_total = collateral_trial + collateral_chain
        if not is_root_simulated and collateral_points != split_total:
            errors.append({
                "type": "margin_collateral_lock_mismatch",
                "position_id": position["id"],
                "position_uuid": position_uuid,
                "status": position["status"],
                "expected_collateral_points": split_total,
                "actual_collateral_points": collateral_points,
            })
        expected = 0 if is_root_simulated else (int(position["collateral_chain_points"] or 0) if position["status"] == "open" else 0)
        actual = ledger_net.pop(position_uuid, 0)
        if expected != actual:
            errors.append({
                "type": "margin_collateral_lock_mismatch",
                "position_id": position["id"],
                "position_uuid": position_uuid,
                "status": position["status"],
                "expected_frozen_points": expected,
                "actual_frozen_points": actual,
            })
    for position_uuid, actual in ledger_net.items():
        if actual:
            errors.append({
                "type": "margin_collateral_orphan_lock",
                "position_uuid": position_uuid,
                "actual_frozen_points": actual,
            })


def verify_spot_realized_pnl(service, conn, errors):
    seen_fills = set()
    rows = conn.execute(
        """
        SELECT p.*, f.side, f.quantity_units AS fill_quantity_units,
               f.price_points, f.notional_points, f.fee_points AS fill_fee_points
        FROM trading_spot_realized_pnl p
        LEFT JOIN trading_fills f ON f.id=p.fill_id
        ORDER BY p.id ASC
        """
    ).fetchall()
    for row in rows:
        fill_id = row["fill_id"]
        if fill_id in seen_fills:
            errors.append({"type": "spot_realized_pnl_duplicate_fill", "fill_id": fill_id, "pnl_id": row["id"]})
        seen_fills.add(fill_id)
        if row["side"] != "sell":
            errors.append({"type": "spot_realized_pnl_fill_not_sell", "fill_id": fill_id, "pnl_id": row["id"], "side": row["side"]})
            continue
        if int(row["quantity_units"] or 0) != int(row["fill_quantity_units"] or 0):
            errors.append({"type": "spot_realized_pnl_quantity_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
        if _to_decimal(row["sell_price_points"] or 0, name="sell_price_points", minimum=0) != _to_decimal(row["price_points"] or 0, name="price_points", minimum=0):
            errors.append({"type": "spot_realized_pnl_price_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
        if int(row["gross_proceeds_points"] or 0) != int(row["notional_points"] or 0):
            errors.append({"type": "spot_realized_pnl_proceeds_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
        if int(row["sell_fee_points"] or 0) != int(row["fill_fee_points"] or 0):
            errors.append({"type": "spot_realized_pnl_sell_fee_mismatch", "fill_id": fill_id, "pnl_id": row["id"]})
        expected = (
            int(row["gross_proceeds_points"] or 0)
            - int(row["sell_fee_points"] or 0)
            - int(row["gross_cost_points"] or 0)
        )
        if int(row["net_pnl_points"] or 0) != expected:
            errors.append({
                "type": "spot_realized_pnl_replay_mismatch",
                "fill_id": fill_id,
                "pnl_id": row["id"],
                "expected_net_pnl_points": expected,
                "actual_net_pnl_points": int(row["net_pnl_points"] or 0),
            })


def verify_state_on_conn(service, conn, *, enter_safe_mode=False):
    errors = []
    totals = replay_positions(service, conn)
    positions_table, _route_ctx = service._resolve_table("positions", action="verify_state")
    rows = conn.execute(f"SELECT * FROM {positions_table} ORDER BY user_id, market_symbol").fetchall()
    seen = set()
    for row in rows:
        key = (int(row["user_id"]), row["market_symbol"])
        seen.add(key)
        expected_total = totals.get(key, 0)
        actual_total = int(row["quantity_units"]) + int(row["locked_quantity_units"])
        if expected_total != actual_total:
            errors.append({
                "type": "spot_position_replay_mismatch",
                "user_id": key[0],
                "market_symbol": key[1],
                "expected_total_units": expected_total,
                "actual_total_units": actual_total,
            })
    for key, expected_total in totals.items():
        if key not in seen and expected_total:
            errors.append({
                "type": "spot_position_missing",
                "user_id": key[0],
                "market_symbol": key[1],
                "expected_total_units": expected_total,
                "actual_total_units": 0,
            })
    verify_open_order_locks(service, conn, errors)
    verify_fill_ledgers(service, conn, errors)
    verify_reserve_pool(service, conn, errors)
    verify_sim_accounts(service, conn, errors)
    verify_margin_position_locks(service, conn, errors)
    verify_spot_realized_pnl(service, conn, errors)
    result = {"ok": not errors, "errors": errors, "checked_at": _now_text()}
    if errors and enter_safe_mode:
        conn.execute(
            "UPDATE trading_state SET safe_mode=1, reason=?, verification_json=?, updated_at=?, updated_by=NULL WHERE id=1",
            ("trading_state_verification_failed", _json_dumps(result), _now_text()),
        )
        service._audit_event(conn, "TRADING_SAFE_MODE_ENTERED", "trading state verification failed", severity="critical", metadata=result)
    return result


def verify_state(service):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        result = verify_state_on_conn(service, conn, enter_safe_mode=True)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
