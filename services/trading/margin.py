"""Trading margin risk/account/liquidation helpers."""

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from services.notifications import create_notification_if_enabled
from services.server_mode_routing import resolve_table
from services.trading.accounting.core import fee_points, notional_points
from services.trading.constants import ASSET_SCALE
from services.trading.notifications import (
    create_trading_user_notification,
    margin_near_liquidation_notification_payload,
    margin_price_jump_notification_payload,
)
from services.trading.validators import _to_decimal, _to_int
from services.trading_mode_gate import (
    assert_same_world,
    liquidation_settle_table,
    liquidation_target_table,
)


POSITION_MARGIN_LONG = "margin_long"
POSITION_MARGIN_SHORT = "short"
POSITION_MARGIN_SHORT_LEGACY = "margin_short"


def _now_text():
    return datetime.now().isoformat()


def _is_short_position(position_type):
    return str(position_type or "") in {POSITION_MARGIN_SHORT, POSITION_MARGIN_SHORT_LEGACY}


def margin_risk_payload(
    service,
    conn,
    position,
    market=None,
    *,
    now_text=None,
    price_override_points=None,
    price_source_override=None,
    strict_high_risk=True,
    allow_internal_price_override=False,
):
    market = market or service._market(conn, position["market_symbol"])
    if price_override_points is None:
        price, price_source, price_meta = service._current_market_price_points(
            conn, market, with_meta=True, high_risk=True
        )
    else:
        if not allow_internal_price_override:
            raise ValueError("internal price override is not allowed")
        price = float(
            _to_decimal(
                price_override_points,
                name="price_override_points",
                minimum=0.00000001,
            )
        )
        price_source = str(price_source_override or "scan_window_replay")
        price_meta = {
            "price_health": "override_replay",
            "fallback_reason": "",
            "excluded_sources": [],
            "warnings": ["internal_price_override"],
            "high_risk_blocked": False,
            "high_risk_block_reason": "internal replay override",
            "requested_price_mode": "risk_grade",
            "reference_price_points": price,
            "risk_grade_price_points": price,
            "resolved_source": price_source,
            "reference_provider_count": 0,
            "risk_grade_provider_count": 0,
            "stale": False,
            "degraded": False,
            "override_price": True,
        }
    if strict_high_risk and bool(price_meta.get("high_risk_blocked")):
        raise ValueError(
            str(price_meta.get("high_risk_block_reason") or "risk-grade price unavailable")
        )
    quantity_units = int(position["quantity_units"])
    exit_notional = notional_points(quantity_units, price)
    close_fee = fee_points(exit_notional, float(market["fee_rate_percent"] or 0))
    interest = service._margin_interest_points(position, now_text=now_text)
    collateral = int(position["collateral_points"] or 0)
    principal = int(position["principal_points"] or 0)
    entry_price = float(
        _to_decimal(
            position["entry_price_points"] or price,
            name="entry_price_points",
            minimum=0.00000001,
        )
    )
    entry_notional = notional_points(quantity_units, entry_price)
    initial_margin_percent = (
        round((collateral * 100.0) / entry_notional, 4) if entry_notional > 0 else 0.0
    )
    if position["position_type"] == POSITION_MARGIN_LONG:
        equity_after = exit_notional - principal - interest - close_fee
        delta = equity_after - collateral
    else:
        delta = principal - exit_notional - interest - close_fee
        equity_after = collateral + delta
    settings = service._settings_payload(conn)
    maintenance_percent = float(settings.get("margin_maintenance_percent") or 0)
    maintenance_points = int(math.ceil(exit_notional * maintenance_percent / 100.0))
    fee_rate_percent = float(market["fee_rate_percent"] or 0)
    fee_rate_decimal = Decimal(str(fee_rate_percent)) / Decimal("100")
    break_even_price_points = None
    quantity_decimal = Decimal(quantity_units)
    if quantity_units > 0:
        if position["position_type"] == POSITION_MARGIN_LONG:
            required_exit_value = (
                Decimal(collateral + principal + int(position["open_fee_points"] or 0))
                + Decimal(str(interest))
            )
            denominator = Decimal("1") - fee_rate_decimal
            if denominator > 0:
                break_even_price_points = float(
                    (
                        required_exit_value
                        * Decimal(ASSET_SCALE)
                        / (quantity_decimal * denominator)
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                )
        else:
            recoverable_value = Decimal(principal - int(position["open_fee_points"] or 0)) - Decimal(
                str(interest)
            )
            denominator = Decimal("1") + fee_rate_decimal
            if recoverable_value > 0 and denominator > 0:
                break_even_price_points = float(
                    (
                        recoverable_value
                        * Decimal(ASSET_SCALE)
                        / (quantity_decimal * denominator)
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
                )
    denominator_percent = None
    liquidation_notional = None
    if position["position_type"] == POSITION_MARGIN_LONG:
        denominator_percent = 100.0 - fee_rate_percent - maintenance_percent
        if denominator_percent > 0:
            liquidation_notional = int(
                math.ceil((principal + interest) * 100.0 / denominator_percent)
            )
    else:
        denominator_percent = 100.0 + fee_rate_percent + maintenance_percent
        liquidation_base = collateral + principal - interest
        if denominator_percent > 0 and liquidation_base > 0:
            liquidation_notional = int(
                math.ceil(liquidation_base * 100.0 / denominator_percent)
            )
    liquidation_price_points = None
    if liquidation_notional is not None and quantity_units > 0:
        liquidation_price_points = float(
            (
                Decimal(liquidation_notional)
                * Decimal(ASSET_SCALE)
                / Decimal(quantity_units)
            ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        )
    maintenance_ratio_percent = (
        round((equity_after * 100.0) / maintenance_points, 2)
        if maintenance_points > 0
        else 0.0
    )
    if equity_after <= maintenance_points:
        risk_status = "liquidation"
        risk_reason = "權益已低於維持保證金，會被列入強制平倉"
    elif maintenance_ratio_percent < 150.0:
        risk_status = "warning"
        risk_reason = "整體維持率偏低，建議補保證金或降低倉位"
    elif _is_short_position(position["position_type"]):
        risk_status = "short_price_risk"
        risk_reason = "借券放空在價格上漲時會虧損，價格越高維持率越低"
    else:
        risk_status = "normal"
        risk_reason = "融資做多在價格下跌時會虧損，價格越低維持率越低"
    return {
        "price_points": price,
        "price_source": price_source,
        "price_context": service._build_price_context(
            market_symbol=position["market_symbol"],
            price_type="risk_grade",
            price_points=price,
            price_source=price_source,
            price_meta=price_meta,
        ),
        "exit_notional_points": exit_notional,
        "close_fee_points": close_fee,
        "interest_points": interest,
        "collateral_points": collateral,
        "initial_margin_points": collateral,
        "original_margin_points": collateral,
        "initial_margin_percent": initial_margin_percent,
        "entry_notional_points": entry_notional,
        "principal_points": principal,
        "delta_points": delta,
        "unrealized_pnl_points": delta,
        "breakeven_price_points": break_even_price_points,
        "equity_after_points": equity_after,
        "maintenance_percent": maintenance_percent,
        "maintenance_points": maintenance_points,
        "maintenance_margin_percent": maintenance_percent,
        "maintenance_margin_points": maintenance_points,
        "liquidation_notional_points": liquidation_notional,
        "liquidation_price_points": liquidation_price_points,
        "maintenance_ratio_percent": maintenance_ratio_percent,
        "risk_status": risk_status,
        "risk_reason": risk_reason,
        "liquidation_required": equity_after <= maintenance_points,
    }


def margin_position_payload_with_risk(
    service,
    conn,
    row,
    *,
    market=None,
    risk_overrides=None,
    strict_risk=False,
    allow_internal_price_override=False,
):
    item = service._margin_position_payload(row)
    try:
        risk = margin_risk_payload(
            service,
            conn,
            row,
            market=market,
            allow_internal_price_override=allow_internal_price_override,
            **(risk_overrides or {}),
        )
    except Exception as exc:
        if strict_risk:
            raise
        risk = {
            "risk_status": "unavailable",
            "risk_reason": f"風險資料暫時無法計算：{str(exc)[:160]}",
            "liquidation_required": False,
        }
    item["risk"] = risk
    item["maintenance_ratio_percent"] = risk.get("maintenance_ratio_percent")
    item["risk_status"] = risk.get("risk_status")
    item["risk_reason"] = risk.get("risk_reason")
    item["equity_after_points"] = risk.get("equity_after_points")
    item["maintenance_points"] = risk.get("maintenance_points")
    item["maintenance_margin_points"] = risk.get("maintenance_margin_points")
    item["maintenance_margin_percent"] = risk.get("maintenance_margin_percent")
    item["initial_margin_points"] = risk.get("initial_margin_points")
    item["original_margin_points"] = risk.get("original_margin_points")
    item["initial_margin_percent"] = risk.get("initial_margin_percent")
    item["entry_notional_points"] = risk.get("entry_notional_points")
    item["current_price_points"] = risk.get("price_points")
    item["unrealized_pnl_points"] = risk.get("unrealized_pnl_points")
    item["breakeven_price_points"] = risk.get("breakeven_price_points")
    item["liquidation_price_points"] = risk.get("liquidation_price_points")
    return item


def margin_free_margin_points(service, conn, user_id):
    user_id = int(user_id)
    if service._is_root_user_id(conn, user_id):
        account = service._root_sim_account(conn, user_id)
        return int(account["balance_points"] or 0)
    wallet_payload = service._wallet_payload(conn, user_id)
    wallet_available = int(wallet_payload.get("points_balance") or 0)
    trial = service._trial_credit_row(conn, user_id)
    trial_available = (
        int(trial["available_points"] or 0)
        if trial and trial["status"] == "active"
        else 0
    )
    return max(0, wallet_available + trial_available)


def margin_account_payload(service, conn, user_id, rows=None):
    user_id = int(user_id)
    if rows is None:
        rows = [
            margin_position_payload_with_risk(service, conn, row)
            for row in conn.execute(
                "SELECT * FROM trading_margin_positions WHERE user_id=? AND status='open' ORDER BY id ASC",
                (user_id,),
            ).fetchall()
        ]
    active = [row for row in rows if row.get("status") == "open"]
    total_position_equity = 0
    total_maintenance = 0
    total_borrowed = 0
    total_unrealized = 0
    warning_count = 0
    unavailable_count = 0
    for row in active:
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        total_position_equity += int(
            risk.get("equity_after_points") or row.get("equity_after_points") or 0
        )
        total_maintenance += int(
            risk.get("maintenance_points") or row.get("maintenance_points") or 0
        )
        total_borrowed += int(row.get("principal_points") or 0)
        total_unrealized += int(
            risk.get("unrealized_pnl_points") or row.get("unrealized_pnl_points") or 0
        )
        status = str(risk.get("risk_status") or row.get("risk_status") or "")
        if status == "unavailable":
            unavailable_count += 1
        elif status == "warning":
            warning_count += 1
    free_margin = margin_free_margin_points(service, conn, user_id) if active else 0
    account_equity = total_position_equity + free_margin
    available_margin = account_equity - total_maintenance
    ratio = (
        round((account_equity / total_maintenance) * 100, 2)
        if total_maintenance > 0
        else None
    )
    liquidation_required = bool(
        active and total_maintenance > 0 and account_equity <= total_maintenance
    )
    if liquidation_required:
        status = "liquidation"
        reason = "整戶權益已低於總維持保證金，會依風險順序強制平倉"
    elif unavailable_count:
        status = "unavailable"
        reason = f"{unavailable_count} 筆倉位風險資料無法計算"
    elif active and ratio is not None and ratio < 150.0:
        status = "warning"
        reason = "整戶維持率偏低，建議補保證金、平倉或降低倉位"
    elif warning_count:
        status = "warning"
        reason = f"{warning_count} 筆倉位接近風險區"
    elif active:
        status = "normal"
        reason = "整戶維持率正常"
    else:
        status = "none"
        reason = "目前沒有借貸倉位"
    return {
        "mode": "cross_margin",
        "user_id": user_id,
        "open_count": len(active),
        "account_equity_points": account_equity,
        "total_position_equity_points": total_position_equity,
        "free_margin_points": free_margin,
        "available_margin_points": available_margin,
        "total_borrowed_points": total_borrowed,
        "total_maintenance_requirement_points": total_maintenance,
        "total_maintenance_points": total_maintenance,
        "total_unrealized_pnl_points": total_unrealized,
        "cross_margin_ratio_percent": ratio,
        "maintenance_ratio_percent": ratio,
        "liquidation_required": liquidation_required,
        "liquidation_count": 1 if liquidation_required else 0,
        "warning_count": warning_count + unavailable_count,
        "status": status,
        "reason": reason,
        "auto_transfer_rule": "available wallet/trial/root-simulated balance is counted as free cross margin during risk checks",
    }


def margin_summary_payload(service, conn, user_id, rows):
    return margin_account_payload(service, conn, user_id, rows)


def margin_liquidation_order_key(row):
    risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
    equity = int(risk.get("equity_after_points") or row.get("equity_after_points") or 0)
    maintenance = int(risk.get("maintenance_points") or row.get("maintenance_points") or 0)
    deficit = equity - maintenance
    ratio = risk.get("maintenance_ratio_percent")
    try:
        ratio_value = float(ratio)
    except Exception:
        ratio_value = -999999.0
    return (deficit, ratio_value, -int(row.get("principal_points") or 0), int(row.get("id") or 0))


def margin_summary_payload_legacy(rows):
    active = [row for row in rows if row.get("status") == "open"]
    total_equity = 0
    total_maintenance = 0
    liquidation_count = 0
    warning_count = 0
    for row in active:
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        total_equity += int(risk.get("equity_after_points") or 0)
        total_maintenance += int(risk.get("maintenance_points") or 0)
        if risk.get("liquidation_required"):
            liquidation_count += 1
        elif str(risk.get("risk_status") or "") in {"warning", "unavailable"}:
            warning_count += 1
    ratio = round((total_equity / total_maintenance) * 100, 2) if total_maintenance > 0 else None
    if liquidation_count:
        status = "liquidation"
        reason = f"{liquidation_count} 筆倉位低於維持保證金"
    elif warning_count:
        status = "warning"
        reason = f"{warning_count} 筆倉位需要注意"
    elif active:
        status = "normal"
        reason = "整戶維持率正常"
    else:
        status = "none"
        reason = "目前沒有借貸倉位"
    return {
        "open_count": len(active),
        "total_equity_after_points": total_equity,
        "total_maintenance_points": total_maintenance,
        "maintenance_ratio_percent": ratio,
        "status": status,
        "reason": reason,
        "liquidation_count": liquidation_count,
        "warning_count": warning_count,
    }


def notify_margin_risk_alerts(service, conn, *, position, risk, market):
    try:
        user_id = int(position["user_id"])
        position_uuid = str(position["position_uuid"])
        market_symbol = str(position["market_symbol"])
        position_label = "融資做多" if position["position_type"] == "margin_long" else "借券放空"
        price = float(_to_decimal(risk.get("price_points") or 0, name="price_points", minimum=0))
        entry_price = float(
            _to_decimal(position["entry_price_points"] or 0, name="entry_price_points", minimum=0)
        )
        ratio = risk.get("maintenance_ratio_percent")
        liquidation_price = risk.get("liquidation_price_points")
        if not risk.get("liquidation_required") and ratio is not None and float(ratio) <= 150.0:
            alert_type = "trading_margin_near_liquidation"
            if not service._has_unread_margin_alert(
                conn, user_id=user_id, alert_type=alert_type, position_uuid=position_uuid
            ):
                notice = margin_near_liquidation_notification_payload(
                    market_symbol=market_symbol,
                    position_label=position_label,
                    price=price,
                    liquidation_price=liquidation_price,
                    ratio=ratio,
                    position_uuid=position_uuid,
                )
                create_trading_user_notification(
                    conn,
                    user_id=user_id,
                    notification_type=notice["notification_type"],
                    title=notice["title"],
                    body=notice["body"],
                    create_notification=create_notification_if_enabled,
                )
        if entry_price > 0 and price > 0:
            move_percent = abs(price - entry_price) * 100.0 / entry_price
            threshold = float(market["max_price_jump_percent"] or 10)
            if move_percent >= threshold:
                alert_type = "trading_margin_price_jump"
                if not service._has_unread_margin_alert(
                    conn, user_id=user_id, alert_type=alert_type, position_uuid=position_uuid
                ):
                    direction = "上漲" if price > entry_price else "下跌"
                    notice = margin_price_jump_notification_payload(
                        market_symbol=market_symbol,
                        position_label=position_label,
                        direction=direction,
                        move_percent=move_percent,
                        entry_price=entry_price,
                        price=price,
                        position_uuid=position_uuid,
                    )
                    create_trading_user_notification(
                        conn,
                        user_id=user_id,
                        notification_type=notice["notification_type"],
                        title=notice["title"],
                        body=notice["body"],
                        create_notification=create_notification_if_enabled,
                    )
    except Exception as exc:
        service._audit_event(
            conn,
            "TRADING_MARGIN_RISK_NOTIFY_FAILED",
            "margin risk notification failed",
            actor={"username": "system", "role": "system"},
            target_user_id=int(position["user_id"]),
            market_symbol=str(position["market_symbol"]),
            severity="warning",
            metadata={
                "position_uuid": str(position["position_uuid"]),
                "risk_status": str((risk or {}).get("risk_status") or ""),
                "error": str(exc)[:200],
            },
        )


def close_margin_position(
    service,
    *,
    actor,
    position_uuid,
    force_liquidation=False,
    price_override_points=None,
    price_source_override=None,
    allow_internal_price_override=False,
    ctx=None,
):
    ctx = service._resolve_trading_ctx(ctx, action="close_margin_position")
    actor_user_id = service._actor_id(actor)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        service._assert_writable(conn)
        margin_positions_table, route_ctx = service._resolve_table(
            "margin_positions", ctx, action="close_margin_position"
        )
        position = conn.execute(
            f"SELECT * FROM {margin_positions_table} WHERE position_uuid=?",
            (str(position_uuid or ""),),
        ).fetchone()
        if not position:
            raise ValueError("margin position not found")
        user_id = int(position["user_id"])
        if not force_liquidation and int(user_id) != int(actor_user_id or 0):
            raise ValueError("cannot close another user's margin position")
        if position["status"] != "open":
            raise ValueError("margin position is not open")
        if force_liquidation:
            source_table = liquidation_target_table(route_ctx)
            settle_table = liquidation_settle_table(route_ctx)
            assert_same_world(route_ctx, route_ctx, "liquidation")
            if source_table != margin_positions_table:
                raise ValueError("liquidation source table mismatch")
            if settle_table != resolve_table("wallets", route_ctx):
                raise ValueError("liquidation settle table mismatch")
            if route_ctx.mode != "production":
                raise ValueError(
                    "shadow liquidation is not supported yet; production-only until shadow funding world lands"
                )
        position = service._accrue_margin_interest(conn, position, actor=actor, ctx=route_ctx)
        market = service._market(conn, position["market_symbol"])
        risk = margin_risk_payload(
            service,
            conn,
            position,
            market,
            price_override_points=price_override_points,
            price_source_override=price_source_override,
            strict_high_risk=True,
            allow_internal_price_override=allow_internal_price_override,
        )
        account_risk = None
        if force_liquidation:
            open_rows = [
                margin_position_payload_with_risk(
                    service,
                    conn,
                    row,
                    risk_overrides={
                        "price_override_points": (
                            price_override_points
                            if row["market_symbol"] == position["market_symbol"]
                            else None
                        ),
                        "price_source_override": (
                            price_source_override
                            if row["market_symbol"] == position["market_symbol"]
                            else None
                        ),
                    }
                    if price_override_points is not None
                    else None,
                    strict_risk=True,
                    allow_internal_price_override=allow_internal_price_override,
                )
                for row in conn.execute(
                    f"SELECT * FROM {margin_positions_table} WHERE user_id=? AND status='open' ORDER BY id ASC",
                    (user_id,),
                ).fetchall()
            ]
            account_risk = margin_account_payload(service, conn, user_id, open_rows)
            if not account_risk.get("liquidation_required"):
                raise ValueError("margin position recovered above liquidation threshold")
        price = risk["price_points"]
        price_source = risk["price_source"]
        close_fee = risk["close_fee_points"]
        interest = risk["interest_points"]
        principal = int(position["principal_points"] or 0)
        collateral = int(position["collateral_points"] or 0)
        collateral_trial = (
            int(position["collateral_trial_points"] or 0)
            if "collateral_trial_points" in position.keys()
            else 0
        )
        collateral_chain = (
            int(position["collateral_chain_points"] or 0)
            if "collateral_chain_points" in position.keys()
            else collateral
        )
        delta = risk["delta_points"]
        ledger_uuids = []
        is_root_simulated = service._is_root_user_id(conn, user_id)
        if principal and not is_root_simulated:
            service._reserve_delta(
                conn,
                delta=principal,
                event_type="margin_principal_repaid",
                reason="TRADING_MARGIN_PRINCIPAL_REPAID",
                actor=actor,
            )
        if is_root_simulated:
            simulated_return = max(0, collateral + delta)
            service._sim_delta(
                conn, user_id, balance_delta=simulated_return, locked_delta=-collateral
            )
            if collateral + delta < 0:
                service._audit_event(
                    conn,
                    "TRADING_ROOT_SIM_MARGIN_BAD_DEBT",
                    "root simulated margin position closed below collateral",
                    actor=actor,
                    target_user_id=user_id,
                    market_symbol=market["symbol"],
                    severity="warning",
                    metadata={
                        "position_uuid": position["position_uuid"],
                        "simulated_bad_debt_points": abs(collateral + delta),
                        "risk": risk,
                    },
                )
        elif collateral_chain:
            ledger_uuids.append(
                service._ledger(
                    conn,
                    ctx=route_ctx,
                    user_id=user_id,
                    currency_type="points",
                    direction="unfreeze",
                    amount=collateral_chain,
                    action_type="trading_margin_collateral_unfreeze",
                    reference_type="trading_margin_position",
                    reference_id=position["position_uuid"],
                    idempotency_key=f"trading:margin:collateral_unfreeze:{position['position_uuid']}",
                    reason="TRADING_MARGIN_COLLATERAL_RELEASE",
                    public_metadata={
                        "position_type": position["position_type"],
                        "market": market["symbol"],
                        "trial_collateral_points": collateral_trial,
                        "chain_collateral_points": collateral_chain,
                    },
                    actor=actor,
                )["ledger_uuid"]
            )
        if is_root_simulated:
            pass
        elif delta > 0:
            service._reserve_delta(
                conn,
                delta=-delta,
                event_type="margin_profit_paid",
                reason="TRADING_MARGIN_PROFIT_PAID",
                actor=actor,
            )
            if collateral_trial:
                service._release_trial_margin_collateral(
                    conn,
                    user_id,
                    collateral_trial=collateral_trial,
                    available_delta_if_active=collateral_trial,
                )
            ledger_uuids.append(
                service._ledger(
                    conn,
                    ctx=route_ctx,
                    user_id=user_id,
                    currency_type="points",
                    direction="credit",
                    amount=delta,
                    action_type="trading_margin_profit",
                    reference_type="trading_margin_position",
                    reference_id=position["position_uuid"],
                    idempotency_key=f"trading:margin:profit:{position['position_uuid']}",
                    reason="TRADING_MARGIN_PROFIT",
                    public_metadata={
                        "position_type": position["position_type"],
                        "market": market["symbol"],
                        "exit_price_points": price,
                    },
                    actor=actor,
                )["ledger_uuid"]
            )
        elif delta < 0:
            remaining_loss = abs(delta)
            if collateral_trial:
                trial_loss = min(collateral_trial, remaining_loss)
                trial_return = collateral_trial - trial_loss
                service._release_trial_margin_collateral(
                    conn,
                    user_id,
                    collateral_trial=collateral_trial,
                    available_delta_if_active=trial_return,
                )
                remaining_loss -= trial_loss
            wallet_payload = service._wallet_payload(conn, user_id, ctx=ctx)
            wallet_balance = int(wallet_payload.get("points_balance") or 0)
            debit_amount = min(remaining_loss, wallet_balance)
            bad_debt = remaining_loss - debit_amount
            if debit_amount:
                ledger_uuids.append(
                    service._ledger(
                        conn,
                        ctx=route_ctx,
                        user_id=user_id,
                        currency_type="points",
                        direction="debit",
                        amount=debit_amount,
                        action_type="trading_margin_loss",
                        reference_type="trading_margin_position",
                        reference_id=position["position_uuid"],
                        idempotency_key=f"trading:margin:loss:{position['position_uuid']}",
                        reason=(
                            "TRADING_MARGIN_LIQUIDATION_LOSS"
                            if force_liquidation
                            else "TRADING_MARGIN_LOSS"
                        ),
                        public_metadata={
                            "position_type": position["position_type"],
                            "market": market["symbol"],
                            "exit_price_points": price,
                            "bad_debt_points": bad_debt,
                        },
                        actor=actor,
                    )["ledger_uuid"]
                )
            if bad_debt:
                service._audit_event(
                    conn,
                    "TRADING_MARGIN_BAD_DEBT",
                    "margin position closed with bad debt",
                    actor=actor,
                    target_user_id=user_id,
                    market_symbol=market["symbol"],
                    severity="critical",
                    metadata={
                        "position_uuid": position["position_uuid"],
                        "bad_debt_points": bad_debt,
                        "risk": risk,
                    },
                )
        elif collateral_trial:
            service._release_trial_margin_collateral(
                conn,
                user_id,
                collateral_trial=collateral_trial,
                available_delta_if_active=collateral_trial,
            )
        if close_fee and not is_root_simulated:
            service._reserve_delta(
                conn,
                delta=close_fee,
                event_type="margin_fee_retained",
                reason="TRADING_MARGIN_CLOSE_FEE",
                actor=actor,
            )
        if interest and not is_root_simulated:
            service._reserve_delta(
                conn,
                delta=interest,
                event_type="margin_interest_retained",
                reason="TRADING_MARGIN_INTEREST",
                actor=actor,
            )
        now = _now_text()
        next_status = "liquidated" if force_liquidation else "closed"
        conn.execute(
            f"""
            UPDATE {margin_positions_table}
            SET close_fee_points=?, interest_points=?, exit_price_points=?, realized_pnl_points=?, status=?, closed_at=?, updated_at=?
            WHERE id=?
            """,
            (close_fee, interest, price, delta, next_status, now, now, position["id"]),
        )
        event_type = (
            "TRADING_MARGIN_POSITION_LIQUIDATED"
            if force_liquidation
            else "TRADING_MARGIN_POSITION_CLOSED"
        )
        service._audit_event(
            conn,
            event_type,
            "margin borrow position liquidated"
            if force_liquidation
            else "margin borrow position closed",
            actor=actor,
            target_user_id=user_id,
            market_symbol=market["symbol"],
            severity="warning" if force_liquidation else "info",
            metadata={
                "position_id": position["id"],
                "position_uuid": position["position_uuid"],
                "position_type": position["position_type"],
                "entry_price_points": float(
                    _to_decimal(
                        position["entry_price_points"],
                        name="entry_price_points",
                        minimum=0,
                    )
                ),
                "exit_price_points": price,
                "price_source": price_source,
                "delta_points": delta,
                "interest_points": interest,
                "close_fee_points": close_fee,
                "funding_mode": (
                    "root_simulated"
                    if is_root_simulated
                    else ("trial_mixed" if collateral_trial else "points_chain")
                ),
                "override_price": bool(price_override_points is not None),
                "risk": risk,
                "account_risk": account_risk,
                "ledger_uuids": ledger_uuids,
            },
        )
        if not is_root_simulated:
            service._record_user_trade_volume(
                conn,
                user_id=user_id,
                trade_kind="margin",
                notional_points=int(risk.get("exit_notional_points") or 0),
                fee_points=close_fee,
                occurred_at=now,
            )
        if force_liquidation:
            service._notify_margin_liquidated(conn, user_id=user_id, position=position, risk=risk)
        conn.commit()
        row = conn.execute(
            f"SELECT * FROM {margin_positions_table} WHERE id=?",
            (position["id"],),
        ).fetchone()
        return {
            "ok": True,
            "position": service._margin_position_payload(row),
            "delta_points": delta,
            "interest_points": interest,
            "close_fee_points": close_fee,
            "funding": service._funding_payload(conn, user_id),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def scan_margin_liquidations(service, *, actor=None, limit=100, ctx=None):
    ctx = service._resolve_trading_ctx(ctx, action="scan_margin_liquidations")
    limit = _to_int(limit or 100, name="limit", minimum=1, maximum=500)
    actor = actor or {"username": "system", "role": "system"}
    conn = service.get_db()
    candidates = []
    errors = []
    scanned = 0
    try:
        service.ensure_schema(conn)
        margin_positions_table, route_ctx = service._resolve_table(
            "margin_positions", ctx, action="scan_margin_liquidations"
        )
        liquidation_target_table(route_ctx)
        liquidation_settle_table(route_ctx)
        assert_same_world(route_ctx, route_ctx, "liquidation")
        settings = service._settings_payload(conn)
        if not settings.get("borrowing_enabled"):
            return {
                "ok": True,
                "enabled": False,
                "reason": "borrowing_disabled",
                "scanned": 0,
                "candidates": [],
                "liquidated": [],
                "errors": [],
            }
        if not settings.get("margin_liquidation_enabled"):
            return {
                "ok": True,
                "enabled": False,
                "reason": "liquidation_disabled",
                "scanned": 0,
                "candidates": [],
                "liquidated": [],
                "errors": [],
            }
        state = service._state(conn)
        if state.get("safe_mode"):
            return {
                "ok": True,
                "enabled": False,
                "reason": "trading_safe_mode",
                "scanned": 0,
                "candidates": [],
                "liquidated": [],
                "errors": [],
            }
        if route_ctx.mode != "production":
            return {
                "ok": True,
                "enabled": False,
                "reason": "shadow_liquidation_unsupported",
                "scanned": 0,
                "candidates": [],
                "liquidated": [],
                "errors": [],
            }
        rows = conn.execute(
            f"SELECT * FROM {margin_positions_table} WHERE status='open' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        scanned = len(rows)
        positions_by_user = {}
        for position in rows:
            try:
                position = service._accrue_margin_interest(conn, position, actor=actor, ctx=route_ctx)
                market = service._market(conn, position["market_symbol"])
                current_price, price_source, price_meta = service._current_market_price_points(
                    conn, market, with_meta=True, high_risk=True
                )
                if bool(price_meta.get("high_risk_blocked")):
                    errors.append(
                        {
                            "position_uuid": position["position_uuid"],
                            "user_id": int(position["user_id"]),
                            "error": str(
                                price_meta.get("high_risk_block_reason")
                                or "price source is in conservative mode"
                            ),
                            "price_health": str(price_meta.get("price_health") or ""),
                        }
                    )
                    continue
                price_window = service._recent_price_window(
                    market["symbol"], lookback_seconds=65, interval="1m", conn=conn
                )
                replay_price = float(current_price)
                if price_window:
                    if position["position_type"] == "margin_long":
                        replay_price = min(float(current_price), float(price_window["low_points"]))
                    else:
                        replay_price = max(float(current_price), float(price_window["high_points"]))
                payload = margin_position_payload_with_risk(
                    service,
                    conn,
                    position,
                    market=market,
                    risk_overrides={
                        "price_override_points": replay_price,
                        "price_source_override": (
                            f"{price_source}+scan_window"
                            if replay_price != current_price
                            else price_source
                        ),
                    },
                    strict_risk=True,
                    allow_internal_price_override=True,
                )
                risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
                notify_margin_risk_alerts(service, conn, position=position, risk=risk, market=market)
                positions_by_user.setdefault(int(position["user_id"]), []).append(payload)
            except Exception as exc:
                errors.append(
                    {
                        "position_uuid": position["position_uuid"],
                        "user_id": int(position["user_id"]),
                        "error": str(exc),
                    }
                )
        for user_id, user_positions in positions_by_user.items():
            account_risk = margin_account_payload(service, conn, user_id, user_positions)
            if not account_risk.get("liquidation_required"):
                continue
            ordered = sorted(
                [row for row in user_positions if row.get("status") == "open"],
                key=margin_liquidation_order_key,
            )
            if not ordered:
                continue
            first = ordered[0]
            candidates.append(
                {
                    "position_uuid": first["position_uuid"],
                    "user_id": int(first["user_id"]),
                    "market_symbol": first["market_symbol"],
                    "position_type": first["position_type"],
                    "risk": first.get("risk") or {},
                    "account_risk": account_risk,
                    "liquidation_order": [row["position_uuid"] for row in ordered],
                }
            )
        conn.commit()
    finally:
        conn.close()

    liquidated = []
    for candidate in candidates:
        try:
            result = close_margin_position(
                service,
                actor=actor,
                position_uuid=candidate["position_uuid"],
                force_liquidation=True,
                price_override_points=(candidate.get("risk") or {}).get("price_points"),
                price_source_override=(candidate.get("risk") or {}).get("price_source"),
                allow_internal_price_override=True,
                ctx=ctx,
            )
            liquidated.append(
                {
                    "position_uuid": candidate["position_uuid"],
                    "user_id": candidate["user_id"],
                    "market_symbol": candidate["market_symbol"],
                    "delta_points": int(result.get("delta_points") or 0),
                    "interest_points": int(result.get("interest_points") or 0),
                    "close_fee_points": int(result.get("close_fee_points") or 0),
                    "risk": candidate["risk"],
                    "account_risk": candidate.get("account_risk"),
                    "liquidation_order": candidate.get("liquidation_order") or [],
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "position_uuid": candidate["position_uuid"],
                    "user_id": candidate["user_id"],
                    "error": str(exc),
                }
            )
    return {
        "ok": not errors,
        "enabled": True,
        "scanned": scanned,
        "candidates": candidates,
        "liquidated": liquidated,
        "errors": errors,
    }
