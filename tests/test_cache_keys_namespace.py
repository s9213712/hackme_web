"""Phase 6 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — namespaced cache keys.

Locks the contract: every cache key carries mode (and tester_id where
internal_test). Drift-free key strings make Phase 5 (matching engine)
isolation provable.
"""

import pytest

from services.cache_keys import make_cache_key, parse_cache_key


def test_production_key_has_mode_prefix():
    k = make_cache_key("orderbook", mode="production", market="BTC/POINTS")
    assert k == "orderbook:production:market=BTC/POINTS"


def test_internal_test_key_requires_tester_id():
    with pytest.raises(ValueError):
        make_cache_key("orderbook", mode="internal_test", market="BTC/POINTS")
    k = make_cache_key("orderbook", mode="internal_test", tester_id=7, market="BTC/POINTS")
    assert k == "orderbook:internal_test:tester7:market=BTC/POINTS"


def test_missing_mode_kwarg_raises_typeerror():
    """The whole point: forgetting mode= must fail noisily at the call site."""
    with pytest.raises(TypeError):
        make_cache_key("orderbook", market="BTC/POINTS")  # type: ignore[call-arg]


def test_empty_mode_raises_valueerror():
    with pytest.raises(ValueError):
        make_cache_key("orderbook", mode="", market="BTC/POINTS")


def test_empty_logical_raises_valueerror():
    with pytest.raises(ValueError):
        make_cache_key("", mode="production")


def test_dims_are_sorted_for_determinism():
    """Two callers with the same dims (in any order) produce the same key."""
    a = make_cache_key("price", mode="production", side="bid", market="BTC")
    b = make_cache_key("price", mode="production", market="BTC", side="bid")
    assert a == b


def test_dim_value_with_colon_rejected():
    """Embedded ':' would break parse_cache_key — refuse at compose time."""
    with pytest.raises(ValueError):
        make_cache_key("orderbook", mode="production", market="BTC:POINTS")


def test_keys_for_different_modes_differ():
    prod = make_cache_key("orderbook", mode="production", market="BTC")
    test = make_cache_key("orderbook", mode="test", market="BTC")
    internal = make_cache_key("orderbook", mode="internal_test", tester_id=1, market="BTC")
    assert prod != test
    assert prod != internal
    assert test != internal


def test_keys_for_different_testers_differ():
    a = make_cache_key("orderbook", mode="internal_test", tester_id=1, market="BTC")
    b = make_cache_key("orderbook", mode="internal_test", tester_id=2, market="BTC")
    assert a != b


def test_tester_id_str_int_coerced():
    k = make_cache_key("orderbook", mode="internal_test", tester_id="42", market="BTC")
    assert "tester42:" in k


def test_parse_round_trips_production():
    k = make_cache_key("orderbook", mode="production", market="BTC/POINTS", side="bid")
    parsed = parse_cache_key(k)
    assert parsed["logical"] == "orderbook"
    assert parsed["mode"] == "production"
    assert parsed["dims"] == {"market": "BTC/POINTS", "side": "bid"}
    assert "tester_id" not in parsed


def test_parse_round_trips_internal_test():
    k = make_cache_key("orderbook", mode="internal_test", tester_id=9, market="BTC")
    parsed = parse_cache_key(k)
    assert parsed["mode"] == "internal_test"
    assert parsed["tester_id"] == 9
    assert parsed["dims"] == {"market": "BTC"}


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_cache_key("nope")
    with pytest.raises(ValueError):
        parse_cache_key("")
    with pytest.raises(ValueError):
        parse_cache_key(123)  # type: ignore[arg-type]
