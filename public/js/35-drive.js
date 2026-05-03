function formatDriveBytes(bytes) {
  if (bytes === null || bytes === undefined) return "無上限";
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const DRIVE_PRIVACY_MODE_LABELS = {
  standard_plain: "一般檔案",
  server_encrypted: "伺服器端加密",
  e2ee: "端到端加密",
};

const DRIVE_PRIVACY_MODE_DESCRIPTIONS = {
  standard_plain: "伺服器可讀明文並掃毒，預覽與分享支援最完整",
  server_encrypted: "磁碟上是密文，伺服器可暫時解密掃毒、預覽與下載明文",
  e2ee: "瀏覽器端加密，站方無法讀取，預覽與掃毒受限",
};

const DRIVE_PRIVACY_MODE_COMPARISON = [
  {
    mode: "standard_plain",
    bestFor: "一般檔案、附件、相簿、分享",
    serverAccess: "可讀明文",
    scan: "伺服器掃毒",
    preview: "最完整",
    keyRisk: "無本機金鑰風險",
  },
  {
    mode: "server_encrypted",
    bestFor: "降低磁碟或備份外洩風險",
    serverAccess: "可暫時解密",
    scan: "解密後伺服器掃毒",
    preview: "通過政策後可預覽",
    keyRisk: "伺服器金鑰遺失會影響復原",
  },
  {
    mode: "e2ee",
    bestFor: "高度私密保存",
    serverAccess: "不可讀明文",
    scan: "只能檢查密文/metadata；可附本機回報",
    preview: "不提供伺服器預覽",
    keyRisk: "清除瀏覽器金鑰後可能無法解密",
  },
];

const DRIVE_E2EE_PASSPHRASE_WRAPPER = "browser_passphrase_pbkdf2_v2";
const DRIVE_E2EE_PBKDF2_ITERATIONS = 310000;
const driveE2eeSessionPassphrases = new Map();
const ATTACHMENT_FILE_SELECT_IDS = [
  "chat-attachment-existing-file-id",
  "dm-attachment-existing-file-id",
  "announcement-attachment-existing-file-id",
];

let driveTransferRows = [];
let driveAttachmentFileOptions = [];
let driveAttachmentFileOptionsLoadedAt = 0;
let driveStorageUpgradeCatalog = [];
let driveStorageUpgradeCanPurchase = false;
let driveStorageUpgradeMessage = "";
let driveRemoteDownloadCapabilities = { direct: true, bt_magnet: false, bt_file: false };
const driveRemotePollingTaskIds = new Set();
const DRIVE_TRANSFER_COMPLETED_VISIBLE_MS = 6000;
const DRIVE_TRANSFER_FAILED_VISIBLE_MS = 15000;
const DRIVE_REMOTE_STATUS_RETRY_LIMIT = 12;

function drivePrivacyModeLabel(mode) {
  return DRIVE_PRIVACY_MODE_LABELS[mode] || mode || "-";
}

function drivePrivacyModeDescription(mode) {
  return DRIVE_PRIVACY_MODE_DESCRIPTIONS[mode] || "";
}

function renderDrivePrivacyModeComparison() {
  const target = $("drive-privacy-mode-comparison");
  if (!target) return;
  target.innerHTML = `
    <div class="drive-mode-table-wrap">
      <table class="drive-mode-table">
        <thead>
          <tr>
            <th>模式</th>
            <th>適合用途</th>
            <th>站方能否讀取</th>
            <th>安全檢查</th>
            <th>預覽/下載</th>
            <th>注意事項</th>
          </tr>
        </thead>
        <tbody>
          ${DRIVE_PRIVACY_MODE_COMPARISON.map((item) => `
            <tr>
              <td><strong>${sanitize(drivePrivacyModeLabel(item.mode))}</strong><span>${sanitize(item.mode)}</span></td>
              <td>${sanitize(item.bestFor)}</td>
              <td>${sanitize(item.serverAccess)}</td>
              <td>${sanitize(item.scan)}</td>
              <td>${sanitize(item.preview)}</td>
              <td>${sanitize(item.keyRisk)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
    <div class="drive-card-sub">結論：要預覽、掃毒、分享就用「一般檔案」；要防磁碟/備份外洩但保留伺服器功能用「伺服器端加密」；真正不想讓站方讀內容才用 E2EE。</div>
  `;
}

function attachmentFileDisplayName(file) {
  return file?.original_filename_plain_for_public || file?.display_name || file?.filename || file?.id || file?.file_id || "雲端檔案";
}

function attachmentFileOptionLabel(file) {
  const id = file?.id || file?.file_id || "";
  const name = attachmentFileDisplayName(file);
  const size = typeof formatDriveBytes === "function" ? formatDriveBytes(file?.size_bytes || 0) : `${Number(file?.size_bytes || 0)} bytes`;
  const scan = file?.scan_status || "-";
  const risk = file?.risk_level || "-";
  return `${name} · ${size} · scan=${scan} · risk=${risk} · #${id}`;
}

function renderAttachmentFileSelects(files = driveAttachmentFileOptions) {
  const rows = Array.isArray(files) ? files : [];
  ATTACHMENT_FILE_SELECT_IDS.forEach((id) => {
    const select = $(id);
    if (!select) return;
    const previous = select.value || "";
    if (!rows.length) {
      select.innerHTML = `<option value="">目前沒有可選擇的雲端檔案</option>`;
      return;
    }
    select.innerHTML = `<option value="">請選擇雲端檔案</option>` + rows.map((file) => {
      const fileId = file.id || file.file_id || "";
      return `<option value="${sanitize(fileId)}">${sanitize(attachmentFileOptionLabel(file))}</option>`;
    }).join("");
    if (previous && rows.some((file) => String(file.id || file.file_id || "") === previous)) {
      select.value = previous;
    }
  });
}

async function ensureAttachmentFileOptionsLoaded({ force = false } = {}) {
  if (!currentUser || !canAccessModule("privacy_uploads")) return [];
  const fresh = driveAttachmentFileOptionsLoadedAt && Date.now() - driveAttachmentFileOptionsLoadedAt < 30000;
  if (!force && fresh) {
    renderAttachmentFileSelects();
    return driveAttachmentFileOptions;
  }
  ATTACHMENT_FILE_SELECT_IDS.forEach((id) => {
    const select = $(id);
    if (select && !select.value) select.innerHTML = `<option value="">讀取雲端檔案中...</option>`;
  });
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + "/cloud-drive/files", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    ATTACHMENT_FILE_SELECT_IDS.forEach((id) => {
      const select = $(id);
      if (select) select.innerHTML = `<option value="">雲端檔案讀取失敗</option>`;
    });
    return [];
  }
  driveAttachmentFileOptions = Array.isArray(json.files) ? json.files : [];
  driveAttachmentFileOptionsLoadedAt = Date.now();
  renderAttachmentFileSelects();
  return driveAttachmentFileOptions;
}

function isDriveE2eeMode(mode) {
  return String(mode || "") === "e2ee";
}

function driveBytesToBase64(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  let binary = "";
  for (let i = 0; i < view.length; i += 1) binary += String.fromCharCode(view[i]);
  return btoa(binary);
}

function driveBase64ToBytes(value) {
  const binary = atob(String(value || ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function driveBufferToHex(buffer) {
  return Array.from(new Uint8Array(buffer || [])).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function driveRandomNonce(length = 12) {
  const nonce = new Uint8Array(length);
  window.crypto.getRandomValues(nonce);
  return nonce;
}

function driveE2eeModeSelected() {
  return isDriveE2eeMode($("drive-upload-privacy-mode")?.value || "");
}

function askDriveUploadPrivacyOptions({ allowE2ee = true, title = "選擇隱私模式" } = {}) {
  return new Promise((resolve) => {
    const overlay = $("drive-upload-mode-overlay");
    const titleEl = $("drive-upload-mode-title");
    const e2eeChoice = $("drive-upload-mode-e2ee-choice");
    const e2eeFields = $("drive-upload-mode-e2ee-fields");
    const passphraseInput = $("drive-upload-mode-passphrase");
    const passphraseConfirm = $("drive-upload-mode-passphrase-confirm");
    const scanReport = $("drive-upload-mode-client-scan-report");
    const msg = $("drive-upload-mode-msg");
    const confirmBtn = $("drive-upload-mode-confirm-btn");
    const cancelBtn = $("drive-upload-mode-cancel-btn");
    if (!overlay || !confirmBtn || !cancelBtn) {
      resolve({ privacyMode: "standard_plain", passphrase: "", includeClientScanReport: false });
      return;
    }
    const radios = Array.from(document.querySelectorAll("input[name='drive-upload-mode-choice']"));
    const setMsg = (text = "", ok = false) => {
      if (!msg) return;
      msg.textContent = text;
      msg.className = text ? `msg ${ok ? "ok" : "err"}` : "msg";
    };
    const selectedMode = () => radios.find((radio) => radio.checked)?.value || "standard_plain";
    const sync = () => {
      const isE2ee = selectedMode() === "e2ee";
      if (e2eeFields) e2eeFields.style.display = isE2ee ? "" : "none";
    };
    const cleanup = (value) => {
      confirmBtn.removeEventListener("click", onConfirm);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlayClick);
      radios.forEach((radio) => radio.removeEventListener("change", sync));
      overlay.classList.remove("show");
      overlay.setAttribute("aria-hidden", "true");
      document.body.classList.remove("modal-open");
      resolve(value);
    };
    const onCancel = () => cleanup(null);
    const onOverlayClick = (event) => {
      if (event.target === overlay) cleanup(null);
    };
    const onConfirm = () => {
      const privacyMode = selectedMode();
      const options = { privacyMode, passphrase: "", includeClientScanReport: false };
      if (privacyMode === "e2ee") {
        const passphrase = passphraseInput?.value || "";
        const confirm = passphraseConfirm?.value || "";
        if (!passphrase || passphrase.length < 10) {
          setMsg("E2EE 檔案加密密碼至少 10 個字元");
          return;
        }
        if (passphrase !== confirm) {
          setMsg("兩次輸入的 E2EE 檔案加密密碼不一致");
          return;
        }
        options.passphrase = passphrase;
        options.includeClientScanReport = !!scanReport?.checked;
      }
      cleanup(options);
    };
    if (titleEl) titleEl.textContent = title;
    if (e2eeChoice) e2eeChoice.style.display = allowE2ee ? "" : "none";
    radios.forEach((radio) => {
      radio.checked = radio.value === "standard_plain";
      radio.disabled = radio.value === "e2ee" && !allowE2ee;
      radio.addEventListener("change", sync);
    });
    if (passphraseInput) passphraseInput.value = "";
    if (passphraseConfirm) passphraseConfirm.value = "";
    if (scanReport) scanReport.checked = false;
    setMsg("");
    sync();
    confirmBtn.addEventListener("click", onConfirm);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlayClick);
    overlay.classList.add("show");
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  });
}

function updateDriveE2eePassphraseVisibility() {
  const field = $("drive-e2ee-passphrase-field");
  const clientScan = $("drive-upload-client-scan-report");
  const isE2ee = driveE2eeModeSelected();
  if (field) field.style.display = isE2ee ? "" : "none";
  if (clientScan) clientScan.closest?.("label")?.classList.toggle("muted", !isE2ee);
}

function getDriveE2eeUploadPassphrase() {
  const passphrase = $("drive-e2ee-passphrase")?.value || "";
  const confirm = $("drive-e2ee-passphrase-confirm")?.value || "";
  if (!passphrase) throw new Error("請輸入 E2EE 檔案加密密碼");
  if (passphrase.length < 10) throw new Error("E2EE 檔案加密密碼至少 10 個字元");
  if (passphrase !== confirm) throw new Error("兩次輸入的 E2EE 檔案加密密碼不一致");
  return passphrase;
}

function clearDriveE2eeUploadPassphrase() {
  if ($("drive-e2ee-passphrase")) $("drive-e2ee-passphrase").value = "";
  if ($("drive-e2ee-passphrase-confirm")) $("drive-e2ee-passphrase-confirm").value = "";
}

function driveE2eeSessionKey(fileId) {
  return `${currentUserId || "anon"}:${String(fileId || "")}`;
}

function driveE2eeKnownFileIds(fileId) {
  const ids = new Set();
  const addId = (value) => {
    const normalized = String(value || "").trim();
    if (normalized) ids.add(normalized);
  };
  addId(fileId);
  const known = findKnownDriveFile(fileId);
  if (known) {
    addId(known.id);
    addId(known.file_id);
    addId(known.storage_file_id);
  }
  return Array.from(ids);
}

function clearDriveE2eeSessionPassphrases() {
  driveE2eeSessionPassphrases.clear();
}

function forgetDriveE2eeSessionPassphrase(fileId) {
  driveE2eeKnownFileIds(fileId).forEach((id) => {
    driveE2eeSessionPassphrases.delete(driveE2eeSessionKey(id));
  });
}

function getRememberedDriveE2eeSessionPassphrase(fileId) {
  for (const id of driveE2eeKnownFileIds(fileId)) {
    const key = driveE2eeSessionKey(id);
    if (driveE2eeSessionPassphrases.has(key)) {
      return driveE2eeSessionPassphrases.get(key);
    }
  }
  return "";
}

function rememberDriveE2eeSessionPassphrase(fileId, passphrase) {
  if (!passphrase) return;
  driveE2eeKnownFileIds(fileId).forEach((id) => {
    driveE2eeSessionPassphrases.set(driveE2eeSessionKey(id), passphrase);
  });
}

async function getDriveE2eeSessionPassphrase(fileId, promptText, { force = false } = {}) {
  if (!force) {
    const remembered = getRememberedDriveE2eeSessionPassphrase(fileId);
    if (remembered) return remembered;
  }
  const passphrase = await askDriveE2eePassphrase(promptText);
  return passphrase || "";
}

async function deriveDriveE2eePassphraseKey(passphrase, salt, iterations = DRIVE_E2EE_PBKDF2_ITERATIONS) {
  if (!window.crypto?.subtle) {
    throw new Error("此瀏覽器不支援端到端加密上傳，請改用私密檔案或換用支援 WebCrypto 的瀏覽器。");
  }
  const material = await window.crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase || ""),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return window.crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt: salt instanceof Uint8Array ? salt : driveBase64ToBytes(salt),
      iterations: Math.max(100000, Number(iterations || DRIVE_E2EE_PBKDF2_ITERATIONS)),
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

async function encryptDriveJsonMetadata(fileKey, payload) {
  const nonce = driveRandomNonce();
  const encoded = new TextEncoder().encode(JSON.stringify(payload || {}));
  const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, fileKey, encoded);
  return JSON.stringify({
    alg: "AES-GCM",
    v: 1,
    nonce: driveBytesToBase64(nonce),
    ciphertext: driveBytesToBase64(ciphertext),
  });
}

async function wrapDriveFileKey(fileKey, passphrase) {
  const rawKey = await window.crypto.subtle.exportKey("raw", fileKey);
  const salt = driveRandomNonce(16);
  const nonce = driveRandomNonce();
  const wrappingKey = await deriveDriveE2eePassphraseKey(passphrase, salt);
  const wrapped = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, wrappingKey, rawKey);
  return JSON.stringify({
    alg: "AES-GCM",
    v: 2,
    wrapped_by: DRIVE_E2EE_PASSPHRASE_WRAPPER,
    kdf: "PBKDF2-SHA256",
    iterations: DRIVE_E2EE_PBKDF2_ITERATIONS,
    salt: driveBytesToBase64(salt),
    nonce: driveBytesToBase64(nonce),
    ciphertext: driveBytesToBase64(wrapped),
  });
}

async function unwrapDriveFileKey(encryptedFileKey, passphrase) {
  const envelope = JSON.parse(encryptedFileKey || "{}");
  if (envelope.wrapped_by !== DRIVE_E2EE_PASSPHRASE_WRAPPER || !envelope.salt) {
    throw new Error("此檔案使用舊版本機 vault key 包裝，無法用密碼解密；請重新上傳為新版 E2EE。");
  }
  const wrappingKey = await deriveDriveE2eePassphraseKey(passphrase, envelope.salt, envelope.iterations);
  const rawKey = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: driveBase64ToBytes(envelope.nonce) },
    wrappingKey,
    driveBase64ToBytes(envelope.ciphertext)
  );
  return window.crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, true, ["encrypt", "decrypt"]);
}

async function decryptDriveJsonMetadata(fileKey, encryptedMetadata) {
  if (!encryptedMetadata) return {};
  const envelope = JSON.parse(encryptedMetadata || "{}");
  const plaintext = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: driveBase64ToBytes(envelope.nonce) },
    fileKey,
    driveBase64ToBytes(envelope.ciphertext)
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

async function decryptDriveE2eeBlob(blob, e2ee, passphrase) {
  const fileKey = await unwrapDriveFileKey(e2ee.encrypted_file_key, passphrase);
  const plaintext = await window.crypto.subtle.decrypt(
    { name: "AES-GCM", iv: driveBase64ToBytes(e2ee.nonce) },
    fileKey,
    await blob.arrayBuffer()
  );
  const metadata = await decryptDriveJsonMetadata(fileKey, e2ee.encrypted_metadata);
  return {
    blob: new Blob([plaintext], { type: metadata.mime_type || "application/octet-stream" }),
    filename: metadata.filename || "download",
  };
}

