"""Compact-window checks on the real offscreen window and controller (PUMA).

Numbered as in the compact-window plan: 4, labels sit beside their fields;
5, nothing in the four form docks is clipped; 8, the menu routes that
replaced the Simulation dock's buttons are wired. Checks 4 and 5 run in both
View > Column Width settings, beside the block checks: each form group is
one block wide, Wide lays a wide dock out two-up in usage order, and the
setting is saved with the layout.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import SIGNAL, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QGroupBox,  # noqa: E402
                               QLabel, QMessageBox, QPushButton, QToolButton)

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from gui import metrics  # noqa: E402
from gui.docks.base_dock import NARROW, WIDE  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402

FORM_DOCKS = ("instrument_dock", "sample_dock", "scattering_dock", "simulation_dock")
LAPTOP, MONITOR = (1108, 851), (2560, 1392)
SIZES = pytest.mark.parametrize("size", [LAPTOP, MONITOR], ids=["1108x851", "2560x1392"])
MODES = pytest.mark.parametrize("mode", [NARROW, WIDE])
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
    win.controller = ctrl  # as main() does
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


def _resize(win, size, mode=None):
    win.resize(*size)
    QApplication.processEvents()
    assert (win.width(), win.height()) == size
    if mode is not None:
        win.column_width_actions[mode].trigger()  # as the View menu does
        for _ in range(3):  # the dock resize, then each panel's reflow
            QApplication.processEvents()


def _blocks(dock):
    """The dock's group boxes in usage order (the order the dock added them)."""
    return [block for block in dock._content_widget._blocks if block.isVisible()]


def _block_columns(dock):
    return sorted({block.x() for block in _blocks(dock)})


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


@MODES
def test_labels_sit_beside_their_fields(window, mode):
    """Check 4: from a label's text to its field is the metrics gap, not the dock's spare width."""
    _resize(window, MONITOR, mode)
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


@SIZES
@MODES
def test_nothing_clipped(window, size, mode):
    """Check 5: every visible text control is at least its size hint wide, or elided with a tooltip."""
    _resize(window, size, mode)
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


@pytest.mark.parametrize("action", ["save_parameters_action", "load_parameters_action",
                                    "clear_runtimes_action"])
def test_menu_routes_are_wired(window, action):
    """Check 8: the File/Config actions replacing the dock buttons reach a handler.

    Load Defaults is exercised end to end by test_orientation_gui.py. The
    handlers are bound at construction, so this counts receivers rather than
    monkeypatching the controller afterwards.
    """
    assert getattr(window, action).receivers(SIGNAL("triggered(bool)")) >= 1
    dock = window.simulation_dock
    for removed in ("quit_button", "clear_runtimes_button", "save_button",
                    "load_button", "defaults_button"):
        assert not hasattr(dock, removed), removed


@SIZES
@MODES
def test_blocks_fit_without_horizontal_scroll(window, size, mode):
    """No form dock scrolls sideways or cuts a block off; no block is wider than one block."""
    _resize(window, size, mode)
    bad = []
    for name in FORM_DOCKS:
        dock = getattr(window, name)
        scroll = dock._scroll_area
        if scroll.horizontalScrollBar().isVisible():
            bad.append(f"{name}: horizontal scrollbar")
        viewport = scroll.viewport()
        for block in _blocks(dock):
            right = block.mapTo(viewport, QPoint(block.width(), 0)).x()
            if block.width() > metrics.BLOCK_WIDTH or right > viewport.width():
                bad.append(f"{name}: {block.title()!r} {block.width()} px wide, "
                           f"right edge {right} of {viewport.width()}")
    assert not bad, "\n".join(bad)


def test_wide_lays_blocks_two_up_in_usage_order(window):
    """Wide at 2560x1392: down the left column, then the right; Narrow: one column."""
    dock = window.instrument_dock
    _resize(window, MONITOR, WIDE)
    columns = _block_columns(dock)
    assert len(columns) == 2, columns
    placed = sorted(_blocks(dock), key=lambda block: (block.x(), block.y()))
    assert placed == _blocks(dock), [block.title() for block in placed]
    _resize(window, MONITOR, NARROW)
    assert len(_block_columns(dock)) == 1
    assert dock.width() == dock.width_for_blocks(1)  # the plot got the rest


def test_wide_falls_back_to_one_column_when_narrow(window):
    """Wide, with the dock dragged narrower than two blocks, gives one column."""
    dock = window.instrument_dock
    _resize(window, MONITOR, WIDE)
    assert len(_block_columns(dock)) == 2
    narrower = dock.width_for_blocks(2) - 2 * metrics.BLOCK_REFLOW_HYSTERESIS
    window.resizeDocks([dock, window.scattering_dock], [narrower, narrower], Qt.Horizontal)
    QApplication.processEvents()
    assert dock.width() < dock.width_for_blocks(2)
    assert len(_block_columns(dock)) == 1


