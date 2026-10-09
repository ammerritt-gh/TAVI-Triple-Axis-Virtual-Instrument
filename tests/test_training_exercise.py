"""Mount-only training exercises: the code, the observability check, the grader's recovery."""
import base64
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument
from instruments.tas_runtime import training_reach_error
from tavi.neutron_conversions import energy2k
from tavi.orientation import axis_rotation, solve_stage, stage_record
from tavi.reflection_catalog import reference_hkls
from tavi.tas_geometry import lab_q_from_stt, mccode_rotation_matrix, stt_from_q_norm
from tavi.ub_matrix import (
    MOTOR_ZERO_REFUSAL, ObservedPeak, UBMatrix, compute_B_matrix, decode_mount_exercise,
    encode_training, generate_training_exercise, grade_alignment, has_two_nonparallel,
)

FIXED_E = 14.7


def _setup(instrument_id):
    """(plugin, a state at the fixed energy, Al's B, its low-order reflections)."""
    plugin = get_instrument(instrument_id)
    d = plugin.descriptor()
    spec = next(s for s in d.samples if s.id == "Al_bragg")
    state = plugin.default_state()
    state.monocris, state.anacris = d.mono_crystals[0].id, d.ana_crystals[0].id
    state.K_fixed, state.fixed_E = "Kf Fixed", FIXED_E
    hkls = reference_hkls(spec.reflection_source, spec.space_group, "components")
    return state, compute_B_matrix(*spec.lattice), hkls, spec.lattice


def _limits(instrument_id):
    return get_instrument(instrument_id).descriptor().axis_limits


def _true_readouts(state, u_true, b_true, hkl, k):
    """Where the stage must stand for the true crystal to diffract ``hkl``, or None."""
    q = u_true @ b_true @ np.asarray(hkl, dtype=float)
    try:
        stt = stt_from_q_norm(float(np.linalg.norm(q)), k, k, state.sense_sample)
        readouts = solve_stage(state.goniometer, -q if state.sense_sample > 0 else q,
                               lab_q_from_stt(k, k, stt))
    except ValueError:
        return None
    return readouts, stt


def test_a_mount_only_code_decodes_and_every_other_code_is_refused():
    rotation = mccode_rotation_matrix(3.0, 5.0, -2.0)
    assert np.allclose(decode_mount_exercise(encode_training(rotation, 0.0, 0.0)),
                       rotation, atol=1e-6)

    for motor_zeros in ((1.25, 0.0), (0.0, -0.5), (0.5, 0.5)):
        with pytest.raises(ValueError) as old:
            decode_mount_exercise(encode_training(rotation, *motor_zeros))
        assert str(old.value) == MOTOR_ZERO_REFUSAL == (
            "this exercise was made by an older TAVI and contains motor-zero errors, "
            "which are no longer simulated; ask for a new code")

    # The retired Misalignment dock's code: two floats under its own key.
    key = b"TAVI_ALIGN_2026"
    packed = struct.pack("<ff", 1.5, -0.75)
    retired = base64.urlsafe_b64encode(
        bytes(b ^ key[i % len(key)] for i, b in enumerate(packed))).decode("ascii")
    with pytest.raises(ValueError) as dock:
        decode_mount_exercise(retired)
    assert str(dock.value) == MOTOR_ZERO_REFUSAL
    for code in ("not-a-code", "", "A" * 60):
        with pytest.raises(ValueError, match="cannot be read"):
            decode_mount_exercise(code)


def test_generation_writes_zero_motor_zeros_and_the_code_keeps_its_layout():
    np.random.seed(5)
    code = generate_training_exercise(max_ori_angle=20.0)
    assert len(base64.urlsafe_b64decode(code)) == 44                 # 11 floats, as before
    decode_mount_exercise(code)                                      # mount-only: accepted


def test_generation_says_why_when_no_draw_is_accepted():
    with pytest.raises(ValueError, match=r"\(50 tried\): nothing reachable"):
        generate_training_exercise(45.0, accept=lambda rotation: "nothing reachable")
    # The max-angle spin is the only control: 0 hides nothing.
    assert np.allclose(decode_mount_exercise(generate_training_exercise(0.0)), np.eye(3))


