"""§13 phased rollout acceptance — end-to-end pipeline through every gate.

Ties Phase 1-6 modules together as the spec promises:
  sanitize → analyze → capability → allowlist → inputs → safety → audit ready.

Each fixture exercises the contract end-to-end so a regression in any
phase trips a high-signal failing test (instead of having to chase a
silent silent capability/allowlist drift across 4 modules).
"""

import json

import pytest

from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.capability import (
    check_workflow_capability,
    reset_object_info_cache,
)
from services.comfyui.template.cleanup import (
    cleanup_run_temp_files,
    list_active_run_dirs,
    register_run_dir,
    reset_registry,
)
from services.comfyui.template.run_gate import (
    RunGateFailure,
    run_workflow_through_gates,
)
from services.comfyui.template.safety import enforce_allowlist
from services.comfyui.validation.sanitize import sanitize_workflow_json
from tests.comfyui.fixtures.workflows import (
    controlnet_canny,
    img2img_basic,
    inpaint_basic,
    txt2img_basic,
)


@pytest.fixture(autouse=True)
def _isolate_state():
    reset_object_info_cache()
    reset_registry()
    yield
    reset_object_info_cache()
    reset_registry()


def _client(*, classes, models=None):
    info = {cls: {"input": {"required": {}}} for cls in classes}
    if models is not None:
        for class_type, input_name in (
            ("CheckpointLoaderSimple", "ckpt_name"),
            ("VAELoader", "vae_name"),
            ("LoraLoader", "lora_name"),
            ("ControlNetLoader", "control_net_name"),
            ("UpscaleModelLoader", "model_name"),
        ):
            if class_type in info:
                info[class_type]["input"]["required"][input_name] = [list(models)]
    if "KSampler" in info:
        info["KSampler"]["input"]["required"]["sampler_name"] = [["euler"]]
        info["KSampler"]["input"]["required"]["scheduler"] = [["normal"]]

    class _Stub:
        base_url = "http://stub"
        def get_object_info(self):
            return info
    return _Stub()


def _all_classes(workflow):
    return {node["class_type"] for node in workflow.values()}


def _models_for(workflow):
    return [
        node["inputs"][f]
        for node in workflow.values()
        for f in ("ckpt_name", "vae_name", "lora_name", "control_net_name", "model_name")
        if f in node.get("inputs", {}) and isinstance(node["inputs"][f], str)
    ]


def _full_inputs_for(workflow):
    """Build a user_inputs dict covering every required scalar input the
    analyzer exposes for the given fixture."""
    analysis = analyze_workflow_json(workflow)
    out: dict[str, dict] = {}
    for f in analysis.user_inputs:
        if (f.class_type, f.input_name) == ("SaveImage", "filename_prefix"):
            continue
        # PROTECTED_IMAGE_INPUTS go via image_field_assignments, not user_inputs
        if f.class_type in {"LoadImage", "LoadImageMask"}:
            continue
        bucket = out.setdefault(f.node_id, {})
        bucket[f.input_name] = f.raw_value
    return out


def _stub_upload(*, file_row, target_filename, run_id):
    return {"filename": target_filename, "subfolder": run_id, "type": "input"}


def _file_row(**overrides):
    base = {
        "id": "f-1",
        "owner_user_id": 1,
        "storage_path": "/tmp/cat.png",
        "privacy_mode": "standard_plain",
        "scan_status": "clean",
        "original_filename_plain_for_public": "cat.png",
        "mime_type_plain_for_public": "image/png",
        "size_bytes": 2048,
        "deleted_at": None,
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------------
# Phase 1 acceptance: every fixture clears sanitize + analyze + allowlist
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [txt2img_basic, img2img_basic, inpaint_basic, controlnet_canny],
)
def test_phase1_each_fixture_clears_static_pipeline(factory):
    workflow = factory()
    sanitize_workflow_json(workflow)  # §3
    analysis = analyze_workflow_json(workflow)  # §5
    enforce_allowlist(analysis)  # §7.1


