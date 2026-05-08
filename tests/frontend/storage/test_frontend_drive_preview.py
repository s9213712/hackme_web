from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_cloud_drive_preview_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))
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
    assert 'class="drive-archive-list"' in drive_js
    assert 'class="drive-archive-entry"' in drive_js
    assert 'class="drive-archive-kind"' in drive_js
    assert 'class="drive-archive-entry-meta"' in drive_js
    assert "壓縮後" in drive_js
    assert '".7z", ".rar", ".tar", ".gz"' in drive_js
    assert "closeDrivePreview()" in drive_js
    assert "async function previewDriveE2eeFile(fileId)" in drive_js
    assert "decryptDriveE2eeFileForSession" in drive_js
    assert "function normalizeDrivePreviewBlobMime(blob, expectedMime = \"\")" in drive_js
    assert "new Blob([blob], { type: targetMime })" in drive_js
    assert "function drivePreviewUsesDirectStream(preview)" in drive_js
    assert 'return category === "audio" || category === "video" || category === "pdf";' in drive_js
    assert "async function resolveDrivePreviewMediaUrl(fileId, csrf, preview" in drive_js
    assert 'return drivePreviewContentUrl(fileId);' in drive_js
    assert "function renderDrivePdfPreview(url, title, { encrypted = false } = {})" in drive_js
    assert '這份 PDF 已在瀏覽器解密。若內嵌檢視器無法開啟，請改用新分頁或直接下載。' in drive_js
    assert '若瀏覽器內建 PDF 檢視器未載入，請改用新分頁開啟或直接下載。' in drive_js
    assert '<iframe src="${url}" title="${safeTitle}" loading="lazy"></iframe>' in drive_js
    assert '在新分頁開啟 PDF' in drive_js
    assert '下載 PDF' in drive_js
    assert "driveE2eeSessionPassphrases" in drive_js
    assert "driveE2eeRecentSessionPassphrases" in drive_js
    assert "clearDriveE2eeSessionPassphrases" in (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    assert "return previewAlbumFileFullscreen(fileId, options.fileName || \"\")" in drive_js
    assert 'preview.category === "video"' in drive_js
    assert 'preview.category === "audio"' in drive_js
    assert '<audio controls preload="metadata" src="${url}"></audio>' in drive_js
    assert '<video controls preload="metadata" playsinline src="${url}"></video>' in drive_js
    assert 'preview.category === "pdf"' in drive_js
    assert 'preview.category === "image"' in drive_js
    assert '"img-src":     "\'self\' data: blob:"' in server_py
    assert '"media-src":   "\'self\' blob:"' in server_py
    assert '"frame-src":   "\'self\' blob:"' in server_py
    assert '"object-src":  "\'none\'"' in server_py
    styles_css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".drive-preview-panel object," in styles_css
    assert ".album-full-preview-body object," in styles_css
    assert ".drive-pdf-preview {" in styles_css
    assert ".drive-pdf-preview iframe {" in styles_css
    assert ".drive-archive-list {" in styles_css
    assert ".drive-archive-entry {" in styles_css
    assert ".drive-archive-kind {" in styles_css


def test_filemanager_and_albummanager_ui_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="storage-upload-file"' in index_html
    assert 'id="storage-folder-upload-btn"' in index_html
    assert 'id="drive-remote-download-btn"' in index_html
    assert 'id="drive-remote-torrent-inline-btn"' in index_html
    assert 'id="storage-upload-folder"' in index_html
    assert "webkitdirectory" in index_html
    assert 'id="storage-folder-path"' in index_html
    assert 'id="storage-browser-list"' in index_html
    assert 'id="storage-organize-path"' in index_html
    assert 'id="storage-file-list"' not in index_html
    assert 'id="storage-trash-list"' in index_html
    assert 'id="album-create-title"' in index_html
    assert 'id="album-create-description"' in index_html
    assert 'id="album-create-share-password"' in index_html
    assert 'id="album-edit-share-password"' in index_html
    assert 'id="album-edit-clear-share-password"' in index_html
    assert 'id="album-picker-select"' in index_html
    assert 'id="album-smart-strategy"' in index_html
    assert 'data-drive-action="smart-organize-albums"' in index_html
    assert 'id="album-list"' in index_html
    assert 'id="album-detail-card"' in index_html
    assert 'id="album-file-list"' not in index_html
    assert "不列出，持連結可看" in index_html
    assert "async function uploadStorageFile()" in drive_js
    assert "async function uploadStorageFolder()" in drive_js
    assert "async function smartOrganizeAlbums()" in drive_js
    assert 'storageAction("/storage/albums/smart-organize", "POST"' in drive_js
    assert 'action === "smart-organize-albums"' in drive_js
    assert "function openStorageFolderUploadPicker()" in drive_js
    assert "function storageUploadRelativePath(file)" in drive_js
    assert "file?.webkitRelativePath" in drive_js
    assert 'form.append("virtual_path", virtualPath)' in drive_js
    assert "async function createStorageFolder()" in drive_js
    assert "async function organizeSelectedStorageFile()" in drive_js
    assert "async function renameStorageFile(id, currentPath, currentName = \"\")" in drive_js
    assert "async function moveStorageFileFromRow(id, currentPath)" in drive_js
    assert "async function renameStorageFolder(path, currentName = \"\")" in drive_js
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
    assert 'data-drive-action="rename-storage-folder"' in drive_js
    assert 'data-drive-action="rename-storage-file"' in drive_js
    assert 'data-drive-action="move-storage-file"' in drive_js
    assert 'data-drive-action="move-cloud-to-storage"' in drive_js
    assert 'data-drive-action="folder-to-album"' in drive_js
    assert 'item.status === "failed"' in drive_js
    assert "下載失敗" in drive_js
    assert 'data-drive-action="dismiss-transfer"' in drive_js
    assert "dismissRemoteDownloadTask" in drive_js
    assert "DRIVE_TRANSFER_FAILED_VISIBLE_MS" in drive_js
    assert "DRIVE_REMOTE_STATUS_RETRY_LIMIT" in drive_js
    assert "consecutiveStatusErrors" in drive_js
    assert "狀態暫時讀取失敗，正在重試" in drive_js
    assert 'setTimeout(() => dismissRemoteDownloadTask(task.id, transferId)' not in drive_js
    assert "findDriveTransferRowIdForTask" in drive_js
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
    assert 'driveRemoteDownloadBtn.addEventListener("click", promptRemoteDriveDownloadUrl)' in bootstrap_js
    assert 'driveRemoteTorrentFile.addEventListener("change", () => startRemoteDriveDownload({ source: "torrent"' in bootstrap_js
    assert 'storageFolderCreateBtn.addEventListener("click", createStorageFolder)' in bootstrap_js
    assert 'storageFolderMoveBtn.addEventListener("click", moveStorageFolder)' in bootstrap_js
    assert 'albumCreateBtn.addEventListener("click", createAlbum)' in bootstrap_js


def test_album_viewer_has_dedicated_module():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (
        (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "public" / "js" / "51-admin-server-mode-launch-check.js").read_text(encoding="utf-8")
    )
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
    assert '/js/35-drive.js?v=20260504-drive-media-rename' in index_html
    assert '/styles.css?v=20260505-workflow-preset' in index_html
    assert '/js/00-core.js?v=20260503-appearance-v2' in index_html
    assert '/js/40-auth-users.js?v=20260503-appearance-reset' in index_html
    assert 'src="/js/50-admin.js' in index_html
    assert 'id="root-storage-user-select"' in index_html
    assert 'id="root-storage-save-btn"' in index_html
    assert 'id="root-storage-users"' in index_html
    assert "function loadRootStorageUsers" in admin_js
    assert "function saveRootStorageOverride" in admin_js
    assert '"/root/storage/users"' in admin_js
    assert 'rootStorageSave.addEventListener("click", saveRootStorageOverride)' in bootstrap_js
    album_module_html = index_html.split('id="module-albums"', 1)[1].split('id="module-comfyui"', 1)[0]
    assert "onclick=" not in album_module_html
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
    assert "function openChatAttachmentPicker()" in drive_js
    assert "function attachmentStoragePath(file, prefix = \"attachment\")" in drive_js
    assert 'joinStoragePath("/attachments", uniqueName)' in drive_js
    assert 'form.append("virtual_path", attachmentStoragePath(selectedFile, contextType || "attachment"))' in drive_js
    assert 'form.append("display_name", selectedFile.name || "attachment.bin")' in drive_js
    assert 'data-drive-action="delete-context-attachment"' in drive_js
    assert "async function deleteContextAttachment" in drive_js
    assert "/cloud-drive/refs/${encodeURIComponent(refId)}/delete" in drive_js
    assert "附件編號讀取失敗" in drive_js
    assert "loadChatMessages(selectedChatRoomId" in drive_js
    assert '<select id="chat-attachment-existing-file-id">' in index_html
    assert 'id="chat-attachment-pick-btn"' in index_html
    assert 'id="chat-attachment-upload-btn"' not in index_html
    assert 'id="chat-attachment-existing-btn"' not in index_html
    assert 'form.append("virtual_path", attachmentStoragePath(selectedFile, "chat"))' in drive_js
    assert 'form.append("virtual_path", attachmentStoragePath(selectedFile, "announcement"))' in drive_js
    assert "dm-attachment-existing-file-id" in drive_js
    assert '<select id="announcement-attachment-existing-file-id">' in index_html
    assert 'placeholder="file_id"' not in index_html
    assert "chat-message-image-preview" in drive_js
    assert "driveTransferRows" in drive_js
    assert "xhrUploadWithProgress" in drive_js
    assert "data-folder-path" in drive_js
    assert "function storageFolderRowPathFromEventTarget(target)" in drive_js
    assert 'document.addEventListener("dblclick", (event) => {' in drive_js
    assert 'target.closest(".drive-file-actions")' in drive_js
    assert 'openStorageFolder(folderPath).catch((err) => alert(err.message || "開啟資料夾失敗"))' in drive_js
    assert "/cloud-drive/remote-download/tasks" in drive_js
    assert "async function restoreRemoteDownloadTasks()" in drive_js
    assert "resumeRemoteDownloadTaskPolling(task)" in drive_js
    assert "function classifyRemoteDownloadInput(rawUrl" in drive_js
    assert "torrentUrlsAsBt" in drive_js
    assert "function promptRemoteDriveDownloadUrl()" in drive_js
    assert "function openRemoteTorrentPicker()" in drive_js
    assert "magnet link 或 .torrent URL" in drive_js
    assert "download_mode: effectiveMode" in drive_js
    assert 'source: "torrent-url"' in drive_js
    assert 'id="drive-remote-torrent-file"' in index_html
    assert 'id="drive-remote-torrent-btn"' in index_html
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
    assert "let blob = await fetchDrivePreviewBlob(file.file_id, csrf);" in drive_js
    assert "const remembered = getRememberedDriveE2eeSessionPassphrase(file.file_id);" in drive_js
    assert "buildDriveE2eePreview(file.file_id, csrf)" in drive_js
    assert "const blob = await fetchDrivePreviewContent(file.file_id, csrf);" not in drive_js
    assert 'data-drive-action="add-cloud-to-album"' in drive_js
    assert 'tabModuleAlbums.style.display = (canAccessModule("privacy_uploads") && isFeatureEnabledForUi("feature_storage_albums_enabled", false)) ? "" : "none"' in core_js
    assert "SIDEBAR_MENU_CONFIG" in core_js
    assert '{ label: "相簿", action: "module:albums" }' not in core_js
    assert 'requiresFeatures: ["feature_storage_albums_enabled"]' in core_js
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
    assert 'id="server-mode-token-hint"' in index_html
    assert 'id="server-mode-internal-test-panel" style="display:none;"' in index_html
    assert 'id="server-mode-tester-token-panel" style="display:none;"' in index_html
    assert 'id="internal-test-token-usage-wrap" class="security-profile-preview" style="display:none;"' in index_html
    assert 'id="tester-token-usage-wrap" class="security-profile-preview" style="display:none;"' in index_html
    assert "這顆 token 只綁定指定帳號" in index_html
    assert 'id="internal-test-token-user-id"' in index_html
    assert 'id="internal-test-token-username"' in index_html
    assert "這不是登入 token，不能拿去填 <code>/api/login</code>" in index_html
    assert "loadCurrentSecurityProfileDraft" in admin_js
    assert "renderSecurityProfilePreview" in admin_js
    assert "function applySecurityProfileToInputs" in admin_js
    assert "function applySecurityProfileDataToInputs" in admin_js
    assert "function previewSecurityProfileSelection" in admin_js
    assert "function bindSecurityProfileSelect" in admin_js
    assert "function updateServerModeTokenPanels(modeOverride = null)" in admin_js
    assert 'const usage = $("internal-test-token-usage-wrap");' in admin_js
    assert 'const usage = $("tester-token-usage-wrap");' in admin_js
    assert '"feature_audit_log_enabled"' in admin_js
    assert '"feature_economy_enabled"' in admin_js
    assert "FEATURE_SERVICE_BUNDLES" in admin_js
    assert '"all-enabled"' in admin_js
    assert '"minimum-ops"' in admin_js
    assert "全開" in admin_js
    assert "最低維運" in admin_js
    assert "bundle.replace === true" in admin_js
    assert "feature-bundle-toolbar" in index_html
    assert "feature-advisory-list" in index_html
    assert 'id="sc-feature-audit-log-enabled"' in index_html
    assert 'id="sc-feature-economy-enabled"' in index_html
    assert 'previewSecurityProfileSelection("security-mode-select", "security-mode-profile-preview", "sc")' in bootstrap_js
    assert 'previewSecurityProfileSelection("server-mode-select", "server-mode-profile-preview", "s")' in bootstrap_js
    assert 'bindSecurityProfileSelect("security-mode-select", "security-mode-profile-preview", "sc")' in admin_js
    assert 'bindSecurityProfileSelect("server-mode-select", "server-mode-profile-preview", "s")' in admin_js
    assert "按套用才會寫入伺服器" in admin_js
    assert "await loadSettings();" in admin_js
    assert "populateProfileSelect(\"server-mode-select\"" in admin_js
    assert 'updateServerModeTokenPanels(serverModeSelect.value)' in bootstrap_js
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
    assert "renderStorageFeatureDisabled" in drive_js
    assert ".drive-collapsible-panel" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".settings-feature-advisory" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".album-preview-nav" in (ROOT / "public" / "styles.css").read_text(encoding="utf-8")


def test_album_preview_category_uses_storage_name_before_uploaded_metadata():
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))

    assert 'const name = file?.display_name || file?.virtual_path || file?.original_filename_plain_for_public || file?.storage_path || "";' in drive_js
    assert 'const canTryPreview = category === "image" || category === "metadata";' in drive_js
    assert '["image", "metadata"].includes(driveFileCategory(file))' in drive_js
    assert 'startsWith("image/")' in drive_js


