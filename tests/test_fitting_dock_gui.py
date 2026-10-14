"""Offscreen-Qt checks of the Fitting dock with the real Display dock.

The docks are built the lightest way the code allows: a ``DisplayDock`` and a
``FittingDock(display_dock=...)`` with no main window, no controller and no
McStas.  ``_wire`` repeats the two lifecycle connections of
``gui/main_window.py::_connect_dock_signals`` (a source-text test pins that the
real window makes the same ones).  The controller is a stand-in that records
the goto calls.  Nothing is shown; ``QT_QPA_PLATFORM=offscreen``.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.docks.display_dock import DisplayDock  # noqa: E402
from gui.docks.fitting_dock import FittingDock  # noqa: E402

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