# ----------------------------------------------------------------------------
# Phase 2 acceptance: capability tri-state behavior
# ----------------------------------------------------------------------------


def test_phase2_supported_when_local_has_everything():
    workflow = txt2img_basic()
    classes = _all_classes(workflow)
    models = _models_for(workflow)
    cap = check_workflow_capability(
        analyze_workflow_json(workflow),
        client=_client(classes=classes, models=models),
    )
    assert cap.overall == "SUPPORTED"


def test_phase2_partially_supported_when_only_models_missing():
    workflow = txt2img_basic()
    cap = check_workflow_capability(
        analyze_workflow_json(workflow),
        client=_client(classes=_all_classes(workflow), models=["different.safetensors"]),
    )
    assert cap.overall == "PARTIALLY_SUPPORTED"


def test_phase2_unsupported_when_class_missing_locally():
    workflow = txt2img_basic()
    minimal = _client(classes={"CheckpointLoaderSimple"}, models=_models_for(workflow))
    cap = check_workflow_capability(analyze_workflow_json(workflow), client=minimal)
    assert cap.overall == "UNSUPPORTED"


# ----------------------------------------------------------------------------
# Phase 6 acceptance: end-to-end 5-gate run
# ----------------------------------------------------------------------------


def test_phase6_happy_path_txt2img_runs_through_all_five_gates():
    workflow = txt2img_basic()
    result = run_workflow_through_gates(
        raw_workflow=workflow,
        user_inputs=_full_inputs_for(workflow),
        image_field_assignments={},
        actor={"id": 1, "username": "alice"},
        user_id=1,
        run_id="run123",
        conn=None,
        comfyui_client=_client(classes=_all_classes(workflow), models=_models_for(workflow)),
        upload_callback=_stub_upload,
    )
    assert result.workflow["9"]["inputs"]["filename_prefix"] == "hackme/1/run123"
    assert result.capability.overall == "SUPPORTED"


def test_phase6_img2img_with_image_assignment_remaps_load_image():
    workflow = img2img_basic()
    file_rows = {"f-1": _file_row()}
    result = run_workflow_through_gates(
        raw_workflow=workflow,
        user_inputs=_full_inputs_for(workflow),
        image_field_assignments={"10": "f-1"},
        actor={"id": 1, "username": "alice"},
        user_id=1,
        run_id="run9",
        conn=None,
        comfyui_client=_client(classes=_all_classes(workflow), models=_models_for(workflow)),
        upload_callback=_stub_upload,
        fetch_file_row=lambda _conn, fid: file_rows.get(fid),
    )
    assert result.workflow["10"]["inputs"]["image"] == "run9/1_run9_10.png"
    assert result.audit_metadata["image_remapped"] == 1


def test_phase6_protected_image_input_overwrite_attempt_hard_fails():
    workflow = img2img_basic()
    user_inputs = _full_inputs_for(workflow)
    # Adversarial: try to write the LoadImage.image directly
    user_inputs["10"] = {"image": "/etc/passwd"}
    file_rows = {"f-1": _file_row()}
    with pytest.raises(RunGateFailure) as exc_info:
        run_workflow_through_gates(
            raw_workflow=workflow,
            user_inputs=user_inputs,
            image_field_assignments={"10": "f-1"},
            actor={"id": 1},
            user_id=1,
            run_id="r",
            conn=None,
            comfyui_client=_client(classes=_all_classes(workflow), models=_models_for(workflow)),
            upload_callback=_stub_upload,
            fetch_file_row=lambda _conn, fid: file_rows.get(fid),
        )
    # Either Gate 4 (constraints) or Gate 5 (PROTECTED_IMAGE_INPUTS) — both
    # reject. The spec demands hard fail anywhere along the way.
    assert exc_info.value.gate in (4, 5)


