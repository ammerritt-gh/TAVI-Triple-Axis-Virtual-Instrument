"""Scan-time benchmark dialog (Utilities menu).

A standalone, non-modal "run once on a fresh machine" utility. It runs a short,
fixed sweep of tiny scans around the current GUI position through the ordinary
job worker, tags the records ``source="benchmark"``, and -- on completion --
stores this machine's speed index so per-machine scan-time estimates have a
clean baseline. Organic scan history then refines the estimates over time.

Following ``resolution_dialog.py``: the controller computes (plan shape,
predictions, machine profile, cross-check drift); this dialog only renders and
wires the Run/Cancel buttons to the controller's benchmark orchestration.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QGroupBox, QTableWidget,
                               QTableWidgetItem, QProgressBar, QHeaderView,
                               QMessageBox, QAbstractItemView)
from PySide6.QtCore import Qt

from tavi.runtime_tracker import RuntimeTracker
from tavi.benchmark import DRIFT_HIGHLIGHT_THRESHOLD


# Plan table columns.
_PLAN_HEADERS = ["Stage", "Engine", "ncount", "Points", "Compile", "Predicted"]
# Cross-check table columns.
_XCHECK_HEADERS = ["Stage", "Measured", "History-predicted", "Drift %"]


def _fmt_seconds(value):
    """Human-readable duration, '-' for missing."""
    if value is None:
        return "-"
    return RuntimeTracker.format_time(value)


class BenchmarkDialog(QDialog):
    """Non-modal scan-time benchmarker for the current machine + instrument."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._plan = []
        self.setWindowTitle("Scan-time benchmark")
        self.setMinimumWidth(640)
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self._build_ui()

        # Controller feeds: per-job transitions drive the progress readout; the
        # benchmark_finished signal refreshes the machine panel + cross-check.
        self._controller.job_state_changed.connect(self._on_job_state)
        self._controller.benchmark_finished.connect(self._on_benchmark_finished)

    # --- UI construction ---------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Machine panel.
        machine_box = QGroupBox("This machine")
        machine_grid = QGridLayout(machine_box)
        self._machine_labels = {}
        rows = [
            ("hostname", "Hostname"),
            ("cpu_name", "CPU"),
            ("machine_id", "Machine ID"),
            ("benchmarked_at", "Last benchmark"),
            ("speed_index", "Speed index"),
        ]
        for r, (key, label) in enumerate(rows):
            machine_grid.addWidget(QLabel(f"<b>{label}</b>"), r, 0)
            value_label = QLabel("-")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            machine_grid.addWidget(value_label, r, 1)
            self._machine_labels[key] = value_label
        layout.addWidget(machine_box)

        # Plan table.
        plan_box = QGroupBox("Benchmark plan (ncount editable)")
        plan_layout = QVBoxLayout(plan_box)
        self._plan_table = QTableWidget(0, len(_PLAN_HEADERS))
        self._plan_table.setHorizontalHeaderLabels(_PLAN_HEADERS)
        self._plan_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._plan_table.verticalHeader().setVisible(False)
        plan_layout.addWidget(self._plan_table)
        layout.addWidget(plan_box)

        # Run / Cancel + progress.
        controls = QHBoxLayout()
        self._run_btn = QPushButton("Run benchmark")
        self._run_btn.clicked.connect(self._on_run)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        controls.addWidget(self._run_btn)
        controls.addWidget(self._cancel_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        layout.addWidget(self._progress)
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # Cross-check table.
        xcheck_box = QGroupBox("Cross-check (benchmark vs organic history)")
        xcheck_layout = QVBoxLayout(xcheck_box)
        self._xcheck_table = QTableWidget(0, len(_XCHECK_HEADERS))
        self._xcheck_table.setHorizontalHeaderLabels(_XCHECK_HEADERS)
        self._xcheck_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._xcheck_table.verticalHeader().setVisible(False)
        self._xcheck_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        xcheck_layout.addWidget(self._xcheck_table)
        layout.addWidget(xcheck_box)

    # --- public entry ------------------------------------------------------
    def refresh_from_state(self):
        """Rebuild the machine panel + plan table from current controller state.

        Called by the main window each time the dialog is opened/raised.
        """
        self._refresh_machine_panel()
        self._rebuild_plan_table()

    # --- machine panel -----------------------------------------------------
    def _refresh_machine_panel(self):
        from tavi.machine_profile import machine_fingerprint
        fp = machine_fingerprint()
        profile = {}
        try:
            profile = self._controller.runtime_tracker.machines.get(
                fp["machine_id"], {}) or {}
        except Exception:
            profile = {}

        self._machine_labels["hostname"].setText(str(fp.get("hostname") or "-"))
        self._machine_labels["cpu_name"].setText(str(fp.get("cpu_name") or "-"))
        self._machine_labels["machine_id"].setText(str(fp.get("machine_id") or "-"))
        self._machine_labels["benchmarked_at"].setText(
            str(profile.get("benchmarked_at") or "never"))
        speed = profile.get("speed_index")
        self._machine_labels["speed_index"].setText(
            f"{speed:.3e} s/neutron" if speed else "-")

    # --- plan table --------------------------------------------------------
    def _rebuild_plan_table(self):
        try:
            self._plan = self._controller.build_benchmark_plan()
        except Exception as exc:
            self._plan = []
            self._status_label.setText(f"Could not build plan: {exc}")
        self._plan_table.setRowCount(len(self._plan))
        for r, stage in enumerate(self._plan):
            self._set_plan_cell(r, 0, stage.get("label", ""), editable=False)
            self._set_plan_cell(r, 1, stage.get("engine", ""), editable=False)
            self._set_plan_cell(r, 2, str(int(stage.get("ncount", 0))),
                                editable=True)
            self._set_plan_cell(r, 3, str(int(stage.get("points", 0))),
                                editable=False)
            self._set_plan_cell(
                r, 4, "yes" if stage.get("force_rebuild") else "no",
                editable=False)
            self._set_plan_cell(
                r, 5, _fmt_seconds(stage.get("predicted_seconds")),
                editable=False)

    def _set_plan_cell(self, row, col, text, editable):
        item = QTableWidgetItem(text)
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._plan_table.setItem(row, col, item)

    def _read_plan_ncounts(self):
        """Apply user-edited ncounts from the table back into ``self._plan``."""
        for r, stage in enumerate(self._plan):
            item = self._plan_table.item(r, 2)
            if item is None:
                continue
            try:
                stage["ncount"] = int(float(item.text()))
            except (TypeError, ValueError):
                pass

    # --- run / cancel ------------------------------------------------------
    def _on_run(self):
        if self._controller._has_pending_jobs():
            QMessageBox.warning(
                self, "Scan-time benchmark",
                "A scan is already running or queued. Wait until it finishes "
                "before running the benchmark.")
            return
        if not self._plan:
            self._rebuild_plan_table()
        self._read_plan_ncounts()

        job_ids = self._controller.run_benchmark(self._plan)
        if not job_ids:
            self._status_label.setText("Benchmark did not start.")
            return
        self._progress.setRange(0, len(job_ids))
        self._progress.setValue(0)
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._xcheck_table.setRowCount(0)
        self._status_label.setText(f"Running benchmark ({len(job_ids)} stages)...")

    def _on_cancel(self):
        self._controller.cancel_benchmark()
        self._status_label.setText("Benchmark cancelled.")
        self._cancel_btn.setEnabled(False)

    def _on_job_state(self, job_id, state):
        """Update the progress readout as benchmark stages finish."""
        ids = list(getattr(self._controller, "_benchmark_job_ids", []) or [])
        if not ids or job_id not in ids:
            return
        done = 0
        registry = self._controller._job_registry
        for jid in ids:
            job = registry.get(jid)
            if job is None:
                continue
            snap = job.snapshot()
            if snap.get("state") in ("done", "failed", "cancelled", "stopped"):
                done += 1
        self._progress.setValue(done)
        self._status_label.setText(f"Benchmark: {done}/{len(ids)} stages done.")

    def _on_benchmark_finished(self):
        """Refresh the machine panel + populate the cross-check table."""
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._progress.setValue(self._progress.maximum())
        self._refresh_machine_panel()
        self._status_label.setText("Benchmark complete.")
        try:
            rows = self._controller.benchmark_crosscheck(self._plan)
        except Exception as exc:
            self._status_label.setText(f"Cross-check failed: {exc}")
            return
        self._populate_xcheck(rows)

    def _populate_xcheck(self, rows):
        self._xcheck_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._xcheck_table.setItem(
                r, 0, QTableWidgetItem(str(row.get("label", ""))))
            self._xcheck_table.setItem(
                r, 1, QTableWidgetItem(_fmt_seconds(row.get("measured"))))
            self._xcheck_table.setItem(
                r, 2, QTableWidgetItem(_fmt_seconds(row.get("predicted"))))
            drift = row.get("drift_pct")
            drift_text = "-" if drift is None else f"{drift:+.1f}%"
            drift_item = QTableWidgetItem(drift_text)
            if drift is not None and abs(drift) > DRIFT_HIGHLIGHT_THRESHOLD:
                drift_item.setBackground(Qt.yellow)
                drift_item.setForeground(Qt.black)
            self._xcheck_table.setItem(r, 3, drift_item)
