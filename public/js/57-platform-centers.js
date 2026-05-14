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
let shareCenterActiveTab = "links";

function formatPlatformCenterNumber(value) {
  return new Intl.NumberFormat("zh-TW").format(Number(value || 0));
}

function formatPlatformCenterPoints(value) {
  return `${formatPlatformCenterNumber(value)} 點`;
}

function shareCenterVisibilityLabel(value) {
  const map = {
    public: "公開",
    unlisted: "持連結",
    private: "私人"
  };
  return map[value] || value || "-";
}

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
    const endpoint = currentUser === "root"
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

function setShareCenterTab(tab, { load = true } = {}) {
  shareCenterActiveTab = tab === "videos" ? "videos" : "links";
  document.querySelectorAll("[data-share-center-tab]").forEach((btn) => {
    const active = btn.dataset.shareCenterTab === shareCenterActiveTab;
    btn.classList.toggle("btn-primary", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  const linksPanel = $("share-center-links-panel");
  const videosPanel = $("share-center-videos-panel");
  if (linksPanel) linksPanel.style.display = shareCenterActiveTab === "links" ? "" : "none";
  if (videosPanel) videosPanel.style.display = shareCenterActiveTab === "videos" ? "" : "none";
  const eventsPanel = $("share-center-events");
  if (eventsPanel && shareCenterActiveTab !== "links") eventsPanel.style.display = "none";
  if (shareCenterActiveTab === "videos") platformCenterSetMsg("share-center-msg", "", true);
  else platformCenterSetMsg("video-manage-msg", "", true);
  if (load) {
    if (shareCenterActiveTab === "videos") loadVideoManageCenter();
    else loadShareCenterLinks();
  }
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
    const scopeText = share.access_scope === "account"
      ? `指定帳戶：${share.required_username || share.required_user_id || "-"}`
      : "知道連結即可存取";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(share.resource_title || "分享連結")}</strong>
          <div class="drive-card-sub">${sanitize(share.share_type || "-")} · 建立 ${sanitize(formatChatTime(share.created_at || ""))}</div>
          <div class="drive-card-sub">${sanitize(scopeText)} · 到期 ${sanitize(share.expires_at || "無")} · 次數 ${sanitize(String(share.access_count || 0))}${share.max_views ? " / " + sanitize(String(share.max_views)) : ""} · 密碼 ${share.password_required ? "是" : "否"}</div>
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
  if (shareCenterActiveTab === "videos") {
    await loadVideoManageCenter();
    return;
  }
  await loadShareCenterLinks();
}

async function loadShareCenterLinks() {
  if (!currentUser) return;
  platformCenterSetMsg("share-center-msg", "正在讀取分享連結...", true);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/shares?limit=120", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("share-center-msg", json.msg || "分享連結讀取失敗", false);
      renderShareCenter([]);
      return;
    }
    renderShareCenter(json.shares || []);
    platformCenterSetMsg("share-center-msg", `已載入 ${(json.shares || []).length} 個分享連結`, true);
  } catch (_) {
    platformCenterSetMsg("share-center-msg", "分享連結讀取失敗，請稍後再試。", false);
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

function videoManageRow(videoId) {
  return Array.from(document.querySelectorAll("[data-video-manage-id]"))
    .find((row) => String(row.dataset.videoManageId || "") === String(videoId || ""));
}

function videoManageSummaryFrom(videos = []) {
  return videos.reduce((summary, video) => {
    summary.total_videos += 1;
    summary.total_views += Number(video.view_count || 0);
    summary.total_likes += Number(video.like_count || 0);
    summary.total_revenue_points += Number(video.revenue_points || 0);
    summary.total_platform_fee_points += Number(video.platform_fee_points || 0);
    summary.total_boost_points += Number(video.boost_points_total || 0);
    return summary;
  }, {
    total_videos: 0,
    total_views: 0,
    total_likes: 0,
    total_revenue_points: 0,
    total_platform_fee_points: 0,
    total_boost_points: 0
  });
}

function renderVideoManageCenter(payload = {}) {
  const list = $("video-manage-list");
  if (!list) return;
  const videos = Array.isArray(payload) ? payload : (payload.videos || []);
  const summary = payload.summary || videoManageSummaryFrom(videos);
  if ($("video-manage-count")) $("video-manage-count").textContent = formatPlatformCenterNumber(summary.total_videos);
  if ($("video-manage-views")) $("video-manage-views").textContent = formatPlatformCenterNumber(summary.total_views);
  if ($("video-manage-likes")) $("video-manage-likes").textContent = formatPlatformCenterNumber(summary.total_likes);
  if ($("video-manage-revenue")) $("video-manage-revenue").textContent = formatPlatformCenterNumber(summary.total_revenue_points);
  if ($("video-manage-platform-fee")) $("video-manage-platform-fee").textContent = formatPlatformCenterNumber(summary.total_platform_fee_points);
  if ($("video-manage-boost")) $("video-manage-boost").textContent = formatPlatformCenterNumber(summary.total_boost_points);
  if (!videos.length) {
    list.innerHTML = '<p style="color:var(--muted);">目前沒有自己上傳的影音。</p>';
    return;
  }
  list.innerHTML = videos.map((video) => {
    const id = String(video.id || "");
    const boostActive = !!video.boost_active;
    const boostText = boostActive
      ? `曝光中 · 到期 ${sanitize(formatChatTime(video.boost_expires_at || ""))}`
      : "未加曝光";
    const statusClass = video.visibility === "public" ? "success" : (video.visibility === "unlisted" ? "info" : "muted");
    return `
      <div class="drive-file-row video-manage-row" data-video-manage-id="${sanitize(id)}">
        <div class="video-manage-main">
          <div class="video-manage-head">
            <strong>${sanitize(video.title || "未命名影音")}</strong>
            <span class="badge ${statusClass}">${sanitize(shareCenterVisibilityLabel(video.visibility))}</span>
            <span class="badge ${boostActive ? "info" : "muted"}">${boostText}</span>
          </div>
          <div class="video-manage-fields">
            <label class="field">
              <span>標題</span>
              <input type="text" maxlength="120" data-video-manage-title value="${sanitize(video.title || "")}" />
            </label>
            <label class="field">
              <span>可見性</span>
              <select data-video-manage-visibility>
                <option value="public" ${video.visibility === "public" ? "selected" : ""}>公開</option>
                <option value="unlisted" ${video.visibility === "unlisted" ? "selected" : ""}>持連結</option>
                <option value="private" ${video.visibility === "private" ? "selected" : ""}>私人</option>
              </select>
            </label>
            <label class="field video-manage-description-field">
              <span>說明</span>
              <textarea rows="2" maxlength="2000" data-video-manage-description>${sanitize(video.description || "")}</textarea>
            </label>
          </div>
          <div class="video-manage-metrics" aria-label="影音成效">
            <span>觀看 ${formatPlatformCenterNumber(video.view_count)}</span>
            <span>按讚 ${formatPlatformCenterNumber(video.like_count)}</span>
            <span>留言 ${formatPlatformCenterNumber(video.comment_count)}</span>
            <span>投幣 ${formatPlatformCenterPoints(video.gross_points)}</span>
            <span>實收 ${formatPlatformCenterPoints(video.revenue_points)}</span>
            <span>平台分潤 ${formatPlatformCenterPoints(video.platform_fee_points)}</span>
            <span>分享 ${formatPlatformCenterNumber(video.active_share_count)} / 開啟 ${formatPlatformCenterNumber(video.share_access_count)}</span>
          </div>
          <div class="drive-card-sub">建立 ${sanitize(formatChatTime(video.created_at || ""))} · 更新 ${sanitize(formatChatTime(video.updated_at || ""))} · 來源 ${sanitize(video.cloud_filename || video.cloud_file_id || "-")}</div>
        </div>
        <div class="drive-file-actions video-manage-actions">
          <button class="btn" type="button" data-video-manage-open="${sanitize(id)}">觀看</button>
          <button class="btn" type="button" data-video-manage-links="${sanitize(id)}">分享設定</button>
          <button class="btn btn-primary" type="button" data-video-manage-save="${sanitize(id)}">儲存</button>
          <label class="video-manage-boost-control" title="花積分提升影音在平台列表中的排序曝光，曝光到期後可再次加值。">
            <input type="number" min="10" step="10" value="100" data-video-manage-boost-amount />
            <button class="btn" type="button" data-video-manage-boost="${sanitize(id)}">加曝光</button>
          </label>
          <button class="btn btn-danger" type="button" data-video-manage-delete="${sanitize(id)}">刪除</button>
        </div>
      </div>
    `;
  }).join("");
  list.querySelectorAll("[data-video-manage-open]").forEach((btn) => {
    btn.addEventListener("click", () => openManagedVideo(btn.dataset.videoManageOpen || ""));
  });
  list.querySelectorAll("[data-video-manage-links]").forEach((btn) => {
    btn.addEventListener("click", () => setShareCenterTab("links"));
  });
  list.querySelectorAll("[data-video-manage-save]").forEach((btn) => {
    btn.addEventListener("click", () => saveManagedVideo(btn.dataset.videoManageSave || ""));
  });
  list.querySelectorAll("[data-video-manage-boost]").forEach((btn) => {
    btn.addEventListener("click", () => boostManagedVideo(btn.dataset.videoManageBoost || ""));
  });
  list.querySelectorAll("[data-video-manage-delete]").forEach((btn) => {
    btn.addEventListener("click", () => deleteManagedVideo(btn.dataset.videoManageDelete || ""));
  });
}

async function loadVideoManageCenter() {
  if (!currentUser) return;
  platformCenterSetMsg("video-manage-msg", "正在讀取自己的影音...", true);
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/videos/manage?limit=120", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("video-manage-msg", json.msg || "我的影音讀取失敗", false);
      renderVideoManageCenter({ videos: [] });
      return;
    }
    renderVideoManageCenter(json);
    platformCenterSetMsg("video-manage-msg", `已載入 ${(json.videos || []).length} 支影音`, true);
  } catch (_) {
    platformCenterSetMsg("video-manage-msg", "我的影音讀取失敗，請稍後再試。", false);
  }
}

