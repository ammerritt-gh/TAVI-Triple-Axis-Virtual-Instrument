"""Offscreen tests for the Diagnostic Configuration energy/wavelength choice (u2).

The choice is one bool in the diagnostic settings. The E_monitor checkboxes
follow it in their text only; they stay keyed by monitor id.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from gui.dialogs.diagnostic_config_dialog import DiagnosticConfigDialog  # noqa: E402
from instruments.puma.plugin import _PUMA_MONITORS  # noqa: E402
from tavi.instrument_helpers import WAVELENGTH_MONITORS_KEY  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    yield app


def _button(dialog, text):
    return next(b for b in dialog.findChildren(QPushButton) if b.text() == text)


def test_default_is_energy_and_key_is_false(qapp):
    dialog = DiagnosticConfigDialog(monitors=_PUMA_MONITORS)
    try:
        assert dialog.energy_radio.isChecked()
        assert not dialog.wavelength_radio.isChecked()
        assert dialog.checkboxes["Source EMonitor"].text() == "Source EMonitor"
        assert dialog.get_settings()[WAVELENGTH_MONITORS_KEY] is False
    finally:
        dialog.close()


def test_wavelength_relabels_e_monitors_and_keeps_keys(qapp):
    dialog = DiagnosticConfigDialog(monitors=_PUMA_MONITORS)
    try:
        dialog.checkboxes["Source EMonitor"].setChecked(True)
        dialog.checkboxes["Source PSD"].setChecked(True)
        before = dialog.get_settings()

        dialog.wavelength_radio.setChecked(True)
        assert dialog.checkboxes["Source EMonitor"].text() == "Source LMonitor"
        assert dialog.checkboxes["Premono Emonitor"].text() == "Premono LMonitor"
        assert dialog.checkboxes["Post-analyzer EMonitor"].text() == "Post-analyzer LMonitor"
        assert dialog.checkboxes["Source PSD"].text() == "Source PSD"
        assert dialog.checkboxes["Source DSD"].text() == "Source DSD"
        for monitor in _PUMA_MONITORS:
            if monitor.component_type != "E_monitor":
                assert dialog.checkboxes[monitor.id].text() == monitor.id

        after = dialog.get_settings()
        assert after[WAVELENGTH_MONITORS_KEY] is True
        del after[WAVELENGTH_MONITORS_KEY], before[WAVELENGTH_MONITORS_KEY]
        assert after == before
        assert after["Source EMonitor"] is True and after["Source PSD"] is True

        dialog.energy_radio.setChecked(True)
        assert dialog.checkboxes["Source EMonitor"].text() == "Source EMonitor"
    finally:
        dialog.close()


def test_quick_selection_buttons_leave_choice_alone(qapp):
    dialog = DiagnosticConfigDialog(monitors=_PUMA_MONITORS)
    try:
        dialog.wavelength_radio.setChecked(True)

        _button(dialog, "Select All Monitors").click()
        assert all(dialog.checkboxes[m.id].isChecked() for m in _PUMA_MONITORS)
        assert dialog.wavelength_radio.isChecked()

        _button(dialog, "Deselect All Monitors").click()
        assert not any(dialog.checkboxes[m.id].isChecked() for m in _PUMA_MONITORS)
        assert dialog.wavelength_radio.isChecked()

        for button in dialog.findChildren(QPushButton):
            if button.text().endswith(" Only"):
                button.click()
        assert dialog.wavelength_radio.isChecked()
        assert not dialog.energy_radio.isChecked()
        assert dialog.checkboxes["Source EMonitor"].text() == "Source LMonitor"
    finally:
        dialog.close()


def test_reopened_dialog_shows_saved_choice(qapp):
    first = DiagnosticConfigDialog(monitors=_PUMA_MONITORS)
    try:
        first.checkboxes["Source EMonitor"].setChecked(True)
        first.wavelength_radio.setChecked(True)
        saved = first.get_settings()
    finally:
        first.close()

    reopened = DiagnosticConfigDialog(current_settings=saved, monitors=_PUMA_MONITORS)
    try:
        assert reopened.wavelength_radio.isChecked()
        assert not reopened.energy_radio.isChecked()
        assert reopened.checkboxes["Source EMonitor"].isChecked()
        assert reopened.checkboxes["Source EMonitor"].text() == "Source LMonitor"
    finally:
        reopened.close()


def test_default_settings_choose_energy():
    defaults = DiagnosticConfigDialog.get_default_settings(_PUMA_MONITORS)
    assert defaults[WAVELENGTH_MONITORS_KEY] is False


def test_tooltip_and_legend(qapp):
    dialog = DiagnosticConfigDialog(monitors=_PUMA_MONITORS)
    try:
        tip = dialog.wavelength_radio.toolTip()
        assert "λ" in tip and "wavelength" in tip
        assert dialog.energy_radio.toolTip() == tip
        legend = [w.text() for w in dialog.findChildren(QLabel)
                  if "EMonitor: Energy Monitor" in w.text()]
        assert legend and "LMonitor: Wavelength Monitor" in legend[0]
    finally:
        dialog.close()
