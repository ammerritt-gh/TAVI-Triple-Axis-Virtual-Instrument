"""Ledger entry 4: a scan entered only in command box 2 must preview like
the same text in command box 1.

``tavi.utilities.normalize_scan_commands`` is one extraction of the
lone-command-2 swap rule that already existed, written out identically,
at ``validate_scan_launch_state`` (API manifest expansion) and
``run_simulation`` (execution). This file pins the extracted helper's own
semantics and the headline preview/execution agreement it restores; the two
existing call sites' behavior is unchanged and covered by the existing
suite (see ``tests/test_relative_mode_swap.py`` for ``run_simulation``'s
swap, and ``tests/test_curvature_relative_scan_travel.py`` for
``validate_scan_launch_state``'s untouched 2-D and cmd1-only paths).
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
from tavi.utilities import normalize_scan_commands  # noqa: E402


# ---------------------------------------------------------------- unit level

def test_normalize_swaps_only_a_lone_command_2():
    """cmd2 non-empty, cmd1 empty: cmd2 is promoted to slot 1 and the two
    relative-mode flags move with it (the promoted command keeps ITS OWN
    relative setting, not command 1's)."""
    cmd1, cmd2, rel1, rel2 = normalize_scan_commands(
        "", "rva 1 1.2 0.1", False, True,
    )
    assert (cmd1, cmd2, rel1, rel2) == ("rva 1 1.2 0.1", "", True, False)


def test_normalize_empty2_marker_is_caller_chosen():
    """The vacated second slot takes whatever empty marker the caller
    supplies -- run_simulation needs ``None``, validate_scan_launch_state
    needs ``""``; this is the one place they differ."""
    _, cmd2_default, _, _ = normalize_scan_commands(
        "", "rva 1 1.2 0.1", False, False,
    )
    assert cmd2_default == ""

    _, cmd2_none, _, _ = normalize_scan_commands(
        "", "rva 1 1.2 0.1", False, False, empty2=None,
    )
    assert cmd2_none is None


def test_normalize_leaves_a_genuine_2d_pair_alone():
    cmd1, cmd2, rel1, rel2 = normalize_scan_commands(
        "H 1 2 0.5", "rva 1 1.2 0.1", True, True,
    )
    assert (cmd1, cmd2, rel1, rel2) == ("H 1 2 0.5", "rva 1 1.2 0.1", True, True)


def test_normalize_leaves_both_empty_alone():
    cmd1, cmd2, rel1, rel2 = normalize_scan_commands(
        "", "", False, False,
    )
    assert (cmd1, cmd2, rel1, rel2) == ("", "", False, False)


def test_normalize_leaves_a_lone_command_1_alone():
    cmd1, cmd2, rel1, rel2 = normalize_scan_commands(
        "rva 1 1.2 0.1", "", True, False,
    )
    assert (cmd1, cmd2, rel1, rel2) == ("rva 1 1.2 0.1", "", True, False)


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
