"""Compact-window checks on the real offscreen window and controller (PUMA).

Numbered as in the compact-window plan: 1, the first-start layout pick;
2, each View > Layout preset places every dock; 3, the 2-column work surface
is on screen at the laptop size; 4, labels sit beside their fields (in 4
columns); 5, nothing in the four form docks is clipped; 6, the layout file:
round trip, the version set-aside, bad files and lost docks; 7, the Instrument
blocks run in usage order and the folded ones summarise their fields; 8, the
menu routes that replaced the Simulation dock's buttons are wired. Checks 4
and 5 run in both View > Column Width settings, beside the block checks: each
form group is one block wide, Wide lays a wide dock out two-up in usage order,
and the setting is saved with the layout. No preset switch may leave a stray
tab strip painted in the window.
"""
import json
import os
import sys
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import SIGNAL, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,  # noqa: E402
                               QGroupBox, QLabel, QMessageBox, QPushButton, QTabBar,
                               QToolButton)

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
INSTRUMENTS = ["puma", "in8", "in12", "panda"]
# Plan check 7: the Instrument blocks in usage order. Collimations, Slits and
# Modules appear only where the descriptor declares them.
INSTRUMENT_ORDER = ["Instrument Angles", "Energies and Wave Vectors", "Collimations",
                    "Slit Apertures (mm)", "Monochromator and Analyzer Crystals",
                    "Crystal Focusing (Absolute Radii, m)", "Experimental Modules",
                    "Source Control"]


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


def _trigger(action):
    action.trigger()  # as the View menu does
    for _ in range(3):  # the dock resize, then each panel's reflow
        QApplication.processEvents()


def _resize(win, size, mode=None, columns=None):
    """Window at ``size``; then View > Column Width ``mode`` and View > Layout ``columns``.

    The preset is applied first too, so the previous one's minimum cannot hold
    the window open; one that cannot fit ``size`` (4 columns need about 1140 px)
    grows the window to its minimum, as Qt does on screen.
    """
    if columns is not None:
        _trigger(win.layout_actions[columns])
    win.resize(*size)
    QApplication.processEvents()
    assert (win.width(), win.height()) == size or win.minimumSizeHint().width() > size[0]
    if mode is not None:
        _trigger(win.column_width_actions[mode])
    if columns is not None:
        _trigger(win.layout_actions[columns])  # sized at this window size


PLACED = ("instrument_dock", "sample_dock", "scattering_dock", "simulation_dock",
          "display_dock", "output_dock", "data_control_dock", "fitting_dock", "api_dock")
# Each preset's columns, left to right, each listed top to bottom; and the
# docks tabbed behind another (primary first in each group).
PRESET_COLUMNS = {
    2: [["instrument_dock", "scattering_dock"], ["display_dock", "simulation_dock"]],
    3: [["instrument_dock", "scattering_dock", "simulation_dock"],
        ["sample_dock", "ub_matrix_dock"],
        ["display_dock", "output_dock", "data_control_dock"]],
    4: [["instrument_dock"], ["sample_dock"], ["scattering_dock", "simulation_dock"],
        ["display_dock", "output_dock"]],
}
PRESET_TABS = {
    2: [["scattering_dock", "sample_dock"],
        ["instrument_dock", "output_dock", "data_control_dock", "fitting_dock", "api_dock"]],
    3: [["data_control_dock", "api_dock", "fitting_dock"]],
    4: [["output_dock", "data_control_dock", "fitting_dock", "api_dock"]],
}


def _tab_strips(win):
    """The tab strips painted inside the window, as the sets of their tab titles."""
    return Counter(frozenset(bar.tabText(i) for i in range(bar.count()))
                   for bar in win.findChildren(QTabBar, options=Qt.FindDirectChildrenOnly)
                   if bar.isVisible() and win.rect().intersects(bar.geometry()))


def _assert_no_stray_tab_strip(win, columns, extra=()):
    """Exactly the preset's live tab strips (and ``extra``): no stale one from an earlier arrangement, no twin."""
    expected = Counter(frozenset(getattr(win, name).windowTitle() for name in group)
                       for group in [*PRESET_TABS[columns], *extra])
    assert _tab_strips(win) == expected


def _blocks(dock):
    """The dock's group boxes in usage order (the order the dock added them)."""
    return [block for block in dock._content_widget._blocks if block.isVisible()]


def _title(block):
    """A block's title: the group box's own, or a folding block's header title."""
    return block.title() or getattr(block, "title_text", "")


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


def test_initial_layout_for_size():
    """Check 1: 2 columns on a laptop or a short screen, 3 on a large one, Wide from 2000 px wide."""
    from gui.main_window import initial_layout_for_size as pick

    tall, wide = metrics.LAYOUT_THREE_COLUMNS_MIN_HEIGHT, metrics.LAYOUT_WIDE_FROM
    assert pick(1108, 851) == (2, NARROW)
    assert pick(1536, 826) == (2, NARROW)  # 1920x1080 at 125 %
    assert pick(1920, 1040) == (3, NARROW)  # 1920x1080 at 100 %
    assert pick(1920, 1160) == (3, NARROW)  # 1920x1200
    assert pick(2560, 1392) == (3, WIDE)  # ruling M
    assert pick(2048, 824) == (2, WIDE)  # a short wide screen: 2560x1080 at 125 %
    assert pick(metrics.LAYOUT_TWO_COLUMNS_BELOW - 1, 2000) == (2, NARROW)
    assert pick(metrics.LAYOUT_TWO_COLUMNS_BELOW, tall) == (3, NARROW)
    assert pick(metrics.LAYOUT_TWO_COLUMNS_BELOW, tall - 1) == (2, NARROW)
    assert pick(wide, tall) == (3, WIDE)


