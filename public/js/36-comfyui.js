'use strict';

let comfyuiCurrentImage = null;
let comfyuiGeneratedImages = [];
let comfyuiSelectedImageIndex = 0;
let comfyuiSavedResult = null;
let comfyuiModelsLoaded = false;
let comfyuiServerAvailable = null;
let comfyuiAlbumsLoaded = false;
let comfyuiProgressTimer = null;
let comfyuiProgressStartedAt = 0;
let comfyuiGenerateAbortController = null;
let comfyuiActiveJobId = null;
let comfyuiMaxBatchSize = 1;
let comfyuiBillingQuote = null;
let comfyuiDefaultWidth = 1024;
let comfyuiDefaultHeight = 1024;
let comfyuiAvailableLoras = [];
let comfyuiLoraDetails = {};
let comfyuiAvailableEmbeddings = [];
let comfyuiAvailableVaes = [];
let comfyuiSelectedLoras = [];
let comfyuiConnectionMode = "remote";
let comfyuiLocalStartPollTimer = null;
let comfyuiCivitaiInspection = null;
let comfyuiCivitaiSearchResults = [];
let comfyuiControlnetTypes = {};
let comfyuiUpscaleModels = [];
let comfyuiGenerationModes = [];
let comfyuiHistoryItems = [];
let comfyuiWorkflowPresets = [];
let comfyuiWorkflowCurrentPresetId = null;
let comfyuiWorkflowEditorDefaults = null;
let comfyuiInputAssets = {
  source: { file: null, imageRef: null, previewUrl: "", filename: "" },
  mask: { file: null, imageRef: null, previewUrl: "", filename: "" },
  control: { file: null, imageRef: null, previewUrl: "", filename: "" },
};
const COMFYUI_GENERATION_TIMEOUT_SECONDS = 1800;
const COMFYUI_MAX_LORAS = 8;
const COMFYUI_LORA_EXTRA_PRICE = 1;
const COMFYUI_VAE_BUILTIN = "__checkpoint_builtin__";
const COMFYUI_IMAGE_ASSET_KEYS = ["source", "mask", "control"];
const COMFYUI_CONTROLNET_TIPS = {
  canny: "適合保留邊緣與輪廓，常用於重畫原圖構圖。",
  depth: "適合保留場景深度與立體關係。",
  openpose: "適合固定人物姿勢與骨架。",
  lineart: "適合線稿上色或乾淨描線重建。",
  scribble: "適合塗鴉快速構圖。",
  softedge: "適合柔和邊緣與輪廓引導。",
  tile: "適合局部細節補強與放大。",
};
const COMFYUI_DRAFT_FIELD_IDS = [
  "comfyui-generation-mode",
  "comfyui-model-select",
  "comfyui-vae-select",
  "comfyui-prompt",
  "comfyui-negative-prompt",
  "comfyui-width",
  "comfyui-height",
  "comfyui-steps",
  "comfyui-cfg",
  "comfyui-batch-size",
  "comfyui-run-count",
  "comfyui-seed",
  "comfyui-sampler",
  "comfyui-scheduler",
  "comfyui-denoise-strength",
  "comfyui-upscale-model",
  "comfyui-controlnet-enabled",
  "comfyui-controlnet-type",
  "comfyui-controlnet-model",
  "comfyui-controlnet-preprocessor",
  "comfyui-control-strength",
  "comfyui-control-start",
  "comfyui-control-end",
  "comfyui-outpaint-left",
  "comfyui-outpaint-top",
  "comfyui-outpaint-right",
  "comfyui-outpaint-bottom",
  "comfyui-outpaint-feathering",
  "comfyui-save-path",
  "comfyui-album-select",
  "comfyui-share-title",
  "comfyui-share-note",
];
const COMFYUI_DYNAMIC_SELECT_IDS = [
  "comfyui-model-select",
  "comfyui-vae-select",
  "comfyui-sampler",
  "comfyui-scheduler",
  "comfyui-album-select",
  "comfyui-controlnet-type",
  "comfyui-controlnet-model",
  "comfyui-controlnet-preprocessor",
  "comfyui-upscale-model",
];
const COMFYUI_INPUT_ASSET_META = {
  source: {
    fileInputId: "comfyui-source-image-file",
    previewId: "comfyui-source-image-preview",
    metaId: "comfyui-source-image-meta",
    clearBtnId: "comfyui-source-image-clear-btn",
    cardId: "comfyui-source-image-card",
    emptyText: "尚未選擇來源圖片",
    title: "來源圖片",
  },
  mask: {
    fileInputId: "comfyui-mask-image-file",
    previewId: "comfyui-mask-image-preview",
    metaId: "comfyui-mask-image-meta",
    clearBtnId: "comfyui-mask-image-clear-btn",
    cardId: "comfyui-mask-image-card",
    emptyText: "尚未選擇遮罩圖片",
    title: "遮罩圖片",
  },
  control: {
    fileInputId: "comfyui-control-image-file",
    previewId: "comfyui-control-image-preview",
    metaId: "comfyui-control-image-meta",
    clearBtnId: "comfyui-control-image-clear-btn",
    cardId: "comfyui-control-image-card",
    emptyText: "尚未選擇控制圖",
    title: "控制圖",
  },
};

function setComfyuiTabAvailability(available, detail = "") {
  comfyuiServerAvailable = available === null ? null : !!available;
  const tab = $("tab-module-comfyui");
  if (tab) {
    tab.disabled = false;
    tab.classList.remove("disabled");
    tab.setAttribute("aria-disabled", "false");
    tab.title = detail || "";
  }
  const status = $("comfyui-status");
  if (status && comfyuiServerAvailable === false) {
    status.textContent = detail || "ComfyUI 伺服器未連線";
  }
  updateComfyuiStartButton();
}

function isComfyuiAvailableForNavigation() {
  return true;
}

function comfyuiRequestQuery() {
  return "";
}

function comfyuiRequestPayloadExtras() {
  return {};
}

function comfyuiBackendLabel(payload = {}) {
  return "";
}

function comfyuiConnectionModeLabel(mode = comfyuiConnectionMode) {
  return String(mode || "remote").trim().toLowerCase() === "local"
    ? "本地 ComfyUI"
    : "雲端 / 遠端 API";
}

function comfyuiConnectionModeDetail(mode = comfyuiConnectionMode) {
  return String(mode || "remote").trim().toLowerCase() === "local"
    ? "目前是本地模式：可由 root 啟動 / 停止本地 ComfyUI，且 root 可在下方折疊區管理本地模型下載。"
    : "目前是雲端 / 遠端模式：此頁會直接呼叫遠端 ComfyUI API 生圖，不提供本地模型下載。";
}

function updateComfyuiModeNote(modeOverride = null) {
  const normalizedMode = String(modeOverride || comfyuiConnectionMode || "remote").trim().toLowerCase() === "local"
    ? "local"
    : "remote";
  const note = $("comfyui-mode-note");
  const badge = $("comfyui-mode-badge");
  const detail = $("comfyui-mode-detail");
  if (note) note.textContent = `目前模式：${comfyuiConnectionModeLabel(normalizedMode)}`;
  if (badge) {
    badge.textContent = normalizedMode === "local" ? "本地模式" : "雲端 / 遠端模式";
    badge.dataset.mode = normalizedMode;
  }
  if (detail) detail.textContent = comfyuiConnectionModeDetail(normalizedMode);
}

function setComfyuiMessage(text, ok = true) {
  const msg = $("comfyui-msg");
  if (!msg) return;
  if (!text) {
    msg.className = "msg";
    msg.textContent = "";
    return;
  }
  flash(msg, text, ok);
}

function setComfyuiIdleSuspend(reason, active, label) {
  if (typeof setInactivitySuspendState === "function") {
    setInactivitySuspendState(reason, !!active, label || "ComfyUI 工作中");
  }
}

function setComfyuiBusy(busy) {
  const generate = $("comfyui-generate-btn");
  const interrupt = $("comfyui-interrupt-btn");
  const refresh = $("comfyui-refresh-btn");
  const start = $("comfyui-start-btn");
  const stop = $("comfyui-stop-btn");
  const unavailable = comfyuiServerAvailable === false;
  if (generate) {
    generate.disabled = !!busy || unavailable;
    generate.textContent = busy ? "產生中..." : "產生圖片";
  }
  if (interrupt) interrupt.disabled = !busy;
  if (refresh) refresh.disabled = !!busy;
  if (start) start.disabled = !!busy;
  if (stop) stop.disabled = !!busy;
  setComfyuiIdleSuspend("comfyui_generate", !!busy, "ComfyUI 產圖中");
}

function updateComfyuiStartButton() {
  const start = $("comfyui-start-btn");
  const stop = $("comfyui-stop-btn");
  const isRoot = currentUser === "root";
  updateComfyuiModeNote();
  if (start) {
    start.style.display = comfyuiConnectionMode === "local" && comfyuiServerAvailable !== true ? "" : "none";
    start.disabled = !!comfyuiGenerateAbortController;
  }
  if (stop) {
    stop.style.display = isRoot && comfyuiConnectionMode === "local" && comfyuiServerAvailable === true ? "" : "none";
    stop.disabled = !!comfyuiGenerateAbortController;
  }
}

function stopComfyuiLocalStartPolling() {
  if (comfyuiLocalStartPollTimer) {
    clearTimeout(comfyuiLocalStartPollTimer);
    comfyuiLocalStartPollTimer = null;
  }
  setComfyuiIdleSuspend("comfyui_start_local", false, "ComfyUI 啟動中");
}

function scheduleComfyuiLocalStartPolling({ attemptsLeft = 120, delayMs = 5000 } = {}) {
  stopComfyuiLocalStartPolling();
  if (comfyuiConnectionMode !== "local" || attemptsLeft <= 0) return;
  setComfyuiIdleSuspend("comfyui_start_local", true, "ComfyUI 啟動中");
  comfyuiLocalStartPollTimer = setTimeout(async () => {
    comfyuiLocalStartPollTimer = null;
    const ok = await refreshComfyuiStatus({ switchAway: false });
    if (ok) {
      setComfyuiMessage("本地 ComfyUI 已啟動完成。", true);
      await loadComfyuiModels();
      return;
    }
    scheduleComfyuiLocalStartPolling({ attemptsLeft: attemptsLeft - 1, delayMs });
  }, delayMs);
}

function applyComfyuiRuntimeLimits(payload = {}) {
  const parsed = Number(payload.max_batch_size || 1);
  comfyuiMaxBatchSize = Math.max(1, Math.min(8, Number.isFinite(parsed) ? parsed : 1));
  const defaultWidth = Number(payload.default_width || payload.comfyui_default_width || 1024);
  const defaultHeight = Number(payload.default_height || payload.comfyui_default_height || 1024);
  comfyuiDefaultWidth = Math.max(64, Math.min(2048, Number.isFinite(defaultWidth) ? defaultWidth : 1024));
  comfyuiDefaultHeight = Math.max(64, Math.min(2048, Number.isFinite(defaultHeight) ? defaultHeight : 1024));
  const draft = readComfyuiDraft();
  const widthInput = $("comfyui-width");
  const heightInput = $("comfyui-height");
  if (widthInput && !draft["comfyui-width"]) widthInput.value = String(comfyuiDefaultWidth);
  if (heightInput && !draft["comfyui-height"]) heightInput.value = String(comfyuiDefaultHeight);
  const input = $("comfyui-batch-size");
  if (!input) return;
  input.min = "1";
  input.max = String(comfyuiMaxBatchSize);
  if (!input.value || Number(input.value) > comfyuiMaxBatchSize) input.value = String(comfyuiMaxBatchSize);
  if (comfyuiMaxBatchSize === 1) input.value = "1";
  input.disabled = comfyuiMaxBatchSize <= 1;
  input.title = comfyuiMaxBatchSize <= 1
    ? "目前系統限制單次只能產生 1 張，root 可在安全中心調整"
    : `目前單次最多 ${comfyuiMaxBatchSize} 張`;
  comfyuiBillingQuote = payload.billing || null;
  if (payload.lora_extra_unit_price !== undefined) {
    comfyuiBillingQuote = { ...(comfyuiBillingQuote || {}), lora_extra_unit_price: Number(payload.lora_extra_unit_price || COMFYUI_LORA_EXTRA_PRICE) };
  }
  const generate = $("comfyui-generate-btn");
  if (generate && comfyuiBillingQuote?.unit_price) {
    generate.title = `非 root 帳號成功產圖後每張扣 ${comfyuiBillingQuote.unit_price} 點；每個 LoRA 每張額外 +${comfyuiBillingQuote.lora_extra_unit_price || COMFYUI_LORA_EXTRA_PRICE} 點；產圖失敗不扣點，丟棄預覽不退款`;
  }
  updateComfyuiRootPanelVisibility();
}

function comfyuiGenerationMode() {
  return String($("comfyui-generation-mode")?.value || "txt2img").trim().toLowerCase() || "txt2img";
}

function comfyuiModeUsesSourceImage(mode = comfyuiGenerationMode()) {
  return ["img2img", "inpaint", "outpaint", "upscale"].includes(String(mode || "").trim().toLowerCase());
}

function comfyuiModeUsesMaskImage(mode = comfyuiGenerationMode()) {
  return String(mode || "").trim().toLowerCase() === "inpaint";
}

function comfyuiModeUsesOutpaint(mode = comfyuiGenerationMode()) {
  return String(mode || "").trim().toLowerCase() === "outpaint";
}

function comfyuiModeUsesUpscale(mode = comfyuiGenerationMode()) {
  return String(mode || "").trim().toLowerCase() === "upscale";
}

function isComfyuiControlnetEnabled() {
  return !!$("comfyui-controlnet-enabled")?.checked;
}

function comfyuiModeTip(mode = comfyuiGenerationMode()) {
  switch (String(mode || "").trim().toLowerCase()) {
    case "img2img":
      return "圖生圖：以上傳來源圖為基底重畫，適合保留構圖與色塊。";
    case "inpaint":
      return "局部重繪：需要來源圖與遮罩圖，只重畫你標出的區域。";
    case "outpaint":
      return "向外延展：以來源圖為中心向外擴邊，讓模型補完畫面外框。";
    case "upscale":
      return "放大修復：使用 scale model 先放大，再保留原圖細節。";
    default:
      return "文字生圖：只需要提示詞，不需要來源圖片。";
  }
}

function comfyuiReadableModeLabel(mode = comfyuiGenerationMode()) {
  const normalized = String(mode || "").trim().toLowerCase();
  const hit = comfyuiGenerationModes.find((item) => String(item?.key || "").trim().toLowerCase() === normalized);
  if (hit?.label) return String(hit.label);
  return {
    txt2img: "文字生圖",
    img2img: "圖生圖",
    inpaint: "局部重繪",
    outpaint: "向外延展",
    upscale: "放大修復",
  }[normalized] || normalized || "文字生圖";
}

