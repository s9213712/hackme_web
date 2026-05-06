"""Compatibility facade for storage quota purchase helpers."""

import sys as _sys

from services.storage import quota_purchases as _impl

_sys.modules[__name__] = _impl
