#!/usr/bin/env python3
"""Browser smoke test for the admin feature switch/package UI."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT / "public"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def run_probe(port: int) -> dict:
    handler = functools.partial(QuietHandler, directory=str(PUBLIC_DIR))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as server:
        actual_port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return run_browser(f"http://127.0.0.1:{actual_port}/")
        finally:
            server.shutdown()
            thread.join(timeout=5)


def run_browser(url: str) -> dict:
    page_errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#feature-switch-groups details", state="attached", timeout=10000)
        data = page.evaluate(
            """() => {
              const groups = [...document.querySelectorAll('#feature-switch-groups details')]
                .map((el) => el.textContent.trim());
              const options = [...document.querySelectorAll('#feature-bundle-select option')]
                .map((el) => el.value)
                .filter(Boolean);
              document.querySelector('#feature-bundle-select').value = 'exchange-ops';
              document.querySelector('#feature-bundle-select')
                .dispatchEvent(new Event('change', { bubbles: true }));
              document.querySelector('#feature-bundle-apply').click();
              const afterExchange = {
                economy: document.querySelector('#s-feature-economy-enabled')?.checked,
                chain: document.querySelector('#s-feature-points-chain-enabled')?.checked,
                trading: document.querySelector('#s-feature-trading-enabled')?.checked,
                experiments: document.querySelector('#s-feature-experiments-enabled') !== null,
                status: document.querySelector('#settings-msg')?.textContent || '',
              };
              document
                .querySelector('[data-feature-group-key="economy"][data-feature-group-action="off"]')
                .click();
              const afterEconomyOff = {
                economy: document.querySelector('#s-feature-economy-enabled')?.checked,
                chain: document.querySelector('#s-feature-points-chain-enabled')?.checked,
                trading: document.querySelector('#s-feature-trading-enabled')?.checked,
                advisory: document.querySelector('#feature-advisory-list')?.textContent || '',
              };
              document
                .querySelector('[data-feature-group-key="economy"][data-feature-group-action="on"]')
                .click();
              const afterEconomyOn = {
                economy: document.querySelector('#s-feature-economy-enabled')?.checked,
                chain: document.querySelector('#s-feature-points-chain-enabled')?.checked,
                trading: document.querySelector('#s-feature-trading-enabled')?.checked,
              };
              return { groups, options, afterExchange, afterEconomyOff, afterEconomyOn };
            }"""
        )
        browser.close()

    expected_bundles = {
        "ops-minimum",
        "safe-community",
        "creator-media",
        "points-chain-rc1",
        "exchange-ops",
        "low-resource",
        "full-user",
    }
    missing = sorted(expected_bundles - set(data["options"]))
    checks = {
        "groups_rendered": len(data["groups"]) >= 6,
        "expected_bundles_present": not missing,
        "exchange_ops_enables_economy_chain_trading": all(
            data["afterExchange"][key] for key in ("economy", "chain", "trading")
        ),
        "economy_group_off_disables_all": not any(
            data["afterEconomyOff"][key] for key in ("economy", "chain", "trading")
        ),
        "economy_group_on_enables_all": all(
            data["afterEconomyOn"][key] for key in ("economy", "chain", "trading")
        ),
        "experiments_switch_present": bool(data["afterExchange"]["experiments"]),
        "no_page_errors": not page_errors,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "missing_bundles": missing,
        "page_errors": page_errors[:10],
        "console_errors": console_errors[:10],
        "data": data,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    result = run_probe(args.port)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
