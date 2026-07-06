"""Unit tests for tavi/scan_jobs.py (job model, registry, budget math).

Pure stdlib, no Qt. Covers the remote-API job data model described in
``docs/API_SERVER_DESIGN.md`` §13 phase 5: JobState values, JobRegistry id
sequencing/ordering, JSON-safe snapshots, and BudgetLimits.check_submission.
"""
import json
import math
import threading
import time

import pytest

from tavi.scan_jobs import (
    JobState,
    JobRegistry,
    ScanJob,
    ScanResult,
    BudgetLimits,
)


# --------------------------------------------------------------------------
# JobState
# --------------------------------------------------------------------------

def test_jobstate_values_are_plain_strings():
    assert JobState.QUEUED.value == "queued"
    assert JobState.RUNNING.value == "running"
    assert JobState.DONE.value == "done"
    assert JobState.FAILED.value == "failed"
    assert JobState.CANCELLED.value == "cancelled"
    assert JobState.STOPPED.value == "stopped"
    # str subclass: compares/serializes as its plain string form.
    assert JobState.QUEUED == "queued"
    assert json.dumps(JobState.DONE) == '"done"'


def test_jobstate_is_terminal():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    for st in (JobState.QUEUED, JobState.RUNNING):
        job.state = st
        assert job.is_terminal() is False
    for st in (JobState.DONE, JobState.FAILED, JobState.CANCELLED,
               JobState.STOPPED):
        job.state = st
        assert job.is_terminal() is True


# --------------------------------------------------------------------------
# JobRegistry
# --------------------------------------------------------------------------

def _mk_job(reg):
    jid = reg.next_id()
    job = ScanJob(job_id=jid, source="api", launch_state={})
    reg.add(job)
    return job


def test_next_id_is_sequential_zero_padded():
    reg = JobRegistry()
    assert reg.next_id() == "j-0001"
    assert reg.next_id() == "j-0002"
    assert reg.next_id() == "j-0003"


def test_add_and_get():
    reg = JobRegistry()
    job = _mk_job(reg)
    assert reg.get(job.job_id) is job
    assert reg.get("j-9999") is None


def test_all_jobs_oldest_first():
    reg = JobRegistry()
    jobs = [_mk_job(reg) for _ in range(4)]
    ordered = reg.all_jobs()
    assert [j.job_id for j in ordered] == [j.job_id for j in jobs]


def test_recent_newest_first():
    reg = JobRegistry()
    jobs = [_mk_job(reg) for _ in range(5)]
    snaps = reg.recent()
    ids = [s["job_id"] for s in snaps]
    assert ids == [j.job_id for j in reversed(jobs)]


def test_recent_caps_at_n():
    reg = JobRegistry()
    for _ in range(10):
        _mk_job(reg)
    snaps = reg.recent(3)
    assert len(snaps) == 3
    # Newest three, newest first.
    assert [s["job_id"] for s in snaps] == ["j-0010", "j-0009", "j-0008"]


def test_recent_default_n_is_50():
    reg = JobRegistry()
    for _ in range(60):
        _mk_job(reg)
    assert len(reg.recent()) == 50


def test_recent_returns_snapshot_dicts_not_jobs():
    reg = JobRegistry()
    _mk_job(reg)
    snaps = reg.recent()
    assert isinstance(snaps[0], dict)
    assert snaps[0]["state"] == "queued"


# --------------------------------------------------------------------------
# ScanJob.snapshot / launch summary
# --------------------------------------------------------------------------

def _job_with_result(counts, mode="1D", include_meta=None):
    result = ScanResult(
        mode=mode,
        variable_1="A3",
        variable_2=None,
        scan_values_1=[1.0, 2.0, 3.0],
        scan_values_2=None,
        valid_mask_1=[True, True, False],
        valid_mask_2d=None,
        counts=counts,
        counts_grid=None,
        total_counts=42.0,
        max_counts=20.0,
        output_folder="/out/x",
        metadata=include_meta or {},
    )
    job = ScanJob(
        job_id="j-0001",
        source="api",
        launch_state={"vals": {
            "scan_command1": "sc A3 0 1 3",
            "scan_command2": "",
            "number_neutrons": 1e6,
            "secret_object": object(),  # must NOT leak into summary
        }},
        result=result,
    )
    return job


