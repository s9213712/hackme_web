'use strict';

const videoState = {
  sort: "new",
  videos: [],
  current: null,
  viewRecordedFor: new Set(),
  browseLoaded: false,
  currentHls: null,
  currentObjectUrl: "",
  hlsLibraryPromise: null,
  playbackSessionId: 0,
};
let videoPublishDriveFiles = [];
const VIDEO_SHARE_FRAGMENT_STORAGE_KEY = "hackme_web.video_share_fragments";
const VIDEO_HLS_JS_URL = "/js/vendor/hls.light.min.js?v=20260505-hlsjs";
const VIDEO_E2EE_STREAM_V2_WORKER_URL = "/js/workers/e2ee-stream-v2-worker.js?v=20260505-e2eev2";
const VIDEO_E2EE_STREAM_V2_CHUNK_SIZE = 512 * 1024;

function videoMsg(text, ok = true) {
  const el = $("video-msg");
  if (el) flash(el, text, ok);
}

function destroyCurrentVideoPlaybackArtifacts() {
  if (videoState.currentHls && typeof videoState.currentHls.destroy === "function") {
    try {
      videoState.currentHls.destroy();
    } catch (_) {
      // ignore teardown failure
    }
  }
  videoState.currentHls = null;
  if (videoState.currentObjectUrl) {
    try {
      URL.revokeObjectURL(videoState.currentObjectUrl);
    } catch (_) {
      // ignore revoke failure
    }
  }
  videoState.currentObjectUrl = "";
}

function setVideoPlaybackStatus(text, bad = false) {
  const status = $("video-playback-status");
  if (!status) return;
  status.textContent = text || "";
  status.dataset.state = bad ? "error" : "info";
}

function resetVideoPlaybackStatusState() {
  const status = $("video-playback-status");
  if (!status) return;
  delete status.dataset.state;
}

function loadVideoHlsLibrary() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (videoState.hlsLibraryPromise) return videoState.hlsLibraryPromise;
  videoState.hlsLibraryPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-video-hls-js="1"]');
    if (existing) {
      existing.addEventListener("load", () => resolve(window.Hls || null), { once: true });
      existing.addEventListener("error", () => reject(new Error("HLS.js 載入失敗")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = VIDEO_HLS_JS_URL;
    script.async = true;
    script.defer = true;
    script.dataset.videoHlsJs = "1";
    script.onload = () => resolve(window.Hls || null);
    script.onerror = () => reject(new Error("HLS.js 載入失敗"));
    document.head.appendChild(script);
  }).catch((err) => {
    videoState.hlsLibraryPromise = null;
    throw err;
  });
  return videoState.hlsLibraryPromise;
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

function videoBase64ToBytes(value) {
  const binary = atob(String(value || "").replace(/\s+/g, ""));
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

async function exportRawDriveFileKey(fileKey) {
  const exported = await window.crypto.subtle.exportKey("raw", fileKey);
  return new Uint8Array(exported);
}

async function decryptDriveE2eeBlobWithFileKey(blob, e2ee, fileKey) {
  const plaintext = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: videoBase64ToBytes(e2ee.nonce) },
    fileKey,
    await blob.arrayBuffer()
  );
  const metadata = await decryptDriveJsonMetadata(fileKey, e2ee.encrypted_metadata);
  return {
    blob: new Blob([plaintext], { type: metadata.mime_type || "application/octet-stream" }),
    filename: metadata.filename || "download",
    metadata,
  };
}

