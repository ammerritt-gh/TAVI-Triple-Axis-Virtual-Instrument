"""Fitting dock for TAVI -- quick peak fit of the displayed 1D scan + goto.

This is the GUI half of ``docs/CONTROL_FEATURES_DESIGN.md`` §1 ("goto CEN"):
the operator runs a 1D scan, optionally restricts the abscissa range, presses
**Fit**, and drives the scanned variable to the fitted centre, the centre of
mass, or the highest measured bin.

Three ownership rules shape this file:

* **No arithmetic here.**  Every number comes from ``tavi.scan_fits`` (Qt-free,
  unit-tested there): :func:`~tavi.scan_fits.com`,
  :func:`~tavi.scan_fits.peak_max`, :func:`~tavi.scan_fits.fit_peak` (with its
  intensity readout), the lineshape title, the scan variable's unit, the
  Copy-results text, and the scan-variable -> parameter-field table.  The dock
  formats and never re-implements the mapping or decides the goto policy.
* **No widget writes outside the dock.**  Moving the instrument goes through
  ``TAVIController.goto_scan_variable`` / ``revert_last_goto``, which own the
  refusal, the message centre entry, and the journal record.
* **The scan data is read through one accessor.**  ``DisplayDock.scan_snapshot()``
  hands over copies; this dock never reaches into the display dock's private
  arrays, so the two can evolve independently.

The layout: one top row (range controls, Fit), then the Position, Lineshape and
Intensity groups -- side by side when the dock is wide enough for them, stacked
in the same order when it is not -- then one status line with Copy results.

The overlay artists (fit curve, centre line, range shading) are drawn on the
display dock's axes but *owned here*: they are created, invalidated and dropped
by this dock alone.

Gating is deliberately soft (see ``CONTROL_FEATURES_DESIGN.md`` §1.6 and the
2026-07-26 status note appended to it): only a missing or failed fit disables
CEN's Go.  A converged fit with warnings stays enabled and turns amber, with
the warnings in its tooltip -- the operator judges, with the overlay in view.

Everything in this module runs on the GUI thread.  The fit is milliseconds for
the scan sizes TAVI produces, so it runs synchronously; there is no worker.
"""
import logging

import numpy as np

from PySide6.QtWidgets import (QApplication, QBoxLayout, QGroupBox, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QStyle, QStyleOptionGroupBox,
                               QWidget)
from PySide6.QtCore import Qt, Slot, QEvent, QSize

from matplotlib.widgets import SpanSelector

from gui import theme
from gui.docks.base_dock import BaseDockWidget
from tavi import scan_fits

log = logging.getLogger(__name__)

#: CEN's Go when the fit converged with warnings or points arrived since it.
_WARNING_STYLE = "background-color: %s; color: %s;" % (theme.WARNING_FILL,
                                                       theme.WARNING_TEXT)

#: Colours of the artists this dock owns on the display dock's axes.
_CURVE_COLOR = "#d62728"
_CENTER_COLOR = "#7f2020"
_SPAN_COLOR = "#ffb000"

#: Toolbar modes that must be switched off before the span selector is usable.
#: ``NavigationToolbar2.mode`` stringifies to exactly these labels.
_TOOLBAR_PAN = "pan/zoom"
_TOOLBAR_ZOOM = "zoom rect"

#: Group titles.
_POSITION_TITLE = "Position"
_LINESHAPE_TITLE = "Lineshape"
_INTENSITY_TITLE = "Intensity, background removed"

#: Row labels, each in one place so a rename is a one-line change.
_ROW_LABELS = {
    "cen": "CEN",
    "com": "COM",
    "max": "MAX",
    "eta": "η",
    "fwhm": "FWHM",
    "height": "Height",
    "background": "Background",
    "quality": "Fit quality",
    "integrated": "Integrated",
    "normalised": "Normalised",
    "raw": "Raw, range",
}
_POSITION_ROWS = ("cen", "com", "max")
_LINESHAPE_ROWS = ("eta", "fwhm", "height", "background", "quality")
_INTENSITY_ROWS = ("integrated", "normalised", "raw")
#: Every row the fit fills; COM and MAX come from the scan, not the fit.
_FIT_ROWS = ("cen",) + _LINESHAPE_ROWS + _INTENSITY_ROWS

#: What each row's number is, its unit, and when to use it.
_ROW_TIPS = {
    "cen": "Fitted peak centre ± its error, from the fit (it can lie between "
           "measured points).",
    "com": "Centre of mass: the counts-weighted mean position of the measured "
           "points in the selection.",
    "max": "Highest measured bin - not interpolated",
    "eta": "Lorentzian fraction of the pseudo-Voigt: 0 is pure Gaussian, "
           "1 pure Lorentzian.",
    "fwhm": "Full width at half maximum of the fitted peak, in the scan "
            "variable's unit.",
    "height": "Fitted peak height above the background, in counts per point.",
    "background": "Fitted flat background, in counts per point. "
                  "\"0 (at limit)\": the fit pushed it to its lower bound, "
                  "zero, where an error bar would mean nothing.",
    "quality": "Reduced deviance: the Poisson deviance per degree of freedom, "
               "about 1 for a good fit. Then the points fitted (n) and the "
               "degrees of freedom (dof).",
    "integrated": "Integrated intensity, in counts: the fitted peak's summed "
                  "counts at this scan's points, background removed (the fit's "
                  "area divided by the step). It depends on the step: halve "
                  "the step and it doubles. Use it to read the peak against "
                  "the plotted counts.\n\"uneven steps\": the fitted points are "
                  "not evenly spaced, so no single step converts the area to "
                  "counts.",
    "normalised": "Normalised intensity, in counts × the scan variable's unit: "
                  "the fit's Area parameter, equal to Integrated × step. It "
                  "does not depend on the step: use it to compare scans taken "
                  "with different step sizes. The step it relates to is shown "
                  "after it.",
    "raw": "Raw counts over the fit range, in counts: the measured counts minus "
           "the fitted background, summed over the points the fit used. "
           "Model-free, and covers only what was measured: use it to check "
           "Integrated.",
}
_RAW_ERROR_UNAVAILABLE = ("\nError unavailable: the fit could not determine "
                          "the background's error.")

