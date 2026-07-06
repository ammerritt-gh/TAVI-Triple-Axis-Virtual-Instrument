"""Resolution calculator dialog (Utilities menu).

A standalone, non-modal "check once and work" utility: pick (H, K, L, deltaE)
and a method, hit Recompute, read the theoretical TAS FWHMs and 2-D projection
ellipses for the *current* main-window instrument setup. It mutates no state --
the user edits components in the main window, then recomputes here.

All computation goes through ``TAVIController.compute_resolution`` (the same path
the GET /resolution API uses); this module only presents the returned dict. It is
GUI-only, so PySide6 and matplotlib imports live here, not in the core package.
"""
import math

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QDoubleSpinBox, QComboBox, QPushButton,
                               QGroupBox, QSizePolicy)
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse


# Method combo entries -> resolution() method strings.
_METHODS = [("Auto", "auto"),
            ("Cooper-Nathans", "cooper_nathans"),
            ("Popovici", "popovici")]

# Projection planes: result key -> (title, x-label, y-label).
_PLANES = [
    ("q_par_q_perp", "Q∥ vs Q⟂", "Q∥ (Å⁻¹)", "Q⟂ (Å⁻¹)"),
    ("q_par_E", "Q∥ vs E", "Q∥ (Å⁻¹)", "E (meV)"),
    ("q_perp_E", "Q⟂ vs E", "Q⟂ (Å⁻¹)", "E (meV)"),
]


