function formatDriveBytes(bytes) {
  if (bytes === null || bytes === undefined) return "無上限";
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function renderDriveGroupedStats(targetId, grouped, emptyText) {
  const el = $(targetId);
  if (!el) return;
  const entries = Object.entries(grouped || {});
  if (!entries.length) {
    el.innerHTML = `<div class="drive-empty">${sanitize(emptyText || "尚無資料")}</div>`;
    return;
  }
  el.innerHTML = entries.map(([name, item]) => `
    <div class="drive-pill">
      <strong>${sanitize(name)}</strong>
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
    limitLabel.textContent = `單檔限制：${maxFile} · 每日上傳：${daily} · 檔案數：${Number(quota.file_count || 0)}`;
  }
  if (barFill) {
    barFill.style.width = `${percent}%`;
    barFill.dataset.warning = percent >= 90 ? "high" : percent >= 70 ? "medium" : "low";
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
  renderDriveGroupedStats("drive-mode-summary", quota.by_privacy_mode, "尚無隱私模式統計");
}

function driveFileNeedsWarning(file) {
  const risk = file && file.risk_level;
  const status = file && file.scan_status;
  return ["high", "blocked", "unknown_encrypted"].includes(risk) || ["infected", "quarantined", "failed", "unknown_encrypted"].includes(status);
}

function renderDriveFiles(files) {
  const list = $("drive-file-list");
  if (!list) return;
  if (!Array.isArray(files) || !files.length) {
    list.innerHTML = `<div class="drive-empty">尚無雲端檔案</div>`;
    return;
  }
  list.innerHTML = files.map((file) => {
    const name = file.original_filename_plain_for_public || file.id || "download.bin";
    const warn = driveFileNeedsWarning(file);
    return `
      <div class="drive-file-row">
        <div>
          <strong>${sanitize(name)}</strong>
          <div class="drive-card-sub">${formatDriveBytes(file.size_bytes || 0)} · ${sanitize(file.privacy_mode || "-")} · risk=${sanitize(file.risk_level || "-")} · scan=${sanitize(file.scan_status || "-")}</div>
        </div>
        <div class="drive-file-actions">
          <button class="btn" type="button" onclick="previewDriveFile('${sanitize(file.id)}')">預覽</button>
          <button class="btn" type="button" onclick="editDriveTextFile('${sanitize(file.id)}')">編輯文字</button>
          <button class="btn ${warn ? "btn-danger" : "btn-primary"}" type="button" onclick="downloadDriveFile('${sanitize(file.id)}', ${warn ? "true" : "false"})">下載</button>
          <button class="btn btn-danger" type="button" onclick="deleteDriveFile('${sanitize(file.id)}')">刪除</button>
        </div>
      </div>
    `;
  }).join("");
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
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const form = new FormData();
  form.append("file", input.files[0]);
  form.append("privacy_mode", $("drive-upload-privacy-mode")?.value || "private_scannable");
  const res = await fetch(API + "/cloud-drive/upload", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" },
    body: form
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) {
    const detail = json.error_code ? `${json.msg || "雲端硬碟上傳失敗"}（${json.error_code}）` : (json.msg || `雲端硬碟上傳失敗（HTTP ${res.status}）`);
    alert(detail);
    return;
  }
  input.value = "";
  await loadDriveDashboard();
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
  if (!window.confirm("刪除此雲端硬碟檔案？既有附件引用會失效。")) return;
  try {
    await storageAction(`/cloud-drive/files/${encodeURIComponent(fileId)}`, "DELETE");
    await loadDriveDashboard();
  } catch (err) {
    alert(err.message || "刪除失敗");
  }
}

let currentDrivePreviewUrl = "";

function clearDrivePreviewUrl() {
  if (currentDrivePreviewUrl) {
    URL.revokeObjectURL(currentDrivePreviewUrl);
    currentDrivePreviewUrl = "";
  }
}

async function fetchDrivePreviewContent(fileId, csrf) {
  const res = await fetch(API + `/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content`, {
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrf || "" }
  });
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.msg || "預覽內容讀取失敗");
  }
  clearDrivePreviewUrl();
  currentDrivePreviewUrl = URL.createObjectURL(await res.blob());
  return currentDrivePreviewUrl;
}

function renderDrivePreviewMetadata(preview) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (!panel || !card) return;
  card.style.display = "block";
  panel.innerHTML = `
    <div><strong>${sanitize(preview.filename || "preview")}</strong></div>
    <div class="drive-card-sub">${sanitize(preview.category || "-")} · ${formatDriveBytes(preview.size_bytes || 0)} · ${sanitize(preview.mime_type || "-")} · scan=${sanitize(preview.scan_status || "-")}</div>
  `;
}

async function previewDriveFile(fileId) {
  const panel = $("drive-preview-panel");
  const card = $("drive-preview-card");
  if (card) card.style.display = "block";
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
    renderDrivePreviewMetadata(preview);
    if (!panel) return;
    if (preview.render_mode === "text") {
      panel.innerHTML += `<pre class="drive-preview-text">${sanitize(preview.text || "")}</pre>${preview.truncated ? '<div class="drive-card-sub">內容過長，已截斷顯示。</div>' : ""}<button class="btn" type="button" onclick="editDriveTextFile('${sanitize(fileId)}')">線上修改此文字檔</button>`;
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
          <button class="btn btn-primary" type="button" onclick="saveDriveTextFile('${sanitize(fileId)}')">儲存修改</button>
          <button class="btn" type="button" onclick="previewDriveFile('${sanitize(fileId)}')">取消</button>
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
    await previewDriveFile(fileId);
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
          <button class="btn" type="button" onclick="previewDriveFile('${sanitize(ref.file_id)}')">預覽</button>
          <button class="btn ${warn ? "btn-danger" : "btn-primary"}" type="button" onclick="downloadDriveFile('${sanitize(ref.file_id)}', ${warn ? "true" : "false"})">下載</button>
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

async function uploadChatAttachment() {
  await uploadContextAttachment({
    fileInputId: "chat-attachment-file",
    contextType: "group_chat",
    contextId: selectedChatRoomId,
    grantRole: "user",
    refresh: () => loadContextAttachments("group_chat", selectedChatRoomId, "chat-attachment-list")
  });
}

async function attachExistingChatFile() {
  await attachExistingContextAttachment({
    fileId: $("chat-attachment-existing-file-id")?.value.trim() || "",
    contextType: "group_chat",
    contextId: selectedChatRoomId,
    grantRole: "user",
    refresh: () => loadContextAttachments("group_chat", selectedChatRoomId, "chat-attachment-list")
  });
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

function renderStorageFiles(files) {
  const list = $("storage-file-list");
  if (!list) return;
  if (!Array.isArray(files) || !files.length) {
    list.innerHTML = `<div class="drive-empty">尚無 Storage 檔案</div>`;
    return;
  }
  list.innerHTML = files.map((file) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(file.display_name || file.virtual_path || file.id)}</strong>
        <div class="drive-card-sub">${sanitize(file.virtual_path || "-")} · ${formatDriveBytes(file.size_bytes || 0)} · scan=${sanitize(file.scan_status || "-")}</div>
      </div>
      <div class="drive-file-actions">
        <button class="btn" type="button" onclick="downloadStorageFile('${sanitize(file.id)}')">下載</button>
        <button class="btn" type="button" onclick="addStorageFileToAlbum('${sanitize(file.id)}')">加到相簿</button>
        <button class="btn btn-danger" type="button" onclick="trashStorageFile('${sanitize(file.id)}')">回收</button>
      </div>
    </div>
  `).join("");
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
        <button class="btn" type="button" onclick="restoreStorageFile('${sanitize(file.id)}')">還原</button>
        <button class="btn btn-danger" type="button" onclick="purgeStorageFile('${sanitize(file.id)}')">永久移除</button>
      </div>
    </div>
  `).join("");
}

function renderAlbums(albums) {
  const list = $("album-list");
  if (!list) return;
  if (!Array.isArray(albums) || !albums.length) {
    list.innerHTML = `<div class="drive-empty">尚無相簿</div>`;
    return;
  }
  list.innerHTML = albums.map((album) => `
    <div class="drive-file-row">
      <div>
        <strong>${sanitize(album.title || album.id)}</strong>
        <div class="drive-card-sub">id=${sanitize(album.id)} · ${sanitize(album.visibility || "private")} · ${Number(album.file_count || 0)} 個檔案</div>
      </div>
      <button class="btn btn-danger" type="button" onclick="deleteAlbum('${sanitize(album.id)}')">刪除</button>
    </div>
  `).join("");
}

async function loadStorageFiles(csrf) {
  const headers = { "X-CSRF-Token": csrf || "" };
  const [filesRes, trashRes, albumsRes] = await Promise.all([
    fetch(API + "/storage/files", { credentials: "same-origin", headers }),
    fetch(API + "/storage/trash", { credentials: "same-origin", headers }),
    fetch(API + "/storage/albums", { credentials: "same-origin", headers })
  ]);
  const filesJson = await filesRes.json().catch(() => ({}));
  const trashJson = await trashRes.json().catch(() => ({}));
  const albumsJson = await albumsRes.json().catch(() => ({}));
  renderStorageFiles(filesJson.ok ? filesJson.files || [] : []);
  renderStorageTrash(trashJson.ok ? trashJson.files || [] : []);
  renderAlbums(albumsJson.ok ? albumsJson.albums || [] : []);
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
  form.append("virtual_path", pathInput?.value || input.files[0].name);
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
  await fetchCsrfToken({ force: true });
  const csrf = getCsrfToken();
  const headers = { "X-CSRF-Token": csrf || "" };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(API + path, {
    method,
    credentials: "same-origin",
    headers,
    body: body ? JSON.stringify(body) : undefined
  });
  const json = await res.json().catch(() => ({}));
  if (!json.ok) throw new Error(json.msg || "操作失敗");
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
  if (!window.confirm("永久移除此 storage entry？原始雲端檔案不會被刪除。")) return;
  try {
    await storageAction(`/storage/files/${encodeURIComponent(id)}/purge`, "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
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

async function createAlbum() {
  const title = $("album-create-title")?.value || "";
  const visibility = $("album-create-visibility")?.value || "private";
  if (!title.trim()) {
    alert("請輸入相簿名稱");
    return;
  }
  try {
    await storageAction("/storage/albums", "POST", { title, visibility });
    $("album-create-title").value = "";
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
}

async function deleteAlbum(id) {
  if (!window.confirm("刪除此相簿？不會刪除原始檔案。")) return;
  try {
    await storageAction(`/storage/albums/${encodeURIComponent(id)}`, "DELETE");
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
}

async function addStorageFileToAlbum(storageFileId) {
  const albumId = window.prompt("請輸入相簿 id（可從 AlbumManager 列表複製）");
  if (!albumId) return;
  try {
    await storageAction(`/storage/albums/${encodeURIComponent(albumId)}/files`, "POST", { storage_file_id: storageFileId });
    await loadDriveDashboard();
  } catch (err) { alert(err.message); }
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
    await loadDriveFiles(csrf);
    await loadStorageFiles(csrf);
    if (msg) msg.className = "msg";
  } catch (err) {
    if (msg) flash(msg, "雲端硬碟狀態讀取失敗", false);
  }
}
