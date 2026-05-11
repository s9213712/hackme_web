from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_selected_template_lora_loader_renders_interactive_controls():
    workflow_js = _read("public/js/36-comfyui-workflows.js")

    assert 'field?.class_type === "LoraLoader" && field?.input_name === "lora_name"' in workflow_js
    assert 'return { kind: "lora", nodeId: field.node_id }' in workflow_js
    assert 'data-comfyui-template-lora-node' in workflow_js
    assert "let comfyuiTemplateLoraOverrides = {};" in workflow_js
    assert "upsertComfyuiTemplateLora(nodeId, select.value)" in workflow_js
    assert "applyComfyuiPromptTerms(detail.trained_words || [])" in workflow_js
    assert "已加入 LoRA，並自動補上 trigger words" in workflow_js


def test_selected_template_lora_loader_exposes_weight_controls_and_run_inputs():
    workflow_js = _read("public/js/36-comfyui-workflows.js")
    route_py = _read("routes/comfyui_sections/workflow_routes.py")

    assert 'field?.input_name === "strength_model" || field?.input_name === "strength_clip"' in workflow_js
    assert 'data-comfyui-template-lora-strength' in workflow_js
    assert "updateComfyuiTemplateLoraStrength(nodeId, field, input.value)" in workflow_js
    assert "function collectComfyuiTemplateUserInputs(detail)" in workflow_js
    assert "user_inputs: userInputs" in workflow_js
    assert "def _apply_legacy_workflow_user_inputs(workflow_json, user_inputs):" in route_py
    assert "key not in inputs or isinstance(inputs.get(key), list)" in route_py
