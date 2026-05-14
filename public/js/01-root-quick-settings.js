'use strict';

const ROOT_MODULE_QUICK_SETTINGS = {
  chat: {
    label: "聊天室",
    section: "features",
    fields: [
      { id: "s-feature-chat-enabled", label: "開放聊天室" },
      { id: "s-module-chat-min-role", label: "最低可用角色" },
      { id: "s-feature-attachments-enabled", label: "允許聊天附件" },
      { id: "s-feature-reports-enabled", label: "啟用檢舉審核" },
      { id: "s-feature-reports-notifications-enabled", label: "啟用檢舉 / 通知" },
    ],
  },
  announcements: {
    label: "公告",
    section: "features",
    fields: [
      { id: "s-feature-community-enabled", label: "開放公告 / 討論功能" },
      { id: "s-module-community-min-role", label: "公告與討論最低角色" },
      { id: "s-feature-attachments-enabled", label: "允許公告附件" },
      { id: "s-feature-reports-notifications-enabled", label: "啟用管理通知" },
    ],
  },
  community: {
    label: "討論區",
    section: "features",
    fields: [
      { id: "s-feature-community-enabled", label: "開放討論區" },
      { id: "s-module-community-min-role", label: "最低可用角色" },
      { id: "s-feature-forum-core-enabled", label: "新版論壇核心" },
      { id: "s-feature-attachments-enabled", label: "允許附件" },
      { id: "s-feature-reports-enabled", label: "啟用檢舉審核" },
    ],
  },
  drive: {
    label: "雲端硬碟",
    section: "drive",
    fields: [
      { id: "s-feature-privacy-uploads-enabled", label: "開放雲端硬碟 / E2EE" },
      { id: "s-feature-storage-albums-enabled", label: "開放相簿" },
      { id: "s-cloud-drive-global-capacity-limit-mb", label: "全站容量上限 MB" },
      { id: "s-storage-maintenance-auto-enabled", label: "每日自動維護" },
      { id: "s-storage-trash-retention-days", label: "回收筒保留天數" },
      { id: "s-cd-require-scan-before-download", label: "下載前要求掃描", save: "drivePolicy" },
      { id: "s-cd-block-unclean-downloads", label: "阻擋未掃描乾淨下載", save: "drivePolicy" },
    ],
  },
  albums: {
    label: "相簿",
    section: "drive",
    fields: [
      { id: "s-feature-storage-albums-enabled", label: "開放相簿" },
      { id: "s-feature-privacy-uploads-enabled", label: "開放雲端硬碟 / E2EE" },
      { id: "s-cloud-drive-global-capacity-limit-mb", label: "全站容量上限 MB" },
      { id: "s-storage-trash-retention-days", label: "回收筒保留天數" },
    ],
  },
  videos: {
    label: "影音",
    section: "billing",
    fields: [
      { id: "s-feature-videos-enabled", label: "開放影音分享" },
      { id: "s-module-videos-min-role", label: "最低可用角色" },
      { id: "s-video-tip-fee-percent", label: "投幣平台抽成 %" },
      { id: "s-video-tip-min-points", label: "投幣最低點數" },
      { id: "s-feature-privacy-uploads-enabled", label: "允許引用雲端檔案" },
    ],
  },
  games: {
    label: "遊戲區",
    section: "features",
    fields: [
      { id: "s-feature-games-enabled", label: "開放遊戲區" },
      { id: "s-module-games-min-role", label: "最低可用角色" },
    ],
  },
  jobs: {
    label: "任務中心",
    section: "system",
    note: "任務中心目前主要顯示後台任務狀態，沒有獨立功能開關；可從這裡快速調整通知靜音或前往完整設定。",
    fields: [
      { id: "s-notification-muted-types", label: "靜音通知類型" },
    ],
  },
  shares: {
    label: "分享管理",
    section: "drive",
    fields: [
      { id: "s-feature-privacy-uploads-enabled", label: "開放檔案分享來源" },
      { id: "s-feature-storage-albums-enabled", label: "開放相簿分享來源" },
      { id: "s-feature-videos-enabled", label: "開放影音分享來源" },
      { id: "s-cd-revoke-shares-on-suspension", label: "停權時撤銷分享", save: "drivePolicy" },
      { id: "s-cd-warn-high-risk-downloads", label: "高風險下載警告", save: "drivePolicy" },
    ],
  },
  comfyui: {
    label: "AI 產圖",
    section: "system",
    fields: [
      { id: "s-feature-comfyui-enabled", label: "開放 AI 產圖" },
      { id: "s-module-comfyui-min-role", label: "最低可用角色" },
      { id: "s-comfyui-connection-mode", label: "連線模式" },
      { id: "s-comfyui-remote-api-url", label: "遠端 API 位址", visibleWhen: { id: "s-comfyui-connection-mode", value: "remote" } },
      { id: "s-comfyui-base-dir", label: "本地 ComfyUI 資料夾", visibleWhen: { id: "s-comfyui-connection-mode", value: "local" } },
      { id: "s-comfyui-local-start-script", label: "本地啟動腳本", visibleWhen: { id: "s-comfyui-connection-mode", value: "local" } },
      { id: "s-comfyui-api-host", label: "本地 API Host", visibleWhen: { id: "s-comfyui-connection-mode", value: "local" } },
      { id: "s-comfyui-api-port", label: "本地 API Port", visibleWhen: { id: "s-comfyui-connection-mode", value: "local" } },
      { id: "s-comfyui-diffusers-model-repo", label: "Hugging Face Repo", visibleWhen: { id: "s-comfyui-connection-mode", value: "diffusers" } },
      { id: "s-comfyui-huggingface-api-token", label: "Hugging Face API Token", visibleWhen: { id: "s-comfyui-connection-mode", value: "diffusers" } },
      { id: "s-comfyui-huggingface-api-token-clear", label: "清除已儲存 HF Token", visibleWhen: { id: "s-comfyui-connection-mode", value: "diffusers" } },
      { id: "s-comfyui-diffusers-device", label: "Diffusers Device", visibleWhen: { id: "s-comfyui-connection-mode", value: "diffusers" } },
      { id: "s-comfyui-diffusers-dtype", label: "Diffusers dtype", visibleWhen: { id: "s-comfyui-connection-mode", value: "diffusers" } },
      { id: "s-comfyui-max-batch-size", label: "單次張數上限" },
      { id: "s-comfyui-default-width", label: "預設寬度" },
      { id: "s-comfyui-default-height", label: "預設高度" },
    ],
  },
  economy: {
    label: "積分系統",
    section: "features",
    fields: [
      { id: "s-feature-economy-enabled", label: "開放積分系統" },
      { id: "s-feature-trading-enabled", label: "開放積分交易所" },
    ],
  },
  trading: {
    label: "積分交易所",
    section: "trading",
    fields: [
      { id: "s-feature-economy-enabled", label: "開放積分系統" },
      { id: "s-feature-trading-enabled", label: "開放交易所" },
      { id: "root-trading-enabled", label: "啟用交易引擎", save: "trading" },
      { id: "root-trading-borrowing-enabled", label: "允許借貸交易", save: "trading" },
      { id: "root-trading-maintenance-percent", label: "維持保證金 %", save: "trading" },
      { id: "root-trading-price-source", label: "交易價格來源", save: "trading" },
      { id: "root-trading-price-fusion-min-provider-count", label: "融合最低來源數", save: "trading" },
      { id: "root-trading-price-fusion-trade-min-provider-count", label: "交易最低健康來源數", save: "trading" },
      { id: "root-trading-simulated-slippage-enabled", label: "啟用模擬滑價", save: "trading" },
      { id: "root-trading-bot-auto-enabled", label: "交易機器人自動掃描", save: "trading" },
      { id: "root-trading-bot-audit-enabled", label: "交易機器人定期稽核", save: "trading" },
    ],
  },
  appeals: {
    label: "申覆",
    section: "features",
    fields: [
      { id: "s-feature-appeals-enabled", label: "開放用戶申覆" },
      { id: "s-module-appeals-min-role", label: "最低可用角色" },
      { id: "s-feature-reports-notifications-enabled", label: "啟用審核通知" },
    ],
  },
  accounts: {
    label: "帳號管理",
    section: "features",
    fields: [
      { id: "s-feature-accounts-enabled", label: "開放帳號管理" },
      { id: "s-module-accounts-min-role", label: "最低可用角色" },
      { id: "s-feature-account-security-enabled", label: "帳號安全強化" },
      { id: "s-feature-identity-governance-enabled", label: "身份治理 / 會員等級" },
      { id: "s-feature-member-governance-enabled", label: "會員治理與投票" },
      { id: "s-feature-violation-center-enabled", label: "違規中心" },
      { id: "s-feature-reports-notifications-enabled", label: "管理通知" },
    ],
  },
  server: {
    label: "安全中心",
    section: "security",
    fields: [
      { id: "s-maintenance-mode", label: "維護模式" },
      { id: "s-audit-chain-enabled", label: "審計 hash chain" },
      { id: "s-ip-blocking-enabled", label: "錯誤登入鎖 IP" },
      { id: "s-login-violation-enabled", label: "錯誤登入寫入違規" },
      { id: "s-rate-limit-violation-enabled", label: "速率限制寫入違規" },
      { id: "s-root-ip-whitelist-enabled", label: "root IP 白名單" },
      { id: "s-root-ip-whitelist", label: "root IP 白名單內容" },
      { id: "s-server-ssl-enabled", label: "啟用 HTTPS" },
    ],
  },
};