function fillComfyuiGenerationModes(values = []) {
  comfyuiGenerationModes = Array.isArray(values) && values.length
    ? values
      .filter((item) => item && typeof item === "object" && item.key)
      .map((item) => ({
        key: String(item.key),
        label: String(item.label || item.key),
        available: item.available !== false,
      }))
    : [
        { key: "txt2img", label: "文字生圖", available: true },
        { key: "img2img", label: "圖生圖", available: true },
        { key: "inpaint", label: "局部重繪", available: true },
        { key: "outpaint", label: "向外延展", available: true },
        { key: "upscale", label: "放大修復", available: true },
      ];
  const select = $("comfyui-generation-mode");
  if (!select) return;
  select.innerHTML = comfyuiGenerationModes.map((item) => (
    `<option value="${sanitize(item.key)}"${item.available ? "" : ' disabled="disabled"'}>${sanitize(item.label)}</option>`
  )).join("");
}

function fillComfyuiControlnetTypes(types = {}) {
  comfyuiControlnetTypes = types && typeof types === "object" ? types : {};
  const select = $("comfyui-controlnet-type");
  if (!select) return;
  const options = Object.entries(comfyuiControlnetTypes).length
    ? Object.entries(comfyuiControlnetTypes).map(([key, item]) => {
        const available = item && item.available === true;
        const label = available
          ? (item.label || key)
          : `${item?.label || key}（缺少 nodes / models）`;
        return `<option value="${sanitize(key)}"${available ? "" : ' disabled="disabled"'}>${sanitize(label)}</option>`;
      }).join("")
    : Object.entries(COMFYUI_CONTROLNET_TIPS).map(([key]) => `<option value="${sanitize(key)}">${sanitize(key)}</option>`).join("");
  select.innerHTML = options;
}

function comfyuiSelectedControlnetType() {
  return String($("comfyui-controlnet-type")?.value || "canny").trim().toLowerCase() || "canny";
}

function fillComfyuiControlnetModelOptions() {
  const select = $("comfyui-controlnet-model");
  if (!select) return;
  const type = comfyuiSelectedControlnetType();
  const info = comfyuiControlnetTypes?.[type] || {};
  const models = Array.isArray(info.matching_models) ? info.matching_models : [];
  const previous = select.value || "";
  select.innerHTML = ['<option value="">自動選擇可用模型</option>']
    .concat(models.map((model) => `<option value="${sanitize(model)}">${sanitize(model)}</option>`))
    .join("");
  if (previous && models.includes(previous)) select.value = previous;
}

function fillComfyuiControlnetPreprocessorOptions() {
  const select = $("comfyui-controlnet-preprocessor");
  if (!select) return;
  const type = comfyuiSelectedControlnetType();
  const info = comfyuiControlnetTypes?.[type] || {};
  const preprocessors = Array.isArray(info.available_preprocessors) ? info.available_preprocessors : [];
  const previous = select.value || "";
  select.innerHTML = ['<option value="">自動選擇</option>']
    .concat(preprocessors.map((name) => `<option value="${sanitize(name)}">${sanitize(name)}</option>`))
    .join("");
  if (previous && preprocessors.includes(previous)) {
    select.value = previous;
  } else if (!previous && info.default_preprocessor) {
    select.value = info.default_preprocessor;
  }
}

function fillComfyuiUpscaleModels(values = []) {
  comfyuiUpscaleModels = Array.isArray(values) ? values.filter(Boolean).map(String) : [];
  const select = $("comfyui-upscale-model");
  if (!select) return;
  const previous = select.value || "";
  const options = comfyuiUpscaleModels.length
    ? comfyuiUpscaleModels.map((value) => `<option value="${sanitize(value)}">${sanitize(value)}</option>`)
    : ['<option value="">目前沒有可用的放大模型</option>'];
  select.innerHTML = options.join("");
  if (previous && comfyuiUpscaleModels.includes(previous)) select.value = previous;
}

function updateComfyuiControlnetTip() {
  const tip = $("comfyui-controlnet-tip");
  if (!tip) return;
  const type = comfyuiSelectedControlnetType();
  const typeInfo = comfyuiControlnetTypes?.[type] || {};
  const available = typeInfo.available === true;
  const tail = available ? "" : " 目前缺少對應 nodes 或 models，無法建立工作。";
  tip.textContent = `${COMFYUI_CONTROLNET_TIPS[type] || "可利用控制圖約束構圖與細節。"}${tail}`;
}

function updateComfyuiModeVisibility() {
  const mode = comfyuiGenerationMode();
  const modeTip = $("comfyui-generation-mode-tip");
  const denoiseField = $("comfyui-denoise-field");
  const upscaleField = $("comfyui-upscale-model-field");
  const outpaintPanel = $("comfyui-outpaint-panel");
  const controlFields = $("comfyui-controlnet-fields");
  const controlCard = $(COMFYUI_INPUT_ASSET_META.control.cardId);
  const maskCard = $(COMFYUI_INPUT_ASSET_META.mask.cardId);
  if (modeTip) modeTip.textContent = comfyuiModeTip(mode);
  if (denoiseField) denoiseField.style.display = mode === "txt2img" || mode === "upscale" ? "none" : "";
  if (upscaleField) upscaleField.style.display = comfyuiModeUsesUpscale(mode) ? "" : "none";
  if (outpaintPanel) outpaintPanel.style.display = comfyuiModeUsesOutpaint(mode) ? "" : "none";
  if (maskCard) maskCard.style.display = comfyuiModeUsesMaskImage(mode) ? "" : "none";
  if (controlFields) controlFields.style.display = isComfyuiControlnetEnabled() ? "" : "none";
  if (controlCard) controlCard.style.display = isComfyuiControlnetEnabled() ? "" : "none";
  updateComfyuiControlnetTip();
}

function comfyuiAssetState(key) {
  return comfyuiInputAssets[key] || { file: null, imageRef: null, previewUrl: "", filename: "" };
}

function revokeComfyuiAssetPreview(asset) {
  if (asset?.previewUrl && String(asset.previewUrl).startsWith("blob:")) {
    try { URL.revokeObjectURL(asset.previewUrl); } catch (_err) {}
  }
}

function renderComfyuiInputAsset(key) {
  const meta = COMFYUI_INPUT_ASSET_META[key];
  if (!meta) return;
  const preview = $(meta.previewId);
  const status = $(meta.metaId);
  const clearBtn = $(meta.clearBtnId);
  const fileInput = $(meta.fileInputId);
  const asset = comfyuiAssetState(key);
  if (preview) {
    if (asset.previewUrl) {
      preview.innerHTML = `<img src="${sanitize(asset.previewUrl)}" alt="${sanitize(meta.title)}預覽" />`;
    } else {
      preview.innerHTML = `<span class="drive-card-sub">${sanitize(meta.emptyText)}</span>`;
    }
  }
  if (status) {
    if (asset.file) {
      status.textContent = `已選擇本地檔：${asset.filename || asset.file.name || "未命名圖片"} · ${formatDriveBytes(asset.file.size || 0)}`;
    } else if (asset.imageRef?.filename) {
      status.textContent = `使用已保存的 ${meta.title}：${asset.filename || asset.imageRef.filename}`;
    } else {
      status.textContent = key === "mask" ? "建議與來源圖片尺寸一致。" : (key === "control" ? "控制圖只在啟用 ControlNet 時送出。" : "可上傳 PNG、JPG、WEBP。");
    }
  }
  if (clearBtn) clearBtn.disabled = !asset.file && !asset.imageRef;
  if (fileInput && !asset.file) fileInput.value = "";
}

function setComfyuiInputAssetFromFile(key, file) {
  const asset = comfyuiAssetState(key);
  revokeComfyuiAssetPreview(asset);
  comfyuiInputAssets[key] = {
    file,
    imageRef: null,
    previewUrl: file ? URL.createObjectURL(file) : "",
    filename: file?.name || "",
  };
  renderComfyuiInputAsset(key);
}

function setComfyuiInputAssetFromRef(key, imageRef, previewUrl = "", filename = "") {
  const asset = comfyuiAssetState(key);
  revokeComfyuiAssetPreview(asset);
  comfyuiInputAssets[key] = {
    file: null,
    imageRef: imageRef || null,
    previewUrl: previewUrl || "",
    filename: filename || imageRef?.filename || "",
  };
  renderComfyuiInputAsset(key);
}

function clearComfyuiInputAsset(key) {
  const asset = comfyuiAssetState(key);
  revokeComfyuiAssetPreview(asset);
  comfyuiInputAssets[key] = { file: null, imageRef: null, previewUrl: "", filename: "" };
  renderComfyuiInputAsset(key);
}

async function loadComfyuiImageRefPreview(imageRef) {
  const res = await apiFetch(API + "/comfyui/image-preview", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || ""
    },
    body: JSON.stringify({ image_ref: imageRef })
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 圖片預覽讀取失敗（HTTP ${res.status}）`);
  return json.image || {};
}

async function hydrateComfyuiInputAssetFromRef(key, imageRef) {
  if (!imageRef?.filename) {
    clearComfyuiInputAsset(key);
    return;
  }
  try {
    await fetchCsrfToken({ force: true });
    const preview = await loadComfyuiImageRefPreview(imageRef);
    setComfyuiInputAssetFromRef(key, imageRef, preview.data_url || "", imageRef.filename || "");
  } catch (err) {
    setComfyuiInputAssetFromRef(key, imageRef, "", imageRef.filename || "");
    setComfyuiMessage(err.message || "圖片預覽讀取失敗", false);
  }
}

function fillComfyuiSelect(id, values, fallback) {
  const select = $(id);
  if (!select) return;
  const options = Array.isArray(values) && values.length ? values : [fallback].filter(Boolean);
  select.innerHTML = options.map((value) => `<option value="${sanitize(value)}">${sanitize(value)}</option>`).join("");
}

function fillComfyuiVaeSelect(values = []) {
  comfyuiAvailableVaes = Array.isArray(values) ? values.filter(Boolean).map(String) : [];
  const select = $("comfyui-vae-select");
  if (!select) return;
  const options = [`<option value="${COMFYUI_VAE_BUILTIN}">使用 checkpoint 內建 VAE</option>`]
    .concat(comfyuiAvailableVaes.map((value) => `<option value="${sanitize(value)}">${sanitize(value)}</option>`));
  select.innerHTML = options.join("");
}

function updateComfyuiResultButtons(hasImage) {
  const save = $("comfyui-save-btn");
  const discard = $("comfyui-discard-btn");
  const share = $("comfyui-share-btn");
  if (save) save.disabled = !hasImage;
  if (discard) discard.disabled = !hasImage;
  if (share) share.disabled = !hasImage;
}

function formatComfyuiDuration(seconds) {
  const safe = Math.max(0, Math.floor(Number(seconds) || 0));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function setComfyuiProgress({ visible = true, running = false, percent = 0, label = "", detail = "" } = {}) {
  const panel = $("comfyui-progress-panel");
  const bar = $("comfyui-progress-bar");
  const labelEl = $("comfyui-progress-label");
  const percentEl = $("comfyui-progress-percent");
  const detailEl = $("comfyui-progress-detail");
  if (!panel) return;
  panel.style.display = visible ? "" : "none";
  panel.classList.toggle("running", !!running);
  const safePercent = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  if (bar) bar.style.width = `${safePercent}%`;
  if (labelEl) labelEl.textContent = label || "等待 ComfyUI";
  if (percentEl) percentEl.textContent = `${safePercent}%`;
  if (detailEl) detailEl.textContent = detail || "";
}

function stopComfyuiProgress({ complete = false, error = "" } = {}) {
  if (comfyuiProgressTimer) {
    clearInterval(comfyuiProgressTimer);
    comfyuiProgressTimer = null;
  }
  if (complete) {
    setComfyuiProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "圖片已完成",
      detail: "ComfyUI 已回傳產圖結果"
    });
  } else if (error) {
    setComfyuiProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "產圖失敗",
      detail: error
    });
  } else {
    setComfyuiProgress({ visible: false });
  }
}

function startComfyuiProgress(timeoutSeconds = COMFYUI_GENERATION_TIMEOUT_SECONDS) {
  comfyuiProgressStartedAt = Date.now();
  setComfyuiProgress({
    visible: true,
    running: true,
    percent: 0,
    label: "已送出產圖請求",
    detail: `已等待 00:00 / 上限 ${formatComfyuiDuration(timeoutSeconds)}`
  });
}

function applyComfyuiJobProgress(progress = {}, timeoutSeconds = COMFYUI_GENERATION_TIMEOUT_SECONDS) {
  const elapsed = Math.max(0, Math.floor((Date.now() - comfyuiProgressStartedAt) / 1000));
  const percent = Math.max(0, Math.min(100, Math.round(Number(progress.percent) || 0)));
  let label = "等待 ComfyUI";
  const phase = String(progress.phase || "").toLowerCase();
  if (phase === "queued") label = "排隊中";
  else if (phase === "running") label = "ComfyUI 執行中";
  else if (phase === "completed") label = "圖片已完成";
  else if (phase === "error") label = "產圖失敗";
  const queueText = progress.queue_remaining !== null && progress.queue_remaining !== undefined
    ? `，佇列剩餘 ${progress.queue_remaining}`
    : "";
  const nodeText = progress.current_node ? `，節點 ${progress.current_node}` : "";
  const detail = `${progress.detail || "等待進度資料"}${queueText}${nodeText}；已等待 ${formatComfyuiDuration(elapsed)} / 上限 ${formatComfyuiDuration(timeoutSeconds)}`;
  setComfyuiProgress({
    visible: true,
    running: phase !== "completed" && phase !== "error",
    percent,
    label,
    detail
  });
}

async function pollComfyuiJobUntilDone(jobId, controller, timeoutSeconds) {
  comfyuiActiveJobId = jobId;
  const deadline = Date.now() + timeoutSeconds * 1000 + 15000;
  while (Date.now() < deadline) {
    if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
    const res = await apiFetch(API + `/comfyui/jobs/${encodeURIComponent(jobId)}`, {
      credentials: "same-origin",
      signal: controller.signal,
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 工作狀態讀取失敗（HTTP ${res.status}）`);
    const job = json.job || {};
    applyComfyuiJobProgress(job.progress || {}, timeoutSeconds);
    if (job.status === "completed" && job.result) return job.result;
    if (job.status === "error") throw new Error(job.error || job.progress?.detail || "ComfyUI 產圖失敗");
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error("ComfyUI 進度查詢逾時");
}

function selectedComfyuiAlbumId() {
  const value = $("comfyui-album-select")?.value || "";
  return value || null;
}

function comfyuiDraftStorageKey() {
  return `hackme_web:comfyui:draft:${currentUser || "anonymous"}`;
}

function readComfyuiDraft() {
  try {
    return JSON.parse(localStorage.getItem(comfyuiDraftStorageKey()) || "{}") || {};
  } catch (err) {
    return {};
  }
}

function writeComfyuiDraft() {
  const draft = {};
  COMFYUI_DRAFT_FIELD_IDS.forEach((id) => {
    const el = $(id);
    if (!el) return;
    draft[id] = el.value;
  });
  draft.selected_loras = comfyuiSelectedLoras;
  try {
    localStorage.setItem(comfyuiDraftStorageKey(), JSON.stringify(draft));
  } catch (err) {
    // Storage may be unavailable in private mode; keep the live DOM values.
  }
}

