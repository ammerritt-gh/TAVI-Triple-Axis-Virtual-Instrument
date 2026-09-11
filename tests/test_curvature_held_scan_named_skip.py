"""D21: a HELD-curvature refusal must not fire on an axis the scan command
itself names.

``_held_curvature_issues`` (GUI) and ``build_api_launch_state``'s HELD loop
(API) both used to check a HELD radius's CURRENT value against travel before
noticing that a non-empty scan command is about to promote that same axis
to SCANNED -- so an unlocked PUMA rhm field/patch at 1.0 (below the 2.0 m
minimum) plus a legal absolute "rhm 3.0 4.0 0.5" was refused for a value the
scan never actually uses. Both now skip any axis
``_scan_named_curvature_axes`` finds in a non-empty scan command -- one
predicate, shared, not a rule enforced on one side and not its twin.
"""
import contextlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


# PUMA declares rhm min_radius_m = 2.0.


def test_gui_unlocked_out_of_travel_field_is_not_refused_when_the_scan_names_it():
    """rhm field at 1.0 (below the 2.0 m minimum), Ideal lock off (HELD),
    but the scan command names rhm -- ``_preflight_scan_validation`` must
    not hard-block on the stale HELD value."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(ana)
        idock.rhm_edit.setText("1.0")
        assert ctrl.is_bending_locked("rhm") is False

        sdock = ctrl.window.simulation_dock
        sdock.scan_command_1_edit.setText("rhm 3.0 4.0 0.5")
        sdock.scan_command_2_edit.setText("")

        hard, _ = ctrl._preflight_scan_validation()
        assert hard == [], (
            f"a scan naming rhm must not be refused for the stale HELD "
            f"field value it is about to override: {hard}"
        )


def test_gui_the_skip_does_not_open_a_hole_for_a_scan_actually_out_of_travel():
    """Same setup, but the scan range ITSELF is out of travel -- the skip on
    the HELD check must not hide that; ``_scan_command_issues`` (the range
    check) still refuses it."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(ana)
        idock.rhm_edit.setText("1.0")

        sdock = ctrl.window.simulation_dock
        sdock.scan_command_1_edit.setText("rhm 1.0 1.5 0.5")
        sdock.scan_command_2_edit.setText("")

        hard, _ = ctrl._preflight_scan_validation()
        assert hard, "an out-of-travel scan range must still be refused"
        assert "rhm" in hard[0]


def test_api_held_rhm_with_a_scan_naming_it_is_accepted():
    """A patched rhm=1.0 alongside a legal absolute scan naming rhm must not
    be refused for the value the scan overrides at every point."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rhm": 1.0,
            "scan_command1": "rhm 3.0 4.0 0.5",
        })
        assert launch["vals"]["rhm"] == 1.0


def test_api_held_rhm_without_a_scan_naming_it_is_refused_as_today():
    """The same patched rhm=1.0 with an unrelated scan command must still be
    refused -- the skip is scoped to axes the scan actually names, not a
    blanket exemption."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        with pytest.raises(cm.ApiError) as excinfo:
            ctrl.build_api_launch_state({
                "monocris": mono, "anacris": ana,
                "rhm": 1.0,
                "scan_command1": "deltaE 0 1 0.5",
            })
        assert excinfo.value.status == 400
        assert excinfo.value.code == "curvature_out_of_travel"
        assert "rhm" in excinfo.value.message
