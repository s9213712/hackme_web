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

