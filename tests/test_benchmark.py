"""Tests for the scan-time benchmarker (step 6).

Qt-free coverage of the pure benchmark module (plan shape, drift math) and the
estimator's additive ``source`` filter. The controller-level force_rebuild
early-out is Qt-bound (importing TAVI_PySide6 needs PySide6 + mcstasscript), so
it is skip-guarded in the style of test_record_enrichment.py.
"""
import json

import pytest

from tavi import benchmark
from tavi.machine_profile import machine_fingerprint
from tavi.runtime_tracker import RuntimeTracker


# ==========================================================================
# Pure plan builder (Qt-free)
# ==========================================================================

def test_plan_default_shape_with_deterministic():
    plan = benchmark.build_benchmark_plan(deterministic_supported=True)
    # Base plan: cold + warm mcstas at the low ncount, then deterministic. The
    # per-neutron rate is measured by the adaptive sweep, not a fixed stage.
    assert [s["engine"] for s in plan] == ["mcstas", "mcstas", "deterministic"]
    # Stage 1 is the cold/compile stage; only it forces a rebuild.
    assert plan[0]["force_rebuild"] is True
    assert all(s["force_rebuild"] is False for s in plan[1:])
    assert [s["points"] for s in plan] == [3, 5, 20]
    # Both mcstas stages run at the low ncount (1e4).
    assert plan[0]["ncount"] == 10000
    assert plan[1]["ncount"] == 10000


def test_plan_omits_deterministic_when_unsupported():
    plan = benchmark.build_benchmark_plan(deterministic_supported=False)
    assert [s["engine"] for s in plan] == ["mcstas", "mcstas"]
    assert all(s["engine"] != "deterministic" for s in plan)


def test_plan_ncount_override():
    plan = benchmark.build_benchmark_plan(
        ncounts=(5000,), deterministic_supported=False)
    assert plan[0]["ncount"] == 5000
    assert plan[1]["ncount"] == 5000


def test_plan_extra_ncount_entries_ignored():
    # A legacy (low, high) tuple still applies the low count; high is ignored.
    plan = benchmark.build_benchmark_plan(
        ncounts=(7000, 500000), deterministic_supported=False)
    assert plan[0]["ncount"] == 7000
    assert plan[1]["ncount"] == 7000


# ==========================================================================
# Adaptive rate sweep (next_rate_stage, Qt-free)
# ==========================================================================

def test_next_rate_stage_first_call_jumps_to_start_ncount():
    # First adaptive call: last stage is the base warm stage (low ncount, spp
    # == overhead). The sweep jumps straight to the start ncount (1e6).
    stage = benchmark.next_rate_stage(
        overhead_s=1.33, last_ncount=10000, last_spp=1.33,
        elapsed_adaptive_s=0.0)
    assert stage is not None
    assert stage["ncount"] == 1_000_000
    assert stage["engine"] == "mcstas"
    assert stage["points"] == benchmark.ADAPTIVE_STAGE_POINTS
    assert stage["force_rebuild"] is False


def test_next_rate_stage_stops_on_rate_signal():
    # spp has climbed to >= target_ratio x overhead: enough lever arm, stop.
    stage = benchmark.next_rate_stage(
        overhead_s=1.33, last_ncount=100_000_000, last_spp=4.5,
        elapsed_adaptive_s=15.0)
    assert stage is None


def test_next_rate_stage_stops_on_max_ncount():
    # Next escalation would exceed the ncount ceiling: stop.
    stage = benchmark.next_rate_stage(
        overhead_s=1.33, last_ncount=1_000_000_000, last_spp=2.0,
        elapsed_adaptive_s=5.0, max_ncount=10 ** 9)
    assert stage is None


def test_next_rate_stage_stops_on_budget():
    # Projected next-stage cost (2 * spp * 10) overflows the remaining budget.
    # spp=5 -> projected 100 s; remaining = 75 - 20 = 55 s -> stop.
    stage = benchmark.next_rate_stage(
        overhead_s=1.33, last_ncount=10_000_000, last_spp=5.0,
        elapsed_adaptive_s=20.0, budget_s=75.0)
    assert stage is None


def test_next_rate_stage_escalation_sequence():
    # A generous budget and a slow-rising spp produce 1e6 -> 1e7 -> 1e8 ...,
    # escalating x10 each stage until a stop rule fires.
    overhead = 1.0
    ncounts = []
    last_ncount, last_spp, elapsed = 10000, overhead, 0.0
    for _ in range(6):
        stage = benchmark.next_rate_stage(
            overhead, last_ncount, last_spp, elapsed,
            budget_s=10_000.0, target_ratio=3.0)
        if stage is None:
            break
        ncounts.append(stage["ncount"])
        last_ncount = stage["ncount"]
        # spp rises just under the 3x-overhead stop threshold so the sweep keeps
        # escalating for the length of this sequence check.
        last_spp = overhead * 1.1
        elapsed += 2.0
    assert ncounts[:3] == [1_000_000, 10_000_000, 100_000_000]