async function prepareDriveE2eeUpload(file, passphrase, includeClientScanReport = false) {
  if (!window.crypto?.subtle) {
    throw new Error("此瀏覽器不支援端到端加密上傳，請改用私密檔案或換用支援 WebCrypto 的瀏覽器。");
  }
  const originalName = file.name || "未命名檔案";
  const plaintext = await file.arrayBuffer();
  const fileKey = await window.crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
  const nonce = driveRandomNonce();
  const ciphertext = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, fileKey, plaintext);
  const encryptedBlob = new Blob([ciphertext], { type: "application/octet-stream" });
  const encryptedMetadata = await encryptDriveJsonMetadata(fileKey, {
    filename: originalName,
    mime_type: file.type || "application/octet-stream",
    size_bytes: file.size,
    encrypted_at: new Date().toISOString(),
  });
  const encryptedFileKey = await wrapDriveFileKey(fileKey, passphrase);
  const ciphertextHash = await window.crypto.subtle.digest("SHA-256", ciphertext);
  return {
    blob: encryptedBlob,
    filename: originalName,
    encrypted_metadata: encryptedMetadata,
    encrypted_file_key: encryptedFileKey,
    wrapped_by: DRIVE_E2EE_PASSPHRASE_WRAPPER,
    ciphertext_sha256: driveBufferToHex(ciphertextHash),
    encryption_algorithm: "AES-GCM",
    encryption_version: "browser-passphrase-v2",
    nonce: driveBytesToBase64(nonce),
    client_scan_report: includeClientScanReport ? {
      ok: false,
      mode: "browser_e2ee_upload",
      note: "檔案已在瀏覽器端加密；伺服器無法驗證本機掃描結果。",
    } : null,
  };
}

const ALBUM_VISIBILITY_LABELS = {
  private: "私人",
  unlisted: "不列出，持連結可看",
  public: "公開",
};

function albumVisibilityLabel(value) {
  return ALBUM_VISIBILITY_LABELS[value] || value || "私人";
}

function renderDriveGroupedStats(targetId, grouped, emptyText, labelFn) {
  const el = $(targetId);
  if (!el) return;
  const entries = Object.entries(grouped || {});
  if (!entries.length) {
    el.innerHTML = `<div class="drive-empty">${sanitize(emptyText || "尚無資料")}</div>`;
    return;
  }
  el.innerHTML = entries.map(([name, item]) => `
    <div class="drive-pill">
      <strong>${sanitize(labelFn ? labelFn(name) : name)}</strong>
      <span>${Number(item.count || 0)} 個 · ${formatDriveBytes(item.bytes || 0)}</span>
    </div>
  `).join("");
}

function storageUpgradeLabel(item) {
  const bytes = formatDriveBytes(item.storage_bytes || 0);
  const days = Number(item.duration_days || 0);
  return `${item.label || item.item_name || item.item_key} · ${bytes} / ${days} 天`;
}

function storageUpgradePricePreviewHtml(item) {
  if (!item) return "";
  const effective = Number(item.effective_price ?? item.base_price ?? 0);
  const base = Number(item.base_price || 0);
  const tierMultiplier = Number(item.tier_multiplier || 1);
  if (tierMultiplier > 1) {
    return `<span style="color:var(--warning,#e6a817)">本次定價：<strong>${effective} 積分</strong>（基礎 ${base} × ${tierMultiplier.toFixed(1)} 階梯加價）</span>`;
  }
  return `本次定價：<strong>${effective} 積分</strong>`;
}

function renderStorageUpgrade(payload) {
  const card = $("drive-storage-upgrade-card");
  const select = $("drive-storage-upgrade-select");
  const summary = $("drive-storage-upgrade-summary");
  const list = $("drive-storage-upgrade-active-list");
  const button = document.querySelector("[data-drive-action='purchase-storage-upgrade']");
  if (!card || !select || !summary || !list) return;

  const canPurchase = Boolean(payload?.can_purchase);
  const isRoot = currentUser === "root";
  driveStorageUpgradeCanPurchase = canPurchase && !isRoot;
  driveStorageUpgradeMessage = payload?.message || (isRoot ? "root 依實際磁碟容量控管，不需要購買容量方案" : "");
  driveStorageUpgradeCatalog = driveStorageUpgradeCanPurchase && Array.isArray(payload?.catalog) ? payload.catalog : [];
  select.innerHTML = driveStorageUpgradeCatalog.length
    ? driveStorageUpgradeCatalog.map((item) => `<option value="${sanitize(item.item_key)}">${sanitize(storageUpgradeLabel(item))}</option>`).join("")
    : `<option value="">${isRoot ? "root 不需要購買容量方案" : "目前沒有可用的容量方案"}</option>`;
  select.disabled = !canPurchase || !driveStorageUpgradeCatalog.length;
  if (button) {
    button.disabled = !driveStorageUpgradeCanPurchase || !driveStorageUpgradeCatalog.length;
    button.textContent = driveStorageUpgradeCanPurchase ? "用積分購買容量" : (isRoot ? "root 不需要購買容量" : "容量方案不可購買");
    button.title = driveStorageUpgradeCanPurchase ? "用積分購買所選雲端硬碟容量" : (driveStorageUpgradeMessage || "目前沒有可購買的容量方案");
  }
  const pricePreview = $("drive-storage-upgrade-price-preview");
  const updatePricePreview = () => {
    if (!pricePreview) return;
    const key = select.value;
    const item = driveStorageUpgradeCatalog.find((i) => i.item_key === key);
    pricePreview.innerHTML = item ? storageUpgradePricePreviewHtml(item) : "";
  };
  select.removeEventListener("change", select._upgradePriceHandler);
  select._upgradePriceHandler = updatePricePreview;
  select.addEventListener("change", updatePricePreview);
  updatePricePreview();

  const usage = payload?.usage || {};
  const purchased = Number(usage.purchased_extra_bytes || 0);
  summary.textContent = canPurchase
    ? `已加購容量：${formatDriveBytes(purchased)}`
    : (payload?.message || "此帳號不需要加購容量");

  const active = Array.isArray(payload?.active_purchases) ? payload.active_purchases : [];
  list.innerHTML = active.length
    ? active.map((row) => `
      <div class="drive-pill">
        <strong>${sanitize(row.item_key)}</strong>
        <span>${formatDriveBytes(row.purchased_bytes || 0)} · 到期 ${sanitize(row.expires_at || "-")}</span>
      </div>
    `).join("")
    : `<div class="drive-empty">目前沒有有效的加購容量</div>`;
}

function renderDriveDashboard(payload) {
  const security = payload && payload.security ? payload.security : {};
  const quota = security.usage || (payload && payload.quota) || {};
  const used = Number(quota.used_bytes || 0);
  const total = quota.total_bytes;
  const remaining = quota.remaining_bytes;
  const percent = total === null || total === undefined ? 0 : Math.max(0, Math.min(100, Number(quota.percent_used || 0)));

  const usedLabel = $("drive-used-label");
  const totalLabel = $("drive-total-label");
  const remainingLabel = $("drive-remaining-label");
  const limitLabel = $("drive-limit-label");
  const barFill = $("drive-quota-bar-fill");

  if (usedLabel) usedLabel.textContent = formatDriveBytes(used);
  if (totalLabel) totalLabel.textContent = total === null || total === undefined ? " / 無上限" : ` / ${formatDriveBytes(total)}`;
  if (remainingLabel) remainingLabel.textContent = `剩餘容量：${formatDriveBytes(remaining)}`;
  if (limitLabel) {
    const maxFile = formatDriveBytes(quota.max_file_size_bytes);
    const daily = quota.upload_rate_limit_per_day === null || quota.upload_rate_limit_per_day === undefined ? "無上限" : `${quota.upload_rate_limit_per_day} 次`;
    const diskNote = quota.quota_source === "root_disk_available_90_percent"
      ? ` · root 上限：儲存磁碟可用空間 90%，${quota.warning_threshold_percent || 80}% 起警示`
      : String(quota.quota_source || "").startsWith("manager_role_fixed_1gb")
        ? " · manager 上限：1 GB"
      : "";
    const purchaseNote = Number(quota.purchased_extra_bytes || 0) > 0 ? ` · 加購：${formatDriveBytes(quota.purchased_extra_bytes)}` : "";
    limitLabel.textContent = `單檔限制：${maxFile} · 每日上傳：${daily} · 檔案數：${Number(quota.file_count || 0)}${diskNote}${purchaseNote}`;
    limitLabel.style.color = quota.warning_active ? "#ffb74d" : "var(--muted)";
  }
  if (barFill) {
    barFill.style.width = `${percent}%`;
    barFill.dataset.warning = quota.warning_active || percent >= 80 ? "high" : percent >= 65 ? "medium" : "low";
  }

  const list = $("drive-security-list");
  if (list) {
    const restrictions = Array.isArray(security.restrictions) ? security.restrictions : [];
    list.innerHTML = restrictions.length
      ? restrictions.map((item) => `<li>${sanitize(item)}</li>`).join("")
      : "<li>目前沒有額外限制</li>";
  }

  renderDriveGroupedStats("drive-risk-summary", quota.by_risk_level, "尚無風險統計");
  renderDriveGroupedStats("drive-scan-summary", quota.by_scan_status, "尚無掃描狀態");
  renderDriveGroupedStats("drive-mode-summary", quota.by_privacy_mode, "尚無隱私模式統計", drivePrivacyModeLabel);
  renderDrivePrivacyModeComparison();
}

function driveFileNeedsWarning(file) {
  const risk = file && file.risk_level;
  const status = file && file.scan_status;
  return ["high", "blocked", "unknown_encrypted"].includes(risk) || ["infected", "quarantined", "failed", "unknown_encrypted"].includes(status);
}

function driveFileExtension(name) {
  const lower = String(name || "").toLowerCase();
  for (const ext of [".tar.gz", ".tar.bz2", ".tar.xz"]) {
    if (lower.endsWith(ext)) return ext;
  }
  const dot = lower.lastIndexOf(".");
  return dot >= 0 ? lower.slice(dot) : "";
}

function driveFileIsE2ee(file) {
  return String(file?.privacy_mode || "") === "e2ee";
}

