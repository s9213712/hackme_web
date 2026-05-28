'use strict';

const sharedFileState = {
  token: "",
  file: null,
  previewObjectUrl: "",
  password: "",
  hls: null,
  hlsLibraryPromise: null,
};
const SHARED_FILE_HLS_JS_URL = "/js/hls.light.min.js?v=20260505-hlsjs";

function sharedFileToken() {
  const el = document.getElementById("shared-file-token");
  try {
    return JSON.parse(el?.textContent || '""') || "";
  } catch (_) {
    return "";
  }
}

function sharedFileSetMsg(text, bad = false) {
  const el = document.getElementById("shared-file-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = bad ? "msg err" : "msg";
}

function sharedFilePasswordStorageKey() {
  return `hackme:shared-file-password:${sharedFileState.token || sharedFileToken()}`;
}

function sharedFileRememberedPassword() {
  try {
    return sessionStorage.getItem(sharedFilePasswordStorageKey()) || "";
  } catch (_) {
    return "";
  }
}

function sharedFileSetPassword(password) {
  sharedFileState.password = String(password || "");
  try {
    if (sharedFileState.password) sessionStorage.setItem(sharedFilePasswordStorageKey(), sharedFileState.password);
    else sessionStorage.removeItem(sharedFilePasswordStorageKey());
  } catch (_) {}
}

function sharedFileRequestOptions(extra = {}) {
  const headers = { ...(extra.headers || {}) };
  if (sharedFileState.password) headers["X-Share-Password"] = sharedFileState.password;
  return { ...extra, credentials: "same-origin", headers };
}

function sharedFileUrlWithPassword(url) {
  const parsed = new URL(url || "/", window.location.origin);
  if (sharedFileState.password) parsed.searchParams.set("password", sharedFileState.password);
  return `${parsed.pathname}${parsed.search}`;
}

function sharedFileErrorFromResponse(res, json, fallback) {
  const err = new Error(json?.msg || fallback || `HTTP ${res.status}`);
  err.status = res.status;
  err.reason = json?.reason || "";
  return err;
}

function sharedFileSetLoginRequired(required) {
  const link = document.getElementById("shared-file-login-link");
  if (!link) return;
  link.hidden = !required;
  if (required) {
    const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    link.href = `/?return_to=${encodeURIComponent(returnTo)}`;
  }
}

function sharedFileMaybeShowLogin(err) {
  sharedFileSetLoginRequired(err?.reason === "login_required" || Number(err?.status) === 401);
}

function sharedFileFormatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function sharedFileProgressText(loaded, total) {
  const loadedText = sharedFileFormatBytes(loaded || 0);
  const totalNum = Number(total || 0);
  if (!Number.isFinite(totalNum) || totalNum <= 0) return `${loadedText} / 計算中`;
  const percent = Math.max(0, Math.min(100, (Number(loaded || 0) / totalNum) * 100));
  return `${Math.round(percent)}% · ${loadedText} / ${sharedFileFormatBytes(totalNum)}`;
}

function sharedFileShowProgress(title, loaded = 0, total = 0, detail = "") {
  const totalNum = Number(total || 0);
  const loadedNum = Math.max(0, Number(loaded || 0));
  const percent = totalNum > 0 ? Math.max(0, Math.min(100, Math.round((loadedNum / totalNum) * 100))) : 0;
  const progressAttr = totalNum > 0 ? ` value="${percent}" max="100"` : "";
  sharedFileShowPreview(`
    <div class="shared-file-progress">
      <strong>${sharedFileEscape(title || "處理中")}</strong>
      <progress${progressAttr}></progress>
      <span>${sharedFileEscape(sharedFileProgressText(loadedNum, totalNum))}</span>
      ${detail ? `<small>${sharedFileEscape(detail)}</small>` : ""}
    </div>
  `);
}

async function sharedFileReadResponseBlobWithProgress(res, title, totalHint = 0) {
  const totalHeader = Number(res.headers.get("Content-Length") || 0);
  const total = totalHeader > 0 ? totalHeader : Number(totalHint || 0);
  const contentType = res.headers.get("Content-Type") || "application/octet-stream";
  if (!res.body || typeof res.body.getReader !== "function") {
    sharedFileShowProgress(title, 0, total, "瀏覽器無法逐段回報進度，改用一般讀取。");
    const blob = await res.blob();
    sharedFileShowProgress(title, blob.size || total, blob.size || total, "資料讀取完成。");
    return blob;
  }
  sharedFileShowProgress(title, 0, total, "保持此頁開啟；大型加密檔案需要時間。");
  const reader = res.body.getReader();
  const chunks = [];
  let loaded = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    chunks.push(value);
    loaded += value.byteLength || 0;
    sharedFileShowProgress(title, loaded, total, "資料傳輸中。");
  }
  sharedFileShowProgress(title, loaded, total || loaded, "資料傳輸完成。");
  return new Blob(chunks, { type: contentType });
}

async function sharedFileFetchBlobWithProgress(url, options = {}, title = "下載中", totalHint = 0) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw sharedFileErrorFromResponse(res, json, `讀取失敗（HTTP ${res.status}）`);
  }
  return sharedFileReadResponseBlobWithProgress(res, title, totalHint);
}

function sharedFileEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function sharedFileClearPreview() {
  if (sharedFileState.hls && typeof sharedFileState.hls.destroy === "function") {
    try {
      sharedFileState.hls.destroy();
    } catch (_) {}
  }
  sharedFileState.hls = null;
  if (sharedFileState.previewObjectUrl) {
    URL.revokeObjectURL(sharedFileState.previewObjectUrl);
    sharedFileState.previewObjectUrl = "";
  }
}

function sharedFilePreviewBox() {
  return document.getElementById("shared-file-preview");
}

function sharedFileContentUrl(file) {
  return sharedFileUrlWithPassword(file?.preview_content_url || `/api/storage/shared/${encodeURIComponent(sharedFileState.token)}/preview/content`);
}

function sharedFilePreviewMetadataUrl(file) {
  return sharedFileUrlWithPassword(file?.preview_url || `/api/storage/shared/${encodeURIComponent(sharedFileState.token)}/preview`);
}

function sharedFileRenderPasswordForm(message = "此分享連結需要密碼。") {
  const msg = document.getElementById("shared-file-msg");
  if (!msg) return;
  msg.className = "msg";
  msg.innerHTML = `
    <form id="shared-file-password-form" class="password-form">
      <label for="shared-file-password-input">${sharedFileEscape(message)}</label>
      <input id="shared-file-password-input" type="password" autocomplete="current-password" placeholder="輸入分享密碼" />
      <button type="submit">解鎖分享</button>
    </form>
  `;
  const input = document.getElementById("shared-file-password-input");
  if (input) input.focus();
  const form = document.getElementById("shared-file-password-form");
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const password = document.getElementById("shared-file-password-input")?.value || "";
      sharedFileSetPassword(password);
      sharedFileLoad();
    }, { once: true });
  }
}

function sharedFileClearPasswordForm() {
  const form = document.getElementById("shared-file-password-form");
  if (form) form.remove();
}

function sharedFileExtension(filename) {
  const lower = String(filename || "").toLowerCase();
  for (const ext of [".tar.gz", ".tar.bz2", ".tar.xz"]) {
    if (lower.endsWith(ext)) return ext;
  }
  const index = lower.lastIndexOf(".");
  return index >= 0 ? lower.slice(index) : "";
}