async function buildVideoE2eeStreamV2Package(fileKey, decryptedBlob, metadata) {
  const contentType = String(metadata?.mime_type || decryptedBlob?.type || "application/octet-stream").toLowerCase();
  if (!contentType.startsWith("video/") && !contentType.startsWith("audio/")) {
    throw new Error("E2EE Streaming v2 只支援影片或音訊檔。");
  }
  const plaintext = new Uint8Array(await decryptedBlob.arrayBuffer());
  const rawKey = await exportRawDriveFileKey(fileKey);
  const chunks = [];
  const bundleParts = [];
  let ciphertextOffset = 0;
  for (let index = 0, plainOffset = 0; plainOffset < plaintext.byteLength; index += 1, plainOffset += VIDEO_E2EE_STREAM_V2_CHUNK_SIZE) {
    const plainChunk = plaintext.slice(plainOffset, Math.min(plainOffset + VIDEO_E2EE_STREAM_V2_CHUNK_SIZE, plaintext.byteLength));
    const nonce = new Uint8Array(12);
    window.crypto.getRandomValues(nonce);
    const chunkKey = await window.crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM", length: 256 }, false, ["encrypt"]);
    const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, chunkKey, plainChunk);
    const cipherBytes = new Uint8Array(ciphertext);
    const digest = await window.crypto.subtle.digest("SHA-256", cipherBytes);
    bundleParts.push(cipherBytes);
    chunks.push({
      chunk_index: index,
      nonce: videoShareBytesToBase64(nonce),
      ciphertext_offset: ciphertextOffset,
      ciphertext_size: cipherBytes.byteLength,
      plaintext_offset: plainOffset,
      plaintext_size: plainChunk.byteLength,
      ciphertext_sha256: Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join(""),
    });
    ciphertextOffset += cipherBytes.byteLength;
  }
  return {
    manifest_json: JSON.stringify({
      e2ee_stream_version: 2,
      algorithm: "AES-GCM",
      chunk_size: VIDEO_E2EE_STREAM_V2_CHUNK_SIZE,
      chunk_count: chunks.length,
      content_type: contentType,
      duration_hint: 0,
      byte_range_hint: {
        total_plaintext_bytes: plaintext.byteLength,
      },
      created_at: new Date().toISOString(),
      chunks,
    }),
    bundle_blob: new Blob(bundleParts, { type: "application/octet-stream" }),
  };
}

