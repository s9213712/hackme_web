function switchServerTab(tab) {
  currentServerTab = tab;
  ["health", "integrity", "settings", "env"].forEach((name) => {
    const sec = $("sec-server-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-server-health", "tab-server-integrity", "tab-server-settings", "tab-server-env"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-server-" + tab);
  });
  if (tab === "health") loadServerHealth();
  if (tab === "integrity") loadIntegrityGuard();
  if (tab === "settings") loadSettings();
  if (tab === "env") loadServerEnv();
}

function switchSettingsSection(tab) {
  currentSettingsSection = tab;
  ["security", "features", "appearance", "system", "drive", "member-levels"].forEach((name) => {
    const sec = $("sec-settings-" + name);
    if (sec) sec.classList.toggle("active", name === tab);
  });
  ["tab-settings-security", "tab-settings-features", "tab-settings-appearance", "tab-settings-system", "tab-settings-drive", "tab-settings-member-levels"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.classList.toggle("active", id === "tab-settings-" + tab);
  });
  if (tab === "drive") loadCloudDriveAdminPolicy();
  if (tab === "member-levels") loadEditableMemberLevelRules();
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
  ["users","audit","violations","governance","appeals","reports"].forEach(t => {
    const sec = $("sec-" + t);
    if (sec) sec.classList.toggle("active", t === tab);
  });
  ["tab-users","tab-audit","tab-violations","tab-governance","tab-appeals","tab-reports"].forEach(id => {
    const btn = $(id);
    if (btn) btn.classList.toggle("active", id === "tab-" + tab);
  });
  if (tab === "audit") loadAudit(0);
  if (tab === "violations") loadViolations(0);
  if (tab === "governance") loadGovernanceDashboard();
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

// ── Governance UI ───────────────────────────────────────────
async function loadGovernanceDashboard() {
  await Promise.allSettled([loadMemberLevelRulesSummary(), loadGovernanceProposals()]);
}

async function loadMemberLevelRulesSummary() {
  const container = $("member-level-rules-list");
  if (!container) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/member-level-rules", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    container.innerHTML = `<div style="color:#ffb74d;">${sanitize(json.msg || "會員規則僅 root 可讀取或功能尚未啟用")}</div>`;
    return;
  }
  const rules = Array.isArray(json.rules) ? json.rules : [];
  container.innerHTML = rules.map((r) => {
    const level = r.level || "";
    const flags = [
      r.can_post ? "發文" : "禁發文",
      r.can_comment ? "留言" : "禁留言",
      r.can_send_dm ? "私訊" : "禁私訊",
      r.can_upload_attachment ? "上傳" : "禁上傳",
      r.requires_moderation ? "需審核" : "免審"
    ].join(" · ");
    return `<div style="border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:.6rem;background:rgba(0,0,0,.2);">
      <div style="font-weight:700;color:#e0e0f0;">${sanitize(level)}</div>
      <div style="color:var(--muted);margin-top:.2rem;">${sanitize(flags)}</div>
      <div style="color:#82b1ff;margin-top:.25rem;">post ${r.daily_post_limit ?? "-"} · upload ${r.attachment_quota_mb ?? 0} MB · report weight ${r.report_weight ?? "-"}</div>
    </div>`;
  }).join("");
}

