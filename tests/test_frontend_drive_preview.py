from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_drive_preview_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    server_py = (ROOT / "server.py").read_text(encoding="utf-8")

    assert 'id="drive-preview-card"' in index_html
    assert 'id="drive-preview-panel"' in index_html
    assert 'class="drive-file-preview-layout"' in index_html
    assert "async function previewDriveFile(fileId, options = {})" in drive_js
    assert "function shouldOpenDriveFullscreen(fileId" in drive_js
    assert "DRIVE_FULLSCREEN_PREVIEW_MS" in drive_js
    assert "/preview/content" in drive_js
    assert "drive-preview-archive" in drive_js
    assert "drive-preview-text" in drive_js
    assert "function renderDriveArchiveEntries(entries)" in drive_js
    assert '".7z", ".rar", ".tar", ".gz"' in drive_js
    assert "closeDrivePreview()" in drive_js
    assert 'data-drive-action="preview" data-file-id="${sanitize(file.id)}"' in drive_js
    assert 'data-drive-action="preview" data-file-id="${sanitize(file.file_id)}"' in drive_js
    assert "return previewAlbumFileFullscreen(fileId, options.fileName || \"\")" in drive_js
    assert 'preview.category === "video"' in drive_js
    assert 'preview.category === "audio"' in drive_js
    assert '<audio controls src="${url}"></audio>' in drive_js
    assert 'preview.category === "pdf"' in drive_js
    assert 'preview.category === "image"' in drive_js
    assert '"img-src":     "\'self\' data: blob:"' in server_py
    assert '"media-src":   "\'self\' blob:"' in server_py
    assert '"frame-src":   "\'self\' blob:"' in server_py


def test_filemanager_and_albummanager_ui_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="storage-upload-file"' in index_html
    assert 'id="storage-folder-upload-btn"' in index_html
    assert 'id="storage-upload-folder"' in index_html
    assert "webkitdirectory" in index_html
    assert 'id="storage-folder-path"' in index_html
    assert 'id="storage-folder-list"' in index_html
    assert 'id="storage-organize-path"' in index_html
    assert 'id="storage-file-list"' in index_html
    assert 'id="storage-trash-list"' in index_html
    assert 'id="album-create-title"' in index_html
    assert 'id="album-create-description"' in index_html
    assert 'id="album-create-share-password"' in index_html
    assert 'id="album-edit-share-password"' in index_html
    assert 'id="album-edit-clear-share-password"' in index_html
    assert 'id="album-picker-select"' in index_html
    assert 'id="album-list"' in index_html
    assert 'id="album-detail-card"' in index_html
    assert 'id="album-file-list"' not in index_html
    assert "不列出，持連結可看" in index_html
    assert "async function uploadStorageFile()" in drive_js
    assert "async function uploadStorageFolder()" in drive_js
    assert "function openStorageFolderUploadPicker()" in drive_js
    assert "function storageUploadRelativePath(file)" in drive_js
    assert "file?.webkitRelativePath" in drive_js
    assert 'form.append("virtual_path", virtualPath)' in drive_js
    assert "async function createStorageFolder()" in drive_js
    assert "async function organizeSelectedStorageFile()" in drive_js
    assert "async function moveStorageFileFromRow(id, currentPath)" in drive_js
    assert "async function moveCloudFileToStorage(fileId, name)" in drive_js
    assert "async function moveStorageFolder()" in drive_js
    assert "async function createAlbum()" in drive_js
    assert "async function openAlbum(id" in drive_js
    assert "await openAlbumViewer(id, options);" in drive_js
    assert "async function saveAlbumDetail()" in drive_js
    assert "function albumShareLinkMarkup(album)" in drive_js
    assert "async function copyAlbumShareUrl(url)" in drive_js
    assert 'data-drive-action="copy-album-share-link"' in drive_js
    assert "share_url" in drive_js
    assert "payload.share_password = sharePassword" in drive_js
    assert "clear_share_password" in drive_js
    assert "password_required" in drive_js
    assert "async function removeAlbumFile(albumId, albumFileId)" in drive_js
    assert "請輸入相簿 id" not in drive_js
    assert 'id="storage-breadcrumb"' in index_html
    assert 'id="storage-selection-label"' in index_html
    assert 'data-drive-action="open-storage-folder"' in drive_js
    assert 'data-drive-action="move-storage-file"' in drive_js
    assert 'data-drive-action="move-cloud-to-storage"' in drive_js
    assert 'data-drive-action="folder-to-album"' in drive_js
    assert "async function createAlbumFromFolder(path, name = \"\")" in drive_js
    assert 'storageAction("/storage/folders/album", "POST"' in drive_js
    assert 'storageAction("/storage/folders/trash", "POST"' in drive_js
    assert "操作失敗（HTTP ${res.status}）" in drive_js
    assert 'data-drive-action="edit-text" data-file-id="${sanitize(file.id)}">編輯文字</button>' not in drive_js
    assert 'id="storage-organize-btn"' not in index_html
    assert "loadStorageFiles(csrf)" in drive_js
    assert 'storageUploadBtn.addEventListener("click", openStorageUploadPicker)' in bootstrap_js
    assert 'storageFolderUploadBtn.addEventListener("click", openStorageFolderUploadPicker)' in bootstrap_js
    assert 'storageUploadFile.addEventListener("change", uploadStorageFile)' in bootstrap_js
    assert 'storageUploadFolder.addEventListener("change", uploadStorageFolder)' in bootstrap_js
    assert 'storageFolderCreateBtn.addEventListener("click", createStorageFolder)' in bootstrap_js
    assert 'storageFolderMoveBtn.addEventListener("click", moveStorageFolder)' in bootstrap_js
    assert 'albumCreateBtn.addEventListener("click", createAlbum)' in bootstrap_js


