import io
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, make_response

from routes.comfyui import register_comfyui_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.comfyui_client import ComfyUIClient, ComfyUIImage
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import create_album, ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy


ROOT = Path(__file__).resolve().parents[1]


class FakeComfyUIClient:
    base_url = "http://fake-comfyui"
    last_timeout_seconds = None
    discarded = []
    interrupted = 0

    def health_check(self, *, timeout=3):
        return {"ok": True, "system": {"os": "test"}}

    def get_models(self):
        return ["dream.safetensors", "photo.ckpt"]

    def get_sampler_options(self):
        return {"samplers": ["euler", "dpmpp_2m"], "schedulers": ["normal", "karras"]}

    def generate_image(self, params, *, timeout_seconds=180):
        FakeComfyUIClient.last_timeout_seconds = timeout_seconds
        batch_size = int(params.get("batch_size") or 1)
        images = []
        for index in range(batch_size):
            images.append({
                "image_ref": {"filename": f"hackme_web_{index + 1:05d}_.png", "subfolder": "", "type": "output"},
                "mime_type": "image/png",
                "data": f"fake-png-bytes-{index + 1}".encode("utf-8"),
            })
        return {
            "prompt_id": "prompt-1",
            "image_ref": images[0]["image_ref"],
            "mime_type": images[0]["mime_type"],
            "data": images[0]["data"],
            "images": images,
        }

    def fetch_image(self, image_ref):
        return ComfyUIImage(
            filename=image_ref.get("filename") or "hackme_web_00001_.png",
            subfolder=image_ref.get("subfolder") or "",
            type=image_ref.get("type") or "output",
            mime_type="image/png",
            data=b"fake-png-bytes",
        )

    def discard_image(self, image_ref, *, prompt_id=None):
        FakeComfyUIClient.discarded.append({"image_ref": dict(image_ref), "prompt_id": prompt_id})
        return {"file_deleted": True, "file_missing": False, "file_delete_supported": True, "history_deleted": bool(prompt_id)}

    def interrupt(self):
        FakeComfyUIClient.interrupted += 1
        return {"interrupted": True}


class FailingComfyUIClient(FakeComfyUIClient):
    def generate_image(self, params, *, timeout_seconds=180):
        from services.comfyui_client import ComfyUIError

        raise ComfyUIError("ComfyUI 產圖失敗")


class FakePointsService:
    def __init__(self, balance=100, fail_spend=False):
        self.balance = int(balance)
        self.fail_spend = fail_spend
        self.spends = []

    def list_catalog(self):
        return [{
            "item_key": "comfyui_txt2img_basic",
            "item_name": "基礎生圖一次",
            "category": "comfyui",
            "currency_type": "points",
            "base_price": 5,
            "enabled": 1,
            "metadata": {},
        }]

    def get_wallet(self, user_id):
        return {"user_id": user_id, "points_balance": self.balance}

    def spend_points(self, *, user_id, item_key, quantity=1, reference_type=None,
                     reference_id=None, idempotency_key=None, metadata=None, actor=None):
        if self.fail_spend:
            raise ValueError("billing failed")
        amount = 5 * int(quantity or 1)
        if self.balance < amount:
            raise ValueError("insufficient balance")
        self.balance -= amount
        spend = {
            "user_id": user_id,
            "item_key": item_key,
            "quantity": int(quantity or 1),
            "reference_type": reference_type,
            "reference_id": reference_id,
            "metadata": metadata or {},
            "amount": amount,
        }
        self.spends.append(spend)
        return {
            "ok": True,
            "ledger": {"ledger_uuid": f"ledger-{len(self.spends)}", "amount": amount},
            "wallet": self.get_wallet(user_id),
            "item": {"base_price": 5},
        }


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _actor():
    return {
        "id": 1,
        "username": "alice",
        "role": "user",
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }


class OfflineComfyUIClient:
    base_url = "http://fake-offline"

    def health_check(self, *, timeout=3):
        from services.comfyui_client import ComfyUIError

        raise ComfyUIError("ComfyUI 連線失敗：refused")


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES (1, 'alice', 'user');
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_cloud_drive_attachment_schema(conn)
    ensure_storage_album_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    conn.commit()
    conn.close()


