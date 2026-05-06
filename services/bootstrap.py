"""Compatibility facade for services.platform.bootstrap."""

import sys as _sys
from services.platform import bootstrap as _impl

_sys.modules[__name__] = _impl
