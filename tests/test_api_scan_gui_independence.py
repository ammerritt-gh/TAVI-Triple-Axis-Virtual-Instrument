"""GUI-independence of API scan submission (docs/API_SERVER_DESIGN.md sec 8).

POST /scan and POST /validate build their launch state from instrument defaults
overlaid with the request's ``parameters`` patch, reading NO live GUI widgets, so
text a human left in a scan-command widget can never poison an API scan and an
API scan never mutates the GUI. These tests instantiate the real controller with
an offscreen Qt platform (the API server disabled) and drive
``build_api_launch_state`` / ``_default_parameter_values`` directly -- the same
seam ``_submit_scan_on_gui`` / ``_validate_scan_on_gui`` use.
"""
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


@pytest.fixture(scope="module")
def controller():
    """A real TAVIController on an offscreen Qt platform, API server disabled."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    iid = infos[0].id
    instrument = get_instrument(iid)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=iid, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        del window
        del app


def test_defaults_key_set_matches_gui_values(controller):
    # The widget-free defaults dict must cover exactly get_gui_values()'s keys,
    # so overlaying a patch onto it produces a complete launch vals dict.
    assert set(controller._default_parameter_values().keys()) == \
        set(controller.get_gui_values().keys())


def test_scan_command2_widget_does_not_poison_api_scan(controller):
    # Headline regression: junk left in the scan_command_2 widget (never
    # submitted) must not bleed into an API scan that patches only command 1.
    controller.window.simulation_dock.scan_command_2_edit.setText("JUNK 9 9 9")
    launch = controller.build_api_launch_state(
        {"scan_command1": "H 1.9 2.1 0.01"}
    )
    assert launch["vals"]["scan_command1"] == "H 1.9 2.1 0.01"
    assert launch["vals"]["scan_command2"] == ""


def test_missing_scan_command_is_rejected(controller):
    # Defaults carry empty scan commands, so a patch with none is missing_required.
    with pytest.raises(cm.ApiError) as exc:
        controller.build_api_launch_state({})
    assert exc.value.code == "missing_required"
    with pytest.raises(cm.ApiError) as exc2:
        controller.build_api_launch_state({"scan_command1": "   "})
    assert exc2.value.code == "missing_required"


def test_hkl_patch_derives_matching_q(controller):
    # ISAR sends H/K/L and scans deltaE in momentum mode; the momentum-mode scan
    # template reads vals qx/qy/qz, so the HKL->Q derivation must match the
    # sample-mount solve under the (possibly adopted) lattice.
    launch = controller.build_api_launch_state(
        {"H": 1.0, "K": 1.0, "L": 0.0, "scan_command1": "deltaE 0 2 0.5"}
    )
    vals = launch["vals"]
    expected = controller._hkl_to_sample_q(1.0, 1.0, 0.0, vals)
    assert (vals["qx"], vals["qy"], vals["qz"]) == pytest.approx(expected)


def test_build_does_not_mutate_gui(controller):
    # Building an API launch state must leave every live widget untouched.
    before = controller.get_gui_values()
    controller.build_api_launch_state(
        {"H": 3.0, "scan_command1": "K -0.1 0.1 0.02"}
    )
    after = controller.get_gui_values()
    assert before == after


def test_invalid_patch_field_is_rejected(controller):
    with pytest.raises(cm.ApiError) as exc:
        controller.build_api_launch_state(
            {"scan_command1": "H 1.9 2.1 0.01", "Ei": "not-a-number"}
        )
    assert exc.value.code == "invalid_parameters"
    assert "Ei" in exc.value.details["errors"]
