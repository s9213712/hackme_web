from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_admin_settings_distinguish_comfyui_credits_from_site_points():
    html = _read("public/index.html")

    assert "ComfyUI 官方 credits 不是本站積分" in html
    assert "Settings / Credits" in html
    assert "本站錢包、交易所體驗金與任務獎勵不能支付" in html


def test_runtime_status_mentions_official_credits_not_site_points():
    js = _read("public/js/36-comfyui.js")

    assert "官方 credits 請至 ComfyUI UI 的 Settings / Credits 查看" in js
    assert "ComfyUI credits 不是本站積分" in js


def test_paid_workflow_confirmation_names_official_credits():
    js = _read("public/js/36-comfyui-workflows.js")

    assert "ComfyUI 官方 credits，不會扣本站積分" in js
    assert "餘額與購買請到 ComfyUI UI 的 Settings / Credits 查看" in js
