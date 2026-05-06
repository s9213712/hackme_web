"""Compatibility facade for captcha helpers."""

import sys as _sys

from services.security import captcha as _impl

_sys.modules[__name__] = _impl
