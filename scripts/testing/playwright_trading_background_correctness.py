#!/usr/bin/env python3
"""Playwright-backed trading background-engine correctness probe.

This script targets an isolated hackme_web dev/test runtime. It drives setup
through browser sessions, closes those sessions, then verifies that server-side
background jobs continue to match orders, trigger TP/SL, run bots, accrue
interest, and liquidate margin positions without any active browser page.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER_PASSWORD = "TradeQa123!"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Recorder:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.checks.append(Check(name=name, ok=bool(ok), detail=detail, data=data))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    def require(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.add(name, ok, detail, **data)
        if not ok:
            raise RuntimeError(f"{name}: {detail}")

    @property
    def failures(self) -> list[Check]:
        return [row for row in self.checks if not row.ok]


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def taiwan_id_number(index: int) -> str:
    letter_code = 10
    digits = [1, 2, 3, 4, 5, (index // 100) % 10, (index // 10) % 10, index % 10]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    total = (letter_code // 10) * weights[0] + (letter_code % 10) * weights[1]
    for digit, weight in zip(digits, weights[2:10]):
        total += digit * weight
    check = (10 - (total % 10)) % 10
    return "A" + "".join(str(digit) for digit in digits) + str(check)


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def db_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    conn = connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def db_all(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def db_exec(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> None:
    conn = connect(db_path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def db_exec_many(db_path: Path, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
    conn = connect(db_path)
    try:
        for sql, params in statements:
            conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def api(page, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({method, path, body}) => {
          const csrfRes = await fetch('/api/csrf-token', {credentials: 'same-origin'});
          const csrfJson = await csrfRes.json().catch(() => ({}));
          const token = csrfJson.csrf_token || '';
          const headers = {'X-CSRF-Token': token};
          const options = {method, credentials: 'same-origin', headers};
          if (body !== null && body !== undefined) {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
          }
          const res = await fetch('/api' + path, options);
          const text = await res.text();
          let parsed = null;
          try { parsed = JSON.parse(text); } catch (_) { parsed = {raw: text}; }
          return {status: res.status, ok: res.ok, body: parsed, text};
        }
        """,
        {"method": method.upper(), "path": path, "body": body},
    )


def login(page, base_url: str, username: str, password: str) -> dict[str, Any]:
    page.goto(base_url + "/api/version", wait_until="domcontentloaded")
    res = api(page, "POST", "/login", {"username": username, "password": password})
    page.goto(base_url + "/api/version", wait_until="domcontentloaded")
    return res


def assert_api_ok(rec: Recorder, name: str, res: dict[str, Any], *, statuses={200}, body_ok: bool | None = True) -> None:
    payload = res.get("body") if isinstance(res.get("body"), dict) else {}
    ok = int(res.get("status") or 0) in set(statuses)
    if body_ok is True:
        ok = ok and payload.get("ok") is True
    elif body_ok is False:
        ok = ok and payload.get("ok") is not True
    rec.require(name, ok, f"status={res.get('status')} body={json.dumps(payload, ensure_ascii=False)[:240]}")


def create_user(page, username: str, index: int, *, password: str = DEFAULT_USER_PASSWORD) -> int:
    payload = {
        "username": username,
        "password": password,
        "password_confirm": password,
        "nickname": username,
        "real_name": f"Trading QA {index}",
        "id_number": taiwan_id_number(700 + index),
        "birthdate": "2000-01-01",
        "phone": f"09{index:08d}",
        "role": "user",
        "status": "active",
        "member_level": "trusted",
    }
    created = api(page, "POST", "/admin/users", payload)
    if int(created["status"]) not in {200, 409}:
        raise RuntimeError(f"create user failed {username}: {created}")
    users = api(page, "GET", "/admin/users")
    for row in users.get("body", {}).get("users", []):
        if row.get("username") == username:
            return int(row["id"])
    raise RuntimeError(f"created user not listed: {username}")


