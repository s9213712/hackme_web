"""Compatibility facade for security event helpers."""

import sys as _sys

from services.security import events as _impl

_sys.modules[__name__] = _impl
