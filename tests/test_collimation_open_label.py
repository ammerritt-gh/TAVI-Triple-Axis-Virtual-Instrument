"""Collimation reads as what is installed: a zero collimator shows as Open.

The visible text is display only; the stored value stays "0" (and the empty
set for PUMA's stacked alpha_2 with nothing checked). Real InstrumentDock,
offscreen Qt, no McStas.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
from gui.docks.base_dock import COLLIMATION_OPEN_TOOLTIP, collimation_label  # noqa: E402
from gui.docks.instrument_dock import InstrumentDock  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402

IDS = [info.id for info in available_instruments()]

# Held at module level so the application outlives every dock built below.
_APP = QApplication.instance() or QApplication([sys.argv[0]])


def _dock(instrument_id):
    return InstrumentDock(descriptor=get_instrument(instrument_id).descriptor())


def _open_label(dock, slot_id):
    row = next(iter(dock.collimation_widgets[slot_id].values())).parent()
    return next(w for w in row.findChildren(QLabel) if w.text() == "Open")


def test_all_four_instruments_are_covered():
    assert len(IDS) == 4


@pytest.mark.parametrize("instrument_id", IDS)
def test_texts_data_and_tooltips(instrument_id):
    dock = _dock(instrument_id)
    for slot in dock.descriptor.collimation:
        widget = dock.collimation_widgets[slot.id]
        if isinstance(widget, dict):
            pairs = [(value, check.text()) for value, check in widget.items()]
            assert all(c.toolTip() == COLLIMATION_OPEN_TOOLTIP for c in widget.values())
            assert _open_label(dock, slot.id).toolTip() == COLLIMATION_OPEN_TOOLTIP
        else:
            pairs = [(widget.itemData(i), widget.itemText(i)) for i in range(widget.count())]
            assert widget.toolTip() == COLLIMATION_OPEN_TOOLTIP
        assert [v for v, _ in pairs] == list(slot.allowed)
        for value, text in pairs:
            assert text == ("Open" if value == "0" else value + "'")


def test_puma_alpha_2_open_label_follows_checks():
    dock = _dock("puma")
    checks = dock.collimation_widgets["alpha_2"]
    label = _open_label(dock, "alpha_2")
    assert not label.isHidden()  # fresh dock: no box checked yet
    dock.set_collimation_values({})
    assert checks["40"].isChecked() and label.isHidden()  # descriptor default
    checks["40"].setChecked(False)
    assert not label.isHidden()
    assert dock.collimation_values()["alpha_2"] == set()
    checks["30"].setChecked(True)
    assert label.isHidden()
    dock.set_collimation_values({"alpha_2": set()})
    assert not label.isHidden()
    assert dock.collimation_values()["alpha_2"] == set()
    dock.set_collimation_values({"alpha_2": {"30", "60"}})
    assert label.isHidden()
    assert dock.collimation_values()["alpha_2"] == {"30", "60"}


def test_open_round_trips_as_zero_never_as_text():
    dock = _dock("in8")
    combo = dock.collimation_widgets["alpha_1"]
    dock.set_collimation_values({"alpha_1": "40"})
    assert combo.currentText() == "40'"
    assert dock.collimation_values()["alpha_1"] == "40"
    dock.set_collimation_values({"alpha_1": "0"})
    assert combo.currentText() == "Open"
    assert dock.collimation_values()["alpha_1"] == "0"
    dock.set_collimation_values({"alpha_1": "99"})  # unknown value: left alone
    assert dock.collimation_values()["alpha_1"] == "0"
    dock.set_collimation_values({"alpha_1": "40"})
    dock.set_collimation_values({})  # descriptor defaults
    assert dock.collimation_values()["alpha_1"] == "0"


def test_puma_defaults_restored():
    dock = _dock("puma")
    dock.set_collimation_values({"alpha_1": "0", "alpha_3": "60"})
    dock.set_collimation_values({})
    assert dock.collimation_values() == {
        "alpha_1": "40", "alpha_2": {"40"}, "alpha_3": "30", "alpha_4": "30"}


def test_label_helper_on_metadata_shapes():
    assert collimation_label("0") == "Open"
    assert collimation_label(0.0) == "Open"
    assert collimation_label("40") == "40'"
    assert collimation_label(40.0) == "40'"
    assert collimation_label("open") == "Open"
    assert collimation_label([30, 0, 60]) == "30'+60'"
    assert collimation_label([0, 0, 0]) == "Open"
    assert collimation_label("30'+40'") == "30'+40'"
