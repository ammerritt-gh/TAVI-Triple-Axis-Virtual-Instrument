"""Schema v2 + machine-aware estimator tests for RuntimeTracker.

Covers: v1 file loads unchanged, v2 round-trip (records + machines block),
unknown-future-field tolerated, selection-chain fallbacks (local/legacy/
scaled/pooled), compile-pollution fix (reused-binary records never contribute
compile), deterministic flat scaling, and recency-weighting sanity.
"""
import json

from tavi.machine_profile import machine_fingerprint
from tavi.runtime_tracker import RuntimeTracker, ScanRecord


def _rec(name="in8", first=12.0, avg=2.0, neutrons=100000, points=5,
         compile_t=0.0, ts="2026-07-01T00:00:00", machine_id=None,
         engine="mcstas", execution_mode=None, binary_reused=None,
         build_fp_hash=None, source="organic"):
    return {
        "instrument_name": name,
        "num_points": points,
        "num_neutrons": neutrons,
        "first_scan_time": first,
        "avg_subsequent_time": avg,
        "total_time": first + (points - 1) * avg,
        "timestamp": ts,
        "compilation_time": compile_t,
        "machine_id": machine_id,
        "engine": engine,
        "execution_mode": execution_mode,
        "binary_reused": binary_reused,
        "build_fp_hash": build_fp_hash,
        "source": source,
    }


def _tracker(tmp_path, payload):
    config = tmp_path / "runtimes.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    return RuntimeTracker(config_path=str(config))


# --------------------------------------------------------------------------
# Schema v2: load / round-trip / tolerance
# --------------------------------------------------------------------------

def test_v1_file_loads_unchanged(tmp_path):
    # v1 file: no version, no machines, no v2 record fields.
    v1_rec = {
        "instrument_name": "in8", "num_points": 5, "num_neutrons": 100000,
        "first_scan_time": 12.0, "avg_subsequent_time": 2.0,
        "total_time": 20.0, "timestamp": "2025-01-01T00:00:00",
        "compilation_time": 4.0,
    }
    tracker = _tracker(tmp_path, {"records": {"in8": [v1_rec]}})
    assert tracker.get_record_count("in8") == 1
    rec = tracker.records["in8"][0]
    # v2 fields default sensibly.
    assert rec.machine_id is None
    assert rec.engine == "mcstas"
    assert rec.source == "organic"
    assert rec.binary_reused is None
    assert tracker.machines == {}


def test_v2_round_trip(tmp_path):
    config = tmp_path / "runtimes.json"
    config.write_text(json.dumps({"records": {}}), encoding="utf-8")
    tracker = RuntimeTracker(config_path=str(config))
    tracker.set_machine_profile("abc123", hostname="host", cpu_name="CPU",
                                cpu_count=8, speed_index=1e-5,
                                benchmarked_at="2026-07-01T00:00:00")
    tracker.add_record(instrument_name="in8", num_points=5, num_neutrons=100000,
                       first_scan_time=12.0, avg_subsequent_time=2.0,
                       total_time=20.0, compilation_time=4.0,
                       machine_id="abc123", engine="mcstas",
                       execution_mode="backengine", binary_reused=False,
                       build_fp_hash="deadbeef0001", source="benchmark")

    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert "abc123" in saved["machines"]
    assert saved["machines"]["abc123"]["speed_index"] == 1e-5
    rec = saved["records"]["in8"][0]
    assert rec["machine_id"] == "abc123"
    assert rec["binary_reused"] is False
    assert rec["source"] == "benchmark"

    # Reload preserves everything.
    reloaded = RuntimeTracker(config_path=str(config))
    assert reloaded.machines["abc123"]["cpu_name"] == "CPU"
    got = reloaded.records["in8"][0]
    assert got.execution_mode == "backengine"
    assert got.build_fp_hash == "deadbeef0001"


def test_unknown_future_field_tolerated(tmp_path):
    # A future schema adds a field this version doesn't know. History must
    # survive (not wiped by a TypeError).
    rec = _rec(name="in8")
    rec["some_future_field"] = {"nested": [1, 2, 3]}
    tracker = _tracker(tmp_path, {"version": 3, "records": {"in8": [rec]}})
    assert tracker.get_record_count("in8") == 1
    assert not hasattr(tracker.records["in8"][0], "some_future_field")


def test_malformed_machines_block_is_ignored(tmp_path):
    tracker = _tracker(tmp_path, {"records": {"in8": [_rec()]},
                                  "machines": "not-a-dict"})
    assert tracker.machines == {}
    assert tracker.get_record_count("in8") == 1


# --------------------------------------------------------------------------
# Selection chain: local / legacy / scaled / pooled
# --------------------------------------------------------------------------

def test_basis_local_when_machine_matches(tmp_path):
    me = machine_fingerprint()["machine_id"]
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=me),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 10, 100000, needs_compile=False)
    assert est["basis"] == "local"
    assert est["machine_samples"] == 1
    assert est["estimated_seconds"] == 20.0