def test_column_width_saved_with_the_layout(window, tmp_path, monkeypatch):
    """Save then restore round-trips column_width; missing or unknown reads as Narrow."""
    path = tmp_path / "view_layout.json"
    monkeypatch.setattr(window, "_get_layout_config_path", lambda: str(path))
    try:
        window.set_column_width(WIDE, fit=False)
        assert window.save_layout_to_file()
        assert json.loads(path.read_text(encoding="utf-8"))["column_width"] == WIDE
        window.set_column_width(NARROW, fit=False)
        assert window._restore_layout_from_file()
        assert window._column_width == WIDE
        for stored in ({}, {"column_width": "huge"}):
            path.write_text(json.dumps({"layout_version": 2, **stored}), encoding="utf-8")
            assert window._restore_layout_from_file()
            assert window._column_width == NARROW, stored
    finally:
        window.set_column_width(NARROW, fit=False)


@pytest.mark.parametrize("instrument_id", ["puma", "in8", "in12", "panda"])
def test_every_group_fits_one_block(instrument_id):
    """Each form-dock group box, as each instrument's descriptor builds it, fits one block."""
    from gui.docks.instrument_dock import InstrumentDock
    from gui.docks.unified_sample_dock import UnifiedSampleDock
    from gui.docks.unified_scattering_dock import UnifiedScatteringDock
    from gui.docks.unified_simulation_dock import UnifiedSimulationDock

    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    _use_windows_ui_font(app)
    descriptor = get_instrument(instrument_id).descriptor()
    docks = [InstrumentDock(descriptor=descriptor), UnifiedSampleDock(descriptor=descriptor),
             UnifiedScatteringDock(), UnifiedSimulationDock()]
    try:
        wide = []
        for dock in docks:
            dock.show()  # sizes settle on a polished widget
            app.processEvents()
            for box in dock.findChildren(QGroupBox):
                if box.isVisible() and box.sizeHint().width() > metrics.BLOCK_WIDTH:
                    wide.append(f"{type(dock).__name__}: {box.title()!r} "
                                f"{box.sizeHint().width()} px")
        assert not wide, f"wider than {metrics.BLOCK_WIDTH} px:\n" + "\n".join(wide)
    finally:
        for dock in docks:
            dock.deleteLater()
        app.processEvents()
        app.setFont(font)


def test_scattering_point_is_q_beside_hkl(window):
    """Q left, HKL right on level rows, ΔE below, Fixed Mode its own block; Tab runs Q, HKL, ΔE, mode."""
    _resize(window, MONITOR, NARROW)
    dock = window.scattering_dock

    def at(widget):
        return widget.mapTo(window, QPoint(0, 0))

    for q, hkl in ((dock.qx_edit, dock.H_edit), (dock.qy_edit, dock.K_edit),
                   (dock.qz_edit, dock.L_edit)):
        assert at(q).y() == at(hkl).y() and at(q).x() < at(hkl).x()
    assert at(dock.deltaE_edit).y() > at(dock.qz_edit).y()
    point, fixed = _blocks(dock)
    assert point.isAncestorOf(dock.deltaE_edit) and not point.isAncestorOf(dock.K_fixed_combo)
    assert fixed.isAncestorOf(dock.K_fixed_combo) and fixed.isAncestorOf(dock.fixed_E_edit)
    chain = [dock.qx_edit, dock.qy_edit, dock.qz_edit, dock.H_edit, dock.K_edit,
             dock.L_edit, dock.deltaE_edit, dock.K_fixed_combo, dock.fixed_E_edit]
    seen, widget = [], dock.qx_edit
    while len(seen) < len(chain):
        if widget in chain:
            seen.append(widget)
        widget = widget.nextInFocusChain()
        assert widget is not dock.qx_edit, "focus chain closed early"
    assert seen == chain


def test_clear_runtime_data_keeps_other_instruments(window, monkeypatch):
    """Clear Runtime Data deletes only the current instrument's records, and says which."""
    ctrl = window.controller
    tracker = ctrl.runtime_tracker
    tracker.add_record("puma", 5, 10000, 20.0, 2.0, 28.0)
    tracker.add_record("in8", 5, 10000, 20.0, 2.0, 28.0)
    asked = []

    def answer_yes(_parent, _title, text, *_rest):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", answer_yes)
    window.clear_runtimes_action.trigger()
    assert ctrl.instrument.display_name in asked[0]
    assert tracker.get_record_count("puma") == 0
    assert tracker.get_record_count("in8") >= 1