def _in_view(dock, widget):
    """Whether ``widget`` lies wholly inside ``dock``'s scroll viewport, scrolled to the top."""
    scroll = dock._scroll_area
    scroll.verticalScrollBar().setValue(0)
    viewport = scroll.viewport()
    return viewport.rect().contains(widget.rect().translated(widget.mapTo(viewport, QPoint(0, 0))))


TITLE_BAR = 40  # px a maximised window's title bar takes from the screen's available height


def test_three_columns_at_the_smallest_pick_show_the_first_use_path(window):
    """3 columns at the smallest screen picking them: the first-use path is in view, nothing scrolled.

    Instrument's Angles and Energies, Scattering's H, K, L and dE, and
    Simulation's Run, Stop and progress. The scan commands may need a scroll
    here: the threshold is set by what Instrument needs, so that 1920x1080
    at 100 % gets 3 columns.
    """
    _resize(window, (metrics.LAYOUT_TWO_COLUMNS_BELOW,
                     metrics.LAYOUT_THREE_COLUMNS_MIN_HEIGHT - TITLE_BAR), NARROW, columns=3)
    instrument, scattering, simulation = (window.instrument_dock, window.scattering_dock,
                                          window.simulation_dock)
    angles, energies = _blocks(instrument)[:2]
    assert [_title(angles), _title(energies)] == INSTRUMENT_ORDER[:2]
    hidden = [_title(block) for block in (angles, energies) if not _in_view(instrument, block)]
    hidden += [name for dock, names in (
        (scattering, ["H_edit", "K_edit", "L_edit", "deltaE_edit"]),
        (simulation, ["run_button", "stop_button", "progress_bar"]))
        for name in names if not _in_view(dock, getattr(dock, name))]
    assert not hidden, hidden


@pytest.mark.parametrize("size", [LAPTOP, (1536, 826)], ids=["1108x851", "1536x826"])
def test_three_columns_keep_the_elastic_share(window, size):
    """3 columns chosen on a short window: Instrument keeps its share; Simulation scrolls under Run.

    The content-height docks give way, the lower first; Run, Stop and the
    progress sit at Simulation's top, so they stay in view.
    """
    _resize(window, size, NARROW, columns=3)
    column = window._dock_area_height()
    assert window.instrument_dock.height() >= metrics.SPLIT_ELASTIC_MIN_SHARE * column - 10, (
        window.instrument_dock.height(), column)
    simulation = window.simulation_dock
    assert all(_in_view(simulation, getattr(simulation, name))
               for name in ("run_button", "stop_button", "progress_bar"))


def test_plot_gets_most_of_its_column(window):
    """In 3 columns Display gets more height than the Log and the tabs together."""
    _resize(window, LAPTOP, NARROW, columns=3)
    heights = [d.height() for d in (window.display_dock, window.output_dock,
                                    window.data_control_dock)]
    assert heights[0] > heights[1] + heights[2], heights
    assert window.display_dock.canvas.height() >= metrics.DISPLAY_CANVAS_MIN_HEIGHT


def _assert_preset_placement(win, columns, extra_strips=()):
    """Check 2's placement: every placed dock docked and shown, in its column or behind its tab.

    UB Matrix docked and shown in 3 columns, floating and hidden otherwise;
    no tab strip but the preset's and ``extra_strips`` (groups of dock names).
    """
    for name in PLACED:
        dock = getattr(win, name)
        assert not dock.isFloating() and not dock.isHidden(), name
    lefts = []
    for column in PRESET_COLUMNS[columns]:
        docks = [getattr(win, name) for name in column]
        assert all(not dock.visibleRegion().isEmpty() for dock in docks), column
        assert len({dock.x() for dock in docks}) == 1, column  # one column
        tops = [dock.y() for dock in docks]
        assert tops == sorted(tops), column  # in order, top to bottom
        lefts.append(docks[0].x())
    assert lefts == sorted(lefts) and len(set(lefts)) == len(lefts), lefts
    for primary, *behind in PRESET_TABS[columns]:
        tabbed = win.tabifiedDockWidgets(getattr(win, primary))
        assert all(getattr(win, name) in tabbed for name in behind), primary
        assert not getattr(win, primary).visibleRegion().isEmpty(), primary  # raised
    ub = win.ub_matrix_dock
    assert (not ub.isFloating() and ub.isVisible()) if columns == 3 else (
        ub.isFloating() and ub.isHidden())
    _assert_no_stray_tab_strip(win, columns, extra_strips)


@pytest.mark.parametrize("columns, size", [(2, LAPTOP), (3, MONITOR), (4, MONITOR), (3, LAPTOP)],
                         ids=["2-1108x851", "3-2560x1392", "4-2560x1392", "3-1108x851"])
def test_preset_places_every_dock(window, columns, size):
    """Check 2: every placed dock docked and shown, in its column or behind its tab; no stray strip."""
    _resize(window, size, NARROW, columns=columns)
    assert (window.width(), window.height()) == size  # the preset fits its reference size
    _assert_preset_placement(window, columns)
    reciprocal = window.reciprocal_space_dock
    assert reciprocal.isHidden()  # as at first start
    reciprocal.toggleViewAction().trigger()  # View > Reciprocal Space
    QApplication.processEvents()
    try:
        assert reciprocal in window.tabifiedDockWidgets(window.display_dock)
    finally:
        reciprocal.toggleViewAction().trigger()
        QApplication.processEvents()


