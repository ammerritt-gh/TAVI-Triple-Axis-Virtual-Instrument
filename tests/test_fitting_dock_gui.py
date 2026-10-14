"""Offscreen-Qt checks of the Fitting dock with the real Display dock.

The docks are built the lightest way the code allows: a ``DisplayDock`` and a
``FittingDock(display_dock=...)`` with no main window, no controller and no
McStas.  ``_wire`` repeats the two lifecycle connections of
``gui/main_window.py::_connect_dock_signals`` (a source-text test pins that the
real window makes the same ones).  The controller is a stand-in that records
the goto calls.  ``QT_QPA_PLATFORM=offscreen``: only the geometry check shows
the dock, on the offscreen platform, never on the desktop.
"""
import dataclasses
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import (QApplication, QBoxLayout, QLabel,  # noqa: E402
                               QPushButton, QWidget)

from gui import theme  # noqa: E402
from gui.docks.display_dock import DisplayDock  # noqa: E402
from gui.docks.fitting_dock import FittingDock  # noqa: E402
from tavi import scan_fits  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class _Controller:
    """Stand-in for TAVIController: idle, records every goto it is asked for."""

    def __init__(self):
        self.gotos = []
        self.reverts = 0

    def _scan_busy(self):
        return False

    def can_revert_goto(self):
        return bool(self.gotos)

    def goto_scan_variable(self, variable, value, label=""):
        self.gotos.append((variable, float(value), label))
        return True, "%s: %s -> %g" % (label, variable, value)

    def revert_last_goto(self):
        self.reverts += 1
        return True, "reverted"


def _wire(display, fitting):
    """The lifecycle connections ``MainWindow._connect_dock_signals`` makes."""
    display.scan_data_reset.connect(fitting.on_scan_reset)
    display.scan_data_finished.connect(fitting.on_scan_finished)
    display.plot_rebuilt.connect(fitting.on_plot_rebuilt)


@pytest.fixture()
def docks():
    """(display, fitting, controller), freshly built and wired for each test."""
    QApplication.instance() or QApplication([sys.argv[0]])
    display = DisplayDock()
    fitting = FittingDock(display_dock=display)
    controller = _Controller()
    fitting.set_controller(controller)
    _wire(display, fitting)
    yield display, fitting, controller
    fitting._teardown_span_selector()
    fitting.deleteLater()
    display.deleteLater()


def _scan_peak(display, n=21, measured=None):
    """Initialise a 1D scan over [-1, 1] and measure a Gaussian peak at 0.1."""
    x = np.linspace(-1.0, 1.0, n)
    display.initialize_scan("1D", list(x), [True] * n, "h")
    rng = np.random.default_rng(7)
    for i in range(n if measured is None else measured):
        counts = 5.0 + 200.0 * np.exp(-0.5 * ((x[i] - 0.1) / 0.15) ** 2)
        display.update_1d_point(i, float(rng.poisson(counts)))
    return x


def test_overlay_survives_mid_scan_axes_rebuild(docks):
    display, fitting, _ = docks
    _scan_peak(display, measured=20)  # the last point stays unmeasured

    fitting.range_button.setChecked(True)          # leave range selection on
    fitting._on_span_selected(-0.6, 0.8)           # what a drag on the plot does
    fitting._on_fit_clicked()
    assert fitting._fit_result is not None and fitting._fit_result.converged

    ax = display.ax
    old_curve, old_center = fitting._curve_artist, fitting._center_artist
    old_span, old_selector = fitting._span_artist, fitting._span_selector
    assert old_curve in ax.lines and old_center in ax.lines
    assert old_span in ax.patches and old_selector is not None
    before = {key: label.text() for key, label in fitting._result_labels.items()}
    status_before = fitting.status_label.text()
    fit_before = fitting._fit_result

    display.mark_1d_point_invalid(20)              # clears and rebuilds the axes

    # The rebuild really destroyed the old artists ...
    assert old_curve not in ax.lines and old_center not in ax.lines
    assert old_span not in ax.patches
    # ... and the dock redrew them: new objects, children of the current axes.
    assert display.ax is ax
    assert fitting._curve_artist is not None and fitting._curve_artist is not old_curve
    assert fitting._curve_artist in ax.lines
    assert fitting._center_artist is not None and fitting._center_artist in ax.lines
    assert fitting._span_artist is not None and fitting._span_artist in ax.patches
    # The span selector is a new one on the current axes, still active.
    selector = fitting._span_selector
    assert selector is not None and selector is not old_selector
    assert selector.ax is ax and selector.active
    assert fitting.range_button.isChecked()
    assert all(artist.axes is ax for artist in selector.artists)
    # Nothing else changed: fit, range, fields and readout survive.
    assert fitting._fit_result is fit_before
    assert fitting._range == (-0.6, 0.8)
    assert fitting.range_min_edit.text() == "-0.6" and fitting.range_max_edit.text() == "0.8"
    assert {key: label.text() for key, label in fitting._result_labels.items()} == before
    assert fitting.status_label.text() == status_before
    assert fitting.goto_cen_button.isEnabled()


