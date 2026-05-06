"""Compatibility facade for storage quota enforcement helpers."""

import sys as _sys

from services.storage import quota_enforcement as _impl

_sys.modules[__name__] = _impl
