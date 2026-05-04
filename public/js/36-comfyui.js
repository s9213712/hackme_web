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
const COMFYUI_GENERATION_TIMEOUT_SECONDS = 900;
const COMFYUI_MAX_LORAS = 8;
const COMFYUI_LORA_EXTRA_PRICE = 1;
const COMFYUI_VAE_BUILTIN = "__checkpoint_builtin__";
const COMFYUI_DRAFT_FIELD_IDS = [
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
  "comfyui-save-path",
  "comfyui-album-select",
  "comfyui-share-title",
  "comfyui-share-note",
];

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
    if (!includeDynamicSelects && ["comfyui-model-select", "comfyui-vae-select", "comfyui-sampler", "comfyui-scheduler", "comfyui-album-select"].includes(id)) {
      return;
    }
    setComfyuiFieldValue(id, draft[id]);
  });
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
      ? "目前是本地模式，可在這裡管理 Civitai 模型下載。"
      : "目前是雲端 / 遠端模式，所以這個區塊只保留說明。若要用 Civitai 下載模型到本站的本地 ComfyUI，請先把 backend 切回本地模式。";
  }
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
      comfyuiSelectedLoras.splice(index, 1);
      renderComfyuiSelectedLoras();
      writeComfyuiDraft();
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
    .concat(comfyuiAvailableLoras.map((value) => `<option value="${sanitize(value)}">${sanitize(value)}</option>`));
  select.innerHTML = options.join("");
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

function insertComfyuiEmbeddingToken(name) {
  const prompt = $("comfyui-prompt");
  const cleanName = String(name || "").trim();
  if (!prompt || !cleanName) return;
  const embeddingTag = `<embeddings:${cleanName}>`;
  if ((prompt.value || "").includes(embeddingTag)) {
    setComfyuiMessage("這個 Embedding 已經在提示詞裡。", false);
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
  setComfyuiMessage(`已把 ${cleanName} 插入提示詞。`, true);
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

function addSelectedComfyuiLora() {
  if (comfyuiSelectedLoras.length >= COMFYUI_MAX_LORAS) {
    setComfyuiMessage(`已達 LoRA 數量上限 ${COMFYUI_MAX_LORAS} 個。`, false);
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
  const detail = comfyuiLoraDetails?.[name] || {};
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
    const res = await apiFetch(API + "/comfyui/models" + comfyuiRequestQuery(), {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (json.connection_mode) comfyuiConnectionMode = json.connection_mode;
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 連線失敗（HTTP ${res.status}）`);
    comfyuiConnectionMode = json.connection_mode || comfyuiConnectionMode || "remote";
    fillComfyuiSelect("comfyui-model-select", json.models || [], "");
    fillComfyuiLoraSelect(json.loras || []);
    comfyuiLoraDetails = json.lora_details && typeof json.lora_details === "object" ? json.lora_details : {};
    fillComfyuiVaeSelect(json.vaes || []);
    renderComfyuiEmbeddingShortcuts(json.embeddings || []);
    fillComfyuiSelect("comfyui-sampler", json.samplers || [], "euler");
    fillComfyuiSelect("comfyui-scheduler", json.schedulers || [], "normal");
    restoreComfyuiDraft();
    applyComfyuiRuntimeLimits(json);
    comfyuiModelsLoaded = true;
    loadComfyuiAlbums({ force: true }).catch(() => {});
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
    vae: vae === COMFYUI_VAE_BUILTIN ? "" : vae,
    loras: comfyuiSelectedLoras.slice(0, COMFYUI_MAX_LORAS),
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
          "Content-Type": "application/json",
          "X-CSRF-Token": getCsrfToken() || ""
        },
        body: JSON.stringify({
          ...payload,
          batch_size: 1,
          async_progress: true,
          confirm_billing: billingConfirmation.required,
          timeout_seconds: COMFYUI_GENERATION_TIMEOUT_SECONDS,
          ...comfyuiRequestPayloadExtras()
        })
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