async function loadGovernanceProposals() {
  const list = $("governance-proposal-list");
  const msg = $("governance-msg");
  if (!list) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const status = $("governance-proposal-status")?.value || "";
  const url = API + "/admin/moderation/proposals" + (status ? "?status=" + encodeURIComponent(status) : "");
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "治理提案讀取失敗")}</div>`;
    if (msg) msg.textContent = "";
    return;
  }
  const proposals = Array.isArray(json.proposals) ? json.proposals : [];
  if (msg) msg.textContent = `共 ${proposals.length} 筆`;
  if (!proposals.length) {
    list.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>目前沒有治理提案</p>";
    return;
  }
  list.innerHTML = proposals.map((p) => {
    const target = p.target?.username || `#${p.target_user_id}`;
    const proposer = p.proposed_by?.username || `#${p.proposed_by_user_id}`;
    const votes = (p.votes || []).map(v => `${sanitize(v.voter_username || "")}:${sanitize(v.vote || "")}`).join(" · ") || "尚無投票";
    const canVote = p.status === "pending";
    const canExecute = p.status === "approved";
    const canOverride = currentUser === "root" && p.status !== "executed";
    return `<div style="border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:.65rem;margin-bottom:.55rem;background:rgba(0,0,0,.22);">
      <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;">
        <strong>#${p.id}</strong>
        <span style="color:#82b1ff;">${sanitize(p.action_type || "")}</span>
        <span>target=${sanitize(target)}</span>
        <span style="color:${p.status === "approved" ? "#4caf50" : p.status === "rejected" ? "#ff4f6d" : "#ffb74d"};">${sanitize(p.status || "")}</span>
        <span style="margin-left:auto;color:var(--muted);">${p.approve_count || 0}/${p.required_votes || 0} approve · ${p.reject_count || 0} reject</span>
      </div>
      <div style="color:var(--muted);margin-top:.25rem;">proposer=${sanitize(proposer)} · expires=${sanitize(p.expires_at || "")}</div>
      <div style="margin-top:.35rem;white-space:pre-wrap;">${sanitize(p.reason || "")}</div>
      <div style="color:var(--muted);margin-top:.35rem;">votes: ${votes}</div>
      <div class="admin-toolbar" style="display:flex;gap:.45rem;margin-top:.5rem;">
        ${canVote ? `<button class="btn btn-primary" data-governance-vote="approve" data-proposal-id="${p.id}">同意</button><button class="btn" data-governance-vote="reject" data-proposal-id="${p.id}">否決</button>` : ""}
        ${canExecute ? `<button class="btn btn-primary" data-governance-execute="${p.id}">執行</button>` : ""}
        ${canOverride ? `<button class="btn" style="color:#ffb74d;" data-governance-override="${p.id}">root override</button>` : ""}
      </div>
    </div>`;
  }).join("");
  list.querySelectorAll("button[data-governance-vote]").forEach((btn) => {
    btn.addEventListener("click", () => voteGovernanceProposal(btn.getAttribute("data-proposal-id"), btn.getAttribute("data-governance-vote")));
  });
  list.querySelectorAll("button[data-governance-execute]").forEach((btn) => {
    btn.addEventListener("click", () => executeGovernanceProposal(btn.getAttribute("data-governance-execute")));
  });
  list.querySelectorAll("button[data-governance-override]").forEach((btn) => {
    btn.addEventListener("click", () => overrideGovernanceProposal(btn.getAttribute("data-governance-override")));
  });
}

async function createGovernanceProposal() {
  const targetId = parseInt($("governance-target-user-id")?.value || "0", 10);
  const reason = ($("governance-reason")?.value || "").trim();
  if (!targetId || !reason) {
    alert("請填目標 user id 與提案原因");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    target_user_id: targetId,
    action_type: $("governance-action-type")?.value || "warn",
    action_value: ($("governance-action-value")?.value || "").trim() || null,
    required_votes: parseInt($("governance-required-votes")?.value || "2", 10),
    ttl_hours: parseInt($("governance-ttl-hours")?.value || "72", 10),
    reason
  };
  const res = await fetch(API + "/admin/moderation/proposals", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "治理提案已建立" : "治理提案建立失敗"));
  if (json.ok) {
    if ($("governance-reason")) $("governance-reason").value = "";
    await loadGovernanceProposals();
  }
}

async function voteGovernanceProposal(proposalId, vote) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const comment = prompt("投票備註（可空白）") || "";
  const res = await fetch(API + `/admin/moderation/proposals/${proposalId}/vote`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ vote, comment })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "已完成投票" : "投票失敗"));
  await loadGovernanceProposals();
}