def _build_app(db_path, storage_root, settings=None, comfyui_client=None, actor=None, points_service=None):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_comfyui_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": actor or _actor,
        "get_db": get_db,
        "get_system_settings": lambda: {"feature_comfyui_enabled": True, **(settings or {})},
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 10,
            "max_attachment_size_mb": 10,
            "upload_rate_limit_per_day": 10,
        },
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "comfyui_client": comfyui_client or FakeComfyUIClient(),
        "points_service": points_service or FakePointsService(),
    })
    return app


def test_comfyui_models_and_generate_routes(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    models = client.get("/api/comfyui/models")
    assert models.status_code == 200
    assert models.get_json()["models"] == ["dream.safetensors", "photo.ckpt"]
    assert models.get_json()["max_batch_size"] == 1

    status = client.get("/api/comfyui/status")
    assert status.status_code == 200
    assert status.get_json()["available"] is True
    assert status.get_json()["max_batch_size"] == 1

    generated = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "width": 512,
            "height": 512,
            "steps": 12,
            "cfg": 6.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "seed": 123,
            "batch_size": 3,
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["image"]["prompt_id"] == "prompt-1"
    assert body["image"]["data_url"].startswith("data:image/png;base64,")
    assert body["image"]["seed"] == 123
    assert body["image"]["batch_size"] == 1
    assert len(body["images"]) == 1
    assert body["images"][0]["image_ref"]["filename"] == "hackme_web_00001_.png"
    assert FakeComfyUIClient.last_timeout_seconds == 600


def test_comfyui_batch_limit_is_root_configurable(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    client = _build_app(db_path, storage_root, settings={"comfyui_max_batch_size": 3}, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={
            "model": "dream.safetensors",
            "prompt": "a quiet test image",
            "seed": 123,
            "batch_size": 3,
        },
    )
    assert generated.status_code == 200
    body = generated.get_json()
    assert body["image"]["batch_size"] == 3
    assert len(body["images"]) == 3
    assert body["images"][2]["image_ref"]["filename"] == "hackme_web_00003_.png"
    assert body["billing"]["charged"] is True
    assert body["billing"]["total_price"] == 15
    assert points.spends == [{
        "user_id": 1,
        "item_key": "comfyui_txt2img_basic",
        "quantity": 3,
        "reference_type": "comfyui_generation",
        "reference_id": "prompt-1",
        "metadata": {
            "charged_after_success": True,
            "unit_price": 5,
            "quantity": 3,
            "total_price": 15,
        },
        "amount": 15,
    }]


def test_comfyui_generation_failure_does_not_charge_points(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=100)
    client = _build_app(db_path, storage_root, comfyui_client=FailingComfyUIClient(), points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "this will fail", "seed": 123},
    )

    assert generated.status_code == 503
    assert points.spends == []
    assert points.balance == 100


def test_comfyui_generation_rejects_when_points_are_insufficient_before_work(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=4)
    client = _build_app(db_path, storage_root, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "too expensive", "seed": 123},
    )

    assert generated.status_code == 409
    assert "積分不足" in generated.get_json()["msg"]
    assert points.spends == []


