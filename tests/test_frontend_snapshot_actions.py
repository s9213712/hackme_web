from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_action_buttons_do_not_submit_settings_form():
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert 'type="button" data-snapshot-restore=' in admin_js
    assert 'type="button" data-snapshot-download=' in admin_js
    assert 'type="button" data-snapshot-delete=' in admin_js
    assert 'type="button" id="btn-confirm-restore"' in admin_js
    assert 'btn.addEventListener("click", (event) => {' in admin_js
    assert "event.preventDefault();" in admin_js
    assert "downloadSnapshot(id);" in admin_js
