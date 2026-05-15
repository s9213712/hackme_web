// Album / preview / share block moved out of 35-drive.js for readability.

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
  if (!storageAlbumsFeatureEnabled()) {
    renderStorageFeatureDisabled();
    return;
  }
  if (!currentUser || !canAccessModule("privacy_uploads")) return;
  const msg = $("album-gallery-msg");
  try {
    const csrf = await fetchCsrfToken();
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