def test_comfyui_generation_does_not_charge_root(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    points = FakePointsService(balance=0)
    root_actor = {
        "id": 1,
        "username": "root",
        "role": "super_admin",
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }
    client = _build_app(db_path, storage_root, actor=lambda: root_actor, points_service=points).test_client()

    generated = client.post(
        "/api/comfyui/generate",
        json={"model": "dream.safetensors", "prompt": "root free", "seed": 123},
    )

    assert generated.status_code == 200
    body = generated.get_json()
    assert body["billing"] == {"charged": False, "exempt": "root"}
    assert points.spends == []


def test_comfyui_workflow_uses_requested_batch_size():
    workflow = ComfyUIClient("http://fake-comfyui").build_text_to_image_workflow({
        "model": "dream.safetensors",
        "prompt": "batch test",
        "negative_prompt": "",
        "width": 512,
        "height": 512,
        "steps": 12,
        "cfg": 6.5,
        "sampler_name": "euler",
        "scheduler": "normal",
        "seed": 123,
        "batch_size": 4,
        "filename_prefix": "hackme_web",
    })

    assert workflow["5"]["inputs"]["batch_size"] == 4


def test_comfyui_status_reports_offline_backend(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_comfyui_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": _actor,
        "get_db": get_db,
        "get_system_settings": lambda: {"feature_comfyui_enabled": True},
        "get_member_level_rule": lambda conn, level: {},
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "comfyui_client": OfflineComfyUIClient(),
    })

    status = app.test_client().get("/api/comfyui/status")
    assert status.status_code == 200
    body = status.get_json()
    assert body["ok"] is True
    assert body["available"] is False
    assert body["comfyui_url"] == "http://fake-offline"


def test_comfyui_save_stores_generated_image_in_user_storage(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "virtual_path": "/ComfyUI/smoke.png",
        },
    )

    assert saved.status_code == 200
    body = saved.get_json()
    assert body["storage_file"]["virtual_path"] == "/ComfyUI/smoke.png"
    assert body["file"]["file_id"]

    stored_path = storage_root / "users" / "1" / body["file"]["file_id"]
    assert not stored_path.exists()
    assert list(storage_root.glob("users/1/*/hackme_web_00001_.png"))


def test_comfyui_discard_deletes_original_comfyui_file(tmp_path):
    FakeComfyUIClient.discarded = []
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    discarded = client.post(
        "/api/comfyui/discard",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "prompt_id": "prompt-1",
        },
    )

    assert discarded.status_code == 200
    body = discarded.get_json()
    assert body["discard"]["file_deleted"] is True
    assert body["discard"]["history_deleted"] is True
    assert FakeComfyUIClient.discarded == [{
        "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
        "prompt_id": "prompt-1",
    }]


def test_comfyui_discard_tolerates_plain_text_history_response(tmp_path, monkeypatch):
    output_dir = tmp_path / "comfy-output"
    output_dir.mkdir()
    image_path = output_dir / "plain-history.png"
    image_path.write_bytes(b"fake-png")
    monkeypatch.setenv("COMFYUI_OUTPUT_DIR", str(output_dir))
    calls = []

    class PlainTextResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"OK"

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return PlainTextResponse()

    monkeypatch.setattr("services.comfyui_client.urllib.request.urlopen", fake_urlopen)

    result = ComfyUIClient("http://fake-comfyui").discard_image(
        {"filename": "plain-history.png", "subfolder": "", "type": "output"},
        prompt_id="prompt-plain",
    )

    assert result["file_deleted"] is True
    assert result["history_deleted"] is True
    assert not image_path.exists()
    assert calls == ["http://fake-comfyui/history"]


def test_comfyui_discard_without_file_delete_endpoint_clears_preview_with_warning(tmp_path):
    class UnsupportedDeleteClient:
        def discard_image(self, image_ref, *, prompt_id=None):
            return {
                "file_deleted": False,
                "file_missing": False,
                "file_delete_supported": False,
                "history_deleted": bool(prompt_id),
            }

    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root, comfyui_client=UnsupportedDeleteClient()).test_client()

    discarded = client.post(
        "/api/comfyui/discard",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "prompt_id": "prompt-1",
        },
    )

    assert discarded.status_code == 200
    body = discarded.get_json()
    assert body["ok"] is True
    assert body["warning"] == "source_file_not_deleted"
    assert body["discard"]["history_deleted"] is True
    assert "原始檔可能仍留在 ComfyUI output" in body["msg"]


def test_comfyui_interrupt_requests_backend_interrupt(tmp_path):
    FakeComfyUIClient.interrupted = 0
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    client = _build_app(db_path, storage_root).test_client()

    interrupted = client.post("/api/comfyui/interrupt", json={})

    assert interrupted.status_code == 200
    body = interrupted.get_json()
    assert body["ok"] is True
    assert body["interrupt"]["interrupted"] is True
    assert FakeComfyUIClient.interrupted == 1