def test_rebuild_without_fit_or_range_draws_nothing(docks):
    display, fitting, _ = docks
    _scan_peak(display, measured=20)
    ax = display.ax
    lines_before = len(ax.lines)
    display.mark_1d_point_invalid(20)
    assert fitting._curve_artist is None and fitting._center_artist is None
    assert fitting._span_artist is None and fitting._span_selector is None
    assert len(display.ax.lines) <= lines_before   # the dock added no lines


def test_new_scan_still_clears_everything(docks):
    display, fitting, _ = docks
    _scan_peak(display, measured=20)
    fitting.range_button.setChecked(True)
    fitting._on_span_selected(-0.6, 0.8)
    fitting._on_fit_clicked()
    assert fitting._fit_result is not None

    display.initialize_scan("1D", [0.0, 1.0, 2.0], [True] * 3, "h")

    assert fitting._fit_result is None and fitting._seed is None
    assert fitting._curve_artist is None and fitting._center_artist is None
    assert fitting._span_artist is None
    assert fitting._range is None
    assert fitting.range_min_edit.text() == "" and fitting.range_max_edit.text() == ""
    assert not fitting.goto_cen_button.isEnabled()
    # A selector left switched on follows the new axes, as before.
    assert fitting.range_button.isChecked() and fitting._span_selector.ax is display.ax


def test_goto_cen_reaches_the_controller(docks):
    display, fitting, controller = docks
    _scan_peak(display)
    fitting._on_fit_clicked()
    fitting.goto_cen_button.click()
    assert len(controller.gotos) == 1
    variable, value, label = controller.gotos[0]
    assert (variable, label) == ("h", "goto CEN")
    assert value == pytest.approx(fitting._fit_result.center)


def test_plot_rebuilt_ignores_a_2d_display(docks):
    display, fitting, _ = docks
    display.initialize_scan(
        "2D", [0.0, 1.0], [], "a", "b", [0.0, 1.0],
        valid_mask_2d=np.ones((2, 2), dtype=bool))
    fitting.on_plot_rebuilt()          # must neither raise nor draw
    assert fitting._curve_artist is None and fitting._span_artist is None


def test_main_window_wires_plot_rebuilt():
    source = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "self.display_dock.plot_rebuilt.connect(" in source
    assert "self.fitting_dock.on_plot_rebuilt" in source


# ---------------------------------------------------------------------------
# The condensed layout: per-row Go, the readout, Copy results, the reflow
# ---------------------------------------------------------------------------

def _scan_counts(display, x, counts, variable="h"):
    """Initialise a 1D scan over ``x`` and measure ``counts`` point by point."""
    display.initialize_scan("1D", list(x), [True] * len(x), variable)
    for i, value in enumerate(counts):
        display.update_1d_point(i, float(value))


def _shown(label):
    return not label.isHidden()


def test_each_go_drives_its_own_rows_value(docks):
    display, fitting, controller = docks
    _scan_peak(display)
    fitting._on_fit_clicked()
    rows = fitting._result_labels
    expected = {"cen": fitting._fit_result.center, "com": fitting._com.x,
                "max": fitting._max.x}
    buttons = {"cen": fitting.goto_cen_button, "com": fitting.goto_com_button,
               "max": fitting.goto_max_button}
    assert {b.accessibleName() for b in buttons.values()} == {
        "Go to CEN", "Go to COM", "Go to MAX"}
    for kind, button in buttons.items():
        assert button.text() == "Go" and button.isEnabled()
        assert button.toolTip().startswith("Drives h to this row's value")
        button.click()
        variable, value, label = controller.gotos[-1]
        assert (variable, label) == ("h", "goto " + kind.upper())
        assert value == pytest.approx(expected[kind])
        # ... and it is the value that row shows.
        assert rows[kind].text().startswith("%.6g" % expected[kind])
    assert fitting.status_label.text().startswith("goto MAX")
    assert fitting.revert_button.isEnabled()