function setComfyuiFieldValue(id, value) {
  const el = $(id);
  if (!el || value === undefined || value === null) return;
  if (el.tagName === "SELECT") {
    const exists = Array.from(el.options || []).some((option) => option.value === String(value));
    if (!exists && String(value)) return;
  }
  el.value = String(value);
}

function restoreComfyuiDraft({ includeDynamicSelects = true } = {}) {
  const draft = readComfyuiDraft();
  if (Array.isArray(draft.selected_loras)) {
    comfyuiSelectedLoras = draft.selected_loras
      .filter((item) => item && typeof item === "object" && item.name)
      .slice(0, COMFYUI_MAX_LORAS)
      .map((item) => ({
        name: String(item.name),
        strength_model: Number.isFinite(Number(item.strength_model)) ? Number(item.strength_model) : 1,
        strength_clip: Number.isFinite(Number(item.strength_clip)) ? Number(item.strength_clip) : 1,
      }));
    renderComfyuiSelectedLoras();
  }
  COMFYUI_DRAFT_FIELD_IDS.forEach((id) => {
    if (!includeDynamicSelects && COMFYUI_DYNAMIC_SELECT_IDS.includes(id)) {
      return;
    }
    setComfyuiFieldValue(id, draft[id]);
  });
  updateComfyuiModeVisibility();
}

function updateComfyuiRootPanelVisibility(modeOverride = null) {
  const panel = $("comfyui-root-model-panel");
  const details = $("comfyui-root-model-details");
  const hint = $("comfyui-root-model-mode-hint");
  const mode = String(modeOverride || comfyuiConnectionMode || "remote").trim().toLowerCase();
  const show = currentUser === "root";
  const localReady = mode === "local";
  updateComfyuiModeNote(mode);
  if (panel) panel.style.display = show ? "" : "none";
  if (details && !show) details.open = false;
  if (!panel) return;
  panel.querySelectorAll("input, select, button").forEach((el) => {
    el.disabled = !localReady;
  });
  panel.dataset.mode = localReady ? "local" : "remote";
  if (hint) {
    hint.textContent = localReady
      ? "目前是本地模式，可在這裡用 Civitai 下載或直接上傳模型檔。"
      : "目前是雲端 / 遠端模式，所以這個區塊只保留說明。若要管理本站的本地 ComfyUI 模型，請先把 backend 切回本地模式。";
  }
  updateComfyuiModelSourceMode();
}

function renderComfyuiSelectedLoras() {
  const box = $("comfyui-selected-loras");
  const count = $("comfyui-lora-count");
  if (!box) return;
  comfyuiSelectedLoras = comfyuiSelectedLoras.slice(0, COMFYUI_MAX_LORAS);
  if (count) count.textContent = `${comfyuiSelectedLoras.length} / ${COMFYUI_MAX_LORAS}`;
  if (!comfyuiSelectedLoras.length) {
    box.innerHTML = '<span class="drive-card-sub">尚未選擇 LoRA</span>';
    return;
  }
  box.innerHTML = comfyuiSelectedLoras.map((item, index) => `
    <div class="comfyui-lora-chip" title="${sanitize(item.name)}">
      <div class="comfyui-lora-chip-head">
        <span>${sanitize(item.name)}</span>
        <button type="button" data-comfyui-remove-lora="${index}" aria-label="移除 ${sanitize(item.name)}">×</button>
      </div>
      <div class="comfyui-lora-weight-grid">
        <label>
          <span>Model</span>
          <input type="number" min="-2" max="2" step="0.05" data-comfyui-lora-strength-model="${index}" value="${sanitize(String(item.strength_model ?? 1))}" />
        </label>
        <label>
          <span>CLIP</span>
          <input type="number" min="-2" max="2" step="0.05" data-comfyui-lora-strength-clip="${index}" value="${sanitize(String(item.strength_clip ?? 1))}" />
        </label>
      </div>
    </div>
  `).join("");
  box.querySelectorAll("[data-comfyui-remove-lora]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-comfyui-remove-lora"));
      removeComfyuiSelectedLoraByIndex(index);
    });
  });
  box.querySelectorAll("[data-comfyui-lora-strength-model]").forEach((input) => {
    input.addEventListener("input", () => updateComfyuiSelectedLoraStrength(input, "strength_model"));
    input.addEventListener("change", () => updateComfyuiSelectedLoraStrength(input, "strength_model"));
  });
  box.querySelectorAll("[data-comfyui-lora-strength-clip]").forEach((input) => {
    input.addEventListener("input", () => updateComfyuiSelectedLoraStrength(input, "strength_clip"));
    input.addEventListener("change", () => updateComfyuiSelectedLoraStrength(input, "strength_clip"));
  });
}

function updateComfyuiSelectedLoraStrength(input, field) {
  const datasetKey = field === "strength_clip" ? "comfyuiLoraStrengthClip" : "comfyuiLoraStrengthModel";
  const index = Number(input?.dataset?.[datasetKey]);
  if (!Number.isInteger(index) || !comfyuiSelectedLoras[index]) return;
  const value = Number(input.value || 1);
  const normalized = Math.max(-2, Math.min(2, Number.isFinite(value) ? value : 1));
  comfyuiSelectedLoras[index][field] = Math.round(normalized * 100) / 100;
  input.value = String(comfyuiSelectedLoras[index][field]);
  writeComfyuiDraft();
}

function fillComfyuiLoraSelect(values = []) {
  comfyuiAvailableLoras = Array.isArray(values) ? values.filter(Boolean).map(String) : [];
  const select = $("comfyui-lora-select");
  if (!select) return;
  const options = ['<option value="">不使用 LoRA（可略過）</option>']
    .concat(comfyuiAvailableLoras.map((value) => {
      const detail = comfyuiLoraDetails?.[value] || {};
      const supported = detail.supported === true;
      const reason = detail.base_model
        ? `${detail.base_model} 不支援`
        : "base model 未知，暫不可用";
      const label = supported ? value : `${value}（不可用：${reason}）`;
      return `<option value="${sanitize(value)}"${supported ? "" : ' disabled="disabled"'}>${sanitize(label)}</option>`;
    }));
  select.innerHTML = options.join("");
}

function pruneUnsupportedComfyuiSelectedLoras({ notify = false } = {}) {
  const removed = [];
  comfyuiSelectedLoras = comfyuiSelectedLoras.filter((item) => {
    const detail = comfyuiLoraDetails?.[item?.name] || {};
    const keep = detail.supported === true;
    if (!keep && item?.name) removed.push(String(item.name));
    return keep;
  });
  if (!removed.length) return removed;
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
  if (notify) {
    setComfyuiMessage(`已移除不支援的 LoRA：${removed.join(", ")}。目前只允許 SDXL、Pony、Illustrious、Noob 系列。`, false);
  }
  return removed;
}

function applyComfyuiPromptTerms(terms = []) {
  const prompt = $("comfyui-prompt");
  if (!prompt) return [];
  const existing = String(prompt.value || "");
  const existingLower = existing.toLowerCase();
  const normalizedTerms = Array.isArray(terms)
    ? terms.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const missingTerms = normalizedTerms.filter((term) => !existingLower.includes(term.toLowerCase()));
  if (!missingTerms.length) return [];
  const separator = existing.trim() ? ", " : "";
  prompt.value = `${existing}${separator}${missingTerms.join(", ")}`;
  writeComfyuiDraft();
  return missingTerms;
}

function comfyuiPromptField(promptType = "prompt") {
  return $(promptType === "negative" ? "comfyui-negative-prompt" : "comfyui-prompt");
}