def test_two_columns_keep_the_work_surface_on_screen(window):
    """Check 3: 2 columns at 1108x851, Narrow, nothing scrolled: Run to the plot, all on screen."""
    _resize(window, LAPTOP, NARROW, columns=2)
    must_see = {window.simulation_dock: ["run_button", "stop_button", "progress_bar",
                                         "scan_command_1_edit", "scan_command_2_edit"],
                window.scattering_dock: ["H_edit", "K_edit", "L_edit", "deltaE_edit"]}
    for dock, names in must_see.items():
        assert not dock.visibleRegion().isEmpty(), dock.windowTitle()  # the raised tab
        scroll = dock._scroll_area
        scroll.verticalScrollBar().setValue(0)
        viewport = scroll.viewport()
        for name in names:
            widget = getattr(dock, name)
            rect = widget.rect().translated(widget.mapTo(viewport, QPoint(0, 0)))
            assert viewport.rect().contains(rect), (name, rect, viewport.rect())
    canvas = window.display_dock.canvas
    assert canvas.width() >= metrics.DISPLAY_CANVAS_MIN_WIDTH
    assert canvas.height() >= metrics.DISPLAY_CANVAS_MIN_HEIGHT


def test_switching_layouts_keeps_fields_folds_and_width(window):
    """Switching 2, 3, 4 columns keeps field values, the folds, the column width and the plot."""
    group = window.instrument_dock.collapsible_groups["instrument.source"]
    canvas = window.display_dock.canvas
    # A plain field in a dock that changes tab group with every preset (the
    # H/K/L fields would keep their pending-edit border after the test).
    field = window.data_control_dock.save_folder_edit
    before = field.text()
    field.setText("C:/kept/across/layouts")
    try:
        _resize(window, MONITOR, WIDE)
        group.set_collapsed(False)
        for columns in (2, 3, 4, 2):
            _resize(window, MONITOR, columns=columns)
            assert field.text() == "C:/kept/across/layouts"
            assert not group.is_collapsed()
            assert window._column_width == WIDE and window.column_width_actions[WIDE].isChecked()
            assert window.display_dock.canvas is canvas and canvas.isVisible()
            _assert_no_stray_tab_strip(window, columns)
    finally:
        group.set_collapsed(True)
        window.set_column_width(NARROW, fit=False)
        field.setText(before)


@MODES
def test_labels_sit_beside_their_fields(window, mode):
    """Check 4 (4 columns): from a label's text to its field is the metrics gap, not spare width."""
    _resize(window, MONITOR, mode, columns=4)
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


COLUMNS = pytest.mark.parametrize("columns", [2, 3, 4], ids=["2col", "3col", "4col"])


@SIZES
@MODES
@COLUMNS
def test_nothing_clipped(window, size, mode, columns):
    """Check 5: every visible text control is at least its size hint wide, or elided with a tooltip."""
    _resize(window, size, mode, columns)
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


HOURS = 123 * 3600 + 59 * 60 + 59  # a scan of five days, as the tracker formats it


def _feed_runtime_texts(win):
    """Each runtime-updated label in the form docks, given its longest realistic text.

    Through the controller's own slots and the docks' own setters where they
    exist, so the format strings are the real ones. Returns {name: label}.
    """
    from tavi.runtime_tracker import RuntimeTracker
    from gui.docks.unified_simulation_dock import SCAN_CHI_REFUSAL

    ctrl, sim, sample = win.controller, win.simulation_dock, win.sample_dock
    long_time = RuntimeTracker.format_time(HOURS)  # "123h 59m 59s"
    ctrl.update_progress(99999, 100000)
    ctrl.update_remaining_time("123:59:59")  # the worker's {hours:02d}:{minutes:02d}:{seconds:02d}
    ctrl.update_elapsed_time(long_time)
    ctrl.update_counts_entry(123456789012.0, 1234567890123.0)
    sim.update_pre_scan_estimate(long_time)
    sim.update_time_per_point(f"~{long_time}/point")
    sim.update_point_count_display(1000, 1000, 999999, 1)
    sim.update_total_time_estimate(long_time, RuntimeTracker.format_time(3723))
    sim.set_scan_command_warning(
        1, "Unknown variable 'xyz'. Valid: qx, qy, qz, H, K, L, deltaE, A1-A4, 2theta, "
           "omega, sgl, sgu, etc.")
    sim.set_scan_command_warning(2, SCAN_CHI_REFUSAL)
    sim.set_scan_conflict_warning(
        "Conflict: a Q/HKL scan solves the arcs sgl/sgu at every point, so they cannot be "
        "scanned in it; scan 'kappa' (the lower-arc correction) instead, or scan the arcs "
        "in angle mode")
    sample.show_mount_plane(((-10, 10, -12), (0.333333, -0.666667, 1.25)))
    sample.spacegroup_combo.setCurrentIndex(sample.spacegroup_combo.findData(146))  # R3
    sample._update_spacegroup_info()  # the longest constraint text: trigonal
    sample.lattice_warning_label.setText(
        "⚠ Trigonal (R) requires a = b = c; Trigonal (R) requires α = β = γ")
    sample.lattice_warning_label.show()
    sample.update_ub_indicator(False)
    sample.update_misalignment_indicator(False)
    ctrl._set_angles_stale("the analyzer cannot reach this kf: A6 would be 181.3 deg, "
                           "past its 140 deg limit")
    for group in win.instrument_dock.collapsible_groups.values():
        group.set_summary("ρhm 3.25 m (ideal 3.31 m), ρvm 1.75 m, ρha 2.10 m, "
                          "ρva ideal 0.82 m; source Mono, dE 0.5 meV, Ei 14.7 meV")
    for _ in range(3):
        QApplication.processEvents()
    names = {sim: ["progress_label", "remaining_time_label", "elapsed_time_label",
                   "max_counts_label", "total_counts_label", "pre_scan_estimate_label",
                   "time_per_point_label", "point_count_label", "total_time_estimate_label",
                   "scan_warning_1_label", "scan_warning_2_label", "scan_conflict_label"],
             sample: ["mount_status_label", "crystal_system_label", "lattice_warning_label",
                      "ub_indicator_label", "misalignment_indicator_label"],
             win.instrument_dock: ["angles_stale_label"]}
    fed = {name: getattr(dock, name) for dock, attrs in names.items() for name in attrs}
    fed.update({f"{key} summary": group.summary_label
                for key, group in win.instrument_dock.collapsible_groups.items()})
    return fed