function driveFileCategory(file) {
  const name = file?.display_name || file?.virtual_path || file?.original_filename_plain_for_public || file?.storage_path || "";
  const mime = String(file?.mime_type_plain_for_public || file?.mime_type || "").toLowerCase();
  const ext = driveFileExtension(name);
  if (mime.startsWith("audio/") || [".aac", ".aif", ".aiff", ".amr", ".flac", ".m4a", ".mid", ".midi", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"].includes(ext)) return "audio";
  if (mime.startsWith("video/") || [".m4v", ".mov", ".mp4", ".ogv", ".webm"].includes(ext)) return "video";
  if (mime.startsWith("image/") || [".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"].includes(ext)) return "image";
  if (mime === "application/pdf" || ext === ".pdf") return "pdf";
  if (mime.startsWith("text/") || [".c", ".cc", ".cpp", ".cs", ".css", ".csv", ".go", ".htm", ".html", ".ini", ".java", ".js", ".json", ".jsx", ".log", ".md", ".php", ".py", ".rs", ".sh", ".sql", ".text", ".toml", ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml"].includes(ext) || !ext) return "text";
  if ([".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"].includes(ext)) return "archive";
  return "metadata";
}

function driveFileIsImage(file) {
  return driveFileCategory(file) === "image";
}

function driveTextLanguage(filename = "") {
  const ext = driveFileExtension(filename);
  const map = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".htm": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".php": "php",
    ".py": "python",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
  };
  return map[ext] || "text";
}

function driveHighlightCode(text = "", filename = "") {
  const language = driveTextLanguage(filename);
  let html = sanitize(text || "");
  if (language === "markdown") return html;
  if (["javascript", "typescript", "python", "cpp", "c", "csharp", "java", "go", "rust", "php", "shell"].includes(language)) {
    html = html.replace(/(&quot;.*?&quot;|&#39;.*?&#39;|".*?"|'.*?')/g, '<span class="drive-code-string">$1</span>');
    html = html.replace(/\b(function|return|const|let|var|if|else|for|while|class|def|import|from|try|except|catch|public|private|protected|static|void|int|float|double|char|bool|string|auto|struct|namespace|using|new|delete|async|await|yield|match|enum|impl|fn|mut|package|func|go|defer|echo|then|fi)\b/g, '<span class="drive-code-keyword">$1</span>');
    html = html.replace(/\b(true|false|null|None|nil|nullptr|self|this)\b/g, '<span class="drive-code-literal">$1</span>');
    html = html.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="drive-code-number">$1</span>');
  } else if (["json", "yaml", "toml"].includes(language)) {
    html = html.replace(/(&quot;[^&]*?&quot;)(\s*:)/g, '<span class="drive-code-key">$1</span>$2');
    html = html.replace(/\b(true|false|null)\b/g, '<span class="drive-code-literal">$1</span>');
    html = html.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="drive-code-number">$1</span>');
  } else if (["html", "xml"].includes(language)) {
    html = html.replace(/(&lt;\/?[\w:-]+|\/?&gt;)/g, '<span class="drive-code-keyword">$1</span>');
    html = html.replace(/\b([\w:-]+)=/g, '<span class="drive-code-key">$1</span>=');
  } else if (language === "css") {
    html = html.replace(/([.#]?[a-zA-Z_][\w-]*)(\s*\{)/g, '<span class="drive-code-key">$1</span>$2');
    html = html.replace(/\b([a-z-]+)(\s*:)/g, '<span class="drive-code-keyword">$1</span>$2');
  }
  return html;
}

function driveRenderTextPreview(preview) {
  const filename = preview?.filename || "";
  const text = preview?.text || "";
  const language = driveTextLanguage(filename);
  if (language === "markdown" && typeof markdownToSafeHtml === "function") {
    return `
      <div class="drive-markdown-preview">${markdownToSafeHtml(text)}</div>
      <details class="drive-source-details">
        <summary>查看 Markdown 原始碼</summary>
        <pre class="drive-preview-text"><code>${sanitize(text)}</code></pre>
      </details>
    `;
  }
  const languageLabel = language === "text" ? "純文字" : language;
  return `
    <div class="drive-card-sub">語言：${sanitize(languageLabel)}</div>
    <pre class="drive-preview-text drive-code-preview language-${sanitize(language)}"><code>${driveHighlightCode(text, filename)}</code></pre>
  `;
}

function drivePrimaryAction(file) {
  if (driveFileIsE2ee(file)) return { action: "preview", label: "解密預覽" };
  const category = driveFileCategory(file);
  if (category === "text") return { action: "edit-text", label: "編輯" };
  if (category === "audio" || category === "video") return { action: "preview", label: "串流" };
  if (category === "metadata") return { action: "preview", label: "資訊" };
  return { action: "preview", label: "預覽" };
}

function driveTransferPercent(item) {
  const raw = Number(item?.progress_percent);
  if (Number.isFinite(raw)) return Math.max(0, Math.min(100, raw));
  const loaded = Number(item?.loaded_bytes || 0);
  const total = Number(item?.total_bytes || 0);
  if (total > 0) return Math.max(0, Math.min(100, (loaded / total) * 100));
  return null;
}

function addDriveTransferRow(item) {
  const id = item.id || `transfer-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const row = {
    id,
    kind: item.kind || "upload",
    status: item.status || "running",
    phase: item.phase || "starting",
    name: item.name || item.filename || "處理中的檔案",
    loaded_bytes: item.loaded_bytes || 0,
    total_bytes: item.total_bytes ?? null,
    progress_percent: item.progress_percent ?? 0,
    msg: item.msg || "準備中",
  };
  driveTransferRows = [row, ...driveTransferRows.filter((existing) => existing.id !== id)];
  renderDriveFiles(lastDriveFiles || []);
  renderStorageBrowser();
  return id;
}

function findDriveTransferRowIdForTask(taskId) {
  if (!taskId) return "";
  const row = driveTransferRows.find((item) => item.task_id === taskId);
  return row?.id || "";
}

function updateDriveTransferRow(id, updates) {
  let found = false;
  driveTransferRows = driveTransferRows.map((item) => {
    if (item.id !== id) return item;
    found = true;
    return { ...item, ...updates };
  });
  if (!found) {
    addDriveTransferRow({ id, ...updates });
    return;
  }
  renderDriveFiles(lastDriveFiles || []);
  renderStorageBrowser();
}

function removeDriveTransferRow(id) {
  driveTransferRows = driveTransferRows.filter((item) => item.id !== id);
  renderDriveFiles(lastDriveFiles || []);
  renderStorageBrowser();
}

async function dismissRemoteDownloadTask(taskId, transferId) {
  if (taskId) {
    await fetchCsrfToken({ force: true });
    await apiFetch(API + `/cloud-drive/remote-download/tasks/${encodeURIComponent(taskId)}`, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" },
    }).catch(() => {});
  }
  removeDriveTransferRow(transferId);
}

function renderDriveTransferRow(item) {
  const percent = driveTransferPercent(item);
  const width = percent === null ? 100 : percent;
  const label = percent === null ? "計算中" : `${Math.round(percent)}%`;
  const bytes = item.total_bytes
    ? `${formatDriveBytes(item.loaded_bytes || 0)} / ${formatDriveBytes(item.total_bytes)}`
    : (
      item.loaded_bytes
        ? formatDriveBytes(item.loaded_bytes)
        : (item.status === "completed" ? "已保存" : "等待資料")
    );
  const statusClass = item.status === "failed" ? "failed" : item.status === "completed" ? "completed" : "running";
  const statusText = item.status === "failed"
    ? "下載失敗"
    : item.status === "completed"
      ? "下載完成"
      : (item.kind === "remote_download" ? "下載中" : "上傳中");
  return `
    <div class="drive-file-row drive-transfer-row ${sanitize(statusClass)}">
      <div>
        <strong>${sanitize(item.name || item.filename || "處理中的檔案")}</strong>
        <div class="drive-card-sub">${sanitize(statusText)} · ${sanitize(item.msg || item.phase || "處理中")} · ${sanitize(bytes)}</div>
        <div class="drive-progress" aria-label="${sanitize(label)}">
          <div class="drive-progress-fill ${percent === null ? "indeterminate" : ""}" style="width:${width}%;"></div>
        </div>
      </div>
      <div class="drive-file-actions">
        <span class="drive-progress-label">${sanitize(label)}</span>
        ${item.status === "failed" || item.status === "completed" ? `<button class="btn btn-small" type="button" data-drive-action="dismiss-transfer" data-transfer-id="${sanitize(item.id)}" data-task-id="${sanitize(item.task_id || "")}">移除</button>` : ""}
      </div>
    </div>
  `;
}

let lastDriveFiles = [];

function renderDriveFiles(files) {
  lastDriveFiles = Array.isArray(files) ? files : [];
  const list = $("drive-file-list");
  if (!list) return;
  const transferHtml = driveTransferRows.map(renderDriveTransferRow).join("");
  if ((!Array.isArray(files) || !files.length) && !driveTransferRows.length) {
    list.innerHTML = `<div class="drive-empty">尚無雲端檔案</div>`;
    return;
  }
  const fileHtml = (Array.isArray(files) ? files : []).map((file) => {
    const name = file.original_filename_plain_for_public || file.id || "download.bin";
    const warn = driveFileNeedsWarning(file);
    const primary = drivePrimaryAction(file);
    const e2eeNote = driveFileIsE2ee(file) ? " · 需密碼預覽" : "";
    const rowAction = ` data-drive-action="preview"`;
    const albumButton = driveFileIsImage(file)
      ? `<button class="btn" type="button" data-drive-action="add-cloud-to-album" data-file-id="${sanitize(file.id)}" data-name="${sanitize(name)}">加入相簿</button>`
      : "";
    return `
      <div class="drive-file-row"${rowAction} data-file-id="${sanitize(file.id)}" data-name="${sanitize(name)}">
        <div>
          <strong>${sanitize(name)}</strong>
          <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · ${sanitize(drivePrivacyModeLabel(file.privacy_mode))}${drivePrivacyModeDescription(file.privacy_mode) ? `（${sanitize(drivePrivacyModeDescription(file.privacy_mode))}）` : ""} · ${sanitize(driveFileCategory(file))}${sanitize(e2eeNote)} · risk=${sanitize(file.risk_level || "-")} · scan=${sanitize(file.scan_status || "-")}</div>
        </div>
        <div class="drive-file-actions">
          <button class="btn" type="button" data-drive-action="${sanitize(primary.action)}" data-file-id="${sanitize(file.id)}">${sanitize(primary.label)}</button>
          <button class="btn" type="button" data-drive-action="move-cloud-to-storage" data-file-id="${sanitize(file.id)}" data-name="${sanitize(name)}">移動</button>
          ${albumButton}
          <button class="btn ${warn ? "btn-danger" : "btn-primary"}" type="button" data-drive-action="download" data-file-id="${sanitize(file.id)}" data-warn="${warn ? "1" : "0"}">下載</button>
          <button class="btn btn-danger" type="button" data-drive-action="delete-cloud" data-file-id="${sanitize(file.id)}">移到垃圾桶</button>
        </div>
      </div>
    `;
  }).join("");
  list.innerHTML = transferHtml + fileHtml;
}

function askDriveE2eePassphrase(promptText = "請輸入此檔案的 E2EE 加密密碼。") {
  return new Promise((resolve) => {
    const overlay = $("drive-e2ee-passphrase-overlay");
    const input = $("drive-e2ee-passphrase-input");
    const msg = $("drive-e2ee-passphrase-msg");
    const label = $("drive-e2ee-passphrase-prompt");
    const confirmBtn = $("drive-e2ee-passphrase-confirm-btn");
    const cancelBtn = $("drive-e2ee-passphrase-cancel-btn");
    if (!overlay || !input || !confirmBtn || !cancelBtn) {
      resolve(window.prompt(promptText) || "");
      return;
    }
    let done = false;
    const cleanup = (value) => {
      if (done) return;
      done = true;
      overlay.classList.remove("show");
      overlay.setAttribute("aria-hidden", "true");
      const anyOverlayOpen = document.querySelector(".user-edit-overlay.show, .album-full-preview-overlay.show");
      if (!anyOverlayOpen) document.body.classList.remove("modal-open");
      confirmBtn.removeEventListener("click", onConfirm);
      cancelBtn.removeEventListener("click", onCancel);
      input.removeEventListener("keydown", onKeydown);
      input.value = "";
      if (msg) msg.textContent = "";
      resolve(value || "");
    };
    const onConfirm = () => {
      if (!input.value) {
        if (msg) flash(msg, "請輸入 E2EE 加密密碼", false);
        return;
      }
      cleanup(input.value);
    };
    const onCancel = () => cleanup("");
    const onKeydown = (event) => {
      if (event.key === "Enter") onConfirm();
      if (event.key === "Escape") onCancel();
    };
    if (label) label.textContent = promptText;
    overlay.classList.add("show");
    overlay.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    confirmBtn.addEventListener("click", onConfirm);
    cancelBtn.addEventListener("click", onCancel);
    input.addEventListener("keydown", onKeydown);
    setTimeout(() => input.focus(), 0);
  });
}

async function loadDriveFiles(csrf) {
  const list = $("drive-file-list");
  if (!list) return;
  const res = await apiFetch(API + "/cloud-drive/files", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = `<div class="drive-empty">${sanitize(json.msg || "檔案列表讀取失敗")}</div>`;
    return;
  }
  const files = json.files || [];
  renderDriveFiles(files);
  driveAttachmentFileOptions = Array.isArray(files) ? files : [];
  driveAttachmentFileOptionsLoadedAt = Date.now();
  renderAttachmentFileSelects(files);
}

async function uploadDriveFile() {
  const input = $("drive-upload-file");
  if (!input || !input.files || !input.files[0]) {
    alert("請先選擇檔案");
    return;
  }
  const file = input.files[0];
  const transferId = addDriveTransferRow({
    kind: "upload",
    name: file.name,
    loaded_bytes: 0,
    total_bytes: file.size,
    progress_percent: 0,
    msg: "等待上傳",
  });
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const privacyMode = $("drive-upload-privacy-mode")?.value || "standard_plain";
  const form = new FormData();
  try {
    if (isDriveE2eeMode(privacyMode)) {
      updateDriveTransferRow(transferId, { phase: "encrypting", msg: "瀏覽器端加密中", progress_percent: null });
      const includeClientScanReport = !!$("drive-upload-client-scan-report")?.checked;
      const encrypted = await prepareDriveE2eeUpload(file, getDriveE2eeUploadPassphrase(), includeClientScanReport);
      form.append("file", encrypted.blob, encrypted.filename);
      form.append("encrypted_metadata", encrypted.encrypted_metadata);
      form.append("encrypted_file_key", encrypted.encrypted_file_key);
      form.append("wrapped_by", encrypted.wrapped_by);
      form.append("ciphertext_sha256", encrypted.ciphertext_sha256);
      form.append("encryption_algorithm", encrypted.encryption_algorithm);
      form.append("encryption_version", encrypted.encryption_version);
      form.append("nonce", encrypted.nonce);
      if (encrypted.client_scan_report) form.append("client_scan_report", JSON.stringify(encrypted.client_scan_report));
    } else {
      form.append("file", file);
    }
    form.append("privacy_mode", privacyMode);
    const { status, json } = await xhrUploadWithProgress(API + "/cloud-drive/upload", form, csrf, (event) => {
      if (event.lengthComputable) {
        updateDriveTransferRow(transferId, {
          loaded_bytes: event.loaded,
          total_bytes: event.total,
          progress_percent: (event.loaded / event.total) * 100,
          msg: event.loaded >= event.total ? "伺服器儲存與掃描中" : "上傳中",
        });
      } else {
        updateDriveTransferRow(transferId, {
          loaded_bytes: event.loaded || 0,
          total_bytes: null,
          progress_percent: null,
          msg: "上傳中",
        });
      }
    });
    if (status < 200 || status >= 300 || !json.ok) {
      const detail = json.error_code ? `${json.msg || "雲端硬碟上傳失敗"}（${json.error_code}）` : (json.msg || `雲端硬碟上傳失敗（HTTP ${status}）`);
      updateDriveTransferRow(transferId, { status: "failed", phase: "failed", msg: detail, progress_percent: 100 });
      alert(detail);
      return;
    }
    updateDriveTransferRow(transferId, { status: "completed", phase: "completed", msg: "上傳完成", progress_percent: 100, loaded_bytes: file.size, total_bytes: file.size });
    input.value = "";
    if (isDriveE2eeMode(privacyMode)) clearDriveE2eeUploadPassphrase();
    await loadDriveDashboard();
    setTimeout(() => removeDriveTransferRow(transferId), DRIVE_TRANSFER_COMPLETED_VISIBLE_MS);
  } catch (err) {
    const detail = err.message || "雲端硬碟上傳失敗";
    updateDriveTransferRow(transferId, { status: "failed", phase: "failed", msg: detail, progress_percent: 100 });
    alert(detail);
  }
}

function xhrUploadWithProgress(url, form, csrf, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (typeof onProgress === "function") onProgress(event);
    };
    xhr.onload = () => {
      let json = {};
      try {
        json = JSON.parse(xhr.responseText || "{}");
      } catch (err) {
        json = {};
      }
      resolve({ status: xhr.status, json });
    };
    xhr.onerror = () => reject(new Error("上傳連線失敗"));
    xhr.ontimeout = () => reject(new Error("上傳逾時"));
    xhr.send(form);
  });
}

async function loadRemoteDownloadCapabilities() {
  const status = $("drive-remote-download-status");
  const torrentButtons = [$("drive-remote-torrent-inline-btn"), $("drive-remote-torrent-btn")].filter(Boolean);
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  await fetchCsrfToken({ force: true });
  try {
    const res = await apiFetch(API + "/cloud-drive/remote-download/capabilities", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      driveRemoteDownloadCapabilities = { direct: true, bt_magnet: false, bt_file: false };
      if (status) status.textContent = json.msg || "BT 能力讀取失敗；Direct link 仍可用";
      torrentButtons.forEach((button) => {
        button.disabled = true;
        button.title = "BT 能力讀取失敗，請稍後重新整理";
      });
      return;
    }
    const caps = json.capabilities || {};
    driveRemoteDownloadCapabilities = {
      direct: true,
      bt_magnet: !!caps.bt_magnet,
      bt_file: !!caps.bt_file,
    };
    const btReady = driveRemoteDownloadCapabilities.bt_magnet || driveRemoteDownloadCapabilities.bt_file;
    torrentButtons.forEach((button) => {
      button.disabled = !btReady;
      button.title = btReady ? `BT 可用：${caps.aria2c_path || "aria2c"}` : "BT 不可用：伺服器需安裝 aria2c";
    });
    if (status) {
      status.textContent = btReady
        ? `Direct link 可用；BT/magnet 可用（${caps.aria2c_path || "aria2c"}）`
        : "Direct link 可用；BT/magnet 不可用，伺服器需安裝 aria2c";
    }
  } catch (err) {
    driveRemoteDownloadCapabilities = { direct: true, bt_magnet: false, bt_file: false };
    if (status) status.textContent = "BT 能力檢查失敗；Direct link 仍可用";
    torrentButtons.forEach((button) => {
      button.disabled = true;
      button.title = "BT 能力檢查失敗，請稍後重新整理";
    });
  }
}

function classifyRemoteDownloadInput(rawUrl, { torrentUrlsAsBt = false } = {}) {
  const url = String(rawUrl || "").trim();
  if (!url) return { ok: false, kind: "", label: "", msg: "請輸入 direct link 或 magnet link" };
  if (url.startsWith("magnet:?")) return { ok: true, kind: "magnet", label: "BT magnet" };
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    return { ok: false, kind: "", label: "", msg: "網址格式不正確，只接受 http、https direct link 或 magnet link" };
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    return { ok: false, kind: "", label: "", msg: "只接受 http、https direct link 或 magnet link" };
  }
  if (torrentUrlsAsBt && parsed.pathname.toLowerCase().endsWith(".torrent")) {
    return { ok: true, kind: "torrent_url", label: "BT torrent URL" };
  }
  return { ok: true, kind: "direct", label: "direct link" };
}

function promptRemoteDriveDownloadUrl() {
  const input = $("drive-remote-url");
  const current = (input?.value || "").trim();
  const value = window.prompt("輸入 Direct link URL（http/https）", current);
  if (value === null) return;
  if (input) input.value = value.trim();
  const torrentInput = $("drive-remote-torrent-file");
  if (torrentInput) torrentInput.value = "";
  startRemoteDriveDownload({ source: "url", downloadMode: "direct", triggerButton: $("drive-remote-download-btn") });
}

function openRemoteTorrentPicker() {
  const input = $("drive-remote-torrent-file");
  const caps = driveRemoteDownloadCapabilities || {};
  if (!caps.bt_file && !caps.bt_magnet) {
    alert("BT 功能目前不可用，請確認伺服器已安裝 aria2c。");
    return;
  }
  if (caps.bt_magnet) {
    const value = window.prompt("輸入 magnet link 或 .torrent URL；若要上傳 .torrent 檔，請留空後按確定");
    if (value === null) return;
    if (value.trim()) {
      if ($("drive-remote-url")) $("drive-remote-url").value = value.trim();
      if (input) input.value = "";
      startRemoteDriveDownload({ source: "torrent-url", downloadMode: "bt", triggerButton: $("drive-remote-torrent-inline-btn") });
      return;
    }
  }
  if (!input || !caps.bt_file) return;
  input.value = "";
  input.click();
}

async function startRemoteDriveDownload({ source = "auto", downloadMode = "direct", triggerButton = null } = {}) {
  const url = source === "torrent" ? "" : ($("drive-remote-url")?.value || "").trim();
  const torrentInput = $("drive-remote-torrent-file");
  const torrentFile = source === "url" || source === "torrent-url" ? null : (torrentInput?.files?.[0] || null);
  if (!url && !torrentFile) {
    if (source === "auto") return promptRemoteDriveDownloadUrl();
    alert("請輸入下載網址，或上傳 .torrent BT 種子檔");
    return;
  }
  if (url && torrentFile) {
    alert("下載網址和 BT 種子檔請擇一使用");
    return;
  }
  const effectiveMode = torrentFile ? "bt" : (downloadMode === "bt" || source === "torrent-url" ? "bt" : "direct");
  const detected = url
    ? classifyRemoteDownloadInput(url, { torrentUrlsAsBt: effectiveMode === "bt" })
    : { ok: true, kind: "torrent_file", label: "BT torrent file" };
  if (!detected.ok) {
    alert(detected.msg || "下載網址格式不正確");
    return;
  }
  const caps = driveRemoteDownloadCapabilities || {};
  if (detected.kind === "magnet" && !caps.bt_magnet) {
    alert("BT magnet 功能目前不可用，請確認伺服器已安裝 aria2c。");
    return;
  }
  if ((detected.kind === "torrent_file" || detected.kind === "torrent_url") && !caps.bt_file) {
    alert("BT torrent 功能目前不可用，請確認伺服器已安裝 aria2c。");
    return;
  }
  const options = await askDriveUploadPrivacyOptions({ allowE2ee: false, title: `${detected.label || "遠端下載"}儲存前選擇隱私模式` });
  if (!options) return;
  if ($("drive-remote-privacy-mode")) $("drive-remote-privacy-mode").value = options.privacyMode;
  const transferId = addDriveTransferRow({
    kind: "remote_download",
    name: torrentFile ? torrentFile.name : url,
    loaded_bytes: 0,
    total_bytes: null,
    progress_percent: 0,
    msg: `建立${detected.label || "遠端"}下載任務`,
  });
  const button = triggerButton || $("drive-remote-download-btn");
  const oldText = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "下載中...";
  }
  try {
    await fetchCsrfToken({ force: true });
    let res;
    if (torrentFile) {
      const form = new FormData();
      form.append("torrent_file", torrentFile);
      form.append("privacy_mode", options.privacyMode);
      form.append("virtual_path", $("drive-remote-virtual-path")?.value || "");
      res = await apiFetch(API + "/cloud-drive/remote-download/torrent-tasks", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": getCsrfToken() || "" },
        body: form
      });
    } else {
      const status = $("drive-remote-download-status");
      if (status) status.textContent = `偵測為 ${detected.label}，正在建立下載任務...`;
      res = await apiFetch(API + "/cloud-drive/remote-download/tasks", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
        body: JSON.stringify({
          url,
          download_mode: effectiveMode,
          privacy_mode: options.privacyMode,
          virtual_path: $("drive-remote-virtual-path")?.value || ""
        })
      });
    }
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `遠端下載失敗（HTTP ${res.status}）`);
    const task = json.task || {};
    if (!task.id) throw new Error("遠端下載任務建立失敗");
    updateDriveTransferRow(transferId, {
      id: transferId,
      task_id: task.id,
      status: task.status || "running",
      phase: task.phase || "queued",
      msg: task.msg || "已加入下載佇列",
    });
    if ($("drive-remote-url")) $("drive-remote-url").value = "";
    if (torrentInput) torrentInput.value = "";
    flash($("drive-msg"), json.msg || "遠端下載任務已建立，可繼續操作頁面", true);
    resumeRemoteDownloadTaskPolling(task);
  } catch (err) {
    updateDriveTransferRow(transferId, { status: "failed", phase: "failed", msg: err.message || "遠端下載失敗", progress_percent: 100 });
    alert(err.message || "遠端下載失敗");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = oldText || "開始下載";
    }
  }
}

function driveSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollRemoteDownloadTask(taskId, transferId) {
  if (!taskId) throw new Error("遠端下載任務建立失敗");
  let consecutiveStatusErrors = 0;
  while (true) {
    await driveSleep(900);
    let res;
    let json = {};
    try {
      await fetchCsrfToken({ force: true });
      res = await apiFetch(API + `/cloud-drive/remote-download/tasks/${encodeURIComponent(taskId)}`, {
        credentials: "same-origin",
        headers: { "X-CSRF-Token": getCsrfToken() || "" }
      });
      json = await res.json().catch(() => ({}));
      if (!res.ok || !json.ok) {
        throw new Error(json.msg || `遠端下載狀態讀取失敗（HTTP ${res.status}）`);
      }
      consecutiveStatusErrors = 0;
    } catch (err) {
      consecutiveStatusErrors += 1;
      updateDriveTransferRow(transferId, {
        status: "running",
        phase: "status_retry",
        msg: `狀態暫時讀取失敗，正在重試（${consecutiveStatusErrors}/${DRIVE_REMOTE_STATUS_RETRY_LIMIT}）`,
      });
      if (consecutiveStatusErrors < DRIVE_REMOTE_STATUS_RETRY_LIMIT) {
        continue;
      }
      const statusError = new Error(err.message || "遠端下載狀態連續讀取失敗");
      statusError.remoteStatusTransient = true;
      throw statusError;
    }
    const task = json.task || {};
    updateDriveTransferRow(transferId, {
      task_id: task.id || taskId,
      name: task.filename || task.url || "遠端下載",
      status: task.status || "running",
      phase: task.phase || "",
      loaded_bytes: task.loaded_bytes,
      total_bytes: task.total_bytes,
      progress_percent: task.progress_percent,
      msg: task.msg || "",
    });
    const status = $("drive-remote-download-status");
    if (status) {
      const percent = task.progress_percent === null || task.progress_percent === undefined ? "計算中" : `${Math.round(Number(task.progress_percent || 0))}%`;
      status.textContent = `${task.msg || "遠端下載中"} · ${percent}`;
    }
    if (task.status === "completed") return task;
    if (task.status === "failed") {
      const failedError = new Error(task.error || task.msg || "遠端下載失敗");
      failedError.remoteTaskFailed = true;
      throw failedError;
    }
  }
}

function remoteTaskTransferId(taskId) {
  return `remote-task-${taskId}`;
}

function applyRemoteDownloadTaskToTransfer(task) {
  if (!task?.id) return null;
  const transferId = findDriveTransferRowIdForTask(task.id) || remoteTaskTransferId(task.id);
  updateDriveTransferRow(transferId, {
    id: transferId,
    task_id: task.id,
    kind: "remote_download",
    name: task.filename || task.torrent_filename || task.url || "遠端下載",
    status: task.status || "running",
    phase: task.phase || "",
    loaded_bytes: task.loaded_bytes,
    total_bytes: task.total_bytes,
    progress_percent: task.progress_percent,
    msg: task.msg || "",
  });
  return transferId;
}

function resumeRemoteDownloadTaskPolling(task) {
  if (!task?.id || !["queued", "running"].includes(task.status)) return;
  if (driveRemotePollingTaskIds.has(task.id)) return;
  const transferId = applyRemoteDownloadTaskToTransfer(task);
  if (!transferId) return;
  driveRemotePollingTaskIds.add(task.id);
  pollRemoteDownloadTask(task.id, transferId)
    .then(async () => {
      await loadDriveDashboard();
    })
    .catch((err) => {
      if (err?.remoteStatusTransient) {
        updateDriveTransferRow(transferId, {
          status: "running",
          phase: "status_retry_paused",
          msg: `${err.message || "狀態暫時讀取失敗"}；任務仍保留，稍後自動重試`,
          progress_percent: null,
        });
        setTimeout(() => {
          driveRemotePollingTaskIds.delete(task.id);
          resumeRemoteDownloadTaskPolling({ ...task, status: "running" });
        }, 5000);
        return;
      }
      updateDriveTransferRow(transferId, {
        status: "failed",
        phase: "failed",
        msg: err.message || "遠端下載失敗",
        progress_percent: 100,
      });
    })
    .finally(() => {
      driveRemotePollingTaskIds.delete(task.id);
    });
}

async function restoreRemoteDownloadTasks() {
  await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/cloud-drive/remote-download/tasks", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" },
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) return;
  const tasks = Array.isArray(json.tasks) ? json.tasks : [];
  tasks.forEach((task) => {
    const transferId = applyRemoteDownloadTaskToTransfer(task);
    if (!transferId) return;
    if (task.status === "completed" || task.status === "failed") {
      return;
    }
    resumeRemoteDownloadTaskPolling(task);
  });
}

async function downloadDriveFile(fileId, likelyHighRisk) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const doFetch = (confirmed) => apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/download${confirmed ? "?confirm_high_risk=1" : ""}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  let res = await doFetch(false);
  if (res.status === 409 || likelyHighRisk) {
    let warningText = "此檔案可能高風險、未完整掃描或為 E2EE 密文。請確認你信任來源後再下載。";
    if (res.status === 409) {
      const json = await res.json().catch(() => ({}));
      warningText = json.msg || warningText;
    }
    if (!window.confirm(warningText)) return;
    res = await doFetch(true);
  }
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    alert(json.msg || "下載失敗");
    return;
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/i);
  let name = match ? match[1] : "download.bin";
  let outputBlob = blob;
  const keyRes = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/e2ee-key`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (keyRes.ok) {
    const keyJson = await keyRes.json().catch(() => ({}));
    if (keyJson.ok && keyJson.e2ee) {
      try {
        const passphrase = await getDriveE2eeSessionPassphrase(fileId, "請輸入此 E2EE 檔案的加密密碼。密碼不會送到伺服器；本次登入期間會暫存在瀏覽器記憶體。");
        if (!passphrase) return;
        const decrypted = await decryptDriveE2eeBlob(blob, keyJson.e2ee, passphrase);
        rememberDriveE2eeSessionPassphrase(fileId, passphrase);
        outputBlob = decrypted.blob;
        name = decrypted.filename || name;
      } catch (err) {
        forgetDriveE2eeSessionPassphrase(fileId);
        alert(`${err.message || "端到端加密檔案解密失敗"}\n\n請確認輸入的是上傳此檔案時設定的 E2EE 加密密碼；伺服器無法重設或找回此密碼。`);
        return;
      }
    }
  }
  const url = URL.createObjectURL(outputBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function deleteDriveFile(fileId) {
  if (!window.confirm("將此檔案移到垃圾桶？清空垃圾桶前仍可還原。")) return;
  try {
    await storageAction(`/cloud-drive/files/${encodeURIComponent(fileId)}`, "DELETE");
    await loadDriveDashboard();
  } catch (err) {
    alert(err.message || "移到垃圾桶失敗");
  }
}

async function moveCloudFileToStorage(fileId, name) {
  const requested = window.prompt("移動到 FileManager 路徑", joinStoragePath(currentStoragePath || "/", name || "file"));
  if (requested === null) return;
  const path = normalizeStoragePath(requested, name || "file");
  if (path === "/") {
    alert("請輸入包含檔名的路徑");
    return;
  }
  try {
    await storageAction("/storage/files/attach-existing", "POST", {
      file_id: fileId,
      virtual_path: path,
      display_name: storageBaseName(path),
    });
    currentStoragePath = storageDirName(path);
    await loadDriveDashboard();
  } catch (err) {
    alert(err.message || "移動失敗");
  }
}

let currentDrivePreviewUrl = "";
let selectedAlbumId = "";
let selectedStorageFileId = "";
let selectedStorageFilePath = "";
let currentStoragePath = "/";
let storageFilesCache = [];
let storageFoldersCache = [];
let storageAlbumsCache = [];
let selectedAlbumViewerId = "";
let pendingAlbumPickerResolve = null;
let albumThumbObjectUrls = [];
let currentAlbumFullPreviewUrl = "";
let albumPreviewSequence = [];
let albumPreviewIndex = -1;
let lastDrivePreviewClick = { fileId: "", at: 0 };
const DRIVE_FULLSCREEN_PREVIEW_MS = 450;

function getAlbumThumbSize() {
  const stored = localStorage.getItem("albumThumbSize") || "medium";
  return ["small", "medium", "large"].includes(stored) ? stored : "medium";
}

function setAlbumThumbSize(size) {
  const normalized = ["small", "medium", "large"].includes(size) ? size : "medium";
  localStorage.setItem("albumThumbSize", normalized);
  const select = $("album-thumb-size");
  if (select) select.value = normalized;
  const grid = $("album-viewer-files");
  if (grid) {
    grid.classList.remove("album-thumb-small", "album-thumb-medium", "album-thumb-large");
    grid.classList.add(`album-thumb-${normalized}`);
  }
}

function clearAlbumThumbObjectUrls() {
  albumThumbObjectUrls.forEach((url) => URL.revokeObjectURL(url));
  albumThumbObjectUrls = [];
}

function clearDrivePreviewUrl() {
  if (currentDrivePreviewUrl) {
    URL.revokeObjectURL(currentDrivePreviewUrl);
    currentDrivePreviewUrl = "";
  }
}

function driveFileIsImage(file) {
  const mime = String(file?.mime_type_plain_for_public || file?.mime_type || "").toLowerCase();
  const name = String(file?.original_filename_plain_for_public || file?.display_name || file?.filename || "").toLowerCase();
  return mime.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg|avif)$/.test(name);
}

function drivePreviewContentUrl(fileId) {
  return `${API}/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content`;
}

function findKnownDriveFile(fileId) {
  const target = String(fileId || "");
  const sources = [
    ...(Array.isArray(lastDriveFiles) ? lastDriveFiles : []),
    ...(Array.isArray(storageFilesCache) ? storageFilesCache : []),
    ...(Array.isArray(albumPreviewSequence) ? albumPreviewSequence : []),
  ];
  return sources.find((file) => String(file?.id || file?.file_id || "") === target || String(file?.file_id || "") === target) || null;
}

async function fetchDriveE2eeKey(fileId, csrf) {
  const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/e2ee-key`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok || !json.e2ee) throw new Error(json.msg || "E2EE 解密資訊讀取失敗");
  return json.e2ee;
}

async function fetchDriveE2eeCiphertext(fileId, csrf) {
  const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.msg || "E2EE 密文讀取失敗");
  }
  return res.blob();
}

async function decryptDriveE2eeFileForSession(fileId, csrf, promptText) {
  const e2ee = await fetchDriveE2eeKey(fileId, csrf);
  const ciphertext = await fetchDriveE2eeCiphertext(fileId, csrf);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const passphrase = await getDriveE2eeSessionPassphrase(fileId, promptText, { force: attempt > 0 });
    if (!passphrase) return null;
    try {
      const decrypted = await decryptDriveE2eeBlob(ciphertext, e2ee, passphrase);
      rememberDriveE2eeSessionPassphrase(fileId, passphrase);
      return decrypted;
    } catch (err) {
      forgetDriveE2eeSessionPassphrase(fileId);
      if (attempt > 0) throw err;
      alert("E2EE 密碼不正確或檔案已損壞，請重新輸入。");
    }
  }
  return null;
}

async function buildDriveE2eePreview(fileId, csrf) {
  const decrypted = await decryptDriveE2eeFileForSession(
    fileId,
    csrf,
    "請輸入此 E2EE 檔案的加密密碼。密碼不會送到伺服器；本次登入期間會暫存在瀏覽器記憶體。"
  );
  if (!decrypted) return null;
  const known = findKnownDriveFile(fileId) || {};
  const filename = decrypted.filename || known.display_name || known.original_filename_plain_for_public || "download";
  const fileLike = {
    ...known,
    id: fileId,
    display_name: filename,
    original_filename_plain_for_public: filename,
    mime_type_plain_for_public: decrypted.blob.type || known.mime_type_plain_for_public || "",
    privacy_mode: "e2ee",
    size_bytes: decrypted.blob.size,
    risk_level: known.risk_level || "unknown_encrypted",
    scan_status: known.scan_status || "skipped_e2ee",
  };
  const category = driveFileCategory(fileLike);
  const preview = {
    file_id: fileId,
    filename,
    size_bytes: decrypted.blob.size,
    privacy_mode: "e2ee",
    risk_level: fileLike.risk_level,
    scan_status: fileLike.scan_status,
    category,
    mime_type: decrypted.blob.type || fileLike.mime_type_plain_for_public || "application/octet-stream",
    render_mode: "metadata",
    previewable: ["audio", "video", "image", "pdf", "text"].includes(category),
    e2ee_browser_decrypted: true,
  };
  if (["audio", "video", "image", "pdf"].includes(category)) {
    preview.render_mode = "media";
    return { preview, blob: decrypted.blob };
  }
  if (category === "text") {
    const maxBytes = 65536;
    preview.render_mode = "text";
    preview.truncated = decrypted.blob.size > maxBytes;
    preview.text = await decrypted.blob.slice(0, maxBytes).text();
    return { preview, blob: decrypted.blob };
  }
  return { preview, blob: decrypted.blob };
}

function clearAlbumFullPreviewUrl() {
  if (currentAlbumFullPreviewUrl) {
    URL.revokeObjectURL(currentAlbumFullPreviewUrl);
    currentAlbumFullPreviewUrl = "";
  }
}

async function fetchDrivePreviewBlob(fileId, csrf) {
  const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.msg || "預覽內容讀取失敗");
  }
  return res.blob();
}

async function fetchDrivePreviewContent(fileId, csrf) {
  const blob = await fetchDrivePreviewBlob(fileId, csrf);
  clearDrivePreviewUrl();
  currentDrivePreviewUrl = URL.createObjectURL(blob);
  return currentDrivePreviewUrl;
}

function renderDriveDecryptedPreviewMedia(preview, blob, { fullscreen = false } = {}) {
  const url = URL.createObjectURL(blob);
  const title = sanitize(preview.filename || "E2EE preview");
  if (fullscreen) {
    clearAlbumFullPreviewUrl();
    currentAlbumFullPreviewUrl = url;
  } else {
    clearDrivePreviewUrl();
    currentDrivePreviewUrl = url;
  }
  if (preview.category === "audio") return `<audio controls ${fullscreen ? "autoplay " : ""}src="${url}"></audio>`;
  if (preview.category === "video") return `<video controls ${fullscreen ? "autoplay " : ""}src="${url}"></video>`;
  if (preview.category === "image") return `<img src="${url}" alt="${title}" />`;
  if (preview.category === "pdf") return `<iframe src="${url}" title="${title}"></iframe>`;
  return `<div class="drive-empty">此 E2EE 檔案已在瀏覽器解密，但目前不支援 inline 預覽。</div>`;
}

function closeDrivePreview() {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  clearDrivePreviewUrl();
  if (panel) panel.innerHTML = `<div class="drive-empty">請從左側檔案清單選擇要預覽的檔案</div>`;
  if (card) card.style.display = "";
  lastDrivePreviewClick = { fileId: "", at: 0 };
}

function closeAlbumFullPreview() {
  const overlay = $("album-full-preview-overlay");
  const body = $("album-full-preview-body");
  clearAlbumFullPreviewUrl();
  albumPreviewIndex = -1;
  if (body) body.innerHTML = "";
  if (overlay) {
    overlay.classList.remove("show");
    overlay.setAttribute("aria-hidden", "true");
  }
  document.body.classList.remove("modal-open");
}

function albumPreviewFileName(file) {
  return albumFileDisplayName(file || {}) || "圖片預覽";
}

function setAlbumPreviewSequence(files = [], fileId = "") {
  const rows = (Array.isArray(files) ? files : [])
    .filter((file) => file?.file_id && (typeof driveFileIsImage !== "function" || driveFileIsImage(file)));
  albumPreviewSequence = rows;
  albumPreviewIndex = rows.findIndex((file) => String(file.file_id) === String(fileId || ""));
}

function albumPreviewCurrentCountLabel() {
  if (!albumPreviewSequence.length || albumPreviewIndex < 0) return "";
  return `${albumPreviewIndex + 1} / ${albumPreviewSequence.length}`;
}

function updateAlbumPreviewControls() {
  const hasMany = albumPreviewSequence.length > 1 && albumPreviewIndex >= 0;
  document.querySelectorAll("[data-drive-action='album-preview-prev'], [data-drive-action='album-preview-next']").forEach((button) => {
    button.disabled = !hasMany;
    button.classList.toggle("is-disabled", !hasMany);
  });
}

function renderDrivePreviewMetadata(preview, fileId) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (!panel || !card) return "";
  card.style.display = "block";
  return `
    <div>
      <strong>${sanitize(preview.filename || "preview")}</strong>
      <div class="drive-card-sub">
        ${sanitize(preview.category || "-")} · ${formatDriveBytes(preview.size_bytes || 0)} · ${sanitize(preview.mime_type || "-")}
        · ${sanitize(drivePrivacyModeLabel(preview.privacy_mode))} · risk=${sanitize(preview.risk_level || "-")} · scan=${sanitize(preview.scan_status || "-")}
      </div>
    </div>
    <div class="drive-file-actions" style="justify-content:flex-start;">
      <button class="btn btn-primary" type="button" data-drive-action="download" data-file-id="${sanitize(fileId)}" data-warn="${driveFileNeedsWarning(preview) ? "1" : "0"}">下載</button>
      ${preview.render_mode === "text" ? `<button class="btn" type="button" data-drive-action="edit-text" data-file-id="${sanitize(fileId)}">編輯文字</button>` : ""}
      <button class="btn" type="button" data-drive-action="close-preview">關閉預覽</button>
    </div>
  `;
}

function isDriveE2eeServerPreviewError(response, payload) {
  const msg = String(payload?.msg || payload?.message || "");
  return response?.status === 403 && msg.includes("E2EE") && msg.includes("伺服器預覽");
}

function shouldOpenDriveFullscreen(fileId, options = {}) {
  if (options.skipRepeatCheck) return false;
  const now = Date.now();
  const repeated = lastDrivePreviewClick.fileId === String(fileId || "") && now - lastDrivePreviewClick.at <= DRIVE_FULLSCREEN_PREVIEW_MS;
  lastDrivePreviewClick = { fileId: String(fileId || ""), at: now };
  return repeated;
}

function renderDriveArchiveEntries(entries) {
  const rows = Array.isArray(entries) ? entries : [];
  if (!rows.length) return "壓縮檔內無可列出的項目";
  return rows.map((entry) => {
    const name = `${entry.is_dir ? "[dir] " : ""}${sanitize(entry.name || "-")}`;
    const size = entry.size === null || entry.size === undefined ? "-" : formatDriveBytes(entry.size || 0);
    const compressed = entry.compressed_size === null || entry.compressed_size === undefined ? "" : ` · compressed ${formatDriveBytes(entry.compressed_size || 0)}`;
    const note = entry.note ? ` · ${sanitize(entry.note)}` : "";
    return `${name} · ${size}${compressed}${note}`;
  }).join("\n");
}

async function previewDriveFile(fileId, options = {}) {
  const knownFile = findKnownDriveFile(fileId);
  if (driveFileIsE2ee(knownFile)) {
    if (shouldOpenDriveFullscreen(fileId, options)) {
      return previewAlbumFileFullscreen(fileId, options.fileName || "");
    }
    return previewDriveE2eeFile(fileId);
  }
  if (shouldOpenDriveFullscreen(fileId, options)) {
    return previewAlbumFileFullscreen(fileId, options.fileName || "");
  }
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (card) card.style.display = "";
  if (panel) panel.innerHTML = `<div class="drive-empty">讀取預覽中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok && isDriveE2eeServerPreviewError(res, json)) {
      return previewDriveE2eeFile(fileId);
    }
    if (!json.ok) throw new Error(json.msg || "預覽失敗");
    const preview = json.preview || {};
    if (!panel) return;
    panel.innerHTML = renderDrivePreviewMetadata(preview, fileId);
    if (preview.render_mode === "text") {
      panel.innerHTML += `${driveRenderTextPreview(preview)}${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "archive") {
      const entries = Array.isArray(preview.entries) ? preview.entries : [];
      panel.innerHTML += `<div class="drive-preview-archive">${renderDriveArchiveEntries(entries)}</div>${preview.truncated ? '<div class="drive-card-sub">項目過多，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "media") {
      const url = await fetchDrivePreviewContent(fileId, csrf);
      if (preview.category === "audio") panel.innerHTML += `<audio controls src="${url}"></audio>`;
      else if (preview.category === "video") panel.innerHTML += `<video controls src="${url}"></video>`;
      else if (preview.category === "image") panel.innerHTML += `<img src="${url}" alt="${sanitize(preview.filename || "image preview")}" />`;
      else if (preview.category === "pdf") panel.innerHTML += `<iframe src="${url}" title="PDF preview"></iframe>`;
      else panel.innerHTML += `<div class="drive-empty">此檔案無可用預覽。</div>`;
      return;
    }
    panel.innerHTML += `<div class="drive-empty">此檔案類型目前只提供 metadata，不支援 inline 預覽。</div>`;
  } catch (err) {
    clearDrivePreviewUrl();
    if (panel) panel.innerHTML = `<div class="drive-empty">${sanitize(err.message || "預覽失敗")}</div>`;
  }
}

async function previewDriveE2eeFile(fileId) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (card) card.style.display = "";
  if (panel) panel.innerHTML = `<div class="drive-empty">等待 E2EE 密碼並在瀏覽器解密中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const decrypted = await buildDriveE2eePreview(fileId, csrf);
    if (!decrypted || !panel) return;
    const { preview, blob } = decrypted;
    panel.innerHTML = renderDrivePreviewMetadata(preview, fileId);
    if (preview.render_mode === "text") {
      panel.innerHTML += `${driveRenderTextPreview(preview)}${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "media") {
      panel.innerHTML += renderDriveDecryptedPreviewMedia(preview, blob);
      return;
    }
    panel.innerHTML += `<div class="drive-empty">此 E2EE 檔案已在瀏覽器解密，但目前只提供 metadata 預覽。</div>`;
  } catch (err) {
    clearDrivePreviewUrl();
    if (panel) panel.innerHTML = `<div class="drive-empty">${sanitize(err.message || "E2EE 預覽失敗")}</div>`;
  }
}

async function previewAlbumFileFullscreen(fileId, fileName = "", options = {}) {
  if (Array.isArray(options.files)) {
    setAlbumPreviewSequence(options.files, fileId);
  } else if (!albumPreviewSequence.some((file) => String(file.file_id) === String(fileId || ""))) {
    setAlbumPreviewSequence([], fileId);
  } else {
    albumPreviewIndex = albumPreviewSequence.findIndex((file) => String(file.file_id) === String(fileId || ""));
  }
  const overlay = $("album-full-preview-overlay");
  const title = $("album-full-preview-title");
  const meta = $("album-full-preview-meta");
  const body = $("album-full-preview-body");
  if (!overlay || !body) return previewDriveFile(fileId, { skipRepeatCheck: true, fileName });
  clearAlbumFullPreviewUrl();
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  if (title) title.textContent = fileName || albumPreviewFileName(albumPreviewSequence[albumPreviewIndex]) || "檔案預覽";
  if (meta) meta.textContent = "讀取檔案中...";
  updateAlbumPreviewControls();
  body.innerHTML = `<div class="drive-empty">讀取檔案中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const knownFile = findKnownDriveFile(fileId);
    if (driveFileIsE2ee(knownFile)) {
      const decrypted = await buildDriveE2eePreview(fileId, csrf);
      if (!decrypted) return;
      const { preview, blob } = decrypted;
      if (title) title.textContent = preview.filename || fileName || "E2EE 預覽";
      const countLabel = albumPreviewCurrentCountLabel();
      const baseMeta = `${countLabel ? `${countLabel} · ` : ""}${formatDriveBytes(preview.size_bytes || 0)} · ${preview.mime_type || blob.type || "-"} · E2EE 瀏覽器解密`;
      if (meta) meta.textContent = baseMeta;
      if (preview.render_mode === "text") {
        body.innerHTML = `${driveRenderTextPreview(preview)}${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
        return;
      }
      if (preview.render_mode === "media") {
        body.innerHTML = renderDriveDecryptedPreviewMedia(preview, blob, { fullscreen: true });
        return;
      }
      body.innerHTML = `<div class="drive-empty">此 E2EE 檔案已在瀏覽器解密，但目前只提供 metadata 預覽。</div>`;
      return;
    }
    const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "預覽失敗");
    const preview = json.preview || {};
    if (title) title.textContent = preview.filename || fileName || albumPreviewFileName(albumPreviewSequence[albumPreviewIndex]) || "檔案預覽";
    const countLabel = albumPreviewCurrentCountLabel();
    const baseMeta = `${countLabel ? `${countLabel} · ` : ""}${formatDriveBytes(preview.size_bytes || 0)} · ${preview.mime_type || "-"} · scan=${preview.scan_status || "-"}`;
    if (preview.render_mode === "text") {
      if (meta) meta.textContent = baseMeta;
      body.innerHTML = `${driveRenderTextPreview(preview)}${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "archive") {
      const entries = Array.isArray(preview.entries) ? preview.entries : [];
      if (meta) meta.textContent = baseMeta;
      body.innerHTML = `<div class="drive-preview-archive">${renderDriveArchiveEntries(entries)}</div>${preview.truncated ? '<div class="drive-card-sub">項目過多，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode !== "media") {
      throw new Error("這個檔案類型目前只提供右側 metadata 預覽");
    }
    const blob = await fetchDrivePreviewBlob(fileId, csrf);
    currentAlbumFullPreviewUrl = URL.createObjectURL(blob);
    if (meta) meta.textContent = `${formatDriveBytes(preview.size_bytes || 0)} · ${preview.mime_type || blob.type || "-"} · scan=${preview.scan_status || "-"}`;
    if (preview.category === "image") {
      body.innerHTML = `<img src="${currentAlbumFullPreviewUrl}" alt="${sanitize(preview.filename || fileName || "image preview")}" />`;
    } else if (preview.category === "video") {
      body.innerHTML = `<video controls autoplay src="${currentAlbumFullPreviewUrl}"></video>`;
    } else if (preview.category === "audio") {
      body.innerHTML = `<audio controls autoplay src="${currentAlbumFullPreviewUrl}"></audio>`;
    } else if (preview.category === "pdf") {
      body.innerHTML = `<iframe src="${currentAlbumFullPreviewUrl}" title="${sanitize(preview.filename || fileName || "PDF preview")}"></iframe>`;
    } else {
      throw new Error("這個檔案類型目前只支援右側預覽");
    }
  } catch (err) {
    clearAlbumFullPreviewUrl();
    updateAlbumPreviewControls();
    if (meta) meta.textContent = "";
    body.innerHTML = `<div class="drive-empty">${sanitize(err.message || "預覽失敗")}</div>`;
  }
}

function stepAlbumPreview(direction) {
  if (!albumPreviewSequence.length || albumPreviewIndex < 0) return;
  const nextIndex = (albumPreviewIndex + direction + albumPreviewSequence.length) % albumPreviewSequence.length;
  const nextFile = albumPreviewSequence[nextIndex];
  if (!nextFile?.file_id) return;
  albumPreviewIndex = nextIndex;
  previewAlbumFileFullscreen(nextFile.file_id, albumPreviewFileName(nextFile)).catch((err) => alert(err.message || "預覽失敗"));
}

async function editDriveTextFile(fileId) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (card) card.style.display = "block";
  if (panel) panel.innerHTML = `<div class="drive-empty">讀取文字內容中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "讀取失敗");
    const preview = json.preview || {};
    if (preview.render_mode !== "text") throw new Error("目前只支援文字類檔案線上修改");
    if (panel) {
      panel.innerHTML = `
        <div><strong>${sanitize(preview.filename || "text")}</strong></div>
        <textarea id="drive-text-editor" rows="14">${sanitize(preview.text || "")}</textarea>
        <div class="drive-file-actions" style="justify-content:flex-start;">
          <button class="btn btn-primary" type="button" data-drive-action="save-text" data-file-id="${sanitize(fileId)}">儲存修改</button>
          <button class="btn" type="button" data-drive-action="preview" data-file-id="${sanitize(fileId)}">取消</button>
        </div>
      `;
    }
  } catch (err) {
    if (panel) panel.innerHTML = `<div class="drive-empty">${sanitize(err.message || "讀取失敗")}</div>`;
  }
}

async function saveDriveTextFile(fileId) {
  const editor = $("drive-text-editor");
  if (!editor) return;
  try {
    await storageAction(`/cloud-drive/files/${encodeURIComponent(fileId)}/text`, "PUT", { content: editor.value });
    await loadDriveDashboard();
    await previewDriveFile(fileId, { skipRepeatCheck: true });
  } catch (err) {
    alert(err.message || "儲存失敗");
  }
}

function openDriveTextDocumentModal() {
  const overlay = $("drive-new-doc-overlay");
  if (!overlay) return;
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  const msg = $("drive-new-doc-msg");
  if (msg) msg.textContent = "";
  setTimeout(() => $("drive-new-doc-name")?.focus?.(), 0);
}

function closeDriveTextDocumentModal({ clear = false } = {}) {
  const overlay = $("drive-new-doc-overlay");
  if (!overlay) return;
  overlay.classList.remove("show");
  overlay.setAttribute("aria-hidden", "true");
  const anyOverlayOpen = document.querySelector(".user-edit-overlay.show, .album-full-preview-overlay.show");
  if (!anyOverlayOpen) document.body.classList.remove("modal-open");
  const msg = $("drive-new-doc-msg");
  if (msg) msg.textContent = "";
  if (clear) {
    if ($("drive-new-doc-name")) $("drive-new-doc-name").value = "";
    if ($("drive-new-doc-content")) $("drive-new-doc-content").value = "";
  }
}

async function createDriveTextDocument() {
  const filename = ($("drive-new-doc-name")?.value || "").trim() || "untitled.txt";
  const content = $("drive-new-doc-content")?.value || "";
  const privacyMode = $("drive-new-doc-privacy-mode")?.value || "standard_plain";
  const msg = $("drive-new-doc-msg");
  try {
    const json = await storageAction("/cloud-drive/files/text", "POST", {
      filename,
      content,
      privacy_mode: privacyMode,
      virtual_path: joinStoragePath(currentStoragePath, filename),
    });
    if ($("drive-new-doc-name")) $("drive-new-doc-name").value = "";
    if ($("drive-new-doc-content")) $("drive-new-doc-content").value = "";
    if (msg) flash(msg, "文檔已建立", true);
    await loadDriveDashboard();
    closeDriveTextDocumentModal({ clear: true });
    const fileId = json.file?.file_id || json.file?.id;
    if (fileId) await previewDriveFile(fileId, { skipRepeatCheck: true });
  } catch (err) {
    if (msg) flash(msg, err.message || "建立文檔失敗", false);
    else alert(err.message || "建立文檔失敗");
  }
}

function renderContextAttachmentRefs(targetId, refs) {
  const list = $(targetId);
  if (!list) return;
  if (!Array.isArray(refs) || !refs.length) {
    list.innerHTML = `<div class="drive-empty">尚無附件</div>`;
    return;
  }
  list.innerHTML = refs.map((ref) => {
    const name = ref.original_filename_plain_for_public || ref.file_id || "download.bin";
    const warn = driveFileNeedsWarning(ref);
    const imagePreview = driveFileIsImage(ref)
      ? `<button class="chat-message-image-preview" type="button" data-drive-action="album-full-preview" data-file-id="${sanitize(ref.file_id)}" data-name="${sanitize(name)}"><img src="${sanitize(drivePreviewContentUrl(ref.file_id))}" alt="${sanitize(name)}" loading="lazy" /></button>`
      : "";
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(name)}</strong>
          <div class="drive-card-sub">${formatDriveBytes(ref.size_bytes || 0)} · ${sanitize(ref.context_type || "-")}#${sanitize(ref.context_id || "-")} · risk=${sanitize(ref.risk_level || "-")} · scan=${sanitize(ref.scan_status || "-")}</div>
          ${imagePreview}
        </div>
        <div class="drive-file-actions">
          <button class="btn" type="button" data-drive-action="preview" data-file-id="${sanitize(ref.file_id)}">預覽</button>
          <button class="btn ${warn ? "btn-danger" : "btn-primary"}" type="button" data-drive-action="download" data-file-id="${sanitize(ref.file_id)}" data-warn="${warn ? "1" : "0"}">下載</button>
          <button class="btn btn-danger" type="button" data-drive-action="delete-context-attachment" data-ref-id="${sanitize(ref.id)}" data-context-type="${sanitize(ref.context_type || "")}" data-context-id="${sanitize(ref.context_id || "")}" data-target-id="${sanitize(targetId)}">移除附件</button>
        </div>
      </div>
    `;
  }).join("");
}

async function deleteContextAttachment(refId, contextType, contextId, targetId) {
  if (!refId) {
    alert("附件編號讀取失敗，請重新整理後再試。");
    return;
  }
  if (!window.confirm("將此附件從目前項目移除？原雲端檔案不會被刪除。")) return;
  await storageAction(`/cloud-drive/refs/${encodeURIComponent(refId)}/delete`, "POST");
  if (contextType === "chat_message" && typeof loadChatMessages === "function" && selectedChatRoomId) {
    await loadChatMessages(selectedChatRoomId, false);
  } else if (contextType && contextId && targetId) {
    await loadContextAttachments(contextType, contextId, targetId);
  }
  await ensureAttachmentFileOptionsLoaded({ force: true });
}

async function loadContextAttachments(contextType, contextId, targetId) {
  if (!contextType || !contextId || !targetId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/cloud-drive/refs?context_type=${encodeURIComponent(contextType)}&context_id=${encodeURIComponent(contextId)}`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    const list = $(targetId);
    if (list) list.innerHTML = `<div class="drive-empty">${sanitize(json.msg || "附件讀取失敗")}</div>`;
    return;
  }
  renderContextAttachmentRefs(targetId, json.refs || []);
}

async function uploadContextAttachment({ fileInputId, contextType, contextId, grantUserIds = [], grantRole = null, refresh }) {
  const input = $(fileInputId);
  if (!input?.files?.[0]) {
    alert("請先選擇附件檔案");
    return;
  }
  if (!contextId) {
    alert("請先選擇對話、聊天室或公告");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", input.files[0]);
  form.append("privacy_mode", "standard_plain");
  form.append("context_type", contextType);
  form.append("context_id", String(contextId));
  grantUserIds.forEach((id) => form.append("grant_user_ids", String(id)));
  if (grantRole) form.append("grant_role", grantRole);
  const res = await apiFetch(API + "/cloud-drive/upload", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    alert(json.error_code ? `${json.msg || "附件上傳失敗"}（${json.error_code}）` : (json.msg || `附件上傳失敗（HTTP ${res.status}）`));
    return;
  }
  input.value = "";
  if (typeof refresh === "function") await refresh();
}

async function attachExistingContextAttachment({ fileId, contextType, contextId, grantUserIds = [], grantRole = null, refresh }) {
  if (!fileId) {
    alert("請先從下拉選單選擇雲端檔案");
    return;
  }
  if (!contextId) {
    alert("請先選擇對話、聊天室或公告");
    return;
  }
  await storageAction("/cloud-drive/attach-existing", "POST", {
    file_id: fileId,
    context_type: contextType,
    context_id: String(contextId),
    grant_user_ids: grantUserIds,
    grant_role: grantRole,
    can_preview: true
  });
  if (typeof refresh === "function") await refresh();
}

async function uploadPendingChatAttachment() {
  const input = $("chat-attachment-file");
  if (!input?.files?.[0]) {
    alert("請先選擇附件檔案");
    return;
  }
  if (!selectedChatRoomId) {
    alert("請先選擇聊天室");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", input.files[0]);
  form.append("privacy_mode", "standard_plain");
  const res = await apiFetch(API + "/cloud-drive/upload", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    alert(json.error_code ? `${json.msg || "附件上傳失敗"}（${json.error_code}）` : (json.msg || `附件上傳失敗（HTTP ${res.status}）`));
    return;
  }
  input.value = "";
  await ensureAttachmentFileOptionsLoaded({ force: true });
  if (typeof addPendingChatAttachment === "function") {
    addPendingChatAttachment(json.file || {});
  }
  setChatMsg("chat-room-warn", "附件已加入待送清單，按送出後會出現在該則訊息下方", true);
}

async function addExistingChatFileToPending(fileId) {
  if (!fileId) {
    await ensureAttachmentFileOptionsLoaded();
    alert("請先從下拉選單選擇雲端檔案");
    return;
  }
  if (!selectedChatRoomId) {
    alert("請先選擇聊天室");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/files/${encodeURIComponent(fileId)}/status`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    alert(json.msg || `檔案讀取失敗（HTTP ${res.status}）`);
    return;
  }
  if (typeof addPendingChatAttachment === "function") {
    addPendingChatAttachment(json.file || { file_id: fileId });
  }
  const input = $("chat-attachment-existing-file-id");
  if (input) input.value = "";
  setChatMsg("chat-room-warn", "既有雲端檔已加入待送清單，按送出後會出現在該則訊息下方", true);
}

async function uploadChatAttachment() {
  await uploadPendingChatAttachment();
}

async function attachExistingChatFile() {
  await ensureAttachmentFileOptionsLoaded();
  await addExistingChatFileToPending($("chat-attachment-existing-file-id")?.value.trim() || "");
}

function currentDmGrantUserIds() {
  const thread = typeof currentDmThread === "function" ? currentDmThread() : null;
  return thread?.other_user_id ? [thread.other_user_id] : [];
}

async function uploadDmAttachment() {
  await uploadContextAttachment({
    fileInputId: "dm-attachment-file",
    contextType: "dm",
    contextId: selectedDmThreadId,
    grantUserIds: currentDmGrantUserIds(),
    refresh: () => loadContextAttachments("dm", selectedDmThreadId, "dm-attachment-list")
  });
  await ensureAttachmentFileOptionsLoaded({ force: true });
}

async function attachExistingDmFile() {
  await ensureAttachmentFileOptionsLoaded();
  await attachExistingContextAttachment({
    fileId: $("dm-attachment-existing-file-id")?.value.trim() || "",
    contextType: "dm",
    contextId: selectedDmThreadId,
    grantUserIds: currentDmGrantUserIds(),
    refresh: () => loadContextAttachments("dm", selectedDmThreadId, "dm-attachment-list")
  });
}

async function createAnnouncementAttachmentRequest(fileId, announcementId, reason) {
  await storageAction("/cloud-drive/announcement-attachment-requests", "POST", {
    file_id: fileId,
    announcement_id: announcementId,
    reason: reason || "announcement attachment"
  });
  alert("公告附件請求已送出，等待 root 核准");
}

async function uploadAnnouncementAttachmentRequest() {
  const announcementId = Number($("announcement-attachment-announcement-id")?.value || 0);
  const input = $("announcement-attachment-file");
  if (!announcementId) {
    alert("請輸入公告 ID");
    return;
  }
  if (!input?.files?.[0]) {
    alert("請先選擇公告附件");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", input.files[0]);
  form.append("privacy_mode", "standard_plain");
  const res = await apiFetch(API + "/cloud-drive/upload", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    alert(json.error_code ? `${json.msg || "公告附件上傳失敗"}（${json.error_code}）` : (json.msg || `公告附件上傳失敗（HTTP ${res.status}）`));
    return;
  }
  input.value = "";
  await createAnnouncementAttachmentRequest(json.file?.file_id, announcementId, $("announcement-attachment-reason")?.value || "");
  await ensureAttachmentFileOptionsLoaded({ force: true });
}

async function attachExistingAnnouncementFile() {
  const announcementId = Number($("announcement-attachment-announcement-id")?.value || 0);
  await ensureAttachmentFileOptionsLoaded();
  const fileId = $("announcement-attachment-existing-file-id")?.value.trim() || "";
  if (!announcementId) {
    alert("請輸入公告 ID");
    return;
  }
  if (!fileId) {
    alert("請先從下拉選單選擇雲端檔案");
    return;
  }
  await createAnnouncementAttachmentRequest(fileId, announcementId, $("announcement-attachment-reason")?.value || "");
}

function normalizeStoragePath(path, fallbackName = "") {
  const raw = String(path || fallbackName || "").replace(/\\/g, "/").trim();
  const parts = raw.split("/").map((part) => part.trim()).filter(Boolean);
  return parts.length ? `/${parts.join("/")}` : "/";
}

function storageBaseName(path) {
  const normalized = normalizeStoragePath(path);
  if (normalized === "/") return "我的雲端硬碟";
  return normalized.split("/").filter(Boolean).pop() || normalized;
}

function storageDirName(path) {
  const parts = normalizeStoragePath(path).split("/").filter(Boolean);
  parts.pop();
  return parts.length ? `/${parts.join("/")}` : "/";
}

function joinStoragePath(folder, name) {
  const base = normalizeStoragePath(folder);
  const cleanName = String(name || "").replace(/\\/g, "/").split("/").filter(Boolean).join("/");
  if (!cleanName) return base;
  return base === "/" ? `/${cleanName}` : `${base}/${cleanName}`;
}

function storageUploadRelativePath(file) {
  const relative = String(file?.webkitRelativePath || file?.relativePath || file?.name || "").replace(/\\/g, "/");
  return relative.split("/").filter(Boolean).join("/");
}

function storageDepth(path) {
  return normalizeStoragePath(path).split("/").filter(Boolean).length;
}

function renderStorageBreadcrumb() {
  const target = $("storage-breadcrumb");
  if (!target) return;
  const parts = currentStoragePath.split("/").filter(Boolean);
  const crumbs = [`<button type="button" data-drive-action="open-storage-folder" data-path="/">我的雲端硬碟</button>`];
  let walk = "";
  parts.forEach((part) => {
    walk += `/${part}`;
    crumbs.push(`<span>/</span><button type="button" data-drive-action="open-storage-folder" data-path="${sanitize(walk)}">${sanitize(part)}</button>`);
  });
  target.innerHTML = crumbs.join("");
}

function setStorageSelection(id = "", path = "") {
  selectedStorageFileId = id || "";
  selectedStorageFilePath = path || "";
  const label = $("storage-selection-label");
  if (label) label.textContent = selectedStorageFileId ? `已選取：${selectedStorageFilePath || selectedStorageFileId}` : "未選取檔案";
}

function renderStorageBrowser() {
  renderStorageBreadcrumb();
  const list = $("storage-browser-list");
  if (!list) return;
  const rows = [];
  rows.push(...driveTransferRows.map(renderDriveTransferRow));
  if (currentStoragePath !== "/") {
    rows.push(storageParentRow());
  }
  rows.push(...storageFolderRows(storageFoldersCache));
  rows.push(...storageFileRows(storageFilesCache));
  list.innerHTML = rows.length ? rows.join("") : `<div class="drive-empty">這個資料夾沒有檔案或資料夾</div>`;
}

function storageParentRow() {
  return `
    <div class="drive-file-row storage-browser-row storage-browser-folder">
      <div>
        <strong>上一層</strong>
        <div class="drive-card-sub">資料夾 · ${sanitize(storageDirName(currentStoragePath))}</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn" type="button" data-drive-action="open-storage-folder" data-path="${sanitize(storageDirName(currentStoragePath))}">開啟</button>
      </div>
    </div>
  `;
}

function storageFolderRows(folders) {
  return (Array.isArray(folders) ? folders : [])
    .filter((folder) => {
      const path = normalizeStoragePath(folder.virtual_path || folder.display_name || "");
      return path !== "/" && storageDirName(path) === currentStoragePath;
    })
    .map((folder) => {
      const name = storageBaseName(folder.virtual_path || folder.display_name || "folder");
      return `
        <div class="drive-file-row storage-browser-row storage-browser-folder">
          <div>
            <strong>${sanitize(name)}</strong>
            <div class="drive-card-sub">資料夾 · ${folder.is_explicit ? "已建立" : "由檔案路徑產生"} · 直接 ${Number(folder.file_count || 0)} 個 · 含子資料夾 ${Number(folder.recursive_file_count || 0)} 個</div>
          </div>
          <div class="drive-file-actions">
            <button class="btn btn-primary" type="button" data-drive-action="open-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">開啟</button>
            <button class="btn" type="button" data-drive-action="folder-to-album" data-path="${sanitize(folder.virtual_path || "")}" data-name="${sanitize(name)}">設為相簿</button>
            <button class="btn" type="button" data-drive-action="select-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">移動</button>
            <button class="btn btn-danger" type="button" data-drive-action="trash-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">刪除</button>
          </div>
        </div>
      `;
    });
}

function storageFileRows(files) {
  return (Array.isArray(files) ? files : [])
    .filter((file) => storageDirName(file.virtual_path || file.display_name || "") === currentStoragePath)
    .map((file) => {
      const primary = drivePrimaryAction(file);
      const e2ee = driveFileIsE2ee(file);
      const rowAction = ` data-drive-action="preview"`;
      const albumButton = driveFileIsImage(file)
        ? `<button class="btn" type="button" data-drive-action="add-storage-to-album" data-storage-file-id="${sanitize(file.id)}" data-name="${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}">加入相簿</button>`
        : "";
      return `
    <div class="drive-file-row storage-browser-row storage-browser-file"${rowAction} data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}">
      <div>
        <strong>${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}</strong>
        <div class="drive-card-sub">檔案 · ${formatDriveBytes(file.size_bytes || 0)} · ${sanitize(driveFileCategory(file))}${e2ee ? " · 需密碼預覽" : ""} · scan=${sanitize(file.scan_status || "-")} · ${sanitize(file.virtual_path || "-")}</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn" type="button" data-drive-action="${sanitize(primary.action)}" data-file-id="${sanitize(file.file_id)}">${sanitize(primary.label)}</button>
        <button class="btn" type="button" data-drive-action="move-storage-file" data-storage-file-id="${sanitize(file.id)}" data-path="${sanitize(file.virtual_path || "")}">移動</button>
        <button class="btn" type="button" data-drive-action="download-storage" data-storage-file-id="${sanitize(file.id)}">下載</button>
        ${albumButton}
        <button class="btn btn-danger" type="button" data-drive-action="trash-storage" data-storage-file-id="${sanitize(file.id)}">回收</button>
      </div>
    </div>
  `;
    });
}

function updateAlbumTargetSelect(albums) {
  const select = $("album-picker-select");
  if (!select) return;
  const previous = select.value || selectedAlbumId || "";
  const liveAlbums = Array.isArray(albums) ? albums : [];
  select.innerHTML = `<option value="">選擇相簿</option>${liveAlbums.map((album) => `
    <option value="${sanitize(album.id)}">${sanitize(album.title || album.id)}（${albumVisibilityLabel(album.visibility)}）</option>
  `).join("")}`;
  if (previous && liveAlbums.some((album) => album.id === previous)) {
    select.value = previous;
  }
}

function renderStorageTrash(files) {
  const list = $("storage-trash-list");
  if (!list) return;
  if (!Array.isArray(files) || !files.length) {
    list.innerHTML = `<div class="drive-empty">回收筒是空的</div>`;
    return;
  }
  list.innerHTML = files.map((file) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(file.display_name || file.virtual_path || file.id)}</strong>
        <div class="drive-card-sub">${sanitize(file.virtual_path || "-")} · ${formatDriveBytes(file.size_bytes || 0)}</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn" type="button" data-drive-action="restore-storage" data-storage-file-id="${sanitize(file.id)}">還原</button>
        <button class="btn btn-danger" type="button" data-drive-action="purge-storage" data-storage-file-id="${sanitize(file.id)}">永久移除</button>
      </div>
    </div>
  `).join("");
}

function renderAlbums(albums) {
  const list = $("album-list");
  if (!list) return;
  storageAlbumsCache = Array.isArray(albums) ? albums : [];
  updateAlbumTargetSelect(storageAlbumsCache);
  if (!Array.isArray(albums) || !albums.length) {
    list.innerHTML = `<div class="drive-empty">尚無相簿</div>`;
    closeAlbumDetail();
    return;
  }
  list.innerHTML = albums.map((album) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(album.title || album.id)}</strong>
        <div class="drive-card-sub">${sanitize(albumVisibilityLabel(album.visibility))} · ${Number(album.file_count || 0)} 個檔案${album.description ? ` · ${sanitize(album.description)}` : ""}</div>
        ${albumShareLinkMarkup(album)}
      </div>
      <div class="drive-file-actions">
        <button class="btn btn-primary" type="button" data-drive-action="open-album" data-album-id="${sanitize(album.id)}">預覽</button>
        <button class="btn btn-danger" type="button" data-drive-action="delete-album" data-album-id="${sanitize(album.id)}">刪除</button>
      </div>
    </div>
  `).join("");
}

async function loadStorageFiles(csrf) {
  const headers = { "X-CSRF-Token": csrf || "" };
  const [filesRes, trashRes, foldersRes, albumsRes] = await Promise.all([
    apiFetch(API + "/storage/files", { credentials: "same-origin", headers }),
    apiFetch(API + "/storage/trash", { credentials: "same-origin", headers }),
    apiFetch(API + "/storage/folders", { credentials: "same-origin", headers }),
    apiFetch(API + "/storage/albums", { credentials: "same-origin", headers })
  ]);
  const filesJson = await filesRes.json().catch(() => ({}));
  const trashJson = await trashRes.json().catch(() => ({}));
  const foldersJson = await foldersRes.json().catch(() => ({}));
  const albumsJson = await albumsRes.json().catch(() => ({}));
  storageFilesCache = filesJson.ok ? filesJson.files || [] : [];
  storageFoldersCache = foldersJson.ok ? foldersJson.folders || [] : [];
  renderStorageBrowser();
  renderStorageTrash(trashJson.ok ? trashJson.files || [] : []);
  renderAlbums(albumsJson.ok ? albumsJson.albums || [] : []);
  if (selectedAlbumId && (albumsJson.ok ? (albumsJson.albums || []).some((album) => album.id === selectedAlbumId) : false)) {
    await openAlbum(selectedAlbumId, { quiet: true });
  }
}

async function createStorageFolder() {
  const input = $("storage-folder-path");
  const requested = input?.value || window.prompt("新增資料夾名稱", "");
  if (requested === null) return;
  if (!String(requested).trim()) return;
  const path = requested && requested.startsWith("/") ? requested : joinStoragePath(currentStoragePath, requested || "");
  if (!path.trim()) {
    alert("請輸入資料夾路徑");
    return;
  }
  try {
    await storageAction("/storage/folders", "POST", { path });
    if (input) input.value = "";
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "建立資料夾失敗"); }
}

