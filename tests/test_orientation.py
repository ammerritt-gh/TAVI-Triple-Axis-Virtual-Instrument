"""Orientation core: the sample stage, its solver, the McStas sample arm, and
the UB fit on them.

Peaks are generated through each instrument's own stage solve
(``calculate_stage_angles``) at both sample senses, so the fit sees exactly
the readouts an operator records. The McStas rule is composed here arm by
arm, independently of ``sample_arm_euler``, as the generated C does it:
``R_abs(child) = R_rel @ R_abs(parent)``, ``v_local = R_abs @ v_global``,
``R_rel = mccode_rotation_matrix(ROTATED)``.
"""
import copy
import dataclasses
import importlib
import math

import numpy as np
import pytest

from instruments.tas_runtime import HKL_CALC, MOTORS, Q_CALC
from plan_helpers import context, hkl_point, motors_point, plan_for, q_point
from tavi.neutron_conversions import energy2k, k2energy
from tavi.orientation import (
    StageAxis,
    StageUnreachable,
    check_travel,
    lock_plane,
    q_mount_from_stage,
    sample_arm_euler,
    solve_stage,
    stage_record,
    stage_rotation,
)
from tavi.sample_mount import SampleMount, reciprocal_basis_tas
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    instrument_q_to_component_q,
    lab_q_from_stt,
    mccode_rotation_matrix,
    solve_instrument_angles,
    stt_from_q_norm,
)
from tavi.ub_matrix import ObservedPeak, UBMatrix

LATTICE = (4.05, 4.05, 4.05, 90.0, 90.0, 90.0)
K = 2.0                        # elastic, reachable on every instrument's PG(002)
E_K = k2energy(K)
U_IN_PLANE = mccode_rotation_matrix(0.0, 23.0, 0.0)   # about the vertical mount y
PEAKS_2 = [(1, 0, 0), (0, 1, 0)]
# The third peak needs a tilt (12.6 deg of elevation), inside every
# instrument's arc travel (PANDA's +/-15 deg is the tightest).
PEAKS_3 = [(1, 0, 0), (0, 1, 0), (2, 1, 0.5)]

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


# --- independent helpers ------------------------------------------------------

def _rot(axis, deg):
    """Right-handed rotation about an axis, written out in the test."""
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k)


def _arm_rotated(axis, deg):
    """ROTATED of an Arm turning ``deg`` right-handedly about a coordinate
    axis of its parent: McStas sets R_rel = X/Y/Z(angle), each the transpose
    of the active rotation, so the angle goes in the axis's own slot."""
    return tuple(deg * float(c) for c in axis)


def _mcstas_lab_vector(chain, v_local):
    """A vector fixed in the last arm of ``chain`` (R_rel per arm, from the
    sample-position frame outward), expressed in the sample-position frame."""
    r_abs = np.eye(3)
    for r_rel in chain:
        r_abs = r_rel @ r_abs
    return r_abs.T @ v_local


def _stage_chain(gonio, angles, u):
    """One Arm per stage axis, then the crystal mount (R_rel = U^T)."""
    chain = [mccode_rotation_matrix(*_arm_rotated(ax.axis, angles[ax.name]))
             for ax in gonio]
    chain.append(np.asarray(u).T)
    return chain


def _stage_readouts(angles):
    _mtt, _stt, sth, sgl, _att, sgu = angles
    return {"A3": sth, "sgl": sgl, "sgu": sgu}


def _peak(model, B, hkl, U):
    """Record a peak, with its stage record, at the setting the instrument
    solves for U.B.hkl."""
    qx, qy, qz = component_q_to_instrument_q(U @ B @ np.array(hkl, dtype=float))
    angles, flags = model.calculate_stage_angles(
        qx, qy, qz, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
    assert flags == []
    _mtt, stt, sth, sgl, _att, _sgu = angles
    peak = ObservedPeak(hkl=tuple(hkl), angles=(sth, sgl, stt), ki=K, kf=K,
                        stage=stage_record(model.goniometer, _stage_readouts(angles)))
    peak.readouts = angles   # test-only: the full (mtt, stt, sth, sgl, att, sgu)
    return peak


# --- the UB fit ------------------------------------------------------------------

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

    # The runtime readback goes through the same stage: angles -> Q.
    for peak in ub.peaks:
        mtt, stt, sth, sgl, att, sgu = peak.readouts
        q_and_e, flags = model.calculate_q_and_deltaE(
            mtt, stt, sth, sgl, att, E_K, "Kf Fixed", "pg002", "pg002", sgu=sgu)
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


def test_tilted_legacy_peaks_on_the_positive_sense_fit_back():
    """Peaks without a stage record, taken on the +1 branch with a nonzero
    legacy tilt (saz): the fit reads them through the legacy inverse and
    recovers the tilted U."""
    u_true = mccode_rotation_matrix(-30, 10, 20)
    ub = UBMatrix(*LATTICE)
    saved = []
    for hkl in [(1, 0, 0), (0, 1, 0), (1, 1, 1)]:
        q = component_q_to_instrument_q(u_true @ ub.B @ np.array(hkl, dtype=float))
        a = solve_instrument_angles(q, K, K, sense_sample=1)
        saved.append({"hkl": list(hkl), "angles": [a.sth, a.saz, a.stt], "ki": K, "kf": K})
    assert all(d["angles"][2] > 0 for d in saved)
    assert max(abs(d["angles"][1]) for d in saved) > 5.0

    ub = UBMatrix.from_dict({"lattice": list(LATTICE), "peaks": saved})
    assert [(p.sense_sample, p.stage) for p in ub.peaks] == [(1, None)] * 3
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, u_true, rtol=0.0, atol=1e-9)


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_legacy_triple_of_a_tilted_stage_peak_fits_the_same_u(models, name, sense):
    """The triple saved beside a stage record, read without the record (and
    without its sense, as an older reader does), fits the same tilted U."""
    from tavi.orientation import legacy_triple

    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    u_true = _rot((1, 0, 0), 6.0) @ _rot((0, 0, 1), -4.0) @ U_IN_PLANE
    B = UBMatrix(*LATTICE).B
    legacy = []
    for hkl in PEAKS_3:
        peak = _peak(model, B, hkl, u_true)
        stt = peak.angles[2]
        legacy.append({"hkl": list(hkl), "angles": list(legacy_triple(peak.stage, stt, K, K, sense)),
                       "ki": K, "kf": K})
    assert max(abs(d["angles"][1]) for d in legacy) > 1.0       # tilted: saz is used
    ub = UBMatrix.from_dict({"lattice": list(LATTICE), "peaks": legacy})
    assert all(p.is_legacy and p.sense_sample == sense for p in ub.peaks)
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, u_true, rtol=0.0, atol=1e-9)


def test_peak_sense_and_stage_round_trip_through_dict():
    peak = ObservedPeak(hkl=(1, 0, 0), angles=(10.0, 0.0, 40.0), ki=K, kf=K,
                        sense_sample=-1, stage={"A3": 10.0})
    back = ObservedPeak.from_dict(peak.to_dict())
    assert back.sense_sample == -1
    assert back.stage == {"A3": 10.0}


# --- 1.7: Take Position records the stage; the fit rule (A1) -------------------

