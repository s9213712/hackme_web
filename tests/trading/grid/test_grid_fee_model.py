import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading.trading_engine import TradingEngineService, ensure_trading_schema


ROOT = Path(__file__).resolve().parents[3]


def _db(tmp_path):
    path = tmp_path / "grid_fee_model.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES "
        "('alice', 'user', 'active'), "
        "('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _services(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    prices = {"BTC/POINTS": 77059, "ETH/POINTS": 5000}
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: prices[symbol])
    trading.test_prices = prices
    return points, trading


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


def test_grid_preview_calculates_gross_fee_net_and_break_even_with_decimal_math(tmp_path):
    _, trading = _services(tmp_path)

    preview = trading.preview_grid_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 100,
            "upper_price_points": 101,
            "grid_count": 2,
            "order_amount_points": 10000,
            "spacing_mode": "arithmetic",
            "order_mode": "maker",
        },
    )

    buy_fee_rate = Decimal("0.00075")
    sell_fee_rate = Decimal("0.00075")
    gross_profit = Decimal("100")
    buy_fee = Decimal("10000") * buy_fee_rate
    sell_fee = Decimal("10100") * sell_fee_rate
    total_fee = buy_fee + sell_fee
    net_profit = gross_profit - total_fee
    break_even = ((Decimal("1") + buy_fee_rate) / (Decimal("1") - sell_fee_rate) - Decimal("1")) * Decimal("100")

    assert preview["fee_model"]["spot_fee_percent"] == "0.1"
    assert preview["fee_model"]["grid_discount_percent"] == "25"
    assert preview["fee_model"]["buy_fee_percent"] == "0.075"
    assert preview["fee_model"]["sell_fee_percent"] == "0.075"
    assert preview["fee_model"]["round_trip_fee_percent"] == "0.15"
    assert Decimal(preview["break_even"]["min_spread_percent"]) == break_even.quantize(Decimal("0.0001"))
    assert Decimal(preview["grid_profit"]["estimated_gross_profit_per_grid"]) == gross_profit
    assert Decimal(preview["grid_profit"]["estimated_fee_per_grid"]) == total_fee.quantize(Decimal("0.00000001"))
    assert Decimal(preview["grid_profit"]["estimated_net_profit_per_grid"]) == net_profit.quantize(Decimal("0.00000001"))
    assert Decimal(preview["grid_profit"]["estimated_net_spread_percent"]) == Decimal("0.8493")
    assert preview["risk"]["status"] == "green"


def test_grid_preview_sets_red_and_yellow_risk_states_and_requires_confirmation(tmp_path):
    _, trading = _services(tmp_path)

    red_preview = trading.preview_grid_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 100000,
            "upper_price_points": 100100,
            "grid_count": 2,
            "order_amount_points": 10000,
        },
    )
    yellow_preview = trading.preview_grid_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 100000,
            "upper_price_points": 100200,
            "grid_count": 2,
            "order_amount_points": 10000,
        },
    )

    assert red_preview["risk"]["status"] == "red"
    assert red_preview["risk"]["blocked"] is True
    assert "損益兩平至少需要" in red_preview["risk"]["message"]
    assert yellow_preview["risk"]["status"] == "yellow"
    assert yellow_preview["risk"]["requires_confirmation"] is True
    assert "利潤過薄" in yellow_preview["risk"]["message"]

    with pytest.raises(ValueError, match="利潤過薄"):
        trading.create_grid_bot(
            actor=_actor(),
            payload={
                "name": "thin-profit-grid",
                "market_symbol": "ETH/POINTS",
                "lower_price_points": 100000,
                "upper_price_points": 100200,
                "grid_count": 2,
                "order_amount_points": 10000,
            },
        )


def test_grid_preview_blocks_when_amount_cannot_buy_minimum_unit(tmp_path):
    _, trading = _services(tmp_path)

    preview = trading.preview_grid_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 1_000_000_000,
            "upper_price_points": 1_100_000_000,
            "grid_count": 2,
            "order_amount_points": 1,
        },
    )

    assert preview["risk"]["status"] == "red"
    assert preview["risk"]["blocked"] is True
    assert "最小單位" in preview["risk"]["message"]