function selectStorageFileForOrganize(id, path) {
  setStorageSelection(id, path);
}

async function organizeSelectedStorageFile() {
  if (!selectedStorageFileId) {
    alert("請先在 Storage 檔案列表選取檔案");
    return;
  }
  const requested = $("storage-organize-path")?.value || window.prompt("移動或重新命名到", selectedStorageFilePath || currentStoragePath);
  if (requested === null) return;
  if (!String(requested).trim()) return;
  const path = requested && requested.startsWith("/") ? requested : joinStoragePath(currentStoragePath, requested || "");
  if (!path.trim()) {
    alert("請輸入新路徑");
    return;
  }
  try {
    await storageAction(`/storage/files/${encodeURIComponent(selectedStorageFileId)}/organize`, "PUT", { virtual_path: path });
    setStorageSelection("", "");
    if ($("storage-organize-path")) $("storage-organize-path").value = "";
    currentStoragePath = storageDirName(path);
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "整理檔案失敗"); }
}

async function moveStorageFileFromRow(id, currentPath) {
  setStorageSelection(id, currentPath);
  const requested = window.prompt("移動或重新命名到", currentPath || currentStoragePath);
  if (requested === null) return;
  if (!String(requested).trim()) return;
  const path = requested && requested.startsWith("/") ? requested : joinStoragePath(currentStoragePath, requested || "");
  if (!path.trim() || path === "/") {
    alert("請輸入包含檔名的新路徑");
    return;
  }
  try {
    await storageAction(`/storage/files/${encodeURIComponent(id)}/organize`, "PUT", { virtual_path: path });
    setStorageSelection("", "");
    currentStoragePath = storageDirName(path);
    await loadDriveDashboard();
  } catch (err) {
    alert(err.message || "移動檔案失敗");
  }
}

