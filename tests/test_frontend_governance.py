from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_governance_target_uses_member_select():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert '<select id="governance-target-user-id">' in index_html
    assert 'placeholder="目標 user id"' not in index_html
    assert "/js/50-admin.js?v=20260429-restart-button" in index_html
    assert "/js/90-bootstrap.js?v=20260429-root-storage-override" in index_html
    assert "function renderGovernanceTargetOptions" in admin_js
    assert "請選擇治理目標" in admin_js
    assert "target_user_id: targetId" in admin_js
    assert "請選擇治理目標並填寫提案原因" in admin_js
    assert "<label>處理對象</label>" in index_html
    assert "<label>處理方式</label>" in index_html
    assert "<label>動作值</label>" in index_html
    assert "<label>投票規則</label>" in index_html
    assert "<label>需要同意票數</label>" not in index_html
    assert "<label>投票期限（小時）</label>" in index_html
    assert "<label>提案原因</label>" in index_html
    assert "記違規警告" in index_html
    assert "限制功能" in index_html
    assert "調整會員等級" in index_html
    assert 'id="governance-action-value-help"' in index_html
    assert "GOVERNANCE_ACTION_VALUE_HELP" in admin_js
    assert "GOVERNANCE_HIGH_RISK_ACTIONS" in admin_js
    assert "governancePolicySummary" in admin_js
    assert "function updateGovernanceActionValueHelp" in admin_js
    assert "newbie / normal / restricted / suspended" in admin_js
    assert "required_votes:" not in admin_js
    assert "root override" not in admin_js