def test_album_gallery_layout_wraps_long_filenames():
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))

    assert 'class="drive-gallery-file-info"' in drive_js
    assert ".drive-gallery-tile {" in css
    assert "overflow: hidden;" in css
    assert ".drive-gallery-tile strong" in css
    assert "overflow-wrap: anywhere;" in css
    assert "word-break: break-word;" in css


def test_cloud_drive_privacy_modes_use_human_labels():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))

    assert 'value="standard_plain">一般檔案（可掃毒、可預覽、可分享）' in index_html
    assert 'value="server_encrypted">伺服器端加密（磁碟密文、下載明文）' in index_html
    assert 'value="e2ee">端到端加密（站方無法讀取）' in index_html
    assert "三種模式怎麼選" in index_html
    assert "非 E2EE 會讓伺服器取得明文" in index_html
    assert "E2EE 上傳時附本機掃描回報" in index_html
    assert "新增文檔" in index_html
    assert 'data-drive-action="create-text-document"' in index_html
    assert "virtual_path: joinStoragePath(currentStoragePath, filename)" in drive_js
    assert "drivePrivacyModeLabel(file.privacy_mode)" in drive_js
    assert "DRIVE_PRIVACY_MODE_COMPARISON" in drive_js
    assert "伺服器端加密" in drive_js
    assert "站方無法讀取" in drive_js
    assert "driveRenderTextPreview" in drive_js
    assert "driveHighlightCode" in drive_js
    assert "需密碼預覽" in drive_js
    assert "解密預覽" in drive_js
    assert "isDriveE2eeServerPreviewError" in drive_js
    assert "return previewDriveE2eeFile(fileId);" in drive_js
    assert "root 上限：儲存磁碟可用空間 90%" in drive_js
    assert "manager 上限：1 GB" in drive_js
    assert "warning_active" in drive_js


