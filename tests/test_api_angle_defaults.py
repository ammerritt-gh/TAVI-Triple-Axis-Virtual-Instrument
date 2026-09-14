"""API/GUI angle defaults must describe the active instrument, not PUMA's.

Covers audit entry 2 (docs/audits/release-1-3.md): the unpatched reference
state ``_default_parameter_values`` builds (and ``set_default_parameters``
mirrors for GUI startup) must be solved from the active instrument's own
geometry, not hard-coded PUMA literals.
"""
import math
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

INSTRUMENT_IDS = [info.id for info in available_instruments()]


@pytest.fixture()
def controller(instrument_id):
    """A real TAVIController on an offscreen Qt platform, API server disabled."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        del window


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_api_angle_defaults_match_instrument_branches(controller, instrument_id):
    plugin = get_instrument(instrument_id)
    geometry = plugin.descriptor().geometry
    ctrl = controller

    launch = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})
    vals = launch["vals"]

    actual = tuple(1 if vals[k] > 0 else -1 for k in ("mtt", "stt", "att"))
    expected = (int(geometry.sense_mono), int(geometry.sense_sample), int(geometry.sense_ana))
    assert actual == expected, (
        f"{instrument_id}: mtt/stt/att signs {actual}, expected {expected}"
    )

    validation = ctrl.validate_scan_launch_state(launch)
    assert validation["infeasible"] == []


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_api_angle_defaults_reconcile_with_default_energy(controller, instrument_id):
    ctrl = controller
    launch = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})
    vals = launch["vals"]

    # nominal_energies_from_angles reads monocris/anacris off the state it is
    # called on; the live GUI-tracked ctrl.instrument_state never carries them
    # (they stay live only on a throwaway state, same pattern
    # TAVI_PySide6.py's own validation path uses at ~4756).
    check_state = ctrl.instrument.default_state()
    check_state.monocris = vals['monocris']
    check_state.anacris = vals['anacris']
    Ei, Ef = check_state.nominal_energies_from_angles(vals['mtt'], vals['att'])
    assert Ei is not None and math.isclose(Ei, 14.7, abs_tol=1e-2)
    assert Ef is not None and math.isclose(Ef, 14.7, abs_tol=1e-2)


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_gui_startup_defaults_match_api_defaults(controller, instrument_id):
    ctrl = controller
    launch = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})
    api_vals = launch["vals"]

    gui_vals = ctrl.get_gui_values()
    assert math.isclose(gui_vals['mtt'], api_vals['mtt'], abs_tol=1e-3)
    assert math.isclose(gui_vals['att'], api_vals['att'], abs_tol=1e-3)