def test_cen_go_keeps_its_three_state_soft_gate(docks):
    display, fitting, _ = docks
    _scan_peak(display, measured=20)
    cen = fitting.goto_cen_button
    # No fit: disabled, and the tooltip says why.
    assert not cen.isEnabled() and "press Fit" in cen.toolTip()
    assert cen.styleSheet() == ""
    fitting._on_fit_clicked()
    assert fitting._fit_result.converged and not fitting._fit_result.warnings
    # A clean converged fit: plain and enabled.
    assert cen.isEnabled() and cen.styleSheet() == ""
    # A point measured after the fit: amber from the theme, reason in the tooltip.
    display.update_1d_point(20, 5.0)
    fitting.refresh_gating("running", "done")      # a job transition
    assert cen.isEnabled()
    assert theme.WARNING_FILL in cen.styleSheet()
    assert theme.WARNING_TEXT in cen.styleSheet()
    assert "1 point(s) measured since this fit" in cen.toolTip()
    assert "1 point(s) measured since this fit" in fitting.status_label.text()


def test_pinned_shape_names_itself_and_background_at_limit(docks):
    display, fitting, _ = docks
    x = np.linspace(-1.0, 1.0, 41)
    _scan_counts(display, x, 1000.0 * np.exp(-0.5 * ((x - 0.1) / 0.15) ** 2))
    fitting._on_fit_clicked()
    result = fitting._fit_result
    assert result.eta_fixed == 0.0 and result.background_at_limit
    assert fitting._lineshape_group.full_title() == "Lineshape: Gaussian"
    assert not _shown(fitting._name_labels["eta"])
    assert not _shown(fitting._result_labels["eta"])
    assert fitting._result_labels["background"].text() == "0 (at limit)"


def test_free_shape_shows_eta_with_its_error(docks):
    display, fitting, _ = docks
    x = np.linspace(-1.0, 1.0, 41)
    u = (x - 0.1) / 0.15
    voigt = 0.5 * np.exp(-0.5 * u ** 2) + 0.5 / (1.0 + (u / 1.1774) ** 2)
    _scan_counts(display, x, 20.0 + 1000.0 * voigt)
    fitting._on_fit_clicked()
    result = fitting._fit_result
    assert result.converged and result.eta_fixed is None
    title = fitting._lineshape_group.full_title()
    assert title == "Lineshape: " + scan_fits.lineshape_title(result)
    assert title.startswith("Lineshape: pseudo-Voigt, η = ")
    assert _shown(fitting._result_labels["eta"]) and "±" in fitting._result_labels["eta"].text()
    assert fitting._result_labels["background"].text().endswith("counts")
    # A new scan puts the plain title and the eta row back.
    _scan_peak(display)
    assert fitting._lineshape_group.full_title() == "Lineshape"


def test_intensity_rows_units_and_step(docks):
    display, fitting, _ = docks
    _scan_peak(display)                                      # step 0.1 in h
    fitting._on_fit_clicked()
    result, rows = fitting._fit_result, fitting._result_labels
    assert {fitting._name_labels[k].text() for k in ("integrated", "normalised", "raw")} \
        == {"Integrated", "Normalised", "Raw, range"}
    assert not any("Area" in label.text() for label in fitting._name_labels.values())
    assert rows["integrated"].text() == "%.6g ± %.3g counts" % (
        result.integrated, result.integrated_err)
    assert rows["normalised"].text() == "%.6g ± %.3g counts·r.l.u. (Δh = 0.1)" % (
        result.area, result.area_err)
    assert rows["raw"].text() == "%.6g ± %.3g counts" % (
        result.raw_counts, result.raw_counts_err)
    # The Normalised unit is spelled as Copy results spells it.
    tsv = scan_fits.results_tsv("h", result, fitting._com, fitting._max)
    unit_cell = next(line.split("\t")[3] for line in tsv.splitlines()
                     if line.startswith("Normalised\t"))
    assert unit_cell in rows["normalised"].text()
    for key, words in (("integrated", "halve the step and it doubles"),
                       ("normalised", "compare scans taken with different step"),
                       ("raw", "Model-free")):
        assert words in rows[key].toolTip()
        assert "not the area" not in rows[key].toolTip()
    assert "not to monitor" in rows["normalised"].toolTip()
    assert "tails" in rows["integrated"].toolTip()
    # Integrated and Raw agree only when no point in the range is missing.
    assert "every point in it was measured" in rows["raw"].toolTip()