def _fmt(value, digits=4):
    """Compact fixed-point string; '-' for missing values."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "-"
    return f"{value:.{digits}g}"


class ResolutionDialog(QDialog):
    """Non-modal theoretical-resolution calculator for the current setup."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.setWindowTitle("Resolution calculator")
        self.setMinimumWidth(640)
        # Non-modal, independent window so the user can keep editing the main GUI.
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self._build_ui()

    # --- UI construction ---------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Inputs row: H, K, L, deltaE, method, Recompute.
        input_box = QGroupBox("Point and method")
        input_layout = QHBoxLayout(input_box)
        self._spins = {}
        for key, label in (("H", "H"), ("K", "K"), ("L", "L"), ("deltaE", "ΔE (meV)")):
            input_layout.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(4)
            spin.setSingleStep(0.1)
            input_layout.addWidget(spin)
            self._spins[key] = spin

        input_layout.addWidget(QLabel("Method"))
        self._method_combo = QComboBox()
        for label, value in _METHODS:
            self._method_combo.addItem(label, value)
        input_layout.addWidget(self._method_combo)

        recompute_btn = QPushButton("Recompute")
        recompute_btn.clicked.connect(self.recompute)
        input_layout.addWidget(recompute_btn)
        input_layout.addStretch()
        layout.addWidget(input_box)

        # Setup summary (what was actually computed).
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.RichText)
        layout.addWidget(self._summary_label)

        # Prominent amber banner for cn_valid == False (invalidations).
        self._banner_label = QLabel("")
        self._banner_label.setWordWrap(True)
        self._banner_label.setTextFormat(Qt.RichText)
        self._banner_label.setStyleSheet(
            "QLabel { background: #ffc107; color: #3a2f00; border: 1px solid "
            "#b38600; border-radius: 4px; padding: 6px; font-weight: bold; }"
        )
        self._banner_label.setVisible(False)
        layout.addWidget(self._banner_label)

        # FWHM readouts.
        self._readout_label = QLabel("")
        self._readout_label.setWordWrap(True)
        self._readout_label.setTextFormat(Qt.RichText)
        self._readout_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._readout_label)

        # Lighter warnings list.
        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        self._warnings_label.setStyleSheet("QLabel { color: #8a6d00; }")
        self._warnings_label.setVisible(False)
        layout.addWidget(self._warnings_label)

        # Projection ellipses.
        self._figure = Figure(figsize=(9.0, 3.2))
        self._figure.set_tight_layout(True)
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setMinimumHeight(240)
        layout.addWidget(self._canvas, 1)

    # --- public entry ------------------------------------------------------
    def refresh_from_state(self):
        """Prefill inputs from current GUI values and recompute.

        Called by the main window each time the dialog is opened/raised so the
        point tracks the live scattering panel.
        """
        try:
            vals = self._controller.get_gui_values() or {}
        except Exception:
            vals = {}
        for key in ("H", "K", "L", "deltaE"):
            if key in vals:
                try:
                    self._spins[key].setValue(float(vals[key]))
                except (TypeError, ValueError):
                    pass
        self.recompute()

    def recompute(self):
        """Run the shared compute_resolution path and render the result."""
        method = self._method_combo.currentData()
        try:
            result = self._controller.compute_resolution(
                self._spins["H"].value(), self._spins["K"].value(),
                self._spins["L"].value(), self._spins["deltaE"].value(), method,
            )
        except Exception as exc:  # controller/adapter failure -> show, never crash
            self._render_error(f"Resolution computation failed: {exc}")
            return
        self._render(result)

    # --- rendering ---------------------------------------------------------
    def _render_error(self, message):
        self._summary_label.setText("")
        self._banner_label.setVisible(False)
        self._warnings_label.setVisible(False)
        self._readout_label.setText(f"<b>{message}</b>")
        self._clear_plots("computation failed")

    def _render(self, result):
        self._summary_label.setText(self._setup_summary(result))

        invalidations = result.get("invalidations") or ()
        if invalidations and not result.get("cn_valid", True):
            self._banner_label.setText(
                "<b>Resolution model not applicable (cn_valid = false):</b><br>"
                + "<br>".join(str(x) for x in invalidations)
            )
            self._banner_label.setVisible(True)
        else:
            self._banner_label.setVisible(False)

        warnings = result.get("warnings") or ()
        if warnings:
            self._warnings_label.setText(
                "Warnings: " + "; ".join(str(x) for x in warnings)
            )
            self._warnings_label.setVisible(True)
        else:
            self._warnings_label.setVisible(False)

        if not result.get("ok", False):
            reason = result.get("reason") or "resolution unavailable at this geometry"
            self._readout_label.setText(
                f"<b>No resolution:</b> {reason}"
            )
            self._clear_plots(reason)
            return

        self._readout_label.setText(self._readout_html(result))
        self._draw_projections(result.get("projections") or {})

    def _setup_summary(self, result):
        cfg = result.get("config") or {}
        try:
            vals = self._controller.get_gui_values() or {}
        except Exception:
            vals = {}
        try:
            instrument = self._controller.descriptor.display_name
        except Exception:
            instrument = "?"
        alf = cfg.get("alf") or []
        alf_str = "/".join(_fmt(a, 3) for a in alf) if alf else "-"
        parts = [
            f"<b>Instrument:</b> {instrument}",
            f"mono {vals.get('monocris', '?')} / ana {vals.get('anacris', '?')}",
            f"{vals.get('K_fixed', '?')} @ {_fmt(vals.get('fixed_E'))}",
            f"dₘ={_fmt(cfg.get('dm'), 4)} dₐ={_fmt(cfg.get('da'), 4)} Å",
            f"collim {alf_str}'",
        ]
        return "Computed for: " + " &nbsp;|&nbsp; ".join(parts)

    def _readout_html(self, result):
        method = result.get("method", "?")
        fwhm = result.get("fwhm") or {}
        bragg = result.get("bragg") or {}
        r0 = result.get("r0")
        rows = [
            ("Vanadium ΔE (meV)", _fmt(result.get("vanadium_fwhm_meV")),
             _fmt(bragg.get("dE"))),
            ("Δq∥ (Å⁻¹)", _fmt(fwhm.get("dq_par")),
             _fmt(bragg.get("dq_par"))),
            ("Δq⟂ (Å⁻¹)", _fmt(fwhm.get("dq_perp")),
             _fmt(bragg.get("dq_perp"))),
            ("Δq_z (Å⁻¹)", _fmt(fwhm.get("dq_z")),
             _fmt(bragg.get("dq_z"))),
        ]
        html = [f"<b>Method used:</b> {method}"]
        if r0 is not None:
            html[0] += f" &nbsp; <b>R0:</b> {_fmt(r0)}"
        html.append("<table cellspacing='6'>")
        html.append("<tr><td></td><td><b>Vanadium (marginal)</b></td>"
                    "<td><b>Bragg (coherent)</b></td></tr>")
        for name, van, bra in rows:
            html.append(f"<tr><td>{name}</td><td>{van}</td><td>{bra}</td></tr>")
        html.append("</table>")
        return "".join(html)

    # --- projection plot ---------------------------------------------------
    def _clear_plots(self, message):
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
        ax.set_axis_off()
        self._canvas.draw_idle()

    def _draw_projections(self, projections):
        self._figure.clear()
        for i, (key, title, xlabel, ylabel) in enumerate(_PLANES):
            ax = self._figure.add_subplot(1, len(_PLANES), i + 1)
            plane = projections.get(key)
            if not plane:
                ax.text(0.5, 0.5, "n/a", ha="center", va="center")
                ax.set_axis_off()
                continue
            fw = plane.get("fwhm_principal") or [0.0, 0.0]
            width = float(fw[0]) if len(fw) > 0 else 0.0
            height = float(fw[1]) if len(fw) > 1 else 0.0
            angle = math.degrees(float(plane.get("tilt_rad", 0.0)))
            ell = Ellipse((0.0, 0.0), width=width, height=height, angle=angle,
                          fill=False, edgecolor="#1f77b4", linewidth=1.5)
            ax.add_patch(ell)
            span_x = max(width, height, 1e-6)
            span_y = max(width, height, 1e-6)
            ax.set_xlim(-0.7 * span_x, 0.7 * span_x)
            ax.set_ylim(-0.7 * span_y, 0.7 * span_y)
            ax.axhline(0.0, color="#cccccc", linewidth=0.5)
            ax.axvline(0.0, color="#cccccc", linewidth=0.5)
            ax.set_title(title, fontsize=9)
            ax.set_xlabel(xlabel, fontsize=8)
            ax.set_ylabel(ylabel, fontsize=8)
            ax.tick_params(labelsize=7)
        self._canvas.draw_idle()
