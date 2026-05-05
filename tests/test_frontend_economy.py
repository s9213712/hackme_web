from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_registration_only_requires_account_password_and_nickname():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    auth_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    register_section = index_html.split('id="sec-register"', 1)[1].split('id="captcha-field"', 1)[0]

    assert 'id="reg-user"' in register_section
    assert 'id="reg-pw"' in register_section
    assert 'id="reg-pw-confirm"' in register_section
    assert 'id="reg-nickname"' in register_section
    assert 'id="reg-idno"' not in register_section
    assert "身分證不可為空" not in auth_js
    assert "真實姓名不可為空" not in auth_js
    assert "請填寫生日" not in auth_js
    assert "請填寫電話" not in auth_js
    assert "id_number: idNo" not in auth_js


def test_root_points_page_is_chain_operations_console():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="economy-user-summary-grid"' in index_html
    assert 'id="economy-user-ledger-card"' in index_html
    assert 'id="economy-subtabs"' in index_html
    assert 'id="tab-economy-balance"' in index_html
    assert 'id="tab-economy-chain"' in index_html
    assert 'id="economy-balance-page"' in index_html
    assert 'id="economy-chain-page"' in index_html
    economy_balance_page = index_html.split('id="economy-balance-page"', 1)[1].split('id="economy-chain-page"', 1)[0]
    economy_chain_page = index_html.split('id="economy-chain-page"', 1)[1].split('id="economy-msg"', 1)[0]
    assert 'id="economy-root-virtual-card"' in economy_balance_page
    assert 'id="economy-trading-summary-card"' in economy_balance_page
    assert 'id="economy-root-card"' in economy_chain_page
    assert 'id="economy-admin-card"' in economy_chain_page
    assert "PointsChain 私有鏈管理" in index_html
    assert 'id="economy-root-report-btn"' in index_html
    assert 'id="economy-rollback-ledger-uuid"' in index_html
    assert 'id="economy-rollback-btn"' in index_html
    assert 'id="economy-audit-list"' in index_html
    assert 'id="economy-risk-ledger-list"' in index_html
    assert 'id="economy-chain-countdown"' in index_html
    assert 'id="economy-chain-loaded-at"' in index_html
    assert 'id="economy-chain-status"' in index_html
    assert "<pre id=\"economy-chain-status\"" not in index_html
    assert 'id="economy-root-virtual-card"' in index_html
    assert 'id="economy-root-virtual-total"' in index_html
    assert "剩餘積分 + 現貨估值" in index_html
    assert 'id="economy-manual-adjust-details"' in index_html
    assert 'id="economy-chain-backup-details"' in index_html
    assert 'id="economy-chain-account-details"' in index_html
    assert 'id="economy-chain-detail-lists"' in index_html
    assert 'id="economy-account-query-card"' in index_html
    assert 'id="economy-query-user-id"' in index_html
    assert 'id="economy-account-query-btn"' in index_html
    assert 'id="economy-query-points-balance"' in index_html
    assert 'id="economy-wallet-sanction-card"' in index_html
    assert 'id="economy-wallet-sanction-status"' in index_html
    assert 'id="economy-wallet-sanction-risk"' in index_html
    assert 'id="economy-wallet-freeze-amount"' in index_html
    assert 'id="economy-wallet-unfreeze-amount"' in index_html
    assert 'id="economy-wallet-sanction-btn"' in index_html
    assert 'id="economy-query-ledger-list"' in index_html
    assert 'id="economy-adjustment-list"' in index_html
    assert 'id="economy-admin-card-title"' in index_html
    assert 'id="economy-admin-card-sub"' in index_html
    assert 'id="economy-adjust-panel"' in index_html
    assert '<select id="economy-adjust-user-id">' in index_html
    assert '<input type="number" id="economy-adjust-user-id"' not in index_html
    assert 'id="economy-adjust-currency"' not in index_html
    assert "全站積分" in index_html
    assert "加減分明細" in index_html
    assert "手動加減分與待審核" in index_html
    assert "積分錢包" in index_html
    assert "積分交易所" in index_html
    assert "/js/55-economy.js?v=20260501-wallet-auto-refresh" in index_html
    assert "/js/50-admin.js?v=20260504-fusion-coverage-v1" in index_html
    assert "/js/56-trading.js?v=" in index_html
    assert 'id="economy-recovery-card"' in index_html
    assert 'id="economy-backup-btn"' in index_html
    assert 'id="economy-recovery-auto-handle-btn"' in index_html
    assert 'id="economy-recovery-approve-btn"' in index_html
    assert "function renderEconomyRecovery" in economy_js
    assert 'fetchEconomyJson("/root/points/chain/backups"' in economy_js
    assert 'fetchEconomyJson("/root/points/chain/recovery/auto-handle"' in economy_js
    assert 'fetchEconomyJson("/root/points/chain/recovery/approve"' in economy_js
    assert "async function autoHandlePointsChainRecovery()" in economy_js
    assert '["economy-recovery-auto-handle-btn", autoHandlePointsChainRecovery]' in economy_js
    assert "/js/90-bootstrap.js?v=20260503-appearance-v2" in index_html
    assert 'const rootMode = currentUser === "root";' in economy_js
    assert 'const canManagePoints = canManageEconomyPoints();' in economy_js
    assert 'adminCard.style.display = canManagePoints ? "" : "none"' in economy_js
    assert 'if ($("economy-admin-ledger-list")) $("economy-admin-ledger-list").innerHTML = "";' in economy_js
    assert 'if ($("economy-pending-list")) $("economy-pending-list").innerHTML = "";' in economy_js
    assert "function setEconomyActivePage(page" in economy_js
    assert 'chainTab.textContent = rootMode ? "積分私有鏈" : "審核";' in economy_js
    assert 'else title.textContent = nextPage === "chain" ? "積分私有鏈" : "積分餘額";' in economy_js
    assert 'fetchEconomyJson("/root/points/report")' in economy_js
    assert "startEconomyBlockCountdown" in economy_js
    assert "function canManageEconomyPoints()" in economy_js
    assert "function setEconomyRootLayout(rootMode)" in economy_js
    assert 'currentUser === "root" || currentRole === "manager" || currentRole === "super_admin"' in economy_js
    assert "最後更新" in economy_js
    assert "bindEconomyInlineEvents" in economy_js
    assert "economyAutoRefreshTimer" in economy_js
    assert 'currentModuleTab !== "economy"' in economy_js
    assert "}, 30000)" in economy_js
    assert "economy-adjustment-list" in economy_js
    assert 'adminLedgerList.style.display = rootMode ? "none" : ""' in economy_js
    assert 'if (adjustPanel) adjustPanel.style.display = rootMode ? "" : "none";' in economy_js
    assert 'adminTitle.textContent = "手動加減分";' in economy_js
    assert "加減分歷史統一在下方明細查看" in economy_js
    assert "只有 root 可以手動調整積分" in economy_js
    assert 'fetchEconomyJson("/admin/users")' in economy_js
    assert "function renderEconomyAdjustUserOptions" in economy_js
    assert "async function loadEconomyAccountLookup()" in economy_js
    assert "async function downloadCsvEndpoint" in economy_js
    assert "apiFetch(API + path" in economy_js
    assert "window.location.href = API + path" not in economy_js
    assert "async function sanctionEconomyWallet()" in economy_js
    assert "renderEconomyAccountLookup" in economy_js
    assert "formatEconomyVerificationSummary" in economy_js
    assert "formatEconomyRecoveryResult" in economy_js
    assert "PointsChain 已恢復並完成驗證" in economy_js
    assert "const resultMessage = formatEconomyRecoveryResult(json);" in economy_js
    assert "await loadEconomyDashboard();\n    economySetMsg(resultMessage, !!json.ok);" in economy_js
    assert "setEconomyChainStatus" in economy_js
    assert "JSON.stringify(json.report?.verification" not in economy_js
    assert "JSON.stringify(json.verification" not in economy_js
    assert '/admin/points/wallets/${encodeURIComponent(userId)}' in economy_js
    assert '/root/points/wallets/${encodeURIComponent(userId)}/sanction' in economy_js
    assert '["economy-wallet-sanction-btn", sanctionEconomyWallet]' in economy_js
    assert "economy-account-query-btn" in economy_js
    assert "會員讀取失敗" in economy_js
    assert "請先選擇要查詢的會員" in economy_js
    assert "請先選擇要調整的會員" in economy_js
    assert "economy-adjust-currency" not in economy_js
    assert 'return "點";' in economy_js
    assert 'async function rollbackEconomyLedger()' in economy_js
    assert "/rollback" in economy_js
    assert "bindEconomyInlineEvents" in bootstrap_js
    assert 'id="tab-settings-billing"' in index_html
    assert 'id="sec-settings-billing"' in index_html
    assert 'id="tab-settings-trading"' in index_html
    assert 'id="sec-settings-trading"' in index_html
    assert 'id="root-catalog-item-key"' in index_html
    assert 'id="root-catalog-storage-gb"' in index_html
    assert 'id="root-catalog-save-btn"' in index_html
    assert 'id="root-trading-enabled"' in index_html
    assert 'id="root-trading-borrowing-enabled"' in index_html
    assert 'id="root-trading-borrowing-enabled" checked' in index_html
    assert 'id="root-trading-borrow-apr-btc-eth"' in index_html
    assert 'id="root-trading-borrow-apr-usdt-points"' in index_html
    assert 'id="root-trading-borrow-interest-interval-hours"' in index_html
    assert 'id="root-trading-borrow-interest-minimum-hours"' in index_html
    assert 'id="root-trading-grid-fee-discount-percent"' in index_html
    assert 'id="root-trading-margin-long-financing-percent"' in index_html
    assert 'id="root-trading-short-collateral-percent"' in index_html
    assert "融資九成" in index_html
    assert "借券六成" in index_html
    assert "融資可貸比例（%）" in index_html
    assert "借券原始保證金比例（%）" in index_html
    assert "維持保證金比例（%）" in index_html
    assert 'id="root-trading-price-source"' in index_html
    assert 'value="fused_weighted"' in index_html
    assert 'id="root-trading-price-fusion-mode"' in index_html
    assert 'id="root-trading-price-fusion-depth-band-percent"' in index_html
    assert 'id="root-trading-price-fusion-depth-levels"' in index_html
    assert 'id="root-trading-price-fusion-min-coverage-percent"' in index_html
    assert 'id="root-trading-price-fusion-max-provider-weight"' in index_html
    assert 'id="root-trading-price-fusion-min-provider-count"' in index_html
    assert 'id="root-trading-price-fusion-weights"' in index_html
    assert 'class="trading-fusion-weight-list"' in index_html
    assert 'id="root-trading-price-fusion-market"' in index_html
    assert 'id="root-trading-price-fusion-refresh-btn"' in index_html
    assert 'id="root-trading-price-fusion-summary"' in index_html
    assert 'id="root-trading-price-fusion-provider-list"' in index_html
    assert 'id="root-trading-price-fusion-excluded-list"' in index_html
    assert "價格來源降級" in admin_js
    assert 'id="root-trading-max-price-staleness"' in index_html
    assert 'id="root-trading-liquidation-enabled"' in index_html
    assert 'id="root-trading-maintenance-percent"' in index_html
    assert 'id="root-trading-futures-enabled"' in index_html
    assert 'id="root-trading-pvp-enabled"' in index_html
    assert 'id="root-trading-reserve-pool"' in index_html
    assert 'id="root-trading-btc-trade-enabled"' in index_html
    assert 'id="root-trading-btc-trade-repo"' in index_html
    assert 'id="root-trading-btc-trade-branch"' in index_html
    assert 'id="root-trading-btc-trade-path"' in index_html
    assert 'id="root-trading-btc-trade-check-btn"' in index_html
    assert 'id="root-trading-btc-trade-setup-btn"' in index_html
    assert "BTC_trade 專案資料夾" in index_html
    assert 'id="root-trading-market-settings"' in index_html
    assert 'id="root-trading-settings-save-btn"' in index_html
    assert "function loadRootEconomyCatalog()" in admin_js
    assert 'apiFetch(API + "/root/economy/catalog"' in admin_js
    assert "saveRootEconomyCatalogItem" in admin_js
    assert "function loadRootTradingSettings()" in admin_js
    assert "function saveRootTradingSettings()" in admin_js
    assert "function renderRootTradingFusionWeightInputs" in admin_js
    assert "trading-fusion-weight-chip" in admin_js
    assert "trading-fusion-weight-unit" in admin_js
    assert "top 10 / 50 / 100 / 200 / 500 / 1000" in index_html
    assert "coverage truncated" in admin_js
    assert "唯一合格來源" in admin_js
    assert "reference 來源" in admin_js
    assert "reference 可用來源" in admin_js
    assert "請求市場" in admin_js
    assert "內部市場" in admin_js
    assert "目前不是正常 fused price" in admin_js
    assert "reference 占比" in admin_js
    assert "風控級占比" in admin_js
    assert "depth score" in admin_js
    assert "density" in admin_js
    assert "資料截斷，不代表該交易所真實深度不足" in admin_js
    assert "provider depth limit reached" in admin_js
    assert 'id="root-trading-price-stream-ws-enabled"' in index_html
    assert 'id="root-trading-price-stream-ws-stale-seconds"' in index_html
    assert "price_stream_ws_enabled" in admin_js
    assert "price_stream_ws_stale_seconds" in admin_js
    assert "provider input" in admin_js
    assert 'fallback ${transportState.fallback ? "HTTP polling" : "no"}' in admin_js
    assert "last update" in admin_js
    assert "transportState" in admin_js
    assert "最低覆蓋門檻（%）" in index_html
    assert "最少可用來源數" in index_html
    assert "price_fusion_depth_band_percent" in admin_js
    assert "price_fusion_min_orderbook_coverage_percent" in admin_js
    assert "max_single_provider_weight_percent" in admin_js
    assert "price_fusion_depth_levels" in admin_js
    assert "price_fusion_min_provider_count" in admin_js
    assert "function renderRootTradingPriceFusionMarketOptions" in admin_js
    assert "function renderRootTradingPriceFusionStatus" in admin_js
    assert "function loadRootTradingPriceFusionStatus" in admin_js
    assert "function toggleRootTradingPriceFusionControls" in admin_js
    assert "collectRootTradingFusionWeights" in admin_js
    assert "adminInputPercent" in admin_js
    assert "adminFormatPercent" in admin_js
    assert 'apiFetch(API + "/root/trading/settings"' in admin_js
    assert 'apiFetch(API + `/root/trading/price-fusion-status?market_symbol=${encodeURIComponent(selectedMarket)}`' in admin_js
    assert "parseRootTradingSettingsResponse" in admin_js
    assert "交易所參數 API 找不到" in admin_js
    assert "交易所參數儲存中" in admin_js
    assert 'id="root-trading-borrow-apr-btc-eth"' in index_html
    assert 'id="root-trading-borrow-apr-usdt-points"' in index_html
    assert 'id="root-trading-borrow-interest-interval-hours"' in index_html
    assert 'id="root-trading-borrow-interest-minimum-hours"' in index_html
    assert 'id="root-trading-grid-fee-discount-percent"' in index_html
    assert 'id="trading-funding-pool-rate-btc-eth"' in index_html
    assert 'id="trading-funding-pool-rate-usdt-points"' in index_html
    assert "borrow_apr_btc_eth_percent" in admin_js
    assert "borrow_apr_usdt_points_percent" in admin_js
    assert "borrow_interest_interval_hours" in admin_js
    assert "borrow_interest_minimum_hours" in admin_js
    assert "grid_fee_discount_percent" in admin_js
    assert "margin_long_financing_percent" in admin_js
    assert "short_collateral_percent" in admin_js
    assert "price_source" in admin_js
    assert "max_price_staleness_seconds" in admin_js
    assert "btc_trade_enabled" in admin_js
    assert "btc_trade_repo_url" in admin_js
    assert "btc_trade_branch" in admin_js
    assert "btc_trade_project_dir" in admin_js
    assert "root-trading-btc-trade-start-btn" in index_html
    assert "/root/trading/btc-trade/start" in admin_js
    assert "/root/trading/btc-trade/start-status" in admin_js
    assert "pollRootBtcTradeStartJob" in admin_js
    assert "一鍵啟動預測" in index_html
    assert "資料是否過期" in index_html
    assert "重訓模型，再執行預測腳本並等待新的預測資料" in index_html
    assert "function checkRootBtcTradeStatus" in admin_js
    assert 'apiFetch(API + "/root/trading/btc-trade/check"' in admin_js
    assert "function setupRootBtcTrade" in admin_js
    assert 'apiFetch(API + "/root/trading/btc-trade/setup"' in admin_js
    assert "margin_liquidation_enabled" in admin_js
    assert "margin_maintenance_percent" in admin_js
    assert "collectRootTradingMarketSettings" in admin_js
    assert 'switchSettingsSection("billing")' in bootstrap_js
    assert 'switchSettingsSection("trading")' in bootstrap_js
    assert "loadRootTradingSettings" in bootstrap_js
    assert "checkRootBtcTradeStatus" in bootstrap_js
    assert "setupRootBtcTrade" in bootstrap_js
    billing_section = index_html.split('id="sec-settings-billing"', 1)[1].split('id="sec-settings-trading"', 1)[0]
    trading_settings_section = index_html.split('id="sec-settings-trading"', 1)[1].split('id="sec-settings-drive"', 1)[0]
    assert 'id="root-trading-enabled"' not in billing_section
    assert "服務扣點與容量商品" in billing_section
    assert "交易所設定已獨立成單獨分頁" in trading_settings_section
    assert "基本開關與風控" in trading_settings_section
    assert "價格來源與融合比例" in trading_settings_section
    assert "不必剛好加總 100，系統會自動正規化" in trading_settings_section
    assert "前 N 檔" in trading_settings_section
    assert "中間價附近 ±1% 範圍內的買賣盤名目量" in trading_settings_section
    assert "較弱一側作為 depth score" in trading_settings_section
    assert "不建議單獨作為強平、機器人或實際成交的唯一依據" in trading_settings_section
    assert "機器人掃描與稽核" in trading_settings_section
    assert "BTC_trade 信號整合" in trading_settings_section
    assert "各交易對參數" in trading_settings_section
    assert "累積利息" in index_html
    assert "下一次計息" in index_html
    assert ".trading-fusion-weight-list" in styles
    assert ".trading-fusion-weight-chip" in styles
    assert ".trading-fusion-inline-input" in styles


