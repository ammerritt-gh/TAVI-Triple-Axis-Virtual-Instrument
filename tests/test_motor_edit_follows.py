"""A motor edit moves the position; a position edit moves the motors (PUMA, offscreen).

Reads every value from the dock fields the operator sees. The expected
position is the instrument's own forward kinematics at the motors as shown.
"""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402
from test_orientation_gui import _controller_for  # noqa: E402
from TAVI_PySide6 import format_editable_number  # noqa: E402
from instruments.tas_runtime import compute_scan_snapshot, describe_scan_error_flags  # noqa: E402
from tavi.neutron_conversions import energy2k, k2angle  # noqa: E402

TOL = 2e-3  # the dock shows 4 decimals; forward kinematics of the shown motors


@pytest.fixture
def ctrl():
    yield from _controller_for("puma")


def _num(edit):
    return float(edit.text() or 0)


def _type_and_finish(edit, value):
    edit.setText(format_editable_number(value))
    edit.editingFinished.emit()


def _forward(ctrl):
    """Q (qx, qy, qz) and deltaE from the motors as the dock shows them."""
    idock = ctrl.window.instrument_dock
    vals = ctrl.get_gui_values()
    q_vals, errors = ctrl.instrument_state.calculate_q_and_deltaE(
        _num(idock.mtt_edit), _num(idock.stt_edit), _num(idock.omega_edit),
        _num(idock.sgl_edit), _num(idock.att_edit),
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"],
        sgu=_num(idock.sgu_edit),
    )
    assert not errors, errors
    return q_vals


def _assert_follows_motors(ctrl):
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    qx, qy, qz, dE = _forward(ctrl)
    shown = [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit), _num(sdock.deltaE_edit)]
    assert shown == pytest.approx([qx, qy, qz, dE], abs=TOL)
    H, K, L = ctrl._sample_q_to_hkl(qx, qy, qz, ctrl.get_gui_values())
    assert [_num(sdock.H_edit), _num(sdock.K_edit), _num(sdock.L_edit)] == pytest.approx([H, K, L], abs=TOL)
    assert not idock.angles_stale_label.isVisibleTo(idock)


def test_a2_edit_moves_q_hkl_and_deltae(ctrl):
    _type_and_finish(ctrl.window.instrument_dock.mtt_edit, 60.0)
    _assert_follows_motors(ctrl)


def test_a6_edit_moves_q_hkl_and_deltae(ctrl):
    _type_and_finish(ctrl.window.instrument_dock.att_edit, 50.0)
    _assert_follows_motors(ctrl)


def test_ei_edit_moves_q_hkl_and_deltae(ctrl):
    _type_and_finish(ctrl.window.instrument_dock.Ei_edit, 20.0)
    _assert_follows_motors(ctrl)


def test_q_and_deltae_edits_still_move_the_motors(ctrl):
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    old_omega = _num(idock.omega_edit)
    # A Q that the motors reach: the forward kinematics at A3 + 5 deg.
    vals = ctrl.get_gui_values()
    target, errors = ctrl.instrument_state.calculate_q_and_deltaE(
        _num(idock.mtt_edit), _num(idock.stt_edit), old_omega + 5.0,
        _num(idock.sgl_edit), _num(idock.att_edit),
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"],
        sgu=_num(idock.sgu_edit),
    )
    assert not errors, errors
    for edit, value in zip((sdock.qx_edit, sdock.qy_edit, sdock.qz_edit), target[:3]):
        edit.setText(format_editable_number(value))
    sdock.qx_edit.editingFinished.emit()
    assert _num(idock.omega_edit) != pytest.approx(old_omega, abs=TOL)
    assert [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit)] == pytest.approx(
        list(target[:3]), abs=TOL)
    _assert_follows_motors(ctrl)

    # deltaE holds Q and re-solves the motors.
    held = [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit)]
    _type_and_finish(sdock.deltaE_edit, _num(sdock.deltaE_edit) + 0.5)
    assert [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit)] == pytest.approx(held, abs=TOL)
    _assert_follows_motors(ctrl)


def test_a2_edit_emits_one_reciprocal_snapshot_at_new_position(ctrl):
    sdock = ctrl.window.scattering_dock
    snapshots = []
    ctrl.reciprocal_state_changed.connect(snapshots.append)
    try:
        _type_and_finish(ctrl.window.instrument_dock.mtt_edit, 60.0)
        QTest.qWait(50)  # the coalesced single-shot snapshot timer
    finally:
        ctrl.reciprocal_state_changed.disconnect(snapshots.append)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert [snap["qx"], snap["qy"], snap["qz"]] == pytest.approx(
        [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit)], abs=1e-9)