function sharedFileCategory(filename, mime = "") {
  const type = String(mime || "").toLowerCase();
  const ext = sharedFileExtension(filename);
  if (type.startsWith("image/") || [".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"].includes(ext)) return "image";
  if (type.startsWith("video/") || [".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".webm", ".wmv"].includes(ext)) return "video";
  if (type.startsWith("audio/") || [".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"].includes(ext)) return "audio";
  if (type === "application/pdf" || ext === ".pdf") return "pdf";
  if (type.startsWith("text/") || [".css", ".csv", ".htm", ".html", ".ini", ".js", ".json", ".log", ".md", ".py", ".sh", ".sql", ".text", ".toml", ".txt", ".xml", ".yaml", ".yml"].includes(ext) || !ext) return "text";
  return "metadata";
}

function sharedFileStreamAsset(file) {
  return file?.stream_asset && typeof file.stream_asset === "object" ? file.stream_asset : null;
}

function sharedFileSubtitles(file) {
  const stream = sharedFileStreamAsset(file);
  const tracks = Array.isArray(stream?.subtitles) ? stream.subtitles : [];
  return tracks
    .filter((track) => track && track.name && track.url)
    .map((track) => ({
      label: String(track.label || track.language || "字幕"),
      language: String(track.language || "und"),
      url: String(track.url || ""),
      isDefault: !!track.is_default,
    }));
}

function sharedFileAudioTracks(file) {
  const stream = sharedFileStreamAsset(file);
  const tracks = Array.isArray(stream?.audio_tracks) ? stream.audio_tracks : [];
  return tracks
    .filter((track) => track && track.name)
    .map((track) => ({
      name: String(track.name || ""),
      label: String(track.label || track.language || track.name || "音軌"),
      language: String(track.language || "und"),
      streamIndex: Number(track.stream_index ?? -1),
      isDefault: !!track.is_default,
    }));
}

function sharedFileServiceOptions(file) {
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  if (!["video", "audio"].includes(category)) return [];
  const stream = sharedFileStreamAsset(file);
  const proxy = stream?.realtime_proxy || {};
  const directAvailable = !!file?.can_preview && file?.privacy_mode !== "server_encrypted";
  const realtimeAvailable = !!(stream?.realtime_proxy_url || proxy.url) && proxy.available !== false;
  const hlsAvailable = sharedFileHasReadyHls(file);
  const profilePolicy = stream?.premium_hls_profile_policy || {};
  const profileDriftSuffix = profilePolicy.profile_drift ? " 目前 HLS 資產與現行 Premium profile 不一致，建議排程重建。" : "";
  return [
    {
      mode: "direct",
      label: "Basic · 直接串流",
      available: directAvailable,
      summary: "最低費率；直接送原始檔，格式相容性取決於瀏覽器。",
    },
    {
      mode: "realtime_proxy",
      label: "Standard · 即時轉封裝",
      available: realtimeAvailable,
      summary: "中階費率；用即時 CPU 處理 MKV 或特殊音訊，一次輸出選定音軌。",
    },
    {
      mode: "prepared_hls",
      label: "Premium · 預處理 HLS",
      available: hlsAvailable,
      summary: "最高費率；預先建立分段串流，支援多音軌、多字幕與穩定跳轉。" + profileDriftSuffix,
    },
  ];
}

function sharedFileServiceModeStorageKey(file) {
  return `hackme_web.shared_file_service_mode.${sharedFileState.token || sharedFileToken()}.${file?.id || file?.file_id || file?.display_name || ""}`;
}

function sharedFileSelectedServiceMode(file) {
  const options = sharedFileServiceOptions(file);
  const availableModes = new Set(options.filter((option) => option.available).map((option) => option.mode));
  let saved = "";
  try {
    saved = localStorage.getItem(sharedFileServiceModeStorageKey(file)) || "";
  } catch (_) {
    saved = "";
  }
  if (saved && availableModes.has(saved)) return saved;
  if (availableModes.has("prepared_hls")) return "prepared_hls";
  if (availableModes.has("realtime_proxy")) return "realtime_proxy";
  if (availableModes.has("direct")) return "direct";
  return "prepared_hls";
}

function sharedFileSaveServiceMode(file, mode) {
  try {
    localStorage.setItem(sharedFileServiceModeStorageKey(file), String(mode || ""));
  } catch (_) {}
}

function sharedFileSelectedAudioTrack(file) {
  const tracks = sharedFileAudioTracks(file);
  if (!tracks.length) return null;
  const select = document.getElementById("shared-file-audio-track-select");
  if (select) {
    const selected = Math.max(0, Math.min(tracks.length - 1, Number(select.value || 0)));
    return tracks[selected] || tracks[0];
  }
  return tracks.find((track) => track.isDefault) || tracks[0];
}

function sharedFileRealtimeProxyUrl(file, startSeconds = 0) {
  const stream = sharedFileStreamAsset(file);
  const raw = String(stream?.realtime_proxy_url || stream?.realtime_proxy?.url || "").trim();
  if (!raw) return "";
  const url = new URL(raw, window.location.origin);
  const track = sharedFileSelectedAudioTrack(file);
  if (track?.name) url.searchParams.set("audio", track.name);
  const start = Number(startSeconds || 0);
  if (Number.isFinite(start) && start > 0) url.searchParams.set("start", String(Math.max(0, Math.round(start * 1000) / 1000)));
  return sharedFileUrlWithPassword(`${url.pathname}${url.search}`);
}

function sharedFileSubtitleShiftStorageKey() {
  return `hackme_web.shared_file_subtitle_shift_ms.${sharedFileState.token || sharedFileToken()}`;
}

function clampSharedFileSubtitleShiftMs(value) {
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(-3600000, Math.min(3600000, Math.round(parsed)));
}

function sharedFileSubtitleShiftSecondsValue(ms) {
  const seconds = clampSharedFileSubtitleShiftMs(ms) / 1000;
  return Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(1).replace(/\.0$/, "");
}

function sharedFileSubtitleShiftMs() {
  try {
    return clampSharedFileSubtitleShiftMs(localStorage.getItem(sharedFileSubtitleShiftStorageKey()) || 0);
  } catch (_) {
    return 0;
  }
}

function sharedFileSetSubtitleShiftMs(value) {
  const offset = clampSharedFileSubtitleShiftMs(value);
  try {
    const key = sharedFileSubtitleShiftStorageKey();
    if (offset) localStorage.setItem(key, String(offset));
    else localStorage.removeItem(key);
  } catch (_) {}
  return offset;
}

function sharedFileSubtitleUrlWithShift(url, shiftMs) {
  const raw = sharedFileUrlWithPassword(url || "");
  if (!raw) return raw;
  const offset = clampSharedFileSubtitleShiftMs(shiftMs);
  try {
    const parsed = new URL(raw, window.location.origin);
    if (offset) parsed.searchParams.set("shift_ms", String(offset));
    else parsed.searchParams.delete("shift_ms");
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch (_) {
    if (!offset) return raw;
    const separator = raw.includes("?") ? "&" : "?";
    return `${raw}${separator}shift_ms=${encodeURIComponent(String(offset))}`;
  }
}

function sharedFileSyncSubtitleTracks(player, file) {
  if (!player) return;
  Array.from(player.querySelectorAll('track[data-shared-file-subtitle="1"]')).forEach((track) => track.remove());
  const shiftMs = sharedFileSubtitleShiftMs();
  sharedFileSubtitles(file).forEach((track, index) => {
    const el = document.createElement("track");
    el.kind = "subtitles";
    el.label = track.label || track.language || "字幕";
    el.srclang = track.language || "und";
    el.src = sharedFileSubtitleUrlWithShift(track.url, shiftMs);
    el.dataset.sharedFileSubtitle = "1";
    if (track.isDefault || index === 0) el.default = true;
    player.appendChild(el);
  });
}

function sharedFileSubtitleShiftControlsMarkup(file, selectedMode = "") {
  const subtitles = sharedFileSubtitles(file);
  const audioTracks = sharedFileAudioTracks(file);
  const serviceOptions = sharedFileServiceOptions(file);
  const mode = selectedMode || sharedFileSelectedServiceMode(file);
  const showAudio = ["prepared_hls", "realtime_proxy"].includes(mode);
  if (serviceOptions.length < 2 && !subtitles.length && (!showAudio || audioTracks.length < 2)) return "";
  const selectedOption = serviceOptions.find((option) => option.mode === mode) || serviceOptions[0] || {};
  const serviceMarkup = serviceOptions.length >= 2 ? `
    <div class="shared-file-progress shared-file-service-mode">
      <strong>方案</strong>
      <select id="shared-file-service-mode-select">
        ${serviceOptions.map((option) => `<option value="${sharedFileEscape(option.mode)}"${option.mode === mode ? " selected" : ""}${option.available ? "" : " disabled"}>${sharedFileEscape(option.label)}</option>`).join("")}
      </select>
      <small>${sharedFileEscape(selectedOption.summary || "")}</small>
    </div>
  ` : "";
  const defaultAudioIndex = Math.max(0, audioTracks.findIndex((track) => track.isDefault));
  const audioMarkup = showAudio && audioTracks.length >= 2 ? `
    <div class="shared-file-progress shared-file-audio-track">
      <strong>音軌</strong>
      <select id="shared-file-audio-track-select">
        ${audioTracks.map((track, index) => `<option value="${index}"${index === defaultAudioIndex ? " selected" : ""}>${sharedFileEscape(track.label)}</option>`).join("")}
      </select>
      ${mode === "realtime_proxy" ? "<small>Standard 即時轉封裝會重新開啟串流以套用音軌。</small>" : ""}
    </div>
  ` : "";
  const subtitleMarkup = subtitles.length ? `
    <div class="shared-file-progress shared-file-subtitle-shift">
      <strong>字幕延遲</strong>
      <div class="shared-file-subtitle-shift-row">
        <button type="button" data-shared-file-subtitle-shift-step="-500">-0.5s</button>
        <input id="shared-file-subtitle-shift-seconds" type="number" min="-3600" max="3600" step="0.1" value="${sharedFileEscape(sharedFileSubtitleShiftSecondsValue(sharedFileSubtitleShiftMs()))}" />
        <button type="button" data-shared-file-subtitle-shift-step="500">+0.5s</button>
        <button type="button" data-shared-file-subtitle-shift-reset="1">重置</button>
      </div>
    </div>
  ` : "";
  return `
    ${serviceMarkup}
    ${audioMarkup}
    ${subtitleMarkup}
  `;
}

function sharedFileBindSubtitleShiftControls(file, player) {
  const serviceSelect = document.getElementById("shared-file-service-mode-select");
  if (serviceSelect) {
    serviceSelect.addEventListener("change", () => {
      sharedFileSaveServiceMode(file, serviceSelect.value);
      sharedFileRenderStreamingPreview(file).catch((err) => sharedFileSetMsg(err.message || "預覽失敗", true));
    });
  }
  const audioSelect = document.getElementById("shared-file-audio-track-select");
  if (audioSelect) {
    audioSelect.addEventListener("change", () => sharedFileApplyAudioTrack(file));
  }
  const input = document.getElementById("shared-file-subtitle-shift-seconds");
  if (!input) return;
  const applyShift = (nextMs) => {
    const offset = sharedFileSetSubtitleShiftMs(nextMs);
    input.value = sharedFileSubtitleShiftSecondsValue(offset);
    sharedFileSyncSubtitleTracks(player, file);
    sharedFileSetMsg(offset ? `字幕時間校正：${sharedFileSubtitleShiftSecondsValue(offset)} 秒。` : "字幕時間校正已重置。");
  };
  input.addEventListener("change", () => applyShift(Number(input.value || 0) * 1000));
  document.querySelectorAll("[data-shared-file-subtitle-shift-step]").forEach((button) => {
    button.addEventListener("click", () => applyShift(sharedFileSubtitleShiftMs() + Number(button.dataset.sharedFileSubtitleShiftStep || 0)));
  });
  const reset = document.querySelector("[data-shared-file-subtitle-shift-reset]");
  if (reset) reset.addEventListener("click", () => applyShift(0));
}

function sharedFileApplyAudioTrack(file) {
  const tracks = sharedFileAudioTracks(file);
  const select = document.getElementById("shared-file-audio-track-select");
  if (sharedFileSelectedServiceMode(file) === "realtime_proxy") {
    const player = document.getElementById("shared-file-hls-player");
    if (!select || tracks.length < 2 || !player) return;
    const selected = Math.max(0, Math.min(tracks.length - 1, Number(select.value || 0)));
    const resumeAt = Number(player.currentTime || 0);
    const wasPaused = player.paused;
    const nextUrl = sharedFileRealtimeProxyUrl(file, resumeAt);
    if (!nextUrl) return;
    player.src = nextUrl;
    if (typeof player.load === "function") player.load();
    if (!wasPaused && typeof player.play === "function") player.play().catch(() => {});
    sharedFileSetMsg(`音軌：${tracks[selected]?.label || "音軌"}。`);
    return;
  }
  const hls = sharedFileState.hls;
  if (!select || tracks.length < 2 || !hls || !Array.isArray(hls.audioTracks)) return;
  const selected = Math.max(0, Math.min(tracks.length - 1, Number(select.value || 0)));
  const chosen = tracks[selected];
  const index = hls.audioTracks.findIndex((track) => {
    const name = String(track.name || track.label || "").toLowerCase();
    const lang = String(track.lang || track.language || "").toLowerCase();
    return name === chosen.label.toLowerCase() || lang === chosen.language.toLowerCase();
  });
  if (index >= 0) hls.audioTrack = index;
}

function sharedFileStreamProgressText(stream) {
  const progress = Number(stream?.progress_percent || 0);
  const progressText = progress > 0 ? `${Math.min(100, Math.max(0, Math.round(progress)))}%` : "處理中";
  const detail = stream?.stage_detail || stream?.job_error_message || stream?.error_message || "";
  return detail ? `${progressText} · ${detail}` : progressText;
}

function sharedFileIsServerEncryptedVideoProcessing(file) {
  const stream = sharedFileStreamAsset(file);
  return file?.privacy_mode === "server_encrypted"
    && sharedFileCategory(file?.display_name || "", file?.mime_type || "") === "video"
    && stream
    && (stream.status === "processing" || stream.job_status === "running" || stream.job_status === "queued");
}

function sharedFileHasReadyHls(file) {
  const stream = sharedFileStreamAsset(file);
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  return ["video", "audio"].includes(category)
    && stream
    && stream.status === "ready"
    && !!stream.master_manifest_ready;
}

function sharedFileHlsMasterUrl(file) {
  const stream = sharedFileStreamAsset(file);
  return sharedFileUrlWithPassword(stream?.master_url || `/api/storage/shared/${encodeURIComponent(sharedFileState.token)}/hls/master.m3u8`);
}

function sharedFileBrowserSupportsNativeHls(mediaType = "video") {
  const probe = document.createElement(mediaType === "audio" ? "audio" : "video");
  return !!(probe && typeof probe.canPlayType === "function" && probe.canPlayType("application/vnd.apple.mpegurl"));
}

function sharedFileLoadHlsLibrary() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (sharedFileState.hlsLibraryPromise) return sharedFileState.hlsLibraryPromise;
  sharedFileState.hlsLibraryPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-shared-file-hls-js="1"]');
    if (existing) {
      existing.addEventListener("load", () => resolve(window.Hls || null), { once: true });
      existing.addEventListener("error", () => reject(new Error("HLS.js 載入失敗")), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = SHARED_FILE_HLS_JS_URL;
    script.async = true;
    script.defer = true;
    script.dataset.sharedFileHlsJs = "1";
    script.onload = () => resolve(window.Hls || null);
    script.onerror = () => reject(new Error("HLS.js 載入失敗"));
    document.head.appendChild(script);
  }).catch((err) => {
    sharedFileState.hlsLibraryPromise = null;
    throw err;
  });
  return sharedFileState.hlsLibraryPromise;
}

function sharedFileBase64ToBytes(value) {
  const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function sharedFileFragmentKey() {
  const hash = String(window.location.hash || "").replace(/^#/, "");
  const params = new URLSearchParams(hash);
  return params.get("key") || params.get("k") || hash;
}

async function sharedFileUnwrapE2eeKey(envelope, fragmentKey) {
  const payload = typeof envelope === "string" ? JSON.parse(envelope || "{}") : (envelope || {});
  if (payload.alg !== "AES-GCM" || Number(payload.v || 0) !== 1) {
    throw new Error("E2EE 分享授權版本不支援。");
  }
  if (!fragmentKey) {
    throw new Error("分享連結缺少 E2EE 片段金鑰，請確認複製的是完整連結。");
  }
  const shareKey = await window.crypto.subtle.importKey(
    "raw",
    sharedFileBase64ToBytes(fragmentKey),
    { name: "AES-GCM", length: 256 },
    false,
    ["decrypt"],
  );
  const rawFileKey = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: sharedFileBase64ToBytes(payload.nonce) },
    shareKey,
    sharedFileBase64ToBytes(payload.ciphertext),
  );
  return window.crypto.subtle.importKey("raw", rawFileKey, { name: "AES-GCM" }, false, ["decrypt"]);
}

async function sharedFileDecryptMetadata(fileKey, encryptedMetadata) {
  if (!encryptedMetadata) return {};
  const envelope = JSON.parse(encryptedMetadata || "{}");
  const plaintext = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: sharedFileBase64ToBytes(envelope.nonce) },
    fileKey,
    sharedFileBase64ToBytes(envelope.ciphertext),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

async function sharedFileDecryptBlob(blob, file) {
  const e2ee = file?.e2ee || {};
  const fileKey = await sharedFileUnwrapE2eeKey(e2ee.wrapped_file_key_envelope, sharedFileFragmentKey());
  const plaintext = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: sharedFileBase64ToBytes(e2ee.nonce) },
    fileKey,
    await blob.arrayBuffer(),
  );
  const metadata = await sharedFileDecryptMetadata(fileKey, e2ee.encrypted_metadata);
  return {
    blob: new Blob([plaintext], { type: metadata.mime_type || "application/octet-stream" }),
    filename: metadata.filename || file.display_name || "download.bin",
  };
}

function sharedFileSaveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download.bin";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function sharedFileShowPreview(html) {
  const box = sharedFilePreviewBox();
  if (!box) return;
  box.hidden = false;
  box.innerHTML = html;
}

async function sharedFileRenderHlsPreview(file) {
  sharedFileClearPreview();
  const box = sharedFilePreviewBox();
  if (!box) return;
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  const mediaType = category === "audio" ? "audio" : "video";
  const masterUrl = sharedFileHlsMasterUrl(file);
  const safeName = sharedFileEscape(file?.display_name || "preview");
  const subtitleControls = sharedFileSubtitleShiftControlsMarkup(file, "prepared_hls");
  sharedFileShowPreview(mediaType === "audio"
    ? `<audio id="shared-file-hls-player" controls preload="metadata"></audio>${subtitleControls}`
    : `<video id="shared-file-hls-player" controls playsinline preload="metadata" title="${safeName}"></video>${subtitleControls}`);
  const player = document.getElementById("shared-file-hls-player");
  if (!player) return;
  sharedFileSyncSubtitleTracks(player, file);
  sharedFileBindSubtitleShiftControls(file, player);
  if (sharedFileBrowserSupportsNativeHls(mediaType)) {
    player.src = masterUrl;
    sharedFileSetMsg("已使用 HLS 串流預覽。");
    return;
  }
  try {
    const HlsCtor = await sharedFileLoadHlsLibrary();
    if (!HlsCtor || typeof HlsCtor.isSupported !== "function" || !HlsCtor.isSupported()) {
      throw new Error("目前瀏覽器不支援 HLS.js 所需的 MediaSource。");
    }
    const hls = new HlsCtor({ enableWorker: true, backBufferLength: 30 });
    sharedFileState.hls = hls;
    hls.on(HlsCtor.Events.ERROR, (_event, data) => {
      if (!data?.fatal) return;
      sharedFileSetMsg(`HLS 串流播放失敗：${data?.details || "請稍後重試"}`, true);
    });
    hls.loadSource(masterUrl);
    hls.attachMedia(player);
    if (HlsCtor.Events.AUDIO_TRACKS_UPDATED) {
      hls.on(HlsCtor.Events.AUDIO_TRACKS_UPDATED, () => sharedFileApplyAudioTrack(file));
    }
    sharedFileSetMsg("已使用 HLS.js 串流預覽；不會直接解密並拉取整個原始大檔。");
  } catch (err) {
    sharedFileSetMsg(err.message || "HLS 串流初始化失敗", true);
  }
}

