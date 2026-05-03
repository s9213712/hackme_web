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
let comfyuiMaxBatchSize = 1;
let comfyuiBillingQuote = null;
let comfyuiDefaultWidth = 1024;
let comfyuiDefaultHeight = 1024;
let comfyuiAvailableLoras = [];
let comfyuiSelectedLoras = [];
let comfyuiConnectionMode = "remote";
const COMFYUI_GENERATION_TIMEOUT_SECONDS = 900;
const COMFYUI_MAX_LORAS = 8;
const COMFYUI_LORA_EXTRA_PRICE = 1;
const COMFYUI_DRAFT_FIELD_IDS = [
  "comfyui-model-select",
  "comfyui-lora-limit",
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
  "comfyui-save-path",
  "comfyui-album-select",
  "comfyui-share-title",
  "comfyui-share-note",
];

function setComfyuiTabAvailability(available, detail = "") {
  comfyuiServerAvailable = available === null ? null : !!available;
  const tab = $("tab-module-comfyui");
  const unavailable = comfyuiServerAvailable === false && comfyuiConnectionMode !== "local";
  if (tab) {
    tab.disabled = unavailable;
    tab.classList.toggle("disabled", unavailable);
    tab.setAttribute("aria-disabled", unavailable ? "true" : "false");
    tab.title = unavailable ? (detail || "ComfyUI 伺服器未連線") : "";
  }
  const status = $("comfyui-status");
  if (status && comfyuiServerAvailable === false) {
    status.textContent = detail || "ComfyUI 伺服器未連線";
  }
  updateComfyuiStartButton();
}

function isComfyuiAvailableForNavigation() {
  return comfyuiServerAvailable !== false;
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

function setComfyuiBusy(busy) {
  const generate = $("comfyui-generate-btn");
  const interrupt = $("comfyui-interrupt-btn");
  const refresh = $("comfyui-refresh-btn");
  const start = $("comfyui-start-btn");
  const unavailable = comfyuiServerAvailable === false;
  if (generate) {
    generate.disabled = !!busy || unavailable;
    generate.textContent = busy ? "產生中..." : "產生圖片";
  }
  if (interrupt) interrupt.disabled = !busy;
  if (refresh) refresh.disabled = !!busy;
  if (start) start.disabled = !!busy;
}

function updateComfyuiStartButton() {
  const start = $("comfyui-start-btn");
  if (!start) return;
  start.style.display = comfyuiConnectionMode === "local" && comfyuiServerAvailable !== true ? "" : "none";
  start.disabled = !!comfyuiGenerateAbortController;
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

function fillComfyuiSelect(id, values, fallback) {
  const select = $(id);
  if (!select) return;
  const options = Array.isArray(values) && values.length ? values : [fallback].filter(Boolean);
  select.innerHTML = options.map((value) => `<option value="${sanitize(value)}">${sanitize(value)}</option>`).join("");
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
  if (comfyuiProgressTimer) clearInterval(comfyuiProgressTimer);
  comfyuiProgressStartedAt = Date.now();
  const update = () => {
    const elapsed = Math.max(0, Math.floor((Date.now() - comfyuiProgressStartedAt) / 1000));
    const ratio = timeoutSeconds > 0 ? elapsed / timeoutSeconds : 0;
    const percent = Math.min(95, Math.max(5, Math.round(ratio * 95)));
    let label = "送出產圖請求";
    if (elapsed >= 8) label = "ComfyUI 執行中";
    if (elapsed >= 45) label = "等待圖片輸出";
    if (elapsed >= Math.max(60, timeoutSeconds * 0.75)) label = "仍在等待 ComfyUI";
    setComfyuiProgress({
      visible: true,
      running: true,
      percent,
      label,
      detail: `已等待 ${formatComfyuiDuration(elapsed)} / 上限 ${formatComfyuiDuration(timeoutSeconds)}`
    });
  };
  update();
  comfyuiProgressTimer = setInterval(update, 1000);
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
    const limit = $("comfyui-lora-limit");
    if (limit && !draft["comfyui-lora-limit"]) limit.value = String(comfyuiSelectedLoras.length);
    renderComfyuiSelectedLoras();
  }
  COMFYUI_DRAFT_FIELD_IDS.forEach((id) => {
    if (!includeDynamicSelects && ["comfyui-model-select", "comfyui-sampler", "comfyui-scheduler", "comfyui-album-select"].includes(id)) {
      return;
    }
    setComfyuiFieldValue(id, draft[id]);
  });
}

function updateComfyuiRootPanelVisibility() {
  const panel = $("comfyui-root-model-panel");
  if (panel) panel.style.display = currentUser === "root" ? "" : "none";
}

function normalizeComfyuiLoraLimit() {
  const input = $("comfyui-lora-limit");
  const value = Math.max(0, Math.min(COMFYUI_MAX_LORAS, Math.floor(Number(input?.value || 0))));
  if (input) input.value = String(value);
  return value;
}

function renderComfyuiSelectedLoras() {
  const box = $("comfyui-selected-loras");
  if (!box) return;
  const limit = normalizeComfyuiLoraLimit();
  if (comfyuiSelectedLoras.length > limit) {
    comfyuiSelectedLoras = comfyuiSelectedLoras.slice(0, limit);
  }
  if (!comfyuiSelectedLoras.length) {
    box.innerHTML = '<span class="drive-card-sub">尚未選擇 LoRA</span>';
    return;
  }
  box.innerHTML = comfyuiSelectedLoras.map((item, index) => `
    <span class="comfyui-lora-chip" title="${sanitize(item.name)}">
      <span>${sanitize(item.name)}</span>
      <button type="button" data-comfyui-remove-lora="${index}" aria-label="移除 ${sanitize(item.name)}">×</button>
    </span>
  `).join("");
  box.querySelectorAll("[data-comfyui-remove-lora]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.getAttribute("data-comfyui-remove-lora"));
      comfyuiSelectedLoras.splice(index, 1);
      const limitInput = $("comfyui-lora-limit");
      if (limitInput) limitInput.value = String(comfyuiSelectedLoras.length);
      renderComfyuiSelectedLoras();
      writeComfyuiDraft();
    });
  });
}

