"""Compatibility facade for storage maintenance helpers."""

import sys as _sys

from services.storage import maintenance as _impl

_sys.modules[__name__] = _impl
