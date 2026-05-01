from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_points_page_is_chain_operations_console():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

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
    assert "/js/56-trading.js?v=20260501-trading-split-refresh" in index_html
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
    assert "/js/90-bootstrap.js?v=20260430-trading-page-split" in index_html
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
    assert 'adminTitle.textContent = rootMode ? "手動加減分與待審核" : "待審核獎勵"' in economy_js
    assert "加減分歷史統一在下方明細查看" in economy_js
    assert "只有 root 可以手動調整積分" in economy_js
    assert 'fetchEconomyJson("/admin/users")' in economy_js
    assert "function renderEconomyAdjustUserOptions" in economy_js
    assert "async function loadEconomyAccountLookup()" in economy_js
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
    assert 'id="root-catalog-item-key"' in index_html
    assert 'id="root-catalog-storage-gb"' in index_html
    assert 'id="root-catalog-save-btn"' in index_html
    assert "function loadRootEconomyCatalog()" in admin_js
    assert 'apiFetch(API + "/root/economy/catalog"' in admin_js
    assert "saveRootEconomyCatalogItem" in admin_js
    assert 'switchSettingsSection("billing")' in bootstrap_js


def test_trading_exchange_is_separate_from_wallet_page():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")
    economy_section = index_html.split('id="module-economy"', 1)[1].split('id="module-trading"', 1)[0]
    trading_section = index_html.split('id="module-trading"', 1)[1].split('id="module-accounts"', 1)[0]

    assert 'id="tab-module-trading"' in index_html
    assert "積分交易所" in trading_section
    assert 'id="trading-card"' in trading_section
    assert 'id="trading-submit-order-btn"' in trading_section
    assert 'id="trading-order-estimate"' in trading_section
    assert 'id="trading-order-form"' in trading_section
    assert 'id="trading-availability-note"' in trading_section
    assert 'id="trading-root-card"' in trading_section
    assert 'id="trading-funding-available"' in trading_section
    assert 'id="trading-root-reset-sim-btn"' in trading_section
    assert 'id="trading-reference-chart"' in trading_section
    assert 'id="trading-reference-tooltip"' in trading_section
    assert 'id="trading-reference-interval"' in trading_section
    assert '<option value="1s" selected>1 秒</option>' in trading_section
    assert 'id="trading-btc-trade-card"' not in trading_section
    assert 'id="trading-btc-trade-path"' not in trading_section
    assert "Binance 參考價格" in trading_section
    assert "蠟燭圖" in trading_section
    assert "root 可使用現貨與合約模擬交易" in trading_section
    assert "root 以外用戶目前僅開放" in trading_section
    assert 'id="trading-root-contract-card"' in trading_section
    assert 'id="trading-contract-open-btn"' in trading_section
    assert 'id="trading-contract-position-list"' in trading_section
    assert 'id="trading-submit-order-btn"' not in economy_section
    assert 'id="trading-root-card"' not in economy_section
    assert 'id="economy-trading-summary-card"' in economy_section
    assert 'id="economy-spot-position-quantity"' in economy_section
    assert 'id="economy-spot-position-detail-list"' in economy_section
    assert "現貨明細" in economy_section
    assert "市價平倉" in economy_section
    assert "現貨部位" in economy_section
    assert "各交易對分開計算" in economy_section
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
    assert "function rootVirtualSpotValue" in trading_js
    assert "function renderEconomySpotPositionDetails" in trading_js
    assert "function submitEconomySpotSell" in trading_js
    assert "data-economy-spot-limit" in trading_js
    assert "data-economy-spot-market-close" in trading_js
    assert "成本價（總額）" in trading_js
    assert "目前部位價值" in trading_js
    assert "盈虧" in trading_js
    assert "tradingSpotCostBasis" in trading_js
    assert "payload.emergency_close = true" in trading_js
    assert "手續費按平時 2 倍計算" in trading_js
    assert "function tradingOrderDraftEstimate" in trading_js
    assert "function syncTradingOrderSideTheme" in trading_js
    assert "trading-order-buy" in trading_js
    assert "trading-order-sell" in trading_js
    assert "買入下單" in trading_js
    assert "賣出下單" in trading_js
    assert ".trading-order-buy" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".trading-submit-sell" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert "function updateTradingOrderEstimate" in trading_js
    assert "超過可用" in trading_js
    assert "超過可賣現貨" in trading_js
    assert "economy-root-virtual-total" in trading_js
    assert "available + spotValue" in trading_js
    assert "function loadTradingReferencePrices" in trading_js
    assert "function restartTradingReferenceAutoRefresh" in trading_js
    assert "function tradingReferenceAutoRefreshMs" in trading_js
    assert 'interval === "1s" ? 1000 : 2000' in trading_js
    assert "loadTradingReferencePrices({ silent: true, priceOnly: true })" in trading_js
    assert "tradingReferenceChartAutoTimer" in trading_js
    assert "tradingReferenceChartAutoBusy" in trading_js
    assert "}, 5000)" in trading_js
    assert "if (!options.priceOnly) renderTradingReferenceChart(json);" in trading_js
    assert 'currentModuleTab !== "trading"' in trading_js
    assert "tradingDashboardAutoTimer" in trading_js
    assert "function renderTradingReferenceChart" in trading_js
    assert "function updateTradingReferenceTooltip" in trading_js
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
    assert "BTC/USDT、ETH/USDT" in trading_js
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
    assert '["economy-trading-open-btn", openTradingModuleFromWallet]' in trading_js
    assert '["economy-root-virtual-open-btn", openTradingModuleFromWallet]' in trading_js
