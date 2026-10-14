"""The crash log catches what would otherwise vanish: uncaught errors on the
GUI thread, in worker threads and inside Qt paint handlers, plus the header
naming the platform, without growing past its limit. Offscreen Qt, no McStas."""
import faulthandler
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from tavi import crash_log  # noqa: E402

_APP = QApplication.instance() or QApplication([sys.argv[0]])


@pytest.fixture
def log(tmp_path, monkeypatch):
    """Install into a temp file; pytest's own faulthandler and hooks are put back."""
    seen, enabled = [], []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: seen.append(exc[0]))
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_type))
    monkeypatch.setattr(faulthandler, "enable", lambda *a, **k: enabled.append(a[0]))
    monkeypatch.setattr(crash_log, "_stream", None)
    path = crash_log.install(tmp_path / "tavi-crash.log")
    yield path, seen, enabled
    crash_log._stream.close()


def test_header_names_platform_and_versions(log):
    path, _, _ = log
    text = path.read_text(encoding="utf-8")
    assert "TAVI started" in text
    assert "platform:" in text and "PySide6:" in text and "XDG_SESSION_TYPE=" in text


@pytest.mark.parametrize("platform, on", [("linux", True), ("darwin", True), ("win32", False)])
def test_faulthandler_writes_to_the_log_except_on_windows(tmp_path, monkeypatch, platform, on):
    enabled = []
    monkeypatch.setattr(faulthandler, "enable", lambda *a, **k: enabled.append(a[0]))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(crash_log, "_stream", None)
    monkeypatch.setattr(crash_log.sys, "platform", platform)
    crash_log.install(tmp_path / "tavi-crash.log")
    try:
        assert enabled == ([crash_log._stream] if on else [])
    finally:
        crash_log._stream.close()


def test_uncaught_error_is_logged_and_passed_on(log):
    path, seen, _ = log
    try:
        raise RuntimeError("main thread boom")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert seen == [RuntimeError]
    assert "RuntimeError: main thread boom" in path.read_text(encoding="utf-8")


def test_worker_thread_error_is_logged_and_passed_on(log):
    path, seen, _ = log

    def fail():
        raise ValueError("worker boom")

    worker = threading.Thread(target=fail, name="scan-worker")
    worker.start()
    worker.join()
    text = path.read_text(encoding="utf-8")
    assert seen == [ValueError]
    assert "Uncaught exception in thread scan-worker" in text
    assert "ValueError: worker boom" in text


def test_error_in_qt_paint_handler_is_logged(log):
    path, seen, _ = log

    class Broken(QWidget):
        def paintEvent(self, event):
            raise ZeroDivisionError("paint boom")

    # Inside an event loop, as in the app: a direct grab() would re-raise instead.
    widget = Broken()
    widget.resize(20, 20)
    loop = QEventLoop()
    QTimer.singleShot(0, widget.grab)
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    assert seen == [ZeroDivisionError]
    text = path.read_text(encoding="utf-8")
    assert "ZeroDivisionError" in text and "paint boom" in text


def test_a_session_stops_writing_at_the_limit(log, monkeypatch):
    path, _, _ = log
    monkeypatch.setattr(crash_log, "MAX_BYTES", 2_000)
    for _ in range(100):
        crash_log.record("Uncaught exception", "x" * 100)
    text = path.read_text(encoding="utf-8")
    assert len(text) < 2_000 + 200
    assert text.count("Log limit reached") == 1
