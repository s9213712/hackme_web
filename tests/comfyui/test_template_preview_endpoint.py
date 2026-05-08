"""§8 preview endpoint regression — POST /api/comfyui/templates/preview."""

import io
import json

import pytest
from flask import Flask, request as flask_request

from routes.comfyui_sections.template_routes import register_comfyui_template_routes
from services.comfyui.template.capability import reset_object_info_cache
from services.comfyui.template.preview_store import (
    InMemoryPreviewStore,
)


@pytest.fixture(autouse=True)
def _isolate_object_info_cache():
    reset_object_info_cache()
    yield
    reset_object_info_cache()


# Reused minimal txt2img workflow.
TXT2IMG = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality", "clip": ["4", 1]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5, "denoise": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
}


def _stub_client(*, classes, models=None, samplers=None):
    info = {cls: {"input": {"required": {}}} for cls in classes}
    if "CheckpointLoaderSimple" in info and models is not None:
        info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [list(models)]
    if "KSampler" in info:
        info["KSampler"]["input"]["required"]["sampler_name"] = [list(samplers or ["euler", "dpmpp_2m"])]
        info["KSampler"]["input"]["required"]["scheduler"] = [["normal", "karras"]]

    class _Stub:
        base_url = "http://stub"
        def get_object_info(self):
            return info
    return _Stub()


_SENTINEL = object()


def _build_app(*, actor=_SENTINEL, client=None, store=None):
    """Build a minimal Flask app with the template routes wired up."""
    app = Flask(__name__)

    if actor is _SENTINEL:
        actor = {"id": 1, "username": "alice"}
    actor_box = {"actor": actor}

    def _actor_or_401():
        if actor_box["actor"] is None:
            resp = app.response_class(
                response=json.dumps({"ok": False, "msg": "未登入"}, ensure_ascii=False),
                status=401,
                mimetype="application/json",
            )
            return None, resp
        return dict(actor_box["actor"]), None

    audit_log: list[dict] = []
    def _audit(action, ip, *, user="-", success=True, ua="", detail=""):
        audit_log.append({"action": action, "user": user, "success": success, "detail": detail})

    # `store or InMemoryPreviewStore()` would be wrong here too — see
    # template_routes.py for the empty-__len__ falsy gotcha.
    actual_store = store if store is not None else InMemoryPreviewStore()
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": _actor_or_401,
        "json_resp": lambda payload: app.response_class(
            response=json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
        ),
        "require_csrf": lambda f: f,  # tests skip CSRF
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test-agent",
        "audit": _audit,
        "comfyui_binding": lambda actor: "http://stub" if client is not None else None,
        "client_for_url": lambda binding: client,
        "preview_store": actual_store,
    })
    app.config.update({"actor_box": actor_box, "audit_log": audit_log})
    return app


def test_preview_returns_token_for_valid_workflow():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["preview_token"].startswith("tkn_")
    assert body["capability"]["overall"] == "SUPPORTED"
    assert body["preview_token_ttl_seconds"] == 30 * 60
    # Token is in the store, owned by actor 1
    assert store.get(token=body["preview_token"], user_id=1) is not None


def test_preview_accepts_workflow_text_string():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/preview",
            json={"workflow_text": json.dumps(TXT2IMG)},
        )
    assert rv.status_code == 200


def test_preview_accepts_multipart_upload():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        data = {
            "workflow": (
                io.BytesIO(json.dumps(TXT2IMG).encode("utf-8")),
                "workflow.json",
                "application/json",
            ),
        }
        rv = c.post("/api/comfyui/templates/preview", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True


def test_preview_rejects_ui_graph_format():
    """UI graph (`{"nodes":[...]}`) must be rejected with the format hint."""
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler"}), store=store)
    ui_graph_workflow = {"nodes": [{"id": 1, "type": "CLIPTextEncode"}], "links": []}
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": ui_graph_workflow})
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["ok"] is False
    assert body["stage"] == "sanitize"


def test_preview_rejects_explicitly_denied_class():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler", "ReActorFaceSwap"}), store=store)
    bad = {**TXT2IMG, "10": {"class_type": "ReActorFaceSwap", "inputs": {"image": ["8", 0]}}}
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": bad})
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "allowlist"
    assert "ReActorFaceSwap" in body["denied_classes"]


def test_preview_unauthenticated_returns_401():
    app = _build_app(actor=None, store=InMemoryPreviewStore())
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 401


def test_preview_capability_unsupported_when_client_missing():
    """No ComfyUI binding → capability=UNSUPPORTED, but preview still returns
    a token so the UI can render the analysis panels and tell the user to
    connect ComfyUI first."""
    store = InMemoryPreviewStore()
    app = _build_app(client=None, store=store)
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["capability"]["overall"] == "UNSUPPORTED"
    assert any("ComfyUI" in b for b in body["capability"]["blockers"])


def test_preview_unparseable_json_string_returns_parse_error():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler"}), store=store)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/preview",
            json={"workflow_text": "not json"},
        )
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "parse"


def test_preview_oversized_multipart_rejected():
    store = InMemoryPreviewStore()
    app = _build_app(client=_stub_client(classes={"KSampler"}), store=store)
    blob = b"{" + (b"x" * (260 * 1024)) + b"}"  # 260KB > WORKFLOW_MAX_JSON_BYTES
    data = {"workflow": (io.BytesIO(blob), "workflow.json", "application/json")}
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/preview", data=data, content_type="multipart/form-data")
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "parse"
    assert "上限" in body["msg"]


def test_preview_audits_pass_and_fail_paths():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        c.post("/api/comfyui/templates/preview", json={"workflow": TXT2IMG})
        c.post("/api/comfyui/templates/preview", json={"workflow_text": "garbage"})
    log = app.config["audit_log"]
    actions = [(e["action"], e["success"]) for e in log]
    assert ("COMFYUI_TEMPLATE_PREVIEW_PASS", True) in actions
    assert ("COMFYUI_TEMPLATE_PREVIEW_FAIL", False) in actions
