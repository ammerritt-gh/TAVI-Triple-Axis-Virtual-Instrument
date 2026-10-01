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
import importlib
import math

import numpy as np
import pytest

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
def test_correction_changed_after_take_position_keeps_the_crystal_in_place(models, name, sense):
    """Peaks taken under psi = 1, psi then set to 2, refit, drive to a new HKL:
    the emitted physical angles put the per-sense -/+ U_true B hkl on Q_lab.

    Hidden zero errors are on throughout and are never part of a record. The
    new psi (and kappa) cancel them, the one case where the operator's model
    (readout frame, no zero errors) is exact for a tilted crystal: a turntable
    or lower-arc offset is not a mount rotation once the arcs move, so any
    other case can only be fitted in the least-squares sense."""
    from instruments.tas_runtime import stage_corrections

    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    u_true = _rot((1, 0, 0), 3.0) @ U_IN_PLANE
    model.U_true = u_true                  # the arm reads the true mount
    model.mis_omega, model.mis_chi, model.kappa = -2.0, -0.3, 0.3
    gonio = model.goniometer

    def solve(q_mount):
        qx, qy, qz = component_q_to_instrument_q(q_mount)
        angles, flags = model.calculate_stage_angles(
            qx, qy, qz, 0.0, E_K, "Kf Fixed", "pg002", "pg002")
        assert flags == []
        return angles

    # Take Position under psi = 1 at the setting where the TRUE crystal reflects.
    model.psi = 1.0
    peaks = []
    for hkl in [(1, 0, 0), (0, 1, 0), (1, 1, 0)]:
        _mtt, stt, a3, sgl, _att, sgu = solve(u_true @ CUBIC_B @ np.array(hkl, float))
        readouts = {"A3": a3 - model.psi - model.mis_omega,     # physical -> readout
                    "sgl": sgl - model.kappa - model.mis_chi, "sgu": sgu}
        record = stage_record(gonio, readouts, stage_corrections(gonio, vars(model)),
                              ki=K, kf=K, sense=sense)
        assert set(record) == {"axes", "angles", "corrections", "ki", "kf", "sense"}
        peaks.append(ObservedPeak(hkl=hkl, angles=(readouts["A3"], 0.0, stt), ki=K, kf=K,
                                  stage=record))
    assert all(p.sense_sample == sense for p in peaks)

    model.psi = 2.0
    target = np.array((1, -1, 0), dtype=float)

    def drive_and_emit(corrections):
        ub = UBMatrix(*LATTICE)
        ub.peaks = peaks
        ub.calculate_U_from_peaks(corrections)
        _mtt, stt, a3, sgl, _att, sgu = solve(ub.UB @ target)
        model.A3, model.sgl, model.sgu = a3, sgl, sgu
        params = model.build_point_params(0.0)
        arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                     params["sample_rz_param"])      # (R_stage U_true)^T
        lab = arm.T @ (CUBIC_B @ target)
        return (-lab if sense > 0 else lab), lab_q_from_stt(K, K, stt)

    placed, q_lab = drive_and_emit(stage_corrections(gonio, vars(model)))
    assert np.allclose(placed, q_lab, rtol=0.0, atol=1e-9)

    # Reading the peaks as recorded (the correction change ignored) misses by
    # the 1 deg psi moved: the rule is what brings the crystal back.
    placed, q_lab = drive_and_emit(None)
    assert _miss_deg(placed, q_lab) > 0.5


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
            model.A3, model.sgl, model.sgu = sth, sgl, sgu
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
        model.A3, model.sgl, model.sgu = 30.0, 1.5, -2.0     # the same physical angles
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

            model.A3, model.sgl, model.sgu = sth, sgl, sgu
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
    scan_point = [*q, 0.0, 3.84, 0.84, 1.98, 1.40, 0.0, 0.0, 0.0]
    assert 45 > 2 * travel
    assert not _arcs_can_level(config.goniometer, instrument_q_to_component_q(q))

    _angles, flags = copy.deepcopy(config).calculate_stage_angles(
        *q, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert len(flags) == 1 and flags[0].startswith("stage: ")
    reason = describe_scan_error_flags(flags)
    assert reason.split()[0] in ("sgl", "sgu")
    assert f"travel is [-{travel}, {travel}]°" in reason

    feasible, feasibility_reason = plugin.check_point_feasibility(
        config, "momentum", scan_point, vals)
    snapshot = plugin.compute_snapshot((scan_point, 0), 0, "momentum", config, vals,
                                       str(tmp_path))
    assert (feasible, feasibility_reason) == (False, reason)
    assert snapshot.params is None
    assert describe_scan_error_flags(snapshot.error_flags) == reason


def test_angle_mode_reads_the_arcs_from_their_slots_and_checks_travel(tmp_path):
    from instruments import tas_runtime
    from instruments.tas_runtime import SCAN_POINT_LENGTH, SLOT_SGL, SLOT_SGU

    plugin, config = _plugin_config(_in12_vals())
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        2.0, 0.0, 0.0, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert flags == []

    def point(sgl, sgu):
        scan_point = [0.0] * SCAN_POINT_LENGTH
        scan_point[:8] = [angles[0], angles[1], angles[2], angles[4], 3.84, 0.84, 1.98, 1.40]
        scan_point[SLOT_SGL], scan_point[SLOT_SGU] = sgl, sgu
        return scan_point

    geom = tas_runtime._solve_point_geometry(
        copy.deepcopy(config), "angle", point(3.0, -2.0), _in12_vals())
    assert geom["error_flags"] == []
    assert (geom["sgl"], geom["sgu"]) == (3.0, -2.0)

    # The per-point record carries the arcs, not the retired chi.
    snapshot = plugin.compute_snapshot((point(3.0, -2.0), 0), 0, "angle", config,
                                       _in12_vals(), str(tmp_path))
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (3.0, -2.0)
    assert "chi" not in snapshot.metadata
    assert (snapshot.params["sgl_param"], snapshot.params["sgu_param"]) == (3.0, -2.0)

    # An 11-slot point (written before the sgu slot) runs with sgu = 0.
    geom = tas_runtime._solve_point_geometry(
        copy.deepcopy(config), "angle", point(3.0, -2.0)[:11], _in12_vals())
    assert (geom["sgl"], geom["sgu"]) == (3.0, 0.0)

    feasible, reason = tas_runtime.check_point_feasibility(
        config, "angle", point(25.0, 0.0), _in12_vals())
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


def test_old_scan_folder_reads_chi_as_sgl(tmp_path):
    from tavi.data_processing import read_parameters_from_file

    (tmp_path / "scan_parameters.txt").write_text(
        "scan_command1: chi 0 2 1\nchi: 2.5\nkappa: 0.0\n", encoding="utf-8")
    params = read_parameters_from_file(str(tmp_path))
    assert params["sgl"] == 2.5 and params["chi"] == 2.5

    (tmp_path / "scan_parameters.txt").write_text(
        "chi: 2.5\nsgl: 1.0\n", encoding="utf-8")
    assert read_parameters_from_file(str(tmp_path))["sgl"] == 1.0


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
                         "tilts": tilts, "kappa": 0.0}
    return plugin, config