def test_uneven_steps_and_unknown_unit(docks):
    display, fitting, _ = docks
    x = np.concatenate([np.linspace(-1.0, 0.0, 11), np.linspace(0.05, 1.0, 20)])
    counts = 20.0 + 1000.0 * np.exp(-0.5 * ((x - 0.1) / 0.15) ** 2)
    _scan_counts(display, x, np.random.default_rng(1).poisson(counts),
                 variable="mystery_axis")
    fitting._on_fit_clicked()
    result, rows = fitting._fit_result, fitting._result_labels
    assert result.converged and not result.steps_even
    assert rows["integrated"].text() == "uneven steps"
    assert rows["normalised"].text().endswith("counts × mystery_axis (uneven steps)")
    assert rows["raw"].text().endswith("counts")


def test_raw_error_unavailable_shows_the_value_alone(docks, monkeypatch):
    display, fitting, _ = docks
    real_fit = scan_fits.fit_peak
    monkeypatch.setattr(scan_fits, "fit_peak", lambda *a, **k: dataclasses.replace(
        real_fit(*a, **k), raw_counts_err=None))
    _scan_peak(display)
    fitting._on_fit_clicked()
    raw = fitting._result_labels["raw"]
    assert raw.text() == "%.6g counts" % fitting._fit_result.raw_counts
    assert "Error unavailable" in raw.toolTip()


def test_copy_results_puts_the_u1_text_on_the_clipboard(docks):
    display, fitting, _ = docks
    clipboard = QApplication.clipboard()
    _scan_peak(display)
    # No fit: COM and MAX only, and the status line says so.
    assert fitting.copy_results_button.isEnabled()
    fitting.copy_results_button.click()
    no_fit = scan_fits.QuickFitResult(converged=False, reason="no fit")
    assert clipboard.text() == scan_fits.results_tsv("h", no_fit, fitting._com,
                                                     fitting._max)
    assert [line.split("\t")[0] for line in clipboard.text().splitlines()] == [
        "quantity", "COM", "MAX"]
    assert "COM and MAX only" in fitting.status_label.text()
    # With a fit: the whole result.
    fitting._on_fit_clicked()
    fitting.copy_results_button.click()
    assert clipboard.text() == scan_fits.results_tsv(
        "h", fitting._fit_result, fitting._com, fitting._max)
    assert "Normalised\t" in clipboard.text()
    # Every value stays selectable text.
    for label in list(fitting._result_labels.values()) + [fitting.status_label]:
        assert label.textInteractionFlags() & Qt.TextSelectableByMouse
    assert not hasattr(fitting, "com_copy_button")
    assert not hasattr(fitting, "max_copy_button")


def test_copy_keeps_the_points_since_note_in_the_status(docks):
    display, fitting, _ = docks
    _scan_peak(display, measured=20)
    fitting._on_fit_clicked()
    display.update_1d_point(20, 5.0)           # a point arrives after the fit
    fitting.copy_results_button.click()
    # The copy message leads; the fit's own status line follows and carries the note.
    assert fitting.status_label.text() == (
        "Copied the fit results, COM and MAX to the clipboard. Fit converged. "
        "1 point(s) measured since this fit -- press Fit again to use them.")
    assert "predates" not in fitting.status_label.text()
    # Nothing measured after the fit: the copy message and the plain status.
    _scan_peak(display)
    fitting._on_fit_clicked()
    fitting.copy_results_button.click()
    assert fitting.status_label.text() == (
        "Copied the fit results, COM and MAX to the clipboard. Fit converged.")


def test_copy_keeps_the_fit_warnings_in_the_status(docks):
    display, fitting, _ = docks
    _scan_peak(display)
    fitting._on_fit_clicked()
    fitting._fit_result = dataclasses.replace(
        fitting._fit_result, warnings=["centre near the range edge"])
    fitting.copy_results_button.click()
    assert fitting.status_label.text() == (
        "Copied the fit results, COM and MAX to the clipboard. Fit converged. "
        "Warnings: centre near the range edge.")