_RANGE_TIP = ("Drag on the plot to pick the abscissa window the fit uses.\n"
              "Pan/zoom is switched off while this is active.")
_CLEAR_TIP = "Fit the whole scan again."
_FIT_TIP = ("Fit a pseudo-Voigt + flat background to the selection.\n"
            "Never runs by itself -- press it again after more points arrive.")
_NO_SCAN_TIP = "no 1D scan is displayed -- run or load one"

_COPY_TIP = ("Puts the whole result on the clipboard as tab-separated text "
             "(quantity, value, error, unit), ready to paste into a notebook "
             "or spreadsheet. With no fit, copies COM and MAX only.")


def _fmt(value, digits=6):
    """Compact display for a single number; ``None`` becomes ``'-'``."""
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        log.warning("fitting dock: unformattable value %r: %s", value, exc)
        return str(value)
    if not np.isfinite(number):
        return str(number)
    return "%.*g" % (digits, number)


def _fmt_pm(value, error):
    """``value ± err`` for the readout; a missing error prints ``± ?``."""
    if value is None:
        return "-"
    if error is None:
        return "%s ± ?" % _fmt(value)
    return "%s ± %s" % (_fmt(value), _fmt(error, 3))


def _with_unit(text, unit):
    """``text unit``, or ``text`` alone when there is no unit or no value."""
    return "%s %s" % (text, unit) if unit and text != "-" else text


class _ValueLabel(QLabel):
    """Selectable text that wraps at spaces rather than clip in a narrow dock.

    It prefers one line: QLabel's word-wrap size hint folds any text over
    about twenty characters onto two, which would put the groups side by side
    with every value wrapped. The minimum stays QLabel's, the longest word.
    """

    def __init__(self, text="-"):
        super().__init__(text)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def sizeHint(self):
        hint = super().sizeHint()
        margins = self.contentsMargins()
        line = max(self.fontMetrics().horizontalAdvance(text)
                   for text in self.text().split("\n"))
        width = max(hint.width(), line + margins.left() + margins.right()
                    + 2 * self.margin() + 1)   # 1: advance-to-layout rounding
        return QSize(width, self.heightForWidth(width))


