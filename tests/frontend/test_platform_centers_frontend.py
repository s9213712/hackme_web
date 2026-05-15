from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_platform_center_frontend_surfaces_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    platform_js = (ROOT / "public" / "js" / "57-platform-centers.js").read_text(encoding="utf-8")

    assert 'id="tab-module-jobs"' in index_html
    assert 'id="module-jobs"' in index_html
    assert 'id="tab-module-shares"' not in index_html
    assert 'id="module-shares"' in index_html
    assert 'id="share-center-events"' in index_html
    assert 'data-share-center-tab="links"' in index_html
    assert 'data-share-center-tab="videos"' in index_html
    assert 'id="video-manage-list"' in index_html
    assert 'id="video-manage-platform-fee"' in index_html
    assert 'id="economy-asset-admin-risk"' in index_html
    assert "/js/57-platform-centers.js" in index_html
    assert 'module: "jobs"' in core_js
    assert 'label: "分享管理", action: "module:shares", moduleKey: "shares"' in core_js
    assert 'label: "任務中心", group: "管理"' in core_js
    assert 'switchModuleTab("jobs")' in admin_js or 'normTab === "jobs"' in admin_js
    assert 'normTab === "videos" || normTab === "shares"' in admin_js
    assert 'loadJobCenter()' in platform_js
    assert 'loadDriveTaskCenterJobs({ csrf })' in platform_js
    assert 'mergePlatformJobCenterJobs([...jobs, ...driveJobs])' in platform_js
    assert 'loadShareCenter()' in platform_js
    assert 'loadVideoManageCenter()' in platform_js
    assert 'function renderVideoManageCenter' in platform_js
    assert '/videos/manage?limit=120' in platform_js
    assert '/boost' in platform_js
    assert 'data-video-manage-save' in platform_js
    assert 'data-video-manage-delete' in platform_js
    assert 'data-video-manage-boost' in platform_js
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
    assert 'currentUser === "root"' in platform_js
    assert '&all=1' not in platform_js
    assert '/shares?limit=120"' in platform_js
    assert 'share-center-countdown' in platform_js
    assert '.share-center-countdown' in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert 'const timeLabel = isOpenEvent ? "開啟時間" : "時間"' in platform_js
    assert 'IP 來源：${sanitize(ip)}' in platform_js
    assert 'event.source_ip || event.ip' in platform_js
    assert '.share-center-event-row' in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert '.video-manage-row' in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert '/admin/trading/asset-overview' in platform_js
    assert '交易資產總覽讀取失敗' in platform_js
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    assert 'function loadDriveTaskCenterJobs' in drive_js
    assert 'driveRemoteTaskToJobCenterJob' in drive_js
    assert 'driveTransferToJobCenterJob' in drive_js
    assert 'source_ref: json.file?.file_id ? `cloud_file:${json.file.file_id}` : ""' in drive_js
