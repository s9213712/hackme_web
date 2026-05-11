from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


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
    assert "function videoPlaybackUrl(video)" in videos_js
    assert "playback_url" in videos_js
    assert 'form.append("cover", coverFile)' in videos_js
    assert 'form.append("cloud_file_id", payload.cloud_file_id)' in videos_js
    assert "} else if (coverFile) {" in videos_js
    assert "video-thumb-image" in videos_js
    assert "video-thumb-audio" in videos_js
    assert "browserSupportsNativeHls" in videos_js
    assert "loadVideoHlsLibrary" in videos_js
    assert "attachVideoHlsJsPlayer" in videos_js
    assert "/js/hls.light.min.js?v=20260505-hlsjs" in videos_js
    assert "/js/vendor/hls.light.min.js" not in videos_js
    assert "HLS.js" in videos_js
    assert "HLS 串流" in videos_js
    assert "function humanVideoStreamStatus" in videos_js
    assert "data-video-prepare-stream" in videos_js
    assert "prepareVideoStream" in videos_js
    assert "VIDEO_SHARE_FRAGMENT_STORAGE_KEY" in videos_js
    assert "VIDEO_E2EE_STREAM_V2_WORKER_URL" in videos_js
    assert "/js/e2ee-stream-v2-worker.js?v=20260505-e2eev2" in videos_js
    assert "/js/workers/e2ee-stream-v2-worker.js" not in videos_js
    assert "buildVideoE2eeShareEnvelope" in videos_js
    assert "prepareVideoE2eeShareArtifacts" in videos_js
    assert "buildVideoE2eeStreamV2Package" in videos_js
    assert "uploadVideoE2eeStreamV2Package" in videos_js
    assert 'share_wrapped_file_key_envelope' in videos_js
    assert 'share_expires_at' in videos_js
    assert 'share_max_views' in videos_js
    assert 'remaining_views' in videos_js
    assert 'state_message' in videos_js
    assert 'password_locked_until' in videos_js
    assert 'data-video-share-regenerate' in videos_js
    assert 'data-video-share-revoke' in videos_js
    assert 'data-video-share-save' in videos_js
    assert 'data-video-share-clear-password' in videos_js
    assert 'share_fragment_key' in videos_js
    assert 'getRememberedVideoShareFragment' in videos_js
    assert 'mode === "e2ee_stream_v2"' in videos_js
    assert 'mode === "e2ee_direct"' in videos_js
    assert "fetchVideoE2eeChunkWithRetry" in videos_js
    assert "pruneVideoE2eeChunkCache" in videos_js
    assert "videoE2eeChunkIndexForTime" in videos_js
    assert "正在追上快轉目標" in videos_js
    assert 'setVideoPlaybackActionButton(' in videos_js
    assert '開始 E2EE 播放' in videos_js
    assert '未按下播放前，不會主動要求 E2EE 密碼。' in videos_js
    assert '完整分享連結' in videos_js
    assert '伺服器無法復原，只能重新產生分享' in videos_js
    assert '重新產生此分享時，瀏覽器會要求發布者再次輸入原始 E2EE 密碼' in videos_js
    assert ".video-audio-player" in styles
    assert ".video-thumb-image" in styles
    assert ".video-share-manage-grid" in styles


def test_video_platform_uses_separate_watch_view_and_mobile_layout():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    videos_js = (ROOT / "public" / "js" / "39-videos.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="video-browse-view"' in index_html
    assert 'id="video-watch-view"' in index_html
    assert "function showVideoBrowseView" in videos_js
    assert "function showVideoWatchView" in videos_js
    assert "/playback" in videos_js
    assert "video-back-btn" in videos_js
    assert "#videos/" in videos_js
    assert '<a class="video-card" href="#videos/${Number(video.id || 0)}" data-video-open=' in videos_js
    assert 'event.preventDefault();' in videos_js
    assert 'class="video-thumb-media"' in videos_js
    assert "#t=0.1" in videos_js
    assert 'share_requires_fragment_key' in videos_js
    assert 'strict E2EE' in videos_js
    assert '正在使用 E2EE Streaming v2' in videos_js
    assert 'MediaSource' in videos_js
    assert 'Web Worker' in videos_js
    assert '分享連結與設定已更新。' in videos_js
    assert '分享連結已撤銷' in videos_js
    assert 'videoShareStateSummary' in videos_js
    assert 'saveVideoShareSettings' in videos_js
    assert '已改用直接串流' in videos_js
    assert 'id="video-playback-action"' in videos_js
    assert "@media (max-width: 720px)" in styles
    assert "#module-videos .admin-tools" in styles
    assert ".video-watch-topbar" in styles
    assert ".video-thumb-media" in styles
    assert "pointer-events: none" in styles
    assert '#video-playback-status[data-state="error"]' in styles


def test_video_share_copy_and_shared_page_guardrails_are_visible_in_ui_code():
    videos_js = (ROOT / "public" / "js" / "39-videos.js").read_text(encoding="utf-8")
    shared_page = (ROOT / "public" / "js" / "shared-video.js").read_text(encoding="utf-8")

    assert 'await navigator.clipboard.writeText(url);' in videos_js
    assert 'videoMsg("連結已複製", true);' in videos_js
    assert 'window.prompt("分享連結", url);' in videos_js
    assert "此 E2EE 分享連結的本機片段金鑰不可復原；若遺失只能重新產生分享。" in videos_js
    assert "AbortController" in shared_page
    assert "setTimeout(() => controller.abort(), 10000);" in shared_page
    assert 'loadSharedVideo().catch((err) => setMsg(err.message || "分享影音載入失敗", true));' in shared_page
    assert "/js/hls.light.min.js?v=20260505-hlsjs" in shared_page
    assert "/js/e2ee-stream-v2-worker.js?v=20260505-e2eev2" in shared_page
    assert "fetchSharedE2eeChunkWithRetry" in shared_page
    assert "pruneSharedE2eeChunkCache" in shared_page
    assert "sharedE2eeChunkIndexForTime" in shared_page
    assert "正在追上快轉目標" in shared_page
    assert "/js/vendor/hls.light.min.js" not in shared_page
    assert "/js/workers/e2ee-stream-v2-worker.js" not in shared_page


def test_shared_video_page_layout_is_viewport_bounded():
    html = (ROOT / "routes" / "videos.py").read_text(encoding="utf-8")

    assert "min-height:100dvh" in html
    assert "#player-host video" in html
    assert "max-height:min(64dvh, 560px)" in html
    assert "max-height:min(48dvh, calc(100dvh - 210px))" in html
    assert "@media (max-height: 520px) and (orientation: landscape)" in html
    assert 'mimetype="text/html"' in html
    assert 'mimetype="text/html; charset=utf-8"' not in html