def _miss_deg(a, b):
    return math.degrees(math.acos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_peaks_taken_on_the_true_crystal_drive_it_back_to_a_new_hkl(models, name, sense):
    """Peaks taken where the TRUE crystal reflects, refit, drive to a new HKL:
    the emitted stage angles put the per-sense -/+ U_true B hkl on Q_lab. The
    record holds the readouts, ki, kf and the sense, nothing else."""
    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    u_true = _rot((1, 0, 0), 3.0) @ U_IN_PLANE
    model.U_true = u_true                  # the arm reads the true mount
    gonio = model.goniometer

    def solve(q_mount):
        qx, qy, qz = component_q_to_instrument_q(q_mount)
        angles, flags = model.calculate_stage_angles(
            qx, qy, qz, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
        assert flags == []
        return angles

    peaks = []
    for hkl in [(1, 0, 0), (0, 1, 0), (1, 1, 0)]:
        _mtt, stt, a3, sgl, _att, sgu = solve(u_true @ CUBIC_B @ np.array(hkl, float))
        record = stage_record(gonio, {"A3": a3, "sgl": sgl, "sgu": sgu},
                              ki=K, kf=K, sense=sense)
        assert set(record) == {"axes", "angles", "ki", "kf", "sense"}
        peaks.append(ObservedPeak(hkl=hkl, angles=(a3, 0.0, stt), ki=K, kf=K, stage=record))
    assert all(p.sense_sample == sense for p in peaks)

    ub = UBMatrix(*LATTICE)
    ub.peaks = peaks
    ub.calculate_U_from_peaks()
    target = np.array((1, -1, 0), dtype=float)
    _mtt, stt, a3, sgl, _att, sgu = solve(ub.UB @ target)
    model.sample_rotation_deg, model.sgl, model.sgu = a3, sgl, sgu
    params = model.build_point_params(0.0)
    arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                 params["sample_rz_param"])      # (R_stage U_true)^T
    lab = arm.T @ (CUBIC_B @ target)
    assert np.allclose(-lab if sense > 0 else lab, lab_q_from_stt(K, K, stt),
                       rtol=0.0, atol=1e-9)


def test_a_stage_record_holds_the_readouts_and_nothing_retired():
    from instruments.descriptor import tas_goniometer
    from tavi.orientation import record_angles

    record = stage_record(tas_goniometer(), {"A3": 30.0, "sgl": 2.0, "sgu": -1.0},
                          ki=K, kf=K, sense=1)
    assert set(record) == {"axes", "angles", "ki", "kf", "sense"}
    assert record_angles(record) == {"A3": 30.0, "sgl": 2.0, "sgu": -1.0}


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


@pytest.mark.parametrize("hkls", [PEAKS_2, [(1, 0, 0), (0, 1, 0), (1, 1, 1)]],
                         ids=["2peak", "3peak"])
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


# --- lens 1: the stage round trip through the McStas rule ------------------------

LATTICES = {
    "cubic": (4.05, 4.05, 4.05, 90.0, 90.0, 90.0),
    "hexagonal": (3.21, 3.21, 5.21, 90.0, 90.0, 120.0),
    "monoclinic": (5.10, 6.30, 7.20, 90.0, 103.5, 90.0),
}
K_RT = 2.662
E_RT = k2energy(K_RT)
HKL_POOL = [(h, k, l) for h in range(-3, 4) for k in range(-3, 4) for l in (-1, 0, 1)
            if (h, k, l) != (0, 0, 0)]
SEEDS = {name: 101 * i for i, name in enumerate(INSTRUMENTS, start=1)}


def _random_mount(rng):
    return _rot(rng.normal(size=3), rng.uniform(0.5, 10.0))


def _arcs_can_level(gonio, q):
    """Whether a TAS stage (turntable about y, lower arc ``sgl`` about x, upper
    arc ``sgu`` about z, symmetric travel) can bring mount-frame ``q`` into the
    horizontal plane, decided in closed form rather than by a search.

    Level means ``(R_x(sgl) R_z(sgu) q)_y = 0``, i.e. ``tan(sgl) = A(sgu) / q_z``
    with ``A(u) = q_x sin u + q_y cos u = r sin(u + phi)``. So the smallest
    lower-arc angle over the upper arc's travel is ``atan(min |A| / |q_z|)``,
    and ``|r sin|`` over an interval is zero if the interval holds a multiple
    of 180 deg, else smallest at an end (it is concave between its zeros)."""
    _turntable, sgl, sgu = gonio
    assert np.allclose(sgl.axis, (1, 0, 0)) and np.allclose(sgu.axis, (0, 0, 1))
    assert sgl.lower == -sgl.upper and sgu.lower == -sgu.upper
    if sgl.upper >= 90.0:
        return True
    r, phi = math.hypot(q[0], q[1]), math.atan2(q[1], q[0])
    half = math.radians(min(sgu.upper, 180.0))
    lo, hi = phi - half, phi + half
    if math.floor(hi / math.pi) >= math.ceil(lo / math.pi):
        a_min = 0.0
    else:
        a_min = min(abs(r * math.sin(lo)), abs(r * math.sin(hi)))
    return a_min <= abs(q[2]) * math.tan(math.radians(sgl.upper))


@pytest.mark.parametrize("lattice", list(LATTICES))
@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_stage_round_trip_puts_hkl_on_q_lab_and_fits_back(models, name, sense, lattice):
    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    sign = -1.0 if sense > 0 else 1.0          # D2: +1 puts -U B hkl on Q_lab
    B = reciprocal_basis_tas(*LATTICES[lattice])
    rng = np.random.default_rng(SEEDS[name] + 7 * sense + len(lattice))
    arcs_used = []
    for _mount in range(2):
        U = _random_mount(rng)
        model.U_true = U                   # the arm reads the true mount
        peaks = []
        for index in rng.permutation(len(HKL_POOL)):
            hkl = np.array(HKL_POOL[index], dtype=float)
            if not 0.5 < np.linalg.norm(B @ hkl) < 4.8:
                continue
            qx, qy, qz = component_q_to_instrument_q(U @ B @ hkl)
            angles, flags = model.calculate_stage_angles(
                qx, qy, qz, 0.0, E_RT, "Kf Fixed", "pg002", "pg002")
            # A refusal only where the arcs provably cannot level Q (never on
            # IN8, whose travel is unlimited), and then only the stage's.
            reachable = _arcs_can_level(model.goniometer, U @ B @ hkl)
            assert bool(flags) == (not reachable), (hkl, flags)
            if flags:
                assert all(f.startswith("stage: ") for f in flags), flags
                continue
            mtt, stt, sth, sgl, att, sgu = angles
            readouts = _stage_readouts(angles)
            q_lab = lab_q_from_stt(K_RT, K_RT, stt)

            # The McStas rule, composed arm by arm in this test.
            v_lab = _mcstas_lab_vector(_stage_chain(model.goniometer, readouts, U), B @ hkl)
            assert np.linalg.norm(v_lab - sign * q_lab) < 1e-9 * np.linalg.norm(q_lab)

            # The emitted single arm: build_point_params -> sample_r*_param.
            model.sample_rotation_deg, model.sgl, model.sgu = sth, sgl, sgu
            params = model.build_point_params(0.0)
            arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                         params["sample_rz_param"])
            v_emit = _mcstas_lab_vector([arm], B @ hkl)
            assert np.linalg.norm(v_emit - sign * q_lab) < 1e-9 * np.linalg.norm(q_lab)

            # A4: the readback through the full stage lands on the target HKL.
            q_and_e, flags = model.calculate_q_and_deltaE(
                mtt, stt, sth, sgl, att, E_RT, "Kf Fixed", "pg002", "pg002", sgu=sgu)
            assert flags == []
            hkl_back = SampleMount(B, U).q_to_hkl(
                *instrument_q_to_component_q(np.array(q_and_e[:3])))
            assert np.allclose(hkl_back, hkl, rtol=0.0, atol=1e-9)

            peaks.append(ObservedPeak(
                hkl=tuple(hkl), angles=(sth, sgl, stt), ki=K_RT, kf=K_RT,
                stage=stage_record(model.goniometer, readouts)))
            arcs_used.append((abs(sgl), abs(sgu)))
            if len(peaks) == 5:
                break
        assert len(peaks) >= 3, "too few reachable reflections to test"
        ub = UBMatrix(*LATTICES[lattice])
        ub.peaks = peaks
        ub.calculate_U_from_peaks()
        assert np.allclose(ub.U, U, rtol=0.0, atol=1e-9)
    # The accepted points drove both arcs, so the arc chain was exercised.
    assert min(np.max(arcs_used, axis=0)) > 0.5, arcs_used


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_calculate_ub_moves_the_readouts_never_the_crystal(models, name, sense):
    """Truth apart from belief: a UB fitted from peaks of a different
    orientation changes the readouts commanded for an HKL (the rlu path reads
    the operator's mount) while the emitted sample arm for the same physical
    angles stays bit-identical (it reads U_true only)."""
    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    model.U_true = _rot((1, 2, 0), 4.0) @ U_IN_PLANE
    ub = UBMatrix(*LATTICE)                      # the operator's UB: the standard setting

    def arm_and_readouts():
        model.sample_mount = SampleMount(ub.B, ub.U)      # as each plugin's scan_config sets it
        qx, qy, qz = component_q_to_instrument_q(model.sample_mount.hkl_to_q(1, 1, 0))
        angles, flags = model.calculate_stage_angles(
            qx, qy, qz, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
        assert flags == []
        model.sample_rotation_deg, model.sgl, model.sgu = 30.0, 1.5, -2.0     # the same physical angles
        params = model.build_point_params(0.0)
        arm = tuple(params[f"sample_r{axis}_param"] for axis in "xyz")
        return arm, _stage_readouts(angles)

    arm_before, readouts_before = arm_and_readouts()
    u_other = _rot((1, 0, 0), 2.0) @ _rot((0, 1, 0), 17.0)
    ub.peaks = [_peak(model, ub.B, hkl, u_other) for hkl in PEAKS_2]
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, u_other, rtol=0.0, atol=1e-9)
    arm_after, readouts_after = arm_and_readouts()

    assert arm_after == arm_before
    assert abs(readouts_after["A3"] - readouts_before["A3"]) > 5.0


# --- in plane: today's numbers and today's McStas rotation -------------------------

@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_in_plane_matches_legacy_solve_and_old_four_arm_chain(models, name):
    model = copy.deepcopy(models[name])
    model.sample_mount = SampleMount.from_lattice_tas(*LATTICE)       # U = I
    for sense in (model.sense_sample, -model.sense_sample):
        model.sense_sample = sense
        for q in ([2.5, 0.0, 0.0], [1.1, -1.9, 0.0], [-0.7, 2.2, 0.0], [-2.0, -1.0, 0.0]):
            angles, flags = model.calculate_stage_angles(
                *q, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
            assert flags == []
            mtt, stt, sth, sgl, att, sgu = angles
            k = energy2k(E_K)         # the model's own ki = kf, not K itself
            legacy = solve_instrument_angles(np.array(q), k, k, sense_sample=sense)
            assert (sgl, sgu) == (0.0, 0.0)
            assert (sth, stt) == (legacy.sth, legacy.stt)

            model.sample_rotation_deg, model.sgl, model.sgu = sth, sgl, sgu
            params = model.build_point_params(0.0)
            new = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                         params["sample_rz_param"])
            # base 971a91e9: sample_gonio [saz] -> sample_chi_arm [chi_total]
            # -> sample_cradle [0, A3 + omega_offset_total, 0] -> sample_mount
            # [mount Euler], every tilt, offset and mount angle zero.
            old = np.eye(3)
            for rotated in ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, sth, 0.0), (0.0, 0.0, 0.0)):
                old = mccode_rotation_matrix(*rotated) @ old
            assert np.allclose(new, old, rtol=0.0, atol=1e-12)


