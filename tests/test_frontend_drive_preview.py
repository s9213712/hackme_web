from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_drive_preview_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    server_py = (ROOT / "server.py").read_text(encoding="utf-8")

    assert 'id="drive-preview-card"' in index_html
    assert 'id="drive-preview-panel"' in index_html
    assert "async function previewDriveFile(fileId)" in drive_js
    assert "/preview/content" in drive_js
    assert "drive-preview-archive" in drive_js
    assert "drive-preview-text" in drive_js
    assert "closeDrivePreview()" in drive_js
    assert 'preview.category === "image"' in drive_js
    assert '"img-src":     "\'self\' data: blob:"' in server_py
    assert '"media-src":   "\'self\' blob:"' in server_py
    assert '"frame-src":   "\'self\' blob:"' in server_py


def test_filemanager_and_albummanager_ui_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="storage-upload-file"' in index_html
    assert 'id="storage-folder-path"' in index_html
    assert 'id="storage-folder-list"' in index_html
    assert 'id="storage-organize-path"' in index_html
    assert 'id="storage-file-list"' in index_html
    assert 'id="storage-trash-list"' in index_html
    assert 'id="album-create-title"' in index_html
    assert 'id="album-create-description"' in index_html
    assert 'id="album-target-select"' in index_html
    assert 'id="album-list"' in index_html
    assert 'id="album-detail-card"' in index_html
    assert 'id="album-file-list"' in index_html
    assert "不列出，持連結可看" in index_html
    assert "async function uploadStorageFile()" in drive_js
    assert "async function createStorageFolder()" in drive_js
    assert "async function organizeSelectedStorageFile()" in drive_js
    assert "async function moveStorageFileFromRow(id, currentPath)" in drive_js
    assert "async function moveCloudFileToStorage(fileId, name)" in drive_js
    assert "async function moveStorageFolder()" in drive_js
    assert "async function createAlbum()" in drive_js
    assert "async function openAlbum(id" in drive_js
    assert "async function saveAlbumDetail()" in drive_js
    assert "async function removeAlbumFile(albumId, albumFileId)" in drive_js
    assert "請輸入相簿 id" not in drive_js
    assert 'id="storage-breadcrumb"' in index_html
    assert 'id="storage-selection-label"' in index_html
    assert 'data-drive-action="open-storage-folder"' in drive_js
    assert 'data-drive-action="move-storage-file"' in drive_js
    assert 'data-drive-action="move-cloud-to-storage"' in drive_js
    assert 'data-drive-action="edit-text" data-file-id="${sanitize(file.id)}">編輯文字</button>' not in drive_js
    assert 'id="storage-organize-btn"' not in index_html
    assert "loadStorageFiles(csrf)" in drive_js
    assert 'storageUploadBtn.addEventListener("click", openStorageUploadPicker)' in bootstrap_js
    assert 'storageUploadFile.addEventListener("change", uploadStorageFile)' in bootstrap_js
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
    assert '/js/35-drive.js?v=20260429-torrent-upload' in index_html
    assert '/styles.css?v=20260429-sidebar-polish' in index_html
    assert '/js/00-core.js?v=20260429-sidebar-polish' in index_html
    assert '/js/50-admin.js?v=20260429-sidebar' in index_html
    assert "onclick=" not in index_html
    assert "onclick=" not in drive_js
    assert "data-drive-action" in drive_js
    assert "driveTransferRows" in drive_js
    assert "xhrUploadWithProgress" in drive_js
    assert "/cloud-drive/remote-download/tasks" in drive_js
    assert 'id="drive-remote-torrent-file"' in index_html
    assert "/cloud-drive/remote-download/torrent-tasks" in drive_js
    assert "FormData" in drive_js
    assert "async function loadAlbumGallery()" in drive_js
    assert "async function openAlbumViewer(id)" in drive_js
    assert 'tabModuleAlbums.style.display = canAccessModule("privacy_uploads") ? "" : "none"' in core_js
    assert "SIDEBAR_MENU_CONFIG" in core_js
    assert "SIDEBAR_ICON_PATHS" in core_js
    assert "sidebar-footer" in index_html
    assert "sidebar-current-user" in index_html
    assert "SIDEBAR_COLLAPSED_STORAGE_KEY" in core_js
    assert "localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY" in core_js
    assert "data-sidebar-action" in core_js
    assert 'switchModuleTab("albums")' in bootstrap_js
    assert "sidebarToggle.addEventListener" in bootstrap_js
    assert 'normTab === "albums"' in admin_js


def test_cloud_drive_privacy_modes_use_human_labels():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert 'value="private_scannable">私密檔案（伺服器掃毒後保存）' in index_html
    assert 'value="public_attachment">公開附件（可預覽、可分享）' in index_html
    assert 'value="e2ee_vault">端到端加密（站方無法讀取）' in index_html
    assert 'value="e2ee_vault_with_client_scan">端到端加密（附本機掃描回報）' in index_html
    assert "drivePrivacyModeLabel(file.privacy_mode)" in drive_js
    assert "root/admin 上限：儲存磁碟可用空間 90%" in drive_js
    assert "warning_active" in drive_js
