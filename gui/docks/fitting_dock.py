"""Fitting dock for TAVI -- quick peak fit of the displayed 1D scan + goto.

This is the GUI half of ``docs/CONTROL_FEATURES_DESIGN.md`` §1 ("goto CEN"):
the operator runs a 1D scan, optionally restricts the abscissa range, presses
**Fit**, and drives the scanned variable to the fitted centre, the centre of
mass, or the highest measured bin.

Three ownership rules shape this file:

* **No arithmetic here.**  Every number comes from ``tavi.scan_fits`` (Qt-free,
  unit-tested there): :func:`~tavi.scan_fits.com`,
  :func:`~tavi.scan_fits.peak_max`, :func:`~tavi.scan_fits.fit_peak`, and the
  scan-variable -> parameter-field table.  The dock never re-implements the
  mapping and never decides the goto policy.
* **No widget writes outside the dock.**  Moving the instrument goes through
  ``TAVIController.goto_scan_variable`` / ``revert_last_goto``, which own the
  refusal, the message centre entry, and the journal record.
* **The scan data is read through one accessor.**  ``DisplayDock.scan_snapshot()``
  hands over copies; this dock never reaches into the display dock's private
  arrays, so the two can evolve independently.

The overlay artists (fit curve, centre line, range shading) are drawn on the
display dock's axes but *owned here*: they are created, invalidated and dropped
by this dock alone.

Gating is deliberately soft (see ``CONTROL_FEATURES_DESIGN.md`` §1.6 and the
2026-07-26 status note appended to it): only a missing or failed fit disables
"Go to CEN".  A converged fit with warnings stays enabled and turns amber, with
the warnings in its tooltip -- the operator judges, with the overlay in view.

Everything in this module runs on the GUI thread.  The fit is milliseconds for
the scan sizes TAVI produces, so it runs synchronously; there is no worker.
"""
import logging

import numpy as np

from PySide6.QtWidgets import (QApplication, QGroupBox, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QWidget)
from PySide6.QtCore import Qt, Slot

from matplotlib.widgets import SpanSelector

from gui.docks.base_dock import BaseDockWidget
from tavi import scan_fits

log = logging.getLogger(__name__)

#: Background for a converged-but-flagged "Go to CEN" button.
_AMBER_STYLE = "background-color: #e8a33d; color: #202020;"

#: Colours of the artists this dock owns on the display dock's axes.
_CURVE_COLOR = "#d62728"
_CENTER_COLOR = "#7f2020"
_SPAN_COLOR = "#ffb000"

#: Toolbar modes that must be switched off before the span selector is usable.
#: ``NavigationToolbar2.mode`` stringifies to exactly these labels.
_TOOLBAR_PAN = "pan/zoom"
_TOOLBAR_ZOOM = "zoom rect"


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
    """``value ± err`` for the results grid; a missing error prints ``± ?``."""
    if value is None:
        return "-"
    if error is None:
        return "%s ± ?" % _fmt(value)
    return "%s ± %s" % (_fmt(value), _fmt(error, 3))


