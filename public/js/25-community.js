let communityBoards = [];
let communityAnnouncements = [];
let communityBoardReviews = [];
let communityThreadReviews = [];
let selectedCommunityBoardId = null;
let selectedCommunityThreadId = null;
let communityThreads = [];
let selectedCommunityBoard = null;
let selectedCommunityThread = null;
let communityBoardQuery = "";
let communityThreadQuery = "";
let communityThreadPage = 0;
let communityThreadLimit = 10;
let communityThreadTotal = 0;

function communityStatusLabel(status) {
  if (status === "approved") return "已開放";
  if (status === "pending") return "待審核";
  if (status === "rejected") return "已駁回";
  return status || "未知";
}

function canManageCommunity() {
  return currentRole === "manager" || currentRole === "super_admin";
}

function canDeleteCommunityItem(authorUserId, ownerUserId) {
  if (canManageCommunity()) return true;
  return Number(currentUserId) === Number(authorUserId) || Number(currentUserId) === Number(ownerUserId);
}

function communityReactionButton(post, value, label) {
  const active = Number(post.user_reaction || 0) === Number(value);
  return `<button class="btn community-mini-btn${active ? " active" : ""}" type="button" data-community-reaction="${post.id}" data-reaction-value="${value}">${label} ${value === 1 ? (post.like_count || 0) : (post.dislike_count || 0)}</button>`;
}

function renderCommunityAnnouncements() {
  const list = $("community-announcement-list");
  const editor = $("community-announcement-editor");
  if (editor) editor.style.display = (currentRole === "manager" || currentRole === "super_admin") ? "block" : "none";
  if (!list) return;
  if (!communityAnnouncements.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有公告</p>";
    return;
  }
  list.innerHTML = communityAnnouncements.map((item) => `
    <div class="community-card">
      <div class="community-card-head">
        <strong>${item.is_pinned ? "📌 " : ""}${sanitize(item.title || "")}</strong>
        ${(currentRole === "manager" || currentRole === "super_admin") ? `<button class="btn community-mini-btn" type="button" data-del-announcement="${item.id}">刪除</button>` : ""}
      </div>
      <div class="community-meta">${sanitize(item.author_username || "")} · ${sanitize(formatChatTime(item.created_at || ""))}</div>
      <div class="community-body">${sanitize(item.content || "")}</div>
    </div>
  `).join("");
  list.querySelectorAll("button[data-del-announcement]").forEach((btn) => {
    btn.addEventListener("click", () => deleteAnnouncement(parseInt(btn.getAttribute("data-del-announcement"), 10)));
  });
}

