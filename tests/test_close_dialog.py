"""The close dialog and the instrument-switch restart: ask first, force-stop, then close.

Offscreen Qt with the real window and controller (``api_overrides={"disabled":
True}``), no McStas: the plugin's ``build`` and ``run_point`` and the detector
reader are replaced by a stand-in whose point runs a sleeping ``sys.executable``
child inside the controller's real ``PointScope``, so a force stop ends a real
process and the job ends ``stopped`` with ``"kill"``.

The dialog is the real ``QMessageBox`` shown modally; a single-shot timer finds
it through ``QApplication.activeModalWidget()``, records its texts and default
button, and clicks the named button.  Every process a test starts is ended by
the force stop; teardown force-stops again and waits for idle.

Wall-time budget for this file: 15 s.  Every wait has a wall-clock deadline
that fails the test rather than hanging it.
"""
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.scan_jobs import JobState  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")

DEADLINE_S = 10.0
SCAN = "deltaE 10 20 5"      # three PUMA points, all feasible at H=1 K=0 L=0
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def pump_until(predicate, what, timeout=DEADLINE_S):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    pytest.fail(f"timed out after {timeout} s waiting for {what}")


class Rig:
    """A real window and controller whose points run a sleeping child process."""

    def __init__(self, monkeypatch, tmp_path):
        self.app = QApplication.instance() or QApplication([sys.argv[0]])
        self.window = cm.TAVIMainWindow(
            get_instrument("puma").descriptor(), instrument_infos=available_instruments(),
            current_instrument_id="puma", save_selection=lambda _id: None)
        self.ctrl = cm.TAVIController(self.window, get_instrument("puma"),
                                      api_overrides={"disabled": True})
        self.window.controller = self.ctrl      # main() does this after construction
        self.ctrl.output_directory = str(tmp_path / "output")
        self.ctrl._binary_reuse_cache = None
        monkeypatch.setattr(self.ctrl.instrument, "build", lambda *a, **k: "stub-instrument")
        monkeypatch.setattr(cm, "read_1Ddetector_file", lambda folder: (1.0, 0.1, 10.0))
        monkeypatch.setattr(self.ctrl.instrument, "run_point", self._run_point)
        self.points_started = 0
        self.dialogs = []           # one dict per QMessageBox seen
        self.click = "Keep running"  # the button the next dialog gets
        self.window.show()

    def _run_point(self, instrument, snapshot, output_folder, number_neutrons,
                   execution_state, mpi_count=1):
        os.makedirs(output_folder, exist_ok=True)
        self.points_started += 1
        subprocess.run(SLEEPER, timeout=30)     # ended by the force stop
        info = {'mode': 'stub', 'returncode': 0, 'stdout': '', 'binary_path': None,
                'output_folder': output_folder, 'error_message': None,
                'launcher_argv': [], 'armed_direct_run': False}
        return "stub-data", [], info

    def submit(self):
        launch = self.ctrl.build_api_launch_state(
            {"H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": SCAN})
        self.ctrl._compile_launch(launch)
        launch["planned_feasible_mask"] = [True] * len(launch["expansion"].points)
        return self.ctrl.submit_scan_job(launch, "gui")

    def running_job(self):
        job = self.submit()
        pump_until(lambda: self.points_started >= 1, "the first point to start")
        return job

    def answer_dialogs(self):
        """Answer every modal QMessageBox that opens, recording what it showed."""
        def answer():
            box = QApplication.activeModalWidget()
            if not isinstance(box, QMessageBox):
                return
            by_text = {b.text(): b for b in box.buttons()}
            self.dialogs.append({
                "text": box.text(), "buttons": sorted(by_text),
                "default": box.defaultButton().text(),
                "escape": box.escapeButton().text()})
            by_text[self.click].click()
        self._timer = QTimer(self.window)
        self._timer.setInterval(20)
        self._timer.timeout.connect(answer)
        self._timer.start()

    def log(self):
        self.ctrl._drain_updates()
        return self.window.output_dock.message_text.toPlainText()

    def teardown(self):
        self._timer_stop()
        if not self.ctrl.is_idle():
            self.ctrl.force_stop_all()
            pump_until(self.ctrl.is_idle, "the controller to be idle after the test")
        self.ctrl.shutdown()
        self.window.deleteLater()
        self.app.processEvents()

    def _timer_stop(self):
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()


@pytest.fixture
def rig(monkeypatch, tmp_path):
    r = Rig(monkeypatch, tmp_path)
    print("import root:", os.path.dirname(cm.__file__), file=sys.__stdout__)
    r.answer_dialogs()
    try:
        yield r
    finally:
        r.teardown()


def state(job):
    with job.lock:
        return job.state


def wait_terminal(job):
    done = (JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.STOPPED)
    pump_until(lambda: state(job) in done, f"job {job.job_id} to end")
    pump_until(lambda: job.result is not None or state(job) == JobState.CANCELLED,
               "its result")
    return state(job)