async function sharedFileRenderDirectMediaPreview(file) {
  sharedFileClearPreview();
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  const mediaType = category === "audio" ? "audio" : "video";
  const safeName = sharedFileEscape(file?.display_name || "preview");
  const src = sharedFileContentUrl(file);
  const controls = sharedFileSubtitleShiftControlsMarkup(file, "direct");
  sharedFileShowPreview(mediaType === "audio"
    ? `<audio id="shared-file-hls-player" controls preload="metadata" src="${sharedFileEscape(src)}"></audio>${controls}`
    : `<video id="shared-file-hls-player" controls playsinline preload="metadata" src="${sharedFileEscape(src)}" title="${safeName}"></video>${controls}`);
  const player = document.getElementById("shared-file-hls-player");
  if (player) {
    sharedFileSyncSubtitleTracks(player, file);
    sharedFileBindSubtitleShiftControls(file, player);
  }
  sharedFileSetMsg("目前使用 Basic 直接串流；若瀏覽器不支援此格式，請改用 Standard 或 Premium。");
}

async function sharedFileRenderRealtimeProxyPreview(file) {
  sharedFileClearPreview();
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  const mediaType = category === "audio" ? "audio" : "video";
  const safeName = sharedFileEscape(file?.display_name || "preview");
  const src = sharedFileRealtimeProxyUrl(file, 0);
  if (!src) {
    sharedFileShowPreview(`<pre>${safeName}\nStandard 即時轉封裝目前不可用。</pre>`);
    sharedFileSetMsg("Standard 即時轉封裝目前不可用。", true);
    return;
  }
  const controls = sharedFileSubtitleShiftControlsMarkup(file, "realtime_proxy");
  sharedFileShowPreview(mediaType === "audio"
    ? `<audio id="shared-file-hls-player" controls preload="metadata" src="${sharedFileEscape(src)}"></audio>${controls}`
    : `<video id="shared-file-hls-player" controls playsinline preload="metadata" src="${sharedFileEscape(src)}" title="${safeName}"></video>${controls}`);
  const player = document.getElementById("shared-file-hls-player");
  if (player) {
    sharedFileSyncSubtitleTracks(player, file);
    sharedFileBindSubtitleShiftControls(file, player);
  }
  sharedFileSetMsg("目前使用 Standard 即時轉封裝；伺服器會即時轉出瀏覽器較好播放的音訊。");
}