function renderCommunityBoardReviews() {
  const panel = $("community-board-review-panel");
  const list = $("community-board-review-list");
  const canReview = currentRole === "manager" || currentRole === "super_admin";
  if (panel) panel.style.display = canReview ? "block" : "none";
  if (!list || !canReview) return;
  if (!communityBoardReviews.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有待審核討論區</p>";
    return;
  }
  list.innerHTML = communityBoardReviews.map((item) => `
    <div class="community-card">
      <div class="community-card-head">
        <strong>${sanitize(item.title || "")}</strong>
        <span class="community-badge pending">${communityStatusLabel(item.status)}</span>
      </div>
      <div class="community-meta">申請者：${sanitize(item.owner_username || "")} · ${sanitize(formatChatTime(item.created_at || ""))}</div>
      <div class="community-body">${sanitize(item.description || "")}</div>
      <div class="community-actions">
        <button class="btn btn-primary" type="button" data-board-review="${item.id}" data-board-action="approve">核准</button>
        <button class="btn" type="button" data-board-review="${item.id}" data-board-action="reject">駁回</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("button[data-board-review]").forEach((btn) => {
    btn.addEventListener("click", () => reviewCommunityBoard(
      parseInt(btn.getAttribute("data-board-review"), 10),
      btn.getAttribute("data-board-action")
    ));
  });
}

function renderCommunityThreadReviews() {
  const panel = $("community-thread-review-panel");
  const list = $("community-thread-review-list");
  const canReview = currentRole === "manager" || currentRole === "super_admin";
  if (panel) panel.style.display = canReview ? "block" : "none";
  if (!list || !canReview) return;
  if (!communityThreadReviews.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有待審核主題</p>";
    return;
  }
  list.innerHTML = communityThreadReviews.map((item) => `
    <div class="community-card">
      <div class="community-card-head">
        <strong>${sanitize(item.title || "")}</strong>
        <span class="community-badge pending">${communityStatusLabel(item.status)}</span>
      </div>
      <div class="community-meta">作者：${sanitize(item.author_username || "")} · ${sanitize(formatChatTime(item.created_at || ""))}</div>
      <div class="community-body">${sanitize(item.content || "")}</div>
      <div class="community-actions">
        <button class="btn btn-primary" type="button" data-thread-review="${item.id}" data-thread-action="approve">核准公開</button>
        <button class="btn" type="button" data-thread-review="${item.id}" data-thread-action="reject">駁回</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("button[data-thread-review]").forEach((btn) => {
    btn.addEventListener("click", () => reviewCommunityThread(
      parseInt(btn.getAttribute("data-thread-review"), 10),
      btn.getAttribute("data-thread-action")
    ));
  });
}

function renderCommunityBoards() {
  const list = $("community-board-list");
  if (!list) return;
  const query = communityBoardQuery.trim().toLowerCase();
  const visibleBoards = communityBoards.filter((board) => {
    if (!query) return true;
    return [board.title, board.description, board.rules, board.owner_username].some((v) => String(v || "").toLowerCase().includes(query));
  });
  if (!visibleBoards.length) {
    list.innerHTML = "<p style='color:var(--muted);'>目前沒有討論區</p>";
    return;
  }
  list.innerHTML = visibleBoards.map((board) => `
    <button class="community-board-item${Number(selectedCommunityBoardId) === Number(board.id) ? " active" : ""}" type="button" data-open-board="${board.id}">
      <div class="community-card-head">
        <strong>${sanitize(board.title || "")}</strong>
        <span class="community-badge ${sanitize(board.status || "")}">${communityStatusLabel(board.status)}</span>
      </div>
      <div class="community-meta">版主：${sanitize(board.owner_username || "")}</div>
      <div class="community-body">${sanitize(board.description || "")}</div>
      <div class="community-meta">主題 ${board.thread_count || 0} · 留言 ${board.post_count || 0}</div>
    </button>
  `).join("");
  list.querySelectorAll("button[data-open-board]").forEach((btn) => {
    btn.addEventListener("click", () => openCommunityBoard(parseInt(btn.getAttribute("data-open-board"), 10)));
  });
}

function renderCommunityThreads(board) {
  const heading = $("community-board-heading");
  const meta = $("community-board-meta");
  const list = $("community-thread-list");
  const creator = $("community-thread-creator");
  const rulesView = $("community-board-rules-view");
  const pageInfo = $("community-thread-page-info");
  const prevBtn = $("community-thread-prev");
  const nextBtn = $("community-thread-next");
  const submitBtn = $("community-thread-submit");
  if (heading) heading.textContent = board ? board.title : "請先選擇討論區";
  if (meta) {
    meta.textContent = board
      ? `${board.owner_username || "-"} · ${communityStatusLabel(board.status)}${board.review_note ? ` · ${board.review_note}` : ""}`
      : "";
  }
  if (rulesView) {
    if (board && board.rules) {
      rulesView.style.display = "block";
      rulesView.textContent = `版規：${board.rules}`;
    } else {
      rulesView.style.display = "none";
      rulesView.textContent = "";
    }
  }
  if (pageInfo) pageInfo.textContent = board ? `第 ${communityThreadPage + 1} 頁` : "第 1 頁";
  if (prevBtn) prevBtn.disabled = communityThreadPage <= 0;
  if (nextBtn) nextBtn.disabled = ((communityThreadPage + 1) * communityThreadLimit) >= communityThreadTotal;
  if (creator) creator.style.display = board && board.status === "approved" ? "block" : "none";
  if (submitBtn) submitBtn.textContent = (currentRole === "manager" || currentRole === "super_admin") ? "發布主題" : "送審主題";
  if (!list) return;
  if (!board) {
    list.innerHTML = "<p style='color:var(--muted);'>請先選擇左側討論區</p>";
    return;
  }
  if (!communityThreads.length) {
    list.innerHTML = "<p style='color:var(--muted);'>這個討論區尚無主題</p>";
    return;
  }
  list.innerHTML = communityThreads.map((thread) => `
    <button class="community-thread-item${Number(selectedCommunityThreadId) === Number(thread.id) ? " active" : ""}" type="button" data-open-thread="${thread.id}">
      <strong>${sanitize(thread.title || "")}</strong>
      <div class="community-meta">${sanitize(thread.author_username || "")} · ${sanitize(formatChatTime(thread.created_at || ""))}</div>
      <div class="community-meta">${communityStatusLabel(thread.status)}${thread.review_note ? ` · ${sanitize(thread.review_note)}` : ""}</div>
      <div class="community-body">${sanitize((thread.content || "").slice(0, 140))}${(thread.content || "").length > 140 ? "..." : ""}</div>
      <div class="community-meta">回覆 ${thread.reply_count || 0}</div>
    </button>
  `).join("");
  list.querySelectorAll("button[data-open-thread]").forEach((btn) => {
    btn.addEventListener("click", () => openCommunityThread(parseInt(btn.getAttribute("data-open-thread"), 10)));
  });
}

function renderCommunityThreadDetail(thread, posts) {
  const heading = $("community-thread-heading");
  const detail = $("community-thread-detail");
  const replyBox = $("community-reply-box");
  const lockTools = $("community-thread-lock-tools");
  const lockToggle = $("community-thread-lock-toggle");
  const deleteThreadBtn = $("community-thread-delete-btn");
  if (heading) heading.textContent = thread ? thread.title : "主題內容";
  if (replyBox) replyBox.style.display = thread && thread.board_status === "approved" && thread.status === "approved" && !thread.is_locked ? "block" : "none";
  if (lockTools) lockTools.style.display = thread && (canManageCommunity() || canDeleteCommunityItem(thread.author_user_id)) ? "flex" : "none";
  if (lockToggle && thread) lockToggle.textContent = thread.is_locked ? "解除鎖定" : "鎖定主題";
  if (lockToggle) lockToggle.style.display = thread && canManageCommunity() ? "" : "none";
  if (deleteThreadBtn) deleteThreadBtn.style.display = thread && canDeleteCommunityItem(thread.author_user_id) ? "" : "none";
  if (!detail) return;
  if (!thread) {
    detail.innerHTML = "<p style='color:var(--muted);'>請選擇主題以查看內容與留言</p>";
    return;
  }
  const replies = Array.isArray(posts) && posts.length
    ? posts.map((post) => `
        <div class="community-card${post.is_hidden ? " community-hidden-post" : ""}">
          <div class="community-card-head">
            <div class="community-meta">${post.is_pinned ? "置頂 · " : ""}${sanitize(post.author_username || "")} · ${sanitize(formatChatTime(post.created_at || ""))}${post.is_hidden ? ` · 已隱藏：${sanitize(post.hidden_reason || "")}` : ""}</div>
            <div style="display:flex;gap:.35rem;flex-wrap:wrap;justify-content:flex-end;">
              ${canManageCommunity() ? `<button class="btn community-mini-btn" type="button" data-pin-community-post="${post.id}" data-pinned="${post.is_pinned ? "1" : "0"}">${post.is_pinned ? "取消置頂" : "置頂"}</button>` : ""}
              ${canDeleteCommunityItem(post.author_user_id, thread.author_user_id) ? `<button class="btn community-mini-btn" type="button" data-delete-community-post="${post.id}">刪除</button>` : ""}
            </div>
          </div>
          <div class="community-body">${sanitize(post.content || "")}</div>
          <div class="community-actions" style="margin-top:.45rem;">
            ${communityReactionButton(post, 1, "讚")}
            ${communityReactionButton(post, -1, "倒讚")}
          </div>
        </div>
      `).join("")
    : "<p style='color:var(--muted);'>尚無留言</p>";
  detail.innerHTML = `
    <div class="community-card">
      <div class="community-meta">${sanitize(thread.author_username || "")} · ${sanitize(formatChatTime(thread.created_at || ""))} · ${sanitize(thread.board_title || "")}${thread.is_locked ? " · 已鎖定" : ""}</div>
      <div class="community-meta">${communityStatusLabel(thread.status)}${thread.review_note ? ` · ${sanitize(thread.review_note)}` : ""}</div>
      <div class="community-body">${sanitize(thread.content || "")}</div>
    </div>
    <div class="mini-title" style="margin:.8rem 0 .45rem;">留言區</div>
    ${replies}
  `;
  detail.querySelectorAll("button[data-delete-community-post]").forEach((btn) => {
    btn.addEventListener("click", () => deleteCommunityPost(parseInt(btn.getAttribute("data-delete-community-post"), 10)));
  });
  detail.querySelectorAll("button[data-pin-community-post]").forEach((btn) => {
    btn.addEventListener("click", () => toggleCommunityPostPin(
      parseInt(btn.getAttribute("data-pin-community-post"), 10),
      btn.getAttribute("data-pinned") !== "1"
    ));
  });
  detail.querySelectorAll("button[data-community-reaction]").forEach((btn) => {
    btn.addEventListener("click", () => reactToCommunityPost(
      parseInt(btn.getAttribute("data-community-reaction"), 10),
      parseInt(btn.getAttribute("data-reaction-value"), 10)
    ));
  });
}

async function loadAnnouncements() {
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/announcements", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  communityAnnouncements = Array.isArray(json.announcements) ? json.announcements : [];
  renderCommunityAnnouncements();
}

async function publishAnnouncement() {
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/announcements", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({
      title: $("community-announcement-title")?.value || "",
      content: $("community-announcement-content")?.value || "",
      is_pinned: !!$("community-announcement-pinned")?.checked
    })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "公告發布失敗", !!json.ok);
  if (json.ok) {
    if ($("community-announcement-title")) $("community-announcement-title").value = "";
    if ($("community-announcement-content")) $("community-announcement-content").value = "";
    if ($("community-announcement-pinned")) $("community-announcement-pinned").checked = false;
    await loadAnnouncements();
  }
}

