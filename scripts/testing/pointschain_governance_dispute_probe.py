#!/usr/bin/env python3
"""Targeted Playwright probe for PointsChain governance/dispute UI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", default="root")
    parser.add_argument("--password", default="root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = {"ok": False, "checks": []}

    def check(name: str, ok: bool, detail: str = "") -> None:
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(10000)
        page.goto(args.base_url, wait_until="domcontentloaded")
        page.fill("#li-user", args.username)
        page.fill("#li-pw", args.password)
        page.click("#li-btn")
        page.wait_for_selector("#tab-module-economy", state="visible", timeout=15000)
        check("login", True, f"logged in as {args.username}")

        page.click("#tab-module-economy")
        page.wait_for_selector("#module-economy", state="visible", timeout=10000)
        page.wait_for_selector("#tab-economy-governance", state="visible", timeout=10000)
        check("governance_tab_visible", True)

        page.click("#tab-economy-governance")
        page.wait_for_selector("#economy-governance-page.active", timeout=10000)
        page.wait_for_timeout(800)
        check("governance_page_split_from_explorer", page.locator("#economy-governance-page.active").count() == 1)
        check("dispute_card_present", page.locator("#economy-dispute-card").count() == 1)
        check("governance_category_select_present", page.locator("#economy-governance-category-select").count() == 1)
        check("governance_status_tabs_present", page.locator("[data-governance-status-filter]").count() == 3)
        page.click('#economy-governance-status-tabs [data-governance-status-filter="voting"]')
        page.wait_for_timeout(150)
        check("governance_voting_tab_active", "active" in (page.locator('#economy-governance-status-tabs [data-governance-status-filter="voting"]').get_attribute("class") or ""))
        page.click('#economy-governance-status-tabs [data-governance-status-filter="closed"]')
        page.wait_for_timeout(150)
        check("governance_closed_tab_active", "active" in (page.locator('#economy-governance-status-tabs [data-governance-status-filter="closed"]').get_attribute("class") or ""))
        page.click('#economy-governance-status-tabs [data-governance-status-filter="review"]')
        page.wait_for_timeout(150)
        check("governance_review_tab_active", "active" in (page.locator('#economy-governance-status-tabs [data-governance-status-filter="review"]').get_attribute("class") or ""))
        check("mint_ui_present", page.locator("#economy-governance-mint-create-details").count() == 1)
        check("policy_ui_present", page.locator("#economy-governance-policy-create-details").count() == 1)
        check("emergency_lockdown_ui_present", page.locator("#economy-governance-lockdown-create-btn").count() == 1)
        check("cold_wallet_legacy_delete_select_removed", page.locator("#economy-wallet-delete-cold-address").count() == 0)

        page.select_option("#economy-governance-category-select", "mint")
        page.wait_for_timeout(250)
        check("mint_category_visible", page.locator("#economy-governance-mint-create-details").evaluate("el => getComputedStyle(el).display !== 'none'"))
        check("public_category_hidden_when_mint_selected", page.locator("#economy-public-governance-create-details").evaluate("el => getComputedStyle(el).display === 'none'"))

        page.select_option("#economy-governance-category-select", "dispute")
        page.wait_for_timeout(250)
        selected_case_text = page.locator("#economy-governance-selected-case").inner_text()
        check("dispute_category_requires_case_selection", "未選取疑義交易案件" in selected_case_text, selected_case_text)

        page.click("#tab-economy-explorer")
        page.wait_for_selector("#economy-explorer-page.active", timeout=10000)
        check("explorer_not_governance", page.locator("#economy-governance-page.active").count() == 0)

        page.click("#tab-economy-governance")
        page.wait_for_selector("#economy-governance-page.active", timeout=10000)
        page.select_option("#economy-governance-category-select", "treasury")
        page.wait_for_timeout(250)
        page.eval_on_selector("#economy-governance-treasury-create-details", "el => el.open = true")
        page.select_option("#economy-governance-treasury-action", "EXCHANGE_FUND_REPLENISH")
        page.wait_for_function(
            "() => { const el = document.querySelector('#economy-governance-treasury-destination'); return el && el.readOnly && el.value && el.value.startsWith('pc1'); }",
            timeout=15000,
        )
        treasury_dest = page.eval_on_selector(
            "#economy-governance-treasury-destination",
            "el => ({value: el.value, readOnly: el.readOnly})",
        )
        check(
            "exchange_replenish_address_locked",
            bool(treasury_dest["readOnly"]) and str(treasury_dest["value"]).startswith("pc1"),
            json.dumps(treasury_dest, ensure_ascii=False),
        )

        page.click("#tab-economy-transactions")
        page.wait_for_selector("#economy-transactions-page.active", timeout=10000)
        page.wait_for_timeout(800)
        dispute_buttons = page.locator("#economy-transactions-list [data-dispute-tx]").count()
        check("transaction_dispute_button_rendered", dispute_buttons >= 1, f"count={dispute_buttons}")
        if dispute_buttons:
            page.on("dialog", lambda dialog: dialog.dismiss())
            page.locator("#economy-transactions-list [data-dispute-tx]").first.click()
            page.wait_for_timeout(250)
            transaction_msg = page.locator("#economy-transactions-msg").inner_text()
            check(
                "transaction_dispute_click_has_feedback",
                "疑義交易" in transaction_msg or "root 不能代替" in transaction_msg,
                transaction_msg,
            )

        result["ok"] = all(item["ok"] for item in result["checks"])
        browser.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