async function sharedFileRenderStreamingPreview(file) {
  const category = sharedFileCategory(file?.display_name || "", file?.mime_type || "");
  if (!["video", "audio"].includes(category)) return false;
  const mode = sharedFileSelectedServiceMode(file);
  if (mode === "direct") {
    await sharedFileRenderDirectMediaPreview(file);
    return true;
  }
  if (mode === "realtime_proxy") {
    await sharedFileRenderRealtimeProxyPreview(file);
    return true;
  }
  if (sharedFileHasReadyHls(file)) {
    await sharedFileRenderHlsPreview(file);
    return true;
  }
  return false;
}

async function sharedFileRenderBlobPreview(blob, filename) {
  sharedFileClearPreview();
  const safeName = sharedFileEscape(filename || "preview");
  const category = sharedFileCategory(filename, blob.type || "");
  if (category === "text") {
    const text = await blob.text();
    sharedFileShowPreview(`<pre>${sharedFileEscape(text.slice(0, 65536))}</pre>`);
    return;
  }
  if (["image", "video", "audio", "pdf"].includes(category)) {
    const url = URL.createObjectURL(blob);
    sharedFileState.previewObjectUrl = url;
    if (category === "image") {
      sharedFileShowPreview(`<img src="${url}" alt="${safeName}" />`);
    } else if (category === "video") {
      sharedFileShowPreview(`<video controls playsinline preload="metadata" src="${url}"></video>`);
    } else if (category === "audio") {
      sharedFileShowPreview(`<audio controls preload="metadata" src="${url}"></audio>`);
    } else {
      sharedFileShowPreview(`<iframe src="${url}" title="${safeName}" loading="lazy"></iframe>`);
    }
    return;
  }
  sharedFileShowPreview(`<pre>${safeName}\n${sharedFileEscape(sharedFileFormatBytes(blob.size || 0))}</pre>`);
}