function rootModuleQuickConfig(tab = currentModuleTab) {
  return ROOT_MODULE_QUICK_SETTINGS[tab] || null;
}

function rootModuleQuickButtonLabel(tab) {
  const label = rootModuleQuickConfig(tab)?.label || tab || "目前頁面";
  return `${label}快速設定`;
}

function ensureRootModuleSettingsButtons() {
  document.querySelectorAll(".module-section[id^='module-']").forEach((section) => {
    if (section.querySelector(":scope > .root-module-settings-btn")) return;
    const tab = section.id.replace(/^module-/, "");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "root-module-settings-btn";
    button.dataset.rootModuleSettings = tab;
    button.setAttribute("aria-label", rootModuleQuickButtonLabel(tab));
    button.title = rootModuleQuickButtonLabel(tab);
    button.textContent = "⚙";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openRootModuleSettings(tab);
    });
    section.prepend(button);
  });
}

function syncRootModuleSettingsButtons() {
  ensureRootModuleSettingsButtons();
  const rootMode = currentUser === "root";
  document.querySelectorAll(".root-module-settings-btn").forEach((button) => {
    const section = button.closest(".module-section");
    const tab = button.dataset.rootModuleSettings || "";
    const visible = rootMode && !!section?.classList.contains("active") && !!rootModuleQuickConfig(tab);
    button.classList.toggle("show", visible);
    button.hidden = !visible;
  });
}

