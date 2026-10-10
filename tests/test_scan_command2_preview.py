"""Ledger entry 4: a scan entered only in command box 2 must preview like
the same text in command box 1.

The point plan keeps a lone command 2 as the scan's only axis
(``instruments.rules.expand``; ``tests/test_rules.py`` and
``tests/test_relative_mode_swap.py`` pin it); this pins the preview label.
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


# ------------------------------------------------------------- widget level

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


def test_a_scan_entered_only_in_command_box_2_previews_like_command_box_1():
    """On IN8: 'rva 1 1.2 0.1' in box 2 alone must produce IDENTICAL preview
    text to the same command in box 1, and it must take the one-dimensional
    label form (not 'N x M') -- ledger entry 4's headline failure."""
    with _controller("in8") as ctrl:
        dock = ctrl.window.simulation_dock

        dock.scan_command_1_edit.setText("rva 1 1.2 0.1")
        dock.scan_command_2_edit.setText("")
        ctrl._update_scan_estimates()
        label_cmd1 = dock.point_count_label.text()

        dock.scan_command_1_edit.setText("")
        dock.scan_command_2_edit.setText("rva 1 1.2 0.1")
        ctrl._update_scan_estimates()
        label_cmd2 = dock.point_count_label.text()

        assert label_cmd2 == label_cmd1
        assert "×" not in label_cmd2
        assert label_cmd2 == "3 points (3 valid / 0 invalid)"
