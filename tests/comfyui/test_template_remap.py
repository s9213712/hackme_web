"""Remap regression for the ComfyUI template importer (§7.3 + §10.3.3)."""

import pytest

from routes.comfyui_sections.workflow_routes import _default_upload_callback
from services.comfyui.template.remap import (
    PROTECTED_IMAGE_INPUTS,
    SafetyError,
    remap_load_image_to_cloud_file,
)


def _row(**overrides):
    """Build a minimal uploaded_files row with §7.3-compatible defaults."""
    base = {
        "id": "f-1",
        "owner_user_id": 7,
        "storage_path": "/tmp/uploaded/f-1.png",
        "privacy_mode": "standard_plain",
        "risk_level": "low",
        "scan_status": "clean",
        "original_filename_plain_for_public": "cat.png",
        "mime_type_plain_for_public": "image/png",
        "size_bytes": 1024,
        "deleted_at": None,
    }
    base.update(overrides)
    return base


def _stub_fetch(rows_by_id):
    """Return a fetch_file_row callable that reads from a dict."""
    def _fetch(_conn, cloud_file_id):
        return rows_by_id.get(cloud_file_id)
    return _fetch


def _stub_upload(*, file_row, target_filename, run_id):
    """Pretend ComfyUI accepted the upload and returned its filename."""
    return {"filename": target_filename, "subfolder": run_id, "type": "input"}


WORKFLOW_WITH_LOAD_IMAGE = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "user_path.png"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["X", 1]}},
    "3": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["X", 0]}},
}


def test_protected_inputs_set_matches_spec():
    """Mirror the spec's PROTECTED_INPUTS list (§10.3.3)."""
    assert PROTECTED_IMAGE_INPUTS == frozenset({
        ("LoadImage", "image"),
        ("LoadImageMask", "image"),
        ("LoadImageMask", "mask"),
    })


def test_remap_replaces_load_image_value_and_does_not_mutate_input():
    rows = {"f-1": _row()}
    out = remap_load_image_to_cloud_file(
        WORKFLOW_WITH_LOAD_IMAGE,
        image_field_assignments={"1": "f-1"},
        actor={"id": 7},
        conn=None,
        run_id="run9",
        upload_callback=_stub_upload,
        fetch_file_row=_stub_fetch(rows),
    )
    assert out["1"]["inputs"]["image"] == "run9/7_run9_1.png"
    # original unchanged
    assert WORKFLOW_WITH_LOAD_IMAGE["1"]["inputs"]["image"] == "user_path.png"