def _rlu_point(hkl):
    return [*hkl, 0.0, 3.84, 0.84, 1.98, 1.40, 0.0, 0.0, 0.0, 0.0]


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
    feasible, reason = check_point_feasibility(config, "rlu", _rlu_point((1, 0, 1)), _in12_vals())
    assert not feasible
    assert reason == f"Q is {out:+.4g}° out of " + locked_plane_text(tilts, PLANE_001)

    snapshot = plugin.compute_snapshot((_rlu_point((2, 1, 0)), 0), 0, "rlu", config,
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
            plugin.compute_snapshot((_rlu_point(hkl), 0), 0, "rlu", state, _in12_vals(),
                                    str(tmp_path)).metadata for state in (config, free))
        for key in ("mtt", "stt", "sth", "att", "sgl", "sgu"):
            assert locked_md[key] == pytest.approx(free_md[key], abs=1e-9), (hkl, key)


def test_an_angle_mode_point_runs_at_the_lock_or_is_refused(tmp_path):
    """Angle mode under a lock: arc slots that match the lock (to the GUI
    fields' four-decimal rounding) run at the lock's exact tilts; a slot that
    differs is refused by feasibility, before anything runs."""
    from instruments import tas_runtime
    from instruments.tas_runtime import SCAN_POINT_LENGTH, SLOT_SGL, SLOT_SGU
    from tavi.orientation import locked_plane_text

    plugin, config = _locked_in12(_rot((1, 0, 0), 3.0) @ _rot((0, 0, 1), -2.0))
    tilts = config.plane_lock["tilts"]
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        2.0, 0.0, 0.0, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert flags == []

    def point(sgl, sgu):
        scan_point = [0.0] * SCAN_POINT_LENGTH
        scan_point[:8] = [angles[0], angles[1], angles[2], angles[4], 3.84, 0.84, 1.98, 1.40]
        scan_point[SLOT_SGL], scan_point[SLOT_SGU] = sgl, sgu
        return scan_point

    shown = (round(tilts["sgl"], 4), round(tilts["sgu"], 4))
    snapshot = plugin.compute_snapshot((point(*shown), 0), 0, "angle", config,
                                       _in12_vals(), str(tmp_path))
    assert snapshot.error_flags == []
    assert (snapshot.metadata["sgl"], snapshot.metadata["sgu"]) == (tilts["sgl"], tilts["sgu"])

    feasible, reason = tas_runtime.check_point_feasibility(
        config, "angle", point(shown[0] + 0.5, shown[1]), _in12_vals())
    assert not feasible
    assert reason == (f"sgl = {shown[0] + 0.5:.4g}° is not a tilt of "
                      + locked_plane_text(tilts, PLANE_001))


