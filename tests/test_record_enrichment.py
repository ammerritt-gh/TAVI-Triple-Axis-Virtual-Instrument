"""Tests for schema-v2 record enrichment at scan-record time (step 4).

Two surfaces, both headless (no McStas run):

  * ``RuntimeTracker.add_record`` persistence of the engine-specific schema-v2
    fields the McStas and deterministic recording paths write -- Qt-free, via a
    temp ``runtimes.json``. This is the record *contract* both engines rely on.
  * ``TAVIController._dominant_execution_mode`` -- the static derivation the
    McStas path uses to stamp ``execution_mode`` (style of test_binary_reuse.py;
    importing TAVI_PySide6 needs PySide6 + mcstasscript, so it skips otherwise).
"""
import json

import pytest

from tavi.runtime_tracker import RuntimeTracker
from tavi.machine_profile import machine_fingerprint


# ==========================================================================
# add_record persistence of schema-v2 engine fields (Qt-free)
# ==========================================================================

def _tracker(tmp_path):
    return RuntimeTracker(config_path=str(tmp_path / "runtimes.json"))


def _only_record(tmp_path):
    """Reload from disk and return the single persisted record dict."""
    data = json.loads((tmp_path / "runtimes.json").read_text(encoding="utf-8"))
    recs = data["records"]["puma"]
    assert len(recs) == 1
    return recs[0], data


def test_mcstas_record_fields_persist(tmp_path):
    tracker = _tracker(tmp_path)
    machine_id = machine_fingerprint()["machine_id"]
    tracker.add_record(
        instrument_name="puma",
        num_points=5,
        num_neutrons=100000,
        first_scan_time=12.0,
        avg_subsequent_time=2.0,
        total_time=20.0,
        compilation_time=10.0,
        machine_id=machine_id,
        engine="mcstas",
        execution_mode="backengine",
        binary_reused=False,
        build_fp_hash="abc123def456",
        source="organic",
    )
    rec, data = _only_record(tmp_path)
    assert data["version"] == 2
    assert rec["engine"] == "mcstas"
    assert rec["machine_id"] == machine_id
    assert rec["execution_mode"] == "backengine"
    assert rec["binary_reused"] is False
    assert rec["build_fp_hash"] == "abc123def456"
    assert rec["source"] == "organic"
    assert rec["compilation_time"] == 10.0


def test_reused_binary_record_carries_zero_compile(tmp_path):
    """Reuse path records binary_reused=True and no compile time (step 4)."""
    tracker = _tracker(tmp_path)
    tracker.add_record(
        instrument_name="puma",
        num_points=5,
        num_neutrons=100000,
        first_scan_time=2.1,
        avg_subsequent_time=2.0,
        total_time=10.0,
        compilation_time=0.0,
        machine_id=machine_fingerprint()["machine_id"],
        engine="mcstas",
        execution_mode="direct",
        binary_reused=True,
        build_fp_hash="deadbeefcafe",
        source="organic",
    )
    rec, _ = _only_record(tmp_path)
    assert rec["binary_reused"] is True
    assert rec["compilation_time"] == 0.0
    # A reused-binary record must never feed the compile estimator.
    records = tracker.records["puma"]
    pairs = [(r, 1.0) for r in records]
    assert tracker._compile_seconds(pairs) == 0.0


def test_deterministic_record_fields_persist(tmp_path):
    tracker = _tracker(tmp_path)
    machine_id = machine_fingerprint()["machine_id"]
    tracker.add_record(
        instrument_name="puma",
        num_points=20,
        num_neutrons=100000,
        first_scan_time=0.05,
        avg_subsequent_time=0.05,
        total_time=1.0,
        compilation_time=0.0,
        machine_id=machine_id,
        engine="deterministic",
        execution_mode=None,
        binary_reused=None,
        build_fp_hash=None,
        source="organic",
    )
    rec, _ = _only_record(tmp_path)
    assert rec["engine"] == "deterministic"
    assert rec["machine_id"] == machine_id
    assert rec["compilation_time"] == 0.0
    assert rec["binary_reused"] is None
    assert rec["build_fp_hash"] is None


def test_benchmark_source_is_recorded(tmp_path):
    tracker = _tracker(tmp_path)
    tracker.add_record(
        instrument_name="puma",
        num_points=3,
        num_neutrons=10000,
        first_scan_time=5.0,
        avg_subsequent_time=1.0,
        total_time=8.0,
        machine_id=machine_fingerprint()["machine_id"],
        engine="mcstas",
        source="benchmark",
    )
    rec, _ = _only_record(tmp_path)
    assert rec["source"] == "benchmark"


def test_engine_filtered_estimate_ignores_other_engine(tmp_path):
    """A deterministic record must not feed the mcstas estimate and vice versa."""
    tracker = _tracker(tmp_path)
    machine_id = machine_fingerprint()["machine_id"]
    # One slow mcstas record ...
    tracker.add_record(
        instrument_name="puma", num_points=3, num_neutrons=100000,
        first_scan_time=30.0, avg_subsequent_time=30.0, total_time=90.0,
        machine_id=machine_id, engine="mcstas", source="organic",
    )
    # ... and one fast deterministic record.
    tracker.add_record(
        instrument_name="puma", num_points=3, num_neutrons=100000,
        first_scan_time=0.05, avg_subsequent_time=0.05, total_time=0.15,
        machine_id=machine_id, engine="deterministic", source="organic",
    )
    mcstas = tracker.estimate_scan_seconds(
        "puma", 3, 100000, needs_compile=False, engine="mcstas")
    det = tracker.estimate_scan_seconds(
        "puma", 3, 100000, needs_compile=False, engine="deterministic")
    assert mcstas["samples"] == 1
    assert det["samples"] == 1
    # The mcstas estimate reflects the 30s/point record, not the 0.05s one.
    assert mcstas["estimated_seconds"] > 10.0
    assert det["estimated_seconds"] < 1.0


# ==========================================================================
# _dominant_execution_mode static derivation (Qt-bound; skips without deps)
# ==========================================================================

# Guarded import so the Qt-free tests above always run; only the static-method
# tests below skip when PySide6 / mcstasscript are unavailable.
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


def _timing(mode):
    return {"execution_mode": mode}


@qt_required
def test_dominant_mode_all_backengine():
    fn = controller_module.TAVIController._dominant_execution_mode
    assert fn([_timing("backengine"), _timing("backengine")]) == "backengine"


@qt_required
def test_dominant_mode_all_direct():
    fn = controller_module.TAVIController._dominant_execution_mode
    assert fn([_timing("direct"), _timing("direct")]) == "direct"


@qt_required
def test_dominant_mode_mixed():
    fn = controller_module.TAVIController._dominant_execution_mode
    assert fn([_timing("backengine"), _timing("direct")]) == "mixed"


@qt_required
def test_dominant_mode_skipped_only_is_none():
    fn = controller_module.TAVIController._dominant_execution_mode
    assert fn([_timing("skipped"), _timing(None)]) is None


@qt_required
def test_dominant_mode_empty_is_none():
    fn = controller_module.TAVIController._dominant_execution_mode
    assert fn([]) is None
    assert fn(None) is None