class FittingDock(BaseDockWidget):
    """Range selection, quick fit, COM/MAX readouts, and the goto buttons."""

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
        # None means "Go to CEN" has nothing to act on.
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

        body_layout.addWidget(self._build_range_group())
        body_layout.addWidget(self._build_actions_group())
        body_layout.addWidget(self._build_results_group())
        body_layout.addWidget(self._build_goto_group())

    def _build_range_group(self):
        group = QGroupBox("Range")
        outer = QVBoxLayout(group)

        self.range_button = QPushButton("Select range")
        self.range_button.setCheckable(True)
        self.range_button.setToolTip(
            "Drag on the plot to pick the abscissa window the fit uses.\n"
            "Pan/zoom is switched off while this is active."
        )
        self.range_button.toggled.connect(self._on_range_button_toggled)
        outer.addWidget(self.range_button)

        fields = QHBoxLayout()
        fields.addWidget(QLabel("min:"))
        self.range_min_edit = QLineEdit()
        self.range_min_edit.setPlaceholderText("full scan")
        self.range_min_edit.editingFinished.connect(self._on_range_fields_edited)
        fields.addWidget(self.range_min_edit, 1)
        fields.addWidget(QLabel("max:"))
        self.range_max_edit = QLineEdit()
        self.range_max_edit.setPlaceholderText("full scan")
        self.range_max_edit.editingFinished.connect(self._on_range_fields_edited)
        fields.addWidget(self.range_max_edit, 1)
        self.range_clear_button = QPushButton("Clear")
        self.range_clear_button.setToolTip("Fit the whole scan again.")
        self.range_clear_button.clicked.connect(self._on_range_cleared)
        fields.addWidget(self.range_clear_button)
        outer.addLayout(fields)

        return group

    def _build_actions_group(self):
        group = QGroupBox("Peak")
        outer = QVBoxLayout(group)

        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip(
            "Fit a pseudo-Voigt + flat background to the selection.\n"
            "Never runs by itself -- press it again after more points arrive."
        )
        self.fit_button.clicked.connect(self._on_fit_clicked)
        outer.addWidget(self.fit_button)

        self.com_label, com_row, self.com_copy_button = self._readout_row("COM")
        self.com_copy_button.clicked.connect(
            lambda: self._copy_estimate(self._com, "COM")
        )
        outer.addLayout(com_row)

        self.max_label, max_row, self.max_copy_button = self._readout_row("MAX")
        self.max_copy_button.clicked.connect(
            lambda: self._copy_estimate(self._max, "MAX")
        )
        outer.addLayout(max_row)

        return group

    def _readout_row(self, name):
        """A ``name = value`` label plus its copy-to-clipboard button."""
        row = QHBoxLayout()
        label = QLabel("%s: -" % name)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(label, 1)
        button = QPushButton("Copy")
        button.setMaximumWidth(56)
        button.setToolTip("Copy the %s value to the clipboard (full precision)."
                          % name)
        button.setEnabled(False)
        row.addWidget(button)
        return label, row, button

    def _build_results_group(self):
        group = QGroupBox("Fit result")
        outer = QVBoxLayout(group)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self._result_labels = {}
        rows = [
            ("center", "Center"), ("fwhm", "FWHM"), ("height", "Height"),
            ("area", "Area"), ("eta", "eta"), ("background", "Background"),
            ("deviance", "Reduced deviance"), ("dof", "n / dof"),
        ]
        for row, (key, title) in enumerate(rows):
            grid.addWidget(QLabel("%s:" % title), row, 0)
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(value, row, 1)
            self._result_labels[key] = value
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        self.status_label = QLabel("No fit yet.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.status_label)

        return group

    def _build_goto_group(self):
        group = QGroupBox("Go to")
        outer = QHBoxLayout(group)
        self.goto_com_button = QPushButton("Go to COM")
        self.goto_com_button.clicked.connect(
            lambda: self._on_goto_clicked("com")
        )
        self.goto_max_button = QPushButton("Go to MAX")
        self.goto_max_button.clicked.connect(
            lambda: self._on_goto_clicked("max")
        )
        self.goto_cen_button = QPushButton("Go to CEN")
        self.goto_cen_button.clicked.connect(
            lambda: self._on_goto_clicked("cen")
        )
        self.revert_button = QPushButton("Revert")
        self.revert_button.clicked.connect(self._on_revert_clicked)
        for button in (self.goto_com_button, self.goto_max_button,
                       self.goto_cen_button, self.revert_button):
            outer.addWidget(button)
        return group

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
    def on_scan_finished(self):
        """The displayed scan finished (or a saved scan finished loading).

        Refreshes the cheap COM/MAX reductions and the button gating. The fit
        is *not* re-run: fitting is an explicit operator action.
        """
        self._refresh_gating()

    @Slot()
    def refresh_gating(self, *args):
        """Recompute COM/MAX and re-evaluate button enablement.

        Connected to ``job_state_changed(str, str)``, so it accepts and
        ignores positional arguments. The COM/MAX refresh is part of the job:
        those are goto targets, and a job transition means the scan they were
        computed from may have moved on.
        """
        self._refresh_gating()

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

    def _invalidate_fit(self):
        """Drop the cached fit, its warm start, its overlay, and the readout."""
        self._fit_result = None
        self._fit_n_points = None
        self._seed = None
        self._remove_fit_artists()
        for label in self._result_labels.values():
            label.setText("-")
        self.status_label.setText("No fit for the current selection.")

    def _show_result(self, result):
        """Fill the results grid and the status line from ``result``."""
        labels = self._result_labels
        if result.converged:
            labels["center"].setText(_fmt_pm(result.center, result.center_err))
            labels["fwhm"].setText(_fmt_pm(result.fwhm, result.fwhm_err))
            labels["height"].setText(_fmt_pm(result.height, result.height_err))
            labels["area"].setText(_fmt_pm(result.area, result.area_err))
            if result.eta_fixed is not None:
                labels["eta"].setText("%s (fixed)" % _fmt(result.eta_fixed, 2))
            else:
                labels["eta"].setText(_fmt_pm(result.eta, result.eta_err))
            labels["background"].setText(
                _fmt_pm(result.background, result.background_err))
            labels["deviance"].setText(_fmt(result.deviance_reduced, 4))
            labels["dof"].setText("%d / %d" % (result.n_points, result.dof))
        else:
            for label in labels.values():
                label.setText("-")

        parts = []
        if result.converged:
            parts.append("Fit converged.")
        else:
            parts.append("Fit failed: %s" % (result.reason or "unknown reason"))
        if result.warnings:
            parts.append("Warnings: " + "; ".join(result.warnings) + ".")
        caveat = self._noiseless_caveat()
        if caveat:
            parts.append(caveat)
        self.status_label.setText(" ".join(parts))

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

        variable = self._variable_name() or "x"
        self._set_readout(self.com_label, self.com_copy_button, "COM",
                          variable, self._com)
        self._set_readout(self.max_label, self.max_copy_button, "MAX",
                          variable, self._max)

        if self._max is not None and self._max.ok:
            width = self._max.bin_width
            self.max_label.setToolTip(
                "Highest measured bin (width %s) - not interpolated"
                % _fmt(width, 4))
        else:
            self.max_label.setToolTip(
                "Highest measured bin - not interpolated")

    def _set_readout(self, label, copy_button, name, variable, estimate):
        if estimate is not None and estimate.ok:
            label.setText("%s: %s = %s" % (name, variable, _fmt(estimate.x)))
            copy_button.setEnabled(True)
        else:
            reason = estimate.reason if estimate is not None else "no scan"
            label.setText("%s: %s" % (name, reason or "unavailable"))
            copy_button.setEnabled(False)

    def _copy_estimate(self, estimate, name):
        """Put an estimate on the clipboard at full precision."""
        if estimate is None or not estimate.ok or estimate.x is None:
            self.status_label.setText("No %s value to copy." % name)
            return
        QApplication.clipboard().setText(repr(float(estimate.x)))
        self.status_label.setText("Copied %s to the clipboard." % name)

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

        self.fit_button.setEnabled(is_1d)
        self.range_button.setEnabled(is_1d)
        self.range_clear_button.setEnabled(is_1d)

        variable = self._variable_name()
        field = scan_fits.field_for_scan_variable(variable) if variable else None
        idle = not self._busy()
        goto_reason = ""
        if not is_1d:
            goto_reason = "no 1D scan is displayed"
        elif field is None:
            goto_reason = "scan variable '%s' is not goto-able" % variable
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
                button.setToolTip("Target: %s = %s" % (variable, _fmt(value)))

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

    def _refresh_cen_button(self, can_goto, goto_reason, variable):
        """Three-state soft gate on "Go to CEN".

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
        target = "Target: %s = %s" % (variable, _fmt(result.center))
        notes = list(result.warnings)
        arrived = self._points_since_fit()
        if arrived:
            notes.append(
                "%d point(s) measured since this fit -- press Fit again to use them"
                % arrived)
        if notes:
            button.setStyleSheet(_AMBER_STYLE)
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
        for label in self._result_labels.values():
            label.setText("-")
        self.status_label.setText("2D scan displayed - fitting is 1D only.")
        self._draw()
