"""Compatibility facade for access-control helpers."""

import sys as _sys

from services.security import access_controls as _impl

_sys.modules[__name__] = _impl