def test_copy_keeps_the_noiseless_caveat(docks):
    display, fitting, controller = docks
    controller.last_scan_result = SimpleNamespace(metadata={"noiseless": True})
    _scan_peak(display)
    fitting._on_fit_clicked()
    fitting.copy_results_button.click()
    assert fitting.status_label.text().startswith(
        "Copied the fit results, COM and MAX to the clipboard. Fit converged.")
    assert "noiseless run" in fitting.status_label.text()
    # No fit: the copy message alone, with the caveat after it.
    _scan_peak(display)
    fitting.copy_results_button.click()
    assert fitting.status_label.text().startswith(
        "No fit for the current selection: copied COM and MAX only.")
    assert "noiseless run" in fitting.status_label.text()


def test_copy_after_a_failed_fit_keeps_the_reason(docks):
    display, fitting, _ = docks
    _scan_peak(display)
    fitting._on_span_selected(-0.25, 0.05)     # three points: too few to fit
    fitting._on_fit_clicked()
    assert fitting._fit_result is None
    assert "Fit failed: need at least 6" in fitting.status_label.text()
    fitting.copy_results_button.click()
    assert fitting.status_label.text().startswith(
        "No fit for the current selection: copied COM and MAX only. "
        "Fit failed: need at least 6")
    # A range change drops the failure: Copy no longer repeats it.
    fitting._on_span_selected(-0.6, 0.8)
    fitting.copy_results_button.click()
    assert fitting.status_label.text() == (
        "No fit for the current selection: copied COM and MAX only.")
    # So does a new scan, after a fresh failed fit.
    fitting._on_span_selected(-0.25, 0.05)
    fitting._on_fit_clicked()
    _scan_peak(display)
    fitting.copy_results_button.click()
    assert "Fit failed" not in fitting.status_label.text()


def test_without_a_scan_disabled_controls_say_why(docks):
    _display, fitting, _ = docks
    assert not fitting.copy_results_button.isEnabled()
    assert "nothing to copy" in fitting.copy_results_button.toolTip()
    for button in (fitting.fit_button, fitting.range_button,
                   fitting.range_clear_button, fitting.goto_cen_button,
                   fitting.goto_com_button, fitting.goto_max_button):
        assert not button.isEnabled()
        assert "no 1D scan is displayed" in button.toolTip()
    assert fitting.revert_button.toolTip() == "nothing to revert"
    # A 1D scan with nothing measured yet: the click says so, nothing copied.
    display = _display
    display.initialize_scan("1D", [0.0, 0.1, 0.2], [True] * 3, "h")
    QApplication.clipboard().setText("untouched")
    fitting.copy_results_button.click()
    assert QApplication.clipboard().text() == "untouched"
    assert fitting.status_label.text().startswith("Nothing to copy")


def test_a_2d_scan_says_why_each_control_is_off(docks):
    display, fitting, _ = docks
    _scan_peak(display)
    fitting._on_fit_clicked()          # 1D tooltips are now set on every control
    display.initialize_scan(
        "2D", [0.0, 1.0], [], "a", "b", [0.0, 1.0],
        valid_mask_2d=np.ones((2, 2), dtype=bool))
    for button in (fitting.fit_button, fitting.range_button,
                   fitting.range_clear_button, fitting.goto_cen_button,
                   fitting.goto_com_button, fitting.goto_max_button,
                   fitting.revert_button, fitting.copy_results_button):
        assert not button.isEnabled()
        assert button.toolTip() == "The Fitting dock works on 1D scans only."


@pytest.fixture()
def windows_ui_font():
    """Measure with the font the real window uses (Segoe UI 9 pt on Windows).

    As ``test_compact_layout._use_windows_ui_font``: the offscreen platform's
    fallback glyphs are about twice Segoe UI's width.
    """
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf")
    if sys.platform == "win32" and os.path.exists(path):
        if QFontDatabase.addApplicationFont(path) < 0:
            pytest.fail("could not load %s" % path)
        app.setFont(QFont("Segoe UI", 9))
    yield
    app.setFont(font)


LONG_VARIABLE = "sample_turntable_rotation_angle"   # 31 characters


