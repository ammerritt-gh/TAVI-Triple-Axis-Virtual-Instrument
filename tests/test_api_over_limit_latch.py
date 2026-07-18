"""Regression: an over-limit scan must be rejected on the cheap point count
BEFORE the per-point feasibility expansion runs.

Background (observed live 2026-07-08): a 594-point scan (max_points=200) sent to
POST /scan or POST /validate latched the server -- every subsequent API call
failed until process restart. Root cause: ``_submit_scan_on_gui`` /
``_validate_scan_on_gui`` ran ``validate_scan_launch_state`` (which deep-copies
the scan config and runs the angle solver once per point) on the single GUI
thread BEFORE the max_points budget check. For a scan far over the limit that
per-point expansion monopolized the GUI event loop, so every other bridged API
call timed out with 503 gui_busy; retries piled more expansions on the queue and
the wedge never cleared.

These tests drive the REAL ``TaviApiBackend`` validation bodies through a
synchronous stand-in bridge (the production bridge marshals onto the GUI thread;
here we run the call inline) and a stub controller whose
``validate_scan_launch_state`` counts how often the expensive expansion ran. The
regression guard is ``expansion_calls == 0`` for an over-limit request: if the
ordering is reverted the expansion runs and these fail.

Importing ``TAVI_PySide6`` needs PySide6 + mcstasscript, so the module skips when
either is unavailable (same guard as ``test_parameters_persistence.py``).
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as controller_module
from tavi.scan_jobs import JobRegistry, JobState, ScanJob, BudgetLimits

ApiError = controller_module.ApiError
TaviApiBackend = controller_module.TaviApiBackend

_CMD1 = "H 0 5.93 0.01"  # grammar-valid; it is the point COUNT that is over limit


class _SyncBridge:
    """Stand-in for ApiBridge: run the marshalled call inline (no GUI thread)."""

    def call_on_gui(self, fn, timeout=5.0):
        return fn()


class _StubController:
    """Minimal controller exposing only what the validation bodies call.

    ``validate_scan_launch_state`` is the expensive per-point expansion in
    production; here it just records that it ran (and how many point-solves it
    would have performed) so the tests can assert it is skipped for an over-limit
    scan.
    """

    def __init__(self, npoints, max_points=200):
        self._npoints = npoints
        self._job_registry = JobRegistry()
        self._budget_limits = BudgetLimits(max_points=max_points)
        self._journal = SimpleNamespace(record=lambda *a, **k: None)
        self.runtime_tracker = SimpleNamespace(
            estimate_scan_seconds=lambda *a, **k: {
                "estimated_seconds": 1.0, "confidence": "low", "samples": 0}
        )
        self.descriptor = SimpleNamespace(id="puma")
        self.instrument = object()
        self.expansion_calls = 0        # times the per-point expansion ran
        self.feasibility_solves = 0     # per-point solves it performed
        self.messages = []

    # -- GUI-independent launch-state builder (the seam the bodies use) --
    def build_api_launch_state(self, patch):
        vals = {"scan_command1": _CMD1, "scan_command2": "",
                "number_neutrons": 1e5}
        vals.update(patch or {})
        return {
            "vals": vals,
            "scan_config": object(),
            "relative_mode_1": False, "relative_mode_2": False,
        }

    def _validate_scan_commands_text(self, c1, c2):
        return ""  # grammar OK

    def _count_scan_points(self, c1, c2):
        return self._npoints  # cheap, mirrors production

    # -- the expensive expansion the fix must skip when over limit -------
    def validate_scan_launch_state(self, launch_state):
        self.expansion_calls += 1
        self.feasibility_solves += self._npoints
        return {
            "requested_points": self._npoints,
            "feasible_points": self._npoints,
            "partial": False,
            "planned_feasible_mask": [True] * self._npoints,
            "feasible_segments": [
                {"start_index": 0, "end_index": self._npoints - 1}],
            "point_manifest": [],
            "per_command": [],
            "infeasible": [],
        }

    def print_to_message_center(self, msg):
        self.messages.append(msg)

    # -- enqueue (success path only) -------------------------------------
    def submit_scan_job(self, launch_state, source):
        job = ScanJob(job_id="j-0001", source=source, launch_state=launch_state)
        job.progress_total = self._npoints
        self._job_registry.add(job)
        return job


def _backend(npoints, max_points=200):
    ctrl = _StubController(npoints, max_points=max_points)
    return TaviApiBackend(ctrl, _SyncBridge()), ctrl


# --------------------------------------------------------------------------
# Over-limit: clean rejection WITHOUT the per-point expansion
# --------------------------------------------------------------------------

def test_over_limit_validate_rejects_without_expansion():
    backend, ctrl = _backend(594)
    result = backend.submit_validate({})

    assert result["would_queue"] is False
    assert any("limit_exceeded" in b for b in result["blockers"])
    assert any("594" in b and "200" in b for b in result["blockers"])
    # The latch fix: the expensive per-point expansion never ran.
    assert ctrl.expansion_calls == 0
    assert ctrl.feasibility_solves == 0
    # Response is still well-shaped.
    assert result["requested_points"] == 594
    assert result["cost"]["requested_points"] == 594


def test_over_limit_submit_rejects_without_expansion_or_enqueue():
    backend, ctrl = _backend(594)
    with pytest.raises(ApiError) as excinfo:
        backend.submit_scan({})

    err = excinfo.value
    assert err.status == 429
    assert err.code == "limit_exceeded"
    assert "594" in err.message and "200" in err.message
    assert ctrl.expansion_calls == 0
    assert ctrl.feasibility_solves == 0
    # Nothing was queued.
    assert list(ctrl._job_registry.all_jobs()) == []


# --------------------------------------------------------------------------
# No latch: the very next request on the SAME backend behaves normally
# --------------------------------------------------------------------------

def test_normal_request_after_over_limit_still_works():
    # An over-limit submission first (the trigger that used to latch).
    over_backend, _ = _backend(594)
    with pytest.raises(ApiError):
        over_backend.submit_scan({})

    # A within-limit validate then submit must both succeed normally.
    backend, ctrl = _backend(150)

    validation = backend.submit_validate({})
    assert validation["would_queue"] is True
    assert validation["blockers"] == []
    assert ctrl.expansion_calls == 1  # within-limit scan DOES expand

    payload = backend.submit_scan({})
    assert payload["job_id"] == "j-0001"
    assert payload["state"] == "queued"
    assert ctrl.expansion_calls == 2  # submit expands too


# --------------------------------------------------------------------------
# Boundary: exactly at the limit still expands and queues (not over)
# --------------------------------------------------------------------------

def test_at_limit_boundary_is_allowed():
    backend, ctrl = _backend(200)  # == max_points, not over
    validation = backend.submit_validate({})
    assert validation["would_queue"] is True
    assert ctrl.expansion_calls == 1


class _ExplodingInstrument:
    """Reproduce the isolated angle-solver exception seen at 4.657 meV."""

    def check_point_feasibility(self, scan_config, scan_mode, point, vals):
        if abs(float(point[3]) - 4.657) < 1e-9:
            raise OSError(22, "Invalid argument")
        return True, None


class _ManifestController:
    _SCAN_VARIABLE_TO_INDEX = {"deltaE": 3}
    instrument = _ExplodingInstrument()

    def _determine_scan_mode(self, cmd1, cmd2):
        return "rlu"

    def _build_scan_point_template(self, scan_mode, vals):
        return [2.0, 0.0, 0.0, 0.0]

    def normalize_scan_variable(self, variable):
        return variable

    def print_to_message_center(self, message):
        raise AssertionError("manifest expansion unexpectedly failed: %s" % message)


def test_isolated_4657_solver_error_is_masked_not_scan_fatal():
    launch_state = {
        "vals": {
            "scan_command1": "deltaE 4.557 4.757 0.1",
            "scan_command2": "",
        },
        "scan_config": object(),
        "relative_mode_1": False,
        "relative_mode_2": False,
    }

    result = controller_module.TAVIController.validate_scan_launch_state(
        _ManifestController(), launch_state)

    assert result["requested_points"] == 3
    assert result["feasible_points"] == 2
    assert result["partial"] is True
    assert result["planned_feasible_mask"] == [True, False, True]
    assert result["infeasible"] == [{
        "index": 1,
        "values": {"deltaE": pytest.approx(4.657)},
        "kind": "geometry_solver_error",
        "reason": "angle solve error: [Errno 22] Invalid argument",
    }]
