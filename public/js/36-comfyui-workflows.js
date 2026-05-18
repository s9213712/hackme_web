function comfyuiWorkflowPresetById(presetId) {
  return comfyuiWorkflowPresets.find((item) => Number(item?.id) === Number(presetId)) || null;
}

function comfyuiWorkflowPaidApiNodes(detail) {
  const nodes = detail?.paid_api_nodes;
  return nodes && nodes.required && Array.isArray(nodes.nodes) ? nodes.nodes : [];
}

function comfyuiWorkflowPaidApiWarningHtml(detail) {
  const nodes = comfyuiWorkflowPaidApiNodes(detail);
  if (!nodes.length) return "";
  const labels = nodes.map((node) => `${node.node_id || "-"}:${node.class_type || node.title || "API node"}`).slice(0, 6);
  return `
    <div class="comfyui-workflow-paid-api-warning">
      可能使用 ComfyUI 付費/API node，執行前會要求確認。節點：${sanitize(labels.join(", "))}${nodes.length > labels.length ? `，另 ${sanitize(String(nodes.length - labels.length))} 個` : ""}
    </div>
  `;
}

function setComfyuiWorkflowStatus(text) {
  const status = $("comfyui-workflow-status");
  if (status) status.textContent = text || "";
}

function resetComfyuiWorkflowEditor({ keepStatus = false } = {}) {
  comfyuiWorkflowCurrentPresetId = null;
  comfyuiWorkflowEditorDefaults = null;
  setComfyuiFieldValue("comfyui-workflow-title", "");
  setComfyuiFieldValue("comfyui-workflow-description", "");
  setComfyuiFieldValue("comfyui-workflow-visibility", "private");
  setComfyuiFieldValue("comfyui-workflow-purpose", "txt2img");
  setComfyuiFieldValue("comfyui-workflow-comfyui-version", "");
  setComfyuiFieldValue("comfyui-workflow-project-version", "");
  setComfyuiFieldValue("comfyui-workflow-schema-version", "1");
  setComfyuiFieldValue("comfyui-workflow-json", "");
  setComfyuiFieldValue("comfyui-workflow-layout-json", "");
  const defaultInput = $("comfyui-workflow-is-default");
  if (defaultInput) defaultInput.checked = false;
  const fileInput = $("comfyui-workflow-file");
  if (fileInput) fileInput.value = "";
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = true;
  renderComfyuiWorkflowBuilderPreview();
  if (!keepStatus) setComfyuiWorkflowStatus("尚未選取 workflow preset");
}

function markComfyuiWorkflowEditorDirty() {
  const note = $("comfyui-workflow-editor-note");
  if (note) note.textContent = "有未儲存的版面修改；請按「新增版面」或「更新目前選擇」才會保存。";
}

const COMFYUI_WORKFLOW_NODE_TEMPLATES = {
  checkpoint_loader: {
    class_type: "CheckpointLoaderSimple",
    label: "Checkpoint Loader",
    inputs: { ckpt_name: "" },
  },
  positive_prompt: {
    class_type: "CLIPTextEncode",
    label: "Positive Prompt",
    inputs: { text: "masterpiece, best quality", clip: "" },
  },
  negative_prompt: {
    class_type: "CLIPTextEncode",
    label: "Negative Prompt",
    inputs: { text: "low quality, blurry", clip: "" },
  },
  ksampler: {
    class_type: "KSampler",
    label: "KSampler",
    inputs: { seed: 0, steps: 20, cfg: 7, sampler_name: "euler", scheduler: "normal" },
  },
  vae_decode: {
    class_type: "VAEDecode",
    label: "VAE Decode",
    inputs: { samples: "", vae: "" },
  },
  save_image: {
    class_type: "SaveImage",
    label: "Save Image",
    inputs: { filename_prefix: "hackme_web" },
  },
  load_image: {
    class_type: "LoadImage",
    label: "Load Image",
    inputs: { image: "" },
  },
  load_image_mask: {
    class_type: "LoadImageMask",
    label: "Load Mask",
    inputs: { image: "", channel: "alpha" },
  },
  vae_encode: {
    class_type: "VAEEncode",
    label: "VAE Encode",
    inputs: { pixels: "", vae: "" },
  },
  vae_encode_for_inpaint: {
    class_type: "VAEEncodeForInpaint",
    label: "VAE Encode Inpaint",
    inputs: { pixels: "", vae: "", mask: "", grow_mask_by: 6 },
  },
  image_pad_for_outpaint: {
    class_type: "ImagePadForOutpaint",
    label: "Outpaint Pad",
    inputs: { image: "", left: 0, top: 0, right: 0, bottom: 0, feathering: 40 },
  },
  lora_loader: {
    class_type: "LoraLoader",
    label: "LoRA Loader",
    inputs: { lora_name: "", strength_model: 1, strength_clip: 1, model: "", clip: "" },
  },
  ksampler_advanced: {
    class_type: "KSamplerAdvanced",
    label: "KSampler Advanced",
    inputs: { add_noise: "enable", noise_seed: 0, steps: 20, cfg: 7, sampler_name: "euler", scheduler: "normal", start_at_step: 0, end_at_step: 20, return_with_leftover_noise: "enable", model: "", positive: "", negative: "", latent_image: "" },
  },
  controlnet_loader: {
    class_type: "ControlNetLoader",
    label: "ControlNet Loader",
    inputs: { control_net_name: "" },
  },
  controlnet_apply_advanced: {
    class_type: "ControlNetApplyAdvanced",
    label: "ControlNet Apply Advanced",
    inputs: { positive: "", negative: "", control_net: "", image: "", strength: 1, start_percent: 0, end_percent: 1 },
  },
  upscale_model_loader: {
    class_type: "UpscaleModelLoader",
    label: "Upscale Model Loader",
    inputs: { model_name: "" },
  },
  image_upscale: {
    class_type: "ImageUpscaleWithModel",
    label: "Image Upscale",
    inputs: { upscale_model: "", image: "" },
  },
};

function parseComfyuiWorkflowEditorJson(fieldId, fallback) {
  const text = String($(fieldId)?.value || "").trim();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : fallback;
  } catch (err) {
    throw new Error(`${fieldId === "comfyui-workflow-layout-json" ? "UI Layout JSON" : "Workflow JSON"} 格式錯誤：${err.message || err}`);
  }
}

function setComfyuiWorkflowEditorJson(workflow, layout) {
  setComfyuiFieldValue("comfyui-workflow-json", JSON.stringify(workflow || {}, null, 2));
  setComfyuiFieldValue("comfyui-workflow-layout-json", JSON.stringify(layout || {}, null, 2));
  renderComfyuiWorkflowBuilderPreview();
  markComfyuiWorkflowEditorDirty();
}

function nextComfyuiWorkflowNodeId(workflow) {
  const ids = Object.keys(workflow || {})
    .map((key) => Number(key))
    .filter((value) => Number.isFinite(value) && value > 0);
  return String((ids.length ? Math.max(...ids) : 0) + 1);
}

function normalizeComfyuiLayoutJson(layout) {
  const normalized = layout && typeof layout === "object" && !Array.isArray(layout) ? { ...layout } : {};
  if (!Array.isArray(normalized.node_order)) normalized.node_order = [];
  if (!normalized.node_positions || typeof normalized.node_positions !== "object" || Array.isArray(normalized.node_positions)) {
    normalized.node_positions = {};
  }
  if (!normalized.field_overrides || typeof normalized.field_overrides !== "object" || Array.isArray(normalized.field_overrides)) {
    normalized.field_overrides = {};
  }
  normalized.layout_schema_version = String(normalized.layout_schema_version || "1");
  return normalized;
}

function addComfyuiWorkflowNode(templateKey, label = "") {
  const template = COMFYUI_WORKFLOW_NODE_TEMPLATES[templateKey];
  if (!template) throw new Error("請選擇要追加的節點類型。");
  const workflow = parseComfyuiWorkflowEditorJson("comfyui-workflow-json", {});
  const layout = normalizeComfyuiLayoutJson(parseComfyuiWorkflowEditorJson("comfyui-workflow-layout-json", {}));
  const nodeId = nextComfyuiWorkflowNodeId(workflow);
  workflow[nodeId] = {
    class_type: template.class_type,
    inputs: { ...(template.inputs || {}) },
  };
  const cleanLabel = String(label || template.label || template.class_type).trim().slice(0, 80);
  if (cleanLabel) {
    workflow[nodeId]._meta = { title: cleanLabel };
    layout.field_overrides[nodeId] = { label: cleanLabel };
  }
  layout.node_order = layout.node_order.filter((item) => String(item) !== nodeId).concat([nodeId]);
  const index = layout.node_order.length - 1;
  layout.node_positions[nodeId] = [40 + (index % 3) * 280, 40 + Math.floor(index / 3) * 180];
  setComfyuiWorkflowEditorJson(workflow, layout);
  setComfyuiMessage(`已追加 ${template.label || template.class_type} 節點；尚未儲存。`, true);
}

function createBlankComfyuiWorkflowLayout() {
  comfyuiWorkflowCurrentPresetId = null;
  comfyuiWorkflowEditorDefaults = null;
  if (!$("comfyui-workflow-title")?.value) setComfyuiFieldValue("comfyui-workflow-title", "我的 ComfyUI 工作流版面");
  setComfyuiFieldValue("comfyui-workflow-purpose", "custom");
  setComfyuiWorkflowEditorJson({}, {
    layout_schema_version: "1",
    node_order: [],
    node_positions: {},
    field_overrides: {},
  });
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = true;
  setComfyuiWorkflowStatus("已建立空白版面草稿；追加節點或貼上 workflow JSON 後可新增保存。");
}