def _kept(ctrl):
    """Every energy, wavevector and position field the dock shows, in a fixed order."""
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    edits = (idock.Ki_edit, idock.Ei_edit, idock.Kf_edit, idock.Ef_edit, sdock.fixed_E_edit,
             sdock.deltaE_edit, sdock.qx_edit, sdock.qy_edit, sdock.qz_edit,
             sdock.H_edit, sdock.K_edit, sdock.L_edit)
    return [_num(edit) for edit in edits]


ZERO_TAKE_OFFS = [("mtt_edit", 60.0, "Kf Fixed"), ("mtt_edit", 60.0, "Ki Fixed"),
                  ("att_edit", 50.0, "Kf Fixed"), ("att_edit", 50.0, "Ki Fixed")]


@pytest.mark.parametrize("edit,off_zero,mode", ZERO_TAKE_OFFS)
def test_a_single_zero_take_off_keeps_the_energies_and_the_position_and_says_why(ctrl, edit, off_zero, mode):
    """A crystal at exactly zero transmits and selects no energy: that side's energy and
    wavevector, the fixed energy, Q, HKL and the transfer keep their last values (never 0) under
    the stale mark, with a notice; moving the angle off zero derives forward again."""
    idock = ctrl.window.instrument_dock
    _, errors = ctrl.apply_parameters({"K_fixed": mode})
    assert not errors, errors
    before = _kept(ctrl)
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(getattr(idock, edit), 0.0)
    finally:
        ctrl.message_printed.disconnect(seen.append)
    assert _kept(ctrl) == pytest.approx(before, abs=1e-9)
    assert idock.angles_stale_label.isVisibleTo(idock)
    assert ctrl._angles_stale
    notice = [m for m in seen if "transmits" in m and "selects no energy" in m]
    assert notice, seen
    _type_and_finish(getattr(idock, edit), off_zero)
    assert not idock.angles_stale_label.isVisibleTo(idock)
    assert not ctrl._angles_stale
    _assert_follows_motors(ctrl)


def test_zero_take_off_of_both_crystals_leaves_q_and_says_why(ctrl):
    """Both crystals at exactly zero select no energy, so Q has no value at these motors: the
    fields keep the last position and the message center says why."""
    idock = ctrl.window.instrument_dock
    _type_and_finish(idock.mtt_edit, 0.0)
    before = _kept(ctrl)
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(idock.att_edit, 0.0)
    finally:
        ctrl.message_printed.disconnect(seen.append)
    assert _kept(ctrl) == pytest.approx(before, abs=1e-9)
    notice = [m for m in seen if "transmits" in m and "selects no energy" in m]
    assert notice, seen
    assert "still show the previous position" in notice[0]
    assert idock.angles_stale_label.isVisibleTo(idock)
    _type_and_finish(idock.mtt_edit, 60.0)
    _type_and_finish(idock.att_edit, 50.0)
    assert not idock.angles_stale_label.isVisibleTo(idock)
    assert not ctrl._angles_stale
    _assert_follows_motors(ctrl)


def test_a_zero_take_off_label_says_what_keeps_the_last_point(ctrl):
    idock = ctrl.window.instrument_dock
    _type_and_finish(idock.mtt_edit, 0.0)
    assert idock.angles_stale_label.isVisibleTo(idock)
    text = idock.angles_stale_label.text()
    assert "Angles above" not in text, text
    assert "Q, HKL and the energy transfer keep the last point" in text and "selects no energy" in text, text


@pytest.mark.parametrize("name,energy", [("A2", "incident_energy_mev"), ("A6", "final_energy_mev")])
def test_a_patched_zero_take_off_reports_no_zero_energy_and_no_q_from_a_zero_wavevector(ctrl, name, energy):
    before = ctrl.api_parameters()
    applied, errors = ctrl.apply_parameters({name: 0.0})
    assert not errors, errors
    state = ctrl.api_parameters()
    assert state[energy] == pytest.approx(before[energy]) and state[energy] != 0
    keys = ("q_instrument_x_inv_angstrom", "q_instrument_y_inv_angstrom", "q_instrument_z_inv_angstrom",
            "h", "k", "l", "energy_transfer_mev", "fixed_E")
    assert [state[k] for k in keys] == pytest.approx([before[k] for k in keys], abs=1e-9)
    assert ctrl._angles_stale


