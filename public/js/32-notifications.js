'use strict';

const NOTIFICATION_POLL_MS = 30000;

function setNotificationBadge(count) {
  const badge = $("notification-badge");
  if (!badge) return;
  const n = Math.max(0, parseInt(count || 0, 10));
  badge.textContent = n > 99 ? "99+" : String(n);
  badge.style.display = n > 0 ? "inline-flex" : "none";
  const readAll = $("notification-read-all");
  if (readAll) {
    readAll.disabled = n <= 0;
    readAll.textContent = n > 0 ? `全部已讀 (${n})` : "全部已讀";
  }
}

function renderNotifications(items, unreadCount) {
  setNotificationBadge(unreadCount);
  const list = $("notification-list");
  if (!list) return;
  const notifications = Array.isArray(items) ? items : [];
  if (!notifications.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有通知</p>";
    return;
  }
  list.innerHTML = notifications.map((item) => {
    const cls = item.is_read ? "notification-item" : "notification-item unread";
    const readAction = item.is_read
      ? ""
      : `<button class="btn" type="button" data-notification-read="${item.id}" style="width:auto;padding:.35rem .55rem;font-size:.72rem;">已讀</button>`;
    const link = item.link
      ? `<div class="notification-meta">連結：${sanitize(item.link)}</div>`
      : "";
    return `
      <div class="${cls}">
        <div class="notification-title">
          <span>${sanitize(item.title || "通知")}</span>
          ${readAction}
        </div>
        <div class="notification-body">${sanitize(item.body || "")}</div>
        <div class="notification-meta">${sanitize(formatChatTime(item.created_at || ""))} · ${sanitize(item.type || "system")}</div>
        ${link}
      </div>
    `;
  }).join("");
  list.querySelectorAll("button[data-notification-read]").forEach((btn) => {
    btn.addEventListener("click", () => markNotificationRead(parseInt(btn.getAttribute("data-notification-read"), 10)));
  });
}

async function loadNotifications() {
  if (!currentUser) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  try {
    const res = await apiFetch(API + "/notifications?limit=20", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      if (res.status === 503) setNotificationBadge(0);
      const list = $("notification-list");
      if (notificationsOpen && list) {
        list.innerHTML = `<p style="color:#ffb74d;">${sanitize(json.msg || "通知讀取失敗，請稍後重試。")}</p>`;
      }
      return;
    }
    renderNotifications(json.notifications, json.unread_count);
  } catch (_) {
    const list = $("notification-list");
    if (notificationsOpen && list) {
      list.innerHTML = "<p style='color:#ffb74d;'>通知讀取失敗，請稍後重試。</p>";
    }
  }
}

async function markNotificationRead(notificationId) {
  if (!currentUser || !notificationId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/notifications/${notificationId}/read`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    alert(json.msg || "通知已讀更新失敗");
    return;
  }
  await loadNotifications();
}

async function markAllNotificationsRead() {
  if (!currentUser) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/notifications/read-all", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    alert(json.msg || "全部已讀失敗");
    return;
  }
  await loadNotifications();
}

function toggleNotificationPanel() {
  const panel = $("notification-panel");
  if (!panel) return;
  notificationsOpen = !notificationsOpen;
  panel.classList.toggle("show", notificationsOpen);
  if (notificationsOpen) loadNotifications();
}

function closeNotificationPanel() {
  notificationsOpen = false;
  const panel = $("notification-panel");
  if (panel) panel.classList.remove("show");
}

function startNotificationPoll() {
  stopNotificationPoll();
  loadNotifications();
  notificationPollTimer = setInterval(loadNotifications, NOTIFICATION_POLL_MS);
}

function stopNotificationPoll() {
  if (notificationPollTimer) {
    clearInterval(notificationPollTimer);
    notificationPollTimer = null;
  }
  closeNotificationPanel();
  setNotificationBadge(0);
}
