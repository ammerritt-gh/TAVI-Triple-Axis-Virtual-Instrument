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
    lock_plane,
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


@pytest.mark.parametrize("lattice", list(LATTICES))
@pytest.mark.parametrize("sense", [-1, 1])
@pytest.mark.parametrize("name", list(INSTRUMENTS))
def test_stage_round_trip_puts_hkl_on_q_lab_and_fits_back(models, name, sense, lattice):
    model = copy.deepcopy(models[name])
    model.sense_sample = sense
    sign = -1.0 if sense > 0 else 1.0          # D2: +1 puts -U B hkl on Q_lab
    B = reciprocal_basis_tas(*LATTICES[lattice])
    rng = np.random.default_rng(SEEDS[name] + 7 * sense + len(lattice))
    for _mount in range(2):
        U = _random_mount(rng)
        model.sample_mount = SampleMount(B, U)
        peaks = []
        for index in rng.permutation(len(HKL_POOL)):
            hkl = np.array(HKL_POOL[index], dtype=float)
            if not 0.5 < np.linalg.norm(B @ hkl) < 4.8:
                continue
            qx, qy, qz = component_q_to_instrument_q(U @ B @ hkl)
            angles, flags = model.calculate_stage_angles(
                qx, qy, qz, 0.0, E_RT, "Kf Fixed", "pg002", "pg002")
            if flags:
                # Only the arcs' travel may refuse a point here.
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
            if len(peaks) == 5:
                break
        assert len(peaks) >= 3, "too few reachable reflections to test"
        ub = UBMatrix(*LATTICES[lattice])
        ub.peaks = peaks
        ub.calculate_U_from_peaks()
        assert np.allclose(ub.U, U, rtol=0.0, atol=1e-9)


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


@pytest.mark.parametrize("q", [
    (0.0, 3.0, 0.0),                    # vertical: needs chi = +/-90 deg
    (0.0, -2.2, 0.0),
    (1.0, 2.0, -0.5),
    (-1.3, -0.4, 2.1),
], ids=["up", "down", "tilted-a", "tilted-b"])
def test_eulerian_cradle_description_round_trips(q):
    q = np.array(q)
    stt = stt_from_q_norm(float(np.linalg.norm(q)), K_RT, K_RT, -1)
    q_lab = lab_q_from_stt(K_RT, K_RT, stt)
    angles = solve_stage(EULER, q, q_lab)
    v_lab = _mcstas_lab_vector(_stage_chain(EULER, angles, np.eye(3)), q)
    assert np.linalg.norm(v_lab - q_lab) < 1e-9 * np.linalg.norm(q_lab)
    if q[0] == q[2] == 0.0:
        assert abs(angles["chi"]) == pytest.approx(90.0, abs=1e-9)


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


def _in12_vals(**overrides):
    vals = {
        "K_fixed": "Kf Fixed", "source_type": "Maxwellian", "source_dE": 2.0,
        "rhm": 3.84, "rvm": 0.84, "rha": 1.98, "rva": 1.40,
        "fixed_E": IN12_E, "monocris": "pg002", "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "30", "alpha_4": "0"},
        "slits_mm": {"sbl": (30.0, 60.0), "dbl_hgap": 50.0},
        "deltaE": 0.0, "chi": 0.0,
    }
    vals.update(overrides)
    return vals


def _in12_config(vals):
    pytest.importorskip("mcstasscript")
    from instruments.in12.plugin import IN12Plugin

    plugin = IN12Plugin()
    state = plugin.default_state()
    return plugin, plugin.scan_config(state, vals, None, {}, state.sample_mount)


def test_unreachable_elevation_is_refused_identically_everywhere(tmp_path):
    """45 deg of elevation cannot be levelled on +/-20 deg arcs: the arcs'
    rotation angle is at most |sgl| + |sgu| <= 40 deg, and no rotation moves a
    vector's elevation by more than its own angle. Established analytically,
    not by a grid sharing the solver's search."""
    from instruments.tas_runtime import describe_scan_error_flags

    vals = _in12_vals()
    plugin, config = _in12_config(vals)
    q = 2.5 * np.array([math.cos(math.radians(45)), 0.0, math.sin(math.radians(45))])
    scan_point = [*q, 0.0, 3.84, 0.84, 1.98, 1.40, 0.0, 0.0, 0.0]

    _angles, flags = copy.deepcopy(config).calculate_stage_angles(
        *q, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert len(flags) == 1 and flags[0].startswith("stage: ")
    reason = describe_scan_error_flags(flags)
    assert reason.split()[0] in ("sgl", "sgu")
    assert "travel is [-20, 20]°" in reason

    feasible, feasibility_reason = plugin.check_point_feasibility(
        config, "momentum", scan_point, vals)
    snapshot = plugin.compute_snapshot((scan_point, 0), 0, "momentum", config, vals,
                                       str(tmp_path))
    assert (feasible, feasibility_reason) == (False, reason)
    assert snapshot.params is None
    assert describe_scan_error_flags(snapshot.error_flags) == reason


def test_angle_mode_reads_the_arcs_and_checks_their_travel():
    from instruments import tas_runtime

    _, config = _in12_config(_in12_vals())
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        2.0, 0.0, 0.0, 0.0, IN12_E, "Kf Fixed", "pg002", "pg002")
    assert flags == []
    scan_point = [angles[0], angles[1], angles[2], angles[4], 3.84, 0.84, 1.98, 1.40,
                  0.0, 0.0, 0.0]

    for patch, expected in (({"chi": 5.0}, (5.0, 0.0)),
                            ({"chi": 5.0, "sgl": 3.0, "sgu": -2.0}, (3.0, -2.0))):
        geom = tas_runtime._solve_point_geometry(
            copy.deepcopy(config), "angle", scan_point, _in12_vals(**patch))
        assert geom["error_flags"] == []
        assert (geom["sgl"], geom["sgu"]) == expected

    feasible, reason = tas_runtime.check_point_feasibility(
        config, "angle", scan_point, _in12_vals(chi=25.0))
    assert not feasible
    assert reason == "sgl 25° is outside its travel [-20, 20]°"


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


# --- corrections and zero errors reach McStas as axis rotations -------------------

@pytest.mark.parametrize(("field", "axis_name"), [
    ("psi", "A3"), ("mis_omega", "A3"), ("kappa", "sgl"), ("mis_chi", "sgl"),
])
def test_offset_changes_the_emitted_rotation_by_that_axis_rotation(models, field, axis_name):
    model = copy.deepcopy(models["in8"])
    u = _rot((2, -1, 1), 6.0)
    model.sample_mount = SampleMount(CUBIC_B, u)
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
    assert plugin.build_fingerprint(config) == before
