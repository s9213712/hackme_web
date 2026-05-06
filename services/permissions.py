"""Compatibility facade for permission helpers."""

import sys as _sys

from services.security import permissions as _impl

_sys.modules[__name__] = _impl