def test_snapshot_is_json_safe_strict():
    job = _job_with_result([1.0, 2.0, 3.0])
    snap = job.snapshot(include_data=True)
    # allow_nan=False raises on NaN/inf; must succeed.
    json.dumps(snap, allow_nan=False)


def test_snapshot_nan_inf_in_results_become_none():
    job = _job_with_result([1.0, float("nan"), float("inf")])
    snap = job.snapshot(include_data=True)
    assert snap["result"]["counts"] == [1.0, None, None]
    # And the whole thing is strict-JSON serializable.
    json.dumps(snap, allow_nan=False)


def test_snapshot_nan_in_summary_scalars_become_none():
    job = _job_with_result([1.0])
    job.result.total_counts = float("nan")
    job.result.max_counts = float("inf")
    snap = job.snapshot(include_data=False)
    assert snap["result"]["total_counts"] is None
    assert snap["result"]["max_counts"] is None


def test_skipped_points_default_empty_and_in_summary():
    # A normal job carries an empty skipped_points list in both snapshot views.
    job = _job_with_result([1.0, 2.0, 3.0])
    assert job.result.skipped_points == []
    summary = job.snapshot(include_data=False)["result"]
    assert summary["skipped_points"] == []
    data = job.snapshot(include_data=True)["result"]
    assert data["skipped_points"] == []


def test_skipped_points_serialized_in_snapshot():
    # An allow_partial job records infeasible points; they must survive the
    # JSON-safe snapshot in both summary and data views.
    skipped = [
        {"index": 2, "values": {"H": 2.01},
         "reason": "scattering triangle does not close"},
    ]
    job = _job_with_result([1.0, 2.0, None])
    job.result.skipped_points = skipped
    summary = job.snapshot(include_data=False)["result"]
    assert summary["skipped_points"] == skipped
    data = job.snapshot(include_data=True)["result"]
    assert data["skipped_points"] == skipped
    # Still strict-JSON serializable.
    json.dumps(job.snapshot(include_data=True), allow_nan=False)


def test_snapshot_include_data_toggles_arrays():
    job = _job_with_result([1.0, 2.0, 3.0], include_meta={"foo": "bar"})

    no_data = job.snapshot(include_data=False)
    assert "counts" not in no_data["result"]
    assert "scan_values_1" not in no_data["result"]
    # Summary scalars always present.
    assert no_data["result"]["mode"] == "1D"
    assert no_data["result"]["total_counts"] == 42.0

    with_data = job.snapshot(include_data=True)
    assert with_data["result"]["counts"] == [1.0, 2.0, 3.0]
    assert with_data["result"]["scan_values_1"] == [1.0, 2.0, 3.0]
    assert with_data["result"]["valid_mask_1"] == [True, True, False]
    assert with_data["result"]["metadata"] == {"foo": "bar"}


def test_snapshot_result_none_when_no_result():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    snap = job.snapshot()
    assert snap["result"] is None


def test_snapshot_launch_summary_exposes_commands_and_full_parameters():
    job = _job_with_result([1.0])
    snap = job.snapshot()
    launch = snap["launch"]
    assert launch["scan_command1"] == "sc A3 0 1 3"
    assert launch["scan_command2"] == ""
    assert launch["number_neutrons"] == 1e6
    assert launch["isolated"] is False
    # The full frozen parameter set is exposed for downstream consumers...
    assert launch["parameters"]["scan_command1"] == "sc A3 0 1 3"
    assert launch["parameters"]["number_neutrons"] == 1e6
    # ...but non-serializable objects in launch_state must not leak out.
    assert "secret_object" not in launch
    assert "secret_object" not in launch["parameters"]
    json.dumps(snap, allow_nan=False)


