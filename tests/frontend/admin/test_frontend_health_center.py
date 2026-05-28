from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_health_center_is_grouped_into_readable_sections():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (
        (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "public" / "js" / "51-admin-server-mode-launch-check.js").read_text(encoding="utf-8")
    )

    assert 'id="server-health-workqueue"' in index_html
    assert 'id="server-health-counts"' in index_html
    assert 'id="server-health-storage"' in index_html
    assert 'id="server-health-audit"' in index_html
    assert 'id="server-health-frontend-observability"' in index_html
    assert 'id="server-health-playwright-ci"' in index_html
    assert 'class="health-dashboard"' in index_html
    assert 'class="health-summary-grid"' in index_html
    assert 'class="health-section-grid"' in index_html
    assert "待處理事項" in index_html
    assert "資料量" in index_html
    assert "儲存空間" in index_html
    assert "審計與檢查" in index_html
    assert "前端觀測" in index_html
    assert "function renderHealthRows" in admin_js
    assert "function renderRootFrontendTimingObservability" in admin_js
    assert "hackme.root.${key}.start" in admin_js
    assert "hackme.root.${key}.end" in admin_js
    assert '"first-summary"' in admin_js
    assert '"secondary-chart"' in admin_js
    assert "rootAdminTimingFinish(\"first-summary\"" in admin_js
    assert "rootAdminTimingFinish(\"secondary-chart\"" in admin_js
    assert "health-metric-card" in admin_js
    assert "health-row" in admin_js
    assert "pending_moderation_proposals" in admin_js
    assert "quarantined_files" in admin_js
    assert "Readiness:" in admin_js
    assert "Anomaly:" in admin_js
    assert "function loadPlaywrightCiHealth" in admin_js
    assert "/admin/health/playwright-ci" in admin_js
    assert "GitHub Actions" in admin_js


def test_platform_stats_render_as_charts_instead_of_metric_cards():
    admin_js = (
        (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "public" / "js" / "51-admin-server-mode-launch-check.js").read_text(encoding="utf-8")
    )

    assert "function renderPlatformBarChart" in admin_js
    assert "function renderPlatformNetChart" in admin_js
    assert "platform-stats-chart" in admin_js
    assert "platform-chart-row" in admin_js
    assert "流量與使用者" in admin_js
    assert "本月積分收支" in admin_js
    assert "本月積分淨值" in admin_js
    platform_section = admin_js.split("async function loadPlatformStats()", 1)[1]
    assert "const cards = [" not in platform_section