def _label_problem(label, blocks):
    """Why ``label`` is clipped or outside its block (one of ``blocks``), or None.

    Check 5's rule: at least its size hint wide, or word-wrapped with the
    height its text needs, or elided with the full text as its tooltip.
    """
    block = label.parentWidget()
    while block not in blocks:
        block = block.parentWidget()
    rect = label.rect().translated(label.mapTo(block, QPoint(0, 0)))
    if not block.rect().contains(rect):
        return f"outside its block {block.rect()}: {rect}"
    if block.width() > metrics.BLOCK_WIDTH:
        return f"its block is {block.width()} px wide"
    if label.wordWrap():
        if label.height() < label.heightForWidth(label.width()):
            return f"wrapped, {label.height()} px tall of {label.heightForWidth(label.width())}"
        return None
    if label.width() >= label.sizeHint().width():
        return None
    if "…" in label.text() and label.toolTip() and label.toolTip() != label.text():
        return None
    return f"{label.width()} < {label.sizeHint().width()} px"


@MODES
def test_running_scan_texts_are_not_clipped(window, mode):
    """Every runtime-updated form-dock label, at its longest realistic text, fits its block."""
    _resize(window, MONITOR, mode, columns=4)
    sim, sample = window.simulation_dock, window.sample_dock
    groups = window.instrument_dock.collapsible_groups.values()
    stale = window.instrument_dock.angles_stale_label
    saved = {label: (label.text(), label.isHidden(), label.toolTip())
             for label in window.findChildren(QLabel)}
    summaries = {group: group._summary for group in groups}
    space_group = sample.spacegroup_combo.currentIndex()
    mount = (sample.mount_u_edit.text(), sample.mount_v_edit.text())
    try:
        fed = _feed_runtime_texts(window)
        blocks = [block for name in FORM_DOCKS
                  for block in getattr(window, name)._content_widget._blocks]
        assert not [name for name, label in fed.items() if label.isHidden()]
        bad = [f"{name} {label.text()!r}: {problem}" for name, label in fed.items()
               if (problem := _label_problem(label, blocks))]
        assert not bad, "\n".join(bad)
    finally:
        sim.clear_all_scan_warnings()
        window.controller._angles_stale = None
        sample.spacegroup_combo.setCurrentIndex(space_group)
        sample.mount_u_edit.setText(mount[0])
        sample.mount_v_edit.setText(mount[1])
        for group, summary in summaries.items():
            group.set_summary(summary)
        for label, (text, hidden, tip) in saved.items():
            label.setText(text)
            label.setToolTip(tip)
            label.setHidden(hidden)
        stale.setHidden(saved[stale][1])
        QApplication.processEvents()


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
@COLUMNS
def test_blocks_fit_without_horizontal_scroll(window, size, mode, columns):
    """No form dock scrolls sideways or cuts a block off; no block is wider than one block."""
    _resize(window, size, mode, columns)
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
    _resize(window, MONITOR, WIDE, columns=3)
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
    _resize(window, MONITOR, WIDE, columns=3)
    assert len(_block_columns(dock)) == 2
    narrower = dock.width_for_blocks(2) - 2 * metrics.BLOCK_REFLOW_HYSTERESIS
    window.resizeDocks([dock, window.scattering_dock], [narrower, narrower], Qt.Horizontal)
    QApplication.processEvents()
    assert dock.width() < dock.width_for_blocks(2)
    assert len(_block_columns(dock)) == 1


def test_column_width_saved_with_the_layout(window, layout_file):
    """Save then restart round-trips column_width; missing or unknown reads as Narrow."""
    try:
        window.set_column_width(WIDE, fit=False)
        assert window.save_layout_to_file()
    finally:
        window.set_column_width(NARROW, fit=False)
    saved = json.loads(layout_file.read_text(encoding="utf-8"))
    assert saved["column_width"] == WIDE
    rest = {key: value for key, value in saved.items() if key != "column_width"}
    for stored, expected in ((saved, WIDE), (rest, NARROW), ({**rest, "column_width": "huge"}, NARROW)):
        layout_file.write_text(json.dumps(stored), encoding="utf-8")
        restarted = _restart(show=False)
        try:
            assert restarted._layout_restored
            assert restarted._column_width == expected, stored.get("column_width")
        finally:
            _close(restarted)


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
    for group in docks[0].collapsible_groups.values():
        group.set_collapsed(False)  # measure the folding blocks' fields too
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