async function saveManagedVideo(videoId) {
  const row = videoManageRow(videoId);
  if (!row) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const payload = {
    title: row.querySelector("[data-video-manage-title]")?.value || "",
    description: row.querySelector("[data-video-manage-description]")?.value || "",
    visibility: row.querySelector("[data-video-manage-visibility]")?.value || "public"
  };
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/manage`, {
      method: "PUT",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf || ""
      },
      body: JSON.stringify(payload)
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("video-manage-msg", json.msg || "影音更新失敗", false);
      return;
    }
    platformCenterSetMsg("video-manage-msg", "影音資料已更新", true);
    await loadVideoManageCenter();
  } catch (_) {
    platformCenterSetMsg("video-manage-msg", "影音更新失敗，請稍後再試。", false);
  }
}

async function deleteManagedVideo(videoId) {
  if (!videoId || !confirm("確定要刪除這支影音？分享連結也會失效。")) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/manage`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("video-manage-msg", json.msg || "影音刪除失敗", false);
      return;
    }
    platformCenterSetMsg("video-manage-msg", "影音已刪除", true);
    await loadVideoManageCenter();
  } catch (_) {
    platformCenterSetMsg("video-manage-msg", "影音刪除失敗，請稍後再試。", false);
  }
}

async function boostManagedVideo(videoId) {
  const row = videoManageRow(videoId);
  if (!row) return;
  const amount = Number(row.querySelector("[data-video-manage-boost-amount]")?.value || 0);
  if (!Number.isFinite(amount) || amount < 10) {
    platformCenterSetMsg("video-manage-msg", "曝光積分至少 10 點", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const idempotency = typeof makeVideoIdempotencyKey === "function"
    ? makeVideoIdempotencyKey("video-boost")
    : `video-boost:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/boost`, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf || "",
        "Idempotency-Key": idempotency
      },
      body: JSON.stringify({ amount, idempotency_key: idempotency })
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      platformCenterSetMsg("video-manage-msg", json.msg || "曝光加值失敗", false);
      return;
    }
    platformCenterSetMsg("video-manage-msg", `已投入 ${formatPlatformCenterPoints(amount)} 增加曝光`, true);
    await loadVideoManageCenter();
  } catch (_) {
    platformCenterSetMsg("video-manage-msg", "曝光加值失敗，請稍後再試。", false);
  }
}

async function openManagedVideo(videoId) {
  if (!videoId) return;
  if (typeof switchModuleTab === "function") switchModuleTab("videos");
  if (typeof openVideoDetail === "function") {
    await openVideoDetail(videoId);
  }
}

document.addEventListener("click", (event) => {
  const tab = event.target?.closest?.("[data-share-center-tab]");
  if (!tab) return;
  event.preventDefault();
  setShareCenterTab(tab.dataset.shareCenterTab || "links");
});

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