function splitComfyuiPromptTerms(text) {
  return String(text || "")
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinComfyuiPromptTerms(terms = []) {
  return Array.isArray(terms)
    ? terms.map((item) => String(item || "").trim()).filter(Boolean).join(", ")
    : "";
}

function removeComfyuiPromptTerms(terms = [], { promptType = "prompt" } = {}) {
  const prompt = comfyuiPromptField(promptType);
  if (!prompt) return [];
  const normalizedTerms = Array.isArray(terms)
    ? terms.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (!normalizedTerms.length) return [];
  const removalSet = new Set(normalizedTerms.map((item) => item.toLowerCase()));
  const removed = [];
  const keptTerms = splitComfyuiPromptTerms(prompt.value).filter((term) => {
    const shouldRemove = removalSet.has(term.toLowerCase());
    if (shouldRemove) removed.push(term);
    return !shouldRemove;
  });
  if (!removed.length) return [];
  prompt.value = joinComfyuiPromptTerms(keptTerms);
  writeComfyuiDraft();
  return removed;
}

function isNegativeComfyuiEmbedding(name) {
  const normalized = String(name || "").trim().toLowerCase();
  return normalized.includes("negative") || normalized.includes("neg");
}

function insertComfyuiEmbeddingToken(name) {
  const cleanName = String(name || "").trim();
  const promptType = isNegativeComfyuiEmbedding(cleanName) ? "negative" : "prompt";
  const prompt = comfyuiPromptField(promptType);
  const otherPromptType = promptType === "negative" ? "prompt" : "negative";
  const otherPrompt = comfyuiPromptField(otherPromptType);
  if (!prompt || !cleanName) return;
  const embeddingTag = `<embeddings:${cleanName}>`;
  if ((prompt.value || "").includes(embeddingTag)) {
    removeComfyuiPromptTerms([embeddingTag], { promptType });
    setComfyuiMessage(`已從${promptType === "negative" ? "負面" : "正向"}提示詞移除 ${cleanName}。`, true);
    prompt.focus();
    return;
  }
  if (otherPrompt && (otherPrompt.value || "").includes(embeddingTag)) {
    removeComfyuiPromptTerms([embeddingTag], { promptType: otherPromptType });
    setComfyuiMessage(`已從${otherPromptType === "negative" ? "負面" : "正向"}提示詞移除 ${cleanName}。`, true);
    prompt.focus();
    return;
  }
  const raw = prompt.value || "";
  const start = Number.isInteger(prompt.selectionStart) ? prompt.selectionStart : raw.length;
  const end = Number.isInteger(prompt.selectionEnd) ? prompt.selectionEnd : raw.length;
  const prefix = start > 0 && !/[\s,\n]$/.test(raw.slice(0, start)) ? ", " : "";
  const suffix = end < raw.length && !/^[\s,]/.test(raw.slice(end)) ? " " : "";
  prompt.value = `${raw.slice(0, start)}${prefix}${embeddingTag}${suffix}${raw.slice(end)}`;
  const cursor = start + prefix.length + embeddingTag.length + suffix.length;
  prompt.focus();
  if (typeof prompt.setSelectionRange === "function") prompt.setSelectionRange(cursor, cursor);
  writeComfyuiDraft();
  setComfyuiMessage(`已把 ${cleanName} 插入${promptType === "negative" ? "負面" : "正向"}提示詞。`, true);
}

function renderComfyuiEmbeddingShortcuts(values = []) {
  comfyuiAvailableEmbeddings = Array.isArray(values) ? values.filter(Boolean).map(String) : [];
  const box = $("comfyui-embedding-shortcuts");
  if (!box) return;
  if (!comfyuiAvailableEmbeddings.length) {
    box.innerHTML = '<span class="drive-card-sub">目前沒有可用的 Embedding。</span>';
    return;
  }
  box.innerHTML = comfyuiAvailableEmbeddings.map((value) => (
    `<button class="comfyui-embedding-chip" type="button" data-comfyui-embedding="${sanitize(value)}" title="插入 ${sanitize(value)}">${sanitize(value)}</button>`
  )).join("");
  box.querySelectorAll("[data-comfyui-embedding]").forEach((button) => {
    button.addEventListener("click", () => insertComfyuiEmbeddingToken(button.getAttribute("data-comfyui-embedding")));
  });
}

function loraTermsStillNeededAfterRemoving(nameToRemove) {
  const needed = new Set();
  comfyuiSelectedLoras.forEach((item) => {
    if (!item?.name || item.name === nameToRemove) return;
    const detail = comfyuiLoraDetails?.[item.name] || {};
    (detail.trained_words || []).forEach((term) => {
      const cleanTerm = String(term || "").trim();
      if (cleanTerm) needed.add(cleanTerm.toLowerCase());
    });
  });
  return needed;
}

function removeComfyuiSelectedLoraByIndex(index) {
  const current = comfyuiSelectedLoras[index];
  if (!current) return;
  const detail = comfyuiLoraDetails?.[current.name] || {};
  const trainedWords = Array.isArray(detail.trained_words)
    ? detail.trained_words.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const stillNeeded = loraTermsStillNeededAfterRemoving(current.name);
  const removableTerms = trainedWords.filter((term) => !stillNeeded.has(term.toLowerCase()));
  comfyuiSelectedLoras.splice(index, 1);
  if (removableTerms.length) removeComfyuiPromptTerms(removableTerms, { promptType: "prompt" });
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
}

function clearSelectedComfyuiLoras() {
  if (!comfyuiSelectedLoras.length) {
    setComfyuiMessage("目前沒有已加入的 LoRA。", false);
    return;
  }
  const removableTerms = [];
  comfyuiSelectedLoras.forEach((item) => {
    const detail = comfyuiLoraDetails?.[item?.name] || {};
    (detail.trained_words || []).forEach((term) => {
      const cleanTerm = String(term || "").trim();
      if (cleanTerm) removableTerms.push(cleanTerm);
    });
  });
  comfyuiSelectedLoras = [];
  if (removableTerms.length) removeComfyuiPromptTerms(removableTerms, { promptType: "prompt" });
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
  setComfyuiMessage("已清空已選 LoRA，並移除相關 trigger words。", true);
}

function addSelectedComfyuiLora() {
  const name = $("comfyui-lora-select")?.value || "";
  if (!name) {
    clearSelectedComfyuiLoras();
    return;
  }
  if (comfyuiSelectedLoras.length >= COMFYUI_MAX_LORAS) {
    setComfyuiMessage(`已達 LoRA 數量上限 ${COMFYUI_MAX_LORAS} 個。`, false);
    return;
  }
  if (comfyuiSelectedLoras.some((item) => item.name === name)) {
    setComfyuiMessage("這個 LoRA 已經加入。", false);
    return;
  }
  const detail = comfyuiLoraDetails?.[name] || {};
  if (detail.supported !== true) {
    setComfyuiMessage(detail.support_message || "這個 LoRA 目前不支援；只允許 SDXL、Pony、Illustrious、Noob 系列。", false);
    return;
  }
  comfyuiSelectedLoras.push({ name, strength_model: 1, strength_clip: 1 });
  const insertedTerms = applyComfyuiPromptTerms(detail.trained_words || []);
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
  if (insertedTerms.length) {
    setComfyuiMessage(`已加入 LoRA，並自動補上 trigger words：${insertedTerms.join(", ")}`, true);
  }
}

function bindComfyuiDraftPersistence() {
  restoreComfyuiDraft({ includeDynamicSelects: false });
  COMFYUI_DRAFT_FIELD_IDS.forEach((id) => {
    const el = $(id);
    if (!el || el.dataset.comfyuiDraftBound === "1") return;
    el.dataset.comfyuiDraftBound = "1";
    if (id === "comfyui-save-path") {
      el.addEventListener("input", () => {
        el.dataset.comfyuiAutoPath = "0";
      });
    }
    el.addEventListener("input", writeComfyuiDraft);
    el.addEventListener("change", writeComfyuiDraft);
  });
}

function bindComfyuiAdvancedUi() {
  const modeSelect = $("comfyui-generation-mode");
  if (modeSelect && modeSelect.dataset.comfyuiBound !== "1") {
    modeSelect.dataset.comfyuiBound = "1";
    modeSelect.addEventListener("change", () => {
      updateComfyuiModeVisibility();
      writeComfyuiDraft();
    });
  }
  const controlEnabled = $("comfyui-controlnet-enabled");
  if (controlEnabled && controlEnabled.dataset.comfyuiBound !== "1") {
    controlEnabled.dataset.comfyuiBound = "1";
    controlEnabled.addEventListener("change", () => {
      updateComfyuiModeVisibility();
      writeComfyuiDraft();
    });
  }
  const controlType = $("comfyui-controlnet-type");
  if (controlType && controlType.dataset.comfyuiBound !== "1") {
    controlType.dataset.comfyuiBound = "1";
    controlType.addEventListener("change", () => {
      fillComfyuiControlnetModelOptions();
      fillComfyuiControlnetPreprocessorOptions();
      updateComfyuiControlnetTip();
      writeComfyuiDraft();
    });
  }
  const modelSourceMode = $("comfyui-model-source-mode");
  if (modelSourceMode && modelSourceMode.dataset.comfyuiBound !== "1") {
    modelSourceMode.dataset.comfyuiBound = "1";
    modelSourceMode.addEventListener("change", updateComfyuiModelSourceMode);
  }
  const uploadBtn = $("comfyui-model-upload-btn");
  if (uploadBtn && uploadBtn.dataset.comfyuiBound !== "1") {
    uploadBtn.dataset.comfyuiBound = "1";
    uploadBtn.addEventListener("click", () => {
      uploadComfyuiModelFile().catch((err) => setComfyuiMessage(err.message || "模型上傳失敗", false));
    });
  }
  const civitaiSearchBtn = $("comfyui-civitai-search-btn");
  if (civitaiSearchBtn && civitaiSearchBtn.dataset.comfyuiBound !== "1") {
    civitaiSearchBtn.dataset.comfyuiBound = "1";
    civitaiSearchBtn.addEventListener("click", () => {
      searchComfyuiCivitaiModels().catch((err) => setComfyuiMessage(err.message || "Civitai 搜尋失敗", false));
    });
  }
  ["model", "preprocessor"].forEach((name) => {
    const el = $(`comfyui-controlnet-${name}`);
    if (!el || el.dataset.comfyuiBound === "1") return;
    el.dataset.comfyuiBound = "1";
    el.addEventListener("change", writeComfyuiDraft);
  });
  Object.entries(COMFYUI_INPUT_ASSET_META).forEach(([key, meta]) => {
    const fileInput = $(meta.fileInputId);
    if (fileInput && fileInput.dataset.comfyuiBound !== "1") {
      fileInput.dataset.comfyuiBound = "1";
      fileInput.addEventListener("change", () => {
        const file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
        if (!file) {
          clearComfyuiInputAsset(key);
          return;
        }
        if (!/^image\/(png|jpeg|webp)$/i.test(file.type || "")) {
          setComfyuiMessage("控制圖、遮罩圖與來源圖只支援 PNG、JPG、WEBP。", false);
          fileInput.value = "";
          return;
        }
        setComfyuiInputAssetFromFile(key, file);
      });
    }
    const clearBtn = $(meta.clearBtnId);
    if (clearBtn && clearBtn.dataset.comfyuiBound !== "1") {
      clearBtn.dataset.comfyuiBound = "1";
      clearBtn.addEventListener("click", () => clearComfyuiInputAsset(key));
    }
  });
  const refreshBtn = $("comfyui-history-refresh-btn");
  if (refreshBtn && refreshBtn.dataset.comfyuiBound !== "1") {
    refreshBtn.dataset.comfyuiBound = "1";
    refreshBtn.addEventListener("click", () => {
      loadComfyuiHistory().catch((err) => setComfyuiMessage(err.message || "ComfyUI 歷史紀錄讀取失敗", false));
    });
  }
  const workflowRefreshBtn = $("comfyui-workflows-refresh-btn");
  if (workflowRefreshBtn && workflowRefreshBtn.dataset.comfyuiBound !== "1") {
    workflowRefreshBtn.dataset.comfyuiBound = "1";
    workflowRefreshBtn.addEventListener("click", () => {
      loadComfyuiWorkflowPresets().catch((err) => setComfyuiMessage(err.message || "workflow preset 讀取失敗", false));
    });
  }
  const workflowFile = $("comfyui-workflow-file");
  if (workflowFile && workflowFile.dataset.comfyuiBound !== "1") {
    workflowFile.dataset.comfyuiBound = "1";
    workflowFile.addEventListener("change", () => {
      loadComfyuiWorkflowFile().catch((err) => setComfyuiMessage(err.message || "workflow 檔案讀取失敗", false));
    });
  }
  const workflowExportCurrentBtn = $("comfyui-workflow-export-current-btn");
  if (workflowExportCurrentBtn && workflowExportCurrentBtn.dataset.comfyuiBound !== "1") {
    workflowExportCurrentBtn.dataset.comfyuiBound = "1";
    workflowExportCurrentBtn.addEventListener("click", () => {
      exportCurrentComfyuiWorkflow().catch((err) => setComfyuiMessage(err.message || "workflow 匯出失敗", false));
    });
  }
  const workflowImportBtn = $("comfyui-workflow-import-btn");
  if (workflowImportBtn && workflowImportBtn.dataset.comfyuiBound !== "1") {
    workflowImportBtn.dataset.comfyuiBound = "1";
    workflowImportBtn.addEventListener("click", () => {
      importComfyuiWorkflowPreset().catch((err) => setComfyuiMessage(err.message || "workflow 匯入失敗", false));
    });
  }
  const workflowUpdateBtn = $("comfyui-workflow-update-btn");
  if (workflowUpdateBtn && workflowUpdateBtn.dataset.comfyuiBound !== "1") {
    workflowUpdateBtn.dataset.comfyuiBound = "1";
    workflowUpdateBtn.addEventListener("click", () => {
      updateComfyuiWorkflowPreset().catch((err) => setComfyuiMessage(err.message || "workflow 更新失敗", false));
    });
  }
  const workflowResetBtn = $("comfyui-workflow-reset-btn");
  if (workflowResetBtn && workflowResetBtn.dataset.comfyuiBound !== "1") {
    workflowResetBtn.dataset.comfyuiBound = "1";
    workflowResetBtn.addEventListener("click", () => resetComfyuiWorkflowEditor());
  }
  updateComfyuiModeVisibility();
  updateComfyuiModelSourceMode();
  Object.keys(COMFYUI_INPUT_ASSET_META).forEach((key) => renderComfyuiInputAsset(key));
}

async function loadComfyuiLastSettings() {
  const draft = readComfyuiDraft();
  if (!Object.keys(draft).length) {
    setComfyuiMessage("目前沒有保存過的 ComfyUI 設定", false);
    return;
  }
  if (!comfyuiModelsLoaded && comfyuiServerAvailable !== false) {
    await loadComfyuiModels();
  }
  restoreComfyuiDraft();
  setComfyuiMessage("已載入上次 ComfyUI 設定", true);
}

async function loadComfyuiAlbums({ force = false } = {}) {
  const select = $("comfyui-album-select");
  if (!select) return [];
  if (comfyuiAlbumsLoaded && !force) {
    restoreComfyuiDraft();
    return Array.from(select.options || []);
  }
  select.innerHTML = '<option value="">不加入相簿</option><option value="" disabled>讀取相簿中...</option>';
  try {
    const json = typeof storageAction === "function"
      ? await storageAction("/storage/albums", "GET")
      : await (async () => {
          await fetchCsrfToken({ force: true });
          const res = await apiFetch(API + "/storage/albums", {
            credentials: "same-origin",
            headers: { "X-CSRF-Token": getCsrfToken() || "" }
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok || !body.ok) throw new Error(body.msg || `相簿讀取失敗（HTTP ${res.status}）`);
          return body;
        })();
    const albums = Array.isArray(json.albums) ? json.albums : [];
    select.innerHTML = '<option value="">不加入相簿</option>' + albums.map((album) => (
      `<option value="${sanitize(String(album.id))}">${sanitize(album.title || `相簿 ${album.id}`)}</option>`
    )).join("");
    comfyuiAlbumsLoaded = true;
    restoreComfyuiDraft();
    return albums;
  } catch (err) {
    select.innerHTML = '<option value="">相簿讀取失敗</option>';
    comfyuiAlbumsLoaded = false;
    setComfyuiMessage(err.message || "相簿讀取失敗", false);
    return [];
  }
}

function comfyuiHistoryItemById(historyId) {
  return comfyuiHistoryItems.find((item) => Number(item?.id) === Number(historyId)) || null;
}

function renderComfyuiHistory() {
  const list = $("comfyui-history-list");
  const status = $("comfyui-history-status");
  if (!list) return;
  if (!Array.isArray(comfyuiHistoryItems) || !comfyuiHistoryItems.length) {
    list.innerHTML = '<div class="drive-empty">尚無 ComfyUI 歷史紀錄</div>';
    if (status) status.textContent = "尚未找到可重跑的 ComfyUI 歷史紀錄";
    return;
  }
  if (status) status.textContent = `最近 ${comfyuiHistoryItems.length} 筆 ComfyUI 歷史紀錄，可直接套回或重跑。`;
  list.innerHTML = comfyuiHistoryItems.map((item) => {
    const payload = item?.payload || {};
    const control = item?.controlnet || {};
    const mode = comfyuiReadableModeLabel(item?.generation_mode || payload?.generation_mode || "txt2img");
    const controlLabel = control?.type ? ` · ControlNet ${String(control.type).toUpperCase()}` : "";
    const model = payload?.model ? ` · ${payload.model}` : "";
    const prompt = sanitize(String(payload?.prompt || "").slice(0, 140) || "（無提示詞）");
    const createdAt = sanitize(String(item?.created_at || "").replace("T", " ").slice(0, 16));
    return `
      <div class="comfyui-history-item">
        <div class="comfyui-history-head">
          <strong>${sanitize(mode)}</strong>
          <span>${createdAt}</span>
        </div>
        <div class="drive-card-sub">${sanitize(`ID #${item.id}${model}${controlLabel}`)}</div>
        <div class="comfyui-history-prompt">${prompt}</div>
        <div class="drive-card-sub">
          ${sanitize(`步數 ${payload.steps || "-"} · CFG ${payload.cfg || "-"} · Seed ${payload.seed ?? "random"} · 張數 ${payload.batch_size || 1}`)}
        </div>
        <div class="drive-file-actions" style="justify-content:flex-start;">
          <button class="btn btn-sm" type="button" data-comfyui-history-apply="${item.id}">套回表單</button>
          <button class="btn btn-sm" type="button" data-comfyui-history-rerun="${item.id}">一鍵重跑</button>
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-comfyui-history-apply]").forEach((button) => {
    button.addEventListener("click", () => {
      applyComfyuiHistoryToForm(Number(button.getAttribute("data-comfyui-history-apply")));
    });
  });
  list.querySelectorAll("[data-comfyui-history-rerun]").forEach((button) => {
    button.addEventListener("click", () => {
      rerunComfyuiHistory(Number(button.getAttribute("data-comfyui-history-rerun")));
    });
  });
}

async function loadComfyuiHistory() {
  if (!currentUser || !canAccessModule("comfyui")) return [];
  const status = $("comfyui-history-status");
  if (status) status.textContent = "正在讀取 ComfyUI 歷史紀錄...";
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/comfyui/history", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    const message = json.msg || `ComfyUI 歷史紀錄讀取失敗（HTTP ${res.status}）`;
    if (status) status.textContent = message;
    throw new Error(message);
  }
  comfyuiHistoryItems = Array.isArray(json.history) ? json.history : [];
  renderComfyuiHistory();
  return comfyuiHistoryItems;
}

async function applyComfyuiHistoryAssets(inputAssets = {}) {
  await Promise.all([
    inputAssets?.source_image_ref
      ? hydrateComfyuiInputAssetFromRef("source", inputAssets.source_image_ref)
      : Promise.resolve(clearComfyuiInputAsset("source")),
    inputAssets?.mask_image_ref
      ? hydrateComfyuiInputAssetFromRef("mask", inputAssets.mask_image_ref)
      : Promise.resolve(clearComfyuiInputAsset("mask")),
    inputAssets?.control_image_ref
      ? hydrateComfyuiInputAssetFromRef("control", inputAssets.control_image_ref)
      : Promise.resolve(clearComfyuiInputAsset("control")),
  ]);
}

async function applyComfyuiHistoryToForm(historyId) {
  const item = comfyuiHistoryItemById(historyId);
  if (!item) {
    setComfyuiMessage("找不到這筆 ComfyUI 歷史紀錄。", false);
    return;
  }
  const payload = item.payload || {};
  const controlnet = item.controlnet || {};
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
    ["comfyui-generation-mode", payload.generation_mode || item.generation_mode || "txt2img"],
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
    ["comfyui-outpaint-left", payload.outpaint?.left ?? 128],
    ["comfyui-outpaint-top", payload.outpaint?.top ?? 128],
    ["comfyui-outpaint-right", payload.outpaint?.right ?? 128],
    ["comfyui-outpaint-bottom", payload.outpaint?.bottom ?? 128],
    ["comfyui-outpaint-feathering", payload.outpaint?.feathering ?? 48],
  ].forEach(([id, value]) => setComfyuiFieldValue(id, value));
  const controlEnabled = !!controlnet?.type;
  if ($("comfyui-controlnet-enabled")) $("comfyui-controlnet-enabled").checked = controlEnabled;
  fillComfyuiControlnetModelOptions();
  fillComfyuiControlnetPreprocessorOptions();
  await applyComfyuiHistoryAssets(item.input_assets || {});
  updateComfyuiModeVisibility();
  writeComfyuiDraft();
  setComfyuiMessage(`已套回第 ${historyId} 筆 ComfyUI 歷史，可直接再調整後重跑。`, true);
}

