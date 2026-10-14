"""Record the processes a scan point starts, and end exactly those on demand.

Windows only, like TAVI's installer; there is no other platform branch.  No Qt
imports and no dependency beyond the standard library and ``ctypes``.

A ``PointScope`` is entered on the thread that runs one Monte Carlo point.
While it is active, every process that thread launches through
``subprocess.Popen`` is recorded (the ``mpiexec`` launcher of a direct point,
or the ``cmd.exe`` under which McStasScript compiles and runs the first
point).  Launches on any other thread, and on any thread with no scope, are
never recorded -- so the restarted TAVI window, which the main thread starts
after the event loop has ended, can never be reached.

``install()`` wraps ``subprocess.Popen.__init__`` once.  Outside a scope the
wrapper only calls through.  Inside one it does *check, launch, record* as one
step under the scope lock: a launch after a kill, or the scope's first launch
after a stop was requested, is refused with ``PointLaunchRefused`` (an
``OSError``, so ``tas_runtime``'s existing launch-failure path handles it).

``PointScope.kill(log)`` ends every live process of the scope's *known set* and
returns at once; a daemon thread does the work and reports through ``log``.
The known set is the recorded roots plus their descendants, tracked by a
watcher thread while the point runs and re-scanned during the kill, so a worker
whose launcher exited first is still found.  An entry is
``(pid, creation time, first seen gone)``.  A process joins the set when its
parent PID matches an entry and its creation time lies between that entry's
creation and the time the entry was first seen gone; the window is what stops
a reused PID from pulling an unrelated process in.

Lock discipline (the controller's order is ``_stop_lock``, then this scope's
lock, then a ``job.lock``): the scope lock is held only around
check-then-launch-then-record, ``kill``'s flag updates, and reading or merging
the known set.  It is never held across a process-table read, a ``taskkill``,
a sleep or a join.

Test budget: ``tests/test_point_processes.py`` keeps to 10 s.
"""
import ctypes
import functools
import logging
import os
import subprocess
import threading
import time
from collections import namedtuple
from ctypes import wintypes

logger = logging.getLogger(__name__)

TRACK_INTERVAL_S = 1.0   # how often the watcher reads the process table
KILL_WAIT_S = 10.0       # how long a kill keeps trying before it names survivors
KILL_POLL_S = 0.1        # the kill thread's rescan period

CREATE_NO_WINDOW = 0x08000000

Survivor = namedtuple("Survivor", "pid image")


class PointLaunchRefused(OSError):
    """A launch inside a scope was refused because a stop or kill came first."""


# ---------------------------------------------------------------- Win32 layer

_TH32CS_SNAPPROCESS = 0x2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x102
_ERROR_INVALID_PARAMETER = 87  # OpenProcess on a PID that does not exist
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
for _fn in (_k32.Process32FirstW, _k32.Process32NextW):
    _fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _fn.restype = wintypes.BOOL
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_k32.GetProcessTimes.restype = wintypes.BOOL
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
_k32.GetSystemTimeAsFileTime.restype = None


def _ft(filetime):
    return (filetime.dwHighDateTime << 32) | filetime.dwLowDateTime


def _filetime_now():
    ft = wintypes.FILETIME()
    _k32.GetSystemTimeAsFileTime(ctypes.byref(ft))
    return _ft(ft)


def _read_table():
    """The process table as ``{pid: (parent pid, image name)}``."""
    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap is None or snap == _INVALID_HANDLE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    table = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return table


def _created_of(handle):
    """Creation time (FILETIME ticks) of an open process handle, or None."""
    times = [wintypes.FILETIME() for _ in range(4)]
    if not _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        logger.warning("GetProcessTimes failed (error %s)", ctypes.get_last_error())
        return None
    return _ft(times[0])


def _probe(pid):
    """``(creation time, still running)`` for a PID, or None if it cannot be opened.

    Running is read from the process object, not the table, because a process
    that has exited but whose handle someone still holds stays listed.
    """
    handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        if err != _ERROR_INVALID_PARAMETER:
            logger.warning("OpenProcess(%s) failed (error %s)", pid, err)
        return None
    try:
        return _created_of(handle), _k32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
    finally:
        _k32.CloseHandle(handle)


def _taskkill(pid):
    """End a process and its tree.  Output is captured and no window is shown."""
    try:
        done = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("taskkill for PID %s could not run", pid)
        return
    if done.returncode:  # 128 = already gone, the usual harmless case
        logger.info("taskkill PID %s returned %s: %s", pid, done.returncode,
                    done.stderr.decode(errors="replace").strip())


