"""Compact-window checks on the real offscreen window and controller (PUMA).

Numbered as in the compact-window plan: 4, labels sit beside their fields;
5, nothing in the four form docks is clipped.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QLabel,  # noqa: E402
                               QPushButton, QToolButton)

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from gui import metrics  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402

FORM_DOCKS = ("instrument_dock", "sample_dock", "scattering_dock", "simulation_dock")
LAPTOP, MONITOR = (1108, 851), (2560, 1392)
GAP_TOLERANCE = 2  # px


@pytest.fixture(scope="module")
def window():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    _use_windows_ui_font(app)
    instrument = get_instrument("puma")
    # The default arrangement, not whatever layout an earlier test's window
    # saved into the session's temp config on close.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cm.TAVIMainWindow, "_restore_layout_from_file", lambda self: False)
        win = cm.TAVIMainWindow(
            instrument.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id=instrument.id, save_selection=lambda _id: None,
        )
    ctrl = cm.TAVIController(win, instrument, api_overrides={"disabled": True})
    win.show()  # offscreen: layouts only settle on a shown window
    app.processEvents()  # lets the startup geometry timer fire before any resize
    try:
        yield win
    finally:
        ctrl.shutdown()
        win.deleteLater()
        app.processEvents()
        app.setFont(font)


def _use_windows_ui_font(app):
    """Measure with the font the real window uses (Segoe UI 9 pt on Windows).

    The offscreen platform has no font database of its own; its fallback
    glyphs are about twice Segoe UI's width, which would fail check 5 on text
    that fits in the real window.
    """
    path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf")
    if sys.platform == "win32" and os.path.exists(path):
        if QFontDatabase.addApplicationFont(path) < 0:
            pytest.fail(f"could not load {path}")
        app.setFont(QFont("Segoe UI", 9))


def _resize(win, size):
    win.resize(*size)
    QApplication.processEvents()
    assert (win.width(), win.height()) == size


def _label_field_pairs(dock):
    """(label, field) for each one-column label directly left of a non-label widget.

    A label spanning several columns (a status line) is not a form label.
    """
    for grid in dock.findChildren(QGridLayout):
        for index in range(grid.count()):
            label = grid.itemAt(index).widget()
            if not isinstance(label, QLabel) or not label.isVisible():
                continue
            row, col, _rows, cols = grid.getItemPosition(index)
            right = grid.itemAtPosition(row, col + 1)
            field = right.widget() if right is not None else None
            if (cols == 1 and field is not None and not isinstance(field, QLabel)
                    and field.isVisible()):
                yield label, field


def test_labels_sit_beside_their_fields(window):
    """Check 4: from a label's text to its field is the metrics gap, not the dock's spare width."""
    _resize(window, MONITOR)
    seen, bad = 0, []
    for name in FORM_DOCKS:
        for label, field in _label_field_pairs(getattr(window, name)):
            seen += 1
            # The end of the label's drawn text, not of its widget, which
            # stretches with its grid column.
            text = label.style().itemTextRect(label.fontMetrics(), label.contentsRect(),
                                              label.alignment(), label.isEnabled(),
                                              label.text())
            label_right = label.mapTo(window, QPoint(text.x() + text.width(), 0)).x()
            gap = field.mapTo(window, QPoint(0, 0)).x() - label_right
            if not 0 <= gap <= metrics.LABEL_FIELD_GAP + GAP_TOLERANCE:
                bad.append(f"{name}: {label.text()!r} -> {type(field).__name__} "
                           f"{field.objectName()!r}: {gap} px")
    assert seen > 20, f"only {seen} label/field pairs found"
    assert not bad, f"{len(bad)} of {seen} pairs not beside their label:\n" + "\n".join(bad)


@pytest.mark.parametrize("size", [LAPTOP, MONITOR], ids=["1108x851", "2560x1392"])
def test_nothing_clipped(window, size):
    """Check 5: every visible text control is at least its size hint wide, or elided with a tooltip."""
    _resize(window, size)
    clipped = []
    for name in FORM_DOCKS:
        dock = getattr(window, name)
        for kind in (QLabel, QPushButton, QCheckBox, QToolButton):
            for widget in dock.findChildren(kind):
                if not widget.isVisible():
                    continue
                if isinstance(widget, QLabel) and widget.wordWrap():
                    continue  # wraps instead of clipping
                if widget.width() >= widget.sizeHint().width():
                    continue
                if "…" in widget.text() and widget.toolTip():
                    continue  # elided, full text in the tooltip
                clipped.append(f"{name}: {type(widget).__name__} {widget.text()!r} "
                               f"{widget.width()} < {widget.sizeHint().width()} px")
    assert not clipped, "\n".join(clipped)