async function rerunComfyuiHistory(historyId) {
  if (!historyId) return;
  await fetchCsrfToken({ force: true });
  setComfyuiBusy(true);
  setComfyuiMessage("正在建立 ComfyUI 重跑工作...", true);
  startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS);
  const controller = new AbortController();
  comfyuiGenerateAbortController = controller;
  try {
    const res = await apiFetch(API + `/comfyui/history/${encodeURIComponent(historyId)}/rerun`, {
      method: "POST",
      credentials: "same-origin",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({})
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 歷史重跑失敗（HTTP ${res.status}）`);
    const result = await pollComfyuiJobUntilDone(json.job?.job_id, controller, COMFYUI_GENERATION_TIMEOUT_SECONDS);
    const images = Array.isArray(result.images) && result.images.length ? result.images : [result.image].filter(Boolean);
    comfyuiGeneratedImages = images;
    renderComfyuiGeneratedImages(comfyuiGeneratedImages);
    setComfyuiSelectedImage(0);
    stopComfyuiProgress({ complete: true });
    updateComfyuiResultButtons(true);
    loadComfyuiHistory().catch(() => {});
    setComfyuiMessage(`已重跑第 ${historyId} 筆 ComfyUI 歷史。`, true);
  } catch (err) {
    stopComfyuiProgress({ error: err.message || "ComfyUI 歷史重跑失敗" });
    setComfyuiMessage(err.message || "ComfyUI 歷史重跑失敗", false);
  } finally {
    if (comfyuiGenerateAbortController === controller) comfyuiGenerateAbortController = null;
    setComfyuiBusy(false);
  }
}

function comfyuiWorkflowPresetById(presetId) {
  return comfyuiWorkflowPresets.find((item) => Number(item?.id) === Number(presetId)) || null;
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
  setComfyuiFieldValue("comfyui-workflow-json", "");
  const fileInput = $("comfyui-workflow-file");
  if (fileInput) fileInput.value = "";
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = true;
  if (!keepStatus) setComfyuiWorkflowStatus("尚未選取 workflow preset");
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
    const mode = item?.default_params?.generation_mode ? comfyuiReadableModeLabel(item.default_params.generation_mode) : "Workflow";
    return `
      <div class="comfyui-workflow-item">
        <div class="comfyui-workflow-item-head">
          <div class="comfyui-workflow-item-title">
            <strong>${sanitize(item?.title || `Workflow #${item?.id || ""}`)}</strong>
            <span>${sanitize(mode)} · ${sanitize(String(item?.updated_at || "").replace("T", " ").slice(0, 16))}</span>
          </div>
          <div class="comfyui-workflow-flags">
            ${item?.is_official ? '<span class="comfyui-workflow-chip">官方</span>' : ""}
            <span class="comfyui-workflow-chip">${sanitize(item?.visibility || "private")}</span>
            <span class="comfyui-workflow-chip">${sanitize(String((item?.workflow_hash || "").slice(0, 12) || "-"))}</span>
          </div>
        </div>
        <div class="drive-card-sub">${sanitize(item?.description || "未填寫說明")}</div>
        <div class="comfyui-workflow-meta">
          ${models.length ? `<span class="comfyui-workflow-chip">模型 ${sanitize(String(models.length))}</span>` : ""}
          ${loras.length ? `<span class="comfyui-workflow-chip">LoRA ${sanitize(String(loras.length))}</span>` : ""}
          ${controlnets.length ? `<span class="comfyui-workflow-chip">ControlNet ${sanitize(String(controlnets.length))}</span>` : ""}
        </div>
        ${dependencyHtml}
        <div class="drive-card-sub">所需模型：${sanitize(models.join(", ") || "無")}</div>
        <div class="drive-card-sub">所需 LoRA：${sanitize(loras.join(", ") || "無")}</div>
        <div class="drive-card-sub">所需 ControlNet：${sanitize(controlnets.join(", ") || "無")}</div>
        ${renderComfyuiWorkflowRunList(item?.recent_runs || [])}
        <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.55rem;">
          <button class="btn btn-sm" type="button" data-comfyui-workflow-apply="${item.id}">套回表單</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-run="${item.id}">執行</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-export="${item.id}">匯出 JSON</button>
          <button class="btn btn-sm" type="button" data-comfyui-workflow-edit="${item.id}">載入編輯</button>
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

function renderComfyuiWorkflowPresets(payload = {}) {
  comfyuiWorkflowPresets = Array.isArray(payload.presets) ? payload.presets : [];
  renderComfyuiWorkflowPresetList("comfyui-workflow-my-list", payload.my_presets || [], "尚無個人 preset");
  renderComfyuiWorkflowPresetList("comfyui-workflow-official-list", payload.official_presets || [], "尚無官方 preset");
  renderComfyuiWorkflowPresetList("comfyui-workflow-shared-list", payload.shared_presets || [], "尚無其他可讀 preset");
  const total = comfyuiWorkflowPresets.length;
  const warning = payload.dependency_warning ? `；依賴檢查警告：${payload.dependency_warning}` : "";
  setComfyuiWorkflowStatus(`目前可見 ${total} 個 workflow preset${warning}`);
}

async function loadComfyuiWorkflowPresets() {
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
  renderComfyuiWorkflowPresets(json);
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
  setComfyuiFieldValue("comfyui-workflow-json", JSON.stringify(preset.workflow_json || {}, null, 2));
  const updateBtn = $("comfyui-workflow-update-btn");
  if (updateBtn) updateBtn.disabled = !preset.can_edit;
  setComfyuiWorkflowStatus(`正在編輯 #${preset.id} ${preset.title || ""}`);
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
  setComfyuiWorkflowStatus(`已匯出目前 workflow，hash ${String((json.workflow_hash || "").slice(0, 12) || "-")}`);
  setComfyuiMessage("已把目前表單轉成 workflow JSON，可直接保存成 preset。", true);
  downloadComfyuiWorkflowText(`comfyui-current-workflow-${Date.now()}.json`, json.workflow_text || JSON.stringify(json.workflow_json || {}, null, 2));
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
      title: $("comfyui-workflow-title")?.value || "",
      description: $("comfyui-workflow-description")?.value || "",
      visibility: $("comfyui-workflow-visibility")?.value || "private",
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
      title: $("comfyui-workflow-title")?.value || "",
      description: $("comfyui-workflow-description")?.value || "",
      visibility: $("comfyui-workflow-visibility")?.value || "private",
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
  await fetchCsrfToken({ force: true });
  setComfyuiBusy(true);
  setComfyuiMessage("正在建立 workflow 執行工作...", true);
  startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS);
  const controller = new AbortController();
  comfyuiGenerateAbortController = controller;
  try {
    const res = await apiFetch(API + `/comfyui/workflows/${encodeURIComponent(presetId)}/run`, {
      method: "POST",
      credentials: "same-origin",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || "",
      },
      body: JSON.stringify({}),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `workflow 執行失敗（HTTP ${res.status}）`);
    const result = await pollComfyuiJobUntilDone(json.job?.job_id, controller, COMFYUI_GENERATION_TIMEOUT_SECONDS);
    const images = Array.isArray(result.images) && result.images.length ? result.images : [result.image].filter(Boolean);
    comfyuiGeneratedImages = images;
    renderComfyuiGeneratedImages(comfyuiGeneratedImages);
    setComfyuiSelectedImage(0);
    stopComfyuiProgress({ complete: true });
    updateComfyuiResultButtons(true);
    await loadComfyuiWorkflowPresets();
    setComfyuiMessage(`已執行 workflow preset #${presetId}。`, true);
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
  downloadComfyuiWorkflowText(json.filename || `comfyui-workflow-${presetId}.json`, json.workflow_text || JSON.stringify(json.workflow_json || {}, null, 2));
  setComfyuiMessage(`已匯出 workflow preset #${presetId}。`, true);
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
  comfyuiWorkflowEditorDefaults = null;
  setComfyuiMessage(`已載入 workflow 檔：${file.name}`, true);
}

function comfyuiSaveRequestPayload() {
  return {
    image_ref: comfyuiCurrentImage?.image_ref,
    virtual_path: $("comfyui-save-path")?.value || "",
    album_id: selectedComfyuiAlbumId()
  };
}

function setComfyuiSelectedImage(index) {
  const nextIndex = Math.max(0, Math.min(Number(index) || 0, comfyuiGeneratedImages.length - 1));
  comfyuiSelectedImageIndex = nextIndex;
  comfyuiCurrentImage = comfyuiGeneratedImages[nextIndex] || null;
  comfyuiSavedResult = null;
  const meta = $("comfyui-result-meta");
  if (meta && comfyuiCurrentImage) {
    const total = comfyuiGeneratedImages.length;
    const batchLabel = total > 1 ? ` · 第 ${nextIndex + 1}/${total} 張` : "";
    meta.textContent = `model=${comfyuiCurrentImage.model || "-"} · seed=${comfyuiCurrentImage.seed ?? "-"}${batchLabel} · ${formatDriveBytes(comfyuiCurrentImage.size_bytes || 0)}`;
  }
  const savePath = $("comfyui-save-path");
  if (savePath && comfyuiCurrentImage?.image_ref?.filename && (!savePath.value.trim() || savePath.dataset.comfyuiAutoPath === "1")) {
    savePath.value = `/output/${comfyuiCurrentImage.image_ref.filename}`;
    savePath.dataset.comfyuiAutoPath = "1";
    writeComfyuiDraft();
  }
  updateComfyuiResultButtons(!!comfyuiCurrentImage?.image_ref);
}

function renderComfyuiGeneratedImages(images) {
  const preview = $("comfyui-preview");
  if (!preview) return;
  if (!Array.isArray(images) || !images.length) {
    preview.innerHTML = `<div class="drive-empty">尚未產生圖片</div>`;
    return;
  }
  if (images.length === 1) {
    preview.innerHTML = `<img src="${sanitize(images[0].data_url || "")}" alt="ComfyUI generated image" />`;
    return;
  }
  preview.innerHTML = `
    <div class="comfyui-batch-grid">
      ${images.map((image, index) => `
        <button class="comfyui-batch-item${index === comfyuiSelectedImageIndex ? " active" : ""}" type="button" data-comfyui-image-index="${index}" title="選擇第 ${index + 1} 張">
          <img src="${sanitize(image.data_url || "")}" alt="ComfyUI generated image ${index + 1}" />
          <span>第 ${index + 1} 張</span>
        </button>
      `).join("")}
    </div>
  `;
  preview.querySelectorAll("[data-comfyui-image-index]").forEach((button) => {
    button.addEventListener("click", () => {
      setComfyuiSelectedImage(parseInt(button.getAttribute("data-comfyui-image-index"), 10));
      renderComfyuiGeneratedImages(comfyuiGeneratedImages);
    });
  });
}

async function loadComfyuiModels() {
  if (!currentUser || !canAccessModule("comfyui")) return;
  const status = $("comfyui-status");
  if (status) status.textContent = "連線 ComfyUI 中...";
  setComfyuiMessage("");
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/comfyui/models" + comfyuiRequestQuery(), {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (json.connection_mode) comfyuiConnectionMode = json.connection_mode;
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 連線失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "remote";
    fillComfyuiSelect("comfyui-model-select", json.models || [], "");
    comfyuiLoraDetails = json.lora_details && typeof json.lora_details === "object" ? json.lora_details : {};
    fillComfyuiLoraSelect(json.loras || []);
    fillComfyuiVaeSelect(json.vaes || []);
    renderComfyuiEmbeddingShortcuts(json.embeddings || []);
    fillComfyuiSelect("comfyui-sampler", json.samplers || [], "euler");
    fillComfyuiSelect("comfyui-scheduler", json.schedulers || [], "normal");
    fillComfyuiGenerationModes(json.generation_modes || []);
    fillComfyuiControlnetTypes(json.controlnet_types || {});
    fillComfyuiUpscaleModels(json.upscale_models || []);
    fillComfyuiControlnetModelOptions();
    fillComfyuiControlnetPreprocessorOptions();
    restoreComfyuiDraft();
    pruneUnsupportedComfyuiSelectedLoras({ notify: true });
    updateComfyuiModeVisibility();
    applyComfyuiRuntimeLimits(json);
    comfyuiModelsLoaded = true;
    loadComfyuiAlbums({ force: true }).catch(() => {});
    loadComfyuiHistory().catch(() => {});
    loadComfyuiWorkflowPresets().catch(() => {});
    setComfyuiTabAvailability(true);
    if (status) status.textContent = `已連線 ${json.comfyui_url || "ComfyUI"}${comfyuiBackendLabel(json)}，模型 ${Number((json.models || []).length)} 個，LoRA ${Number((json.loras || []).length)} 個，Embedding ${Number((json.embeddings || []).length)} 個，VAE ${Number((json.vaes || []).length)} 個`;
  } catch (err) {
    comfyuiModelsLoaded = false;
    comfyuiLoraDetails = {};
    setComfyuiTabAvailability(false, err.message || "ComfyUI 伺服器未連線");
    if (status) status.textContent = "ComfyUI 未連線";
    const startHint = comfyuiConnectionMode === "local" ? "。若使用本地模式，請先按「啟動 ComfyUI」。" : "";
    setComfyuiMessage((err.message || "ComfyUI 模型讀取失敗") + startHint, false);
  }
}

async function refreshComfyuiStatus({ switchAway = true } = {}) {
  if (!currentUser || !canAccessModule("comfyui")) {
    setComfyuiTabAvailability(null);
    return false;
  }
  const status = $("comfyui-status");
  if (status) status.textContent = "檢測 ComfyUI 伺服器中...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/comfyui/status" + comfyuiRequestQuery(), {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (json.connection_mode) comfyuiConnectionMode = json.connection_mode;
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 狀態檢測失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "remote";
    const available = !!json.available;
    const starting = !!json.starting;
    applyComfyuiRuntimeLimits(json);
    const detail = available
      ? `已偵測 ${json.comfyui_url || "ComfyUI"}${comfyuiBackendLabel(json)}`
      : (json.msg || `找不到 ${json.comfyui_url || "ComfyUI"} 伺服器`);
    setComfyuiTabAvailability(available, detail);
    if (available) stopComfyuiLocalStartPolling();
    else if (starting && comfyuiConnectionMode === "local") scheduleComfyuiLocalStartPolling();
    else stopComfyuiLocalStartPolling();
    if (status) status.textContent = detail;
    if (!available) {
      comfyuiModelsLoaded = false;
      setComfyuiBusy(false);
    }
    return available;
  } catch (err) {
    const message = err.message || "ComfyUI 伺服器未連線";
    setComfyuiTabAvailability(false, message);
    comfyuiModelsLoaded = false;
    setComfyuiBusy(false);
    return false;
  }
}

async function startLocalComfyui() {
  const start = $("comfyui-start-btn");
  const status = $("comfyui-status");
  let keepIdleSuspend = false;
  if (start) {
    start.disabled = true;
    start.textContent = "啟動中...";
  }
  setComfyuiIdleSuspend("comfyui_start_local", true, "ComfyUI 啟動中");
  setComfyuiMessage("正在送出本地 ComfyUI 啟動請求。第一次安裝依賴可能需要數分鐘。", true);
  if (status) status.textContent = "正在啟動本地 ComfyUI...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/comfyui/start", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({})
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 啟動失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "local";
    const info = json.start || {};
    setComfyuiMessage(json.msg || "已送出 ComfyUI 啟動請求。", true);
    if (status) status.textContent = info.already_running ? "ComfyUI 已在執行中" : "已送出啟動請求，正在重新檢查連線...";
    if (info.started && info.available === false) {
      comfyuiServerAvailable = false;
      setComfyuiTabAvailability(false, info.message || "ComfyUI 正在背景啟動中");
      if (status) status.textContent = info.message || "ComfyUI 正在背景啟動中，稍後請按重新整理模型";
      keepIdleSuspend = true;
      scheduleComfyuiLocalStartPolling();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await loadComfyuiModels();
  } catch (err) {
    setComfyuiMessage(err.message || "ComfyUI 啟動失敗", false);
    if (status) status.textContent = "ComfyUI 啟動失敗";
  } finally {
    if (!keepIdleSuspend) setComfyuiIdleSuspend("comfyui_start_local", false, "ComfyUI 啟動中");
    if (start) {
      start.disabled = false;
      start.textContent = "啟動 ComfyUI";
    }
    updateComfyuiStartButton();
  }
}

async function stopLocalComfyui() {
  const stop = $("comfyui-stop-btn");
  const status = $("comfyui-status");
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以停止本地 ComfyUI。", false);
    return;
  }
  if (stop) {
    stop.disabled = true;
    stop.textContent = "停止中...";
  }
  setComfyuiMessage("正在停止本地 ComfyUI...", true);
  if (status) status.textContent = "正在停止本地 ComfyUI...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/stop", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({})
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 停止失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "local";
    comfyuiModelsLoaded = false;
    setComfyuiTabAvailability(false, json.msg || "ComfyUI 已停止");
    if (status) status.textContent = json.msg || "ComfyUI 已停止";
    setComfyuiMessage(json.msg || "已停止本地 ComfyUI。", true);
    stopComfyuiLocalStartPolling();
  } catch (err) {
    setComfyuiMessage(err.message || "ComfyUI 停止失敗", false);
    if (status) status.textContent = "ComfyUI 停止失敗";
  } finally {
    if (stop) {
      stop.disabled = false;
      stop.textContent = "停止 ComfyUI";
    }
    updateComfyuiStartButton();
  }
}

