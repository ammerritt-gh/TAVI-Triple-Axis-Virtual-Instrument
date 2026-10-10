"""The point maximum over the API: POST /validate and POST /scan refuse a scan over it.

The refusal comes from the plan (instruments/rules.py), before any expansion or
closed-form budget count is materialised, so a 1e8-point request never builds its
array. force and allow_partial do not clear it.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as cm  # noqa: E402
from instruments import rules  # noqa: E402
from test_api_partial_collimation import issues_for  # noqa: E402
from test_slit_scans import _SyncBridge, in8  # noqa: E402,F401  (the IN8 controller fixture)

MESSAGE = "This scan has {:,} points; the maximum is 100,000."


def _no_run(*_args):
    raise AssertionError("a scan over the maximum was expanded")


@pytest.mark.parametrize("cmd1, cmd2, box, count", [
    ("A3 0 100 0.000001", "", 1, 100_000_001),
    ("A3 0 100000 1", "", 1, 100_001),
    ("", "A3 0 100 0.000001", 2, 100_000_001),
    ("A3 0 1000 1", "A4 0 1000 1", None, 1_002_001),       # each 1001 alone, the pair over it
])
def test_a_scan_over_the_maximum_is_refused_whatever_the_flags(in8, monkeypatch, cmd1, cmd2, box, count):
    monkeypatch.setattr(rules, "parse_scan_steps", _no_run)
    text = MESSAGE.format(count)
    if box is not None:
        text = f"Command {box}: {text}"
    params = {"scan_command1": cmd1, "scan_command2": cmd2}
    backend = cm.TaviApiBackend(in8, _SyncBridge())

    result = backend.submit_validate({"parameters": params, "force": True, "allow_partial": True})
    assert result["would_queue"] is False
    assert f"scan_validation: {text}" in result["blockers"], result["blockers"]
    with pytest.raises(cm.ApiError) as refused:
        backend.submit_scan({"parameters": params, "force": True, "allow_partial": True})
    assert (refused.value.status, refused.value.code) == (400, "scan_validation")
    assert str(refused.value.message) == text


def test_the_budget_count_of_a_huge_scan_is_closed_form(in8, monkeypatch):
    """/validate counts the budget on every request: the count is closed form, no 1e8-point array."""
    monkeypatch.setattr(cm, "parse_scan_steps", _no_run, raising=False)
    started = time.perf_counter()
    assert in8._count_scan_points("A3 0 100 0.000001", "") == 100_000_001
    assert time.perf_counter() - started < 1.0


def test_a_scan_at_the_maximum_clears_the_gate(in8):
    """100,000 points is the largest the gate admits. Its per-point feasibility is not run
    here: that expands every point on the GUI thread."""
    hard, _soft = issues_for(in8, "A3 0 99999 1")
    assert hard == []


def test_a_step_too_small_for_its_range_is_a_400_not_a_500(in8):
    """A3 0 1 1e-309 overflows the step count: /validate and /scan refuse it by name."""
    params = {"scan_command1": "A3 0 1 1e-309"}
    backend = cm.TaviApiBackend(in8, _SyncBridge())
    message = "Step (1e-309) is too small for the range 0 to 1."

    result = backend.submit_validate({"parameters": params})
    assert result["would_queue"] is False
    assert f"scan_validation: Command 1: {message}" in result["blockers"], result["blockers"]
    with pytest.raises(cm.ApiError) as refused:
        backend.submit_scan({"parameters": params})
    assert (refused.value.status, refused.value.code) == (400, "scan_validation")
