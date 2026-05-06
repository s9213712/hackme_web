"""Compatibility facade for static trading-market catalog helpers."""

import sys as _sys

from services.trading import catalog as _impl

_sys.modules[__name__] = _impl