def _standalone_instrument_dock(instrument_id):
    """The Instrument dock alone, shown, in the window's font; no controller."""
    from gui.docks.instrument_dock import InstrumentDock

    app = QApplication.instance() or QApplication([sys.argv[0]])
    _use_windows_ui_font(app)
    descriptor = get_instrument(instrument_id).descriptor()
    dock = InstrumentDock(descriptor=descriptor)
    dock.show()  # the summary elides to the laid-out block width
    app.processEvents()
    return dock, descriptor


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_instrument_blocks_in_usage_order(instrument_id):
    """Check 7: the Instrument blocks run in usage order, the optional ones exactly where declared."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    dock, descriptor = _standalone_instrument_dock(instrument_id)
    try:
        declared = {"Collimations": descriptor.collimation,
                    "Slit Apertures (mm)": descriptor.slits,
                    "Experimental Modules": descriptor.modules}
        expected = [title for title in INSTRUMENT_ORDER if declared.get(title, True)]
        assert [_title(block) for block in dock._content_widget._blocks] == expected
    finally:
        dock.deleteLater()
        app.processEvents()
        app.setFont(font)


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_folded_blocks_summarise_their_fields(instrument_id):
    """Check 7: folded, a block's summary line follows each of its fields."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    dock, descriptor = _standalone_instrument_dock(instrument_id)
    groups = dock.collapsible_groups
    try:
        assert set(groups) == {"instrument.focusing", "instrument.source"} | (
            {"instrument.modules"} if descriptor.modules else set())

        def summary(key):
            group = groups[key]
            assert group.is_collapsed() and not group.body.isVisible()
            assert group.summary_label.isVisible() and group.header.text() == group.title_text
            shown, full = group.summary_label.text(), group.summary_label.toolTip()
            assert shown == full or shown.endswith("…"), (shown, full)  # elided, never cut
            return shown, full

        changes = [
            ("instrument.focusing", lambda: dock.rhm_edit.setText("3.25")),
            ("instrument.focusing", lambda: dock.rva_ideal_button.setChecked(
                not dock.rva_ideal_button.isChecked())),
            ("instrument.source", lambda: dock.set_source_id("Mono")),
            ("instrument.source", lambda: dock.source_dE_edit.setText("0.5")),
        ]
        for module in descriptor.modules:
            widget = dock.module_widgets[module.id]
            if isinstance(widget, QComboBox):
                changes.append(("instrument.modules",
                                lambda w=widget: w.setCurrentIndex(w.count() - 1)))
            else:
                changes.append(("instrument.modules",
                                lambda w=widget: w.setChecked(not w.isChecked())))
        for key, change in changes:
            before = summary(key)
            change()
            app.processEvents()
            assert summary(key) != before, (key, before)
    finally:
        dock.deleteLater()
        app.processEvents()
        app.setFont(font)


def test_header_toggles_from_the_keyboard_without_reflow(window):
    """Space and Enter fold and unfold a block; the blocks keep their columns."""
    _resize(window, MONITOR, WIDE, columns=3)
    dock = window.instrument_dock
    group = dock.collapsible_groups["instrument.focusing"]
    columns = {_title(block): block.x() for block in _blocks(dock)}
    assert len(set(columns.values())) == 2, columns
    try:
        assert group.is_collapsed()
        assert group.header.accessibleName() == group.title_text
        assert group.header.focusPolicy() & Qt.TabFocus
        QTest.keyClick(group.header, Qt.Key_Space)
        QApplication.processEvents()
        assert not group.is_collapsed() and group.body.isVisible()
        assert not group.summary_label.isVisible()
        assert {_title(block): block.x() for block in _blocks(dock)} == columns
        QTest.keyClick(group.header, Qt.Key_Return)
        QApplication.processEvents()
        assert group.is_collapsed() and not group.body.isVisible()
    finally:
        group.set_collapsed(True)


def test_folded_state_saved_with_the_layout(window, layout_file, capsys):
    """Save then restart round-trips the folds; a missing or non-boolean entry folds, logged."""
    groups = window.instrument_dock.collapsible_groups
    try:
        groups["instrument.focusing"].set_collapsed(False)
        assert window.save_layout_to_file()
    finally:
        groups["instrument.focusing"].set_collapsed(True)
    layout = json.loads(layout_file.read_text(encoding="utf-8"))
    saved = layout.pop("collapsed_groups")
    assert saved == {"instrument.focusing": False, "instrument.modules": True,
                     "instrument.source": True}
    layout_file.write_text(json.dumps({**layout, "collapsed_groups": saved}), encoding="utf-8")
    restarted = _restart(show=False)
    try:
        assert {key: group.is_collapsed() for key, group
                in restarted.instrument_dock.collapsible_groups.items()} == saved
    finally:
        _close(restarted)
    cases = [
        ({}, {key: True for key in groups}),
        ({"collapsed_groups": ["instrument.source"]}, {key: True for key in groups}),
        ({"collapsed_groups": {"instrument.focusing": "no", "instrument.source": False}},
         {"instrument.focusing": True, "instrument.modules": True,
          "instrument.source": False}),
    ]
    for stored, expected in cases:
        layout_file.write_text(json.dumps({**layout, **stored}), encoding="utf-8")
        capsys.readouterr()
        restarted = _restart(show=False)
        try:
            assert restarted._layout_restored
            state = {key: group.is_collapsed()
                     for key, group in restarted.instrument_dock.collapsible_groups.items()}
            assert state == expected, stored
            logged = capsys.readouterr().out
            for key, collapsed in expected.items():  # no case stores a valid True
                assert (f"collapsed_groups[{key!r}]" in logged) == collapsed, (stored, logged)
        finally:
            _close(restarted)


@pytest.fixture
def layout_file(window, tmp_path, monkeypatch):
    """A view_layout.json in a temp folder, read and written by every window while the test runs.

    Patched on the shared window too: an earlier test's instance patch, once
    undone, leaves an instance attribute that would shadow the class's.
    """
    path = tmp_path / "view_layout.json"
    monkeypatch.setattr(cm.TAVIMainWindow, "_get_layout_config_path", lambda self: str(path))
    monkeypatch.setattr(window, "_get_layout_config_path", lambda: str(path))
    return path


def _restart(show=True):
    """A new window as main() builds it (no controller): the layout file restored, then shown.

    The shared window is never restored into: restoring over a shown window
    leaves the replaced tab groups' strips behind, which TAVI never does.
    """
    instrument = get_instrument("puma")
    win = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    if show:
        win.show()
        for _ in range(3):  # the startup timer: fit to the screen, size the preset
            QApplication.processEvents()
    return win


def _close(win):
    win.deleteLater()
    QApplication.processEvents()


def _log(win):
    return win.output_dock.message_text.toPlainText()


