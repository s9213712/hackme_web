'use strict';

const videoState = {
  sort: "new",
  videos: [],
  current: null,
  viewRecordedFor: new Set(),
  browseLoaded: false,
};

function videoMsg(text, ok = true) {
  const el = $("video-msg");
  if (el) flash(el, text, ok);
}

function videoDisplayName(file) {
  return file.original_filename_plain_for_public || file.display_name || file.id || "影音檔";
}

function videoMime(file) {
  return String(file.mime_type_plain_for_public || file.mime_type || "").toLowerCase();
}

function isCloudMediaFile(file) {
  const name = videoDisplayName(file).toLowerCase();
  const mime = videoMime(file);
  return mime.startsWith("video/")
    || mime.startsWith("audio/")
    || [".mp4", ".m4v", ".mov", ".webm", ".ogv", ".avi", ".mkv", ".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg"].some((ext) => name.endsWith(ext));
}

function formatVideoCount(value, unit = "") {
  const number = Number(value || 0);
  if (number >= 10000) return `${(number / 10000).toFixed(1)}萬${unit}`;
  return `${number}${unit}`;
}

function videoVisibilityLabel(value) {
  if (value === "private") return "私人";
  if (value === "unlisted") return "持連結可看";
  return "公開";
}

function videoStreamUrl(video) {
  const id = Number(video?.id || 0);
  return video?.stream_url || (id ? `/api/videos/${id}/stream` : "");
}

function videoThumbMarkup(video) {
  if (video.cover_url) {
    return `
      <div class="video-thumb video-thumb-cover">
        <img class="video-thumb-image" src="${sanitize(video.cover_url)}" alt="${sanitize(video.title || "影音封面")}" loading="lazy" />
        <span class="video-thumb-play">${video.media_type === "audio" ? "♪" : "▶"}</span>
      </div>
    `;
  }
  const url = videoStreamUrl(video);
  if (video.media_type === "audio") {
    return `<div class="video-thumb video-thumb-audio"><span>♪</span></div>`;
  }
  if (!url) {
    return `<div class="video-thumb"><span>▶</span></div>`;
  }
  return `
    <div class="video-thumb video-thumb-media-wrap">
      <video class="video-thumb-media" muted playsinline preload="metadata" src="${sanitize(url)}#t=0.1" aria-hidden="true"></video>
      <span class="video-thumb-play">▶</span>
    </div>
  `;
}

function makeVideoIdempotencyKey(prefix = "video-tip") {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `${prefix}:${window.crypto.randomUUID()}`;
  }
  return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
}

function showVideoBrowseView({ updateHash = false } = {}) {
  const browse = $("video-browse-view");
  const watch = $("video-watch-view");
  const detail = $("video-detail");
  if (browse) browse.style.display = "";
  if (watch) watch.style.display = "none";
  if (detail) detail.innerHTML = "";
  videoState.current = null;
  if (updateHash && /^#videos\/\d+$/.test(location.hash || "")) {
    history.pushState(null, "", `${location.pathname}${location.search}#videos`);
  }
}

function showVideoWatchView() {
  const browse = $("video-browse-view");
  const watch = $("video-watch-view");
  if (browse) browse.style.display = "none";
  if (watch) watch.style.display = "";
}

