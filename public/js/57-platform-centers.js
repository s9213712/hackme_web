'use strict';

function platformCenterSetMsg(id, text, ok = true) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.className = "msg " + (ok ? "ok" : "err");
}

function platformStatusLabel(status) {
  const map = {
    queued: "排隊中",
    running: "執行中",
    waiting_external: "等待外部服務",
    succeeded: "已完成",
    failed: "失敗",
    cancelled: "已取消",
    retry_wait: "等待重試",
    expired: "已逾時",
    active: "啟用中",
    revoked: "已撤銷",
    expired_share: "已到期",
    view_limit_reached: "次數已用完"
  };
  return map[status] || status || "-";
}

function platformSeverityClass(status) {
  if (["failed", "expired", "expired_share", "revoked", "view_limit_reached"].includes(status)) return "danger";
  if (["running", "waiting_external", "queued", "active"].includes(status)) return "info";
  if (status === "succeeded") return "success";
  return "muted";
}

let shareCenterCountdownTimer = null;

function parseShareCenterExpiresAt(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw.replace(" ", "T");
  const timestamp = Date.parse(normalized);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function formatShareCenterCountdown(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "已到期";
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `剩餘 ${days} 天 ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `剩餘 ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function updateShareCenterCountdowns() {
  const items = Array.from(document.querySelectorAll("[data-share-countdown-until]"));
  const now = Date.now();
  items.forEach((item) => {
    const timestamp = parseShareCenterExpiresAt(item.getAttribute("data-share-countdown-until"));
    item.textContent = timestamp ? `倒數計時：${formatShareCenterCountdown(timestamp - now)}` : "";
  });
  if (!items.length && shareCenterCountdownTimer) {
    clearInterval(shareCenterCountdownTimer);
    shareCenterCountdownTimer = null;
  }
}

function scheduleShareCenterCountdowns() {
  updateShareCenterCountdowns();
  const hasCountdown = !!document.querySelector("[data-share-countdown-until]");
  if (hasCountdown && !shareCenterCountdownTimer) {
    shareCenterCountdownTimer = setInterval(updateShareCenterCountdowns, 1000);
  }
  if (!hasCountdown && shareCenterCountdownTimer) {
    clearInterval(shareCenterCountdownTimer);
    shareCenterCountdownTimer = null;
  }
}

function renderJobCenterJobs(jobs = []) {
  const list = $("job-center-list");
  if (!list) return;
  const running = jobs.filter((j) => ["queued", "running", "waiting_external", "retry_wait"].includes(j.status)).length;
  const failed = jobs.filter((j) => ["failed", "expired"].includes(j.status)).length;
  const done = jobs.filter((j) => j.status === "succeeded").length;
  if ($("job-center-running-count")) $("job-center-running-count").textContent = String(running);
  if ($("job-center-failed-count")) $("job-center-failed-count").textContent = String(failed);
  if ($("job-center-done-count")) $("job-center-done-count").textContent = String(done);
  if (!jobs.length) {
    list.innerHTML = '<p style="color:var(--muted);">目前沒有任務紀錄。</p>';
    return;
  }
  list.innerHTML = jobs.map((job) => {
    const percent = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    const cls = platformSeverityClass(job.status);
    const err = job.error_message
      ? `<div class="drive-card-sub" style="color:#ffb74d;">${sanitize(job.error_stage || job.stage || "error")}：${sanitize(job.error_message)}</div>`
      : "";
    const cancel = job.cancellable && !["succeeded", "failed", "cancelled", "expired"].includes(job.status)
      ? `<button class="btn btn-danger" type="button" data-job-cancel="${sanitize(job.job_uuid)}">取消</button>`
      : "";
    const retry = ["failed", "retry_wait", "expired", "cancelled"].includes(job.status)
      ? `<button class="btn" type="button" data-job-retry="${sanitize(job.job_uuid)}">重試</button>`
      : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(job.title || "任務")}</strong>
          <div class="drive-card-sub">${sanitize(job.source_module || "-")} · ${sanitize(job.job_type || "-")} · ${sanitize(formatChatTime(job.updated_at || job.created_at || ""))}</div>
          <div class="drive-card-sub">${sanitize(job.stage || job.status || "-")} ${job.stage_detail ? "· " + sanitize(job.stage_detail) : ""}</div>
          <div class="mini-progress" aria-label="任務進度"><span style="width:${percent}%"></span></div>
          ${err}
        </div>
        <div class="drive-file-actions">
          <span class="badge ${cls}">${sanitize(platformStatusLabel(job.status))} · ${percent}%</span>
          ${cancel}
          ${retry}
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-job-cancel]").forEach((btn) => {
    btn.addEventListener("click", () => updateJobCenterJob(btn.dataset.jobCancel, "cancel"));
  });
  list.querySelectorAll("[data-job-retry]").forEach((btn) => {
    btn.addEventListener("click", () => updateJobCenterJob(btn.dataset.jobRetry, "retry"));
  });
}

