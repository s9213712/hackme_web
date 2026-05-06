import json
import math
import sqlite3
from pathlib import Path

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_DIR = ROOT / "workflows" / "system"


def _db(tmp_path):
    path = tmp_path / "workflow_templates_codex.db"

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
        "INSERT INTO users (username, role, status) VALUES ('alice', 'user', 'active'), ('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _trading(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    return TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: 100000)


def _actor():
    return {"id": 1, "username": "alice", "role": "user"}


def _smoke_candles():
    candles = []
    price = 1000.0
    for index in range(260):
        if index < 210:
            price += 1.6
        elif index < 225:
            price -= 9.5
        elif index < 240:
            price += 8.0
        else:
            price += math.sin(index / 3.0) * 3.0 - 1.2
        close = round(price, 2)
        candles.append(
            {
                "time": index,
                "time_iso": f"2024-01-{(index // 24) + 1:02d}T{(index % 24):02d}:00:00+00:00",
                "open_points": close,
                "high_points": round(close * 1.01, 2),
                "low_points": round(close * 0.99, 2),
                "close_points": close,
                "price_points": close,
            }
        )
    return candles


def test_codex_templates_are_unique_system_workflows():
    original_ids = {
        "dip_buy",
        "breakout_buy",
        "stop_loss",
        "rsi_scale",
        "ma_pullback",
        "bollinger_reversion",
        "kd_momentum",
        "risk_guard",
        "full_entry_exit",
        "staged_profit_taking",
        "ma200_trend_entry",
        "swing_bb_ma50",
    }
    paths = sorted(SYSTEM_DIR.glob("*_codex.json"))
    assert len(paths) >= 5
    ids = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["scope"] == "system"
        assert payload["id"].endswith("_codex")
        assert payload["id"] not in original_ids
        ids.append(payload["id"])
    assert len(ids) == len(set(ids))


def test_codex_templates_validate_and_smoke_backtest(tmp_path):
    trading = _trading(tmp_path)
    candles = _smoke_candles()
    for path in sorted(SYSTEM_DIR.glob("*_codex.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = trading._validate_workflow(payload["workflow"])
        assert validated["strategy_kind"] == "workflow_graph"
        assert validated["nodes"]
        assert validated["edges"]
        result = trading.backtest_trading_bot(
            actor=_actor(),
            payload={
                "market_symbol": "BTC/POINTS",
                "strategy": "workflow",
                "workflow_json": payload["workflow"],
                "initial_cash_points": 100000,
                "candles": candles,
            },
        )
        assert result["ok"] is True, path.name
        assert result["trade_count"] >= 0
        assert result["final_value_points"] >= 0