function selectStorageFolderForMove(path) {
  const oldPath = normalizeStoragePath(path);
  const requested = window.prompt("移動資料夾到", oldPath);
  if (!requested) return;
  if ($("storage-folder-move-old")) $("storage-folder-move-old").value = oldPath;
  if ($("storage-folder-move-new")) $("storage-folder-move-new").value = requested.startsWith("/") ? requested : joinStoragePath(storageDirName(oldPath), requested);
  moveStorageFolder();
}

async function moveStorageFolder() {
  const oldPath = $("storage-folder-move-old")?.value || "";
  const newPath = $("storage-folder-move-new")?.value || "";
  if (!oldPath.trim() || !newPath.trim()) {
    alert("請輸入原資料夾與新資料夾路徑");
    return;
  }
  try {
    await storageAction("/storage/folders/move", "PUT", { old_path: oldPath, new_path: newPath });
    if ($("storage-folder-move-old")) $("storage-folder-move-old").value = "";
    if ($("storage-folder-move-new")) $("storage-folder-move-new").value = "";
    currentStoragePath = normalizeStoragePath(newPath);
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "移動資料夾失敗"); }
}

async function trashStorageFolder(path) {
  const folderPath = normalizeStoragePath(path);
  if (!window.confirm(`將資料夾「${folderPath}」與其中檔案移到垃圾桶？`)) return;
  try {
    await storageAction("/storage/folders/trash", "POST", { path: folderPath });
    if (currentStoragePath === folderPath || currentStoragePath.startsWith(`${folderPath}/`)) {
      currentStoragePath = storageDirName(folderPath);
    }
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "刪除資料夾失敗"); }
}