# --- corrections and zero errors reach McStas as axis rotations -------------------

@pytest.mark.parametrize(("field", "axis_name"), [
    ("psi", "A3"), ("mis_omega", "A3"), ("kappa", "sgl"), ("mis_chi", "sgl"),
])
def test_offset_changes_the_emitted_rotation_by_that_axis_rotation(models, field, axis_name):
    model = copy.deepcopy(models["in8"])
    u = _rot((2, -1, 1), 6.0)
    model.U_true = u                       # the arm reads the true mount
    model.A3, model.sgl, model.sgu = 37.0, 4.0, -6.0
    before = mccode_rotation_matrix(*sample_arm_euler(
        model.goniometer, model.physical_stage_angles(), u)).T
    setattr(model, field, 1.75)
    params = model.build_point_params(0.0)
    emitted = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                     params["sample_rz_param"]).T
    shifted = {"A3": 37.0, "sgl": 4.0, "sgu": -6.0}
    shifted[axis_name] += 1.75
    expected = (_rot((0, 1, 0), shifted["A3"]) @ _rot((1, 0, 0), shifted["sgl"])
                @ _rot((0, 0, 1), shifted["sgu"]) @ u)
    assert np.allclose(emitted, expected, rtol=0.0, atol=1e-12)
    assert not np.allclose(emitted, before, rtol=0.0, atol=1e-6)


def test_corrections_and_zero_errors_follow_the_stage_description(models, monkeypatch):
    """Which state field corrects an axis, and which hides its zero error, is
    declared on the axis (TAS: A3 psi / mis_omega, sgl kappa / mis_chi, sgu
    none). A description that maps them otherwise is read as written."""
    import dataclasses

    from instruments.tas_runtime import TAS_Instrument, stage_corrections

    model = copy.deepcopy(models["in8"])
    a3, sgl, sgu = model.goniometer
    assert [(ax.correction, ax.zero_error) for ax in model.goniometer] == [
        ("psi", "mis_omega"), ("kappa", "mis_chi"), (None, None)]
    remapped = (dataclasses.replace(a3, correction="kappa", zero_error=None),
                dataclasses.replace(sgl, correction=None, zero_error=None),
                dataclasses.replace(sgu, correction="psi", zero_error="mis_chi"))
    monkeypatch.setattr(TAS_Instrument, "goniometer", property(lambda self: remapped))
    model.A3, model.sgl, model.sgu = 30.0, 2.0, -3.0
    model.psi, model.kappa, model.mis_omega, model.mis_chi = 1.0, 0.5, 0.25, -0.125
    assert model.physical_stage_angles() == {"A3": 30.5, "sgl": 2.0, "sgu": -2.125}
    assert stage_corrections(remapped, {"psi": 1.0, "kappa": 0.5}) == {
        "A3": 0.5, "sgl": 0.0, "sgu": 1.0}


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
    for field, value in (("A3", 12.0), ("sgl", 3.0), ("sgu", -4.0), ("psi", 1.0),
                         ("kappa", -1.0), ("mis_omega", 0.5), ("mis_chi", 0.25)):
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