def test_trading_exchange_is_separate_from_wallet_page():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")
    workflow_templates = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "workflows" / "system").glob("*.json"))
    )
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    economy_section = index_html.split('id="module-economy"', 1)[1].split('id="module-trading"', 1)[0]
    trading_section = index_html.split('id="module-trading"', 1)[1].split('id="module-accounts"', 1)[0]

    assert 'id="tab-module-trading"' in index_html
    assert "積分交易所" in trading_section
    assert 'id="trading-card"' in trading_section
    assert 'id="trading-submit-order-btn"' in trading_section
    assert 'id="trading-order-estimate"' in trading_section
    assert 'id="trading-margin-card"' in trading_section
    assert 'id="trading-margin-type"' in trading_section
    assert 'id="trading-margin-collateral"' in trading_section
    assert 'id="trading-margin-open-btn"' in trading_section
    assert 'id="trading-margin-position-list"' in trading_section
    assert 'id="trading-margin-account-summary"' in trading_section
    assert "全倉維持率" in trading_section
    assert 'id="trading-order-form"' in trading_section
    assert 'id="trading-availability-note"' in trading_section
    assert 'id="trading-trial-credit-available"' in trading_section
    assert 'id="trading-trial-credit-note"' in trading_section
    assert 'id="trading-root-card"' in trading_section
    assert 'id="trading-limit-match-btn"' in trading_section
    assert 'id="trading-liquidation-scan-btn"' in trading_section
    assert 'id="trading-liquidation-status"' in trading_section
    assert 'id="trading-funding-available"' in trading_section
    assert "交易總可用" in trading_section
    assert 'id="trading-root-reset-sim-btn"' in trading_section
    assert 'id="trading-btc-signal-card"' in trading_section
    assert 'id="trading-btc-signal-body"' in trading_section
    assert "比特幣信號" in trading_section
    assert 'id="trading-reference-chart"' in trading_section
    assert 'id="trading-reference-tooltip"' in trading_section
    assert 'id="trading-reference-interval"' in trading_section
    assert '<option value="1s">1 秒</option>' not in trading_section
    assert '<option value="1m">1 分</option>' not in trading_section
    assert '<option value="5m">5 分</option>' in trading_section
    assert '<option value="15m" selected>15 分</option>' in trading_section
    assert 'id="trading-indicator-ma5"' in trading_section
    assert 'id="trading-indicator-ma10"' in trading_section
    assert 'id="trading-indicator-ma20" checked' in trading_section
    assert 'id="trading-indicator-ma30"' in trading_section
    assert 'id="trading-indicator-ma60"' in trading_section
    assert 'id="trading-indicator-ema12"' in trading_section
    assert 'id="trading-indicator-ema26"' in trading_section
    assert 'id="trading-indicator-ema50"' in trading_section
    assert 'id="trading-indicator-bollinger"' in trading_section
    assert 'id="trading-indicator-rsi14"' in trading_section
    assert 'id="trading-indicator-kd"' in trading_section
    assert 'id="trading-btc-trade-card"' not in trading_section
    assert 'id="trading-btc-trade-path"' not in trading_section
    assert "Binance 參考價格" in trading_section
    assert "蠟燭圖" in trading_section
    assert "root 可使用現貨與合約模擬交易" in trading_section
    assert "一般用戶可使用已啟用的積分現貨市場" in trading_section
    assert 'id="trading-root-contract-card"' in trading_section
    assert 'id="trading-contract-open-btn"' in trading_section
    assert 'id="trading-contract-position-list"' in trading_section
    assert 'id="trading-submit-order-btn"' not in economy_section
    assert 'id="trading-root-card"' not in economy_section
    assert 'id="economy-trading-summary-card"' in economy_section
    assert 'id="economy-wallet-download-btn"' in economy_section
    assert 'id="economy-trading-export-btn"' in economy_section
    assert 'id="economy-spot-position-quantity"' in economy_section
    assert 'id="economy-spot-position-detail-list"' in economy_section
    assert "現貨明細" in economy_section
    assert "進階倉位明細" in economy_section
    assert "市價平倉" in economy_section
    assert "現貨部位" in economy_section
    assert "各交易對分開計算" in economy_section
    assert 'id="economy-margin-position-count"' in economy_section
    assert 'id="economy-margin-position-summary"' in economy_section
    assert 'id="economy-margin-position-detail-list"' in economy_section
    assert "整戶維持率" in trading_js
    assert "補保證金" in trading_js
    assert "原始保證金" in trading_js
    assert "原始保證金率" in trading_js
    assert "原始保證金最低需求" in trading_js
    assert "放空價格風險" in trading_js
    assert "價格上漲會虧損並降低維持率" in trading_js
    assert "未實現盈虧" in trading_js
    assert "損益平衡價" in trading_js
    assert "逐倉估算強平價" in trading_js
    assert "損益平衡價已含開倉費、累積利息與預估平倉手續費" in trading_js
    assert "實際清算仍依全倉維持率" in trading_js
    assert "你填寫的保證金已超過本次買入名目金額，這不屬於融資交易" in trading_js
    assert "請改用現貨買入" in trading_js
    assert "且至少要借 1 點" in trading_js
    assert "原始保證金不足，至少需要" in trading_js
    assert "renderTradingMarginAccountSummary" in trading_js
    assert "liquidation_price_points" in trading_js
    assert "breakeven_price_points" in trading_js
    assert "unrealized_pnl_points" in trading_js
    assert "function tradingMarginLiveInterest" in trading_js
    assert "function tradingMarginBreakEvenPrice" in trading_js
    assert "function tradingMarginNextInterestAtMs" in trading_js
    assert 'id="economy-contract-position-count"' in economy_section
    assert 'id="economy-contract-position-summary"' in economy_section
    assert 'id="economy-trading-order-list"' in economy_section
    assert 'id="economy-trading-fill-list"' in economy_section
    assert 'id="economy-catalog-list"' not in economy_section
    assert "服務價格" not in economy_section
    assert 'tab-module-trading", module: "trading"' in core_js
    assert 'switchModuleTab("trading")' in bootstrap_js
    assert 'if (normTab === "trading"' in admin_js
    assert "function renderTradingWalletSummary" in trading_js
    assert "function loadTradingBtcSignal" in trading_js
    assert "function tradingBtcSignalCountdownText" in trading_js
    assert "function updateTradingBtcSignalMeta" in trading_js
    assert "next_prediction_at" in trading_js
    assert "下次預測倒數" in trading_js
    assert "策略版本" in trading_js
    assert "fear_greed" in trading_js
    assert "/trading/btc-signal" in trading_js
    assert "function rootVirtualSpotValue" in trading_js
    assert "function renderEconomySpotPositionDetails" in trading_js
    assert "function renderEconomyMarginPositionDetails" in trading_js
    assert "function submitEconomySpotSell" in trading_js
    assert "data-economy-spot-limit" in trading_js
    assert "data-economy-spot-market-close" in trading_js
    assert "data-economy-margin-close" in trading_js
    assert "data-economy-margin-add-collateral" in trading_js
    assert "data-margin-add-collateral" in trading_js
    assert "addTradingMarginCollateral" in trading_js
    assert "margin_positions" in trading_js
    assert "margin_summary" in trading_js
    assert ">確認</button>" in trading_js
    assert ">市價平倉</button>" in trading_js
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    assert "/points/wallet/export.csv" in economy_js
    assert "/trading/history/export.csv" in economy_js
    assert '"economy-wallet-download-btn", downloadEconomyWalletCsv' in economy_js
    assert '"economy-trading-export-btn", downloadEconomyTradingCsv' in economy_js
    assert "grid-template-columns: minmax(120px, .85fr) repeat(5" in styles
    assert "持有成本" in trading_js
    assert "損益平均價格" in trading_js
    assert "目前部位價值" in trading_js
    assert "盈虧" in trading_js
    assert "已實現盈虧" in trading_js
    assert "realized_pnl_points" in trading_js
    assert "unrealized_pnl_points" in trading_js
    assert "tradingSpotCostBasis" in trading_js
    assert "payload.emergency_close = true" in trading_js
    assert "手續費按平時 2 倍計算" in trading_js
    assert "function tradingOrderDraftEstimate" in trading_js
    assert "function syncTradingOrderSideTheme" in trading_js
    assert "function tradingOrderInputMode" in trading_js
    assert "function syncTradingOrderInputMode" in trading_js
    assert 'id="trading-input-mode"' in trading_section
    assert "用點數換算" in trading_section
    assert "買入時點數視為含手續費的總支出" in trading_js
    assert "quantity: tradingQuantityForSubmit(estimate.quantity)" in trading_js
    assert "trading-order-buy" in trading_js
    assert "trading-order-sell" in trading_js
    assert "買入下單" in trading_js
    assert "賣出下單" in trading_js
    assert ".trading-order-buy" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".trading-submit-sell" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert "function updateTradingOrderEstimate" in trading_js
    assert "超過可用" in trading_js
    assert "超過可賣現貨" in trading_js
    assert "function openTradingMarginPosition" in trading_js
    assert "function closeTradingMarginPosition" in trading_js
    assert "現貨交易機器人" in trading_section
    assert "自動化 Workflow" in trading_section
    assert "定投" in trading_section
    assert "回測分析" in trading_section
    assert "/trading-workflow-editor.html" in trading_section
    assert 'id="trading-auto-workflow-json"' in trading_section
    assert 'id="trading-workflow-load-btn"' in trading_section
    assert 'id="trading-workflow-template-select"' in trading_section
    assert 'id="trading-workflow-template-apply-btn"' in trading_section
    assert 'id="trading-workflow-template-explanation"' in trading_section
    assert 'id="trading-workflow-custom-name"' in trading_section
    assert 'id="trading-workflow-custom-save-btn"' in trading_section
    assert "保守逢低買入" in trading_section
    assert "突破追價買入" in trading_section
    assert "持倉跌破停損" in trading_section
    assert "RSI 分批買賣" in trading_section
    assert "MA 趨勢回踩" in trading_section
    assert "布林通道均值回歸" in trading_section
    assert "KD 動能追蹤" in trading_section
    assert "停利停損風控" in trading_section
    assert (ROOT / "public" / "trading-workflow-editor.html").exists()
    assert 'id="trading-auto-bot-save-btn"' in trading_section
    assert 'id="trading-dca-bot-save-btn"' in trading_section
    assert 'id="trading-bot-scan-btn"' in trading_section
    assert 'id="trading-backtest-run-btn"' in trading_section
    assert 'id="trading-auto-bot-market"' in trading_section
    assert 'id="trading-dca-bot-market"' in trading_section
    assert 'id="trading-backtest-market"' in trading_section
    assert 'id="trading-backtest-date-hint"' in trading_section
    assert 'id="trading-bot-type"' not in trading_section
    assert "function saveTradingBot" in trading_js
    assert "function saveTradingDcaBot" in trading_js
    assert "function scanTradingBots" in trading_js
    assert "function backtestTradingBot" in trading_js
    assert "function formatBacktestDatetimeLocal" in trading_js
    assert "function updateBacktestDateRangeGuidance" in trading_js
    assert "function tradingBotRecentFills" in trading_js
    assert "function renderTradingBotFillDetails" in trading_js
    assert "function increaseTradingBotMaxRuns" in trading_js
    assert "/trading/bots/${encodeURIComponent(botUuid)}/increase-runs" in trading_js
    assert "function tradingBotNextRunText" in trading_js
    assert "function updateTradingBotCountdowns" in trading_js
    assert "data-trading-bot-next-run" in trading_js
    assert "data-trading-bot-increase-runs" in trading_js
    assert "增加次數" in trading_js
    assert "不限制" in trading_js
    assert "交易明細（" in trading_js
    assert "設定摘要" in trading_js
    assert "已立即執行第一筆" in trading_js
    assert "function tradingErrorText" in trading_js
    assert "交易所 API 不存在" in trading_js
    assert "function bindTradingActionButton" in trading_js
    assert "自動化機器人新增失敗" in trading_js
    assert "定投機器人新增失敗" in trading_js
    assert "未提供錯誤原因" in trading_js
    assert "正在新增自動化機器人" in trading_js
    assert 'id="trading-dca-bot-max-runs"' in trading_section
    assert "輸入 -1 代表不限制執行次數" in trading_section
    assert "parseTradingWorkflowInput" in trading_js
    assert "function tradingWorkflowTemplates" in trading_js
    assert "function loadTradingWorkflowTemplates" in trading_js
    assert "function renderTradingWorkflowTemplateExplanation" in trading_js
    assert "function saveTradingWorkflowCustomTemplate" in trading_js
    assert "function applyTradingWorkflowTemplate" in trading_js
    assert "workflow_graph" in workflow_templates
    assert "system_template" in workflow_templates
    assert "stop_loss_percent" in workflow_templates
    assert "take_profit_percent" in workflow_templates
    assert "未載入圖表，正在由後端下載歷史 K 線後回測" in trading_js
    assert "auto_fetch_reference_candles = true" in trading_js
    assert "estimateBacktestRequestedCandles" in trading_js
    assert "BACKTEST_TOTAL_CANDLE_LIMIT" in trading_js
    assert "若保留開始時間，結束最晚可選" in trading_js
    assert "若保留結束時間，開始最早可選" in trading_js
    assert "先選開始或結束時間" in trading_js
    assert "basePayload.candle_limit = estimatedCandles || 500" in trading_js
    assert 'id="root-trading-bot-audit-summary"' in index_html
    assert 'id="root-trading-bot-audit-run-btn"' in index_html
    assert "function loadRootTradingBotAuditDashboard" in admin_js
    assert "function runRootTradingBotAudit" in admin_js
    assert "function reviewTradingAuditBugReport" in admin_js
    assert "後端自動分" in trading_js
    assert "資料來源" in trading_js
    assert "prepareTradingBacktestFromBot" in trading_js
    assert '"/trading/bots/scan"' in trading_js
    assert '"/trading/bots/backtest"' in trading_js
    assert "tradingState.bots" in trading_js
    assert "function matchTradingLimitOrders" in trading_js
    assert "function scanTradingLiquidations" in trading_js
    assert "function renderTradingMarginPositions" in trading_js
    assert "function renderTradingFills" in trading_js
    assert "record_type" in trading_js
    assert "margin_" in trading_js
    assert "進階交易" in trading_js
    assert "損益" in trading_js
    assert '"/trading/margin/open"' in trading_js
    assert '"/root/trading/liquidations/scan"' in trading_js
    assert '"/root/trading/orders/match"' in trading_js
    assert "borrowing_enabled" in trading_js
    assert "margin_liquidation_enabled" in trading_js
    assert "margin_maintenance_percent" in trading_js
    assert "margin_long_financing_percent" in trading_js
    assert "short_collateral_percent" in trading_js
    assert "tradingInputPercent" in trading_js
    assert "formatTradingPercent" in trading_js
    assert "initial_margin_points" in trading_js
    assert "maintenance_margin_points" in trading_js
    assert "融資可貸比例" in trading_js
    assert "借券保證金比例" in trading_js
    assert 'if (marginCard) marginCard.style.display = "";' in trading_js
    assert "marginControlsDisabled" in trading_js
    assert 'const marginControlsDisabled = !borrowingEnabled;' in trading_js
    assert 'marginControlsDisabled = !borrowingEnabled || currentUser === "root"' not in trading_js
    assert "root 可用模擬資金進行融資 / 借券" in trading_js
    assert "root 尚未開啟借貸交易，目前僅可查看此區。" in trading_js
    assert "保證金不足，至少需要" in trading_js
    assert "可用資金不足，需要" in trading_js
    assert "進階交易開倉失敗：" in trading_js
    assert "trading-margin-open-btn" in trading_js
    assert '"trading-limit-match-btn", matchTradingLimitOrders' in trading_js
    assert '"trading-liquidation-scan-btn", scanTradingLiquidations' in trading_js
    assert "economy-root-virtual-total" in trading_js
    assert "available + spotValue" in trading_js
    assert "trial_credit" in trading_js
    assert "function tradingTrialCountdownText" in trading_js
    assert "setInterval(updateTradingTrialCountdown, 1000)" in trading_js
    assert "總可用" in trading_js
    assert "體驗金" in trading_js
    assert "真實積分" in trading_js
    assert "體驗金優先" in trading_js
    assert "function loadTradingReferencePrices" in trading_js
    assert "function restartTradingReferenceAutoRefresh" in trading_js
    assert "function tradingReferenceAutoRefreshMs" in trading_js
    assert "return 1000;" in trading_js
    assert 'interval === "1s"' not in trading_js
    assert "loadTradingReferencePrices({ silent: true, priceOnly: true })" in trading_js
    assert "tradingReferenceChartAutoTimer" in trading_js
    assert "tradingReferenceChartAutoBusy" in trading_js
    assert "}, 5000)" in trading_js
    assert "function tradingReferenceChartLimit" in trading_js
    assert "function mergeTradingReferenceLatestPayload" in trading_js
    assert "function tradingReferencePayloadHasCandles" in trading_js
    assert "loadTradingReferencePrices({ silent: true, latestOnly: true })" in trading_js
    assert 'const latestParam = latestOnly ? "&latest=1" : "";' in trading_js
    assert "tradingReferencePriceAbort" in trading_js
    assert "tradingReferenceChartAbort" in trading_js
    assert "保留上一張蠟燭圖" in trading_js
    assert "tradingState.referencePrices = null" not in trading_js
    assert 'currentModuleTab !== "trading"' in trading_js
    assert "tradingDashboardAutoTimer" in trading_js
    assert "function renderTradingReferenceChart" in trading_js
    assert "function updateTradingReferenceTooltip" in trading_js
    assert "function tradingIndicatorSeries" in trading_js
    assert "function tradingBollingerSeries" in trading_js
    assert "function tradingRsiSeries" in trading_js
    assert "function tradingKdSeries" in trading_js
    assert "function buildTradingReferenceIndicators" in trading_js
    assert "function drawTradingOscillatorPanel" in trading_js
    assert "drawTradingIndicatorLine" in trading_js
    assert "trading-indicator-ma20" in trading_js
    assert "trading-indicator-rsi14" in trading_js
    assert "trading-indicator-kd" in trading_js
    assert "RSI / KD" in trading_js
    assert "布林線" in trading_section
    assert "function tradingReferenceTimeLabel" in trading_js
    assert "tradingReferenceChartModel" in trading_js
    assert "tradingReferenceHoverIndex" in trading_js
    assert 'referenceChart.addEventListener("mousemove", updateTradingReferenceTooltip)' in trading_js
    assert 'referenceChart.addEventListener("mouseleave", hideTradingReferenceTooltip)' in trading_js
    assert "resetRootTradingSimulatedBalance" in trading_js
    assert "/trading/reference-prices" in trading_js
    assert "/trading/btc-trade-signal" not in trading_js
    assert "/root/trading/btc-trade-settings" not in trading_js
    assert "/root/trading/simulated-balance/reset" in trading_js
    assert "刪除 root 的模擬訂單、成交紀錄、現貨與合約持倉" in trading_js
    assert "已清除訂單" in trading_js
    assert "Binance 公開 API" in trading_js
    assert "function tradingDisplaySymbol" in trading_js
    assert "function tradingBaseAssetLabel" in trading_js
    assert "目前對 root 以外用戶開放 ${publicSpotSymbols.join(\"、\") || \"已啟用的積分現貨市場\"} 現貨。" in trading_js
    assert "直接輸入 ${assetLabel} 枚數。" in trading_js
    assert 'tradingDisplaySymbol(market.symbol)' in trading_js
    assert "ctx.fillRect(x - bodyW / 2, bodyTop, bodyW, bodyH)" in trading_js
    assert "ctx.strokeRect(x - bodyW / 2, bodyTop, bodyW, bodyH)" in trading_js
    assert "1 POINT = 1 USDT" not in trading_js
    assert "≈" not in trading_js
    assert "function renderBtcTradeSignal" not in trading_js
    assert "root 模擬資金" in trading_js
    assert 'contractCard.style.display = currentUser === "root" ? "" : "none"' in trading_js
    assert "openRootTradingContract" in trading_js
    assert "closeRootTradingContract" in trading_js
    assert "/root/trading/contracts" in trading_js
    assert "futures_positions" in trading_js
    assert "totalSpotQuantity" not in trading_js
    assert "function tradingPositionLabel" in trading_js
    assert 'activePositions.map((row) => tradingPositionLabel(row)).join(" / ")' in trading_js
    assert "rootVirtualSpotValue(activePositions, markets)" in trading_js
    assert 'renderTradingOrders(orders, "economy-trading-order-list", false)' in trading_js
    assert '"economy-trading-open-btn", openTradingModuleFromWallet' in trading_js
    assert '"economy-root-virtual-open-btn", openTradingModuleFromWallet' in trading_js
    assert 'id="trading-current-delta"' in trading_section
    assert 'id="trading-current-health"' in trading_section
    assert "TRADING_LIVE_PRICE_REFRESH_MS = 2000" in trading_js
    assert "function loadTradingLivePrice()" in trading_js
    assert "function renderTradingCurrentPrice" in trading_js
    assert "/trading/live-price?market=" in trading_js
    assert "updateTradingOrderEstimate();" in trading_js
    assert "price_health" in trading_js
    assert "fallback_reason" in trading_js
    assert "excluded_sources" in trading_js
    assert "high_risk_block_reason" in trading_js
    assert "warnings" in trading_js
    assert "defaulted_market" in trading_js
    assert "function tradingTransportStateSummary" in trading_js
    assert "transport_state" in trading_js
    assert "WebSocket provider input 已退回 HTTP polling" in trading_js
    assert "provider input stale" in trading_js
    assert "🟡 reference 價格降級" in trading_js
    assert "🟢 reference 價格正常" in trading_js

    workflow_editor = (ROOT / "public" / "trading-workflow-editor.html").read_text(encoding="utf-8")
    workflow_editor_js = (ROOT / "public" / "js" / "trading-workflow-editor.js").read_text(encoding="utf-8")
    workflow_editor_surface = workflow_editor + workflow_editor_js
    assert "workflow_graph" in workflow_editor_surface
    assert "nodes" in workflow_editor_surface
    assert "edges" in workflow_editor_surface
    assert "input/output ports" in workflow_editor_surface
    assert "TRUE/FALSE branch" in workflow_editor_surface
    assert "start_node_id" in workflow_editor_surface
    assert "nested AND/OR" in workflow_editor_surface or "Nested AND" in workflow_editor_surface
    assert 'data-add="logic"' in workflow_editor_surface
    assert 'data-add="condition"' in workflow_editor_surface
    assert 'data-add="action"' in workflow_editor_surface
    assert 'data-add="control"' in workflow_editor_surface
    assert "data-port-node" in workflow_editor_surface
    assert "data-graph-canvas" in workflow_editor_surface
    assert 'draggable="true"' in workflow_editor_surface
    assert "function handleClick" in workflow_editor_surface
    assert "function handleDrop" in workflow_editor_surface
    assert "function handleInput" in workflow_editor_surface
    assert "HackmeTradingWorkflowEditor" in workflow_editor_surface


