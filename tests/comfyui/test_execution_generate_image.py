"""Regression for services.comfyui.execution.generate_image()."""

from services.comfyui import execution as comfy_execution


class _GeneratedImage:
    filename = "done.png"
    subfolder = ""
    type = "output"
    mime_type = "image/png"
    data = b"png"


def test_generate_image_accepts_generate_from_workflow_func():
    called = {}

    def _build_generation_workflow(params):
        called["params"] = dict(params)
        return {"3": {"class_type": "KSampler", "inputs": {"steps": params["steps"]}}}

    def _generate_from_workflow(workflow, *, timeout_seconds=1800, expected_count=1, progress_callback=None):
        called["workflow"] = workflow
        called["timeout_seconds"] = timeout_seconds
        called["expected_count"] = expected_count
        if progress_callback:
            progress_callback({"phase": "running", "percent": 50})
        return {"prompt_id": "p1", "images": [{"image_ref": {"filename": "x.png", "subfolder": "", "type": "output"}}]}

    progress_events = []
    result = comfy_execution.generate_image(
        client=object(),
        params={"steps": 30, "batch_size": 2},
        timeout_seconds=77,
        progress_callback=progress_events.append,
        build_generation_workflow_func=_build_generation_workflow,
        generate_from_workflow_func=_generate_from_workflow,
        error_cls=RuntimeError,
    )

    assert called["params"] == {"steps": 30, "batch_size": 2}
    assert called["workflow"]["3"]["inputs"]["steps"] == 30
    assert called["timeout_seconds"] == 77
    assert called["expected_count"] == 2
    assert progress_events == [{"phase": "running", "percent": 50}]
    assert result["prompt_id"] == "p1"


def test_wait_for_images_treats_transient_history_timeout_as_recoverable(monkeypatch):
    clock = {"now": 0.0}
    progress_events = []

    class FlakyHistoryClient:
        timeout = 1

        def __init__(self):
            self.calls = 0

        def _json_request(self, path, *, timeout=None):
            assert path == "/history/prompt-1"
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("ComfyUI 連線失敗：timed out")
            return {
                "prompt-1": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {"9": {"images": [{"filename": "done.png", "subfolder": "", "type": "output"}]}},
                }
            }

    def fake_time():
        return clock["now"]

    def fake_sleep(seconds):
        clock["now"] += max(float(seconds), 0.15)

    monkeypatch.setattr(comfy_execution.time, "time", fake_time)
    monkeypatch.setattr(comfy_execution.time, "sleep", fake_sleep)

    images = comfy_execution.wait_for_images(
        FlakyHistoryClient(),
        "prompt-1",
        timeout_seconds=10,
        poll_interval=0.5,
        expected_count=1,
        error_cls=RuntimeError,
        progress_callback=progress_events.append,
    )

    assert images == [{"filename": "done.png", "subfolder": "", "type": "output"}]
    assert any(event.get("backend_unresponsive") is True for event in progress_events)
    assert any(event.get("phase") == "completed" for event in progress_events)


def test_generate_from_workflow_retries_transient_output_fetch(monkeypatch):
    progress_events = []

    class ReadyClient:
        timeout = 1

        def _json_request(self, path, *, method="GET", payload=None, timeout=None):
            if path == "/prompt":
                return {"prompt_id": "prompt-2"}
            assert path == "/history/prompt-2"
            return {
                "prompt-2": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {"9": {"images": [{"filename": "done.png", "subfolder": "", "type": "output"}]}},
                }
            }

    fetch_calls = {"count": 0}

    def flaky_fetcher(image_ref):
        fetch_calls["count"] += 1
        if fetch_calls["count"] == 1:
            raise RuntimeError("ComfyUI 連線失敗：timed out")
        assert image_ref == {"filename": "done.png", "subfolder": "", "type": "output"}
        return _GeneratedImage()

    monkeypatch.setattr(comfy_execution.time, "sleep", lambda _seconds: None)

    result = comfy_execution.generate_from_workflow(
        ReadyClient(),
        {"3": {"class_type": "KSampler", "inputs": {}}},
        timeout_seconds=10,
        expected_count=1,
        progress_callback=progress_events.append,
        error_cls=RuntimeError,
        image_fetcher=flaky_fetcher,
    )

    assert fetch_calls["count"] == 2
    assert result["prompt_id"] == "prompt-2"
    assert result["images"][0]["image_ref"] == {"filename": "done.png", "subfolder": "", "type": "output"}
    assert any(event.get("phase") == "fetching_output" for event in progress_events)


def test_generate_from_workflow_can_skip_output_fetching(monkeypatch):
    class ReadyClient:
        timeout = 1

        def _json_request(self, path, *, method="GET", payload=None, timeout=None):
            if path == "/prompt":
                return {"prompt_id": "prompt-3"}
            assert path == "/history/prompt-3"
            return {
                "prompt-3": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {"9": {"images": [{"filename": "done.png", "subfolder": "", "type": "output"}]}},
                }
            }

    def forbidden_fetcher(_image_ref):
        raise AssertionError("fetch_outputs=False must not pull image bytes into the web job result")

    monkeypatch.setattr(comfy_execution.time, "sleep", lambda _seconds: None)

    result = comfy_execution.generate_from_workflow(
        ReadyClient(),
        {"3": {"class_type": "KSampler", "inputs": {}}},
        timeout_seconds=10,
        expected_count=1,
        fetch_outputs=False,
        error_cls=RuntimeError,
        image_fetcher=forbidden_fetcher,
    )

    assert result["prompt_id"] == "prompt-3"
    assert result["image_ref"] == {"filename": "done.png", "subfolder": "", "type": "output"}
    assert result["data"] == b""
    assert result["images"] == [{
        "image_ref": {"filename": "done.png", "subfolder": "", "type": "output"},
        "mime_type": "image/png",
        "data": b"",
        "size_bytes": 0,
    }]


def test_delete_queue_items_deletes_only_supplied_prompt_ids():
    calls = []

    class QueueClient:
        def _json_request(self, path, *, method="GET", payload=None, timeout=None, allow_non_json=False):
            calls.append({
                "path": path,
                "method": method,
                "payload": payload,
                "timeout": timeout,
                "allow_non_json": allow_non_json,
            })
            return {}

    result = comfy_execution.delete_queue_items(
        QueueClient(),
        ["prompt-1", "", None, "prompt-2"],
        timeout_seconds=7,
    )

    assert result == {}
    assert calls == [{
        "path": "/queue",
        "method": "POST",
        "payload": {"delete": ["prompt-1", "prompt-2"]},
        "timeout": 7,
        "allow_non_json": True,
    }]
