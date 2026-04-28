'use strict';

let comfyuiCurrentImage = null;
let comfyuiModelsLoaded = false;

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
  const refresh = $("comfyui-refresh-btn");
  if (generate) {
    generate.disabled = !!busy;
    generate.textContent = busy ? "產生中..." : "產生圖片";
  }
  if (refresh) refresh.disabled = !!busy;
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
  if (save) save.disabled = !hasImage;
  if (discard) discard.disabled = !hasImage;
}

async function loadComfyuiModels() {
  if (!currentUser || !canAccessModule("comfyui")) return;
  const status = $("comfyui-status");
  if (status) status.textContent = "連線 ComfyUI 中...";
  setComfyuiMessage("");
  try {
    await fetchCsrfToken({ force: true });
    const res = await fetch(API + "/comfyui/models", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `ComfyUI 連線失敗（HTTP ${res.status}）`);
    fillComfyuiSelect("comfyui-model-select", json.models || [], "");
    fillComfyuiSelect("comfyui-sampler", json.samplers || [], "euler");
    fillComfyuiSelect("comfyui-scheduler", json.schedulers || [], "normal");
    comfyuiModelsLoaded = true;
    if (status) status.textContent = `已連線 ${json.comfyui_url || "ComfyUI"}，模型 ${Number((json.models || []).length)} 個`;
  } catch (err) {
    comfyuiModelsLoaded = false;
    if (status) status.textContent = "ComfyUI 未連線";
    setComfyuiMessage(err.message || "ComfyUI 模型讀取失敗", false);
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
    width: comfyuiNumberValue("comfyui-width", 512),
    height: comfyuiNumberValue("comfyui-height", 512),
    steps: comfyuiNumberValue("comfyui-steps", 20),
    cfg: comfyuiNumberValue("comfyui-cfg", 7),
    seed: $("comfyui-seed")?.value ? comfyuiNumberValue("comfyui-seed", 0) : undefined,
    sampler_name: $("comfyui-sampler")?.value || "euler",
    scheduler: $("comfyui-scheduler")?.value || "normal",
    filename_prefix: "hackme_web"
  };
}

async function generateComfyuiImage() {
  if (!comfyuiModelsLoaded) {
    await loadComfyuiModels();
  }
  const preview = $("comfyui-preview");
  const meta = $("comfyui-result-meta");
  if (preview) preview.innerHTML = `<div class="drive-empty">產生圖片中...</div>`;
  if (meta) meta.textContent = "";
  comfyuiCurrentImage = null;
  updateComfyuiResultButtons(false);
  setComfyuiBusy(true);
  setComfyuiMessage("");
  try {
    await fetchCsrfToken({ force: true });
    const res = await fetch(API + "/comfyui/generate", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify(comfyuiPayload())
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `產圖失敗（HTTP ${res.status}）`);
    comfyuiCurrentImage = json.image || null;
    if (!comfyuiCurrentImage?.data_url) throw new Error("ComfyUI 未回傳圖片");
    if (preview) {
      preview.innerHTML = `<img src="${comfyuiCurrentImage.data_url}" alt="ComfyUI generated image" />`;
    }
    if (meta) {
      meta.textContent = `model=${comfyuiCurrentImage.model || "-"} · seed=${comfyuiCurrentImage.seed ?? "-"} · ${formatDriveBytes(comfyuiCurrentImage.size_bytes || 0)}`;
    }
    const savePath = $("comfyui-save-path");
    if (savePath && !savePath.value.trim()) {
      const filename = comfyuiCurrentImage.image_ref?.filename || "comfyui.png";
      savePath.value = `/ComfyUI/${filename}`;
    }
    updateComfyuiResultButtons(true);
    setComfyuiMessage("圖片已產生，可選擇存到雲端硬碟或丟棄預覽。", true);
  } catch (err) {
    if (preview) preview.innerHTML = `<div class="drive-empty">${sanitize(err.message || "產圖失敗")}</div>`;
    setComfyuiMessage(err.message || "產圖失敗", false);
  } finally {
    setComfyuiBusy(false);
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
    const res = await fetch(API + "/comfyui/save", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken() || ""
      },
      body: JSON.stringify({
        image_ref: comfyuiCurrentImage.image_ref,
        virtual_path: $("comfyui-save-path")?.value || ""
      })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `儲存失敗（HTTP ${res.status}）`);
    setComfyuiMessage(`已存到雲端硬碟：${json.storage_file?.virtual_path || json.file?.file_id || ""}`, true);
    if (typeof loadDriveDashboard === "function") await loadDriveDashboard();
  } catch (err) {
    setComfyuiMessage(err.message || "儲存失敗", false);
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "存到雲端硬碟";
    }
  }
}

function discardComfyuiImage() {
  comfyuiCurrentImage = null;
  const preview = $("comfyui-preview");
  const meta = $("comfyui-result-meta");
  if (preview) preview.innerHTML = `<div class="drive-empty">已丟棄這次預覽</div>`;
  if (meta) meta.textContent = "";
  updateComfyuiResultButtons(false);
  setComfyuiMessage("這次圖片未存入雲端硬碟。", true);
}
