"""Trading service package.

The concrete engine lives in :mod:`services.trading.engine`, and the
package-local :mod:`services.trading.trading_engine` facade preserves
source-visible breadcrumbs for regression checks without leaving a
root-level shim behind.
"""
