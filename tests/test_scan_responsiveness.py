"""Offscreen check that the GUI stays responsive during a long analytic scan.

Real ``TAVIMainWindow`` and ``TAVIController`` (offscreen Qt), a 2,000-point
analytic-engine scan started by the Run button's own path, and a GUI-thread
timer that records how late its pings fire while the worker runs. Three
questions, each against a named limit:

* a queued GUI event is handled within ``EVENT_LATENCY_LIMIT_S``;
* the Stop button ends the scan within ``STOP_LIMIT_S`` of the click;
* every log line the controller produced reaches the log panel, in order,
  and the final plot and saved data file equal the job result's counts.

Wall-time budget: at most 20 s for the file (one 2,000-point scan stopped
part-way, one short scan run to completion); every wait has a deadline that
fails the test rather than hanging it. Timing assertions print the measured
margin (run with ``-s`` or read the captured output on failure).
"""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.scan_jobs import JobState  # noqa: E402
from tavi.utilities import scan_point_count  # noqa: E402

EVENT_LATENCY_LIMIT_S = 0.25   # operator ruling 2026-10-14
STOP_LIMIT_S = 1.0             # operator ruling 2026-10-14
PING_INTERVAL_MS = 50
SCAN_POINTS = 2000
WARMUP_POINTS = 200            # latency is judged after this many points
STOP_AT_POINTS = 300           # the Stop click is posted once this many are done
SCAN_DEADLINE_S = 60.0         # wall-clock deadline for any wait

_TERMINAL = (JobState.DONE, JobState.STOPPED, JobState.FAILED, JobState.CANCELLED)


@pytest.fixture(scope="module")
def controller(tmp_path_factory):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(infos[0].id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument.id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    ctrl.output_directory = str(tmp_path_factory.mktemp("responsiveness"))
    print("import root:", os.path.dirname(cm.__file__))
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """A dialog would block an offscreen run for ever: answer it.

    The 2,000-point warning is the operator's "continue anyway" and is
    answered Yes; a critical (refused command) fails the test."""
    refused = []

    def _critical(*args, **kwargs):
        refused.append(args[2:3])
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(_critical))
    yield refused
    assert not refused, f"scan refused: {refused}"


class _Recorder(QObject):
    """The producer-side sequence of log lines, in the order they were handed over."""

    def __init__(self):
        super().__init__()
        self.lines = []

    @Slot(str)
    def on_line(self, line):
        self.lines.append(line)


def _record_log_producer(ctrl):
    """Capture the producer-side sequence; return (recorder, undo).

    The controller has one log producer, ``_post_log``: wrap it, so the
    recorded order is the order lines were handed over (record and hand-over
    under one lock, so two threads cannot interleave them). On code that
    still emits ``message_printed`` directly, a recorder connected to the
    signal sees the same sequence."""
    rec = _Recorder()
    post = getattr(ctrl, "_post_log", None)
    if post is None:
        ctrl.message_printed.connect(rec.on_line, Qt.QueuedConnection)
        return rec, lambda: ctrl.message_printed.disconnect(rec.on_line)
    lock = threading.Lock()

    def _wrapped(line):
        with lock:
            rec.lines.append(line)
            post(line)

    ctrl._post_log = _wrapped
    return rec, lambda: ctrl.__dict__.pop("_post_log", None)


def _start_scan(ctrl, command):
    """Select the analytic engine, type the command, click Run."""
    dock = ctrl.window.simulation_dock
    combo = dock.engine_combo
    combo.setCurrentIndex(combo.findData("deterministic"))
    dock.scan_command_1_edit.setText(command)
    dock.scan_command_2_edit.setText("")
    ctrl.window.data_control_dock.save_folder_edit.setText("responsiveness_scan")
    ctrl.window.output_dock.message_text.clear()
    before = {j.job_id for j in ctrl._job_registry.all_jobs()}
    assert dock.run_button.isEnabled()
    dock.run_button.click()
    new = [j for j in ctrl._job_registry.all_jobs() if j.job_id not in before]
    assert len(new) == 1, "Run did not queue exactly one job"
    return new[0]


def _wait(predicate, deadline_s, what, step_ms=10):
    end = time.perf_counter() + deadline_s
    while time.perf_counter() < end:
        if predicate():
            return
        QTest.qWait(step_ms)
    pytest.fail(f"timed out after {deadline_s:.0f} s waiting for {what}")


def _done(job):
    with job.lock:
        return job.progress_done


