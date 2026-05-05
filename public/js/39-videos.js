'use strict';

const videoState = {
  sort: "new",
  videos: [],
  current: null,
  viewRecordedFor: new Set(),
  browseLoaded: false,
};
let videoPublishDriveFiles = [];
const VIDEO_SHARE_FRAGMENT_STORAGE_KEY = "hackme_web.video_share_fragments";

function videoMsg(text, ok = true) {
  const el = $("video-msg");
  if (el) flash(el, text, ok);
}

function loadVideoShareFragments() {
  try {
    return JSON.parse(sessionStorage.getItem(VIDEO_SHARE_FRAGMENT_STORAGE_KEY) || "{}") || {};
  } catch (_) {
    return {};
  }
}

function saveVideoShareFragments(data) {
  try {
    sessionStorage.setItem(VIDEO_SHARE_FRAGMENT_STORAGE_KEY, JSON.stringify(data || {}));
  } catch (_) {
    // ignore session storage failure
  }
}

function rememberVideoShareFragment(shareUrl, fragmentKey) {
  const url = String(shareUrl || "").trim();
  const fragment = String(fragmentKey || "").trim();
  if (!url || !fragment) return;
  const state = loadVideoShareFragments();
  state[url] = fragment;
  saveVideoShareFragments(state);
}

function getRememberedVideoShareFragment(shareUrl) {
  const state = loadVideoShareFragments();
  return String(state[String(shareUrl || "").trim()] || "").trim();
}

function forgetRememberedVideoShareFragment(shareUrl) {
  const state = loadVideoShareFragments();
  const key = String(shareUrl || "").trim();
  if (!key || !Object.prototype.hasOwnProperty.call(state, key)) return;
  delete state[key];
  saveVideoShareFragments(state);
}

function videoSelectedDriveFile() {
  const target = String($("video-publish-file")?.value || "");
  return videoPublishDriveFiles.find((file) => String(file?.id || "") === target) || null;
}

function videoShareBytesToBase64(bytes) {
  const buffer = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  let binary = "";
  for (let i = 0; i < buffer.length; i += 1) binary += String.fromCharCode(buffer[i]);
  return btoa(binary);
}

function videoShareBytesToBase64Url(bytes) {
  return videoShareBytesToBase64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function buildVideoE2eeShareEnvelope(fileId) {
  if (!window.crypto?.subtle || typeof fetchDriveE2eeKey !== "function" || typeof unwrapDriveFileKey !== "function" || typeof getDriveE2eeSessionPassphrase !== "function" || typeof rememberDriveE2eeSessionPassphrase !== "function") {
    throw new Error("目前瀏覽器無法建立 E2EE 影音分享授權。");
  }
  if (!getCsrfToken()) {
    await fetchCsrfToken();
  }
  const csrf = getCsrfToken() || "";
  const e2ee = await fetchDriveE2eeKey(fileId, csrf);
  const passphrase = await getDriveE2eeSessionPassphrase(
    fileId,
    "請輸入此 E2EE 影音原始加密密碼。密碼只會在瀏覽器端使用，用來建立分享授權。"
  );
  if (!passphrase) {
    throw new Error("E2EE 影音分享需要先輸入原始加密密碼。");
  }
  const fileKey = await unwrapDriveFileKey(e2ee.encrypted_file_key, passphrase);
  rememberDriveE2eeSessionPassphrase(fileId, passphrase);
  const rawFileKey = await window.crypto.subtle.exportKey("raw", fileKey);
  const shareKeyBytes = new Uint8Array(32);
  window.crypto.getRandomValues(shareKeyBytes);
  const shareKey = await window.crypto.subtle.importKey("raw", shareKeyBytes, { name: "AES-GCM", length: 256 }, false, ["encrypt"]);
  const nonce = new Uint8Array(12);
  window.crypto.getRandomValues(nonce);
  const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, shareKey, rawFileKey);
  return {
    share_wrapped_file_key_envelope: JSON.stringify({
      alg: "AES-GCM",
      v: 1,
      nonce: videoShareBytesToBase64(nonce),
      ciphertext: videoShareBytesToBase64(new Uint8Array(ciphertext)),
    }),
    share_fragment_key: videoShareBytesToBase64Url(shareKeyBytes),
  };
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

function videoPlaybackUrl(video) {
  const id = Number(video?.id || 0);
  return video?.playback_url || (id ? `/api/videos/${id}/playback` : "");
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
    videoPublishDriveFiles = files;
    select.innerHTML = files.length
      ? files.map((file) => `<option value="${sanitize(file.id)}">${sanitize(videoDisplayName(file))}</option>`).join("")
      : `<option value="">雲端硬碟目前沒有可發布的影音檔</option>`;
  } catch (err) {
    videoPublishDriveFiles = [];
    select.innerHTML = `<option value="">影音檔讀取失敗</option>`;
    videoMsg(err.message || "影音檔讀取失敗", false);
  }
}

