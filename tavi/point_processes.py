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

Every entry of the known set holds an open process handle from the moment it is
recorded or discovered.  While a handle is open Windows cannot reuse its PID, so
the handle is the identity: liveness and the exit time are read from it, and a
process is ended with ``TerminateProcess`` on it.  No taskkill, no bare PID.  A
process joins the known set when its parent PID matches an entry and its
creation time lies between that entry's creation time and exit time (open-ended
while the entry runs); the window keeps an unrelated child out.

``PointScope.kill(log)`` ends every live process of the known set and returns at
once; a daemon thread does the work and reports through ``log``.  It rescans the
table every ``KILL_POLL_S`` until nothing is left or ``KILL_WAIT_S`` has passed,
and never calls anything that can block.  ``wait_killed(timeout)`` returns the
processes still running if the kill outlasts the wait.

``release()`` closes the handles.  The controller calls it only after it has
unpublished the scope as the active one, so no kill can reach a released scope:
after ``wait_killed`` when the point was killed, otherwise once the point
completed; ``__del__`` calls it as a fallback.  A kill still running keeps its
handles open and closes them when it ends.

Lock discipline (the controller's order is ``_stop_lock``, then this scope's
lock, then a ``job.lock``): the scope lock is held around check-then-launch-then-
record, ``kill``'s flag updates, and every update or read of the known set.  Those
handle queries are non-blocking.  The lock is never held across a process-table
read, a sleep or a join.

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

Survivor = namedtuple("Survivor", "pid image")


class PointLaunchRefused(OSError):
    """A launch inside a scope was refused because a stop or kill came first."""


# ---------------------------------------------------------------- Win32 layer

_TH32CS_SNAPPROCESS = 0x2
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_PROCESS_RIGHTS = _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE
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
_k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_k32.TerminateProcess.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.GetSystemTimeAsFileTime.argtypes = [ctypes.POINTER(wintypes.FILETIME)]
_k32.GetSystemTimeAsFileTime.restype = None
_k32.GetCurrentProcess.argtypes = []
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_k32.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                 ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                 wintypes.BOOL, wintypes.DWORD]
_k32.DuplicateHandle.restype = wintypes.BOOL
_DUPLICATE_SAME_ACCESS = 0x2


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


def _times(handle):
    """``(creation, exit)`` of a process handle in FILETIME ticks (exit is 0 while it runs), or None."""
    ft = [wintypes.FILETIME() for _ in range(4)]
    if not _k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in ft)):
        logger.warning("GetProcessTimes failed (error %s)", ctypes.get_last_error())
        return None
    return _ft(ft[0]), _ft(ft[1])


class _Proc:
    """An open handle on one process.  While it is open, Windows cannot reuse the PID."""

    __slots__ = ("pid", "handle", "created")

    def __init__(self, pid, handle, created):
        self.pid, self.handle, self.created = pid, handle, created

    def running(self):
        return _k32.WaitForSingleObject(self.handle, 0) == _WAIT_TIMEOUT

    def exit_time(self):
        """None while the process runs; else its real exit time (FILETIME ticks)."""
        if self.running():
            return None
        times = _times(self.handle)
        if times is None or not times[1]:
            logger.warning("exit time of PID %s is unreadable; using the scan time", self.pid)
            return _filetime_now()
        return times[1]

    def terminate(self):
        """``TerminateProcess`` on this handle; True once the process is ended."""
        if _k32.TerminateProcess(self.handle, 1):
            return True
        err = ctypes.get_last_error()
        if not self.running():
            return True  # it exited on its own in the meantime
        logger.warning("TerminateProcess failed for PID %s (error %s)", self.pid, err)
        return False

    def close(self):
        _k32.CloseHandle(self.handle)


def _open_proc(pid, warned=None):
    """Open a process with the rights the guard needs; None (logged) if it cannot be opened.

    ``warned`` (a set) logs each PID's failure once, so a rescan every second does not
    repeat it for the length of a point.
    """
    handle = _k32.OpenProcess(_PROCESS_RIGHTS, False, pid)
    if not handle:
        err = ctypes.get_last_error()
        if err != _ERROR_INVALID_PARAMETER and (warned is None or pid not in warned):  # 87: no such PID
            logger.warning("OpenProcess(%s) failed (error %s)", pid, err)
            if warned is not None:
                warned.add(pid)
        return None
    times = _times(handle)
    return _Proc(pid, handle, times[0] if times else None)


def _dup_popen_handle(popen):
    """A handle of our own duplicated from Popen's, when OpenProcess was refused; None (logged)."""
    source = getattr(popen, "_handle", None)
    if source is None:
        return None
    me = _k32.GetCurrentProcess()
    dup = wintypes.HANDLE()
    if not _k32.DuplicateHandle(me, int(source), me, ctypes.byref(dup), 0, False,
                                _DUPLICATE_SAME_ACCESS):
        logger.warning("DuplicateHandle for PID %s failed (error %s)", popen.pid,
                       ctypes.get_last_error())
        return None
    times = _times(dup)
    return _Proc(popen.pid, dup.value, times[0] if times else None)


# ------------------------------------------------------------------ known set

class _Known:
    """One entry of the known set.  ``proc`` is its held handle; None only if it could not be opened."""

    __slots__ = ("pid", "created", "gone", "image", "proc")

    def __init__(self, pid, created, gone, image, proc):
        self.pid, self.created, self.gone, self.image, self.proc = pid, created, gone, image, proc