# --- the stage as data: an Eulerian cradle ---------------------------------------

EULER = (StageAxis("omega", (0.0, 1.0, 0.0)), StageAxis("chi", (0.0, 0.0, 1.0)),
         StageAxis("phi", (0.0, 1.0, 0.0)))


@pytest.mark.parametrize("sense", [-1, 1])
def test_eulerian_cradle_description_round_trips(sense):
    """The TAS round trip on a cradle description: a non-identity U, both
    senses, the independent McStas composition and the emitted single arm
    (``sample_arm_euler``), the readback, and the fit back to U. Two of the
    reflections are made vertical in the mount frame (U B hkl along +/-y), so
    they need chi = +/-90 deg and reach the Euler emission there."""
    sign = -1.0 if sense > 0 else 1.0          # D2: +1 puts -U B hkl on Q_lab
    U = _rot((1, 2, 3), 17.0)
    B = CUBIC_B
    vertical = [np.linalg.solve(B, U.T @ np.array([0.0, s, 0.0])) for s in (3.0, -2.2)]
    hkls = [np.array(h, dtype=float) for h in ((1, 0, 0), (0, 1, 1), (1, -1, 2))] + vertical
    peaks = []
    for index, hkl in enumerate(hkls):
        q_mount = U @ B @ hkl
        stt = stt_from_q_norm(float(np.linalg.norm(q_mount)), K_RT, K_RT, sense)
        q_lab = lab_q_from_stt(K_RT, K_RT, stt)
        angles = solve_stage(EULER, sign * q_mount, q_lab)
        if index >= 3:
            assert abs(angles["chi"]) == pytest.approx(90.0, abs=1e-9)

        v_lab = _mcstas_lab_vector(_stage_chain(EULER, angles, U), B @ hkl)
        assert np.linalg.norm(v_lab - sign * q_lab) < 1e-9 * np.linalg.norm(q_lab)
        arm = mccode_rotation_matrix(*sample_arm_euler(EULER, angles, U))
        v_emit = _mcstas_lab_vector([arm], B @ hkl)
        assert np.linalg.norm(v_emit - sign * q_lab) < 1e-9 * np.linalg.norm(q_lab)
        assert np.allclose(q_mount_from_stage(EULER, angles, stt, K_RT, K_RT, sense),
                           q_mount, rtol=0.0, atol=1e-9)

        peaks.append(ObservedPeak(hkl=tuple(hkl), angles=(0.0, 0.0, stt), ki=K_RT, kf=K_RT,
                                  stage=stage_record(EULER, angles, sense=sense)))
    ub = UBMatrix(*LATTICE)
    ub.peaks = peaks
    ub.calculate_U_from_peaks()
    assert np.allclose(ub.U, U, rtol=0.0, atol=1e-9)


# --- McStas Euler emission at the gimbal ------------------------------------------

@pytest.mark.parametrize("u", [np.eye(3), _rot((1, 2, 3), 7.0)], ids=["U=I", "U"])
@pytest.mark.parametrize("sgu", [12.5, -33.0])
@pytest.mark.parametrize("a3", [90.0, -90.0])
def test_sample_arm_euler_rebuilds_stage_rotation_at_the_gimbal(a3, sgu, u):
    from instruments.in8.plugin import in8_descriptor

    gonio = in8_descriptor().goniometer
    target = (_rot((0, 1, 0), a3) @ _rot((0, 0, 1), sgu) @ u).T
    rebuilt = mccode_rotation_matrix(*sample_arm_euler(
        gonio, {"A3": a3, "sgl": 0.0, "sgu": sgu}, u))
    assert np.allclose(rebuilt, target, rtol=0.0, atol=1e-12)


# --- travel (lens 3) ---------------------------------------------------------------

IN12_K = 2.0
IN12_E = k2energy(IN12_K)
CUBIC_B = reciprocal_basis_tas(*LATTICE)


def _in12_stage(models, u, hkl):
    model = copy.deepcopy(models["in12"])
    qx, qy, qz = component_q_to_instrument_q(u @ CUBIC_B @ np.array(hkl, dtype=float))
    return model.calculate_stage_angles(qx, qy, qz, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")


def test_two_degree_misorientation_of_200_solves_with_small_arcs(models):
    angles, flags = _in12_stage(models, _rot((0.3, 0.0, 1.0), 2.0), (2, 0, 0))
    assert flags == []
    assert abs(angles[3]) < 3.0 and abs(angles[5]) < 3.0
    assert max(abs(angles[3]), abs(angles[5])) > 0.1          # it did need a tilt


def test_020_parallel_to_the_upper_arc_is_found(models):
    """(0,K,0) lies along the upper arc, which cannot move it (A2)."""
    angles, flags = _in12_stage(models, _rot((1, 0, 0), 2.0), (0, 2, 0))
    assert flags == []
    assert abs(angles[3]) == pytest.approx(2.0, abs=1e-6)     # sgl
    assert angles[5] == pytest.approx(0.0, abs=1e-6)          # sgu


@pytest.mark.parametrize(("axis", "hkl", "slot"), [
    ((0, 0, 1), (2, 0, 0), 5),      # Q along x: the upper arc levels it
    ((1, 0, 0), (0, 2, 0), 3),      # Q along z: the lower arc levels it
])
def test_near_limit_settings_solve(models, axis, hkl, slot):
    angles, flags = _in12_stage(models, _rot(axis, 19.5), hkl)
    assert flags == []
    assert abs(angles[slot]) == pytest.approx(19.5, abs=1e-6)


def test_off_grid_travel_finds_a_point_reachable_only_in_its_corner():
    """Travel of +/-17.3 deg is not on the 0.5 deg grid. Q is built so that the
    levelling curve crosses the travel box only in its corner, between the
    grid values 17.0 and 17.5 of both arcs: tan(sgl) = A(sgu) / q_z passes
    (17.25, 17.25) with slope -1. Only the travel ends as nodes find it."""
    travel = 17.3
    gonio = (StageAxis("A3", (0.0, 1.0, 0.0)),
             StageAxis("sgl", (1.0, 0.0, 0.0), -travel, travel),
             StageAxis("sgu", (0.0, 0.0, 1.0), -travel, travel))
    s0 = math.radians(17.25)
    theta = math.atan2(math.tan(s0), -1.0 / math.cos(s0) ** 2)    # u0 + phi
    r = math.hypot(math.tan(s0), 1.0 / math.cos(s0) ** 2)
    phi = theta - s0
    q = np.array([r * math.cos(phi), r * math.sin(phi), 1.0])
    assert _arcs_can_level(gonio, q)
    q_lab = np.linalg.norm(q) * np.array([1.0, 0.0, 0.0])

    angles = solve_stage(gonio, q, q_lab)
    assert all(abs(angles[name]) <= travel for name in ("sgl", "sgu"))
    assert min(abs(angles["sgl"]), abs(angles["sgu"])) > 17.0       # the corner
    assert np.allclose(stage_rotation(gonio, angles) @ q, q_lab, rtol=0.0, atol=1e-9)


@pytest.mark.parametrize("azimuth", [77.0, 182.0, 224.0])
def test_a_point_exactly_at_the_travel_corner_solves(azimuth):
    """Q levelled by exactly (sgl, sgu) = (-17.3, 17.3), the corner of +/-17.3
    deg travel (and nowhere else inside it, for these azimuths): the root solved
    at one arc's end node lands ~1e-14 deg past the other's limit, which
    TRAVEL_TOLERANCE_DEG absorbs."""
    travel = 17.3
    gonio = (StageAxis("A3", (0.0, 1.0, 0.0)),
             StageAxis("sgl", (1.0, 0.0, 0.0), -travel, travel),
             StageAxis("sgu", (0.0, 0.0, 1.0), -travel, travel))
    a = math.radians(azimuth)
    q_lab = 2.0 * np.array([math.cos(a), 0.0, math.sin(a)])
    q = (_rot((1, 0, 0), -travel) @ _rot((0, 0, 1), travel)).T @ q_lab

    angles = solve_stage(gonio, q, q_lab)
    assert (angles["sgl"], angles["sgu"]) == pytest.approx((-travel, travel), abs=1e-9)
    from tavi.orientation import TRAVEL_TOLERANCE_DEG
    assert all(abs(angles[name]) <= travel + TRAVEL_TOLERANCE_DEG for name in ("sgl", "sgu"))
    assert np.allclose(stage_rotation(gonio, angles) @ q, q_lab, rtol=0.0, atol=1e-9)


def _in12_vals(**overrides):
    vals = {
        "K_fixed": "Kf Fixed", "source_type": "Maxwellian", "source_dE": 2.0,
        "rhm": 3.84, "rvm": 0.84, "rha": 1.98, "rva": 1.40,
        "fixed_E": IN12_E, "monocris": "pg002", "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "30", "alpha_4": "0"},
        "slits_mm": {"sbl": (30.0, 60.0), "dbl_hgap": 50.0},
        "deltaE": 0.0,
    }
    vals.update(overrides)
    return vals


def _plugin_config(vals, name="in12"):
    pytest.importorskip("mcstasscript")
    cls = {"in8": "IN8Plugin", "in12": "IN12Plugin", "panda": "PANDAPlugin"}[name]
    plugin = getattr(importlib.import_module(f"instruments.{name}.plugin"), cls)()
    state = plugin.default_state()
    return plugin, plugin.scan_config(state, vals, None, {}, state.sample_mount)


@pytest.mark.parametrize(("name", "travel", "slits_mm"), [
    ("in12", 20, {"sbl": (30.0, 60.0), "dbl_hgap": 50.0}),
    ("panda", 15, {"ms1": 40.0, "ss1": (40.0, 80.0), "ss2": (40.0, 80.0)}),
], ids=["in12", "panda"])
def test_unreachable_elevation_is_refused_identically_everywhere(tmp_path, name, travel,
                                                                 slits_mm):
    """45 deg of elevation cannot be levelled on IN12's +/-20 deg or PANDA's
    +/-15 deg arcs: the arcs' rotation angle is at most |sgl| + |sgu|, and no
    rotation moves a vector's elevation by more than its own angle; the
    closed form ``_arcs_can_level`` agrees. Established analytically, not by
    a grid sharing the solver's search."""
    from instruments.tas_runtime import describe_scan_error_flags

    vals = _in12_vals(slits_mm=slits_mm)
    plugin, config = _plugin_config(vals, name)
    q = 2.5 * np.array([math.cos(math.radians(45)), 0.0, math.sin(math.radians(45))])
    scan_point = q_point(*q)
    assert 45 > 2 * travel
    assert not _arcs_can_level(config.goniometer, instrument_q_to_component_q(q))

    _angles, flags = copy.deepcopy(config).calculate_stage_angles(
        *q, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert len(flags) == 1 and flags[0].startswith("stage: ")
    reason = describe_scan_error_flags(flags)
    assert reason.split()[0] in ("sgl", "sgu")
    assert f"travel is [-{travel}, {travel}]°" in reason

    plan = plan_for(plugin, config, vals, Q_CALC)
    check = plugin.check_point_feasibility(config, plan, scan_point)
    snapshot = plugin.compute_snapshot(plan, scan_point, 0, config, vals, str(tmp_path))
    assert (check.feasible, check.reason) == (False, reason)
    assert snapshot.params is None
    assert describe_scan_error_flags(snapshot.error_flags) == reason


def test_direct_motors_read_the_arcs_from_the_point_and_check_travel(tmp_path):
    from instruments import tas_runtime
    from instruments.tas_runtime import SGU

    plugin, config = _plugin_config(_in12_vals())
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        2.0, 0.0, 0.0, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert flags == []

    def point(sgl, sgu):
        return motors_point(angles[0], angles[1], angles[2], angles[4], sgl, sgu)

    geom = tas_runtime._solve_point_geometry(
        copy.deepcopy(config), MOTORS, point(3.0, -2.0), _in12_vals())
    assert geom["error_flags"] == []
    assert (geom["sgl"], geom["sgu"]) == (3.0, -2.0)

    # The per-point record carries the arcs, not the retired chi.
    plan = plan_for(plugin, config, _in12_vals(), MOTORS)
    snapshot = plugin.compute_snapshot(plan, point(3.0, -2.0), 0, config,
                                       _in12_vals(), str(tmp_path))
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (3.0, -2.0)
    assert "chi" not in snapshot.metadata
    assert (snapshot.params["sgl_param"], snapshot.params["sgu_param"]) == (3.0, -2.0)

    # An instrument without an upper arc has no sgu in its points: it runs at 0.
    no_upper = {qid: v for qid, v in point(3.0, -2.0).items() if qid != SGU}
    geom = tas_runtime._solve_point_geometry(
        copy.deepcopy(config), MOTORS, no_upper, _in12_vals())
    assert (geom["sgl"], geom["sgu"]) == (3.0, 0.0)

    feasible, reason = tas_runtime.check_point_feasibility(
        config, MOTORS, point(25.0, 0.0), _in12_vals())
    assert not feasible
    # The solver's own refusal words (one formatter for every travel refusal).
    assert reason == "sgl needs 25° but its travel is [-20, 20]°"


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan], ids=["inf", "-inf", "nan"])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_non_finite_arc_is_refused_on_every_instrument(models, name, bad):
    """Unlimited travel (IN8) contains inf, and nan fails every
    comparison: finiteness is refused first, in plain words."""
    model = models[name]
    reason = f"sgu must be a finite angle, not {bad}"
    assert model.arc_travel_flags({"sgl": 0.0, "sgu": bad}) == ["stage: " + reason]
    with pytest.raises(StageUnreachable, match=f"^{reason}$"):
        check_travel(model.goniometer, {"sgu": bad})


