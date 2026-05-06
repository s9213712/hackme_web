"""Compatibility facade for server-mode routing helpers."""

import sys as _sys

from services.server_mode import routing as _impl

_sys.modules[__name__] = _impl