def test_comfyui_interrupt_tolerates_plain_text_response(monkeypatch):
    calls = []

    class PlainTextResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"interrupted"

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return PlainTextResponse()

    monkeypatch.setattr("services.comfyui_client.urllib.request.urlopen", fake_urlopen)

    result = ComfyUIClient("http://fake-comfyui").interrupt()

    assert result == {"raw": "interrupted"}
    assert calls == ["http://fake-comfyui/interrupt"]


def test_comfyui_save_can_add_generated_image_to_album(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    album, msg = create_album(conn, actor=_actor(), title="AI Gallery")
    assert msg is None
    conn.commit()
    conn.close()
    client = _build_app(db_path, storage_root).test_client()

    saved = client.post(
        "/api/comfyui/save",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "virtual_path": "/ComfyUI/album.png",
            "album_id": album["id"],
        },
    )

    assert saved.status_code == 200
    body = saved.get_json()
    assert body["album"]["id"] == album["id"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT file_id, storage_file_id FROM album_files WHERE album_id=? AND deleted_at IS NULL",
        (album["id"],),
    ).fetchone()
    conn.close()
    assert row["file_id"] == body["file"]["file_id"]
    assert row["storage_file_id"] == body["storage_file"]["id"]


def test_comfyui_share_creates_comfyui_thread_with_preview_grant(tmp_path):
    db_path = tmp_path / "comfyui.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    album, msg = create_album(conn, actor=_actor(), title="Shared AI")
    assert msg is None
    conn.commit()
    conn.close()
    client = _build_app(db_path, storage_root).test_client()

    shared = client.post(
        "/api/comfyui/share",
        json={
            "image_ref": {"filename": "hackme_web_00001_.png", "subfolder": "", "type": "output"},
            "virtual_path": "/ComfyUI/share.png",
            "album_id": album["id"],
            "title": "My ComfyUI share",
            "note": "這張圖的心得",
            "generation": {
                "model": "dream.safetensors",
                "prompt": "a quiet test image",
                "negative_prompt": "noise",
                "width": 512,
                "height": 768,
                "steps": 18,
                "cfg": 6.5,
                "seed": 123,
                "batch_size": 2,
                "sampler_name": "euler",
                "scheduler": "normal",
            },
        },
    )

    assert shared.status_code == 200
    body = shared.get_json()
    assert body["thread"]["title"] == "My ComfyUI share"
    file_id = body["file"]["file_id"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    thread = conn.execute("SELECT * FROM forum_threads WHERE id=?", (body["thread"]["id"],)).fetchone()
    grant = conn.execute(
        "SELECT * FROM file_access_grants WHERE file_id=? AND context_type='forum_thread' AND context_id=?",
        (file_id, str(body["thread"]["id"])),
    ).fetchone()
    album_file = conn.execute(
        "SELECT id FROM album_files WHERE album_id=? AND file_id=? AND deleted_at IS NULL",
        (album["id"], file_id),
    ).fetchone()
    conn.close()
    assert thread["board_id"] == body["thread"]["board_id"]
    assert "[[comfyui-image:" + file_id + "]]" in thread["content"]
    assert "這張圖的心得" in thread["content"]
    assert "a quiet test image" in thread["content"]
    assert "張數：2" in thread["content"]
    assert grant["granted_to_role"] == "user"
    assert grant["can_preview"] == 1
    assert album_file is not None


def test_comfyui_frontend_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    community_js = (ROOT / "public" / "js" / "25-community.js").read_text(encoding="utf-8")
    comfyui_js = (ROOT / "public" / "js" / "36-comfyui.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    settings_py = (ROOT / "services" / "settings.py").read_text(encoding="utf-8")
    smoke = (ROOT / "security" / "run_functional_smoke.sh").read_text(encoding="utf-8")

    assert 'id="tab-module-comfyui"' in index_html
    assert 'id="module-comfyui"' in index_html
    assert 'id="comfyui-model-select"' in index_html
    assert 'id="comfyui-generate-btn"' in index_html
    assert 'id="comfyui-load-last-btn"' in index_html
    assert 'id="comfyui-interrupt-btn"' in index_html
    assert 'id="comfyui-batch-size"' in index_html
    assert 'id="comfyui-save-btn"' in index_html
    assert 'id="comfyui-album-select"' in index_html
    assert 'id="comfyui-share-btn"' in index_html
    assert 'id="comfyui-progress-panel"' in index_html
    assert "/js/36-comfyui.js?v=20260429-comfyui-load-last" in index_html
    assert "/styles.css?v=20260429-ui-polish" in index_html
    assert "width: min(420px, 100%);" in css
    assert "max-height: 320px;" in css
    assert 'id="s-comfyui-api-port"' in index_html
    assert 'id="s-comfyui-max-batch-size"' in index_html
    assert 'tabModuleComfyui.style.display = canAccessModule("comfyui") ? "" : "none"' in core_js
    assert 'switchModuleTab("comfyui")' in bootstrap_js
    assert 'normTab === "comfyui"' in admin_js
    assert 'fetch(API + "/comfyui/generate"' in comfyui_js
    assert 'fetch(API + "/comfyui/interrupt"' in comfyui_js
    assert 'fetch(API + "/comfyui/save"' in comfyui_js
    assert 'fetch(API + "/comfyui/discard"' in comfyui_js
    assert 'source_file_not_deleted' in comfyui_js
    assert 'fetch(API + "/comfyui/share"' in comfyui_js
    assert 'fetch(API + "/comfyui/status"' in comfyui_js
    assert 'let comfyuiMaxBatchSize = 1;' in comfyui_js
    assert 'let comfyuiBillingQuote = null;' in comfyui_js
    assert 'function applyComfyuiRuntimeLimits(payload = {})' in comfyui_js
    assert "非 root 帳號成功產圖後每張扣" in comfyui_js
    assert "json.billing?.charged" in comfyui_js
    assert 'batch_size: Math.max(1, Math.min(comfyuiMaxBatchSize, comfyuiNumberValue("comfyui-batch-size", 1)))' in comfyui_js
    assert "comfyuiGeneratedImages" in comfyui_js
    assert "renderComfyuiGeneratedImages" in comfyui_js
    assert "COMFYUI_DRAFT_FIELD_IDS" in comfyui_js
    assert "hackme_web:comfyui:draft" in comfyui_js
    assert "bindComfyuiDraftPersistence" in comfyui_js
    assert "function loadLastComfyuiSettings()" in comfyui_js
    assert "restoreComfyuiDraft()" in comfyui_js
    assert 'album_id: selectedComfyuiAlbumId()' in comfyui_js
    assert "startComfyuiProgress(COMFYUI_GENERATION_TIMEOUT_SECONDS)" in comfyui_js
    assert "stopComfyuiProgress({ complete: true })" in comfyui_js
    assert "comfyuiGenerateAbortController.abort()" in comfyui_js
    assert "comfyuiShareGenerationPayload" in comfyui_js
    assert "payload.seed = comfyuiCurrentImage.seed" in comfyui_js
    assert "interruptComfyuiGeneration" in bootstrap_js
    assert 'comfyuiLoadLastBtn.addEventListener("click", loadLastComfyuiSettings)' in bootstrap_js
    assert "bindComfyuiDraftPersistence" in bootstrap_js
    assert 'shareComfyuiToCommunity' in bootstrap_js
    assert "comfyui-image:" in community_js
    assert "communityPreviewContentUrl" in community_js
    assert "csrf_token=${encodeURIComponent(token)}" in community_js
    assert "/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content" in community_js
    assert "/js/25-community.js?v=20260429-moderator-user-select" in index_html
    assert 'isComfyuiAvailableForNavigation' in admin_js
    assert '"feature_comfyui_enabled": True' in settings_py
    assert '"comfyui_api_port": 8192' in settings_py
    assert '"comfyui_max_batch_size": 1' in settings_py
    assert "/api/comfyui/models" in smoke