function createTxt2ImgComfyuiStarterWorkflow() {
  comfyuiWorkflowCurrentPresetId = null;
  comfyuiWorkflowEditorDefaults = {
    generation_mode: "txt2img",
    steps: 20,
    cfg: 7,
    sampler_name: "euler",
    scheduler: "normal",
    width: 1024,
    height: 1024,
  };
  if (!$("comfyui-workflow-title")?.value) setComfyuiFieldValue("comfyui-workflow-title", "txt2img 起始工作流");
  setComfyuiFieldValue("comfyui-workflow-purpose", "txt2img");
  const workflow = {
    "1": { class_type: "CheckpointLoaderSimple", inputs: { ckpt_name: "" }, _meta: { title: "主模型" } },
    "2": { class_type: "CLIPTextEncode", inputs: { clip: ["1", 1], text: "masterpiece, best quality" }, _meta: { title: "正向提示詞" } },
    "3": { class_type: "CLIPTextEncode", inputs: { clip: ["1", 1], text: "low quality, blurry" }, _meta: { title: "負向提示詞" } },
    "4": { class_type: "EmptyLatentImage", inputs: { width: 1024, height: 1024, batch_size: 1 }, _meta: { title: "畫布尺寸" } },
    "5": { class_type: "KSampler", inputs: { model: ["1", 0], positive: ["2", 0], negative: ["3", 0], latent_image: ["4", 0], seed: 0, steps: 20, cfg: 7, sampler_name: "euler", scheduler: "normal", denoise: 1 }, _meta: { title: "採樣器" } },
    "6": { class_type: "VAEDecode", inputs: { samples: ["5", 0], vae: ["1", 2] }, _meta: { title: "VAE 解碼" } },
    "7": { class_type: "SaveImage", inputs: { images: ["6", 0], filename_prefix: "hackme_web" }, _meta: { title: "儲存圖片" } },
  };
  const layout = {
    layout_schema_version: "1",
    node_order: ["1", "2", "3", "4", "5", "6", "7"],
    node_positions: {
      "1": [40, 40],
      "2": [320, 20],
      "3": [320, 200],
      "4": [320, 380],
      "5": [620, 160],
      "6": [900, 160],
      "7": [1180, 160],
    },
    field_overrides: {
      "1": { label: "主模型" },
      "2": { label: "正向提示詞" },
      "3": { label: "負向提示詞" },
      "4": { label: "畫布尺寸" },
      "5": { label: "Sampler / Scheduler / Steps / CFG / Seed" },
      "6": { label: "VAE 解碼" },
      "7": { label: "輸出檔名" },
    },
  };
  setComfyuiWorkflowEditorJson(workflow, layout);
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = true;
  setComfyuiWorkflowStatus("已建立 txt2img 起始版草稿；可繼續追加節點或新增保存。");
}

function renderComfyuiWorkflowBuilderPreview() {
  const preview = $("comfyui-workflow-builder-preview");
  if (!preview) return;
  let workflow = {};
  let layout = {};
  try {
    workflow = parseComfyuiWorkflowEditorJson("comfyui-workflow-json", {});
    layout = normalizeComfyuiLayoutJson(parseComfyuiWorkflowEditorJson("comfyui-workflow-layout-json", {}));
  } catch (err) {
    preview.textContent = err.message || "Workflow JSON 尚無法預覽。";
    return;
  }
  const ids = Object.keys(workflow || {});
  if (!ids.length) {
    preview.textContent = "目前尚未建立節點。";
    return;
  }
  const ordered = (layout.node_order || []).filter((id) => workflow[id]).concat(ids.filter((id) => !(layout.node_order || []).includes(id)));
  preview.innerHTML = `
    <div class="comfyui-workflow-flags">
      <span class="comfyui-workflow-chip">節點 ${sanitize(String(ids.length))}</span>
      <span class="comfyui-workflow-chip">版面位置 ${sanitize(String(Object.keys(layout.node_positions || {}).length))}</span>
    </div>
    <div class="comfyui-workflow-builder-node-list">
      ${ordered.slice(0, 12).map((id) => {
        const node = workflow[id] || {};
        const title = node?._meta?.title || layout.field_overrides?.[id]?.label || node.class_type || `Node ${id}`;
        return `<span class="comfyui-workflow-chip">${sanitize(id)} · ${sanitize(title)}</span>`;
      }).join("")}
      ${ordered.length > 12 ? `<span class="comfyui-workflow-chip">另 ${sanitize(String(ordered.length - 12))} 個</span>` : ""}
    </div>
  `;
}

function comfyuiWorkflowEditorPayload() {
  return {
    title: $("comfyui-workflow-title")?.value || "",
    description: $("comfyui-workflow-description")?.value || "",
    visibility: $("comfyui-workflow-visibility")?.value || "private",
    purpose: $("comfyui-workflow-purpose")?.value || "custom",
    comfyui_version: $("comfyui-workflow-comfyui-version")?.value || "",
    project_version: $("comfyui-workflow-project-version")?.value || "",
    workflow_schema_version: $("comfyui-workflow-schema-version")?.value || "1",
    layout_json: $("comfyui-workflow-layout-json")?.value || undefined,
    is_default: !!$("comfyui-workflow-is-default")?.checked,
  };
}