async function prepareVideoE2eeShareArtifacts(fileId) {
  if (!window.crypto?.subtle || typeof fetchDriveE2eeKey !== "function" || typeof unwrapDriveFileKey !== "function") {
    throw new Error("目前瀏覽器無法建立 E2EE 分享串流授權。");
  }
  if (!getCsrfToken()) {
    await fetchCsrfToken();
  }
  const csrf = getCsrfToken() || "";
  const e2ee = await fetchDriveE2eeKey(fileId, csrf);
  const passphrase = await getDriveE2eeSessionPassphrase(
    fileId,
    "請輸入此 E2EE 影音原始加密密碼。密碼只會在瀏覽器端使用，用來建立分享授權與 Streaming v2 分段。"
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
  const cipherBlob = await fetchDriveE2eeCiphertext(fileId, csrf);
  const decrypted = await decryptDriveE2eeBlobWithFileKey(cipherBlob, e2ee, fileKey);
  const streamV2 = await buildVideoE2eeStreamV2Package(fileKey, decrypted.blob, decrypted.metadata);
  return {
    share_wrapped_file_key_envelope: JSON.stringify({
      alg: "AES-GCM",
      v: 1,
      nonce: videoShareBytesToBase64(nonce),
      ciphertext: videoShareBytesToBase64(new Uint8Array(ciphertext)),
    }),
    share_fragment_key: videoShareBytesToBase64Url(shareKeyBytes),
    stream_v2_manifest_json: streamV2.manifest_json,
    stream_v2_bundle_blob: streamV2.bundle_blob,
  };
}

async function uploadVideoE2eeStreamV2Package(fileId, artifacts) {
  if (!artifacts?.stream_v2_manifest_json || !artifacts?.stream_v2_bundle_blob) return null;
  const form = new FormData();
  form.append("manifest_json", artifacts.stream_v2_manifest_json);
  form.append("bundle", artifacts.stream_v2_bundle_blob, "e2ee-stream-v2.bundle");
  const res = await apiFetch(`/api/media/${encodeURIComponent(fileId)}/e2ee-stream-v2`, {
    method: "POST",
    credentials: "same-origin",
    body: form,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
  return json.asset || null;
}

async function buildVideoE2eeShareEnvelope(fileId) {
  const artifacts = await prepareVideoE2eeShareArtifacts(fileId);
  return {
    share_wrapped_file_key_envelope: artifacts.share_wrapped_file_key_envelope,
    share_fragment_key: artifacts.share_fragment_key,
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
  videoState.playbackSessionId += 1;
  destroyCurrentVideoPlaybackArtifacts();
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
      e2eeShare = await prepareVideoE2eeShareArtifacts(selectedFile.id);
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
    if (e2eeShare && selectedFile?.id) {
      try {
        await uploadVideoE2eeStreamV2Package(selectedFile.id, e2eeShare);
      } catch (err) {
        videoMsg(`影音已發布，但 E2EE Streaming v2 建立失敗：${err.message || "請稍後重試"}`, false);
      }
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
  if (playback?.mode === "e2ee_stream_v2") {
    return {
      mode: "e2ee_stream_v2",
      src: "",
      statusText: "正在使用 E2EE Streaming v2：密文分段下載、瀏覽器端解密；若裝置不支援會退回舊版完整解密播放。",
    };
  }
  if (playback?.mode === "e2ee_direct") {
    return {
      mode: "e2ee_direct",
      src: "",
      statusText: "端到端加密影音會在瀏覽器端完整解密播放，速度會較慢。",
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
      mode: "hls_native",
      src: playback.master_url || playback.fallback_url || videoStreamUrl(video),
      statusText: "Safari / 原生 HLS 已啟用。",
    };
  }
  if (playback.master_url) {
    return {
      mode: "hls_js",
      src: "",
      masterUrl: playback.master_url,
      fallbackUrl: playback.fallback_url || videoStreamUrl(video),
      statusText: "桌機瀏覽器將使用內建 HLS.js 播放；若初始化失敗會自動退回直接串流。",
    };
  }
  return {
    mode: "direct",
    src: playback.fallback_url || videoStreamUrl(video),
    statusText: "目前瀏覽器不支援 HLS，已改用直接串流。",
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

function videoShareStateSummary(video) {
  const share = video?.share_link || null;
  if (!share || !share.url) {
    return {
      state: "missing",
      label: "尚未建立分享連結",
      remaining: "剩餘觀看次數：尚未啟用",
    };
  }
  const state = String(share.state || "active");
  const remainingText = Number(share.max_views || 0) > 0
    ? `剩餘觀看次數：${Number(share.remaining_views || 0)} / ${Number(share.max_views || 0)}`
    : "剩餘觀看次數：不限";
  return {
    state,
    label: share.state_message || "分享連結有效",
    remaining: remainingText,
  };
}

function videoNeedsE2eeShareEnvelope(video, options = {}) {
  const visibility = String(video?.visibility || "");
  const isE2ee = String(video?.cloud_privacy_mode || "") === "e2ee";
  if (visibility !== "unlisted" || !isE2ee) return false;
  if (options.regenerate) return true;
  if (!video?.share_url) return true;
  return false;
}

async function saveVideoShareSettings(video, { clearPassword = false, regenerate = false } = {}) {
  if (!video?.id || video?.visibility !== "unlisted") return;
  const passwordInput = $("video-share-password-manage");
  const expiresInput = $("video-share-expires-at-manage");
  const maxViewsInput = $("video-share-max-views-manage");
  const button = $("video-share-save-btn");
  const payload = {
    share_expires_at: (expiresInput?.value || "").trim(),
    share_max_views: (maxViewsInput?.value || "").trim(),
  };
  if (clearPassword) {
    payload.share_password = "";
  } else {
    const passwordValue = (passwordInput?.value || "").trim();
    if (passwordValue) payload.share_password = passwordValue;
  }
  let e2eeShare = null;
  if (videoNeedsE2eeShareEnvelope(video, { regenerate })) {
    try {
      e2eeShare = await prepareVideoE2eeShareArtifacts(video.cloud_file_id);
      payload.share_wrapped_file_key_envelope = e2eeShare.share_wrapped_file_key_envelope;
    } catch (err) {
      return videoMsg(err.message || "E2EE 分享授權建立失敗", false);
    }
  }
  if (regenerate) payload.regenerate = true;
  if (button) button.disabled = true;
  try {
    const json = await updateVideoShareLink(video, payload);
    if (video.share_url) forgetRememberedVideoShareFragment(video.share_url);
    if (e2eeShare && json.share_link?.url) {
      rememberVideoShareFragment(json.share_link.url, e2eeShare.share_fragment_key);
      try {
        await uploadVideoE2eeStreamV2Package(video.cloud_file_id, e2eeShare);
      } catch (err) {
        videoMsg(`分享設定已更新，但 E2EE Streaming v2 建立失敗：${err.message || "請稍後重試"}`, false);
      }
    }
    if (passwordInput) passwordInput.value = "";
    videoMsg(regenerate ? "分享連結與設定已更新。" : "分享設定已儲存。", true);
    await loadVideos(videoState.sort);
    await openVideoDetail(video.id);
  } catch (err) {
    videoMsg(err.message || "分享設定更新失敗", false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function regenerateVideoShareLink(video) {
  if (!video?.id || video?.visibility !== "unlisted") return;
  await saveVideoShareSettings(video, { regenerate: true });
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

async function hydrateVideoE2eePlayer(video, playback, sessionId) {
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
  if (sessionId !== videoState.playbackSessionId) return;
  destroyCurrentVideoPlaybackArtifacts();
  videoState.currentObjectUrl = URL.createObjectURL(decrypted.blob);
  player.src = videoState.currentObjectUrl;
  const status = $("video-playback-status");
  if (status) {
    status.textContent = "已在瀏覽器端以原始 E2EE 密碼解密播放；本次登入 session 內密碼會暫存在瀏覽器記憶體。";
  }
}

function playerTimeBuffered(player, timeSeconds) {
  if (!player?.buffered) return false;
  const target = Number(timeSeconds || 0);
  for (let i = 0; i < player.buffered.length; i += 1) {
    if (target >= player.buffered.start(i) && target <= player.buffered.end(i)) return true;
  }
  return false;
}

function videoSupportsE2eeStreamV2() {
  return Boolean(window.MediaSource && window.Worker && window.crypto?.subtle);
}

function createVideoE2eeStreamWorker() {
  return new Worker(VIDEO_E2EE_STREAM_V2_WORKER_URL);
}

function decryptVideoE2eeChunkWithWorker(worker, keyBytes, nonce, ciphertext) {
  return new Promise((resolve, reject) => {
    const id = `${Date.now()}:${Math.random().toString(16).slice(2)}`;
    const keyBuffer = keyBytes.buffer.slice(0);
    const handleMessage = (event) => {
      const payload = event?.data || {};
      if (payload.id !== id) return;
      worker.removeEventListener("message", handleMessage);
      if (payload.type === "decrypt-chunk-ok") {
        resolve(payload.plaintext);
      } else {
        reject(new Error(payload.message || "E2EE Streaming v2 chunk 解密失敗"));
      }
    };
    worker.addEventListener("message", handleMessage);
    worker.postMessage(
      {
        type: "decrypt-chunk",
        id,
        keyBytes: keyBuffer,
        nonce,
        ciphertext,
      },
      [keyBuffer, ciphertext]
    );
  });
}

function appendSourceBufferAsync(sourceBuffer, payload) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      sourceBuffer.removeEventListener("updateend", onEnd);
      sourceBuffer.removeEventListener("error", onErr);
    };
    const onEnd = () => {
      cleanup();
      resolve();
    };
    const onErr = () => {
      cleanup();
      reject(new Error("MediaSource append 失敗"));
    };
    sourceBuffer.addEventListener("updateend", onEnd, { once: true });
    sourceBuffer.addEventListener("error", onErr, { once: true });
    sourceBuffer.appendBuffer(payload);
  });
}

async function resolveVideoE2eePlaybackKey(video, playback) {
  const csrf = getCsrfToken() || "";
  const e2ee = await fetchDriveE2eeKey(video.cloud_file_id, csrf);
  for (const passphrase of getDriveE2eeSessionPassphraseCandidates(video.cloud_file_id)) {
    try {
      const fileKey = await unwrapDriveFileKey(e2ee.encrypted_file_key, passphrase);
      rememberDriveE2eeSessionPassphrase(video.cloud_file_id, passphrase);
      return new Uint8Array(await window.crypto.subtle.exportKey("raw", fileKey));
    } catch (_) {
      forgetDriveE2eeSessionPassphrase(video.cloud_file_id);
    }
  }
  const passphrase = await getDriveE2eeSessionPassphrase(
    video.cloud_file_id,
    "請輸入此 E2EE 影音的原始加密密碼。strict E2EE Streaming v2 只在瀏覽器端解密，伺服器無法看到明文。",
    { force: true }
  );
  if (!passphrase) throw new Error("E2EE 影音播放需要原始加密密碼。");
  const fileKey = await unwrapDriveFileKey(e2ee.encrypted_file_key, passphrase);
  rememberDriveE2eeSessionPassphrase(video.cloud_file_id, passphrase);
  return new Uint8Array(await window.crypto.subtle.exportKey("raw", fileKey));
}

async function attachVideoE2eeStreamV2Player(video, playback, sessionId) {
  const player = $("video-player");
  if (!player) return;
  if (!videoSupportsE2eeStreamV2()) {
    setVideoPlaybackStatus("目前裝置不支援 E2EE Streaming v2，已退回舊版完整解密播放。", false);
    await hydrateVideoE2eePlayer(video, playback, sessionId);
    return;
  }
  const manifestRes = await apiFetch(playback.manifest_url, { credentials: "same-origin" });
  const manifestJson = await manifestRes.json().catch(() => ({}));
  if (!manifestRes.ok || manifestJson.available === false) {
    setVideoPlaybackStatus(manifestJson.msg || "此 strict E2EE 影音尚未建立 Streaming v2 manifest，已退回舊版完整解密播放。", false);
    await hydrateVideoE2eePlayer(video, playback, sessionId);
    return;
  }
  const rawKeyBytes = await resolveVideoE2eePlaybackKey(video, playback);
  destroyCurrentVideoPlaybackArtifacts();
  const mediaSource = new MediaSource();
  const objectUrl = URL.createObjectURL(mediaSource);
  videoState.currentObjectUrl = objectUrl;
  player.src = objectUrl;
  setVideoPlaybackStatus("正在使用 E2EE Streaming v2：密文分段下載、瀏覽器端 Web Worker 解密，伺服器無法看到明文。", false);
  const worker = createVideoE2eeStreamWorker();
  let nextChunk = 0;
  let closed = false;
  let sourceBuffer = null;
  const cleanup = () => {
    if (closed) return;
    closed = true;
    try { worker.terminate(); } catch (_) {}
  };
  const fallbackToFull = async (reason, seekTarget = null) => {
    cleanup();
    setVideoPlaybackStatus(reason, false);
    await hydrateVideoE2eePlayer(video, playback, sessionId);
    if (seekTarget !== null) {
      const onLoaded = () => {
        player.removeEventListener("loadedmetadata", onLoaded);
        try { player.currentTime = seekTarget; } catch (_) {}
      };
      player.addEventListener("loadedmetadata", onLoaded);
    }
  };
  player.addEventListener("seeking", () => {
    if (closed || !sourceBuffer) return;
    const target = Number(player.currentTime || 0);
    if (!playerTimeBuffered(player, target) && nextChunk < Number(manifestJson.chunk_count || 0)) {
      fallbackToFull("偵測到尚未緩衝區段的快轉，已退回舊版完整解密播放以確保可用性。", target).catch((err) => {
        setVideoPlaybackStatus(err?.message || "E2EE 影音快轉 fallback 失敗", true);
      });
    }
  });
  mediaSource.addEventListener("sourceopen", () => {
    if (closed || sessionId !== videoState.playbackSessionId) {
      cleanup();
      return;
    }
    try {
      sourceBuffer = mediaSource.addSourceBuffer(manifestJson.content_type || playback.status?.content_type || video.cloud_mime_type || "video/mp4");
    } catch (err) {
      fallbackToFull("目前裝置無法以 MediaSource 播放此 strict E2EE 影音，已退回舊版完整解密播放。").catch(() => {});
      return;
    }
    const pump = async () => {
      if (closed || sessionId !== videoState.playbackSessionId || !sourceBuffer) return;
      if (nextChunk >= Number(manifestJson.chunk_count || 0)) {
        if (mediaSource.readyState === "open" && !sourceBuffer.updating) {
          try { mediaSource.endOfStream(); } catch (_) {}
        }
        cleanup();
        setVideoPlaybackStatus("正在使用 E2EE Streaming v2；若裝置或格式不支援快轉，系統會退回舊版完整解密播放。", false);
        return;
      }
      const chunkMeta = manifestJson.chunks?.[nextChunk];
      if (!chunkMeta) {
        fallbackToFull("E2EE Streaming v2 chunk metadata 缺失，已退回舊版完整解密播放。").catch(() => {});
        return;
      }
      try {
        const chunkUrl = playback.chunk_url_template.replace("__INDEX__", String(chunkMeta.chunk_index));
        const chunkRes = await apiFetch(chunkUrl, { credentials: "same-origin" });
        if (!chunkRes.ok) {
          const payload = await chunkRes.json().catch(() => ({}));
          throw new Error(payload.msg || `HTTP ${chunkRes.status}`);
        }
        const cipher = await chunkRes.arrayBuffer();
        const plaintext = await decryptVideoE2eeChunkWithWorker(worker, new Uint8Array(rawKeyBytes), chunkMeta.nonce, cipher);
        await appendSourceBufferAsync(sourceBuffer, new Uint8Array(plaintext));
        nextChunk += 1;
        setVideoPlaybackStatus(`正在使用 E2EE Streaming v2：已解密分段 ${nextChunk} / ${manifestJson.chunk_count}。`, false);
        queueMicrotask(() => { pump().catch(() => {}); });
      } catch (err) {
        fallbackToFull(`E2EE Streaming v2 分段播放失敗，已退回舊版完整解密播放。${err?.message ? ` (${err.message})` : ""}`).catch(() => {});
      }
    };
    pump().catch((err) => {
      fallbackToFull(err?.message || "E2EE Streaming v2 初始化失敗").catch(() => {});
    });
  }, { once: true });
}

function fallbackVideoPlayerToDirect(player, playback, message, bad = false) {
  destroyCurrentVideoPlaybackArtifacts();
  const fallbackSrc = playback?.fallback_url || playback?.stream_url || "";
  if (fallbackSrc) {
    player.src = fallbackSrc;
    if (typeof player.load === "function") player.load();
  }
  setVideoPlaybackStatus(message || "HLS 初始化失敗，已改用直接串流。", bad);
}

function clearVideoPlaybackAction() {
  const wrap = $("video-playback-action");
  if (wrap) wrap.innerHTML = "";
}

function setVideoPlaybackActionButton(label, onClick, helperText = "") {
  const wrap = $("video-playback-action");
  if (!wrap) return;
  wrap.innerHTML = `
    <button class="btn btn-primary" type="button" id="video-playback-start-btn">${sanitize(label || "開始播放")}</button>
    ${helperText ? `<div class="drive-card-sub">${sanitize(helperText)}</div>` : ""}
  `;
  const button = $("video-playback-start-btn");
  if (!button) return;
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {
      clearVideoPlaybackAction();
      await onClick();
    } catch (err) {
      const message = err?.message || "影音播放初始化失敗";
      setVideoPlaybackStatus(message, true);
      videoMsg(message, false);
      button.disabled = false;
      setVideoPlaybackActionButton(label, onClick, helperText);
    }
  }, { once: true });
}

async function attachVideoHlsJsPlayer(player, playback, sessionId) {
  const statusText = "已使用 HLS.js 播放，桌機 Chrome / Firefox / Edge 可穩定播放 HLS；若網路或格式異常會自動退回直接串流。";
  let HlsCtor = null;
  try {
    HlsCtor = await loadVideoHlsLibrary();
    if (!HlsCtor || typeof HlsCtor.isSupported !== "function" || !HlsCtor.isSupported()) {
      throw new Error("目前瀏覽器不支援 HLS.js 所需的 MediaSource。");
    }
    if (sessionId !== videoState.playbackSessionId) return;
  } catch (err) {
    if (sessionId !== videoState.playbackSessionId) return;
    fallbackVideoPlayerToDirect(player, playback, `HLS.js 載入失敗，已改用直接串流。${err?.message ? ` (${err.message})` : ""}`, true);
    return;
  }
  destroyCurrentVideoPlaybackArtifacts();
  const hls = new HlsCtor({
    enableWorker: true,
    backBufferLength: 30,
  });
  videoState.currentHls = hls;
  hls.on(HlsCtor.Events.MANIFEST_PARSED, () => {
    if (sessionId !== videoState.playbackSessionId) return;
    setVideoPlaybackStatus(statusText, false);
  });
  hls.on(HlsCtor.Events.ERROR, (_event, data) => {
    if (sessionId !== videoState.playbackSessionId) return;
    if (!data?.fatal) return;
    const detail = data?.details ? ` (${data.details})` : "";
    fallbackVideoPlayerToDirect(player, playback, `HLS.js 播放失敗，已改用直接串流。${detail}`, true);
  });
  hls.loadSource(playback.master_url || "");
  hls.attachMedia(player);
}

async function activateVideoPlaybackMode(video, playback, playbackSource, sessionId) {
  const player = $("video-player");
  if (!player) return;
  resetVideoPlaybackStatusState();
  if (playback?.mode === "e2ee_stream_v2") {
    clearVideoPlaybackAction();
    setVideoPlaybackStatus("此 strict E2EE 影音會在瀏覽器端解密。按下「開始 E2EE 播放」後才會讀取分享授權或要求密碼。", false);
    setVideoPlaybackActionButton(
      "開始 E2EE 播放",
      () => attachVideoE2eeStreamV2Player(video, playback, sessionId),
      "未按下播放前，不會主動要求 E2EE 密碼。"
    );
    return;
  }
  if (playback?.mode === "e2ee_direct") {
    clearVideoPlaybackAction();
    setVideoPlaybackStatus("此 strict E2EE 影音會在瀏覽器端完整解密。按下「開始 E2EE 播放」後才會要求原始密碼。", false);
    setVideoPlaybackActionButton(
      "開始 E2EE 播放",
      () => hydrateVideoE2eePlayer(video, playback, sessionId),
      "未按下播放前，不會主動要求 E2EE 密碼。"
    );
    return;
  }
  clearVideoPlaybackAction();
  if (playbackSource?.mode === "hls_js") {
    setVideoPlaybackStatus(playbackSource.statusText || "正在初始化 HLS.js 播放器...", false);
    await attachVideoHlsJsPlayer(player, playback, sessionId);
    return;
  }
  destroyCurrentVideoPlaybackArtifacts();
}

function renderVideoDetail(video, comments = [], playback = null) {
  const detail = $("video-detail");
  if (!detail) return;
  destroyCurrentVideoPlaybackArtifacts();
  videoState.playbackSessionId += 1;
  const playbackSessionId = videoState.playbackSessionId;
  videoState.current = video;
  showVideoWatchView();
  const playbackSource = playbackSourceForVideo(video, playback);
  const playbackStatus = playback?.status || {};
  const streamStatusText = humanVideoStreamStatus(playback) || String(playback?.stream_warning || "").trim();
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
  const shareState = videoShareStateSummary(video);
  const shareInfo = video.can_edit && video.visibility === "unlisted"
    ? `
      <details class="drive-collapsible-panel" open>
        <summary>
          <span>
            <span class="drive-card-title">分享控制</span>
            <span class="drive-card-sub">${sanitize(shareState.label)}</span>
          </span>
        </summary>
        <div class="drive-collapsible-body">
          <div class="drive-card-sub">${sanitize(video.share_url || "尚未建立分享連結")}</div>
          <div class="drive-card-sub">目前狀態：${sanitize(shareState.label)}</div>
          <div class="drive-card-sub">已觀看次數：${sanitize(String(video.share_link?.access_count ?? 0))}</div>
          <div class="drive-card-sub">${sanitize(shareState.remaining)}</div>
          <div class="drive-card-sub">${video.share_link?.last_accessed_at ? `最後觀看：${sanitize(video.share_link.last_accessed_at)}` : "最後觀看：尚無紀錄"}</div>
          <div class="drive-card-sub">${video.share_link?.password_locked_until ? `分享密碼鎖定到：${sanitize(video.share_link.password_locked_until)}` : "分享密碼狀態：可正常驗證"}</div>
          ${video.share_requires_fragment_key ? `
            <div class="field-help">此影音採 strict E2EE。觀看者需使用完整分享連結；若設定第二層分享密碼，還需要「完整連結 + 分享密碼」。伺服器端不提供轉檔、縮圖或內容掃描。</div>
            <div class="field-help">重新產生此分享時，瀏覽器會要求發布者再次輸入原始 E2EE 密碼；伺服器端不保存原始密碼、raw file key 或 <code>#vk</code> fragment。</div>
            <div class="field-help">${rememberedFragment
              ? "本次登入 session 已保存此分享的片段金鑰，可直接複製完整連結。"
              : "此裝置目前沒有保存片段金鑰；若完整連結遺失，伺服器無法復原，只能重新產生分享。"}
            </div>
            <div class="field-help">資料截斷或 fragment 遺失不會讓伺服器幫你復原分享金鑰；如果遺失，只能重新產生分享。</div>
          ` : `
            <div class="field-help">非 E2EE 分享可使用 HLS 或直接串流；若有設定分享密碼，觀看者需要先解鎖。</div>
          `}
          <div class="drive-card-sub">${video.share_password_required ? "已設定第二層分享密碼" : "未設定第二層分享密碼"}</div>
          <div class="drive-card-sub">${video.share_expires_at ? `到期時間：${sanitize(video.share_expires_at)}` : "到期時間：未限制"}</div>
          <div class="drive-card-sub">${Number(video.share_max_views || 0) > 0 ? `最大觀看次數：${Number(video.share_max_views || 0)}` : "最大觀看次數：不限"}</div>
          <div class="video-share-manage-grid">
            <label>
              <span class="drive-card-sub">更新分享密碼</span>
              <input id="video-share-password-manage" type="password" autocomplete="new-password" placeholder="留空代表不變更" />
            </label>
            <label>
              <span class="drive-card-sub">到期時間</span>
              <input id="video-share-expires-at-manage" type="datetime-local" value="${sanitize(String(video.share_expires_at || "").slice(0, 16))}" />
            </label>
            <label>
              <span class="drive-card-sub">最大觀看次數</span>
              <input id="video-share-max-views-manage" type="number" min="0" step="1" value="${sanitize(String(video.share_max_views || 0))}" />
            </label>
          </div>
          <div class="drive-file-actions" style="justify-content:flex-start;margin-top:.65rem;">
            <button class="btn btn-sm" type="button" id="video-share-save-btn" data-video-share-save="${Number(video.id || 0)}">${video.share_url ? "儲存分享設定" : "建立分享連結"}</button>
            <button class="btn btn-sm" type="button" data-video-share-clear-password="${Number(video.id || 0)}">移除分享密碼</button>
            <button class="btn btn-sm" type="button" data-video-copy-link="${Number(video.id || 0)}">複製完整分享連結</button>
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
          ${sanitize(playbackSource.statusText || streamStatusText || "")}
        </div>
        <div class="drive-file-actions" id="video-playback-action" style="justify-content:flex-start;margin-top:.45rem;"></div>
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
  activateVideoPlaybackMode(video, playback, playbackSource, playbackSessionId).catch((err) => {
    if (playbackSessionId !== videoState.playbackSessionId) return;
    const message = err?.message || "影音播放初始化失敗";
    setVideoPlaybackStatus(message, true);
    videoMsg(message, false);
  });
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
    window.prompt("分享連結", url);
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
  const saveShare = event.target.closest("[data-video-share-save]");
  if (saveShare) {
    saveVideoShareSettings(videoState.current);
    return;
  }
  const clearSharePassword = event.target.closest("[data-video-share-clear-password]");
  if (clearSharePassword) {
    saveVideoShareSettings(videoState.current, { clearPassword: true });
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