@pytest.mark.parametrize("instrument_id, reachable", [("panda", False), ("in8", True)])
def test_the_check_refuses_a_rotation_the_stage_cannot_reach(instrument_id, reachable):
    """In the standard mount (1 0 0) lies along x and (0 1 0) along z, in the
    plane; (0 0 1) is vertical. A 45 deg turn about x tips (0 1 0) and (0 0 1)
    45 deg out of the plane, past PANDA's +/-15 deg arcs and inside IN8's
    unlimited travel, while (1 0 0) stays put: one direction is never enough."""
    state, b, _, _ = _setup(instrument_id)
    limits = _limits(instrument_id)
    rotation = axis_rotation((1, 0, 0), 45.0)
    assert training_reach_error(state, np.eye(3), b, [(1, 0, 0), (0, 1, 0)], limits) is None
    for pair in ([(1, 0, 0), (0, 1, 0)], [(0, 1, 0), (0, 0, 1)]):
        reason = training_reach_error(state, rotation, b, pair, limits)
        assert (reason is None) == reachable, pair
        if not reachable:
            assert "at least two non-parallel" in reason


def test_a_locked_plane_does_not_change_what_a_student_can_find():
    state, b, hkls, _ = _setup("panda")
    state.plane_lock = {"hkl_u": [1, 0, 0], "hkl_v": [0, 1, 0], "tilts": {"sgl": 0.0, "sgu": 0.0}}
    # 30 deg about (1 0 1) is refused by PANDA's travel (only a parallel pair is
    # reachable), so the observable case uses 20 deg.
    assert training_reach_error(state, axis_rotation((1, 0, 1), 20.0), b, hkls,
                                _limits("panda")) is None
    assert state.plane_lock is not None                    # the caller's state is not touched


def test_generation_on_panda_always_leaves_two_reachable_reflections():
    """The dock lets a teacher ask for 45 deg against PANDA's +/-15 deg arcs;
    every code generated with the check has at least two non-parallel
    reflections the true crystal brings into the plane (found here with
    solve_stage alone, not the check)."""
    state, b, hkls, _ = _setup("panda")
    k = energy2k(FIXED_E)
    for seed in range(12):
        np.random.seed(seed)
        code = generate_training_exercise(
            45.0, accept=lambda rotation: training_reach_error(
                state, rotation, b, hkls, _limits("panda")))
        rotation = decode_mount_exercise(code)
        reached = [hkl for hkl in hkls if _true_readouts(state, rotation, b, hkl, k)]
        assert has_two_nonparallel(reached), (seed, reached)


def test_a_generated_exercise_is_recovered_to_aligned_from_tilted_peaks():
    """PANDA, a hidden turn of up to 45 deg: peaks found where the true
    crystal diffracts, with the arcs tilted, fit a UB the grader calls
    aligned -- the hidden error is exactly a U, so nothing is left over."""
    state, b, hkls, lattice = _setup("panda")
    k, gonio, sense = energy2k(FIXED_E), state.goniometer, state.sense_sample
    np.random.seed(2)
    code = generate_training_exercise(
        45.0, accept=lambda rotation: training_reach_error(
            state, rotation, b, hkls, _limits("panda")))
    u_true = decode_mount_exercise(code)

    found = []
    for hkl in hkls:
        setting = _true_readouts(state, u_true, b, hkl, k)
        if setting is not None and abs(setting[0]["sgl"]) + abs(setting[0]["sgu"]) > 1.0:
            found.append((hkl, *setting))
    assert has_two_nonparallel(hkl for hkl, _, _ in found), "this seed has no tilted pair"
    peaks = [ObservedPeak(hkl=hkl, angles=(readouts["A3"], readouts["sgl"], stt), ki=k, kf=k,
                          stage=stage_record(gonio, readouts, ki=k, kf=k, sense=sense))
             for hkl, readouts, stt in found]
    ub = UBMatrix(*lattice)
    ub.peaks = peaks
    ub.calculate_U_from_peaks()

    grade = grade_alignment(gonio, sense, k, k, ub.UB, u_true, b, [p.hkl for p in peaks])
    assert grade["status"] == "aligned" and grade["worst_miss"] < 1e-6, grade
    assert np.allclose(ub.U, u_true, atol=1e-5)


# --- the controller: nothing is applied from a refused code -----------------------------

