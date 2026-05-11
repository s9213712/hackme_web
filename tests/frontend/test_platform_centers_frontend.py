from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_platform_center_frontend_surfaces_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    platform_js = (ROOT / "public" / "js" / "57-platform-centers.js").read_text(encoding="utf-8")

    assert 'id="tab-module-jobs"' in index_html
    assert 'id="module-jobs"' in index_html
    assert 'id="tab-module-shares"' in index_html
    assert 'id="module-shares"' in index_html
    assert 'id="share-center-events"' in index_html
    assert 'id="economy-asset-admin-risk"' in index_html
    assert "/js/57-platform-centers.js" in index_html
    assert 'module: "jobs"' in core_js
    assert 'module: "shares"' in core_js
    assert 'switchModuleTab("jobs")' in admin_js or 'normTab === "jobs"' in admin_js
    assert 'loadJobCenter()' in platform_js
    assert 'loadShareCenter()' in platform_js
    assert 'loadTradingAssetOverview()' in platform_js
    assert 'confirm("確定要取消這個任務？")' in platform_js
    assert 'parsed.origin === location.origin' in platform_js
    assert 'loadShareCenterEvents' in platform_js
    assert '/access-events' in platform_js
    assert 'function formatShareCenterCountdown(ms)' in platform_js
    assert '倒數計時：${formatShareCenterCountdown' in platform_js
    assert 'data-share-countdown-until' in platform_js
    assert 'scheduleShareCenterCountdowns()' in platform_js
    assert 'setInterval(updateShareCenterCountdowns, 1000)' in platform_js
    assert 'share-center-countdown' in platform_js
    assert '.share-center-countdown' in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert '/admin/trading/asset-overview' in platform_js
    assert '交易資產總覽讀取失敗' in platform_js