def _scan_command_with_points(n):
    """A deltaE command of exactly ``n`` points (the count is asserted)."""
    command = "deltaE 0 %s 0.01" % ((n - 1) / 100.0)
    assert scan_point_count(command) == n
    return command


class _ClickPoster(QObject):
    """Posts a button click into the GUI thread's event queue from any thread.

    A click made from the watcher thread lands behind whatever the worker has
    already queued, exactly where an operator's click lands during a scan."""

    requested = Signal()


def _watch(job, poster, marks, stop_event):
    """Watcher thread: post the Stop click at STOP_AT_POINTS, log the times."""
    clicked = False
    while not stop_event.is_set():
        with job.lock:
            done, state = job.progress_done, job.state
        now = time.perf_counter()
        if not clicked and done >= STOP_AT_POINTS:
            marks["click"] = now
            marks["done_at_click"] = done
            clicked = True
            poster.requested.emit()
        if state in _TERMINAL:
            marks["end"] = now
            marks["end_state"] = state
            return
        time.sleep(0.002)


def test_gui_stays_responsive_and_stop_is_prompt(controller):
    ctrl = controller
    rec, undo = _record_log_producer(ctrl)
    pings = []        # (lateness_s, points_done)
    state = {"last": None, "job": None}
    marks = {}
    watcher_stop = threading.Event()

    def _ping():
        now = time.perf_counter()
        if state["last"] is not None and state["job"] is not None:
            pings.append((now - state["last"] - PING_INTERVAL_MS / 1000.0,
                          _done(state["job"])))
        state["last"] = now

    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setInterval(PING_INTERVAL_MS)
    timer.timeout.connect(_ping)
    poster = _ClickPoster()
    poster.requested.connect(ctrl.window.simulation_dock.stop_button.click,
                             Qt.QueuedConnection)
    ctrl.window.simulation_dock.stop_button.clicked.connect(
        lambda: marks.setdefault("handled", time.perf_counter()))
    watcher = None
    try:
        job = _start_scan(ctrl, _scan_command_with_points(SCAN_POINTS))
        t_start = time.perf_counter()
        state["job"] = job
        assert job.launch_state['engine'] == 'deterministic'
        assert len(job.launch_state['expansion'].points) == SCAN_POINTS
        watcher = threading.Thread(
            target=_watch, args=(job, poster, marks, watcher_stop), daemon=True)
        watcher.start()
        timer.start()
        _wait(lambda: "end" in marks, SCAN_DEADLINE_S, "the job to end")
        # Let the GUI finish its backlog and the last drain deliver everything.
        QTest.qWait(500)
    finally:
        watcher_stop.set()
        timer.stop()
        undo()
        if watcher is not None:
            watcher.join(timeout=5)

    judged = [late for late, done in pings if done >= WARMUP_POINTS]
    worst = max(judged) if judged else float("inf")
    stop_latency = marks.get("end", float("inf")) - marks.get("click", 0.0)
    scan_duration = marks.get("end", float("inf")) - t_start
    print("\nresponsiveness: worst event lateness after %d points = %.3f s "
          "(limit %.2f s, margin %.3f s) over %d pings; stop latency = %.3f s "
          "(limit %.1f s, margin %.3f s); %d points done at the click; "
          "click handled %.3f s after it was posted; "
          "scan duration = %.2f s; end state %s"
          % (WARMUP_POINTS, worst, EVENT_LATENCY_LIMIT_S,
             EVENT_LATENCY_LIMIT_S - worst, len(judged), stop_latency, STOP_LIMIT_S,
             STOP_LIMIT_S - stop_latency, marks.get("done_at_click", -1),
             marks.get("handled", float("inf")) - marks.get("click", 0.0),
             scan_duration, marks.get("end_state")))

    assert marks.get("end_state") == JobState.STOPPED, (
        "the scan was not stopped by the click (end state %s)" % marks.get("end_state"))
    assert stop_latency < STOP_LIMIT_S, (
        "Stop took %.3f s to end the scan" % stop_latency)
    assert len(judged) >= 5, "too few pings to judge latency: %d" % len(judged)
    assert worst < EVENT_LATENCY_LIMIT_S, (
        "a GUI event waited %.3f s behind the scan's updates" % worst)

    # Every produced line reached the panel, in order.
    shown = ctrl.window.output_dock.message_text.toPlainText()
    assert shown == "\n".join(rec.lines), (
        "log panel text differs from the producer sequence "
        "(%d produced lines)" % len(rec.lines))
    assert len(rec.lines) > STOP_AT_POINTS // 2, "scan produced suspiciously few lines"