async function createAlbumFromFolder(path, name = "") {
  const folderPath = normalizeStoragePath(path);
  const defaultTitle = name || storageBaseName(folderPath) || "資料夾相簿";
  const title = window.prompt("建立相簿名稱", defaultTitle);
  if (title === null) return;
  const cleanTitle = title.trim();
  if (!cleanTitle) {
    alert("相簿名稱不可為空");
    return;
  }
  try {
    const json = await storageAction("/storage/folders/album", "POST", {
      path: folderPath,
      title: cleanTitle,
      visibility: "private"
    });
    storageAlbumsCache = [];
    selectedAlbumId = json.album?.id || selectedAlbumId;
    await loadDriveDashboard();
    alert(`已建立相簿「${json.album?.title || cleanTitle}」，加入 ${Number(json.album?.added_count || json.album?.files?.length || 0)} 個檔案`);
  } catch (err) {
    alert(err.message || "資料夾設為相簿失敗");
  }
}

function openStorageFolder(path) {
  currentStoragePath = normalizeStoragePath(path);
  setStorageSelection("", "");
  renderStorageBrowser();
}

function openStorageUploadPicker() {
  const input = $("storage-upload-file");
  if (input) input.click();
}

function openStorageFolderUploadPicker() {
  const input = $("storage-upload-folder");
  if (input) input.click();
}