def direct_prepare_market(db_path: Path, *, price: int) -> None:
    now = utc_now()
    statements: list[tuple[str, tuple[Any, ...]]] = [
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.price_source", "manual_root", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.borrowing_enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.margin_liquidation_enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.bot_auto_scan_enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.bot_audit_enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.borrow_interest_percent_daily", "24", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.borrow_interest_interval_hours", "1", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.borrow_interest_minimum_hours", "1", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.background_worker_dev_ready_enabled", "true", now, 0),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("trading.qa_live_price_provider_enabled", "true", now, 0),
        ),
        (
            "UPDATE trading_markets SET manual_price_points=?, price_source='manual_root', max_price_jump_percent=1000, fee_rate_percent=0.3, min_order_points=1, max_order_points=1000000, enabled=1, spot_enabled=1, live_price_confirmed_at=COALESCE(live_price_confirmed_at, ?), updated_at=? WHERE symbol='ETH/POINTS'",
            (int(price), now, now),
        ),
        (
            "UPDATE trading_markets SET manual_price_points=?, price_source='manual_root', max_price_jump_percent=1000, fee_rate_percent=0.3, min_order_points=1, max_order_points=1000000, enabled=1, spot_enabled=1, live_price_confirmed_at=COALESCE(live_price_confirmed_at, ?), updated_at=? WHERE symbol='BTC/POINTS'",
            (int(price) * 10, now, now),
        ),
        (
            "UPDATE trading_markets_registry SET enabled=1, allow_margin=1, allow_bots=1, allow_risk_grade_usage=1, live_price_enabled=1, reference_price_enabled=1, updated_at=? WHERE symbol IN ('ETH/POINTS', 'BTC/POINTS')",
            (now,),
        ),
    ]
    db_exec_many(db_path, statements)


def set_price_and_due_jobs(db_path: Path, price: int, job_keys: list[str], *, risk_grade: bool = False) -> None:
    now = utc_now()
    price_source = "binance_public_api" if risk_grade else "manual_root"
    statements = [
        (
            "UPDATE trading_markets SET manual_price_points=?, price_source=?, updated_at=?, live_price_confirmed_at=COALESCE(live_price_confirmed_at, ?) WHERE symbol='ETH/POINTS'",
            (int(price), price_source, now, now),
        ),
        (
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES ('trading.price_source', ?, ?, 0)",
            (price_source, now),
        ),
    ]
    for key in job_keys:
        statements.append(
            (
                "UPDATE trading_background_jobs SET enabled=1, interval_seconds=1, next_run_at=NULL, lease_until=NULL, lease_owner=NULL, updated_at=? WHERE job_key=?",
                (now, key),
            )
        )
    db_exec_many(db_path, statements)


def configure_background_jobs(db_path: Path, *, enabled: bool) -> None:
    now = utc_now()
    db_exec(
        db_path,
        "UPDATE trading_background_jobs SET enabled=?, interval_seconds=1, next_run_at=NULL, lease_until=NULL, lease_owner=NULL, updated_at=?",
        (1 if enabled else 0, now),
    )


def deplete_trial_credits(db_path: Path, user_ids: list[int]) -> None:
    now = utc_now()
    statements = []
    for user_id in user_ids:
        statements.append(
            (
                """
                INSERT OR REPLACE INTO trading_trial_credits (
                    user_id, initial_points, available_points, locked_points, deployed_points,
                    status, activated_at, expires_at, updated_at
                ) VALUES (?, 0, 0, 0, 0, 'depleted', ?, ?, ?)
                """,
                (int(user_id), now, now, now),
            )
        )
    db_exec_many(db_path, statements)


def wait_until(rec: Recorder, name: str, predicate, *, timeout: float = 15.0, interval: float = 0.25) -> Any:
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            rec.add(name, True, str(last_value)[:260])
            return last_value
        time.sleep(interval)
    rec.add(name, False, f"timeout after {timeout}s last={last_value}")
    raise RuntimeError(name)


def user_page(browser, base_url: str, username: str, password: str):
    ctx = browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    res = login(page, base_url, username, password)
    if int(res["status"]) != 200 or res.get("body", {}).get("ok") is not True:
        ctx.close()
        raise RuntimeError(f"login failed for {username}: {res}")
    return ctx, page