# ------------------------------------------------------------------ known set

class _Known:
    """One entry of the known set: a process identified by PID and creation time."""

    __slots__ = ("pid", "created", "gone", "image")

    def __init__(self, pid, created, gone, image):
        self.pid, self.created, self.gone, self.image = pid, created, gone, image

    def copy(self):
        return _Known(self.pid, self.created, self.gone, self.image)


def _same_running(entry, state):
    """Is the probed process the entry's own and still running?"""
    return (state is not None and state[1]
            and (entry.created is None or state[0] == entry.created))


def _discover(known, table, probe, now):
    """Grow ``known`` (a list of ``_Known`` copies) from one process table.

    An entry no longer running gets ``gone = now`` once.  A process whose parent
    PID matches an entry joins when its creation time lies in the entry's
    window [created, gone] (open-ended while the entry is alive); dead entries
    stay, so orphans of an exited parent are still found.  Repeats until stable
    so a grandchild in the same table is found in the same pass.
    """
    cache = {}

    def look(pid):
        if pid not in cache:
            cache[pid] = probe(pid)
        return cache[pid]

    for entry in known:
        if entry.gone is None:
            if not _same_running(entry, look(entry.pid)):
                entry.gone = now
            elif entry.pid in table:
                entry.image = table[entry.pid][1]
    grew = True
    while grew:
        grew = False
        by_pid = {}
        for entry in known:
            by_pid.setdefault(entry.pid, []).append(entry)
        for pid, (ppid, name) in table.items():
            same_pid = by_pid.get(pid, ())
            if pid == ppid or any(k.gone is None for k in same_pid):
                continue
            for parent in by_pid.get(ppid, ()):
                state = look(pid)
                if state is None:
                    break
                created, running = state
                if any(k.created == created for k in same_pid):
                    break
                if created is not None:
                    if parent.created is not None and created < parent.created:
                        continue
                    if parent.gone is not None and created > parent.gone:
                        continue
                known.append(_Known(pid, created, None if running else now, name))
                grew = True
                break


# --------------------------------------------------------------------- scope

_tls = threading.local()


