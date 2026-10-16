"""PANDA's new GUI surfaces: the Velocity selector toggle and the 21-monitor list.

Real InstrumentDock and DiagnosticConfigDialog, offscreen Qt, nothing shown,
no McStas.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
from gui.dialogs.diagnostic_config_dialog import DiagnosticConfigDialog  # noqa: E402
from gui.docks.instrument_dock import InstrumentDock  # noqa: E402
from instruments.panda.plugin import panda_descriptor  # noqa: E402
from instruments.registry import get_instrument  # noqa: E402

# Held at module level so the application outlives every widget built below.
_APP = QApplication.instance() or QApplication([sys.argv[0]])


def test_velocity_selector_toggle_is_on_the_panda_dock_unchecked():
    dock = InstrumentDock(descriptor=get_instrument("panda").descriptor())
    toggle = dock.module_widgets["v_selector"]
    assert isinstance(toggle, QCheckBox)
    assert toggle.text() == "Velocity selector"
    assert toggle.isChecked() is False


def test_diagnostic_dialog_lists_all_21_panda_monitors():
    monitors = panda_descriptor().monitors
    ids = [monitor.id for monitor in monitors]
    assert len(ids) == 21
    dialog = DiagnosticConfigDialog(monitors=monitors)
    assert dialog.monitor_ids == ids
    assert set(dialog.checkboxes) >= set(ids)
    for monitor_id in ids:
        assert dialog.checkboxes[monitor_id].text() == monitor_id
    group = next(g for g in dialog.findChildren(QGroupBox) if g.title() == "Detector Monitors")
    assert len(group.findChildren(QCheckBox)) == len(ids)