@pytest.mark.parametrize("edit,side,energy,wavevector", [
    ("mtt_edit", "mono", "Ei", "Ki"), ("att_edit", "ana", "Ef", "Kf")])
def test_a_gui_run_at_a_zero_take_off_records_that_energy_absent(ctrl, edit, side, energy, wavevector):
    """The Run button's launch (dock state, kept energies and all) runs the transmission path:
    that side's energy and wavevector are recorded absent, never the kept number and never 0."""
    _type_and_finish(getattr(ctrl.window.instrument_dock, edit), 0.0)
    ctrl.window.simulation_dock.scan_command_1_edit.setText("A4 20 22 1")
    launch = ctrl._collect_simulation_launch_state()
    # The launch's own numbers, as the API launch records them (they reach the parameters file).
    assert launch["vals"][energy] is None and launch["vals"][wavevector] is None
    plan, expansion = ctrl._compile_launch(launch)
    metadata = compute_scan_snapshot(plan, expansion.points[0], 0, launch["scan_config"],
                                     launch["vals"], "unused").metadata
    assert side in metadata["transmission"]
    assert metadata[energy] is None and metadata[wavevector] is None
    assert not ctrl.validate_scan_launch_state(launch)["infeasible"]   # the run's own feasibility check


def test_a_gui_run_refuses_a_zero_take_off_beside_a_scan_that_re_solves_the_crystals(ctrl, monkeypatch):
    """Run refuses what the API refuses: a zero A2 beside an H scan (the crystal angles are
    re-solved per point) never starts, while a direct-motor scan at the same zero still runs."""
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    submitted = []
    monkeypatch.setattr(ctrl, "submit_scan_job", lambda *a, **k: submitted.append(a))
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(ctrl.window.instrument_dock.mtt_edit, 0.0)
        sdock = ctrl.window.simulation_dock
        sdock.scan_command_1_edit.setText("H 1 2 0.5")
        ctrl.run_simulation_thread()
        assert submitted == [], seen
        assert any("re-solves" in m and "A2" in m for m in seen), seen
        sdock.scan_command_1_edit.setText("A4 20 22 1")
        ctrl.run_simulation_thread()
        assert len(submitted) == 1, seen
    finally:
        ctrl.message_printed.disconnect(seen.append)


def _equal_energy_mono_text(ctrl):
    """An A2 whose Ki equals the dock's fixed Kf bit for bit, as full-precision text."""
    vals = ctrl.get_gui_values()
    state = ctrl.instrument_state
    mono_info, _ = ctrl.instrument.crystal_info(vals["monocris"], vals["anacris"])
    angle = state.sense_mono * 2 * k2angle(energy2k(vals["fixed_E"]), mono_info["dm"])
    for step in range(-6, 7):
        candidate = angle
        for _ in range(abs(step)):
            candidate = math.nextafter(candidate, math.inf if step > 0 else -math.inf)
        _, flags = state.calculate_q_and_deltaE(
            candidate, 0.0, 0.0, 0.0, vals["att"], vals["fixed_E"], vals["K_fixed"],
            vals["monocris"], vals["anacris"], sgu=0.0)
        if flags:
            return repr(candidate)
    pytest.fail("no A2 within a few ulps gives exactly zero Q at A4 = 0")


def test_forward_scattering_records_zero_q_and_hkl_like_the_launch(ctrl):
    """A4 = 0 at equal incident and final energies is a position: Q = 0, HKL = (0, 0, 0)."""
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    if ctrl.get_gui_values()["K_fixed"] != "Kf Fixed":
        pytest.skip("the equal-energy A2 is built for the Kf-fixed default")
    idock.mtt_edit.setText(_equal_energy_mono_text(ctrl))
    idock.mtt_edit.editingFinished.emit()
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(idock.stt_edit, 0.0)
    finally:
        ctrl.message_printed.disconnect(seen.append)
    assert [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit)] == pytest.approx([0, 0, 0], abs=1e-12)
    assert [_num(sdock.H_edit), _num(sdock.K_edit), _num(sdock.L_edit)] == pytest.approx([0, 0, 0], abs=1e-9)
    assert _num(sdock.deltaE_edit) == pytest.approx(0.0, abs=1e-9)
    assert not idock.angles_stale_label.isVisibleTo(idock)
    assert any("forward scattering" in m for m in seen), seen