def test_an_old_chi_folder_is_refused_not_read_as_sgl(tmp_path):
    """A folder from before the arcs has no api_version: it is refused whole, so its
    chi is never read under another name."""
    from tavi.data_processing import (OutputVersionError, read_parameters_from_file,
                                      require_output_version)

    (tmp_path / "scan_parameters.txt").write_text(
        "scan_command1: chi 0 2 1\nchi: 2.5\n", encoding="utf-8")
    params = read_parameters_from_file(str(tmp_path))
    assert "sgl" not in params
    with pytest.raises(OutputVersionError, match="older TAVI"):
        require_output_version(params, str(tmp_path))


# --- locked mode --------------------------------------------------------------------

def test_locked_mode_never_moves_a_tilt_and_refuses_out_of_plane():
    from instruments.in12.plugin import in12_descriptor

    gonio = in12_descriptor().goniometer
    u = _rot((1, 0, 0), 3.0) @ _rot((0, 0, 1), -2.0)
    ub = u @ CUBIC_B
    lock = lock_plane(gonio, ub, (1, 0, 0), (0, 1, 0))
    inner = stage_rotation(gonio[1:], lock)
    for hkl in ((1, 0, 0), (0, 1, 0)):
        q = ub @ np.array(hkl, dtype=float)
        assert abs((inner @ q)[1]) < 1e-12 * np.linalg.norm(q)
    assert max(abs(v) for v in lock.values()) < 4.0

    for hkl in ((2, 0, 0), (1, 1, 0), (-1, 2, 0), (0, -2, 0)):
        q = ub @ np.array(hkl, dtype=float)
        stt = stt_from_q_norm(float(np.linalg.norm(q)), IN12_K, IN12_K, -1)
        q_lab = lab_q_from_stt(IN12_K, IN12_K, stt)
        angles = solve_stage(gonio, q, q_lab, locked=lock)
        assert {name: angles[name] for name in lock} == lock
        assert np.allclose(stage_rotation(gonio, angles) @ q, q_lab, rtol=0.0, atol=1e-9)

    q = ub @ np.array([1.0, 0.0, 1.0])
    stt = stt_from_q_norm(float(np.linalg.norm(q)), IN12_K, IN12_K, -1)
    out = math.degrees(math.asin((inner @ q)[1] / np.linalg.norm(q)))
    with pytest.raises(StageUnreachable, match="out of the locked scattering plane") as err:
        solve_stage(gonio, q, lab_q_from_stt(IN12_K, IN12_K, stt), locked=lock)
    assert f"{out:+.4g}°" in str(err.value)


@pytest.mark.parametrize(("lock", "reason"), [
    ({"sgl": 25.0, "sgu": 0.0},
     "sgl needs 25° for the locked scattering plane but its travel is [-20, 20]°"),
    ({"sgl": 1.0}, "the lock does not set sgu"),
    ({"sgl": 1.0, "sgu": 0.0, "chi": 2.0}, "the lock names chi, which this stage lacks"),
], ids=["past-travel", "missing-axis", "unknown-axis"])
def test_locked_mode_refuses_a_lock_this_stage_cannot_hold(lock, reason):
    """A lock carried from a saved session or another instrument: tilts past
    this stage's travel, or axis names it does not have, are refused, never
    read as reachable or as 0 deg."""
    from instruments.in12.plugin import in12_descriptor

    gonio = in12_descriptor().goniometer
    q = np.array([2.0, 0.0, 0.0])
    with pytest.raises(StageUnreachable) as err:
        solve_stage(gonio, q, np.array([0.0, 0.0, 2.0]), locked=lock)
    assert str(err.value) == reason


def test_lock_plane_past_travel_is_refused_in_the_shared_words():
    """A plane 30 deg off horizontal on IN12's +/-20 deg arcs: the refusal
    is the one travel wording (``_travel_refusal``)."""
    from instruments.in12.plugin import in12_descriptor

    gonio = in12_descriptor().goniometer
    with pytest.raises(StageUnreachable) as err:
        lock_plane(gonio, _rot((1, 0, 0), 30.0) @ CUBIC_B, (1, 0, 0), (0, 1, 0))
    assert str(err.value) == (
        "sgl needs -30° to bring the plane horizontal but its travel is [-20, 20]°")


# --- Unit 2 (C6): a locked plane in the runtime ---------------------------------------

PLANE_001 = ((1, 0, 0), (0, 1, 0))


def _locked_in12(u):
    """An IN12 scan config whose operator UB has U = ``u`` and whose
    ``plane_lock`` holds (1 0 0)/(0 1 0) where that UB levels it."""
    plugin, config = _plugin_config(_in12_vals())
    config.sample_mount = SampleMount.from_lattice_tas(*LATTICE, R_mount=u)
    tilts = lock_plane(config.goniometer, config.sample_mount.mounted_basis, *PLANE_001)
    config.plane_lock = {"hkl_u": list(PLANE_001[0]), "hkl_v": list(PLANE_001[1]),
                         "tilts": tilts}
    return plugin, config


