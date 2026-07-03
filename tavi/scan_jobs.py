"""Job queue data structures for TAVI scan execution.

Pure Python, no Qt imports -- this module holds the job/registry/result data
model shared between the GUI controller and (in later phases) the remote API
server. Everything here is designed to be JSON-serializable via ``snapshot()``
so HTTP request threads can read a consistent view without touching live
worker state. See ``docs/API_SERVER_DESIGN.md`` sections 7 and 13 (phase 1).
"""
import copy
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JobState(str, Enum):
    """Lifecycle states for a scan job.

    Inherits from ``str`` so ``json.dumps`` and comparisons treat the value as
    its plain string form (e.g. ``"queued"``).
    """
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


# Terminal states -- a job in one of these will never run again.
_TERMINAL_STATES = frozenset(
    {JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.STOPPED}
)


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into a JSON-serializable form.

    NaN/inf floats become ``None`` (bare ``NaN`` is invalid JSON and breaks
    strict parsers), ``JobState`` becomes its string value, and containers are
    copied element-wise. Everything else is passed through unchanged.
    """
    if isinstance(value, JobState):
        return value.value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(v) for v in value), key=str)
    return value


@dataclass
class ScanResult:
    """In-memory record of a scan's geometry and accumulating counts.

    Arrays are plain Python lists (not ndarrays) so ``json.dumps`` works
    directly. ``counts`` (1D) or ``counts_grid`` (2D) are pre-sized with
    ``None`` placeholders that the worker thread fills in by index as points
    complete; ``None`` means unmeasured or invalid.
    """
    mode: str  # '1D' | '2D' | 'single'
    variable_1: str
    variable_2: Optional[str]
    scan_values_1: List[float]
    scan_values_2: Optional[List[float]]
    valid_mask_1: List[bool]
    valid_mask_2d: Optional[List[List[bool]]]
    counts: Optional[List[Optional[float]]]
    counts_grid: Optional[List[List[Optional[float]]]]
    total_counts: float = 0.0
    max_counts: float = 0.0
    output_folder: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_data: bool = False) -> Dict[str, Any]:
        """Return a JSON-safe dict view of this result.

        With ``include_data=False`` the heavy arrays are omitted, leaving just
        summary scalars; with ``include_data=True`` the full arrays are
        included (NaN sanitized to ``None``). Callers already hold the job lock.
        """
        summary = {
            'mode': self.mode,
            'variable_1': self.variable_1,
            'variable_2': self.variable_2,
            'total_counts': _json_safe(self.total_counts),
            'max_counts': _json_safe(self.max_counts),
            'output_folder': self.output_folder,
        }
        if not include_data:
            return summary
        summary.update({
            'scan_values_1': _json_safe(self.scan_values_1),
            'scan_values_2': _json_safe(self.scan_values_2),
            'valid_mask_1': _json_safe(self.valid_mask_1),
            'valid_mask_2d': _json_safe(self.valid_mask_2d),
            'counts': _json_safe(self.counts),
            'counts_grid': _json_safe(self.counts_grid),
            'metadata': _json_safe(self.metadata),
        })
        return summary


@dataclass
class ScanJob:
    """A single queued/running scan, with its frozen launch state and result.

    Only the job worker thread mutates ``state``/``result``/timestamps; other
    threads read a consistent copy via ``snapshot()`` under ``lock``.
    """
    job_id: str
    source: str  # 'gui' | 'api'
    launch_state: Dict[str, Any]
    state: JobState = JobState.QUEUED
    submitted_at: Optional[float] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress_done: int = 0
    progress_total: int = 0
    error: Optional[str] = None
    result: Optional[ScanResult] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        # Condition shares the job lock so a thread holding ``lock`` (every
        # state-transition site does) can call ``notify_state_change()`` to wake
        # long-poll waiters, and a waiter's ``wait()`` releases/re-acquires the
        # same lock. Not a dataclass field: excluded from eq/repr, rebuilt fresh
        # per instance.
        self._state_cond = threading.Condition(self.lock)

    def notify_state_change(self) -> None:
        """Wake any long-poll waiters after a state change.

        The caller MUST already hold ``self.lock`` (all state-transition sites
        mutate ``state`` under it); this simply notifies the shared condition.
        """
        self._state_cond.notify_all()

    def wait_for_terminal(self, timeout: float,
                          abort: "Optional[threading.Event]" = None) -> bool:
        """Block until this job reaches a terminal state, timeout, or abort.

        Returns True if the job is terminal on return, False if the wait
        expired (or ``abort`` was set) while still non-terminal. ``abort`` lets
        server shutdown release the waiter promptly (shutdown both sets the
        event and notifies via the registry).
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._state_cond:
            while self.state not in _TERMINAL_STATES:
                if abort is not None and abort.is_set():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._state_cond.wait(remaining)
            return self.state in _TERMINAL_STATES

    def _launch_summary(self) -> Dict[str, Any]:
        """Small JSON-safe view of the frozen launch state.

        The full ``launch_state`` holds non-serializable objects (scan_config,
        sample mount, etc.), so only the fields useful to a remote observer --
        the scan commands and neutron count -- are exposed.
        """
        vals = self.launch_state.get('vals', {}) if isinstance(self.launch_state, dict) else {}
        return {
            'scan_command1': vals.get('scan_command1', ''),
            'scan_command2': vals.get('scan_command2', ''),
            'number_neutrons': _json_safe(vals.get('number_neutrons')),
        }

    def snapshot(self, include_data: bool = False) -> Dict[str, Any]:
        """Return a deep-copied, JSON-safe view of this job under its lock."""
        with self.lock:
            snap = {
                'job_id': self.job_id,
                'source': self.source,
                'state': self.state.value,
                'submitted_at': self.submitted_at,
                'started_at': self.started_at,
                'finished_at': self.finished_at,
                'progress': {
                    'done': self.progress_done,
                    'total': self.progress_total,
                },
                'error': self.error,
                'launch': self._launch_summary(),
                'result': (
                    self.result.to_dict(include_data=include_data)
                    if self.result is not None else None
                ),
            }
        # Deep-copy outside the lock is fine: the dict above is freshly built
        # from immutable scalars plus already-copied result data.
        return copy.deepcopy(snap)

    def is_terminal(self) -> bool:
        """True if the job has reached a terminal state (caller holds lock)."""
        return self.state in _TERMINAL_STATES