def _discover(known, table, open_proc, taken=None):
    """Grow ``known`` (a list of ``_Known``) from one process table.

    A running entry whose process has exited gets ``gone``, its real exit time,
    once.  A process whose parent PID matches an entry joins when its creation
    time lies in the entry's window [created, gone] (open-ended while the entry
    runs), holding the handle ``open_proc`` gave it; a handle not adopted is
    closed.  Dead entries stay, so orphans of an exited parent are still found.
    Repeats until stable so a grandchild in the same table is found in the same pass.
    ``taken`` is when the table was read: a handle to a process created later
    belongs to a PID reused after the read, so it is never adopted.
    """
    opened = {}  # candidate PID -> its open _Proc; None once adopted or not openable

    def candidate(pid):
        if pid not in opened:
            opened[pid] = open_proc(pid)
        return opened[pid]

    try:
        for entry in known:
            if entry.gone is None and entry.proc is not None:
                exited = entry.proc.exit_time()
                if exited is not None:
                    entry.gone = exited
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
                    if parent.created is None:
                        continue  # no lower bound: its window cannot tell a reused PID apart
                    proc = candidate(pid)
                    if proc is None:
                        break
                    if any(k.created == proc.created for k in same_pid):
                        break
                    if proc.created is None:
                        logger.warning("PID %s has no creation time; not collected", pid)
                        continue
                    if proc.created < parent.created:
                        continue
                    if parent.gone is not None and proc.created > parent.gone:
                        continue
                    if taken is not None and proc.created > taken:
                        continue
                    known.append(_Known(pid, proc.created, proc.exit_time(), name, proc))
                    opened[pid] = None  # the entry owns the handle now
                    grew = True
                    break
    finally:
        for proc in opened.values():
            if proc is not None:
                proc.close()


# --------------------------------------------------------------------- scope

_tls = threading.local()


class PointScope:
    """The processes one scan point starts; see the module docstring.

    Use as ``with PointScope(stop_requested) as scope:`` on the point's thread.
    ``kill`` may be called from any thread, before, during or after the block.
    The controller calls ``release()`` only once no kill can reach the scope any
    more: after it has unpublished the scope as the active one, and, when the point
    was killed, after ``wait_killed``.  A kill after ``release()`` ends nothing.
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
        self._killing = False     # a kill thread is running and owns closing the handles
        self._released = False
        self._closed = False      # the handles are closed; nothing more can be read
        self._warned = set()      # PIDs whose failed open was already logged
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

    def __del__(self):
        self.release()

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
        # Popen still holds its own handle, so the PID cannot have been reused yet.
        proc = _open_proc(popen.pid) or _dup_popen_handle(popen)
        if proc is None:
            logger.warning("PID %s could not be held; it cannot be ended by handle", popen.pid)
        self._roots.append(popen)
        self._known.append(_Known(popen.pid, proc.created if proc else None, None,
                                  os.path.basename(str(first)) or "?", proc))
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
        """Read the table outside the lock, grow the known set under it, return the live entries."""
        taken = _filetime_now()
        try:
            table = _read_table()
        except OSError:
            logger.exception("process table unreadable; liveness still comes from the held handles")
            table = {}
        with self._lock:
            if self._closed:
                return []
            _discover(self._known, table, lambda pid: _open_proc(pid, self._warned), taken)
            return [e for e in self._known if e.gone is None]

    def known(self):
        """Copies of the known set as ``(pid, creation time, exit time or None while running)``."""
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
            if self._closed:
                message = "Force stop: the point's processes were released before the stop, so they cannot be checked."
            elif self._known:
                self._killing = True
                threading.Thread(target=self._kill_main, args=(log,),
                                 name="point-kill", daemon=True).start()
                return
            else:
                message = "Force stop: no process was recorded for this point."
        self._say(log, message)
        self._killed_done.set()

    def _kill_main(self, log):
        deadline = time.monotonic() + KILL_WAIT_S
        live, tried, ended = [], set(), []
        try:
            while True:
                live = self._rescan()
                if not live or time.monotonic() >= deadline:
                    break
                for entry in live:
                    if entry in tried or entry.pid == os.getpid():
                        continue
                    tried.add(entry)  # one attempt each: a failure stays a survivor, not a retry loop
                    if entry.proc is not None and entry.proc.terminate():
                        ended.append(entry)
                time.sleep(KILL_POLL_S)
            ended = [e for e in ended if e not in live]
            survivors = [Survivor(e.pid, e.image) for e in live]
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
            with self._lock:
                self._killing = False
                if self._released:
                    self._close_handles()
                self._killed_done.set()

    @staticmethod
    def _say(log, message):
        try:
            log(message)
        except Exception:
            logger.exception("the kill log callback failed")

    def wait_killed(self, timeout):
        """Block until the kill has finished or ``timeout`` passes; return the survivors.

        ``Survivor(pid, image)`` tuples: the survivors the kill reported or, if it is
        still running when the wait ends, the recorded processes still running now.
        Empty if ``kill`` was never called or nothing survived.
        """
        if not self.killed:
            return []
        if self._killed_done.wait(timeout):
            with self._lock:
                return list(self._survivors)
        with self._lock:
            if self._killed_done.is_set():
                return list(self._survivors)
            return [Survivor(e.pid, e.image) for e in self._known
                    if e.gone is None and e.proc is not None and e.proc.running()]

    def release(self):
        """Close every held handle.  Idempotent; a kill still running closes them when it ends."""
        with self._lock:
            self._released = True
            if not self._killing:
                self._close_handles()

    def _close_handles(self):
        """Close the held handles.  The caller holds the lock."""
        for entry in self._known:
            if entry.proc is not None:
                entry.proc.close()
                entry.proc = None
        self._closed = True


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
