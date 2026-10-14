"""The point-process guard ends what a scan point started, and only that.

Windows only; no McStas.  The stand-ins are ``sys.executable`` processes that
write their PID into a temp folder and sleep.  Every test cleans up each
process it started, by PID and creation time, in a ``finally``-style fixture
teardown, and every wait has a deadline.

Wall-time budget for this file: 10 s (the slowest case is the grandchild
orphan, about 2 s).
"""
import os
import subprocess
import sys
import threading
import time

import pytest

from tavi import point_processes as pp

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process table")

DEADLINE_S = 8.0

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
elif role == "top":
    spawn("middle")
    time.sleep(60)
elif role == "middle":
    spawn("sleeper")
    time.sleep(0.8)
'''


@pytest.fixture(scope="module", autouse=True)
def _hook():
    pp.install()


def wait_for(predicate, what, timeout=DEADLINE_S):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    pytest.fail(f"timed out after {timeout} s waiting for {what}")


def alive(pid):
    state = pp._probe(pid)
    return bool(state and state[1])


def end_by_pid(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=pp.CREATE_NO_WINDOW, timeout=15)


@pytest.fixture
def tree(tmp_path):
    """A folder for stand-in PID files; ends every PID found there at teardown."""
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8", newline="\n")
    spawned = []  # PIDs the test started by other means

    class Tree:
        dir = tmp_path
        argv = lambda self, role: [sys.executable, str(script), role, str(tmp_path)]  # noqa: E731
        track = spawned.append

        def pid(self, role):
            def read():
                try:
                    return int((tmp_path / f"{role}.pid").read_text())
                except (OSError, ValueError):
                    return None
            return wait_for(read, f"{role}.pid")

    yield Tree()
    pids = list(spawned)
    for f in tmp_path.glob("*.pid"):
        try:
            pids.append(int(f.read_text()))
        except (OSError, ValueError):
            pass
    for pid in pids:
        if alive(pid):
            end_by_pid(pid)


class Worker:
    """Runs ``fn`` inside ``scope`` on its own thread (a point thread)."""

    def __init__(self, scope, fn):
        self.result = self.exc = None
        self.thread = threading.Thread(target=self._run, args=(scope, fn), daemon=True)
        self.thread.start()

    def _run(self, scope, fn):
        try:
            with scope:
                self.result = fn()
        except BaseException as exc:  # reported to the test, which asserts on it
            self.exc = exc

    def join(self, timeout=DEADLINE_S):
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the worker thread did not finish"
        return self


def run(argv):
    return lambda: subprocess.run(argv, timeout=30).returncode


def gone(*pids):
    return wait_for(lambda: not any(alive(p) for p in pids), f"PIDs {pids} to be gone",
                    pp.KILL_WAIT_S)


# ------------------------------------------------------------------ kill tests

def test_ending_only_the_root_leaves_the_child(tree):
    """The premise: Windows keeps a child alive when its parent is ended."""
    proc = subprocess.Popen(tree.argv("parent"), creationflags=pp.CREATE_NO_WINDOW)
    tree.track(proc.pid)
    child = tree.pid("sleeper")
    proc.kill()
    proc.wait(DEADLINE_S)
    time.sleep(0.2)
    assert alive(child), "the child should have outlived its parent"


def test_kill_ends_a_process_tree(tree):
    scope = pp.PointScope()
    worker = Worker(scope, run(tree.argv("parent")))
    parent, child = tree.pid("parent"), tree.pid("sleeper")
    wait_for(lambda: scope.known(), "the root to be recorded")
    logs = []
    scope.kill(logs.append)
    assert scope.interrupted and scope.killed
    assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
    gone(parent, child)
    worker.join()
    assert worker.exc is None and worker.result is not None, "subprocess.run did not return"
    assert len(logs) == 1 and str(parent) in logs[0] and str(child) in logs[0], logs


def test_kill_twice_is_harmless(tree):
    scope = pp.PointScope()
    Worker(scope, run(tree.argv("parent")))
    tree.pid("sleeper")
    wait_for(lambda: scope.known(), "the root to be recorded")
    logs = []
    scope.kill(logs.append)
    scope.kill(logs.append)
    assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
    assert len(logs) == 1


def test_orphan_is_still_ended(tree):
    scope = pp.PointScope()
    worker = Worker(scope, run(tree.argv("orphaner")))
    orphaner, child = tree.pid("orphaner"), tree.pid("sleeper")
    worker.join()  # the recorded root has exited; its child lives on
    assert alive(child) and not alive(orphaner)
    logs = []
    scope.kill(logs.append)
    assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
    gone(child)
    assert not scope.interrupted, "the recorded process had already exited"


def test_grandchild_orphan_is_ended(tree, monkeypatch):
    monkeypatch.setattr(pp, "TRACK_INTERVAL_S", 0.05)
    scope = pp.PointScope()
    Worker(scope, run(tree.argv("top")))
    middle, grandchild = tree.pid("middle"), tree.pid("sleeper")
    # the watcher sees the grandchild, then sees the intermediate gone
    wait_for(lambda: any(p == grandchild for p, _, _ in scope.known()), "the grandchild to be known")
    wait_for(lambda: any(p == middle and g is not None for p, _, g in scope.known()),
             "the intermediate to be seen gone")
    assert alive(grandchild) and not alive(middle)
    scope.kill(lambda m: None)
    assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
    gone(grandchild, tree.pid("top"))


def test_late_kill_leaves_interrupted_false():
    scope = pp.PointScope()
    Worker(scope, run([sys.executable, "-c", "pass"])).join()
    logs = []
    scope.kill(logs.append)
    assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
    assert scope.killed and not scope.interrupted
    assert len(logs) == 1


def test_a_process_outside_the_scope_is_not_reached(tree):
    scope = pp.PointScope()
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        release.wait(DEADLINE_S)

    worker = Worker(scope, hold)
    assert entered.wait(DEADLINE_S)
    # started on this (the main) thread while the scope is active on another
    outsider = subprocess.Popen(tree.argv("sleeper"), creationflags=pp.CREATE_NO_WINDOW)
    tree.track(outsider.pid)
    try:
        tree.pid("sleeper")
        logs = []
        scope.kill(logs.append)
        assert scope.wait_killed(pp.KILL_WAIT_S + 1) == []
        assert "no process was recorded" in logs[0]
        time.sleep(0.3)
        assert outsider.poll() is None and alive(outsider.pid)
    finally:
        release.set()
        worker.join()
        end_by_pid(outsider.pid)


def test_survivors_are_named(tree, monkeypatch):
    monkeypatch.setattr(pp, "KILL_WAIT_S", 0.4)
    monkeypatch.setattr(pp, "_taskkill", lambda pid: None)
    scope = pp.PointScope()
    worker = Worker(scope, lambda: subprocess.Popen(tree.argv("sleeper"),
                                                    creationflags=pp.CREATE_NO_WINDOW)).join()
    proc = worker.result
    tree.track(proc.pid)
    logs = []
    scope.kill(logs.append)
    survivors = scope.wait_killed(5.0)
    image = pp._read_table()[proc.pid][1]
    # a console host may ride along as a child of the stand-in; the stand-in must be named
    assert (proc.pid, image) in [(s.pid, s.image) for s in survivors]
    assert len(logs) == 1 and str(proc.pid) in logs[0] and image in logs[0] and "by hand" in logs[0]
    assert scope.interrupted and alive(proc.pid)


# --------------------------------------------------------------- launch refusal

def test_a_launch_after_a_stop_request_is_refused(tmp_path):
    marker = tmp_path / "ran"
    scope = pp.PointScope(stop_requested=lambda: True)
    worker = Worker(scope, run([sys.executable, "-c", f"open({str(marker)!r}, 'w')"])).join()
    assert isinstance(worker.exc, pp.PointLaunchRefused) and isinstance(worker.exc, OSError)
    assert scope.refused and not marker.exists() and scope.known() == []


def test_only_the_first_launch_checks_the_stop_flag_and_a_kill_refuses_all(tmp_path):
    stop = threading.Event()
    scope = pp.PointScope(stop_requested=stop.is_set)
    quick = [sys.executable, "-c", "pass"]

    def sequence():
        subprocess.run(quick, timeout=30)
        stop.set()
        subprocess.run(quick, timeout=30)       # the point already began: allowed
        scope.kill(lambda m: None)
        with pytest.raises(pp.PointLaunchRefused):
            subprocess.run(quick, timeout=30)

    worker = Worker(scope, sequence).join()
    assert worker.exc is None, worker.exc
    assert scope.refused and scope.killed and len(scope.known()) == 2


# ------------------------------------------------------ the known-set rule itself

def _table(*rows):
    return {pid: (ppid, f"p{pid}.exe") for pid, ppid in rows}


def test_creation_time_window_rejects_reused_pids():
    """Synthetic tables: no real PID reuse is needed to pin the rule."""
    known = [pp._Known(100, 1000, None, "a.exe")]
    states = {100: (1000, True), 200: (1500, True), 201: (900, True), 400: (1600, True)}
    pp._discover(known, _table((100, 4), (200, 100), (201, 100), (400, 200)),
                 states.get, now=1700)
    assert sorted(e.pid for e in known) == [100, 200, 400]  # 201 predates its parent
    assert all(e.gone is None for e in known)

    # PID 100 died and was reused by an unrelated process created at 3000
    known = [pp._Known(100, 1000, None, "a.exe")]
    states = {100: (3000, True), 300: (2500, True), 301: (1800, False), 302: (1200, True)}
    pp._discover(known, _table((100, 4), (300, 100), (301, 100), (302, 100)),
                 states.get, now=2000)
    by_pid = {e.pid: e for e in known}
    assert by_pid[100].gone == 2000 and not any(e.pid == 100 and e.created == 3000 for e in known)
    assert 300 not in by_pid, "created after the entry was seen gone"
    assert by_pid[301].gone == 2000 and by_pid[302].gone is None  # inside the window: collected

    # an entry already seen gone keeps its window closed
    known = [pp._Known(100, 1000, 1900, "a.exe")]
    states = {100: None, 500: (1950, True), 501: (1850, True)}
    pp._discover(known, _table((500, 100), (501, 100)), states.get, now=5000)
    assert sorted(e.pid for e in known) == [100, 501]


# --------------------------------------------------------------------- install

def test_install_twice_keeps_one_wrapper_and_the_guard():
    pp.install()
    first = subprocess.Popen.__init__
    pp.install()
    assert subprocess.Popen.__init__ is first
    assert getattr(first, "_tavi_no_window", False), "the conftest tripwire attribute was lost"
    hooks, fn = 0, first
    while fn is not None:
        hooks += "_tavi_point_hook" in vars(fn)
        fn = getattr(fn, "__wrapped__", None)
    assert hooks == 1
    # outside a scope the wrapper only calls through
    assert subprocess.run([sys.executable, "-c", "pass"], timeout=30).returncode == 0
