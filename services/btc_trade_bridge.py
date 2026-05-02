import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


ASSET_SCALE = 100_000_000
DEFAULT_TIMEFRAME = "4h"
BTC_TRADE_TIMEFRAME_SECONDS = {"1h": 60 * 60, "4h": 4 * 60 * 60, "1d": 24 * 60 * 60}
BTC_TRADE_SIGNAL_KEYS = {
    "bar_ts",
    "generated_at",
    "strategy_version",
    "report_title",
    "signal_ok",
    "ml_ok",
    "position",
    "entry_price",
    "entry_atr",
    "current_price",
    "fear_greed",
    "capital",
    "btc",
    "total_equity",
    "total_pnl_pct",
    "hold_bars",
    "entry_checks",
    "ml_status",
    "report_text",
    "telegram_text",
    "timeframe",
}


def expand_server_path(raw_path):
    value = str(raw_path or "").strip()
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_btc_trade_time(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _btc_trade_next_prediction(signal, *, timeframe=DEFAULT_TIMEFRAME, fallback_updated_at=None):
    interval = BTC_TRADE_TIMEFRAME_SECONDS.get(str(timeframe or DEFAULT_TIMEFRAME).lower(), 4 * 60 * 60)
    base = (
        _parse_btc_trade_time(signal.get("bar_ts"))
        or _parse_btc_trade_time(signal.get("generated_at"))
        or _parse_btc_trade_time(fallback_updated_at)
    )
    if not base:
        return None
    now = datetime.now(timezone.utc)
    next_at = base + timedelta(seconds=interval)
    while next_at <= now:
        next_at += timedelta(seconds=interval)
    return {
        "next_prediction_at": next_at.isoformat(),
        "next_prediction_seconds": max(0, int((next_at - now).total_seconds())),
        "prediction_interval_seconds": interval,
    }


def _latest_jsonl_record(path):
    latest_line = ""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                latest_line = line.strip()
    if not latest_line:
        raise ValueError("empty report log")
    payload = json.loads(latest_line)
    if not isinstance(payload, dict):
        raise ValueError("latest report is not an object")
    return payload


def btc_trade_status(project_dir):
    root = expand_server_path(project_dir)
    if not root:
        return {
            "configured": False,
            "available": False,
            "needs_initialization": True,
            "message": "root 尚未設定 BTC_trade 專案資料夾",
        }
    runtime = root / "runtime"
    report_path = runtime / "report_log_4h.jsonl"
    portfolio_path = runtime / "portfolio_state_4h.json"
    trade_log_path = runtime / "trade_log_4h.json"
    checks = {
        "project_dir": root.is_dir(),
        "hourly_check": (root / "hourly_check.py").is_file(),
        "update_data": (root / "update_data.py").is_file(),
        "backtest_report": (root / "backtest_report.py").is_file(),
        "runtime_dir": runtime.is_dir(),
        "report_log": report_path.is_file(),
    }
    missing = [name for name, ok in checks.items() if not ok]
    payload = {
        "configured": True,
        "available": False,
        "needs_initialization": bool(missing),
        "checks": checks,
        "missing": missing,
        "message": "",
        "commands": [
            "python3 update_data.py",
            "python3 hourly_check.py --timeframe 4h",
            "python3 backtest_report.py --timeframe 4h",
        ],
    }
    if missing:
        payload["message"] = "BTC_trade 專案尚未可用，請先在該資料夾執行初始化或產生信號報告"
        return payload
    try:
        latest = _latest_jsonl_record(report_path)
    except Exception as exc:
        payload["needs_initialization"] = True
        payload["message"] = f"BTC_trade 信號報告無法讀取：{exc.__class__.__name__}"
        return payload
    signal = {key: latest.get(key) for key in BTC_TRADE_SIGNAL_KEYS if key in latest}
    timeframe = str(signal.get("timeframe") or DEFAULT_TIMEFRAME).lower()
    signal["timeframe"] = timeframe
    signal["source"] = "BTC_trade/runtime/report_log_4h.jsonl"
    try:
        stat = report_path.stat()
        signal["updated_at"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        signal["age_seconds"] = max(0, int(time.time() - stat.st_mtime))
    except Exception:
        pass
    if portfolio_path.is_file():
        try:
            portfolio = _load_json_file(portfolio_path)
            if isinstance(portfolio, dict):
                signal["portfolio"] = {
                    "position": portfolio.get("position"),
                    "capital": portfolio.get("capital"),
                    "cash": portfolio.get("cash", portfolio.get("capital")),
                    "btc": portfolio.get("btc"),
                    "entry_price": portfolio.get("entry_price"),
                    "total_equity": portfolio.get("total_equity"),
                    "updated_at": portfolio.get("updated_at") or portfolio.get("timestamp") or portfolio.get("last_bar_ts"),
                }
        except Exception:
            pass
    if trade_log_path.is_file():
        try:
            trades = _load_json_file(trade_log_path)
            if isinstance(trades, list) and trades:
                last_trade = trades[-1] if isinstance(trades[-1], dict) else {}
                signal["last_trade"] = {
                    "action": last_trade.get("action"),
                    "timestamp": last_trade.get("timestamp"),
                    "pnl_pct": last_trade.get("pnl_pct"),
                    "exit_reason": last_trade.get("exit_reason") or last_trade.get("reason"),
                    "strategy_version": last_trade.get("strategy_version"),
                    "batch": last_trade.get("batch"),
                }
        except Exception:
            pass
    next_prediction = _btc_trade_next_prediction(signal, timeframe=timeframe, fallback_updated_at=signal.get("updated_at"))
    if next_prediction:
        signal.update(next_prediction)
    payload["available"] = True
    payload["needs_initialization"] = False
    payload["message"] = "BTC_trade 信號可用"
    payload["signal"] = signal
    return payload


def btc_to_units(btc_amount):
    return int(float(btc_amount) * ASSET_SCALE)


def units_to_btc(units):
    return int(units or 0) / ASSET_SCALE


def units_to_btc_str(units):
    return f"{units_to_btc(units):.8f}"


class BtcTradeBridge:
    def __init__(
        self,
        *,
        hackme_dir,
        btc_trade_dir,
        bridge_username="btc_bridge",
        market_symbol="BTC/USDT",
        quantity_scale=1.0,
        min_btc_quantity=0.000001,
        db_path=None,
        chain_seed_path=None,
        state_path=None,
    ):
        self.hackme_dir = expand_server_path(hackme_dir) or Path.cwd()
        self.btc_trade_dir = expand_server_path(btc_trade_dir)
        self.bridge_username = str(bridge_username or "btc_bridge")
        self.market_symbol = str(market_symbol or "BTC/USDT").strip().upper()
        self.quantity_scale = float(quantity_scale or 0)
        self.min_btc_quantity = float(min_btc_quantity or 0)
        self.db_path = Path(db_path) if db_path else self.hackme_dir / "database" / "database.db"
        self.chain_seed_path = Path(chain_seed_path) if chain_seed_path else self.hackme_dir / ".chain_seed"
        runtime = self.btc_trade_dir / "runtime" if self.btc_trade_dir else Path("runtime")
        self.trade_log_path = runtime / "trade_log_4h.json"
        self.state_path = Path(state_path) if state_path else runtime / "bridge_state.json"

    def status(self):
        return btc_trade_status(self.btc_trade_dir)

    def load_state(self):
        if not self.state_path.exists():
            return {
                "last_trade_count": 0,
                "open_quantity_units": 0,
                "open_entry_trade_idx": None,
                "total_buy_orders": 0,
                "total_sell_orders": 0,
                "last_run_at": None,
            }
        return _load_json_file(self.state_path)

    def save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = self.state_path.with_name(f"{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    def get_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _chain_seed(self):
        with open(self.chain_seed_path, encoding="utf-8") as fh:
            return fh.read().strip()

    def init_services(self):
        hackme_dir = str(self.hackme_dir)
        if hackme_dir not in sys.path:
            sys.path.insert(0, hackme_dir)
        from services.points_chain import PointsLedgerService
        from services.trading_engine import TradingEngineService

        points_service = PointsLedgerService(
            get_db=self.get_db,
            chain_secret=self._chain_seed(),
            backup_dir=self.hackme_dir / "database" / "points_chain_backups",
        )
        return TradingEngineService(get_db=self.get_db, points_service=points_service)

    def bridge_actor(self):
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT id, username, role FROM users WHERE username=?",
                (self.bridge_username,),
            ).fetchone()
            if not row:
                return None
            return {"id": int(row["id"]), "username": row["username"], "role": row["role"]}
        finally:
            conn.close()

    def spot_position_units(self, user_id):
        conn = self.get_db()
        try:
            row = conn.execute(
                "SELECT quantity_units FROM trading_spot_positions WHERE user_id=? AND market_symbol=?",
                (int(user_id), self.market_symbol),
            ).fetchone()
            return int(row["quantity_units"]) if row else 0
        finally:
            conn.close()

    def _load_trades(self):
        if not self.trade_log_path.exists():
            raise FileNotFoundError(f"BTC_trade trade log not found: {self.trade_log_path}")
        trades = _load_json_file(self.trade_log_path)
        if not isinstance(trades, list):
            raise ValueError("BTC_trade trade log must be a list")
        return trades

    def run(self, *, dry_run=False):
        trades = self._load_trades()
        state = self.load_state()
        last_count = int(state.get("last_trade_count", 0) or 0)
        new_trades = trades[last_count:]
        result = {
            "ok": True,
            "dry_run": bool(dry_run),
            "processed_from": last_count,
            "trade_count": len(trades),
            "new_count": len(new_trades),
            "orders": [],
            "skipped": [],
            "errors": [],
        }
        if not new_trades:
            if not dry_run:
                self.save_state(state)
            return result

        actor = {"id": 0, "username": self.bridge_username, "role": "user"} if dry_run else self.bridge_actor()
        if not actor:
            result["ok"] = False
            result["errors"].append(f"bridge account not found: {self.bridge_username}")
            return result
        trading_service = None if dry_run else self.init_services()
        open_units = int(state.get("open_quantity_units", 0) or 0)

        for offset, trade in enumerate(new_trades):
            trade_idx = last_count + offset
            if not isinstance(trade, dict):
                result["skipped"].append({"idx": trade_idx, "reason": "trade row is not an object"})
                continue
            action = str(trade.get("action") or "").upper()
            if action == "ENTRY":
                raw_btc = float(trade.get("btc") or 0)
                scaled_btc = raw_btc * self.quantity_scale
                if scaled_btc < self.min_btc_quantity:
                    result["skipped"].append({"idx": trade_idx, "action": action, "reason": "quantity below minimum", "btc": scaled_btc})
                    continue
                quantity = f"{scaled_btc:.8f}"
                quantity_units = btc_to_units(scaled_btc)
                if dry_run:
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "buy", "quantity": quantity, "dry_run": True})
                    continue
                try:
                    order_result = trading_service.place_order(
                        actor=actor,
                        market_symbol=self.market_symbol,
                        side="buy",
                        order_type="market",
                        quantity=quantity,
                    )
                    open_units += quantity_units
                    state["open_quantity_units"] = open_units
                    state["open_entry_trade_idx"] = trade_idx
                    state["total_buy_orders"] = int(state.get("total_buy_orders", 0) or 0) + 1
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "buy", "quantity": quantity, "order": order_result.get("order")})
                except Exception as exc:
                    result["ok"] = False
                    result["errors"].append({"idx": trade_idx, "action": action, "error": str(exc)})
            elif action == "PARTIAL_EXIT":
                actual_units = self.spot_position_units(actor["id"]) if not dry_run else max(0, open_units)
                if actual_units <= 0:
                    result["skipped"].append({"idx": trade_idx, "action": action, "reason": "no hackme spot position"})
                    continue
                sell_units = max(1, actual_units // 3)
                quantity = units_to_btc_str(sell_units)
                if dry_run:
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "sell", "quantity": quantity, "dry_run": True})
                    continue
                try:
                    order_result = trading_service.place_order(
                        actor=actor,
                        market_symbol=self.market_symbol,
                        side="sell",
                        order_type="market",
                        quantity=quantity,
                    )
                    open_units = max(0, open_units - sell_units)
                    state["open_quantity_units"] = open_units
                    state["total_sell_orders"] = int(state.get("total_sell_orders", 0) or 0) + 1
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "sell", "quantity": quantity, "order": order_result.get("order")})
                except Exception as exc:
                    result["ok"] = False
                    result["errors"].append({"idx": trade_idx, "action": action, "error": str(exc)})
            elif action == "FULL_EXIT":
                actual_units = self.spot_position_units(actor["id"]) if not dry_run else max(0, open_units)
                if actual_units <= 0:
                    open_units = 0
                    state["open_quantity_units"] = 0
                    state["open_entry_trade_idx"] = None
                    result["skipped"].append({"idx": trade_idx, "action": action, "reason": "no hackme spot position"})
                    continue
                quantity = units_to_btc_str(actual_units)
                if dry_run:
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "sell", "quantity": quantity, "dry_run": True})
                    continue
                try:
                    order_result = trading_service.place_order(
                        actor=actor,
                        market_symbol=self.market_symbol,
                        side="sell",
                        order_type="market",
                        quantity=quantity,
                    )
                    open_units = 0
                    state["open_quantity_units"] = 0
                    state["open_entry_trade_idx"] = None
                    state["total_sell_orders"] = int(state.get("total_sell_orders", 0) or 0) + 1
                    result["orders"].append({"idx": trade_idx, "action": action, "side": "sell", "quantity": quantity, "order": order_result.get("order")})
                except Exception as exc:
                    result["ok"] = False
                    result["errors"].append({"idx": trade_idx, "action": action, "error": str(exc)})
            else:
                result["skipped"].append({"idx": trade_idx, "action": action, "reason": "unknown trade action"})

        if result["ok"] and not dry_run:
            state["last_trade_count"] = len(trades)
        if not dry_run:
            self.save_state(state)
        result["state"] = state
        return result