def test_trading_reference_polling_does_not_overwrite_live_execution_price():
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")

    assert 'Reference-price polling is for the chart only.' in trading_js
    assert 'market.manual_price_points = Number(last.close_points || 0);' not in trading_js
    assert 'market.price_source = json.source || "binance_public_api";' not in trading_js


def test_trading_live_price_polling_uses_two_second_timer_and_health_badges():
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert "tradingLivePriceTimer = setInterval" in trading_js
    assert "TRADING_LIVE_PRICE_REFRESH_MS" in trading_js
    assert 'currentModuleTab !== "trading" && currentModuleTab !== "economy"' in trading_js
    assert "function tradingLivePriceTargetSymbols()" in trading_js
    assert "function refreshTradingWalletLiveMetrics()" in trading_js
    assert "refreshTradingWalletLiveMetrics();" in trading_js
    assert "tradingState.state = state;" in trading_js
    assert "const marginSummary = payload.margin_summary || tradingLiveMarginSummary(marginPositions);" in trading_js
    assert "const liveRisk = tradingLiveMarginRisk(row);" in trading_js
    assert "#trading-current-price.trading-price-up" in styles
    assert "#trading-current-price.trading-price-down" in styles
    assert "#trading-current-health.warning" in styles


def test_spot_position_details_show_holding_cost_and_break_even_price():
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")

    assert "function tradingSpotHoldingCost(position, market)" in trading_js
    assert "function tradingSpotHoldingCostPerUnit(position, market)" in trading_js
    assert "function tradingSpotBreakEvenExitPrice(position, market)" in trading_js
    assert "持有成本" in trading_js
    assert "損益平均價格" in trading_js
    assert "單顆" in trading_js
    assert "已含預估賣出手續費" in trading_js
    assert "risk-grade 價計算未實現盈虧" in trading_js


def test_trading_ui_labels_reference_and_risk_grade_price_usage():
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")
    trading_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    assert "function tradingMarketPriceContext" in trading_js
    assert "function tradingPriceContextSummary" in trading_js
    assert "目前價格（reference）" in trading_html
    assert "用途：展示 / 一般估值" in trading_html
    assert "市價單估值採用風控級價格" in trading_js
    assert "風控級價格用途：融資 / 強平 / 保證金 / PnL" in trading_js
    assert "目前部位價值採 reference price；未實現盈虧採 risk-grade price" in trading_js
    assert "reference price：" in trading_js
