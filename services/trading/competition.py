"""Trading bot competition leaderboards and weekly rewards."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal

from services.trading._clock import now_text as _now_text
from services.trading.accounting.core import fee_points, notional_points, units_to_quantity


BOT_COMPETITION_REWARD_ACTION = "trading_bot_weekly_competition_reward"
BOT_COMPETITION_REWARD_REFERENCE = "trading_bot_competition"
BOT_COMPETITION_DEFAULT_REWARD_POINTS = 100
BOT_COMPETITION_CATEGORIES = (
    {"category": "dca", "label": "定投機器人", "bot_kind": "trading_bot", "bot_type": "dca"},
    {"category": "workflow", "label": "Workflow 機器人", "bot_kind": "trading_bot", "bot_type": "conditional"},
    {"category": "grid", "label": "網格機器人", "bot_kind": "grid_bot", "bot_type": None},
)
WEEK_KEY_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def _json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        parsed = json.loads(value)
    except Exception:
        return default if default is not None else {}
    return parsed if parsed is not None else (default if default is not None else {})


def _row_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return row.get(key, default) if hasattr(row, "get") else default


def bot_competition_week_key(value=None):
    if isinstance(value, str) and WEEK_KEY_RE.match(value):
        return value
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.now()
    iso = dt.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def bot_competition_previous_week_key(value=None):
    dt = value if isinstance(value, datetime) else datetime.now()
    return bot_competition_week_key(dt - timedelta(days=7))


def bot_competition_week_bounds(week_key):
    match = WEEK_KEY_RE.match(str(week_key or ""))
    if not match:
        week_key = bot_competition_week_key()
        match = WEEK_KEY_RE.match(week_key)
    year = int(match.group(1))
    week = int(match.group(2))
    start = datetime.fromisocalendar(year, week, 1)
    end = start + timedelta(days=7)
    return start.isoformat(), end.isoformat()


def _competition_settings(settings):
    safe = settings if isinstance(settings, dict) else {}
    try:
        reward_points = int(safe.get("bot_competition_weekly_reward_points") or BOT_COMPETITION_DEFAULT_REWARD_POINTS)
    except Exception:
        reward_points = BOT_COMPETITION_DEFAULT_REWARD_POINTS
    return {
        "enabled": safe.get("bot_competition_enabled", True) is not False,
        "weekly_reward_points": max(0, reward_points),
    }


def _display_symbol(service, symbol):
    renderer = getattr(service, "market_display_symbol", None)
    if callable(renderer):
        try:
            return renderer(symbol)
        except Exception:
            pass
    return str(symbol or "")


def _market_map(conn):
    return {
        row["symbol"]: {
            "price_points": float(row["manual_price_points"] or 0),
            "fee_rate_percent": float(row["fee_rate_percent"] or 0),
        }
        for row in conn.execute("SELECT symbol, manual_price_points, fee_rate_percent FROM trading_markets").fetchall()
    }


def _workflow_summary(workflow):
    if not isinstance(workflow, dict):
        return {"type": "legacy", "summary": "單條件策略"}
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    branches = workflow.get("branches") if isinstance(workflow.get("branches"), list) else []
    actions = [node for node in nodes if isinstance(node, dict) and node.get("type") == "action"]
    conditions = [node for node in nodes if isinstance(node, dict) and node.get("type") == "condition"]
    return {
        "type": "graph" if nodes else "branches" if branches else "workflow",
        "name": str(workflow.get("name") or workflow.get("strategy_kind") or ""),
        "nodes": len(nodes),
        "conditions": len(conditions),
        "actions": len(actions),
        "branches": len(branches),
    }


def _shared_parameters(row, *, category):
    if not bool(_row_get(row, "share_parameters", 0)):
        return None
    if category == "grid":
        return {
            "market_symbol": _row_get(row, "market_symbol"),
            "lower_price_points": _row_get(row, "lower_price_points"),
            "upper_price_points": _row_get(row, "upper_price_points"),
            "grid_count": _row_get(row, "grid_count"),
            "order_amount_points": _row_get(row, "order_amount_points"),
            "stop_loss_percent": _row_get(row, "stop_loss_percent"),
            "take_profit_percent": _row_get(row, "take_profit_percent"),
            "total_trades": _row_get(row, "total_trades"),
        }
    bot_type = str(_row_get(row, "bot_type") or "conditional")
    if bot_type == "dca":
        return {
            "market_symbol": _row_get(row, "market_symbol"),
            "interval_hours": _row_get(row, "interval_hours"),
            "budget_points": _row_get(row, "budget_points"),
            "max_runs": _row_get(row, "max_runs"),
            "stop_loss_percent": _row_get(row, "stop_loss_percent"),
            "take_profit_percent": _row_get(row, "take_profit_percent"),
        }
    return {
        "market_symbol": _row_get(row, "market_symbol"),
        "trigger_type": _row_get(row, "trigger_type"),
        "trigger_price_points": _row_get(row, "trigger_price_points"),
        "side": _row_get(row, "side"),
        "order_type": _row_get(row, "order_type"),
        "quantity_text": _row_get(row, "quantity_text"),
        "limit_price_points": _row_get(row, "limit_price_points"),
        "cooldown_seconds": _row_get(row, "cooldown_seconds"),
        "max_runs": _row_get(row, "max_runs"),
        "workflow_summary": _workflow_summary(_json_loads(_row_get(row, "workflow_json"), None)),
    }


def _bot_fills(conn, *, bot_id, start_at, end_at):
    return conn.execute(
        """
        SELECT f.*, o.order_uuid
        FROM trading_bot_runs r
        JOIN trading_orders o ON o.order_uuid = r.order_uuid
        JOIN trading_fills f ON f.order_id = o.id
        WHERE r.bot_id=? AND r.order_uuid IS NOT NULL
          AND f.created_at>=? AND f.created_at<?
        ORDER BY f.created_at ASC, f.id ASC
        """,
        (int(bot_id), start_at, end_at),
    ).fetchall()


def _grid_fills(conn, *, grid_bot_id, start_at, end_at):
    return conn.execute(
        """
        SELECT f.*, o.order_uuid
        FROM trading_grid_orders go
        JOIN trading_orders o ON o.order_uuid = go.trading_order_uuid
        JOIN trading_fills f ON f.order_id = o.id
        WHERE go.grid_bot_id=? AND go.trading_order_uuid IS NOT NULL
          AND f.created_at>=? AND f.created_at<?
        ORDER BY f.created_at ASC, f.id ASC
        """,
        (int(grid_bot_id), start_at, end_at),
    ).fetchall()


def _performance_from_fills(fills, *, current_price_points, fee_rate_percent):
    inventory_units = 0
    cost_basis = Decimal("0")
    buy_cost = Decimal("0")
    sell_notional = Decimal("0")
    realized = Decimal("0")
    order_uuids = set()

    for fill in fills:
        side = str(_row_get(fill, "side") or "").lower()
        quantity_units = int(_row_get(fill, "quantity_units", 0) or 0)
        notional = Decimal(str(int(_row_get(fill, "notional_points", 0) or 0)))
        fee = Decimal(str(int(_row_get(fill, "fee_points", 0) or 0)))
        order_uuid = _row_get(fill, "order_uuid")
        if order_uuid:
            order_uuids.add(order_uuid)
        if quantity_units <= 0:
            continue
        if side == "buy":
            total_cost = notional + fee
            inventory_units += quantity_units
            cost_basis += total_cost
            buy_cost += total_cost
            continue
        if side != "sell":
            continue
        sell_notional += notional
        net_credit = notional - fee
        if inventory_units <= 0 or cost_basis <= 0:
            realized -= fee
            continue
        matched_units = min(quantity_units, inventory_units)
        matched_ratio = Decimal(matched_units) / Decimal(quantity_units)
        cost_removed = cost_basis * Decimal(matched_units) / Decimal(inventory_units)
        realized += (net_credit * matched_ratio) - cost_removed
        if quantity_units > matched_units:
            unmatched_ratio = Decimal(quantity_units - matched_units) / Decimal(quantity_units)
            realized -= fee * unmatched_ratio
        inventory_units -= matched_units
        cost_basis -= cost_removed
        if inventory_units <= 0:
            inventory_units = 0
            cost_basis = Decimal("0")

    current_value = 0
    if inventory_units > 0 and current_price_points and current_price_points > 0:
        gross_value = notional_points(inventory_units, current_price_points)
        exit_fee = fee_points(gross_value, fee_rate_percent)
        current_value = max(0, gross_value - exit_fee)
    pnl = realized + Decimal(str(current_value)) - cost_basis
    principal = max(int(buy_cost), int(sell_notional), 0)
    performance = float((pnl / Decimal(principal)) * Decimal("100")) if principal > 0 else 0.0
    return {
        "fill_count": len(fills),
        "order_count": len(order_uuids),
        "principal_points": principal,
        "pnl_points": int(pnl.to_integral_value()),
        "performance_percent": round(performance, 6),
        "realized_pnl_points": int(realized.to_integral_value()),
        "current_value_points": int(current_value),
        "inventory_quantity_units": int(inventory_units),
        "inventory_quantity": units_to_quantity(int(inventory_units)),
        "eligible": len(fills) > 0 and principal > 0,
    }


def _leaderboard_for_trading_bots(service, conn, *, spec, start_at, end_at, markets):
    rows = conn.execute(
        """
        SELECT b.*, u.username
        FROM trading_bots b
        JOIN users u ON u.id = b.user_id
        WHERE b.bot_type=? AND COALESCE(u.status, 'active')='active'
        ORDER BY b.id ASC
        """,
        (spec["bot_type"],),
    ).fetchall()
    leaderboard = []
    for row in rows:
        symbol = str(row["market_symbol"] or "")
        market = markets.get(symbol, {})
        metrics = _performance_from_fills(
            _bot_fills(conn, bot_id=row["id"], start_at=start_at, end_at=end_at),
            current_price_points=float(market.get("price_points") or 0),
            fee_rate_percent=float(market.get("fee_rate_percent") or 0),
        )
        leaderboard.append({
            **metrics,
            "category": spec["category"],
            "category_label": spec["label"],
            "bot_kind": spec["bot_kind"],
            "bot_uuid": row["bot_uuid"],
            "bot_name": row["name"],
            "user_id": int(row["user_id"]),
            "username": row["username"],
            "market_symbol": symbol,
            "display_symbol": _display_symbol(service, symbol),
            "enabled": bool(row["enabled"]),
            "share_parameters": bool(_row_get(row, "share_parameters", 0)),
            "shared_parameters": _shared_parameters(row, category=spec["category"]),
        })
    return _rank_leaderboard(leaderboard)


def _leaderboard_for_grid_bots(service, conn, *, spec, start_at, end_at, markets):
    rows = conn.execute(
        """
        SELECT gb.*, u.username
        FROM trading_grid_bots gb
        JOIN users u ON u.id = gb.user_id
        WHERE COALESCE(u.status, 'active')='active'
        ORDER BY gb.id ASC
        """
    ).fetchall()
    leaderboard = []
    for row in rows:
        symbol = str(row["market_symbol"] or "")
        market = markets.get(symbol, {})
        metrics = _performance_from_fills(
            _grid_fills(conn, grid_bot_id=row["id"], start_at=start_at, end_at=end_at),
            current_price_points=float(market.get("price_points") or 0),
            fee_rate_percent=float(market.get("fee_rate_percent") or 0),
        )
        leaderboard.append({
            **metrics,
            "category": spec["category"],
            "category_label": spec["label"],
            "bot_kind": spec["bot_kind"],
            "bot_uuid": row["bot_uuid"],
            "bot_name": row["name"],
            "user_id": int(row["user_id"]),
            "username": row["username"],
            "market_symbol": symbol,
            "display_symbol": _display_symbol(service, symbol),
            "enabled": bool(row["enabled"]),
            "share_parameters": bool(_row_get(row, "share_parameters", 0)),
            "shared_parameters": _shared_parameters(row, category=spec["category"]),
        })
    return _rank_leaderboard(leaderboard)


def _rank_leaderboard(rows):
    rows.sort(
        key=lambda item: (
            0 if item.get("eligible") else 1,
            -float(item.get("performance_percent") or 0),
            -int(item.get("pnl_points") or 0),
            str(item.get("bot_name") or ""),
        )
    )
    rank = 0
    for item in rows:
        if item.get("eligible"):
            rank += 1
            item["rank"] = rank
        else:
            item["rank"] = None
    return rows


def _reward_rows(conn, week_key):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT r.*, u.username
            FROM trading_bot_competition_rewards r
            JOIN users u ON u.id = r.user_id
            WHERE r.week_key=?
            ORDER BY r.category ASC, r.rank ASC
            """,
            (week_key,),
        ).fetchall()
    ]


