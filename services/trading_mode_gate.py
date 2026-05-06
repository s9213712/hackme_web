"""Compatibility facade for trading server-mode gates."""

import sys as _sys

from services.trading import mode_gate as _impl

_sys.modules[__name__] = _impl
