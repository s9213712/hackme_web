"use strict";
// Standalone JS for /shared/videos/<token>.
// Extracted from routes/videos.py inline <script> to satisfy CSP
// `script-src: 'self'` (server.py:623). See issue #182.
//
// TOKEN is delivered via a <script id="share-token" type="application/json">
// island in the rendered HTML.

(function () {
  const TOKEN = (() => {
    const el = document.getElementById("share-token");
    if (!el) return "";
    try { return JSON.parse(el.textContent || "\"\"") || ""; } catch (_) { return ""; }
  })();

  function $(id) { return document.getElementById(id); }
  function setMsg(text, bad=false) {
    const el = $("msg");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = bad ? "#ff9da1" : "#b9c2f0";
  }
  function isSharePasswordResponse(res, json) {
    const reason = String(json?.reason || "").trim();
    return [401, 403, 429].includes(Number(res?.status || 0))
      || !!json?.password_required
      || ["password_required", "password_invalid", "password_locked"].includes(reason);
  }
  function showSharePasswordPrompt(message) {
    const form = $("share-password-form");
    if (form) form.classList.remove("hidden");
    const input = $("share-password");
    if (input) {
      try { input.focus(); } catch (_err) {}
    }
    const meta = $("meta");
    if (meta && (!meta.textContent || meta.textContent === "讀取中...")) {
      meta.textContent = "此分享影音需要先解鎖";
    }
    setMsg(message || "這部影音需要分享密碼");
  }
  function formatProgressBytes(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num) || num <= 0) return "0 B";
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
    if (num < 1024 * 1024 * 1024) return `${(num / 1024 / 1024).toFixed(1)} MB`;
    return `${(num / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[ch] || ch));
  }
  async function readBlobWithProgress(response, onProgress) {
    if (!response.body || typeof response.body.getReader !== "function") {
      return response.blob();
    }
    const total = Number(response.headers.get("Content-Length") || 0);
    const reader = response.body.getReader();
    const chunks = [];
    let loaded = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        loaded += value.byteLength || 0;
        if (typeof onProgress === "function") onProgress(loaded, total);
      }
    }
    return new Blob(chunks, { type: response.headers.get("Content-Type") || "application/octet-stream" });
  }
  function browserSupportsNativeHls(mediaType="video") {
    const probe = document.createElement(mediaType === "audio" ? "audio" : "video");
    return !!(probe && typeof probe.canPlayType === "function" && probe.canPlayType("application/vnd.apple.mpegurl"));
  }
  function sharedQualityOptions(playback={}) {
    const variants = Array.isArray(playback?.variants)
      ? playback.variants
      : (Array.isArray(playback?.status?.variants) ? playback.status.variants : []);
    return variants.filter((variant) => variant && variant.name).map((variant) => {
      const height = Number(variant.height || 0);
      const label = variant.label
        || (variant.name === "original" ? (height ? `原畫質 ${height}p` : "原畫質") : (height ? `${height}p` : variant.name));
      return {
        name: String(variant.name || ""),
        label: String(label || variant.name || ""),
        height,
        playlistUrl: String(variant.playlist_url || ""),
        manifestUrl: String(variant.manifest_url || ""),
        chunkUrlTemplate: String(variant.chunk_url_template || ""),
      };
    });
  }
  function preferredSharedQuality(playback={}) {
    const options = sharedQualityOptions(playback);
    if (!options.length) return null;
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection?.saveData || Number(connection?.downlink || 0) > 0 && Number(connection.downlink) < 2) {
      const low = options.find((option) => Number(option.height || 0) === 480)
        || options.find((option) => Number(option.height || 0) === 360);
      if (low) return low;
    }
    const preferredName = String(playback?.default_quality || playback?.quality_policy?.default_quality || "").trim();
    if (preferredName) {
      const named = options.find((option) => option.name === preferredName);
      if (named) return named;
    }
    return options.find((option) => Number(option.height || 0) === 720)
      || options.find((option) => Number(option.height || 0) === 480)
      || options.find((option) => option.name !== "original" && option.name !== "audio")
      || options[0]
      || null;
  }
  function fallbackSharedQuality(playback={}) {
    const options = sharedQualityOptions(playback);
    const fallbackName = String(playback?.fallback_quality || playback?.quality_policy?.fallback_quality || "").trim();
    if (fallbackName) {
      const named = options.find((option) => option.name === fallbackName);
      if (named) return named;
    }
    return options.find((option) => Number(option.height || 0) === 480) || null;
  }
  function selectedSharedQuality(playback={}) {
    const select = $("quality-select");
    const selected = String(select?.value || "").trim();
    if (!selected || selected === "auto") return null;
    return sharedQualityOptions(playback).find((option) => option.name === selected) || null;
  }
  let sharedHls = null;
  let sharedHlsLoadPromise = null;
  let sharedManualQualitySelection = false;
  let sharedAutoQualityFallbackApplied = false;
  let sharedUserSeeking = false;
  let sharedLastSeekAt = 0;
  let sharedLastSeekTarget = 0;
  let shareSessionId = "";
  let sharedE2eeFragmentKey = "";
  let sharedE2eeStreamCleanup = null;
  const SHARED_E2EE_STREAM_V2_MAX_RETRIES = 2;
  const SHARED_E2EE_STREAM_V2_CACHE_LIMIT = 16;
  function withShareSession(url) {
    const raw = String(url || "");
    if (!raw || !shareSessionId) return raw;
    try {
      const parsed = new URL(raw, window.location.origin);
      parsed.searchParams.set("share_session", shareSessionId);
      return parsed.pathname + parsed.search + parsed.hash;
    } catch (_err) {
      const separator = raw.includes("?") ? "&" : "?";
      return `${raw}${separator}share_session=${encodeURIComponent(shareSessionId)}`;
    }
  }
  function rememberShareSession(value) {
    shareSessionId = String(value || "").trim();
  }
  function applyShareSessionToPlayback(playback) {
    if (!playback || typeof playback !== "object") return playback || {};
    [
      "fallback_url",
      "stream_url",
      "ciphertext_url",
      "e2ee_key_url",
      "manifest_url",
      "chunk_url_template",
      "master_url",
    ].forEach((key) => {
      if (playback[key]) playback[key] = withShareSession(playback[key]);
    });
    for (const variant of playback.variants || []) {
      if (!variant || typeof variant !== "object") continue;
      ["playlist_url", "manifest_url", "chunk_url_template"].forEach((key) => {
        if (variant[key]) variant[key] = withShareSession(variant[key]);
      });
    }
    return playback;
  }
  function destroySharedPlaybackArtifacts() {
    if (sharedE2eeStreamCleanup) {
      try { sharedE2eeStreamCleanup(); } catch (_) {}
      sharedE2eeStreamCleanup = null;
    }
    if (sharedHls && typeof sharedHls.destroy === "function") {
      try { sharedHls.destroy(); } catch (_) {}
    }
    sharedHls = null;
  }
  function renderSharedQualityControl(playback={}) {
    const host = $("quality-host");
    if (!host) return;
    const options = sharedQualityOptions(playback);
    if (options.length < 2) {
      host.classList.add("hidden");
      host.innerHTML = "";
      return;
    }
    const preferred = preferredSharedQuality(playback);
    host.innerHTML = `
      <label for="quality-select">畫質</label>
      <select id="quality-select">
        <option value="auto"${preferred?.name ? "" : " selected"}>自動</option>
        ${options.map((option) => `<option value="${escapeHtml(option.name)}"${option.name === preferred?.name ? " selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}
      </select>
      <small>預設 720p；網路不穩時會嘗試退回 480p。串流衍生畫質不佔用分享者雲端硬碟容量。</small>
    `;
    host.classList.remove("hidden");
    const select = $("quality-select");
    if (select) {
      select.addEventListener("change", () => {
        sharedManualQualitySelection = true;
        applySharedQualitySelection(playback);
      });
    }
  }
  function applySharedQualitySelection(playback={}) {
    const player = $("shared-player");
    if (!player) return;
    const variant = selectedSharedQuality(playback);
    if (playback?.mode === "e2ee_stream_v2") {
      if (!sharedE2eeFragmentKey) {
        setMsg(variant ? `已選擇 ${variant.label}；按下「開始 E2EE 播放」後套用。` : "已切回自動畫質；按下「開始 E2EE 播放」後套用。");
        return;
      }
      const resumeAt = sharedPlaybackResumeTime(player);
      const wasPaused = player.paused;
      attachSharedE2eeStreamV2(player, playback, sharedE2eeFragmentKey, {
        resumeAt,
        autoplay: !wasPaused,
      }).catch((err) => setMsg(err.message || "E2EE 畫質切換失敗", true));
      return;
    }
    if (sharedHls && Array.isArray(sharedHls.levels)) {
      if (!variant) {
        sharedHls.currentLevel = -1;
        setMsg("畫質：自動；播放器會依網路狀況調整。");
        return;
      }
      const levelIndex = sharedHls.levels.findIndex((level) => Number(level.height || 0) === Number(variant.height || 0));
      if (levelIndex >= 0) {
        sharedHls.currentLevel = levelIndex;
        setMsg(`畫質：${variant.label}。`);
        return;
      }
    }
    const nextUrl = variant?.playlistUrl || playback.master_url || "";
    if (!nextUrl) return;
    const resumeAt = sharedPlaybackResumeTime(player);
    const wasPaused = player.paused;
    player.src = nextUrl;
    if (typeof player.load === "function") player.load();
    player.addEventListener("loadedmetadata", () => {
      try {
        if (resumeAt > 0 && Number.isFinite(resumeAt)) player.currentTime = resumeAt;
        if (!wasPaused && typeof player.play === "function") player.play().catch(() => {});
      } catch (_err) {}
    }, { once: true });
    setMsg(variant ? `畫質：${variant.label}。` : "畫質：自動。");
  }
  function bindSharedSeekProtection(player) {
    if (!player || player.dataset.sharedSeekProtectionBound === "1") return;
    player.dataset.sharedSeekProtectionBound = "1";
    player.addEventListener("seeking", () => {
      sharedUserSeeking = true;
      sharedLastSeekAt = Date.now();
      sharedLastSeekTarget = Number(player.currentTime || 0);
    });
    const clearSeeking = () => {
      sharedLastSeekAt = Date.now();
      sharedLastSeekTarget = Number(player.currentTime || sharedLastSeekTarget || 0);
      window.setTimeout(() => {
        if (Date.now() - Number(sharedLastSeekAt || 0) >= 900) {
          sharedUserSeeking = false;
        }
      }, 950);
    };
    player.addEventListener("seeked", clearSeeking);
    player.addEventListener("playing", clearSeeking);
  }
  function sharedQualityFallbackDeferredForSeek(player) {
    if (!player) return false;
    const recentSeek = Date.now() - Number(sharedLastSeekAt || 0) < 1500;
    return !!(player.seeking || sharedUserSeeking || recentSeek);
  }
  function sharedPlaybackResumeTime(player) {
    if (!player) return 0;
    const seekTarget = Number(sharedLastSeekTarget || 0);
    if (sharedQualityFallbackDeferredForSeek(player) && Number.isFinite(seekTarget) && seekTarget > 0) {
      return seekTarget;
    }
    const current = Number(player.currentTime || 0);
    return Number.isFinite(current) ? current : 0;
  }
  function fallbackSharedPlaybackToLowerQuality(playback={}, reason="") {
    if (sharedManualQualitySelection || sharedAutoQualityFallbackApplied) return false;
    const player = $("shared-player");
    if (sharedQualityFallbackDeferredForSeek(player)) {
      setMsg("正在跳轉到指定時間，暫不自動切換畫質。");
      return false;
    }
    const fallback = fallbackSharedQuality(playback);
    if (!fallback) return false;
    const current = selectedSharedQuality(playback);
    if (current && current.name === fallback.name) return false;
    const select = $("quality-select");
    if (!select) return false;
    if (select) select.value = fallback.name;
    sharedAutoQualityFallbackApplied = true;
    applySharedQualitySelection(playback);
    setMsg(`網路狀況不穩，已自動切換為 ${fallback.label}${reason ? `；${reason}` : ""}。`);
    return true;
  }
  function clearSharedPlaybackAction() {
    const wrap = $("player-action");
    if (!wrap) return;
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
  }
  function showSharedPlaybackAction(label, onClick, helperText="") {
    const wrap = $("player-action");
    if (!wrap) return;
    wrap.classList.remove("hidden");
    wrap.innerHTML = `
      <button type="button" id="shared-playback-start-btn">${label}</button>
      ${helperText ? `<div class="meta" style="margin-top:.5rem;">${helperText}</div>` : ""}
    `;
    const button = $("shared-playback-start-btn");
    if (!button) return;
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.disabled = true;
      try {
        clearSharedPlaybackAction();
        await onClick();
      } catch (err) {
        setMsg(err.message || "E2EE 影音播放初始化失敗", true);
        button.disabled = false;
        showSharedPlaybackAction(label, onClick, helperText);
      }
    }, { once: true });
  }
  function loadSharedHlsLibrary(url) {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (sharedHlsLoadPromise) return sharedHlsLoadPromise;
    sharedHlsLoadPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-shared-hls-js="1"]');
      if (existing) {
        existing.addEventListener("load", () => resolve(window.Hls || null), { once: true });
        existing.addEventListener("error", () => reject(new Error("HLS.js 載入失敗")), { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = url;
      script.async = true;
      script.defer = true;
      script.dataset.sharedHlsJs = "1";
      script.onload = () => resolve(window.Hls || null);
      script.onerror = () => reject(new Error("HLS.js 載入失敗"));
      document.head.appendChild(script);
    }).catch((err) => {
      sharedHlsLoadPromise = null;
      throw err;
    });
    return sharedHlsLoadPromise;
  }
  function b64ToBytes(value) {
    const binary = atob(String(value || "").replace(/\s+/g, ""));
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
    return out;
  }
  function b64UrlToBytes(value) {
    const normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
    return b64ToBytes(padded);
  }
  function playerTimeBuffered(player, timeSeconds) {
    if (!player?.buffered) return false;
    const target = Number(timeSeconds || 0);
    for (let i = 0; i < player.buffered.length; i += 1) {
      if (target >= player.buffered.start(i) && target <= player.buffered.end(i)) return true;
    }
    return false;
  }
  function browserSupportsE2eeStreamV2() {
    return Boolean(window.MediaSource && window.Worker && window.crypto?.subtle);
  }
  function sharedE2eeChunkIndexForTime(manifest, timeSeconds) {
    const chunkCount = Number(manifest?.chunk_count || 0);
    const duration = Number(manifest?.duration_hint || 0);
    const target = Number(timeSeconds || 0);
    if (!Number.isFinite(chunkCount) || chunkCount <= 0 || !Number.isFinite(duration) || duration <= 0) return null;
    if (!Number.isFinite(target) || target <= 0) return 0;
    return Math.max(0, Math.min(chunkCount - 1, Math.floor((target / duration) * chunkCount)));
  }
  function pruneSharedE2eeChunkCache(cache, keepAroundIndex) {
    if (!cache || cache.size <= SHARED_E2EE_STREAM_V2_CACHE_LIMIT) return;
    const keep = Number(keepAroundIndex || 0);
    const keys = Array.from(cache.keys()).sort((a, b) => Math.abs(a - keep) - Math.abs(b - keep));
    const keepSet = new Set(keys.slice(0, SHARED_E2EE_STREAM_V2_CACHE_LIMIT));
    for (const key of cache.keys()) {
      if (!keepSet.has(key)) cache.delete(key);
    }
  }
  async function fetchSharedE2eeChunkWithRetry(url, retries = SHARED_E2EE_STREAM_V2_MAX_RETRIES) {
    let lastError = null;
    for (let attempt = 0; attempt <= retries; attempt += 1) {
      try {
        const chunkRes = await fetch(withShareSession(url), { credentials: "same-origin" });
        if (!chunkRes.ok) {
          const payload = await chunkRes.json().catch(() => ({}));
          throw new Error(payload.msg || `HTTP ${chunkRes.status}`);
        }
        return chunkRes.arrayBuffer();
      } catch (err) {
        lastError = err;
        if (attempt >= retries) break;
        await new Promise((resolve) => setTimeout(resolve, 200 * (attempt + 1)));
      }
    }
    throw lastError || new Error("E2EE Streaming v2 分段下載失敗");
  }
  function createSharedE2eeWorker() {
    return new Worker("/js/e2ee-stream-v2-worker.js?v=20260505-e2eev2");
  }
  function decryptSharedChunkWithWorker(worker, keyBytes, nonce, ciphertext) {
    return new Promise((resolve, reject) => {
      const id = `${Date.now()}:${Math.random().toString(16).slice(2)}`;
      const keyBuffer = keyBytes.buffer.slice(0);
      const onMessage = (event) => {
        const payload = event?.data || {};
        if (payload.id !== id) return;
        worker.removeEventListener("message", onMessage);
        if (payload.type === "decrypt-chunk-ok") resolve(payload.plaintext);
        else reject(new Error(payload.message || "E2EE chunk 解密失敗"));
      };
      worker.addEventListener("message", onMessage);
      worker.postMessage({
        type: "decrypt-chunk",
        id,
        keyBytes: keyBuffer,
        nonce,
        ciphertext,
      }, [keyBuffer, ciphertext]);
    });
  }
  function appendSharedSourceBufferAsync(sourceBuffer, payload) {
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
  function shareKeyFromFragment() {
    const hash = String(window.location.hash || "");
    const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
    return String(params.get("vk") || "").trim();
  }
    async function importShareKey(rawFragment) {
      const bytes = b64UrlToBytes(rawFragment);
      if (bytes.byteLength < 32) {
      throw new Error("分享連結缺少有效的片段金鑰，請向分享者重新取得完整連結。");
      }
      return crypto.subtle.importKey("raw", bytes, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
    }
  async function unwrapSharedFileKeyBytes(envelopeText, fragmentKey) {
    const envelope = JSON.parse(envelopeText || "{}");
    if (String(envelope.alg || "") !== "AES-GCM" || Number(envelope.v || 0) !== 1) {
      throw new Error("分享金鑰封裝格式不支援，請分享者重新產生分享連結。");
    }
    try {
      const wrappingKey = await importShareKey(fragmentKey);
      return await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: b64ToBytes(envelope.nonce) },
        wrappingKey,
        b64ToBytes(envelope.ciphertext)
      );
    } catch (_) {
      throw new Error("分享授權無效或已被竄改。請確認你持有完整分享連結；若分享者遺失 fragment，只能重新產生分享。");
    }
  }
  async function unwrapSharedFileKey(envelopeText, fragmentKey) {
    const rawKey = await unwrapSharedFileKeyBytes(envelopeText, fragmentKey);
    return crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, true, ["decrypt"]);
  }
  async function decryptJsonMetadata(fileKey, encryptedMetadata) {
    const envelope = JSON.parse(encryptedMetadata || "{}");
    const plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64ToBytes(envelope.nonce) }, fileKey, b64ToBytes(envelope.ciphertext));
    return JSON.parse(new TextDecoder().decode(plaintext));
  }
  async function decryptSharedE2eeBlob(blob, e2eeShare, fragmentKey) {
    const fileKey = await unwrapSharedFileKey(e2eeShare.wrapped_file_key_envelope, fragmentKey);
    const plaintext = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64ToBytes(e2eeShare.nonce) }, fileKey, await blob.arrayBuffer());
    const metadata = await decryptJsonMetadata(fileKey, e2eeShare.encrypted_metadata);
    return {
      blob: new Blob([plaintext], { type: metadata.mime_type || "application/octet-stream" }),
      filename: metadata.filename || "media",
    };
  }
  async function fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, message, seekTarget = null) {
    setMsg(message || "已退回舊版完整解密播放。", false);
    setMsg("正在讀取 E2EE 分享授權：伺服器只會提供密文與分享封裝，不會接收原始密碼、raw file key 或 #vk。");
    const keyRes = await fetch(withShareSession(playback.e2ee_key_url), { credentials: "same-origin" });
    const keyJson = await keyRes.json().catch(() => ({}));
    if (!keyRes.ok || !keyJson.ok || !keyJson.e2ee_share) throw new Error(keyJson.msg || "E2EE 分享解密資訊讀取失敗");
    const cipherRes = await fetch(withShareSession(playback.ciphertext_url), { credentials: "same-origin" });
    if (!cipherRes.ok) throw new Error("E2EE 密文讀取失敗");
    const cipherBlob = await readBlobWithProgress(cipherRes, (loaded, total) => {
      const summary = total > 0
        ? `${formatProgressBytes(loaded)} / ${formatProgressBytes(total)}`
        : formatProgressBytes(loaded);
      setMsg(`正在下載加密影音檔：${summary}。完成後會在瀏覽器端解密，不會把密碼或金鑰送到伺服器。`);
    });
    setMsg("正在瀏覽器端解密影音。這一步不會把原始 E2EE 密碼、raw file key 或 #vk 傳到伺服器。");
    const decrypted = await decryptSharedE2eeBlob(cipherBlob, keyJson.e2ee_share, fragmentKey);
    player.src = URL.createObjectURL(decrypted.blob);
    if (seekTarget !== null) {
      player.addEventListener("loadedmetadata", () => {
        try { player.currentTime = seekTarget; } catch (_) {}
      }, { once: true });
    }
  }
  function sharedE2eeQualityOptions(playback={}) {
    return sharedQualityOptions(playback).filter((option) => option.manifestUrl && option.chunkUrlTemplate);
  }
  function preferredSharedE2eeQuality(playback={}, preferOriginal=false) {
    const options = sharedE2eeQualityOptions(playback);
    if (!options.length) return null;
    if (preferOriginal) {
      return options.find((option) => option.name === "original") || options[0] || null;
    }
    const selected = selectedSharedQuality(playback);
    if (selected && selected.manifestUrl && selected.chunkUrlTemplate) return selected;
    const preferred = preferredSharedQuality({ ...playback, variants: options });
    return preferred || options.find((option) => option.name === "original") || options[0] || null;
  }
  async function attachSharedE2eeStreamV2(player, playback, fragmentKey, options={}) {
    if (!browserSupportsE2eeStreamV2()) {
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, "目前裝置不支援 E2EE Streaming v2，已退回舊版完整解密播放。");
      return;
    }
    if (sharedE2eeStreamCleanup) {
      try { sharedE2eeStreamCleanup(); } catch (_) {}
      sharedE2eeStreamCleanup = null;
    }
    const activeVariant = preferredSharedE2eeQuality(playback, !!options.preferOriginal);
    const activeManifestUrl = activeVariant?.manifestUrl || playback.manifest_url || "";
    const activeChunkUrlTemplate = activeVariant?.chunkUrlTemplate || playback.chunk_url_template || "";
    if (!activeManifestUrl || !activeChunkUrlTemplate) {
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, "此 strict E2EE 影音尚未建立可用的 encrypted streaming manifest，已退回舊版完整解密播放。");
      return;
    }
    setMsg(`正在讀取 E2EE 分享授權：strict E2EE 仍由瀏覽器端持有 fragment 與解密能力。${activeVariant?.label ? `畫質：${activeVariant.label}。` : ""}`);
    const manifestRes = await fetch(withShareSession(activeManifestUrl), { credentials: "same-origin" });
    const manifestJson = await manifestRes.json().catch(() => ({}));
    if (!manifestRes.ok || manifestJson.available === false) {
      if (activeVariant?.name !== "original" && playback.manifest_url && playback.chunk_url_template) {
        const select = $("quality-select");
        if (select) select.value = "original";
        setMsg(`${activeVariant?.label || "所選畫質"}暫不可用，改用原畫質 encrypted stream。`);
        await attachSharedE2eeStreamV2(player, playback, fragmentKey, {
          ...options,
          preferOriginal: true,
        });
        return;
      }
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, manifestJson.msg || "此 strict E2EE 影音尚未建立 Streaming v2 manifest，已退回舊版完整解密播放。");
      return;
    }
    const rawKey = new Uint8Array(await unwrapSharedFileKeyBytes((await (await fetch(withShareSession(playback.e2ee_key_url), { credentials: "same-origin" })).json()).e2ee_share.wrapped_file_key_envelope, fragmentKey));
    const mediaSource = new MediaSource();
    const objectUrl = URL.createObjectURL(mediaSource);
    player.src = objectUrl;
    const resumeAt = Number(options.resumeAt || 0);
    const autoplay = !!options.autoplay;
    if (resumeAt > 0 || autoplay) {
      player.addEventListener("loadedmetadata", () => {
        try {
          if (resumeAt > 0 && Number.isFinite(resumeAt)) player.currentTime = resumeAt;
          if (autoplay && typeof player.play === "function") player.play().catch(() => {});
        } catch (_) {}
      }, { once: true });
    }
    setMsg(`正在使用 E2EE Streaming v2：${activeVariant?.label || "自動畫質"}，密文分段下載、瀏覽器端 Web Worker 解密，伺服器無法看到明文。`);
    const worker = createSharedE2eeWorker();
    let nextChunk = 0;
    let sourceBuffer = null;
    let closed = false;
    let pendingSeekChunk = null;
    const chunkCache = new Map();
    const cleanup = () => {
      if (closed) return;
      closed = true;
      try { worker.terminate(); } catch (_) {}
      try { URL.revokeObjectURL(objectUrl); } catch (_) {}
      if (sharedE2eeStreamCleanup === cleanup) sharedE2eeStreamCleanup = null;
    };
    sharedE2eeStreamCleanup = cleanup;
    const fallback = async (message, seekTarget = null) => {
      cleanup();
      await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, message, seekTarget);
    };
    player.addEventListener("seeking", () => {
      const target = Number(player.currentTime || 0);
      const targetChunk = sharedE2eeChunkIndexForTime(manifestJson, target);
      if (!playerTimeBuffered(player, target) && targetChunk !== null && targetChunk >= nextChunk) {
        pendingSeekChunk = targetChunk;
        setMsg(`快轉目標尚未緩衝，正在以 Streaming v2 追上分段 ${targetChunk + 1}。`);
        return;
      }
      if (!playerTimeBuffered(player, target) && nextChunk < Number(manifestJson.chunk_count || 0)) {
        fallback("偵測到尚未緩衝區段的快轉，已退回舊版完整解密播放以確保可用性。", target).catch((err) => setMsg(err.message || "E2EE fallback 失敗", true));
      }
    });
    mediaSource.addEventListener("sourceopen", () => {
      try {
        sourceBuffer = mediaSource.addSourceBuffer(manifestJson.content_type || "video/mp4");
      } catch (err) {
        fallback("目前裝置無法以 MediaSource 播放此 strict E2EE 影音，已退回舊版完整解密播放。").catch((fallbackErr) => setMsg(fallbackErr.message || "E2EE fallback 失敗", true));
        return;
      }
      const pump = async () => {
        if (closed || !sourceBuffer) return;
        if (nextChunk >= Number(manifestJson.chunk_count || 0)) {
          if (mediaSource.readyState === "open" && !sourceBuffer.updating) {
            try { mediaSource.endOfStream(); } catch (_) {}
          }
          cleanup();
          setMsg(`正在使用 E2EE Streaming v2：${activeVariant?.label || "自動畫質"}；若裝置或格式不支援快轉，系統會退回舊版完整解密播放。`);
          return;
        }
        const meta = manifestJson.chunks?.[nextChunk];
        if (!meta) {
          await fallback("E2EE Streaming v2 chunk metadata 缺失，已退回舊版完整解密播放。");
          return;
        }
        let plain = chunkCache.get(Number(meta.chunk_index));
        if (!plain) {
          const cipher = await fetchSharedE2eeChunkWithRetry(activeChunkUrlTemplate.replace("__INDEX__", String(meta.chunk_index)));
          plain = await decryptSharedChunkWithWorker(worker, new Uint8Array(rawKey), meta.nonce, cipher);
          chunkCache.set(Number(meta.chunk_index), plain);
          pruneSharedE2eeChunkCache(chunkCache, Number(meta.chunk_index));
        }
        await appendSharedSourceBufferAsync(sourceBuffer, new Uint8Array(plain));
        nextChunk += 1;
        if (pendingSeekChunk !== null && nextChunk > pendingSeekChunk) pendingSeekChunk = null;
        const seekNote = pendingSeekChunk !== null ? "，正在追上快轉目標" : "";
        setMsg(`正在使用 E2EE Streaming v2：${activeVariant?.label || "自動畫質"}，已解密分段 ${nextChunk} / ${manifestJson.chunk_count}${seekNote}。`);
        queueMicrotask(() => {
          pump().catch((err) => fallback(`E2EE Streaming v2 分段播放失敗，已退回舊版完整解密播放。 (${err.message || "unknown"})`));
        });
      };
      pump().catch((err) => fallback(err.message || "E2EE Streaming v2 初始化失敗"));
    }, { once: true });
  }
  async function fetchCsrfToken() {
    // The shared-video page is standalone (no global core helpers loaded), so
    // we fetch the CSRF token on demand rather than relying on getCsrfToken().
    try {
      const res = await fetch("/api/csrf-token", { credentials: "same-origin" });
      const json = await res.json().catch(() => ({}));
      return String(json?.csrf_token || "");
    } catch (_) {
      return "";
    }
  }
  async function unlockShare(password) {
    const csrf = await fetchCsrfToken();
    const headers = { "Content-Type": "application/json" };
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const res = await fetch(`/api/videos/shared/${encodeURIComponent(TOKEN)}/unlock`, {
      method: "POST",
      credentials: "same-origin",
      headers,
      body: JSON.stringify({ password }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `HTTP ${res.status}`);
    rememberShareSession(json.share_session_id);
    return json;
  }
  async function fetchJson(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(withShareSession(url), {
        credentials: "same-origin",
        signal: controller.signal,
      });
      const json = await res.json().catch(() => ({}));
      return { res, json };
    } finally {
      clearTimeout(timer);
    }
  }
  async function loadSharedVideo() {
    const metaEl = $("meta");
    if (metaEl) metaEl.textContent = "正在讀取分享資訊...";
    const meta = await fetchJson(`/api/videos/shared/${encodeURIComponent(TOKEN)}`);
    if (isSharePasswordResponse(meta.res, meta.json)) {
      showSharePasswordPrompt(meta.json.msg || "這部影音需要分享密碼");
      return;
    }
    if (!meta.res.ok || !meta.json.ok) throw new Error(meta.json.msg || `HTTP ${meta.res.status}`);
    rememberShareSession(meta.json.share_session_id);
    const video = meta.json.video || {};
    $("title").textContent = video.title || "分享影音";
    $("meta").textContent = `${video.owner_nickname || video.owner_username || "使用者"} · ${video.visibility || "unlisted"}`;
    if (video.share_requires_fragment_key) {
      const requirements = [];
      requirements.push("此 E2EE 影音必須使用完整分享連結");
      if (video.share_password_required) requirements.push("並輸入分享密碼");
      requirements.push("若遺失連結片段金鑰，分享者只能重新產生分享。");
      setMsg(requirements.join(" · "));
    }
    if (metaEl) metaEl.textContent = `${video.owner_nickname || video.owner_username || "使用者"} · 準備讀取播放資訊`;
    const playback = await fetchJson(`/api/videos/shared/${encodeURIComponent(TOKEN)}/playback`);
    if (isSharePasswordResponse(playback.res, playback.json)) {
      showSharePasswordPrompt(playback.json.msg || "這部影音需要分享密碼");
      return;
    }
    if (!playback.res.ok || !playback.json.ok) throw new Error(playback.json.msg || `HTTP ${playback.res.status}`);
    rememberShareSession(playback.json.share_session_id);
    await renderPlayback(video, applyShareSessionToPlayback(playback.json));
  }
  async function renderPlayback(video, playback) {
    const host = $("player-host");
    host.classList.remove("hidden");
    const mediaTag = video.media_type === "audio" ? "audio" : "video";
    host.innerHTML = mediaTag === "audio"
      ? `<audio id="shared-player" controls preload="metadata"></audio>`
      : `<video id="shared-player" controls playsinline preload="metadata"></video>`;
    const player = $("shared-player");
    if (!player) return;
    destroySharedPlaybackArtifacts();
    sharedManualQualitySelection = false;
    sharedAutoQualityFallbackApplied = false;
    sharedUserSeeking = false;
    sharedLastSeekAt = 0;
    sharedLastSeekTarget = 0;
    sharedE2eeFragmentKey = "";
    bindSharedSeekProtection(player);
    const qualityHost = $("quality-host");
    if (qualityHost) {
      qualityHost.classList.add("hidden");
      qualityHost.innerHTML = "";
    }
    if (playback.mode === "e2ee_stream_v2") {
      $("e2ee-note").classList.remove("hidden");
      renderSharedQualityControl(playback);
      setMsg("這是 strict E2EE 分享影音。按下「開始 E2EE 播放」後，才會在瀏覽器端讀取 fragment 並解密。");
      showSharedPlaybackAction("開始 E2EE 播放", async () => {
        const fragmentKey = shareKeyFromFragment();
        if (!fragmentKey) {
          throw new Error("此 E2EE 分享影音缺少連結片段金鑰，無法復原。請向分享者重新取得完整連結；若分享者也遺失，只能重新產生分享。");
        }
        sharedE2eeFragmentKey = fragmentKey;
        await attachSharedE2eeStreamV2(player, playback, fragmentKey);
      }, "未按下播放前，不會主動要求密碼或開始解密。");
      return;
    }
    if (playback.mode === "e2ee_direct") {
      $("e2ee-note").classList.remove("hidden");
      setMsg("這是 strict E2EE 分享影音。按下「開始 E2EE 播放」後，才會在瀏覽器端完整解密播放。");
      showSharedPlaybackAction("開始 E2EE 播放", async () => {
        const fragmentKey = shareKeyFromFragment();
        if (!fragmentKey) {
          throw new Error("此 E2EE 分享影音缺少連結片段金鑰，無法復原。請向分享者重新取得完整連結；若分享者也遺失，只能重新產生分享。");
        }
        await fallbackSharedE2eeToFullDecrypt(player, playback, fragmentKey, "正在使用舊版完整解密播放。strict E2EE 不支援伺服器端轉檔、縮圖與內容掃描，速度會較慢。");
      }, "未按下播放前，不會主動要求密碼或開始解密。");
      return;
    }
    clearSharedPlaybackAction();
    const directFallbackAllowed = playback.direct_fallback_allowed !== false;
    renderSharedQualityControl(playback);
    const preferred = preferredSharedQuality(playback);
    const preferredUrl = preferred?.playlistUrl || playback.master_url || "";
    if (playback.mode === "hls" && browserSupportsNativeHls(video.media_type)) {
      player.src = preferredUrl || (directFallbackAllowed ? (playback.fallback_url || "") : "");
      player.addEventListener("stalled", () => fallbackSharedPlaybackToLowerQuality(playback, "原生 HLS 偵測到載入停滯"));
      player.addEventListener("waiting", () => fallbackSharedPlaybackToLowerQuality(playback, "原生 HLS 偵測到等待資料"));
      player.addEventListener("error", () => {
        if (sharedQualityFallbackDeferredForSeek(player)) {
          setMsg("正在跳轉到指定時間，暫不因播放錯誤切換來源。");
          return;
        }
        if (!fallbackSharedPlaybackToLowerQuality(playback, "原生 HLS 播放錯誤") && directFallbackAllowed) {
          player.src = playback.fallback_url || playback.stream_url || "";
          setMsg("HLS 播放失敗，已改用直接串流。", true);
        }
      }, { once: true });
      setMsg(preferred ? `Safari / 原生 HLS 已啟用，預設 ${preferred.label}。` : "Safari / 原生 HLS 已啟用。");
      return;
    }
    if (playback.mode === "hls" && playback.master_url) {
      try {
        const Hls = await loadSharedHlsLibrary(playback.hls_js_url || "/js/hls.light.min.js?v=20260505-hlsjs");
        if (!Hls || typeof Hls.isSupported !== "function" || !Hls.isSupported()) {
          throw new Error("目前瀏覽器不支援 HLS.js 所需的 MediaSource");
        }
        sharedHls = new Hls({ enableWorker: true, backBufferLength: 30 });
        sharedHls.on(Hls.Events.MANIFEST_PARSED, () => {
          if (selectedSharedQuality(playback)) applySharedQualitySelection(playback);
        });
        sharedHls.on(Hls.Events.ERROR, (_event, data) => {
          const detail = data?.details ? String(data.details) : "";
          const type = data?.type ? String(data.type) : "";
          const shouldTryAutoFallback = detail.toLowerCase().includes("buffer") || type.toLowerCase().includes("network") || data?.fatal;
          if (shouldTryAutoFallback && sharedQualityFallbackDeferredForSeek(player)) {
            setMsg("正在跳轉到指定時間，暫不因緩衝等待切換畫質。");
            if (data?.fatal && typeof sharedHls.recoverMediaError === "function") {
              try { sharedHls.recoverMediaError(); } catch (_err) {}
            }
            return;
          }
          if (shouldTryAutoFallback && fallbackSharedPlaybackToLowerQuality(playback, detail ? detail : "已降低串流負擔")) {
            if (data?.fatal && typeof sharedHls.recoverMediaError === "function") {
              try { sharedHls.recoverMediaError(); } catch (_err) {}
            }
            return;
          }
          if (!data?.fatal) return;
          destroySharedPlaybackArtifacts();
          if (directFallbackAllowed) {
            player.src = playback.fallback_url || playback.stream_url || "";
            setMsg(`HLS.js 播放失敗，已改用直接串流。${data?.details ? ` (${data.details})` : ""}`, true);
            return;
          }
          player.removeAttribute("src");
          setMsg(`HLS.js 播放失敗，且此影音不允許主程序直接解密串流。${data?.details ? ` (${data.details})` : ""}`, true);
        });
        sharedHls.loadSource(playback.master_url);
        sharedHls.attachMedia(player);
        setMsg("已使用 HLS.js 播放；桌機 Chrome / Firefox / Edge 可穩定播放 HLS。");
        return;
      } catch (err) {
        if (directFallbackAllowed) {
          player.src = playback.fallback_url || playback.stream_url || "";
          setMsg(`HLS.js 初始化失敗，已改用直接串流。${err?.message ? ` (${err.message})` : ""}`, true);
          return;
        }
        player.removeAttribute("src");
        setMsg(`HLS.js 初始化失敗，且此影音不允許主程序直接解密串流。${err?.message ? ` (${err.message})` : ""}`, true);
        return;
      }
    }
    player.src = directFallbackAllowed ? (playback.fallback_url || playback.stream_url || "") : "";
    setMsg(playback.stream_warning || (playback.high_performance_streaming ? "目前使用高效串流。" : "目前使用直接串流。"));
  }
  $("share-password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await unlockShare(($("share-password").value || "").trim());
      $("share-password-form").classList.add("hidden");
      setMsg("分享密碼驗證成功。");
      await loadSharedVideo();
    } catch (err) {
      setMsg(err.message || "分享密碼驗證失敗", true);
    }
  });
  loadSharedVideo().catch((err) => setMsg(err.message || "分享影音載入失敗", true));
})();