def _rlu_point(hkl):
    return hkl_point(*hkl)


def test_a_lock_refuses_an_out_of_plane_point_naming_the_plane_and_the_angle(tmp_path):
    """Feasibility (the path the GUI count, the masks, the API preflight and
    the run share) refuses (1 0 1) under a (1 0 0)/(0 1 0) lock with the
    plane and the angle Q leaves it by; an in-plane point runs at the lock."""
    from instruments.tas_runtime import check_point_feasibility
    from tavi.orientation import locked_plane_text

    plugin, config = _locked_in12(_rot((1, 0, 0), 3.0) @ _rot((0, 0, 1), -2.0))
    tilts = config.plane_lock["tilts"]
    assert max(abs(v) for v in tilts.values()) > 1.0

    q = config.sample_mount.mounted_basis @ np.array([1.0, 0.0, 1.0])
    signed = -q if config.sense_sample > 0 else q
    up = np.asarray(config.goniometer[0].axis, dtype=float)
    out = math.degrees(math.asin(up @ stage_rotation(config.goniometer[1:], tilts) @ signed
                                 / np.linalg.norm(q)))
    feasible, reason = check_point_feasibility(config, HKL_CALC, _rlu_point((1, 0, 1)),
                                               _in12_vals())
    assert not feasible
    assert reason == f"Q is {out:+.4g}° out of " + locked_plane_text(tilts, PLANE_001)

    snapshot = plugin.compute_snapshot(plan_for(plugin, config, _in12_vals(), HKL_CALC),
                                       _rlu_point((2, 1, 0)), 0, config,
                                       _in12_vals(), str(tmp_path))
    assert snapshot.error_flags == []
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (tilts["sgl"], tilts["sgu"])


@pytest.mark.parametrize("hkl", [(1, 0.5, 0), (2, -1.3, 0), (0.1, 0.05, 0)])
def test_a_lock_accepts_an_in_plane_q_rounded_like_the_gui_fields(hkl):
    """The GUI solves from Q fields rounded to four decimals (1/A): under a
    tilted lock that rounding leaves an in-plane Q a hair out of the plane,
    which must still solve, at the lock's exact tilts."""
    from tavi.tas_geometry import component_q_to_instrument_q

    _plugin, config = _locked_in12(_rot((1, 0, 0), 3.0) @ _rot((0, 0, 1), -2.0))
    tilts = config.plane_lock["tilts"]
    q = component_q_to_instrument_q(np.array(config.sample_mount.hkl_to_q(*hkl), dtype=float))
    qx, qy, qz = (round(float(c), 4) for c in q)
    angles, flags = config.calculate_stage_angles(
        qx, qy, qz, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002", locked=config.plane_lock)
    assert flags == []
    assert (angles[3], angles[5]) == (tilts["sgl"], tilts["sgu"])


def test_an_in_plane_scan_in_locked_mode_matches_free_mode(tmp_path):
    """With the UB level, free mode needs no tilt for an in-plane point, and
    locked mode, holding the same zero tilts, gives the same A1-A4."""
    plugin, config = _locked_in12(np.eye(3))
    assert config.plane_lock["tilts"] == pytest.approx({"sgl": 0.0, "sgu": 0.0}, abs=1e-12)
    free = copy.deepcopy(config)
    free.plane_lock = None
    for hkl in ((2, 0, 0), (1, 1, 0), (1, 2, 0)):
        locked_md, free_md = (
            plugin.compute_snapshot(plan_for(plugin, state, _in12_vals(), HKL_CALC),
                                    _rlu_point(hkl), 0, state, _in12_vals(),
                                    str(tmp_path)).metadata for state in (config, free))
        for key in ("mtt", "stt", "sth", "att", "sgl", "sgu"):
            assert locked_md[key] == pytest.approx(free_md[key], abs=1e-9), (hkl, key)


def test_a_direct_motor_point_under_a_lock_runs_at_the_lock_tilts(tmp_path):
    """Amendment 2 (kept, provisional): under a lock a direct-motor point takes
    the arcs from the lock. Typed arcs that disagree are followed by the lock,
    not refused: the plan reads no arc as an input, gives both the "plane lock"
    provenance, and the point runs and is emitted at the lock's exact tilts."""
    from instruments.rules import SET_PER_POINT, build_plan, expand
    from instruments.tas_runtime import SGL, SGU
    from tavi.quantities import public_values

    plugin, config = _locked_in12(_rot((1, 0, 0), 3.0) @ _rot((0, 0, 1), -2.0))
    tilts = config.plane_lock["tilts"]
    assert max(abs(v) for v in tilts.values()) > 1.0
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        2.0, 0.0, 0.0, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert flags == []

    vals = _in12_vals(mtt=angles[0], stt=angles[1], omega=angles[2], att=angles[4],
                      sgl=tilts["sgl"] + 0.5, sgu=tilts["sgu"] - 0.7, H=0.0, K=0.0, L=0.0,
                      qx=2.0, qy=0.0, qz=0.0)
    plan = build_plan([("A3 %r %r 1" % (angles[2], angles[2]), False), ("", False)],
                      context(plugin, config, vals))
    for arc in (SGL, SGU):
        assert (plan.provenance[arc].role, plan.provenance[arc].policies) == (
            SET_PER_POINT, ("plane lock",)), arc
        assert arc not in plan.inputs
    point = expand(plan, public_values(vals, plugin.descriptor().slits)).points[0]
    assert SGL not in point and SGU not in point

    check = plugin.check_point_feasibility(config, plan, point)
    assert check.feasible, check.reason
    snapshot = plugin.compute_snapshot(plan, point, 0, config, vals, str(tmp_path))
    assert snapshot.error_flags == []
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (tilts["sgl"], tilts["sgu"])
    assert (snapshot.params["sgl_param"], snapshot.params["sgu_param"]) == (
        tilts["sgl"], tilts["sgu"])

    # A point handed over with disagreeing arcs anyway still runs at the lock.
    typed = motors_point(angles[0], angles[1], angles[2], angles[4],
                         tilts["sgl"] + 0.5, tilts["sgu"] - 0.7)
    snapshot = plugin.compute_snapshot(plan, typed, 0, config, vals, str(tmp_path))
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (tilts["sgl"], tilts["sgu"])


# --- the stage readouts reach McStas as axis rotations -------------------------------

@pytest.mark.parametrize("axis_name", ["A3", "sgl", "sgu"])
def test_a_readout_changes_the_emitted_rotation_by_that_axis_rotation(models, axis_name):
    model = copy.deepcopy(models["in8"])
    u = _rot((2, -1, 1), 6.0)
    model.U_true = u                       # the arm reads the true mount
    model.sample_rotation_deg, model.sgl, model.sgu = 37.0, 4.0, -6.0
    assert model.stage_readouts() == {"A3": 37.0, "sgl": 4.0, "sgu": -6.0}
    before = mccode_rotation_matrix(*sample_arm_euler(
        model.goniometer, model.stage_readouts(), u)).T
    attr = "sample_rotation_deg" if axis_name == "A3" else axis_name
    setattr(model, attr, getattr(model, attr) + 1.75)
    params = model.build_point_params(0.0)
    emitted = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                     params["sample_rz_param"]).T
    shifted = {"A3": 37.0, "sgl": 4.0, "sgu": -6.0}
    shifted[axis_name] += 1.75
    expected = (_rot((0, 1, 0), shifted["A3"]) @ _rot((1, 0, 0), shifted["sgl"])
                @ _rot((0, 0, 1), shifted["sgu"]) @ u)
    assert np.allclose(emitted, expected, rtol=0.0, atol=1e-12)
    assert not np.allclose(emitted, before, rtol=0.0, atol=1e-6)
    assert not [name for name in params if name.startswith(("kappa", "psi", "mis"))]


def test_the_stage_description_carries_no_correction_and_no_zero_offset(models):
    """The stage is data: axis, travel, nothing the runtime adds to a readout."""
    from instruments.descriptor import GonioAxis

    assert [f.name for f in dataclasses.fields(GonioAxis)] == ["name", "axis", "limits"]


@pytest.mark.parametrize(("angles", "named"), [
    ({"A3": 1.0, "sgl": 2.0}, "sgu"),
    ({"A3": 1.0, "sgl": 2.0, "sgu": 3.0, "chi": 4.0}, "chi"),
    ({"omega": 1.0, "chi": 2.0, "phi": 3.0}, "A3"),
], ids=["missing", "unknown", "other-stage"])
def test_stage_readers_refuse_angles_that_do_not_match_the_stage(angles, named):
    """A missing or unknown axis name is an error naming it, never 0 deg."""
    from instruments.descriptor import tas_goniometer

    gonio = tas_goniometer()
    for read in (lambda: stage_rotation(gonio, angles),
                 lambda: sample_arm_euler(gonio, angles, np.eye(3)),
                 lambda: stage_record(gonio, angles)):
        with pytest.raises(ValueError, match=named):
            read()
    if named == "chi":                                   # check_travel allows a subset
        with pytest.raises(ValueError, match=named):
            check_travel(gonio, {"chi": 1.0})


# --- the build fingerprint ignores orientation ----------------------------------