async function executeGovernanceProposal(proposalId) {
  if (!confirm("確定執行已通過的治理提案？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/admin/moderation/proposals/${proposalId}/execute`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "治理提案已執行" : "執行失敗"));
  await Promise.all([loadGovernanceProposals(), loadUsers()]);
}

async function overrideGovernanceProposal(proposalId) {
  if (currentUser !== "root" || !confirm("確定 root override 並立即執行此提案？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/root/moderation/proposals/${proposalId}/override`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "root override 已執行" : "override 失敗"));
  await Promise.all([loadGovernanceProposals(), loadUsers()]);
}

function openGovernanceProposalForUser(userId, username) {
  switchAdminTab("governance");
  if ($("governance-target-user-id")) $("governance-target-user-id").value = userId;
  if ($("governance-reason")) $("governance-reason").value = `針對 ${username || "user #" + userId} 建立治理提案：`;
}

// ── Settings & restart ───────────────────────────────────────
const MEMBER_LEVEL_BOOL_FIELDS = [
  ["can_post", "可發文"],
  ["can_comment", "可留言"],
  ["can_send_dm", "可私訊"],
  ["can_upload_attachment", "可上傳附件"],
  ["can_report", "可檢舉"],
  ["requires_moderation", "發文需審核"],
  ["require_admin_approval", "升等需 admin 核准"],
  ["require_root_approval", "升等需 root 核准"]
];
const MEMBER_LEVEL_INT_FIELDS = [
  ["daily_post_limit", "每日發文上限"],
  ["daily_dm_limit", "每日私訊上限"],
  ["post_rate_limit_per_hour", "每小時發文限制"],
  ["comment_rate_limit_per_hour", "每小時留言限制"],
  ["dm_rate_limit_per_day", "每日私訊 rate limit"],
  ["upload_rate_limit_per_day", "每日上傳限制"],
  ["max_attachment_size_mb", "單檔上限 MB"],
  ["attachment_quota_mb", "總容量 MB"],
  ["report_weight", "檢舉權重"],
  ["min_account_age_days", "升等帳齡天數"],
  ["min_approved_content_count", "升等核准內容數"],
  ["min_points", "升等點數"],
  ["min_trust_score", "升等 trust_score"],
  ["min_reputation", "升等 reputation"],
  ["max_violation_score", "升等最大違規分"],
  ["downgrade_violation_threshold", "降級/處分建議門檻"],
  ["session_idle_timeout_minutes", "閒置登出分鐘"]
];
const CLOUD_DRIVE_POLICY_BOOL_FIELDS = [
  "require_scan_before_download",
  "block_unclean_downloads",
  "warn_high_risk_downloads",
  "allow_inline_preview_for_high_risk",
  "e2ee_server_scan_claim_allowed",
  "revoke_shares_on_suspension"
];
const CLOUD_DRIVE_POLICY_INT_FIELDS = [
  "max_archive_files",
  "max_archive_uncompressed_bytes",
  "max_daily_downloads"
];

function cloudDrivePolicyInputId(key) {
  return "s-cd-" + key.replaceAll("_", "-");
}

async function loadCloudDriveAdminPolicy() {
  if (!currentUser || currentUser !== "root") return;
  const rootEl = $("s-cd-require-scan-before-download");
  if (!rootEl) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/cloud-drive/security-policy", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("cloud-drive-policy-msg");
  if (!json.ok) {
    if (msg) {
      msg.textContent = json.msg || "雲端硬碟安全政策讀取失敗";
      msg.style.color = "#ff4f6d";
    }
    return;
  }
  const p = json.policy || {};
  CLOUD_DRIVE_POLICY_BOOL_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) el.checked = !!p[key];
  });
  CLOUD_DRIVE_POLICY_INT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) el.value = p[key] ?? 0;
  });
  if ($("s-cd-notes")) $("s-cd-notes").value = p.notes || "";
  if (msg) msg.textContent = "";
}

