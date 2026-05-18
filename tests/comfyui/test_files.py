from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from services.comfyui.files import fetch_file, normalize_file_ref, safe_local_image_path


class DummyComfyUIError(RuntimeError):
    pass


@dataclass
class DummyComfyUIFile:
    filename: str
    subfolder: str
    type: str
    mime_type: str
    data: bytes


class FakeResponse:
    def __init__(self, data=b"fake-image", content_type="image/png"):
        self._data = data
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._data


class FakeClient:
    timeout = 2

    def _url(self, path):
        return f"http://fake-comfy.test{path}"


def _fetch(file_ref, monkeypatch, fake_urlopen):
    monkeypatch.setattr("services.comfyui.files.urllib.request.urlopen", fake_urlopen)
    return fetch_file(
        FakeClient(),
        file_ref,
        error_cls=DummyComfyUIError,
        file_cls=DummyComfyUIFile,
        accept="image/*",
        empty_label="ComfyUI 圖片",
    )


def test_normalize_file_ref_splits_embedded_subfolder():
    normalized = normalize_file_ref(
        {"filename": "hackme/7/run-a/output.png", "type": "output"},
        error_cls=DummyComfyUIError,
    )

    assert normalized == {"filename": "output.png", "subfolder": "hackme/7/run-a", "type": "output"}


def test_fetch_file_uses_normalized_view_query(monkeypatch):
    requested = []

    def fake_urlopen(req, timeout):
        requested.append(req.full_url)
        return FakeResponse()

    result = _fetch({"filename": "hackme/7/run-a/output.png", "type": "output"}, monkeypatch, fake_urlopen)

    query = parse_qs(urlparse(requested[0]).query)
    assert query == {"filename": ["output.png"], "subfolder": ["hackme/7/run-a"], "type": ["output"]}
    assert result.filename == "output.png"
    assert result.subfolder == "hackme/7/run-a"
    assert result.type == "output"
    assert result.data == b"fake-image"


def test_fetch_file_falls_back_from_output_to_temp_on_404(monkeypatch):
    requested_types = []

    def fake_urlopen(req, timeout):
        query = parse_qs(urlparse(req.full_url).query)
        requested_types.append(query.get("type", [""])[0])
        if requested_types[-1] == "output":
            raise HTTPError(req.full_url, 404, "Not Found", {}, None)
        return FakeResponse(data=b"temp-image")

    result = _fetch({"filename": "preview.png", "type": "output"}, monkeypatch, fake_urlopen)

    assert requested_types == ["output", "temp"]
    assert result.type == "temp"
    assert result.data == b"temp-image"


def test_fetch_file_reports_context_when_all_candidates_404(monkeypatch):
    def fake_urlopen(req, timeout):
        raise HTTPError(req.full_url, 404, "Not Found", {}, None)

    with pytest.raises(DummyComfyUIError) as exc_info:
        _fetch({"filename": "hackme/7/missing.png", "type": "output"}, monkeypatch, fake_urlopen)

    message = str(exc_info.value)
    assert "404 Not Found" in message
    assert "hackme/7/missing.png" in message


def test_safe_local_image_path_accepts_embedded_subfolder(tmp_path):
    path = safe_local_image_path(
        {"filename": "hackme/7/run-a/output.png", "type": "output"},
        error_cls=DummyComfyUIError,
        local_base_dir=str(tmp_path),
    )

    assert path == (tmp_path / "output" / "hackme" / "7" / "run-a" / "output.png").resolve()


@pytest.mark.parametrize(
    "image_ref",
    [
        {"filename": "../secret.png", "type": "output"},
        {"filename": "/secret.png", "type": "output"},
        {"filename": "C:/secret.png", "type": "output"},
        {"filename": "ok.png", "subfolder": "../secret", "type": "output"},
    ],
)
def test_normalize_file_ref_rejects_unsafe_paths(image_ref):
    with pytest.raises(DummyComfyUIError):
        normalize_file_ref(image_ref, error_cls=DummyComfyUIError)
