"""Orientation core: the one sense-aware angles-to-Q path and the UB fit on it.

Peaks are generated through each instrument's own angle solve
(``calculate_angles``) at both sample senses, so the fit sees exactly the
signed readouts an operator's Take Position records.
"""
import importlib

import numpy as np
import pytest

from tavi.neutron_conversions import k2energy
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    mccode_rotation_matrix,
    solve_instrument_angles,
)
from tavi.ub_matrix import ObservedPeak, UBMatrix

LATTICE = (4.05, 4.05, 4.05, 90.0, 90.0, 90.0)
K = 2.0                        # elastic, reachable on every instrument's PG(002)
E_K = k2energy(K)
U_IN_PLANE = mccode_rotation_matrix(0.0, 23.0, 0.0)   # about the vertical mount y
PEAKS_2 = [(1, 0, 0), (0, 1, 0)]
PEAKS_3 = [(1, 0, 0), (0, 1, 0), (1, 1, 1)]           # (1,1,1) needs a tilt

INSTRUMENTS = {
    "puma": ("instruments.puma.model", "PUMA_Instrument"),
    "in8": ("instruments.in8.model", "IN8_Instrument"),
    "in12": ("instruments.in12.model", "IN12_Instrument"),
    "panda": ("instruments.panda.model", "PANDA_Instrument"),
}


@pytest.fixture(scope="module")
def models():
    pytest.importorskip("mcstasscript")
    return {
        name: getattr(importlib.import_module(module), cls)()
        for name, (module, cls) in INSTRUMENTS.items()
    }


def _peak(model, B, hkl, U):
    """Record a peak at the setting the instrument solves for U.B.hkl."""
    qx, qy, qz = component_q_to_instrument_q(U @ B @ np.array(hkl, dtype=float))
    angles, flags = model.calculate_angles(
        qx, qy, qz, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
    assert flags == []
    _mtt, stt, sth, saz, _att = angles
    peak = ObservedPeak(hkl=tuple(hkl), angles=(sth, saz, stt), ki=K, kf=K)
    peak.readouts = angles   # test-only: the full (mtt, stt, sth, saz, att)
    return peak


@pytest.mark.parametrize("hkls", [PEAKS_2, PEAKS_3], ids=["2peak", "3peak"])
@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_fit_recovers_known_u_for_every_instrument_and_sense(models, name, sense, hkls):
    model = models[name]
    model.sense_sample = sense
    ub = UBMatrix(*LATTICE)
    ub.peaks = [_peak(model, ub.B, hkl, U_IN_PLANE) for hkl in hkls]

    assert all(np.sign(p.angles[2]) == sense for p in ub.peaks)
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, U_IN_PLANE, rtol=0.0, atol=1e-9)

    # The runtime readback goes through the same function: angles -> Q.
    for peak in ub.peaks:
        q_and_e, flags = model.calculate_q_and_deltaE(
            *peak.readouts, E_K, "Kf Fixed", "pg002", "pg002")
        assert flags == []
        expected = component_q_to_instrument_q(U_IN_PLANE @ ub.B @ np.array(peak.hkl, float))
        assert np.allclose(q_and_e[:3], expected, rtol=0.0, atol=1e-9)


def test_legacy_peak_dict_with_positive_stt_fits_correctly(models):
    model = models["in8"]
    model.sense_sample = 1
    B = UBMatrix(*LATTICE).B
    saved = []
    for hkl in PEAKS_2:
        d = _peak(model, B, hkl, U_IN_PLANE).to_dict()
        d.pop("sense_sample", None)
        d.pop("stage", None)
        assert d["angles"][2] > 0
        saved.append(d)

    ub = UBMatrix.from_dict({"lattice": list(LATTICE), "peaks": saved})
    assert [p.sense_sample for p in ub.peaks] == [1, 1]
    assert [p.stage for p in ub.peaks] == [None, None]
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, U_IN_PLANE, rtol=0.0, atol=1e-9)


def test_peak_sense_and_stage_round_trip_through_dict():
    peak = ObservedPeak(hkl=(1, 0, 0), angles=(10.0, 0.0, 40.0), ki=K, kf=K,
                        sense_sample=-1, stage={"A3": 10.0})
    back = ObservedPeak.from_dict(peak.to_dict())
    assert back.sense_sample == -1
    assert back.stage == {"A3": 10.0}


@pytest.mark.parametrize("hkls", [
    [(1, 0, 0), (2, 0, 0)],
    [(1, 0, 0), (2, 0, 0), (-1, 0, 0)],
], ids=["2peak", "3peak"])
def test_failed_fit_leaves_previous_ub_in_place(hkls):
    ub = UBMatrix(*LATTICE)
    ub.set_U(U_IN_PLANE)
    before_u, before_ub = ub.U, ub.UB
    ub.peaks = []
    for hkl in hkls:
        q = component_q_to_instrument_q(ub.UB @ np.array(hkl, dtype=float))
        a = solve_instrument_angles(q, K, K)
        ub.peaks.append(ObservedPeak(hkl=hkl, angles=(a.sth, a.saz, a.stt), ki=K, kf=K))

    with pytest.raises(ValueError, match="collinear"):
        ub.calculate_U_from_peaks()
    assert np.array_equal(ub.U, before_u)
    assert np.array_equal(ub.UB, before_ub)


# TAS_MCP (MCPs/TAS_MCP, tas_mcp/session.py set_orientation_from_peaks) builds
# peaks with the legacy triple only; its feasibility tool reports stt on the
# baked negative branch (stt_from_q_norm / solve_instrument_angles default
# sense -1), so that is the sign its callers pass back. U values below were
# produced by this exact call on the unit's base (971a91e9).
TAS_MCP_K = 2.6634
TAS_MCP_BASE_U = {
    2: [[0.9254165783983234, 0.2146101771427565, -0.3123245560187264],
        [-0.33682408883346515, 0.843493268656316, -0.41841204441673263],
        [0.17364817766693036, 0.49240387650610407, 0.8528685319524433]],
    3: [[0.9254165783983233, 0.21461017714275607, -0.3123245560187262],
        [-0.3368240888334649, 0.8434932686563159, -0.41841204441673285],
        [0.17364817766693047, 0.492403876506104, 0.8528685319524432]],
}


@pytest.mark.parametrize("hkls", [PEAKS_2, PEAKS_3], ids=["2peak", "3peak"])
def test_tas_mcp_constructor_call_is_bit_identical_to_base(hkls):
    u_true = mccode_rotation_matrix(-30, 10, 20)
    ub = UBMatrix(*LATTICE)
    raw = []
    for hkl in hkls:
        q = component_q_to_instrument_q(u_true @ ub.B @ np.array(hkl, dtype=float))
        a = solve_instrument_angles(q, TAS_MCP_K, TAS_MCP_K)
        raw.append({"hkl": list(hkl), "angles": [a.sth, a.saz, a.stt],
                    "ki": TAS_MCP_K, "kf": TAS_MCP_K})
    # Mirror of session.py's constructor call, verbatim in shape.
    ub.peaks = [
        ObservedPeak(
            hkl=tuple(p["hkl"]),
            angles=tuple(p["angles"]),
            ki=float(p["ki"]),
            kf=float(p["kf"]),
        )
        for p in raw
    ]
    ub.calculate_U_from_peaks()
    assert ub.U.tolist() == TAS_MCP_BASE_U[len(hkls)]
