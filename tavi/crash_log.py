"""A crash log that survives a hard crash.

``install()`` appends to ``output/tavi-crash.log``: a header per launch
(platform, library versions, display session), every thread's Python stack
on a native crash (``faulthandler``), and uncaught Python errors from any
thread, including the ones PySide6 reports from paint and mouse handlers.
Qt-free; ``main()`` adds Qt's version, display plugin and Qt's own warnings
through ``record()`` once a QApplication exists.
"""
import datetime
import faulthandler
import os
import platform
import sys
import threading
import traceback
from importlib import metadata
from pathlib import Path

from tavi.local_state import REPO_ROOT

LOG_PATH = REPO_ROOT / "output" / "tavi-crash.log"
MAX_BYTES = 1_000_000

_stream = None


def _version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def environment():
    """One block naming what a crash depends on: OS, versions, display session."""
    env = {name: os.environ.get(name, "")
           for name in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY",
                        "DISPLAY", "QT_QPA_PLATFORM", "QT_SCALE_FACTOR")}
    return "\n".join([
        f"platform: {platform.platform()}",
        f"python: {sys.version.split()[0]}  PySide6: {_version('PySide6')}  "
        f"matplotlib: {_version('matplotlib')}  numpy: {_version('numpy')}",
        "session: " + "  ".join(f"{name}={value or '-'}" for name, value in env.items()),
    ])


def record(title, text=""):
    """Append one timestamped entry; a no-op until ``install()`` has run."""
    if _stream is None:
        return
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    body = text.rstrip("\n") + "\n" if text else ""
    try:
        _stream.write(f"[{stamp}] {title}\n{body}")
        _stream.flush()
    except (OSError, ValueError) as exc:
        print(f"TAVI crash log: could not write: {exc}", file=sys.stderr)


def install(path=LOG_PATH):
    """Open the log, enable faulthandler on it and hook uncaught exceptions."""
    global _stream
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > MAX_BYTES:
        os.replace(path, path.with_name(path.name + ".1"))
    # Kept open for the whole process: faulthandler writes to its descriptor.
    _stream = open(path, "a", encoding="utf-8", newline="\n")
    faulthandler.enable(_stream, all_threads=True)

    previous_hook = sys.excepthook

    def excepthook(exc_type, exc, tb):
        record("Uncaught exception",
               "".join(traceback.format_exception(exc_type, exc, tb)))
        previous_hook(exc_type, exc, tb)

    previous_thread_hook = threading.excepthook

    def thread_excepthook(args):
        if args.exc_type is not SystemExit:
            name = args.thread.name if args.thread is not None else "unknown"
            record(f"Uncaught exception in thread {name}",
                   "".join(traceback.format_exception(
                       args.exc_type, args.exc_value, args.exc_traceback)))
        previous_thread_hook(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    record("TAVI started", environment())
    return path
