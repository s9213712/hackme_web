"""§8.2 / §8.2.1 preview-token store interface + default in-memory implementation.

The preview/import flow:

1. ``POST /api/comfyui/templates/preview`` returns a 32-hex token referring
   to the analyzed + sanitized workflow. We do NOT echo the workflow back
   to the client beyond the UI schema; storing it server-side avoids
   round-trip tampering.

2. ``POST /api/comfyui/workflows/import`` consumes the token, looks up
   the stored workflow / analysis, applies user-filled inputs, and writes
   the final preset into the database.

The interface is split from the storage so multi-worker deployments can
swap the default in-memory LRU for Redis or a DB temp table without
changing callers (see §8.2.1).

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §8.2 / §8.2.1.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


PREVIEW_TOKEN_TTL_SECONDS = 30 * 60  # §8.2 — 30 minutes default


def _generate_token() -> str:
    """Return ``tkn_<32 hex>`` per §8.2's prefix convention."""
    return f"tkn_{secrets.token_hex(16)}"


@dataclass
class PreviewEntry:
    """One preview record. ``payload`` is opaque to the store."""

    user_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    expires_at: float = 0.0


class PreviewStore(Protocol):
    """Interface routes call into.

    Implementations must be thread-safe; the default in-memory LRU is.
    """

    def put(self, *, user_id: int, payload: dict[str, Any]) -> str:
        """Persist a preview payload, return its token."""

    def get(self, *, token: str, user_id: int) -> PreviewEntry | None:
        """Look up a preview by (token, user_id). Mismatched user → None."""

    def consume(self, *, token: str, user_id: int) -> PreviewEntry | None:
        """Atomic get + delete. Used by import to make tokens single-use."""

    def expire(self) -> int:
        """Drop every entry whose TTL has passed. Returns number removed."""

    def clear(self) -> None:
        """Drop everything. Test helper / admin endpoint hook."""


class InMemoryPreviewStore:
    """Thread-safe in-memory store with LRU eviction + TTL.

    Suitable for single-process / sticky-session deployments. Multi-worker
    deployments must swap this for Redis/DB-backed storage (§8.2.1) so a
    preview minted by worker A can be redeemed by worker B.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = PREVIEW_TOKEN_TTL_SECONDS,
        max_entries: int = 256,
        clock: callable = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        # token → PreviewEntry; insertion-ordered for LRU drop
        self._entries: dict[str, PreviewEntry] = {}

    def _expire_locked(self, *, now: float) -> int:
        """Drop expired entries (caller holds lock)."""
        expired = [tk for tk, ent in self._entries.items() if ent.expires_at <= now]
        for tk in expired:
            del self._entries[tk]
        return len(expired)

    def _enforce_capacity_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            # Drop oldest (FIFO since dict preserves insertion order in 3.7+)
            oldest_token = next(iter(self._entries))
            del self._entries[oldest_token]

    def put(self, *, user_id: int, payload: dict[str, Any]) -> str:
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("user_id must be a positive int")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        now = self._clock()
        entry = PreviewEntry(
            user_id=int(user_id),
            payload=dict(payload),
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._expire_locked(now=now)
            token = _generate_token()
            # secrets.token_hex collision is astronomically improbable; loop only
            # as paranoid defense.
            while token in self._entries:
                token = _generate_token()
            self._entries[token] = entry
            self._enforce_capacity_locked()
        return token

    def get(self, *, token: str, user_id: int) -> PreviewEntry | None:
        if not token or not isinstance(token, str):
            return None
        now = self._clock()
        with self._lock:
            self._expire_locked(now=now)
            entry = self._entries.get(token)
            if entry is None:
                return None
            if entry.user_id != int(user_id):
                return None
            return entry

    def consume(self, *, token: str, user_id: int) -> PreviewEntry | None:
        if not token or not isinstance(token, str):
            return None
        now = self._clock()
        with self._lock:
            self._expire_locked(now=now)
            entry = self._entries.get(token)
            if entry is None:
                return None
            if entry.user_id != int(user_id):
                return None
            del self._entries[token]
            return entry

    def expire(self) -> int:
        now = self._clock()
        with self._lock:
            return self._expire_locked(now=now)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # Read-only inspection for tests / debug.
    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def tokens(self) -> Iterable[str]:
        with self._lock:
            return list(self._entries.keys())


# Module-level singleton used by the route layer in single-process deployments.
# Multi-worker deployments must replace this via ``set_default_preview_store``
# at startup with a Redis/DB-backed implementation per §8.2.1.

_default_store: PreviewStore = InMemoryPreviewStore()
_default_store_lock = threading.Lock()


def get_default_preview_store() -> PreviewStore:
    """Return the module-level singleton store."""
    return _default_store


def set_default_preview_store(store: PreviewStore) -> None:
    """Swap the singleton (e.g., to a Redis-backed implementation at startup)."""
    global _default_store
    with _default_store_lock:
        _default_store = store


def reset_default_preview_store() -> None:
    """Test helper — restore a fresh InMemoryPreviewStore."""
    set_default_preview_store(InMemoryPreviewStore())


__all__ = [
    "InMemoryPreviewStore",
    "PREVIEW_TOKEN_TTL_SECONDS",
    "PreviewEntry",
    "PreviewStore",
    "get_default_preview_store",
    "reset_default_preview_store",
    "set_default_preview_store",
]