def test_phase6_run_id_registered_for_cleanup():
    """Gate 5 calling register_run_dir before remap means even if remap
    fails the cleanup sweeper has a row to reap (§10.3.2)."""
    workflow = img2img_basic()
    file_rows = {"f-1": _file_row()}
    run_workflow_through_gates(
        raw_workflow=workflow,
        user_inputs=_full_inputs_for(workflow),
        image_field_assignments={"10": "f-1"},
        actor={"id": 1, "username": "alice"},
        user_id=1,
        run_id="run42",
        conn=None,
        comfyui_client=_client(classes=_all_classes(workflow), models=_models_for(workflow)),
        upload_callback=_stub_upload,
        fetch_file_row=lambda _conn, fid: file_rows.get(fid),
    )
    active = [e.run_id for e in list_active_run_dirs()]
    assert "run42" in active


def test_phase6_cleanup_purges_run_id_from_registry():
    register_run_dir(run_id="ghost", user_id=7)
    ok = cleanup_run_temp_files(
        run_id="ghost",
        user_id=7,
        cleanup_callback=lambda **_: True,
    )
    assert ok is True
    assert "ghost" not in [e.run_id for e in list_active_run_dirs()]


# ----------------------------------------------------------------------------
# Phase 13 acceptance summary: every Phase a "completion checkbox"
# ----------------------------------------------------------------------------


def test_acceptance_summary_phases_implemented():
    """High-signal smoke confirming every Phase exposes its public surface
    so a future regression that ablates a module doesn't slip past CI."""
    from services.comfyui.template import (
        # Phase 1
        analyze_workflow_json,
        is_allowed_class,
        # Phase 2
        check_workflow_capability,
        # Phase 3
        enforce_allowlist,
        rewrite_save_image_prefix,
        # Phase 3.5
        remap_load_image_to_cloud_file,
        # Phase 4a
        DatabasePreviewStore,
        InMemoryPreviewStore,
        get_default_preview_store,
        # Phase 6
        run_workflow_through_gates,
        # §10.3.2
        cleanup_run_temp_files,
        sweep_orphaned_run_dirs,
        # §11
        errors,
        # §18.1
        seed_default_comfyui_workflows,
        list_runtime_workflows,
    )
    assert callable(analyze_workflow_json)
    assert callable(is_allowed_class)
    assert callable(check_workflow_capability)
    assert callable(enforce_allowlist)
    assert callable(rewrite_save_image_prefix)
    assert callable(remap_load_image_to_cloud_file)
    assert callable(DatabasePreviewStore)
    assert callable(get_default_preview_store)
    assert callable(run_workflow_through_gates)
    assert callable(cleanup_run_temp_files)
    assert callable(sweep_orphaned_run_dirs)
    assert callable(seed_default_comfyui_workflows)
    assert callable(list_runtime_workflows)
    assert hasattr(errors, "Stage")


def test_acceptance_summary_settings_flags_registered():
    from services.platform.settings import DEFAULT_SETTINGS, FEATURE_FLAG_KEYS
    assert "feature_comfyui_legacy_import_enabled" in FEATURE_FLAG_KEYS
    assert "feature_comfyui_template_importer_strict" in FEATURE_FLAG_KEYS
    # Defaults match §15 rollout intent
    assert DEFAULT_SETTINGS["feature_comfyui_legacy_import_enabled"] is True
    assert DEFAULT_SETTINGS["feature_comfyui_template_importer_strict"] is False


def test_acceptance_summary_route_exports_present():
    from routes.comfyui_sections import (
        register_comfyui_admin_routes,
        register_comfyui_template_routes,
        register_comfyui_workflow_routes,
    )
    assert callable(register_comfyui_admin_routes)
    assert callable(register_comfyui_template_routes)
    assert callable(register_comfyui_workflow_routes)


def test_acceptance_summary_frontend_module_present():
    """Phase 5 frontend must export the importer namespace."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    js = (repo / "public" / "js" / "36-comfyui.js").read_text(encoding="utf-8")
    assert "ComfyUITemplateImporter" in js
    assert "/api/comfyui/templates/preview" in js
    assert "/api/comfyui/templates/import" in js