@pytest.mark.parametrize(("name", "cls"), [
    ("puma", "PUMAPlugin"), ("in8", "IN8Plugin"), ("in12", "IN12Plugin"),
    ("panda", "PANDAPlugin"),
])
def test_build_fingerprint_is_unchanged_by_orientation(name, cls):
    pytest.importorskip("mcstasscript")
    plugin = getattr(importlib.import_module(f"instruments.{name}.plugin"), cls)()
    config = plugin.default_state()
    before = plugin.build_fingerprint(config)
    for field, value in (("A3", 12.0), ("sgl", 3.0), ("sgu", -4.0)):
        setattr(config, field, value)
    config.sample_mount = SampleMount(CUBIC_B, _rot((1, 1, 0), 8.0))
    config.U_true = _rot((1, -1, 0), 5.0)
    assert plugin.build_fingerprint(config) == before


# --- Unit 2 (C2): the mounting plane -----------------------------------------------

def test_h0l_mount_puts_101_in_the_plane_with_the_arcs_at_zero(models):
    """Mounted with (1 0 0) along x and (0 0 1) in plane, (1 0 1) solves on
    IN8 with both arcs at 0, and (1 0 0) lies along the mount x axis."""
    from tavi.ub_matrix import u_from_plane

    model = copy.deepcopy(models["in8"])
    u = u_from_plane(CUBIC_B, (1, 0, 0), (0, 0, 1))
    assert np.allclose(u @ CUBIC_B @ np.array([1.0, 0.0, 0.0]),
                       [np.linalg.norm(CUBIC_B[:, 0]), 0.0, 0.0], rtol=0.0, atol=1e-12)
    for hkl in ((1, 0, 1), (2, 0, -1), (0, 0, 2)):
        q = u @ CUBIC_B @ np.array(hkl, dtype=float)
        angles, flags = model.calculate_stage_angles(
            *component_q_to_instrument_q(q), 0.0, E_K, "Kf Fixed", "pg002", "pg002")
        assert flags == []
        assert (angles[3], angles[5]) == pytest.approx((0.0, 0.0), abs=1e-9), hkl


def test_a_non_orthogonal_plane_mount_puts_both_vectors_horizontal():
    from tavi.ub_matrix import u_from_plane

    B = reciprocal_basis_tas(5.1, 6.3, 7.2, 80.0, 103.5, 110.0)
    hkl_u, hkl_v = np.array([1.0, 1.0, 0.0]), np.array([0.0, 1.0, 2.0])
    u = u_from_plane(B, hkl_u, hkl_v)
    assert np.allclose(u.T @ u, np.eye(3), rtol=0.0, atol=1e-12)
    assert np.linalg.det(u) == pytest.approx(1.0, abs=1e-12)
    q_u, q_v = u @ B @ hkl_u, u @ B @ hkl_v
    assert abs(q_u[1]) < 1e-12 and abs(q_u[2]) < 1e-12 and q_u[0] > 0     # along +x
    assert abs(q_v[1]) < 1e-12 and q_v[2] > 0                               # in plane, +z side


@pytest.mark.parametrize(("hkl_u", "hkl_v", "reason"), [
    ((1, 0, 0), (2, 0, 0), "(1 0 0) and (2 0 0) are parallel, so they span no plane"),
    ((0, 0, 0), (0, 0, 1), "the vector along x, (0 0 0), is zero"),
], ids=["parallel", "zero"])
def test_a_plane_that_spans_nothing_is_refused_with_the_reason(hkl_u, hkl_v, reason):
    from tavi.ub_matrix import u_from_plane

    with pytest.raises(ValueError) as err:
        u_from_plane(CUBIC_B, hkl_u, hkl_v)
    assert str(err.value) == reason


# --- Unit 2 (C4): the analytic engine reads the true mount --------------------------

Q_200 = component_q_to_instrument_q(CUBIC_B @ np.array([2.0, 0.0, 0.0]))


def _engine_point(config, calculation, coords, tmp_path, sgl=0.0, sgu=0.0):
    """One IN8 scan point through the shared snapshot, and the engine's HKL."""
    from instruments.tas_runtime import true_point_hkl

    point = {HKL_CALC: hkl_point, Q_CALC: q_point}.get(calculation)
    point = (motors_point(*coords, sgl, sgu) if calculation == MOTORS else point(*coords))
    plugin, _ = _plugin_config(_in12_vals(), "in8")
    plan = plan_for(plugin, config, _in12_vals(), calculation)
    snapshot = plugin.compute_snapshot(plan, point, 0, config, _in12_vals(), str(tmp_path))
    assert snapshot.error_flags == []
    return snapshot, np.array(true_point_hkl(config, snapshot.metadata, CUBIC_B))


def _in8_config(sense, u_true=np.eye(3), u_operator=np.eye(3)):
    _, config = _plugin_config(_in12_vals(), "in8")
    config.sense_sample = sense
    config.U_true = u_true
    config.sample_mount = SampleMount(CUBIC_B, u_operator)
    return config


def _angle_coords(snapshot):
    """The angle-mode point that drives the stage where ``snapshot`` stood."""
    md = snapshot.metadata
    return (md["mtt"], md["stt"], md["sth"], md["att"]), md["sgl"], md["sgu"]


@pytest.mark.parametrize("sense", [-1, 1])
def test_engine_hkl_through_a_wrong_ub_misses_the_reflection(tmp_path, sense):
    """An rlu point at (2 0 0) with the operator's UB on the truth evaluates
    on the reflection; with the UB 3 deg off about the vertical the crystal
    presents (2 0 0) turned by 3 deg."""
    _, on = _engine_point(_in8_config(sense), HKL_CALC, (2, 0, 0, 0), tmp_path)
    assert on == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)

    wrong = _in8_config(sense, u_operator=_rot((0, 1, 0), 3.0))
    _, off = _engine_point(wrong, HKL_CALC, (2, 0, 0, 0), tmp_path)
    assert np.linalg.norm(off) == pytest.approx(2.0, abs=1e-9)
    assert _miss_deg(off, np.array([2.0, 0.0, 0.0])) == pytest.approx(3.0, abs=1e-6)


@pytest.mark.parametrize("mode", [HKL_CALC, Q_CALC, MOTORS])
def test_a_hidden_mount_rotation_reaches_the_engine_in_every_mode(tmp_path, mode):
    """A hidden 3 deg turn of the crystal in its mount takes it off (2 0 0)
    in every calculation, by exactly that turn."""
    coords = (2, 0, 0, 0) if mode == HKL_CALC else (*Q_200, 0.0)
    sgl = sgu = 0.0
    if mode == MOTORS:
        reference, _ = _engine_point(_in8_config(-1), HKL_CALC, (2, 0, 0, 0), tmp_path)
        coords, sgl, sgu = _angle_coords(reference)
    hkls = {}
    for turn in (0.0, 3.0):
        config = _in8_config(-1, u_true=_rot((0, 1, 0), turn))
        _, hkls[turn] = _engine_point(config, mode, coords, tmp_path, sgl=sgl, sgu=sgu)
    assert hkls[0.0] == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)
    assert _miss_deg(hkls[3.0], np.array([2.0, 0.0, 0.0])) == pytest.approx(3.0, abs=1e-6)


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("mode", [HKL_CALC, Q_CALC, MOTORS])
def test_engine_hkl_is_the_emitted_arm_on_lab_q_and_ignores_the_ub(tmp_path, mode, sense):
    """At tilted arcs, B_true @ hkl is the emitted sample arm's rotation
    applied to the lab Q (signed per sense): the engine sees the crystal McStas
    builds. In the Q and direct-motor calculations the operator's UB does not move it."""
    u_true = _rot((1, 2, 0), 6.0) @ U_IN_PLANE
    coords = {HKL_CALC: (2, 1, 0.5, 0.0), Q_CALC: (2.4, 0.6, 0.5, 0.0)}.get(mode)
    sgl = sgu = 0.0
    if mode == MOTORS:
        reference, _ = _engine_point(_in8_config(sense, u_true, _rot((1, 0, 0), 5.0)),
                                     HKL_CALC, (2, 1, 0.5, 0.0), tmp_path)
        coords, _sgl, _sgu = _angle_coords(reference)
        sgl, sgu = 4.0, -6.0
    found = []
    for u_operator in (_rot((1, 0, 0), 5.0), _rot((0, 1, 1), 9.0)):
        config = _in8_config(sense, u_true, u_operator)
        snapshot, hkl = _engine_point(config, mode, coords, tmp_path, sgl=sgl, sgu=sgu)
        md, params = snapshot.metadata, snapshot.params
        assert abs(md["sgl"]) + abs(md["sgu"]) > 1.0                 # the arcs are tilted
        arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                     params["sample_rz_param"])
        lab_q = lab_q_from_stt(md["Ki"], md["Kf"], md["stt"])
        signed = -1.0 if sense > 0 else 1.0
        assert np.allclose(CUBIC_B @ hkl, signed * arm @ lab_q, rtol=0.0, atol=1e-9)
        found.append(hkl)
    if mode != HKL_CALC:
        assert np.array_equal(found[0], found[1])


# --- Unit 2 (C5): training graded on the truth --------------------------------------

STANDARD_REFLECTIONS = [(1, 0, 0), (0, 1, 0), (1, 1, 0)]
# The same physical geometry on both senses: PUMA is -1, IN8 +1.
SENSES = [("puma", -1), ("in8", 1)]