async function deleteAnnouncement(id) {
  if (!confirm("確定要刪除這則公告？")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/announcements/" + id, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "公告刪除失敗", !!json.ok);
  if (json.ok) await loadAnnouncements();
}

async function loadCommunityBoards() {
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/boards", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  communityBoards = Array.isArray(json.boards) ? json.boards : [];
  const requestPanel = $("community-board-request-panel");
  if (requestPanel) requestPanel.style.display = (currentRole === "manager" || currentRole === "super_admin") ? "block" : "none";
  renderCommunityBoards();
  selectedCommunityBoard = communityBoards.find((item) => Number(item.id) === Number(selectedCommunityBoardId)) || null;
  renderCommunityThreads(selectedCommunityBoard);
}

async function requestCommunityBoard() {
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/boards", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({
      title: $("community-board-title")?.value || "",
      description: $("community-board-description")?.value || "",
      rules: $("community-board-rules")?.value || ""
    })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-board-request-msg"), json.msg || "申請送出失敗", !!json.ok);
  if (json.ok) {
    if ($("community-board-title")) $("community-board-title").value = "";
    if ($("community-board-description")) $("community-board-description").value = "";
    if ($("community-board-rules")) $("community-board-rules").value = "";
    await loadCommunityBoards();
    if (currentRole === "manager" || currentRole === "super_admin") await loadCommunityBoardReviews();
  }
}

