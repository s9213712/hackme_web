from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_transaction_dispute_frontend_uses_account_bound_official_hot_proof():
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")

    assert "function economyWalletSupportsAccountBoundDisputeProof" in economy_js
    assert 'wallet_type || "") === "official_hot"' in economy_js
    assert 'custody_mode || "") === "server_hot"' in economy_js
    assert "account_bound_proof: !!proof.account_bound_proof" in economy_js
    assert "使用帳號持有狀態建立疑義，不要求私鑰" in economy_js
    assert "使用帳號持有狀態回覆，不要求私鑰" in economy_js
    assert "root 帳號不使用匿名地址疑義流程" in economy_js
    assert "官方錢包或官方地址事故請改走官方治理" in economy_js
    assert "ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS = 12" in economy_js
    assert "function economyPromptAddressDisputeStatement" in economy_js
    assert "疑義交易說明太短" in economy_js
    assert "To 地址回覆太短" in economy_js
    assert "至少 ${ECONOMY_ADDRESS_DISPUTE_MIN_STATEMENT_CHARS} 字" in economy_js
    assert "等待 From 地址本機簽署疑義交易" in economy_js
    assert "createEconomyTransactionDispute(btn.dataset.disputeTx || \"\")" not in economy_js
    notifications_js = (ROOT / "public" / "js" / "32-notifications.js").read_text(encoding="utf-8")
    notifications_service = (ROOT / "services" / "system" / "notifications.py").read_text(encoding="utf-8")
    assert "points_chain_dispute_reply" in notifications_js
    assert "data-notification-dispute-reply" in notifications_js
    assert "replyEconomyTransactionDispute" in notifications_js
    assert '"metadata": metadata' in notifications_service


def test_governance_frontend_has_status_tabs_and_inline_dispute_voting():
    economy_js = (ROOT / "public" / "js" / "55-economy.js").read_text(encoding="utf-8")
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    assert 'id="economy-governance-status-tabs"' in index_html
    assert 'data-governance-status-filter="review"' in index_html
    assert 'data-governance-status-filter="voting"' in index_html
    assert 'data-governance-status-filter="closed"' in index_html
    assert "公共投票與疑義事件總看板" in index_html
    assert 'id="economy-governance-public-count"' in index_html
    assert 'id="economy-governance-dispute-count"' in index_html
    assert index_html.index('id="economy-governance-card"') < index_html.index('id="economy-dispute-card"')
    assert index_html.index('id="economy-governance-list"') < index_html.index('id="economy-public-governance-create-details"')
    assert "let economyGovernanceStatusFilter" in economy_js
    assert "function updateEconomyGovernanceOverviewCounts" in economy_js
    assert "economy-governance-public-status" in economy_js
    assert "economy-governance-dispute-status" in economy_js
    assert "function economyGovernanceStatusBucket" in economy_js
    assert "function economyRenderGovernanceProposalCard" in economy_js
    assert "let economyExpandedGovernanceProposalUuids" in economy_js
    assert "function toggleEconomyGovernanceProposal" in economy_js
    assert "data-governance-toggle-proposal" in economy_js
    assert "economy-governance-proposal-action-panel" in economy_js
    assert "提案投票 / 執行操作" in economy_js
    assert "economy-dispute-governance-panel" in economy_js
    assert "economy-dispute-governance-materials" in economy_js
    assert "疑義交易雙方材料" in economy_js
    assert "To 尚未回覆" in economy_js
    assert 'String(proposal.reference || "").startsWith("transaction_dispute:")' in economy_js
    assert 'economyGovernanceCategory !== "dispute"' in economy_js
    assert "economySelectedDisputeProposalUuids.has" in economy_js
    assert "bindEconomyGovernanceEvents(list)" in economy_js
    assert "scrollIntoView" not in economy_js[economy_js.index("function bindEconomyDisputeEvents"):economy_js.index("async function submitEconomyWalletTransfer")]


def test_admin_user_list_shows_official_hot_wallet_for_manager_only():
    users_route = (ROOT / "routes" / "users.py").read_text(encoding="utf-8")
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")

    assert "official_hot_wallet_address" in users_route
    assert "points_wallet_identities" in users_route
    assert "wallet_type='official_hot'" in users_route
    assert "custody_mode='server_hot'" in users_route
    assert "官方熱錢包：" in users_js
    assert "u.official_hot_wallet_address" in users_js
    assert "currentRole === \"manager\" || currentRole === \"super_admin\"" in users_js