async function loadJobCenter() {
  if (!currentUser) return;
  platformCenterSetMsg("job-center-msg", "正在讀取任務中心...", true);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const endpoint = (currentRole === "manager" || currentRole === "super_admin")
      ? API + "/admin/jobs?limit=80"
      : API + "/jobs?limit=80";
    const res = await apiFetch(endpoint, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("job-center-msg", json.msg || "任務中心讀取失敗", false);
      renderJobCenterJobs([]);
      return;
    }
    renderJobCenterJobs(json.jobs || []);
    platformCenterSetMsg("job-center-msg", `已載入 ${(json.jobs || []).length} 筆任務`, true);
  } catch (_) {
    platformCenterSetMsg("job-center-msg", "任務中心讀取失敗，請稍後再試。", false);
  }
}

async function updateJobCenterJob(jobUuid, action) {
  if (!jobUuid || !["cancel", "retry"].includes(action)) return;
  if (action === "cancel" && !confirm("確定要取消這個任務？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/jobs/${encodeURIComponent(jobUuid)}/${action}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    platformCenterSetMsg("job-center-msg", json.msg || "任務更新失敗", false);
    return;
  }
  platformCenterSetMsg("job-center-msg", json.msg || "任務已更新", true);
  await loadJobCenter();
}

function renderShareCenter(shares = []) {
  const list = $("share-center-list");
  if (!list) return;
  const active = shares.filter((s) => s.status === "active").length;
  const ended = shares.length - active;
  const accesses = shares.reduce((total, s) => total + Number(s.access_count || 0), 0);
  if ($("share-center-active-count")) $("share-center-active-count").textContent = String(active);
  if ($("share-center-ended-count")) $("share-center-ended-count").textContent = String(ended);
  if ($("share-center-access-count")) $("share-center-access-count").textContent = String(accesses);
  if (!shares.length) {
    list.innerHTML = '<p style="color:var(--muted);">目前沒有分享連結。</p>';
    scheduleShareCenterCountdowns();
    return;
  }
  list.innerHTML = shares.map((share) => {
    const status = share.status === "expired" ? "expired_share" : share.status;
    let url = "";
    if (share.share_url) {
      try {
        const parsed = new URL(share.share_url, location.origin);
        if (parsed.origin === location.origin) url = parsed.href;
      } catch (_) {
        url = "";
      }
    }
    const copy = url ? `<button class="btn" type="button" data-share-copy="${sanitize(url)}">複製</button>` : "";
    const events = `<button class="btn" type="button" data-share-events-type="${sanitize(share.share_type)}" data-share-events-id="${sanitize(share.id)}">紀錄</button>`;
    const revoke = share.status === "active"
      ? `<button class="btn btn-danger" type="button" data-share-revoke-type="${sanitize(share.share_type)}" data-share-revoke-id="${sanitize(share.id)}">撤銷</button>`
      : "";
    const countdown = share.expires_at
      ? `<div class="drive-card-sub share-center-countdown" data-share-countdown-until="${sanitize(share.expires_at)}">倒數計時：${sanitize(formatShareCenterCountdown((parseShareCenterExpiresAt(share.expires_at) || 0) - Date.now()))}</div>`
      : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(share.resource_title || "分享連結")}</strong>
          <div class="drive-card-sub">${sanitize(share.share_type || "-")} · 建立 ${sanitize(formatChatTime(share.created_at || ""))}</div>
          <div class="drive-card-sub">到期 ${sanitize(share.expires_at || "無")} · 次數 ${sanitize(String(share.access_count || 0))}${share.max_views ? " / " + sanitize(String(share.max_views)) : ""} · 密碼 ${share.password_required ? "是" : "否"}</div>
          ${countdown}
          ${url ? `<div class="drive-card-sub drive-share-link">${sanitize(url)}</div>` : ""}
        </div>
        <div class="drive-file-actions">
          <span class="badge ${platformSeverityClass(status)}">${sanitize(platformStatusLabel(status))}</span>
          ${copy}
          ${events}
          ${revoke}
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-share-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const url = btn.dataset.shareCopy || "";
      try {
        await navigator.clipboard.writeText(url);
        platformCenterSetMsg("share-center-msg", "分享連結已複製", true);
      } catch (_) {
        window.prompt("分享連結", url);
      }
    });
  });
  list.querySelectorAll("[data-share-revoke-id]").forEach((btn) => {
    btn.addEventListener("click", () => revokeShareCenterLink(btn.dataset.shareRevokeType || "", btn.dataset.shareRevokeId || ""));
  });
  list.querySelectorAll("[data-share-events-id]").forEach((btn) => {
    btn.addEventListener("click", () => loadShareCenterEvents(btn.dataset.shareEventsType || "", btn.dataset.shareEventsId || ""));
  });
  scheduleShareCenterCountdowns();
}