function comfyuiNumberValue(id, fallback) {
  const raw = $(id)?.value;
  if (raw === "" || raw === null || raw === undefined) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

function comfyuiPayload() {
  const vae = $("comfyui-vae-select")?.value || COMFYUI_VAE_BUILTIN;
  const mode = comfyuiGenerationMode();
  const payload = {
    generation_mode: mode,
    model: $("comfyui-model-select")?.value || "",
    prompt: $("comfyui-prompt")?.value || "",
    negative_prompt: $("comfyui-negative-prompt")?.value || "",
    width: comfyuiNumberValue("comfyui-width", comfyuiDefaultWidth),
    height: comfyuiNumberValue("comfyui-height", comfyuiDefaultHeight),
    steps: comfyuiNumberValue("comfyui-steps", 20),
    cfg: comfyuiNumberValue("comfyui-cfg", 7),
    batch_size: Math.max(1, Math.min(comfyuiMaxBatchSize, comfyuiNumberValue("comfyui-batch-size", 1))),
    seed: $("comfyui-seed")?.value ? comfyuiNumberValue("comfyui-seed", 0) : undefined,
    sampler_name: $("comfyui-sampler")?.value || "euler",
    scheduler: $("comfyui-scheduler")?.value || "normal",
    vae: vae === COMFYUI_VAE_BUILTIN ? "" : vae,
    loras: comfyuiSelectedLoras.slice(0, COMFYUI_MAX_LORAS),
    denoise_strength: comfyuiNumberValue("comfyui-denoise-strength", 0.65),
    filename_prefix: "hackme_web",
  };
  if (comfyuiInputAssets.source?.imageRef) payload.source_image_ref = comfyuiInputAssets.source.imageRef;
  if (comfyuiInputAssets.mask?.imageRef) payload.mask_image_ref = comfyuiInputAssets.mask.imageRef;
  if (isComfyuiControlnetEnabled()) {
    payload.controlnet = {
      type: comfyuiSelectedControlnetType(),
      model_name: $("comfyui-controlnet-model")?.value || "",
      preprocessor: $("comfyui-controlnet-preprocessor")?.value || "",
      strength: comfyuiNumberValue("comfyui-control-strength", 1),
      start_percent: comfyuiNumberValue("comfyui-control-start", 0),
      end_percent: comfyuiNumberValue("comfyui-control-end", 1),
    };
    if (comfyuiInputAssets.control?.imageRef) payload.controlnet.image_ref = comfyuiInputAssets.control.imageRef;
  }
  if (mode === "outpaint") {
    payload.outpaint = {
      left: Math.max(0, Math.floor(comfyuiNumberValue("comfyui-outpaint-left", 128))),
      top: Math.max(0, Math.floor(comfyuiNumberValue("comfyui-outpaint-top", 128))),
      right: Math.max(0, Math.floor(comfyuiNumberValue("comfyui-outpaint-right", 128))),
      bottom: Math.max(0, Math.floor(comfyuiNumberValue("comfyui-outpaint-bottom", 128))),
      feathering: Math.max(0, Math.floor(comfyuiNumberValue("comfyui-outpaint-feathering", 48))),
    };
  }
  if (mode === "upscale") {
    payload.upscale_model = $("comfyui-upscale-model")?.value || "";
  }
  return payload;
}

function comfyuiValidatePayloadForUi(payload) {
  const mode = String(payload?.generation_mode || "").trim().toLowerCase();
  const needsSource = comfyuiModeUsesSourceImage(mode);
  const needsMask = comfyuiModeUsesMaskImage(mode);
  if (needsSource && !comfyuiInputAssets.source?.file && !payload.source_image_ref) {
    return `「${comfyuiReadableModeLabel(mode)}」需要來源圖片。`;
  }
  if (needsMask && !comfyuiInputAssets.mask?.file && !payload.mask_image_ref) {
    return "局部重繪需要遮罩圖片。";
  }
  if (isComfyuiControlnetEnabled() && !comfyuiInputAssets.control?.file && !payload.controlnet?.image_ref) {
    return "啟用 ControlNet 時需要控制圖。";
  }
  if (mode === "upscale" && !String(payload.upscale_model || "").trim()) {
    return "放大修復需要選擇 scale model。";
  }
  return "";
}

function comfyuiBuildGenerateRequest(payload) {
  const useMultipart = COMFYUI_IMAGE_ASSET_KEYS.some((key) => comfyuiInputAssets[key]?.file);
  if (!useMultipart) {
    return {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
  }
  const form = new FormData();
  const appendScalar = (key, value) => {
    if (value === undefined || value === null || value === "") return;
    form.append(key, String(value));
  };
  appendScalar("generation_mode", payload.generation_mode);
  appendScalar("model", payload.model);
  appendScalar("prompt", payload.prompt);
  appendScalar("negative_prompt", payload.negative_prompt);
  appendScalar("width", payload.width);
  appendScalar("height", payload.height);
  appendScalar("steps", payload.steps);
  appendScalar("cfg", payload.cfg);
  appendScalar("batch_size", payload.batch_size);
  appendScalar("seed", payload.seed);
  appendScalar("sampler_name", payload.sampler_name);
  appendScalar("scheduler", payload.scheduler);
  appendScalar("vae", payload.vae);
  appendScalar("denoise_strength", payload.denoise_strength);
  appendScalar("upscale_model", payload.upscale_model);
  appendScalar("filename_prefix", payload.filename_prefix);
  if (payload.source_image_ref) form.append("source_image_ref", JSON.stringify(payload.source_image_ref));
  if (payload.mask_image_ref) form.append("mask_image_ref", JSON.stringify(payload.mask_image_ref));
  if (Array.isArray(payload.loras) && payload.loras.length) form.append("loras_json", JSON.stringify(payload.loras));
  if (payload.controlnet) {
    appendScalar("controlnet_enabled", true);
    appendScalar("controlnet_type", payload.controlnet.type);
    appendScalar("controlnet_model", payload.controlnet.model_name || "");
    appendScalar("controlnet_preprocessor", payload.controlnet.preprocessor || "");
    appendScalar("control_strength", payload.controlnet.strength);
    appendScalar("control_start", payload.controlnet.start_percent);
    appendScalar("control_end", payload.controlnet.end_percent);
    if (payload.controlnet.image_ref) form.append("control_image_ref", JSON.stringify(payload.controlnet.image_ref));
  }
  if (payload.outpaint) {
    appendScalar("outpaint_left", payload.outpaint.left);
    appendScalar("outpaint_top", payload.outpaint.top);
    appendScalar("outpaint_right", payload.outpaint.right);
    appendScalar("outpaint_bottom", payload.outpaint.bottom);
    appendScalar("outpaint_feathering", payload.outpaint.feathering);
  }
  if (comfyuiInputAssets.source?.file) form.append("source_image", comfyuiInputAssets.source.file, comfyuiInputAssets.source.file.name || "source.png");
  if (comfyuiInputAssets.mask?.file) form.append("mask_image", comfyuiInputAssets.mask.file, comfyuiInputAssets.mask.file.name || "mask.png");
  if (comfyuiInputAssets.control?.file) form.append("control_image", comfyuiInputAssets.control.file, comfyuiInputAssets.control.file.name || "control.png");
  return { headers: {}, body: form };
}

function comfyuiRunCount() {
  return Math.max(1, Math.min(10, Math.floor(comfyuiNumberValue("comfyui-run-count", 1))));
}

function comfyuiShareGenerationPayload() {
  const payload = comfyuiPayload();
  if (comfyuiCurrentImage && comfyuiCurrentImage.seed !== undefined && comfyuiCurrentImage.seed !== null) {
    payload.seed = comfyuiCurrentImage.seed;
  }
  if (comfyuiCurrentImage?.model) {
    payload.model = comfyuiCurrentImage.model;
  }
  return payload;
}

function confirmComfyuiBilling(payload) {
  if (currentUser === "root") return { confirmed: true, required: false };
  if (!comfyuiBillingQuote?.unit_price) return { confirmed: true, required: false };
  const unitPrice = Number(comfyuiBillingQuote.unit_price || 0);
  const batchSize = Math.max(1, Math.min(comfyuiMaxBatchSize, Number(payload?.batch_size || 1)));
  const runCount = comfyuiRunCount();
  const totalImages = batchSize * runCount;
  const loraCount = Array.isArray(payload?.loras) ? payload.loras.length : 0;
  const loraUnitPrice = Number(comfyuiBillingQuote.lora_extra_unit_price || COMFYUI_LORA_EXTRA_PRICE);
  const loraExtra = loraCount * loraUnitPrice * totalImages;
  const totalPrice = unitPrice * totalImages + loraExtra;
  const loraText = loraCount > 0 ? `\nLoRA 加價：${loraCount} 個 x ${loraUnitPrice} 點 x ${totalImages} 張 = ${loraExtra} 點。` : "";
  const confirmed = window.confirm(
    `本次成功產圖最多將扣 ${totalPrice} 點（基礎 ${unitPrice} 點 x ${batchSize} 張 x ${runCount} 次）。${loraText}\n` +
    "產圖失敗不扣點；丟棄預覽不退款。\n\n是否確認送出？"
  );
  return { confirmed, required: true, totalPrice, unitPrice, batchSize, runCount, totalImages, loraCount, loraExtra };
}

async function preflightComfyuiBilling(payload, runCount, billingConfirmation) {
  if (!billingConfirmation?.required) return null;
  const res = await apiFetch(API + "/comfyui/billing-quote", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": getCsrfToken() || ""
    },
    body: JSON.stringify({
      ...payload,
      run_count: runCount,
      ...comfyuiRequestPayloadExtras()
    })
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    throw new Error(json.msg || `ComfyUI 扣點預檢失敗（HTTP ${res.status}）`);
  }
  return json.billing || null;
}

async function generateComfyuiImage() {
  if (comfyuiServerAvailable === false) {
    const hint = comfyuiConnectionMode === "local" ? "請先按「啟動 ComfyUI」，或確認已有其他使用者啟動服務。" : "ComfyUI 伺服器未連線，無法產圖。";
    setComfyuiMessage(hint, false);
    return;
  }
  if (!comfyuiModelsLoaded) {
    await loadComfyuiModels();
  }
  if (!comfyuiModelsLoaded) return;
  const payload = comfyuiPayload();
  const validationMessage = comfyuiValidatePayloadForUi(payload);
  if (validationMessage) {
    setComfyuiMessage(validationMessage, false);
    return;
  }
  const runCount = comfyuiRunCount();
  const billingConfirmation = confirmComfyuiBilling(payload);
  if (!billingConfirmation.confirmed) {
    setComfyuiMessage("已取消產圖扣點確認", false);
    return;
  }
  const preview = $("comfyui-preview");
  const meta = $("comfyui-result-meta");
  if (preview) preview.innerHTML = `<div class="drive-empty">產生圖片中...</div>`;
  if (meta) meta.textContent = "";
  comfyuiCurrentImage = null;
  comfyuiGeneratedImages = [];
  comfyuiSelectedImageIndex = 0;
  comfyuiSavedResult = null;
  updateComfyuiResultButtons(false);
  setComfyuiBusy(true);
  setComfyuiMessage("");
  const controller = new AbortController();
  comfyuiGenerateAbortController = controller;
  try {
    await fetchCsrfToken({ force: true });
    const preflightBilling = await preflightComfyuiBilling(payload, runCount, billingConfirmation);
    if (preflightBilling) {
      comfyuiBillingQuote = { ...(comfyuiBillingQuote || {}), ...preflightBilling };
    }
    const generateRequest = comfyuiBuildGenerateRequest(payload);
    startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS * runCount);
    let totalCharged = 0;
    const generated = [];
    const requestedBatchSize = Math.max(1, Math.min(comfyuiMaxBatchSize, Number(payload.batch_size || 1)));
    const totalRequests = runCount * requestedBatchSize;
    for (let requestIndex = 0; requestIndex < totalRequests; requestIndex += 1) {
      if (controller.signal.aborted) throw new DOMException("Aborted", "AbortError");
      const runIndex = Math.floor(requestIndex / requestedBatchSize);
      const batchIndex = requestIndex % requestedBatchSize;
      setComfyuiMessage(`正在產生第 ${requestIndex + 1} / ${totalRequests} 張圖片...`, true);
      const startRes = await apiFetch(API + "/comfyui/generate", {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
        headers: {
          "X-CSRF-Token": getCsrfToken() || "",
          ...(generateRequest.headers || {})
        },
        body: (() => {
          if (generateRequest.body instanceof FormData) {
            const body = new FormData();
            generateRequest.body.forEach((value, key) => body.append(key, value));
            body.append("batch_size", "1");
            body.append("async_progress", "true");
            body.append("confirm_billing", billingConfirmation.required ? "true" : "false");
            body.append("timeout_seconds", String(COMFYUI_GENERATION_TIMEOUT_SECONDS));
            Object.entries(comfyuiRequestPayloadExtras() || {}).forEach(([key, value]) => {
              if (value !== undefined && value !== null && value !== "") body.append(key, String(value));
            });
            return body;
          }
          return JSON.stringify({
            ...payload,
            batch_size: 1,
            async_progress: true,
            confirm_billing: billingConfirmation.required,
            timeout_seconds: COMFYUI_GENERATION_TIMEOUT_SECONDS,
            ...comfyuiRequestPayloadExtras()
          });
        })()
      });
      const startJson = await startRes.json().catch(() => ({}));
      if (!startRes.ok || !startJson.ok) throw new Error(startJson.msg || `第 ${requestIndex + 1} 張產圖失敗（HTTP ${startRes.status}）`);
      const jobId = startJson.job?.job_id;
      if (!jobId) throw new Error("ComfyUI 未回傳工作編號");
      const json = await pollComfyuiJobUntilDone(jobId, controller, COMFYUI_GENERATION_TIMEOUT_SECONDS);
      const runImages = Array.isArray(json.images) && json.images.length ? json.images : [json.image].filter(Boolean);
      runImages.forEach((image) => {
        generated.push({ ...image, run_index: runIndex, batch_index: batchIndex, run_count: runCount });
      });
      comfyuiGeneratedImages = generated.slice();
      if (comfyuiGeneratedImages.length) {
        comfyuiSelectedImageIndex = Math.max(0, comfyuiGeneratedImages.length - 1);
        comfyuiCurrentImage = comfyuiGeneratedImages[comfyuiSelectedImageIndex];
        renderComfyuiGeneratedImages(comfyuiGeneratedImages);
        setComfyuiSelectedImage(comfyuiSelectedImageIndex);
        updateComfyuiResultButtons(true);
      }
      if (json.billing?.charged) totalCharged += Number(json.billing.total_price || 0);
    }
    comfyuiGeneratedImages = generated;
    comfyuiCurrentImage = comfyuiGeneratedImages[0] || null;
    if (!comfyuiCurrentImage?.data_url) throw new Error("ComfyUI 未回傳圖片");
    renderComfyuiGeneratedImages(comfyuiGeneratedImages);
    setComfyuiSelectedImage(0);
    stopComfyuiProgress({ complete: true });
    updateComfyuiResultButtons(true);
    loadComfyuiHistory().catch(() => {});
    const billingText = totalCharged > 0
      ? `已扣 ${totalCharged} 點。`
      : "";
    setComfyuiMessage(`已執行 ${runCount} 次，共產生 ${comfyuiGeneratedImages.length} 張圖片；${billingText}請選擇要儲存或分享的圖片。`, true);
  } catch (err) {
    const interrupted = err?.name === "AbortError";
    const message = interrupted ? "已中斷產圖" : (err.message || "產圖失敗");
    if (preview) preview.innerHTML = `<div class="drive-empty">${sanitize(message)}</div>`;
    stopComfyuiProgress({ error: message });
    setComfyuiMessage(message, interrupted);
  } finally {
    comfyuiActiveJobId = null;
    if (comfyuiGenerateAbortController === controller) comfyuiGenerateAbortController = null;
    setComfyuiBusy(false);
  }
}

