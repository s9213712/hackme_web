function formatDriveBytes(bytes) {
  if (bytes === null || bytes === undefined) return "無上限";
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const DRIVE_PRIVACY_MODE_LABELS = {
  private_scannable: "私密檔案",
  public_attachment: "公開附件",
  e2ee_vault: "端到端加密",
  e2ee_vault_with_client_scan: "端到端加密 + 本機掃描",
};

const DRIVE_PRIVACY_MODE_DESCRIPTIONS = {
  private_scannable: "伺服器可掃毒，適合一般個人檔案",
  public_attachment: "可預覽、可分享，不適合機密資料",
  e2ee_vault: "站方無法讀取，掃毒能力受限",
  e2ee_vault_with_client_scan: "站方無法讀取，附本機掃描回報",
};

let driveTransferRows = [];

function drivePrivacyModeLabel(mode) {
  return DRIVE_PRIVACY_MODE_LABELS[mode] || mode || "-";
}

function drivePrivacyModeDescription(mode) {
  return DRIVE_PRIVACY_MODE_DESCRIPTIONS[mode] || "";
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
    const diskNote = quota.quota_source === "admin_role_disk_available_90_percent"
      ? ` · root/admin 上限：儲存磁碟可用空間 90%，${quota.warning_threshold_percent || 80}% 起警示`
      : "";
    limitLabel.textContent = `單檔限制：${maxFile} · 每日上傳：${daily} · 檔案數：${Number(quota.file_count || 0)}${diskNote}`;
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

function driveFileCategory(file) {
  const name = file?.display_name || file?.virtual_path || file?.original_filename_plain_for_public || file?.storage_path || "";
  const mime = String(file?.mime_type_plain_for_public || file?.mime_type || "").toLowerCase();
  const ext = driveFileExtension(name);
  if (mime.startsWith("audio/") || [".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".weba"].includes(ext)) return "audio";
  if (mime.startsWith("video/") || [".m4v", ".mov", ".mp4", ".ogv", ".webm"].includes(ext)) return "video";
  if (mime.startsWith("image/") || [".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"].includes(ext)) return "image";
  if (mime === "application/pdf" || ext === ".pdf") return "pdf";
  if (mime.startsWith("text/") || [".css", ".csv", ".htm", ".html", ".ini", ".js", ".json", ".log", ".md", ".py", ".sql", ".text", ".toml", ".txt", ".xml", ".yaml", ".yml"].includes(ext)) return "text";
  if ([".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"].includes(ext)) return "archive";
  return "metadata";
}

function driveFileIsImage(file) {
  return driveFileCategory(file) === "image";
}

function drivePrimaryAction(file) {
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
  return id;
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
}

function removeDriveTransferRow(id) {
  driveTransferRows = driveTransferRows.filter((item) => item.id !== id);
  renderDriveFiles(lastDriveFiles || []);
}

function renderDriveTransferRow(item) {
  const percent = driveTransferPercent(item);
  const width = percent === null ? 100 : percent;
  const label = percent === null ? "計算中" : `${Math.round(percent)}%`;
  const bytes = item.total_bytes
    ? `${formatDriveBytes(item.loaded_bytes || 0)} / ${formatDriveBytes(item.total_bytes)}`
    : (item.loaded_bytes ? formatDriveBytes(item.loaded_bytes) : "等待資料");
  const statusClass = item.status === "failed" ? "failed" : item.status === "completed" ? "completed" : "running";
  return `
    <div class="drive-file-row drive-transfer-row ${sanitize(statusClass)}">
      <div>
        <strong>${sanitize(item.name || item.filename || "處理中的檔案")}</strong>
        <div class="drive-card-sub">${sanitize(item.kind === "remote_download" ? "下載中" : "上傳中")} · ${sanitize(item.msg || item.phase || "處理中")} · ${sanitize(bytes)}</div>
        <div class="drive-progress" aria-label="${sanitize(label)}">
          <div class="drive-progress-fill ${percent === null ? "indeterminate" : ""}" style="width:${width}%;"></div>
        </div>
      </div>
      <div class="drive-file-actions">
        <span class="drive-progress-label">${sanitize(label)}</span>
      </div>
    </div>
  `;
}

let lastDriveFiles = [];

function renderDriveFiles(files) {
  const list = $("drive-file-list");
  if (!list) return;
  lastDriveFiles = Array.isArray(files) ? files : [];
  const transferHtml = driveTransferRows.map(renderDriveTransferRow).join("");
  if ((!Array.isArray(files) || !files.length) && !driveTransferRows.length) {
    list.innerHTML = `<div class="drive-empty">尚無雲端檔案</div>`;
    return;
  }
  const fileHtml = (Array.isArray(files) ? files : []).map((file) => {
    const name = file.original_filename_plain_for_public || file.id || "download.bin";
    const warn = driveFileNeedsWarning(file);
    const primary = drivePrimaryAction(file);
    const albumButton = driveFileIsImage(file)
      ? `<button class="btn" type="button" data-drive-action="add-cloud-to-album" data-file-id="${sanitize(file.id)}" data-name="${sanitize(name)}">加入相簿</button>`
      : "";
    return `
      <div class="drive-file-row" data-drive-action="preview" data-file-id="${sanitize(file.id)}" data-name="${sanitize(name)}">
        <div>
          <strong>${sanitize(name)}</strong>
          <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · ${sanitize(drivePrivacyModeLabel(file.privacy_mode))}${drivePrivacyModeDescription(file.privacy_mode) ? `（${sanitize(drivePrivacyModeDescription(file.privacy_mode))}）` : ""} · ${sanitize(driveFileCategory(file))} · risk=${sanitize(file.risk_level || "-")} · scan=${sanitize(file.scan_status || "-")}</div>
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

async function loadDriveFiles(csrf) {
  const list = $("drive-file-list");
  if (!list) return;
  const res = await fetch(API + "/cloud-drive/files", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    list.innerHTML = `<div class="drive-empty">${sanitize(json.msg || "檔案列表讀取失敗")}</div>`;
    return;
  }
  renderDriveFiles(json.files || []);
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
  const form = new FormData();
  form.append("file", file);
  form.append("privacy_mode", $("drive-upload-privacy-mode")?.value || "private_scannable");
  try {
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
    await loadDriveDashboard();
    removeDriveTransferRow(transferId);
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
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  await fetchCsrfToken({ force: true });
  const res = await fetch(API + "/cloud-drive/remote-download/capabilities", {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": getCsrfToken() || "" }
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    if (status) status.textContent = json.msg || "遠端下載能力讀取失敗";
    return;
  }
  const caps = json.capabilities || {};
  if (status) {
    status.textContent = caps.bt_magnet || caps.bt_file
      ? `Direct link 可用，magnet / .torrent 可用（${caps.aria2c_path || "aria2c"}）`
      : "Direct link 可用；magnet / .torrent 不可用，伺服器需安裝 aria2c";
  }
}

async function startRemoteDriveDownload() {
  const url = ($("drive-remote-url")?.value || "").trim();
  const torrentInput = $("drive-remote-torrent-file");
  const torrentFile = torrentInput?.files?.[0] || null;
  if (!url && !torrentFile) {
    alert("請輸入下載網址，或上傳 .torrent BT 種子檔");
    return;
  }
  if (url && torrentFile) {
    alert("下載網址和 BT 種子檔請擇一使用");
    return;
  }
  const transferId = addDriveTransferRow({
    kind: "remote_download",
    name: torrentFile ? torrentFile.name : url,
    loaded_bytes: 0,
    total_bytes: null,
    progress_percent: 0,
    msg: "建立下載任務",
  });
  const button = $("drive-remote-download-btn");
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
      form.append("privacy_mode", $("drive-remote-privacy-mode")?.value || "private_scannable");
      form.append("virtual_path", $("drive-remote-virtual-path")?.value || "");
      res = await fetch(API + "/cloud-drive/remote-download/torrent-tasks", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": getCsrfToken() || "" },
        body: form
      });
    } else {
      res = await fetch(API + "/cloud-drive/remote-download/tasks", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrfToken() || "" },
        body: JSON.stringify({
          url,
          privacy_mode: $("drive-remote-privacy-mode")?.value || "private_scannable",
          virtual_path: $("drive-remote-virtual-path")?.value || ""
        })
      });
    }
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `遠端下載失敗（HTTP ${res.status}）`);
    const task = json.task || {};
    updateDriveTransferRow(transferId, {
      id: transferId,
      task_id: task.id,
      status: task.status || "running",
      phase: task.phase || "queued",
      msg: task.msg || "已加入下載佇列",
    });
    await pollRemoteDownloadTask(task.id, transferId);
    if ($("drive-remote-url")) $("drive-remote-url").value = "";
    if (torrentInput) torrentInput.value = "";
    flash($("drive-msg"), json.msg || "遠端下載已保存", true);
    await loadDriveDashboard();
    removeDriveTransferRow(transferId);
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
  while (true) {
    await driveSleep(900);
    await fetchCsrfToken({ force: true });
    const res = await fetch(API + `/cloud-drive/remote-download/tasks/${encodeURIComponent(taskId)}`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": getCsrfToken() || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.ok) throw new Error(json.msg || `遠端下載狀態讀取失敗（HTTP ${res.status}）`);
    const task = json.task || {};
    updateDriveTransferRow(transferId, {
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
    if (task.status === "failed") throw new Error(task.error || task.msg || "遠端下載失敗");
  }
}

async function downloadDriveFile(fileId, likelyHighRisk) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const doFetch = (confirmed) => fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/download${confirmed ? "?confirm_high_risk=1" : ""}`, {
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
  const name = match ? match[1] : "download.bin";
  const url = URL.createObjectURL(blob);
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

function clearAlbumFullPreviewUrl() {
  if (currentAlbumFullPreviewUrl) {
    URL.revokeObjectURL(currentAlbumFullPreviewUrl);
    currentAlbumFullPreviewUrl = "";
  }
}

async function fetchDrivePreviewBlob(fileId, csrf) {
  const res = await fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content`, {
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
  if (body) body.innerHTML = "";
  if (overlay) {
    overlay.classList.remove("show");
    overlay.setAttribute("aria-hidden", "true");
  }
  document.body.classList.remove("modal-open");
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

function shouldOpenDriveFullscreen(fileId, options = {}) {
  if (options.skipRepeatCheck) return false;
  const now = Date.now();
  const repeated = lastDrivePreviewClick.fileId === String(fileId || "") && now - lastDrivePreviewClick.at <= DRIVE_FULLSCREEN_PREVIEW_MS;
  lastDrivePreviewClick = { fileId: String(fileId || ""), at: now };
  return repeated;
}

async function previewDriveFile(fileId, options = {}) {
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
    const res = await fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "預覽失敗");
    const preview = json.preview || {};
    if (!panel) return;
    panel.innerHTML = renderDrivePreviewMetadata(preview, fileId);
    if (preview.render_mode === "text") {
      panel.innerHTML += `<pre class="drive-preview-text">${sanitize(preview.text || "")}</pre>${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "archive") {
      const entries = Array.isArray(preview.entries) ? preview.entries : [];
      panel.innerHTML += `<div class="drive-preview-archive">${entries.map((entry) => `${entry.is_dir ? "[dir] " : ""}${sanitize(entry.name || "-")} · ${formatDriveBytes(entry.size || 0)}`).join("\n") || "壓縮檔內無可列出的項目"}</div>${preview.truncated ? '<div class="drive-card-sub">項目過多，已截斷顯示。</div>' : ""}`;
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

async function previewAlbumFileFullscreen(fileId, fileName = "") {
  const overlay = $("album-full-preview-overlay");
  const title = $("album-full-preview-title");
  const meta = $("album-full-preview-meta");
  const body = $("album-full-preview-body");
  if (!overlay || !body) return previewDriveFile(fileId, { skipRepeatCheck: true, fileName });
  clearAlbumFullPreviewUrl();
  overlay.classList.add("show");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  if (title) title.textContent = fileName || "檔案預覽";
  if (meta) meta.textContent = "讀取檔案中...";
  body.innerHTML = `<div class="drive-empty">讀取檔案中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) throw new Error(json.msg || "預覽失敗");
    const preview = json.preview || {};
    if (title) title.textContent = preview.filename || fileName || "檔案預覽";
    const baseMeta = `${formatDriveBytes(preview.size_bytes || 0)} · ${preview.mime_type || "-"} · scan=${preview.scan_status || "-"}`;
    if (preview.render_mode === "text") {
      if (meta) meta.textContent = baseMeta;
      body.innerHTML = `<pre class="drive-preview-text">${sanitize(preview.text || "")}</pre>${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}`;
      return;
    }
    if (preview.render_mode === "archive") {
      const entries = Array.isArray(preview.entries) ? preview.entries : [];
      if (meta) meta.textContent = baseMeta;
      body.innerHTML = `<div class="drive-preview-archive">${entries.map((entry) => `${entry.is_dir ? "[dir] " : ""}${sanitize(entry.name || "-")} · ${formatDriveBytes(entry.size || 0)}`).join("\n") || "壓縮檔內無可列出的項目"}</div>${preview.truncated ? '<div class="drive-card-sub">項目過多，已截斷顯示。</div>' : ""}`;
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
    if (meta) meta.textContent = "";
    body.innerHTML = `<div class="drive-empty">${sanitize(err.message || "預覽失敗")}</div>`;
  }
}

async function editDriveTextFile(fileId) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (card) card.style.display = "block";
  if (panel) panel.innerHTML = `<div class="drive-empty">讀取文字內容中...</div>`;
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview`, {
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
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(name)}</strong>
          <div class="drive-card-sub">${formatDriveBytes(ref.size_bytes || 0)} · ${sanitize(ref.context_type || "-")}#${sanitize(ref.context_id || "-")} · risk=${sanitize(ref.risk_level || "-")} · scan=${sanitize(ref.scan_status || "-")}</div>
        </div>
        <div class="drive-file-actions">
          <button class="btn" type="button" data-drive-action="preview" data-file-id="${sanitize(ref.file_id)}">預覽</button>
          <button class="btn ${warn ? "btn-danger" : "btn-primary"}" type="button" data-drive-action="download" data-file-id="${sanitize(ref.file_id)}" data-warn="${warn ? "1" : "0"}">下載</button>
        </div>
      </div>
    `;
  }).join("");
}

async function loadContextAttachments(contextType, contextId, targetId) {
  if (!contextType || !contextId || !targetId) return;
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/cloud-drive/refs?context_type=${encodeURIComponent(contextType)}&context_id=${encodeURIComponent(contextId)}`, {
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
  form.append("privacy_mode", "private_scannable");
  form.append("context_type", contextType);
  form.append("context_id", String(contextId));
  grantUserIds.forEach((id) => form.append("grant_user_ids", String(id)));
  if (grantRole) form.append("grant_role", grantRole);
  const res = await fetch(API + "/cloud-drive/upload", {
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
    alert("請輸入既有雲端 file_id");
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
  form.append("privacy_mode", "private_scannable");
  const res = await fetch(API + "/cloud-drive/upload", {
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
  if (typeof addPendingChatAttachment === "function") {
    addPendingChatAttachment(json.file || {});
  }
  setChatMsg("chat-room-warn", "附件已加入待送清單，按送出後會出現在該則訊息下方", true);
}

async function addExistingChatFileToPending(fileId) {
  if (!fileId) {
    alert("請輸入既有雲端 file_id");
    return;
  }
  if (!selectedChatRoomId) {
    alert("請先選擇聊天室");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/files/${encodeURIComponent(fileId)}/status`, {
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
}

async function attachExistingDmFile() {
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
  form.append("privacy_mode", "private_scannable");
  const res = await fetch(API + "/cloud-drive/upload", {
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
}

async function attachExistingAnnouncementFile() {
  const announcementId = Number($("announcement-attachment-announcement-id")?.value || 0);
  const fileId = $("announcement-attachment-existing-file-id")?.value.trim() || "";
  if (!announcementId) {
    alert("請輸入公告 ID");
    return;
  }
  if (!fileId) {
    alert("請輸入既有雲端 file_id");
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
  renderStorageFolders(storageFoldersCache);
  renderStorageFiles(storageFilesCache);
}

function renderStorageFiles(files) {
  const list = $("storage-file-list");
  if (!list) return;
  const visibleFiles = (Array.isArray(files) ? files : []).filter((file) => storageDirName(file.virtual_path || file.display_name || "") === currentStoragePath);
  if (!visibleFiles.length) {
    list.innerHTML = `<div class="drive-empty">這個資料夾沒有檔案</div>`;
    return;
  }
  list.innerHTML = visibleFiles.map((file) => {
    const primary = drivePrimaryAction(file);
    const albumButton = driveFileIsImage(file)
      ? `<button class="btn" type="button" data-drive-action="add-storage-to-album" data-storage-file-id="${sanitize(file.id)}" data-name="${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}">加入相簿</button>`
      : "";
    return `
    <div class="drive-file-row" data-drive-action="preview" data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}">
      <div>
        <strong>${sanitize(file.display_name || storageBaseName(file.virtual_path) || file.id)}</strong>
        <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · ${sanitize(driveFileCategory(file))} · scan=${sanitize(file.scan_status || "-")} · ${sanitize(file.virtual_path || "-")}</div>
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
  }).join("");
}

function renderStorageFolders(folders) {
  const list = $("storage-folder-list");
  if (!list) return;
  const visibleFolders = (Array.isArray(folders) ? folders : []).filter((folder) => {
    const path = normalizeStoragePath(folder.virtual_path || folder.display_name || "");
    return path !== "/" && storageDirName(path) === currentStoragePath;
  });
  const rows = [];
  if (currentStoragePath !== "/") {
    rows.push(`
      <div class="drive-file-row">
        <div>
          <strong>上一層</strong>
          <div class="drive-card-sub">${sanitize(storageDirName(currentStoragePath))}</div>
        </div>
        <div class="drive-file-actions">
          <button class="btn" type="button" data-drive-action="open-storage-folder" data-path="${sanitize(storageDirName(currentStoragePath))}">開啟</button>
        </div>
      </div>
    `);
  }
  if (!visibleFolders.length && !rows.length) {
    list.innerHTML = `<div class="drive-empty">尚無資料夾</div>`;
    return;
  }
  rows.push(...visibleFolders.map((folder) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(storageBaseName(folder.virtual_path || folder.display_name || "folder"))}</strong>
        <div class="drive-card-sub">${folder.is_explicit ? "已建立" : "由檔案路徑產生"} · 直接 ${Number(folder.file_count || 0)} 個 · 含子資料夾 ${Number(folder.recursive_file_count || 0)} 個</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn btn-primary" type="button" data-drive-action="open-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">開啟</button>
        <button class="btn" type="button" data-drive-action="folder-to-album" data-path="${sanitize(folder.virtual_path || "")}" data-name="${sanitize(storageBaseName(folder.virtual_path || folder.display_name || "folder"))}">設為相簿</button>
        <button class="btn" type="button" data-drive-action="select-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">移動</button>
        <button class="btn btn-danger" type="button" data-drive-action="trash-storage-folder" data-path="${sanitize(folder.virtual_path || "")}">刪除</button>
      </div>
    </div>
  `));
  list.innerHTML = rows.join("");
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
      </div>
      <div class="drive-file-actions">
        <button class="btn btn-primary" type="button" data-drive-action="open-album" data-album-id="${sanitize(album.id)}">開啟</button>
        <button class="btn btn-danger" type="button" data-drive-action="delete-album" data-album-id="${sanitize(album.id)}">刪除</button>
      </div>
    </div>
  `).join("");
}

async function loadStorageFiles(csrf) {
  const headers = { "X-CSRF-Token": csrf || "" };
  const [filesRes, trashRes, foldersRes, albumsRes] = await Promise.all([
    fetch(API + "/storage/files", { credentials: "same-origin", headers }),
    fetch(API + "/storage/trash", { credentials: "same-origin", headers }),
    fetch(API + "/storage/folders", { credentials: "same-origin", headers }),
    fetch(API + "/storage/albums", { credentials: "same-origin", headers })
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

async function uploadStorageFile() {
  const input = $("storage-upload-file");
  const pathInput = $("storage-upload-path");
  if (!input || !input.files || !input.files[0]) {
    alert("請先選擇檔案");
    return;
  }
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", input.files[0]);
  form.append("virtual_path", pathInput?.value || joinStoragePath(currentStoragePath, input.files[0].name));
  const res = await fetch(API + "/storage/files", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) {
    alert(json.msg || "Storage 上傳失敗");
    return;
  }
  input.value = "";
  if (pathInput) pathInput.value = "";
  await loadDriveDashboard();
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
    res = await fetch(API + path, options);
  } catch (err) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    try {
      res = await fetch(API + path, options);
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
  if (!window.confirm("永久移除此垃圾桶項目？由「我的檔案」移入垃圾桶的檔案會永久失效。")) return;
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
  if (!window.confirm("清空垃圾桶？由「我的檔案」移入垃圾桶的檔案會永久失效。")) return;
  try {
    await storageAction("/storage/trash/purge", "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message || "清空垃圾桶失敗"); }
}

async function downloadStorageFile(id) {
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const res = await fetch(API + `/storage/files/${encodeURIComponent(id)}/download`, {
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
  if (!title.trim()) {
    alert("請輸入相簿名稱");
    return;
  }
  try {
    const json = await storageAction("/storage/albums", "POST", { title, description, visibility });
    $("album-create-title").value = "";
    if ($("album-create-description")) $("album-create-description").value = "";
    selectedAlbumId = json.album?.id || "";
    await loadDriveDashboard();
    await loadAlbumGallery();
  } catch (err) { alert(err.message); }
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

function renderAlbumFiles(album) {
  const list = $("album-file-list");
  if (!list) return;
  const files = Array.isArray(album.files) ? album.files : [];
  if (!files.length) {
    list.innerHTML = `<div class="drive-empty">這本相簿還沒有檔案。到雲端硬碟的圖片檔旁按「加入相簿」。</div>`;
    return;
  }
  list.innerHTML = files.map((file) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(albumFileDisplayName(file))}</strong>
        <div class="drive-card-sub">${sanitize(file.virtual_path || "-")} · ${formatDriveBytes(file.size_bytes || 0)} · risk=${sanitize(file.risk_level || "-")} · scan=${sanitize(file.scan_status || "-")}${file.caption ? ` · ${sanitize(file.caption)}` : ""}</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn" type="button" data-drive-action="album-full-preview" data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(albumFileDisplayName(file))}">預覽</button>
        ${file.storage_file_id ? `<button class="btn" type="button" data-drive-action="download-storage" data-storage-file-id="${sanitize(file.storage_file_id)}">下載</button>` : `<button class="btn" type="button" data-drive-action="download" data-file-id="${sanitize(file.file_id)}" data-warn="0">下載</button>`}
        <button class="btn btn-danger" type="button" data-drive-action="remove-album-file" data-album-id="${sanitize(album.id)}" data-album-file-id="${sanitize(file.id)}">移出</button>
      </div>
    </div>
  `).join("");
}

function renderAlbumDetail(album) {
  const card = $("album-detail-card");
  if (!card) return;
  selectedAlbumId = album.id || "";
  card.style.display = "block";
  const title = $("album-detail-title");
  const meta = $("album-detail-meta");
  if (title) title.textContent = album.title || "相簿內容";
  if (meta) meta.textContent = `${albumVisibilityLabel(album.visibility)} · ${Number((album.files || []).length)} 個檔案 · ${album.updated_at || album.created_at || ""}`;
  if ($("album-edit-title")) $("album-edit-title").value = album.title || "";
  if ($("album-edit-description")) $("album-edit-description").value = album.description || "";
  if ($("album-edit-visibility")) $("album-edit-visibility").value = album.visibility || "private";
  renderAlbumFiles(album);
}

async function openAlbum(id, options = {}) {
  if (!id) return;
  try {
    const json = await storageAction(`/storage/albums/${encodeURIComponent(id)}`, "GET");
    renderAlbumDetail(json.album || {});
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
    const json = await storageAction(`/storage/albums/${encodeURIComponent(selectedAlbumId)}`, "PUT", {
      title: $("album-edit-title")?.value || "",
      description: $("album-edit-description")?.value || "",
      visibility: $("album-edit-visibility")?.value || "private",
    });
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
    const res = await fetch(API + "/storage/albums", {
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
  clearAlbumThumbObjectUrls();
  const card = $("album-viewer-card");
  if (card) card.style.display = "none";
}

function renderAlbumPreviewTile(file) {
  const name = albumFileDisplayName(file);
  const category = driveFileCategory(file);
  const thumbKey = file.id || file.file_id;
  const canTryPreview = category === "image" || category === "metadata";
  const thumb = canTryPreview
    ? `<div class="drive-gallery-thumb" data-album-thumb-key="${sanitize(thumbKey)}"><span>讀取預覽</span></div>`
    : `<div class="drive-gallery-thumb drive-gallery-thumb-placeholder"><span>${sanitize(category)}</span></div>`;
  return `
    <div class="drive-gallery-tile">
      ${thumb}
      <div class="drive-gallery-file-info">
        <strong>${sanitize(name)}</strong>
        <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · <span data-album-category-key="${sanitize(thumbKey)}">${sanitize(category)}</span> · scan=${sanitize(file.scan_status || "-")}</div>
      </div>
      <div class="drive-file-actions" style="justify-content:flex-start;">
        <button class="btn" type="button" data-drive-action="album-full-preview" data-file-id="${sanitize(file.file_id)}" data-name="${sanitize(name)}">預覽</button>
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
      const blob = await fetchDrivePreviewBlob(file.file_id, csrf);
      if (!String(blob.type || "").toLowerCase().startsWith("image/")) throw new Error("不是圖片預覽");
      const url = URL.createObjectURL(blob);
      albumThumbObjectUrls.push(url);
      holder.innerHTML = `<img src="${url}" alt="${sanitize(albumFileDisplayName(file))}" loading="lazy" />`;
      const categoryLabel = Array.from(document.querySelectorAll("[data-album-category-key]")).find((node) => node.dataset.albumCategoryKey === String(thumbKey));
      if (categoryLabel) categoryLabel.textContent = "image";
    } catch (err) {
      holder.innerHTML = `<span>無法預覽</span>`;
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
  if (card) card.style.display = "block";
  if (filesEl) filesEl.innerHTML = `<div class="drive-empty">讀取相簿中...</div>`;
  try {
    const json = await storageAction(`/storage/albums/${encodeURIComponent(id)}`, "GET");
    const album = json.album || {};
    const files = Array.isArray(album.files) ? album.files : [];
    if (title) title.textContent = album.title || "相簿";
    if (meta) meta.textContent = `${albumVisibilityLabel(album.visibility)} · ${files.length} 個檔案${album.description ? ` · ${album.description}` : ""}`;
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
  const msg = $("drive-msg");
  try {
    await fetchCsrfToken({ force: true });
    const csrf = getCsrfToken();
    const res = await fetch(API + "/files/security-policy", {
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf || "" }
    });
    const json = await res.json().catch(() => ({}));
    if (!json.ok) {
      if (msg) flash(msg, json.msg || "雲端硬碟狀態讀取失敗", false);
      return;
    }
    renderDriveDashboard(json);
    await loadRemoteDownloadCapabilities();
    await loadDriveFiles(csrf);
    await loadStorageFiles(csrf);
    if (msg) msg.className = "msg";
  } catch (err) {
    if (msg) flash(msg, "雲端硬碟狀態讀取失敗", false);
  }
}

document.addEventListener("click", (event) => {
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
  const path = button.dataset.path || "";
  const name = button.dataset.name || "";
  const warn = button.dataset.warn === "1";
  (async () => {
    if (action === "preview") return previewDriveFile(fileId, { fileName: name });
    if (action === "album-full-preview") return previewAlbumFileFullscreen(fileId, name);
    if (action === "edit-text") return editDriveTextFile(fileId);
    if (action === "save-text") return saveDriveTextFile(fileId);
    if (action === "download") return downloadDriveFile(fileId, warn);
    if (action === "move-cloud-to-storage") return moveCloudFileToStorage(fileId, name);
    if (action === "add-cloud-to-album") return addCloudFileToAlbum(fileId, name);
    if (action === "delete-cloud") return deleteDriveFile(fileId);
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
    if (action === "delete-album") return deleteAlbum(albumId);
    if (action === "close-album-detail") return closeAlbumDetail();
    if (action === "save-album-detail") return saveAlbumDetail();
    if (action === "remove-album-file") return removeAlbumFile(albumId, albumFileId);
    if (action === "open-album-viewer") return openAlbumViewer(albumId);
    if (action === "close-album-viewer") return closeAlbumViewer();
    if (action === "refresh-albums") return loadAlbumGallery();
  })().catch((err) => alert(err.message || "操作失敗"));
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("album-full-preview-overlay")?.classList.contains("show")) {
    closeAlbumFullPreview();
  }
});