def test_remap_rejects_workflow_with_unfilled_protected_node():
    rows = {"f-1": _row()}
    with pytest.raises(SafetyError, match="沒有指定圖片來源"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={},  # node "1" needs assignment but didn't get one
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_assignment_for_non_load_image_node():
    rows = {"f-1": _row()}
    with pytest.raises(SafetyError, match="不存在或非 LoadImage"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1", "2": "f-1"},  # "2" is CLIPTextEncode
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_other_owner():
    rows = {"f-1": _row(owner_user_id=99)}
    with pytest.raises(SafetyError, match="不屬於你"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_missing_file_row():
    with pytest.raises(SafetyError, match="不存在或已刪除"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "missing-id"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch({}),
        )


def test_remap_rejects_deleted_file():
    rows = {"f-1": _row(deleted_at="2026-05-08T12:00:00")}
    with pytest.raises(SafetyError, match="已刪除"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_non_standard_plain_privacy_mode():
    rows = {"f-1": _row(privacy_mode="e2ee")}
    with pytest.raises(SafetyError, match="standard_plain"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_disallowed_mime():
    rows = {"f-1": _row(mime_type_plain_for_public="image/heic")}
    with pytest.raises(SafetyError, match="MIME"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_disallowed_extension():
    rows = {"f-1": _row(original_filename_plain_for_public="cat.heic")}
    with pytest.raises(SafetyError, match="副檔名"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_oversize_file():
    rows = {"f-1": _row(size_bytes=99 * 1024 * 1024)}  # 99 MiB
    with pytest.raises(SafetyError, match="超過上限"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_unscanned_when_skip_not_allowed():
    rows = {"f-1": _row(scan_status="skipped")}
    with pytest.raises(SafetyError, match="未通過安全掃描"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
            upload_scan_skip_allowed=False,
        )


def test_remap_accepts_skipped_scan_when_root_opted_in():
    rows = {"f-1": _row(scan_status="skipped")}
    out = remap_load_image_to_cloud_file(
        WORKFLOW_WITH_LOAD_IMAGE,
        image_field_assignments={"1": "f-1"},
        actor={"id": 7},
        conn=None,
        run_id="r",
        upload_callback=_stub_upload,
        fetch_file_row=_stub_fetch(rows),
        upload_scan_skip_allowed=True,
    )
    assert out["1"]["inputs"]["image"].startswith("r/7_r_1.")


def test_remap_decode_failure_propagates_as_safety_error():
    rows = {"f-1": _row()}

    def _bad_decoder(_bytes):
        raise ValueError("not an image")

    with pytest.raises(SafetyError, match="解碼失敗"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
            image_decoder=_bad_decoder,
            file_bytes_loader=lambda _row: b"\x00\x01",
        )


def test_remap_rejects_empty_run_id():
    rows = {"f-1": _row()}
    with pytest.raises(SafetyError, match="run_id"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_missing_actor_id():
    rows = {"f-1": _row()}
    with pytest.raises(SafetyError, match="actor.id"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={},
            conn=None,
            run_id="r",
            upload_callback=_stub_upload,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_rejects_upload_callback_returning_no_filename():
    rows = {"f-1": _row()}

    def _bad_callback(*, file_row, target_filename, run_id):
        return {"filename": "", "subfolder": run_id}

    with pytest.raises(SafetyError, match="未取得檔名"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_bad_callback,
            fetch_file_row=_stub_fetch(rows),
        )


def test_remap_converts_upload_callback_error_to_safety_error():
    rows = {"f-1": _row()}

    def _failing_callback(*, file_row, target_filename, run_id):
        raise RuntimeError("connection reset")

    with pytest.raises(SafetyError, match="上傳圖片到 ComfyUI 失敗"):
        remap_load_image_to_cloud_file(
            WORKFLOW_WITH_LOAD_IMAGE,
            image_field_assignments={"1": "f-1"},
            actor={"id": 7},
            conn=None,
            run_id="r",
            upload_callback=_failing_callback,
            fetch_file_row=_stub_fetch(rows),
        )


def test_default_workflow_upload_callback_surfaces_comfyui_errors(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"png-bytes")

    class _FailingClient:
        def upload_image_bytes(self, *args, **kwargs):
            raise RuntimeError("connection reset")

    callback = _default_upload_callback(_FailingClient())
    with pytest.raises(RuntimeError, match="connection reset"):
        callback(
            file_row={"storage_path": str(source)},
            target_filename="target.png",
            run_id="run1",
        )


def test_default_workflow_upload_callback_rejects_empty_source(tmp_path):
    source = tmp_path / "empty.png"
    source.write_bytes(b"")
    callback = _default_upload_callback(object())
    with pytest.raises(RuntimeError, match="內容為空"):
        callback(
            file_row={"storage_path": str(source)},
            target_filename="target.png",
            run_id="run1",
        )


def test_remap_handles_load_image_mask_node():
    workflow = {
        "1": {"class_type": "LoadImageMask", "inputs": {"image": "x.png", "channel": "alpha"}},
        "2": {"class_type": "VAEEncodeForInpaint", "inputs": {"pixels": ["1", 0], "vae": ["X", 0]}},
    }
    rows = {"m-1": _row(id="m-1")}
    out = remap_load_image_to_cloud_file(
        workflow,
        image_field_assignments={"1": "m-1"},
        actor={"id": 7},
        conn=None,
        run_id="abc",
        upload_callback=_stub_upload,
        fetch_file_row=_stub_fetch(rows),
    )
    assert out["1"]["inputs"]["image"] == "abc/7_abc_1.png"
    # channel input untouched
    assert out["1"]["inputs"]["channel"] == "alpha"
