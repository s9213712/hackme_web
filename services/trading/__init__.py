"""Trading service package.

The concrete engine now lives in :mod:`services.trading.engine`, while the
legacy :mod:`services.trading_engine` path remains as a compatibility facade.
This package collects extracted helper modules behind stable compatibility
boundaries while the integration branch converges toward a coarser,
maintainable modular layout.
"""