async function interruptComfyuiGeneration() {
  if (!comfyuiGenerateAbortController) {
    setComfyuiMessage("目前沒有進行中的產圖可中斷", false);
    return;
  }
  const interruptBtn = $("comfyui-interrupt-btn");
  if (interruptBtn) {
    interruptBtn.disabled = true;
    interruptBtn.textContent = "中斷中...";
  }
  setComfyuiProgress({
    visible: true,
    running: false,
    percent: 100,
    label: "正在中斷產圖",
    detail: "已停止前端等待，後端會在不影響其他使用者時才送出 ComfyUI 中斷"
  });
  comfyuiGenerateAbortController.abort();
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/comfyui/interrupt", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({
        ...comfyuiRequestPayloadExtras()
      })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `中斷產圖失敗（HTTP ${res.status}）`);
    setComfyuiMessage(json.msg || "已送出中斷產圖請求", true);
  } catch (err) {
    setComfyuiMessage(err.message || "中斷產圖失敗", false);
  } finally {
    if (interruptBtn) {
      interruptBtn.textContent = "中斷產圖";
    }
  }
}

async function saveComfyuiImageToDrive() {
  if (!comfyuiCurrentImage?.image_ref) {
    setComfyuiMessage("目前沒有可儲存的產圖結果", false);
    return;
  }
  const saveBtn = $("comfyui-save-btn");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "儲存中...";
  }
  setComfyuiMessage("");
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/comfyui/save", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify(comfyuiSaveRequestPayload())
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `儲存失敗（HTTP ${res.status}）`);
    comfyuiSavedResult = json;
    const albumText = json.album ? "，並加入相簿" : "";
    setComfyuiMessage(`已存到雲端硬碟${albumText}：${json.storage_file?.virtual_path || json.file?.file_id || ""}`, true);
    if (typeof loadDriveDashboard === "function") await loadDriveDashboard();
    await loadComfyuiAlbums({ force: true });
  } catch (err) {
    setComfyuiMessage(err.message || "儲存失敗", false);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "存到雲端硬碟";
    }
  }
}

async function discardComfyuiImage() {
  const imagesToDiscard = comfyuiGeneratedImages.length ? comfyuiGeneratedImages : [comfyuiCurrentImage].filter(Boolean);
  if (imagesToDiscard.some((image) => image?.image_ref)) {
    const discardBtn = $("comfyui-discard-btn");
    if (discardBtn) {
      discardBtn.disabled = true;
      discardBtn.textContent = "刪除中...";
    }
    try {
      await fetchCsrfToken({ force: true });
      for (const image of imagesToDiscard) {
        if (!image?.image_ref) continue;
        const res = await apiFetch(API + "/comfyui/discard", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": getCsrfToken() || ""
          },
          body: JSON.stringify({
            image_ref: image.image_ref,
            prompt_id: image.prompt_id || ""
          })
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok || !json.ok) throw new Error(json.msg || `刪除 ComfyUI 原始檔失敗（HTTP ${res.status}）`);
        if (json.warning === "source_file_not_deleted") {
          setComfyuiMessage(json.msg || "已丟棄預覽；ComfyUI 原始檔未刪除。", false);
        }
      }
    } catch (err) {
      if (discardBtn) {
        discardBtn.disabled = false;
        discardBtn.textContent = "丟棄預覽";
      }
      setComfyuiMessage(err.message || "刪除 ComfyUI 原始檔失敗", false);
      return;
    }
  }
  comfyuiCurrentImage = null;
  comfyuiGeneratedImages = [];
  comfyuiSelectedImageIndex = 0;
  comfyuiSavedResult = null;
  const preview = $("comfyui-preview");
  const meta = $("comfyui-result-meta");
  if (preview) preview.innerHTML = `<div class="drive-empty">已丟棄這次預覽</div>`;
  if (meta) meta.textContent = "";
  stopComfyuiProgress();
  updateComfyuiResultButtons(false);
  const discardBtn = $("comfyui-discard-btn");
  if (discardBtn) discardBtn.textContent = "丟棄預覽";
  if (!$("comfyui-msg")?.textContent) {
    setComfyuiMessage("已丟棄預覽，ComfyUI 原始檔也已刪除。", true);
  }
}

async function shareComfyuiToCommunity() {
  if (!comfyuiCurrentImage?.image_ref && !comfyuiSavedResult?.file?.file_id) {
    setComfyuiMessage("目前沒有可分享的產圖結果", false);
    return;
  }
  const shareBtn = $("comfyui-share-btn");
  if (shareBtn) {
    shareBtn.disabled = true;
    shareBtn.textContent = "分享中...";
  }
  setComfyuiMessage("");
  try {
    await fetchCsrfToken({ force: true });
    const savedFile = comfyuiSavedResult?.file || {};
    const savedStorageFile = comfyuiSavedResult?.storage_file || {};
    const res = await apiFetch(API + "/comfyui/share", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({
        ...comfyuiSaveRequestPayload(),
        file_id: savedFile.file_id || "",
        storage_file_id: savedStorageFile.id || "",
        title: $("comfyui-share-title")?.value || "",
        note: $("comfyui-share-note")?.value || "",
        generation: comfyuiShareGenerationPayload()
      })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `分享失敗（HTTP ${res.status}）`);
    comfyuiSavedResult = {
      file: json.file,
      storage_file: json.storage_file,
      album: json.album
    };
    setComfyuiMessage(`${json.msg || "已分享到 ComfyUI 專區"}：${json.thread?.title || ""}`, true);
    if (json.thread?.board_id && typeof switchModuleTab === "function") {
      if (typeof loadCommunityBoards === "function") loadCommunityBoards().catch(() => {});
    }
    if (typeof loadDriveDashboard === "function") await loadDriveDashboard();
    await loadComfyuiAlbums({ force: true });
  } catch (err) {
    setComfyuiMessage(err.message || "分享失敗", false);
  } finally {
    if (shareBtn) {
      shareBtn.disabled = !comfyuiCurrentImage?.image_ref;
      shareBtn.textContent = "分享到 ComfyUI 專區";
    }
  }
}

function formatComfyuiCivitaiFileSize(file) {
  const sizeBytes = Number(file?.size_bytes || 0);
  if (sizeBytes > 0 && typeof formatDriveBytes === "function") {
    return formatDriveBytes(sizeBytes);
  }
  const sizeKb = Number(file?.size_kb || 0);
  if (sizeKb > 0 && typeof formatDriveBytes === "function") {
    return formatDriveBytes(Math.round(sizeKb * 1024));
  }
  return "";
}

function summarizeComfyuiCivitaiHashes(file) {
  const hashes = file && typeof file.hashes === "object" ? file.hashes : {};
  return Object.entries(hashes)
    .filter(([key, value]) => String(key || "").trim() && String(value || "").trim())
    .slice(0, 3)
    .map(([key, value]) => `${String(key).toUpperCase()}: ${String(value)}`);
}

function renderComfyuiCivitaiSearchResults(results) {
  const box = $("comfyui-civitai-search-results");
  if (!box) return;
  comfyuiCivitaiSearchResults = Array.isArray(results) ? results.slice() : [];
  if (!comfyuiCivitaiSearchResults.length) {
    box.innerHTML = '<div class="drive-card-sub">沒有符合條件的 Civitai 模型。可調整關鍵字、base model、類型或 Safe/NSFW 篩選。</div>';
    return;
  }
  box.innerHTML = comfyuiCivitaiSearchResults.map((item) => {
    const latestVersion = item.latest_version || {};
    const primaryFile = latestVersion.primary_file || {};
    const hashSummary = summarizeComfyuiCivitaiHashes(primaryFile);
    const compatibleModels = Array.isArray(item.compatible_models) ? item.compatible_models.filter(Boolean) : [];
    const sizeLabel = formatComfyuiCivitaiFileSize(primaryFile);
    const createdAt = latestVersion.created_at ? new Date(latestVersion.created_at).toLocaleString() : "";
    const nsfwChip = item.nsfw ? '<span class="comfyui-civitai-search-chip warn">NSFW</span>' : '<span class="comfyui-civitai-search-chip">Safe</span>';
    return `
      <div class="comfyui-civitai-search-card">
        <div class="comfyui-civitai-search-head">
          <div class="comfyui-civitai-search-title">
            <strong>${sanitize(item.name || "未命名模型")}</strong>
            <span>${sanitize(item.creator ? `by ${item.creator}` : "官方未提供作者")} · ${sanitize(item.type || "未知類型")} · ${sanitize(`版本 ${item.version_count || 0}`)}</span>
          </div>
          <div class="comfyui-civitai-search-flags">
            <span class="comfyui-civitai-search-chip">${sanitize(item.suggested_model_type || "checkpoint")}</span>
            ${nsfwChip}
          </div>
        </div>
        <div class="comfyui-civitai-search-meta">
          <span>最新版本：${sanitize(latestVersion.name || "未命名版本")}</span>
          ${latestVersion.base_model ? `<span>Base model：${sanitize(latestVersion.base_model)}</span>` : ""}
          ${createdAt ? `<span>更新時間：${sanitize(createdAt)}</span>` : ""}
        </div>
        <div class="comfyui-civitai-search-meta">
          ${compatibleModels.length ? `<span>相容模型：${sanitize(compatibleModels.join(", "))}</span>` : '<span>相容模型：官方未標示</span>'}
          ${primaryFile.name ? `<span>檔案：${sanitize(primaryFile.name)}</span>` : ""}
          ${sizeLabel ? `<span>大小：${sanitize(sizeLabel)}</span>` : ""}
        </div>
        <div class="comfyui-civitai-search-hashes">
          ${hashSummary.length ? hashSummary.map((value) => `<span>${sanitize(value)}</span>`).join("") : '<span>hash：官方未提供</span>'}
        </div>
        <div class="drive-card-sub">搜尋結果使用固定版本摘要顯示；若顯示下載前資料不足，可先帶入下載區讀取完整版本與檔案清單。</div>
        <div class="drive-file-actions" style="justify-content:flex-start;">
          <button class="btn" type="button" data-comfyui-civitai-select="${sanitize(String(item.model_id || ""))}">帶入下載區</button>
        </div>
      </div>
    `;
  }).join("");
  box.querySelectorAll("[data-comfyui-civitai-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const modelId = button.getAttribute("data-comfyui-civitai-select") || "";
      useComfyuiCivitaiSearchResult(modelId).catch((err) => setComfyuiMessage(err.message || "帶入 Civitai 模型失敗", false));
    });
  });
}

async function useComfyuiCivitaiSearchResult(modelId) {
  const selected = comfyuiCivitaiSearchResults.find((item) => String(item.model_id || "") === String(modelId || ""));
  if (!selected) {
    setComfyuiMessage("找不到要帶入的 Civitai 搜尋結果。", false);
    return;
  }
  if ($("comfyui-civitai-url")) $("comfyui-civitai-url").value = selected.selected_page_url || selected.page_url || "";
  if ($("comfyui-model-download-type") && selected.suggested_model_type) {
    $("comfyui-model-download-type").value = selected.suggested_model_type;
  }
  const status = $("comfyui-civitai-search-status");
  if (status) status.textContent = `已帶入 ${selected.name}，正在讀取完整版本與檔案資訊...`;
  await inspectComfyuiCivitaiModel();
}

async function searchComfyuiCivitaiModels() {
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以搜尋 Civitai 模型。", false);
    return;
  }
  const button = $("comfyui-civitai-search-btn");
  const status = $("comfyui-civitai-search-status");
  const query = ($("comfyui-civitai-search-query")?.value || "").trim();
  const baseModel = ($("comfyui-civitai-search-base-model")?.value || "").trim();
  const modelType = ($("comfyui-civitai-search-type")?.value || "").trim();
  const nsfwMode = ($("comfyui-civitai-search-nsfw")?.value || "safe").trim() || "safe";
  if (button) {
    button.disabled = true;
    button.textContent = "搜尋中...";
  }
  if (status) status.textContent = "正在搜尋 Civitai 模型...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/civitai/search", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || "",
      },
      body: JSON.stringify({
        query,
        base_model: baseModel,
        model_type: modelType,
        nsfw_mode: nsfwMode,
        limit: 12,
      }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `Civitai 搜尋失敗（HTTP ${res.status}）`);
    renderComfyuiCivitaiSearchResults(json.results || []);
    if (status) status.textContent = json.msg || "已取得 Civitai 搜尋結果。";
    setComfyuiMessage(json.msg || "已取得 Civitai 搜尋結果。", true);
  } catch (err) {
    renderComfyuiCivitaiSearchResults([]);
    if (status) status.textContent = err.message || "Civitai 搜尋失敗";
    setComfyuiMessage(err.message || "Civitai 搜尋失敗", false);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "搜尋 Civitai";
    }
  }
}