async function saveCloudDriveAdminPolicy() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {};
  CLOUD_DRIVE_POLICY_BOOL_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) payload[key] = !!el.checked;
  });
  CLOUD_DRIVE_POLICY_INT_FIELDS.forEach((key) => {
    const el = $(cloudDrivePolicyInputId(key));
    if (el) payload[key] = parseInt(el.value || "0");
  });
  payload.notes = $("s-cd-notes")?.value || "";
  const res = await fetch(API + "/admin/cloud-drive/security-policy", {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("cloud-drive-policy-msg");
  if (msg) {
    msg.textContent = json.ok ? "雲端硬碟安全政策已儲存" : (json.msg || "儲存失敗");
    msg.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
}

async function loadEditableMemberLevelRules() {
  if (!currentUser || currentUser !== "root") return;
  const container = $("settings-member-level-rules");
  if (!container) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/admin/member-level-rules", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    container.innerHTML = `<div style="color:#ff4f6d;">${sanitize(json.msg || "會員等級規則讀取失敗")}</div>`;
    return;
  }
  const rules = Array.isArray(json.rules) ? json.rules : [];
  container.innerHTML = rules.map((rule) => {
    const level = rule.level || "";
    const bools = MEMBER_LEVEL_BOOL_FIELDS.map(([key, label]) => `
      <label style="font-size:.74rem;color:var(--text);"><input type="checkbox" data-level="${sanitize(level)}" data-rule-bool="${key}" ${rule[key] ? "checked" : ""} /> ${label}</label>
    `).join("");
    const ints = MEMBER_LEVEL_INT_FIELDS.map(([key, label]) => `
      <label style="font-size:.7rem;color:var(--muted);">${label}
        <input type="number" min="0" data-level="${sanitize(level)}" data-rule-int="${key}" value="${Number(rule[key] || 0)}" style="margin-top:.18rem;" />
      </label>
    `).join("");
    return `<div style="border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:.7rem;background:rgba(0,0,0,.24);">
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.55rem;">
        <strong style="font-size:.95rem;">${sanitize(level)}</strong>
        <button class="btn btn-primary" type="button" data-save-member-level="${sanitize(level)}" style="margin-left:auto;padding:.35rem .55rem;font-size:.72rem;">儲存</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.35rem;margin-bottom:.55rem;">${bools}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:.45rem;">${ints}</div>
    </div>`;
  }).join("");
  container.querySelectorAll("[data-save-member-level]").forEach((btn) => {
    btn.addEventListener("click", () => saveMemberLevelRule(btn.getAttribute("data-save-member-level")));
  });
}

async function saveMemberLevelRule(level) {
  if (!level) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const container = $("settings-member-level-rules");
  const payload = {};
  MEMBER_LEVEL_BOOL_FIELDS.forEach(([key]) => {
    const el = container?.querySelector(`[data-level="${CSS.escape(level)}"][data-rule-bool="${key}"]`);
    if (el) payload[key] = !!el.checked;
  });
  MEMBER_LEVEL_INT_FIELDS.forEach(([key]) => {
    const el = container?.querySelector(`[data-level="${CSS.escape(level)}"][data-rule-int="${key}"]`);
    if (el) payload[key] = parseInt(el.value || "0");
  });
  const res = await fetch(API + "/admin/member-level-rules/" + encodeURIComponent(level), {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify(payload)
  });
  const json = await res.json().catch(() => ({}));
  const msg = $("member-level-settings-msg");
  if (msg) {
    msg.textContent = json.ok ? `${level} 規則已儲存` : (json.msg || "會員等級規則儲存失敗");
    msg.style.color = json.ok ? "#4caf50" : "#ff4f6d";
  }
  if (json.ok) loadMemberLevelRulesSummary();
}

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
  if ($("s-login-violation-enabled")) $("s-login-violation-enabled").checked = !!s.login_violation_enabled;
  if ($("s-rate-limit-violation-enabled")) $("s-rate-limit-violation-enabled").checked = !!s.rate_limit_violation_enabled;
  if ($("s-root-ip-whitelist-enabled")) $("s-root-ip-whitelist-enabled").checked = !!s.root_ip_whitelist_enabled;
  if ($("s-root-ip-whitelist")) $("s-root-ip-whitelist").value = s.root_ip_whitelist || "";
  if ($("s-browser-only-mode-enabled")) $("s-browser-only-mode-enabled").checked = !!s.browser_only_mode_enabled;
  if ($("s-integrity-guard-enabled")) $("s-integrity-guard-enabled").checked = s.integrity_guard_enabled !== false;
  if ($("s-integrity-guard-strict-mode")) $("s-integrity-guard-strict-mode").checked = !!s.integrity_guard_strict_mode;
  if ($("s-allow-register")) $("s-allow-register").checked = !!s.allow_register;
  if ($("s-require-email")) $("s-require-email").checked = !!s.require_email_verification;
  if ($("s-max-fail")) $("s-max-fail").value = s.max_login_failures || 5;
  if ($("s-block-dur")) $("s-block-dur").value = s.block_duration_minutes || 30;
  if ($("s-session-ttl")) $("s-session-ttl").value = s.session_ttl_hours || 24;
  if ($("s-server-listen-host")) $("s-server-listen-host").value = s.server_listen_host || "";
  if ($("s-server-listen-port")) $("s-server-listen-port").value = s.server_listen_port || "";
  if ($("s-cloud-drive-storage-root")) $("s-cloud-drive-storage-root").value = s.cloud_drive_storage_root || "";
  if ($("s-snapshot-daily-auto-enabled")) $("s-snapshot-daily-auto-enabled").checked = !!s.snapshot_daily_auto_enabled;
  if ($("s-snapshot-daily-time")) $("s-snapshot-daily-time").value = s.snapshot_daily_time || "03:00";
  const bindStatus = $("server-bind-status");
  if (bindStatus) {
    const restartText = bind.restart_required ? "需重啟才會套用新 listen 設定" : "目前執行中的 listen 設定已一致";
    bindStatus.textContent = `目前 ${bind.current_host || bind.host || "0.0.0.0"}:${bind.current_port || bind.port || 5000}，下次啟動 ${bind.host || "0.0.0.0"}:${bind.port || 5000}。${restartText}`;
    bindStatus.style.color = bind.restart_required ? "#ffb74d" : "var(--muted)";
  }
  const driveStorage = json.cloud_drive_storage || {};
  const driveStorageStatus = $("cloud-drive-storage-status");
  if (driveStorageStatus) {
    const restartText = driveStorage.restart_required ? "需重啟服務器才會切到新儲存根目錄" : "目前執行中的儲存根目錄已一致";
    driveStorageStatus.textContent = `目前 ${driveStorage.current_root || "-"}，下次啟動 ${driveStorage.effective_next_root || "-"}。${restartText}`;
    driveStorageStatus.style.color = driveStorage.restart_required ? "#ffb74d" : "var(--muted)";
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

async function loadIntegrityGuard() {
  if (!currentUser || currentUser !== "root") return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const [statusRes, findingsRes] = await Promise.all([
    fetch(API + "/root/integrity/status", { credentials: "same-origin", headers: { "X-CSRF-Token": csrf || "" } }),
    fetch(API + "/root/integrity/findings?status=pending", { credentials: "same-origin", headers: { "X-CSRF-Token": csrf || "" } })
  ]);
  const statusJson = await statusRes.json().catch(() => ({}));
  const findingsJson = await findingsRes.json().catch(() => ({}));
  const summary = $("integrity-summary");
  const warning = $("integrity-warning");
  const list = $("integrity-findings");
  if (!summary || !warning || !list) return;
  if (!statusJson.ok) {
    summary.innerHTML = `<div style="color:#ff4f6d;">${sanitize(statusJson.msg || "Integrity Guard 狀態讀取失敗")}</div>`;
    warning.textContent = "";
    list.innerHTML = "";
    return;
  }
  const ig = statusJson.integrity || {};
  const s = ig.summary || {};
  const last = ig.last_scan || {};
  const cards = [
    ["受保護檔案", String(ig.protected_files || 0), "#82b1ff"],
    ["Pending", String(s.pending || 0), (s.pending || 0) ? "#ffb74d" : "#4caf50"],
    ["High Risk", String(s.high_risk_pending || 0), (s.high_risk_pending || 0) ? "#ff4f6d" : "#4caf50"],
    ["Modified", String(s.modified || 0), (s.modified || 0) ? "#ffb74d" : "#82b1ff"],
    ["Added", String(s.added || 0), (s.added || 0) ? "#ffb74d" : "#82b1ff"],
    ["Deleted", String(s.deleted || 0), (s.deleted || 0) ? "#ff4f6d" : "#82b1ff"],
    ["上次掃描", sanitize(last.finished_at || last.started_at || "-"), "#82b1ff"],
    ["Manifest 簽章", last.manifest_signature_valid === 1 ? "有效" : "未驗證/異常", last.manifest_signature_valid === 1 ? "#4caf50" : "#ff4f6d"],
  ];
  summary.innerHTML = cards.map(([label, value, color]) => `
    <div style="border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.22);border-radius:8px;padding:.6rem;">
      <div style="font-size:.68rem;color:var(--muted);">${label}</div>
      <div style="font-size:1rem;color:${color};font-weight:700;margin-top:.2rem;word-break:break-all;">${value}</div>
    </div>
  `).join("");
  if ((s.high_risk_pending || 0) > 0) {
    warning.innerHTML = `<span style="color:#ff4f6d;font-weight:700;">高風險警告：</span>此變更涉及安全核心、root、admin、auth、snapshot、storage 或 Integrity Guard 本身。pending/rejected high risk finding 會阻止進入準上線模式。`;
  } else if ((s.pending || 0) > 0) {
    warning.innerHTML = `<span style="color:#ffb74d;font-weight:700;">待處理：</span>存在尚未審核的檔案完整性變更，請確認是否為合法部署。`;
  } else {
    warning.innerHTML = `<span style="color:#4caf50;font-weight:700;">正常：</span>目前沒有 pending finding。`;
  }
  const findings = Array.isArray(findingsJson.findings) ? findingsJson.findings : [];
  if (!findings.length) {
    list.innerHTML = "<p style='color:var(--muted);text-align:center;padding:1rem;'>目前沒有 pending integrity finding</p>";
    return;
  }
  list.innerHTML = findings.map((f) => `
    <div style="border:1px solid ${f.risk_level === "high" ? "rgba(255,79,109,.45)" : "rgba(255,255,255,.1)"};border-radius:9px;padding:.65rem;margin-bottom:.55rem;background:rgba(0,0,0,.22);">
      <div style="display:flex;gap:.45rem;align-items:center;flex-wrap:wrap;">
        <strong>#${f.id}</strong>
        <span style="color:${f.risk_level === "high" ? "#ff4f6d" : f.risk_level === "medium" ? "#ffb74d" : "#82b1ff"};">${sanitize(f.risk_level || "")}</span>
        <span style="color:#82b1ff;">${sanitize(f.change_type || "")}</span>
        <span style="word-break:break-all;">${sanitize(f.file_path || "")}</span>
        <span style="margin-left:auto;color:var(--muted);">${sanitize(f.detected_at || "")}</span>
      </div>
      <div style="color:var(--muted);margin-top:.35rem;word-break:break-all;">old=${sanitize(f.old_hash || "-")} · new=${sanitize(f.new_hash || "-")}</div>
      <div style="color:var(--muted);margin-top:.2rem;">size ${f.old_size ?? "-"} -> ${f.new_size ?? "-"} · category=${sanitize(f.category || "")}</div>
      <div class="admin-toolbar" style="display:flex;gap:.45rem;margin-top:.5rem;">
        <button class="btn btn-primary" data-integrity-action="approve" data-finding-id="${f.id}">approve</button>
        <button class="btn" data-integrity-action="reject" data-finding-id="${f.id}">reject</button>
        <button class="btn" data-integrity-action="ignore" data-finding-id="${f.id}">ignore</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("[data-integrity-action]").forEach((btn) => {
    btn.addEventListener("click", () => reviewIntegrityFinding(btn.getAttribute("data-finding-id"), btn.getAttribute("data-integrity-action")));
  });
}

async function rescanIntegrityGuard() {
  if (!confirm("重新掃描會比對目前檔案與已核准 manifest，異常不會自動核准。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/root/integrity/rescan", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  alert(json.ok ? "Integrity Guard 掃描完成" : (json.msg || "掃描失敗"));
  await loadIntegrityGuard();
}

async function reviewIntegrityFinding(id, action) {
  if (!id || !action) return;
  let confirmText = "";
  let note = "";
  if (action === "approve") {
    alert("approve 代表你確認這些檔案變更是合法部署或可信修改，系統將更新 hash manifest。");
    confirmText = prompt("請輸入 APPROVE INTEGRITY UPDATE 以確認：") || "";
    if (confirmText !== "APPROVE INTEGRITY UPDATE") {
      alert("確認字串不正確，已取消 approve。");
      return;
    }
  } else {
    if (!confirm(`確定要 ${action} 這筆 integrity finding？`)) return;
  }
  note = prompt("審核備註（可留空）：") || "";
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/root/integrity/findings/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
    body: JSON.stringify({ confirm: confirmText, note })
  });
  const json = await res.json().catch(() => ({}));
  alert(json.msg || (json.ok ? "操作完成" : "操作失敗"));
  await loadIntegrityGuard();
}

async function exportIntegrityReport() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + "/root/integrity/report", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    alert(json.msg || "匯出失敗");
    return;
  }
  const blob = new Blob([JSON.stringify(json.report || {}, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "integrity_report.json";
  a.click();
  URL.revokeObjectURL(url);
}

async function saveSettings() {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    maintenance_mode: !!$("s-maintenance-mode")?.checked,
    audit_chain_enabled: !!$("s-audit-chain-enabled")?.checked,
    ip_blocking_enabled: !!$("s-ip-blocking-enabled")?.checked,
    login_violation_enabled: !!$("s-login-violation-enabled")?.checked,
    rate_limit_violation_enabled: !!$("s-rate-limit-violation-enabled")?.checked,
    root_ip_whitelist_enabled: !!$("s-root-ip-whitelist-enabled")?.checked,
    root_ip_whitelist: $("s-root-ip-whitelist")?.value || "",
    browser_only_mode_enabled: !!$("s-browser-only-mode-enabled")?.checked,
    integrity_guard_enabled: !!$("s-integrity-guard-enabled")?.checked,
    integrity_guard_strict_mode: !!$("s-integrity-guard-strict-mode")?.checked,
    allow_register: !!$("s-allow-register")?.checked,
    require_email_verification: !!$("s-require-email")?.checked,
    max_login_failures: parseInt($("s-max-fail")?.value || "5"),
    block_duration_minutes: parseInt($("s-block-dur")?.value || "30"),
    session_ttl_hours: parseInt($("s-session-ttl")?.value || "24"),
    server_listen_host: ($("s-server-listen-host")?.value || "").trim(),
    server_listen_port: parseInt($("s-server-listen-port")?.value || "0"),
    cloud_drive_storage_root: ($("s-cloud-drive-storage-root")?.value || "").trim(),
    snapshot_daily_auto_enabled: !!$("s-snapshot-daily-auto-enabled")?.checked,
    snapshot_daily_time: $("s-snapshot-daily-time")?.value || "03:00",
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
    const driveStorage = json.cloud_drive_storage || {};
    const restartParts = [];
    if (bind.restart_required) restartParts.push("listen IP/port");
    if (driveStorage.restart_required) restartParts.push("雲端硬碟儲存位置");
    const restartHint = restartParts.length ? `，${restartParts.join("、")} 需重啟服務器後生效` : "";
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
