'use strict';

const sharedFileState = {
  token: "",
  file: null,
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

function sharedFileFormatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
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

async function sharedFileFetchDownload(file, confirmed = false) {
  const url = new URL(file.download_url, window.location.origin);
  if (confirmed) url.searchParams.set("confirm_high_risk", "1");
  const res = await fetch(url.pathname + url.search, { credentials: "same-origin" });
  if (res.status === 409 && !confirmed) {
    const json = await res.json().catch(() => ({}));
    if (json.requires_confirmation && window.confirm(json.msg || "此檔案可能高風險，仍要下載？")) {
      return sharedFileFetchDownload(file, true);
    }
  }
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.msg || `下載失敗（HTTP ${res.status}）`);
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
    sharedFileSetMsg(err.message || "下載失敗", true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function sharedFileLoad() {
  sharedFileState.token = sharedFileToken();
  const title = document.getElementById("shared-file-title");
  const meta = document.getElementById("shared-file-meta");
  const btn = document.getElementById("shared-file-download-btn");
  if (!sharedFileState.token) {
    sharedFileSetMsg("分享連結不完整。", true);
    return;
  }
  try {
    const res = await fetch(`/api/storage/shared/${encodeURIComponent(sharedFileState.token)}`, { credentials: "same-origin" });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || "分享連結不存在或已失效");
    const file = json.file || {};
    sharedFileState.file = file;
    if (title) title.textContent = file.display_name || "檔案下載";
    const e2eeText = file.e2ee?.requires_fragment_key ? " · E2EE 瀏覽器端解密" : "";
    const scopeText = file.access_scope === "account" ? ` · 限 ${file.required_username || "指定帳戶"}` : " · 知道連結即可下載";
    if (meta) meta.textContent = `${sharedFileFormatBytes(file.size_bytes)}${scopeText}${e2eeText}`;
    if (btn) {
      btn.disabled = false;
      btn.addEventListener("click", sharedFileDownload);
    }
    sharedFileSetMsg(file.e2ee?.requires_fragment_key ? "請使用包含 #key= 的完整分享連結下載。" : "");
  } catch (err) {
    if (title) title.textContent = "檔案無法下載";
    if (meta) meta.textContent = "";
    sharedFileSetMsg(err.message || "分享連結不存在或已失效", true);
  }
}

document.addEventListener("DOMContentLoaded", sharedFileLoad);
