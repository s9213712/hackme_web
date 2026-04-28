from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_community_composers_are_button_opened_not_permanent():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    community_js = (ROOT / "public" / "js" / "25-community.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="community-announcement-open-btn"' in index_html
    assert 'id="tab-module-announcements"' in index_html
    assert 'id="module-announcements"' in index_html
    assert 'id="community-announcement-cancel-btn"' in index_html
    assert index_html.index('id="module-announcements"') < index_html.index('id="module-community"')
    assert 'id="community-board-request-open-btn"' in index_html
    assert 'id="community-board-request-cancel-btn"' in index_html
    assert 'id="community-thread-create-open-btn"' in index_html
    assert 'id="community-thread-create-cancel-btn"' in index_html
    assert 'id="community-tools-panel" class="community-tools-drawer" style="display:none;"' in index_html
    assert 'id="community-review-area" class="community-review-area" style="display:none;"' in index_html
    assert 'id="community-board-stage"' in index_html
    assert 'id="community-thread-stage" class="community-stage" style="display:none;"' in index_html
    assert 'id="community-detail-stage" class="community-stage" style="display:none;"' in index_html
    assert 'id="community-board-request-panel" style="display:none;"' in index_html
    assert 'id="community-thread-creator" style="display:none;"' in index_html

    assert "communityAnnouncementEditorOpen = false" in community_js
    assert "communityBoardRequestOpen = false" in community_js
    assert "communityThreadCreatorOpen = false" in community_js
    assert 'communityMode = "boards"' in community_js
    assert "reactToCommunityThread" in community_js
    assert "rewardCommunityThread" in community_js
    assert "penalizeCommunityPost" in community_js
    assert 'switchModuleTab("announcements")' in bootstrap_js
    assert "toggleCommunityAnnouncementEditor(true)" in bootstrap_js
    assert "toggleCommunityBoardRequest(true)" in bootstrap_js
    assert "toggleCommunityThreadCreator(true)" in bootstrap_js