def test_cloud_drive_storage_upgrade_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))
    routes_py = (ROOT / "routes" / "files.py").read_text(encoding="utf-8")
    upload_security_py = (ROOT / "services" / "security" / "upload_security.py").read_text(encoding="utf-8")

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
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))

    assert "async function prepareDriveE2eeUpload(file, passphrase, includeClientScanReport = false)" in drive_js
    assert "window.crypto.subtle.generateKey" in drive_js
    assert "deriveDriveE2eePassphraseKey" in drive_js
    assert "PBKDF2" in drive_js
    assert "encrypted_file_key" in drive_js
    assert 'form.append("encrypted_file_key", encrypted.encrypted_file_key)' in drive_js
    assert 'form.append("encrypted_metadata", encrypted.encrypted_metadata)' in drive_js
    assert 'form.append("ciphertext_sha256", encrypted.ciphertext_sha256)' in drive_js
    assert 'form.append("encryption_algorithm", encrypted.encryption_algorithm)' in drive_js
    assert 'form.append("encryption_version", encrypted.encryption_version)' in drive_js
    assert 'form.append("nonce", encrypted.nonce)' in drive_js
    assert 'form.append("file", encrypted.blob, encrypted.filename)' in drive_js
    assert 'const originalName = file.name || "未命名檔案";' in drive_js
    assert "filename: originalName" in drive_js
    assert "vault.bin" not in drive_js
    assert "browser_passphrase_pbkdf2_v2" in drive_js
    assert "localStorage.getItem(DRIVE_E2EE" not in drive_js
    assert "此瀏覽器不支援端到端加密上傳" in drive_js