def _assert_picked_preset(win):
    """The preset first start picks for the window's screen, every placed dock docked and shown."""
    from gui.main_window import initial_layout_for_size

    assert not win._layout_restored
    room = win.screen().availableGeometry()
    columns, _width = initial_layout_for_size(room.width(), room.height())
    assert win._columns == columns
    for name in PLACED:
        dock = getattr(win, name)
        assert not dock.isFloating() and not dock.isHidden(), name
    _assert_no_stray_tab_strip(win, columns)


def test_saved_layout_wins_on_restart(window, layout_file):
    """Check 6: the next start restores the arrangement, the column width and the folds."""
    groups = window.instrument_dock.collapsible_groups
    try:
        _resize(window, MONITOR, WIDE, columns=4)
        groups["instrument.source"].set_collapsed(False)
        assert window.save_layout_to_file()
    finally:
        groups["instrument.source"].set_collapsed(True)
        window.set_column_width(NARROW, fit=False)
    restarted = _restart()
    try:
        assert restarted._layout_restored
        assert restarted._columns == 4 and restarted._column_width == WIDE
        assert restarted.column_width_actions[WIDE].isChecked()
        assert not restarted.instrument_dock.collapsible_groups["instrument.source"].is_collapsed()
        lefts = [getattr(restarted, name).x()
                 for name in ("instrument_dock", "sample_dock", "scattering_dock", "display_dock")]
        assert lefts == sorted(lefts) and len(set(lefts)) == 4, lefts
        assert restarted.simulation_dock.x() == restarted.scattering_dock.x()
        _assert_no_stray_tab_strip(restarted, 4)
    finally:
        _close(restarted)


@pytest.mark.parametrize("version", [2, 4])
def test_other_version_layout_is_set_aside(window, layout_file, version):
    """Check 6: an older or newer file is renamed .v<N>.bak (over an older one), said so, and the preset applies."""
    assert window.save_layout_to_file()
    layout = json.loads(layout_file.read_text(encoding="utf-8"))
    layout["layout_version"] = version
    layout_file.write_text(json.dumps(layout), encoding="utf-8")
    backup = layout_file.with_name(f"view_layout.json.v{version}.bak")
    backup.write_text("an older set-aside layout", encoding="utf-8")
    restarted = _restart()
    try:
        assert not layout_file.exists()
        assert json.loads(backup.read_text(encoding="utf-8")) == layout
        log = _log(restarted)
        assert "set aside" in log and str(backup) in log
        assert f"another TAVI version (layout version {version};" in log and "older" not in log
        _assert_picked_preset(restarted)
    finally:
        _close(restarted)


@pytest.mark.parametrize("copy_fails", [False, True], ids=["copied", "neither"])
def test_set_aside_that_cannot_rename_says_so(window, layout_file, monkeypatch, copy_fails):
    """A locked file that cannot be renamed is copied aside instead, or the log says it will be overwritten."""
    import gui.main_window as main_window

    assert window.save_layout_to_file()
    layout = json.loads(layout_file.read_text(encoding="utf-8"))
    layout["layout_version"] = 2
    layout_file.write_text(json.dumps(layout), encoding="utf-8")
    backup = layout_file.with_name("view_layout.json.v2.bak")

    def locked(*_args):
        raise PermissionError(13, "The process cannot access the file", str(layout_file))

    monkeypatch.setattr(main_window.os, "replace", locked)
    if copy_fails:
        monkeypatch.setattr(main_window.shutil, "copyfile", locked)
    restarted = _restart()
    try:
        log = _log(restarted)
        assert str(layout_file) in log and "The process cannot access the file" in log
        assert "could not be moved" in log and "overwritten when TAVI closes" in log
        assert "could not restore" not in log
        assert layout_file.exists()  # the rename did not happen
        if copy_fails:
            assert not backup.exists() and "copying failed too" in log
        else:
            assert json.loads(backup.read_text(encoding="utf-8")) == layout
            assert f"copied to {backup}" in log
        _assert_picked_preset(restarted)
    finally:
        _close(restarted)


@pytest.mark.parametrize("damage", ["window_state", "json"])
def test_unreadable_layout_falls_back(window, layout_file, damage):
    """Check 6: a state Qt refuses, or broken JSON, gives the preset and a log line; nothing raises."""
    assert window.save_layout_to_file()
    if damage == "window_state":
        layout = json.loads(layout_file.read_text(encoding="utf-8"))
        layout["window_state"] = "Z2FyYmFnZQ=="  # base64 of "garbage"
        layout_file.write_text(json.dumps(layout), encoding="utf-8")
    else:
        layout_file.write_text('{"layout_version": 3, "window_state": ', encoding="utf-8")
    restarted = _restart()
    try:
        assert "could not restore" in _log(restarted)
        _assert_picked_preset(restarted)
    finally:
        _close(restarted)


FAR = QPoint(-20000, -20000)


def _on_screen(dock):
    return any(screen.availableGeometry().intersects(dock.frameGeometry())
               for screen in QGuiApplication.screens())