function renderComfyuiCivitaiFiles(versionId) {
  const fileSelect = $("comfyui-civitai-file");
  if (!fileSelect) return;
  const versions = comfyuiCivitaiInspection?.versions || [];
  const selectedVersion = versions.find((item) => String(item.id) === String(versionId || "")) || null;
  const files = selectedVersion?.files || [];
  fileSelect.innerHTML = files.length
    ? files.map((file) => {
        const sizeLabel = file.size_kb ? ` · ${Math.round(Number(file.size_kb) / 1024 * 10) / 10} MB` : "";
        return `<option value="${sanitize(String(file.id || ""))}">${sanitize(file.name || "未命名檔案")}${sanitize(sizeLabel)}</option>`;
      }).join("")
    : `<option value="">這個版本沒有可下載檔案</option>`;
}

function renderComfyuiCivitaiTrainedWords(versionId) {
  const box = $("comfyui-civitai-trained-words");
  if (!box) return;
  const versions = comfyuiCivitaiInspection?.versions || [];
  const selectedVersion = versions.find((item) => String(item.id) === String(versionId || "")) || null;
  const trainedWords = Array.isArray(selectedVersion?.trained_words)
    ? selectedVersion.trained_words.filter(Boolean).map(String)
    : [];
  if (!trainedWords.length) {
    box.innerHTML = '<span class="drive-card-sub">這個版本沒有提供 trigger words，或官方沒有填寫。</span>';
    return;
  }
  box.innerHTML = trainedWords.map((value) => (
    `<button class="comfyui-embedding-chip" type="button" data-comfyui-trained-word="${sanitize(value)}" title="Trigger word：${sanitize(value)}">${sanitize(value)}</button>`
  )).join("");
  box.querySelectorAll("[data-comfyui-trained-word]").forEach((button) => {
    button.addEventListener("click", () => {
      const triggerWord = button.getAttribute("data-comfyui-trained-word") || "";
      if (!triggerWord) return;
      setComfyuiMessage(`這個版本的 trigger word：${triggerWord}`, true);
    });
  });
}

function renderComfyuiCivitaiInspection(model) {
  const versionSelect = $("comfyui-civitai-version");
  const status = $("comfyui-model-download-status");
  if (!versionSelect) return;
  comfyuiCivitaiInspection = model || null;
  const versions = comfyuiCivitaiInspection?.versions || [];
  versionSelect.innerHTML = versions.length
    ? versions.map((version) => {
        const labelBits = [version.name || `Version ${version.id}`];
        if (version.base_model) labelBits.push(version.base_model);
        return `<option value="${sanitize(String(version.id || ""))}">${sanitize(labelBits.join(" · "))}</option>`;
      }).join("")
    : `<option value="">請先讀取模型</option>`;
  const selectedVersionId = comfyuiCivitaiInspection?.selected_version_id || versions[0]?.id || "";
  versionSelect.value = selectedVersionId ? String(selectedVersionId) : "";
  renderComfyuiCivitaiFiles(versionSelect.value);
  renderComfyuiCivitaiTrainedWords(versionSelect.value);
  if ($("comfyui-model-download-type") && comfyuiCivitaiInspection?.suggested_model_type) {
    $("comfyui-model-download-type").value = comfyuiCivitaiInspection.suggested_model_type;
  }
  if (status && model) {
    const creator = model.creator ? ` · by ${model.creator}` : "";
    status.textContent = `已讀取 ${model.name}${creator}，請選擇版本與檔案。`;
  }
}

function comfyuiSelectedModelSourceMode() {
  return String($("comfyui-model-source-mode")?.value || "civitai").trim().toLowerCase() || "civitai";
}

function updateComfyuiModelSourceMode() {
  const mode = comfyuiSelectedModelSourceMode();
  const civitai = $("comfyui-model-source-civitai");
  const upload = $("comfyui-model-source-upload");
  if (civitai) civitai.style.display = mode === "upload" ? "none" : "";
  if (upload) upload.style.display = mode === "upload" ? "" : "none";
}

function onComfyuiCivitaiVersionChange() {
  const versionId = $("comfyui-civitai-version")?.value || "";
  renderComfyuiCivitaiFiles(versionId);
  renderComfyuiCivitaiTrainedWords(versionId);
}

function setComfyuiModelDownloadProgress({ visible = true, running = false, percent = 0, label = "", detail = "" } = {}) {
  const panel = $("comfyui-model-download-progress");
  const bar = $("comfyui-model-download-progress-bar");
  const labelEl = $("comfyui-model-download-progress-label");
  const percentEl = $("comfyui-model-download-progress-percent");
  const detailEl = $("comfyui-model-download-progress-detail");
  if (!panel) return;
  panel.style.display = visible ? "" : "none";
  panel.classList.toggle("running", !!running);
  const safePercent = Math.max(0, Math.min(100, Math.round(Number(percent) || 0)));
  if (bar) bar.style.width = `${safePercent}%`;
  if (labelEl) labelEl.textContent = label || "模型下載中";
  if (percentEl) percentEl.textContent = `${safePercent}%`;
  if (detailEl) detailEl.textContent = detail || "";
}

async function pollComfyuiModelDownloadJob(jobId) {
  setComfyuiIdleSuspend("comfyui_model_download", true, "ComfyUI 模型下載中");
  try {
    while (true) {
      const res = await apiFetch(API + `/root/comfyui/download-jobs/${encodeURIComponent(jobId)}`, {
        credentials: "same-origin",
        headers: { "X-CSRF-Token": getCsrfToken() || "" }
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || !json.ok) throw new Error(json.msg || `模型下載進度讀取失敗（HTTP ${res.status}）`);
      const job = json.job || {};
      const progress = job.progress || {};
      const totalBytes = Number(progress.total_bytes || 0);
      const writtenBytes = Number(progress.bytes_written || 0);
      const sizeText = totalBytes > 0
        ? `${formatDriveBytes(writtenBytes)} / ${formatDriveBytes(totalBytes)}`
        : `${formatDriveBytes(writtenBytes)}`;
      const detail = `${progress.detail || "等待下載進度"}${writtenBytes > 0 ? `；${sizeText}` : ""}`;
      setComfyuiModelDownloadProgress({
        visible: true,
        running: job.status !== "completed" && job.status !== "error",
        percent: Number(progress.percent || 0),
        label: job.status === "completed" ? "模型已下載" : (job.status === "error" ? "模型下載失敗" : "模型下載中"),
        detail,
      });
      if (job.status === "completed") return job.result || {};
      if (job.status === "error") throw new Error(job.error || progress.detail || "模型下載失敗");
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  } finally {
    setComfyuiIdleSuspend("comfyui_model_download", false, "ComfyUI 模型下載中");
  }
}

async function inspectComfyuiCivitaiModel() {
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以下載 ComfyUI 模型。", false);
    return;
  }
  const inspectBtn = $("comfyui-civitai-inspect-btn");
  const status = $("comfyui-model-download-status");
  const pageUrl = ($("comfyui-civitai-url")?.value || "").trim();
  if (!pageUrl) {
    if (status) status.textContent = "請輸入 Civitai 模型頁網址。";
    setComfyuiMessage("請輸入 Civitai 模型頁網址。", false);
    return;
  }
  if (inspectBtn) {
    inspectBtn.disabled = true;
    inspectBtn.textContent = "讀取中...";
  }
  if (status) status.textContent = "正在讀取 Civitai 官方模型資訊...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/civitai/inspect", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({ page_url: pageUrl })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `模型資訊讀取失敗（HTTP ${res.status}）`);
    renderComfyuiCivitaiInspection(json.model || null);
    setComfyuiMessage(json.msg || "已讀取 Civitai 模型資訊。", true);
  } catch (err) {
    comfyuiCivitaiInspection = null;
    renderComfyuiCivitaiInspection(null);
    if (status) status.textContent = err.message || "模型資訊讀取失敗";
    setComfyuiMessage(err.message || "模型資訊讀取失敗", false);
  } finally {
    if (inspectBtn) {
      inspectBtn.disabled = false;
      inspectBtn.textContent = "讀取模型資訊";
    }
  }
}

async function downloadComfyuiCivitaiModel() {
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以下載 ComfyUI 模型。", false);
    return;
  }
  const button = $("comfyui-model-download-btn");
  const status = $("comfyui-model-download-status");
  const pageUrl = ($("comfyui-civitai-url")?.value || "").trim();
  const type = $("comfyui-model-download-type")?.value || "checkpoint";
  const baseDir = ($("comfyui-model-base-dir")?.value || "").trim();
  const versionId = $("comfyui-civitai-version")?.value || "";
  const fileId = $("comfyui-civitai-file")?.value || "";
  if (!pageUrl) {
    if (status) status.textContent = "請輸入 Civitai 模型頁網址。";
    setComfyuiMessage("請先輸入 Civitai 模型頁網址。", false);
    return;
  }
  if (!versionId) {
    if (status) status.textContent = "請先讀取模型資訊並選擇版本。";
    setComfyuiMessage("請先讀取模型資訊並選擇版本。", false);
    return;
  }
  const versions = Array.isArray(comfyuiCivitaiInspection?.versions) ? comfyuiCivitaiInspection.versions : [];
  const selectedVersion = versions.find((item) => String(item.id || "") === String(versionId)) || null;
  const selectedFile = Array.isArray(selectedVersion?.files)
    ? selectedVersion.files.find((item) => String(item.id || "") === String(fileId || "")) || selectedVersion.files[0] || null
    : null;
  const confirmBits = [
    `模型：${comfyuiCivitaiInspection?.name || "未命名模型"}`,
    `版本：${selectedVersion?.name || versionId}`,
    `檔案：${selectedFile?.name || "未命名檔案"}`,
  ];
  const sizeLabel = formatComfyuiCivitaiFileSize(selectedFile);
  if (sizeLabel) confirmBits.push(`大小：${sizeLabel}`);
  const hashSummary = summarizeComfyuiCivitaiHashes(selectedFile);
  if (hashSummary.length) confirmBits.push(`Hash：${hashSummary.join(" / ")}`);
  const compatibleModels = Array.isArray(comfyuiCivitaiInspection?.versions)
    ? [...new Set(comfyuiCivitaiInspection.versions.map((item) => String(item.base_model || "").trim()).filter(Boolean))]
    : [];
  if (compatibleModels.length) confirmBits.push(`相容模型：${compatibleModels.join(", ")}`);
  confirmBits.push("下載後會直接寫入本地 ComfyUI models 目錄。");
  if (!window.confirm(`請再次確認要下載這個 Civitai 模型：\n\n${confirmBits.join("\n")}`)) {
    if (status) status.textContent = "已取消模型下載。";
    setComfyuiMessage("已取消模型下載。", false);
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = "下載中...";
  }
  if (status) status.textContent = "正在建立模型下載工作...";
  setComfyuiModelDownloadProgress({
    visible: true,
    running: true,
    percent: 0,
    label: "準備下載",
    detail: "正在建立模型下載工作..."
  });
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/civitai/download", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({ page_url: pageUrl, version_id: versionId, file_id: fileId, type, base_dir: baseDir, async_progress: true })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `模型下載失敗（HTTP ${res.status}）`);
    const jobId = json.job?.job_id;
    if (!jobId) throw new Error("ComfyUI 未回傳模型下載工作編號");
    const info = await pollComfyuiModelDownloadJob(jobId);
    if (status) {
      const versionLabel = info?.civitai?.version_name ? ` · ${info.civitai.version_name}` : "";
      const trainedWords = Array.isArray(info?.civitai?.trained_words) ? info.civitai.trained_words.filter(Boolean) : [];
      const trainedText = trainedWords.length ? `；trigger words：${trainedWords.join(", ")}` : "";
      status.textContent = `${json.msg || "模型已下載"}${versionLabel}（${formatDriveBytes(info.size_bytes || 0)}）${trainedText}`;
    }
    setComfyuiModelDownloadProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "模型已下載",
      detail: `${info.filename || ""} · ${formatDriveBytes(info.size_bytes || 0)}`
    });
    setComfyuiMessage(json.msg || "模型已下載。請重新整理模型清單。", true);
    await loadComfyuiModels();
  } catch (err) {
    if (status) status.textContent = err.message || "模型下載失敗";
    setComfyuiModelDownloadProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "模型下載失敗",
      detail: err.message || "模型下載失敗"
    });
    setComfyuiMessage(err.message || "模型下載失敗", false);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "下載選定版本";
    }
  }
}

async function downloadComfyuiModelFromUrl() {
  return downloadComfyuiCivitaiModel();
}

async function uploadComfyuiModelFile() {
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以匯入 ComfyUI 模型。", false);
    return;
  }
  const button = $("comfyui-model-upload-btn");
  const status = $("comfyui-model-download-status");
  const fileInput = $("comfyui-model-upload-file");
  const file = fileInput?.files?.[0] || null;
  const type = $("comfyui-model-download-type")?.value || "checkpoint";
  const baseDir = ($("comfyui-model-base-dir")?.value || "").trim();
  if (!file) {
    if (status) status.textContent = "請先選擇要上傳的模型檔案。";
    setComfyuiMessage("請先選擇要上傳的模型檔案。", false);
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = "上傳中...";
  }
  if (status) status.textContent = "正在上傳模型檔...";
  setComfyuiModelDownloadProgress({
    visible: true,
    running: true,
    percent: 0,
    label: "準備匯入",
    detail: `正在上傳 ${file.name} ...`
  });
  try {
    await fetchCsrfToken({ force: true });
    const form = new FormData();
    form.append("type", type);
    form.append("base_dir", baseDir);
    form.append("model_file", file);
    const res = await apiFetch(API + "/root/comfyui/model-upload", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" },
      body: form,
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `模型上傳失敗（HTTP ${res.status}）`);
    const info = json.upload || {};
    if (status) status.textContent = `${json.msg || "模型已匯入"}（${formatDriveBytes(info.size_bytes || 0)}）`;
    setComfyuiModelDownloadProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "模型已匯入",
      detail: `${info.filename || file.name} · ${formatDriveBytes(info.size_bytes || 0)}`
    });
    setComfyuiMessage(json.msg || "模型已匯入。請重新整理模型清單。", true);
    if (fileInput) fileInput.value = "";
    await loadComfyuiModels();
  } catch (err) {
    if (status) status.textContent = err.message || "模型上傳失敗";
    setComfyuiModelDownloadProgress({
      visible: true,
      running: false,
      percent: 100,
      label: "模型上傳失敗",
      detail: err.message || "模型上傳失敗"
    });
    setComfyuiMessage(err.message || "模型上傳失敗", false);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "上傳模型檔";
    }
  }
}
