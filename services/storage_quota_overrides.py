"""Compatibility facade for storage quota override helpers."""

import sys as _sys

from services.storage import quota_overrides as _impl

_sys.modules[__name__] = _impl
