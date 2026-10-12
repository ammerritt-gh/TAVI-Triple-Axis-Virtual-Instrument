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

import instruments.builtin  # noqa: F401,E402
from test_orientation_gui import _controller_for  # noqa: E402
from TAVI_PySide6 import format_editable_number  # noqa: E402
from instruments.tas_runtime import describe_scan_error_flags  # noqa: E402
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


def test_zero_take_off_leaves_q_and_says_why(ctrl):
    """Both crystals at exactly zero select no energy, so Q has no value at
    these motors: the fields keep the last position and the message center
    says so. A2 alone still has a Q (only the analyzer side is lost)."""
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    _type_and_finish(idock.mtt_edit, 0.0)
    before = [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit),
              _num(sdock.H_edit), _num(sdock.K_edit), _num(sdock.L_edit)]
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(idock.att_edit, 0.0)
    finally:
        ctrl.message_printed.disconnect(seen.append)

    vals = ctrl.get_gui_values()
    _, errors = ctrl.instrument_state.calculate_q_and_deltaE(
        _num(idock.mtt_edit), _num(idock.stt_edit), _num(idock.omega_edit),
        _num(idock.sgl_edit), _num(idock.att_edit),
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"],
        sgu=_num(idock.sgu_edit),
    )
    assert errors, "precondition: A2 = A6 = 0 must raise an error flag"
    notice = [m for m in seen if "cannot follow these motors" in m]
    assert notice, seen
    assert describe_scan_error_flags(errors) in notice[0]
    assert "still show the previous position" in notice[0]
    assert [_num(sdock.qx_edit), _num(sdock.qy_edit), _num(sdock.qz_edit),
            _num(sdock.H_edit), _num(sdock.K_edit), _num(sdock.L_edit)] == pytest.approx(
        before, abs=TOL)


def test_zero_take_off_marks_the_position_stale_and_clears_on_the_next_edit(ctrl):
    """The motors define no Q at A2 = A6 = 0: the Q/HKL fields keep the last point under the
    same stale mark a typed Q the stage cannot reach gets, and the next good motor edit clears it."""
    idock, sdock = ctrl.window.instrument_dock, ctrl.window.scattering_dock
    _type_and_finish(idock.mtt_edit, 0.0)
    seen = []
    ctrl.message_printed.connect(seen.append)
    try:
        _type_and_finish(idock.att_edit, 0.0)
    finally:
        ctrl.message_printed.disconnect(seen.append)
    assert idock.angles_stale_label.isVisibleTo(idock)
    assert ctrl._angles_stale
    assert any("cannot follow these motors" in m for m in seen), seen
    _type_and_finish(idock.mtt_edit, 60.0)
    _type_and_finish(idock.att_edit, 50.0)
    assert not idock.angles_stale_label.isVisibleTo(idock)
    assert not ctrl._angles_stale
    _assert_follows_motors(ctrl)


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