def test_docks_saved_off_screen_come_back(window, layout_file, monkeypatch):
    """Check 6: floating docks saved off every screen come back on one after a restart.

    Misalignment (docked once by the user, so the saved state holds it) and UB
    Matrix (opened, so floating, in 4 columns), both shown and saved far off,
    as on a monitor since unplugged. The restart leaves them there, as a
    window system that does not clamp would, so only the rescue brings them
    back: checked before the window is shown (the offscreen platform may
    clamp a window it creates) and after. A hidden floating dock cannot be
    lost this way: Qt 6.11 restores it docked.
    """
    misalignment, ub = window.misalignment_dock, window.ub_matrix_dock
    try:
        _resize(window, MONITOR, NARROW, columns=4)
        window.addDockWidget(Qt.RightDockWidgetArea, misalignment)
        misalignment.setFloating(True)
        for dock in (misalignment, ub):
            dock.show()
            dock.move(FAR)
        QApplication.processEvents()
        assert ub.isFloating() and not _on_screen(misalignment) and not _on_screen(ub)
        assert window.save_layout_to_file()
    finally:
        window.removeDockWidget(misalignment)
        misalignment.setFloating(True)
        misalignment.hide()
        ub.hide()
    names = ("misalignment_dock", "ub_matrix_dock")
    _unclamped_restore(monkeypatch, *names)
    restarted = _restart(show=False)
    try:
        assert restarted._layout_restored
        assert all(not getattr(restarted, name).isHidden() for name in names)
        lost = [name for name in names if not _on_screen(getattr(restarted, name))]
        assert not lost, lost
        assert "brought back" in _log(restarted)
        restarted.show()
        QApplication.processEvents()
        lost = [name for name in names if not _on_screen(getattr(restarted, name))]
        assert not lost, lost
    finally:
        _close(restarted)


def _open_from_sample_dock(win, button):
    """Click the Sample dock's open button, as the user does, and return the dock geometries."""
    before = {name: getattr(win, name).geometry() for name in PLACED}
    getattr(win.sample_dock, button).click()
    QApplication.processEvents()
    return before


@pytest.mark.parametrize("columns", [2, 3, 4])
def test_hidden_ub_matrix_opens_in_its_preset_place_after_restart(window, layout_file, columns):
    """Check 6: UB Matrix saved hidden opens from the Sample dock where its preset puts it.

    The session starts in 3 columns, as on a large screen, and switches.
    With 2 or 4 columns UB Matrix opens floating and on screen, the docks
    where they were: Qt 6.11 restores the dock the preset took out and
    floated as docked, so unless the restore floats it again it opens as a
    full-width row. With 3 it opens docked under Sample.
    """
    ub = window.ub_matrix_dock
    try:
        _resize(window, MONITOR, NARROW, columns=3)
        _resize(window, MONITOR, NARROW, columns=columns)
        ub.hide()  # closed, in 3 columns; already hidden in 2 or 4
        assert ub.isFloating() == (columns != 3)
        assert window.save_layout_to_file()
    finally:
        _resize(window, MONITOR, NARROW, columns=columns)
    restarted = _restart()
    try:
        ub, sample = restarted.ub_matrix_dock, restarted.sample_dock
        assert ub.isHidden()
        before = _open_from_sample_dock(restarted, "open_ub_matrix_button")
        assert ub.isVisible()
        if columns == 3:
            assert not ub.isFloating() and ub.x() == sample.x() and ub.y() > sample.y()
        else:
            assert ub.isFloating() and _on_screen(ub)
            moved = [name for name, rect in before.items()
                     if getattr(restarted, name).geometry() != rect]
            assert not moved, moved
    finally:
        _close(restarted)


def test_hidden_misalignment_opens_floating_after_restart(window, layout_file):
    """Check 6: Misalignment docked by the user, floated by a preset and closed opens floating after a restart."""
    misalignment = window.misalignment_dock
    try:
        _resize(window, MONITOR, NARROW, columns=4)
        window.addDockWidget(Qt.RightDockWidgetArea, misalignment)
        misalignment.setFloating(False)  # docked by the user
        _resize(window, MONITOR, NARROW, columns=4)  # the preset floats it again
        misalignment.hide()
        assert misalignment.isFloating()
        assert window.save_layout_to_file()
    finally:
        misalignment.hide()
    restarted = _restart()
    try:
        misalignment = restarted.misalignment_dock
        assert misalignment.isHidden()
        before = _open_from_sample_dock(restarted, "open_misalignment_button")
        assert misalignment.isVisible() and misalignment.isFloating() and _on_screen(misalignment)
        moved = [name for name, rect in before.items()
                 if getattr(restarted, name).geometry() != rect]
        assert not moved, moved
    finally:
        _close(restarted)


def test_lost_docks_are_rescued(window):
    """The rescue itself: a homeless dock is centred on the screen, a placed one docked again."""
    misalignment, display = window.misalignment_dock, window.display_dock
    _resize(window, MONITOR, NARROW, columns=4)
    try:
        misalignment.setFloating(True)
        misalignment.show()
        display.setFloating(True)
        for dock in (misalignment, display):
            dock.move(FAR)
        QApplication.processEvents()
        window._rescue_lost_docks()
        QApplication.processEvents()
        assert _on_screen(misalignment)
        assert not display.isFloating() and not display.visibleRegion().isEmpty()
        assert "brought back" in _log(window)
        _assert_no_stray_tab_strip(window, 4)
    finally:
        misalignment.hide()
        if display.isFloating():
            _resize(window, MONITOR, NARROW, columns=4)


def _unclamped_restore(monkeypatch, *names):
    """Restore as a window system that leaves floating docks where they were saved would.

    Qt 6.11's restoreState puts a floating dock back on a screen by itself;
    this moves the named docks, when floating, back off every screen after it.
    """
    restore = cm.TAVIMainWindow.restoreState

    def unclamped(self, state):
        restored = restore(self, state)
        for name in names:
            if getattr(self, name).isFloating():
                getattr(self, name).move(FAR)
        return restored

    monkeypatch.setattr(cm.TAVIMainWindow, "restoreState", unclamped)