def _engine_point(config, mode, coords, tmp_path, sgl=0.0, sgu=0.0, kappa=0.0, psi=0.0):
    """One IN8 scan point through the shared snapshot, and the engine's HKL."""
    from instruments.tas_runtime import (SLOT_KAPPA, SLOT_PSI, SLOT_SGL, SLOT_SGU,
                                         true_point_hkl)

    point = [*coords, 3.84, 0.84, 1.98, 1.40, 0.0, 0.0, 0.0, 0.0]
    point[SLOT_SGL], point[SLOT_SGU], point[SLOT_KAPPA], point[SLOT_PSI] = sgl, sgu, kappa, psi
    plugin, _ = _plugin_config(_in12_vals(), "in8")
    snapshot = plugin.compute_snapshot((point, 0), 0, mode, config, _in12_vals(), str(tmp_path))
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
    _, on = _engine_point(_in8_config(sense), "rlu", (2, 0, 0, 0), tmp_path)
    assert on == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)

    wrong = _in8_config(sense, u_operator=_rot((0, 1, 0), 3.0))
    _, off = _engine_point(wrong, "rlu", (2, 0, 0, 0), tmp_path)
    assert np.linalg.norm(off) == pytest.approx(2.0, abs=1e-9)
    assert _miss_deg(off, np.array([2.0, 0.0, 0.0])) == pytest.approx(3.0, abs=1e-6)


@pytest.mark.parametrize("mode", ["rlu", "momentum", "orientation", "angle"])
def test_hidden_turntable_zero_error_reaches_the_engine_in_every_mode(tmp_path, mode):
    """WIP Entry 14: a hidden 3 deg turntable zero error with psi = 0 takes
    the crystal off (2 0 0) in every mode; psi = -3 puts it back."""
    coords = (2, 0, 0, 0) if mode == "rlu" else (*Q_200, 0.0)
    sgl = sgu = 0.0
    if mode == "angle":
        reference, _ = _engine_point(_in8_config(-1), "rlu", (2, 0, 0, 0), tmp_path)
        coords, sgl, sgu = _angle_coords(reference)
    hkls = {}
    for mis, psi in ((0.0, 0.0), (3.0, 0.0), (3.0, -3.0)):
        config = _in8_config(-1)
        config.mis_omega = mis
        _, hkls[(mis, psi)] = _engine_point(config, mode, coords, tmp_path,
                                            sgl=sgl, sgu=sgu, psi=psi)
    assert hkls[(0.0, 0.0)] == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)
    assert np.linalg.norm(hkls[(3.0, 0.0)] - [2.0, 0.0, 0.0]) > 0.05
    assert hkls[(3.0, -3.0)] == pytest.approx([2.0, 0.0, 0.0], abs=1e-9)