async function loadCommunityBoardReviews() {
  if (!(currentRole === "manager" || currentRole === "super_admin")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/boards/reviews", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  communityBoardReviews = Array.isArray(json.items) ? json.items : [];
  renderCommunityBoardReviews();
}

async function loadCommunityThreadReviews() {
  if (!(currentRole === "manager" || currentRole === "super_admin")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/threads/reviews", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) return;
  communityThreadReviews = Array.isArray(json.items) ? json.items : [];
  renderCommunityThreadReviews();
}

async function reviewCommunityBoard(boardId, action) {
  await fetchCsrfToken({ force: true });
  const note = prompt(action === "approve" ? "核准備註（可留空）" : "駁回原因（可留空）", "") || "";
  const res = await fetch(API + "/community/boards/" + boardId + "/review", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({ action, note })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "審核失敗", !!json.ok);
  if (json.ok) {
    await Promise.all([loadCommunityBoardReviews(), loadCommunityBoards()]);
  }
}

async function reviewCommunityThread(threadId, action) {
  await fetchCsrfToken({ force: true });
  const note = prompt(action === "approve" ? "核准備註（可留空）" : "駁回原因（可留空）", "") || "";
  const res = await fetch(API + "/community/threads/" + threadId + "/review", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({ action, note })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "主題審核失敗", !!json.ok);
  if (json.ok) {
    await Promise.all([loadCommunityThreadReviews(), loadCommunityBoards()]);
    if (selectedCommunityBoardId) await openCommunityBoard(selectedCommunityBoardId);
  }
}

async function openCommunityBoard(boardId) {
  selectedCommunityBoardId = boardId;
  selectedCommunityThreadId = null;
  selectedCommunityThread = null;
  communityThreadPage = 0;
  await fetchCsrfToken({ force: true });
  const q = encodeURIComponent(communityThreadQuery || "");
  const res = await fetch(API + "/community/boards/" + boardId + "/threads?page=" + communityThreadPage + "&limit=" + communityThreadLimit + "&q=" + q, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    flash($("community-msg"), json.msg || "討論區讀取失敗", false);
    return;
  }
  const board = json.board || null;
  selectedCommunityBoard = board;
  communityThreads = Array.isArray(json.threads) ? json.threads : [];
  communityThreadTotal = Number(json.total || 0);
  communityThreadPage = Number(json.page || 0);
  renderCommunityBoards();
  renderCommunityThreads(board);
  renderCommunityThreadDetail(null, []);
}

async function createCommunityThread() {
  if (!selectedCommunityBoardId) {
    flash($("community-msg"), "請先選擇討論區", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/boards/" + selectedCommunityBoardId + "/threads", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({
      title: $("community-thread-title")?.value || "",
      content: $("community-thread-content")?.value || ""
    })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "主題建立失敗", !!json.ok);
  if (json.ok) {
    if ($("community-thread-title")) $("community-thread-title").value = "";
    if ($("community-thread-content")) $("community-thread-content").value = "";
    await openCommunityBoard(selectedCommunityBoardId);
    if (currentRole !== "manager" && currentRole !== "super_admin") {
      flash($("community-msg"), json.msg || "主題已送審", true);
    } else {
      await loadCommunityThreadReviews();
    }
  }
}

async function openCommunityThread(threadId) {
  selectedCommunityThreadId = threadId;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/threads/" + threadId, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    flash($("community-msg"), json.msg || "主題讀取失敗", false);
    return;
  }
  selectedCommunityThread = json.thread || null;
  renderCommunityThreads(selectedCommunityBoard || communityBoards.find((item) => Number(item.id) === Number(selectedCommunityBoardId)) || null);
  renderCommunityThreadDetail(selectedCommunityThread, json.posts || []);
}

