"""Search acceleration must preserve uint64 hashes and collision order."""

import numpy as np
import pytest

from tetra3.tetra3 import (
    _get_table_indices_from_hash,
    _get_table_indices_from_hash_fast,
    _pattern_hash_to_index,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("bins", [10, 50, 250, 1000])
@pytest.mark.parametrize("width", [5, 9])
def test_batch_hash_matches_scalar_with_uint64_overflow(bins, width):
    rng = np.random.default_rng(812)
    codes = rng.integers(0, bins + 1, size=(100, width), dtype=np.uint64)
    expected = [_pattern_hash_to_index(row, bins, 100003) for row in codes]
    np.testing.assert_array_equal(_pattern_hash_to_index(codes, bins, 100003), expected)


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.uint32, np.uint64])
def test_probe_matches_legacy_for_collisions_and_partial_zero_rows(dtype):
    rng = np.random.default_rng(992)
    table = rng.integers(0, 10, size=(101, 4)).astype(dtype)
    table[rng.random(101) < 0.6] = 0
    table[0] = [0, 0, 0, 1]
    table[1] = [1, 0, 0, 0]
    for index in range(len(table)):
        np.testing.assert_array_equal(
            _get_table_indices_from_hash_fast(index, table),
            _get_table_indices_from_hash(index, table),
        )


def test_empty_probe_result_is_valid_for_catalog_indexing():
    table = np.zeros((7, 4), dtype=np.uint16)
    indices = _get_table_indices_from_hash_fast(5, table)
    assert table[indices].shape == (0, 4)


def test_probe_preserves_uint64_wraparound():
    table = np.zeros((101, 4), dtype=np.uint16)
    start = np.uint64(0xFFFFFFFFFFFFFFFF)
    table[int(start) % len(table), 0] = 1
    with np.errstate(over="ignore"):
        expected = _get_table_indices_from_hash(start, table)
    np.testing.assert_array_equal(
        _get_table_indices_from_hash_fast(start, table), expected
    )


def test_reference_mode_is_selected_at_instance_creation(monkeypatch):
    from tetra3 import Tetra3

    monkeypatch.setenv("TETRA3_SEARCH_OPTIMIZED", "0")
    assert not Tetra3(load_database=None)._search_optimized
    monkeypatch.delenv("TETRA3_SEARCH_OPTIMIZED")
    assert Tetra3(load_database=None)._search_optimized


def test_search_budget_is_nested_and_restored_after_exception(monkeypatch):
    from tetra3 import tetra3 as core

    now = [10.0]
    monkeypatch.setattr(core, "precision_timestamp", lambda: now[0])
    assert not core.search_budget_expired()
    with core.search_budget(1000):
        with pytest.raises(ValueError), core.search_budget(5000):
            now[0] = 11.1
            assert core.search_budget_expired()
            raise ValueError("test cleanup")
        assert core.search_budget_expired()
    assert not core.search_budget_expired()


def test_cascade_stops_at_shared_deadline_and_recovery_gets_fresh_budget(monkeypatch):
    from tetra3 import tetra3 as core
    from PiFinder.solver import _solve_center_first_remainder

    now = [10.0]
    monkeypatch.setattr(core, "precision_timestamp", lambda: now[0])
    called = []

    def slow():
        called.append("raw")
        now[0] += 2
        return {}

    stages = [("first", slow), ("late", lambda: called.append("late"))]
    result, path = _solve_center_first_remainder(stages, budget_ms=1000)
    assert not result and not path
    assert called == ["raw"]
    recovered = {"RA": 1, "Dec": 2}
    assert (
        _solve_center_first_remainder([("preprocessed", lambda: recovered)])[0]
        == recovered
    )


@pytest.mark.parametrize("cause", ["timeout", "cancel"])
def test_inner_hash_search_checks_stop_before_next_lookup(monkeypatch, cause):
    from tetra3 import tetra3 as core

    solver = core.Tetra3()
    now = [10.0]
    monkeypatch.setattr(core, "precision_timestamp", lambda: now[0])
    calls = []

    def lookup(*args):
        calls.append(args[0])
        if cause == "timeout":
            now[0] += 1
        else:
            solver.cancel_solve()
        return None, None

    monkeypatch.setattr(solver, "_get_all_patterns_for_index", lookup)
    centroids = np.random.default_rng(37).uniform(10, 500, (30, 2))
    result = solver.solve_from_centroids(centroids, (512, 512), solve_timeout=50)
    assert len(calls) == 1
    assert result["RA"] is None
    assert result["status"] == (core.TIMEOUT if cause == "timeout" else core.CANCELLED)
    assert not solver._cancelled