function ensureRootModuleSettingsModal() {
  let overlay = $("root-module-settings-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "root-module-settings-overlay";
  overlay.className = "user-edit-overlay root-module-settings-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "root-module-settings-title");
  overlay.innerHTML = `
    <div class="user-edit-modal root-module-settings-modal">
      <div class="drive-card-heading compact-heading">
        <div>
          <div class="mini-title" id="root-module-settings-title">頁面設定</div>
          <div class="drive-card-sub" id="root-module-settings-subtitle">root 快速設定</div>
        </div>
        <button type="button" class="btn btn-sm" id="root-module-settings-close">關閉</button>
      </div>
      <div class="root-module-settings-note" id="root-module-settings-note"></div>
      <div class="settings-option-grid root-module-settings-grid" id="root-module-settings-fields"></div>
      <div id="root-module-settings-msg" class="msg"></div>
      <div class="edit-user-actions">
        <button type="button" id="root-module-settings-full" class="btn">完整設定</button>
        <button type="button" id="root-module-settings-save" class="btn btn-primary">儲存</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  $("root-module-settings-close")?.addEventListener("click", closeRootModuleSettings);
  $("root-module-settings-full")?.addEventListener("click", () => openRootModuleFullSettings());
  $("root-module-settings-save")?.addEventListener("click", saveRootModuleSettings);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeRootModuleSettings();
  });
  return overlay;
}

function rootModuleProxyId(sourceId) {
  return `root-module-setting-${sourceId}`;
}

function rootModuleFieldValue(source) {
  if (!source) return "";
  if (source.type === "checkbox") return !!source.checked;
  return source.value ?? "";
}

function rootModuleFieldVisible(field) {
  if (!field?.visibleWhen) return true;
  const source = $(rootModuleProxyId(field.visibleWhen.id)) || $(field.visibleWhen.id);
  if (!source) return true;
  const values = Array.isArray(field.visibleWhen.value) ? field.visibleWhen.value : [field.visibleWhen.value];
  return values.includes(rootModuleFieldValue(source));
}

function updateRootModuleConditionalFields() {
  const config = rootModuleQuickConfig($("root-module-settings-overlay")?.dataset.moduleTab || currentModuleTab);
  if (!config) return;
  config.fields.forEach((field) => {
    const row = document.querySelector(`[data-root-module-field-row="${field.id}"]`);
    if (row) row.style.display = rootModuleFieldVisible(field) ? "" : "none";
  });
}

function rootModuleRenderSettingField(field) {
  const source = $(field.id);
  if (!source) return "";
  const proxyId = rootModuleProxyId(field.id);
  const label = sanitize(field.label || source.closest(".field")?.querySelector("label")?.textContent || field.id);
  const hint = field.hint ? `<div class="field-hint">${sanitize(field.hint)}</div>` : "";
  const sourceTag = source.tagName.toLowerCase();
  if (source.type === "checkbox") {
    return `
      <div class="field root-module-setting-field" data-root-module-field-row="${sanitize(field.id)}">
        <label><input type="checkbox" id="${sanitize(proxyId)}" data-root-setting-source="${sanitize(field.id)}" ${source.checked ? "checked" : ""} /> ${label}</label>
        ${hint}
      </div>
    `;
  }
  if (sourceTag === "select") {
    const options = Array.from(source.options || []).map((option) => `
      <option value="${sanitize(option.value)}" ${option.selected ? "selected" : ""}>${sanitize(option.textContent || option.value)}</option>
    `).join("");
    return `
      <div class="field root-module-setting-field" data-root-module-field-row="${sanitize(field.id)}">
        <label for="${sanitize(proxyId)}">${label}</label>
        <select id="${sanitize(proxyId)}" data-root-setting-source="${sanitize(field.id)}">${options}</select>
        ${hint}
      </div>
    `;
  }
  if (sourceTag === "textarea") {
    return `
      <div class="field root-module-setting-field" data-root-module-field-row="${sanitize(field.id)}">
        <label for="${sanitize(proxyId)}">${label}</label>
        <textarea id="${sanitize(proxyId)}" data-root-setting-source="${sanitize(field.id)}" rows="${sanitize(source.getAttribute("rows") || "3")}">${sanitize(source.value || "")}</textarea>
        ${hint}
      </div>
    `;
  }
  const attrs = ["min", "max", "step", "placeholder", "autocomplete"].map((name) => {
    const value = source.getAttribute(name);
    return value == null ? "" : ` ${name}="${sanitize(value)}"`;
  }).join("");
  const type = source.type || "text";
  return `
    <div class="field root-module-setting-field" data-root-module-field-row="${sanitize(field.id)}">
      <label for="${sanitize(proxyId)}">${label}</label>
      <input type="${sanitize(type)}" id="${sanitize(proxyId)}" data-root-setting-source="${sanitize(field.id)}" value="${sanitize(source.value || "")}"${attrs} />
      ${hint}
    </div>
  `;
}

function renderRootModuleSettingsFields(tab) {
  const config = rootModuleQuickConfig(tab);
  const fieldsWrap = $("root-module-settings-fields");
  const note = $("root-module-settings-note");
  if (!fieldsWrap || !config) return;
  const renderedFields = (config.fields || []).map(rootModuleRenderSettingField).filter(Boolean);
  note.textContent = config.note || "只顯示此頁最常用的 root 設定；完整低頻設定仍保留在安全中心。";
  fieldsWrap.innerHTML = renderedFields.length
    ? renderedFields.join("")
    : `<div class="drive-empty">此頁目前沒有專用快速設定，請使用完整設定。</div>`;
  fieldsWrap.querySelectorAll("input, select, textarea").forEach((el) => {
    el.addEventListener("input", updateRootModuleConditionalFields);
    el.addEventListener("change", updateRootModuleConditionalFields);
  });
  updateRootModuleConditionalFields();
}

async function preloadRootModuleSettings(config) {
  const saves = new Set((config.fields || []).map((field) => field.save || "settings"));
  if (saves.has("settings") && typeof loadSettings === "function") await loadSettings();
  if (saves.has("drivePolicy") && typeof loadCloudDriveAdminPolicy === "function") await loadCloudDriveAdminPolicy();
  if (saves.has("trading") && typeof loadRootTradingSettings === "function") await loadRootTradingSettings();
}

async function openRootModuleSettings(tab = currentModuleTab) {
  if (currentUser !== "root") return;
  const config = rootModuleQuickConfig(tab);
  if (!config) return;
  const overlay = ensureRootModuleSettingsModal();
  overlay.dataset.moduleTab = tab;
  $("root-module-settings-title").textContent = `${config.label}設定`;
  $("root-module-settings-subtitle").textContent = "root 快速設定";
  $("root-module-settings-fields").innerHTML = `<div class="drive-empty">設定讀取中...</div>`;
  const msg = $("root-module-settings-msg");
  if (msg) msg.className = "msg";
  overlay.classList.add("show");
  document.body.classList.add("modal-open");
  try {
    await preloadRootModuleSettings(config);
    renderRootModuleSettingsFields(tab);
    const firstInput = overlay.querySelector("input, select, textarea, button");
    firstInput?.focus?.();
  } catch (err) {
    if (msg) {
      msg.textContent = err?.message || "設定讀取失敗";
      msg.className = "msg show err";
    }
  }
}

function closeRootModuleSettings() {
  const overlay = $("root-module-settings-overlay");
  if (!overlay) return;
  overlay.classList.remove("show");
  document.body.classList.remove("modal-open");
}

function syncRootModuleProxyValues() {
  const overlay = $("root-module-settings-overlay");
  if (!overlay) return;
  overlay.querySelectorAll("[data-root-setting-source]").forEach((proxy) => {
    const source = $(proxy.dataset.rootSettingSource || "");
    if (!source) return;
    if (source.type === "checkbox") source.checked = !!proxy.checked;
    else source.value = proxy.value;
  });
  if (typeof updateComfyuiConnectionModeFields === "function") updateComfyuiConnectionModeFields();
}

async function saveRootModuleSettings() {
  const overlay = $("root-module-settings-overlay");
  const config = rootModuleQuickConfig(overlay?.dataset.moduleTab || currentModuleTab);
  const msg = $("root-module-settings-msg");
  const saveBtn = $("root-module-settings-save");
  if (!config || !overlay) return;
  const saves = new Set((config.fields || []).map((field) => field.save || "settings"));
  syncRootModuleProxyValues();
  if (saveBtn) saveBtn.disabled = true;
  if (msg) {
    msg.textContent = "儲存中...";
    msg.className = "msg show info";
  }
  try {
    if (saves.has("drivePolicy") && typeof saveCloudDriveAdminPolicy === "function") await saveCloudDriveAdminPolicy();
    if (saves.has("trading") && typeof saveRootTradingSettings === "function") await saveRootTradingSettings();
    if (saves.has("settings") && typeof saveSettings === "function") await saveSettings();
    if (msg) {
      msg.textContent = `${config.label}設定已送出`;
      msg.className = "msg show ok";
      scheduleInlineMessageClear(msg, msg.textContent, true);
    }
    syncRootModuleSettingsButtons();
  } catch (err) {
    if (msg) {
      msg.textContent = err?.message || "儲存失敗";
      msg.className = "msg show err";
    }
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

function openRootModuleFullSettings(tab = $("root-module-settings-overlay")?.dataset.moduleTab || currentModuleTab) {
  const config = rootModuleQuickConfig(tab);
  closeRootModuleSettings();
  if (typeof switchModuleTab === "function") switchModuleTab("server");
  if (typeof switchServerTab === "function") switchServerTab("settings");
  if (config?.section && typeof switchSettingsSection === "function") switchSettingsSection(config.section);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", syncRootModuleSettingsButtons);
} else {
  syncRootModuleSettingsButtons();
}
