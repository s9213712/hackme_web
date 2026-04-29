from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_governance_target_uses_member_select():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert '<select id="governance-target-user-id">' in index_html
    assert 'placeholder="目標 user id"' not in index_html
    assert "/js/50-admin.js?v=20260429-governance-target-select" in index_html
    assert "function renderGovernanceTargetOptions" in admin_js
    assert "請選擇治理目標" in admin_js
    assert "target_user_id: targetId" in admin_js
    assert "請選擇治理目標並填寫提案原因" in admin_js