def test_cloud_drive_e2ee_download_decrypts_in_browser():
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))

    assert "async function unwrapDriveFileKey(encryptedFileKey, passphrase)" in drive_js
    assert "async function decryptDriveE2eeBlob(blob, e2ee, passphrase)" in drive_js
    assert "/e2ee-key" in drive_js
    assert "/preview/content" in drive_js
    assert "askDriveE2eePassphrase" in drive_js
    assert "getDriveE2eeSessionPassphrase" in drive_js
    assert "function rememberDriveE2eeSessionPassphrase(fileId, passphrase)" in drive_js
    assert "function getRememberedDriveE2eeSessionPassphrase(fileId)" in drive_js
    assert "function rememberDriveE2eeRecentSessionPassphrase(passphrase)" in drive_js
    assert "function getDriveE2eeSessionPassphraseCandidates(fileId)" in drive_js
    assert "driveE2eeRecentSessionPassphrases.forEach(addCandidate);" in drive_js
    assert "for (const passphrase of getDriveE2eeSessionPassphraseCandidates(fileId))" in drive_js
    assert "const passphrase = await getDriveE2eeSessionPassphrase(fileId, promptText, { force: true });" in drive_js
    assert "const decrypted = await decryptDriveE2eeBlob(blob, keyJson.e2ee, passphrase);" in drive_js
    assert "rememberDriveE2eeSessionPassphrase(fileId, passphrase);" in drive_js
    assert "const remembered = getRememberedDriveE2eeSessionPassphrase(file.file_id);" in drive_js
    assert "buildDriveE2eePreview(file.file_id, csrf)" in drive_js
    assert "image · E2EE" in drive_js
    assert "outputBlob = decrypted.blob" in drive_js
    assert "name = decrypted.filename || name" in drive_js
    assert "伺服器無法重設或找回此密碼" in drive_js