def test_snapshot_launch_summary_handles_missing_vals():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    snap = job.snapshot()
    assert snap["launch"] == {
        "scan_command1": "",
        "scan_command2": "",
        "number_neutrons": None,
        "isolated": False,
        "parameters": {},
        # Engine provenance defaults to mcstas for jobs with no engine set.
        "engine": "mcstas",
    }


def test_snapshot_launch_summary_reports_isolated_flag():
    job = ScanJob(job_id="j-0001", source="api",
                  launch_state={"vals": {}, "isolated": True})
    assert job.snapshot()["launch"]["isolated"] is True


def test_snapshot_launch_number_neutrons_nan_becomes_none():
    job = ScanJob(job_id="j-0001", source="api",
                  launch_state={"vals": {"number_neutrons": float("nan")}})
    snap = job.snapshot()
    assert snap["launch"]["number_neutrons"] is None


def test_snapshot_core_fields():
    job = ScanJob(job_id="j-0007", source="gui", launch_state={},
                  submitted_at=1.0, started_at=2.0, finished_at=3.0,
                  progress_done=3, progress_total=10, error="boom")
    job.state = JobState.FAILED
    snap = job.snapshot()
    assert snap["job_id"] == "j-0007"
    assert snap["source"] == "gui"
    assert snap["state"] == "failed"
    assert snap["submitted_at"] == 1.0
    assert snap["started_at"] == 2.0
    assert snap["finished_at"] == 3.0
    assert snap["progress"] == {"done": 3, "total": 10}
    assert snap["error"] == "boom"


# --------------------------------------------------------------------------
# BudgetLimits.check_submission
# --------------------------------------------------------------------------

def test_budget_passes_within_all_limits():
    limits = BudgetLimits()
    assert limits.check_submission(points=10, neutrons_per_point=1e6,
                                   pending_cost=0.0) is None


def test_budget_rejects_over_max_points():
    limits = BudgetLimits(max_points=200)
    reason = limits.check_submission(points=201, neutrons_per_point=1.0,
                                     pending_cost=0.0)
    assert reason is not None
    assert "201" in reason and "200" in reason


def test_budget_points_boundary_equal_passes():
    limits = BudgetLimits(max_points=200, queue_neutron_budget=1e30)
    assert limits.check_submission(points=200, neutrons_per_point=1.0,
                                   pending_cost=0.0) is None


def test_budget_rejects_over_max_neutrons_per_point():
    limits = BudgetLimits(max_neutrons_per_point=1e8)
    reason = limits.check_submission(points=1, neutrons_per_point=1e8 + 1,
                                     pending_cost=0.0)
    assert reason is not None
    assert "neutrons/point" in reason


def test_budget_neutrons_per_point_boundary_equal_passes():
    limits = BudgetLimits(max_neutrons_per_point=1e8,
                          queue_neutron_budget=1e30)
    assert limits.check_submission(points=1, neutrons_per_point=1e8,
                                   pending_cost=0.0) is None


def test_budget_rejects_over_queue_budget_with_pending():
    limits = BudgetLimits(max_points=1000, max_neutrons_per_point=1e12,
                          queue_neutron_budget=1e10)
    # pending 9e9 + this job (2 * 1e9 = 2e9) = 1.1e10 > 1e10 budget.
    reason = limits.check_submission(points=2, neutrons_per_point=1e9,
                                     pending_cost=9e9)
    assert reason is not None
    assert "budget" in reason


def test_budget_queue_budget_boundary_equal_passes():
    limits = BudgetLimits(max_points=1000, max_neutrons_per_point=1e12,
                          queue_neutron_budget=1e10)
    # pending 8e9 + this job (2e9) = exactly 1e10, not > budget → allowed.
    assert limits.check_submission(points=2, neutrons_per_point=1e9,
                                   pending_cost=8e9) is None


def test_budget_points_checked_before_budget():
    # Over both points and budget: points reason wins (checked first).
    limits = BudgetLimits(max_points=10, queue_neutron_budget=1.0)
    reason = limits.check_submission(points=100, neutrons_per_point=1e6,
                                     pending_cost=0.0)
    assert "points" in reason


# --------------------------------------------------------------------------
# Idempotency-Key LRU map
# --------------------------------------------------------------------------

