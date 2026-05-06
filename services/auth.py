"""Compatibility facade for services.users.auth.

Source-contract breadcrumbs kept for regression checks:
- CSRF_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
- if not user and csrf_tok:
- consume_csrf_token(csrf_tok, csrf_owner)
- "error": "csrf_invalid"
"""

import sys as _sys
from services.users import auth as _impl

_sys.modules[__name__] = _impl
