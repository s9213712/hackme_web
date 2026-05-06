"""Compatibility facade for password-strength helpers."""

import sys as _sys

from services.security import password_strength as _impl

_sys.modules[__name__] = _impl