def test_idempotent_get_put_roundtrip():
    reg = JobRegistry()
    assert reg.get_idempotent("k1") is None
    reg.put_idempotent("k1", "j-0001")
    assert reg.get_idempotent("k1") == "j-0001"


def test_idempotent_put_overwrites_same_key():
    reg = JobRegistry()
    reg.put_idempotent("k1", "j-0001")
    reg.put_idempotent("k1", "j-0002")
    assert reg.get_idempotent("k1") == "j-0002"


def test_idempotent_lru_evicts_oldest():
    reg = JobRegistry()
    cap = JobRegistry.IDEMPOTENCY_MAX
    for i in range(cap):
        reg.put_idempotent("k%d" % i, "j-%04d" % i)
    # All present.
    assert reg.get_idempotent("k0") == "j-0000"
    # get_idempotent("k0") just touched it (moved to newest), so the now-oldest
    # is "k1". Adding one more key evicts "k1", not "k0".
    reg.put_idempotent("kX", "j-9999")
    assert reg.get_idempotent("k1") is None
    assert reg.get_idempotent("k0") == "j-0000"
    assert reg.get_idempotent("kX") == "j-9999"


def test_idempotent_lru_never_exceeds_cap():
    reg = JobRegistry()
    cap = JobRegistry.IDEMPOTENCY_MAX
    for i in range(cap + 50):
        reg.put_idempotent("k%d" % i, "j-%d" % i)
    # Internal map stays bounded.
    assert len(reg._idempotency) == cap
    # The earliest 50 keys were evicted.
    assert reg.get_idempotent("k0") is None
    assert reg.get_idempotent("k%d" % (cap + 49)) == "j-%d" % (cap + 49)


# --------------------------------------------------------------------------
# Long-poll: wait_for_terminal / notify_state_change / wake_all_waiters
# --------------------------------------------------------------------------

def _set_state(job, state):
    """Transition a job's state the way controller code does (locked + notify)."""
    with job.lock:
        job.state = state
        job.notify_state_change()


def test_wait_for_terminal_immediate_when_already_terminal():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    _set_state(job, JobState.DONE)
    start = time.monotonic()
    assert job.wait_for_terminal(timeout=5.0) is True
    # Returns effectively immediately, not after the timeout.
    assert time.monotonic() - start < 0.5


def test_wait_for_terminal_times_out_when_non_terminal():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    start = time.monotonic()
    assert job.wait_for_terminal(timeout=0.2) is False
    elapsed = time.monotonic() - start
    assert 0.15 <= elapsed < 1.0


def test_wait_for_terminal_woken_by_state_change():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})

    def flip():
        time.sleep(0.1)
        _set_state(job, JobState.DONE)

    t = threading.Thread(target=flip)
    t.start()
    start = time.monotonic()
    reached = job.wait_for_terminal(timeout=5.0)
    elapsed = time.monotonic() - start
    t.join()
    assert reached is True
    # Woken by the notify well before the 5s timeout.
    assert elapsed < 2.0


def test_wait_for_terminal_aborts_on_event():
    job = ScanJob(job_id="j-0001", source="api", launch_state={})
    abort = threading.Event()

    def trip():
        time.sleep(0.1)
        # Mirror shutdown: set abort then notify via the registry helper.
        abort.set()
        with job.lock:
            job.notify_state_change()

    t = threading.Thread(target=trip)
    t.start()
    reached = job.wait_for_terminal(timeout=5.0, abort=abort)
    t.join()
    # Aborted while still non-terminal.
    assert reached is False
    assert job.state == JobState.RUNNING or job.state == JobState.QUEUED


def test_wake_all_waiters_releases_blocked_waiter():
    reg = JobRegistry()
    job = ScanJob(job_id=reg.next_id(), source="api", launch_state={})
    reg.add(job)
    abort = threading.Event()
    result = {}

    def waiter():
        result["reached"] = job.wait_for_terminal(timeout=5.0, abort=abort)

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    # Shutdown sequence: set abort, then wake every job's condition.
    abort.set()
    reg.wake_all_waiters()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert result["reached"] is False
