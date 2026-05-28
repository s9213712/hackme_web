from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_nginx_template_splits_rate_limit_zones_by_traffic_plane():
    conf = (ROOT / "deploy" / "nginx" / "hackme_web.conf.example").read_text(encoding="utf-8")

    for zone in (
        "hackme_api_per_ip",
        "hackme_auth_per_ip",
        "hackme_management_per_ip",
        "hackme_upload_per_ip",
        "hackme_static_per_ip",
    ):
        assert f"zone={zone}" in conf
        assert f"limit_req zone={zone}" in conf

    assert "credential stuffing cannot consume upload or management request budget" in conf
    assert "root/admin endpoints should be async/snapshot-backed" in conf
    assert "slow-client uploads" in conf
    assert "static assets are high fan-out but cheap" in conf
    assert "proxy_request_buffering off" in conf
    assert "root/comfyui/model-upload" in conf
    assert "admin/snapshots/upload-restore" in conf
    assert "styles\\.css" in conf
