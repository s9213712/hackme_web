from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_video_platform_accepts_audio_media_in_ui():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    videos_js = (ROOT / "public" / "js" / "39-videos.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'accept="video/*,audio/*"' in index_html
    assert 'id="video-cover-file"' in index_html
    assert 'accept="image/*"' in index_html
    assert "發布影片或音樂" in index_html
    assert "雲端硬碟影音" in index_html
    assert "function isCloudMediaFile" in videos_js
    assert 'mime.startsWith("audio/")' in videos_js
    assert '".mp3"' in videos_js
    assert 'video.media_type === "audio"' in videos_js
    assert "<audio" in videos_js
    assert "video-audio-player" in videos_js
    assert "function videoThumbMarkup(video)" in videos_js
    assert "video.cover_url" in videos_js
    assert 'form.append("cover", coverFile)' in videos_js
    assert 'form.append("cloud_file_id", payload.cloud_file_id)' in videos_js
    assert "} else if (coverFile) {" in videos_js
    assert "video-thumb-image" in videos_js
    assert "video-thumb-audio" in videos_js
    assert ".video-audio-player" in styles
    assert ".video-thumb-image" in styles


def test_video_platform_uses_separate_watch_view_and_mobile_layout():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    videos_js = (ROOT / "public" / "js" / "39-videos.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="video-browse-view"' in index_html
    assert 'id="video-watch-view"' in index_html
    assert "function showVideoBrowseView" in videos_js
    assert "function showVideoWatchView" in videos_js
    assert "video-back-btn" in videos_js
    assert "#videos/" in videos_js
    assert '<a class="video-card" href="#videos/${Number(video.id || 0)}" data-video-open=' in videos_js
    assert 'event.preventDefault();' in videos_js
    assert 'class="video-thumb-media"' in videos_js
    assert "#t=0.1" in videos_js
    assert "@media (max-width: 720px)" in styles
    assert "#module-videos .admin-tools" in styles
    assert ".video-watch-topbar" in styles
    assert ".video-thumb-media" in styles
    assert "pointer-events: none" in styles
