"""§8 import endpoint regression — POST /api/comfyui/templates/import."""

import json

import pytest
from flask import Flask, request as flask_request

from routes.comfyui_sections.template_routes import register_comfyui_template_routes
from services.comfyui.template.preview_store import InMemoryPreviewStore


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


def _stub_client(*, classes, models=None):
    info = {cls: {"input": {"required": {}}} for cls in classes}
    if "CheckpointLoaderSimple" in info and models is not None:
        info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [list(models)]
    if "KSampler" in info:
        info["KSampler"]["input"]["required"]["sampler_name"] = [["euler"]]
        info["KSampler"]["input"]["required"]["scheduler"] = [["normal"]]

    class _Stub:
        base_url = "http://stub"
        def get_object_info(self):
            return info
    return _Stub()


_SENTINEL = object()


def _build_app(*, actor=_SENTINEL, client=None, store=None, presets=None):
    app = Flask(__name__)
    if actor is _SENTINEL:
        actor = {"id": 1, "username": "alice"}
    actor_box = {"actor": actor}
    audit_log = []
    presets_state = presets if presets is not None else {"by_id": {}, "next_id": 1}

    def _actor_or_401():
        if actor_box["actor"] is None:
            resp = app.response_class(
                response=json.dumps({"ok": False, "msg": "未登入"}),
                status=401, mimetype="application/json",
            )
            return None, resp
        return dict(actor_box["actor"]), None

    def _audit(action, ip, *, user="-", success=True, ua="", detail=""):
        audit_log.append({"action": action, "user": user, "success": success, "detail": detail})

    def _actor_value(actor, key):
        return (actor or {}).get(key)

    class _StubConn:
        def __init__(self, presets_state):
            self.presets_state = presets_state
        def execute(self, *args, **kwargs):
            return None
        def commit(self):
            pass
        def close(self):
            pass

    def _get_db():
        return _StubConn(presets_state)

    def _upsert_workflow_preset(conn, *, preset_id=None, actor, title, description,
                                 visibility, workflow_payload, default_params,
                                 is_official=False, published_by_user_id=None):
        new_id = presets_state["next_id"]
        presets_state["next_id"] += 1
        presets_state["by_id"][new_id] = {
            "id": new_id,
            "owner_user_id": _actor_value(actor, "id"),
            "title": title,
            "description": description,
            "visibility": visibility,
            "workflow_json": workflow_payload["workflow_json"],
            "workflow_hash": workflow_payload["workflow_hash"],
            "default_params": default_params,
        }
        return new_id

    def _load_workflow_preset_row(conn, *, preset_id):
        return presets_state["by_id"].get(preset_id)

    def _workflow_preset_summary(row, *, actor=None, **kwargs):
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "visibility": row["visibility"],
        }

    actual_store = store if store is not None else InMemoryPreviewStore()
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": _actor_or_401,
        "actor_value": _actor_value,
        "json_resp": lambda payload: app.response_class(
            response=json.dumps(payload, ensure_ascii=False),
            mimetype="application/json",
        ),
        "require_csrf": lambda f: f,
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test-agent",
        "audit": _audit,
        "comfyui_binding": lambda a: "http://stub" if client is not None else None,
        "client_for_url": lambda b: client,
        "preview_store": actual_store,
        "get_db": _get_db,
        "upsert_workflow_preset": _upsert_workflow_preset,
        "load_workflow_preset_row": _load_workflow_preset_row,
        "workflow_preset_summary": _workflow_preset_summary,
    })
    app.config.update({
        "actor_box": actor_box,
        "audit_log": audit_log,
        "presets_state": presets_state,
    })
    return app


def _preview_then(client_test, body):
    """Helper: hit /preview, return preview_token."""
    rv = client_test.post("/api/comfyui/templates/preview", json={"workflow": body})
    assert rv.status_code == 200, rv.get_data(as_text=True)
    return rv.get_json()["preview_token"]


def test_import_creates_preset_with_valid_token():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "My txt2img", "visibility": "private"},
        )
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["ok"] is True
    assert body["preset_id"] >= 1
    assert body["preset"]["title"] == "My txt2img"


def test_import_rejects_missing_token():
    app = _build_app()
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/import", json={"title": "x"})
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "token"


def test_import_rejects_unknown_token():
    app = _build_app()
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": "tkn_doesnotexist", "title": "x"},
        )
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "token_invalid"


def test_import_rejects_blank_title():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "  "},
        )
    assert rv.status_code == 400
    assert rv.get_json()["stage"] == "title"


def test_import_token_is_single_use():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv1 = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "first"},
        )
        rv2 = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "second"},
        )
    assert rv1.status_code == 200
    assert rv2.status_code == 400
    assert rv2.get_json()["stage"] == "token_invalid"


def test_import_rejects_when_capability_unsupported():
    """No ComfyUI client → capability=UNSUPPORTED → import blocked."""
    store = InMemoryPreviewStore()
    app = _build_app(client=None, store=store)  # no ComfyUI bound
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": token, "title": "blocked"},
        )
    assert rv.status_code == 400
    body = rv.get_json()
    assert body["stage"] == "capability"
    assert body["unsupported"]


def test_import_audits_pass_and_fail_paths():
    store = InMemoryPreviewStore()
    client = _stub_client(
        classes={"CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode",
                 "KSampler", "VAEDecode", "SaveImage"},
        models=["v1-5.safetensors"],
    )
    app = _build_app(client=client, store=store)
    with app.test_client() as c:
        token = _preview_then(c, TXT2IMG)
        c.post("/api/comfyui/templates/import",
               json={"preview_token": token, "title": "ok"})  # PASS
        c.post("/api/comfyui/templates/import",
               json={"preview_token": "tkn_bad", "title": "fail"})  # FAIL token_invalid
    actions = [(e["action"], e["success"]) for e in app.config["audit_log"]]
    assert ("COMFYUI_TEMPLATE_IMPORT_PASS", True) in actions
    assert ("COMFYUI_TEMPLATE_IMPORT_FAIL", False) in actions


def test_import_unauthenticated_returns_401():
    app = _build_app(actor=None)
    with app.test_client() as c:
        rv = c.post(
            "/api/comfyui/templates/import",
            json={"preview_token": "tkn_x", "title": "x"},
        )
    assert rv.status_code == 401


def test_import_endpoint_skipped_without_preset_helpers():
    """If route ctx omits preset helpers, /import isn't registered (preview-only mode)."""
    app = Flask(__name__)
    register_comfyui_template_routes(app, {
        "request": flask_request,
        "actor_or_401": lambda: ({"id": 1}, None),
        "json_resp": lambda p: app.response_class(
            response=json.dumps(p), mimetype="application/json"
        ),
        "require_csrf": lambda f: f,
        "get_client_ip": lambda: "127.0.0.1",
        "get_ua": lambda: "test",
        "audit": lambda *a, **k: None,
        "comfyui_binding": lambda a: None,
        "client_for_url": lambda b: None,
        # NO get_db / upsert_workflow_preset / etc.
    })
    with app.test_client() as c:
        rv = c.post("/api/comfyui/templates/import", json={"preview_token": "tkn_x", "title": "x"})
    assert rv.status_code == 404