class PointScope:
    """The processes one scan point starts; see the module docstring.

    Use as ``with PointScope(stop_requested) as scope:`` on the point's thread.
    ``kill`` may be called from any thread, before, during or after the block.
    """

    def __init__(self, stop_requested=lambda: False):
        self._lock = threading.RLock()
        self._stop_requested = stop_requested
        self._roots = []          # Popen objects launched on the owner thread
        self._known = []          # _Known entries, guarded by _lock
        self._launched = 0
        self._watcher = None
        self._stop_watch = threading.Event()
        self._killed_done = threading.Event()
        self._survivors = []
        self.killed = False
        self.refused = False
        self.interrupted = False

    # -- context manager (owner thread)
    def __enter__(self):
        if getattr(_tls, "scope", None) is not None:
            raise RuntimeError("a PointScope is already active on this thread")
        _tls.scope = self
        return self

    def __exit__(self, *exc):
        _tls.scope = None
        self._stop_watch.set()
        watcher = self._watcher
        if watcher is not None:
            watcher.join(2.0)
        return False

    # -- the Popen hook
    def _launch(self, original, popen, args, kwargs):
        with self._lock:
            if self.killed or (self._launched == 0 and self._stop_requested()):
                self.refused = True
                raise PointLaunchRefused("launch refused: the scan was stopped")
            original(popen, *args, **kwargs)
            self._launched += 1
            self._record(popen, args, kwargs)

    def _record(self, popen, args, kwargs):
        cmd = args[0] if args else kwargs.get("args", "")
        first = cmd if isinstance(cmd, (str, os.PathLike)) else (cmd[0] if cmd else "")
        created = None
        try:
            created = _created_of(int(popen._handle))
        except Exception:  # an exotic Popen without a handle; the rescans go by PID
            logger.exception("could not read the creation time of PID %s", popen.pid)
        self._roots.append(popen)
        self._known.append(_Known(popen.pid, created, None, os.path.basename(str(first)) or "?"))
        if self._watcher is None:
            self._watcher = threading.Thread(target=self._watch, name="point-watcher", daemon=True)
            self._watcher.start()

    # -- tracking
    def _watch(self):
        # shortcut: an intermediate that starts a child and exits within one
        # interval is not seen; upgrade to a Windows Job Object if the live
        # check or a user ever shows a survivor of that kind.
        while not self._stop_watch.wait(TRACK_INTERVAL_S):
            try:
                self._rescan()
            except Exception:
                logger.exception("point-process watcher scan failed")

    def _rescan(self):
        """Read the table outside the lock, merge into the known set, return live entries."""
        with self._lock:
            snapshot = [e.copy() for e in self._known]
        if not snapshot:
            return []
        try:
            table = _read_table()
        except OSError:
            logger.exception("process table unreadable; scanning by PID only")
            table = {}
        _discover(snapshot, table, _probe, _filetime_now())
        with self._lock:
            index = {(e.pid, e.created): e for e in self._known}
            for fresh in snapshot:
                mine = index.get((fresh.pid, fresh.created))
                if mine is None:
                    self._known.append(fresh)
                    continue
                if mine.gone is None:
                    mine.gone = fresh.gone
                mine.image = fresh.image
        return [e for e in snapshot if e.gone is None]

    def known(self):
        """Copies of the known set as ``(pid, creation time, first seen gone)``."""
        with self._lock:
            return [(e.pid, e.created, e.gone) for e in self._known]

    # -- kill
    def kill(self, log):
        """End every live process of the point; return at once, report to ``log``."""
        with self._lock:
            if self.killed:
                return
            self.killed = True
            self.interrupted = any(p.poll() is None for p in self._roots)
            self._stop_watch.set()
            recorded = bool(self._known)
            if recorded:
                threading.Thread(target=self._kill_main, args=(log,),
                                 name="point-kill", daemon=True).start()
        if not recorded:
            self._say(log, "Force stop: no process was recorded for this point.")
            self._killed_done.set()

    def _kill_main(self, log):
        deadline = time.monotonic() + KILL_WAIT_S
        sent = {}
        live = []
        try:
            while True:
                live = self._rescan()
                if not live or time.monotonic() >= deadline:
                    break
                for entry in live:
                    key = (entry.pid, entry.created)
                    if key not in sent and entry.pid != os.getpid():
                        sent[key] = entry
                        _taskkill(entry.pid)
                time.sleep(KILL_POLL_S)
            survivors = [Survivor(e.pid, e.image) for e in live]
            left = {(e.pid, e.created) for e in live}
            ended = [e for key, e in sent.items() if key not in left]
            with self._lock:
                self._survivors = survivors
            if survivors:
                names = ", ".join(f"{s.image} (PID {s.pid})" for s in survivors)
                msg = (f"Force stop: could not end {names}; end "
                       f"{'it' if len(survivors) == 1 else 'them'} by hand in Task Manager.")
            elif ended:
                msg = "Force stop: ended " + ", ".join(f"{e.image} (PID {e.pid})" for e in ended) + "."
            else:
                msg = "Force stop: no recorded process was still running."
            self._say(log, msg)
        except Exception:
            logger.exception("force stop failed")
            with self._lock:
                self._survivors = [Survivor(e.pid, e.image) for e in live]
            self._say(log, "Force stop failed; check Task Manager for leftover McStas or mpiexec processes.")
        finally:
            self._killed_done.set()

    @staticmethod
    def _say(log, message):
        try:
            log(message)
        except Exception:
            logger.exception("the kill log callback failed")

    def wait_killed(self, timeout):
        """Block until the kill has finished or ``timeout`` passes; return the survivors.

        Survivors are ``Survivor(pid, image)`` tuples still running when the
        kill gave up; empty if the kill has not finished or was never made.
        """
        if self.killed:
            self._killed_done.wait(timeout)
        with self._lock:
            return list(self._survivors)


# ------------------------------------------------------------------- install

_install_lock = threading.Lock()


def install():
    """Wrap ``subprocess.Popen.__init__`` once; later calls do nothing."""
    with _install_lock:
        current = subprocess.Popen.__init__
        if getattr(current, "_tavi_point_hook", False):
            return

        @functools.wraps(current)  # keeps the conftest guard's _tavi_no_window mark
        def hooked(self, *args, **kwargs):
            scope = getattr(_tls, "scope", None)
            if scope is None:
                return current(self, *args, **kwargs)
            return scope._launch(current, self, args, kwargs)

        hooked._tavi_point_hook = True
        subprocess.Popen.__init__ = hooked