async function uploadStorageFile() {
  const input = $("storage-upload-file");
  const pathInput = $("storage-upload-path");
  if (!input || !input.files || !input.files[0]) {
    alert("請先選擇檔案");
    return;
  }
  const file = input.files[0];
  const options = await askDriveUploadPrivacyOptions({ allowE2ee: true, title: `上傳「${file.name}」前選擇隱私模式` });
  if (!options) {
    input.value = "";
    return;
  }
  if ($("drive-upload-privacy-mode")) $("drive-upload-privacy-mode").value = options.privacyMode;
  const transferId = addDriveTransferRow({
    kind: "upload",
    name: file.name,
    loaded_bytes: 0,
    total_bytes: file.size,
    progress_percent: 0,
    msg: "等待上傳",
  });
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  try {
    if (isDriveE2eeMode(options.privacyMode)) {
      updateDriveTransferRow(transferId, { phase: "encrypting", msg: "瀏覽器端加密中", progress_percent: null });
      const encrypted = await prepareDriveE2eeUpload(file, options.passphrase, options.includeClientScanReport);
      form.append("file", encrypted.blob, encrypted.filename);
      form.append("encrypted_metadata", encrypted.encrypted_metadata);
      form.append("encrypted_file_key", encrypted.encrypted_file_key);
      form.append("wrapped_by", encrypted.wrapped_by);
      form.append("ciphertext_sha256", encrypted.ciphertext_sha256);
      form.append("encryption_algorithm", encrypted.encryption_algorithm);
      form.append("encryption_version", encrypted.encryption_version);
      form.append("nonce", encrypted.nonce);
      if (encrypted.client_scan_report) form.append("client_scan_report", JSON.stringify(encrypted.client_scan_report));
    } else {
      form.append("file", file);
    }
    form.append("privacy_mode", options.privacyMode);
    form.append("virtual_path", pathInput?.value || joinStoragePath(currentStoragePath, file.name));
    const { status, json } = await xhrUploadWithProgress(API + "/storage/files", form, csrf, (event) => {
      if (event.lengthComputable) {
        updateDriveTransferRow(transferId, {
          loaded_bytes: event.loaded,
          total_bytes: event.total,
          progress_percent: (event.loaded / event.total) * 100,
          msg: event.loaded >= event.total ? "伺服器儲存與掃描中" : "上傳中",
        });
      } else {
        updateDriveTransferRow(transferId, {
          loaded_bytes: event.loaded || 0,
          total_bytes: null,
          progress_percent: null,
          msg: "上傳中",
        });
      }
    });
    if (status < 200 || status >= 300 || !json.ok) {
      const detail = json.msg || `Storage 上傳失敗（HTTP ${status}）`;
      updateDriveTransferRow(transferId, { status: "failed", phase: "failed", msg: detail, progress_percent: 100 });
      alert(detail);
      return;
    }
    updateDriveTransferRow(transferId, { status: "completed", phase: "completed", msg: "上傳完成", progress_percent: 100, loaded_bytes: file.size, total_bytes: file.size });
    input.value = "";
    if (pathInput) pathInput.value = "";
    await loadDriveDashboard();
    setTimeout(() => removeDriveTransferRow(transferId), DRIVE_TRANSFER_COMPLETED_VISIBLE_MS);
  } catch (err) {
    const detail = err.message || "Storage 上傳失敗";
    updateDriveTransferRow(transferId, { status: "failed", phase: "failed", msg: detail, progress_percent: 100 });
    alert(detail);
  }
}

async function uploadStorageFolder() {
  const input = $("storage-upload-folder");
  const files = Array.from(input?.files || []).filter((file) => file && file.name);
  if (!input || !files.length) {
    alert("請先選擇資料夾");
    return;
  }
  const options = await askDriveUploadPrivacyOptions({ allowE2ee: true, title: `上傳資料夾（${files.length} 個檔案）前選擇隱私模式` });
  if (!options) {
    input.value = "";
    return;
  }
  if ($("drive-upload-privacy-mode")) $("drive-upload-privacy-mode").value = options.privacyMode;
  const totalBytes = files.reduce((sum, file) => sum + Number(file.size || 0), 0);
  const transferId = addDriveTransferRow({
    kind: "upload",
    name: `${storageBaseName(storageUploadRelativePath(files[0]).split("/")[0] || "資料夾")}（${files.length} 個檔案）`,
    loaded_bytes: 0,
    total_bytes: totalBytes,
    progress_percent: 0,
    msg: "資料夾上傳準備中",
  });
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  let uploadedBytes = 0;
  let okCount = 0;
  const failures = [];
  for (const file of files) {
    const relativePath = storageUploadRelativePath(file);
    const virtualPath = joinStoragePath(currentStoragePath, relativePath || file.name);
    const fileSize = Number(file.size || 0);
    updateDriveTransferRow(transferId, {
      loaded_bytes: uploadedBytes,
      total_bytes: totalBytes,
      progress_percent: totalBytes > 0 ? (uploadedBytes / totalBytes) * 100 : null,
      msg: `上傳中：${relativePath || file.name}`,
    });
    const form = new FormData();
    try {
      if (isDriveE2eeMode(options.privacyMode)) {
        const encrypted = await prepareDriveE2eeUpload(file, options.passphrase, options.includeClientScanReport);
        form.append("file", encrypted.blob, encrypted.filename);
        form.append("encrypted_metadata", encrypted.encrypted_metadata);
        form.append("encrypted_file_key", encrypted.encrypted_file_key);
        form.append("wrapped_by", encrypted.wrapped_by);
        form.append("ciphertext_sha256", encrypted.ciphertext_sha256);
        form.append("encryption_algorithm", encrypted.encryption_algorithm);
        form.append("encryption_version", encrypted.encryption_version);
        form.append("nonce", encrypted.nonce);
        if (encrypted.client_scan_report) form.append("client_scan_report", JSON.stringify(encrypted.client_scan_report));
      } else {
        form.append("file", file);
      }
    } catch (err) {
      failures.push(`${relativePath || file.name}: ${err.message || "加密失敗"}`);
      uploadedBytes += Number(file.size || 0);
      continue;
    }
    form.append("privacy_mode", options.privacyMode);
    form.append("virtual_path", virtualPath);
    try {
      const { status, json } = await xhrUploadWithProgress(API + "/storage/files", form, csrf, (event) => {
        const currentLoaded = event.lengthComputable ? Math.min(fileSize, event.loaded || 0) : 0;
        const aggregateLoaded = uploadedBytes + currentLoaded;
        updateDriveTransferRow(transferId, {
          loaded_bytes: aggregateLoaded,
          total_bytes: totalBytes,
          progress_percent: totalBytes > 0 ? (aggregateLoaded / totalBytes) * 100 : null,
          msg: event.lengthComputable
            ? `上傳中：${relativePath || file.name}`
            : `上傳中：${relativePath || file.name}（等待瀏覽器回報大小）`,
        });
      });
      if (status < 200 || status >= 300 || !json.ok) {
        failures.push(`${relativePath || file.name}: ${json.msg || `HTTP ${status}`}`);
      } else {
        okCount += 1;
      }
    } catch (err) {
      failures.push(`${relativePath || file.name}: ${err.message || "上傳失敗"}`);
    }
    uploadedBytes += Number(file.size || 0);
  }
  updateDriveTransferRow(transferId, {
    status: failures.length ? "failed" : "completed",
    phase: failures.length ? "failed" : "completed",
    loaded_bytes: uploadedBytes,
    total_bytes: totalBytes,
    progress_percent: 100,
    msg: failures.length ? `完成 ${okCount}/${files.length}，失敗 ${failures.length}` : `已上傳 ${okCount} 個檔案`,
  });
  input.value = "";
  await loadDriveDashboard();
  if (failures.length) {
    alert(`資料夾上傳完成，但有 ${failures.length} 個檔案失敗：\n${failures.slice(0, 5).join("\n")}${failures.length > 5 ? "\n..." : ""}`);
  } else {
    setTimeout(() => removeDriveTransferRow(transferId), DRIVE_TRANSFER_COMPLETED_VISIBLE_MS);
  }
}

async function storageAction(path, method = "POST", body = null) {
  const csrf = await fetchCsrfToken({ force: true });
  const headers = { "X-CSRF-Token": csrf || "" };
  if (body) headers["Content-Type"] = "application/json";
  const options = {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: body ? JSON.stringify(body) : undefined
  };
  let res;
  try {
    res = await apiFetch(API + path, options);
  } catch (err) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    try {
      res = await apiFetch(API + path, options);
    } catch (retryErr) {
      throw new Error(`連線失敗：${retryErr.message || err.message || "無法連到 API"}`);
    }
  }
  const text = await res.text().catch(() => "");
  let json = {};
  try {
    json = text ? JSON.parse(text) : {};
  } catch (err) {
    json = {};
  }
  if (!res.ok || !json.ok) {
    const fallback = res.ok ? "操作失敗" : `操作失敗（HTTP ${res.status}）`;
    throw new Error(json.msg || fallback);
  }
  return json;
}

async function trashStorageFile(id) {
  try {
    await storageAction(`/storage/files/${encodeURIComponent(id)}`, "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
}

async function restoreStorageFile(id) {
  try {
    await storageAction(`/storage/files/${encodeURIComponent(id)}/restore`, "POST");
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
}

async function purgeStorageFile(id) {
  if (!window.confirm("永久移除此垃圾桶項目？由「資料夾與檔案」移入垃圾桶的檔案會永久失效。")) return;
  try {
    await storageAction(`/storage/files/${encodeURIComponent(id)}/purge`, "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
}

async function restoreStorageTrash() {
  try {
    await storageAction("/storage/trash/restore", "POST");
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "還原垃圾桶失敗"); }
}

async function purgeStorageTrash() {
  if (!window.confirm("清空垃圾桶？由「資料夾與檔案」移入垃圾桶的檔案會永久失效。")) return;
  try {
    await storageAction("/storage/trash/purge", "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "清空垃圾桶失敗"); }
}

async function downloadStorageFile(id) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await apiFetch(API + `/storage/files/${encodeURIComponent(id)}/download`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    alert(json.msg || "下載失敗");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "download.bin";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function ensureAlbumChoicesLoaded() {
  if (storageAlbumsCache.length) return storageAlbumsCache;
  const json = await storageAction("/storage/albums", "GET");
  storageAlbumsCache = Array.isArray(json.albums) ? json.albums : [];
  updateAlbumTargetSelect(storageAlbumsCache);
  return storageAlbumsCache;
}

function closeAlbumPicker(value = "") {
  const overlay = $("album-picker-overlay");
  if (overlay) overlay.classList.remove("show");
  if (pendingAlbumPickerResolve) {
    pendingAlbumPickerResolve(value);
    pendingAlbumPickerResolve = null;
  }
}

async function chooseAlbumForFile(fileLabel = "") {
  const albums = await ensureAlbumChoicesLoaded();
  if (!albums.length) {
    alert("目前沒有相簿，請先到相簿分頁建立相簿");
    return "";
  }
  updateAlbumTargetSelect(albums);
  const label = $("album-picker-file-label");
  if (label) label.textContent = fileLabel ? `將「${fileLabel}」加入` : "選擇要加入的相簿";
  const msg = $("album-picker-msg");
  if (msg) msg.textContent = "";
  const select = $("album-picker-select");
  if (select) select.value = selectedAlbumId && albums.some((album) => album.id === selectedAlbumId) ? selectedAlbumId : albums[0].id;
  const overlay = $("album-picker-overlay");
  if (overlay) overlay.classList.add("show");
  return new Promise((resolve) => {
    pendingAlbumPickerResolve = resolve;
  });
}

async function createAlbum() {
  const title = $("album-create-title")?.value || "";
  const description = $("album-create-description")?.value || "";
  const visibility = $("album-create-visibility")?.value || "private";
  const sharePassword = $("album-create-share-password")?.value || "";
  if (!title.trim()) {
    alert("請輸入相簿名稱");
    return;
  }
  try {
    const payload = { title, description, visibility };
    if (sharePassword) payload.share_password = sharePassword;
    const json = await storageAction("/storage/albums", "POST", payload);
    $("album-create-title").value = "";
    if ($("album-create-description")) $("album-create-description").value = "";
    if ($("album-create-share-password")) $("album-create-share-password").value = "";
    selectedAlbumId = json.album?.id || "";
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message); }
}

async function smartOrganizeAlbums() {
  const strategy = $("album-smart-strategy")?.value || "folder";
  const msg = $("album-smart-organize-msg") || $("album-gallery-msg");
  const button = document.querySelector("[data-drive-action='smart-organize-albums']");
  if (button) button.disabled = true;
  if (msg) flash(msg, "正在整理相簿...", true);
  try {
    const json = await storageAction("/storage/albums/smart-organize", "POST", {
      strategy,
      visibility: "private"
    });
    const result = json.result || {};
    const text = Number(result.media_count || 0)
      ? `智慧整理完成：掃描 ${Number(result.media_count || 0)} 個媒體檔，建立 ${Number(result.created_count || 0)} 本、更新 ${Number(result.updated_count || 0)} 本，新增 ${Number(result.added_count || 0)} 個相簿項目。`
      : "沒有找到可整理的圖片或影片。";
    if (msg) flash(msg, text, true);
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) {
    if (msg) flash(msg, err.message || "智慧整理失敗", false);
  } finally {
    if (button) button.disabled = false;
  }
}

async function deleteAlbum(id) {
  if (!window.confirm("刪除此相簿？不會刪除原始檔案。")) return;
  try {
    await storageAction(`/storage/albums/${encodeURIComponent(id)}`, "DELETE");
    if (selectedAlbumId === id) closeAlbumDetail();
    if (selectedAlbumViewerId === id) closeAlbumViewer();
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message); }
}

async function addCloudFileToAlbum(fileId, fileLabel = "") {
  const albumId = await chooseAlbumForFile(fileLabel);
  if (!albumId) {
    return;
  }
  try {
    await storageAction(`/storage/albums/${encodeURIComponent(albumId)}/files`, "POST", { file_id: fileId });
    selectedAlbumId = albumId;
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message); }
}

async function addStorageFileToAlbum(storageFileId, fileLabel = "") {
  const albumId = await chooseAlbumForFile(fileLabel);
  if (!albumId) {
    return;
  }
  try {
    await storageAction(`/storage/albums/${encodeURIComponent(albumId)}/files`, "POST", { storage_file_id: storageFileId });
    selectedAlbumId = albumId;
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message); }
}

function albumFileDisplayName(file) {
  return file.display_name || file.original_filename_plain_for_public || file.virtual_path || file.file_id || "image";
}

function absoluteAlbumShareUrl(url) {
  if (!url) return "";
  try {
    return new URL(url, window.location.origin).toString();
  } catch (err) {
    return String(url || "");
  }
}

function albumShareLinkMarkup(album) {
  const url = album?.share_url || album?.share_link?.url || "";
  const visibility = album?.visibility || "";
  if (!url) {
    if (visibility === "unlisted") {
      return `<div class="drive-card-sub drive-share-link">分享連結建立中，請儲存或刷新相簿後再複製。</div>`;
    }
    return "";
  }
  const absolute = absoluteAlbumShareUrl(url);
  const passwordNote = album?.share_link?.password_required
    ? `<span class="drive-share-password-note">已設定分享密碼，請另外告知對方密碼。</span>`
    : "";
  return `
    <div class="drive-card-sub drive-share-link">
      <span>持連結可看：<a href="${sanitize(url)}" target="_blank" rel="noreferrer">${sanitize(absolute)}</a></span>
      <button class="btn btn-sm" type="button" data-drive-action="copy-album-share-link" data-share-url="${sanitize(absolute)}">複製</button>
      ${passwordNote}
    </div>
  `;
}

async function copyAlbumShareUrl(url) {
  const shareUrl = absoluteAlbumShareUrl(url);
  if (!shareUrl) {
    alert("這本相簿尚未產生分享連結");
    return;
  }
  try {
    await navigator.clipboard.writeText(shareUrl);
    alert("已複製分享連結");
  } catch (err) {
    window.prompt("分享連結", shareUrl);
  }
}

function renderAlbumDetail(album) {
  const card = $("album-detail-card");
  if (!card) return;
  selectedAlbumId = album.id || "";
  card.style.display = "block";
  const title = $("album-detail-title");
  const meta = $("album-detail-meta");
  if (title) title.textContent = album.title || "相簿內容";
  if (meta) {
    meta.innerHTML = `${sanitize(albumVisibilityLabel(album.visibility))} · ${Number((album.files || []).length)} 個檔案 · ${sanitize(album.updated_at || album.created_at || "")}${albumShareLinkMarkup(album)}`;
  }
  if ($("album-edit-title")) $("album-edit-title").value = album.title || "";
  if ($("album-edit-description")) $("album-edit-description").value = album.description || "";
  if ($("album-edit-visibility")) $("album-edit-visibility").value = album.visibility || "private";
  if ($("album-edit-share-password")) $("album-edit-share-password").value = "";
  if ($("album-edit-clear-share-password")) $("album-edit-clear-share-password").checked = false;
  const passwordState = $("album-edit-share-password-state");
  if (passwordState) {
    passwordState.textContent = album?.share_link?.password_required
      ? "目前已設定分享密碼。留空不變，輸入新密碼可更新。"
      : "目前未設定分享密碼。";
  }
}

async function openAlbum(id, options = {}) {
  if (!id) return;
  try {
    await openAlbumViewer(id, options);
  } catch (err) {
    if (!options.quiet) alert(err.message || "相簿讀取失敗");
  }
}

function closeAlbumDetail() {
  selectedAlbumId = "";
  const card = $("album-detail-card");
  if (card) card.style.display = "none";
}

async function saveAlbumDetail() {
  if (!selectedAlbumId) return;
  try {
    const payload = {
      title: $("album-edit-title")?.value || "",
      description: $("album-edit-description")?.value || "",
      visibility: $("album-edit-visibility")?.value || "private",
    };
    const sharePassword = $("album-edit-share-password")?.value || "";
    if (sharePassword) payload.share_password = sharePassword;
    if ($("album-edit-clear-share-password")?.checked) payload.clear_share_password = true;
    const json = await storageAction(`/storage/albums/${encodeURIComponent(selectedAlbumId)}`, "PUT", payload);
    renderAlbumDetail(json.album || {});
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message || "相簿儲存失敗"); }
}

async function removeAlbumFile(albumId, albumFileId) {
  try {
    const json = await storageAction(`/storage/albums/${encodeURIComponent(albumId)}/files/${encodeURIComponent(albumFileId)}`, "DELETE");
    renderAlbumDetail(json.album || {});
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "移出相簿失敗"); }
}

function renderAlbumGallery(albums) {
  const list = $("album-gallery-list");
  if (!list) return;
  if (!Array.isArray(albums) || !albums.length) {
    list.innerHTML = `<div class="drive-empty">尚無相簿</div>`;
    return;
  }
  list.innerHTML = albums.map((album) => `
    <div class="drive-gallery-tile">
      <div>
        <strong>${sanitize(album.title || album.id)}</strong>
        <div class="drive-card-sub">${sanitize(albumVisibilityLabel(album.visibility))} · ${Number(album.file_count || 0)} 個檔案</div>
        ${albumShareLinkMarkup(album)}
      </div>
      <button class="btn btn-primary" type="button" data-drive-action="open-album-viewer" data-album-id="${sanitize(album.id)}">預覽</button>
    </div>
  `).join("");
}

async function loadAlbumGallery() {
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  const msg = $("album-gallery-msg");
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/storage/albums", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "相簿讀取失敗");
    const albums = json.albums || [];
    storageAlbumsCache = Array.isArray(albums) ? albums : [];
    updateAlbumTargetSelect(storageAlbumsCache);
    renderAlbums(storageAlbumsCache);
    renderAlbumGallery(storageAlbumsCache);
    const activeAlbum = storageAlbumsCache.find((album) => album.id === selectedAlbumViewerId) || storageAlbumsCache[0];
    if (activeAlbum) {
      await openAlbumViewer(activeAlbum.id, { quiet: true });
    } else {
      closeAlbumViewer();
    }
    if (msg) msg.className = "msg";
  } catch (err) {
    if (msg) flash(msg, err.message || "相簿讀取失敗", false);
  }
}

