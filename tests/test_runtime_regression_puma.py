"""Real-data regression: the affine cost model reproduces the observed PUMA
per-point times instead of the inflated pure-per-neutron estimate.

The five records below are a verbatim copy of the user's ``config/runtimes.json``
(four mcstas + one deterministic), the fixture that surfaced the bug: a real
21-point scan at 1e8 neutrons ran at ~4.5 s/point, but the pure-per-neutron
estimator predicted ~1354 s/point (overhead misread as neutron cost). The
``machine_id`` is rewritten to the current fingerprint so the local-machine
pool is exercised (pattern from tests/test_benchmark.py:93).
"""
import json

import pytest

from tavi.machine_profile import machine_fingerprint
from tavi.runtime_tracker import RuntimeTracker

# Verbatim copy of the five records in config/runtimes.json (machine_id is
# rewritten at setup). DO NOT edit these values -- they are the real fixture.
_PUMA_RECORDS = [
    {
        "instrument_name": "puma", "num_points": 3, "num_neutrons": 10000,
        "first_scan_time": 4.156493663787842,
        "avg_subsequent_time": 1.3302580118179321,
        "total_time": 7.062272787094116,
        "timestamp": "2026-07-06T13:42:54.916505",
        "compilation_time": 2.807015100001081,
        "machine_id": "4193b2c64387", "engine": "mcstas",
        "execution_mode": "mixed", "binary_reused": False,
        "build_fp_hash": "da76b250ea58", "source": "benchmark",
    },
    {
        "instrument_name": "puma", "num_points": 5, "num_neutrons": 10000,
        "first_scan_time": 1.3529603481292725,
        "avg_subsequent_time": 1.3298627138137817,
        "total_time": 6.674583435058594,
        "timestamp": "2026-07-06T13:43:01.614839",
        "compilation_time": 0.0,
        "machine_id": "4193b2c64387", "engine": "mcstas",
        "execution_mode": "direct", "binary_reused": True,
        "build_fp_hash": "da76b250ea58", "source": "benchmark",
    },
    {
        "instrument_name": "puma", "num_points": 5, "num_neutrons": 100000,
        "first_scan_time": 1.349696397781372,
        "avg_subsequent_time": 1.3541301488876343,
        "total_time": 6.770726203918457,
        "timestamp": "2026-07-06T13:43:08.408991",
        "compilation_time": 0.0,
        "machine_id": "4193b2c64387", "engine": "mcstas",
        "execution_mode": "direct", "binary_reused": True,
        "build_fp_hash": "da76b250ea58", "source": "benchmark",
    },
    {
        "instrument_name": "puma", "num_points": 20, "num_neutrons": 100000,
        "first_scan_time": 0.0036452770233154296,
        "avg_subsequent_time": 0.0036452770233154296,
        "total_time": 0.0729055404663086,
        "timestamp": "2026-07-06T13:43:08.513550",
        "compilation_time": 0.0,
        "machine_id": "4193b2c64387", "engine": "deterministic",
        "execution_mode": None, "binary_reused": None,
        "build_fp_hash": None, "source": "benchmark",
    },
    {
        "instrument_name": "puma", "num_points": 21, "num_neutrons": 100000000,
        "first_scan_time": 4.106811285018921,
        "avg_subsequent_time": 4.497905492782593,
        "total_time": 94.07197594642639,
        "timestamp": "2026-07-06T13:44:56.508168",
        "compilation_time": 0.0,
        "machine_id": "4193b2c64387", "engine": "mcstas",
        "execution_mode": "direct", "binary_reused": True,
        "build_fp_hash": "da76b250ea58", "source": "organic",
    },
]


def _tracker(tmp_path):
    me = machine_fingerprint()["machine_id"]
    records = []
    for rec in _PUMA_RECORDS:
        rec = dict(rec)
        rec["machine_id"] = me  # rewrite to the current machine
        records.append(rec)
    config = tmp_path / "runtimes.json"
    config.write_text(json.dumps({"version": 2, "records": {"puma": records}}),
                      encoding="utf-8")
    return RuntimeTracker(config_path=str(config))


def _per_point(tracker, num_neutrons):
    est = tracker.estimate_scan_seconds(
        "puma", n_points=1, num_neutrons=num_neutrons,
        needs_compile=False, engine="mcstas")
    return est["per_point_seconds"]


def test_per_point_at_1e8_matches_observed(tmp_path):
    # The real 1e8 scan measured ~4.5 s/point; the old model said ~1354.
    assert _per_point(_tracker(tmp_path), 10**8) == pytest.approx(4.5, rel=0.15)


def test_per_point_at_1e5_is_overhead(tmp_path):
    assert _per_point(_tracker(tmp_path), 10**5) == pytest.approx(1.35, rel=0.10)


def test_per_point_at_1e4_is_overhead(tmp_path):
    assert _per_point(_tracker(tmp_path), 10**4) == pytest.approx(1.33, rel=0.10)


def test_get_estimates_per_point_at_1e8(tmp_path):
    _, run = _tracker(tmp_path).get_estimates("puma", 10**8)
    assert run == pytest.approx(4.5, rel=0.15)


def test_total_21pt_scan_at_1e8_near_observed(tmp_path):
    # 21 points * ~4.5 s ~= 94 s total (the measured wall clock), not hours.
    est = _tracker(tmp_path).estimate_scan_seconds(
        "puma", n_points=21, num_neutrons=10**8,
        needs_compile=False, engine="mcstas")
    assert est["estimated_seconds"] == pytest.approx(94.0, rel=0.20)


def test_deterministic_estimate_unaffected_by_mcstas_records(tmp_path):
    # The lone deterministic record is flat (~0.00365 s/pt) and must be picked
    # by the deterministic engine, untouched by the mcstas affine model.
    est = _tracker(tmp_path).estimate_scan_seconds(
        "puma", n_points=20, num_neutrons=10**8,
        needs_compile=False, engine="deterministic")
    assert est["per_point_seconds"] == pytest.approx(0.0036452770233154296)
    assert est["estimated_seconds"] == pytest.approx(20 * 0.0036452770233154296)


def test_affine_fit_tag_reported(tmp_path):
    est = _tracker(tmp_path).estimate_scan_seconds(
        "puma", n_points=1, num_neutrons=10**8,
        needs_compile=False, engine="mcstas")
    assert est["fit"] == "affine"
    assert est["overhead_seconds"] == pytest.approx(1.33, rel=0.15)
    assert est["rate_per_neutron"] == pytest.approx(3.16e-8, rel=0.30)
