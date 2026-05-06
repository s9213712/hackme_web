"""PointsChain package facade."""

from . import schema as _schema
from .service import PointsLedgerService

globals().update({name: value for name, value in _schema.__dict__.items() if not name.startswith("__")})
