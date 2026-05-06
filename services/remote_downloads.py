"""Compatibility facade for remote download helpers."""

import sys as _sys

from services.storage import remote_downloads as _impl

_sys.modules[__name__] = _impl