def _controller_for(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    plugin = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        plugin.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=plugin.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture(scope="module")
def in8():
    yield from _controller_for("in8")


@pytest.fixture(scope="module")
def panda():
    yield from _controller_for("panda")


@pytest.fixture
def said():
    return []


def _watch(ctrl, said):
    ctrl.message_printed.connect(said.append)
    return lambda: ctrl.message_printed.disconnect(said.append)


def _hidden(ctrl):
    return (ctrl.U_described.copy(), ctrl.R_hidden.copy(), ctrl.instrument_state.U_true.copy(),
            ctrl.ub_matrix.U.copy(), ctrl._exercise)


def _same(a, b):
    return all(np.array_equal(x, y) if isinstance(x, np.ndarray) else x == y
               for x, y in zip(a, b))


def _press_load(ctrl, code):
    ctrl.window.ub_matrix_dock.load_hash_edit.setText(code)
    ctrl.on_load_training()


def test_a_refused_code_applies_nothing(in8, said):
    in8.set_default_parameters()
    rotation = mccode_rotation_matrix(3.0, 5.0, -2.0)
    key = b"TAVI_ALIGN_2026"
    retired = base64.urlsafe_b64encode(bytes(
        b ^ key[i % len(key)] for i, b in enumerate(struct.pack("<ff", 1.5, -0.75)))).decode("ascii")
    stop = _watch(in8, said)
    try:
        for before_code in (None, encode_training(rotation, 0.0, 0.0)):
            in8.set_default_parameters()
            if before_code:
                _press_load(in8, before_code)
            before = _hidden(in8)
            said.clear()
            for code, words in ((encode_training(rotation, 1.25, 0.0), "no longer simulated"),
                                (retired, "no longer simulated"), ("garbage", "cannot be read")):
                _press_load(in8, code)
                assert _same(before, _hidden(in8)), code
                assert any(m.startswith("Exercise refused:") and words in m for m in said), said
                said.clear()
    finally:
        stop()
        in8.set_default_parameters()


@pytest.mark.parametrize("fixture", ["in8", "panda"])
def test_both_engines_present_the_same_hkl_for_a_loaded_mount_only_exercise(
        request, fixture, tmp_path):
    """Audit entry 14: with a hidden mount rotation loaded, the analytic
    engine's presented (H, K, L) (``true_point_hkl``: the point's readouts and
    U_true through B_true) is the (H, K, L) the McStas path is given (the
    emitted sample-arm rotation applied to the lab Q, through B_true), at the
    same commanded point; and both differ from the commanded one by the hidden
    turn. No McStas run: the emitted parameters are what McStas receives."""
    from instruments.tas_runtime import true_point_hkl
    from tavi.tas_geometry import lab_q_from_stt

    ctrl = request.getfixturevalue(fixture)
    ctrl.set_default_parameters()
    code = encode_training(mccode_rotation_matrix(3.0, 5.0, -2.0), 0.0, 0.0)
    _press_load(ctrl, code)
    assert ctrl._exercise == code
    b_true = ctrl._true_B()
    sign = -1.0 if ctrl.instrument_state.sense_sample > 0 else 1.0
    try:
        for commanded in ((2.0, 0.0, 0.2), (1.5, 1.0, 0.3), (2.0, 0.5, -0.2)):
            launch = ctrl.build_api_launch_state(
                {"H": commanded[0], "K": commanded[1], "L": commanded[2], "deltaE": 0.0,
                 "scan_command1": f"H {commanded[0]} {commanded[0]} 1"})
            vals, config = launch["vals"], launch["scan_config"]
            point = ctrl._build_scan_point_template("rlu", vals)
            snapshot = ctrl.instrument.compute_snapshot(
                (point, 0), 0, "rlu", config, vals, str(tmp_path))
            assert snapshot.error_flags == [], snapshot.error_flags
            md, params = snapshot.metadata, snapshot.params
            analytic = np.array(true_point_hkl(config, md, b_true))
            arm = mccode_rotation_matrix(params["sample_rx_param"], params["sample_ry_param"],
                                         params["sample_rz_param"])
            mcstas = np.linalg.solve(
                b_true, sign * arm @ lab_q_from_stt(md["Ki"], md["Kf"], md["stt"]))
            assert analytic == pytest.approx(mcstas, abs=1e-9), commanded
            assert np.linalg.norm(analytic - commanded) > 0.05, "the hidden turn must show"
    finally:
        ctrl.set_default_parameters()


def test_an_old_mount_only_code_loads(in8):
    in8.set_default_parameters()
    code = encode_training(mccode_rotation_matrix(3.0, 5.0, -2.0), 0.0, 0.0)
    _press_load(in8, code)
    assert in8._exercise == code
    assert np.allclose(in8.R_hidden, mccode_rotation_matrix(3.0, 5.0, -2.0), atol=1e-6)
    assert np.array_equal(in8.ub_matrix.U, in8.U_described)
    in8.set_default_parameters()


def test_an_exercise_past_the_instruments_motor_limits_is_refused(in8):
    """IN8's sample 2theta travel is +-120 deg. At fixed Kf 4 meV every Al (111)
    reflection needs about 150 deg, so none is reachable within the limits; the
    arcs alone (unlimited on IN8) would reach them, which is what the limits stop."""
    d = in8.descriptor
    reason = in8._exercise_reach_error(np.eye(3), in8.U_described, "Al_bragg",
                                       d.mono_crystals[0].id, d.ana_crystals[0].id,
                                       "Kf Fixed", 4.0)
    assert reason and "at least two non-parallel" in reason, reason

    state, b, hkls, _ = _setup("in8")
    state.fixed_E = 4.0
    assert training_reach_error(state, np.eye(3), b, hkls, {}) is None


def test_the_reach_check_reads_the_tables_beside_the_package_not_the_working_directory(
        in8, monkeypatch):
    """Started from tests/, the check reads the same reflection tables (and so
    judges the same reflections) as from the repository root."""
    from instruments.paths import COMPONENTS_DIR

    d = in8.descriptor
    args = ("Al_phonon_DFT", d.mono_crystals[0].id, d.ana_crystals[0].id, "Kf Fixed", 14.7)
    read = []
    real = cm.reference_hkls

    def spy(source, space_group, components_dir):
        read.append(components_dir)
        return real(source, space_group, components_dir)

    monkeypatch.setattr(cm, "reference_hkls", spy)
    from_root = in8._exercise_reach_error(np.eye(3), in8.U_described, *args)
    monkeypatch.chdir(os.path.dirname(__file__))
    from_tests = in8._exercise_reach_error(np.eye(3), in8.U_described, *args)
    assert from_tests == from_root
    assert read == [COMPONENTS_DIR, COMPONENTS_DIR], read


def test_panda_refuses_an_unobservable_exercise_and_says_why_at_generation(panda, said,
                                                                         monkeypatch):
    """With only (1 0 0) and (0 1 0) to find, a 45 deg turn about x leaves PANDA
    one reachable direction: load refuses it, generation redraws and then says
    why. With the sample's real reflections the same instrument generates and
    loads a 45 deg exercise."""
    panda.set_default_parameters()
    turned = axis_rotation((1, 0, 0), 45.0)
    code = encode_training(turned, 0.0, 0.0)
    stop = _watch(panda, said)
    try:
        monkeypatch.setattr(cm, "reference_hkls", lambda *a, **k: [(1, 0, 0), (0, 1, 0)])
        before = _hidden(panda)
        _press_load(panda, code)
        assert _same(before, _hidden(panda))
        assert any("Exercise refused: the instrument cannot observe this exercise" in m
                   for m in said), said

        said.clear()
        dock = panda.window.ub_matrix_dock
        dock.max_ori_spin.setValue(45)
        dock.training_hash_display.setText("")
        monkeypatch.setattr("tavi.ub_matrix._random_rotation_matrix", lambda _angle: turned)
        panda.on_generate_training()
        assert dock.training_hash_display.text() == ""
        assert any("Failed to generate training: no hidden rotation within 45" in m
                   and "(50 tried)" in m and "at least two non-parallel" in m for m in said), said

        monkeypatch.undo()
        np.random.seed(4)
        panda.on_generate_training()
        generated = dock.training_hash_display.text()
        assert generated
        _press_load(panda, generated)
        assert panda._exercise == generated
    finally:
        stop()
        panda.set_default_parameters()