def run_stress_burst(page, count: int) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        async ({count}) => {
          async function one(i) {
            const csrfRes = await fetch('/api/csrf-token', {credentials: 'same-origin'});
            const csrfJson = await csrfRes.json().catch(() => ({}));
            const res = await fetch('/api/trading/orders', {
              method: 'POST',
              credentials: 'same-origin',
              headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfJson.csrf_token || ''},
              body: JSON.stringify({
                market_symbol: 'ETH/POINTS',
                side: 'buy',
                order_type: 'market',
                quantity: '0.01'
              })
            });
            const text = await res.text();
            let body = {};
            try { body = JSON.parse(text); } catch (_) { body = {raw: text}; }
            return {index: i, status: res.status, ok: body.ok === true, body};
          }
          return Promise.all(Array.from({length: count}, (_, i) => one(i)));
        }
        """,
        {"count": int(count)},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Playwright trading background correctness QA")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--root-password", default="root")
    parser.add_argument("--user-password", default=DEFAULT_USER_PASSWORD)
    parser.add_argument("--out", default="")
    parser.add_argument("--stress-orders", type=int, default=30)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    db_path = runtime_dir / "database" / "database.db"
    out_dir = Path(args.out).expanduser().resolve() if args.out else runtime_dir / "reports" / "qa" / f"trading_background_{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rec = Recorder()
    scenario: dict[str, Any] = {"db_path": str(db_path), "base_url": base_url, "users": {}}
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        root_ctx = browser.new_context(ignore_https_errors=True)
        root_page = root_ctx.new_page()
        root_login = login(root_page, base_url, "root", args.root_password)
        assert_api_ok(rec, "root login", root_login)
        assert_api_ok(
            rec,
            "enable feature flags",
            api(
                root_page,
                "PUT",
                "/admin/features",
                {
                    "feature_economy_enabled": True,
                    "feature_trading_enabled": True,
                    "feature_reports_notifications_enabled": True,
                },
            ),
        )
        assert_api_ok(rec, "background status API initializes schema", api(root_page, "GET", "/root/trading/background/status?limit=20"))
        configure_background_jobs(db_path, enabled=False)
        direct_prepare_market(db_path, price=100)
        rec.add("direct deterministic market setup", True, "ETH/POINTS manual test price=100 with background jobs paused")

        prefix = f"qa_bg_{int(time.time())}_"
        users = {
            "spot_sl": f"{prefix}spot_sl",
            "spot_tp": f"{prefix}spot_tp",
            "limit": f"{prefix}limit",
            "margin_liq": f"{prefix}margin_liq",
            "margin_tp": f"{prefix}margin_tp",
            "margin_interest": f"{prefix}margin_interest",
            "bot": f"{prefix}bot",
            "stress_a": f"{prefix}stress_a",
            "stress_b": f"{prefix}stress_b",
        }
        user_ids: dict[str, int] = {}
        for index, (role, username) in enumerate(users.items(), start=1):
            user_id = create_user(root_page, username, index, password=args.user_password)
            user_ids[role] = user_id
            seed_points = 60 if role == "margin_liq" else 50000
            assert_api_ok(
                rec,
                f"fund {role}",
                api(
                    root_page,
                    "POST",
                    "/admin/points/adjust",
                    {
                        "user_id": user_id,
                        "currency_type": "points",
                        "direction": "credit",
                        "amount": seed_points,
                        "reason": "playwright trading background QA seed",
                    },
                ),
            )
        scenario["users"] = {role: {"username": users[role], "id": user_ids[role]} for role in users}
        deplete_trial_credits(db_path, list(user_ids.values()))
        rec.add("trial credits depleted for deterministic PointsChain funding", True, f"users={len(user_ids)}")

        root_report_before = api(root_page, "GET", "/admin/trading/report")
        assert_api_ok(rec, "root trading report before scenario", root_report_before)
        reserve_before = int(((root_report_before["body"].get("report") or {}).get("reserve_pool") or {}).get("balance_points") or 0)
        scenario["reserve_before"] = reserve_before

        contexts = [root_ctx]
        pages: dict[str, Any] = {}
        for role, username in users.items():
            ctx, page = user_page(browser, base_url, username, args.user_password)
            contexts.append(ctx)
            pages[role] = page

        # Browser/UI sanity for member trading surface before closing sessions.
        pages["spot_sl"].goto(base_url + "/", wait_until="domcontentloaded")
        pages["spot_sl"].wait_for_function(
            "() => !!document.querySelector('#trading-order-form') && !!document.querySelector('#trading-submit-order-btn')",
            timeout=5000,
        )
        ui_state = pages["spot_sl"].evaluate(
            """
            () => {
              if (typeof window.switchModuleTab === 'function') window.switchModuleTab('trading');
              else document.querySelector('#tab-module-trading')?.click();
              const form = document.querySelector('#trading-order-form');
              const submit = document.querySelector('#trading-submit-order-btn');
              const module = document.querySelector('#module-trading');
              return {
                form_present: !!form,
                submit_present: !!submit,
                module_present: !!module,
                module_active: !!module?.classList?.contains('active'),
              };
            }
            """
        )
        rec.require(
            "member trading UI loaded",
            bool(ui_state.get("form_present") and ui_state.get("submit_present") and ui_state.get("module_present")),
            json.dumps(ui_state, ensure_ascii=False),
        )

        orders: dict[str, Any] = {}
        orders["spot_sl_buy"] = api(
            pages["spot_sl"],
            "POST",
            "/trading/orders",
            {"market_symbol": "ETH/POINTS", "side": "buy", "order_type": "market", "quantity": "10", "stop_loss_percent": 5, "take_profit_percent": 20},
        )
        assert_api_ok(rec, "spot stop-loss seed buy", orders["spot_sl_buy"])
        orders["spot_tp_buy"] = api(
            pages["spot_tp"],
            "POST",
            "/trading/orders",
            {"market_symbol": "ETH/POINTS", "side": "buy", "order_type": "market", "quantity": "10", "stop_loss_percent": 20, "take_profit_percent": 5},
        )
        assert_api_ok(rec, "spot take-profit seed buy", orders["spot_tp_buy"])
        orders["limit_buy"] = api(
            pages["limit"],
            "POST",
            "/trading/orders",
            {"market_symbol": "ETH/POINTS", "side": "buy", "order_type": "limit", "quantity": "5", "limit_price_points": 92},
        )
        assert_api_ok(rec, "limit order seed", orders["limit_buy"])
        orders["margin_liq_open"] = api(
            pages["margin_liq"],
            "POST",
            "/trading/margin/open",
            {"market_symbol": "ETH/POINTS", "position_type": "margin_long", "quantity": "1", "collateral_points": 50, "idempotency_key": f"{prefix}margin_liq"},
        )
        assert_api_ok(rec, "margin liquidation seed open", orders["margin_liq_open"])
        orders["margin_tp_open"] = api(
            pages["margin_tp"],
            "POST",
            "/trading/margin/open",
            {"market_symbol": "ETH/POINTS", "position_type": "margin_long", "quantity": "1", "collateral_points": 50, "take_profit_percent": 5, "idempotency_key": f"{prefix}margin_tp"},
        )
        assert_api_ok(rec, "margin take-profit seed open", orders["margin_tp_open"])
        orders["margin_interest_open"] = api(
            pages["margin_interest"],
            "POST",
            "/trading/margin/open",
            {"market_symbol": "ETH/POINTS", "position_type": "margin_long", "quantity": "1", "collateral_points": 90, "idempotency_key": f"{prefix}margin_interest"},
        )
        assert_api_ok(rec, "margin interest seed open", orders["margin_interest_open"])
        interest_uuid = (orders["margin_interest_open"]["body"].get("position") or {}).get("position_uuid")
        opened_at = (datetime.utcnow().replace(microsecond=0) - timedelta(hours=3, minutes=2)).isoformat()
        db_exec(
            db_path,
            "UPDATE trading_margin_positions SET opened_at=?, interest_accrued_hours=0, interest_points=0, interest_paid_points=0, interest_carry_micropoints=0 WHERE position_uuid=?",
            (opened_at, interest_uuid),
        )
        bot_create = api(
            pages["bot"],
            "POST",
            "/trading/bots",
            {
                "bot_type": "conditional",
                "name": f"{prefix}conditional",
                "market_symbol": "ETH/POINTS",
                "side": "buy",
                "order_type": "market",
                "quantity": "1",
                "trigger_type": "always",
                "trigger_price_points": 0,
                "max_runs": 1,
                "cooldown_seconds": 0,
            },
        )
        assert_api_ok(rec, "conditional bot seed", bot_create)
        scenario["uuids"] = {
            "limit_order": (orders["limit_buy"]["body"].get("order") or {}).get("order_uuid"),
            "margin_liq": (orders["margin_liq_open"]["body"].get("position") or {}).get("position_uuid"),
            "margin_tp": (orders["margin_tp_open"]["body"].get("position") or {}).get("position_uuid"),
            "margin_interest": interest_uuid,
            "bot": (bot_create["body"].get("bot") or {}).get("bot_uuid"),
        }

        for ctx in contexts:
            ctx.close()
        rec.add("all setup browser sessions closed before background trigger", True, "no active Playwright browser context remains")

        # Stage 1: no login/browser. Price drop should match limit order,
        # trigger spot stop-loss, and trigger the conditional bot.
        set_price_and_due_jobs(db_path, 91, ["price_refresh", "order_matching", "take_profit_stop_loss_scan", "bot_trigger_scan", "interest_accrual"])
        wait_until(
            rec,
            "background matched limit order without active login",
            lambda: db_one(db_path, "SELECT status FROM trading_orders WHERE order_uuid=?", (scenario["uuids"]["limit_order"],))["status"] == "filled",
            timeout=20,
        )
        wait_until(
            rec,
            "background triggered spot stop-loss without active login",
            lambda: int(db_one(db_path, "SELECT quantity_units FROM trading_spot_positions WHERE user_id=? AND market_symbol='ETH/POINTS'", (user_ids["spot_sl"],))["quantity_units"] or 0) == 0,
            timeout=20,
        )
        wait_until(
            rec,
            "background triggered conditional bot without active login",
            lambda: int(
                db_one(
                    db_path,
                    """
                    SELECT COUNT(*) AS c
                    FROM trading_bot_runs r
                    JOIN trading_bots b ON b.id=r.bot_id
                    WHERE b.bot_uuid=? AND r.status='triggered' AND COALESCE(r.order_uuid, '')<>''
                    """,
                    (scenario["uuids"]["bot"],),
                )["c"]
                or 0
            )
            >= 1,
            timeout=20,
        )
        wait_until(
            rec,
            "background accrued margin interest without active login",
            lambda: int(db_one(db_path, "SELECT interest_accrued_hours FROM trading_margin_positions WHERE position_uuid=?", (interest_uuid,))["interest_accrued_hours"] or 0) >= 3,
            timeout=20,
        )

        # Stage 2: no login/browser. Price rebound should trigger spot TP and margin TP.
        set_price_and_due_jobs(db_path, 106, ["price_refresh", "take_profit_stop_loss_scan"])
        wait_until(
            rec,
            "background triggered spot take-profit without active login",
            lambda: int(db_one(db_path, "SELECT quantity_units FROM trading_spot_positions WHERE user_id=? AND market_symbol='ETH/POINTS'", (user_ids["spot_tp"],))["quantity_units"] or 0) == 0,
            timeout=20,
        )
        wait_until(
            rec,
            "background triggered margin take-profit without active login",
            lambda: db_one(db_path, "SELECT status FROM trading_margin_positions WHERE position_uuid=?", (scenario["uuids"]["margin_tp"],))["status"] == "closed",
            timeout=20,
        )

        # Stage 3: no login/browser. Crash price should liquidate the weak margin account.
        set_price_and_due_jobs(db_path, 30, ["price_refresh", "margin_liquidation_scan"], risk_grade=True)
        wait_until(
            rec,
            "background liquidated margin account without active login",
            lambda: db_one(db_path, "SELECT status FROM trading_margin_positions WHERE position_uuid=?", (scenario["uuids"]["margin_liq"],))["status"] == "liquidated",
            timeout=20,
        )

        # Re-login only after the no-browser background checks completed, then
        # inspect root UI/API and run a Playwright-driven stress burst.
        root_ctx2 = browser.new_context(ignore_https_errors=True)
        root_page2 = root_ctx2.new_page()
        assert_api_ok(rec, "root re-login after background run", login(root_page2, base_url, "root", args.root_password))
        root_page2.goto(base_url + "/", wait_until="domcontentloaded")
        root_page2.evaluate("() => { document.querySelector('#tab-module-settings')?.click(); document.querySelector('#tab-settings-trading')?.click(); }")
        root_page2.wait_for_selector("#root-trading-background-panel", state="attached", timeout=5000)
        root_ui_state = root_page2.evaluate(
            """
            () => ({
              panel: !!document.querySelector('#root-trading-background-panel'),
              summary: !!document.querySelector('#root-trading-background-summary'),
              jobs: !!document.querySelector('#root-trading-background-jobs'),
              runs: !!document.querySelector('#root-trading-background-runs'),
            })
            """
        )
        rec.require(
            "root background UI panel wired",
            all(root_ui_state.values()),
            json.dumps(root_ui_state, ensure_ascii=False),
        )
        bg_status = api(root_page2, "GET", "/root/trading/background/status?limit=30")
        assert_api_ok(rec, "root background status API after no-login jobs", bg_status)
        bg_jobs = bg_status["body"].get("jobs") or []
        recent_runs = bg_status["body"].get("recent_runs") or []
        rec.require(
            "background job run log contains expected jobs",
            {"order_matching", "take_profit_stop_loss_scan", "bot_trigger_scan", "margin_liquidation_scan", "interest_accrual"}.issubset({row.get("job_key") for row in recent_runs}),
            f"recent={[row.get('job_key') for row in recent_runs[:12]]}",
        )
        rec.require(
            "background jobs have no recorded failures",
            all(int(row.get("failure_count") or 0) == 0 for row in bg_jobs),
            json.dumps([{row.get("job_key"): row.get("failure_count")} for row in bg_jobs], ensure_ascii=False),
        )

        stress_contexts = []
        stress_results: list[dict[str, Any]] = []
        set_price_and_due_jobs(db_path, 100, ["price_refresh"])
        for role in ("stress_a", "stress_b"):
            ctx, page = user_page(browser, base_url, users[role], args.user_password)
            stress_contexts.append(ctx)
            stress_results.extend(run_stress_burst(page, max(1, int(args.stress_orders))))
        for ctx in stress_contexts:
            ctx.close()
        no_5xx = all(int(row.get("status") or 0) < 500 for row in stress_results)
        success_count = sum(1 for row in stress_results if row.get("ok"))
        rec.require(
            "Playwright concurrent order stress has no 5xx and produces fills",
            no_5xx and success_count > 0,
            f"requests={len(stress_results)} success={success_count} statuses={sorted({row.get('status') for row in stress_results})}",
        )

        verify_trading = api(root_page2, "GET", "/root/trading/verify")
        assert_api_ok(rec, "trading verify_state after background/stress", verify_trading)
        verify_chain = api(root_page2, "GET", "/root/points/chain/verify")
        assert_api_ok(rec, "PointsChain verify after background/stress", verify_chain)
        root_report_after = api(root_page2, "GET", "/admin/trading/report")
        assert_api_ok(rec, "root trading report after scenario", root_report_after)
        reserve_after = int(((root_report_after["body"].get("report") or {}).get("reserve_pool") or {}).get("balance_points") or 0)
        scenario["reserve_after"] = reserve_after
        bad_wallets = [
            dict(row)
            for row in db_all(
                db_path,
                """
                SELECT user_id,
                       soft_balance + hard_balance AS points_balance,
                       soft_frozen + hard_frozen AS points_frozen
                FROM points_wallets
                WHERE soft_balance + hard_balance < 0
                   OR soft_frozen + hard_frozen < 0
                """,
            )
        ]
        bad_margin_locks = [
            dict(row)
            for row in db_all(
                db_path,
                "SELECT user_id, market_symbol, locked_quantity_units FROM trading_spot_positions WHERE locked_quantity_units < 0",
            )
        ]
        rec.require("wallet balances/frozen amounts remain non-negative", not bad_wallets, json.dumps(bad_wallets, ensure_ascii=False))
        rec.require("spot locked quantities remain non-negative", not bad_margin_locks, json.dumps(bad_margin_locks, ensure_ascii=False))
        rec.require("reserve pool remains non-negative and collects income", reserve_after >= 0 and reserve_after >= reserve_before, f"before={reserve_before} after={reserve_after}")
        root_ctx2.close()
        browser.close()

    report = {
        "ok": not rec.failures,
        "base_url": base_url,
        "runtime_dir": str(runtime_dir),
        "scenario": scenario,
        "checks": [row.__dict__ for row in rec.checks],
        "failures": [row.__dict__ for row in rec.failures],
    }
    json_path = out_dir / "trading_background_correctness.json"
    md_path = out_dir / "trading_background_correctness.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_lines = [
        "# Trading Background Correctness QA",
        "",
        f"- ok: `{report['ok']}`",
        f"- base_url: `{base_url}`",
        f"- runtime_dir: `{runtime_dir}`",
        f"- reserve_before: `{scenario.get('reserve_before')}`",
        f"- reserve_after: `{scenario.get('reserve_after')}`",
        "",
        "## Checks",
    ]
    for row in rec.checks:
        md_lines.append(f"- [{'PASS' if row.ok else 'FAIL'}] {row.name}: {row.detail}")
    md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")
    print(f"[artifact] {json_path}", flush=True)
    print(f"[artifact] {md_path}", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
