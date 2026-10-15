"""The two-stage stop: graceful first, then a force stop that ends the point's processes.

Offscreen Qt with the real window and controller (``api_overrides={"disabled":
True}``), no McStas: the plugin's ``build`` and ``run_point`` and the detector
reader are replaced by stand-ins.  A stand-in ``run_point`` runs on the
controller's point thread inside its real ``PointScope`` and launches
``sys.executable`` processes (a parent that starts a sleeping child), so the
scope records and the force stop ends real process trees.

Every process a test starts is ended by verified identity in cleanup: the test
opens a handle on each stand-in PID while that stand-in is known to be alive
(it wrote its own PID file), and teardown terminates only through those
handles.  Nothing is killed by image name or by a bare PID.

Wall-time budget for this file: 20 s.  Every wait has a wall-clock deadline
that fails the test rather than hanging it.
"""
import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi import point_processes as pp  # noqa: E402
from tavi.scan_jobs import JobState  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")

DEADLINE_S = 10.0
COUNTS = 10.0                 # what the stand-in detector reader returns
SCAN = "deltaE 10 20 5"       # three PUMA points, all feasible at H=1 K=0 L=0
TERMINAL = (JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.STOPPED)

STAND_IN = '''
import os, subprocess, sys, time
from pathlib import Path
role, d = sys.argv[1], Path(sys.argv[2])
def note(name):
    tmp = d / (name + ".tmp")
    tmp.write_text(str(os.getpid()))
    tmp.replace(d / name)
def spawn(child):
    return subprocess.Popen([sys.executable, __file__, child, str(d)], creationflags=0x08000000)
note(role + ".pid")
if role == "sleeper":
    time.sleep(60)
elif role == "parent":
    spawn("sleeper")
    time.sleep(60)
elif role == "orphaner":
    spawn("sleeper")
'''


def _new_controller(instrument_id="puma"):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    window = cm.TAVIMainWindow(
        get_instrument(instrument_id).descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, get_instrument(instrument_id),
                             api_overrides={"disabled": True})
    return app, window, ctrl


@pytest.fixture(scope="module")
def controller():
    app, window, ctrl = _new_controller()
    print("import root:", os.path.dirname(cm.__file__), file=sys.__stdout__)
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def pump_until(predicate, what, timeout=DEADLINE_S):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    pytest.fail(f"timed out after {timeout} s waiting for {what}")