def _true_peak(gonio, sense, hkl, u_true, b_true, k=K):
    """A peak taken where the true crystal diffracts: the setting that puts the
    true reflection on the lab Q, recorded as the stage readouts."""
    q = u_true @ b_true @ np.array(hkl, dtype=float)
    stt = stt_from_q_norm(float(np.linalg.norm(q)), k, k, sense)
    readouts = solve_stage(gonio, -q if sense > 0 else q, lab_q_from_stt(k, k, stt))
    record = stage_record(gonio, readouts, ki=k, kf=k, sense=sense)
    return ObservedPeak(hkl=tuple(hkl), angles=(readouts["A3"], readouts["sgl"], stt),
                        ki=k, kf=k, stage=record)


def _fit_and_grade(gonio, sense, u_true, peak_hkls, turn_ub=np.eye(3)):
    """The operator fits a UB from peaks taken on the true crystal (lattice
    fields right), optionally turns it, and is graded on those peaks plus the
    standard-setting reflections."""
    from tavi.ub_matrix import grade_alignment

    ub = UBMatrix(*LATTICE)
    ub.peaks = [_true_peak(gonio, sense, hkl, u_true, CUBIC_B) for hkl in peak_hkls]
    ub.calculate_U_from_peaks()
    return grade_alignment(gonio, sense, K, K, turn_ub @ ub.UB, u_true, CUBIC_B,
                           list(peak_hkls) + STANDARD_REFLECTIONS)


@pytest.mark.parametrize(("name", "sense"), SENSES, ids=[n for n, _ in SENSES])
def test_a_fit_on_the_true_crystal_grades_aligned(models, name, sense):
    """A hidden 23 deg turn of the mount: a fit from peaks on the true crystal
    commands the true reflections (aligned). The grade compares settings, not
    U with U."""
    grade = _fit_and_grade(models[name].goniometer, sense, U_IN_PLANE, PEAKS_2)
    assert grade["status"] == "aligned", grade
    assert grade["worst_miss"] < 1e-6


@pytest.mark.parametrize(("name", "sense"), SENSES, ids=[n for n, _ in SENSES])
def test_a_ub_five_degrees_off_grades_way_off(models, name, sense):
    grade = _fit_and_grade(models[name].goniometer, sense, U_IN_PLANE, PEAKS_2,
                           turn_ub=_rot((0, 1, 0), 5.0))
    assert grade["status"] == "way_off", grade
    assert grade["worst_miss"] == pytest.approx(5.0, abs=1e-6)


def test_an_exact_u_on_lattice_fields_two_percent_off_grades_by_its_two_theta_miss(models):
    from tavi.ub_matrix import grade_alignment

    gonio = models["in8"].goniometer
    b_fields = reciprocal_basis_tas(*(1.02 * x for x in LATTICE[:3]), *LATTICE[3:])
    grade = grade_alignment(gonio, 1, K, K, U_IN_PLANE @ b_fields, U_IN_PLANE, CUBIC_B,
                            STANDARD_REFLECTIONS)

    def stt(b, hkl):
        return stt_from_q_norm(float(np.linalg.norm(b @ np.array(hkl, dtype=float))), K, K, 1)

    assert grade["worst_hkl"] == (1, 1, 0)
    assert grade["worst_miss"] == pytest.approx(
        abs(stt(CUBIC_B, (1, 1, 0)) - stt(b_fields, (1, 1, 0))), abs=1e-9)
    assert grade["status"] == "close" and 0.5 < grade["worst_miss"] <= 2.0, grade


def test_a_reflection_whose_true_q_closes_no_triangle_grades_way_off(models):
    """The lattice fields (a = 4.6) reach (2 2 0) at k = 2; the true crystal's
    (2 2 0), |Q| = 4.39, closes no triangle there (|Q| <= 2k = 4)."""
    from tavi.ub_matrix import grade_alignment

    b_fields = reciprocal_basis_tas(4.6, 4.6, 4.6, 90.0, 90.0, 90.0)
    grade = grade_alignment(models["in8"].goniometer, 1, K, K, b_fields, np.eye(3),
                            CUBIC_B, STANDARD_REFLECTIONS + [(2, 2, 0)])
    assert grade["status"] == "way_off" and grade["worst_hkl"] == (2, 2, 0), grade
    assert grade["worst_miss"] == math.inf
    assert "(2 2 0) closes no scattering triangle" in grade["summary"]


