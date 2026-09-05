"""Dispersion viewer: plot a ``Phonon_DFT`` map along a reciprocal-space path.

A thin PySide6 layer over ``tavi.dispersion_map`` and ``tavi.dispersion_path``:
pick a map (and optionally a second one to overlay dashed), a path, and save
the figure.  :class:`DispersionViewerWidget` is a plain ``QWidget`` so the main
TAVI window can host it later; :class:`DispersionViewerWindow` wraps it for the
standalone launcher ``run-dispersion-viewer.bat``.

Figures default to ``<repo>/figures/`` (gitignored), never ``output/``, and the
last save folder is remembered in ``QSettings("TAVI", "DispersionViewer")``.
"""
from __future__ import annotations

import logging
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from tavi.dispersion_map import load_dispersion_map
from tavi.dispersion_path import PRESET_PATHS, PathTrace, parse_path, trace_path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_DIR = ROOT / "components"
FIGURES_DIR = ROOT / "figures"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
OVERLAY_COLOR = "#8a8a86"
NONE_LABEL = "(none)"

log = logging.getLogger(__name__)


class DispersionViewerWidget(QWidget):
    """Controls plus an embedded matplotlib canvas; every control change replots."""

    def __init__(self, components_dir: Path = COMPONENTS_DIR, parent=None):
        super().__init__(parent)
        self.components_dir = Path(components_dir)
        self.settings = QSettings("TAVI", "DispersionViewer")
        self.trace: PathTrace | None = None
        self.overlay_trace: PathTrace | None = None
        self._status = lambda text: None

        self.map_combo = QComboBox()
        self.overlay_combo = QComboBox()
        self.preset_combo = QComboBox()
        self.path_edit = QLineEdit()
        self.points_spin = QSpinBox()
        self.points_spin.setRange(10, 2000)
        self.points_spin.setValue(int(self.settings.value("points", 200)))
        browse = QPushButton("Browse…")
        save = QPushButton("Save PNG…")

        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        toolbar = NavigationToolbar2QT(self.canvas, self)

        form = QFormLayout()
        map_row = QHBoxLayout()
        map_row.addWidget(self.map_combo, 1)
        map_row.addWidget(browse)
        form.addRow("Map", map_row)
        form.addRow("Overlay", self.overlay_combo)
        form.addRow("Preset path", self.preset_combo)
        form.addRow("Path", self.path_edit)
        form.addRow("Points per segment", self.points_spin)
        controls = QVBoxLayout()
        controls.addLayout(form)
        controls.addWidget(save)
        controls.addStretch(1)
        controls_box = QWidget()
        controls_box.setLayout(controls)
        controls_box.setFixedWidth(360)

        plot_column = QVBoxLayout()
        plot_column.addWidget(toolbar)
        plot_column.addWidget(self.canvas, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(controls_box)
        layout.addLayout(plot_column, 1)

        self._populate_maps()
        self.preset_combo.addItems(list(PRESET_PATHS))
        self.path_edit.setText(
            str(self.settings.value("path_text", PRESET_PATHS["fcc short  Γ–X–W–K–Γ–L"]))
        )
        self._select_text(self.map_combo, str(self.settings.value("map", "")))
        self._select_text(self.overlay_combo, str(self.settings.value("overlay", NONE_LABEL)))

        self.map_combo.currentTextChanged.connect(lambda _: self.plot())
        self.overlay_combo.currentTextChanged.connect(lambda _: self.plot())
        self.preset_combo.activated.connect(self._apply_preset)
        self.path_edit.editingFinished.connect(self.plot)
        self.points_spin.valueChanged.connect(lambda _: self.plot())
        browse.clicked.connect(self._browse_map)
        save.clicked.connect(self._save_dialog)

    # -- public API (also what the tests drive) --------------------------------
    def set_status_sink(self, callback) -> None:
        self._status = callback

    @property
    def map_path(self) -> Path | None:
        return self._path_for(self.map_combo.currentText())

    @property
    def overlay_path(self) -> Path | None:
        return self._path_for(self.overlay_combo.currentText())

    def set_map(self, path: Path | str) -> None:
        self._add_and_select(self.map_combo, Path(path))

    def set_overlay(self, path: Path | str | None) -> None:
        if path is None:
            self.overlay_combo.setCurrentText(NONE_LABEL)
        else:
            self._add_and_select(self.overlay_combo, Path(path))

    def set_path_text(self, text: str) -> None:
        self.path_edit.setText(text)

    def plot(self) -> None:
        """Replot from the current controls; errors go to the log, a dialog and the status sink."""
        map_path = self.map_path
        if map_path is None:
            self.axes.clear()
            self.canvas.draw_idle()
            return
        try:
            path = parse_path(self.path_edit.text())
            QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._status(f"Loading {map_path.name} …")
                dispersion = load_dispersion_map(map_path)
                self.trace = trace_path(dispersion, path, self.points_spin.value())
                self.overlay_trace = None
                if self.overlay_path is not None:
                    self._status(f"Loading {self.overlay_path.name} …")
                    overlay = load_dispersion_map(self.overlay_path)
                    self.overlay_trace = trace_path(overlay, path, self.points_spin.value())
            finally:
                QGuiApplication.restoreOverrideCursor()
        except Exception as exc:  # any failure must be visible, never a blank canvas
            log.exception("plot failed for %s", map_path)
            self._status(f"Error: {exc}")
            QMessageBox.critical(self, "Dispersion viewer", f"{type(exc).__name__}: {exc}")
            return
        self._draw(map_path)
        self._remember()
        self._status(
            f"{map_path.name}: {self.trace.energies.shape[1]} branches, "
            f"max {self.trace.energies.max():.2f} meV"
        )

    def save_png(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.figure.savefig(path, dpi=150)
        self.settings.setValue("save_dir", str(path.parent))
        self._status(f"Saved {path}")
        return path

    # -- internals ---------------------------------------------------------------
    def _draw(self, map_path: Path) -> None:
        ax = self.axes
        ax.clear()
        trace = self.trace
        for b in range(trace.energies.shape[1]):
            ax.plot(trace.distance, trace.energies[:, b], color=SERIES[b % len(SERIES)],
                    lw=2, label=f"{map_path.stem}: branch {b + 1}")
        if self.overlay_trace is not None and self.overlay_path is not None:
            overlay = self.overlay_trace
            for b in range(overlay.energies.shape[1]):
                ax.plot(overlay.distance, overlay.energies[:, b], color=OVERLAY_COLOR,
                        lw=1.2, ls="--", label=f"{self.overlay_path.stem}: branch {b + 1}")
        for tick in trace.ticks[1:-1]:
            ax.axvline(tick, color="#d5d4cf", lw=0.8, zorder=0)
        ax.set_xticks(trace.ticks)
        ax.set_xticklabels(trace.labels)
        ax.set_xlim(trace.ticks[0], trace.ticks[-1])
        ax.set_ylim(bottom=0)
        ax.set_ylabel("Energy (meV)")
        ax.set_title(f"{map_path.name} along {'–'.join(trace.labels)}")
        ax.grid(axis="y", color="#e6e5e0", lw=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="upper center",
                  bbox_to_anchor=(0.5, -0.08), ncol=3)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _populate_maps(self) -> None:
        names = sorted(p.name for p in self.components_dir.glob("*.dat"))
        self.map_combo.addItems(names)
        self.overlay_combo.addItem(NONE_LABEL)
        self.overlay_combo.addItems(names)

    def _path_for(self, text: str) -> Path | None:
        if not text or text == NONE_LABEL:
            return None
        candidate = Path(text)
        return candidate if candidate.is_absolute() else self.components_dir / text

    @staticmethod
    def _select_text(combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _add_and_select(self, combo: QComboBox, path: Path) -> None:
        text = path.name if path.parent == self.components_dir else str(path)
        if combo.findText(text) < 0:
            combo.addItem(text)
        combo.setCurrentText(text)

    def _apply_preset(self, index: int) -> None:
        self.path_edit.setText(PRESET_PATHS[self.preset_combo.itemText(index)])
        self.plot()

    def _browse_map(self) -> None:
        start = self.settings.value("browse_dir", str(self.components_dir))
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Open dispersion map", str(start), "Dispersion maps (*.dat);;All files (*)"
        )
        if chosen:
            self.settings.setValue("browse_dir", str(Path(chosen).parent))
            self.set_map(chosen)

    def _save_dialog(self) -> None:
        if self.trace is None or self.map_path is None:
            return
        folder = Path(str(self.settings.value("save_dir", str(FIGURES_DIR))))
        suggested = folder / f"{self.map_path.stem}_{'-'.join(self.trace.labels)}.png"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save figure", str(suggested), "PNG image (*.png)"
        )
        if chosen:
            self.save_png(chosen)

    def _remember(self) -> None:
        self.settings.setValue("map", self.map_combo.currentText())
        self.settings.setValue("overlay", self.overlay_combo.currentText())
        self.settings.setValue("path_text", self.path_edit.text())
        self.settings.setValue("points", self.points_spin.value())


class DispersionViewerWindow(QMainWindow):
    def __init__(self, components_dir: Path = COMPONENTS_DIR):
        super().__init__()
        self.setWindowTitle("TAVI dispersion viewer")
        self.viewer = DispersionViewerWidget(components_dir)
        self.viewer.set_status_sink(self.statusBar().showMessage)
        self.setCentralWidget(self.viewer)
        self.resize(1200, 640)


def main() -> int:
    FIGURES_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=FIGURES_DIR / "dispersion-viewer.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8",
    )
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        window = DispersionViewerWindow()
        window.show()
        window.viewer.plot()
        return app.exec()
    except Exception:  # pythonw has no console: the log and a dialog are the only outputs
        log.exception("dispersion viewer failed to start")
        QMessageBox.critical(None, "Dispersion viewer", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
