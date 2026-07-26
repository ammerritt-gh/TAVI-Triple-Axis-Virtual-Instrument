"""Offscreen regressions for committed versus pending QLineEdit feedback."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


@pytest.fixture(scope="module")
def controller():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(infos[0].id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        del window


def _assert_committed(edit):
    """Let the accepted-change flash finish, then check its settled state."""
    QTest.qWait(500)
    assert edit.property("original_value") == edit.text()
    assert "#FF8C00" not in edit.styleSheet()


def test_apply_parameters_commits_direct_and_derived_fields(controller):
    applied, errors = controller.apply_parameters({"Ei": 20.0})

    assert applied == {"Ei": 20.0}
    assert errors == {}
    _assert_committed(controller.window.instrument_dock.Ei_edit)
    _assert_committed(controller.window.instrument_dock.Ki_edit)


def test_goto_and_revert_leave_the_field_committed(controller):
    edit = controller.window.scattering_dock.H_edit
    old = float(edit.text())

    ok, _message = controller.goto_scan_variable("H", old + 0.25, label="goto CEN")
    assert ok
    _assert_committed(edit)

    ok, _message = controller.revert_last_goto()
    assert ok
    _assert_committed(edit)
    assert float(edit.text()) == pytest.approx(old)


def test_restoring_defaults_does_not_leave_pending_fields(controller):
    controller.set_default_parameters()

    _assert_committed(controller.window.instrument_dock.Ei_edit)
    _assert_committed(controller.window.scattering_dock.H_edit)


def test_user_edit_during_saved_flash_remains_pending(controller):
    edit = controller.window.instrument_dock.Ei_edit
    applied, errors = controller.apply_parameters({"Ei": 20.0})
    assert applied == {"Ei": 20.0}
    assert errors == {}

    edit.setText("21")
    QTest.qWait(500)

    assert edit.property("original_value") == "20"
    assert edit.text() == "21"
    assert "#FF8C00" in edit.styleSheet()

    # Leave the shared controller fixture in a normally committed state.
    edit.editingFinished.emit()
    _assert_committed(edit)


def test_manual_edit_remains_pending_until_its_commit_event(controller):
    edit = controller.window.instrument_dock.Ei_edit
    original = edit.text()
    pending = "22" if original != "22" else "23"
    edit.setText(pending)

    assert edit.property("original_value") == original
    assert "#FF8C00" in edit.styleSheet()

    edit.editingFinished.emit()
    _assert_committed(edit)
