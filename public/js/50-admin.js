function switchServerTab(tab) {
  currentServerTab = tab;
  ["health", "settings", "env"].forEach((name) => {
    const sec = $("sec-server-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-server-health", "tab-server-settings", "tab-server-env"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-server-" + tab);
  });
  if (tab === "health") loadServerHealth();
  if (tab === "settings") loadSettings();
  if (tab === "env") loadServerEnv();
}

function switchSettingsSection(tab) {
  currentSettingsSection = tab;
  ["security", "features", "appearance", "system"].forEach((name) => {
    const sec = $("sec-settings-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-settings-security", "tab-settings-features", "tab-settings-appearance", "tab-settings-system"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-settings-" + tab);
  });
}

function switchModuleTab(tab) {
  const canAccessAccounts = canAccessModule("accounts");
  const canAccessServer = currentRole === "super_admin";
  const canAccessAppeals = currentRole !== "super_admin" && canAccessModule("appeals");
  const canAccessCommunity = !!currentUser && canAccessModule("community");
  const canAccessChat = !!currentUser && canAccessModule("chat");
  const canAccessDrive = !!currentUser && canAccessModule("privacy_uploads");

  let normTab = tab;
  if (tab === "chat" && !canAccessChat) normTab = canAccessCommunity ? "community" : (canAccessDrive ? "drive" : (canAccessAppeals ? "appeals" : (canAccessAccounts ? "accounts" : "chat")));
  if (tab === "community" && !canAccessCommunity) normTab = canAccessChat ? "chat" : (canAccessDrive ? "drive" : (canAccessAppeals ? "appeals" : (canAccessAccounts ? "accounts" : "chat")));
  if (tab === "drive" && !canAccessDrive) normTab = canAccessChat ? "chat" : (canAccessCommunity ? "community" : (canAccessAppeals ? "appeals" : "accounts"));
  if (tab === "accounts" && !canAccessAccounts) normTab = canAccessChat ? "chat" : (canAccessCommunity ? "community" : (canAccessDrive ? "drive" : "appeals"));
  if (tab === "server" && !canAccessServer) normTab = canAccessAccounts ? "accounts" : (canAccessChat ? "chat" : (canAccessCommunity ? "community" : (canAccessDrive ? "drive" : "appeals")));
  if (tab === "appeals" && !canAccessAppeals) normTab = canAccessChat ? "chat" : (canAccessCommunity ? "community" : (canAccessDrive ? "drive" : "accounts"));

  currentModuleTab = normTab;
  const modChat = $("module-chat");
  const modCommunity = $("module-community");
  const modDrive = $("module-drive");
  const modAccounts = $("module-accounts");
  const modServer = $("module-server");
  const modAppeals = $("module-appeals");
  const mChat = $("tab-module-chat");
  const mCommunity = $("tab-module-community");
  const mDrive = $("tab-module-drive");
  const mAccounts = $("tab-module-accounts");
  const mServer = $("tab-module-server");
  const mAppeals = $("tab-module-appeals");

  if (modChat) modChat.classList.toggle("active", normTab === "chat");
  if (modCommunity) modCommunity.classList.toggle("active", normTab === "community");
  if (modDrive) modDrive.classList.toggle("active", normTab === "drive");
  if (modAccounts) modAccounts.classList.toggle("active", normTab === "accounts");
  if (modServer) modServer.classList.toggle("active", normTab === "server");
  if (modAppeals) modAppeals.classList.toggle("active", normTab === "appeals");
  if (mChat) mChat.classList.toggle("active", normTab === "chat");
  if (mCommunity) mCommunity.classList.toggle("active", normTab === "community");
  if (mDrive) mDrive.classList.toggle("active", normTab === "drive");
  if (mAccounts) mAccounts.classList.toggle("active", normTab === "accounts");
  if (mServer) mServer.classList.toggle("active", normTab === "server");
  if (mAppeals) mAppeals.classList.toggle("active", normTab === "appeals");

  if (normTab === "community" && canAccessCommunity) {
    loadCommunityHome();
  }
  if (normTab === "server" && canAccessServer) {
    switchServerTab(currentServerTab || "health");
  }
  if (normTab === "drive" && canAccessDrive) {
    loadDriveDashboard();
  }
  if (normTab === "appeals" && canAccessAppeals) {
    loadUserAppeals();
  }
  if (normTab === "accounts" && canAccessAccounts && currentAdminTab) {
    if (!$("sec-" + currentAdminTab)) switchAdminTab("users");
  }
}

function switchAdminTab(tab) {
  currentAdminTab = tab;
  ["users","audit","violations","appeals","reports"].forEach(t => {
    const sec = $("sec-" + t);
    if (sec) sec.classList.toggle("active", t === tab);
  });
  ["tab-users","tab-audit","tab-violations","tab-appeals","tab-reports"].forEach(id => {
    const btn = $(id);
    if (btn) btn.classList.toggle("active", id === "tab-" + tab);
  });
  if (tab === "audit") loadAudit(0);
  if (tab === "violations") loadViolations(0);
  if (tab === "appeals") loadAdminAppeals(1, adminAppealStatus);
  if (tab === "reports") loadAdminReports(0, adminReportStatus);
}

// ── Audit log ───────────────────────────────────────────────
let auditPage = 0;
const AUDIT_PAGE_SIZE = 20;

async function loadAudit(page) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/audit?page=" + page, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  auditPage = page;
  $("audit-total").textContent = json.total || 0;
  const integrity = json.integrity;
  const integEl = $("audit-integrity");
  if (integEl) {
    if (integrity && integrity.enabled === false) {
      integEl.textContent = "審計鏈檢查已停用";
      integEl.style.color = "var(--muted)";
    } else {
      const chainOk = integrity && integrity.ok;
      integEl.textContent = chainOk ? "🔗 鏈完整" : "⚠️ 鏈已斷！";
      integEl.style.color = chainOk ? "#4caf50" : "#ff4f6d";
    }
  }
  if (currentRole === "super_admin" && integrity && integrity.enabled !== false && integrity.ok === false && integrity.broken_at) {
    alert(`審計紀錄異常：hash chain 在 #${integrity.broken_at} 斷裂，請立即檢查。`);
  }
  const container = $("audit-entries");
  if (!container) return;
  if (!json.entries || json.entries.length === 0) {
    container.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>暫無審計記錄</p>";
    return;
  }
  container.innerHTML = json.entries.map(e => {
    const isObj = typeof e === "object";
    const ts = isObj ? e.timestamp || "" : "";
    const action = isObj ? e.action || "" : e;
    const actor = isObj ? e.actor || "" : "";
    const detail = isObj && e.details ? (typeof e.details === "string" ? e.details : JSON.stringify(e.details)) : "";
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    const isBroken = integrity && integrity.broken_at && Number(e.id) === Number(integrity.broken_at);
    const isFailure = isObj && e.success === false;
    const rowStyle = isBroken
      ? "background:rgba(255,79,109,.22);border:1px solid rgba(255,79,109,.45);"
      : isFailure
        ? "background:rgba(255,79,109,.08);"
        : "";
    const badge = isBroken ? `<span style="color:#ff4f6d;font-weight:bold;">審計異常</span> ` : "";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;${rowStyle}">
      <span style="color:#888;">${ts}</span> ${chain}
      ${badge}
      <span style="color:#e0e0e0;">${sanitize(action)}</span>
      ${actor ? `<span style="color:#82b1ff;"> by ${sanitize(actor)}</span>` : ""}
      ${detail ? `<span style="color:#888;font-size:.68rem;"> ${sanitize(detail)}</span>` : ""}
    </div>`;
  }).join("");
  $("audit-prev").disabled = page === 0;
  $("audit-next").disabled = (page + 1) * AUDIT_PAGE_SIZE >= (json.total || 0);
}

// ── Violations ──────────────────────────────────────────────
let violationsPage = 0;
const VIOLATIONS_PAGE_SIZE = 20;
let violationTargetUser = null;

async function loadViolations(page, username) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const url = username
    ? API + "/admin/violations?page=" + page + "&username=" + encodeURIComponent(username)
    : API + "/admin/violations?page=" + page;
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  violationsPage = page;
  $("violations-total").textContent = json.total || 0;
  const integEl = $("violations-integrity");
  if (integEl) {
    const chainOk = json.integrity === true || (json.integrity && json.integrity.ok === true);
    const chainBad = json.integrity === false || (json.integrity && json.integrity.ok === false);
    integEl.textContent = chainOk ? "🔗 鏈完整" : chainBad ? "⚠️ 鏈已斷！" : "";
    integEl.style.color = chainOk ? "#4caf50" : chainBad ? "#ff4f6d" : "var(--muted)";
  }

  // User pills
  const usersEl = $("violation-users");
  if (usersEl) {
    const selUser = username || violationTargetUser;
    const pillsWrap = document.createElement("div");
    pillsWrap.style.display = "flex";
    pillsWrap.style.flexWrap = "wrap";
    pillsWrap.style.gap = ".25rem";
    pillsWrap.style.alignItems = "center";

    const allBtn = document.createElement("button");
    allBtn.className = "btn";
    allBtn.style.fontSize = ".72rem";
    allBtn.style.padding = ".2rem .5rem";
    allBtn.style.margin = ".1rem";
    allBtn.textContent = "全部";
    allBtn.addEventListener("click", () => loadViolations(0, null));
    pillsWrap.appendChild(allBtn);

    (json.users || []).forEach(u => {
      const btn = document.createElement("button");
      btn.className = "btn";
      if (u.username === selUser) btn.classList.add("btn-primary");
      btn.style.fontSize = ".72rem";
      btn.style.padding = ".2rem .5rem";
      btn.style.margin = ".1rem";
      btn.textContent = `${sanitize(u.username)} (${u.violation_count})`;
      btn.addEventListener("click", () => loadViolations(0, u.username));
      pillsWrap.appendChild(btn);
    });

    usersEl.innerHTML = "";
    usersEl.appendChild(pillsWrap);
    violationTargetUser = username || null;
  }

  const container = $("violation-entries");
  if (!container) return;
  if (!json.entries || json.entries.length === 0) {
    container.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>暫無違規記錄</p>";
    return;
  }
  container.innerHTML = json.entries.map(e => {
    const isObj = typeof e === "object";
    const ts = isObj ? e.timestamp || "" : "";
    const reason = isObj ? e.reason || "" : String(e);
    const username = isObj ? e.username || "" : "";
    const actor = isObj ? e.actor || "" : "";
    const points = isObj ? e.points || 0 : 0;
    const chain = isObj && e._chain_hash ? `<span style="color:#4caf50;">█</span>` : "·";
    return `<div style="border-bottom:1px solid #222;padding:.35rem .25rem;word-break:break-all;">
      <span style="color:#888;">${ts}</span> ${chain}
      ${username ? `<span style="color:#e0e0e0;">${sanitize(username)}</span>` : ""}
      <span style="color:#ff8a80;">${sanitize(reason)}</span>
      ${points ? `<span style="color:#bbb;"> +${points}</span>` : ""}
      ${actor ? `<span style="color:#82b1ff;"> by ${sanitize(actor)}</span>` : ""}
    </div>`;
  }).join("");
  $("violations-prev").disabled = page === 0;
  $("violations-next").disabled = (page + 1) * VIOLATIONS_PAGE_SIZE >= (json.total || 0);
}

async function addViolation(userId) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const reason = prompt("輸入違規原因：");
  if (!reason) return;
  const res = await fetch(API + "/admin/users/" + userId + "/violation", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ reason })
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadViolations(0, violationTargetUser);
    loadUsers();
  } else {
    alert(json.msg || "新增違規失敗");
  }
}

async function resetViolations(userId) {
  if (!confirm("確定要歸零該用戶違規次數？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/users/" + userId + "/reset-violations", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    loadViolations(0, violationTargetUser);
    loadUsers();
  } else {
    alert(json.msg || "歸零失敗");
  }
}

// ── Settings & restart ───────────────────────────────────────
async function loadSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/settings", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  const s = json.settings || {};
  const bind = json.server_bind || {};
  if ($("s-maintenance-mode")) $("s-maintenance-mode").checked = !!s.maintenance_mode;
  if ($("s-audit-chain-enabled")) $("s-audit-chain-enabled").checked = !!s.audit_chain_enabled;
  if ($("s-ip-blocking-enabled")) $("s-ip-blocking-enabled").checked = !!s.ip_blocking_enabled;
  if ($("s-allow-register")) $("s-allow-register").checked = !!s.allow_register;
  if ($("s-require-email")) $("s-require-email").checked = !!s.require_email_verification;
  if ($("s-max-fail")) $("s-max-fail").value = s.max_login_failures || 5;
  if ($("s-block-dur")) $("s-block-dur").value = s.block_duration_minutes || 30;
  if ($("s-session-ttl")) $("s-session-ttl").value = s.session_ttl_hours || 24;
  if ($("s-server-listen-host")) $("s-server-listen-host").value = s.server_listen_host || "";
  if ($("s-server-listen-port")) $("s-server-listen-port").value = s.server_listen_port || "";
  const bindStatus = $("server-bind-status");
  if (bindStatus) {
    const restartText = bind.restart_required ? "需重啟才會套用新 listen 設定" : "目前執行中的 listen 設定已一致";
    bindStatus.textContent = `目前 ${bind.current_host || bind.host || "0.0.0.0"}:${bind.current_port || bind.port || 5000}，下次啟動 ${bind.host || "0.0.0.0"}:${bind.port || 5000}。${restartText}`;
    bindStatus.style.color = bind.restart_required ? "#ffb74d" : "var(--muted)";
  }
  if ($("s-module-chat-min-role")) $("s-module-chat-min-role").value = s.module_chat_min_role || "user";
  if ($("s-module-community-min-role")) $("s-module-community-min-role").value = s.module_community_min_role || "user";
  if ($("s-module-appeals-min-role")) $("s-module-appeals-min-role").value = s.module_appeals_min_role || "user";
  if ($("s-module-accounts-min-role")) $("s-module-accounts-min-role").value = s.module_accounts_min_role || "manager";
  if ($("s-site-bg")) $("s-site-bg").value = s.site_bg || "#0f0f1a";
  if ($("s-site-surface")) $("s-site-surface").value = s.site_surface || "#1a1a2e";
  if ($("s-site-accent")) $("s-site-accent").value = s.site_accent || "#6c63ff";
  if ($("s-site-accent2")) $("s-site-accent2").value = s.site_accent2 || "#00d4aa";
  if ($("s-site-text")) $("s-site-text").value = s.site_text || "#e0e0f0";
  if ($("s-site-muted")) $("s-site-muted").value = s.site_muted || "#8888aa";
  if ($("s-site-layout-mode")) $("s-site-layout-mode").value = s.site_layout_mode || "centered";
  if ($("s-site-density")) $("s-site-density").value = s.site_density || "comfortable";
  FEATURE_SETTING_KEYS.forEach((key) => {
    const el = $(featureSettingInputId(key));
    if (el) el.checked = !!s[key];
  });
  applySiteConfig(s);
  switchSettingsSection(currentSettingsSection || "security");
}

const FEATURE_SETTING_KEYS = [
  "feature_chat_enabled",
  "feature_community_enabled",
  "feature_accounts_enabled",
  "feature_appeals_enabled",
  "feature_audit_log_enabled",
  "feature_violation_center_enabled",
  "feature_reports_enabled",
  "feature_system_health_enabled",
  "feature_identity_governance_enabled",
  "feature_account_security_enabled",
  "feature_member_governance_enabled",
  "feature_server_modes_enabled",
  "feature_snapshot_restore_enabled",
  "feature_health_center_enabled",
  "feature_forum_core_enabled",
  "feature_ui_rebuild_enabled",
  "feature_reports_notifications_enabled",
  "feature_dm_enabled",
  "feature_attachments_enabled",
  "feature_storage_albums_enabled",
  "feature_personalization_enabled",
  "feature_social_search_enabled",
  "feature_advanced_security_enabled",
  "feature_privacy_uploads_enabled"
];

function featureSettingInputId(key) {
  return "s-" + key.replaceAll("_", "-");
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

async function loadServerHealth() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/health", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const summary = $("server-health-summary");
  const details = $("server-health-details");
  if (!summary || !details) return;
  if (!json.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "健康度讀取失敗")}</div>`;
    details.textContent = "";
    return;
  }
  const c = json.counts || {};
  const s = json.storage || {};
  const auditOk = json.audit_integrity && json.audit_integrity.ok;
  const auditEnabled = !(json.audit_integrity && json.audit_integrity.enabled === false);
  const cards = [
    ["整體狀態", json.status === "ok" ? "正常" : "異常", json.status === "ok" ? "#4caf50" : "#ff4f6d"],
    ["維護模式", json.maintenance_mode ? "啟用" : "關閉", json.maintenance_mode ? "#ff4f6d" : "#4caf50"],
    ["審計鏈", auditEnabled ? (auditOk ? "完整" : "異常") : "停用", auditEnabled ? (auditOk ? "#4caf50" : "#ff4f6d") : "#9e9e9e"],
    ["待審檢舉", String(c.pending_reports || 0), (c.pending_reports || 0) ? "#ffb74d" : "#4caf50"],
    ["待審申覆", String(c.pending_appeals || 0), (c.pending_appeals || 0) ? "#ffb74d" : "#4caf50"],
    ["活躍 Session", String(c.active_sessions || 0), "#82b1ff"],
    ["聊天訊息", String(c.chat_messages || 0), "#82b1ff"],
    ["資料庫大小", formatBytes(s.database_bytes), "#82b1ff"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1.05rem;color:${color};font-weight:700;margin-top:.2rem;">${sanitize(value)}</div>
    </div>
  `).join("");
  details.innerHTML = `
    使用者：${c.active_users || 0}/${c.users_total || 0} active ·
    違規紀錄：${c.violations_total || 0} ·
    審計紀錄：${c.audit_entries || 0} ·
    聊天檔案：${s.chat_files || 0} 個 / ${formatBytes(s.chat_bytes)} ·
    ${json.audit_integrity && json.audit_integrity.details ? sanitize(json.audit_integrity.details) : ""}
  `;
  const repairBtn = $("integrity-repair-btn");
  if (repairBtn) {
    repairBtn.disabled = currentUser !== "root";
  }
}

async function repairIntegrityChains() {
  if (currentUser !== "root") {
    alert("只有 root 可處理鏈異常");
    return;
  }
  if (!confirm("確定要重新封鏈並解除維護模式？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/integrity/repair", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "鏈異常已處理" : "處理失敗"));
  await loadServerHealth();
  if (currentAdminTab === "audit") await loadAudit(auditPage);
  if (currentAdminTab === "violations") await loadViolations(violationsPage, violationTargetUser);
}

async function saveSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    maintenance_mode: !!$("s-maintenance-mode")?.checked,
    audit_chain_enabled: !!$("s-audit-chain-enabled")?.checked,
    ip_blocking_enabled: !!$("s-ip-blocking-enabled")?.checked,
    allow_register: !!$("s-allow-register")?.checked,
    require_email_verification: !!$("s-require-email")?.checked,
    max_login_failures: parseInt($("s-max-fail")?.value || "5"),
    block_duration_minutes: parseInt($("s-block-dur")?.value || "30"),
    session_ttl_hours: parseInt($("s-session-ttl")?.value || "24"),
    server_listen_host: ($("s-server-listen-host")?.value || "").trim(),
    server_listen_port: parseInt($("s-server-listen-port")?.value || "0"),
    module_chat_min_role: $("s-module-chat-min-role")?.value || "user",
    module_community_min_role: $("s-module-community-min-role")?.value || "user",
    module_appeals_min_role: $("s-module-appeals-min-role")?.value || "user",
    module_accounts_min_role: $("s-module-accounts-min-role")?.value || "manager",
    site_bg: $("s-site-bg")?.value || "#0f0f1a",
    site_surface: $("s-site-surface")?.value || "#1a1a2e",
    site_accent: $("s-site-accent")?.value || "#6c63ff",
    site_accent2: $("s-site-accent2")?.value || "#00d4aa",
    site_text: $("s-site-text")?.value || "#e0e0f0",
    site_muted: $("s-site-muted")?.value || "#8888aa",
    site_layout_mode: $("s-site-layout-mode")?.value || "centered",
    site_density: $("s-site-density")?.value || "comfortable"
  };
  FEATURE_SETTING_KEYS.forEach((key) => {
    const el = $(featureSettingInputId(key));
    if (el) payload[key] = !!el.checked;
  });
  const res = await fetch(API + "/admin/settings", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const el = $("settings-msg");
  if (el) {
    const bind = json.server_bind || {};
    const restartHint = bind.restart_required ? "，listen IP/port 需重啟服務器後生效" : "";
    el.textContent = json.ok ? `✅ 設定已儲存${restartHint}` : (json.msg || "儲存失敗");
    el.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) {
    applySiteConfig(payload);
    if (currentUser) setAuthState({
      username: currentUser,
      id: currentUserId,
      role: currentRole,
      role_label: $("me-role")?.textContent || currentRole,
      nickname: $("me-nickname")?.textContent || "",
      birthdate: null
    });
  }
}

async function loadServerEnv() {
  if (!currentUser || currentRole !== "super_admin") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/environment", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const summary = $("server-env-summary");
  const details = $("server-env-details");
  if (!summary || !details) return;
  if (!json.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "系統環境讀取失敗")}</div>`;
    details.textContent = "";
    return;
  }
  const env = json.environment || {};
  const cards = [
    ["作業平台", env.platform || "-", "#82b1ff"],
    ["Python", env.python_version || "-", "#82b1ff"],
    ["資料庫", formatBytes(env.database_bytes || 0), "#82b1ff"],
    ["程序 PID", String(env.pid || "-"), "#82b1ff"],
    ["Log 檔數", String(env.log_files || 0), "#82b1ff"],
    ["Anchor 檔數", String(env.anchor_files || 0), "#82b1ff"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1.05rem;color:${color};font-weight:700;margin-top:.2rem;">${sanitize(value)}</div>
    </div>
  `).join("");
  details.innerHTML = `BASE_DIR：${sanitize(env.base_dir || "-")}<br>DB：${sanitize(env.database_path || "-")}<br>聊天檔數：${sanitize(String(env.chat_files || 0))}`;
}

async function restartServer() {
  if (!confirm("⚠️ 確定要重啟伺服器？所有連線將中斷。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/restart", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    setTimeout(() => location.reload(), 3000);
  } else {
    alert(json.msg || "重啟失敗");
  }
}

// ── Bind all UI events ───────────────────────────────────────
