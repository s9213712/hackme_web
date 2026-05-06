"""Compatibility facade for storage path helpers."""

import sys as _sys

from services.storage import paths as _impl

_sys.modules[__name__] = _impl
