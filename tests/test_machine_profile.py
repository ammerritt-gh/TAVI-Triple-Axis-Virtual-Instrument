"""Tests for tavi.machine_profile: fingerprint stability, graceful CPU-name
degradation, and the benchmark-derived speed index."""
from dataclasses import dataclass

import tavi.machine_profile as mp
from tavi.machine_profile import machine_fingerprint, machine_speed_index


@dataclass
class _Rec:
    num_neutrons: int = 100000
    num_points: int = 5
    first_scan_time: float = 12.0
    avg_subsequent_time: float = 2.0
    engine: str = "mcstas"
    source: str = "benchmark"


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------

def test_fingerprint_has_expected_keys(monkeypatch):
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    fp = machine_fingerprint()
    assert set(fp) == {"machine_id", "hostname", "machine", "cpu_count",
                       "cpu_name"}
    assert isinstance(fp["machine_id"], str) and len(fp["machine_id"]) == 12


def test_fingerprint_is_stable_across_calls(monkeypatch):
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    first = machine_fingerprint()
    second = machine_fingerprint()
    assert first == second
    assert first["machine_id"] == second["machine_id"]


def test_fingerprint_returns_copy(monkeypatch):
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    fp = machine_fingerprint()
    fp["machine_id"] = "tampered"
    assert machine_fingerprint()["machine_id"] != "tampered"


def test_fingerprint_deterministic_for_fixed_inputs(monkeypatch):
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(mp.platform, "node", lambda: "host-a")
    monkeypatch.setattr(mp.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(mp.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(mp, "_cpu_name", lambda: "Test CPU")
    fp1 = machine_fingerprint()

    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    fp2 = machine_fingerprint()
    assert fp1["machine_id"] == fp2["machine_id"]

    # A different host must yield a different id.
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)
    monkeypatch.setattr(mp.platform, "node", lambda: "host-b")
    fp3 = machine_fingerprint()
    assert fp3["machine_id"] != fp1["machine_id"]


def test_cpu_name_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(mp, "_FINGERPRINT_CACHE", None)

    def _boom():
        raise RuntimeError("no cpu info")

    monkeypatch.setattr(mp.platform, "processor", _boom)
    monkeypatch.setattr(mp.platform, "system", lambda: "Windows")
    # _cpu_name swallows the error and returns "".
    assert mp._cpu_name() == ""
    fp = machine_fingerprint()
    assert fp["cpu_name"] == ""
    assert len(fp["machine_id"]) == 12


# --------------------------------------------------------------------------
# Speed index
# --------------------------------------------------------------------------

def test_speed_index_none_without_benchmark_records():
    assert machine_speed_index([]) is None
    organic = _Rec(source="organic")
    assert machine_speed_index([organic]) is None


def test_speed_index_median_per_neutron():
    # Two benchmark records at 2.0 s/pt @ 100k -> 2e-5 s/neutron each.
    recs = [_Rec(avg_subsequent_time=2.0, num_neutrons=100000)]
    assert machine_speed_index(recs) == 2.0 / 100000


def test_speed_index_ignores_deterministic_and_organic():
    recs = [
        _Rec(source="organic", avg_subsequent_time=99.0),
        _Rec(engine="deterministic", avg_subsequent_time=99.0),
        _Rec(source="benchmark", avg_subsequent_time=3.0, num_neutrons=100000),
    ]
    assert machine_speed_index(recs) == 3.0 / 100000
