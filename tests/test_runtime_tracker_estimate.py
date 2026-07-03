"""RuntimeTracker.estimate_scan_seconds tests: confidence tiers, ncount scaling,
compile inclusion, and backward-compatible loading of old runtimes.json files.
"""
import json

from tavi.runtime_tracker import RuntimeTracker


def _record(name="in8", first=12.0, avg=2.0, neutrons=100000, points=5,
            compile_t=4.0, ts="2026-01-01T00:00:00"):
    return {
        "instrument_name": name,
        "num_points": points,
        "num_neutrons": neutrons,
        "first_scan_time": first,
        "avg_subsequent_time": avg,
        "total_time": first + (points - 1) * avg,
        "timestamp": ts,
        "compilation_time": compile_t,
    }


def _tracker_with(tmp_path, records):
    config = tmp_path / "runtimes.json"
    config.write_text(json.dumps({"records": records}), encoding="utf-8")
    return RuntimeTracker(config_path=str(config))


# --------------------------------------------------------------------------
# Confidence tiers
# --------------------------------------------------------------------------

def test_confidence_none_when_no_samples(tmp_path):
    tracker = _tracker_with(tmp_path, {})
    est = tracker.estimate_scan_seconds("in8", n_points=5, num_neutrons=100000)
    assert est == {"estimated_seconds": None, "confidence": "none", "samples": 0}


def test_confidence_tier_boundaries():
    assert RuntimeTracker._confidence_from_samples(0) == "none"
    assert RuntimeTracker._confidence_from_samples(1) == "low"
    assert RuntimeTracker._confidence_from_samples(2) == "low"
    assert RuntimeTracker._confidence_from_samples(3) == "medium"
    assert RuntimeTracker._confidence_from_samples(9) == "medium"
    assert RuntimeTracker._confidence_from_samples(10) == "high"
    assert RuntimeTracker._confidence_from_samples(50) == "high"


def test_confidence_low_medium_high_from_record_counts(tmp_path):
    tracker = _tracker_with(tmp_path, {"in8": [_record() for _ in range(2)]})
    assert tracker.estimate_scan_seconds("in8", 5, 100000)["confidence"] == "low"

    tracker = _tracker_with(tmp_path, {"in8": [_record() for _ in range(5)]})
    assert tracker.estimate_scan_seconds("in8", 5, 100000)["confidence"] == "medium"

    tracker = _tracker_with(tmp_path, {"in8": [_record() for _ in range(12)]})
    assert tracker.estimate_scan_seconds("in8", 5, 100000)["confidence"] == "high"


# --------------------------------------------------------------------------
# ncount scaling
# --------------------------------------------------------------------------

def test_per_point_scales_linearly_with_ncount(tmp_path):
    # Single sample: 2.0 s/point at 100k neutrons. Doubling ncount doubles it.
    tracker = _tracker_with(tmp_path, {
        "in8": [_record(avg=2.0, neutrons=100000, compile_t=0.0)]
    })
    est = tracker.estimate_scan_seconds("in8", n_points=10, num_neutrons=200000,
                                        needs_compile=False)
    # 2.0 * (200000/100000) = 4.0 s/point * 10 points = 40.0
    assert est["estimated_seconds"] == 40.0
    assert est["samples"] == 1


def test_nearest_sample_chosen_for_scaling(tmp_path):
    # Two samples; request near the 1M one -> that sample scales.
    tracker = _tracker_with(tmp_path, {
        "in8": [
            _record(avg=1.0, neutrons=100000, compile_t=0.0),
            _record(avg=10.0, neutrons=1000000, compile_t=0.0),
        ]
    })
    est = tracker.estimate_scan_seconds("in8", n_points=1, num_neutrons=900000,
                                        needs_compile=False)
    # Nearest is the 1M sample (10 s/pt): 10 * (900000/1000000) = 9.0
    assert est["estimated_seconds"] == 9.0


def test_needs_compile_adds_compile_time(tmp_path):
    tracker = _tracker_with(tmp_path, {
        "in8": [_record(avg=2.0, neutrons=100000, compile_t=6.0)]
    })
    with_compile = tracker.estimate_scan_seconds("in8", 10, 100000,
                                                 needs_compile=True)
    without = tracker.estimate_scan_seconds("in8", 10, 100000,
                                            needs_compile=False)
    # 10 points * 2.0 s = 20.0; compile median = 6.0.
    assert without["estimated_seconds"] == 20.0
    assert with_compile["estimated_seconds"] == 26.0


def test_invalid_inputs_return_none_estimate(tmp_path):
    tracker = _tracker_with(tmp_path, {"in8": [_record()]})
    assert tracker.estimate_scan_seconds("in8", 5, 0)["estimated_seconds"] is None
    assert tracker.estimate_scan_seconds("in8", 5, -1)["estimated_seconds"] is None
    # Non-negative sample count still reported.
    assert tracker.estimate_scan_seconds("in8", 5, 0)["samples"] == 1


def test_zero_points_estimate_is_compile_only(tmp_path):
    tracker = _tracker_with(tmp_path, {
        "in8": [_record(avg=2.0, neutrons=100000, compile_t=6.0)]
    })
    est = tracker.estimate_scan_seconds("in8", 0, 100000, needs_compile=True)
    assert est["estimated_seconds"] == 6.0


# --------------------------------------------------------------------------
# Backward compatibility
# --------------------------------------------------------------------------

def test_old_runtimes_without_compilation_time_loads_clean(tmp_path):
    # Legacy records predate the compilation_time field entirely.
    legacy = {
        "instrument_name": "in8",
        "num_points": 5,
        "num_neutrons": 100000,
        "first_scan_time": 12.0,
        "avg_subsequent_time": 2.0,
        "total_time": 20.0,
        "timestamp": "2025-01-01T00:00:00",
    }
    tracker = _tracker_with(tmp_path, {"in8": [legacy]})
    assert tracker.get_record_count("in8") == 1
    # Missing field defaults to 0.0; compile then inferred from first-avg.
    rec = tracker.records["in8"][0]
    assert rec.compilation_time == 0.0
    est = tracker.estimate_scan_seconds("in8", 5, 100000, needs_compile=True)
    # per-point 2.0*5 = 10.0; compile inferred = first(12) - avg(2) = 10.0.
    assert est["estimated_seconds"] == 20.0