def pump_for(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def state(job):
    with job.lock:
        return job.state


def wait_terminal(job):
    pump_until(lambda: state(job) in TERMINAL, f"job {job.job_id} to end")
    pump_until(lambda: job.result is not None, "its result")
    return state(job)


def log_text(ctrl):
    ctrl._drain_updates()
    return ctrl.window.output_dock.message_text.toPlainText()


class StandIn:
    """``run_point`` scripted per call, in call order (jobs run one at a time).

    Modes: ``ok`` returns at once; ``tree`` runs a parent+sleeper tree and
    returns when it ends; ``compile`` is ``tree`` and then marks the execution
    state compiled, as ``run_tas_point`` does after ``backengine()``; ``late``
    runs a process that exits, then holds; ``orphan`` runs a parent that leaves
    a sleeping child and exits, then holds; ``block`` starts a tree and holds,
    ignoring the kill; ``hold`` holds; ``gate`` holds, then launches a sleeper;
    ``relaunch`` runs a process that exits, holds, then launches a sleeper.
    A callable is called with (call number, output folder) and returns at once.
    """

    def __init__(self, ctrl, root, script):
        self.ctrl, self.root, self.script = ctrl, root, list(script)
        self.path = root / "stand_in.py"
        self.path.write_text(STAND_IN, encoding="utf-8", newline="\n")
        n = len(self.script)
        self.started = [threading.Event() for _ in range(n)]
        self.release = [threading.Event() for _ in range(n)]
        self.returned = [threading.Event() for _ in range(n)]
        self.calls, self.scopes, self.states, self.raised = [], [], [], {}
        self.threads = []  # the point thread of each call
        self.held = []  # pp._Proc handles on stand-in processes, opened while alive

    def dir(self, n):
        d = self.root / f"call{n}"
        d.mkdir(exist_ok=True)
        return d

    def argv(self, role, n):
        return [sys.executable, str(self.path), role, str(self.dir(n))]

    def pid(self, n, role):
        """Wait for a stand-in's PID file and hold a handle on it (its identity)."""
        def read():
            try:
                return int((self.dir(n) / f"{role}.pid").read_text())
            except (OSError, ValueError):
                return None
        found = pump_until(read, f"call {n} {role}.pid")
        proc = pp._open_proc(found)
        assert proc is not None and proc.running(), f"{role} {found} is not running"
        self.held.append(proc)
        return proc

    def _hold(self, n):
        self.started[n].set()
        if not self.release[n].wait(DEADLINE_S):
            raise RuntimeError(f"stand-in call {n} was never released")

    def __call__(self, instrument, snapshot, output_folder, number_neutrons,
                 execution_state, mpi_count=1):
        n = len(self.calls)
        self.calls.append((snapshot.scan_index, output_folder))
        self.scopes.append(getattr(self.ctrl, "_active_scope", None))
        self.threads.append(threading.current_thread())
        self.states.append(execution_state)
        mode = self.script[n] if n < len(self.script) else "ok"
        try:
            os.makedirs(output_folder, exist_ok=True)
            if callable(mode):
                mode(n, output_folder)
            elif mode in ("tree", "compile", "block"):
                # A partial point: what a killed McStas run leaves behind.
                with open(os.path.join(output_folder, "detector.dat"), "w",
                          encoding="utf-8", newline="\n") as fh:
                    fh.write("# partial\n")
                with open(os.path.join(output_folder, "scan_parameters.txt"), "w",
                          encoding="utf-8", newline="\n") as fh:
                    fh.write("deltaE: 15.0\n")
                if mode == "block":
                    subprocess.Popen(self.argv("parent", n))
                    self._hold(n)
                else:
                    self.started[n].set()
                    subprocess.run(self.argv("parent", n), timeout=30)
                    if mode == "compile":
                        binary = self.root / "instrument.exe"
                        binary.write_bytes(b"half-built")
                        execution_state.first_backengine_succeeded = True
                        execution_state.binary_path = str(binary)
                        execution_state.binary_cwd = str(self.root)
                        execution_state.mpi_launcher_argv = ["mpiexec"]
                        execution_state.direct_run_ready = True
            elif mode == "late":
                subprocess.run([sys.executable, "-c", "pass"], timeout=30)
                self._hold(n)
            elif mode == "orphan":
                subprocess.run(self.argv("orphaner", n), timeout=30)
                self._hold(n)
            elif mode == "hold":
                self._hold(n)
            elif mode == "relaunch":
                subprocess.run([sys.executable, "-c", "pass"], timeout=30)
                self._hold(n)
                try:
                    subprocess.run(self.argv("sleeper", n), timeout=30)
                except BaseException as exc:  # recorded for the test, then re-raised as McStasScript would
                    self.raised[n] = exc
                    raise
            elif mode == "gate":
                self._hold(n)
                try:
                    subprocess.run(self.argv("sleeper", n), timeout=30)
                except BaseException as exc:  # recorded for the test, then re-raised as McStasScript would
                    self.raised[n] = exc
                    raise
        finally:
            if n < len(self.returned):
                self.returned[n].set()
        info = {'mode': 'stub', 'returncode': 0, 'stdout': '', 'binary_path': None,
                'output_folder': output_folder, 'error_message': None,
                'launcher_argv': [], 'armed_direct_run': False}
        return "stub-data", [], info

    def cleanup(self):
        for event in self.release:
            event.set()
        for proc in self.held:
            if proc.running():
                proc.terminate()
            proc.close()


@pytest.fixture
def rig(controller, tmp_path, monkeypatch):
    """The module's controller with McStas replaced; makes stand-ins and jobs."""
    ctrl = controller
    ctrl.output_directory = str(tmp_path / "output")
    ctrl._binary_reuse_cache = None
    monkeypatch.setattr(ctrl.instrument, "build", lambda *a, **k: "stub-instrument")
    monkeypatch.setattr(cm, "read_1Ddetector_file", lambda folder: (1.0, 0.1, COUNTS))
    ctrl.window.output_dock.message_text.clear()
    stand_ins = []

    class Rig:
        def stand_in(self, *script):
            s = StandIn(ctrl, tmp_path, script)
            stand_ins.append(s)
            monkeypatch.setattr(ctrl.instrument, "run_point", s)
            return s

        def submit(self, scan=SCAN, engine=None):
            launch = ctrl.build_api_launch_state(
                {"H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": scan})
            if engine:
                launch["engine"] = engine
            ctrl._compile_launch(launch)
            n = len(launch["expansion"].points)
            launch["planned_feasible_mask"] = [True] * n
            return ctrl.submit_scan_job(launch, "gui")

    yield Rig()
    for s in stand_ins:
        s.cleanup()
    if not ctrl.is_idle():
        ctrl.force_stop_all()
    pump_until(ctrl.is_idle, "the controller to be idle after the test")


def stop_button(ctrl):
    return ctrl.window.simulation_dock.stop_button


def records(ctrl):
    return sum(len(v) for v in ctrl.runtime_tracker.records.values())


# --------------------------------------------------------------- force stop

def test_second_click_kills_the_tree_and_discards_the_point(rig, controller):
    ctrl = controller
    seen_by_next = {}

    def next_job_first_point(n, folder):
        seen_by_next["killed_folder_exists"] = os.path.isdir(killed_folder[0])
        seen_by_next["tree_running"] = [p.running() for p in tree]

    s = rig.stand_in("ok", "tree", next_job_first_point, "hold")
    shown = []
    dock = ctrl.window.display_dock
    real_update = dock.update_1d_point

    def recording_update(index, counts, redraw=True):
        shown.append(index)
        return real_update(index, counts, redraw=redraw)

    dock.update_1d_point = recording_update
    try:
        before = records(ctrl)
        job = rig.submit()
        nxt = rig.submit()          # queued behind it
        pump_until(s.started[1].is_set, "the killed point to start")
        killed_folder = [s.calls[1][1]]
        tree = [s.pid(1, "parent"), s.pid(1, "sleeper")]
        assert job.result.valid_mask_1 == [True, True, True]

        stop_button(ctrl).click()
        assert stop_button(ctrl).text() == "Force stop"
        assert "the scan stops after the current point" in log_text(ctrl)
        assert "Click Force stop to end it immediately" in log_text(ctrl)
        pump_for(0.3)
        assert state(job) == JobState.RUNNING, "a graceful stop must let the point run"
        assert all(p.running() for p in tree)

        t0 = time.monotonic()
        stop_button(ctrl).click()
        assert wait_terminal(job) == JobState.STOPPED
        print(f"force stop to terminal: {time.monotonic() - t0:.2f} s", file=sys.__stdout__)
        assert not any(p.running() for p in tree), "the point's process tree survived"
        assert job.result.stop_mode == "kill"
        assert job.result.counts == [COUNTS, None, None]
        assert job.result.executed_feasible_mask == [True, False, False]
        assert 0 in shown and 1 not in shown, f"the display was given points {shown}"
        data_folder = job.result.output_folder
        assert not os.path.exists(killed_folder[0])
        assert os.path.isfile(os.path.join(data_folder, "scan_0000", "scan_parameters.txt"))
        assert not os.path.exists(os.path.join(data_folder, "1D_scan_data.txt"))
        import json
        with open(os.path.join(data_folder, "stage_timing_summary.json"), encoding="utf-8") as fh:
            timings = json.load(fh)["point_timings"]
        assert [t["scan_index"] for t in timings] == [0]
        assert records(ctrl) == before
        text = log_text(ctrl)
        assert "Scan force-stopped: point 2 of 3 was discarded" in text
        assert f"partial output folder was deleted: {killed_folder[0]}" in text

        # The next job starts only after the kill, its wait and the folder removal.
        pump_until(lambda: state(nxt) == JobState.RUNNING and s.started[3].is_set(),
                   "the next job's held point")
        assert seen_by_next == {"killed_folder_exists": False, "tree_running": [False, False]}
        with job.lock, nxt.lock:
            assert nxt.started_at >= job.finished_at
        assert stop_button(ctrl).text() == "Stop Simulation"

        # Its first click is graceful again.
        stop_button(ctrl).click()
        assert stop_button(ctrl).text() == "Force stop"
        with nxt.lock:
            assert nxt.stop_request == "graceful"
        s.release[3].set()
        assert wait_terminal(nxt) == JobState.STOPPED
        assert nxt.result.stop_mode == "graceful"
        assert nxt.result.counts[0] == COUNTS
        pump_until(lambda: stop_button(ctrl).text() == "Stop Simulation", "the label to return")
    finally:
        dock.update_1d_point = real_update


def test_a_kill_after_the_process_exited_records_the_point(rig, controller):
    ctrl = controller
    s = rig.stand_in("late")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point's process to exit")
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    with job.lock:
        assert job.stop_request == "kill"
    assert s.scopes[0].killed and not s.scopes[0].interrupted
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert job.result.stop_mode == "kill"
    assert job.result.counts == [COUNTS, None, None]
    assert job.result.executed_feasible_mask == [True, False, False]
    assert os.path.isfile(os.path.join(s.calls[0][1], "scan_parameters.txt"))


def test_an_orphan_alive_at_the_kill_discards_the_point(rig, controller):
    """The root had exited but its orphaned child was running at the kill: not executed."""
    ctrl = controller
    seen, next_may_finish = {}, threading.Event()

    def next_point(n, folder):   # held so the runtime records cannot change under the check
        seen.update(orphan_running=orphan.running())
        next_may_finish.wait(DEADLINE_S)

    s = rig.stand_in("orphan", next_point)
    job = rig.submit()
    before = records(ctrl)
    pump_until(s.started[0].is_set, "the orphaner to exit")
    orphan = s.pid(0, "sleeper")
    nxt = rig.submit(scan="deltaE 10 10 5")
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert not s.scopes[0].interrupted, "the root had exited: the point is not interrupted"
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert not orphan.running(), "the orphaned child survived the force stop"
    assert job.result.counts == [None, None, None]
    assert job.result.executed_feasible_mask == [False, False, False]
    assert job.result.stop_mode == "kill"
    assert records(ctrl) == before, "a discarded point reached the runtime records"
    assert not os.path.exists(s.calls[0][1]), "the discarded point's folder survived"
    pump_until(lambda: "orphan_running" in seen, "the next job's point")
    assert seen == {"orphan_running": False}, "the next job started before the orphan was gone"
    next_may_finish.set()
    assert wait_terminal(nxt) == JobState.DONE


def test_a_discarded_point_is_named_one_based_of_the_scan(rig, controller):
    ctrl = controller
    s = rig.stand_in("tree")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    tree = [s.pid(0, "parent"), s.pid(0, "sleeper")]
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert wait_terminal(job) == JobState.STOPPED
    assert not any(p.running() for p in tree)
    assert "Scan force-stopped: point 1 of 3 was discarded (not executed)." in log_text(ctrl)


def test_a_kill_during_the_compile_leaves_no_reusable_binary(rig, controller):
    ctrl = controller
    stale = {"fingerprint": "an older build", "instrument": object(),
              "execution_state": cm.RunExecutionState(), "instr_path": None}
    ctrl._binary_reuse_cache = stale
    s = rig.stand_in("compile")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the compile point to start")
    tree = [s.pid(0, "parent"), s.pid(0, "sleeper")]
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert wait_terminal(job) == JobState.STOPPED
    assert not any(p.running() for p in tree)
    assert ctrl._binary_reuse_cache is None
    state_after = s.states[0]
    assert not state_after.first_backengine_succeeded
    assert not state_after.direct_run_ready
    assert "the next scan compiles again" in log_text(ctrl)


def test_a_folder_that_cannot_be_deleted_loses_its_parameters_file(rig, controller, monkeypatch):
    ctrl = controller
    real_rmtree = cm.shutil.rmtree

    def failing_rmtree(path, *args, **kwargs):
        if os.path.basename(str(path)).startswith("scan_"):
            raise PermissionError(13, "held by a dying process", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cm.shutil, "rmtree", failing_rmtree)
    s = rig.stand_in("tree")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    tree = [s.pid(0, "parent"), s.pid(0, "sleeper")]
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert wait_terminal(job) == JobState.STOPPED
    assert not any(p.running() for p in tree)
    folder = s.calls[0][1]
    assert os.path.isdir(folder)
    assert not os.path.exists(os.path.join(folder, "scan_parameters.txt"))
    text = log_text(ctrl)
    assert "parameters file was removed" in text
    assert f"The folder is not data: {folder}" in text
    assert job.result.counts == [None, None, None]


def test_a_blocked_point_ends_the_scan_and_a_late_wake_keeps_the_new_scope(
        rig, controller, monkeypatch):
    ctrl = controller
    monkeypatch.setattr(ctrl, "POINT_JOIN_AFTER_KILL_S", 0.2)
    s = rig.stand_in("block", "hold")
    job = rig.submit()
    nxt = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    tree = [s.pid(0, "parent"), s.pid(0, "sleeper")]
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert wait_terminal(job) == JobState.STOPPED, "a blocked point must not hold the scan"
    assert not any(p.running() for p in tree)
    assert not s.returned[0].is_set(), "the stand-in should still be blocked"
    assert "still blocked after its processes were ended" in log_text(ctrl)
    assert job.result.counts == [None, None, None]
    assert not os.path.exists(s.calls[0][1])

    pump_until(lambda: s.started[1].is_set(), "the next job's point")
    new_scope = s.scopes[1]
    assert new_scope is not None and ctrl._active_scope is new_scope
    s.release[0].set()      # the left-behind point thread wakes now
    s.threads[0].join(DEADLINE_S)
    assert not s.threads[0].is_alive(), "the left-behind point thread did not end"
    assert ctrl._active_scope is new_scope, "a late wake cleared the next point's scope"
    s.release[1].set()
    assert wait_terminal(nxt) == JobState.DONE


def test_a_kill_after_every_process_exited_ends_a_blocked_call_in_bounded_time(
        rig, controller, monkeypatch):
    ctrl = controller
    monkeypatch.setattr(pp, "KILL_WAIT_S", 0.5)
    monkeypatch.setattr(ctrl, "POINT_JOIN_AFTER_KILL_S", 0.2)
    s = rig.stand_in("late")  # its process exits, then the call holds until teardown
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point's process to exit")
    t0 = time.monotonic()
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    final = wait_terminal(job)
    print(f"blocked point: scan ended {time.monotonic() - t0:.2f} s after the kill", file=sys.__stdout__)
    assert time.monotonic() - t0 < 5.0, "a blocked call held the scan"
    assert final == JobState.STOPPED
    assert not s.returned[0].is_set(), "the stand-in should still be blocked"
    assert "Point 1 of 3: its McStas call is still blocked after its processes were ended" in log_text(ctrl)
    assert job.result.counts == [None, None, None]
    assert job.result.executed_feasible_mask == [False, False, False]
    assert not os.path.exists(s.calls[0][1])


def test_a_launch_refused_after_a_kill_discards_the_point(rig, controller, monkeypatch):
    """The kill lands after the point's process exited; the call launches again while
    the worker waits for it, and that launch is refused: the point is not executed."""
    ctrl = controller
    s = rig.stand_in("relaunch")  # its process exits, then the call holds, then launches again
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point's process to exit")
    scope = s.scopes[0]
    waiting = threading.Event()
    real_wait = scope.wait_killed

    def wait_then_mark(timeout):  # the worker has read its kill-time flags and is now joining the call
        survivors = real_wait(timeout)
        waiting.set()
        return survivors

    monkeypatch.setattr(scope, "wait_killed", wait_then_mark)
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    pump_until(waiting.is_set, "the worker to wait for the kill")
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert isinstance(s.raised.get(0), pp.PointLaunchRefused)
    assert job.result.stop_mode == "kill"
    assert job.result.counts == [None, None, None]
    assert job.result.executed_feasible_mask == [False, False, False]
    assert not os.path.exists(os.path.join(s.dir(0), "sleeper.pid")), "the refused launch created a process"
    assert not os.path.exists(s.calls[0][1]), "the discarded point's folder survived"


# --------------------------------------------------------------- graceful and races

def test_a_graceful_stop_alone_records_the_point_in_flight(rig, controller):
    ctrl = controller
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    stop_button(ctrl).click()
    assert stop_button(ctrl).text() == "Force stop"
    pump_for(0.2)
    assert state(job) == JobState.RUNNING
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert job.result.stop_mode == "graceful"
    assert job.result.counts == [COUNTS, None, None]
    assert job.result.executed_feasible_mask == [True, False, False]
    pump_until(lambda: stop_button(ctrl).text() == "Stop Simulation", "the label to return")


def test_dock_cancel_cancels_a_queued_job_and_shares_the_two_stages(rig, controller):
    ctrl = controller
    s = rig.stand_in("hold")
    job = rig.submit()
    queued = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    ctrl.cancel_job(queued.job_id)
    assert state(queued) == JobState.CANCELLED
    ctrl.cancel_job(job.job_id)                 # first GUI request: graceful
    with job.lock:
        assert job.stop_request == "graceful"
    assert stop_button(ctrl).text() == "Force stop"
    stop_button(ctrl).click()                   # second, from the other control: kill
    with job.lock:
        assert job.stop_request == "kill"
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert job.result.stop_mode == "kill"
    pump_until(ctrl.is_idle, "the worker to finish")
    with queued.lock:
        assert queued.state == JobState.CANCELLED and queued.started_at is None
    assert queued.result is None


def test_a_cancel_while_the_worker_dequeues_is_never_lost(rig, controller, monkeypatch):
    """The seam: the worker's stop_event.clear() runs between its cancelled check and
    the RUNNING transition on the old code; it waits briefly for a cancel there."""
    ctrl = controller
    in_clear, cancelled = threading.Event(), threading.Event()

    class SeamEvent(threading.Event):
        armed = True

        def clear(self):
            if SeamEvent.armed:
                SeamEvent.armed = False
                in_clear.set()
                cancelled.wait(0.5)
            super().clear()

    monkeypatch.setattr(ctrl, "stop_event", SeamEvent())
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(in_clear.is_set, "the worker to dequeue")
    ctrl.cancel_job(job.job_id)
    cancelled.set()
    s.release[0].set()
    final = wait_terminal(job)
    assert final != JobState.DONE, "the cancel was overwritten and the job ran to the end"
    if final == JobState.STOPPED:
        assert job.result.stop_mode == "graceful"


def test_a_stop_between_check_and_launch_refuses_the_launch(rig, controller):
    ctrl = controller
    s = rig.stand_in("gate")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point thread to reach its launch")
    assert ctrl.request_stop(kill=False) == "graceful"
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    assert isinstance(s.raised.get(0), pp.PointLaunchRefused)
    scope = s.scopes[0]
    assert scope.refused and scope.known() == [], "a process was created after the stop"
    assert job.result.counts == [None, None, None]
    assert job.result.executed_feasible_mask == [False, False, False]
    assert not os.path.exists(s.calls[0][1])
    assert "Point 1 of 3 was not executed: the stop arrived before its McStas process started" in log_text(ctrl)


def test_a_click_after_the_relabelled_job_ended_stops_nothing(rig, controller):
    """The label names job A; A ended and queued job B started before the GUI handled it."""
    ctrl = controller
    s = rig.stand_in("hold", "hold")
    first = rig.submit()
    second = rig.submit()
    pump_until(s.started[0].is_set, "the first job's point")
    stop_button(ctrl).click()                 # relabels the button for the first job
    assert stop_button(ctrl).text() == "Force stop"
    s.release[0].set()
    # No event processing here: the GUI must not yet see the first job's end.
    end = time.monotonic() + DEADLINE_S
    while not (state(first) in TERMINAL and s.started[1].is_set()):
        assert time.monotonic() < end, "the second job did not start"
        time.sleep(0.01)
    assert ctrl._force_stop_label_job == first.job_id
    stop_button(ctrl).click()
    with second.lock:
        assert second.stop_request is None, "a click for the ended job stopped the next one"
    assert state(second) == JobState.RUNNING
    assert stop_button(ctrl).text() == "Stop Simulation"
    assert f"scan job {first.job_id} has already ended and nothing else was stopped" in log_text(ctrl)
    s.release[1].set()
    assert wait_terminal(second) == JobState.DONE


def test_the_stop_button_says_what_a_second_click_does(rig, controller):
    ctrl = controller

    def names_the_second_click():
        tip = stop_button(ctrl).toolTip()
        return "Click again to force stop" in tip

    assert names_the_second_click(), repr(stop_button(ctrl).toolTip())
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    stop_button(ctrl).click()
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    pump_until(lambda: stop_button(ctrl).text() == "Stop Simulation", "the label to return")
    assert names_the_second_click(), repr(stop_button(ctrl).toolTip())


def test_a_kill_with_nothing_to_end_logs_the_request_before_its_outcome(rig, controller):
    ctrl = controller
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    text = log_text(ctrl)
    assert "no process was recorded" in text, text
    assert text.index("is being force-stopped now") < text.index("no process was recorded"), text
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED


def test_a_kill_that_finds_the_job_finished_says_so(rig, controller):
    """The job ends between the RUNNING read and request_stop: the log must not stand at 'force-stopped'."""
    ctrl = controller
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    stop_button(ctrl).click()
    ctrl.request_stop = lambda job_id=None, *, kill=False: "finished"   # the race, made certain
    try:
        stop_button(ctrl).click()
    finally:
        del ctrl.request_stop
    text = log_text(ctrl)
    assert "had already ended; nothing was killed" in text, text
    assert text.index("is being force-stopped now") < text.index("had already ended"), text
    assert stop_button(ctrl).text() != "Stopping..."
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED


def test_a_force_stop_under_way_disables_the_button_until_the_scan_ends(rig, controller):
    ctrl = controller
    s = rig.stand_in("hold")
    job = rig.submit()
    pump_until(s.started[0].is_set, "the point to start")
    stop_button(ctrl).click()
    stop_button(ctrl).click()
    assert stop_button(ctrl).text() == "Stopping..."
    assert not stop_button(ctrl).isEnabled()
    assert "Force stop under way" in stop_button(ctrl).toolTip()
    s.release[0].set()
    assert wait_terminal(job) == JobState.STOPPED
    pump_until(lambda: stop_button(ctrl).text() == "Stop Simulation", "the label to return")
    assert stop_button(ctrl).isEnabled()


# --------------------------------------------------------------- analytic engine

def test_an_analytic_scans_second_click_ends_it_as_a_kill(rig, controller, monkeypatch):
    ctrl = controller
    reached, release = threading.Event(), threading.Event()
    calls = []

    def yield_to_gui():
        calls.append(None)
        if len(calls) == 3:
            reached.set()
            release.wait(DEADLINE_S)

    monkeypatch.setattr(ctrl, "_yield_to_gui", yield_to_gui)
    job = rig.submit(scan="deltaE 10 20 2.5", engine="deterministic")
    try:
        pump_until(reached.is_set, "the analytic scan's third point")
        stop_button(ctrl).click()
        assert stop_button(ctrl).text() == "Force stop"
        stop_button(ctrl).click()
    finally:
        release.set()
    assert wait_terminal(job) == JobState.STOPPED
    assert job.result.stop_mode == "kill"
    counts = job.result.counts
    assert counts[0] is not None and counts[1] is not None and counts[2:] == [None] * 3
    pump_until(lambda: stop_button(ctrl).text() == "Stop Simulation", "the label to return")


def test_two_fast_jobs_leave_the_second_jobs_final_progress(rig, controller):
    """Both jobs finish before any of their state signals is handled."""
    ctrl = controller
    QApplication.processEvents()
    ctrl._gui_idle.set()
    first = rig.submit(engine="deterministic")
    second = rig.submit(engine="deterministic")
    ctrl._gui_idle.set()      # a submission's drain may have cleared it; nothing redraws now
    end = time.monotonic() + DEADLINE_S
    while not (state(first) in TERMINAL and state(second) in TERMINAL):
        assert time.monotonic() < end, "the two analytic jobs did not finish"
        time.sleep(0.01)          # no event processing: the signals stay queued
    pump_for(0.5)
    dock = ctrl.window.simulation_dock
    assert dock.progress_bar.value() == 100, dock.progress_label.text()
    assert dock.progress_label.text() == "100% (3/3)"


# --------------------------------------------------------------- shutdown

def test_shutdown_during_a_point_leaves_no_process_behind(tmp_path, monkeypatch):
    app, window, ctrl = _new_controller()
    s = None
    try:
        ctrl.output_directory = str(tmp_path / "output")
        monkeypatch.setattr(ctrl.instrument, "build", lambda *a, **k: "stub-instrument")
        monkeypatch.setattr(cm, "read_1Ddetector_file", lambda folder: (1.0, 0.1, COUNTS))
        s = StandIn(ctrl, tmp_path, ["tree"])
        monkeypatch.setattr(ctrl.instrument, "run_point", s)
        launch = ctrl.build_api_launch_state(
            {"H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": SCAN})
        ctrl._compile_launch(launch)
        job = ctrl.submit_scan_job(launch, "gui")
        queued = ctrl.submit_scan_job(launch, "gui")
        pump_until(s.started[0].is_set, "the point to start")
        tree = [s.pid(0, "parent"), s.pid(0, "sleeper")]
        t0 = time.monotonic()
        ctrl.shutdown()
        took = time.monotonic() - t0
        print(f"shutdown took {took:.2f} s (bound {ctrl.CLOSE_WAIT_S} s)", file=sys.__stdout__)
        assert took < ctrl.CLOSE_WAIT_S
        assert not any(p.running() for p in tree), "shutdown left the point's processes running"
        assert state(job) == JobState.STOPPED and job.result.stop_mode == "kill"
        assert state(queued) == JobState.CANCELLED
        assert ctrl.is_idle()
    finally:
        if s is not None:
            s.cleanup()
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()