@pytest.mark.parametrize(("name", "sense"), SENSES, ids=[n for n, _ in SENSES])
def test_a_tilted_truth_is_recovered_exactly_from_tilted_peaks(models, name, sense):
    """A hidden turn about a tilted axis needs the arcs for every peak. The
    error is exactly a U, so a fit from correctly indexed, noiseless peaks
    recovers it and the grade is aligned to rounding -- no 'approximately'."""
    gonio = models[name].goniometer
    u_true = _rot((2, 0, -1), 8.0) @ U_IN_PLANE
    peaks = [(1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
    for hkl in peaks:                                # the peaks need the arcs
        q = u_true @ CUBIC_B @ np.array(hkl, dtype=float)
        assert abs(q[1]) / np.linalg.norm(q) > math.sin(math.radians(1.0))
    grade = _fit_and_grade(gonio, sense, u_true, peaks)
    assert grade["status"] == "aligned" and grade["worst_miss"] < 1e-6, grade


def test_too_few_reachable_reflections_or_no_sample_cannot_be_assessed(models):
    """At k = 1 (|Q| <= 2) a belief with a = 3, b = 5 reaches only (0 1 0) of
    the standard reflections: one direction grades nothing. No sample: no
    crystal to grade against."""
    from tavi.ub_matrix import grade_alignment

    gonio = models["in8"].goniometer
    b_fields = reciprocal_basis_tas(3.0, 5.0, 4.05, 90.0, 90.0, 90.0)
    grade = grade_alignment(gonio, 1, 1.0, 1.0, b_fields, np.eye(3), CUBIC_B,
                            STANDARD_REFLECTIONS)
    assert grade["status"] == "cannot_assess", grade
    assert "fewer than two" in grade["summary"]
    assert [s.split(":")[0] for s in grade["skipped"]] == ["(1 0 0)", "(1 1 0)"]

    grade = grade_alignment(gonio, 1, K, K, CUBIC_B, np.eye(3), None,
                            STANDARD_REFLECTIONS)
    assert grade["status"] == "cannot_assess" and "no sample" in grade["summary"]


# --- Unit 3 (C1): one (h k l) wording -----------------------------------------------

def test_hkl_text_is_the_one_parenthesised_wording():
    from tavi.orientation import hkl_text

    assert hkl_text((1, 0, -2.5)) == "(1 0 -2.5)"


# --- Unit 3 (C2): the plane normal as a zone axis -----------------------------------

def test_zone_axis_of_a_cubic_110_001_mount_and_a_hexagonal_standard_mount():
    from tavi.ub_matrix import get_scattering_plane_info, small_integer_indices, u_from_plane

    u = u_from_plane(CUBIC_B, (1, 1, 0), (0, 0, 1))
    assert get_scattering_plane_info(u, CUBIC_B)["zone_axis_uvw"] == (1, -1, 0)
    hexagonal = reciprocal_basis_tas(*LATTICES["hexagonal"])
    assert get_scattering_plane_info(np.eye(3), hexagonal)["zone_axis_uvw"] == (0, 0, 1)
    # Either sign, and the smallest of the parallel triples.
    assert small_integer_indices(CUBIC_B @ np.array([-2.0, 2.0, 0.0]), CUBIC_B) == (1, -1, 0)


def test_zone_axis_tolerance_is_an_angle_between_cartesian_vectors():
    """c = 5a, beta = 100 deg: the 0.1 deg tolerance is measured between the
    Cartesian vectors, not between index coefficients."""
    from tavi.ub_matrix import small_integer_indices

    direct = 2 * math.pi * np.linalg.inv(reciprocal_basis_tas(3.0, 4.0, 15.0, 90, 100, 90)).T
    target = direct @ np.array([1.0, 0.0, -1.0])
    turn_axis = np.cross(target, direct[:, 1])
    assert small_integer_indices(_rot(turn_axis, 0.08) @ target, direct) == (1, 0, -1)
    assert small_integer_indices(_rot(turn_axis, 0.12) @ target, direct) != (1, 0, -1)


def test_zone_axis_of_a_monoclinic_mount_is_read_in_the_direct_basis():
    """c = 5a, beta = 100 deg, (0 1 0) and (1 0 1) in the plane: the zone axis
    is their cross product [1 0 -1], a direction of the direct basis
    2 pi (UB)^-T; read against UB itself it would be a reciprocal vector."""
    from tavi.ub_matrix import get_scattering_plane_info, u_from_plane

    b = reciprocal_basis_tas(3.0, 4.0, 15.0, 90, 100, 90)
    zone = get_scattering_plane_info(u_from_plane(b, (0, 1, 0), (1, 0, 1)), b)["zone_axis_uvw"]
    assert zone in ((1, 0, -1), (-1, 0, 1)), zone


def test_an_irrational_plane_normal_has_no_zone_axis():
    from tavi.ub_matrix import get_scattering_plane_info

    u = mccode_rotation_matrix(7.3, 0.0, 11.9)
    info = get_scattering_plane_info(u, CUBIC_B)
    assert info["zone_axis_uvw"] is None
    assert np.allclose(u @ CUBIC_B @ np.array(info["plane_normal_hkl"]), (0, 1, 0))


# --- Unit 3 (C3): residuals and the peak-pair check ---------------------------------

RESIDUAL_HKLS = [(1, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 1)]


def _residual_set(models, lattice, sense, seed, hkls=RESIDUAL_HKLS, relabel=None,
                  fields=None):
    """Peaks ``hkls`` taken where a seeded true crystal (not U = I)
    diffracts; optionally some relabelled ({index: hkl}); a UB fitted from
    them on the lattice ``fields`` (default the true one) and its residuals."""
    from tavi.ub_matrix import alignment_residuals

    gonio = models["in8"].goniometer
    b_true = reciprocal_basis_tas(*LATTICES[lattice])
    u_true = _random_mount(np.random.default_rng(seed))
    peaks = [_true_peak(gonio, sense, hkl, u_true, b_true) for hkl in hkls]
    for index, hkl in (relabel or {}).items():
        peaks[index].hkl = hkl
    ub = UBMatrix(*(fields or LATTICES[lattice]))
    ub.peaks = peaks
    ub.calculate_U_from_peaks()
    return peaks, alignment_residuals(ub.UB, peaks)


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("lattice", ["cubic", "monoclinic"])
def test_a_clean_peak_set_has_no_flag_and_no_residual(models, lattice, sense):
    """At different arc settings: every per-peak angle and every pair
    difference is under 1e-6 deg (a sense applied twice would put a peak 180
    deg off)."""
    peaks, result = _residual_set(models, lattice, sense, seed=31)
    upper = [p.stage["angles"]["sgu"] for p in peaks]
    assert max(upper) - min(upper) > 0.5, upper
    assert result["flags"] == [] and "no flags" in result["summary"]
    assert len(result["peaks"]) == 4 and len(result["pairs"]) == 6
    assert max(r["angle_deg"] for r in result["peaks"]) < 1e-6
    assert max(abs(r["q_mismatch"]) for r in result["peaks"]) < 1e-9
    assert max(abs(p["difference_deg"]) for p in result["pairs"]) < 1e-6


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("lattice", ["cubic", "monoclinic"])
def test_a_non_parallel_mis_index_of_the_same_q_is_caught_by_the_pair_check(
        models, lattice, sense):
    """(1 1 0) labelled (1 -1 0): the same |Q|, so only a pair angle shows it."""
    _peaks, result = _residual_set(models, lattice, sense, seed=37, relabel={2: (1, -1, 0)})
    assert all(abs(r["q_mismatch"]) < 1e-9 for r in result["peaks"])
    flagged = [p for p in result["pairs"] if p["flag"]]
    assert flagged and all((1, -1, 0) in (p["hkl1"], p["hkl2"]) for p in flagged), result
    assert flagged[0]["flag"].endswith("one of them is likely mis-indexed")


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("lattice", ["cubic", "monoclinic"])
def test_a_200_labelled_100_reads_likely_mis_indexed(models, lattice, sense):
    """Parallel, so every pair angle is kept: its |Q| shows it."""
    _peaks, result = _residual_set(models, lattice, sense, seed=41,
                                   hkls=[(2, 0, 0)] + RESIDUAL_HKLS[1:], relabel={0: (1, 0, 0)})
    flagged = [r for r in result["peaks"] if r["flag"]]
    assert [r["hkl"] for r in flagged] == [(1, 0, 0)]
    assert flagged[0]["flag"] == "|Q| is +100.0 % from its indices: likely mis-indexed"
    assert "(1 0 0): |Q| is +100.0 %" in result["summary"]


@pytest.mark.parametrize("lattice", ["cubic", "monoclinic"])
def test_lattice_fields_three_percent_off_read_lattice_fields_off(models, lattice):
    fields = tuple(1.03 * x for x in LATTICES[lattice][:3]) + LATTICES[lattice][3:]
    _peaks, result = _residual_set(models, lattice, 1, seed=47, fields=fields)
    assert len(result["flags"]) == 4
    for row in result["peaks"]:
        assert row["flag"].endswith("lattice fields off by about 3.0 %; try Refine Lattice")
    assert not [p for p in result["pairs"] if p["flag"]]


# --- Unit 3 (C4): Refine Lattice by crystal system ----------------------------------

# (system, the lattice refined from, its free parameters perturbed 1 % each).
REFINE_CASES = {
    "cubic": ("cubic", (4.05, 4.05, 4.05, 90, 90, 90), (4.0905, 4.0905, 4.0905, 90, 90, 90)),
    "tetragonal": ("tetragonal", (4.0, 4.0, 6.0, 90, 90, 90), (4.04, 4.04, 5.94, 90, 90, 90)),
    "orthorhombic": ("orthorhombic", (4.0, 5.0, 6.0, 90, 90, 90),
                     (4.04, 4.95, 6.06, 90, 90, 90)),
    "hexagonal": ("hexagonal", (3.21, 3.21, 5.21, 90, 90, 120),
                  (3.2421, 3.2421, 5.1579, 90, 90, 120)),
    "trigonal-hexagonal-axes": ("trigonal", (3.21, 3.21, 5.21, 90, 90, 120),
                                (3.1779, 3.1779, 5.2621, 90, 90, 120)),
    "trigonal-rhombohedral-axes": ("trigonal", (5.0, 5.0, 5.0, 80, 80, 80),
                                   (5.05, 5.05, 5.05, 80.8, 80.8, 80.8)),
    "monoclinic-b": ("monoclinic", (5.1, 6.3, 7.2, 90, 103.5, 90),
                     (5.151, 6.237, 7.272, 90, 104.535, 90)),
    "monoclinic-a": ("monoclinic", (5.1, 6.3, 7.2, 98, 90, 90),
                     (5.049, 6.363, 7.128, 98.98, 90, 90)),
    "monoclinic-c": ("monoclinic", (5.1, 6.3, 7.2, 90, 90, 112),
                     (5.151, 6.363, 7.128, 90, 90, 110.88)),
    "triclinic": ("triclinic", (5.1, 6.3, 7.2, 85, 95, 100),
                  (5.151, 6.237, 7.272, 85.85, 94.05, 101.0)),
}
REFINE_HKLS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, -1, 1)]


def _refine_peaks(models, lattice, hkls, seed=53):
    """Peaks of ``lattice`` taken under a seeded mount (k = 4, |Q| up to 8)."""
    gonio = models["in8"].goniometer
    u_true = _random_mount(np.random.default_rng(seed))
    b_true = reciprocal_basis_tas(*lattice)
    return [_true_peak(gonio, 1, hkl, u_true, b_true, k=4.0) for hkl in hkls]


@pytest.mark.parametrize("case", list(REFINE_CASES))
def test_refine_lattice_recovers_every_crystal_system(models, case):
    """Refined from the unperturbed lattice, peaks of the perturbed one give
    it back to 1e-6: the constraint per system and the (2 pi)^2 factor from
    G* to the direct metric (the round trip through compute_B_matrix)."""
    from tavi.ub_matrix import refine_lattice_from_peaks

    system, start, perturbed = REFINE_CASES[case]
    result = refine_lattice_from_peaks(_refine_peaks(models, perturbed, REFINE_HKLS), start, system)
    assert result["crystal_system"] == system
    assert np.allclose(result["lattice"], perturbed, rtol=0.0, atol=1e-6), result["lattice"]
    assert result["rms_error"] < 1e-9 and "method" not in result


@pytest.mark.parametrize(("system", "start", "hkls", "words"), [
    ("tetragonal", (4.0, 4.0, 6.0, 90, 90, 90), [(1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
     "tetragonal refinement fits 2 parameters but the 4 valid peaks give 1 independent"),
    ("monoclinic", (5.1, 6.3, 7.2, 90, 103.5, 90), [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
     "monoclinic refinement fits 4 parameters but the 3 valid peaks give 3 independent"),
    ("cubic", (4.0, 4.0, 5.0, 90, 90, 90), [(1, 0, 0), (0, 0, 1)],
     "do not have the cubic metric"),
    ("trigonal", (5.0, 5.0, 6.0, 80, 80, 80), [(1, 0, 0), (0, 0, 1)],
     "do not have the trigonal metric"),
])
def test_refine_lattice_refuses_what_the_peaks_or_fields_cannot_decide(models, system, start,
                                                                      hkls, words):
    from tavi.ub_matrix import refine_lattice_from_peaks

    with pytest.raises(ValueError, match=words):
        refine_lattice_from_peaks(_refine_peaks(models, start, hkls), start, system)


def test_with_no_system_the_fields_highest_symmetry_is_refined(models):
    """D13: hexagonal axes read as hexagonal (the same metric as trigonal on
    them), rhombohedral axes as trigonal."""
    from tavi.ub_matrix import lattice_crystal_system, refine_lattice_from_peaks

    named = {name: lattice_crystal_system(start) for name, (_, start, _) in REFINE_CASES.items()}
    assert named == {"cubic": "cubic", "tetragonal": "tetragonal",
                     "orthorhombic": "orthorhombic", "hexagonal": "hexagonal",
                     "trigonal-hexagonal-axes": "hexagonal",
                     "trigonal-rhombohedral-axes": "trigonal", "monoclinic-b": "monoclinic",
                     "monoclinic-a": "monoclinic", "monoclinic-c": "monoclinic",
                     "triclinic": "triclinic"}
    _, start, perturbed = REFINE_CASES["tetragonal"]
    result = refine_lattice_from_peaks(_refine_peaks(models, perturbed, REFINE_HKLS), start)
    assert result["crystal_system"] == "tetragonal"
    assert np.allclose(result["lattice"], perturbed, rtol=0.0, atol=1e-6)