class _TitledGroup(QGroupBox):
    """A group box whose title elides to its width, full title as tooltip.

    QGroupBox makes its minimum width the title's width, so a long scan
    variable in "Position (...)" would push the group past a narrow dock.
    Here the title prefers its full width (``sizeHint``) but never widens the
    minimum: below that it elides.
    """

    def __init__(self, title):
        super().__init__(title)
        self._full_title = title

    def full_title(self):
        return self._full_title

    def set_full_title(self, title):
        if title == self._full_title:
            return
        self._full_title = title
        self._elide_title()
        self.updateGeometry()

    def _title_overhead(self):
        """Width the group's frame adds around its title text."""
        option = QStyleOptionGroupBox()
        self.initStyleOption(option)
        metrics = self.fontMetrics()
        frame = self.style().sizeFromContents(
            QStyle.CT_GroupBox, option, QSize(0, metrics.height()), self)
        return frame.width() + metrics.horizontalAdvance(" ")

    def minimumSizeHint(self):
        return QWidget.minimumSizeHint(self)

    def sizeHint(self):
        hint = super().sizeHint()
        title = (self._title_overhead()
                 + self.fontMetrics().horizontalAdvance(self._full_title))
        return QSize(max(hint.width(), title), hint.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_title()

    def _elide_title(self):
        room = max(0, self.width() - self._title_overhead())
        text = self.fontMetrics().elidedText(self._full_title, Qt.ElideRight, room)
        if text != self.title():
            self.setTitle(text)
        self.setToolTip(self._full_title if text != self._full_title else "")


class FittingDock(BaseDockWidget):
    """Range selection, quick fit, the Position/Lineshape/Intensity readout,
    the per-row Go buttons, and Copy results."""

    def __init__(self, parent=None, display_dock=None):
        super().__init__("Fitting", parent, use_scroll_area=True)
        self.setObjectName("FittingDock")

        # The dock the scan data and the plot axes come from, and the
        # controller the goto is routed through. Both may be absent early in
        # construction; every user action tolerates that.
        self._display = display_dock
        self._controller = None

        # --- analysis state -------------------------------------------------
        # Selected abscissa window, or None for "the whole scan".
        self._range = None
        # Last converged fit that is still valid for the current scan+range;
        # None means CEN's Go has nothing to act on.
        self._fit_result = None
        # How many points that fit saw. Mid-scan fitting is allowed, so the
        # scan can grow underneath a perfectly valid fit; this is what lets
        # the dock say so instead of quietly presenting a stale centre.
        self._fit_n_points = None
        # Warm start for the next fit of the same scan+range, dropped whenever
        # the fit is invalidated.
        self._seed = None
        self._com = None
        self._max = None

        # --- artists this dock owns on the display dock's axes ---------------
        self._curve_artist = None
        self._center_artist = None
        self._span_artist = None
        self._span_selector = None

        self._build_ui()
        self._refresh_all()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = self.content_layout

        # Shown instead of the controls when the display holds a 2D scan.
        self._notice_label = QLabel("1D scans only")
        self._notice_label.setAlignment(Qt.AlignCenter)
        self._notice_label.setStyleSheet("color: #b06000; font-weight: bold;")
        self._notice_label.setVisible(False)
        layout.addWidget(self._notice_label)

        # Everything else lives in one container so the 2D case is a single
        # setEnabled(False) rather than a list of widgets to keep in sync.
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        layout.addWidget(self._body)
        layout.addStretch(1)

        # Value labels by row key, and the name label beside each.
        self._result_labels = {}
        self._name_labels = {}

        self._top_layout = self._build_top_row()
        body_layout.addLayout(self._top_layout)

        self._groups = (self._build_position_group(),
                        self._build_lineshape_group(),
                        self._build_intensity_group())
        self._groups_layout = QBoxLayout(QBoxLayout.TopToBottom)
        self._groups_layout.setSpacing(8)
        for group in self._groups:
            self._groups_layout.addWidget(group, 0, Qt.AlignTop)
        body_layout.addLayout(self._groups_layout)

        body_layout.addLayout(self._build_status_row())

        # Reflow on a dock resize and when the groups' preferred widths change.
        self._scroll_area.installEventFilter(self)
        self._body.installEventFilter(self)

    def _build_top_row(self):
        """Range controls and Fit: one row when wide, two lines when narrow."""
        self.range_button = QPushButton("Select on plot")
        self.range_button.setCheckable(True)
        self.range_button.setToolTip(_RANGE_TIP)
        self.range_button.toggled.connect(self._on_range_button_toggled)

        self.range_min_edit = QLineEdit()
        self.range_min_edit.setPlaceholderText("full scan")
        self.range_min_edit.editingFinished.connect(self._on_range_fields_edited)
        self.range_max_edit = QLineEdit()
        self.range_max_edit.setPlaceholderText("full scan")
        self.range_max_edit.editingFinished.connect(self._on_range_fields_edited)

        self.range_clear_button = QPushButton("Clear")
        self.range_clear_button.setToolTip(_CLEAR_TIP)
        self.range_clear_button.clicked.connect(self._on_range_cleared)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip(_FIT_TIP)
        self.fit_button.clicked.connect(self._on_fit_clicked)

        self._range_part = QHBoxLayout()
        self._range_part.addWidget(self.range_button)
        self._range_part.addWidget(QLabel("min:"))
        self._range_part.addWidget(self.range_min_edit, 1)
        self._range_part.addWidget(QLabel("max:"))
        self._range_part.addWidget(self.range_max_edit, 1)

        self._fit_part = QHBoxLayout()
        self._fit_part.addWidget(self.range_clear_button)
        self._fit_part.addStretch(1)
        self._fit_part.addWidget(self.fit_button)

        top = QBoxLayout(QBoxLayout.TopToBottom)
        top.addLayout(self._range_part, 0)
        top.addLayout(self._fit_part, 1)
        return top

    def _add_rows(self, grid, keys, vertical=Qt.AlignTop):
        """A name label and a selectable value label per row key."""
        for row, key in enumerate(keys):
            name = QLabel(_ROW_LABELS[key])
            value = _ValueLabel()
            for label in (name, value):
                label.setToolTip(_ROW_TIPS[key])
            grid.addWidget(name, row, 0, Qt.AlignLeft | vertical)
            grid.addWidget(value, row, 1, vertical)
            self._name_labels[key] = name
            self._result_labels[key] = value
        grid.setColumnStretch(1, 1)

    def _build_position_group(self):
        group = _TitledGroup(_POSITION_TITLE)
        self._position_group = group
        grid = QGridLayout(group)
        grid.setVerticalSpacing(4)
        # Centred, so each value reads on the line of its Go.
        self._add_rows(grid, _POSITION_ROWS, Qt.AlignVCenter)

        # A Go at the end of each row: the button acts on its own row's value.
        self.goto_cen_button = QPushButton("Go")
        self.goto_com_button = QPushButton("Go")
        self.goto_max_button = QPushButton("Go")
        for row, (key, button) in enumerate((("cen", self.goto_cen_button),
                                             ("com", self.goto_com_button),
                                             ("max", self.goto_max_button))):
            button.setAccessibleName("Go to %s" % _ROW_LABELS[key])
            button.clicked.connect(lambda _checked=False, kind=key:
                                   self._on_goto_clicked(kind))
            grid.addWidget(button, row, 2)

        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self._on_revert_clicked)
        grid.addWidget(self.revert_button, len(_POSITION_ROWS), 2, Qt.AlignTop)
        return group

    def _build_lineshape_group(self):
        group = _TitledGroup(_LINESHAPE_TITLE)
        self._lineshape_group = group
        grid = QGridLayout(group)
        grid.setVerticalSpacing(4)
        self._add_rows(grid, _LINESHAPE_ROWS)
        return group

    def _build_intensity_group(self):
        group = _TitledGroup(_INTENSITY_TITLE)
        self._intensity_group = group
        grid = QGridLayout(group)
        grid.setVerticalSpacing(4)
        self._add_rows(grid, _INTENSITY_ROWS)
        return group

    def _build_status_row(self):
        row = QHBoxLayout()
        self.status_label = _ValueLabel("No fit yet.")
        row.addWidget(self.status_label, 1)

        self.copy_results_button = QPushButton("Copy results")
        self.copy_results_button.clicked.connect(self._on_copy_results)
        row.addWidget(self.copy_results_button, 0, Qt.AlignTop)
        return row

    # ------------------------------------------------------------------
    # Reflow
    # ------------------------------------------------------------------

    def eventFilter(self, watched, event):
        if ((watched is self._scroll_area and event.type() == QEvent.Resize)
                or (watched is self._body
                    and event.type() == QEvent.LayoutRequest)):
            self._reflow()
        return super().eventFilter(watched, event)

    def _wide(self):
        """True when the scroll area holds the three groups side by side.

        Measured against the groups' preferred widths (and the top row's), not
        their minimums, so side by side is never the cramped arrangement; the
        vertical scrollbar is reserved so it coming and going cannot flip the
        decision.
        """
        scroll = self._scroll_area
        bar = scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        room = scroll.width() - 2 * scroll.frameWidth() - bar
        spacing = self._groups_layout.spacing()
        groups = sum(group.sizeHint().width() for group in self._groups)
        groups += spacing * (len(self._groups) - 1)
        top = (self._range_part.sizeHint().width() + self._top_layout.spacing()
               + self._fit_part.sizeHint().width())
        return room >= max(groups, top)

    def _reflow(self):
        wide = self._wide()
        direction = QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom
        if self._groups_layout.direction() == direction:
            return
        self._top_layout.setDirection(direction)
        # No stretch factors: side by side each group gets its preferred width
        # plus an equal share of the spare (a stretch factor would ignore the
        # preferred widths); stacked, the dock's trailing stretch takes the
        # spare height.
        self._groups_layout.setDirection(direction)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_controller(self, controller):
        """Attach the controller the goto buttons drive.

        Until this is called the goto row stays disabled: there is nothing to
        move the instrument with.
        """
        self._controller = controller
        self._refresh_gating()

    def set_display_dock(self, display_dock):
        """Attach the display dock this dock reads scans and plots through."""
        self._display = display_dock
        self._refresh_all()

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------

    @Slot()
    def on_scan_reset(self):
        """A new scan (or a load) replaced the displayed data.

        The display dock has already cleared its axes at this point, so the
        overlay artists are gone as objects; this drops our references, the
        cached fit, the warm start, and the selected range -- a window picked
        on the previous scan's abscissa means nothing on the new one.
        """
        self._forget_artists()
        self._range = None
        self._set_range_fields(None)
        self._invalidate_fit()
        # The span selector lives on the axes that were just cleared; rebuild
        # it if the user left range selection switched on.
        if self.range_button.isChecked():
            self._teardown_span_selector()
            self._setup_span_selector()
        self._refresh_all()

    @Slot()
    def on_plot_rebuilt(self):
        """The display dock rebuilt its axes but kept the scan data.

        ``ax.clear()`` destroyed the overlay and the span selector's artists;
        redraw them from the state kept here (fit, range, range button). The
        cached fit, range, range fields and readout are left alone.
        """
        if not self._is_1d():
            return
        self._forget_artists()
        if self._fit_result is not None and self._fit_result.converged:
            self._draw_fit_artists(self._fit_result)
        self._draw_span()
        if self.range_button.isChecked():
            self._teardown_span_selector()
            self._setup_span_selector()
        self._refresh_gating()

    @Slot()
    def on_scan_finished(self):
        """The displayed scan finished (or a saved scan finished loading).

        Refreshes the cheap COM/MAX reductions and the button gating. The fit
        is *not* re-run: fitting is an explicit operator action.
        """
        self._refresh_gating()
        self._note_points_since_fit()

    @Slot()
    def refresh_gating(self, *args):
        """Recompute COM/MAX and re-evaluate button enablement.

        Connected to ``job_state_changed(str, str)``, so it accepts and
        ignores positional arguments. The COM/MAX refresh is part of the job:
        those are goto targets, and a job transition means the scan they were
        computed from may have moved on.
        """
        self._refresh_gating()
        self._note_points_since_fit()

    # ------------------------------------------------------------------
    # Scan data access
    # ------------------------------------------------------------------

    def _snapshot(self):
        """Current scan as ``DisplayDock.scan_snapshot()`` hands it over."""
        display = self._display
        if display is None:
            return None
        try:
            return display.scan_snapshot()
        except AttributeError as exc:
            log.warning("fitting dock: display dock has no scan_snapshot: %s", exc)
            return None

    def _variable_name(self):
        snapshot = self._snapshot()
        if not snapshot:
            return ""
        return snapshot.get("variable_name") or ""

    def _is_1d(self, snapshot=None):
        snapshot = self._snapshot() if snapshot is None else snapshot
        return bool(snapshot) and snapshot.get("mode") == "1D" \
            and snapshot.get("x") is not None

    def _busy(self):
        """True when a scan is queued or running, so nothing may be moved."""
        controller = self._controller
        if controller is None:
            return True
        try:
            return bool(controller._scan_busy())
        except AttributeError as exc:
            log.warning("fitting dock: controller has no _scan_busy: %s", exc)
            return True

    # ------------------------------------------------------------------
    # Range selection
    # ------------------------------------------------------------------

    def _on_range_button_toggled(self, checked):
        if checked:
            self._deactivate_navigation_tools()
            self._setup_span_selector()
        else:
            self._teardown_span_selector()

    def _deactivate_navigation_tools(self):
        """Switch pan/zoom off so drags reach the span selector.

        Nothing is restored when range selection is switched off again: the
        operator turned those tools on, and silently turning them back on
        later would be a surprise.
        """
        display = self._display
        toolbar = getattr(display, "toolbar", None)
        if toolbar is None:
            return
        mode = str(getattr(toolbar, "mode", "") or "")
        try:
            if mode == _TOOLBAR_PAN:
                toolbar.pan()
            elif mode == _TOOLBAR_ZOOM:
                toolbar.zoom()
        except Exception as exc:  # matplotlib backend differences
            log.warning("fitting dock: could not deactivate toolbar mode %r: %s",
                        mode, exc)

    def _setup_span_selector(self):
        ax = getattr(self._display, "ax", None)
        if ax is None:
            # Leaving the button checked would advertise a selection mode that
            # cannot work; put it back so the state on screen is the truth.
            log.warning("fitting dock: no axes to attach a span selector to")
            self.range_button.setChecked(False)
            return
        self._span_selector = SpanSelector(
            ax, self._on_span_selected, "horizontal", useblit=False,
            props=dict(alpha=0.25, facecolor=_SPAN_COLOR),
        )

    def _teardown_span_selector(self):
        selector = self._span_selector
        self._span_selector = None
        if selector is None:
            return
        try:
            selector.set_active(False)
            selector.disconnect_events()
        except Exception as exc:
            log.warning("fitting dock: span selector teardown failed: %s", exc)
        self._draw()

    def _on_span_selected(self, low, high):
        """The user dragged a window on the plot."""
        try:
            low, high = float(low), float(high)
        except (TypeError, ValueError) as exc:
            log.warning("fitting dock: unusable span %r/%r: %s", low, high, exc)
            return
        if not np.isfinite(low) or not np.isfinite(high) or low == high:
            self.status_label.setText("Ignored a zero-width range selection.")
            return
        self._set_range((min(low, high), max(low, high)))

    def _on_range_fields_edited(self):
        """min/max typed by hand -- parse both, or refuse the pair."""
        low_text = self.range_min_edit.text().strip()
        high_text = self.range_max_edit.text().strip()
        if not low_text and not high_text:
            self._set_range(None)
            return
        try:
            low = float(low_text)
            high = float(high_text)
        except ValueError:
            self.status_label.setText(
                "Range needs two numbers; the previous range is unchanged.")
            self._set_range_fields(self._range)
            return
        if not np.isfinite(low) or not np.isfinite(high) or low == high:
            self.status_label.setText("Range must have a non-zero width.")
            self._set_range_fields(self._range)
            return
        self._set_range((min(low, high), max(low, high)))

    def _on_range_cleared(self):
        self._set_range(None)

    def _set_range(self, window):
        """Adopt ``window`` (or ``None`` for the whole scan) and invalidate.

        Any previous fit described a different selection, so it is dropped
        together with its overlay and warm start.
        """
        self._range = window
        self._set_range_fields(window)
        self._invalidate_fit()
        self._draw_span()
        self._refresh_gating()

    def _set_range_fields(self, window):
        """Write the numeric fields without re-triggering the edit handler."""
        low_text = "" if window is None else "%.6g" % window[0]
        high_text = "" if window is None else "%.6g" % window[1]
        for edit, text in ((self.range_min_edit, low_text),
                           (self.range_max_edit, high_text)):
            blocked = edit.blockSignals(True)
            try:
                edit.setText(text)
            finally:
                edit.blockSignals(blocked)

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def _on_fit_clicked(self):
        snapshot = self._snapshot()
        if not self._is_1d(snapshot):
            self.status_label.setText("No 1D scan is displayed.")
            self._refresh_all()
            return

        result = scan_fits.fit_peak(
            snapshot["x"], snapshot["counts"], mask=snapshot["mask"],
            xrange=self._range, seed=self._seed,
        )

        self._remove_fit_artists()
        if result.converged:
            self._fit_result = result
            self._fit_n_points = int(snapshot.get("n_measured") or 0)
            self._seed = {
                "area": result.area, "fwhm": result.fwhm,
                "center": result.center, "eta": result.eta,
                "background": result.background,
            }
            self._draw_fit_artists(result)
        else:
            self._fit_result = None
            self._fit_n_points = None
            self._seed = None

        self._show_result(result)
        self._refresh_gating()

    def _clear_fit_rows(self):
        """Every fit-derived row back to '-', the lineshape title plain."""
        for key in _FIT_ROWS:
            self._result_labels[key].setText("-")
        self._set_row_visible("eta", True)
        self._result_labels["raw"].setToolTip(_ROW_TIPS["raw"])
        self._lineshape_group.set_full_title(_LINESHAPE_TITLE)

    def _set_row_visible(self, key, visible):
        self._name_labels[key].setVisible(visible)
        self._result_labels[key].setVisible(visible)

    def _invalidate_fit(self):
        """Drop the cached fit, its warm start, its overlay, and the readout."""
        self._fit_result = None
        self._fit_n_points = None
        self._seed = None
        self._remove_fit_artists()
        self._clear_fit_rows()
        self.status_label.setText("No fit for the current selection.")

    def _show_result(self, result):
        """Fill the fit rows, the lineshape title and the status line."""
        if not result.converged:
            self._clear_fit_rows()
            self._show_status(result)
            return

        rows = self._result_labels
        variable = self._variable_name() or "x"
        unit = scan_fits.scan_variable_unit(variable)

        rows["cen"].setText(_with_unit(_fmt_pm(result.center, result.center_err),
                                       unit))
        self._lineshape_group.set_full_title(
            "%s: %s" % (_LINESHAPE_TITLE, scan_fits.lineshape_title(result)))
        # A pinned shape is named in the title; its eta is not a fitted number.
        self._set_row_visible("eta", result.eta_fixed is None)
        rows["eta"].setText(_fmt_pm(result.eta, result.eta_err))
        rows["fwhm"].setText(_with_unit(_fmt_pm(result.fwhm, result.fwhm_err),
                                        unit))
        rows["height"].setText(
            _with_unit(_fmt_pm(result.height, result.height_err), "counts"))
        if result.background_at_limit:
            rows["background"].setText("0 (at limit)")
        else:
            rows["background"].setText(_with_unit(
                _fmt_pm(result.background, result.background_err), "counts"))
        rows["quality"].setText("%s (n / dof %d / %d)" % (
            _fmt(result.deviance_reduced, 4), result.n_points, result.dof))

        if result.steps_even:
            rows["integrated"].setText(_with_unit(
                _fmt_pm(result.integrated, result.integrated_err), "counts"))
            step_note = "(Δ%s = %s)" % (variable, _fmt(result.step))
        else:
            rows["integrated"].setText("uneven steps")
            step_note = "(uneven steps)"
        # Spelled as scan_fits.results_tsv spells the Normalised unit cell.
        norm_unit = "counts·%s" % unit if unit else "counts × %s" % variable
        rows["normalised"].setText("%s %s %s" % (
            _fmt_pm(result.area, result.area_err), norm_unit, step_note))
        if result.raw_counts_err is None:
            rows["raw"].setText(_with_unit(_fmt(result.raw_counts), "counts"))
            rows["raw"].setToolTip(_ROW_TIPS["raw"] + _RAW_ERROR_UNAVAILABLE)
        else:
            rows["raw"].setText(_with_unit(
                _fmt_pm(result.raw_counts, result.raw_counts_err), "counts"))
            rows["raw"].setToolTip(_ROW_TIPS["raw"])

        self._show_status(result)

    def _show_status(self, result):
        """The status line: outcome, warnings, points since the fit, caveat."""
        parts = []
        if result.converged:
            parts.append("Fit converged.")
        else:
            parts.append("Fit failed: %s" % (result.reason or "unknown reason"))
        if result.warnings:
            parts.append("Warnings: " + "; ".join(result.warnings) + ".")
        arrived = self._points_since_fit() if result.converged else 0
        if arrived:
            parts.append("%d point(s) measured since this fit -- press Fit "
                         "again to use them." % arrived)
        caveat = self._noiseless_caveat()
        if caveat:
            parts.append(caveat)
        self.status_label.setText(" ".join(parts))

    def _note_points_since_fit(self):
        """Restate the fit's status once points have arrived since it."""
        if self._fit_result is not None and self._points_since_fit():
            self._show_status(self._fit_result)

    def _noiseless_caveat(self):
        """Note for a deterministic noiseless run, whose sigma is nominal."""
        controller = self._controller
        result = getattr(controller, "last_scan_result", None) if controller else None
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("noiseless"):
            return "noiseless run - σ nominal"
        return ""

    # ------------------------------------------------------------------
    # COM / MAX
    # ------------------------------------------------------------------

    def _refresh_estimates(self):
        """Recompute COM and MAX over the current selection (cheap)."""
        snapshot = self._snapshot()
        if not self._is_1d(snapshot):
            self._com = None
            self._max = None
        else:
            self._com = scan_fits.com(
                snapshot["x"], snapshot["counts"], mask=snapshot["mask"],
                xrange=self._range)
            self._max = scan_fits.peak_max(
                snapshot["x"], snapshot["counts"], mask=snapshot["mask"],
                xrange=self._range)

        variable = self._variable_name()
        self._position_group.set_full_title(
            "%s (%s)" % (_POSITION_TITLE, variable) if variable else _POSITION_TITLE)
        unit = scan_fits.scan_variable_unit(variable)
        self._set_estimate_row("com", self._com, unit)
        self._set_estimate_row("max", self._max, unit)

        max_label = self._result_labels["max"]
        if self._max is not None and self._max.ok:
            width = self._max.bin_width
            max_label.setToolTip(
                "Highest measured bin (width %s) - not interpolated"
                % _fmt(width, 4))
        else:
            max_label.setToolTip(_ROW_TIPS["max"])

    def _set_estimate_row(self, key, estimate, unit):
        label = self._result_labels[key]
        if estimate is not None and estimate.ok:
            label.setText(_with_unit(_fmt(estimate.x), unit))
        else:
            reason = estimate.reason if estimate is not None else "no scan"
            label.setText(reason or "unavailable")

    # ------------------------------------------------------------------
    # Copy results
    # ------------------------------------------------------------------

    def _on_copy_results(self):
        """Put the whole result on the clipboard as ``scan_fits.results_tsv``."""
        self._refresh_estimates()
        com, peak = self._com, self._max
        result = self._fit_result
        if com is None or peak is None or not (result is not None or com.ok
                                               or peak.ok):
            self.status_label.setText("Nothing to copy: no fit, COM or MAX.")
            self._refresh_gating()
            return
        if result is None:
            result = scan_fits.QuickFitResult(converged=False, reason="no fit")
        text = scan_fits.results_tsv(self._variable_name() or "x", result,
                                     com, peak)
        QApplication.clipboard().setText(text)
        if result.converged:
            copied = "Copied the fit results, COM and MAX to the clipboard."
        else:
            copied = "No fit for the current selection: copied COM and MAX only."
        # Prefix, not replace: the fit's status keeps its warnings and caveats.
        if self._fit_result is not None:
            self._show_status(self._fit_result)
            copied += " " + self.status_label.text()
        else:
            caveat = self._noiseless_caveat()
            if caveat:
                copied += " " + caveat
        self.status_label.setText(copied)

    # ------------------------------------------------------------------
    # Goto
    # ------------------------------------------------------------------

    def _target_for(self, kind):
        """``(value, label)`` for a goto button, or ``(None, label)``."""
        if kind == "com":
            estimate = self._com
            value = estimate.x if (estimate is not None and estimate.ok) else None
            return value, "goto COM"
        if kind == "max":
            estimate = self._max
            value = estimate.x if (estimate is not None and estimate.ok) else None
            return value, "goto MAX"
        result = self._fit_result
        value = result.center if (result is not None and result.converged) else None
        return value, "goto CEN"

    def _on_goto_clicked(self, kind):
        controller = self._controller
        if controller is None:
            self.status_label.setText("Controller not ready.")
            return
        # This is a motion command, so the target is derived from the scan as
        # it is at this instant -- not from whatever the readout was showing
        # when gating last ran. COM and MAX are recomputed here; CEN comes
        # from the cached fit by design (fitting is an explicit action, and a
        # fit that predates newer points is disclosed on the button itself).
        if kind in ("com", "max"):
            self._refresh_estimates()
        value, label = self._target_for(kind)
        if value is None:
            self.status_label.setText("%s: no value available." % label)
            self._refresh_gating()
            return
        # The controller re-derives busy and the field mapping and refuses
        # safely; the dock only reports what came back.
        ok, message = controller.goto_scan_variable(
            self._variable_name(), value, label=label)
        self.status_label.setText(message)
        if not ok:
            log.info("fitting dock: %s", message)
        self._refresh_gating()

    def _on_revert_clicked(self):
        controller = self._controller
        if controller is None:
            self.status_label.setText("Controller not ready.")
            return
        ok, message = controller.revert_last_goto()
        self.status_label.setText(message)
        if not ok:
            log.info("fitting dock: %s", message)
        self._refresh_gating()

    # ------------------------------------------------------------------
    # Overlay artists (owned here, drawn on the display dock's axes)
    # ------------------------------------------------------------------

    def _axes(self):
        return getattr(self._display, "ax", None)

    def _draw(self):
        canvas = getattr(self._display, "canvas", None)
        if canvas is None:
            return
        canvas.draw_idle()

    def _remove_artist(self, artist):
        """Remove one artist, tolerating axes that were cleared underneath."""
        if artist is None:
            return
        try:
            artist.remove()
        except (ValueError, NotImplementedError, AttributeError) as exc:
            log.debug("fitting dock: artist already gone: %s", exc)

    def _remove_fit_artists(self):
        self._remove_artist(self._curve_artist)
        self._remove_artist(self._center_artist)
        self._curve_artist = None
        self._center_artist = None
        self._draw()

    def _forget_artists(self):
        """Drop every artist reference after the axes were cleared elsewhere.

        ``DisplayDock.initialize_scan`` calls ``ax.clear()``, so the artists
        are already detached; calling ``remove()`` on them would raise.
        """
        self._curve_artist = None
        self._center_artist = None
        self._span_artist = None

    def _draw_fit_artists(self, result):
        ax = self._axes()
        if ax is None or result.curve_x is None or result.curve_y is None:
            return
        self._curve_artist, = ax.plot(
            result.curve_x, result.curve_y, color=_CURVE_COLOR, linewidth=1.5,
            zorder=5, label="_fit")
        if result.center is not None:
            self._center_artist = ax.axvline(
                result.center, color=_CENTER_COLOR, linestyle="--",
                linewidth=1.2, zorder=5)
        self._draw()

    def _draw_span(self):
        """Repaint the persistent shading for the selected range."""
        self._remove_artist(self._span_artist)
        self._span_artist = None
        ax = self._axes()
        if ax is not None and self._range is not None:
            self._span_artist = ax.axvspan(
                self._range[0], self._range[1], color=_SPAN_COLOR, alpha=0.15,
                zorder=0)
        self._draw()

    # ------------------------------------------------------------------
    # Enablement
    # ------------------------------------------------------------------

    def _refresh_all(self):
        self._refresh_gating()

    def _refresh_gating(self):
        # COM and MAX are goto targets, so they are recomputed here rather
        # than only on the paths that happen to think of it: every event that
        # can change enablement (scan finished, job state changed, range
        # edited, fit pressed) can also have changed the data underneath the
        # readouts, and a button offering a frozen value is a motion hazard.
        # Both reductions are a couple of numpy passes -- cheap enough to run
        # unconditionally.
        self._refresh_estimates()

        snapshot = self._snapshot()
        is_1d = self._is_1d(snapshot)
        has_scan = bool(snapshot) and snapshot.get("mode") is not None

        # 2D (or a scan of an unknown mode): the whole body is meaningless.
        two_d = has_scan and not is_1d
        self._notice_label.setVisible(two_d)
        self._body.setEnabled(not two_d)
        if two_d:
            self._forget_and_clear_overlay()
            return

        for button, tip in ((self.fit_button, _FIT_TIP),
                            (self.range_button, _RANGE_TIP),
                            (self.range_clear_button, _CLEAR_TIP)):
            button.setEnabled(is_1d)
            button.setToolTip(tip if is_1d else _NO_SCAN_TIP)

        variable = self._variable_name()
        field = scan_fits.field_for_scan_variable(variable) if variable else None
        idle = not self._busy()
        goto_reason = ""
        if not is_1d:
            goto_reason = "no 1D scan is displayed"
        elif field is None:
            goto_reason = "scan variable '%s' is unknown" % variable
        elif not idle:
            goto_reason = "a scan is running or queued"
        can_goto = not goto_reason

        for button, kind in ((self.goto_com_button, "com"),
                             (self.goto_max_button, "max")):
            value, _label = self._target_for(kind)
            button.setEnabled(bool(can_goto and value is not None))
            if goto_reason:
                button.setToolTip(goto_reason)
            elif value is None:
                button.setToolTip("no value available")
            else:
                button.setToolTip(self._go_tip(kind, variable, value))

        self._refresh_cen_button(can_goto, goto_reason, variable)

        controller = self._controller
        can_revert = False
        if controller is not None:
            try:
                can_revert = bool(controller.can_revert_goto())
            except AttributeError as exc:
                log.warning("fitting dock: controller has no can_revert_goto: %s",
                            exc)
        self.revert_button.setEnabled(bool(can_revert and idle))
        if not can_revert:
            self.revert_button.setToolTip("nothing to revert")
        elif not idle:
            self.revert_button.setToolTip("a scan is running or queued")
        else:
            self.revert_button.setToolTip("Undo the last goto.")

        # Gated on the scan alone: COM and MAX move with every point, and the
        # click re-derives them, so a mid-scan copy is never refused on a
        # reading taken before the points arrived.
        self.copy_results_button.setEnabled(is_1d)
        self.copy_results_button.setToolTip(
            _COPY_TIP if is_1d else "nothing to copy -- no 1D scan is displayed")

    @staticmethod
    def _go_tip(kind, variable, value):
        """A Go button's "this affects ___" sentence."""
        return "Drives %s to this row's value: %s = %s." % (
            variable, _ROW_LABELS[kind], _fmt(value))

    def _refresh_cen_button(self, can_goto, goto_reason, variable):
        """Three-state soft gate on CEN's Go.

        Disabled only when there is no converged fit for the current selection
        (or the goto itself is impossible); amber with the warnings in its
        tooltip when the fit converged with flags; plain when it is clean.
        """
        result = self._fit_result
        button = self.goto_cen_button
        if result is None or not result.converged:
            button.setEnabled(False)
            button.setStyleSheet("")
            button.setToolTip(goto_reason or
                              "no converged fit for the current scan and range "
                              "-- press Fit")
            return
        button.setEnabled(bool(can_goto))
        if not can_goto:
            button.setStyleSheet("")
            button.setToolTip(goto_reason)
            return
        target = self._go_tip("cen", variable, result.center)
        notes = list(result.warnings)
        arrived = self._points_since_fit()
        if arrived:
            notes.append(
                "%d point(s) measured since this fit -- press Fit again to use them"
                % arrived)
        if notes:
            button.setStyleSheet(_WARNING_STYLE)
            button.setToolTip(target + "\nFit warnings:\n- " + "\n- ".join(notes))
        else:
            button.setStyleSheet("")
            button.setToolTip(target)

    def _points_since_fit(self):
        """Points measured since the cached fit ran.

        Mid-scan fitting is allowed, so a converged fit routinely describes
        fewer points than the plot now shows. That does not invalidate it --
        the centre is a real target computed from real data -- but presenting
        it without saying so would let an operator drive to a peak position
        the rest of the scan has since moved.
        """
        if self._fit_result is None or self._fit_n_points is None:
            return 0
        snapshot = self._snapshot()
        if not self._is_1d(snapshot):
            return 0
        return max(0, int(snapshot.get("n_measured") or 0) - self._fit_n_points)

    def _forget_and_clear_overlay(self):
        """2D scan: no overlay -- and no stale readout -- may survive.

        The numbers on screen described a 1D scan that is no longer displayed;
        leaving them visible above a disabled body reads as "these are your
        results" for data they were never computed from.
        """
        self._remove_fit_artists()
        self._remove_artist(self._span_artist)
        self._span_artist = None
        self._fit_result = None
        self._fit_n_points = None
        self._seed = None
        self._clear_fit_rows()
        self.status_label.setText("2D scan displayed - fitting is 1D only.")
        self._draw()
