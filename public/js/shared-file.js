'use strict';

const sharedFileState = {
  token: "",
  file: null,
  previewObjectUrl: "",
  password: "",
};

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
  if (type.startsWith("video/") || [".m4v", ".mov", ".mp4", ".ogv", ".webm"].includes(ext)) return "video";
  if (type.startsWith("audio/") || [".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"].includes(ext)) return "audio";
  if (type === "application/pdf" || ext === ".pdf") return "pdf";
  if (type.startsWith("text/") || [".css", ".csv", ".htm", ".html", ".ini", ".js", ".json", ".log", ".md", ".py", ".sh", ".sql", ".text", ".toml", ".txt", ".xml", ".yaml", ".yml"].includes(ext) || !ext) return "text";
  return "metadata";
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
  return res.blob();
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
      const blob = await fetch(sharedFileContentUrl(file), sharedFileRequestOptions()).then(async (res) => {
        if (!res.ok) {
          const json = await res.json().catch(() => ({}));
          throw sharedFileErrorFromResponse(res, json, `預覽失敗（HTTP ${res.status}）`);
        }
        return res.blob();
      });
      const decrypted = await sharedFileDecryptBlob(blob, file);
      await sharedFileRenderBlobPreview(decrypted.blob, decrypted.filename);
      sharedFileSetMsg("預覽已在瀏覽器端解密。");
      return;
    }
    const res = await fetch(sharedFilePreviewMetadataUrl(file), sharedFileRequestOptions());
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw sharedFileErrorFromResponse(res, json, `預覽失敗（HTTP ${res.status}）`);
    sharedFileRenderPreviewMetadata(json.preview || {}, file);
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
    if (meta) meta.textContent = `${sharedFileFormatBytes(file.size_bytes)}${scopeText}${previewText}${passwordText}${e2eeText}`;
    if (downloadBtn) {
      downloadBtn.disabled = false;
      downloadBtn.onclick = sharedFileDownload;
    }
    if (previewBtn) {
      previewBtn.disabled = !file.can_preview;
      previewBtn.onclick = sharedFilePreview;
    }
    sharedFileSetMsg(file.e2ee?.requires_fragment_key ? "請使用包含 #key= 的完整分享連結預覽或下載。" : "");
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