@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("mode", ["rlu", "momentum", "orientation", "angle"])
def test_engine_hkl_is_the_emitted_arm_on_lab_q_and_ignores_the_ub(tmp_path, mode, sense):
    """At tilted arcs, with zero errors and corrections in force, B_true @ hkl
    is the emitted sample arm's rotation applied to the lab Q (signed per
    sense): the engine sees the crystal McStas builds. In the Q and angle
    modes the operator's UB does not move it."""
    u_true = _rot((1, 2, 0), 6.0) @ U_IN_PLANE
    coords = {"rlu": (2, 1, 0.5, 0.0), "momentum": (2.4, 0.6, 0.5, 0.0),
              "orientation": (2.4, 0.6, 0.5, 0.0)}.get(mode)
    sgl = sgu = 0.0
    if mode == "angle":
        reference, _ = _engine_point(_in8_config(sense, u_true, _rot((1, 0, 0), 5.0)),
                                     "rlu", (2, 1, 0.5, 0.0), tmp_path)
        coords, _sgl, _sgu = _angle_coords(reference)
        sgl, sgu = 4.0, -6.0
    found = []
    for u_operator in (_rot((1, 0, 0), 5.0), _rot((0, 1, 1), 9.0)):
        config = _in8_config(sense, u_true, u_operator)
        config.mis_omega, config.mis_chi = 0.7, -0.4
        snapshot, hkl = _engine_point(config, mode, coords, tmp_path,
                                      sgl=sgl, sgu=sgu, kappa=-0.2, psi=0.3)
        md, params = snapshot.metadata, snapshot.params
        assert abs(md["sgl"]) + abs(md["sgu"]) > 1.0                 # the arcs are tilted
        arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                     params["sample_rz_param"])
        lab_q = lab_q_from_stt(md["Ki"], md["Kf"], md["stt"])
        signed = -1.0 if sense > 0 else 1.0
        assert np.allclose(CUBIC_B @ hkl, signed * arm @ lab_q, rtol=0.0, atol=1e-9)
        found.append(hkl)
    if mode != "rlu":
        assert np.array_equal(found[0], found[1])


# --- Unit 2 (C5): training graded on the truth --------------------------------------

STANDARD_REFLECTIONS = [(1, 0, 0), (0, 1, 0), (1, 1, 0)]
# The same physical geometry on both senses: PUMA is -1, IN8 +1.
SENSES = [("puma", -1), ("in8", 1)]


def _true_peak(gonio, sense, hkl, u_true, b_true, corrections, zero_errors, k=K):
    """A peak taken where the true crystal diffracts: the physical setting
    that puts the true reflection on the lab Q, recorded as readouts
    (physical - correction - zero error) with the corrections in force."""
    q = u_true @ b_true @ np.array(hkl, dtype=float)
    stt = stt_from_q_norm(float(np.linalg.norm(q)), k, k, sense)
    physical = solve_stage(gonio, -q if sense > 0 else q, lab_q_from_stt(k, k, stt))
    readouts = {name: angle - corrections.get(name, 0.0) - zero_errors.get(name, 0.0)
                for name, angle in physical.items()}
    record = stage_record(gonio, readouts, corrections=corrections, ki=k, kf=k, sense=sense)
    return ObservedPeak(hkl=tuple(hkl), angles=(readouts["A3"], readouts["sgl"], stt),
                        ki=k, kf=k, stage=record)


def _fit_and_grade(gonio, sense, u_true, zero_errors, corrections, peak_hkls,
                   turn_ub=np.eye(3)):
    """The operator fits a UB from peaks taken on the true crystal (lattice
    fields right), optionally turns it, and is graded on those peaks plus the
    standard-setting reflections."""
    from tavi.ub_matrix import grade_alignment

    ub = UBMatrix(*LATTICE)
    ub.peaks = [_true_peak(gonio, sense, hkl, u_true, CUBIC_B, corrections, zero_errors)
                for hkl in peak_hkls]
    ub.calculate_U_from_peaks(corrections)
    return grade_alignment(gonio, sense, K, K, turn_ub @ ub.UB, corrections, u_true, CUBIC_B,
                           zero_errors, list(peak_hkls) + STANDARD_REFLECTIONS)


@pytest.mark.parametrize("psi", [0.0, -3.0], ids=["fit-absorbs", "psi-corrects"])
@pytest.mark.parametrize(("name", "sense"), SENSES, ids=[n for n, _ in SENSES])
def test_a_fit_on_the_true_crystal_grades_aligned(models, name, sense, psi):
    """A hidden 3 deg turntable zero error: a fit with psi = 0 absorbs it,
    psi = -3 corrects it; both command the true reflections (aligned). The
    grade compares settings, not U with U or psi with the zero error."""
    grade = _fit_and_grade(models[name].goniometer, sense, U_IN_PLANE, {"A3": 3.0},
                           {"A3": psi}, PEAKS_2)
    assert grade["status"] == "aligned", grade
    assert grade["worst_miss"] < 1e-6


