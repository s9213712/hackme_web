"""Compatibility facade for services.governance.sanction_notices.

Source-contract breadcrumbs kept for regression checks:
- points_ledger_uuid
- link="/appeals"
- 你可以到「申覆」分頁提出申覆
- if not appealable:
- violation_id=None / violation_id is not None
"""

import sys as _sys
from services.governance import sanction_notices as _impl

_sys.modules[__name__] = _impl
