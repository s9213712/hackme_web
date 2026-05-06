"""Compatibility facade for trading websocket stream helpers."""

import sys as _sys

from services.trading import streams as _impl

_sys.modules[__name__] = _impl