function fillComfyuiLoraSelect(values = []) {
  comfyuiAvailableLoras = Array.isArray(values) ? values.filter(Boolean).map(String) : [];
  fillComfyuiSelect("comfyui-lora-select", comfyuiAvailableLoras, "");
}

function addSelectedComfyuiLora() {
  const limit = normalizeComfyuiLoraLimit();
  if (limit <= 0) {
    setComfyuiMessage("請先設定 LoRA 數量。", false);
    return;
  }
  if (comfyuiSelectedLoras.length >= limit) {
    setComfyuiMessage(`已達 LoRA 數量上限 ${limit} 個。`, false);
    return;
  }
  const name = $("comfyui-lora-select")?.value || "";
  if (!name) {
    setComfyuiMessage("請先選擇 LoRA。", false);
    return;
  }
  if (comfyuiSelectedLoras.some((item) => item.name === name)) {
    setComfyuiMessage("這個 LoRA 已經加入。", false);
    return;
  }
  comfyuiSelectedLoras.push({ name, strength_model: 1, strength_clip: 1 });
  renderComfyuiSelectedLoras();
  writeComfyuiDraft();
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
    if (id === "comfyui-lora-limit") {
      el.addEventListener("change", () => {
        renderComfyuiSelectedLoras();
      });
    }
    el.addEventListener("input", writeComfyuiDraft);
    el.addEventListener("change", writeComfyuiDraft);
  });
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
    const res = await apiFetch(API + "/comfyui/models", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (json.connection_mode) comfyuiConnectionMode = json.connection_mode;
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 連線失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "remote";
    fillComfyuiSelect("comfyui-model-select", json.models || [], "");
    fillComfyuiLoraSelect(json.loras || []);
    fillComfyuiSelect("comfyui-sampler", json.samplers || [], "euler");
    fillComfyuiSelect("comfyui-scheduler", json.schedulers || [], "normal");
    restoreComfyuiDraft();
    applyComfyuiRuntimeLimits(json);
    comfyuiModelsLoaded = true;
    loadComfyuiAlbums({ force: true }).catch(() => {});
    setComfyuiTabAvailability(true);
    if (status) status.textContent = `已連線 ${json.comfyui_url || "ComfyUI"}，模型 ${Number((json.models || []).length)} 個，LoRA ${Number((json.loras || []).length)} 個`;
  } catch (err) {
    comfyuiModelsLoaded = false;
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
    const res = await apiFetch(API + "/comfyui/status", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (json.connection_mode) comfyuiConnectionMode = json.connection_mode;
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 狀態檢測失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "remote";
    const available = !!json.available;
    applyComfyuiRuntimeLimits(json);
    const detail = available
      ? `已偵測 ${json.comfyui_url || "ComfyUI"}`
      : (json.msg || `找不到 ${json.comfyui_url || "ComfyUI"} 伺服器`);
    setComfyuiTabAvailability(available, detail);
    if (status) status.textContent = detail;
    if (!available) {
      comfyuiModelsLoaded = false;
      setComfyuiBusy(false);
      if (comfyuiConnectionMode !== "local" && currentModuleTab === "comfyui" && switchAway && typeof switchModuleTab === "function") {
        switchModuleTab("chat");
      }
    }
    return available;
  } catch (err) {
    const message = err.message || "ComfyUI 伺服器未連線";
    setComfyuiTabAvailability(false, message);
    comfyuiModelsLoaded = false;
    setComfyuiBusy(false);
    if (comfyuiConnectionMode !== "local" && currentModuleTab === "comfyui" && switchAway && typeof switchModuleTab === "function") {
      switchModuleTab("chat");
    }
    return false;
  }
}

