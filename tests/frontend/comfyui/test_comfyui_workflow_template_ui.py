"""Frontend smoke checks for compact ComfyUI workflow template selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_template_details_are_hidden_until_template_selected():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")

    assert 'id="comfyui-template-summary" class="comfyui-template-summary" hidden' in html
    assert 'id="comfyui-template-panels" class="comfyui-template-panels" hidden' in html
    assert "summary.hidden = true;" in js
    assert "host.hidden = true;" in js
    assert "summary.hidden = false;" in js
    assert "host.hidden = false;" in js
    assert ".comfyui-template-detail-panel" in css


def test_workflow_template_library_cards_are_collapsed_until_opened():
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")

    assert '<details class="comfyui-workflow-item">' in js
    assert '<summary class="comfyui-workflow-item-summary">' in js
    assert '<div class="comfyui-workflow-item-body">' in js
    assert ".comfyui-workflow-item > summary" in css
    assert ".comfyui-workflow-item-body" in css
    assert ".comfyui-workflow-expand-indicator::before" in css


def test_workflow_template_cards_show_default_model_notice():
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")

    assert "function comfyuiWorkflowDefaultModelEntries" in js
    assert "function comfyuiWorkflowDefaultModelSummaryText" in js
    assert "function comfyuiWorkflowDefaultModelNoticeHtml" in js
    assert "預設模型：" in js
    assert "default_params" in js
    assert "required_models" in js
    assert "required_loras" in js
    assert "required_controlnets" in js
    assert "comfyuiWorkflowDefaultModelNoticeHtml(item, 4)" in js
    assert "comfyuiWorkflowDefaultModelNoticeHtml(detail, 8)" in js
    assert ".comfyui-workflow-default-model-notice" in css


def test_workflow_layout_builder_secondary_actions_are_collapsed():
    html = _read("public/index.html")
    css = _read("public/styles.css")

    assert 'class="comfyui-workflow-action-bar"' in html
    assert 'class="drive-file-actions comfyui-workflow-primary-actions"' in html
    assert 'id="comfyui-workflow-open-visual-btn"' in html
    assert 'id="comfyui-workflow-import-btn"' in html
    assert 'id="comfyui-workflow-update-btn"' in html
    assert '<details class="comfyui-workflow-action-menu">' in html
    assert '<summary class="btn comfyui-workflow-more-summary">更多操作</summary>' in html
    assert 'id="comfyui-workflow-new-btn"' in html
    assert 'id="comfyui-workflow-starter-txt2img-btn"' in html
    assert 'id="comfyui-workflow-load-visual-btn"' in html
    assert 'id="comfyui-workflow-export-current-btn"' in html
    assert 'id="comfyui-workflow-reset-btn"' in html

    assert ".comfyui-workflow-action-bar" in css
    assert ".comfyui-workflow-action-menu-body" in css
    assert ".comfyui-workflow-action-menu[open] > summary::after" in css


def test_direct_template_fields_are_editable_for_large_model_workflows():
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")
    assert 'return { kind: "direct", fieldId: field.id };' in js
    assert 'binding.kind === "direct"' in js
    assert "comfyuiTemplateDirectHint" in js
    assert ".comfyui-template-direct-hint" in css


def test_template_loader_model_fields_do_not_reuse_global_vae_select():
    js = _read("public/js/36-comfyui-workflows.js")
    assert 'field?.class_type === "VAELoader" && field?.input_name === "vae_name") ||' in js
    assert 'return { kind: "readonly" };' in js
    assert 'field?.class_type === "VAELoader" && field?.input_name === "vae_name") return { kind: "field", targetId: "comfyui-vae-select" };' not in js
    assert 'binding.targetId === "comfyui-vae-select"' not in js


def test_template_cards_do_not_sync_through_legacy_manual_fields():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui-workflows.js")

    assert "執行時只使用下方模板卡片的值" in js
    assert 'let comfyuiTemplateFieldOverrides = {};' in js
    assert 'if (legacy) legacy.style.display = "none";' in js
    assert "hidden.value = el.value" not in js
    assert "setComfyuiFieldValue(binding.targetId" not in js
    assert "通用生成設定" in html
    assert "非 workflow 模板模式使用；選擇模板後只使用模板卡片內的欄位。" in html


def test_share_metadata_is_prompted_only_when_sharing():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")

    assert "comfyui-share-title" not in html
    assert "comfyui-share-note" not in html
    assert "comfyui-share-title" not in js
    assert "comfyui-share-note" not in js
    assert "function promptComfyuiShareMetadata()" in js
    assert 'window.prompt("分享標題"' in js
    assert 'window.prompt("心得留言（可留空）"' in js


def test_seed_after_generation_mode_is_available_for_generate_and_templates():
    html = _read("public/index.html")
    comfyui_js = _read("public/js/36-comfyui.js")
    workflow_js = _read("public/js/36-comfyui-workflows.js")

    assert 'id="comfyui-seed-after-generate"' in html
    assert '<option value="random">生成後隨機</option>' in html
    assert '<option value="fixed" selected>固定</option>' in html
    assert '<option value="increment">+1</option>' in html
    assert '<option value="decrement">-1</option>' in html
    assert '"comfyui-seed-after-generate"' in comfyui_js
    assert "function applyComfyuiSeedAfterGenerate" in comfyui_js
    assert "function comfyuiSeedAfterGenerateMode" in comfyui_js
    assert "function setComfyuiSeedAfterGenerateMode" in comfyui_js
    assert "randomComfyuiSeedForUi" in comfyui_js
    assert "currentSelectedComfyuiTemplateSeedValue" in comfyui_js
    assert "applyComfyuiSeedAfterGenerate(generated[generated.length - 1]?.seed);" in comfyui_js
    assert 'if (typeof applyComfyuiSeedAfterGenerate === "function") applyComfyuiSeedAfterGenerate(images[images.length - 1]?.seed);' in workflow_js
    assert "function comfyuiTemplateFieldIsSeed" in workflow_js
    assert "function currentSelectedComfyuiTemplateSeedValue" in workflow_js
    assert "function renderComfyuiTemplateSeedAfterGenerateControl" in workflow_js
    assert 'data-comfyui-template-seed-after-generate="1"' in workflow_js
    assert "setComfyuiSeedAfterGenerateMode(select.value)" in workflow_js


def test_template_prompts_ask_before_global_sharing_multiple_fields():
    workflow_js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")

    assert 'let comfyuiTemplatePromptShareMode = "independent";' in workflow_js
    assert "function comfyuiTemplateNeedsPromptSharingChoice" in workflow_js
    assert "function renderComfyuiTemplatePromptSharingControl" in workflow_js
    assert 'data-comfyui-template-prompt-sharing="1"' in workflow_js
    assert "請先選擇是否全域共用提示詞" in workflow_js
    assert "syncComfyuiTemplateSharedPromptFields" in workflow_js
    assert 'data-comfyui-template-prompt-role="${sanitize(binding.promptRole)}"' in workflow_js
    assert ".comfyui-template-prompt-sharing" in css


def test_template_local_images_are_imported_before_safe_remap_gate():
    comfyui_js = _read("public/js/36-comfyui.js")
    workflow_js = _read("public/js/36-comfyui-workflows.js")

    assert 'apiFetch(API + "/comfyui/import-uploaded-image"' in comfyui_js
    assert "function importComfyuiUploadedImage" in comfyui_js
    assert "setComfyuiInputAssetFromRef(assetKey" in comfyui_js
    assert "cloudFileId: image.cloud_file_id" in comfyui_js
    assert "async function ensureComfyuiTemplateImageAssignments" in workflow_js
    assert ".filter((item) => item.hasLocalFile && item.assetKey)" in workflow_js
    assert "await importComfyuiUploadedImage(assetKey);" in workflow_js
    assert "await ensureComfyuiTemplateImageAssignments(templateDetail)" in workflow_js


def test_video_workflow_templates_use_short_foreground_wait_without_losing_job_id():
    comfyui_js = _read("public/js/36-comfyui.js")
    workflow_js = _read("public/js/36-comfyui-workflows.js")

    assert "const COMFYUI_VIDEO_FOREGROUND_TIMEOUT_SECONDS = 900;" in comfyui_js
    assert "const COMFYUI_INTERRUPT_TIMEOUT_SECONDS = 15;" in comfyui_js
    assert "function createComfyuiForegroundTimeoutError(jobId)" in comfyui_js
    assert "err.comfyuiForegroundTimeout = true;" in comfyui_js
    assert "function comfyuiForegroundTimeoutMessage(err)" in comfyui_js
    assert "job_id: interruptedJobId" in comfyui_js
    assert "signal: interruptRequestController.signal" in comfyui_js
    assert "Promise.race([interruptRequest, interruptTimeout])" in comfyui_js
    assert "已停止等待中斷回應" in comfyui_js
    assert "function comfyuiWorkflowPresetForegroundTimeoutSeconds(item = {})" in workflow_js
    assert 'return outputs.includes("video") ? videoTimeout : baseTimeout;' in workflow_js
    assert "const workflowTimeoutSeconds = comfyuiWorkflowPresetForegroundTimeoutSeconds(preset);" in workflow_js
    assert "pollComfyuiJobUntilDone(json.job?.job_id, controller, workflowTimeoutSeconds)" in workflow_js
    assert 'label: timedOut ? "已停止前台等待" : "產圖失敗"' in workflow_js


def test_workflow_only_modes_delegate_generate_button_to_selected_template():
    comfyui_js = _read("public/js/36-comfyui.js")
    workflow_js = _read("public/js/36-comfyui-workflows.js")

    assert 'return "圖生影片：先選來源圖片，再在上方 Workflow 模板選擇支援 I2V 的工作流後執行。";' in comfyui_js
    assert "runSelectedComfyuiWorkflowTemplateFromGenerate" in comfyui_js
    assert "await runSelectedComfyuiWorkflowTemplateFromGenerate(payload.generation_mode);" in comfyui_js
    assert "function runSelectedComfyuiWorkflowTemplateFromGenerate(mode)" in workflow_js
    assert "function comfyuiWorkflowPresetSupportsMode" in workflow_js
    assert 't2a: "t2s"' in comfyui_js
    assert '["audio", "audios", "music", "song", "songs", "sound", "sounds"]' in workflow_js
    assert "const matches = comfyuiWorkflowPresetsForMode(normalized);" in workflow_js
    assert "await runComfyuiWorkflowPreset(presetId);" in workflow_js
    assert "select.focus();" in workflow_js
    assert "const selectedTemplateId = Number(comfyuiSelectedTemplatePresetId || $(\"comfyui-template-select\")?.value || 0);" in comfyui_js
    assert "await runSelectedComfyuiWorkflowTemplateFromGenerate(payload.generation_mode);" in comfyui_js


def test_generation_mode_dropdown_is_hidden_and_system_inferred():
    html = _read("public/index.html")
    comfyui_js = _read("public/js/36-comfyui.js")
    css = _read("public/styles.css")

    assert '<select id="comfyui-generation-mode" hidden aria-hidden="true" tabindex="-1">' in html
    assert "不用手選文生圖或圖生圖" in html
    assert "function inferComfyuiGenerationMode()" in comfyui_js
    assert 'if (comfyuiHasInputAsset("source")) {' in comfyui_js
    assert 'if (comfyuiHasInputAsset("mask")) return "inpaint";' in comfyui_js
    assert 'return "img2img";' in comfyui_js
    assert ".comfyui-auto-mode-display" in css


def test_template_renderer_relabels_ambiguous_existing_manifest_fields():
    workflow_js = _read("public/js/36-comfyui-workflows.js")
    assert "function comfyuiTemplateFieldLabel" in workflow_js
    assert 'return "正向提示詞";' in workflow_js
    assert 'return "負面提示詞";' in workflow_js
    assert 'return "Checkpoint / 大模型";' in workflow_js
    assert 'return comfyuiTemplateLabelWithNoise(field, "Diffusion / UNet 大模型");' in workflow_js
    assert 'return comfyuiTemplateLabelWithNoise(field, "LoRA 模型（Model-only）");' in workflow_js
    assert 'return "放大 / Upscale 模型";' in workflow_js
    assert "const fieldLabel = comfyuiTemplateFieldLabel(field, binding);" in workflow_js


def test_comfyui_tools_are_split_into_subviews():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")
    css = _read("public/styles.css")

    assert 'data-comfyui-view="generate"' in html
    assert 'data-comfyui-view="history"' in html
    assert 'data-comfyui-view="workflow"' in html
    assert 'data-comfyui-view="models" hidden' in html
    assert 'data-comfyui-view-panel="generate"' in html
    assert 'data-comfyui-view-panel="history"' in html
    assert 'data-comfyui-view-panel="workflow"' in html
    assert 'data-comfyui-view-panel="models"' in html
    assert "function setComfyuiView" in js
    assert "bindComfyuiSubnav" in js
    assert ".comfyui-subview[hidden]" in css


def test_local_model_management_hides_outside_local_root_mode():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")
    css = _read("public/styles.css")

    assert 'data-comfyui-view="models" hidden' in html
    assert "function canManageComfyuiLocalModels" in js
    assert 'return currentUser === "root" && mode === "local";' in js
    assert 'const modelsUnavailable = selected === "models" && (!canManageComfyuiLocalModels() || (modelTab && modelTab.hidden));' in js
    assert "const showLocalModels = canManageComfyuiLocalModels(mode);" in js
    assert 'if (panel) panel.style.display = showLocalModels ? "" : "none";' in js
    assert "if (modelsTab) modelsTab.hidden = !showLocalModels;" in js
    assert "if (details && !showLocalModels) details.open = false;" in js
    assert 'document.addEventListener("hackme:account-context-changed"' in js
    assert ".comfyui-subtab[hidden]" in css
