"""Tests for tavi.machine_profile: fingerprint stability, graceful CPU-name
degradation, and the benchmark-derived affine time model."""
from dataclasses import dataclass

import pytest

import tavi.machine_profile as mp
from tavi.machine_profile import (machine_fingerprint, machine_speed_index,
                                  machine_time_model)


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
# Affine time model + deprecated speed-index alias
# --------------------------------------------------------------------------

def test_time_model_none_without_benchmark_records():
    assert machine_time_model([]) is None
    assert machine_time_model([_Rec(source="organic")]) is None


def test_time_model_none_from_single_ncount():
    # A single ncount carries no rate information -> no affine model.
    assert machine_time_model([_Rec(avg_subsequent_time=2.0,
                                    num_neutrons=100000)]) is None


def test_time_model_recovers_overhead_and_rate():
    # per_point = 1.0 + 1e-6 * N: at 1e5 -> 1.1, at 1e6 -> 2.0.
    recs = [
        _Rec(avg_subsequent_time=1.1, num_neutrons=100000),
        _Rec(avg_subsequent_time=2.0, num_neutrons=1000000),
    ]
    model = machine_time_model(recs)
    assert model["overhead"] == pytest.approx(1.0, rel=1e-6)
    assert model["rate"] == pytest.approx(1e-6, rel=1e-6)


def test_speed_index_alias_returns_rate():
    recs = [
        _Rec(avg_subsequent_time=1.1, num_neutrons=100000),
        _Rec(avg_subsequent_time=2.0, num_neutrons=1000000),
    ]
    assert machine_speed_index(recs) == pytest.approx(1e-6, rel=1e-6)


def test_speed_index_none_without_benchmark_records():
    assert machine_speed_index([]) is None
    assert machine_speed_index([_Rec(source="organic")]) is None


def test_time_model_ignores_deterministic_and_organic():
    # Only the two clean mcstas benchmark records feed the fit; the noisy
    # organic/deterministic rows at the same ncounts are excluded.
    recs = [
        _Rec(source="organic", avg_subsequent_time=99.0, num_neutrons=100000),
        _Rec(engine="deterministic", avg_subsequent_time=99.0,
             num_neutrons=1000000),
        _Rec(source="benchmark", avg_subsequent_time=1.1, num_neutrons=100000),
        _Rec(source="benchmark", avg_subsequent_time=2.0, num_neutrons=1000000),
    ]
    model = machine_time_model(recs)
    assert model["overhead"] == pytest.approx(1.0, rel=1e-6)
    assert model["rate"] == pytest.approx(1e-6, rel=1e-6)