@pytest.mark.parametrize("tag, size", [("wide", (1400, 300)), ("narrow", (340, 700))])
def test_layout_reflows_without_clipping(windows_ui_font, docks, monkeypatch,
                                         tmp_path, tag, size):
    display, fitting, _ = docks
    # Let the long name drive a goto, so the Go buttons show enabled.
    monkeypatch.setattr(scan_fits, "field_for_scan_variable", lambda _name: "omega")
    x = np.linspace(-1.0, 1.0, 41)
    peak = 200.0 + 1e6 * np.exp(-0.5 * ((x - 0.1) / 0.15) ** 2)
    _scan_counts(display, x, np.random.default_rng(3).poisson(peak),
                 variable=LONG_VARIABLE)
    fitting._on_fit_clicked()
    assert fitting._fit_result.converged
    assert fitting._result_labels["integrated"].text().startswith("7.5")   # ~10^6 counts

    fitting.resize(*size)
    fitting.show()
    for _ in range(5):
        QApplication.processEvents()

    groups = [fitting._position_group, fitting._lineshape_group,
              fitting._intensity_group]
    assert groups[0].full_title() == "Position (%s)" % LONG_VARIABLE
    rects = [QRect(g.mapTo(fitting, QPoint(0, 0)), g.size()) for g in groups]
    if tag == "wide":
        assert fitting._groups_layout.direction() == QBoxLayout.LeftToRight
        assert len({r.top() for r in rects}) == 1
        assert all(a.right() < b.left() for a, b in zip(rects, rects[1:]))
        # Side by side is never the cramped arrangement: every value on one line.
        wrapped = [label.text() for label in fitting._result_labels.values()
                   if label.isVisibleTo(fitting)
                   and label.height() > label.heightForWidth(100000)]
        assert not wrapped, wrapped
    else:
        assert fitting._groups_layout.direction() == QBoxLayout.TopToBottom
        assert len({r.left() for r in rects}) == 1
        assert all(a.bottom() < b.top() for a, b in zip(rects, rects[1:]))

    scroll = fitting._scroll_area
    viewport = scroll.viewport()
    content = scroll.widget()
    assert content.width() <= viewport.width(), "no horizontal scrolling"
    problems = []
    for widget in fitting.findChildren(QWidget):
        if not widget.isVisibleTo(fitting) or widget is content:
            continue    # the content widget may be taller than the viewport: it scrolls
        parent = widget.parentWidget()
        if parent is not None and not parent.rect().contains(widget.geometry()):
            problems.append("outside its parent: %r %s" % (
                getattr(widget, "text", lambda: "")(), type(widget).__name__))
        if isinstance(widget, (QLabel, QPushButton)) and widget.text():
            if widget.width() < widget.minimumSizeHint().width():
                problems.append("clipped: %r" % widget.text())
            if isinstance(widget, QLabel) and widget.wordWrap() \
                    and widget.height() < widget.heightForWidth(widget.width()):
                problems.append("wrapped text cut off: %r" % widget.text())
    for group in groups:
        if group.title() != group.full_title() and group.toolTip() != group.full_title():
            problems.append("title elided without its full text: %r" % group.title())
    assert not problems, problems

    cen = fitting.goto_cen_button
    assert cen.isEnabled()
    if tag == "wide":
        on_screen = QRect(cen.mapTo(viewport, QPoint(0, 0)), cen.size())
        assert viewport.rect().contains(on_screen), "Go on the CEN row needs a scroll"

    shot = tmp_path / ("fitting_%s.png" % tag)
    assert fitting.grab().save(str(shot))
    print("screenshot:", shot)


def test_a_title_too_long_for_the_dock_elides_with_its_full_text(windows_ui_font, docks):
    display, fitting, _ = docks
    variable = "a_scan_variable_name_far_too_long_for_any_narrow_dock_column"
    _scan_counts(display, np.linspace(0.0, 1.0, 11), np.arange(11.0), variable=variable)
    fitting.resize(340, 700)
    fitting.show()
    for _ in range(5):
        QApplication.processEvents()
    group = fitting._position_group
    assert group.full_title() == "Position (%s)" % variable
    assert group.title() != group.full_title() and group.title().endswith("…")
    assert group.toolTip() == group.full_title()
    assert fitting._scroll_area.widget().width() <= fitting._scroll_area.viewport().width()