def test_basis_legacy_when_machine_id_none(tmp_path):
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=None),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 10, 100000, needs_compile=False)
    assert est["basis"] == "legacy"
    assert est["confidence"] in ("low", "medium")  # capped at medium
    assert est["estimated_seconds"] == 20.0


def test_basis_scaled_for_foreign_machine_with_speed_index(tmp_path):
    me = machine_fingerprint()["machine_id"]
    payload = {
        "records": {"in8": [
            _rec(avg=4.0, neutrons=100000, machine_id="foreign", source="benchmark"),
        ]},
        "machines": {
            me: {"speed_index": 1e-5, "cpu_name": "fast"},
            "foreign": {"speed_index": 2e-5, "cpu_name": "slow"},
        },
    }
    tracker = _tracker(tmp_path, payload)
    est = tracker.estimate_scan_seconds("in8", 10, 100000, needs_compile=False)
    assert est["basis"] == "scaled"
    # foreign 4.0 s/pt * (local 1e-5 / foreign 2e-5) = 2.0 s/pt * 10 = 20.0
    assert est["estimated_seconds"] == 20.0
    assert est["confidence"] == "low"


def test_basis_pooled_when_foreign_without_speed_index(tmp_path):
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id="foreign"),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 10, 100000, needs_compile=False)
    assert est["basis"] == "pooled"
    assert est["confidence"] == "low"
    assert est["estimated_seconds"] == 20.0


def test_local_preferred_over_legacy(tmp_path):
    me = machine_fingerprint()["machine_id"]
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=5.0, neutrons=100000, machine_id=me),
        _rec(avg=99.0, neutrons=100000, machine_id=None),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 1, 100000, needs_compile=False)
    assert est["basis"] == "local"
    assert est["estimated_seconds"] == 5.0
    assert est["machine_samples"] == 1


# --------------------------------------------------------------------------
# Engine filtering + deterministic flat scaling
# --------------------------------------------------------------------------

def test_engine_filter_separates_pools(tmp_path):
    me = machine_fingerprint()["machine_id"]
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=me, engine="mcstas"),
        _rec(avg=50.0, neutrons=100000, machine_id=me, engine="deterministic"),
    ]}})
    mcstas = tracker.estimate_scan_seconds("in8", 1, 100000, needs_compile=False,
                                           engine="mcstas")
    assert mcstas["estimated_seconds"] == 2.0


def test_deterministic_per_point_is_flat_not_scaled(tmp_path):
    me = machine_fingerprint()["machine_id"]
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=3.0, neutrons=100000, machine_id=me, engine="deterministic"),
    ]}})
    # Request 10x the neutrons: deterministic cost is ncount-independent,
    # so per-point stays 3.0 (NOT 30.0).
    est = tracker.estimate_scan_seconds("in8", 4, 1000000, needs_compile=False,
                                        engine="deterministic")
    assert est["estimated_seconds"] == 12.0


# --------------------------------------------------------------------------
# Compile-pollution fix
# --------------------------------------------------------------------------

def test_reused_binary_never_contributes_compile(tmp_path):
    me = machine_fingerprint()["machine_id"]
    # A reused-binary record with a large first_scan_time must NOT inflate
    # the compile estimate via first-avg inference.
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(first=500.0, avg=2.0, neutrons=100000, machine_id=me,
             binary_reused=True, compile_t=0.0),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 5, 100000, needs_compile=True)
    # No compile sample -> compile 0; per-point 2.0 * 5 = 10.0.
    assert est["estimated_seconds"] == 10.0


def test_non_reused_compile_sample_used(tmp_path):
    me = machine_fingerprint()["machine_id"]
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=me, binary_reused=False,
             compile_t=6.0),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 5, 100000, needs_compile=True)
    assert est["estimated_seconds"] == 16.0  # 10 per-point + 6 compile


# --------------------------------------------------------------------------
# Recency weighting sanity
# --------------------------------------------------------------------------

def test_recent_record_dominates_stale_record(tmp_path):
    me = machine_fingerprint()["machine_id"]
    from datetime import datetime, timedelta
    recent = (datetime.now() - timedelta(days=1)).isoformat()
    stale = (datetime.now() - timedelta(days=400)).isoformat()
    # Two recent samples at 2.0, one very old at 100.0. Weighted median must
    # sit at the recent value, not be dragged up by the stale sample.
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=me, ts=recent),
        _rec(avg=2.0, neutrons=100000, machine_id=me, ts=recent),
        _rec(avg=100.0, neutrons=100000, machine_id=me, ts=stale),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 1, 100000, needs_compile=False)
    assert est["estimated_seconds"] == 2.0


def test_benchmark_floor_weight_survives_decay(tmp_path):
    me = machine_fingerprint()["machine_id"]
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=400)).isoformat()
    # A lone, old benchmark anchor should still produce an estimate (floor
    # weight prevents it decaying to zero-weight/no-usable-sample).
    tracker = _tracker(tmp_path, {"records": {"in8": [
        _rec(avg=2.0, neutrons=100000, machine_id=me, ts=old, source="benchmark"),
    ]}})
    est = tracker.estimate_scan_seconds("in8", 5, 100000, needs_compile=False)
    assert est["estimated_seconds"] == 10.0