def get_bot_competition(service, *, actor=None, week=None, auto_award=True):
    requested_week = bool(week)
    week_key = bot_competition_week_key(str(week).strip()) if requested_week else bot_competition_week_key()
    previous_week = bot_competition_previous_week_key()
    start_at, end_at = bot_competition_week_bounds(week_key)
    auto_awarded = []
    if auto_award and not requested_week:
        auto_awarded = award_bot_competition_week(service, actor=None, week=previous_week, auto_award=True).get("awarded", [])

    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        settings = _competition_settings(service._settings_payload(conn))
        markets = _market_map(conn)
        categories = []
        for spec in BOT_COMPETITION_CATEGORIES:
            if spec["bot_kind"] == "grid_bot":
                leaderboard = _leaderboard_for_grid_bots(service, conn, spec=spec, start_at=start_at, end_at=end_at, markets=markets)
            else:
                leaderboard = _leaderboard_for_trading_bots(service, conn, spec=spec, start_at=start_at, end_at=end_at, markets=markets)
            categories.append({
                "category": spec["category"],
                "label": spec["label"],
                "bot_kind": spec["bot_kind"],
                "reward_points": settings["weekly_reward_points"],
                "leaderboard": leaderboard[:100],
                "winner": next((row for row in leaderboard if row.get("eligible")), None),
            })
        return {
            "ok": True,
            "week": week_key,
            "previous_week": previous_week,
            "starts_at": start_at,
            "ends_at": end_at,
            "settings": settings,
            "categories": categories,
            "rewards": _reward_rows(conn, week_key),
            "auto_awarded": auto_awarded,
        }
    finally:
        conn.close()