async function publishVideoFromDrive() {
  const button = $("video-publish-btn");
  const directFile = $("video-upload-file")?.files?.[0] || null;
  const coverFile = $("video-cover-file")?.files?.[0] || null;
  const sharePassword = ($("video-share-password")?.value || "").trim();
  const selectedFile = directFile ? null : videoSelectedDriveFile();
  const payload = {
    cloud_file_id: $("video-publish-file")?.value || "",
    title: ($("video-publish-title")?.value || "").trim(),
    description: ($("video-publish-description")?.value || "").trim(),
    visibility: $("video-publish-visibility")?.value || "public",
    share_password: sharePassword,
    share_expires_at: ($("video-share-expires-at")?.value || "").trim(),
    share_max_views: ($("video-share-max-views")?.value || "").trim(),
  };
  if (!directFile && !payload.cloud_file_id) return videoMsg("請選擇要直接上傳的影音檔，或選擇雲端硬碟中的影音檔", false);
  if (!payload.title && !directFile) return videoMsg("請輸入影音標題", false);
  let e2eeShare = null;
  if (!directFile && selectedFile?.privacy_mode === "e2ee" && payload.visibility === "unlisted") {
    try {
      e2eeShare = await buildVideoE2eeShareEnvelope(selectedFile.id);
      payload.share_wrapped_file_key_envelope = e2eeShare.share_wrapped_file_key_envelope;
    } catch (err) {
      return videoMsg(err.message || "E2EE 影音分享授權建立失敗", false);
    }
  }
  if (button) button.disabled = true;
  try {
    let res;
    if (directFile) {
      const form = new FormData();
      form.append("video", directFile);
      form.append("title", payload.title || directFile.name.replace(/\.[^.]+$/, ""));
      form.append("description", payload.description);
      form.append("visibility", payload.visibility);
      form.append("share_password", payload.share_password);
      form.append("share_expires_at", payload.share_expires_at);
      form.append("share_max_views", payload.share_max_views);
      form.append("privacy_mode", $("video-upload-privacy-mode")?.value || "standard_plain");
      if (coverFile) form.append("cover", coverFile);
      videoMsg("影音檔上傳中，請稍候...", true);
      res = await apiFetch(API + "/videos/upload", {
        method: "POST",
        credentials: "same-origin",
        body: form,
      });
    } else if (coverFile) {
      const form = new FormData();
      form.append("cloud_file_id", payload.cloud_file_id);
      form.append("title", payload.title);
      form.append("description", payload.description);
      form.append("visibility", payload.visibility);
      form.append("share_password", payload.share_password);
      form.append("share_expires_at", payload.share_expires_at);
      form.append("share_max_views", payload.share_max_views);
      if (payload.share_wrapped_file_key_envelope) form.append("share_wrapped_file_key_envelope", payload.share_wrapped_file_key_envelope);
      form.append("cover", coverFile);
      videoMsg("影音封面上傳中，請稍候...", true);
      res = await apiFetch(API + "/videos/publish", {
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
    const shareInput = $("video-share-password");
    if (shareInput) shareInput.value = "";
    const shareMaxViews = $("video-share-max-views");
    if (shareMaxViews) shareMaxViews.value = "";
    const shareExpiresAt = $("video-share-expires-at");
    if (shareExpiresAt) shareExpiresAt.value = "";
    if (e2eeShare && json.video?.share_url) {
      rememberVideoShareFragment(json.video.share_url, e2eeShare.share_fragment_key);
    }
    if (json.stream_warning) {
      videoMsg(`影音已發布；${json.stream_warning}`, false);
    } else if (json.stream_asset?.status === "ready") {
      videoMsg("影音已發布，HLS 串流已就緒", true);
    } else if (json.stream_asset?.status === "processing") {
      videoMsg("影音已發布，HLS 串流準備中", true);
    } else {
      videoMsg("影音已發布", true);
    }
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

function hlsMimeForVideo(mediaType = "video") {
  return mediaType === "audio" ? "application/vnd.apple.mpegurl" : "application/vnd.apple.mpegurl";
}

function browserSupportsNativeHls(mediaType = "video") {
  const probe = document.createElement(mediaType === "audio" ? "audio" : "video");
  return !!(probe && typeof probe.canPlayType === "function" && probe.canPlayType(hlsMimeForVideo(mediaType)));
}

function playbackSourceForVideo(video, playback) {
  if (playback?.mode === "e2ee_direct") {
    return {
      mode: "e2ee_direct",
      src: "",
      statusText: "端到端加密影音會在瀏覽器端解密播放，速度會較慢。",
    };
  }
  if (!playback || playback.mode !== "hls") {
    return {
      mode: "direct",
      src: videoStreamUrl(video),
      statusText: "",
    };
  }
  if (browserSupportsNativeHls(video.media_type)) {
    return {
      mode: "hls",
      src: playback.master_url || playback.fallback_url || videoStreamUrl(video),
      statusText: "HLS 串流已啟用",
    };
  }
  return {
    mode: "direct",
    src: playback.fallback_url || videoStreamUrl(video),
    statusText: "目前瀏覽器不支援原生 HLS，已改用直接串流",
  };
}

function humanVideoStreamStatus(playback) {
  const status = playback?.status || {};
  const streamStatus = String(status.status || "").trim();
  if (streamStatus === "direct_only") return status.error_message || "此影音只支援瀏覽器端解密播放。";
  if (streamStatus === "ready") return "HLS 串流已就緒";
  if (streamStatus === "processing") return "HLS 串流準備中";
  if (streamStatus === "failed") return `HLS 串流失敗：${status.error_message || "請稍後重試"}`;
  if (streamStatus === "unavailable") return status.error_message || "目前檔案無法建立伺服器端串流衍生檔";
  if (streamStatus === "pending") return "目前尚未建立 HLS 串流，可先用直接串流播放";
  return "";
}

async function prepareVideoStream(fileId, videoId) {
  if (!fileId) return videoMsg("找不到對應影音檔案", false);
  const button = document.querySelector(`[data-video-prepare-stream="${String(fileId)}"]`);
  if (button) button.disabled = true;
  try {
    const res = await apiFetch(`/api/media/${encodeURIComponent(fileId)}/prepare-stream`, {
      method: "POST",
      credentials: "same-origin",
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    videoMsg("已更新 HLS 串流衍生檔", true);
    await openVideoDetail(videoId);
  } catch (err) {
    videoMsg(err.message || "HLS 串流準備失敗", false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function updateVideoShareLink(video, options = {}) {
  const payload = {};
  if (Object.prototype.hasOwnProperty.call(options, "share_password")) payload.share_password = options.share_password;
  if (Object.prototype.hasOwnProperty.call(options, "share_wrapped_file_key_envelope")) payload.share_wrapped_file_key_envelope = options.share_wrapped_file_key_envelope;
  if (Object.prototype.hasOwnProperty.call(options, "share_expires_at")) payload.share_expires_at = options.share_expires_at;
  if (Object.prototype.hasOwnProperty.call(options, "share_max_views")) payload.share_max_views = options.share_max_views;
  if (options.regenerate) payload.regenerate = true;
  const res = await apiFetch(`/api/videos/${encodeURIComponent(video.id)}/share-link`, {
    method: "PUT",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json;
}

async function regenerateVideoShareLink(video) {
  if (!video?.id || video?.visibility !== "unlisted") return;
  let e2eeShare = null;
  try {
    if (video.share_requires_fragment_key) {
      e2eeShare = await buildVideoE2eeShareEnvelope(video.cloud_file_id);
    }
    const json = await updateVideoShareLink(video, {
      regenerate: true,
      ...(e2eeShare ? { share_wrapped_file_key_envelope: e2eeShare.share_wrapped_file_key_envelope } : {}),
    });
    if (video.share_url) forgetRememberedVideoShareFragment(video.share_url);
    if (e2eeShare && json.share_link?.url) {
      rememberVideoShareFragment(json.share_link.url, e2eeShare.share_fragment_key);
    }
    videoMsg("分享連結已重新產生；若有舊連結請停止使用。", true);
    await loadVideos(videoState.sort);
    await openVideoDetail(video.id);
  } catch (err) {
    videoMsg(err.message || "重新產生分享連結失敗", false);
  }
}

async function revokeVideoShareLink(video) {
  if (!video?.id || !video?.share_url) return;
  try {
    const res = await apiFetch(`/api/videos/${encodeURIComponent(video.id)}/share-link`, {
      method: "DELETE",
      credentials: "same-origin",
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    forgetRememberedVideoShareFragment(video.share_url);
    videoMsg("分享連結已撤銷。", true);
    await loadVideos(videoState.sort);
    await openVideoDetail(video.id);
  } catch (err) {
    videoMsg(err.message || "撤銷分享連結失敗", false);
  }
}

async function hydrateVideoE2eePlayer(video, playback) {
  const player = $("video-player");
  if (!player) return;
  if (!getCsrfToken()) {
    await fetchCsrfToken();
  }
  const csrf = getCsrfToken() || "";
  const decrypted = await buildDriveE2eePreview(video.cloud_file_id, csrf);
  if (!decrypted?.blob) {
    throw new Error("E2EE 影音解密播放失敗");
  }
  player.src = URL.createObjectURL(decrypted.blob);
  const status = $("video-playback-status");
  if (status) {
    status.textContent = "已在瀏覽器端以原始 E2EE 密碼解密播放；本次登入 session 內密碼會暫存在瀏覽器記憶體。";
  }
}

function renderVideoDetail(video, comments = [], playback = null) {
  const detail = $("video-detail");
  if (!detail) return;
  videoState.current = video;
  showVideoWatchView();
  const playbackSource = playbackSourceForVideo(video, playback);
  const playbackStatus = playback?.status || {};
  const streamStatusText = humanVideoStreamStatus(playback);
  const streamActions = video.can_edit && playback?.mode !== "e2ee_direct"
    ? `
      <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.45rem;">
        <button class="btn btn-sm" type="button" data-video-prepare-stream="${sanitize(video.cloud_file_id || "")}">
          ${playbackStatus.status === "ready" ? "重新建立 HLS 串流" : "準備 HLS 串流"}
        </button>
      </div>
    `
    : "";
  const player = video.media_type === "audio"
    ? `<audio id="video-player" class="video-player video-audio-player" controls preload="metadata" src="${sanitize(playbackSource.src)}"></audio>`
    : `<video id="video-player" class="video-player" controls playsinline preload="metadata" src="${sanitize(playbackSource.src)}"></video>`;
  const rememberedFragment = video.share_requires_fragment_key && video.share_url
    ? getRememberedVideoShareFragment(video.share_url)
    : "";
  const shareInfo = video.can_edit && video.visibility === "unlisted"
    ? `
      <details class="drive-collapsible-panel" open>
        <summary>
          <span>
            <span class="drive-card-title">分享控制</span>
            <span class="drive-card-sub">${video.share_url ? "已建立持連結分享" : "尚未建立分享"}</span>
          </span>
        </summary>
        <div class="drive-collapsible-body">
          <div class="drive-card-sub">${sanitize(video.share_url || "發布後會自動建立分享連結")}</div>
          ${video.share_requires_fragment_key ? `
            <div class="field-help">此影音採 strict E2EE。觀看者需使用完整分享連結；若設定第二層分享密碼，還需要「完整連結 + 分享密碼」。伺服器端不提供轉檔、縮圖或內容掃描。</div>
            <div class="field-help">${rememberedFragment
              ? "本次登入 session 已保存此分享的片段金鑰，可直接複製完整連結。"
              : "此裝置目前沒有保存片段金鑰；若完整連結遺失，伺服器無法復原，只能重新產生分享。"}
            </div>
          ` : `
            <div class="field-help">非 E2EE 分享可使用 HLS 或直接串流；若有設定分享密碼，觀看者需要先解鎖。</div>
          `}
          <div class="drive-card-sub">${video.share_password_required ? "已設定分享密碼" : "未設定分享密碼"}</div>
          <div class="drive-card-sub">${video.share_expires_at ? `到期時間：${sanitize(video.share_expires_at)}` : "到期時間：未限制"}</div>
          <div class="drive-card-sub">${Number(video.share_max_views || 0) > 0 ? `最大觀看次數：${Number(video.share_max_views || 0)}` : "最大觀看次數：不限"}</div>
          <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.65rem;">
            <button class="btn btn-sm" type="button" data-video-copy-link="${Number(video.id || 0)}">複製分享連結</button>
            <button class="btn btn-sm" type="button" data-video-share-regenerate="${Number(video.id || 0)}">重新產生分享</button>
            <button class="btn btn-sm btn-danger" type="button" data-video-share-revoke="${Number(video.id || 0)}">撤銷分享</button>
          </div>
        </div>
      </details>
    `
    : "";
  detail.innerHTML = `
    <div class="video-watch-topbar">
      <button class="btn btn-sm" type="button" id="video-back-btn">← 返回影音列表</button>
      <span class="drive-card-sub">獨立播放頁</span>
    </div>
    <div class="video-watch-layout">
      <div class="video-watch-main">
        ${player}
        <div class="drive-card-sub" id="video-playback-status">
          ${sanitize(playbackSource.statusText || streamStatusText)}
        </div>
        ${streamActions}
        ${shareInfo}
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
  if (playback?.mode === "e2ee_direct") {
    hydrateVideoE2eePlayer(video, playback).catch((err) => {
      const status = $("video-playback-status");
      if (status) status.textContent = err.message || "E2EE 影音解密播放失敗";
      videoMsg(err.message || "E2EE 影音解密播放失敗", false);
    });
  }
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
    let playback = null;
    try {
      const playbackRes = await apiFetch(videoPlaybackUrl(json.video), { credentials: "same-origin" });
      const playbackJson = await playbackRes.json().catch(() => ({}));
      if (playbackRes.ok && playbackJson.ok) {
        playback = playbackJson;
      }
    } catch (_) {
      playback = null;
    }
    renderVideoDetail(json.video, json.comments || [], playback);
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
  const video = videoState.current && Number(videoState.current.id || 0) === Number(videoId || 0)
    ? videoState.current
    : (videoState.videos || []).find((item) => Number(item.id || 0) === Number(videoId || 0));
  let url = `${location.origin}${location.pathname}#videos/${encodeURIComponent(videoId)}`;
  if (video?.visibility === "unlisted" && video?.share_url) {
    url = `${location.origin}${video.share_url}`;
    if (video.share_requires_fragment_key) {
      const fragment = getRememberedVideoShareFragment(video.share_url);
      if (!fragment) {
        return videoMsg("此 E2EE 分享連結的本機片段金鑰不可復原；若遺失只能重新產生分享。", false);
      }
      url += `#vk=${fragment}`;
    }
  }
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
  const prepare = event.target.closest("[data-video-prepare-stream]");
  if (prepare) {
    prepareVideoStream(prepare.dataset.videoPrepareStream, videoState.current?.id || 0);
    return;
  }
  const regenerateShare = event.target.closest("[data-video-share-regenerate]");
  if (regenerateShare) {
    regenerateVideoShareLink(videoState.current);
    return;
  }
  const revokeShare = event.target.closest("[data-video-share-revoke]");
  if (revokeShare) {
    revokeVideoShareLink(videoState.current);
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