async function replyCommunityThread() {
  if (!selectedCommunityThreadId) {
    flash($("community-msg"), "請先選擇主題", false);
    return;
  }
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/threads/" + selectedCommunityThreadId + "/posts", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({
      content: $("community-reply-content")?.value || ""
    })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "留言送出失敗", !!json.ok);
  if (json.ok) {
    if ($("community-reply-content")) $("community-reply-content").value = "";
    await openCommunityThread(selectedCommunityThreadId);
    await openCommunityBoard(selectedCommunityBoardId);
  }
}

async function deleteCommunityThread() {
  if (!selectedCommunityThreadId) return;
  if (!confirm("確定要刪除此主題？回覆也會一併刪除。")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/threads/" + selectedCommunityThreadId, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "主題刪除失敗", !!json.ok);
  if (json.ok) {
    selectedCommunityThreadId = null;
    selectedCommunityThread = null;
    renderCommunityThreadDetail(null, []);
    if (selectedCommunityBoardId) await openCommunityBoard(selectedCommunityBoardId);
  }
}

async function deleteCommunityPost(postId) {
  if (!postId) return;
  if (!confirm("確定要刪除此留言？")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/posts/" + postId, {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "留言刪除失敗", !!json.ok);
  if (json.ok && selectedCommunityThreadId) {
    await openCommunityThread(selectedCommunityThreadId);
    if (selectedCommunityBoardId) await openCommunityBoard(selectedCommunityBoardId);
  }
}

async function toggleCommunityPostPin(postId, pinned) {
  if (!postId) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/posts/" + postId + "/pin", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({ pinned })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "留言置頂更新失敗", !!json.ok);
  if (json.ok && selectedCommunityThreadId) {
    await openCommunityThread(selectedCommunityThreadId);
  }
}

async function reactToCommunityPost(postId, value) {
  if (!postId) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/posts/" + postId + "/reaction", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({ value })
  });
  const json = await res.json().catch(() => ({}));
  if (json.ok) {
    if (json.auto_hidden) {
      flash($("community-msg"), "留言倒讚過多，已自動隱藏並送 root 審核", false);
    }
    if (selectedCommunityThreadId) await openCommunityThread(selectedCommunityThreadId);
    return;
  }
  flash($("community-msg"), json.msg || "反應更新失敗", false);
}

async function toggleCommunityThreadLock() {
  if (!selectedCommunityThreadId || !selectedCommunityThread) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/community/threads/" + selectedCommunityThreadId + "/lock", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
    body: JSON.stringify({ locked: !selectedCommunityThread.is_locked })
  });
  const json = await res.json().catch(() => ({}));
  flash($("community-msg"), json.msg || "主題狀態更新失敗", !!json.ok);
  if (json.ok) {
    await openCommunityThread(selectedCommunityThreadId);
    await openCommunityBoard(selectedCommunityBoardId);
  }
}

async function loadCommunityHome() {
  await Promise.all([
    loadAnnouncements(),
    loadCommunityBoards(),
    (currentRole === "manager" || currentRole === "super_admin") ? loadCommunityBoardReviews() : Promise.resolve(),
    (currentRole === "manager" || currentRole === "super_admin") ? loadCommunityThreadReviews() : Promise.resolve(),
  ]);
}
