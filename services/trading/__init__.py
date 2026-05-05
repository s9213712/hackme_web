"""Trading service package.

Phase 1 of the strangler refactor starts by moving behavior-preserving
pure helpers out of the legacy ``services.trading_engine`` module.

The legacy module remains the public entrypoint for now; this package
only hosts extracted submodules that are safe to import back into the
old engine without changing behavior.
"""