async function startLocalComfyui() {
  const start = $("comfyui-start-btn");
  const status = $("comfyui-status");
  if (start) {
    start.disabled = true;
    start.textContent = "啟動中...";
  }
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
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await loadComfyuiModels();
  } catch (err) {
    setComfyuiMessage(err.message || "ComfyUI 啟動失敗", false);
    if (status) status.textContent = "ComfyUI 啟動失敗";
  } finally {
    if (start) {
      start.disabled = false;
      start.textContent = "啟動 ComfyUI";
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
  return {
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
    loras: comfyuiSelectedLoras.slice(0, normalizeComfyuiLoraLimit()),
    filename_prefix: "hackme_web"
  };
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
      run_count: runCount
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
    await preflightComfyuiBilling(payload, runCount, billingConfirmation);
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
      const res = await apiFetch(API + "/comfyui/generate", {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": getCsrfToken() || ""
        },
        body: JSON.stringify({
          ...payload,
          batch_size: 1,
          confirm_billing: billingConfirmation.required,
          timeout_seconds: COMFYUI_GENERATION_TIMEOUT_SECONDS
        })
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || !json.ok) throw new Error(json.msg || `第 ${requestIndex + 1} 張產圖失敗（HTTP ${res.status}）`);
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
      body: JSON.stringify({})
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

async function downloadComfyuiModelFromUrl() {
  if (currentUser !== "root") {
    setComfyuiMessage("只有 root 可以下載 ComfyUI 模型。", false);
    return;
  }
  const button = $("comfyui-model-download-btn");
  const status = $("comfyui-model-download-status");
  const url = ($("comfyui-model-download-url")?.value || "").trim();
  const type = $("comfyui-model-download-type")?.value || "checkpoint";
  const baseDir = ($("comfyui-model-base-dir")?.value || "").trim();
  if (!url) {
    if (status) status.textContent = "請輸入下載網址。";
    setComfyuiMessage("請輸入 checkpoint 或 LoRA 下載網址。", false);
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = "下載中...";
  }
  if (status) status.textContent = "正在下載模型，請不要關閉頁面...";
  try {
    await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/root/comfyui/download-model", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({ url, type, base_dir: baseDir })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `模型下載失敗（HTTP ${res.status}）`);
    const info = json.download || {};
    if (status) status.textContent = `${json.msg || "模型已下載"}（${formatDriveBytes(info.size_bytes || 0)}）`;
    setComfyuiMessage(json.msg || "模型已下載。請重新整理模型清單。", true);
    await loadComfyuiModels();
  } catch (err) {
    if (status) status.textContent = err.message || "模型下載失敗";
    setComfyuiMessage(err.message || "模型下載失敗", false);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "下載到 ComfyUI";
    }
  }
}