def test_album_viewer_has_dedicated_module():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="tab-module-albums"' in index_html
    assert 'id="module-albums"' in index_html
    assert 'id="app-sidebar"' in index_html
    assert 'id="sidebar-toggle"' in index_html
    assert 'id="album-gallery-list"' in index_html
    assert 'id="album-viewer-card"' in index_html
    assert 'id="album-thumb-size"' in index_html
    assert 'id="album-full-preview-overlay"' in index_html
    assert 'class="drive-collapsible-panel" id="album-management-panel"' in index_html
    assert 'class="drive-collapsible-panel album-viewer-panel" id="album-viewer-card"' in index_html
    assert 'data-drive-action="album-preview-prev"' in index_html
    assert 'data-drive-action="album-preview-next"' in index_html
    assert '/js/35-drive.js?v=20260429-storage-purchase-feedback' in index_html
    assert '/styles.css?v=20260501-mobile-sidebar' in index_html
    assert '/js/00-core.js?v=20260430-trading-page-split' in index_html
    assert '/js/40-auth-users.js?v=20260429-timeout-login' in index_html
    assert 'src="/js/50-admin.js' in index_html
    assert 'id="root-storage-user-select"' in index_html
    assert 'id="root-storage-save-btn"' in index_html
    assert 'id="root-storage-users"' in index_html
    assert "function loadRootStorageUsers" in admin_js
    assert "function saveRootStorageOverride" in admin_js
    assert '"/root/storage/users"' in admin_js
    assert 'rootStorageSave.addEventListener("click", saveRootStorageOverride)' in bootstrap_js
    assert "onclick=" not in index_html
    assert "onclick=" not in drive_js
    assert "data-drive-action" in drive_js
    assert "function drivePreviewContentUrl(fileId)" in drive_js
    assert "function driveFileIsImage(file)" in drive_js
    assert "let albumPreviewSequence = []" in drive_js
    assert "function setAlbumPreviewSequence" in drive_js
    assert "function stepAlbumPreview(direction)" in drive_js
    assert "event.key === \"ArrowLeft\"" in drive_js
    assert "event.key === \"ArrowRight\"" in drive_js
    assert "function renderAttachmentFileSelects" in drive_js
    assert "async function ensureAttachmentFileOptionsLoaded" in drive_js
    assert "請先從下拉選單選擇雲端檔案" in drive_js
    assert 'data-drive-action="delete-context-attachment"' in drive_js
    assert "async function deleteContextAttachment" in drive_js
    assert "/cloud-drive/refs/${encodeURIComponent(refId)}/delete" in drive_js
    assert "附件編號讀取失敗" in drive_js
    assert "loadChatMessages(selectedChatRoomId" in drive_js
    assert '<select id="chat-attachment-existing-file-id">' in index_html
    assert "dm-attachment-existing-file-id" in drive_js
    assert '<select id="announcement-attachment-existing-file-id">' in index_html
    assert 'placeholder="file_id"' not in index_html
    assert "chat-message-image-preview" in drive_js
    assert "driveTransferRows" in drive_js
    assert "xhrUploadWithProgress" in drive_js
    assert "/cloud-drive/remote-download/tasks" in drive_js
    assert 'id="drive-remote-torrent-file"' in index_html
    assert "/cloud-drive/remote-download/torrent-tasks" in drive_js
    assert "FormData" in drive_js
    assert "async function loadAlbumGallery()" in drive_js
    assert "async function openAlbumViewer(id" in drive_js
    assert "async function fetchDrivePreviewBlob(fileId, csrf)" in drive_js
    assert "async function previewAlbumFileFullscreen(fileId" in drive_js
    assert 'data-drive-action="album-full-preview"' in drive_js
    assert 'data-album-sequence="viewer"' in drive_js
    assert "closeAlbumFullPreview" in drive_js
    assert "hydrateAlbumViewerThumbnails" in drive_js
    assert "const blob = await fetchDrivePreviewBlob(file.file_id, csrf);" in drive_js
    assert "const blob = await fetchDrivePreviewContent(file.file_id, csrf);" not in drive_js
    assert 'data-drive-action="add-cloud-to-album"' in drive_js
    assert 'tabModuleAlbums.style.display = canAccessModule("privacy_uploads") ? "" : "none"' in core_js
    assert "SIDEBAR_MENU_CONFIG" in core_js
    assert "SIDEBAR_ICON_PATHS" in core_js
    assert "sidebar-footer" in index_html
    assert "sidebar-current-user" in index_html
    assert "sidebar-current-level" in index_html
    assert "sidebar-points" in index_html
    assert "sidebar-violations" in index_html
    assert "sidebar-server-version" in index_html
    assert "app-action-bar" in index_html
    assert 'id="session-countdown-label"' in index_html
    assert "member_level_label" in core_js
    assert "特殊階級" in core_js
    assert "RESET_RUNTIME_STATE" in index_html
    assert 'id="security-profile-load-current-btn"' in index_html
    assert 'id="security-mode-profile-preview"' in index_html
    assert 'id="server-mode-profile-preview"' in index_html
    assert "loadCurrentSecurityProfileDraft" in admin_js
    assert "renderSecurityProfilePreview" in admin_js
    assert "function applySecurityProfileToInputs" in admin_js
    assert "function applySecurityProfileDataToInputs" in admin_js
    assert "function previewSecurityProfileSelection" in admin_js
    assert "function bindSecurityProfileSelect" in admin_js
    assert '"feature_audit_log_enabled"' in admin_js
    assert '"feature_economy_enabled"' in admin_js
    assert 'id="sc-feature-audit-log-enabled"' in index_html
    assert 'id="sc-feature-economy-enabled"' in index_html
    assert 'previewSecurityProfileSelection("security-mode-select", "security-mode-profile-preview", "sc")' in bootstrap_js
    assert 'previewSecurityProfileSelection("server-mode-select", "server-mode-profile-preview", "s")' in bootstrap_js
    assert 'bindSecurityProfileSelect("security-mode-select", "security-mode-profile-preview", "sc")' in admin_js
    assert 'bindSecurityProfileSelect("server-mode-select", "server-mode-profile-preview", "s")' in admin_js
    assert "按套用才會寫入伺服器" in admin_js
    assert "await loadSettings();" in admin_js
    assert "populateProfileSelect(\"server-mode-select\"" in admin_js
    assert 'confirm: "RESET_RUNTIME_STATE"' in admin_js
    assert '"RUN_RESET"' not in admin_js
    assert "icon-action-btn" in index_html
    assert "server-connection-light" not in index_html
    assert "startClock" not in core_js
    assert "SIDEBAR_COLLAPSED_STORAGE_KEY" in core_js
    assert "localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY" in core_js
    assert "data-sidebar-action" in core_js
    assert 'switchModuleTab("albums")' in bootstrap_js
    assert "sidebarToggle.addEventListener" in bootstrap_js
    assert 'normTab === "albums"' in admin_js
    assert ".drive-collapsible-panel" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".album-preview-nav" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