function sharedFileRenderPreviewMetadata(preview, file) {
  sharedFileClearPreview();
  const category = preview?.category || "metadata";
  const safeName = sharedFileEscape(preview?.filename || file?.display_name || "preview");
  if (preview?.render_mode === "text") {
    sharedFileShowPreview(`<pre>${sharedFileEscape(preview.text || "")}</pre>`);
    return;
  }
  if (preview?.render_mode === "archive") {
    const entries = Array.isArray(preview.entries) ? preview.entries : [];
    const rows = entries.length
      ? entries.map((entry) => `<li>${sharedFileEscape(entry.name || "-")} <span class="meta">${sharedFileEscape(sharedFileFormatBytes(entry.size || entry.compressed_size || 0))}</span></li>`).join("")
      : "<li>沒有可顯示的項目</li>";
    sharedFileShowPreview(`<ol class="preview-list">${rows}</ol>`);
    return;
  }
  if (preview?.render_mode === "media" && ["image", "video", "audio", "pdf"].includes(category)) {
    const url = sharedFileContentUrl(file);
    if (category === "image") {
      sharedFileShowPreview(`<img src="${url}" alt="${safeName}" />`);
    } else if (category === "video") {
      sharedFileShowPreview(`<video controls playsinline preload="metadata" src="${url}"></video>`);
    } else if (category === "audio") {
      sharedFileShowPreview(`<audio controls preload="metadata" src="${url}"></audio>`);
    } else {
      sharedFileShowPreview(`<iframe src="${url}" title="${safeName}" loading="lazy"></iframe>`);
    }
    return;
  }
  sharedFileShowPreview(`<pre>${safeName}\n${sharedFileEscape(preview?.mime_type || "application/octet-stream")}\n${sharedFileEscape(sharedFileFormatBytes(preview?.size_bytes || file?.size_bytes || 0))}</pre>`);
}

async function sharedFileFetchDownload(file, confirmed = false) {
  const url = new URL(file.download_url, window.location.origin);
  if (confirmed) url.searchParams.set("confirm_high_risk", "1");
  const res = await fetch(sharedFileUrlWithPassword(url.pathname + url.search), sharedFileRequestOptions());
  if (res.status === 409 && !confirmed) {
    const json = await res.json().catch(() => ({}));
    if (json.requires_confirmation && window.confirm(json.msg || "此檔案可能高風險，仍要下載？")) {
      return sharedFileFetchDownload(file, true);
    }
  }
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw sharedFileErrorFromResponse(res, json, `下載失敗（HTTP ${res.status}）`);
  }
  const label = file.e2ee?.requires_fragment_key
    ? "正在下載 E2EE 密文"
    : (file.privacy_mode === "server_encrypted" ? "正在伺服器端解密並下載" : "正在下載檔案");
  return sharedFileReadResponseBlobWithProgress(res, label, file.size_bytes || 0);
}

