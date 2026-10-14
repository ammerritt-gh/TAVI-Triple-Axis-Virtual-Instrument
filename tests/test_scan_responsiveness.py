"""Offscreen check that the GUI stays responsive during a long analytic scan.

Real ``TAVIMainWindow`` and ``TAVIController`` (offscreen Qt), a 2,000-point
analytic-engine scan started by the Run button's own path, and a GUI-thread
timer that records how late its pings fire while the worker runs. Three
questions, each against a named limit:

* a queued GUI event is handled within ``EVENT_LATENCY_LIMIT_S``;
* the Stop button ends the scan within ``STOP_LIMIT_S`` of the click;
* every log line the controller produced reaches the log panel, in order,
  and the final plot and saved data file equal the job result's counts;
* display updates applied in a batch (``redraw=False`` then ``redraw()``)
  leave the plot exactly as the per-point path does.

Wall-time budget: at most 20 s for the file (one 2,000-point scan stopped
part-way, two short scans run to completion); every wait has a deadline that
fails the test rather than hanging it. Timing assertions print the measured
margin (run with ``-s`` or read the captured output on failure).
"""
import contextlib
import io
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
    print("import root:", os.path.dirname(cm.__file__), file=sys.__stdout__)
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@contextlib.contextmanager
def _stdout_to_memory():
    """The scan prints a line per point (stage solve); into pytest's capture file
    that cost ~30 ms a line here, so a 2,000-point scan spent a minute before its
    first point. Inside the test body (pytest swaps sys.stdout again around each
    phase) the prints go to memory; this file's own report uses the real stdout."""
    saved = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = saved


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
        with _stdout_to_memory():
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
             scan_duration, marks.get("end_state")), file=sys.__stdout__)

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


def test_worker_line_does_not_overtake_a_gui_line(controller):
    """A worker line that lands after a GUI line was handed over, but before the
    drain takes the buffer, must not be shown ahead of that GUI line."""
    ctrl = controller
    panel = ctrl.window.output_dock.message_text
    panel.clear()
    buf = ctrl._gui_updates
    real_take = buf.take
    landed = []

    def _take_after_worker_lands():
        if not landed:
            landed.append(True)
            worker = threading.Thread(target=ctrl._post_log, args=("worker",), daemon=True)
            worker.start()
            worker.join(timeout=SCAN_DEADLINE_S)
            assert not worker.is_alive(), "worker thread did not finish"
        return real_take()

    buf.take = _take_after_worker_lands
    try:
        ctrl._post_log("gui")
        end = time.perf_counter() + SCAN_DEADLINE_S
        while buf._logs:  # drain until the buffer is empty
            ctrl._drain_updates()
            assert time.perf_counter() < end, "the log buffer never emptied"
    finally:
        del buf.take
    assert panel.toPlainText() == "gui\nworker", (
        "panel shows %r; the GUI line was handed over first" % panel.toPlainText())


def _finish(ctrl, job):
    """Wait for a short scan to end and the plot to say so; return the job."""
    dock = ctrl.window.display_dock
    _wait(lambda: _state_of(job) in _TERMINAL, SCAN_DEADLINE_S, "the short scan to end")
    # scan_complete, then the auto-save, each write the status line.
    _wait(lambda: dock.status_label.text().startswith(("Scan complete", "Plot auto-saved")),
          SCAN_DEADLINE_S, "the plot to show the scan complete")
    assert _state_of(job) == JobState.DONE
    return job


def _state_of(job):
    with job.lock:
        return job.state


def _read_scan_file(path):
    """(x, y) columns of a saved 1D scan file; NaN stays NaN."""
    rows = []
    with open(path, encoding="utf-8", newline="") as handle:
        for line in handle.read().splitlines():
            if line and not line.startswith("#"):
                x, y = line.split()
                rows.append((float(x), float(y)))
    return rows


def test_final_plot_and_saved_data_equal_the_job_result_1d(controller):
    """The buffered path loses and reorders nothing: plot arrays and the saved
    file hold exactly the counts the job recorded."""
    import numpy as np

    ctrl = controller
    job = _finish(ctrl, _start_scan(ctrl, "deltaE 0 2 0.1"))
    result = job.result
    expected = [np.nan if c is None else c for c in result.counts]
    assert sum(not np.isnan(c) for c in expected) >= 10, "scan produced too few points"

    snap = ctrl.window.display_dock.scan_snapshot()
    assert snap['mode'] == '1D'
    assert list(snap['x']) == list(result.scan_values_1)
    np.testing.assert_array_equal(snap['counts'], np.array(expected))
    np.testing.assert_array_equal(snap['mask'], ~np.isnan(np.array(expected)))

    # The saved file: x ascending, one row per point the loop ran (NaN for an invalid one).
    rows = _read_scan_file(os.path.join(result.output_folder, "1D_scan_data.txt"))
    by_x = sorted(zip(result.scan_values_1, expected))
    assert [x for x, _ in rows] == [x for x, _ in by_x]
    np.testing.assert_array_equal(np.array([y for _, y in rows]),
                                  np.array([y for _, y in by_x]))
    assert result.total_counts == pytest.approx(float(np.nansum(expected)))