def test_album_preview_category_uses_storage_name_before_uploaded_metadata():
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert 'const name = file?.display_name || file?.virtual_path || file?.original_filename_plain_for_public || file?.storage_path || "";' in drive_js
    assert 'const canTryPreview = category === "image" || category === "metadata";' in drive_js
    assert '["image", "metadata"].includes(driveFileCategory(file))' in drive_js
    assert 'startsWith("image/")' in drive_js


def test_album_gallery_layout_wraps_long_filenames():
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert 'class="drive-gallery-file-info"' in drive_js
    assert ".drive-gallery-tile {" in css
    assert "overflow: hidden;" in css
    assert ".drive-gallery-tile strong" in css
    assert "overflow-wrap: anywhere;" in css
    assert "word-break: break-word;" in css


def test_cloud_drive_privacy_modes_use_human_labels():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert 'value="standard_plain">一般檔案（可掃毒、可預覽、可分享）' in index_html
    assert 'value="server_encrypted">伺服器端加密（磁碟密文、下載明文）' in index_html
    assert 'value="e2ee">端到端加密（站方無法讀取）' in index_html
    assert "三種模式怎麼選" in index_html
    assert "非 E2EE 會讓伺服器取得明文" in index_html
    assert "E2EE 上傳時附本機掃描回報" in index_html
    assert "drivePrivacyModeLabel(file.privacy_mode)" in drive_js
    assert "DRIVE_PRIVACY_MODE_COMPARISON" in drive_js
    assert "伺服器端加密" in drive_js
    assert "站方無法讀取" in drive_js
    assert "root 上限：儲存磁碟可用空間 90%" in drive_js
    assert "manager 上限：1 GB" in drive_js
    assert "warning_active" in drive_js