class JobRegistry:
    """Thread-safe registry of scan jobs keyed by id.

    Backs both the GUI job table and (later) the API ``/jobs`` endpoint. All
    access is serialized under an internal lock; ``snapshot()`` on individual
    jobs provides the JSON-safe read views.
    """

    # Bounded LRU map of Idempotency-Key -> job_id for POST /scan replay
    # protection. Cap keeps memory bounded; the oldest key is evicted first.
    IDEMPOTENCY_MAX = 256

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, ScanJob] = {}
        self._order: List[str] = []  # insertion order, oldest first
        self._counter = 0
        self._idempotency: "OrderedDict[str, str]" = OrderedDict()

    def next_id(self) -> str:
        """Produce the next sequential job id, e.g. ``'j-0001'``."""
        with self._lock:
            self._counter += 1
            return f"j-{self._counter:04d}"

    def add(self, job: ScanJob) -> None:
        """Register a job by its id."""
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)

    def get(self, job_id: str) -> Optional[ScanJob]:
        """Return the job with ``job_id`` or ``None``."""
        with self._lock:
            return self._jobs.get(job_id)

    def all_jobs(self) -> List[ScanJob]:
        """Return the live job objects, oldest first (caller must lock each)."""
        with self._lock:
            return [self._jobs[jid] for jid in self._order]

    def recent(self, n: int = 50) -> List[Dict[str, Any]]:
        """Return up to ``n`` job snapshots, newest first."""
        with self._lock:
            recent_ids = list(reversed(self._order))[:n]
            jobs = [self._jobs[jid] for jid in recent_ids]
        # Snapshot outside the registry lock so a long deep-copy does not block
        # registration; each job takes its own lock internally.
        return [job.snapshot() for job in jobs]

    def get_idempotent(self, key: str) -> Optional[str]:
        """Return the job id previously stored under ``key`` (LRU touch)."""
        with self._lock:
            job_id = self._idempotency.get(key)
            if job_id is not None:
                self._idempotency.move_to_end(key)
            return job_id

    def put_idempotent(self, key: str, job_id: str) -> None:
        """Record ``key -> job_id``, evicting the oldest beyond the LRU cap."""
        with self._lock:
            if key in self._idempotency:
                self._idempotency.move_to_end(key)
            self._idempotency[key] = job_id
            while len(self._idempotency) > self.IDEMPOTENCY_MAX:
                self._idempotency.popitem(last=False)

    def wake_all_waiters(self) -> None:
        """Notify every job's condition so long-poll waiters can re-check.

        Used on server shutdown (paired with an abort event) so blocked
        handler threads return promptly instead of hanging until their timeout.
        """
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            with job.lock:
                job.notify_state_change()