def test_final_plot_equals_the_job_result_2d(controller):
    import numpy as np

    ctrl = controller
    dock = ctrl.window.simulation_dock
    dock.scan_command_2_edit.setText("")
    dock.engine_combo.setCurrentIndex(dock.engine_combo.findData("deterministic"))
    dock.scan_command_1_edit.setText("deltaE 0 1 0.5")
    dock.scan_command_2_edit.setText("H 1 1.4 0.2")
    ctrl.window.data_control_dock.save_folder_edit.setText("responsiveness_scan_2d")
    before = {j.job_id for j in ctrl._job_registry.all_jobs()}
    dock.run_button.click()
    jobs = [j for j in ctrl._job_registry.all_jobs() if j.job_id not in before]
    assert len(jobs) == 1, "Run did not queue exactly one job"
    job = _finish(ctrl, jobs[0])
    result = job.result
    assert result.mode == '2D'
    expected = np.array([[np.nan if c is None else c for c in row]
                         for row in result.counts_grid])
    assert np.count_nonzero(~np.isnan(expected)) >= 4, "scan produced too few points"
    np.testing.assert_array_equal(ctrl.window.display_dock._counts, expected)
    assert os.path.isfile(os.path.join(result.output_folder, "2D_scan_data.txt"))


def _fed_docks(mode):
    """Two display docks fed the same events: one per point, one batched."""
    import numpy as np
    from gui.docks.display_dock import DisplayDock

    docks = []
    for batched in (False, True):
        dock = DisplayDock()
        if mode == '1D':
            dock.initialize_scan('1D', [float(i) for i in range(8)], [True] * 8, 'deltaE')
            events = [('set_current_scan_index', (0,)), ('update_1d_point', (0, 5.0)),
                      ('set_current_scan_index', (1,)), ('mark_1d_point_invalid', (1,)),
                      ('set_current_scan_index', (2,)), ('update_1d_point', (2, 9.0)),
                      ('set_current_scan_index', (3,)), ('update_1d_point', (3, 2.0))]
        else:
            dock.initialize_scan('2D', [0.0, 1.0, 2.0], [], 'deltaE', 'H',
                                 [0.0, 1.0], np.ones((2, 3), dtype=bool).tolist())
            events = [('set_current_scan_index_2d', (0, 0)), ('update_2d_point', (0, 0, 4.0)),
                      ('set_current_scan_index_2d', (1, 0)), ('mark_2d_point_invalid', (1, 0)),
                      ('set_current_scan_index_2d', (2, 0)), ('update_2d_point', (2, 0, 7.0)),
                      ('set_current_scan_index_2d', (0, 1)), ('update_2d_point', (0, 1, 1.0))]
        for method, args in events:
            getattr(dock, method)(*args, redraw=not batched)
        if batched:
            dock.redraw()
        docks.append(dock)
    return docks


def test_batched_display_updates_draw_what_the_per_point_path_draws_1d(controller):
    import numpy as np

    one_by_one, batched = _fed_docks('1D')
    np.testing.assert_array_equal(one_by_one._line.get_xdata(), batched._line.get_xdata())
    np.testing.assert_array_equal(one_by_one._line.get_ydata(), batched._line.get_ydata())
    assert len(batched._line.get_xdata()) == 3          # the invalid point is not drawn
    assert len(one_by_one.ax.collections) == len(batched.ax.collections) == 2   # unmeasured + the impossible X
    np.testing.assert_array_equal(one_by_one._unmeasured_scatter.get_offsets(),
                                  batched._unmeasured_scatter.get_offsets())
    assert one_by_one.ax.get_ylim() == batched.ax.get_ylim()
    assert one_by_one.status_label.text() == batched.status_label.text()
    assert one_by_one._current_line.get_xdata()[0] == batched._current_line.get_xdata()[0]
    assert batched._replot_pending is False


def test_batched_display_updates_draw_what_the_per_point_path_draws_2d(controller):
    import numpy as np

    one_by_one, batched = _fed_docks('2D')
    np.testing.assert_array_equal(np.ma.getdata(one_by_one._heatmap.get_array()),
                                  np.ma.getdata(batched._heatmap.get_array()))
    assert one_by_one._heatmap.get_clim() == batched._heatmap.get_clim()
    assert one_by_one._current_rect.get_xy() == batched._current_rect.get_xy()
    assert one_by_one.status_label.text() == batched.status_label.text()
    assert batched._replot_pending is False


def test_running_state_keeps_a_fast_scans_final_progress(controller):
    """A fast scan may buffer its final progress before the queued RUNNING
    signal of the next job arrives; the start reset must not wipe it."""
    ctrl = controller
    bar = ctrl.window.simulation_dock.progress_bar
    ctrl._gui_updates.latest('progress_updated', 100, 100)
    ctrl._on_job_state_changed("job-fast", JobState.RUNNING.value)
    assert bar.value() == 100, "the start of a job reset the progress to %d" % bar.value()