async function loadShareCenter() {
  if (!currentUser) return;
  platformCenterSetMsg("share-center-msg", "正在讀取分享管理...", true);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const allParam = (currentRole === "manager" || currentRole === "super_admin") ? "&all=1" : "";
    const res = await apiFetch(API + `/shares?limit=120${allParam}`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("share-center-msg", json.msg || "分享管理讀取失敗", false);
      renderShareCenter([]);
      return;
    }
    renderShareCenter(json.shares || []);
    platformCenterSetMsg("share-center-msg", `已載入 ${(json.shares || []).length} 個分享連結`, true);
  } catch (_) {
    platformCenterSetMsg("share-center-msg", "分享管理讀取失敗，請稍後再試。", false);
  }
}

async function revokeShareCenterLink(type, id) {
  if (!type || !id) return;
  if (!confirm("確定要撤銷這個分享連結？")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/shares/${encodeURIComponent(type)}/${encodeURIComponent(id)}/revoke`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    platformCenterSetMsg("share-center-msg", json.msg || "撤銷分享連結失敗", false);
    return;
  }
  platformCenterSetMsg("share-center-msg", "分享連結已撤銷", true);
  await loadShareCenter();
}

async function loadShareCenterEvents(type, id) {
  if (!type || !id) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const panel = $("share-center-events");
  if (panel) {
    panel.style.display = "block";
    panel.className = "msg ok";
    panel.textContent = "正在讀取分享紀錄...";
  }
  try {
    const res = await apiFetch(API + `/shares/${encodeURIComponent(type)}/${encodeURIComponent(id)}/access-events`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      if (panel) {
        panel.className = "msg err";
        panel.textContent = json.msg || "分享紀錄讀取失敗";
      }
      return;
    }
    const events = json.events || [];
    if (!panel) return;
    if (!events.length) {
      panel.textContent = "目前沒有分享紀錄。";
      return;
    }
    panel.innerHTML = `<strong>分享紀錄</strong><div class="share-center-event-list">${events.map((event) => {
      const when = formatChatTime(event.opened_at || event.created_at || "");
      const ip = event.source_ip || event.ip || "";
      const detail = event.detail || "";
      const userAgent = event.user_agent || "";
      const eventType = event.event_type || "";
      const isOpenEvent = event.opened_at || eventType === "opened" || eventType === "accessed";
      const timeLabel = isOpenEvent ? "開啟時間" : "時間";
      const ipText = ip ? ` · IP 來源：${sanitize(ip)}` : (isOpenEvent ? " · IP 來源：未記錄" : "");
      return `<div class="share-center-event-row">
        <div class="share-center-event-title">${sanitize(event.label || event.event_type || "-")}</div>
        <div class="share-center-event-meta">${timeLabel}：${sanitize(when || "-")}${ipText}</div>
        ${detail ? `<div class="share-center-event-detail">${sanitize(detail)}</div>` : ""}
        ${userAgent ? `<div class="share-center-event-detail">${sanitize(userAgent)}</div>` : ""}
      </div>`;
    }).join("")}</div>`;
  } catch (_) {
    if (panel) {
      panel.className = "msg err";
      panel.textContent = "分享紀錄讀取失敗，請稍後再試。";
    }
  }
}

function renderTradingAssetOverview(overview = {}) {
  const map = {
    "economy-asset-total-equity": overview.total_equity_points,
    "economy-asset-available": overview.available_points,
    "economy-asset-locked": overview.locked_points,
    "economy-asset-spot": overview.spot_market_value_points,
    "economy-asset-margin": overview.margin_position_equity_points,
    "economy-asset-interest": overview.accrued_interest_points
  };
  Object.entries(map).forEach(([id, value]) => {
    if ($(id)) $(id).textContent = `${formatTradingPointsValue(Number(value || 0))} 點`;
  });
  if ($("economy-asset-confidence")) {
    $("economy-asset-confidence").textContent = `${overview.low_confidence_price_count || 0} 個低信心價格 · ${overview.confidence_note || ""}`;
  }
}

function renderTradingAdminAssetOverview(risk = {}) {
  const el = $("economy-asset-admin-risk");
  if (!el) return;
  el.style.display = "block";
  el.textContent = `管理摘要：使用者 ${risk.account_count || 0} · 開放委託 ${risk.open_order_count || 0} · 借貸倉位 ${risk.open_margin_positions || 0} · 借貸本金 ${formatTradingPointsValue(Number(risk.total_margin_principal_points || 0))} 點 · 低信心市場 ${risk.low_confidence_price_count || 0}`;
}

async function loadTradingAssetOverview() {
  if (!currentUser || !canAccessModule("trading")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/trading/asset-overview", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("economy-msg", json.msg || "交易資產總覽讀取失敗", false);
      return;
    }
    renderTradingAssetOverview(json.overview || {});
    if (currentRole === "manager" || currentRole === "super_admin") {
      const adminRes = await apiFetch(API + "/admin/trading/asset-overview", {
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf || "" }
      });
      const adminJson = await adminRes.json().catch(() => ({}));
      if (!adminJson.ok) {
        platformCenterSetMsg("economy-msg", adminJson.msg || "交易管理風險摘要讀取失敗", false);
        return;
      }
      renderTradingAdminAssetOverview(adminJson.risk || {});
    }
  } catch (err) {
    platformCenterSetMsg("economy-msg", err?.message || "交易資產總覽讀取失敗", false);
  }
}
