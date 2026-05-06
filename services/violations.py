"""Compatibility facade for services.governance.violations.

Source-contract breadcrumb kept for regression checks:
- violation_id = cur.lastrowid
"""

import sys as _sys
from services.governance import violations as _impl

_sys.modules[__name__] = _impl
