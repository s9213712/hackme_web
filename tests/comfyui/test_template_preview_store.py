"""Preview-token store regression for the ComfyUI template importer (§8.2)."""

import time

import pytest

from services.comfyui.template.preview_store import (
    DatabasePreviewStore,
    InMemoryPreviewStore,
    PreviewEntry,
    PREVIEW_TOKEN_TTL_SECONDS,
    get_default_preview_store,
    reset_default_preview_store,
    set_default_preview_store,
)
from services.core.sqlite_hardening import connect_sqlite


class _FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


def test_token_format_is_tkn_prefixed_and_32_hex():
    store = InMemoryPreviewStore()
    token = store.put(user_id=1, payload={"hello": "world"})
    assert token.startswith("tkn_")
    assert len(token) == len("tkn_") + 32  # 16 bytes → 32 hex


def test_get_returns_payload_for_owner():
    store = InMemoryPreviewStore()
    token = store.put(user_id=7, payload={"foo": "bar"})
    entry = store.get(token=token, user_id=7)
    assert entry is not None
    assert entry.user_id == 7
    assert entry.payload == {"foo": "bar"}


def test_get_returns_none_for_other_user():
    store = InMemoryPreviewStore()
    token = store.put(user_id=7, payload={"foo": "bar"})
    assert store.get(token=token, user_id=8) is None


def test_get_returns_none_for_unknown_token():
    store = InMemoryPreviewStore()
    assert store.get(token="tkn_doesnotexist", user_id=7) is None


def test_get_returns_none_after_ttl():
    clock = _FakeClock()
    store = InMemoryPreviewStore(ttl_seconds=10, clock=clock)
    token = store.put(user_id=7, payload={})
    clock.advance(11)
    assert store.get(token=token, user_id=7) is None


def test_get_does_not_consume_token():
    store = InMemoryPreviewStore()
    token = store.put(user_id=7, payload={"a": 1})
    assert store.get(token=token, user_id=7) is not None
    # Second get still works
    assert store.get(token=token, user_id=7) is not None


def test_consume_returns_entry_and_deletes_it():
    store = InMemoryPreviewStore()
    token = store.put(user_id=7, payload={"x": 1})
    first = store.consume(token=token, user_id=7)
    assert first is not None and first.payload == {"x": 1}
    assert store.consume(token=token, user_id=7) is None
    assert store.get(token=token, user_id=7) is None


def test_consume_does_not_delete_for_wrong_user():
    store = InMemoryPreviewStore()
    token = store.put(user_id=7, payload={})
    assert store.consume(token=token, user_id=8) is None
    # Still consumable by the rightful owner
    assert store.consume(token=token, user_id=7) is not None


def test_expire_drops_only_expired_entries():
    clock = _FakeClock()
    store = InMemoryPreviewStore(ttl_seconds=10, clock=clock)
    a = store.put(user_id=1, payload={})
    clock.advance(5)
    b = store.put(user_id=1, payload={})
    clock.advance(6)  # a expired (11s old), b still alive (6s old)
    dropped = store.expire()
    assert dropped == 1
    assert store.get(token=a, user_id=1) is None
    assert store.get(token=b, user_id=1) is not None


def test_lru_eviction_when_capacity_exceeded():
    store = InMemoryPreviewStore(max_entries=3)
    tokens = [store.put(user_id=1, payload={"i": i}) for i in range(3)]
    extra = store.put(user_id=1, payload={"i": 99})
    # Oldest (tokens[0]) should be evicted; extra is present
    assert store.get(token=tokens[0], user_id=1) is None
    assert store.get(token=tokens[1], user_id=1) is not None
    assert store.get(token=tokens[2], user_id=1) is not None
    assert store.get(token=extra, user_id=1) is not None


def test_clear_drops_everything():
    store = InMemoryPreviewStore()
    store.put(user_id=1, payload={})
    store.put(user_id=2, payload={})
    assert len(store) == 2
    store.clear()
    assert len(store) == 0


def test_put_rejects_bad_user_id():
    store = InMemoryPreviewStore()
    with pytest.raises(ValueError):
        store.put(user_id=0, payload={})
    with pytest.raises(ValueError):
        store.put(user_id=-3, payload={})


def test_put_rejects_non_dict_payload():
    store = InMemoryPreviewStore()
    with pytest.raises(TypeError):
        store.put(user_id=1, payload="not-a-dict")  # type: ignore[arg-type]


def test_get_with_blank_token_returns_none():
    store = InMemoryPreviewStore()
    assert store.get(token="", user_id=1) is None
    assert store.get(token=None, user_id=1) is None  # type: ignore[arg-type]


def test_default_ttl_matches_spec():
    """§8.2: 30 minutes."""
    assert PREVIEW_TOKEN_TTL_SECONDS == 30 * 60


def test_module_level_singleton_swap_and_reset():
    custom = InMemoryPreviewStore(max_entries=1)
    set_default_preview_store(custom)
    assert get_default_preview_store() is custom
    reset_default_preview_store()
    assert get_default_preview_store() is not custom
    # Subsequent calls return the same fresh instance
    assert get_default_preview_store() is get_default_preview_store()


def test_concurrent_put_does_not_lose_entries():
    """Sanity check that the lock around put/get works under modest contention."""
    import threading

    store = InMemoryPreviewStore(max_entries=1024)
    tokens: list[str] = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            t = store.put(user_id=1, payload={})
            with lock:
                tokens.append(t)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tokens) == 200
    assert len(set(tokens)) == 200, "tokens should all be unique"


def _db_store(path, **kwargs):
    return DatabasePreviewStore(lambda: connect_sqlite(path, timeout=15, row_factory=True, wal=True), **kwargs)


def test_database_store_redeems_token_across_store_instances(tmp_path):
    db_path = tmp_path / "preview_tokens.sqlite3"
    preview_worker = _db_store(db_path)
    import_worker = _db_store(db_path)

    token = preview_worker.put(user_id=7, payload={"workflow": {"1": {"class_type": "KSampler"}}})
    entry = import_worker.consume(token=token, user_id=7)

    assert entry is not None
    assert entry.user_id == 7
    assert entry.payload["workflow"]["1"]["class_type"] == "KSampler"
    assert preview_worker.consume(token=token, user_id=7) is None


def test_database_store_wrong_user_does_not_consume(tmp_path):
    db_path = tmp_path / "preview_tokens.sqlite3"
    preview_worker = _db_store(db_path)
    import_worker = _db_store(db_path)

    token = preview_worker.put(user_id=7, payload={"x": 1})

    assert import_worker.consume(token=token, user_id=8) is None
    assert preview_worker.consume(token=token, user_id=7) is not None


def test_database_store_expires_tokens(tmp_path):
    clock = _FakeClock()
    store = _db_store(tmp_path / "preview_tokens.sqlite3", ttl_seconds=10, clock=clock)

    token = store.put(user_id=7, payload={"x": 1})
    clock.advance(11)

    assert store.get(token=token, user_id=7) is None
    assert store.consume(token=token, user_id=7) is None