async function sharedFileDownload() {
  const file = sharedFileState.file;
  if (!file) return;
  const btn = document.getElementById("shared-file-download-btn");
  if (btn) btn.disabled = true;
  sharedFileSetMsg("準備下載...");
  try {
    const blob = await sharedFileFetchDownload(file);
    if (file.e2ee?.requires_fragment_key) {
      if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 E2EE 分享解密。");
      sharedFileShowProgress("正在瀏覽器端解密 E2EE 檔案", blob.size || file.size_bytes || 0, blob.size || file.size_bytes || 0, "密碼與私鑰只在此瀏覽器使用。");
      sharedFileSetMsg("正在瀏覽器端解密...");
      const decrypted = await sharedFileDecryptBlob(blob, file);
      sharedFileSaveBlob(decrypted.blob, decrypted.filename);
    } else {
      sharedFileSaveBlob(blob, file.display_name || "download.bin");
    }
    sharedFileSetMsg("下載已開始。");
  } catch (err) {
    sharedFileMaybeShowLogin(err);
    sharedFileSetMsg(err.message || "下載失敗", true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function sharedFilePreview() {
  const file = sharedFileState.file;
  if (!file) return;
  const btn = document.getElementById("shared-file-preview-btn");
  if (btn) btn.disabled = true;
  sharedFileSetMsg("準備預覽...");
  try {
    if (!file.can_preview) throw new Error("此分享連結未開放瀏覽器預覽。");
    if (file.e2ee?.requires_fragment_key) {
      if (!window.crypto?.subtle) throw new Error("此瀏覽器不支援 E2EE 分享解密。");
      const blob = await sharedFileFetchBlobWithProgress(
        sharedFileContentUrl(file),
        sharedFileRequestOptions(),
        "正在下載 E2EE 密文以供預覽",
        file.size_bytes || 0,
      );
      sharedFileShowProgress("正在瀏覽器端解密 E2EE 預覽", blob.size || file.size_bytes || 0, blob.size || file.size_bytes || 0, "解密在本機瀏覽器完成，伺服器不會取得明文。");
      const decrypted = await sharedFileDecryptBlob(blob, file);
      await sharedFileRenderBlobPreview(decrypted.blob, decrypted.filename);
      sharedFileSetMsg("預覽已在瀏覽器端解密。");
      return;
    }
    if (await sharedFileRenderStreamingPreview(file)) {
      return;
    }
    if (sharedFileIsServerEncryptedVideoProcessing(file)) {
      const stream = sharedFileStreamAsset(file);
      sharedFileShowPreview(`<pre>${sharedFileEscape(file.display_name || "影片")}\nHLS 串流準備中：${sharedFileEscape(sharedFileStreamProgressText(stream))}</pre>`);
      sharedFileSetMsg("這個伺服器端加密影片仍在背景建立 HLS；完成前不觸發主程序整檔解密預覽。");
      return;
    }
    const res = await fetch(sharedFilePreviewMetadataUrl(file), sharedFileRequestOptions());
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw sharedFileErrorFromResponse(res, json, `預覽失敗（HTTP ${res.status}）`);
    const preview = json.preview || {};
    const previewCategory = preview?.category || sharedFileCategory(file.display_name || "", file.mime_type || "");
    if (
      file.privacy_mode === "server_encrypted"
      && preview?.render_mode === "media"
      && ["image", "video", "audio", "pdf"].includes(previewCategory)
    ) {
      sharedFileSetMsg("HLS 尚未就緒，正在伺服器端解密並傳輸原始檔預覽。");
      const blob = await sharedFileFetchBlobWithProgress(
        sharedFileContentUrl(file),
        sharedFileRequestOptions(),
        "正在伺服器端解密並傳輸原始檔預覽",
        file.size_bytes || preview.size_bytes || 0,
      );
      await sharedFileRenderBlobPreview(blob, preview.filename || file.display_name || "preview");
      sharedFileSetMsg("原始檔預覽已載入；若瀏覽器不支援此格式，請等待 HLS 或下載後播放。");
      return;
    }
    sharedFileRenderPreviewMetadata(preview, file);
    sharedFileSetMsg("預覽已載入。");
  } catch (err) {
    sharedFileMaybeShowLogin(err);
    sharedFileSetMsg(err.message || "預覽失敗", true);
  } finally {
    if (btn) btn.disabled = !sharedFileState.file?.can_preview;
  }
}

async function sharedFileLoad() {
  sharedFileState.token = sharedFileToken();
  if (!sharedFileState.password) sharedFileState.password = sharedFileRememberedPassword();
  const title = document.getElementById("shared-file-title");
  const meta = document.getElementById("shared-file-meta");
  const downloadBtn = document.getElementById("shared-file-download-btn");
  const previewBtn = document.getElementById("shared-file-preview-btn");
  if (!sharedFileState.token) {
    sharedFileSetMsg("分享連結不完整。", true);
    return;
  }
  try {
    const res = await fetch(`/api/storage/shared/${encodeURIComponent(sharedFileState.token)}`, sharedFileRequestOptions());
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw sharedFileErrorFromResponse(res, json, "分享連結不存在或已失效");
    const file = json.file || {};
    sharedFileState.file = file;
    sharedFileClearPasswordForm();
    sharedFileSetLoginRequired(false);
    if (title) title.textContent = file.display_name || "檔案分享";
    const e2eeText = file.e2ee?.requires_fragment_key ? " · E2EE 瀏覽器端解密" : "";
    const previewText = file.can_preview ? " · 可瀏覽器預覽" : " · 未開放預覽";
    const passwordText = file.password_required ? " · 需要分享密碼" : "";
    const scopeText = file.access_scope === "account" ? ` · 限 ${file.required_username || "指定帳戶"}` : " · 知道連結即可下載";
    const stream = sharedFileStreamAsset(file);
    const streamText = stream?.status === "processing"
      ? ` · HLS ${sharedFileStreamProgressText(stream)}`
      : (sharedFileHasReadyHls(file) ? " · HLS 串流已就緒" : "");
    if (meta) meta.textContent = `${sharedFileFormatBytes(file.size_bytes)}${scopeText}${previewText}${passwordText}${e2eeText}${streamText}`;
    if (downloadBtn) {
      downloadBtn.disabled = false;
      downloadBtn.onclick = sharedFileDownload;
    }
    if (previewBtn) {
      previewBtn.disabled = !file.can_preview;
      previewBtn.onclick = sharedFilePreview;
    }
    if (sharedFileIsServerEncryptedVideoProcessing(file)) {
      sharedFileSetMsg(`HLS 串流準備中：${sharedFileStreamProgressText(stream)}。完成前不觸發主程序整檔解密預覽。`);
    } else if (sharedFileHasReadyHls(file)) {
      sharedFileSetMsg("此影音會使用 HLS 串流預覽，不會直接讀取整個原始檔。");
    } else {
      sharedFileSetMsg(file.e2ee?.requires_fragment_key ? "請使用包含 #key= 的完整分享連結預覽或下載。" : "");
    }
  } catch (err) {
    if (title) title.textContent = "檔案無法開啟";
    if (meta) meta.textContent = "";
    sharedFileMaybeShowLogin(err);
    if (err?.reason === "password_required" || err?.reason === "password_invalid") {
      sharedFileSetPassword(err?.reason === "password_invalid" ? "" : sharedFileState.password);
      sharedFileRenderPasswordForm(err?.message || "此分享連結需要密碼。");
      return;
    }
    sharedFileSetMsg(err.message || "分享連結不存在或已失效", true);
  }
}

document.addEventListener("DOMContentLoaded", sharedFileLoad);
window.addEventListener("beforeunload", sharedFileClearPreview);