def test_cloud_drive_storage_upgrade_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    routes_py = (ROOT / "routes" / "files.py").read_text(encoding="utf-8")
    upload_security_py = (ROOT / "services" / "upload_security.py").read_text(encoding="utf-8")

    assert 'id="drive-storage-upgrade-card"' in index_html
    assert 'id="drive-storage-upgrade-select"' in index_html
    assert 'data-drive-action="purchase-storage-upgrade"' in index_html
    assert "function renderStorageUpgrade" in drive_js
    assert 'currentUser === "root"' in drive_js
    assert "root 不需要購買容量方案" in drive_js
    assert "root 依實際磁碟容量控管，不需要購買容量方案" in drive_js
    assert "let driveStorageUpgradeCanPurchase = false;" in drive_js
    assert "button.disabled = !driveStorageUpgradeCanPurchase || !driveStorageUpgradeCatalog.length;" in drive_js
    assert "正在購買容量..." in drive_js
    assert "async function loadStorageUpgradeOptions" in drive_js
    assert "async function purchaseStorageUpgrade" in drive_js
    assert "/cloud-drive/storage-upgrades" in drive_js
    assert "/cloud-drive/storage-upgrades/purchase" in drive_js
    assert 'if (action === "purchase-storage-upgrade") return purchaseStorageUpgrade();' in drive_js
    assert '@app.route("/api/cloud-drive/storage-upgrades", methods=["GET"])' in routes_py
    assert '@app.route("/api/cloud-drive/storage-upgrades/purchase", methods=["POST"])' in routes_py
    assert "root 不需要用積分購買容量" in routes_py
    assert "purchased_extra_bytes" in upload_security_py
    assert "+storage_purchase" in upload_security_py


def test_core_api_fetch_refreshes_csrf_once():
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")

    assert "async function apiFetch" in core_js
    assert 'payload.error !== "csrf_invalid"' in core_js
    assert "fetchCsrfToken({ force: true })" in core_js
    assert "return apiFetch(url, { ...options, credentials: opts.credentials, headers: retryHeaders }, false);" in core_js
    assert 'headers.set("X-CSRF-Token", await fetchCsrfToken());' in core_js
    assert "BroadcastChannel" in core_js


def test_cloud_drive_e2ee_upload_prepares_required_crypto_fields():
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert "async function prepareDriveE2eeUpload(file, includeClientScanReport = false)" in drive_js
    assert "window.crypto.subtle.generateKey" in drive_js
    assert "encrypted_file_key" in drive_js
    assert 'form.append("encrypted_file_key", encrypted.encrypted_file_key)' in drive_js
    assert 'form.append("encrypted_metadata", encrypted.encrypted_metadata)' in drive_js
    assert 'form.append("ciphertext_sha256", encrypted.ciphertext_sha256)' in drive_js
    assert 'form.append("encryption_algorithm", encrypted.encryption_algorithm)' in drive_js
    assert 'form.append("encryption_version", encrypted.encryption_version)' in drive_js
    assert 'form.append("nonce", encrypted.nonce)' in drive_js
    assert 'form.append("file", encrypted.blob, encrypted.filename)' in drive_js
    assert "browser_local_vault_key" in drive_js
    assert "此瀏覽器不支援端到端加密上傳" in drive_js


def test_cloud_drive_e2ee_download_decrypts_in_browser():
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert "async function unwrapDriveFileKey(encryptedFileKey)" in drive_js
    assert "async function decryptDriveE2eeBlob(blob, e2ee)" in drive_js
    assert "/e2ee-key" in drive_js
    assert "const decrypted = await decryptDriveE2eeBlob(blob, keyJson.e2ee);" in drive_js
    assert "outputBlob = decrypted.blob" in drive_js
    assert "name = decrypted.filename || name" in drive_js
    assert "原本的本地 vault key 已不存在" in drive_js
