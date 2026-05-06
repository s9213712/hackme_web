"""Compatibility facade for BTC trade bridge helpers."""

import sys as _sys

from services.trading import btc_bridge as _impl

_sys.modules[__name__] = _impl