def test_rescue_moves_only_the_lost_dock(window, layout_file, monkeypatch):
    """A lost Display goes back to its place; a deliberately floated and a hidden dock stay as saved."""
    fitting, log, display = window.fitting_dock, window.output_dock, window.display_dock
    try:
        _resize(window, MONITOR, NARROW, columns=4)
        fitting.setFloating(True)  # the user's own floating panel, on screen
        fitting.move(240, 180)
        log.hide()  # closed by the user
        display.setFloating(True)  # lost below
        QApplication.processEvents()
        assert window.save_layout_to_file()
    finally:
        _resize(window, MONITOR, NARROW, columns=4)
    baseline = _restart()  # the saved layout as Qt restores it, nothing lost
    try:
        assert baseline.fitting_dock.isFloating()
        kept = baseline.fitting_dock.geometry()
    finally:
        _close(baseline)
    _unclamped_restore(monkeypatch, "display_dock")
    restarted = _restart()
    try:
        assert restarted._layout_restored and "brought back" in _log(restarted)
        display = restarted.display_dock
        assert not display.isFloating() and not display.visibleRegion().isEmpty()
        assert restarted.output_dock.isHidden()
        assert restarted.fitting_dock.isFloating() and restarted.fitting_dock.geometry() == kept
        lefts = [getattr(restarted, name).x()
                 for name in ("instrument_dock", "sample_dock", "scattering_dock")]
        assert lefts == sorted(lefts) and len(set(lefts)) == 3, lefts
        assert restarted.simulation_dock.x() == restarted.scattering_dock.x()
    finally:
        _close(restarted)


def test_lost_dock_without_a_place_still_docks(window):
    """A lost dock Qt kept no place for (UB Matrix in 3 columns, floated out of the layout) docks at the edge."""
    ub = window.ub_matrix_dock
    _resize(window, MONITOR, NARROW, columns=3)
    try:
        window.removeDockWidget(ub)  # no place kept for it
        ub.setFloating(True)
        ub.show()
        ub.move(FAR)
        QApplication.processEvents()
        assert ub.isFloating() and not _on_screen(ub)
        window._rescue_lost_docks()
        QApplication.processEvents()
        assert not ub.isFloating() and ub.isVisible() and not ub.visibleRegion().isEmpty()
    finally:
        _resize(window, MONITOR, NARROW, columns=3)


@pytest.mark.parametrize("visibility", [["MisalignmentDock"], {"MisalignmentDock": "yes"}],
                         ids=["list", "not-bool"])
def test_fallback_still_rescues_lost_docks(window, layout_file, monkeypatch, visibility):
    """A v3 file failing after restoreState falls back to the preset and still brings Misalignment back.

    On screen before the window is shown (TAVI's own rescue; the platform
    may also clamp a window it creates) and once opened.
    """
    misalignment = window.misalignment_dock
    try:
        # Docked once by the user and floated again: now part of the saved state.
        window.addDockWidget(Qt.RightDockWidgetArea, misalignment)
        misalignment.setFloating(True)
        misalignment.show()
        misalignment.move(FAR)
        QApplication.processEvents()
        assert window.save_layout_to_file()
    finally:
        window.removeDockWidget(misalignment)
        misalignment.setFloating(True)
        misalignment.hide()
    layout = json.loads(layout_file.read_text(encoding="utf-8"))
    layout["dock_visibility"] = visibility
    layout_file.write_text(json.dumps(layout), encoding="utf-8")
    _unclamped_restore(monkeypatch, "misalignment_dock")
    restarted = _restart(show=False)
    try:
        assert _on_screen(restarted.misalignment_dock)
        restarted.show()
        restarted._on_open_misalignment_dock()
        QApplication.processEvents()
        assert _on_screen(restarted.misalignment_dock)
    finally:
        _close(restarted)


@pytest.mark.parametrize("columns", [2, 3, 4])
@pytest.mark.parametrize("docked_once", [True, False], ids=["docked-once", "off-screen"])
def test_presets_after_restore_all_panels(window, columns, docked_once):
    """View > Restore All Panels, then a preset: Misalignment floats on screen, the rest as check 2.

    Misalignment was docked once by the user and floated again (Restore All
    Panels docks it back), or was left floating off every screen.
    """
    misalignment, reciprocal = window.misalignment_dock, window.reciprocal_space_dock
    _resize(window, MONITOR, NARROW, columns=3)
    try:
        if docked_once:
            window.addDockWidget(Qt.RightDockWidgetArea, misalignment)
            misalignment.setFloating(True)
        else:
            misalignment.show()  # a window that has been on screen keeps its place
            misalignment.move(FAR)
        misalignment.hide()
        QApplication.processEvents()
        window.restore_all_docks()
        QApplication.processEvents()
        assert all(_on_screen(dock) for dock in window._all_docks if dock.isFloating())
        _resize(window, MONITOR, NARROW, columns=columns)
        assert misalignment.isFloating() and misalignment.isVisible() and _on_screen(misalignment)
        assert reciprocal.isVisible() and reciprocal in window.tabifiedDockWidgets(
            window.display_dock)
        _assert_preset_placement(window, columns, [("display_dock", "reciprocal_space_dock")])
    finally:
        if not misalignment.isFloating():
            window.removeDockWidget(misalignment)
            misalignment.setFloating(True)
        misalignment.hide()
        reciprocal.hide()
        _resize(window, MONITOR, NARROW, columns=columns)


def test_reset_picks_for_the_screen_and_refolds(window):
    """Reset to Default Layout: the screen's pick and width, the window fitted, the blocks folded."""
    from gui.main_window import initial_layout_for_size

    groups = window.instrument_dock.collapsible_groups
    _resize(window, MONITOR, WIDE, columns=4)
    groups["instrument.focusing"].set_collapsed(False)
    window.reset_to_default_layout()
    for _ in range(3):
        QApplication.processEvents()
    room = window.screen().availableGeometry()
    columns, width = initial_layout_for_size(room.width(), room.height())
    assert window._columns == columns and window._column_width == width
    assert window.column_width_actions[width].isChecked()
    assert all(group.is_collapsed() for group in groups.values())
    assert window.isMaximized()
    _assert_no_stray_tab_strip(window, columns)
