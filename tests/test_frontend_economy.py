from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_points_page_is_chain_operations_console():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="economy-user-summary-grid"' in index_html
    assert 'id="economy-user-ledger-card"' in index_html
    assert "root 私有鏈運維" in index_html
    assert 'id="economy-root-report-btn"' in index_html
    assert 'id="economy-rollback-ledger-uuid"' in index_html
    assert 'id="economy-rollback-btn"' in index_html
    assert 'id="economy-audit-list"' in index_html
    assert 'id="economy-risk-ledger-list"' in index_html
    assert 'id="economy-chain-countdown"' in index_html
    assert 'id="economy-chain-loaded-at"' in index_html
    assert 'id="economy-chain-status"' in index_html
    assert "<pre id=\"economy-chain-status\"" not in index_html
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
    assert '<select id="economy-adjust-user-id">' in index_html
    assert '<input type="number" id="economy-adjust-user-id"' not in index_html
    assert 'id="economy-adjust-currency"' not in index_html
    assert "全站積分" in index_html
    assert "加減分明細" in index_html
    assert "手動加減分與待審核" in index_html
    assert "積分系統" in index_html
    assert "/js/55-economy.js?v=20260429-ledger-backup-recovery" in index_html
    assert 'id="economy-recovery-card"' in index_html
    assert 'id="economy-backup-btn"' in index_html
    assert 'id="economy-recovery-approve-btn"' in index_html
    assert "function renderEconomyRecovery" in economy_js
    assert 'fetchEconomyJson("/root/points/chain/backups"' in economy_js
    assert 'fetchEconomyJson("/root/points/chain/recovery/approve"' in economy_js
    assert "/js/90-bootstrap.js?v=20260430-root-billing" in index_html
    assert 'const rootMode = currentUser === "root";' in economy_js
    assert 'const canManagePoints = canManageEconomyPoints();' in economy_js
    assert 'adminCard.style.display = canManagePoints ? "" : "none"' in economy_js
    assert 'if ($("economy-admin-ledger-list")) $("economy-admin-ledger-list").innerHTML = "";' in economy_js
    assert 'if ($("economy-pending-list")) $("economy-pending-list").innerHTML = "";' in economy_js
    assert 'rootMode ? "PointsChain 積分管理" : "PointsChain 積分錢包"' in economy_js
    assert 'fetchEconomyJson("/root/points/report")' in economy_js
    assert "startEconomyBlockCountdown" in economy_js
    assert "function canManageEconomyPoints()" in economy_js
    assert 'currentUser === "root" || currentRole === "manager" || currentRole === "super_admin"' in economy_js
    assert "最後更新" in economy_js
    assert "bindEconomyInlineEvents" in economy_js
    assert "economy-adjustment-list" in economy_js
    assert 'adminLedgerList.style.display = rootMode ? "none" : ""' in economy_js
    assert 'adminTitle.textContent = rootMode ? "手動加減分與待審核" : "管理員調整與審核"' in economy_js
    assert "加減分歷史統一在下方明細查看" in economy_js
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
    assert 'fetch(API + "/root/economy/catalog"' in admin_js
    assert "saveRootEconomyCatalogItem" in admin_js
    assert 'switchSettingsSection("billing")' in bootstrap_js
