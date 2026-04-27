from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_drive_preview_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")

    assert 'id="drive-preview-card"' in index_html
    assert 'id="drive-preview-panel"' in index_html
    assert "async function previewDriveFile(fileId)" in drive_js
    assert "/preview/content" in drive_js
    assert "drive-preview-archive" in drive_js
    assert "drive-preview-text" in drive_js


def test_filemanager_and_albummanager_ui_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="storage-upload-file"' in index_html
    assert 'id="storage-file-list"' in index_html
    assert 'id="storage-trash-list"' in index_html
    assert 'id="album-create-title"' in index_html
    assert 'id="album-list"' in index_html
    assert "async function uploadStorageFile()" in drive_js
    assert "async function createAlbum()" in drive_js
    assert "loadStorageFiles(csrf)" in drive_js
    assert 'storageUploadBtn.addEventListener("click", uploadStorageFile)' in bootstrap_js
    assert 'albumCreateBtn.addEventListener("click", createAlbum)' in bootstrap_js