def test_share_link_copy_buttons_have_clipboard_fallback():
    """Issue #176 / #177 regression guard.

    Both `copyAlbumShareUrl` (drive) and `copyVideoLink` (videos) call
    `navigator.clipboard.writeText`, which is undefined in non-secure
    contexts (HTTP). The fallback MUST give the user a way to manually
    select+copy the URL — not just flash a toast that disappears."""
    drive_js = ((ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8") + "\n" + (ROOT / "public" / "js" / "35-drive-preview-share.js").read_text(encoding="utf-8"))
    video_js = (ROOT / "public" / "js" / "39-videos.js").read_text(encoding="utf-8")

    # Drive: prompt-based fallback is OK (user can select+copy).
    assert "async function copyAlbumShareUrl(url)" in drive_js
    assert "navigator.clipboard.writeText(shareUrl)" in drive_js
    assert 'window.prompt("分享連結"' in drive_js, (
        "drive copyAlbumShareUrl must offer a window.prompt fallback so the "
        "URL is selectable when navigator.clipboard is unavailable"
    )

    # Videos: assert copyVideoLink has a fallback that lets the user
    # actually copy the URL (window.prompt OR a persistent visible element).
    assert "async function copyVideoLink(videoId)" in video_js
    assert "navigator.clipboard.writeText(url)" in video_js
    has_prompt_fallback = "window.prompt" in video_js
    has_input_fallback = (
        "select()" in video_js and "execCommand" in video_js
    )
    assert has_prompt_fallback or has_input_fallback, (
        "copyVideoLink fallback must offer a way for the user to manually "
        "select and copy the URL when navigator.clipboard is unavailable. "
        "videoMsg(url, true) alone is a transient toast and not selectable. "
        "See issue #176."
    )
