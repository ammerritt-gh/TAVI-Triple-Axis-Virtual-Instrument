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
from tavi.neutron_conversions import energy2k, k2angle  # noqa: E402

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

    # Establish fresh defaults explicitly: construction restores the
    # operator's saved config/parameters.json (untracked local state) and
    # then refreshes mtt/att through the crystal-info updates, so reading
    # the widgets as constructed would neither isolate this test from a
    # saved state nor prove the startup writer itself. All four angles are
    # compared, the sample ones included.
    ctrl.set_default_parameters()
    gui_vals = ctrl.get_gui_values()
    for key in ("mtt", "stt", "omega", "att"):
        assert math.isclose(gui_vals[key], api_vals[key], abs_tol=1e-3), (
            f"{instrument_id} startup {key}={gui_vals[key]}, API default {api_vals[key]}"
        )


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_api_energy_patch_rederives_signed_crystal_angle(controller, instrument_id):
    """The API twin of the GUI energy handlers: a patched Ei/Ef moves its own
    crystal onto the instrument's signed branch; an explicit angle wins."""
    plugin = get_instrument(instrument_id)
    geometry = plugin.descriptor().geometry
    ctrl = controller
    default = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})["vals"]
    # The launch state's own crystals, not the live GUI selection: a saved
    # parameters.json may have another crystal selected.
    mono_info, ana_info = ctrl.instrument.crystal_info(default['monocris'], default['anacris'])
    dm, da = mono_info['dm'], ana_info['da']

    vals = ctrl.build_api_launch_state({"Ei": 12, "scan_command1": "A3 35 36 1"})["vals"]
    expected = int(geometry.sense_mono) * 2 * k2angle(energy2k(12), dm)
    assert math.isclose(vals['mtt'], expected, abs_tol=1e-3), (instrument_id, vals['mtt'], expected)
    assert math.isclose(vals['att'], default['att'], abs_tol=1e-6)

    vals = ctrl.build_api_launch_state({"Ef": 12, "scan_command1": "A3 35 36 1"})["vals"]
    expected = int(geometry.sense_ana) * 2 * k2angle(energy2k(12), da)
    assert math.isclose(vals['att'], expected, abs_tol=1e-3), (instrument_id, vals['att'], expected)
    assert math.isclose(vals['mtt'], default['mtt'], abs_tol=1e-6)

    vals = ctrl.build_api_launch_state({"Ei": 12, "mtt": 33.0, "scan_command1": "A3 35 36 1"})["vals"]
    assert vals['mtt'] == 33.0

    # A patched fixed energy moves BOTH sides (deltaE=0 in the defaults, so
    # Ei = Ef = 12) and therefore both crystal angles, as in the GUI.
    vals = ctrl.build_api_launch_state({"fixed_E": 12, "scan_command1": "A3 35 36 1"})["vals"]
    assert math.isclose(vals['Ei'], 12, abs_tol=1e-9) and math.isclose(vals['Ef'], 12, abs_tol=1e-9)
    assert math.isclose(vals['mtt'], int(geometry.sense_mono) * 2 * k2angle(energy2k(12), dm), abs_tol=1e-3)
    assert math.isclose(vals['att'], int(geometry.sense_ana) * 2 * k2angle(energy2k(12), da), abs_tol=1e-3)