function downloadComfyuiWorkflowText(filename, text) {
  const blob = new Blob([String(text || "")], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "comfyui-workflow.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function comfyuiWorkflowEditorStorageKey(key) {
  if (typeof comfyuiUserStorageKey === "function") return comfyuiUserStorageKey(key);
  if (typeof accountScopedStorageKey === "function") return accountScopedStorageKey(key);
  const id = Number(currentUserId || 0);
  const scope = Number.isFinite(id) && id > 0
    ? `user:${id}`
    : (currentUser ? `name:${String(currentUser).trim().toLowerCase()}` : "anonymous");
  return `hackme_web:${scope}:${String(key || "state")}`;
}

function loadComfyuiVisualWorkflowEditorResult() {
  let payload = null;
  try {
    payload = JSON.parse(localStorage.getItem(comfyuiWorkflowEditorStorageKey("hackme_comfyui_workflow_editor_result")) || "null");
  } catch (_) {
    payload = null;
  }
  if (!payload || typeof payload !== "object" || !payload.workflow_json) {
    setComfyuiMessage("尚未找到視覺 Workflow 編輯器結果。請先開啟視覺編輯器並按「送回主頁」。", false);
    return;
  }
  setComfyuiFieldValue("comfyui-workflow-title", payload.name || payload.title || "");
  setComfyuiFieldValue("comfyui-workflow-description", payload.description || "");
  setComfyuiFieldValue("comfyui-workflow-purpose", payload.purpose || "custom");
  setComfyuiFieldValue("comfyui-workflow-schema-version", payload.workflow_schema_version || "1");
  setComfyuiFieldValue("comfyui-workflow-json", JSON.stringify(payload.workflow_json || {}, null, 2));
  setComfyuiFieldValue("comfyui-workflow-layout-json", JSON.stringify(payload.layout_json || {}, null, 2));
  comfyuiWorkflowEditorDefaults = null;
  renderComfyuiWorkflowBuilderPreview();
  markComfyuiWorkflowEditorDirty();
  setComfyuiMessage("已載入視覺 Workflow 編輯器結果；按「新增版面」即可保存。", true);
}

function prepareComfyuiVisualWorkflowEditorInput() {
  let workflow = {};
  let layout = {};
  try {
    workflow = parseComfyuiWorkflowEditorJson("comfyui-workflow-json", {});
    layout = normalizeComfyuiLayoutJson(parseComfyuiWorkflowEditorJson("comfyui-workflow-layout-json", {}));
  } catch (err) {
    setComfyuiMessage(err.message || "目前 workflow JSON 無法送入視覺編輯器", false);
    return;
  }
  const payload = {
    name: $("comfyui-workflow-title")?.value || "ComfyUI 工作流版面",
    description: $("comfyui-workflow-description")?.value || "",
    purpose: $("comfyui-workflow-purpose")?.value || "custom",
    project_version: $("comfyui-workflow-project-version")?.value || "",
    comfyui_version: $("comfyui-workflow-comfyui-version")?.value || "",
    workflow_schema_version: $("comfyui-workflow-schema-version")?.value || "1",
    workflow_json: workflow,
    layout_json: layout,
  };
  try {
    localStorage.setItem(comfyuiWorkflowEditorStorageKey("hackme_comfyui_workflow_editor_input"), JSON.stringify(payload));
  } catch (_) {
    setComfyuiMessage("瀏覽器無法暫存 workflow 給視覺編輯器；請改用編輯器內匯入 JSON。", false);
    return;
  }
  setComfyuiWorkflowStatus("已把目前 workflow 暫存給視覺節點編輯器。");
}

function comfyuiWorkflowDependencyHtml(status) {
  if (!status) return '<div class="drive-card-sub">尚未檢查目前節點與模型依賴。</div>';
  const chips = [];
  if (status.available) {
    chips.push('<span class="comfyui-workflow-chip">依賴可用</span>');
  } else {
    chips.push('<span class="comfyui-workflow-chip bad">缺少依賴</span>');
  }
  if (Array.isArray(status.missing_nodes) && status.missing_nodes.length) {
    chips.push(`<span class="comfyui-workflow-chip bad">缺少 node ${sanitize(status.missing_nodes.length)}</span>`);
  }
  if (Array.isArray(status.missing_models) && status.missing_models.length) {
    chips.push(`<span class="comfyui-workflow-chip bad">缺少模型 ${sanitize(status.missing_models.length)}</span>`);
  }
  if (Array.isArray(status.missing_loras) && status.missing_loras.length) {
    chips.push(`<span class="comfyui-workflow-chip bad">缺少 LoRA ${sanitize(status.missing_loras.length)}</span>`);
  }
  if (Array.isArray(status.missing_controlnets) && status.missing_controlnets.length) {
    chips.push(`<span class="comfyui-workflow-chip bad">缺少 ControlNet ${sanitize(status.missing_controlnets.length)}</span>`);
  }
  const issues = Array.isArray(status.issues) && status.issues.length
    ? `<div class="drive-card-sub">${sanitize(status.issues.join("；"))}</div>`
    : '<div class="drive-card-sub">目前沒有偵測到缺少的 workflow node、模型、LoRA 或 ControlNet。</div>';
  return `<div class="comfyui-workflow-flags">${chips.join("")}</div>${issues}`;
}

function renderComfyuiWorkflowRunList(runs = []) {
  if (!Array.isArray(runs) || !runs.length) {
    return '<div class="drive-card-sub">尚無最近執行結果</div>';
  }
  return `<div class="comfyui-workflow-run-list">${runs.map((run) => {
    const params = run?.params || {};
    const summary = [
      params.seed !== undefined && params.seed !== null ? `seed ${params.seed}` : "",
      params.steps ? `steps ${params.steps}` : "",
      params.cfg ? `CFG ${params.cfg}` : "",
      params.controlnet?.type ? `ControlNet ${String(params.controlnet.type).toUpperCase()}` : "",
    ].filter(Boolean).join(" · ");
    return `
      <div class="comfyui-workflow-run-item">
        <strong>${sanitize(String(run.status || "queued"))}</strong>
        <span> · ${sanitize(String(run.created_at || "").replace("T", " ").slice(0, 16))}</span>
        <div>${sanitize(summary || "未保存額外參數摘要")}</div>
        ${run.error ? `<div class="drive-card-sub">${sanitize(run.error)}</div>` : ""}
      </div>
    `;
  }).join("")}</div>`;
}

function comfyuiTemplateSelectGroups(payload = {}) {
  return [
    { label: "官方模板", items: Array.isArray(payload.official_presets) ? payload.official_presets : [] },
    { label: "我的模板", items: Array.isArray(payload.my_presets) ? payload.my_presets : [] },
    { label: "公開模板", items: Array.isArray(payload.shared_presets) ? payload.shared_presets : [] },
  ].filter((group) => group.items.length);
}

let comfyuiTemplateRenderTimer = null;
let comfyuiTemplateLoraOverrides = {};

function queueRenderSelectedComfyuiTemplate() {
  if (comfyuiTemplateRenderTimer) clearTimeout(comfyuiTemplateRenderTimer);
  comfyuiTemplateRenderTimer = setTimeout(() => {
    comfyuiTemplateRenderTimer = null;
    renderSelectedComfyuiTemplate();
  }, 0);
}

function renderComfyuiTemplateSelector(payload = {}, { silentReload = true } = {}) {
  const select = $("comfyui-template-select");
  if (!select) return;
  const previous = String(comfyuiSelectedTemplatePresetId || select.value || "").trim();
  const groups = comfyuiTemplateSelectGroups(payload);
  const options = ['<option value="">先選擇模板</option>'].concat(groups.map((group) => `
    <optgroup label="${sanitize(group.label)}">
      ${group.items.map((item) => `
        <option value="${sanitize(String(item.id))}">
          ${sanitize(item.title || `Workflow #${item.id}`)}
        </option>
      `).join("")}
    </optgroup>
  `));
  select.innerHTML = options.join("");
  const exists = comfyuiWorkflowPresets.some((item) => String(item?.id || "") === previous);
  select.value = exists ? previous : "";
  comfyuiSelectedTemplatePresetId = select.value ? Number(select.value) : null;
  if (!comfyuiSelectedTemplatePresetId) {
    comfyuiSelectedTemplateDetail = null;
  }
  if (select.dataset.comfyuiTemplateBound !== "1") {
    select.dataset.comfyuiTemplateBound = "1";
    select.addEventListener("change", () => {
      const presetId = Number(select.value || 0);
      if (!presetId) {
        comfyuiSelectedTemplatePresetId = null;
        comfyuiSelectedTemplateDetail = null;
        comfyuiTemplateLoraOverrides = {};
        renderSelectedComfyuiTemplate();
        return;
      }
      loadComfyuiSelectedTemplateDetail(presetId, { silent: false }).catch((err) => {
        setComfyuiMessage(err.message || "模板讀取失敗", false);
      });
    });
  }
  if (comfyuiSelectedTemplatePresetId) {
    const isSameDetail = Number(comfyuiSelectedTemplateDetail?.id || 0) === Number(comfyuiSelectedTemplatePresetId || 0);
    if (silentReload && isSameDetail) {
      renderSelectedComfyuiTemplate();
    } else {
      loadComfyuiSelectedTemplateDetail(comfyuiSelectedTemplatePresetId, {
        silent: silentReload,
        applyDefaults: !silentReload,
      }).catch(() => {});
    }
  } else {
    renderSelectedComfyuiTemplate();
  }
}

async function loadComfyuiSelectedTemplateDetail(presetId, { silent = false, applyDefaults = true } = {}) {
  if (!presetId) return;
  await fetchCsrfToken();
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `模板讀取失敗（HTTP ${res.status}）`);
  comfyuiSelectedTemplatePresetId = Number(presetId);
  comfyuiTemplateLoraOverrides = {};
  comfyuiSelectedTemplateDetail = json.preset || null;
  if (applyDefaults) {
    applyComfyuiWorkflowPresetDefaults(comfyuiSelectedTemplateDetail?.default_params || {});
  }
  renderSelectedComfyuiTemplate();
  if (!silent) {
    setComfyuiMessage(`已切換到模板「${comfyuiSelectedTemplateDetail?.title || `Workflow #${presetId}`}」`, true);
  }
}

function comfyuiTemplateInputKinds(detail) {
  const counts = { text: 0, image: 0, parameter: 0 };
  const panels = Array.isArray(detail?.ui_schema?.panels) ? detail.ui_schema.panels : [];
  panels.forEach((panel) => {
    (panel?.fields || []).forEach((field) => {
      if (field?.synthetic || field?.input_type === "embedding_shortcuts") return;
      const category = String(field?.category || "").trim().toUpperCase();
      if (category === "TEXT") counts.text += 1;
      else if (category === "IMAGE" || field?.input_type === "file_picker") counts.image += 1;
      else counts.parameter += 1;
    });
  });
  return [
    counts.text ? `文字 ${counts.text}` : "",
    counts.image ? `圖片 ${counts.image}` : "",
    counts.parameter ? `參數 ${counts.parameter}` : "",
  ].filter(Boolean);
}

function comfyuiTemplateSummaryMarkup(detail) {
  if (!detail) {
    return "";
  }
  const mode = comfyuiReadableModeLabel(detail?.default_params?.generation_mode || "txt2img");
  const outputs = Array.isArray(detail?.output_kinds) && detail.output_kinds.length ? detail.output_kinds : ["image"];
  const inputKinds = comfyuiTemplateInputKinds(detail);
  const dependency = detail?.dependency_status || detail?.capability || null;
  const blockerItems = Array.isArray(dependency?.blockers) ? dependency.blockers : [];
  const requirementBits = []
    .concat((detail?.required_models || []).map((item) => `${item.kind || "model"}:${item.name || ""}`))
    .concat((detail?.required_controlnets || []).map((item) => `controlnet:${item.name || item}`))
    .concat((detail?.required_loras || []).map((item) => `lora:${item.name || item}`))
    .filter(Boolean);
  return `
    <details class="comfyui-template-detail-panel">
      <summary>
    <div class="comfyui-template-summary-head">
      <div class="comfyui-template-summary-title">
        <strong>${sanitize(detail?.title || `Workflow #${detail?.id || ""}`)}</strong>
        <div class="drive-card-sub">${sanitize(mode)} · ${sanitize(outputs.join(", "))}</div>
      </div>
      <div class="comfyui-template-summary-flags">
        <span class="comfyui-workflow-chip">${sanitize(mode)}</span>
        ${detail?.is_official ? '<span class="comfyui-workflow-chip">官方</span>' : ""}
        <span class="comfyui-workflow-chip">${sanitize(detail?.visibility || "private")}</span>
      </div>
    </div>
      </summary>
    <div class="drive-card-sub">${sanitize(detail?.description || "未填寫模板說明")}</div>
    <div class="drive-card-sub">這個模板會根據 workflow manifest 只顯示需要的欄位；其餘手動欄位收進下方進階區。</div>
    ${requirementBits.length ? `<div class="drive-card-sub" style="margin-top:.35rem;">依賴：${sanitize(requirementBits.join("、"))}</div>` : ""}
    ${comfyuiWorkflowPaidApiWarningHtml(detail)}
    ${inputKinds.length ? `<div class="comfyui-template-output-list">${inputKinds.map((kind) => `<span class="comfyui-workflow-chip">輸入 ${sanitize(kind)}</span>`).join("")}</div>` : ""}
    <div class="comfyui-template-output-list">
      ${outputs.map((kind) => `<span class="comfyui-workflow-chip">輸出 ${sanitize(String(kind))}</span>`).join("")}
      ${dependency?.available === false ? '<span class="comfyui-workflow-chip bad">目前依賴不完整</span>' : ""}
    </div>
    ${blockerItems.length ? `<div class="drive-card-sub" style="margin-top:.45rem;color:#ffd2dc;">${sanitize(blockerItems.join("；"))}</div>` : ""}
    </details>
  `;
}

function comfyuiTemplateSelectOptions(targetId, field = {}) {
  const target = $(targetId);
  const options = [];
  const seen = new Set();
  const addOption = (value, label = value, disabled = false) => {
    const cleanValue = String(value || "");
    if (seen.has(cleanValue)) return;
    seen.add(cleanValue);
    options.push({
      value: cleanValue,
      label: String(label || cleanValue),
      disabled: !!disabled,
    });
  };
  if (target && target.options && target.options.length) {
    Array.from(target.options).forEach((option) => {
      addOption(
        option.value || "",
        option.textContent || option.label || option.value || "",
        option.disabled
      );
    });
    if (field?.current_value !== undefined && field?.current_value !== null) {
      addOption(field.current_value, field.current_value, false);
    }
  } else if (Array.isArray(field?.constraints?.options)) {
    field.constraints.options.forEach((value) => {
      addOption(value, value, false);
    });
  } else if (field?.current_value !== undefined && field?.current_value !== null) {
    addOption(field.current_value, field.current_value, false);
  }
  return options;
}

function comfyuiTemplateLoraSelectOptions(field = {}) {
  const seen = new Set();
  const options = [];
  const addOption = (value, label = value, disabled = false) => {
    const cleanValue = String(value || "");
    if (seen.has(cleanValue)) return;
    seen.add(cleanValue);
    options.push({ value: cleanValue, label: String(label || cleanValue), disabled: !!disabled });
  };
  addOption("", "不使用 LoRA（可略過）");
  const current = String(field?.current_value || "").trim();
  if (current) addOption(current, current, false);
  const source = $("comfyui-lora-select");
  if (source && source.options && source.options.length) {
    Array.from(source.options).forEach((option) => {
      addOption(option.value || "", option.textContent || option.label || option.value || "", option.disabled);
    });
  } else {
    (Array.isArray(comfyuiAvailableLoras) ? comfyuiAvailableLoras : []).forEach((name) => {
      const detail = comfyuiLoraDetails?.[name] || {};
      const supported = detail.supported === true;
      const reason = detail.base_model ? `${detail.base_model} 不支援` : "base model 未知，暫不可用";
      addOption(name, supported ? name : `${name}（不可用：${reason}）`, !supported);
    });
  }
  return options;
}

function comfyuiSelectedLoraIndexForTemplateNode(nodeId) {
  const cleanNodeId = String(nodeId || "");
  if (!cleanNodeId) return -1;
  return comfyuiSelectedLoras.findIndex((item) => String(item?.template_node_id || "") === cleanNodeId);
}

function comfyuiSelectedLoraForTemplateNode(nodeId) {
  const index = comfyuiSelectedLoraIndexForTemplateNode(nodeId);
  return index >= 0 ? comfyuiSelectedLoras[index] : null;
}

function upsertComfyuiTemplateLora(nodeId, name, { notify = true } = {}) {
  const cleanNodeId = String(nodeId || "");
  const cleanName = String(name || "").trim();
  if (cleanNodeId) comfyuiTemplateLoraOverrides[cleanNodeId] = cleanName;
  const existingIndex = comfyuiSelectedLoraIndexForTemplateNode(cleanNodeId);
  if (!cleanName) {
    if (existingIndex >= 0) removeComfyuiSelectedLoraByIndex(existingIndex);
    else renderComfyuiSelectedLoras();
    writeComfyuiDraft();
    return true;
  }
  if (comfyuiSelectedLoras.some((item, index) => index !== existingIndex && item?.name === cleanName)) {
    setComfyuiMessage("這個 LoRA 已經加入。", false);
    return false;
  }
  const detail = comfyuiLoraDetails?.[cleanName] || {};
  if (detail.supported !== true) {
    setComfyuiMessage(detail.support_message || "這個 LoRA 目前不支援；只允許 SDXL、Pony、Illustrious、Noob 系列。", false);
    return false;
  }
  if (existingIndex < 0 && comfyuiSelectedLoras.length >= COMFYUI_MAX_LORAS) {
    setComfyuiMessage(`已達 LoRA 數量上限 ${COMFYUI_MAX_LORAS} 個。`, false);
    return false;
  }
  if (existingIndex >= 0 && comfyuiSelectedLoras[existingIndex]?.name !== cleanName) {
    removeComfyuiSelectedLoraByIndex(existingIndex);
  }
  const nextIndex = comfyuiSelectedLoraIndexForTemplateNode(cleanNodeId);
  const item = {
    name: cleanName,
    strength_model: nextIndex >= 0 ? (comfyuiSelectedLoras[nextIndex].strength_model ?? 1) : 1,
    strength_clip: nextIndex >= 0 ? (comfyuiSelectedLoras[nextIndex].strength_clip ?? 1) : 1,
    template_node_id: cleanNodeId,
  };
  if (nextIndex >= 0) comfyuiSelectedLoras[nextIndex] = item;
  else comfyuiSelectedLoras.push(item);
  const insertedTerms = applyComfyuiPromptTerms(detail.trained_words || []);
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
  if (notify && insertedTerms.length) {
    setComfyuiMessage(`已加入 LoRA，並自動補上 trigger words：${insertedTerms.join(", ")}`, true);
  }
  return true;
}

function updateComfyuiTemplateLoraStrength(nodeId, fieldName, rawValue) {
  const index = comfyuiSelectedLoraIndexForTemplateNode(nodeId);
  if (index < 0 || !comfyuiSelectedLoras[index]) {
    setComfyuiMessage("請先選擇 LoRA，再調整權重。", false);
    return null;
  }
  const field = fieldName === "strength_clip" ? "strength_clip" : "strength_model";
  const value = Number(rawValue);
  const normalized = Math.max(-2, Math.min(2, Number.isFinite(value) ? value : 1));
  comfyuiSelectedLoras[index][field] = Math.round(normalized * 100) / 100;
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
  return comfyuiSelectedLoras[index][field];
}

function comfyuiTemplateFieldBinding(field, detail, ctx) {
  const mode = String(detail?.default_params?.generation_mode || "txt2img").trim().toLowerCase();
  if (field?.class_type === "CLIPTextEncode" && field?.input_name === "text") {
    const binding = { kind: "field", targetId: ctx.textFieldIndex === 0 ? "comfyui-prompt" : "comfyui-negative-prompt" };
    ctx.textFieldIndex += 1;
    return binding;
  }
  if (field?.class_type === "CheckpointLoaderSimple" && field?.input_name === "ckpt_name") return { kind: "field", targetId: "comfyui-model-select" };
  if (field?.class_type === "VAELoader" && field?.input_name === "vae_name") return { kind: "field", targetId: "comfyui-vae-select" };
  if (field?.class_type === "LoraLoader" && field?.input_name === "lora_name") return { kind: "lora", nodeId: field.node_id };
  if (field?.class_type === "LoraLoader" && (field?.input_name === "strength_model" || field?.input_name === "strength_clip")) {
    return { kind: "lora_strength", nodeId: field.node_id, strengthField: field.input_name };
  }
  if (field?.class_type === "UpscaleModelLoader" && field?.input_name === "model_name") return { kind: "field", targetId: "comfyui-upscale-model" };
  if (field?.class_type === "ControlNetLoader" && field?.input_name === "control_net_name") return { kind: "field", targetId: "comfyui-controlnet-model", enableControlnet: true };
  if (field?.class_type === "KSampler" && field?.input_name === "seed") return { kind: "field", targetId: "comfyui-seed" };
  if (field?.class_type === "KSampler" && field?.input_name === "steps") return { kind: "field", targetId: "comfyui-steps" };
  if (field?.class_type === "KSampler" && field?.input_name === "cfg") return { kind: "field", targetId: "comfyui-cfg" };
  if (field?.class_type === "KSampler" && field?.input_name === "sampler_name") return { kind: "field", targetId: "comfyui-sampler" };
  if (field?.class_type === "KSampler" && field?.input_name === "scheduler") return { kind: "field", targetId: "comfyui-scheduler" };
  if (field?.class_type === "KSampler" && field?.input_name === "denoise") return { kind: "field", targetId: "comfyui-denoise-strength" };
  if (field?.class_type === "EmptyLatentImage" && field?.input_name === "width") return { kind: "field", targetId: "comfyui-width" };
  if (field?.class_type === "EmptyLatentImage" && field?.input_name === "height") return { kind: "field", targetId: "comfyui-height" };
  if (field?.class_type === "EmptyLatentImage" && field?.input_name === "batch_size") return { kind: "field", targetId: "comfyui-batch-size" };
  if (field?.class_type === "ControlNetApplyAdvanced" && field?.input_name === "strength") return { kind: "field", targetId: "comfyui-control-strength", enableControlnet: true };
  if (field?.class_type === "ControlNetApplyAdvanced" && field?.input_name === "start_percent") return { kind: "field", targetId: "comfyui-control-start", enableControlnet: true };
  if (field?.class_type === "ControlNetApplyAdvanced" && field?.input_name === "end_percent") return { kind: "field", targetId: "comfyui-control-end", enableControlnet: true };
  if (field?.class_type === "ImagePadForOutpaint" && field?.input_name === "left") return { kind: "field", targetId: "comfyui-outpaint-left" };
  if (field?.class_type === "ImagePadForOutpaint" && field?.input_name === "top") return { kind: "field", targetId: "comfyui-outpaint-top" };
  if (field?.class_type === "ImagePadForOutpaint" && field?.input_name === "right") return { kind: "field", targetId: "comfyui-outpaint-right" };
  if (field?.class_type === "ImagePadForOutpaint" && field?.input_name === "bottom") return { kind: "field", targetId: "comfyui-outpaint-bottom" };
  if (field?.class_type === "ImagePadForOutpaint" && field?.input_name === "feathering") return { kind: "field", targetId: "comfyui-outpaint-feathering" };
  if (field?.class_type === "LoadImageMask" && field?.input_name === "image") return { kind: "image", assetKey: "mask", nodeId: field.node_id };
  if (field?.class_type === "LoadImageMask" && field?.input_name === "channel") return { kind: "readonly" };
  if (field?.class_type === "LoadImage" && field?.input_name === "image") {
    const hasControlnet = !!detail?.default_params?.controlnet?.type;
    const usesSource = ["img2img", "inpaint", "outpaint", "upscale"].includes(mode);
    let assetKey = "source";
    if (usesSource && ctx.loadImageIndex === 0) assetKey = "source";
    else if (hasControlnet) assetKey = "control";
    else if (!usesSource) assetKey = "control";
    ctx.loadImageIndex += 1;
    return { kind: "image", assetKey, nodeId: field.node_id };
  }
  if (field?.category && field.category !== "UNKNOWN") return { kind: "direct", fieldId: field.id };
  return { kind: "readonly" };
}

function comfyuiTemplateFieldValue(binding, field = {}) {
  if (binding.kind === "field") {
    const el = $(binding.targetId);
    if (
      binding.targetId === "comfyui-vae-select" &&
      field?.class_type === "VAELoader" &&
      el &&
      field?.current_value
    ) {
      const templateVae = String(field.current_value);
      const hasTemplateVae = Array.from(el.options || []).some((option) => option.value === templateVae);
      if (el.value === COMFYUI_VAE_BUILTIN || !hasTemplateVae) return templateVae;
    }
    return el ? String(el.value || "") : String(field?.current_value ?? "");
  }
  if (binding.kind === "image") {
    return comfyuiAssetState(binding.assetKey);
  }
  if (binding.kind === "direct") {
    const el = $(`tmpl-${field.id || ""}`);
    return el ? String(el.value || "") : String(field?.current_value ?? "");
  }
  return field?.current_value;
}

function comfyuiTemplateRuntimeValue(binding, field = {}) {
  if (binding.kind === "field") {
    const el = $(binding.targetId);
    if (
      binding.targetId === "comfyui-vae-select" &&
      field?.class_type === "VAELoader" &&
      el &&
      field?.current_value
    ) {
      const templateVae = String(field.current_value);
      const hasTemplateVae = Array.from(el.options || []).some((option) => option.value === templateVae);
      if (el.value === COMFYUI_VAE_BUILTIN || !hasTemplateVae) return templateVae;
    }
    return el ? el.value : field?.current_value;
  }
  if (binding.kind === "lora") {
    const selected = comfyuiSelectedLoraForTemplateNode(binding.nodeId);
    if (Object.prototype.hasOwnProperty.call(comfyuiTemplateLoraOverrides, String(binding.nodeId || ""))) {
      return comfyuiTemplateLoraOverrides[String(binding.nodeId || "")];
    }
    return selected?.name || field?.current_value || "";
  }
  if (binding.kind === "lora_strength") {
    const selected = comfyuiSelectedLoraForTemplateNode(binding.nodeId);
    return selected?.[binding.strengthField] ?? field?.current_value ?? 1;
  }
  if (binding.kind === "direct") {
    const el = $(`tmpl-${field.id || ""}`);
    return el ? el.value : field?.current_value;
  }
  return field?.current_value;
}

function comfyuiTemplateDirectHint(field = {}) {
  const category = String(field?.category || "").toUpperCase();
  const classType = String(field?.class_type || "");
  const inputName = String(field?.input_name || "");
  if (category === "MODEL") {
    if (/clip/i.test(inputName)) return "填 ComfyUI models/clip 或 text_encoders 內實際檔名；缺檔時相容性檢查會提示。";
    if (/unet/i.test(inputName)) return "填 ComfyUI models/diffusion_models 或 unet 內實際檔名；請對應 Flux、SD3.5、Wan 等模型。";
    return "填已安裝模型檔名；若本地或遠端 ComfyUI 找不到，送出前會提示缺少依賴。";
  }
  if (category === "SAMPLER") return "使用 ComfyUI 節點支援的取樣器或排程器名稱。";
  if (classType === "WanImageToVideo" && ["width", "height", "length"].includes(inputName)) return "Wan 影片尺寸與幀數會直接影響 VRAM、速度與輸出長度。";
  if (category === "NUMERIC") return "這是該模型節點的進階數值；不了解時可先保留預設。";
  return "";
}

function normalizeComfyuiTemplateRuntimeValue(field, value) {
  if (field?.category === "NUMERIC" || field?.input_type === "number") {
    const number = Number(value);
    return Number.isFinite(number) ? number : Number(field?.current_value || 0);
  }
  return value === undefined || value === null ? "" : String(value);
}

function collectComfyuiTemplateUserInputs(detail) {
  const userInputs = {};
  const ctx = { textFieldIndex: 0, loadImageIndex: 0 };
  const panels = Array.isArray(detail?.ui_schema?.panels) ? detail.ui_schema.panels : [];
  panels.forEach((panel) => {
    (panel?.fields || []).forEach((field) => {
      if (!field || field.synthetic || field.input_type === "embedding_shortcuts" || !field.node_id || !field.input_name) return;
      const binding = comfyuiTemplateFieldBinding(field, detail, ctx);
      if (binding.kind === "image") return;
      const rawValue = comfyuiTemplateRuntimeValue(binding, field);
      if (!userInputs[field.node_id]) userInputs[field.node_id] = {};
      userInputs[field.node_id][field.input_name] = normalizeComfyuiTemplateRuntimeValue(field, rawValue);
    });
  });
  return userInputs;
}

function collectComfyuiTemplateImageAssignments(detail) {
  const assignments = {};
  const missing = [];
  const ctx = { textFieldIndex: 0, loadImageIndex: 0 };
  const panels = Array.isArray(detail?.ui_schema?.panels) ? detail.ui_schema.panels : [];
  panels.forEach((panel) => {
    (panel?.fields || []).forEach((field) => {
      if (!field || field.synthetic || field.input_type === "embedding_shortcuts" || !field.node_id || !field.input_name) return;
      const binding = comfyuiTemplateFieldBinding(field, detail, ctx);
      if (binding.kind !== "image") return;
      const asset = comfyuiAssetState(binding.assetKey);
      if (asset?.cloudFileId) {
        assignments[String(field.node_id)] = String(asset.cloudFileId);
      } else {
        missing.push({
          nodeId: String(field.node_id),
          label: field.label || field.input_name || `Node ${field.node_id}`,
          assetKey: binding.assetKey,
          hasLocalFile: !!asset?.file,
          hasImageRef: !!asset?.imageRef,
        });
      }
    });
  });
  return { assignments, missing };
}

function comfyuiTemplateUpdateField(binding, field, rawValue) {
  if (binding.enableControlnet && $("comfyui-controlnet-enabled")) {
    $("comfyui-controlnet-enabled").checked = true;
  }
  if (binding.kind === "field") {
    setComfyuiFieldValue(binding.targetId, rawValue);
    updateComfyuiModeVisibility();
    writeComfyuiDraft();
  }
}

function renderComfyuiTemplateEmbeddingShortcuts(field) {
  const values = Array.isArray(comfyuiAvailableEmbeddings) ? comfyuiAvailableEmbeddings : [];
  const content = values.length
    ? values.map((value) => (
      `<button class="comfyui-embedding-chip" type="button" data-comfyui-template-embedding="${sanitize(value)}" title="插入 ${sanitize(value)}">${sanitize(value)}</button>`
    )).join("")
    : '<span class="drive-card-sub">目前沒有可用的 Embedding。</span>';
  return `
    <div class="comfyui-template-field-card is-wide">
      <label>${sanitize(field?.label || "Embedding 快速插入")}</label>
      <div class="comfyui-embedding-shortcuts">${content}</div>
      <div class="drive-card-sub">點一下會把 <code>&lt;embeddings:名稱&gt;</code> 插入正向或負面提示詞。</div>
    </div>
  `;
}

function renderComfyuiTemplateField(field, detail, ctx) {
  if (field?.input_type === "embedding_shortcuts") {
    return renderComfyuiTemplateEmbeddingShortcuts(field);
  }
  const binding = comfyuiTemplateFieldBinding(field, detail, ctx);
  const cardClass = field?.input_type === "textarea" || binding.kind === "image" ? "comfyui-template-field-card is-wide" : "comfyui-template-field-card";
  if (binding.kind === "image") {
    const asset = comfyuiTemplateFieldValue(binding, field) || {};
    const previewHtml = asset.previewUrl
      ? `<img src="${sanitize(asset.previewUrl)}" alt="${sanitize(field.label || "圖片預覽")}" />`
      : `<span class="drive-card-sub">${sanitize(COMFYUI_INPUT_ASSET_META[binding.assetKey]?.emptyText || "尚未選擇圖片")}</span>`;
    const metaText = asset.file
      ? `已選擇本地檔：${asset.filename || asset.file.name || "未命名圖片"}`
      : asset.imageRef?.filename
        ? `使用已保存圖片：${asset.filename || asset.imageRef.filename}`
        : (COMFYUI_INPUT_ASSET_META[binding.assetKey]?.emptyText || "尚未選擇圖片");
    return `
      <div class="${cardClass}">
        <label>${sanitize(field.label || "圖片")}</label>
        <input type="file" data-comfyui-template-image="${sanitize(binding.assetKey)}" accept="image/png,image/jpeg,image/webp" />
        <div class="comfyui-input-preview" style="margin-top:.55rem;">${previewHtml}</div>
        <div class="drive-card-sub" style="margin-top:.45rem;">${sanitize(metaText)}</div>
        <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.45rem;">
          <button class="btn btn-sm" type="button" data-comfyui-template-image-picker="${sanitize(binding.assetKey)}">選擇既有圖片</button>
          ${binding.assetKey === "mask" ? `<button class="btn btn-sm" type="button" data-comfyui-template-mask-editor="1">編輯遮罩</button>` : ""}
          <button class="btn btn-sm" type="button" data-comfyui-template-image-clear="${sanitize(binding.assetKey)}">清除圖片</button>
        </div>
      </div>
    `;
  }
  if (binding.kind === "readonly") {
    return `
      <div class="${cardClass}">
        <label>${sanitize(field.label || field.input_name || "欄位")}</label>
        <div class="comfyui-template-readonly">這個欄位目前沿用模板預設值：${sanitize(String(field?.current_value ?? ""))}</div>
      </div>
    `;
  }
  if (binding.kind === "direct") {
    const value = comfyuiTemplateFieldValue(binding, field);
    const inputType = field?.input_type === "number" ? "number" : "text";
    const minAttr = field?.constraints?.min !== undefined ? ` min="${sanitize(String(field.constraints.min))}"` : "";
    const maxAttr = field?.constraints?.max !== undefined ? ` max="${sanitize(String(field.constraints.max))}"` : "";
    const stepAttr = field?.constraints?.step !== undefined ? ` step="${sanitize(String(field.constraints.step))}"` : "";
    const hint = comfyuiTemplateDirectHint(field);
    return `
      <div class="${cardClass}">
        <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || field.input_name || "欄位")}</label>
        <input id="tmpl-${sanitize(field.id || "")}" type="${sanitize(inputType)}" value="${sanitize(String(value ?? ""))}"${minAttr}${maxAttr}${stepAttr} />
        ${hint ? `<div class="comfyui-template-direct-hint">${sanitize(hint)}</div>` : ""}
      </div>
    `;
  }
  if (binding.kind === "lora") {
    const selected = comfyuiSelectedLoraForTemplateNode(binding.nodeId);
    const overrideKey = String(binding.nodeId || "");
    const current = Object.prototype.hasOwnProperty.call(comfyuiTemplateLoraOverrides, overrideKey)
      ? comfyuiTemplateLoraOverrides[overrideKey]
      : (selected?.name || String(field?.current_value || ""));
    const options = comfyuiTemplateLoraSelectOptions(field);
    return `
      <div class="${cardClass}">
        <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || "LoRA 模型")}</label>
        <select id="tmpl-${sanitize(field.id || "")}" data-comfyui-template-lora-node="${sanitize(binding.nodeId)}">
          ${options.map((option) => `<option value="${sanitize(option.value)}"${option.value === current ? " selected" : ""}${option.disabled ? ' disabled="disabled"' : ""}>${sanitize(option.label)}</option>`).join("")}
        </select>
        <div class="drive-card-sub">選擇後會加入 LoRA 清單，並自動把 Civitai trigger words 補到正向提示詞。</div>
      </div>
    `;
  }
  if (binding.kind === "lora_strength") {
    const selected = comfyuiSelectedLoraForTemplateNode(binding.nodeId);
    const value = selected?.[binding.strengthField] ?? field?.current_value ?? 1;
    const minAttr = field?.constraints?.min !== undefined ? ` min="${sanitize(String(field.constraints.min))}"` : "";
    const maxAttr = field?.constraints?.max !== undefined ? ` max="${sanitize(String(field.constraints.max))}"` : "";
    const stepAttr = field?.constraints?.step !== undefined ? ` step="${sanitize(String(field.constraints.step))}"` : "";
    return `
      <div class="${cardClass}">
        <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || field.input_name || "LoRA 權重")}</label>
        <input id="tmpl-${sanitize(field.id || "")}" type="number" value="${sanitize(String(value ?? 1))}"${minAttr}${maxAttr}${stepAttr} data-comfyui-template-lora-strength="${sanitize(binding.nodeId)}" data-comfyui-template-lora-strength-field="${sanitize(binding.strengthField)}" />
      </div>
    `;
  }
  const value = comfyuiTemplateFieldValue(binding, field);
  if (field?.input_type === "textarea") {
    return `
      <div class="${cardClass}">
        <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || field.input_name || "欄位")}</label>
        <textarea id="tmpl-${sanitize(field.id || "")}" rows="${sanitize(String(field?.constraints?.rows || 4))}" data-comfyui-template-target="${sanitize(binding.targetId)}">${sanitize(value)}</textarea>
      </div>
    `;
  }
  if (field?.input_type === "select") {
    const options = comfyuiTemplateSelectOptions(binding.targetId, field);
    const current = String(value || field?.current_value || "");
    return `
      <div class="${cardClass}">
        <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || field.input_name || "欄位")}</label>
        <select id="tmpl-${sanitize(field.id || "")}" data-comfyui-template-target="${sanitize(binding.targetId)}">
          ${options.map((option) => `<option value="${sanitize(option.value)}"${option.value === current ? " selected" : ""}${option.disabled ? ' disabled="disabled"' : ""}>${sanitize(option.label)}</option>`).join("")}
        </select>
      </div>
    `;
  }
  const inputType = field?.input_type === "number" ? "number" : "text";
  const minAttr = field?.constraints?.min !== undefined ? ` min="${sanitize(String(field.constraints.min))}"` : "";
  const maxAttr = field?.constraints?.max !== undefined ? ` max="${sanitize(String(field.constraints.max))}"` : "";
  const stepAttr = field?.constraints?.step !== undefined ? ` step="${sanitize(String(field.constraints.step))}"` : "";
  return `
    <div class="${cardClass}">
      <label for="tmpl-${sanitize(field.id || "")}">${sanitize(field.label || field.input_name || "欄位")}</label>
      <input id="tmpl-${sanitize(field.id || "")}" type="${sanitize(inputType)}" value="${sanitize(String(value ?? ""))}"${minAttr}${maxAttr}${stepAttr} data-comfyui-template-target="${sanitize(binding.targetId)}" />
    </div>
  `;
}

function bindRenderedComfyuiTemplateFields(detail) {
  const host = $("comfyui-template-panels");
  if (!host) return;
  host.querySelectorAll("[data-comfyui-template-target]").forEach((el) => {
    const targetId = el.getAttribute("data-comfyui-template-target");
    const hidden = $(targetId);
    if (!hidden || el.dataset.boundComfyuiTemplate === "1") return;
    el.dataset.boundComfyuiTemplate = "1";
    const sync = () => {
      hidden.value = el.value;
      if (targetId === "comfyui-controlnet-model" && $("comfyui-controlnet-enabled")) $("comfyui-controlnet-enabled").checked = true;
      updateComfyuiModeVisibility();
      writeComfyuiDraft();
    };
    el.addEventListener("input", sync);
    el.addEventListener("change", sync);
  });
  host.querySelectorAll("[data-comfyui-template-image]").forEach((input) => {
    if (input.dataset.boundComfyuiTemplate === "1") return;
    input.dataset.boundComfyuiTemplate = "1";
    input.addEventListener("change", () => {
      const assetKey = input.getAttribute("data-comfyui-template-image");
      const file = input.files && input.files[0] ? input.files[0] : null;
      if (!file) {
        clearComfyuiInputAsset(assetKey);
        renderSelectedComfyuiTemplate();
        return;
      }
      if (!/^image\/(png|jpeg|webp)$/i.test(file.type || "")) {
        setComfyuiMessage("模板圖片欄位只支援 PNG、JPG、WEBP。", false);
        input.value = "";
        return;
      }
      setComfyuiInputAssetFromFile(assetKey, file);
      renderSelectedComfyuiTemplate();
    });
  });
  host.querySelectorAll("[data-comfyui-template-image-clear]").forEach((button) => {
    if (button.dataset.boundComfyuiTemplate === "1") return;
    button.dataset.boundComfyuiTemplate = "1";
    button.addEventListener("click", () => {
      clearComfyuiInputAsset(button.getAttribute("data-comfyui-template-image-clear"));
      renderSelectedComfyuiTemplate();
    });
  });
  host.querySelectorAll("[data-comfyui-template-image-picker]").forEach((button) => {
    if (button.dataset.boundComfyuiTemplate === "1") return;
    button.dataset.boundComfyuiTemplate = "1";
    button.addEventListener("click", () => {
      openComfyuiImagePicker(button.getAttribute("data-comfyui-template-image-picker"))
        .catch((err) => setComfyuiMessage(err.message || "圖片選擇器開啟失敗", false));
    });
  });
  host.querySelectorAll("[data-comfyui-template-mask-editor]").forEach((button) => {
    if (button.dataset.boundComfyuiTemplate === "1") return;
    button.dataset.boundComfyuiTemplate = "1";
    button.addEventListener("click", () => openComfyuiMaskEditor());
  });
  host.querySelectorAll("[data-comfyui-template-lora-node]").forEach((select) => {
    if (select.dataset.boundComfyuiTemplate === "1") return;
    select.dataset.boundComfyuiTemplate = "1";
    select.addEventListener("change", () => {
      const nodeId = select.getAttribute("data-comfyui-template-lora-node");
      if (upsertComfyuiTemplateLora(nodeId, select.value)) {
        renderSelectedComfyuiTemplate({ preserveOpenPanels: true });
      }
    });
  });
  host.querySelectorAll("[data-comfyui-template-lora-strength]").forEach((input) => {
    if (input.dataset.boundComfyuiTemplate === "1") return;
    input.dataset.boundComfyuiTemplate = "1";
    const sync = () => {
      const nodeId = input.getAttribute("data-comfyui-template-lora-strength");
      const field = input.getAttribute("data-comfyui-template-lora-strength-field");
      const normalized = updateComfyuiTemplateLoraStrength(nodeId, field, input.value);
      if (normalized !== null) input.value = String(normalized);
    };
    input.addEventListener("input", sync);
    input.addEventListener("change", sync);
  });
  host.querySelectorAll("[data-comfyui-template-embedding]").forEach((button) => {
    if (button.dataset.boundComfyuiTemplate === "1") return;
    button.dataset.boundComfyuiTemplate = "1";
    button.addEventListener("click", () => {
      insertComfyuiEmbeddingToken(button.getAttribute("data-comfyui-template-embedding"));
      renderSelectedComfyuiTemplate({ preserveOpenPanels: true });
    });
  });
}

function renderSelectedComfyuiTemplate({ preserveOpenPanels = false } = {}) {
  const summary = $("comfyui-template-summary");
  const host = $("comfyui-template-panels");
  const legacy = $("comfyui-legacy-form-panel");
  if (summary) summary.innerHTML = comfyuiTemplateSummaryMarkup(comfyuiSelectedTemplateDetail);
  if (!host) return;
  if (!comfyuiSelectedTemplateDetail?.ui_schema?.panels) {
    if (summary) summary.hidden = true;
    host.hidden = true;
    host.innerHTML = "";
    if (legacy) legacy.style.display = "none";
    if (typeof updateComfyuiDiffusersUi === "function") updateComfyuiDiffusersUi();
    return;
  }
  if (summary) summary.hidden = false;
  host.hidden = false;
  const detail = comfyuiSelectedTemplateDetail;
  const ctx = { textFieldIndex: 0, loadImageIndex: 0 };
  const panels = (detail.ui_schema.panels || []).filter((panel) => !["compatibility", "raw"].includes(String(panel?.id || "")));
  const openPanelIds = preserveOpenPanels
    ? new Set(Array.from(host.querySelectorAll("[data-comfyui-template-panel-id]"))
      .filter((section) => section.open)
      .map((section) => section.getAttribute("data-comfyui-template-panel-id")))
    : new Set();
  host.innerHTML = panels.map((panel) => {
    const panelId = String(panel?.id || "");
    const isOpen = preserveOpenPanels ? openPanelIds.has(panelId) : !panel?.collapsed_default;
    return `
    <details class="drive-collapsible-panel settings-collapse comfyui-template-render-card" data-comfyui-template-panel-id="${sanitize(panelId)}"${isOpen ? " open" : ""}>
      <summary>
        <div>
          <div class="drive-card-title">${sanitize(panel?.label || panel?.id || "模板區塊")}</div>
          <div class="drive-card-sub">${sanitize(String((panel?.fields || []).filter((field) => !field?.synthetic && field?.input_type !== "embedding_shortcuts").length || 0))} 個欄位</div>
        </div>
      </summary>
      <div class="drive-collapsible-body">
        <div class="comfyui-template-panel-grid">
          ${(panel?.fields || []).map((field) => renderComfyuiTemplateField(field, detail, ctx)).join("")}
        </div>
      </div>
    </details>
  `;
  }).join("");
  bindRenderedComfyuiTemplateFields(detail);
  if (legacy) legacy.style.display = "";
  if (typeof updateComfyuiDiffusersUi === "function") updateComfyuiDiffusersUi();
}

function renderComfyuiWorkflowPresetList(targetId, items, emptyText) {
  const list = $(targetId);
  if (!list) return;
  if (!Array.isArray(items) || !items.length) {
    list.innerHTML = `<div class="drive-empty">${sanitize(emptyText)}</div>`;
    return;
  }
  list.innerHTML = items.map((item) => {
    const dependencyHtml = comfyuiWorkflowDependencyHtml(item?.dependency_status || null);
    const models = Array.isArray(item?.required_models) ? item.required_models.map((entry) => `${entry.kind || "model"}:${entry.name || ""}`) : [];
    const loras = Array.isArray(item?.required_loras) ? item.required_loras.map((entry) => entry.name || entry) : [];
    const controlnets = Array.isArray(item?.required_controlnets) ? item.required_controlnets.map((entry) => entry.name || entry) : [];
    const customNodes = Array.isArray(item?.required_custom_nodes) ? item.required_custom_nodes : [];
    const manifest = item?.manifest_summary || {};
    const mode = item?.default_params?.generation_mode ? comfyuiReadableModeLabel(item.default_params.generation_mode) : "Workflow";
    const purpose = item?.purpose || item?.default_params?.generation_mode || "custom";
    const versionWarnings = Array.isArray(item?.version_warnings) ? item.version_warnings : [];
    return `
      <div class="comfyui-workflow-item">
        <div class="comfyui-workflow-item-head">
          <div class="comfyui-workflow-item-title">
            <strong>${sanitize(item?.title || `Workflow #${item?.id || ""}`)}</strong>
            <span>${sanitize(mode)} · ${sanitize(purpose)} · ${sanitize(String(item?.updated_at || "").replace("T", " ").slice(0, 16))}</span>
          </div>
          <div class="comfyui-workflow-flags">
            ${item?.is_official ? '<span class="comfyui-workflow-chip">官方</span>' : ""}
            ${item?.is_default ? '<span class="comfyui-workflow-chip">預設</span>' : ""}
            <span class="comfyui-workflow-chip">${sanitize(item?.visibility || "private")}</span>
            <span class="comfyui-workflow-chip">Project ${sanitize(item?.project_version || "-")}</span>
            <span class="comfyui-workflow-chip">ComfyUI ${sanitize(item?.comfyui_version || "-")}</span>
            ${manifest?.available ? `<span class="comfyui-workflow-chip">Manifest ${sanitize(String(manifest.panel_count || 0))} panels</span>` : ""}
            <span class="comfyui-workflow-chip">${sanitize(String((item?.workflow_hash || "").slice(0, 12) || "-"))}</span>
          </div>
        </div>
        <div class="drive-card-sub">${sanitize(item?.description || "未填寫說明")}</div>
        <div class="comfyui-workflow-meta">
          ${models.length ? `<span class="comfyui-workflow-chip">模型 ${sanitize(String(models.length))}</span>` : ""}
          ${loras.length ? `<span class="comfyui-workflow-chip">LoRA ${sanitize(String(loras.length))}</span>` : ""}
          ${controlnets.length ? `<span class="comfyui-workflow-chip">ControlNet ${sanitize(String(controlnets.length))}</span>` : ""}
          ${customNodes.length ? `<span class="comfyui-workflow-chip warn">Custom nodes ${sanitize(String(customNodes.length))}</span>` : ""}
        </div>
        ${versionWarnings.length ? `<div class="drive-card-sub" style="margin-top:.4rem;color:#ffe08a;">版本警告：${sanitize(versionWarnings.join("；"))}</div>` : ""}
        ${comfyuiWorkflowPaidApiWarningHtml(item)}
        ${dependencyHtml}
        <div class="drive-card-sub">所需模型：${sanitize(models.join(", ") || "無")}</div>
        <div class="drive-card-sub">所需 LoRA：${sanitize(loras.join(", ") || "無")}</div>
        <div class="drive-card-sub">所需 ControlNet：${sanitize(controlnets.join(", ") || "無")}</div>
        <div class="drive-card-sub">所需 Custom nodes：${sanitize(customNodes.join(", ") || "無")}</div>
        ${renderComfyuiWorkflowRunList(item?.recent_runs || [])}
        <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.55rem;">
          <button class="btn btn-sm" type="button" data-comfyui-workflow-apply="${item.id}">套回表單</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-run="${item.id}">執行</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-export="${item.id}">匯出 JSON</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-edit="${item.id}">載入編輯</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-duplicate="${item.id}">複製</button>
          ${item?.can_edit ? `<button class="btn btn-sm" type="button" data-comfyui-workflow-default="${item.id}">設為預設</button>` : ""}
          ${item?.can_publish_official && !item?.is_official ? `<button class="btn btn-sm" type="button" data-comfyui-workflow-publish="${item.id}">發布官方</button>` : ""}
          ${item?.can_edit ? `<button class="btn btn-sm" type="button" data-comfyui-workflow-delete="${item.id}">刪除</button>` : ""}
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-comfyui-workflow-apply]").forEach((button) => {
    button.addEventListener("click", () => applyComfyuiWorkflowPresetToForm(Number(button.getAttribute("data-comfyui-workflow-apply"))));
  });
  list.querySelectorAll("[data-comfyui-workflow-run]").forEach((button) => {
    button.addEventListener("click", () => {
      runComfyuiWorkflowPreset(Number(button.getAttribute("data-comfyui-workflow-run"))).catch((err) => setComfyuiMessage(err.message || "workflow 執行失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-export]").forEach((button) => {
    button.addEventListener("click", () => {
      exportComfyuiWorkflowPreset(Number(button.getAttribute("data-comfyui-workflow-export"))).catch((err) => setComfyuiMessage(err.message || "workflow 匯出失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      loadComfyuiWorkflowPresetIntoEditor(Number(button.getAttribute("data-comfyui-workflow-edit"))).catch((err) => setComfyuiMessage(err.message || "workflow 讀取失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-duplicate]").forEach((button) => {
    button.addEventListener("click", () => {
      duplicateComfyuiWorkflowPreset(Number(button.getAttribute("data-comfyui-workflow-duplicate"))).catch((err) => setComfyuiMessage(err.message || "workflow 複製失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-default]").forEach((button) => {
    button.addEventListener("click", () => {
      setDefaultComfyuiWorkflowPreset(Number(button.getAttribute("data-comfyui-workflow-default"))).catch((err) => setComfyuiMessage(err.message || "預設版面設定失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-publish]").forEach((button) => {
    button.addEventListener("click", () => {
      publishComfyuiWorkflowPresetOfficial(Number(button.getAttribute("data-comfyui-workflow-publish"))).catch((err) => setComfyuiMessage(err.message || "官方 preset 發布失敗", false));
    });
  });
  list.querySelectorAll("[data-comfyui-workflow-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteComfyuiWorkflowPreset(Number(button.getAttribute("data-comfyui-workflow-delete"))).catch((err) => setComfyuiMessage(err.message || "workflow 刪除失敗", false));
    });
  });
}

function renderComfyuiWorkflowPresets(payload = {}, { silentTemplateReload = true } = {}) {
  comfyuiWorkflowPresets = Array.isArray(payload.presets) ? payload.presets : [];
  renderComfyuiWorkflowPresetList("comfyui-workflow-my-list", payload.my_presets || [], "尚無個人工作流版面");
  renderComfyuiWorkflowPresetList("comfyui-workflow-official-list", payload.official_presets || [], "尚無官方工作流版面");
  renderComfyuiWorkflowPresetList("comfyui-workflow-shared-list", payload.shared_presets || [], "尚無其他可讀工作流版面");
  renderComfyuiTemplateSelector(payload, { silentReload: silentTemplateReload });
  const total = comfyuiWorkflowPresets.length;
  const warning = payload.dependency_warning ? `；依賴檢查警告：${payload.dependency_warning}` : "";
  setComfyuiWorkflowStatus(`目前可見 ${total} 個 workflow 版面${warning}`);
}

async function loadComfyuiWorkflowPresets() {
  const { silentTemplateReload = true } = arguments[0] || {};
  if (!currentUser || !canAccessModule("comfyui")) return [];
  setComfyuiWorkflowStatus("正在讀取 workflow preset...");
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/comfyui/workflows", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    const message = json.msg || `workflow preset 讀取失敗（HTTP ${res.status}）`;
    setComfyuiWorkflowStatus(message);
    throw new Error(message);
  }
  renderComfyuiWorkflowPresets(json, { silentTemplateReload });
  return comfyuiWorkflowPresets;
}

function applyComfyuiWorkflowPresetDefaults(defaults = {}) {
  const payload = defaults || {};
  const controlnet = payload.controlnet || {};
  const loras = Array.isArray(payload.loras) ? payload.loras : [];
  comfyuiSelectedLoras = loras
    .filter((entry) => entry && typeof entry === "object" && entry.name)
    .slice(0, COMFYUI_MAX_LORAS)
    .map((entry) => ({
      name: String(entry.name),
      strength_model: Number.isFinite(Number(entry.strength_model)) ? Number(entry.strength_model) : 1,
      strength_clip: Number.isFinite(Number(entry.strength_clip)) ? Number(entry.strength_clip) : 1,
    }));
  renderComfyuiSelectedLoras();
  [
    ["comfyui-generation-mode", payload.generation_mode || "txt2img"],
    ["comfyui-model-select", payload.model || ""],
    ["comfyui-vae-select", payload.vae || COMFYUI_VAE_BUILTIN],
    ["comfyui-prompt", payload.prompt || ""],
    ["comfyui-negative-prompt", payload.negative_prompt || ""],
    ["comfyui-width", payload.width || comfyuiDefaultWidth],
    ["comfyui-height", payload.height || comfyuiDefaultHeight],
    ["comfyui-steps", payload.steps || 20],
    ["comfyui-cfg", payload.cfg || 7],
    ["comfyui-batch-size", payload.batch_size || 1],
    ["comfyui-seed", payload.seed ?? ""],
    ["comfyui-sampler", payload.sampler_name || "euler"],
    ["comfyui-scheduler", payload.scheduler || "normal"],
    ["comfyui-denoise-strength", payload.denoise_strength ?? 0.65],
    ["comfyui-upscale-model", payload.upscale_model || ""],
    ["comfyui-controlnet-type", controlnet.type || "canny"],
    ["comfyui-controlnet-model", controlnet.model_name || ""],
    ["comfyui-controlnet-preprocessor", controlnet.preprocessor || ""],
    ["comfyui-control-strength", controlnet.strength ?? 1],
    ["comfyui-control-start", controlnet.start_percent ?? 0],
    ["comfyui-control-end", controlnet.end_percent ?? 1],
  ].forEach(([id, value]) => setComfyuiFieldValue(id, value));
  if ($("comfyui-controlnet-enabled")) $("comfyui-controlnet-enabled").checked = !!controlnet?.type;
  updateComfyuiModeVisibility();
  writeComfyuiDraft();
}

function applyComfyuiWorkflowPresetToForm(presetId) {
  const item = comfyuiWorkflowPresetById(presetId);
  if (!item) {
    setComfyuiMessage("找不到這個 workflow preset。", false);
    return;
  }
  applyComfyuiWorkflowPresetDefaults(item.default_params || {});
  setComfyuiMessage(`已套用「${item.title || `Workflow #${presetId}`}」的預設參數；若 workflow 需要來源圖、遮罩或控制圖，請另外確認目前表單已提供。`, true);
}

async function loadComfyuiWorkflowPresetIntoEditor(presetId) {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 讀取失敗（HTTP ${res.status}）`);
  const preset = json.preset || {};
  comfyuiWorkflowCurrentPresetId = Number(preset.id) || null;
  comfyuiWorkflowEditorDefaults = preset.default_params || null;
  setComfyuiFieldValue("comfyui-workflow-title", preset.title || "");
  setComfyuiFieldValue("comfyui-workflow-description", preset.description || "");
  setComfyuiFieldValue("comfyui-workflow-visibility", preset.visibility || "private");
  setComfyuiFieldValue("comfyui-workflow-purpose", preset.purpose || preset.default_params?.generation_mode || "custom");
  setComfyuiFieldValue("comfyui-workflow-comfyui-version", preset.comfyui_version || "");
  setComfyuiFieldValue("comfyui-workflow-project-version", preset.project_version || "");
  setComfyuiFieldValue("comfyui-workflow-schema-version", preset.workflow_schema_version || "1");
  setComfyuiFieldValue("comfyui-workflow-json", JSON.stringify(preset.workflow_json || {}, null, 2));
  setComfyuiFieldValue("comfyui-workflow-layout-json", JSON.stringify(preset.layout_json || {}, null, 2));
  renderComfyuiWorkflowBuilderPreview();
  const defaultInput = $("comfyui-workflow-is-default");
  if (defaultInput) defaultInput.checked = !!preset.is_default;
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = !preset.can_edit;
  const versionCount = Array.isArray(preset.layout_versions) ? preset.layout_versions.length : 0;
  setComfyuiWorkflowStatus(`正在編輯 #${preset.id} ${preset.title || ""}${versionCount ? `；保留 ${versionCount} 筆版本紀錄` : ""}`);
  const note = $("comfyui-workflow-editor-note");
  if (note) note.textContent = "已載入版面。修改後必須按「更新目前選擇」才會保存。";
}

function comfyuiCurrentWorkflowExportable() {
  const mode = comfyuiGenerationMode();
  if (comfyuiModeUsesSourceImage(mode) && comfyuiInputAssets.source?.file && !comfyuiInputAssets.source?.imageRef) {
    return "目前來源圖尚未有可重用 image_ref；若要匯出 img2img / inpaint / outpaint / upscale workflow，請先使用已上傳來源圖或套用歷史紀錄。";
  }
  if (comfyuiModeUsesMaskImage(mode) && comfyuiInputAssets.mask?.file && !comfyuiInputAssets.mask?.imageRef) {
    return "目前遮罩尚未有可重用 image_ref；請先使用已上傳遮罩或套用歷史紀錄。";
  }
  if (isComfyuiControlnetEnabled() && comfyuiInputAssets.control?.file && !comfyuiInputAssets.control?.imageRef) {
    return "目前控制圖尚未有可重用 image_ref；請先使用已上傳控制圖或套用歷史紀錄。";
  }
  return "";
}

async function exportCurrentComfyuiWorkflow() {
  const blocking = comfyuiCurrentWorkflowExportable();
  if (blocking) {
    setComfyuiMessage(blocking, false);
    return;
  }
  const payload = comfyuiPayload();
  const uiMessage = comfyuiValidatePayloadForUi(payload);
  if (uiMessage) {
    setComfyuiMessage(uiMessage, false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/comfyui/workflows/export-current", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify(payload),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 匯出失敗（HTTP ${res.status}）`);
  comfyuiWorkflowEditorDefaults = json.default_params || payload;
  setComfyuiFieldValue("comfyui-workflow-json", json.workflow_text || JSON.stringify(json.workflow_json || {}, null, 2));
  setComfyuiFieldValue("comfyui-workflow-layout-json", json.layout_text || JSON.stringify(json.layout_json || {}, null, 2));
  if (!$("comfyui-workflow-purpose")?.value && json.default_params?.generation_mode) setComfyuiFieldValue("comfyui-workflow-purpose", json.default_params.generation_mode);
  if (json.workflow_preset_json?.project_version) setComfyuiFieldValue("comfyui-workflow-project-version", json.workflow_preset_json.project_version);
  if (json.workflow_preset_json?.workflow_schema_version) setComfyuiFieldValue("comfyui-workflow-schema-version", json.workflow_preset_json.workflow_schema_version);
  setComfyuiWorkflowStatus(`已匯出目前 workflow，hash ${String((json.workflow_hash || "").slice(0, 12) || "-")}`);
  setComfyuiMessage("已把目前表單轉成 workflow 與 layout JSON，可直接保存成自訂版面。", true);
  downloadComfyuiWorkflowText(`comfyui-current-workflow-layout-${Date.now()}.json`, json.workflow_preset_text || JSON.stringify(json.workflow_preset_json || json.workflow_json || {}, null, 2));
}

async function importComfyuiWorkflowPreset() {
  const workflowText = String($("comfyui-workflow-json")?.value || "").trim();
  if (!workflowText) {
    setComfyuiMessage("請先貼上 workflow JSON，或先匯出目前 workflow。", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/comfyui/workflows/import", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({
      ...comfyuiWorkflowEditorPayload(),
      workflow_json: workflowText,
      default_params: comfyuiWorkflowEditorDefaults || undefined,
    }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 匯入失敗（HTTP ${res.status}）`);
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage(json.msg || "已匯入 workflow preset。", true);
}

async function updateComfyuiWorkflowPreset() {
  if (!comfyuiWorkflowCurrentPresetId) {
    setComfyuiMessage("目前沒有選到可更新的 workflow preset。", false);
    return;
  }
  const workflowText = String($("comfyui-workflow-json")?.value || "").trim();
  if (!workflowText) {
    setComfyuiMessage("workflow JSON 不可為空。", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(comfyuiWorkflowCurrentPresetId)}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({
      ...comfyuiWorkflowEditorPayload(),
      workflow_json: workflowText,
      default_params: comfyuiWorkflowEditorDefaults || undefined,
    }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 更新失敗（HTTP ${res.status}）`);
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage(json.msg || "已更新 workflow preset。", true);
}

async function runComfyuiWorkflowPreset(presetId) {
  if (!presetId) return;
  const preset = comfyuiWorkflowPresetById(presetId);
  const templateDetail = Number(comfyuiSelectedTemplateDetail?.id || 0) === Number(presetId) ? comfyuiSelectedTemplateDetail : null;
  const userInputs = templateDetail ? collectComfyuiTemplateUserInputs(templateDetail) : {};
  const imageAssignmentState = templateDetail ? collectComfyuiTemplateImageAssignments(templateDetail) : { assignments: {}, missing: [] };
  if (imageAssignmentState.missing.length) {
    const labels = imageAssignmentState.missing.map((item) => item.label || `Node ${item.nodeId}`).slice(0, 4).join("、");
    setComfyuiMessage(`這個 workflow 有圖片欄位尚未指定可安全重映射的雲端圖片：${labels}。請用「選擇既有圖片」選雲端硬碟圖片，或選歷史產圖讓系統先匯入雲端硬碟。`, false);
    return;
  }
  const paidApiNodes = comfyuiWorkflowPaidApiNodes(preset);
  let confirmPaidApiNodes = false;
  if (paidApiNodes.length) {
    const labels = paidApiNodes.map((node) => `${node.node_id || "-"}:${node.class_type || node.title || "API node"}`).slice(0, 8);
    confirmPaidApiNodes = window.confirm(
      `這個 workflow 可能會消耗 ComfyUI 官方 credits，不會扣本站積分。\n\n節點：${labels.join(", ")}${paidApiNodes.length > labels.length ? `，另 ${paidApiNodes.length - labels.length} 個` : ""}\n\n餘額與購買請到 ComfyUI UI 的 Settings / Credits 查看。\n\n要繼續執行嗎？`
    );
    if (!confirmPaidApiNodes) return;
  }
  await fetchCsrfToken({ force: true });
  setComfyuiBusy(true);
  setComfyuiMessage("正在建立 workflow 執行工作...", true);
  startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS);
  const controller = new AbortController();
  comfyuiGenerateAbortController = controller;
  const runRequest = (confirmed) => apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}/run`, {
    method: "POST",
    credentials: "same-origin",
    signal: controller.signal,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({
      confirm_paid_api_nodes: !!confirmed,
      user_inputs: userInputs,
      image_field_assignments: imageAssignmentState.assignments,
    }),
  });
  try {
    let res = await runRequest(confirmPaidApiNodes);
    let json = await res.json().catch(() => ({}));
    if ((!res.ok || !json.ok) && json.stage === "paid_api_confirmation_required") {
      const nodes = Array.isArray(json.paid_api_nodes?.nodes) ? json.paid_api_nodes.nodes : [];
      const labels = nodes.map((node) => `${node.node_id || "-"}:${node.class_type || node.title || "API node"}`).slice(0, 8);
      if (!window.confirm(`這個 workflow 可能會消耗 ComfyUI 官方 credits，不會扣本站積分。\n\n節點：${labels.join(", ") || "API node"}\n\n餘額與購買請到 ComfyUI UI 的 Settings / Credits 查看。\n\n要繼續執行嗎？`)) {
        throw new Error("已取消付費/API node workflow 執行");
      }
      res = await runRequest(true);
      json = await res.json().catch(() => ({}));
    }
    if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 執行失敗（HTTP ${res.status}）`);
    const result = await pollComfyuiJobUntilDone(json.job?.job_id, controller, COMFYUI_GENERATION_TIMEOUT_SECONDS);
    const rawImages = Array.isArray(result.images) && result.images.length ? result.images : [result.image].filter(Boolean);
    const images = await hydrateComfyuiGeneratedImages(rawImages);
    const media = Array.isArray(result.media) ? result.media : [];
    comfyuiGeneratedImages = images;
    comfyuiGeneratedMedia = media;
    renderComfyuiGeneratedImages(comfyuiGeneratedImages);
    setComfyuiSelectedImage(0);
    stopComfyuiProgress({ complete: true });
    updateComfyuiResultButtons(!!images.length);
    await loadComfyuiWorkflowPresets();
    setComfyuiMessage(`已執行 workflow preset #${presetId}，輸出 ${images.length} 張圖片、${media.length} 個媒體檔。`, true);
  } catch (err) {
    stopComfyuiProgress({ error: err.message || "workflow 執行失敗" });
    setComfyuiMessage(err.message || "workflow 執行失敗", false);
  } finally {
    if (comfyuiGenerateAbortController === controller) comfyuiGenerateAbortController = null;
    setComfyuiBusy(false);
  }
}

async function exportComfyuiWorkflowPreset(presetId) {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}/export`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({}),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 匯出失敗（HTTP ${res.status}）`);
  downloadComfyuiWorkflowText(json.filename || `comfyui-workflow-layout-${presetId}.json`, json.workflow_preset_text || JSON.stringify(json.workflow_preset_json || json.workflow_json || {}, null, 2));
  setComfyuiMessage(`已匯出 workflow 版面 #${presetId}，內含原始 workflow、本專案 preset 包裝與 UI layout。`, true);
}

async function duplicateComfyuiWorkflowPreset(presetId) {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 讀取失敗（HTTP ${res.status}）`);
  const preset = json.preset || {};
  const create = await apiFetch(API + "/comfyui/workflow-layouts", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({
      title: `${preset.title || `Workflow #${presetId}`} copy`,
      description: preset.description || "",
      visibility: "private",
      purpose: preset.purpose || "custom",
      comfyui_version: preset.comfyui_version || "",
      project_version: preset.project_version || "",
      workflow_schema_version: preset.workflow_schema_version || "1",
      layout_json: preset.layout_json || {},
      workflow_json: preset.workflow_json || {},
      default_params: preset.default_params || {},
      required_custom_nodes: preset.required_custom_nodes || [],
    }),
  });
  const created = await create.json().catch(() => ({}));
  if (!create.ok || !created.ok) throw new Error(created.msg || `workflow 複製失敗（HTTP ${create.status}）`);
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage(created.msg || "已複製為新的私人工作流版面。", true);
}

async function setDefaultComfyuiWorkflowPreset(presetId) {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({ is_default: true }),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `預設版面設定失敗（HTTP ${res.status}）`);
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage("已設為我的預設工作流版面。", true);
}

async function deleteComfyuiWorkflowPreset(presetId) {
  if (!window.confirm("刪除 workflow preset 後，對應的 preset 與最近執行結果會一併移除。要繼續嗎？")) return;
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}`, {
    method: "DELETE",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({}),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 刪除失敗（HTTP ${res.status}）`);
  if (Number(comfyuiWorkflowCurrentPresetId) === Number(presetId)) resetComfyuiWorkflowEditor({ keepStatus: true });
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage(json.msg || "已刪除 workflow preset。", true);
}

async function publishComfyuiWorkflowPresetOfficial(presetId) {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + `/admin/comfyui/workflows/${encodeURIComponent(presetId)}/publish-official`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || "",
    },
    body: JSON.stringify({}),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `官方 preset 發布失敗（HTTP ${res.status}）`);
  await loadComfyuiWorkflowPresets();
  setComfyuiMessage(json.msg || "已發布為官方 preset。", true);
}

async function loadComfyuiWorkflowFile() {
  const file = $("comfyui-workflow-file")?.files?.[0] || null;
  if (!file) return;
  const text = await file.text();
  setComfyuiFieldValue("comfyui-workflow-json", text);
  try {
    const parsed = JSON.parse(text);
    const wrapped = parsed?.workflow_preset_json || parsed;
    if (wrapped && typeof wrapped === "object" && wrapped.workflow_json) {
      setComfyuiFieldValue("comfyui-workflow-json", JSON.stringify(wrapped.workflow_json || {}, null, 2));
      setComfyuiFieldValue("comfyui-workflow-layout-json", JSON.stringify(wrapped.layout_json || {}, null, 2));
      setComfyuiFieldValue("comfyui-workflow-title", wrapped.name || wrapped.title || "");
      setComfyuiFieldValue("comfyui-workflow-description", wrapped.description || "");
      setComfyuiFieldValue("comfyui-workflow-purpose", wrapped.purpose || "custom");
      setComfyuiFieldValue("comfyui-workflow-comfyui-version", wrapped.comfyui_version || "");
      setComfyuiFieldValue("comfyui-workflow-project-version", wrapped.project_version || "");
      setComfyuiFieldValue("comfyui-workflow-schema-version", wrapped.workflow_schema_version || "1");
    }
  } catch (_) {
    // Keep raw text in the workflow editor; backend will return a schema_validation stage.
  }
  comfyuiWorkflowEditorDefaults = null;
  renderComfyuiWorkflowBuilderPreview();
  markComfyuiWorkflowEditorDirty();
  setComfyuiMessage(`已載入 workflow 檔：${file.name}`, true);
}