async function loadVideoPublishFiles() {
  const select = $("video-publish-file");
  if (!select) return;
  select.innerHTML = `<option value="">讀取影音檔...</option>`;
  try {
    const res = await apiFetch(API + "/cloud-drive/files", { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    const files = (json.files || []).filter(isCloudMediaFile);
    select.innerHTML = files.length
      ? files.map((file) => `<option value="${sanitize(file.id)}">${sanitize(videoDisplayName(file))}</option>`).join("")
      : `<option value="">雲端硬碟目前沒有可發布的影音檔</option>`;
  } catch (err) {
    select.innerHTML = `<option value="">影音檔讀取失敗</option>`;
    videoMsg(err.message || "影音檔讀取失敗", false);
  }
}

async function publishVideoFromDrive() {
  const button = $("video-publish-btn");
  const directFile = $("video-upload-file")?.files?.[0] || null;
  const payload = {
    cloud_file_id: $("video-publish-file")?.value || "",
    title: ($("video-publish-title")?.value || "").trim(),
    description: ($("video-publish-description")?.value || "").trim(),
    visibility: $("video-publish-visibility")?.value || "public",
  };
  if (!directFile && !payload.cloud_file_id) return videoMsg("請選擇要直接上傳的影音檔，或選擇雲端硬碟中的影音檔", false);
  if (!payload.title && !directFile) return videoMsg("請輸入影音標題", false);
  if (button) button.disabled = true;
  try {
    let res;
    if (directFile) {
      const form = new FormData();
      const coverFile = $("video-cover-file")?.files?.[0] || null;
      form.append("video", directFile);
      form.append("title", payload.title || directFile.name.replace(/\.[^.]+$/, ""));
      form.append("description", payload.description);
      form.append("visibility", payload.visibility);
      form.append("privacy_mode", $("video-upload-privacy-mode")?.value || "standard_plain");
      if (coverFile) form.append("cover", coverFile);
      videoMsg("影音檔上傳中，請稍候...", true);
      res = await apiFetch(API + "/videos/upload", {
        method: "POST",
        credentials: "same-origin",
        body: form,
      });
    } else {
      res = await apiFetch(API + "/videos/publish", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    const input = $("video-upload-file");
    if (input) input.value = "";
    const coverInput = $("video-cover-file");
    if (coverInput) coverInput.value = "";
    videoMsg("影音已發布", true);
    await loadVideoPublishFiles();
    await loadVideos(videoState.sort);
    openVideoDetail(json.video.id);
  } catch (err) {
    videoMsg(err.message || "影音發布失敗", false);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderVideoList() {
  const list = $("video-list");
  if (!list) return;
  if (!videoState.videos.length) {
    list.innerHTML = `<div class="drive-empty">目前沒有可觀看的影音</div>`;
    return;
  }
  list.innerHTML = videoState.videos.map((video) => `
    <a class="video-card" href="#videos/${Number(video.id || 0)}" data-video-open="${Number(video.id || 0)}">
      ${videoThumbMarkup(video)}
      <div class="video-card-body">
        <strong>${sanitize(video.title || "未命名影片")}</strong>
        <div class="drive-card-sub">${sanitize(video.owner_nickname || video.owner_username || "使用者")} · ${formatVideoCount(video.view_count, " 次觀看")}</div>
        <div class="drive-card-sub">${sanitize(videoVisibilityLabel(video.visibility))} · 👍 ${formatVideoCount(video.like_count)} · 🪙 ${formatVideoCount(video.coin_total)}</div>
      </div>
    </a>
  `).join("");
}

async function loadVideos(sort = "new") {
  videoState.sort = sort;
  videoState.browseLoaded = true;
  const list = $("video-list");
  if (list) list.innerHTML = `<div class="drive-empty">影音載入中...</div>`;
  try {
    const res = await apiFetch(API + `/videos?sort=${encodeURIComponent(sort)}`, { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    videoState.videos = Array.isArray(json.videos) ? json.videos : [];
    renderVideoList();
  } catch (err) {
    if (list) list.innerHTML = `<div class="drive-empty">${sanitize(err.message || "影音列表載入失敗")}</div>`;
  }
}

function renderVideoComments(comments) {
  if (!comments || !comments.length) return `<div class="drive-empty">尚無留言</div>`;
  return comments.map((comment) => `
    <div class="video-comment ${comment.parent_id ? "video-comment-reply" : ""}">
      <strong>${sanitize(comment.nickname || comment.username || "使用者")}</strong>
      <p>${sanitize(comment.content || "")}</p>
      <small>${sanitize(comment.created_at || "")}</small>
    </div>
  `).join("");
}

function renderVideoDetail(video, comments = []) {
  const detail = $("video-detail");
  if (!detail) return;
  videoState.current = video;
  showVideoWatchView();
  const player = video.media_type === "audio"
    ? `<audio id="video-player" class="video-player video-audio-player" controls preload="metadata" src="${sanitize(video.stream_url || `/api/videos/${video.id}/stream`)}"></audio>`
    : `<video id="video-player" class="video-player" controls playsinline preload="metadata" src="${sanitize(video.stream_url || `/api/videos/${video.id}/stream`)}"></video>`;
  detail.innerHTML = `
    <div class="video-watch-topbar">
      <button class="btn btn-sm" type="button" id="video-back-btn">← 返回影音列表</button>
      <span class="drive-card-sub">獨立播放頁</span>
    </div>
    <div class="video-watch-layout">
      <div class="video-watch-main">
        ${player}
        <div class="drive-card-heading">
          <div>
            <div class="drive-card-title">${sanitize(video.title || "未命名影片")}</div>
            <div class="drive-card-sub">${sanitize(video.owner_nickname || video.owner_username || "使用者")} · ${formatVideoCount(video.view_count, " 次觀看")} · ${sanitize(videoVisibilityLabel(video.visibility))}</div>
          </div>
          <div class="drive-file-actions">
            <button class="btn" type="button" data-video-like="${Number(video.id || 0)}">${video.liked_by_me ? "取消讚" : "👍 按讚"}</button>
            <button class="btn" type="button" data-video-copy-link="${Number(video.id || 0)}">複製連結</button>
          </div>
        </div>
        <details class="drive-collapsible-panel" open>
          <summary>
            <span>
              <span class="drive-card-title">影音描述</span>
              <span class="drive-card-sub">再次點擊才會收合。</span>
            </span>
          </summary>
          <div class="drive-collapsible-body">${sanitize(video.description || "沒有描述")}</div>
        </details>
        <div class="video-actions-row">
          <input type="number" id="video-tip-amount" min="1" step="1" placeholder="投幣點數" />
          <button class="btn btn-primary" type="button" data-video-tip="${Number(video.id || 0)}">🪙 投幣</button>
        </div>
        <details class="drive-collapsible-panel" open>
          <summary>
            <span>
              <span class="drive-card-title">留言</span>
              <span class="drive-card-sub">${formatVideoCount(video.comment_count, " 則")}</span>
            </span>
          </summary>
          <div class="drive-collapsible-body">
            <textarea id="video-comment-content" rows="3" maxlength="1000" placeholder="留下文字留言"></textarea>
            <div class="drive-file-actions" style="justify-content:flex-start;margin:.5rem 0;">
              <button class="btn" type="button" data-video-comment="${Number(video.id || 0)}">送出留言</button>
            </div>
            <div id="video-comments-list">${renderVideoComments(comments)}</div>
          </div>
        </details>
      </div>
      <aside class="video-recommend">
        <div class="drive-card-title">推薦影片</div>
        ${(videoState.videos || []).filter((item) => Number(item.id) !== Number(video.id)).slice(0, 8).map((item) => `
          <button class="video-recommend-item" type="button" data-video-open="${Number(item.id || 0)}">
            <span class="video-recommend-thumb">${item.media_type === "audio" ? "♪" : "▶"}</span>
            <span>
              <strong>${sanitize(item.title || "未命名影片")}</strong>
              <small>${formatVideoCount(item.view_count, " 次觀看")}</small>
            </span>
          </button>
        `).join("") || `<div class="drive-empty">暫無推薦</div>`}
      </aside>
    </div>
  `;
  bindVideoPlayerView(video.id);
}

function bindVideoPlayerView(videoId) {
  const player = $("video-player");
  if (!player || !videoId) return;
  const key = String(videoId);
  const submitView = async (completed = false) => {
    if (videoState.viewRecordedFor.has(key) && !completed) return;
    videoState.viewRecordedFor.add(key);
    try {
      await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/view`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ watch_seconds: Math.floor(player.currentTime || 0), completed }),
      });
    } catch (_) {
      // View accounting must not interrupt playback.
    }
  };
  let timer = null;
  player.addEventListener("playing", () => {
    if (timer || videoState.viewRecordedFor.has(key)) return;
    timer = setTimeout(() => submitView(false), 6000);
  });
  player.addEventListener("ended", () => submitView(true));
}

async function openVideoDetail(videoId) {
  if (!videoId) return;
  const hash = `#videos/${encodeURIComponent(videoId)}`;
  if (location.hash !== hash) {
    history.pushState(null, "", `${location.pathname}${location.search}${hash}`);
  }
  showVideoWatchView();
  const detail = $("video-detail");
  if (detail) {
    detail.innerHTML = `<div class="drive-empty">影音載入中...</div>`;
  }
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}`, { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    renderVideoDetail(json.video, json.comments || []);
  } catch (err) {
    if (detail) detail.innerHTML = `<div class="drive-empty">${sanitize(err.message || "影音載入失敗")}</div>`;
  }
}

async function likeVideo(videoId) {
  const liked = !!(videoState.current && videoState.current.liked_by_me);
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/like`, {
      method: liked ? "DELETE" : "POST",
      credentials: "same-origin",
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    await loadVideos(videoState.sort);
    await openVideoDetail(videoId);
  } catch (err) {
    videoMsg(err.message || "按讚操作失敗", false);
  }
}

async function tipVideo(videoId) {
  const amount = Number($("video-tip-amount")?.value || 0);
  if (!Number.isFinite(amount) || amount < 1) return videoMsg("請輸入要投幣的點數", false);
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/tip`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Idempotency-Key": makeVideoIdempotencyKey() },
      body: JSON.stringify({ amount: Math.floor(amount) }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    videoMsg(`投幣成功：${Number(json.tip?.amount_points || amount)} 點`, true);
    await loadVideos(videoState.sort);
    await openVideoDetail(videoId);
  } catch (err) {
    videoMsg(err.message || "投幣失敗", false);
  }
}

async function addVideoComment(videoId) {
  const textarea = $("video-comment-content");
  const content = (textarea?.value || "").trim();
  if (!content) return videoMsg("請輸入留言內容", false);
  try {
    const res = await apiFetch(API + `/videos/${encodeURIComponent(videoId)}/comments`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    if (textarea) textarea.value = "";
    await openVideoDetail(videoId);
  } catch (err) {
    videoMsg(err.message || "留言失敗", false);
  }
}

async function copyVideoLink(videoId) {
  const url = `${location.origin}${location.pathname}#videos/${encodeURIComponent(videoId)}`;
  try {
    await navigator.clipboard.writeText(url);
    videoMsg("連結已複製", true);
  } catch (_) {
    videoMsg(url, true);
  }
}

async function loadVideoPlatform() {
  await Promise.all([loadVideos(videoState.sort), loadVideoPublishFiles()]);
  const hash = location.hash || "";
  const match = hash.match(/^#videos\/(\d+)$/);
  if (match) {
    openVideoDetail(match[1]);
  } else {
    showVideoBrowseView();
  }
}

function handleVideoHashRoute() {
  const match = (location.hash || "").match(/^#videos\/(\d+)$/);
  if (match) {
    if (!videoState.browseLoaded) {
      loadVideoPlatform();
    } else {
      openVideoDetail(match[1]);
    }
  } else if ((location.hash || "") === "#videos" && $("video-browse-view")) {
    showVideoBrowseView();
  }
}

window.addEventListener("hashchange", handleVideoHashRoute);

document.addEventListener("click", (event) => {
  const open = event.target.closest("[data-video-open]");
  if (open) {
    event.preventDefault();
    openVideoDetail(open.dataset.videoOpen);
    return;
  }
  const sort = event.target.closest("[data-video-sort]");
  if (sort) {
    loadVideos(sort.dataset.videoSort || "new");
    return;
  }
  const like = event.target.closest("[data-video-like]");
  if (like) {
    likeVideo(like.dataset.videoLike);
    return;
  }
  const tip = event.target.closest("[data-video-tip]");
  if (tip) {
    tipVideo(tip.dataset.videoTip);
    return;
  }
  const comment = event.target.closest("[data-video-comment]");
  if (comment) {
    addVideoComment(comment.dataset.videoComment);
    return;
  }
  const copy = event.target.closest("[data-video-copy-link]");
  if (copy) {
    copyVideoLink(copy.dataset.videoCopyLink);
    return;
  }
  if (event.target.closest("#video-refresh-btn")) {
    loadVideoPlatform();
    return;
  }
  if (event.target.closest("#video-back-btn")) {
    showVideoBrowseView({ updateHash: true });
    return;
  }
  if (event.target.closest("#video-publish-open-btn")) {
    const panel = $("video-publish-panel");
    if (panel) panel.open = !panel.open;
    loadVideoPublishFiles();
    return;
  }
  if (event.target.closest("#video-publish-btn")) {
    publishVideoFromDrive();
  }
});