def award_bot_competition_week(service, *, actor=None, week=None, auto_award=False):
    week_key = bot_competition_week_key(str(week).strip()) if week else bot_competition_previous_week_key()
    competition = get_bot_competition(service, actor=actor, week=week_key, auto_award=False)
    settings = competition.get("settings") or {}
    if settings.get("enabled") is False:
        return {"ok": True, "week": week_key, "enabled": False, "awarded": []}
    reward_points = int(settings.get("weekly_reward_points") or 0)
    if reward_points <= 0:
        return {"ok": True, "week": week_key, "enabled": True, "awarded": []}

    awarded = []
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        for category in competition.get("categories") or []:
            winner = category.get("winner")
            if not winner or not winner.get("eligible"):
                continue
            category_key = str(category.get("category") or winner.get("category") or "")
            existing = conn.execute(
                "SELECT id FROM trading_bot_competition_rewards WHERE week_key=? AND category=?",
                (week_key, category_key),
            ).fetchone()
            if existing:
                continue
            conn.execute("BEGIN IMMEDIATE")
            now = _now_text()
            ledger = service._ledger(
                conn,
                user_id=int(winner["user_id"]),
                currency_type="points",
                direction="credit",
                amount=reward_points,
                action_type=BOT_COMPETITION_REWARD_ACTION,
                reference_type=BOT_COMPETITION_REWARD_REFERENCE,
                reference_id=f"{week_key}:{category_key}",
                idempotency_key=f"trading_bot_competition:{week_key}:{category_key}:{winner['user_id']}",
                reason=f"交易機器人週賽 {category.get('label') or category_key} 第 1 名獎勵",
                public_metadata={
                    "week": week_key,
                    "category": category_key,
                    "rank": 1,
                    "bot_uuid": winner["bot_uuid"],
                    "performance_percent": winner["performance_percent"],
                    "pnl_points": winner["pnl_points"],
                    "auto_award": bool(auto_award),
                },
                actor=actor,
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO trading_bot_competition_rewards (
                    week_key, category, bot_kind, bot_uuid, user_id, rank,
                    performance_percent, pnl_points, principal_points,
                    reward_points, ledger_uuid, awarded_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    week_key,
                    category_key,
                    winner["bot_kind"],
                    winner["bot_uuid"],
                    int(winner["user_id"]),
                    1,
                    float(winner["performance_percent"] or 0),
                    int(winner["pnl_points"] or 0),
                    int(winner["principal_points"] or 0),
                    reward_points,
                    ledger.get("ledger_uuid") if isinstance(ledger, dict) else None,
                    service._actor_id(actor) if actor else None,
                    now,
                ),
            )
            conn.commit()
            awarded.append({
                "week": week_key,
                "category": category_key,
                "category_label": category.get("label") or category_key,
                "user_id": int(winner["user_id"]),
                "username": winner["username"],
                "bot_uuid": winner["bot_uuid"],
                "bot_name": winner["bot_name"],
                "rank": 1,
                "performance_percent": winner["performance_percent"],
                "reward_points": reward_points,
            })
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"ok": True, "week": week_key, "enabled": True, "awarded": awarded}