@pytest.mark.parametrize(("name", "sense"), SENSES, ids=[n for n, _ in SENSES])
def test_a_ub_five_degrees_off_grades_way_off(models, name, sense):
    grade = _fit_and_grade(models[name].goniometer, sense, U_IN_PLANE, {"A3": 3.0},
                           {"A3": 0.0}, PEAKS_2, turn_ub=_rot((0, 1, 0), 5.0))
    assert grade["status"] == "way_off", grade
    assert grade["worst_miss"] == pytest.approx(5.0, abs=1e-6)


def test_an_exact_u_on_lattice_fields_two_percent_off_grades_by_its_two_theta_miss(models):
    from tavi.ub_matrix import grade_alignment

    gonio = models["in8"].goniometer
    b_fields = reciprocal_basis_tas(*(1.02 * x for x in LATTICE[:3]), *LATTICE[3:])
    grade = grade_alignment(gonio, 1, K, K, U_IN_PLANE @ b_fields, {}, U_IN_PLANE, CUBIC_B,
                            {}, STANDARD_REFLECTIONS)

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
    grade = grade_alignment(models["in8"].goniometer, 1, K, K, b_fields, {}, np.eye(3),
                            CUBIC_B, {}, STANDARD_REFLECTIONS + [(2, 2, 0)])
    assert grade["status"] == "way_off" and grade["worst_hkl"] == (2, 2, 0), grade
    assert grade["worst_miss"] == math.inf
    assert "(2 2 0) closes no scattering triangle" in grade["summary"]


@pytest.mark.parametrize("cancelling", [True, False], ids=["cancelling", "residual"])
def test_tilted_truth_grades_by_what_the_fit_leaves(models, cancelling):
    """Under tilted arcs a correction is absorbed exactly only when it cancels
    the zero error (amendment 3c): then aligned; otherwise the grade is the
    least-squares fit's residual miss, smaller than the offsets themselves."""
    gonio = models["in8"].goniometer
    u_true = _rot((2, 0, -1), 8.0) @ U_IN_PLANE
    zero_errors = {"A3": 3.0, "sgl": 2.0}
    corrections = {"A3": -3.0, "sgl": -2.0} if cancelling else {}
    peaks = [(1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)]
    for hkl in peaks:                                # the peaks need the arcs
        q = u_true @ CUBIC_B @ np.array(hkl, dtype=float)
        assert abs(q[1]) / np.linalg.norm(q) > math.sin(math.radians(1.0))
    grade = _fit_and_grade(gonio, 1, u_true, zero_errors, corrections, peaks)
    if cancelling:
        assert grade["status"] == "aligned" and grade["worst_miss"] < 1e-6, grade
    else:
        assert 0.05 < grade["worst_miss"] < math.hypot(3.0, 2.0), grade
        band = "aligned" if grade["worst_miss"] <= 0.5 else (
            "close" if grade["worst_miss"] <= 2.0 else "way_off")
        assert grade["status"] == band


def test_too_few_reachable_reflections_or_no_sample_cannot_be_assessed(models):
    """At k = 1 (|Q| <= 2) a belief with a = 3, b = 5 reaches only (0 1 0) of
    the standard reflections: one direction grades nothing. No sample: no
    crystal to grade against."""
    from tavi.ub_matrix import grade_alignment

    gonio = models["in8"].goniometer
    b_fields = reciprocal_basis_tas(3.0, 5.0, 4.05, 90.0, 90.0, 90.0)
    grade = grade_alignment(gonio, 1, 1.0, 1.0, b_fields, {}, np.eye(3), CUBIC_B, {},
                            STANDARD_REFLECTIONS)
    assert grade["status"] == "cannot_assess", grade
    assert "fewer than two" in grade["summary"]
    assert [s.split(":")[0] for s in grade["skipped"]] == ["(1 0 0)", "(1 1 0)"]

    grade = grade_alignment(gonio, 1, K, K, CUBIC_B, {}, np.eye(3), None, {},
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


def test_an_irrational_plane_normal_has_no_zone_axis():
    from tavi.ub_matrix import get_scattering_plane_info

    u = mccode_rotation_matrix(7.3, 0.0, 11.9)
    info = get_scattering_plane_info(u, CUBIC_B)
    assert info["zone_axis_uvw"] is None
    assert np.allclose(u @ CUBIC_B @ np.array(info["plane_normal_hkl"]), (0, 1, 0))
