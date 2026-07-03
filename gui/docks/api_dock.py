"""Remote API dock for TAVI.

Surfaces the remote API server described in ``docs/API_SERVER_DESIGN.md`` (see
section 10, "What the User Sees"): the listening status, an access-mode toggle,
the scan-job queue table with per-row cancel, a budget readout, and a scrolling
activity log.

The dock never reads worker/registry state directly. All updates arrive on the
GUI thread: status via ``api_status_changed``, activity via ``api_activity``,
and job/budget refreshes via ``job_state_changed`` (all wired in the
controller's ``connect_signals``). User actions (mode change, cancel) call
controller methods through the controller reference set with
``set_controller``.
"""
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTableWidget,
    QTableWidgetItem, QPushButton, QPlainTextEdit, QHeaderView, QWidget,
)
from PySide6.QtCore import Qt, Slot

from gui.docks.base_dock import BaseDockWidget


# Combo entries: display label -> mode value understood by controller.set_api_mode.
_MODE_LABELS = ["Allow control", "Read-only", "Off"]
_MODE_VALUES = ["allow", "readonly", "off"]

# States for which a per-row Cancel button is meaningful/enabled.
_CANCELLABLE_STATES = ("queued", "running")

# Activity log cap (lines); trimmed from the top when exceeded.
_MAX_ACTIVITY_LINES = 500


class ApiDock(BaseDockWidget):
    """Dock widget exposing remote-API status, mode, jobs, budget, and log."""

    def __init__(self, parent=None):
        super().__init__("Remote API", parent, use_scroll_area=True)
        self.setObjectName("api_dock")

        # Controller reference, set by the controller after construction. Until
        # then user actions are no-ops (the server is not up yet either).
        self._controller = None

        layout = self.content_layout

        # ----- Status line ------------------------------------------------
        status_group = QGroupBox("Server")
        status_layout = QVBoxLayout()
        status_group.setLayout(status_layout)
        self.status_label = QLabel("Off")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_group)

        # ----- Access mode ------------------------------------------------
        mode_group = QGroupBox("Access Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(_MODE_LABELS)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo, 1)
        layout.addWidget(mode_group)

        # ----- Budget readout ---------------------------------------------
        budget_group = QGroupBox("Budget")
        budget_layout = QVBoxLayout()
        budget_group.setLayout(budget_layout)
        self.budget_label = QLabel("Pending neutrons: -\nQueued jobs: -")
        budget_layout.addWidget(self.budget_label)
        layout.addWidget(budget_group)

        # ----- Job table --------------------------------------------------
        jobs_group = QGroupBox("Jobs")
        jobs_layout = QVBoxLayout()
        jobs_group.setLayout(jobs_layout)
        self.job_table = QTableWidget(0, 5)
        self.job_table.setHorizontalHeaderLabels(
            ["ID", "Source", "State", "Progress", ""]
        )
        self.job_table.verticalHeader().setVisible(False)
        self.job_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.job_table.setSelectionMode(QTableWidget.NoSelection)
        header = self.job_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        jobs_layout.addWidget(self.job_table)
        layout.addWidget(jobs_group)

        # ----- Activity log -----------------------------------------------
        activity_group = QGroupBox("Activity Log")
        activity_layout = QVBoxLayout()
        activity_group.setLayout(activity_layout)
        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setMaximumBlockCount(_MAX_ACTIVITY_LINES)
        activity_layout.addWidget(self.activity_log)
        layout.addWidget(activity_group)

    # ---- controller wiring ----------------------------------------------

    def set_controller(self, controller):
        """Attach the controller the dock drives user actions through.

        Also does an initial job/budget pull so a dock created before any job
        activity shows the current (empty) state.
        """
        self._controller = controller
        self.refresh_jobs()

    # ---- signal-driven updates (GUI thread) -----------------------------

    @Slot(str, str)
    def set_status(self, url, state):
        """Update the status line from ``api_status_changed`` (url, state)."""
        if url:
            self.status_label.setText(f"{state}\n{url}")
        else:
            self.status_label.setText(state)

    @Slot(str)
    def append_activity(self, msg):
        """Append one line to the activity log (capped via maxBlockCount)."""
        self.activity_log.appendPlainText(msg)

    def set_mode_display(self, mode):
        """Set the mode combo to ``mode`` without emitting a change request."""
        try:
            index = _MODE_VALUES.index(mode)
        except ValueError:
            return
        blocked = self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.setCurrentIndex(index)
        finally:
            self.mode_combo.blockSignals(blocked)

    @Slot(str, str)
    def refresh_jobs(self, *args):
        """Re-pull recent jobs and budget usage and repaint the table.

        Connected to ``job_state_changed(str, str)`` so any transition drives a
        refresh; the positional args are ignored (we always re-pull the full
        recent view). Safe to call with no controller attached.
        """
        controller = self._controller
        if controller is None:
            return

        # Jobs (newest first, via controller helper -- never touch the registry
        # directly from the dock).
        jobs = controller.get_recent_jobs(20)
        self.job_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            job_id = job.get("job_id", "")
            source = job.get("source", "")
            state = job.get("state", "")
            progress = job.get("progress", {}) or {}
            done = progress.get("done", 0)
            total = progress.get("total", 0)
            progress_text = f"{done}/{total}" if total else str(done)

            self.job_table.setItem(row, 0, QTableWidgetItem(str(job_id)))
            self.job_table.setItem(row, 1, QTableWidgetItem(str(source)))
            self.job_table.setItem(row, 2, QTableWidgetItem(str(state)))
            self.job_table.setItem(row, 3, QTableWidgetItem(progress_text))

            cancel_btn = QPushButton("Cancel")
            cancel_btn.setEnabled(state in _CANCELLABLE_STATES)
            cancel_btn.clicked.connect(
                lambda _checked=False, jid=job_id: self._on_cancel_clicked(jid)
            )
            # Wrap so the button does not stretch to fill the whole cell.
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(2, 2, 2, 2)
            cell_layout.addWidget(cancel_btn)
            self.job_table.setCellWidget(row, 4, cell)

        # Budget readout.
        usage = controller.get_api_budget_usage()
        pending = usage.get("pending_neutrons")
        budget = usage.get("budget")
        queued = usage.get("queued_jobs")
        max_queued = usage.get("max_queued")
        self.budget_label.setText(
            f"Pending neutrons: {_fmt(pending)} / {_fmt(budget)}\n"
            f"Queued jobs: {_fmt(queued)} / {_fmt(max_queued)}"
        )

    # ---- user actions ----------------------------------------------------

    def _on_mode_changed(self, index):
        """User picked a mode -- forward to the controller."""
        if self._controller is None:
            return
        if 0 <= index < len(_MODE_VALUES):
            self._controller.set_api_mode(_MODE_VALUES[index])

    def _on_cancel_clicked(self, job_id):
        """User clicked Cancel on a job row -- route through the controller."""
        if self._controller is None or not job_id:
            return
        self._controller.cancel_job(job_id)


def _fmt(value):
    """Compact display for a numeric budget field; '-' when unknown."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
