"""Energy-derived GUI angle writers must use the instrument's signed sense.

Covers audit entry 1 (docs/audits/release-1-3.md): editing Ei/Ef/Ki/Kf must
write mono/analyser two-theta on the same signed branch the runtime uses
(instruments/tas_runtime.py calculate_angles), and the inverse mtt/att
handlers must recover a positive Ki/Kf from that signed angle.
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
def test_energy_edits_write_signed_crystal_angle(controller, instrument_id):
    plugin = get_instrument(instrument_id)
    geometry = plugin.descriptor().geometry
    ctrl = controller

    cases = [
        ("Ei", "mtt", int(geometry.sense_mono), lambda: ctrl.monocris_info['dm']),
        ("Ef", "att", int(geometry.sense_ana), lambda: ctrl.anacris_info['da']),
        ("Ki", "mtt", int(geometry.sense_mono), lambda: ctrl.monocris_info['dm']),
        ("Kf", "att", int(geometry.sense_ana), lambda: ctrl.anacris_info['da']),
    ]
    for field, angle_field, sense, d_spacing in cases:
        ctrl.update_angles_from_q()
        edit = getattr(ctrl.window.instrument_dock, field + "_edit")
        if field in ("Ki", "Kf"):
            text = cm.format_editable_number(energy2k(12))
        else:
            text = "12"
        edit.setText(text)
        edit.editingFinished.emit()

        vals = ctrl.get_gui_values()
        actual = vals[angle_field]
        k = energy2k(12)
        expected = sense * 2 * k2angle(k, d_spacing())
        assert math.isclose(actual, expected, abs_tol=1e-3), (
            f"{instrument_id} {field}=12: {angle_field}={actual}, expected {expected}"
        )


@pytest.mark.parametrize("instrument_id", INSTRUMENT_IDS)
def test_signed_angle_edits_recover_positive_k(controller, instrument_id):
    plugin = get_instrument(instrument_id)
    geometry = plugin.descriptor().geometry
    ctrl = controller

    cases = [
        ("mtt", int(geometry.sense_mono), lambda: ctrl.monocris_info['dm'], "Ki", "Ei"),
        ("att", int(geometry.sense_ana), lambda: ctrl.anacris_info['da'], "Kf", "Ef"),
    ]
    for angle_field, sense, d_spacing, k_field, e_field in cases:
        ctrl.update_angles_from_q()
        k = energy2k(12)
        signed_angle = sense * 2 * k2angle(k, d_spacing())

        edit = getattr(ctrl.window.instrument_dock, angle_field + "_edit")
        # Force a value different from what's currently shown so the
        # changed-guard (_field_value_changed) actually fires.
        edit.setText(cm.format_editable_number(signed_angle + 1.0))
        edit.editingFinished.emit()
        edit.setText(cm.format_editable_number(signed_angle))
        edit.editingFinished.emit()

        vals = ctrl.get_gui_values()
        assert vals[k_field] > 0, (
            f"{instrument_id} {angle_field}={signed_angle}: {k_field}={vals[k_field]} is not positive"
        )
        assert math.isclose(vals[e_field], 12, abs_tol=1e-3), (
            f"{instrument_id} {angle_field}={signed_angle}: {e_field}={vals[e_field]}, expected 12"
        )
