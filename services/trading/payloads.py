"""Trading payload and serializer helpers.

These helpers convert database rows and computed values into response
payloads without performing any I/O or state changes.
"""

from datetime import datetime, timedelta


def order_payload(row, *, units_to_quantity):
    item = dict(row)
    item["quantity"] = units_to_quantity(item["quantity_units"])
    item["filled_quantity"] = units_to_quantity(item["filled_quantity_units"])
    return item


def bot_payload(
    row,
    *,
    bot_max_runs_from_storage,
    bot_max_runs_has_remaining,
    now_text,
    market_display_symbol,
    json_loads,
):
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["share_parameters"] = bool(item.get("share_parameters", 0))
    item["max_runs"] = bot_max_runs_from_storage(item.get("max_runs"))
    item["can_run"] = bool(item["enabled"]) and bot_max_runs_has_remaining(item.get("run_count"), row["max_runs"])
    item["next_run_at"] = None
    if item["can_run"]:
        try:
            if item.get("last_run_at"):
                next_dt = datetime.fromisoformat(str(item["last_run_at"])) + timedelta(seconds=int(item.get("cooldown_seconds") or 0))
                item["next_run_at"] = next_dt.isoformat(timespec="seconds")
            else:
                item["next_run_at"] = now_text()
        except Exception:
            item["next_run_at"] = None
    item["display_symbol"] = market_display_symbol(item.get("market_symbol"))
    item["bot_type_label"] = "定投機器人" if item.get("bot_type") == "dca" else "條件機器人"
    item["workflow"] = json_loads(item.get("workflow_json"), None)
    item["execution_state"] = json_loads(item.get("execution_state_json"), {}) if "execution_state_json" in row.keys() else {}
    return item


def bot_run_payload(row):
    return dict(row)


def market_payload(row, *, json_loads, display_symbol_from_parts):
    item = dict(row)
    legacy_unit = "b" + "ps"
    item.pop(f"fee_{legacy_unit}", None)
    item.pop(f"max_price_jump_{legacy_unit}", None)
    item["futures_enabled"] = bool(item["futures_enabled"])
    item["pvp_matching_enabled"] = bool(item["pvp_matching_enabled"])
    item["enabled"] = bool(item["enabled"])
    item["spot_enabled"] = bool(item["spot_enabled"])
    item["allow_margin"] = bool(item.get("allow_margin"))
    item["allow_bots"] = bool(item.get("allow_bots"))
    item["allow_risk_grade_usage"] = bool(item.get("allow_risk_grade_usage"))
    item["live_price_enabled"] = bool(item.get("live_price_enabled"))
    item["reference_price_enabled"] = bool(item.get("reference_price_enabled"))
    item["btc_trade_enabled"] = bool(item.get("btc_trade_enabled"))
    item["provider_ids"] = json_loads(item.get("provider_ids_json"), {})
    item["display_symbol"] = display_symbol_from_parts(
        base_asset=item.get("base_asset"),
        quote_currency=item.get("quote_currency"),
        display_quote_currency=item.get("display_quote_currency"),
    ) or str(item.get("symbol") or "").strip().upper()
    item["live_price_supported"] = bool(item.get("live_price_enabled"))
    item["reference_price_supported"] = bool(item.get("reference_price_enabled"))
    item["btc_trade_supported"] = bool(item.get("btc_trade_enabled"))
    return item


def position_payload(row, *, units_to_quantity):
    item = dict(row)
    item["quantity"] = units_to_quantity(item["quantity_units"])
    item["locked_quantity"] = units_to_quantity(item["locked_quantity_units"])
    return item


def futures_position_payload(row, *, units_to_quantity):
    item = dict(row)
    item["quantity"] = units_to_quantity(item["quantity_units"])
    return item


def margin_position_payload(
    row,
    *,
    units_to_quantity,
    to_decimal,
    apr_percent_from_daily,
    point_micro_scale,
    default_interest_interval_hours,
    default_interest_minimum_hours,
    now_text,
    billable_interest_hours_from_elapsed_seconds,
):
    item = dict(row)
    item["quantity"] = units_to_quantity(item["quantity_units"])
    item["position_label"] = "融資做多" if item["position_type"] == "margin_long" else "借券放空"
    item["exit_price_points"] = float(to_decimal(item.get("exit_price_points") or 0, name="exit_price_points", minimum=0)) if item.get("exit_price_points") is not None else None
    item["realized_pnl_points"] = int(item.get("realized_pnl_points") or 0)
    item["borrowed_asset_symbol"] = str(item.get("borrowed_asset_symbol") or ("POINTS" if item.get("position_type") == "margin_long" else "")).upper()
    item["interest_interval_hours"] = int(item.get("interest_interval_hours") or default_interest_interval_hours)
    item["interest_minimum_hours"] = int(item.get("interest_minimum_hours") or default_interest_minimum_hours)
    item["interest_capitalized_points"] = int(item.get("interest_points") or 0)
    item["interest_paid_points"] = int(item.get("interest_paid_points") or 0)
    item["interest_accrued_hours"] = int(item.get("interest_accrued_hours") or 0)
    item["interest_carry_micropoints"] = int(item.get("interest_carry_micropoints") or 0)
    item["interest_apr_percent"] = round(apr_percent_from_daily(item.get("interest_percent_daily") or 0), 6)
    item["interest_exact_points"] = round(
        item["interest_capitalized_points"] + (item["interest_carry_micropoints"] / point_micro_scale),
        6,
    )
    try:
        opened_at_dt = datetime.fromisoformat(str(item.get("opened_at") or ""))
        now_dt = datetime.fromisoformat(now_text())
        elapsed_sec = max(0.0, (now_dt - opened_at_dt).total_seconds())
        item["total_elapsed_hours"] = int(elapsed_sec / 3600)
        next_billing_hours = billable_interest_hours_from_elapsed_seconds(
            elapsed_sec,
            interval_hours=item["interest_interval_hours"],
            minimum_hours=item["interest_minimum_hours"],
        )
        if next_billing_hours and next_billing_hours <= item["interest_accrued_hours"]:
            next_billing_hours = item["interest_accrued_hours"] + item["interest_interval_hours"]
        item["next_interest_at"] = (opened_at_dt + timedelta(seconds=next_billing_hours * 3600)).isoformat() if next_billing_hours > 0 else None
    except Exception:
        item["total_elapsed_hours"] = 0
        item["next_interest_at"] = None
    return item


def fill_payload(row, *, units_to_quantity, json_loads, realized=None):
    item = dict(row)
    item["quantity"] = units_to_quantity(item["quantity_units"])
    item["points_ledger_uuids"] = json_loads(item.get("points_ledger_uuids_json"), [])
    if realized is not None:
        item["realized_pnl_points"] = int(realized["net_pnl_points"] or 0)
        item["gross_cost_points"] = int(realized["gross_cost_points"] or 0)
        item["buy_fee_estimate_points"] = int(realized["buy_fee_estimate_points"] or 0)
    return item


def bot_audit_label(status):
    mapping = {
        "unaudited": "未稽核",
        "green": "綠燈",
        "yellow": "黃燈",
        "red": "紅燈",
    }
    return mapping.get(str(status or ""), "未稽核")


def bot_audit_eligibility_reason_label(reason):
    mapping = {
        "has_trade": "已至少成交一筆，納入稽核",
        "aged_24h": "啟用已滿 24 小時，納入稽核",
        "awaiting_first_trade": "尚未成交，且未滿 24 小時",
        "disabled": "機器人目前停用中",
        "audit_disabled": "root 已關閉自動稽核",
    }
    return mapping.get(str(reason or ""), str(reason or ""))
