"""A one-transfer recorder must retain errors even when TAVI catches them."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import zipfile

import pytest

from tools.support.tavi_record import Recorder, supervise


def test_frozen_internal_instrument_state_is_captured(tmp_path):
    recorder = Recorder(tmp_path, tmp_path / "report")
    scope = {}
    exec(compile("def run_simulation(launch_state):\n    return None\n",
                 str(tmp_path / "TAVI_PySide6.py"), "exec"), scope)
    launch = {"vals": {"omega": 0}, "scan_config": SimpleNamespace(mis_omega=7.5, mis_chi=-2)}
    recorder.install()
    try:
        scope["run_simulation"](launch)
    finally:
        recorder.restore()
        recorder.stream.close()
    events = [json.loads(line) for line in (tmp_path / "report/events.jsonl").read_text(encoding="utf-8").splitlines()]
    event = next(e for e in events if e["kind"] == "call")
    assert event["fields"]["launch_state"]["scan_config"] == {"mis_omega": 7.5, "mis_chi": -2}
    assert launch["scan_config"].mis_omega == 7.5


def test_worker_caught_exception_and_exact_subprocess_output(tmp_path):
    recorder = Recorder(tmp_path, tmp_path / "report")
    scope = {}
    exec(compile("def worker():\n    try:\n        open('certainly-missing-tavi-file')\n"
                 "    except FileNotFoundError:\n        pass\n",
                 str(tmp_path / "TAVI_PySide6.py"), "exec"), scope)
    recorder.install()
    try:
        worker = threading.Thread(target=scope["worker"])
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive()
        result = subprocess.run([sys.executable, "-c", "print('raw compiler detail');raise SystemExit(7)"],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 7
    finally:
        recorder.restore()
        recorder.stream.close()
    events = [json.loads(line) for line in (tmp_path / "report/events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["kind"] == "caught_exception" and "certainly-missing-tavi-file" in e["traceback"] for e in events)
    assert any(e["kind"] == "command_result" and e["returncode"] == 7
               and e["stdout"] == "raw compiler detail\n" for e in events)


def test_checked_command_failure_keeps_output(tmp_path):
    recorder = Recorder(tmp_path, tmp_path / "report")
    try:
        recorder.run([sys.executable, "-c", "print('compiler missing header');raise SystemExit(3)"],
                     capture_output=True, text=True, check=True, timeout=10)
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 3
    else:
        raise AssertionError("recorder swallowed the process failure")
    finally:
        recorder.stream.close()
    events = (tmp_path / "report/events.jsonl").read_text(encoding="utf-8")
    assert "compiler missing header" in events
    assert "command_exception" in events


def test_import_failure_still_returns_archive_from_spaced_path(tmp_path):
    root = tmp_path / "TAVI installed"
    root.mkdir()
    with (root / "TAVI_PySide6.py").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("raise RuntimeError('deliberate startup failure')\n")
    output = tmp_path / "USB support reports"
    assert supervise(root, output) == 0
    archives = list(output.glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        assert b"deliberate startup failure" in archive.read("console.txt")
        assert b"caught_exception" in archive.read("events.jsonl")
        assert b"Process result: 1" in archive.read("SUMMARY.txt")


@pytest.mark.parametrize("program, expected", [
    ("import os; os._exit(23)\n", b"Process result: 23"),
    ("import time; time.sleep(20)\n", b"TimeoutExpired"),
])
def test_abrupt_exit_and_deadline_still_package(tmp_path, monkeypatch, program, expected):
    with (tmp_path / "TAVI_PySide6.py").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(program)
    monkeypatch.setenv("TAVI_RECORD_TIMEOUT_SECONDS", "1")
    output = tmp_path / "reports"
    assert supervise(tmp_path, output) == 0
    with zipfile.ZipFile(next(output.glob("*.zip"))) as archive:
        assert expected in archive.read("SUMMARY.txt")
        assert "events.jsonl" in archive.namelist()