def compute_budget_usage(registry: "JobRegistry",
                         limits: "Optional[BudgetLimits]") -> Dict[str, Any]:
    """Return the API budget-usage view: pending neutrons and queue depth.

    Shared by ``TaviApiBackend.get_state`` (the ``/state`` budget block) and the
    GUI API dock (via ``TAVIController.get_api_budget_usage``) so both report the
    same numbers. ``pending_neutrons`` sums the pre-computed ``_api_cost`` of the
    still-pending (QUEUED/RUNNING) API-sourced jobs; ``queued_jobs`` counts jobs
    in QUEUED regardless of source. Budget/limit fields are ``None`` when no
    ``BudgetLimits`` is configured.
    """
    pending_neutrons = 0.0
    queued_jobs = 0
    for job in registry.all_jobs():
        with job.lock:
            state = job.state
            source = job.source
        if state == JobState.QUEUED:
            queued_jobs += 1
        if state in (JobState.QUEUED, JobState.RUNNING) and source == "api":
            pending_neutrons += float(getattr(job, "_api_cost", 0.0) or 0.0)
    return {
        "pending_neutrons": pending_neutrons,
        "budget": limits.queue_neutron_budget if limits is not None else None,
        "queued_jobs": queued_jobs,
        "max_queued": limits.max_queued if limits is not None else None,
    }


@dataclass
class BudgetLimits:
    """Abuse-prevention limits for API-submitted scan jobs.

    Data plus a submission-check helper. Enforcement wiring (HTTP 429) lands in
    phase 3; this phase only defines the limits and the pure check.
    """
    max_queued: int = 10
    max_points: int = 200
    max_neutrons_per_point: float = 1e8
    queue_neutron_budget: float = 1e10

    def check_submission(self, points: int, neutrons_per_point: float,
                         pending_cost: float) -> Optional[str]:
        """Return a human-readable rejection reason, or ``None`` if allowed.

        ``pending_cost`` is the summed points*neutrons already committed to the
        pending queue; the new job's own cost is added on top for the budget
        check. Queue-depth (``max_queued``) is enforced by the caller since it
        depends on live queue state, not the per-submission numbers here.
        """
        if points > self.max_points:
            return (f"scan has {points} points, exceeding the limit of "
                    f"{self.max_points}")
        if neutrons_per_point > self.max_neutrons_per_point:
            return (f"{neutrons_per_point:g} neutrons/point exceeds the limit "
                    f"of {self.max_neutrons_per_point:g}")
        new_cost = points * neutrons_per_point
        if pending_cost + new_cost > self.queue_neutron_budget:
            return (f"queue neutron budget exceeded: pending {pending_cost:g} + "
                    f"this job {new_cost:g} > budget {self.queue_neutron_budget:g}")
        return None