function closeAlbumViewer() {
  selectedAlbumViewerId = "";
  albumPreviewSequence = [];
  albumPreviewIndex = -1;
  clearAlbumThumbObjectUrls();
  const card = $("album-viewer-card");
  if (card) {
    card.open = false;
    card.style.display = "none";
  }
}

function renderAlbumPreviewTile(file) {
  const name = albumFileDisplayName(file);
  const category = driveFileCategory(file);
  const thumbKey = file.id || file.file_id;
  const canTryPreview = category === "image" || category === "metadata";
  const thumb = canTryPreview
    ? `<button class="drive-gallery-thumb drive-gallery-thumb-button" type="button" data-drive-action="album-full-preview" data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(name)}" data-album-sequence="viewer" data-album-thumb-key="${sanitize(thumbKey)}"><span>讀取預覽</span></button>`
    : `<div class="drive-gallery-thumb drive-gallery-thumb-placeholder"><span>${sanitize(category)}</span></div>`;
  return `
    <div class="drive-gallery-tile">
      ${thumb}
      <div class="drive-gallery-file-info">
        <strong>${sanitize(name)}</strong>
        <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · <span data-album-category-key="${sanitize(thumbKey)}">${sanitize(category)}</span> · scan=${sanitize(file.scan_status || "-")}</div>
      </div>
      <div class="drive-file-actions" style="justify-content:flex-start;">
        <button class="btn" type="button" data-drive-action="album-full-preview" data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(name)}" data-album-sequence="viewer">預覽</button>
        ${file.storage_file_id ? `<button class="btn" type="button" data-drive-action="download-storage" data-storage-file-id="${sanitize(file.storage_file_id)}">下載</button>` : `<button class="btn" type="button" data-drive-action="download" data-file-id="${sanitize(file.file_id)}" data-warn="0">下載</button>`}
      </div>
    </div>
  `;
}

async function hydrateAlbumViewerThumbnails(files) {
  clearAlbumThumbObjectUrls();
  const previewCandidates = (Array.isArray(files) ? files : []).filter((file) => ["image", "metadata"].includes(driveFileCategory(file)));
  if (!previewCandidates.length) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  for (const file of previewCandidates) {
    const thumbKey = file.id || file.file_id;
    const holder = Array.from(document.querySelectorAll("[data-album-thumb-key]")).find((node) => node.dataset.albumThumbKey === String(thumbKey));
    if (!holder) continue;
    try {
      let blob = await fetchDrivePreviewBlob(file.file_id, csrf);
      if (!String(blob.type || "").toLowerCase().startsWith("image/")) throw new Error("不是圖片預覽");
      const url = URL.createObjectURL(blob);
      albumThumbObjectUrls.push(url);
      holder.innerHTML = `<img src="${url}" alt="${sanitize(albumFileDisplayName(file))}" loading="lazy" />`;
      const categoryLabel = Array.from(document.querySelectorAll("[data-album-category-key]")).find((node) => node.dataset.albumCategoryKey === String(thumbKey));
      if (categoryLabel) categoryLabel.textContent = "image";
    } catch (err) {
      try {
        const remembered = getRememberedDriveE2eeSessionPassphrase(file.file_id);
        if (!remembered) throw err;
        const decrypted = await buildDriveE2eePreview(file.file_id, csrf);
        if (!decrypted || decrypted.preview.category !== "image") throw err;
        const url = URL.createObjectURL(decrypted.blob);
        albumThumbObjectUrls.push(url);
        holder.innerHTML = `<img src="${url}" alt="${sanitize(decrypted.preview.filename || albumFileDisplayName(file))}" loading="lazy" />`;
        const categoryLabel = Array.from(document.querySelectorAll("[data-album-category-key]")).find((node) => node.dataset.albumCategoryKey === String(thumbKey));
        if (categoryLabel) categoryLabel.textContent = "image · E2EE";
      } catch (_) {
        holder.innerHTML = `<span>無法預覽</span>`;
      }
    }
  }
}

async function openAlbumViewer(id, options = {}) {
  if (!id) return;
  selectedAlbumViewerId = id;
  const card = $("album-viewer-card");
  const title = $("album-viewer-title");
  const meta = $("album-viewer-meta");
  const filesEl = $("album-viewer-files");
  if (card) {
    card.style.display = "block";
    card.open = Boolean(options.openContent);
  }
  if (filesEl) filesEl.innerHTML = `<div class="drive-empty">讀取相簿中...</div>`;
  try {
    const json = await storageAction(`/storage/albums/${encodeURIComponent(id)}`, "GET");
    const album = json.album || {};
    const files = Array.isArray(album.files) ? album.files : [];
    albumPreviewSequence = files.filter((file) => file?.file_id && (typeof driveFileIsImage !== "function" || driveFileIsImage(file)));
    albumPreviewIndex = -1;
    if (title) title.textContent = album.title || "相簿";
    if (meta) {
      meta.innerHTML = `${sanitize(albumVisibilityLabel(album.visibility))} · ${files.length} 個檔案${album.description ? ` · ${sanitize(album.description)}` : ""}${albumShareLinkMarkup(album)}`;
    }
    if (!filesEl) return;
    setAlbumThumbSize(getAlbumThumbSize());
    filesEl.innerHTML = files.length ? files.map(renderAlbumPreviewTile).join("") : `<div class="drive-empty">這本相簿還沒有檔案</div>`;
    hydrateAlbumViewerThumbnails(files).catch(() => {});
  } catch (err) {
    if (filesEl) filesEl.innerHTML = `<div class="drive-empty">${sanitize(err.message || "相簿讀取失敗")}</div>`;
  }
}

async function loadDriveDashboard() {
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  updateDriveE2eePassphraseVisibility();
  const msg = $("drive-msg");
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await apiFetch(API + "/files/security-policy", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      if (msg) flash(msg, json.msg || "雲端硬碟狀態讀取失敗", false);
      return;
    }
    renderDriveDashboard(json);
    await loadStorageUpgradeOptions();
    await loadRemoteDownloadCapabilities();
    await restoreRemoteDownloadTasks();
    await loadDriveFiles(csrf);
    await loadStorageFiles(csrf);
    if (msg) msg.className = "msg";
  } catch (err) {
    if (msg) flash(msg, "雲端硬碟狀態讀取失敗", false);
  }
}

async function loadStorageUpgradeOptions() {
  const card = $("drive-storage-upgrade-card");
  if (!card) return;
  const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
  const res = await apiFetch(API + "/cloud-drive/storage-upgrades", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    renderStorageUpgrade({
      ok: false,
      can_purchase: false,
      message: json.msg || `容量方案讀取失敗（HTTP ${res.status}）`,
      catalog: [],
      active_purchases: [],
    });
    return;
  }
  renderStorageUpgrade(json);
}

function openStorageUpgradePanel() {
  const overlay = $("drive-storage-upgrade-overlay");
  if (!overlay) return;
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  loadStorageUpgradeOptions().catch(() => {});
}

function closeStorageUpgradePanel() {
  const overlay = $("drive-storage-upgrade-overlay");
  if (!overlay) return;
  overlay.classList.remove("show");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

async function purchaseStorageUpgrade() {
  const msg = $("drive-msg");
  if (!driveStorageUpgradeCanPurchase) {
    if (msg) flash(msg, driveStorageUpgradeMessage || "目前沒有可購買的容量方案", false);
    return;
  }
  if (currentUser === "root") {
    if (msg) flash(msg, "root 依實際磁碟容量控管，不需要購買容量方案", false);
    return;
  }
  const itemKey = $("drive-storage-upgrade-select")?.value || "";
  if (!itemKey) {
    if (msg) flash(msg, "請先選擇容量方案", false);
    return;
  }
  const button = document.querySelector("[data-drive-action='purchase-storage-upgrade']");
  if (button) button.disabled = true;
  if (msg) flash(msg, "正在購買容量...", true);
  try {
    const csrf = getCsrfToken() || await fetchCsrfToken({ force: true });
    const res = await apiFetch(API + "/cloud-drive/storage-upgrades/purchase", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf || "" },
      body: JSON.stringify({ item_key: itemKey }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) {
      if (msg) flash(msg, json.msg || `容量購買失敗（HTTP ${res.status}）`, false);
      return;
    }
    if (msg) flash(msg, "容量已加購，積分已扣除", true);
    renderDriveDashboard({ quota: json.usage });
    await loadStorageUpgradeOptions();
    if (typeof loadEconomyDashboard === "function") {
      loadEconomyDashboard().catch(() => {});
    }
  } catch (err) {
    if (msg) flash(msg, err.message || "容量購買失敗", false);
  } finally {
    if (button) button.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  if (event.target?.id === "drive-storage-upgrade-overlay") {
    closeStorageUpgradePanel();
    return;
  }
  const pickerConfirm = event.target?.closest?.("#album-picker-confirm");
  if (pickerConfirm) {
    event.preventDefault();
    const albumId = $("album-picker-select")?.value || "";
    if (!albumId) {
      const msg = $("album-picker-msg");
      if (msg) flash(msg, "請選擇相簿", false);
      return;
    }
    closeAlbumPicker(albumId);
    return;
  }
  const pickerCancel = event.target?.closest?.("#album-picker-cancel");
  if (pickerCancel) {
    event.preventDefault();
    closeAlbumPicker("");
    return;
  }
  const button = event.target?.closest?.("[data-drive-action]");
  if (!button) return;
  event.preventDefault();
  const action = button.dataset.driveAction;
  const fileId = button.dataset.fileId || "";
  const storageFileId = button.dataset.storageFileId || "";
  const albumId = button.dataset.albumId || "";
  const albumFileId = button.dataset.albumFileId || "";
  const refId = button.dataset.refId || "";
  const contextType = button.dataset.contextType || "";
  const contextId = button.dataset.contextId || "";
  const targetId = button.dataset.targetId || "";
  const path = button.dataset.path || "";
  const name = button.dataset.name || "";
  const shareUrl = button.dataset.shareUrl || "";
  const transferId = button.dataset.transferId || "";
  const taskId = button.dataset.taskId || "";
  const warn = button.dataset.warn === "1";
  const albumSequence = button.dataset.albumSequence || "";
  (async () => {
    if (action === "preview") return previewDriveFile(fileId, { fileName: name });
    if (action === "dismiss-transfer") return dismissRemoteDownloadTask(taskId, transferId);
    if (action === "album-full-preview") return previewAlbumFileFullscreen(fileId, name, albumSequence === "viewer" ? { files: albumPreviewSequence } : {});
    if (action === "album-preview-prev") return stepAlbumPreview(-1);
    if (action === "album-preview-next") return stepAlbumPreview(1);
    if (action === "open-storage-upgrade") return openStorageUpgradePanel();
    if (action === "close-storage-upgrade") return closeStorageUpgradePanel();
    if (action === "purchase-storage-upgrade") return purchaseStorageUpgrade();
    if (action === "open-text-document-modal") return openDriveTextDocumentModal();
    if (action === "close-text-document-modal") return closeDriveTextDocumentModal();
    if (action === "create-text-document") return createDriveTextDocument();
    if (action === "edit-text") return editDriveTextFile(fileId);
    if (action === "save-text") return saveDriveTextFile(fileId);
    if (action === "download") return downloadDriveFile(fileId, warn);
    if (action === "move-cloud-to-storage") return moveCloudFileToStorage(fileId, name);
    if (action === "add-cloud-to-album") return addCloudFileToAlbum(fileId, name);
    if (action === "delete-cloud") return deleteDriveFile(fileId);
    if (action === "delete-context-attachment") return deleteContextAttachment(refId, contextType, contextId, targetId);
    if (action === "close-preview") return closeDrivePreview();
    if (action === "close-album-full-preview") return closeAlbumFullPreview();
    if (action === "download-storage") return downloadStorageFile(storageFileId);
    if (action === "select-storage-file") return selectStorageFileForOrganize(storageFileId, path);
    if (action === "move-storage-file") return moveStorageFileFromRow(storageFileId, path);
    if (action === "open-storage-folder") return openStorageFolder(path);
    if (action === "add-storage-to-album") return addStorageFileToAlbum(storageFileId, name);
    if (action === "trash-storage") return trashStorageFile(storageFileId);
    if (action === "restore-storage") return restoreStorageFile(storageFileId);
    if (action === "purge-storage") return purgeStorageFile(storageFileId);
    if (action === "trash-storage-folder") return trashStorageFolder(path);
    if (action === "folder-to-album") return createAlbumFromFolder(path, name);
    if (action === "restore-storage-trash") return restoreStorageTrash();
    if (action === "purge-storage-trash") return purgeStorageTrash();
    if (action === "select-storage-folder") return selectStorageFolderForMove(path);
    if (action === "open-album") return openAlbum(albumId);
    if (action === "copy-album-share-link") return copyAlbumShareUrl(shareUrl);
    if (action === "delete-album") return deleteAlbum(albumId);
    if (action === "close-album-detail") return closeAlbumDetail();
    if (action === "save-album-detail") return saveAlbumDetail();
    if (action === "remove-album-file") return removeAlbumFile(albumId, albumFileId);
    if (action === "open-album-viewer") return openAlbumViewer(albumId);
    if (action === "close-album-viewer") return closeAlbumViewer();
    if (action === "refresh-albums") return loadAlbumGallery();
    if (action === "smart-organize-albums") return smartOrganizeAlbums();
  })().catch((err) => alert(err.message || "操作失敗"));
});

document.addEventListener("focusin", (event) => {
  if (event.target?.matches?.(ATTACHMENT_FILE_SELECT_IDS.map((id) => `#${id}`).join(","))) {
    ensureAttachmentFileOptionsLoaded().catch(() => {});
  }
});

document.addEventListener("change", (event) => {
  if (event.target?.id === "drive-upload-privacy-mode") {
    updateDriveE2eePassphraseVisibility();
  }
});

document.addEventListener("keydown", (event) => {
  const overlayOpen = $("album-full-preview-overlay")?.classList.contains("show");
  const docOverlayOpen = $("drive-new-doc-overlay")?.classList.contains("show");
  const e2eePromptOpen = $("drive-e2ee-passphrase-overlay")?.classList.contains("show");
  const uploadModeOpen = $("drive-upload-mode-overlay")?.classList.contains("show");
  const storageUpgradeOpen = $("drive-storage-upgrade-overlay")?.classList.contains("show");
  if (event.key === "Escape" && overlayOpen) {
    closeAlbumFullPreview();
  } else if (event.key === "Escape" && docOverlayOpen) {
    closeDriveTextDocumentModal();
  } else if (event.key === "Escape" && storageUpgradeOpen) {
    closeStorageUpgradePanel();
  } else if (event.key === "Escape" && uploadModeOpen) {
    $("drive-upload-mode-cancel-btn")?.click?.();
  } else if (event.key === "Escape" && e2eePromptOpen) {
    $("drive-e2ee-passphrase-cancel-btn")?.click?.();
  } else if (overlayOpen && event.key === "ArrowLeft") {
    event.preventDefault();
    stepAlbumPreview(-1);
  } else if (overlayOpen && event.key === "ArrowRight") {
    event.preventDefault();
    stepAlbumPreview(1);
  }
});