# ==========================================================================
# Cross-check drift math (Qt-free)
# ==========================================================================

def test_drift_percent_basic():
    assert benchmark.drift_percent(12.0, 10.0) == pytest.approx(20.0)
    assert benchmark.drift_percent(8.0, 10.0) == pytest.approx(-20.0)
    assert benchmark.drift_percent(10.0, 10.0) == pytest.approx(0.0)


def test_drift_percent_missing_and_zero():
    assert benchmark.drift_percent(None, 10.0) is None
    assert benchmark.drift_percent(10.0, None) is None
    assert benchmark.drift_percent(10.0, 0.0) is None


def test_crosscheck_rows_shape_and_order():
    rows = benchmark.crosscheck_rows([
        {"label": "a", "measured": 12.0, "predicted": 10.0},
        {"label": "b", "measured": None, "predicted": 5.0},
    ])
    assert [r["label"] for r in rows] == ["a", "b"]
    assert rows[0]["drift_pct"] == pytest.approx(20.0)
    assert rows[1]["drift_pct"] is None


# ==========================================================================
# Estimator additive source filter (Qt-free)
# ==========================================================================

def _tracker(tmp_path):
    return RuntimeTracker(config_path=str(tmp_path / "runtimes.json"))


def test_estimate_source_filter_selects_only_that_source(tmp_path):
    tracker = _tracker(tmp_path)
    machine_id = machine_fingerprint()["machine_id"]
    # Fast benchmark record ...
    tracker.add_record(
        instrument_name="puma", num_points=5, num_neutrons=10000,
        first_scan_time=1.0, avg_subsequent_time=1.0, total_time=5.0,
        machine_id=machine_id, engine="mcstas", source="benchmark")
    # ... and a slow organic record at the same config.
    tracker.add_record(
        instrument_name="puma", num_points=5, num_neutrons=10000,
        first_scan_time=10.0, avg_subsequent_time=10.0, total_time=50.0,
        machine_id=machine_id, engine="mcstas", source="organic")

    organic = tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, engine="mcstas",
        source="organic")
    benchmark_only = tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, engine="mcstas",
        source="benchmark")
    pooled = tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, engine="mcstas")

    assert organic["samples"] == 1
    assert benchmark_only["samples"] == 1
    assert pooled["samples"] == 2
    # Organic-only reflects the 10s/point record, benchmark-only the 1s one.
    assert organic["estimated_seconds"] > benchmark_only["estimated_seconds"]


def test_estimate_default_source_is_unchanged(tmp_path):
    """Omitting source pools both sources -- default behavior is preserved."""
    tracker = _tracker(tmp_path)
    machine_id = machine_fingerprint()["machine_id"]
    tracker.add_record(
        instrument_name="puma", num_points=5, num_neutrons=10000,
        first_scan_time=2.0, avg_subsequent_time=2.0, total_time=10.0,
        machine_id=machine_id, engine="mcstas", source="organic")
    est = tracker.estimate_scan_seconds(
        "puma", 5, 10000, needs_compile=False, engine="mcstas")
    assert est["samples"] == 1
    assert est["estimated_seconds"] == pytest.approx(10.0)


# ==========================================================================
# Controller force_rebuild early-out (Qt-bound; skips without deps)
# ==========================================================================

try:
    import mcstasscript  # noqa: F401
    import PySide6  # noqa: F401
    import TAVI_PySide6 as controller_module
    _HAVE_QT = True
except Exception:  # pragma: no cover - import environment dependent
    controller_module = None
    _HAVE_QT = False

qt_required = pytest.mark.skipif(
    not _HAVE_QT, reason="requires PySide6 + mcstasscript")


class _FakeExecState:
    first_backengine_succeeded = True
    binary_path = __file__  # any existing file so os.path.isfile passes


@qt_required
def test_force_rebuild_blocks_reuse():
    fn = controller_module.TAVIController._can_reuse_binary
    cache = {"fingerprint": "fp", "execution_state": _FakeExecState()}
    # Without force_rebuild, a matching cache reuses the binary ...
    assert fn(cache, "fp", False) is True
    # ... with force_rebuild set, reuse is refused regardless of the cache.
    assert fn(cache, "fp", False, force_rebuild=True) is False


@qt_required
def test_reuse_still_refused_on_fingerprint_mismatch():
    fn = controller_module.TAVIController._can_reuse_binary
    cache = {"fingerprint": "fp", "execution_state": _FakeExecState()}
    assert fn(cache, "different", False) is False