def window_closed(r):
    return not r.window.isVisible() and r.ctrl._shutdown_called


# ------------------------------------------------------------ nothing ongoing

def test_close_with_nothing_ongoing_has_no_dialog(rig):
    assert rig.ctrl.ongoing_work() is None
    rig.window.close()
    assert not rig.window.isVisible()
    assert rig.ctrl._shutdown_called
    assert rig.dialogs == []


# ------------------------------------------------------------ a running scan

def test_dialog_for_a_running_scan_defaults_to_keep_running(rig):
    job = rig.running_job()
    rig.click = "Keep running"
    rig.window.close()
    assert len(rig.dialogs) == 1
    d = rig.dialogs[0]
    assert d["buttons"] == ["Keep running", "Stop scan and close"]
    assert d["default"] == "Keep running" and d["escape"] == "Keep running"
    assert "point 1 of 3" in d["text"]
    assert "discards the current point" in d["text"]
    assert rig.window.isVisible() and not rig.ctrl._shutdown_called
    assert state(job) == JobState.RUNNING
    assert not rig.window._close_in_progress


def test_stop_and_close_kills_cancels_queued_then_closes(rig):
    job = rig.running_job()
    queued = rig.submit()
    rig.click = "Stop scan and close"
    rig.window.close()
    assert len(rig.dialogs) == 1
    assert "1 queued job" in rig.dialogs[0]["text"]
    # Not closed at once: the window waits for the force stop without blocking.
    assert rig.window.isVisible(), "the window closed before the force stop finished"
    pump_until(lambda: window_closed(rig), "the window to close")
    assert state(job) == JobState.STOPPED
    assert job.result.stop_mode == "kill"
    assert state(queued) == JobState.CANCELLED
    assert rig.ctrl.is_idle()
    assert len(rig.dialogs) == 1, "a second dialog opened"
    assert "stopping the scan before closing" in rig.log()


def test_a_second_close_while_waiting_does_nothing(rig):
    rig.running_job()
    rig.click = "Stop scan and close"
    rig.window.close()
    assert rig.window._close_in_progress
    rig.window.close()                  # e.g. Ctrl+Q again during the wait
    assert len(rig.dialogs) == 1, "a second dialog opened"
    assert not rig.ctrl._shutdown_called, "shutdown ran before the force stop finished"
    pump_until(lambda: window_closed(rig), "the window to close")
    assert len(rig.dialogs) == 1


def test_a_wait_that_runs_out_closes_anyway_and_says_so(rig, monkeypatch):
    rig.running_job()
    monkeypatch.setattr(type(rig.ctrl), "CLOSE_WAIT_S", 0.3)
    real_idle = rig.ctrl.is_idle
    rig.ctrl.is_idle = lambda: False        # a process that never ends
    try:
        rig.click = "Stop scan and close"
        rig.window.close()
        pump_until(lambda: not rig.window.isVisible(), "the window to close after the wait")
        assert "could not all be confirmed ended" in rig.log()
    finally:
        rig.ctrl.is_idle = real_idle


# --------------------------------------------------------------- queued only

def test_dialog_for_queued_jobs_only_names_the_count(rig):
    rig.running_job()
    rig.submit()
    rig.submit()
    # A queued-only state needs a worker between jobs, which a test cannot hold
    # still; hide the running job from the controller while the dialog is up.
    running = rig.ctrl._active_job
    rig.ctrl._active_job = None
    try:
        assert rig.ctrl.ongoing_work() == {
            "job_id": None, "point": None, "points": None, "queued": 2}
        rig.click = "Keep running"
        rig.window.close()
    finally:
        rig.ctrl._active_job = running
    d = rig.dialogs[0]
    assert d["buttons"] == ["Cancel jobs and close", "Keep running"]
    assert d["default"] == "Keep running" and d["escape"] == "Keep running"
    assert "2 queued jobs" in d["text"]
    assert rig.window.isVisible() and not rig.ctrl._shutdown_called


# ------------------------------------------------------ instrument switch

def test_instrument_switch_force_stops_without_a_second_dialog(rig, monkeypatch):
    job = rig.running_job()
    queued = rig.submit()
    asked = []

    def yes(parent, title, text, *a, **k):
        asked.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(yes))
    other = next(i.id for i in available_instruments() if i.id != "puma")
    rig.window._on_instrument_selected(other)
    assert asked == ["Switch Instrument"]
    assert rig.dialogs == [], "the close dialog opened on top of the switch dialog"
    assert rig.window._restart_instrument_id == other
    assert rig.window.isVisible(), "the window closed before the force stop finished"
    pump_until(lambda: window_closed(rig), "the window to close")
    assert state(job) == JobState.STOPPED and job.result.stop_mode == "kill"
    assert state(queued) == JobState.CANCELLED
    assert rig.window._restart_instrument_id == other
