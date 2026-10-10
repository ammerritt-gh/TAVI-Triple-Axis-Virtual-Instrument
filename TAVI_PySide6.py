"""Main application controller for TAVI with PySide6 GUI."""
import sys
import os
import shutil
import json
import hashlib
import logging
import time
import datetime
import copy
import threading
import queue
import math
import numpy as np
import mcstasscript as ms

from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit
from PySide6.QtCore import QObject, Signal, Slot, QTimer

# Import the instrument contract (the concrete instrument arrives via main())
from tavi.local_state import config_path as local_config_path

from instruments.contract import (
    DEFAULT_MPI_COUNT,
    CurvatureMode,
    PrepFailure,
    RunExecutionState,
)
from instruments.rules import (
    DE,
    Q as Q_IDS,
    Q_CALC,
    RADIUS_CRYSTAL,
    PlanRefused,
    build_plan,
    check_point,
    context_from_state,
    expand,
    point_plan,
)
from instruments.tas_runtime import (
    STAGE_FLAG_PREFIX,
    describe_scan_error_flags,
    training_reach_error,
)
from instruments.paths import COMPONENTS_DIR

log = logging.getLogger(__name__)


def _operator_magnitudes(ideal):
    """Strip the branch sign off radii bound for the operator surface.

    ``ideal_curvature`` returns SIGNED radii, which is what the scan loop
    wants: it hands them to ``set_crystal_bending``, which is the physical
    boundary where a curvature centre has to sit on the take-off side.

    The operator surface is the other contract. A radius shown in a field,
    saved to parameters.json, or sent in an API request is a MAGNITUDE -- how
    tightly the crystal is bent, which is the operator's business. Which side
    it bends toward is instrument geometry and is derived, never typed.

    Keeping that straight is not cosmetic. ``tavi/resolution.py`` applies the
    scattering sense itself (``monorh = radius_cm(cfg.rhm) * sm``), reading
    the same ``vals`` the GUI and API fill. A signed value there is signed
    twice, and the analytic resolution then describes a crystal bent the wrong
    way -- silently, because the emitted McStas geometry is still correct.
    """
    return {axis: abs(value) for axis, value in ideal.items()}


def _vals_with_point_state(vals, metadata):
    """Overlay one point's ACTUALLY APPLIED radii AND kinematics onto a copy
    of ``vals``.

    ``resolution_config`` (``instruments/resolution_adapter.py``) reads
    rhm/rvm/rha/rva straight out of ``vals`` as magnitudes (applying the
    scattering sense itself) and prefers ``vals['Ki']``/``vals['Kf']`` for
    the fixed wavevector (``_kfix``). The frozen launch ``vals`` carries only
    the operator's declared/starting radii and the LAUNCH energies -- never
    what an AUTOFOCUS or SCANNED curvature axis actually ran with at THIS
    point, nor this point's own energy transfer under a direct-angle scan,
    where the snapshot's Ei/Ki/Ef/Kf differ from the launch's (D23): an A4
    scan under Kf-fixed otherwise hands Popovici a per-point energy transfer
    against the LAUNCH Kf instead of the point's own.

    ``metadata`` is the per-point dict carrying rhm/rvm/rha/rva (SIGNED --
    the physical boundary's output), Ei/Ki/Ef/Kf, and deltaE -- snapshot
    metadata (``instruments/tas_runtime.py``'s ``point_energy_metadata``
    merge), or the equivalent freshly built for a point with no snapshot
    (``compute_resolution``). Radii are stripped to magnitudes through
    ``_operator_magnitudes``, the same sign strip the operator/API surface
    already relies on, so the resolution adapter's "arrived signed" guard
    never has cause to fire; Ei/Ki/Ef/Kf/deltaE pass through as-is (already
    unsigned).
    """
    point_vals = dict(vals)
    point_vals.update(_operator_magnitudes(
        {axis: metadata[axis] for axis in ("rhm", "rvm", "rha", "rva")}
    ))
    for key in ("Ei", "Ki", "Ef", "Kf", "deltaE"):
        if key in metadata:
            point_vals[key] = metadata[key]
    return point_vals


def _point_angles(mtt, stt, att):
    """``point_angles`` kwarg for ``resolution_config`` -- this point's own
    solved two-theta angles, so the resolution model reads its scattering
    senses off the point it is describing instead of always rebuilding them
    from the descriptor's declared (normal-branch) ``Geometry``. See
    ``instruments/resolution_adapter.py:_axis_sense``."""
    return {"mtt": mtt, "stt": stt, "att": att}

# Import TAVI core modules
from tavi.data_processing import (read_1Ddetector_file, write_parameters_to_file,
                                   simple_plot_scan_commands, display_existing_data,
                                   read_parameters_from_file, require_output_version,
                                   write_1D_scan, write_2D_scan)
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy
from tavi.utilities import parse_scan_steps, incremented_path_writing, scan_range_error
from tavi.sample_mount import SampleMount
from tavi.orientation import (check_travel, lock_plane, locked_plane_text, plane_text,
                              record_angles, stage_record, stage_rotation)
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    instrument_q_to_component_q,
    lab_q_from_stt,
)
from tavi.ub_matrix import (UBMatrix, ObservedPeak, compute_B_matrix, grade_alignment,
                            decode_mount_exercise, generate_training_exercise, get_scattering_plane_info,
                            u_from_plane, validate_rotation_matrix, alignment_residuals,
                            refine_lattice_from_peaks, small_integer_indices)
from tavi.runtime_tracker import RuntimeTracker
from tavi.settings import load_mpi_count, save_mpi_count
from tavi.machine_profile import machine_fingerprint
from tavi.scan_jobs import (
    BudgetLimits, JobRegistry, JobState, ScanJob, ScanResult, compute_budget_usage,
)
from tavi.api_server import (TaviApiServer, ApiError, load_api_config,
                             MAX_WAITERS, parse_scan_engine,
                             parse_scan_background, ALLOWED_ENGINES,
                             BACKGROUND_SPEC_KEYS)
from tavi import background as _background
from tavi.journal import SessionJournal
from tavi import scan_fits
from tavi.quantities import API_VERSION, QUANTITIES, QuantityRefused, UnknownQuantity
from tavi.quantities import crystal_theta, normalize_write_names, resolve as resolve_quantity
from tavi.quantities import slit_gap_id, slit_gap_ids
from tavi.quantities import public_values as _public_values, schema_unit
from tavi.quantities import to_internal as _to_internal, to_public as _to_public
from tavi.reflection_catalog import (load_reflections, plane_filtered_unique,
                                     primitive_miller, ProjectedReflection,
                                     reference_hkls)
from tavi.reciprocal_interaction import (LiveReciprocalResult, ReachOverlay,
                                         ReciprocalState, format_small,
                                         triangle_can_close)
from tavi.space_groups import generate_allowed_reflections, get_space_group

# Import GUI
from gui.main_window import TAVIMainWindow
from gui.dialogs.background_config_dialog import BackgroundConfigDialog
from gui.dialogs.diagnostic_config_dialog import DiagnosticConfigDialog

# Physical constants
N_MASS = 1.67492749804e-27  # neutron mass
E_CHARGE = 1.602176634e-19  # electron charge
K_B = 0.08617333262  # Boltzmann's constant in meV/K
HBAR_meV = 6.582119569e-13  # H-bar in meV*s
HBAR = 1.05459e-34  # H-bar in J*s


def _background_q_magnitude(metadata):
    """Return |Q| for any executed scan mode from frozen point metadata.

    ``None`` when the monochromator or analyser transmitted (no incident or
    final wavevector was selected, so |Q| is not a claim TAVI can make; the
    angle-mode branch would otherwise crash on ``float(None)``). A
    sample-only transmission -- forward scattering with both crystals
    reflecting -- keeps both wavevectors and its determined |Q| (ruling 7);
    it is the analytic engine, not |Q|, that has nothing to say there.
    """
    transmission = metadata.get("transmission") or []
    if "mono" in transmission or "ana" in transmission:
        # No incident or final wavevector was selected: |Q| is not a claim
        # TAVI can make. A sample-only transmission (forward scattering)
        # keeps both wavevectors and its determined |Q| (ruling 7).
        return None
    q_components = (
        metadata.get("qx"),
        metadata.get("qy"),
        metadata.get("qz"),
    )
    if all(value is not None for value in q_components):
        return math.sqrt(sum(float(value) ** 2 for value in q_components))
    if metadata.get("Ki") is None or metadata.get("Kf") is None:
        return None
    q_lab = lab_q_from_stt(
        float(metadata["Ki"]),
        float(metadata["Kf"]),
        float(metadata["stt"]),
    )
    return math.sqrt(sum(float(value) ** 2 for value in q_lab))


def format_editable_number(value: float, places: int = 4) -> str:
    """Format editable numeric fields with compact fixed-decimal text."""
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "inf" if number > 0 else "-inf"
    rounded = round(number, places)
    if abs(rounded) < 0.5 * 10 ** (-places):
        rounded = 0.0
    return f"{rounded:.{places}f}".rstrip("0").rstrip(".") or "0"


class _GuiCall:
    """A function call marshalled from a worker thread onto the GUI thread.

    Carries the callable plus a ``threading.Event`` the GUI-thread slot sets once
    it has run ``fn`` and stored the result (or the exception). The waiting HTTP
    thread blocks on ``done`` with a timeout.
    """
    __slots__ = ("fn", "done", "result", "error")

    def __init__(self, fn):
        self.fn = fn
        self.done = threading.Event()
        self.result = None
        self.error = None


class ApiBridge(QObject):
    """Marshals backend reads/writes from HTTP worker threads onto the GUI thread.

    Created on the GUI thread. ``call_on_gui`` wraps ``fn`` in a ``_GuiCall`` and
    emits it over the ``_invoke`` signal; because the emitter is a worker thread
    and this object lives on the GUI thread, Qt delivers it as a *queued*
    connection to ``_execute`` on the GUI thread. The worker then waits (with a
    timeout) for the call's Event. If the GUI thread is blocked -- e.g. a modal
    dialog is open -- the wait times out and a 503 ``gui_busy`` is raised instead
    of deadlocking (see docs/API_SERVER_DESIGN.md sec 4.1).
    """

    _invoke = Signal(object)

    def __init__(self):
        super().__init__()
        # Auto/queued connection: created on the GUI thread, emitted from worker
        # threads, so Qt queues delivery onto the GUI thread's event loop.
        self._invoke.connect(self._execute)

    def call_on_gui(self, fn, timeout=5.0):
        """Run ``fn`` on the GUI thread and return its result (or raise).

        Raises ``ApiError(503, 'gui_busy')`` if the GUI thread does not respond
        within ``timeout`` seconds; re-raises any exception ``fn`` raised.
        """
        call = _GuiCall(fn)
        self._invoke.emit(call)
        if not call.done.wait(timeout):
            raise ApiError(
                503, "gui_busy",
                "GUI thread did not respond (busy or modal dialog open)",
            )
        if call.error is not None:
            raise call.error
        return call.result

    @Slot(object)
    def _execute(self, call):
        """GUI-thread slot: run the wrapped callable and signal completion."""
        try:
            call.result = call.fn()
        except Exception as exc:  # propagate to the waiting HTTP thread
            call.error = exc
        finally:
            call.done.set()


class TaviApiBackend:
    """Duck-typed backend consumed by ``TaviApiServer`` (plain class, no Qt).

    Holds a reference to the controller and the ``ApiBridge``. Read endpoints
    that touch GUI widgets (parameters) go through the bridge onto the GUI
    thread; job-registry reads and stop actions use the thread-safe registry,
    per-job locks, and the shared stop event directly (no GUI touch). The write
    endpoints ``patch_parameters`` / ``submit_scan`` are intentionally absent so
    the handler returns 501 until phase 3.
    """

    def __init__(self, controller, bridge):
        self._controller = controller
        self._bridge = bridge
        # Set by _start_api_server after the server is constructed so the backend
        # can report the live access mode. Guarded against None.
        self.server = None
        # Long-poll (GET /scan/{id}?wait=N) coordination: a bounded count of
        # concurrent waiters and an abort event that server shutdown sets so
        # blocked handler threads release promptly.
        self._waiter_lock = threading.Lock()
        self._waiter_count = 0
        self._wait_abort = threading.Event()

    # ---- helpers -------------------------------------------------------

    def _mode(self):
        server = self.server
        return server.mode if server is not None else None

    def _instrument_id(self):
        try:
            return self._controller.descriptor.id
        except Exception:
            return None

    def _get_job_or_404(self, job_id):
        job = self._controller._job_registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        return job

    # ---- read endpoints ------------------------------------------------

    def get_health(self):
        return {
            "status": "ok",
            "instrument": self._instrument_id(),
            "mode": self._mode(),
        }

    def get_parameters(self):
        return self._bridge.call_on_gui(self._controller.api_parameters)

    def get_state(self):
        def read():
            # lock_stale is not a GUI value (so never a launch value or scan
            # metadata); /state adds it, read from the one stale function.
            vals = self._controller.get_gui_values()
            if vals is None:
                return None
            stale = self._controller.lock_stale(vals)
            vals = self._controller.public_values(vals)
            vals['lock_stale'] = stale
            return vals
        params = self._bridge.call_on_gui(read)
        registry = self._controller._job_registry
        active = self._controller._active_job
        current_job = active.job_id if active is not None else None

        queued = []
        for job in registry.all_jobs():
            with job.lock:
                if job.state == JobState.QUEUED:
                    queued.append(job.job_id)

        state = {
            "instrument": self._instrument_id(),
            "mode": self._mode(),
            "busy": current_job is not None,
            "current_job": current_job,
            "queue": queued,
            "parameters": params,
        }
        limits = getattr(self._controller, "_api_limits", None)
        if limits is not None:
            state["limits"] = limits
        state["budget"] = self._budget_usage()
        state["background"] = self._controller.background_profile_state()
        return state

    def get_background(self):
        """GET /background -- the instrument's configured background profile.

        The profile is a plain dict on the controller, not a widget, so this
        needs no GUI hop (same reasoning as :meth:`get_journal`). The response
        is the complete normalized catalog-backed configuration and resolved
        provenance block.
        """
        return self._controller.background_profile_state()

    def set_background(self, body):
        """PUT /background -- replace the profile wholesale (never merges).

        Bridged onto the GUI thread because the write refreshes the dock's
        background row. A spec ``tavi.background.resolve`` rejects surfaces as
        400 ``invalid_background``, mirroring how :meth:`patch_parameters`
        turns field validation failures into 400 ``invalid_parameters``.
        """
        if not isinstance(body, dict):
            raise ApiError(400, "bad_request", "Request body must be a JSON object")
        try:
            return self._bridge.call_on_gui(
                lambda: self._controller.set_background_profile(body)
            )
        except ValueError as exc:
            raise ApiError(400, "invalid_background", str(exc))

    # ---- budget accounting (thread-safe registry reads) ----------------

    def _budget_limits(self):
        return getattr(self._controller, "_budget_limits", None)

    def _pending_api_cost(self):
        """Summed points*neutrons committed by pending API jobs (QUEUED+RUNNING)."""
        total = 0.0
        for job in self._controller._job_registry.all_jobs():
            with job.lock:
                pending = job.state in (JobState.QUEUED, JobState.RUNNING)
                source = job.source
            if pending and source == "api":
                total += float(getattr(job, "_api_cost", 0.0) or 0.0)
        return total

    def _queued_count(self):
        """Number of jobs currently QUEUED (any source)."""
        count = 0
        for job in self._controller._job_registry.all_jobs():
            with job.lock:
                if job.state == JobState.QUEUED:
                    count += 1
        return count

    def _budget_usage(self):
        return compute_budget_usage(
            self._controller._job_registry, self._budget_limits()
        )

    def get_job(self, job_id):
        job = self._get_job_or_404(job_id)
        snap = job.snapshot()
        snap["eta"] = self._eta_for_job(job)
        return snap

    def get_job_data(self, job_id):
        return self._get_job_or_404(job_id).snapshot(include_data=True)

    def get_job_plot_png(self, job_id):
        """GET /scan/{id}/plot.png -- render the job's stored arrays to PNG.

        Reads the JSON-safe result arrays off the thread-safe job snapshot (no
        GUI touch) and renders them in the calling HTTP handler thread via the
        Qt-free ``tavi.plot_render`` module (matplotlib Agg, never pyplot).
        Returns raw PNG bytes; 404 for an unknown job, 409 ``no_data`` when the
        job has no renderable points yet.
        """
        job = self._get_job_or_404(job_id)
        snap = job.snapshot(include_data=True)
        result = snap.get("result")
        # Lazy import so matplotlib is only loaded on first plot request and
        # never at controller import time (keeps the render path off the GUI
        # backend). NoPlotData -> 409 no_data.
        from tavi.plot_render import render_scan_plot_png, NoPlotData
        try:
            return render_scan_plot_png(result, job_id)
        except NoPlotData as exc:
            raise ApiError(409, "no_data", str(exc))

    def get_journal(self, limit=100):
        """GET /journal -- session-narrative ring buffer (read-only).

        Reads the controller's Qt-free ``SessionJournal`` directly (plain deque
        + lock); no GUI-thread hop needed. Allowed in read-only mode.
        """
        return self._controller._journal.read(limit)

    def list_jobs(self):
        return self._controller._job_registry.recent()

    # ---- ETA / long-poll -----------------------------------------------

    def _eta_for_job(self, job):
        """Return the ``{estimated_seconds, confidence, samples}`` ETA for a job.

        Queued jobs estimate the whole scan (compile + all points); a running
        job estimates only the remaining points (compile already sunk). Terminal
        jobs still report a full-scan estimate for reference. Pure computation
        over the runtime tracker -- safe to call off the GUI thread.
        """
        with job.lock:
            state = job.state
            done = job.progress_done
            total = job.progress_total
            launch = job.launch_state if isinstance(job.launch_state, dict) else {}
        vals = launch.get("vals", {}) if isinstance(launch, dict) else {}
        try:
            ncount = int(float(vals.get("number_neutrons") or 0))
        except (TypeError, ValueError):
            ncount = 0
        # The points the job's compiled plan runs (every queued job carries one).
        expansion = launch.get("expansion")
        points = len(expansion.points) if expansion is not None else (total or 1)

        needs_compile = True
        if state == JobState.RUNNING:
            needs_compile = False
            if total > 0:
                points = max(0, total - done)

        instrument_name = self._instrument_id()
        engine = launch.get("engine") or "mcstas"
        return self._controller.runtime_tracker.estimate_scan_seconds(
            instrument_name, points, ncount, needs_compile, engine=engine,
            mpi_count=launch.get("mpi_count"),
        )

    def estimate_queue_drain_seconds(self):
        """Sum the ETA of all pending (QUEUED/RUNNING) jobs, or ``None``.

        Backs the Retry-After hint on 429 responses. Returns ``None`` when no
        pending job yields an estimate (the server then uses its constant).
        """
        total = 0.0
        have_estimate = False
        for job in self._controller._job_registry.all_jobs():
            with job.lock:
                pending = job.state in (JobState.QUEUED, JobState.RUNNING)
            if not pending:
                continue
            secs = self._eta_for_job(job).get("estimated_seconds")
            if secs is not None:
                total += secs
                have_estimate = True
        return total if have_estimate else None

    def wait_for_job(self, job_id, timeout):
        """Block up to ``timeout`` s until the job is terminal; return its status.

        The returned payload matches ``get_job`` plus a ``timed_out`` flag (True
        only when the wait expired while the job was still non-terminal). Caps
        concurrent waiters with HTTP 429 ``too_many_waiters``.
        """
        job = self._get_job_or_404(job_id)
        with self._waiter_lock:
            if self._wait_abort.is_set():
                # Server shutting down: do not block, report current status.
                snap = job.snapshot()
                snap["eta"] = self._eta_for_job(job)
                snap["timed_out"] = False
                return snap
            if self._waiter_count >= MAX_WAITERS:
                raise ApiError(
                    429, "too_many_waiters",
                    "Too many concurrent long-poll waiters (limit %d)" % MAX_WAITERS,
                )
            self._waiter_count += 1
        try:
            reached = job.wait_for_terminal(timeout, abort=self._wait_abort)
        finally:
            with self._waiter_lock:
                self._waiter_count -= 1
        snap = job.snapshot()
        snap["eta"] = self._eta_for_job(job)
        # timed_out only when the wait genuinely expired (not an abort/shutdown).
        snap["timed_out"] = (not reached) and (not self._wait_abort.is_set())
        return snap

    def shutdown_waiters(self):
        """Release all long-poll waiters on server shutdown.

        Sets the abort event and notifies every job's condition so blocked
        ``wait_for_job`` calls return promptly instead of hanging.
        """
        self._wait_abort.set()
        self._controller._job_registry.wake_all_waiters()

    # ---- stop endpoints (thread-safe; no bridge / no GUI touch) --------

    def stop_job(self, job_id):
        job = self._get_job_or_404(job_id)
        with job.lock:
            state = job.state
            if state == JobState.QUEUED:
                job.state = JobState.CANCELLED
                if job.finished_at is None:
                    job.finished_at = time.time()
                job.notify_state_change()
            elif state in _API_TERMINAL_STATES:
                raise ApiError(
                    409, "job_finished",
                    "Job %s already finished (%s)" % (job_id, state.value),
                )
            # RUNNING: fall through and set the shared stop event outside the lock
        if state == JobState.RUNNING:
            self._controller.stop_event.set()
        return job.snapshot()

    def stop_all(self, clear_queue):
        registry = self._controller._job_registry
        running_id = None
        cancelled = []
        for job in registry.all_jobs():
            with job.lock:
                if job.state == JobState.RUNNING:
                    running_id = job.job_id
                elif clear_queue and job.state == JobState.QUEUED:
                    job.state = JobState.CANCELLED
                    if job.finished_at is None:
                        job.finished_at = time.time()
                    job.notify_state_change()
                    cancelled.append(job.job_id)
        if running_id is not None:
            self._controller.stop_event.set()
        return {"stopped": running_id, "cancelled": cancelled}

    # ---- write endpoints ----------------------------------------------

    def _has_active_or_queued(self):
        # Single source of truth, shared with the GUI-side goto (sec 8).
        return self._controller._scan_busy()

    def patch_parameters(self, patch, force):
        """PATCH /parameters -- apply a partial parameter set (sec 6, sec 8).

        Validates the request shape, guards against a busy queue (unless
        ``force``), applies the patch on the GUI thread via the bridge, and
        reports the applied fields plus any per-field errors.
        """
        if not isinstance(patch, dict):
            raise ApiError(400, "bad_request", "Request body must be a JSON object")
        for key, value in patch.items():
            if not isinstance(value, (str, int, float, bool, dict)) or value is None:
                raise ApiError(
                    400, "bad_request",
                    "Field %r must be a scalar or object, got %s"
                    % (key, type(value).__name__),
                )

        if not force and self._has_active_or_queued():
            raise ApiError(
                409, "busy",
                "A scan is running or queued; retry with ?force=1 to override",
            )

        applied, errors = self._bridge.call_on_gui(
            lambda: self._controller.apply_parameters(patch)
        )

        if errors:
            raise ApiError(
                400, "invalid_parameters", "One or more fields failed",
                details={"applied": list(applied), "errors": errors},
            )
        return {"applied": list(applied), "errors": errors}

    def submit_scan(self, body, idempotency_key=None):
        """POST /scan -- queue a scan job with budget enforcement (sec 6, 7).

        Optional ``body['parameters']`` is applied first (same path as
        patch_parameters, minus the busy guard since we are queueing anyway).
        The whole submission runs atomically on the GUI thread so cost accounting
        and enqueue cannot race another submitter. When ``idempotency_key`` is
        given and already maps to a live job, the existing job's status is
        returned (flagged for a 200 replay) instead of creating a new job.
        """
        if not isinstance(body, dict):
            raise ApiError(400, "bad_request", "Request body must be a JSON object")
        patch = body.get("parameters")
        if patch is not None and not isinstance(patch, dict):
            raise ApiError(400, "bad_request", "'parameters' must be a JSON object")
        force = bool(body.get("force", False))
        isolated = bool(body.get("isolated", False))
        allow_partial = body.get("allow_partial", False)
        if not isinstance(allow_partial, bool):
            raise ApiError(400, "bad_request", "'allow_partial' must be a boolean")
        # Execution-backend selection (docs/CONTROL_FEATURES_DESIGN.md §6.4).
        # Validated Qt-free; an unknown engine is a 400 with the allowed list.
        engine, seed, noiseless = parse_scan_engine(body)
        # Per-scan background override: shape-checked Qt-free here, resolved
        # numerically on the GUI thread by the engine that plants it.
        background = parse_scan_background(body)

        result = self._bridge.call_on_gui(
            lambda: self._submit_scan_on_gui(patch, force, idempotency_key,
                                             isolated, allow_partial,
                                             engine, seed, noiseless,
                                             background)
        )
        return result

    def _build_validation(self, controller, launch_state, points, neutrons):
        """Assemble the ``validation`` block for a launch state (points/cost/eta).

        Feasibility + per-command expansion come from the controller (GUI-thread
        angle math); budget/cost and ETA are folded in here since the backend
        owns those. ``points`` is the total requested-point count; ETA and cost
        are scaled to the points that will actually run.
        Returns the ``validation`` dict embedded in 202/validate responses.
        """
        validation = controller.validate_scan_launch_state(launch_state)
        run_points = int(validation.get("feasible_points", points))
        validation["cost"] = dict(
            self._budget_usage(),
            requested_points=points,
            feasible_points=run_points,
            neutrons_per_point=neutrons,
            job_neutrons=run_points * neutrons,
        )
        engine = (launch_state or {}).get("engine") or "mcstas"
        try:
            eta = controller.runtime_tracker.estimate_scan_seconds(
                self._instrument_id(), run_points, int(neutrons), True,
                engine=engine, mpi_count=(launch_state or {}).get("mpi_count"),
            )
        except Exception:
            eta = {"estimated_seconds": None, "confidence": "none", "samples": 0}
        validation["eta"] = eta
        return validation

    @staticmethod
    def _apply_background_to_launch_state(controller, launch_state, background):
        """Stamp the effective background spec and its delivery source.

        A per-scan override REPLACES the controller's configured profile
        wholesale -- it never merges -- so the source tag fully explains which
        of the two the scan ran with.
        """
        launch_state['background'] = copy.deepcopy(
            background if background is not None
            else getattr(
                controller,
                'background_profile',
                _background.default_spec(),
            )
        )
        launch_state['background_source'] = (
            'per_scan_override' if background is not None else 'config_default'
        )

    def _background_validation(self, controller, launch_state):
        """``(block, blocker)`` for the launch state's background at /validate.

        Background sources are sample-independent configuration in schema v2,
        so validation only needs to resolve the complete request. ``blocker`` is
        ``None`` when it resolves and ``invalid_background`` otherwise.
        """
        source = launch_state.get('background_source') or 'config_default'
        try:
            resolved = _background.resolve(launch_state.get('background'))
        except ValueError as exc:
            block = {
                "enabled": None,
                "delivery_source": source,
                "profile_fingerprint": None,
                "effective_fingerprint": None,
            }
            block["error"] = {"id": "invalid_background", "message": str(exc)}
            return block, "invalid_background: %s" % exc
        launch_state['background'] = _background.normalized_spec(resolved)
        return _background.metadata_block(resolved, source), None

    def _submit_scan_on_gui(self, patch, force, idempotency_key=None,
                            isolated=False, allow_partial=False,
                            engine="mcstas", seed=None,
                            noiseless=False, background=None):
        """Atomic scan submission body -- runs on the GUI thread via the bridge.

        Returns the 202 payload dict or raises ``ApiError`` (which the bridge
        re-raises to the HTTP thread for envelope serialization).

        The launch state is built from widget-free defaults overlaid with the
        request's ``parameters`` patch (:meth:`build_api_launch_state`);
        submission neither reads nor writes GUI widgets, so live GUI state can
        never poison an API scan and an API scan never mutates the GUI.
        ``isolated`` is still accepted and echoed for backward compatibility but
        is now a no-op (the path is always isolated); PATCH /parameters is the
        only GUI-mutating endpoint.
        """
        controller = self._controller
        registry = controller._job_registry

        # 0. Idempotency replay: a previously seen key mapping to a live job
        #    returns that job's current status (200 replay) without re-queueing.
        if idempotency_key:
            existing_id = registry.get_idempotent(idempotency_key)
            if existing_id:
                existing = registry.get(existing_id)
                if existing is not None:
                    snap = existing.snapshot()
                    snap["eta"] = self._eta_for_job(existing)
                    snap["_idempotent_reuse"] = True
                    return snap

        # 1. Freeze the launch state from defaults + patch (no widget access).
        launch_state = controller.build_api_launch_state(patch)
        launch_state["isolated"] = bool(isolated)
        # Engine selection (POST /scan body) overrides the default engine baked
        # into the frozen launch state, so an API caller always gets the backend
        # it asked for. seed/noiseless are deterministic-only (ignored by the
        # McStas worker) but stored for provenance either way.
        launch_state["engine"] = engine
        launch_state["seed"] = seed
        launch_state["noiseless"] = bool(noiseless)
        self._apply_background_to_launch_state(controller, launch_state, background)
        vals = launch_state["vals"]
        cmd1 = vals.get("scan_command1", "")
        cmd2 = vals.get("scan_command2", "")

        # 2. Validate scan commands. ``force`` clears the soft issues only;
        #    a hard one is refused whatever the caller says.
        issues = self._blocking_scan_issues(controller, vals, cmd1, cmd2, force)
        if issues:
            raise ApiError(400, "scan_validation", "\n".join(issues))

        # 2a. Resolve the background against this scan's sample -- the same
        #     check /validate runs, so a body that validates cannot be rejected
        #     at scan time for a background reason, and a doomed job is never
        #     queued. Cheap (no per-point work) and already on the GUI thread.
        background_block, background_blocker = self._background_validation(
            controller, launch_state
        )
        if background_blocker is not None:
            raise ApiError(
                400, background_block["error"]["id"],
                background_block["error"]["message"],
                details={"background": background_block},
            )

        # 3. Compute this job's cost.
        try:
            points = controller._count_scan_points(cmd1, cmd2)
        except Exception:
            # A command the gate accepted but the sizer cannot parse: treat
            # it as a single point for budget and let the scan itself report.
            points = 1
        neutrons = float(vals.get("number_neutrons") or 0)

        # 3a. Over-limit guard BEFORE the per-point feasibility expansion.
        #     _build_validation below deep-copies the scan config and runs
        #     the angle solver once per point on the GUI thread; for a scan
        #     far over max_points that monopolizes the single GUI event loop
        #     (starving every other bridged API call) only to be rejected by
        #     the budget check in step 5 anyway. Rejecting here on the cheap
        #     point count keeps an over-limit submission from ever expanding.
        limits = getattr(controller, "_budget_limits", None)
        if limits is not None and points > limits.max_points:
            reason = ("scan has %d points, exceeding the limit of %d"
                      % (points, limits.max_points))
            controller._journal.record("budget", "rejected: %s" % reason)
            raise ApiError(
                429, "limit_exceeded", reason,
                details={"usage": self._budget_usage()},
            )

        # 4. The one compile-and-expand, then always-on feasibility validation
        #    (API path only): the validation block (per-command points +
        #    per-point feasibility + cost + eta). Partial feasibility is
        #    opt-in; by default any infeasible point rejects the whole
        #    submission. A refused plan, or one that cannot be checked, is a
        #    hard refusal that neither force nor allow_partial clears.
        try:
            controller._compile_launch(launch_state)
            validation = self._build_validation(
                controller, launch_state, points, neutrons
            )
        except PlanRefused as refused:
            raise ApiError(400, "scan_validation", str(refused))
        validation["background"] = background_block
        infeasible = validation.get("infeasible", [])
        feasible_points = int(validation.get("feasible_points", points))
        if feasible_points <= 0:
            raise ApiError(
                400, "all_points_infeasible",
                "No requested scan point is feasible",
                details=validation,
            )
        if infeasible and not allow_partial:
            raise ApiError(
                400, "infeasible_points",
                "One or more requested scan points are infeasible",
                details=validation,
            )
        if infeasible:
            launch_state["skipped_indices"] = [e["index"] for e in infeasible]
            launch_state["skipped_points"] = infeasible
        launch_state["planned_feasibility"] = validation.get("point_manifest", [])
        launch_state["planned_feasible_mask"] = validation.get(
            "planned_feasible_mask", [])
        launch_state["feasible_segments"] = validation.get("feasible_segments", [])

        # 5. Budget + queue-depth enforcement (API-sourced jobs only).
        #    ``limits`` was resolved in step 3a for the over-limit guard.
        pending_cost = self._pending_api_cost()
        queued_now = self._queued_count()
        if limits is not None:
            if queued_now >= limits.max_queued:
                reason = ("queue is full: %d queued jobs, limit is %d"
                          % (queued_now, limits.max_queued))
                controller._journal.record("budget", "rejected: %s" % reason)
                raise ApiError(
                    429, "limit_exceeded", reason,
                    details={"usage": self._budget_usage()},
                )
            reason = limits.check_submission(feasible_points, neutrons, pending_cost)
            if reason is not None:
                controller._journal.record("budget", "rejected: %s" % reason)
                raise ApiError(
                    429, "limit_exceeded", reason,
                    details={"usage": self._budget_usage()},
                )

        # 6. Enqueue and tag the job with its cost for future budget math.
        job = controller.submit_scan_job(launch_state, "api")
        job._api_cost = feasible_points * neutrons
        if idempotency_key:
            registry.put_idempotent(idempotency_key, job.job_id)

        position = self._queued_count()
        return {
            "job_id": job.job_id,
            "state": "queued",
            "position": position,
            "isolated": bool(isolated),
            "eta": self._eta_for_job(job),
            "validation": validation,
        }

    def submit_validate(self, body):
        """POST /validate -- run the identical checks as POST /scan, never queue.

        Builds the launch state from widget-free defaults overlaid with any
        inline ``parameters`` patch (:meth:`build_api_launch_state`), then runs
        scan-command + feasibility + budget validation. It reads no widgets, so
        validation is inherently non-mutating. Returns the validation block plus
        ``would_queue`` and ``blockers``. Allowed in read-only mode.
        """
        if not isinstance(body, dict):
            raise ApiError(400, "bad_request", "Request body must be a JSON object")
        patch = body.get("parameters")
        if patch is not None and not isinstance(patch, dict):
            raise ApiError(400, "bad_request", "'parameters' must be a JSON object")
        force = bool(body.get("force", False))
        # Engine selection (docs/CONTROL_FEATURES_DESIGN.md sec 6.4): a
        # deterministic client must be able to dry-run the exact body it will
        # submit -- POST /scan reads these keys, so /validate must too.
        engine, seed, noiseless = parse_scan_engine(body)
        background = parse_scan_background(body)
        return self._bridge.call_on_gui(
            lambda: self._validate_scan_on_gui(
                patch, force, background, engine=engine, seed=seed, noiseless=noiseless,
            )
        )

    @staticmethod
    def _blocking_scan_issues(controller, vals, cmd1, cmd2, force):
        """The scan-command issues that block this request.

        ``force`` is the operator's deliberate override, so it clears exactly
        what the GUI Run button offers as a choice: the soft issues (a very
        long scan). A hard issue -- the command does not describe a scan that
        can run as written: an unknown or refused variable, a malformed
        command -- blocks whatever the caller says, and so does the plan's
        refusal of the pair when the launch compiles (``_compile_launch``). Forcing through one of those ran a scan that
        silently overwrote the radius a crystal pins, or labelled points with
        coordinates they were not taken at (ruling 2026-09-10).
        """
        # API scan commands are always absolute (build_api_launch_state hard-codes
        # relative_mode_1/2 False, unlike the GUI-collected launch state) --
        # relative_1/relative_2 default False here for that reason, not omission.
        # current_values still passes vals' curvature radii through: a future
        # relative API request would need them, and there is no separate
        # "widget-free" reading to diverge from the GUI's.
        current_values = {axis: vals.get(axis) for axis in ("rhm", "rvm", "rha", "rva")}
        hard, soft = controller._scan_command_issues(
            cmd1, cmd2, vals.get("monocris"), vals.get("anacris"), vals.get("modules"),
            current_values=current_values,
        )
        return hard if force else hard + soft

    def _validate_scan_on_gui(self, patch, force, background=None,
                              engine="mcstas", seed=None, noiseless=False):
        """Non-mutating validation body -- runs on the GUI thread via the bridge.

        Builds the launch state from widget-free defaults + the request patch
        (:meth:`build_api_launch_state`), so validation is decoupled from live
        GUI state and cannot mutate it. ``engine``/``seed``/``noiseless`` mirror
        ``_submit_scan_on_gui`` so a dry run reflects exactly the job that
        would run -- ``validate_scan_launch_state`` reads ``launch_state['engine']``
        to decide whether a direct-transmission point is reported infeasible.
        """
        controller = self._controller

        launch_state = controller.build_api_launch_state(patch)
        launch_state["engine"] = engine
        launch_state["seed"] = seed
        launch_state["noiseless"] = bool(noiseless)
        self._apply_background_to_launch_state(controller, launch_state, background)
        vals = launch_state["vals"]
        cmd1 = vals.get("scan_command1", "")
        cmd2 = vals.get("scan_command2", "")

        blockers = []
        background_block, background_blocker = self._background_validation(
            controller, launch_state
        )
        if background_blocker is not None:
            blockers.append(background_blocker)
        scan_issues = self._blocking_scan_issues(controller, vals, cmd1, cmd2, force)
        if scan_issues:
            blockers.append("scan_validation: %s" % "\n".join(scan_issues))

        try:
            points = controller._count_scan_points(cmd1, cmd2)
        except Exception:
            points = 1
        neutrons = float(vals.get("number_neutrons") or 0)

        limits = getattr(controller, "_budget_limits", None)

        # Over-limit guard BEFORE the per-point feasibility expansion in
        # _build_validation (which deep-copies the config and runs the angle
        # solver once per point on the GUI thread). Returning here on the
        # cheap point count keeps an over-limit /validate from monopolizing
        # the single GUI event loop and starving other bridged API calls.
        if limits is not None and points > limits.max_points:
            reason = ("scan has %d points, exceeding the limit of %d"
                      % (points, limits.max_points))
            blockers.append("limit_exceeded: %s" % reason)
            return {
                "requested_points": points,
                "feasible_points": 0,
                "partial": False,
                "planned_feasible_mask": [],
                "feasible_segments": [],
                "point_manifest": [],
                "per_command": [],
                "infeasible": [],
                "cost": dict(
                    self._budget_usage(), requested_points=points,
                    feasible_points=0,
                    neutrons_per_point=neutrons,
                    job_neutrons=0,
                ),
                "eta": {"estimated_seconds": None,
                        "confidence": "none", "samples": 0},
                "background": background_block,
                "would_queue": False,
                "blockers": blockers,
            }

        try:
            controller._compile_launch(launch_state)
            validation = self._build_validation(
                controller, launch_state, points, neutrons
            )
            judged = True
        except PlanRefused as refused:
            # Validation stops at the refusal: no plan, no points to judge. A
            # command issue reported above already says why.
            judged = False
            if not scan_issues:
                blockers.append("scan_validation: %s" % refused)
            validation = {
                "requested_points": points, "feasible_points": 0, "partial": False,
                "planned_feasible_mask": [], "feasible_segments": [],
                "point_manifest": [], "per_command": [], "infeasible": [],
                "cost": dict(self._budget_usage(), requested_points=points,
                             feasible_points=0, neutrons_per_point=neutrons,
                             job_neutrons=0),
                "eta": {"estimated_seconds": None, "confidence": "none", "samples": 0},
            }
        feasible_points = int(validation.get("feasible_points", points))
        if feasible_points <= 0 and judged:
            blockers.append(
                "all_points_infeasible: no requested point is reachable"
            )

        if limits is not None:
            if self._queued_count() >= limits.max_queued:
                blockers.append("limit_exceeded: queue is full")
            reason = limits.check_submission(
                feasible_points, neutrons, self._pending_api_cost()
            )
            if reason is not None:
                blockers.append("limit_exceeded: %s" % reason)

        validation["background"] = background_block
        validation["would_queue"] = not blockers
        validation["blockers"] = blockers
        return validation

    def get_resolution(self, query):
        """GET /resolution -- theoretical TAS resolution at one (h, k, l, energy transfer).

        ``query`` carries optional floats under the canonical IDs ``h``/``k``/``l``/
        ``energy_transfer_mev`` (``None`` -> current GUI value) and a validated ``method`` (``auto`` /
        ``cooper_nathans`` / ``popovici``). Bridged onto the GUI thread like
        :meth:`submit_validate`; a pure read that mutates no state. An infeasible
        geometry returns ``{"ok": false, "reason": ...}`` (the same refusal-string
        vocabulary as /validate) with HTTP 200. Allowed in read-only mode.
        """
        if not isinstance(query, dict):
            raise ApiError(400, "bad_request", "resolution query must be a JSON object")
        return self._bridge.call_on_gui(lambda: self._resolution_on_gui(query))

    def _resolution_on_gui(self, query):
        """GUI-thread body of GET /resolution (read-only; never mutates state).

        A thin query-parsing shell over ``TAVIController.compute_resolution`` --
        the shared computation path the GUI dialog also calls. Omitted
        H/K/L/deltaE (``None``) default to the current GUI values there.
        """
        return self._controller.compute_resolution(
            query.get("h"), query.get("k"), query.get("l"),
            query.get("energy_transfer_mev"), query.get("method") or "auto",
        )

    def get_schema(self):
        """GET /schema -- machine-readable API self-description (read-only)."""
        return self._bridge.call_on_gui(self._controller.build_api_schema)


# Terminal states used by the API stop logic (mirrors scan_jobs terminal set).
_API_TERMINAL_STATES = frozenset(
    {JobState.DONE, JobState.FAILED, JobState.CANCELLED, JobState.STOPPED}
)

# The same terminal set as plain string values (job_state_changed carries the
# JobState.value string, not the enum). Used by the benchmark completion hook.
_JOB_TERMINAL_STATE_VALUES = frozenset(s.value for s in _API_TERMINAL_STATES)


class TAVIController(QObject):
    """Controller class to connect GUI with backend logic."""
    
    # Signals for thread-safe GUI updates
    progress_updated = Signal(int, int)  # current, total
    remaining_time_updated = Signal(str)
    elapsed_time_updated = Signal(str)
    counts_updated = Signal(float, float)  # max_counts, total_counts
    message_printed = Signal(str)
    
    # Signals for real-time display dock updates
    scan_initialized = Signal(str, list, list, str, str, list, list)  # mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d
    scan_point_updated_1d = Signal(int, float)  # index, counts
    scan_point_updated_2d = Signal(int, int, float)  # idx_x, idx_y, counts
    scan_point_invalid_1d = Signal(int)  # index
    scan_point_invalid_2d = Signal(int, int)  # idx_x, idx_y
    scan_current_index_1d = Signal(int)  # current index
    scan_current_index_2d = Signal(int, int)  # idx_x, idx_y
    scan_completed = Signal()  # scan finished
    scan_auto_save = Signal()  # trigger auto-save of plot
    single_point_result = Signal(float, float)  # max_counts, total_counts for single-point scan
    
    # Signals for diagnostic plots (must run on main thread)
    diagnostic_plot_requested = Signal(object)  # McStasData object
    instrument_diagram_requested = Signal(object)  # McStas instrument object
    
    # Signal for runtime data updates (triggers re-estimation of scan times)
    runtime_data_updated = Signal()
    actual_output_folder_updated = Signal(str)
    pre_scan_estimate_updated = Signal(str)

    # Signal for job-queue state transitions (job_id, state value)
    job_state_changed = Signal(str, str)

    # Emitted once every stage of a benchmark plan has reached a terminal state
    # (after the machine speed index has been recomputed and stored). The
    # benchmark dialog refreshes its machine panel + cross-check table on it.
    benchmark_finished = Signal()

    # Remote-API dock feeds (API dock, docs/API_SERVER_DESIGN.md sec 10):
    #   api_activity     -- one activity-log line
    #   api_status_changed -- listening URL (may be "") + human state string
    api_activity = Signal(str)
    api_status_changed = Signal(str, str)
    # Immutable scalar data for the reciprocal dock.  The dock never reads
    # widgets directly, which keeps preview/persisted state separate.
    reciprocal_state_changed = Signal(object)
    reciprocal_live_result = Signal(object)

    def __init__(self, window, instrument, api_overrides=None):
        super().__init__()
        self.window = window
        # CLI overrides for the remote API server (see main()); empty by default.
        self._api_cli_overrides = api_overrides or {}
        self.api_server = None
        # Last SSE-publish error string, so identical consecutive publish
        # failures are logged once instead of spamming the message center.
        self._api_publish_last_error = None
        # Populated by _start_api_server; defaults keep the API backend safe if
        # the server never starts (config load failure / disabled).
        self._api_limits = None
        self._budget_limits = None
        # The active instrument plugin (fixed for the session) and its live state.
        self.instrument = instrument
        self.instrument_state = instrument.default_state()
        self.descriptor = instrument.descriptor()
        self._mcstas_name = self.descriptor.mcstas_name

        # UB matrix for crystal orientation: the operator's belief.
        self.ub_matrix = UBMatrix()
        # The truth apart from it (docs/INSTRUMENT_LAYOUT.md "Truth and
        # belief"): the sample as described (identity = the standard setting,
        # or from the mounting plane), the hidden training rotation, and the
        # loaded training exercise, None or its hash -- the docks only show it.
        self.U_described = np.eye(3)
        self.mount_plane = None
        self.R_hidden = np.eye(3)
        self._exercise = None
        # (code, reason) last reported as blocking the save of parameters.json, so
        # a Run that changes nothing does not say it again.
        self._unsaved_exercise_report = None
        self._set_true_mount()

        # Global variables
        self.stop_event = threading.Event()

        # Scan job queue (API design phase 1): every scan -- GUI or (later) API --
        # runs as a ScanJob through a single persistent worker thread, so runs
        # execute serially instead of racing. See docs/API_SERVER_DESIGN.md sec 7.
        self._job_registry = JobRegistry()
        # Session narrative (parameter changes, job lifecycle, mode/budget events)
        # exposed via GET /api/v1/journal. A Qt-free deque read directly by HTTP
        # handler threads (no GUI-thread hop needed).
        self._journal = SessionJournal()
        self._job_queue = queue.Queue()
        self._active_job = None  # job currently RUNNING in the worker (or None)
        self.last_scan_result = None  # ScanResult from the most recent finished job
        # Single-level undo for goto_scan_variable: {'field', 'old_value',
        # 'variable'} of the last successful goto, or None when there is
        # nothing to revert. Cleared once reverted.
        self._last_goto = None
        # Job ids of the benchmark plan currently in flight (set by
        # run_benchmark, drained by _on_job_state_changed when all are terminal).
        self._benchmark_job_ids = []
        self._benchmark_plan = None
        # MPI count the in-flight benchmark started with (set by run_benchmark).
        self._benchmark_mpi_count = None
        # Adaptive rate-sweep bookkeeping (see _advance_benchmark).
        self._benchmark_adaptive_ncounts = set()
        self._benchmark_finalized = False
        self._shutdown_called = False
        self._job_worker = threading.Thread(
            target=self._job_worker_loop, name="scan-job-worker", daemon=True
        )
        self._job_worker.start()

        self.diagnostic_settings = {}
        self.current_sample_settings = {}
        # Instrument-level background profile (tavi/background.py spec form).
        # Default-off: an unconfigured session plants no background and produces
        # counts identical to a background-free engine. A per-scan override in
        # the launch state replaces this wholesale; it never merges.
        self.background_profile = copy.deepcopy(self.DEFAULT_BACKGROUND_PROFILE)
        # Cross-scan binary reuse (design record §18.5): the last compiled
        # instrument, its execution state, and the build fingerprint it was
        # compiled from. Populated after a scan that actually compiled.
        self._binary_reuse_cache = None
        
        # Flag to prevent recursive updates
        self.updating = False
        # The stage's refusal while the angle fields do not match Q/HKL, else
        # None (_set_angles_stale).
        self._angles_stale = None

        # Track previous field values to detect actual changes (vs spurious editingFinished signals)
        self._previous_values = {}
        
        # Initialize runtime tracker for scan time estimation
        self.runtime_tracker = RuntimeTracker()
        # MPI processes per McStas point (Config menu); frozen into each launch state.
        self.mpi_count = load_mpi_count()

        # Debounce timer for scan command validation and time estimates
        self._scan_update_timer = QTimer()
        self._scan_update_timer.setSingleShot(True)
        self._scan_update_timer.setInterval(300)  # 300ms debounce
        self._scan_update_timer.timeout.connect(self._update_scan_estimates)
        # Several linked controls can settle from one user gesture.  Publish a
        # single authoritative reciprocal snapshot after that burst, never from
        # the 30 Hz live-drag path (which uses reciprocal_live_result instead).
        self._reciprocal_snapshot_timer = QTimer(self)
        self._reciprocal_snapshot_timer.setSingleShot(True)
        self._reciprocal_snapshot_timer.timeout.connect(self.emit_reciprocal_snapshot)
        
        # Initialize crystal info with the descriptor's first mono/ana crystals
        self.monocris_info, self.anacris_info = self.instrument.crystal_info(
            self.descriptor.mono_crystals[0].id, self.descriptor.ana_crystals[0].id
        )
        
        # Initialize output directory
        self.output_directory = os.path.join(os.getcwd(), "output")
        if not os.path.exists(self.output_directory):
            os.makedirs(self.output_directory)
        
        # Connect signals
        self.connect_signals()
        
        # Load parameters
        self.load_parameters()
        
        # Update crystal info based on loaded parameters
        self.update_monocris_info()
        self.update_anacris_info()

        # Update ideal focusing buttons after initial load
        self.update_ideal_bending_buttons()
        
        # Set up visual feedback for all input fields
        self.setup_visual_feedback()
        
        # Trigger initial scan estimate update
        self._update_scan_estimates()
        
        # Print initialization message
        self.print_to_message_center("GUI initialized.")
        self.emit_reciprocal_snapshot()

        # Start the remote API server last, after the message center and job
        # queue are ready (it reports status through print_to_message_center).
        self._start_api_server()

    def _set_api_dock_mode(self, mode):
        """Reflect the effective access mode in the API dock combo (no-op safe)."""
        dock = getattr(self.window, "api_dock", None)
        if dock is not None:
            dock.set_mode_display(mode)

    def _start_api_server(self, mode_override=None):
        """Construct and start the remote API server per config + CLI overrides.

        Called at the end of ``__init__`` so the message center and job queue
        exist. Bind failures are surfaced to the message center and the GUI
        continues without the API. See docs/API_SERVER_DESIGN.md sec 11.
        """
        try:
            cfg = load_api_config()
        except Exception as exc:
            self.print_to_message_center(
                f"API server: could not load config ({exc}); disabled"
            )
            return

        overrides = self._api_cli_overrides or {}
        enabled = bool(cfg.get("enabled", True))
        mode = cfg.get("mode", "allow")
        host = cfg.get("host", "127.0.0.1")
        port = int(cfg.get("port", 8642))
        token = cfg.get("token")
        self._api_limits = cfg.get("limits")

        # Build the enforceable BudgetLimits used by the API submission path
        # (docs/API_SERVER_DESIGN.md sec 7.1). Filter to known fields so an
        # extra key in the user's config cannot raise a TypeError here.
        limits_cfg = self._api_limits if isinstance(self._api_limits, dict) else {}
        known = ("max_queued", "max_points", "max_neutrons_per_point",
                 "queue_neutron_budget")
        self._budget_limits = BudgetLimits(
            **{k: limits_cfg[k] for k in known if k in limits_cfg}
        )

        # CLI overrides win over the config file.
        if overrides.get("disabled"):
            enabled = False
        if overrides.get("port") is not None:
            port = int(overrides["port"])
            enabled = True  # --api-port implies enabled

        # A dock-driven mode change (set_api_mode -> restart) forces a listening
        # mode and enables the server regardless of the persisted enabled flag.
        if mode_override is not None:
            mode = mode_override
            enabled = True

        # 'off' mode (or disabled) means: do not listen at all. TaviApiServer only
        # accepts 'allow'/'readonly', so filter 'off' out before construction.
        if not enabled or mode == "off":
            self.print_to_message_center("API server disabled")
            self._set_api_dock_mode("off")
            self.api_status_changed.emit("", "Off")
            return

        url = f"http://{host}:{port}/api/v1"

        bridge = ApiBridge()  # created on the GUI thread
        self._api_bridge = bridge
        backend = TaviApiBackend(self, bridge)
        try:
            server = TaviApiServer(
                host, port, token, mode, backend, log_callback=self._api_log
            )
        except ValueError as exc:
            self.print_to_message_center(f"API server not started: {exc}")
            self.api_status_changed.emit("", "Failed")
            return

        backend.server = server
        try:
            server.start()
        except OSError as exc:
            self.print_to_message_center(
                f"Warning: API server could not bind {host}:{port} ({exc}); "
                "continuing without remote API"
            )
            self.api_status_changed.emit(url, "Failed")
            return

        self.api_server = server
        self._set_api_dock_mode(mode)
        self.api_status_changed.emit(url, "Listening")
        self.print_to_message_center(
            f"API server listening on {url} (mode: {mode})"
        )
        if host not in ("127.0.0.1", "localhost", "::1"):
            if token:
                self.print_to_message_center(
                    f"Note: API server bound to non-loopback address ({host})."
                )
            else:
                self.print_to_message_center(
                    "SECURITY WARNING: API server is bound to a non-loopback "
                    f"address ({host}) with no bearer token configured; anyone on "
                    "the network can control TAVI. Set a token in "
                    "config/api_config.json."
                )

    def _api_log(self, msg):
        """Forward an API-server log line to the message center.

        Invoked from HTTP request threads and the server's own threads, so it
        must never touch widgets directly. ``message_printed`` is a Qt signal;
        emitting it is thread-safe (Qt delivers it to the GUI-thread slot via a
        queued connection), so this is the safe path off the GUI thread.
        """
        stamp = time.strftime("%H:%M:%S")
        self.message_printed.emit(f"API [{stamp}]: {msg}")
        # Mirror to the API dock's activity log (timestamped, no "API:" prefix).
        self.api_activity.emit(f"[{stamp}] {msg}")

    # ---- API dock support methods ---------------------------------------

    def get_recent_jobs(self, n=20):
        """Return up to ``n`` recent job snapshots (newest first) for the dock.

        Thin wrapper so the dock never touches ``_job_registry`` directly.
        """
        return self._job_registry.recent(n)

    def get_api_budget_usage(self):
        """Return the API budget-usage view (pending neutrons, queue depth).

        Uses the same shared accounting as the ``/state`` endpoint's budget
        block (``tavi.scan_jobs.compute_budget_usage``).
        """
        return compute_budget_usage(self._job_registry, self._budget_limits)

    def cancel_job(self, job_id):
        """Cancel a queued job or stop a running one (API dock Cancel button).

        Mirrors the core of ``TaviApiBackend.stop_job`` without the HTTP error
        envelope: QUEUED -> CANCELLED, RUNNING -> shared stop event, terminal
        states -> no-op. GUI-thread entry; independent of the API server state
        so it works even when the server is off.
        """
        job = self._job_registry.get(job_id)
        if job is None:
            self.print_to_message_center(f"Cancel: unknown job {job_id}")
            return
        with job.lock:
            state = job.state
            if state == JobState.QUEUED:
                job.state = JobState.CANCELLED
                if job.finished_at is None:
                    job.finished_at = time.time()
                job.notify_state_change()
        if state == JobState.QUEUED:
            self.job_state_changed.emit(job_id, JobState.CANCELLED.value)
            self._api_log(f"job {job_id} cancelled from dock")
        elif state == JobState.RUNNING:
            self.stop_event.set()
            self._api_log(f"job {job_id} stop requested from dock")
        # Terminal states: nothing to do.

    def set_api_mode(self, mode):
        """Apply an access mode chosen in the API dock and persist it.

        'off'  -> stop the server if running (connection refused thereafter).
        'allow'/'readonly' -> if the server is stopped/absent, (re)start it with
        this mode; otherwise switch the live mode in place. The chosen mode is
        written back to ``config/api_config.json`` so it survives restart.
        """
        if mode not in ("off", "allow", "readonly"):
            self.print_to_message_center(f"API: ignoring unknown mode '{mode}'")
            return

        if mode == "off":
            if self.api_server is not None:
                self.api_server.stop()
                self.api_server = None
                self._api_log("access mode set to 'off' (server stopped)")
            self.api_status_changed.emit("", "Off")
        else:
            if self.api_server is None:
                # Server not listening -- (re)start it in the requested mode.
                self._start_api_server(mode_override=mode)
            else:
                self.api_server.set_mode(mode)
                url = f"http://{self.api_server.host}:{self.api_server.port}/api/v1"
                self.api_status_changed.emit(url, "Listening")
                self._api_log(f"access mode set to '{mode}'")

        self._journal.record("mode", f"access mode set to '{mode}'")
        self._persist_api_mode(mode)

    def _persist_api_mode(self, mode):
        """Read-modify-write the ``mode`` field of config/api_config.json.

        Preserves any other keys; creates the file (and config dir) if absent.
        Failures are surfaced to the message center, never swallowed silently.
        """
        config_path = str(local_config_path("api_config.json"))
        data = {}
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception as exc:
            self.print_to_message_center(
                f"API: could not read {config_path} to persist mode ({exc})"
            )
        data["mode"] = mode
        # 'off' persists as enabled=False so a restart honors the user's choice;
        # a listening mode re-enables the server on next launch.
        data["enabled"] = mode != "off"
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            self.print_to_message_center(
                f"API: could not persist mode to {config_path} ({exc})"
            )

    def connect_signals(self):
        """Connect all GUI signals to controller methods."""
        # Simulation control buttons (moved to right panel)
        self.window.simulation_dock.run_button.clicked.connect(self.run_simulation_thread)
        self.window.simulation_dock.stop_button.clicked.connect(self.stop_simulation)
        self.window.clear_runtimes_action.triggered.connect(self.clear_runtime_data)

        # Job-queue state transitions are emitted from the worker thread; Qt
        # delivers them to this GUI-thread slot as a queued connection.
        self.job_state_changed.connect(self._on_job_state_changed)

        # Remote-API dock wiring (docs/API_SERVER_DESIGN.md sec 10). The dock
        # drives user actions (mode change, cancel) through the controller ref;
        # controller-to-dock updates all arrive on the GUI thread via signals.
        api_dock = getattr(self.window, "api_dock", None)
        if api_dock is not None:
            api_dock.set_controller(self)
            self.api_activity.connect(api_dock.append_activity)
            self.api_status_changed.connect(api_dock.set_status)
            # Any job transition (from either thread) refreshes the job table
            # and budget readout via the controller's pull helpers.
            self.job_state_changed.connect(api_dock.refresh_jobs)

        # Fitting-dock wiring (docs/CONTROL_FEATURES_DESIGN.md sec 1). The dock
        # reads the scan through display_dock.scan_snapshot() and moves the
        # instrument only through goto_scan_variable/revert_last_goto; the one
        # thing it needs from the controller side is a nudge whenever the busy
        # state changes, so the goto buttons enable/disable with the queue.
        fitting_dock = getattr(self.window, "fitting_dock", None)
        if fitting_dock is not None:
            fitting_dock.set_controller(self)
            self.job_state_changed.connect(fitting_dock.refresh_gating)

        # Parameter actions (File menu)
        self.window.save_parameters_action.triggered.connect(self.save_parameters)
        self.window.load_parameters_action.triggered.connect(
            lambda: self.load_parameters(keep_current_on_refusal=True))
        self.window.load_defaults_action.triggered.connect(self.set_default_parameters)
        
        # Diagnostics button
        self.window.simulation_dock.config_diagnostics_button.clicked.connect(self.configure_diagnostics)

        # Global background gate applies immediately.  Per-source edits are
        # staged in the modal configuration dialog until the user accepts it.
        self.window.simulation_dock.background_enable_check.toggled.connect(
            self._on_background_enabled_toggled
        )
        self.window.simulation_dock.background_config_button.clicked.connect(
            self.configure_background
        )
        self._refresh_background_row()
        
        # Sample configuration button
        self.window.sample_dock.config_sample_button.clicked.connect(self.configure_sample)
        # Optional mounting plane (the sample as described)
        self.window.sample_dock.mount_apply_button.clicked.connect(self.on_apply_mount_plane)
        self.window.sample_dock.mount_clear_button.clicked.connect(self.on_clear_mount_plane)

        # UB Matrix dock
        self.window.ub_matrix_dock.calculate_ub_button.clicked.connect(self.on_calculate_ub)
        self.window.ub_matrix_dock.refine_lattice_button.clicked.connect(self.on_refine_lattice)
        self.window.ub_matrix_dock.reset_ub_button.clicked.connect(self.on_reset_ub)
        self.window.ub_matrix_dock.lock_plane_button.clicked.connect(self.on_lock_plane)
        self.window.ub_matrix_dock.release_plane_button.clicked.connect(self.on_release_plane)
        self.window.ub_matrix_dock.ub_matrix_changed.connect(self.on_ub_matrix_edited)
        self.window.ub_matrix_dock.generate_training_button.clicked.connect(self.on_generate_training)
        self.window.ub_matrix_dock.load_training_button.clicked.connect(self.on_load_training)
        self.window.ub_matrix_dock.clear_training_button.clicked.connect(self.on_clear_training)
        self.window.ub_matrix_dock.check_training_button.clicked.connect(self.on_check_training)
        # Connect peak Take Position and Remove buttons
        self._reconnect_peak_signals()
        self.window.ub_matrix_dock.add_peak_button.clicked.connect(self._on_peak_added)
        
        # Data control buttons
        self.window.data_control_dock.save_browse_button.clicked.connect(
            lambda: self.open_folder_dialog(self.window.data_control_dock.save_folder_edit)
        )
        self.window.data_control_dock.load_browse_button.clicked.connect(
            lambda: self.open_folder_dialog(self.window.data_control_dock.load_folder_edit)
        )
        self.window.data_control_dock.load_data_button.clicked.connect(self.load_and_display_data)
        
        # Connect internal signals to GUI updates
        self.progress_updated.connect(self.update_progress)
        self.remaining_time_updated.connect(self.update_remaining_time)
        self.elapsed_time_updated.connect(self.update_elapsed_time)
        self.counts_updated.connect(self.update_counts_entry)
        self.message_printed.connect(self.window.output_dock.message_text.append)
        
        # Connect display dock signals
        self.scan_initialized.connect(self._on_scan_initialized)
        self.scan_point_updated_1d.connect(self.window.display_dock.update_1d_point)
        self.scan_point_updated_2d.connect(self.window.display_dock.update_2d_point)
        self.scan_point_invalid_1d.connect(self.window.display_dock.mark_1d_point_invalid)
        self.scan_point_invalid_2d.connect(self.window.display_dock.mark_2d_point_invalid)
        self.scan_current_index_1d.connect(self.window.display_dock.set_current_scan_index)
        self.scan_current_index_2d.connect(self.window.display_dock.set_current_scan_index_2d)
        self.scan_completed.connect(self.window.display_dock.scan_complete)
        self.scan_auto_save.connect(self.window.display_dock.auto_save_plot)
        self.single_point_result.connect(self.window.display_dock.show_single_point_result)
        
        # Connect diagnostic plot signals (runs on main thread for matplotlib)
        self.diagnostic_plot_requested.connect(self._show_diagnostic_plots)
        self.instrument_diagram_requested.connect(self._show_instrument_diagram)
        
        # Connect runtime data update signal to refresh scan time estimates
        self.runtime_data_updated.connect(self._update_scan_estimates)
        self.actual_output_folder_updated.connect(self._on_actual_output_folder_updated)
        self.pre_scan_estimate_updated.connect(self.window.simulation_dock.update_pre_scan_estimate)
        
        # Connect crystal selection changes
        self.window.instrument_dock.monocris_combo.currentTextChanged.connect(self.update_monocris_info)
        self.window.instrument_dock.anacris_combo.currentTextChanged.connect(self.update_anacris_info)
        # Which curvature axes are fixed follows the selected crystal, so a
        # scan command that was valid under one crystal can stop being valid
        # under another. The launch path re-validates regardless; this keeps
        # the warning in the dock honest as soon as the selection changes.
        self.window.instrument_dock.monocris_combo.currentTextChanged.connect(
            lambda _text: self.validate_scan_commands())
        self.window.instrument_dock.anacris_combo.currentTextChanged.connect(
            lambda _text: self.validate_scan_commands())

        # Connect NMO selection change to update ideal bending values (instrument-
        # specific coupling; the module widget only exists when declared)
        if getattr(self.window.instrument_dock, "nmo_combo", None) is not None:
            self.window.instrument_dock.nmo_combo.currentTextChanged.connect(self.update_ideal_bending_buttons)

        reciprocal_dock = getattr(self.window, "reciprocal_space_dock", None)
        if reciprocal_dock is not None:
            reciprocal_dock.move_requested.connect(self.apply_reciprocal_move)
            reciprocal_dock.live_move_requested.connect(self.apply_reciprocal_live_move)
            reciprocal_dock.values_requested.connect(self.apply_reciprocal_values)
            reciprocal_dock.plane_requested.connect(self.set_reciprocal_plane)
            self.reciprocal_state_changed.connect(reciprocal_dock.set_snapshot)
            self.reciprocal_live_result.connect(reciprocal_dock.set_live_result)

        # Ideal focusing buttons
        self.window.instrument_dock.rhm_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rhm")
        )
        self.window.instrument_dock.rvm_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rvm")
        )
        self.window.instrument_dock.rha_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rha")
        )
        self.window.instrument_dock.rva_ideal_button.clicked.connect(
            lambda: self.apply_ideal_bending_value("rva")
        )

        # User edits unlock ideal lock
        self.window.instrument_dock.rhm_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rhm")
        )
        self.window.instrument_dock.rvm_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rvm")
        )
        self.window.instrument_dock.rha_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rha")
        )
        self.window.instrument_dock.rva_edit.textEdited.connect(
            lambda: self.unlock_ideal_bending("rva")
        )
        
        # Connect field editing events for linked updates
        # Instrument angles - update energies and Q-space
        self.window.instrument_dock.mtt_edit.editingFinished.connect(self.on_mtt_changed)
        self.window.instrument_dock.att_edit.editingFinished.connect(self.on_att_changed)
        self.window.instrument_dock.stt_edit.editingFinished.connect(self.on_stt_changed)
        self.window.instrument_dock.omega_edit.editingFinished.connect(self.on_omega_changed)
        self.window.instrument_dock.sgl_edit.editingFinished.connect(self.on_arc_changed)
        self.window.instrument_dock.sgu_edit.editingFinished.connect(self.on_arc_changed)
        
        # Energies - update related energies and angles
        self.window.instrument_dock.Ki_edit.editingFinished.connect(self.on_Ki_changed)
        self.window.instrument_dock.Ei_edit.editingFinished.connect(self.on_Ei_changed)
        self.window.instrument_dock.Kf_edit.editingFinished.connect(self.on_Kf_changed)
        self.window.instrument_dock.Ef_edit.editingFinished.connect(self.on_Ef_changed)
        
        # K fixed mode and fixed E - update all related values
        self.window.scattering_dock.K_fixed_combo.currentTextChanged.connect(self.on_K_fixed_changed)
        self.window.scattering_dock.fixed_E_edit.editingFinished.connect(self.on_fixed_E_changed)
        self.window.scattering_dock.K_fixed_combo.currentTextChanged.connect(self.request_reciprocal_snapshot)
        self.window.scattering_dock.fixed_E_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        
        # Q-space - update HKL and angles
        self.window.scattering_dock.qx_edit.editingFinished.connect(self.on_Q_changed)
        self.window.scattering_dock.qy_edit.editingFinished.connect(self.on_Q_changed)
        self.window.scattering_dock.qz_edit.editingFinished.connect(self.on_Q_changed)
        self.window.scattering_dock.qx_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        self.window.scattering_dock.qy_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        self.window.scattering_dock.qz_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        
        # HKL - update Q-space and angles
        self.window.scattering_dock.H_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.scattering_dock.K_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.scattering_dock.L_edit.editingFinished.connect(self.on_HKL_changed)
        self.window.scattering_dock.H_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        self.window.scattering_dock.K_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        self.window.scattering_dock.L_edit.editingFinished.connect(self.request_reciprocal_snapshot)
        
        # DeltaE - update energies
        self.window.scattering_dock.deltaE_edit.editingFinished.connect(self.on_deltaE_changed)
        self.window.scattering_dock.deltaE_edit.editingFinished.connect(self.request_reciprocal_snapshot)

        for field in (
            self.window.instrument_dock.Ki_edit, self.window.instrument_dock.Ei_edit,
            self.window.instrument_dock.Kf_edit, self.window.instrument_dock.Ef_edit,
        ):
            field.editingFinished.connect(self.request_reciprocal_snapshot)
        
        # Lattice parameters - only update via Save button (lock/unlock mechanism)
        # Connect the lattice save signal from the sample dock
        self.window.sample_dock.lattice_parameters_changed.connect(self.on_lattice_changed)
        # Sample selection change -> update the instrument state and show status
        try:
            self.window.sample_dock.sample_combo.currentTextChanged.connect(self.on_sample_changed)
        except Exception:
            pass

        # Refresh centering-rule fallback circles as soon as the sample dock
        # changes its selected space group.
        try:
            self.window.sample_dock.space_group_changed.connect(lambda _group: self.request_reciprocal_snapshot())
            self.window.sample_dock.reflection_source_changed.connect(lambda _enabled: self.request_reciprocal_snapshot())
        except Exception as exc:
            self.print_to_message_center(f"Reciprocal view: space-group refresh unavailable ({exc})")
        
        # Scan command validation - check for conflicts and errors on text change and on focus out
        self.window.simulation_dock.scan_command_1_edit.textChanged.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_2_edit.textChanged.connect(self.validate_scan_commands)
        # Also validate when editing is finished (focus lost) to catch final state
        self.window.simulation_dock.scan_command_1_edit.editingFinished.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_2_edit.editingFinished.connect(self.validate_scan_commands)
        self.window.simulation_dock.scan_command_1_edit.editingFinished.connect(self._trigger_scan_update)
        self.window.simulation_dock.scan_command_2_edit.editingFinished.connect(self._trigger_scan_update)
        
        # Connect scan command and neutron changes to debounced time estimate update
        self.window.simulation_dock.scan_command_1_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.scan_command_2_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.number_neutrons_edit.textChanged.connect(self._trigger_scan_update)
        # Also connect the new mantissa/exponent fields directly for immediate feedback
        self.window.simulation_dock.neutron_mantissa_edit.textChanged.connect(self._trigger_scan_update)
        self.window.simulation_dock.neutron_exponent_edit.textChanged.connect(self._trigger_scan_update)
        # Also update on editingFinished to catch committed changes
        try:
            self.window.simulation_dock.number_neutrons_edit.editingFinished.connect(self._trigger_scan_update)
        except Exception:
            pass
    
    def setup_visual_feedback(self):
        """Set up visual feedback for all input fields to show pending/saved states."""
        # Collect all QLineEdit widgets from all docks
        line_edits = []
        
        # Instrument dock (incl. the descriptor-generated slit edits)
        line_edits.extend(self.window.instrument_dock.line_edits_for_feedback())
        
        # Reciprocal space dock
        line_edits.extend([
            self.window.scattering_dock.qx_edit,
            self.window.scattering_dock.qy_edit,
            self.window.scattering_dock.qz_edit,
            self.window.scattering_dock.H_edit,
            self.window.scattering_dock.K_edit,
            self.window.scattering_dock.L_edit,
            self.window.scattering_dock.deltaE_edit,
        ])
        
        # Scan controls dock
        line_edits.extend([
            self.window.simulation_dock.neutron_mantissa_edit,
            self.window.simulation_dock.neutron_exponent_edit,
            self.window.scattering_dock.fixed_E_edit,
            self.window.simulation_dock.scan_command_1_edit,
            self.window.simulation_dock.scan_command_2_edit,
        ])
        self._feedback_line_edits = line_edits
        
        # Apply visual feedback to all line edits
        for line_edit in line_edits:
            self._setup_field_feedback(line_edit)
    
    def _setup_field_feedback(self, line_edit):
        """Set up visual feedback for a single QLineEdit widget."""
        # Store original value and style
        line_edit.setProperty("original_value", line_edit.text())
        line_edit.setProperty("original_style", line_edit.styleSheet())

        # A refused scan box keeps its error border: the pending and saved
        # flashes below would otherwise overwrite it.
        def refused():
            return line_edit.styleSheet() == self.window.simulation_dock.STYLE_WARNING

        # Connect to textChanged to show pending state
        def on_text_changed():
            if self.updating:
                # A controller transaction owns this text change.  Its caller
                # will make the new value the feedback baseline once the
                # calculation has completed; it is never a pending user edit.
                line_edit.setProperty("programmatic_change", True)
                return
            original = line_edit.property("original_value")
            current = line_edit.text()
            if current != original and not refused():
                # Show pending state with orange border
                line_edit.setStyleSheet("QLineEdit { border: 2px solid #FF8C00; }")
        
        line_edit.textChanged.connect(on_text_changed)
        
        # Connect to editingFinished to show saved state and flash
        original_finished_handler = None
        
        def on_editing_finished():
            if refused():
                return
            original = line_edit.property("original_value")
            current = line_edit.text()
            
            if current != original:
                # Flash with bold dark border to show changes were saved
                line_edit.setStyleSheet("QLineEdit { border: 3px solid #000000; }")
                
                # Update stored original value
                line_edit.setProperty("original_value", current)
                
                # After 300ms, return to normal state
                QTimer.singleShot(300, line_edit, lambda: line_edit.setStyleSheet(line_edit.property("original_style") or ""))
            else:
                # No changes, just return to normal
                line_edit.setStyleSheet(line_edit.property("original_style") or "")
        
        # We need to ensure editingFinished fires AFTER the field update handlers
        # So we'll connect with a slight delay
        def delayed_on_editing_finished():
            QTimer.singleShot(10, line_edit, on_editing_finished)
        
        line_edit.editingFinished.connect(delayed_on_editing_finished)

    def _commit_programmatic_feedback(self, line_edits=None, flash=False):
        """Make controller-written edits visibly committed, never pending.

        ``textChanged`` deliberately cannot tell a user edit from a
        ``setText`` call.  Controller transactions mark the latter while
        ``updating`` is true; this is the single place that advances the
        visual-feedback baseline afterwards.  Passing explicit edits supports
        direct API/goto writes, while the default consumes derived changes
        accumulated by an after-handler.
        """
        if line_edits is None:
            line_edits = getattr(self, "_feedback_line_edits", ())
            line_edits = [
                edit for edit in line_edits
                if edit.property("programmatic_change")
            ]
        for line_edit in line_edits:
            line_edit.setProperty("original_value", line_edit.text())
            line_edit.setProperty("programmatic_change", False)
            if flash:
                self._flash_field_saved(line_edit)
            else:
                line_edit.setStyleSheet(line_edit.property("original_style") or "")
    
    def open_folder_dialog(self, line_edit):
        """Open file dialog to select a folder."""
        default_folder = os.getcwd()
        folder_selected = QFileDialog.getExistingDirectory(
            self.window, "Select Folder", default_folder
        )
        if folder_selected:
            line_edit.setText(folder_selected)
    
    def print_to_message_center(self, message):
        """Print message to the GUI message center."""
        self.message_printed.emit(message)
        print(message)  # Also print to console

    def request_reciprocal_snapshot(self, *_args):
        """Coalesce ordinary widget-originated reciprocal refreshes."""
        # A lattice/UB transaction calls this while ``updating`` is true.  The
        # single-shot runs after that transaction unwinds, so never discard it.
        self._reciprocal_snapshot_timer.start(0)

    def _reciprocal_reach_overlay(self, vals):
        """Build descriptor-only crystal/axis reach metadata for the canvas."""
        try:
            mono = next(spec for spec in self.descriptor.mono_crystals if spec.id == vals["monocris"])
            ana = next(spec for spec in self.descriptor.ana_crystals if spec.id == vals["anacris"])
            def mechanical_radius(crystal, axis_name, current_angle):
                axis = self.descriptor.axis_limits.get(axis_name)
                if axis is None:
                    return None
                bound = axis.upper if current_angle >= 0 else abs(axis.lower)
                theta = min(math.pi / 2, math.radians(abs(bound) / 2))
                if theta <= 1e-9:
                    return None
                return math.pi / crystal.d_spacing / math.sin(theta)
            return ReachOverlay(
                math.pi / mono.d_spacing, math.pi / ana.d_spacing,
                mechanical_radius(mono, "A1", vals["mtt"]),
                mechanical_radius(ana, "A4", vals["att"]),
            )
        except Exception as exc:
            self.print_to_message_center(f"Reciprocal view: reach overlay unavailable ({exc})")
            return None

    def emit_reciprocal_snapshot(self, advisory_result=None):
        """Publish the scalar state consumed by the reciprocal dock.

        This deliberately copies values out of widgets on the GUI thread.  The
        dock may paint repeatedly, but never needs to reach back into widgets.
        """
        try:
            if advisory_result is None:
                self._set_reciprocal_advisory_style(True)
            vals = self.get_gui_values()
            if not vals:
                return
            fixed_e = float(vals["fixed_E"])
            delta_e = float(vals["deltaE"])
            if vals["K_fixed"] == "Ki Fixed":
                ki, kf = energy2k(fixed_e), energy2k(fixed_e - delta_e)
            else:
                kf, ki = energy2k(fixed_e), energy2k(fixed_e + delta_e)
            plane = get_scattering_plane_info(self.ub_matrix.U, self.ub_matrix.B)
            u_hkl, v_hkl = plane["in_plane_vector1_hkl"], plane["in_plane_vector2_hkl"]
            # User-selected view plane is deliberately controller-local: it
            # projects through UB but never writes/remounts UB.
            u_hkl, v_hkl = getattr(self, "_reciprocal_plane_hkl", (u_hkl, v_hkl))
            u_hkl = primitive_miller(*u_hkl)
            v_hkl = primitive_miller(*v_hkl)
            uq = self._hkl_to_sample_q(*u_hkl, vals); vq = self._hkl_to_sample_q(*v_hkl, vals)
            snapshot = {
                "ki": float(ki), "kf": float(kf),
                "qx": float(vals["qx"]), "qy": float(vals["qy"]), "qz": float(vals["qz"]),
                "p2": getattr(self, "_reciprocal_p2", None),
                "basis_u": (float(uq[0]), float(uq[1])), "basis_v": (float(vq[0]), float(vq[1])),
                "plane_u_hkl": u_hkl, "plane_v_hkl": v_hkl,
                "K_fixed": vals["K_fixed"],
                "sense": getattr(self, "_reciprocal_sense", 1),
                "reach_overlay": self._reciprocal_reach_overlay(vals),
            }
            if advisory_result is not None:
                snapshot["reciprocal_advisory"] = advisory_result
            self.reciprocal_state_changed.emit(snapshot)
            self.refresh_reciprocal_reflections(vals)
        except Exception as exc:
            self.print_to_message_center(f"Reciprocal view: could not refresh state ({exc})")

    @Slot(object, object)
    def set_reciprocal_plane(self, u_hkl, v_hkl):
        """Set display-only HKL plane axes after validating their UB projection."""
        try:
            u_hkl = primitive_miller(*u_hkl)
            v_hkl = primitive_miller(*v_hkl)
            vals = self.get_gui_values()
            u_q, v_q = self._hkl_to_sample_q(*u_hkl, vals), self._hkl_to_sample_q(*v_hkl, vals)
            # The v1 canvas is the existing horizontal qx/qy projection.  Do
            # not silently flatten arbitrary 3-D planes: that would make grid
            # snapping lie about HKL.  A later 3-D projection can lift this.
            if abs(u_q[2]) > 1e-7 * max(1.0, math.hypot(u_q[0], u_q[1])) or abs(v_q[2]) > 1e-7 * max(1.0, math.hypot(v_q[0], v_q[1])):
                raise ValueError("U/V must lie in the current horizontal display plane")
            if math.hypot(u_q[0], u_q[1]) < 1e-8 or math.hypot(v_q[0], v_q[1]) < 1e-8:
                raise ValueError("U/V must have an in-plane component")
            if abs(u_q[0]*v_q[1]-u_q[1]*v_q[0]) < 1e-8:
                raise ValueError("U and V are collinear in the displayed plane")
            self._reciprocal_plane_hkl = (tuple(u_hkl), tuple(v_hkl))
            self.emit_reciprocal_snapshot()
            dock = getattr(self.window, "reciprocal_space_dock", None)
            if dock is not None:
                dock.set_plane_status("Display plane updated (view only)")
        except Exception as exc:
            message = f"Display plane rejected: {exc}"
            self.print_to_message_center(f"Reciprocal view: invalid display plane ({exc})")
            dock = getattr(self.window, "reciprocal_space_dock", None)
            if dock is not None:
                dock.set_plane_status(message)

    def refresh_reciprocal_reflections(self, vals=None):
        """Project table reflections or an explicitly labelled centering fallback."""
        dock = getattr(self.window, "reciprocal_space_dock", None)
        if dock is None:
            return
        vals = vals or self.get_gui_values()
        if not vals:
            return
        try:
            key = self.window.sample_dock.get_selected_sample_key()
            spec = next((sample for sample in self.descriptor.samples if sample.id == key), None)
            projected = []
            source = getattr(spec, "reflection_source", None) if spec else None
            use_table = bool(getattr(self.window.sample_dock, "use_sample_reflection_table_check", None)
                             and self.window.sample_dock.use_sample_reflection_table_check.isChecked())
            if use_table and source:
                try:
                    for reflection in load_reflections(os.path.join(os.getcwd(), "components", source)):
                        qx, qy, qz = self._hkl_to_sample_q(reflection.h, reflection.k, reflection.l, vals)
                        projected.append(ProjectedReflection(qx, qy, reflection.f_squared, f"({reflection.h:g},{reflection.k:g},{reflection.l:g})", qz))
                    if projected:
                        dock.set_provenance(f"{len(projected)} sample structure-factor reflections ({source})")
                    else:
                        raise ValueError("reflection table contains no usable rows")
                except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
                    issue = (source, str(exc))
                    if getattr(self, "_reflection_table_issue", None) != issue:
                        self._reflection_table_issue = issue
                        self.print_to_message_center(
                            f"Reciprocal view: reflection table '{source}' unavailable ({exc}); "
                            "using selected space-group centering rule"
                        )
            if not projected:
                try:
                    group = get_space_group(int(self.window.sample_dock.spacegroup_combo.currentData()))
                    centering = group.centering
                    group_label = f"selected space group {group.number} ({group.short_name}), {centering}-centering rule"
                except Exception:
                    centering = "P"
                    group_label = "selected space group unavailable, P-centering rule"
                for h, k, l in generate_allowed_reflections(centering, 4, 4, 4):
                    qx, qy, qz = self._hkl_to_sample_q(h, k, l, vals)
                    projected.append(ProjectedReflection(qx, qy, None, f"({h},{k},{l})", qz))
                dock.set_provenance(f"{group_label} (centering-only; not full structure-factor filtering)")
            displayed = plane_filtered_unique(projected, 0.0)
            dock.canvas.set_reflections(displayed)
        except Exception as exc:
            self.print_to_message_center(f"Reciprocal view: could not refresh reflections ({exc})")

    @Slot(object)
    def apply_reciprocal_move(self, state):
        """Flush a released drag and publish one ordinary authoritative snapshot."""
        result = self._apply_reciprocal_state(state)
        self.reciprocal_live_result.emit(result)
        # The release is the one point that deliberately replaces the local
        # preview.  Live acknowledgements use the separate signal above.
        self.emit_reciprocal_snapshot(result)

    @Slot(object)
    def apply_reciprocal_live_move(self, state):
        """Apply a coalesced drag preview without sending a cancelling snapshot."""
        result = self._apply_reciprocal_state(state)
        self.reciprocal_live_result.emit(result)

    def _reciprocal_advisory(self, candidate_vals, state, delta_e):
        """Run the existing feasibility check as advisory-only live feedback."""
        try:
            sample_key = self.window.sample_dock.get_selected_sample_key()
            config = self.instrument.scan_config(
                self.instrument_state, candidate_vals, sample_key,
                self.diagnostic_settings, self._build_sample_mount(candidate_vals),
            )
            context = context_from_state(config, candidate_vals, self.instrument.capabilities())
            point = {**{qid: candidate_vals[_to_internal(qid)] for qid in Q_IDS}, DE: delta_e}
            check = self.instrument.check_point_feasibility(
                config, point_plan(context, Q_CALC), point)
            return bool(check.feasible), check.reason
        except Exception as exc:
            return None, f"feasibility check unavailable ({exc})"

    def _set_reciprocal_advisory_style(self, feasible):
        """Colour canonical fields without changing their values or feedback state."""
        colour = {False: "#c1121f", None: "#d97706"}.get(feasible)
        style = f"QLineEdit {{ border: 2px solid {colour}; }}" if colour else ""
        for field in (
            self.window.scattering_dock.fixed_E_edit,
            self.window.scattering_dock.deltaE_edit,
            self.window.scattering_dock.qx_edit,
            self.window.scattering_dock.qy_edit,
            self.window.scattering_dock.H_edit,
            self.window.scattering_dock.K_edit,
            self.window.scattering_dock.L_edit,
        ):
            field.setStyleSheet(style)
        for field in (
            self.window.instrument_dock.mtt_edit, self.window.instrument_dock.stt_edit,
            self.window.instrument_dock.omega_edit, self.window.instrument_dock.sgl_edit,
            self.window.instrument_dock.sgu_edit, self.window.instrument_dock.att_edit,
        ):
            field.setStyleSheet(style)

    def _apply_reciprocal_state(self, state):
        """Atomically apply a live triangle state; infeasibility is not rejection."""
        if self.updating:
            return LiveReciprocalResult(state, None, "controller is updating", applied=False)
        vals = self.get_gui_values()
        if not vals:
            return LiveReciprocalResult(state, None, "no reciprocal values available", applied=False)
        previous = {
            name: field.text() for name, field in (
                ("fixed_E", self.window.scattering_dock.fixed_E_edit),
                ("deltaE", self.window.scattering_dock.deltaE_edit),
                ("qx", self.window.scattering_dock.qx_edit),
                ("qy", self.window.scattering_dock.qy_edit),
                ("H", self.window.scattering_dock.H_edit),
                ("K", self.window.scattering_dock.K_edit),
                ("L", self.window.scattering_dock.L_edit),
            )
        }
        previous_tracked = {name: self._previous_values.get(name) for name in previous}
        previous_p2 = getattr(self, "_reciprocal_p2", None)
        previous_sense = getattr(self, "_reciprocal_sense", 1)
        previous_styles = {
            field: field.styleSheet() for field in (
                self.window.scattering_dock.fixed_E_edit,
                self.window.scattering_dock.deltaE_edit,
                self.window.scattering_dock.qx_edit,
                self.window.scattering_dock.qy_edit,
                self.window.scattering_dock.H_edit,
                self.window.scattering_dock.K_edit,
                self.window.scattering_dock.L_edit,
                self.window.instrument_dock.mtt_edit,
                self.window.instrument_dock.stt_edit,
                self.window.instrument_dock.omega_edit,
                self.window.instrument_dock.sgl_edit,
                self.window.instrument_dock.sgu_edit,
                self.window.instrument_dock.att_edit,
            )
        }
        try:
            # qz belongs to the physical point but an in-plane drag has no
            # authority to rewrite its widget.  Preserve the canonical text.
            qz = float(vals["qz"])
            delta_e = k2energy(state.ki) - k2energy(state.kf)
            fixed_e = k2energy(state.ki if vals["K_fixed"] == "Ki Fixed" else state.kf)
            qx = float(format_editable_number(state.qx))
            qy = float(format_editable_number(state.qy))
            fixed_e = float(format_editable_number(fixed_e))
            delta_e = float(format_editable_number(delta_e))
            h, k, l = self._sample_q_to_hkl(qx, qy, qz, vals)
            h, k, l = (float(format_editable_number(value)) for value in (h, k, l))
            candidate_vals = dict(vals, fixed_E=fixed_e, deltaE=delta_e, qx=qx, qy=qy, qz=qz,
                                  H=h, K=k, L=l)
            canonical = ReciprocalState(
                energy2k(fixed_e if vals["K_fixed"] == "Ki Fixed" else fixed_e + delta_e),
                energy2k(fixed_e - delta_e if vals["K_fixed"] == "Ki Fixed" else fixed_e),
                qx, qy, qz, state.p2x, state.p2y, state.basis_u, state.basis_v, state.sense,
            )
            feasible, reason = self._reciprocal_advisory(candidate_vals, canonical, delta_e)
            fields = (
                ("fixed_E", self.window.scattering_dock.fixed_E_edit, fixed_e),
                ("deltaE", self.window.scattering_dock.deltaE_edit, delta_e),
                ("qx", self.window.scattering_dock.qx_edit, qx),
                ("qy", self.window.scattering_dock.qy_edit, qy),
                ("H", self.window.scattering_dock.H_edit, h),
                ("K", self.window.scattering_dock.K_edit, k),
                ("L", self.window.scattering_dock.L_edit, l),
            )
            self.updating = True
            for name, field, value in fields:
                text = format_editable_number(value)
                field.setText(text)
                self._update_tracked_value(name, value, displayed_text=text)
            self._reciprocal_p2 = (canonical.p2x, canonical.p2y)
            self._reciprocal_sense = canonical.sense
            self._set_reciprocal_advisory_style(feasible)
        except Exception as exc:
            self.updating = True
            for name, field in (
                ("fixed_E", self.window.scattering_dock.fixed_E_edit),
                ("deltaE", self.window.scattering_dock.deltaE_edit),
                ("qx", self.window.scattering_dock.qx_edit),
                ("qy", self.window.scattering_dock.qy_edit),
                ("H", self.window.scattering_dock.H_edit),
                ("K", self.window.scattering_dock.K_edit),
                ("L", self.window.scattering_dock.L_edit),
            ):
                field.setText(previous[name])
                if previous_tracked[name] is None:
                    self._previous_values.pop(name, None)
                else:
                    self._previous_values[name] = previous_tracked[name]
            self._reciprocal_p2 = previous_p2
            self._reciprocal_sense = previous_sense
            for field, style in previous_styles.items():
                field.setStyleSheet(style)
            self.updating = False
            return LiveReciprocalResult(state, None, f"reciprocal update rolled back ({exc})", applied=False)
        finally:
            self.updating = False
        # Linked energy controls should follow the canonical widgets for every
        # retained point.  An infeasible/unknown point deliberately leaves
        # angle widgets stale; only a feasible check asks for a new solve.
        self.update_all_variables()
        if feasible:
            self.update_angles_from_q()
        return LiveReciprocalResult(canonical, feasible, reason)

    @Slot(object)
    def apply_reciprocal_values(self, values):
        """Apply dock numeric energy controls through the canonical fixed mode."""
        try:
            vals = self.get_gui_values()
            if not vals:
                return
            state = self.window.reciprocal_space_dock.canvas.model.committed
            ki = max(0.0, float(values.get("ki", state.ki)))
            kf = max(0.0, float(values.get("kf", state.kf)))
            # Ei/Ef are first-class dock edits too.  A changed energy field
            # overrides its displayed k partner for this commit.
            if abs(float(values.get("ei", k2energy(ki))) - k2energy(state.ki)) > 1e-8:
                ki = energy2k(float(values["ei"]))
            if abs(float(values.get("ef", k2energy(kf))) - k2energy(state.kf)) > 1e-8:
                kf = energy2k(float(values["ef"]))
            # Delta-E is independently editable in the dock.  Preserve the
            # current fixed side while deriving the other side through the same
            # energy conversion used by the canonical controller path.
            requested_de = float(values.get("delta_e", state.delta_e))
            if abs(requested_de - state.delta_e) > 1e-8:
                if vals["K_fixed"] == "Ki Fixed":
                    kf = energy2k(k2energy(ki) - requested_de)
                else:
                    ki = energy2k(k2energy(kf) + requested_de)
            requested_q = max(0.0, float(values.get("q", state.q)))
            q_direction = (state.qx / state.q, state.qy / state.q) if state.q > 1e-9 else (1.0, 0.0)
            if not math.isfinite(ki) or not math.isfinite(kf) or ki <= 0 or kf <= 0:
                raise ValueError("ki and kf must be positive")
            if not triangle_can_close(ki, kf, requested_q):
                raise ValueError(
                    f"|Q| must be between {abs(ki-kf):.4g} and {ki+kf:.4g} Å⁻¹ "
                    "for the selected ki and kf"
                )
            self.apply_reciprocal_move(type(state)(ki, kf, requested_q * q_direction[0],
                                                   requested_q * q_direction[1], state.qz,
                                                   state.p2x, state.p2y, state.basis_u,
                                                   state.basis_v, state.sense))
        except Exception as exc:
            self.print_to_message_center(f"Reciprocal energy edit rejected: {exc}")
            self.emit_reciprocal_snapshot()
    
    @Slot(int, int)
    def update_progress(self, current, total):
        """Update progress bar."""
        percentage = int(current * 100 / total) if total > 0 else 0
        self.window.simulation_dock.progress_bar.setValue(percentage)
        self.window.simulation_dock.progress_label.setText(f"{percentage}% ({current}/{total})")
    
    @Slot(str)
    def update_remaining_time(self, remaining_time):
        """Update remaining time label."""
        self.window.simulation_dock.remaining_time_label.setText(f"Estimated Remaining Time: {remaining_time}")

    @Slot(str)
    def update_elapsed_time(self, elapsed_time_str):
        """Update elapsed time label in the UI."""
        # Use the dock helper if available
        try:
            self.window.simulation_dock.update_elapsed_time(elapsed_time_str)
        except Exception:
            # Fallback: set label directly
            try:
                self.window.simulation_dock.elapsed_time_label.setText(f"Elapsed Time: {elapsed_time_str}")
            except Exception:
                pass
    
    @Slot(float, float)
    def update_counts_entry(self, max_counts, total_counts):
        """Update counts display."""
        self.window.simulation_dock.max_counts_label.setText(str(int(max_counts)))
        self.window.simulation_dock.total_counts_label.setText(str(int(total_counts)))
    
    @Slot(str, list, list, str, str, list, list)
    def _on_scan_initialized(self, mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d):
        """Handle scan initialization signal and forward to display dock."""
        if mode == '1D':
            self.window.display_dock.initialize_scan(mode, values1, valid_mask1, var1)
        else:
            self.window.display_dock.initialize_scan(mode, values1, valid_mask1, var1, var2, values2, valid_mask_2d)

    @Slot(str)
    def _on_actual_output_folder_updated(self, folder):
        """Update the resolved output folder on the main thread."""
        self.window.data_control_dock.actual_folder_label.setText(folder)
        self.window.display_dock.set_data_folder(folder)
    
    @Slot(object)
    def _show_diagnostic_plots(self, data):
        """Display diagnostic monitor plots on the main thread.
        
        This slot is called from the simulation thread via signal to ensure
        matplotlib GUI runs on the main thread.
        """
        if data is None or data is math.nan:
            self.print_to_message_center("No diagnostic data to display")
            return
        try:
            self.print_to_message_center("Displaying diagnostic monitor plots...")
            ms.make_sub_plot(data, log=False)
        except Exception as e:
            self.print_to_message_center(f"Could not display diagnostic plots: {e}")
    
    @Slot(object)
    def _show_instrument_diagram(self, instrument):
        """Display instrument diagram on the main thread.
        
        This slot is called from the simulation thread via signal to ensure
        matplotlib GUI runs on the main thread.
        """
        if instrument is None:
            return
        
        try:
            self.print_to_message_center("Displaying instrument diagram...")
            instrument.show_diagram()
        except Exception as e:
            self.print_to_message_center(f"Could not display instrument diagram: {e}")
    
    def _build_scan_metadata(self, vals):
        """Build display metadata from a frozen values snapshot."""
        metadata = {}
        
        # Number of neutrons
        metadata['number_neutrons'] = vals.get('number_neutrons', 1000000)
        
        # Ki/Kf fixed mode
        metadata['K_fixed'] = vals.get('K_fixed', 'Ki Fixed')
        
        # Fixed E
        metadata['fixed_E'] = vals.get('fixed_E', 0)
        
        # Collimations (descriptor-driven container: str or set[str] per slot)
        collimation = vals.get('collimation', {})
        for slot in self.descriptor.collimation:
            value = collimation.get(slot.id)
            if slot.multi_select:
                selected = [v for v in slot.allowed if v in (value or ())]
                metadata[slot.id] = (
                    "+".join(f"{v}'" for v in selected) if selected else "open"
                )
            else:
                metadata[slot.id] = value if value is not None else 'open'
        
        # Crystals
        metadata['monocris'] = vals.get('monocris', self.descriptor.mono_crystals[0].id)
        metadata['anacris'] = vals.get('anacris', self.descriptor.ana_crystals[0].id)
        
        # Q-space coordinates
        metadata['qx'] = vals.get('qx', 0)
        metadata['qy'] = vals.get('qy', 0)
        metadata['qz'] = vals.get('qz', 0)
        
        # HKL coordinates
        metadata['H'] = vals.get('H', 0)
        metadata['K'] = vals.get('K', 0)
        metadata['L'] = vals.get('L', 0)
        
        # Energy transfer
        metadata['deltaE'] = vals.get('deltaE', 0)
        
        # Optional modules (legacy display keys kept for the display dock)
        modules = vals.get('modules', {})
        metadata['NMO_installed'] = modules.get('nmo', 'None')
        metadata['V_selector_installed'] = modules.get('v_selector', False)

        return metadata

    def _build_current_scan_metadata(self):
        """Build scan metadata from current GUI values."""
        vals = self.get_gui_values()
        if not vals:
            return {}

        return self._build_scan_metadata(vals)

    def _write_stage_timing_summary(self, data_folder, stage_summary):
        """Persist per-run stage timing data under the scan output folder."""
        summary_path = os.path.join(data_folder, "stage_timing_summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(stage_summary, handle, indent=2)
        return summary_path
    
    def get_gui_values(self):
        """Helper to get all GUI values as a dict."""
        try:
            mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            att = float(self.window.instrument_dock.att_edit.text() or 0)
            monocris = self.window.instrument_dock.selected_mono_id()
            anacris = self.window.instrument_dock.selected_ana_id()
            modules = self.window.instrument_dock.module_values()
            vals = {
                'mtt': mtt,
                'stt': float(self.window.instrument_dock.stt_edit.text() or 0),
                'omega': float(self.window.instrument_dock.omega_edit.text() or 0),
                'sgl': float(self.window.instrument_dock.sgl_edit.text() or 0),
                'sgu': float(self.window.instrument_dock.sgu_edit.text() or 0),
                'att': att,
                'Ki': float(self.window.instrument_dock.Ki_edit.text() or 0),
                'Ei': float(self.window.instrument_dock.Ei_edit.text() or 0),
                'Kf': float(self.window.instrument_dock.Kf_edit.text() or 0),
                'Ef': float(self.window.instrument_dock.Ef_edit.text() or 0),
                'K_fixed': self.window.scattering_dock.K_fixed_combo.currentText(),
                'fixed_E': float(self.window.scattering_dock.fixed_E_edit.text() or 0),
                'qx': float(self.window.scattering_dock.qx_edit.text() or 0),
                'qy': float(self.window.scattering_dock.qy_edit.text() or 0),
                'qz': float(self.window.scattering_dock.qz_edit.text() or 0),
                'H': float(self.window.scattering_dock.H_edit.text() or 0),
                'K': float(self.window.scattering_dock.K_edit.text() or 0),
                'L': float(self.window.scattering_dock.L_edit.text() or 0),
                'deltaE': float(self.window.scattering_dock.deltaE_edit.text() or 0),
                'lattice_a': float(self.window.sample_dock.lattice_a_edit.text() or 1),
                'lattice_b': float(self.window.sample_dock.lattice_b_edit.text() or 1),
                'lattice_c': float(self.window.sample_dock.lattice_c_edit.text() or 1),
                'lattice_alpha': float(self.window.sample_dock.lattice_alpha_edit.text() or 90),
                'lattice_beta': float(self.window.sample_dock.lattice_beta_edit.text() or 90),
                'lattice_gamma': float(self.window.sample_dock.lattice_gamma_edit.text() or 90),
                # Selected sample as its library id; the "no sample" entry maps
                # to key None internally but surfaces to the API as "none" so it
                # round-trips through apply_parameters/isolation restore.
                'sample': self.window.sample_dock.get_selected_sample_key() or "none",
                # Read-only: the described mount's plane (null = not from a plane).
                **self._mount_plane_fields(),
                'monocris': monocris,
                'anacris': anacris,
                'rhm': float(self.window.instrument_dock.rhm_edit.text() or 0),
                'rvm': float(self.window.instrument_dock.rvm_edit.text() or 0),
                'rha': float(self.window.instrument_dock.rha_edit.text() or 0),
                'rva': float(self.window.instrument_dock.rva_edit.text() or 0),
                # Per-axis curvature policy for the scan about to run: the
                # Ideal lock already tracked per field (locked = follow the
                # optics, unlocked = the operator's own number). A fixed
                # axis's mode is irrelevant -- set_crystal_bending pins it to
                # the declared radius regardless -- so rva follows its lock
                # exactly like its siblings rather than being special-cased.
                'curvature_modes': {
                    'rhm': CurvatureMode.AUTOFOCUS if self.is_bending_locked('rhm')
                           else CurvatureMode.HELD,
                    'rvm': CurvatureMode.AUTOFOCUS if self.is_bending_locked('rvm')
                           else CurvatureMode.HELD,
                    'rha': CurvatureMode.AUTOFOCUS if self.is_bending_locked('rha')
                           else CurvatureMode.HELD,
                    'rva': CurvatureMode.AUTOFOCUS if self.is_bending_locked('rva')
                           else CurvatureMode.HELD,
                },
                'source_type': self.window.instrument_dock.selected_source_id(),
                'source_dE': float(self.window.instrument_dock.source_dE_edit.text() or 2),
                # Descriptor-driven categories (the plugin's scan_config owns the
                # mapping from these containers to its instrument state fields).
                'modules': modules,
                'collimation': self.window.instrument_dock.collimation_values(),
                'slits_mm': self.window.instrument_dock.slit_values_mm(),
                'number_neutrons': self.window.simulation_dock.get_number_neutrons(),
                'scan_command1': self.window.simulation_dock.scan_command_1_edit.text(),
                'scan_command2': self.window.simulation_dock.scan_command_2_edit.text(),
                'diagnostic_mode': self.window.simulation_dock.diagnostic_mode_check.isChecked(),
            }
        except ValueError:
            return None
        # The plane lock (orientation_mode, lock_plane). Its stale mark is not
        # a GUI value: only /state and the UB dock read lock_stale().
        vals.update(self._lock_fields())
        return vals

    def public_values(self, vals):
        """An internal parameter dict under canonical IDs (what the API and job results show)."""
        return _public_values(vals, self.descriptor.slits)

    def output_parameters(self, params):
        """A point's or scan's parameters as scan_parameters.txt records them: canonical IDs only."""
        return self.public_values(params)

    def point_output_parameters(self, vals, metadata, scan_index, number_neutrons):
        """One scan point's scan_parameters.txt: the launch values overlaid by the point's own
        (``public_values`` puts requested radii under their IDs, applied under applied_*)."""
        return self.output_parameters({**vals, **metadata, 'scan_index': scan_index,
                                       'number_neutrons': number_neutrons})

    def api_parameters(self):
        """GET /parameters: the GUI values under canonical IDs, or None when a field will not parse."""
        vals = self.get_gui_values()
        return None if vals is None else self.public_values(vals)

    def _build_sample_mount(self, vals):
        """Build the current component-agnostic sample mount from GUI lattice + UB."""
        local_ub_matrix = copy.deepcopy(self.ub_matrix)
        local_ub_matrix.set_lattice(
            vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
            vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
        )
        return SampleMount.from_lattice_tas(
            vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
            vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
            R_mount=local_ub_matrix.U,
        )

    def _hkl_to_sample_q(self, H, K, L, vals):
        """Convert HKL to public instrument/GUI Q using the current sample mount."""
        q_component = self._build_sample_mount(vals).hkl_to_q(H, K, L)
        q = component_q_to_instrument_q(q_component)
        return float(q[0]), float(q[1]), float(q[2])

    def _sample_q_to_hkl(self, qx, qy, qz, vals):
        """Convert public instrument/GUI Q to HKL using the current sample mount."""
        q_component = instrument_q_to_component_q([qx, qy, qz])
        return self._build_sample_mount(vals).q_to_hkl(*q_component)

    def compute_resolution(self, H=None, K=None, L=None, deltaE=None, method="auto"):
        """Theoretical TAS resolution at one (H, K, L, deltaE).

        The single computation path shared by the GET /resolution backend and the
        Utilities -> Resolution calculator dialog. Each of ``H``/``K``/``L``/
        ``deltaE`` may be ``None`` -> use the current GUI value; they may also be
        numbers or numeric strings. Reads live GUI state but never mutates it, so
        it must run on the GUI thread.

        Returns a JSON-serializable dict: a serialized ``ResolutionResult`` when
        the geometry is feasible and the instrument supports resolution, otherwise
        a ``{"ok": False, "reason": ...}`` refusal (feasibility / unsupported
        instrument) using the same vocabulary as ``/validate``.
        """
        vals = self.get_gui_values()
        if not vals:
            raise ApiError(400, "bad_request", "Could not read GUI values")
        vals = dict(vals)

        # The radius line edits are unrestricted, so a typed "nan" survives
        # get_gui_values' float(). scan_config below assigns vals['rhm'] &c.
        # straight onto a fresh state, which is upstream of
        # set_crystal_bending's non-finite backstop -- that backstop preserves
        # the EXISTING radius, and by then the existing radius is already the
        # NaN. The API's own radius fields are refused at parse time; this is
        # the matching gate for a value typed into the GUI, in the refusal
        # vocabulary this method already uses.
        bad_axes = [axis for axis in ('rhm', 'rvm', 'rha', 'rva')
                    if not math.isfinite(float(vals.get(axis, 0.0)))]
        if bad_axes:
            return {"ok": False, "reason": (
                "curvature radius must be a finite number: "
                + ", ".join(sorted(bad_axes))
            )}

        # Inject the selected sample key (same source _collect_simulation_launch_state
        # uses) so the adapter's eta_s / sample-mosaic path resolves.
        try:
            vals["sample_key"] = self.window.sample_dock.get_selected_sample_key()
        except Exception:
            vals["sample_key"] = None

        # (H, K, L, deltaE): omitted (None) params default to current GUI values.
        def _default(v, key):
            return float(vals[key]) if v is None else float(v)

        H = _default(H, "H")
        K = _default(K, "K")
        L = _default(L, "L")
        deltaE = _default(deltaE, "deltaE")
        method = method or "auto"

        # (H,K,L) -> q0 via the same sample-mount/UB solve the scan generator uses.
        qx, qy, qz = self._hkl_to_sample_q(H, K, L, vals)
        q0 = math.sqrt(qx ** 2 + qy ** 2 + qz ** 2)

        # Feasibility gate: the same per-point angle solve run_simulation applies
        # (throwaway check_state, calculate_stage_angles error flags). Infeasible ->
        # {"ok": false, "reason": ...} with the /validate refusal vocabulary.
        #
        # Built through scan_config -- the same mapping compute_scan_snapshot's
        # launch path and _reciprocal_advisory use -- so module state (e.g.
        # a fitted nested mirror optic) reaches check_state exactly like every
        # other curvature consumer, instead of a hand-picked field subset that
        # a generic controller would have to know one plugin's module names to
        # extend.
        check_state = self.instrument.scan_config(
            self.instrument.default_state(), vals, vals.get('sample_key'),
            self.diagnostic_settings, self._build_sample_mount(vals),
        )
        # A locked plane refuses an out-of-plane point here as in a scan.
        check_state.plane_lock = self.instrument_state.plane_lock
        angles, error_flags = check_state.calculate_stage_angles(
            qx, qy, qz, deltaE, check_state.fixed_E, check_state.K_fixed,
            check_state.monocris, check_state.anacris, locked=check_state.plane_lock,
        )
        angles = angles[:5]
        if error_flags:
            from instruments.tas_runtime import describe_scan_error_flags
            reason = describe_scan_error_flags(error_flags) or (
                "scattering triangle cannot close for this (Q, E) and fixed-k setup"
            )
            return {"ok": False, "reason": reason}

        # This request's OWN curvature, honouring each axis's mode -- there is
        # no snapshot to read applied radii off here (unlike the scan engines
        # above), so it is solved the same way compute_snapshot does: stamp
        # the solved angles onto the state (set_crystal_bending signs off
        # them), recompute AUTOFOCUS axes at THIS point's own two-theta, keep
        # a HELD axis's operator value, and let set_crystal_bending itself
        # pin a fixed axis to its declared radius.
        mtt, stt, sth, _sgl, att = angles
        from instruments.tas_runtime import is_forward_scattering
        if is_forward_scattering(stt):
            # Forward scattering: Cooper-Nathans divides by sin(stt) and has
            # no resolution function there (ruling 7) -- computed from this
            # request's own solved angles, the same reason text
            # ``validate_scan_launch_state`` reports for a scan point.
            return {"ok": False, "reason": (
                "direct transmission (sample): the analytic engine makes no claim"
            )}
        check_state.set_angles(A1=mtt, A2=stt, A3=sth, A4=att)
        curvature_modes = vals.get('curvature_modes') or {}
        radii = {}
        autofocus_axes = []
        for axis in ("rhm", "rvm", "rha", "rva"):
            radii[axis] = vals.get(axis)
            if curvature_modes.get(axis, CurvatureMode.HELD) == CurvatureMode.AUTOFOCUS:
                autofocus_axes.append(axis)
        if autofocus_axes:
            try:
                # requested_axes = exactly the AUTOFOCUS set: an unrelated
                # HELD/SCANNED axis with no established focusing model (IN12's
                # Heusler rva) must not refuse a query that never asked for it.
                ideal = check_state.ideal_curvature(
                    check_state.monocris, check_state.anacris,
                    crystal_theta(mtt), crystal_theta(att),
                    requested_axes=autofocus_axes,
                )
            except ValueError as exc:
                # Same refusal ideal_curvature already gives the GUI Ideal
                # button and the API launch-state recompute (an unknown
                # focusing model, e.g. IN12's Heusler rva) -- surfaced with
                # the same ok:false vocabulary as the feasibility gate above,
                # not a 500.
                #
                # The catch stays broad on purpose: a resolution query should
                # degrade to a stated refusal rather than a 500, because a
                # campaign client can act on the first and only retries the
                # second. But broad also catches things that are not refusals
                # at all, so it is logged. A silent catch would hide a real
                # fault behind a perfectly reasonable-looking answer, which is
                # the failure mode this entire branch has been chasing.
                log.warning(
                    "resolution refused for %s/%s at mtt=%.4g att=%.4g: %s",
                    check_state.monocris, check_state.anacris, mtt, att, exc,
                )
                return {"ok": False, "reason": str(exc)}
            for axis in autofocus_axes:
                radii[axis] = ideal[axis]
        check_state.set_crystal_bending(**radii)
        point_state = {
            axis: getattr(check_state, axis)
            for axis in ("rhm", "rvm", "rha", "rva")
        }
        # This request's own energies, built the identical way the snapshot
        # builds them (point_energy_metadata): an HKL or Q point never sets
        # _angle_energies, so this follows K_fixed + deltaE exactly like
        # compute_scan_snapshot's equivalent point would.
        point_state.update(check_state.point_energy_metadata(deltaE))
        point_state['deltaE'] = deltaE

        # Build the instrument's resolution config (optional plugin method).
        res_fn = getattr(self.instrument, "resolution_config", None)
        if not callable(res_fn):
            return {"ok": False, "reason": "resolution not supported for this instrument"}
        cfg = res_fn(
            _vals_with_point_state(vals, point_state), q0, deltaE,
            point_angles=_point_angles(mtt, stt, att),
        )

        from tavi.resolution import resolution
        return resolution(cfg, method=method).to_dict()

    def background_profile_state(self):
        """Return the complete canonical configuration and resolved metadata."""
        resolved = _background.resolve(self.background_profile)
        return {
            "spec": _background.normalized_spec(resolved),
            "resolved": _background.metadata_block(
                resolved, "config_default"
            ),
        }

    def set_background_profile(self, spec):
        """Validate and store the instrument-level background profile.

        A request REPLACES the stored configuration wholesale -- it never
        merges.  Sparse source maps are normalized to the complete catalog
        before storage. A ``ValueError`` from ``resolve`` propagates with the
        previous state untouched.
        """
        resolved = _background.resolve(spec)
        self.background_profile = _background.normalized_spec(resolved)
        self._refresh_background_row()
        active = sum(1 for state in resolved.sources if state.enabled)
        self._journal.record(
            "parameter",
            "background configuration: enabled=%s active_sources=%d fingerprint=%s"
            % (resolved.enabled, active,
               _background.profile_fingerprint(resolved)),
        )
        return {
            "spec": _background.normalized_spec(resolved),
            "resolved": _background.metadata_block(
                resolved, "config_default"
            ),
        }

    @staticmethod
    def _background_summary(resolved):
        """Concise configuration-button tooltip for enabled source knobs."""
        enabled = [state for state in resolved.sources if state.enabled]
        if not enabled:
            return "No background sources are enabled."
        summary = ", ".join(
            "%s ×%g" % (state.definition.label, state.scale)
            for state in enabled
        )
        if not resolved.enabled:
            return "Global background is off. Configured: " + summary
        return "Active: " + summary

    def _refresh_background_row(self):
        """Sync the simulation dock's background row with the stored profile.

        A no-op before the window exists (controller construction, headless
        tests). Any other failure is logged rather than raised: a display
        refresh must not undo an already-validated profile write.
        """
        dock = getattr(getattr(self, "window", None), "simulation_dock", None)
        if dock is None:
            return
        try:
            resolved = _background.resolve(self.background_profile)
            dock.set_background_display(
                resolved.enabled, self._background_summary(resolved)
            )
        except Exception as exc:
            self.print_to_message_center(
                f"Could not refresh the background row: {exc}"
            )

    def _on_background_enabled_toggled(self, enabled):
        """Apply the global gate immediately while retaining all source knobs."""
        try:
            resolved = _background.resolve(self.background_profile)
            spec = _background.normalized_spec(resolved)
            spec["enabled"] = bool(enabled)
            self.set_background_profile(spec)
        except Exception as exc:
            self.print_to_message_center(
                f"Could not update the global background switch: {exc}"
            )
            self._refresh_background_row()

    def configure_background(self):
        """Open the staged per-source editor and apply only an accepted result."""
        spec = BackgroundConfigDialog.configure(
            copy.deepcopy(self.background_profile), parent=self.window
        )
        if spec is None:
            self.print_to_message_center("Background configuration cancelled")
            return
        try:
            self.set_background_profile(spec)
            self.print_to_message_center("Background configuration applied")
        except ValueError as exc:
            self.print_to_message_center(
                f"Background configuration rejected: {exc}"
            )
            self._refresh_background_row()

    def build_api_launch_state(self, patch):
        """Freeze an API scan launch state from defaults + patch, GUI-independent.

        Runs on the GUI thread (may read ``self.descriptor`` /
        ``instrument_state`` / ``ub_matrix`` / ``diagnostic_settings``) but reads
        and writes NO widgets: the scan a remote caller submits is fully
        decoupled from live GUI state, so text a human left in a scan-command
        widget can never poison it, and an API scan never mutates the GUI
        (docs/API_SERVER_DESIGN.md sec 8). Returns a launch state shaped like
        :meth:`_collect_simulation_launch_state`, or raises ``ApiError`` on a bad
        patch or a missing scan command.
        """
        vals = self._default_parameter_values()
        field_map = self._api_field_map()

        # (a) Resolve the names, then parse/validate the patch with apply_parameters'
        #     own parse fns; an unknown name / bad value collects the identical 400.
        patch, submitted, errors = self._api_resolve_patch(patch or {}, field_map)
        if errors:
            raise ApiError(
                400, "invalid_parameters", "One or more fields failed",
                details={"errors": errors},
            )
        parsed = {}
        for name, value in patch.items():
            if name in self._API_READ_ONLY_FIELDS:
                # Known field (declared read-only in build_api_schema), not an
                # unrecognized one -- see _api_field_map's docstring.
                errors[submitted[name]] = "read-only field"
                continue
            if name in self._LOCK_FIELDS:
                errors[submitted[name]] = ("a scan runs in the session's orientation mode; "
                                           "set it with PATCH /parameters")
                continue
            try:
                parsed[name] = field_map[name][0](value)
            except (ValueError, TypeError) as exc:
                errors[submitted[name]] = "invalid value: %s" % exc
        errors.update({submitted[n]: reason for n, reason in self._lock_refusals(
            {n: v for n, v in patch.items() if n in self._LOCK_HELD_FIELDS}).items()})
        if errors:
            raise ApiError(
                400, "invalid_parameters", "One or more fields failed",
                details={"errors": errors},
            )

        # The frozen parameters and the plugins keep the internal names (until U3);
        # slit gaps land in the nested slits_mm each plugin indexes.
        internal = {_to_internal(n): v for n, v in parsed.items() if not n.startswith("slit.")}
        patched = set(internal)
        vals.update(internal)
        for slit in self.descriptor.slits:
            width = parsed.get(slit_gap_id(slit.stable_id, "horizontal"))
            height = parsed.get(slit_gap_id(slit.stable_id, "vertical"))
            if slit.has_height:
                old_width, old_height = vals['slits_mm'][slit.id]
                if width is not None or height is not None:
                    vals['slits_mm'][slit.id] = (old_width if width is None else width,
                                                 old_height if height is None else height)
            elif width is not None:
                vals['slits_mm'][slit.id] = width

        # Naming an explicit radius holds THAT axis, and only that axis --
        # per-axis is what a per-axis mode means. This replaces the old
        # all-or-nothing pin, where naming one radius froze all four.
        for axis in ('rhm', 'rvm', 'rha', 'rva'):
            if axis in patched:
                vals['curvature_modes'][axis] = CurvatureMode.HELD

        # A patched container replaces the previous object wholesale, so a
        # request naming only some collimation slots would silently drop the
        # rest -- and the plugin's scan_config indexes every slot the
        # descriptor declares, so the next one added to an instrument would
        # turn every previously valid partial request into a KeyError. Refill
        # from the descriptor defaults instead.
        if 'collimation' in patched and isinstance(vals.get('collimation'), dict):
            for slot_id, default in self._descriptor_collimation_defaults().items():
                vals['collimation'].setdefault(slot_id, default)

        # Same hole, same fix, for modules: a patched dict naming only "nmo"
        # dropped "v_selector", and instruments/puma/plugin.py indexes both
        # directly (`modules['nmo']`, `modules['v_selector']`) -- KeyError at
        # launch for a request the PATCH path (set_module_values' `.get(...,
        # default)`) accepts today.
        if 'modules' in patched and isinstance(vals.get('modules'), dict):
            for module_id, default in self._descriptor_module_defaults().items():
                vals['modules'].setdefault(module_id, default)

        # (b) Pure derivation pass (replaces the widget after-handlers).
        lattice_keys = ('lattice_a', 'lattice_b', 'lattice_c',
                        'lattice_alpha', 'lattice_beta', 'lattice_gamma')

        # A patched sample adopts its own lattice unless lattice_* is explicit.
        if 'sample' in patched and not any(k in patched for k in lattice_keys):
            spec = next((s for s in self.descriptor.samples
                         if s.id == vals['sample']), None)
            if spec is not None and spec.lattice is not None:
                (vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                 vals['lattice_alpha'], vals['lattice_beta'],
                 vals['lattice_gamma']) = spec.lattice
        sample_key = None if vals['sample'] == "none" else vals['sample']

        # k<->E consistency: a lone patched member of a k/E pair derives its
        # partner; a patched fixed_E/K_fixed recomputes the fixed side. deltaE
        # stays an independent scan variable (not folded back into the energies).
        if 'Ei' in patched and 'Ki' not in patched:
            vals['Ki'] = energy2k(vals['Ei'])
        elif 'Ki' in patched and 'Ei' not in patched:
            vals['Ei'] = k2energy(vals['Ki'])
        if 'Ef' in patched and 'Kf' not in patched:
            vals['Kf'] = energy2k(vals['Ef'])
        elif 'Kf' in patched and 'Ef' not in patched:
            vals['Ef'] = k2energy(vals['Kf'])
        if 'fixed_E' in patched or 'K_fixed' in patched:
            # Both sides, as the GUI's update_all_variables derives them:
            # the free side is fixed_E offset by the launch state's deltaE.
            if vals['K_fixed'] == "Ki Fixed":
                vals['Ei'] = vals['fixed_E']
                vals['Ef'] = vals['fixed_E'] - vals['deltaE']
            else:
                vals['Ef'] = vals['fixed_E']
                vals['Ei'] = vals['fixed_E'] + vals['deltaE']
            vals['Ki'] = energy2k(vals['Ei'])
            vals['Kf'] = energy2k(vals['Ef'])

        # Energy -> crystal angle, the API twin of the GUI's Ei/Ki/Ef/Kf
        # handlers: a patched energy side re-derives its own take-off angle
        # on the instrument's signed branch unless the caller named that
        # angle explicitly (an explicit A1/A4 is authoritative, as in the
        # GUI). Without this a direct-motor scan patched with Ei=12 kept the
        # reference-state A1 and ran near the reference energy. A
        # non-positive energy is refused here: direct motors take A1/A4 as
        # raw authority and never reaches calculate_angles' own Ei/Ef > 0
        # guard, and a NaN angle passes every limit comparison.
        energy_keys = ('fixed_E', 'K_fixed', 'monocris', 'anacris')
        if any(k in patched for k in energy_keys + ('Ei', 'Ki', 'Ef', 'Kf')):
            if not (vals['Ei'] > 0 and vals['Ef'] > 0):
                raise ApiError(
                    400, "invalid_parameters",
                    "energy transfer %s leaves Ei=%s, Ef=%s; both must be positive"
                    % (vals['deltaE'], vals['Ei'], vals['Ef']),
                )
            mono_info, ana_info = self.instrument.crystal_info(
                vals['monocris'], vals['anacris']
            )
            if 'mtt' not in patched and any(
                    k in patched for k in energy_keys + ('Ei', 'Ki')):
                vals['mtt'] = (self.instrument_state.sense_mono * 2
                               * k2angle(vals['Ki'], mono_info['dm']))
                patched.add('mtt')
            if 'att' not in patched and any(
                    k in patched for k in energy_keys + ('Ef', 'Kf')):
                vals['att'] = (self.instrument_state.sense_ana * 2
                               * k2angle(vals['Kf'], ana_info['da']))
                patched.add('att')

        # HKL<->Q under the (possibly sample-adopted) lattice. HKL is
        # authoritative when position was patched via HKL/lattice/sample; Q is
        # authoritative when patched via qx/qy/qz. LOAD-BEARING: ISAR sends
        # H/K/L and a Q scan's points read qx/qy/qz from the launch snapshot.
        q_keys = ('qx', 'qy', 'qz')
        hkl_trigger = ('H', 'K', 'L') + lattice_keys + ('sample',)
        if (any(k in patched for k in hkl_trigger)
                and not any(k in patched for k in q_keys)):
            vals['qx'], vals['qy'], vals['qz'] = self._hkl_to_sample_q(
                vals['H'], vals['K'], vals['L'], vals
            )
        elif any(k in patched for k in q_keys):
            vals['H'], vals['K'], vals['L'] = self._sample_q_to_hkl(
                vals['qx'], vals['qy'], vals['qz'], vals
            )

        # Refresh the AUTOFOCUS radii's starting numbers when mtt/att/modules/
        # monocris/anacris were patched, so a submitted request already
        # carries sensible values before any point is solved (the real
        # per-point focus still runs in compute_scan_snapshot -- this is just
        # the launch-state snapshot). Per-axis: an axis a caller pinned to an
        # explicit radius above (now HELD, computed above) is never
        # overwritten here, unlike the old all-or-nothing recompute this
        # replaces, where naming ANY one radius silently skipped it for all
        # four. Computed AFTER the HELD loop so a caller naming e.g. rva
        # excludes it here too; also excludes any axis a non-empty scan
        # command names (SCANNED, not a launch-state number to fill in --
        # compute_scan_snapshot answers that per point). Deliberately NOT
        # filtered through ``_askable_curvature_axes``: an axis that is
        # genuinely AUTOFOCUS, unscanned, AND driven with no established
        # focusing model (IN12's Heusler ``rva``) must still reach
        # ``ideal_curvature`` and raise -- nobody pinned or scanned it, so
        # there is no radius to run with, and that refusal is the point.
        if any(k in patched for k in
               ('mtt', 'att', 'modules', 'monocris', 'anacris')):
            requested_axes = {
                axis for axis in ('rhm', 'rvm', 'rha', 'rva')
                if vals['curvature_modes'][axis] == CurvatureMode.AUTOFOCUS
            }
            requested_axes -= self._scan_named_curvature_axes(
                vals.get('scan_command1'), vals.get('scan_command2')
            )
            if requested_axes:
                try:
                    ideal = self._ideal_bending_from_modules(
                        vals['mtt'], vals['att'], vals['monocris'], vals['anacris'],
                        vals['modules'], requested_axes=requested_axes,
                    )
                except ValueError as exc:
                    raise ApiError(400, "invalid_curvature", str(exc))
                if ideal:
                    for axis in requested_axes:
                        vals[axis] = ideal[axis]

        # A HELD radius outside its declared mechanical travel, or off a
        # fixed axis's declared radius, is refused here rather than silently
        # clamped: the caller named this value explicitly. The GUI's
        # ``_held_curvature_issues`` runs the identical check on the
        # equivalent widgets, via the same ``curvature_command_error``, so an
        # operator and an API client see the same sentence for the same
        # out-of-travel value. An axis a non-empty scan command names is
        # skipped -- ``_scan_named_curvature_axes``, shared with the GUI
        # check -- because that axis is about to be promoted to SCANNED and
        # this HELD value is not what the scan will actually run with (D21):
        # a patched rhm=1.0 alongside a legal absolute "rhm 3.0 4.0 0.5"
        # must not be refused for the 1.0 the scan overrides at every point.
        from instruments.tas_runtime import curvature_command_error

        curvature_axis_specs = self._curvature_axis_specs(
            vals['monocris'], vals['anacris'], modules=vals['modules']
        )
        scan_named_axes = self._scan_named_curvature_axes(
            vals.get('scan_command1'), vals.get('scan_command2')
        )
        for axis in ('rhm', 'rvm', 'rha', 'rva'):
            if vals['curvature_modes'][axis] != CurvatureMode.HELD:
                continue
            if axis in scan_named_axes:
                continue
            axis_spec = curvature_axis_specs.get(axis)
            if axis_spec is None:
                continue
            curvature_axis, crystal_name = axis_spec
            error = curvature_command_error(axis, vals[axis], curvature_axis, crystal_name)
            if error:
                raise ApiError(400, "curvature_out_of_travel", error)

        # At least one non-empty scan command is required (a lone command 2 is
        # swapped into command 1 downstream, so either satisfies the check).
        cmd1 = (vals.get('scan_command1') or "").strip()
        cmd2 = (vals.get('scan_command2') or "").strip()
        if not cmd1 and not cmd2:
            raise ApiError(
                400, "missing_required",
                "scan_command1 is required for API scan submission",
            )

        # Assemble the launch state (mirrors _collect_simulation_launch_state
        # minus every widget read). API scan commands are absolute; compact save
        # is off; the save folder is a fixed non-widget API base.
        self._enrich_launch_parameters(vals, sample_key)
        diagnostic_settings = copy.deepcopy(self.diagnostic_settings)
        return {
            'vals': vals,
            'snapshot': self.public_values(vals),
            'save_folder_input': os.path.join(self.output_directory, "api_scans"),
            'sample_key': sample_key,
            'engine': 'mcstas',
            'scan_config': self.instrument.scan_config(
                self.instrument_state, vals, sample_key, diagnostic_settings,
                self._build_sample_mount(vals),
            ),
            'diagnostic_settings': diagnostic_settings,
            'relative_mode_1': False,
            'relative_mode_2': False,
            'compact_save_enabled': False,
            'mpi_count': self.mpi_count,
        }

    def _collect_simulation_launch_state(self):
        """Freeze GUI state before starting the simulation worker thread."""
        vals = self.get_gui_values()
        if not vals:
            return None

        try:
            sample_key = self.window.sample_dock.get_selected_sample_key()
        except Exception:
            sample_key = None

        # Enrich the frozen vals with flat resolution/geometry parameters so they
        # flow through _launch_summary -> _serializable_params into every job's
        # JSON (consumed downstream by ISAR). Reuses the resolution adapter's
        # descriptor/sample lookups rather than duplicating them.
        self._enrich_launch_parameters(vals, sample_key)

        diagnostic_settings = copy.deepcopy(self.diagnostic_settings)

        # GUI-selected execution engine (docs/CONTROL_FEATURES_DESIGN.md §6.4).
        # The API's POST /scan body overrides this in _submit_scan_on_gui; for a
        # GUI-launched run it is the sole source. Defaults to 'mcstas'.
        try:
            engine = self.window.simulation_dock.get_selected_engine()
        except Exception:
            engine = 'mcstas'

        return {
            'vals': vals,
            # What the plan reads at this instant (canonical IDs): typed inputs and the
            # relative bases. The one capture for Run, the preview and the benchmark.
            'snapshot': self._launch_snapshot(vals),
            'save_folder_input': self.window.data_control_dock.save_folder_edit.text(),
            'sample_key': sample_key,
            'engine': engine,
            'scan_config': self.instrument.scan_config(
                self.instrument_state, vals, sample_key, diagnostic_settings,
                self._build_sample_mount(vals),
            ),
            'diagnostic_settings': diagnostic_settings,
            'relative_mode_1': self.window.simulation_dock.relative_1_button.isChecked(),
            'relative_mode_2': self.window.simulation_dock.relative_2_button.isChecked(),
            'compact_save_enabled': self.window.data_control_dock.compact_save_check.isChecked(),
            # A GUI-launched scan always runs the configured profile; the
            # per-scan override is an API-only channel.
            'background': copy.deepcopy(self.background_profile),
            'background_source': 'config_default',
            'mpi_count': self.mpi_count,
        }

    def _plan_input_edits(self):
        """{internal field: line edit} for every dock field a point plan can read."""
        idock, sdock = self.window.instrument_dock, self.window.scattering_dock
        return {
            'mtt': idock.mtt_edit, 'stt': idock.stt_edit, 'omega': idock.omega_edit,
            'att': idock.att_edit, 'sgl': idock.sgl_edit, 'sgu': idock.sgu_edit,
            'rhm': idock.rhm_edit, 'rvm': idock.rvm_edit, 'rha': idock.rha_edit,
            'rva': idock.rva_edit,
            'H': sdock.H_edit, 'K': sdock.K_edit, 'L': sdock.L_edit, 'qx': sdock.qx_edit,
            'qy': sdock.qy_edit, 'qz': sdock.qz_edit, 'deltaE': sdock.deltaE_edit,
            **self._slit_gap_edits(),
        }

    def _slit_gap_edits(self):
        """{gap ID: line edit} for this instrument's own slit gaps, in mm."""
        widgets = self.window.instrument_dock.slit_widgets
        return {qid: widgets[slit.id][widget] for slit in self.descriptor.slits
                for qid, widget in zip(slit_gap_ids(slit), ("width", "height"))}

    def _launch_snapshot(self, vals):
        """``vals`` under canonical IDs, without the plan inputs whose field is empty.

        ``get_gui_values`` reads an empty field as 0 for the edit handlers; a
        launch must not, so an empty field is missing here and a plan that reads
        it (as typed, or as a relative base) refuses naming it (``rules.expand``).
        """
        empty = {_to_public(key) for key, edit in self._plan_input_edits().items()
                 if not edit.text().strip()}
        return {qid: value for qid, value in self.public_values(vals).items()
                if qid not in empty}

    def _enrich_launch_parameters(self, vals, sample_key):
        """Inject flat resolution/geometry parameters into the frozen ``vals``.

        Adds the mono/analyzer/sample mosaics, scattering senses, vertical
        divergences, sample key, and sample temperature so they travel through
        the job JSON (``_launch_summary`` -> ``_serializable_params``) to remote
        consumers (ISAR). Values come from the shared resolution adapter (via the
        plugin's optional ``resolution_config``), not a duplicate descriptor read.
        Best-effort: any failure leaves ``vals`` unenriched rather than blocking a
        launch. Keys are flat and JSON-simple.
        """
        vals['sample_key'] = sample_key

        # Sample temperature from the descriptor sample library (SampleSpec.T).
        temperature = None
        try:
            spec = next((s for s in self.descriptor.samples if s.id == sample_key), None)
            if spec is not None:
                raw_t = (spec.properties or {}).get('T')
                temperature = float(raw_t) if raw_t is not None else None
        except Exception:
            temperature = None
        vals['temperature'] = temperature

        # Mosaics / senses / vertical divergences via the resolution adapter.
        res_fn = getattr(self.instrument, 'resolution_config', None)
        if not callable(res_fn):
            return
        try:
            # q0/w are irrelevant here: resolution_config only assembles the config
            # dataclass (no solver run), so any values populate the geometry fields.
            cfg = res_fn(vals, 0.0, 0.0)
        except Exception:
            return

        try:
            bet = list(cfg.bet) + [None, None, None, None]
            vals.update({
                'eta_m': cfg.eta_m,
                'eta_a': cfg.eta_a,
                'eta_s': cfg.effective_eta_s(),
                'sense_m': int(cfg.sm),
                'sense_s': int(cfg.ss),
                'sense_a': int(cfg.sa),
                'beta_1': bet[0],
                'beta_2': bet[1],
                'beta_3': bet[2],
                'beta_4': bet[3],
            })
        except Exception:
            return

    def set_gui_value(self, widget, value, precision=4):
        """Helper to set GUI value with proper formatting."""
        if self.updating:
            return
        try:
            formatted = format_editable_number(value, precision)
            widget.setText(formatted)
        except (ValueError, TypeError):
            pass

    def normalize_scan_variable(self, name):
        """Canonical quantity ID of a scan command's variable name.

        Any registry spelling (ID, alias, any case) resolves; a name the
        registry refuses as a scan command comes back unchanged, and the
        validators report it.
        """
        if not name:
            return name
        try:
            return resolve_quantity(str(name).strip(), "scan").id
        except QuantityRefused:
            return name

    def _field_value_changed(self, field_name: str, current_value: float, tolerance: float = 1e-9) -> bool:
        """
        Check if a field value has actually changed from its previous value.
        This prevents spurious updates from editingFinished signals when focus changes
        without the value being modified.
        
        Args:
            field_name: Unique identifier for the field
            current_value: The current numeric value of the field
            tolerance: Tolerance for floating point comparison
            
        Returns:
            True if the value has changed, False otherwise
        """
        previous = self._previous_values.get(field_name)
        if previous is None or abs(previous - current_value) > tolerance:
            self._previous_values[field_name] = current_value
            return True
        return False
    
    def _update_tracked_value(self, field_name: str, value: float, precision: int = 4,
                              displayed_text: str | None = None):
        """Update the tracked value for a field (use when setting field programmatically)."""
        text = displayed_text if displayed_text is not None else format_editable_number(value, precision)
        self._previous_values[field_name] = float(text)

    def _set_tracked_angle_text(self, field_name, edit, value):
        """Set a derived angle and track the exact numeric text being displayed."""
        text = format_editable_number(value)
        edit.setText(text)
        self._update_tracked_value(field_name, value, displayed_text=edit.text())
        self._commit_programmatic_feedback([edit])

    def _signed_mtt(self, Ki):
        """Mono two-theta from Ki, on the instrument's declared readout sense.

        Same rule as the runtime (instruments/tas_runtime.py calculate_angles).
        """
        return self.instrument_state.sense_mono * 2 * k2angle(Ki, self.monocris_info['dm'])

    def _signed_att(self, Kf):
        """Analyser two-theta from Kf, on the instrument's declared readout sense.

        Same rule as the runtime (instruments/tas_runtime.py calculate_angles).
        """
        return self.instrument_state.sense_ana * 2 * k2angle(Kf, self.anacris_info['da'])
    
    def update_all_variables(self, skip_crystal_angles=False):
        """
        Comprehensive update of all instrument variables based on K_fixed mode.
        This is the central method that ensures all fields stay in sync.
        
        Args:
            skip_crystal_angles: If True, don't update mtt/att (use when angles are source of truth)
        """
        if self.updating:
            return
        
        vals = self.get_gui_values()
        if not vals or not self.monocris_info or not self.anacris_info:
            return
        
        try:
            self.updating = True
            
            
            # Update Ei and Ef based on K_fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                # Ki/Ei are fixed, calculate Ef
                Ei = vals['fixed_E']
                Ef = Ei - vals['deltaE']
            else:  # Kf Fixed
                # Kf/Ef are fixed, calculate Ei
                Ef = vals['fixed_E']
                Ei = Ef + vals['deltaE']
            
            # Calculate wave vectors from energies
            Ki = energy2k(Ei)
            Kf = energy2k(Ef)
            
            # Recalculate deltaE to ensure consistency
            deltaE = Ei - Ef
            
            # Update energy-related GUI fields
            self.window.instrument_dock.Ei_edit.setText(format_editable_number(Ei))
            self.window.instrument_dock.Ef_edit.setText(format_editable_number(Ef))
            self.window.instrument_dock.Ki_edit.setText(format_editable_number(Ki))
            self.window.instrument_dock.Kf_edit.setText(format_editable_number(Kf))
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            for key, value in (("Ei", Ei), ("Ef", Ef), ("Ki", Ki), ("Kf", Kf), ("deltaE", deltaE), ("fixed_E", vals['fixed_E'])):
                self._update_tracked_value(key, value)
            
            # Only update crystal angles if not skipping (angles are not the source of truth)
            if not skip_crystal_angles:
                mtt = self._signed_mtt(Ki)
                att = self._signed_att(Kf)
                self._set_tracked_angle_text('mtt', self.window.instrument_dock.mtt_edit, mtt)
                self._set_tracked_angle_text('att', self.window.instrument_dock.att_edit, att)
            
        except (ValueError, KeyError) as e:
            pass
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()

    def _compute_ideal_bending_values(self, mtt=None, att=None):
        """Ideal absolute bending radii for the crystals selected in the GUI.

        Thin caller of ``_ideal_bending_from_modules``, naming the crystals
        the GUI actually has selected and the NMO state from its combo --
        never a live-widget read anywhere else, so a hypothetical (mtt, att)
        passed in by a caller still gets today's real crystal selection.
        Returns None for a degenerate geometry (zero take-off angle); a
        driven axis whose crystal declares this axis's focusing model
        unknown (IN12's Heusler ``rva``) is simply left out of the askable
        set (``_askable_curvature_axes``) rather than blanking the whole
        result -- the other three axes still get a real ideal. The caller
        shows "Ideal: --" for a missing key the same way it already does for
        a fully refused result.
        """
        try:
            if mtt is None:
                mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            if att is None:
                att = float(self.window.instrument_dock.att_edit.text() or 0)
            modules = self.window.instrument_dock.module_values()
            monocris = self.window.instrument_dock.selected_mono_id()
            anacris = self.window.instrument_dock.selected_ana_id()
            # Ask only for the axes with an established focusing model --
            # an unrelated driven axis with none (IN12's Heusler rva) must
            # not disable the other three, which the whole-crystal try/except
            # used to do by construction (any raise blanked all four).
            requested_axes = self._askable_curvature_axes(
                monocris, anacris, modules=modules
            )
            return self._ideal_bending_from_modules(
                mtt, att, monocris, anacris, modules,
                requested_axes=requested_axes,
            )
        except ValueError as exc:
            # Expected refusal: an unrequested-but-still-raising crystal
            # lookup failure. A degenerate take-off angle is handled inside
            # ``_ideal_bending_from_modules`` (ZeroDivisionError -> None) and
            # never reaches here. The caller shows "Ideal: --".
            log.info("ideal bending unavailable (%s/%s): %s",
                     monocris, anacris, exc)
            return None
        except Exception:
            # Anything else is a wiring bug, not a refusal. It still degrades
            # to "Ideal: --" rather than taking the window down mid-session,
            # but it is never silent -- this catch used to hide the traceback
            # entirely, and it now guards a call into the instrument model
            # rather than a few lines of arithmetic.
            log.exception("ideal bending raised unexpectedly (%s/%s)",
                          monocris, anacris)
            return None

    def _current_rva_axis(self):
        """The selected analyser's declared ``CurvatureAxis`` for rva.

        The one axis whose declared policy actually varies between crystals
        -- fixed (no operator say), driven with no established focusing model
        (IN12's Heusler), or ordinary. Read fresh from the descriptor via
        ``_curvature_axis_specs`` rather than cached, so a crystal swap is
        picked up the moment it happens.
        """
        from instruments.descriptor import CurvatureAxis

        idock = self.window.instrument_dock
        monocris = idock.selected_mono_id()
        anacris = idock.selected_ana_id()
        # Resolved against the LIVE module state, exactly as the four-axis
        # sync loop in update_ideal_bending_buttons resolves its specs -- a
        # second reading without modules would be a twin that disagrees the
        # day a module override touches rva.
        rva_axis, _ = self._curvature_axis_specs(
            monocris, anacris, modules=idock.module_values()
        ).get('rva', (CurvatureAxis(), ''))
        return rva_axis

    def _apply_rva_axis_policy(self, rva_axis):
        """Enable/disable rva's field and Ideal button per the descriptor.

        Three cases (docs/CONFIGURABLE_INSTRUMENTS.md, this branch's packet):
        fixed -- the operator has no say, the field shows the declared radius
        and is not editable, and the Ideal button is pointless (the applier
        pins the value regardless of mode); driven with no established
        focusing model -- a typed value is legitimate (HELD) but there is no
        optimum to compute, so the Ideal button is disabled with a tooltip
        saying why; otherwise it behaves exactly like rha.
        """
        idock = self.window.instrument_dock
        if not rva_axis.driven:
            idock.rva_ideal_button.setChecked(False)
            idock.rva_ideal_button.setEnabled(False)
            idock.rva_edit.setEnabled(False)
            idock.rva_ideal_button.setToolTip(
                "rva is fixed for this analyser; there is no autofocus and "
                "no operator override."
            )
        elif not rva_axis.focusing_known:
            idock.rva_ideal_button.setChecked(False)
            idock.rva_ideal_button.setEnabled(False)
            idock.rva_edit.setEnabled(True)
            idock.rva_ideal_button.setToolTip(
                "No established focusing model for this analyser's rva; a "
                "typed value is honoured, but autofocus cannot be offered."
            )
        else:
            idock.rva_edit.setEnabled(True)
            if not idock.rva_ideal_button.isChecked():
                idock.rva_ideal_button.setEnabled(True)
            idock.rva_ideal_button.setToolTip("Set rva to the calculated ideal value")

    def update_ideal_bending_buttons(self):
        """Update ideal bending button labels based on current angles."""
        idock = self.window.instrument_dock
        monocris = idock.selected_mono_id()
        anacris = idock.selected_ana_id()
        modules = idock.module_values()
        axis_specs = self._curvature_axis_specs(monocris, anacris, modules=modules)
        rva_axis = self._current_rva_axis()
        self._apply_rva_axis_policy(rva_axis)

        ideal = self._compute_ideal_bending_values()
        if not ideal:
            idock.rhm_ideal_button.setText("Ideal: --")
            idock.rvm_ideal_button.setText("Ideal: --")
            idock.rha_ideal_button.setText("Ideal: --")
            idock.rva_ideal_button.setText("Ideal: --")
            # No ideal (degenerate take-off angle) does not suspend policy:
            # a fixed axis still shows its resolved radius, disabled, so a
            # later Run is not refused on a stale value the module never
            # uses. Same loop as below, with no ideal to sync locked axes to.
            self._sync_curvature_fields(axis_specs, ideal=None)
            return

        rhm_locked = self.is_bending_locked("rhm")
        rvm_locked = self.is_bending_locked("rvm")
        rha_locked = self.is_bending_locked("rha")
        rva_locked = self.is_bending_locked("rva")

        # Show "Flat" when NMO is installed and ideal value is 0
        if ideal['rhm'] == 0:
            idock.rhm_ideal_button.setText(
                f"Ideal ({'L' if rhm_locked else 'U'}): Flat (NMO)"
            )
        else:
            idock.rhm_ideal_button.setText(
                f"Ideal ({'L' if rhm_locked else 'U'}): {ideal['rhm']:.3f} m"
            )

        if ideal['rvm'] == 0:
            idock.rvm_ideal_button.setText(
                f"Ideal ({'L' if rvm_locked else 'U'}): Flat (NMO)"
            )
        else:
            idock.rvm_ideal_button.setText(
                f"Ideal ({'L' if rvm_locked else 'U'}): {ideal['rvm']:.3f} m"
            )

        idock.rha_ideal_button.setText(
            f"Ideal ({'L' if rha_locked else 'U'}): {ideal['rha']:.3f} m"
        )

        if rva_axis.driven and not rva_axis.focusing_known:
            # No model to report a number from -- the button is disabled by
            # policy above; the label matches the "no ideal available" case.
            idock.rva_ideal_button.setText("Ideal: --")
        else:
            idock.rva_ideal_button.setText(
                f"Ideal ({'L' if rva_locked else 'U'}): {ideal['rva']:.3f} m"
            )

        # If locked to ideal, keep fields synced. A fixed axis is always
        # synced regardless of lock bookkeeping -- the field is disabled and
        # the applier pins it anyway, so it must always show the declared
        # radius, sourced here from the producer, never computed locally.
        # One loop over all four: an axis whose RESOLVED policy (this
        # crystal pair plus live module state, e.g. a nested mirror optic
        # fixing rhm/rvm flat) is not driven has its field disabled and
        # synced unconditionally; a driven axis stays editable and is
        # synced only when its own Ideal lock is on. Previously only rva's
        # field ever got disabled here (via ``_apply_rva_axis_policy``) --
        # rhm/rvm/rha kept whatever stale value the operator last typed,
        # with no disabled cue, once a module fixed them flat.
        self._sync_curvature_fields(axis_specs, ideal)

    def _sync_curvature_fields(self, axis_specs, ideal):
        """The one loop that keeps the four radius fields honest.

        A non-driven axis (fixed by declaration, or by a fitted module) is
        disabled and shows its resolved radius; a driven axis is editable
        and synced to its ideal only while its Ideal lock is on. ``ideal``
        may be None (no take-off angle to focus at) or a dict narrowed to
        the askable axes; a locked driven axis with no ideal is left as is.
        """
        idock = self.window.instrument_dock
        axis_edits = {
            "rhm": idock.rhm_edit, "rvm": idock.rvm_edit,
            "rha": idock.rha_edit, "rva": idock.rva_edit,
        }
        if self.updating:
            return
        self.updating = True
        try:
            for axis, edit in axis_edits.items():
                axis_spec = axis_specs.get(axis)
                driven = axis_spec[0].driven if axis_spec else True
                edit.setEnabled(driven)
                if not driven:
                    value = ideal.get(axis) if ideal else None
                    if value is None:
                        value = abs(axis_spec[0].fixed_radius_m or 0.0)
                    self._update_locked_field_if_needed(edit, value)
                elif self.is_bending_locked(axis) and ideal and axis in ideal:
                    self._update_locked_field_if_needed(edit, ideal[axis])
        finally:
            self.updating = False

    def apply_ideal_bending_value(self, key):
        """Apply the ideal bending value to the selected input field."""
        ideal = self._compute_ideal_bending_values()
        if not ideal:
            return
        if key == "rhm":
            self.window.instrument_dock.rhm_ideal_button.setChecked(True)
            self.window.instrument_dock.rhm_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rhm_edit, ideal['rhm'])
        elif key == "rvm":
            self.window.instrument_dock.rvm_ideal_button.setChecked(True)
            self.window.instrument_dock.rvm_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rvm_edit, ideal['rvm'])
        elif key == "rha":
            self.window.instrument_dock.rha_ideal_button.setChecked(True)
            self.window.instrument_dock.rha_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rha_edit, ideal['rha'])
        elif key == "rva":
            self.window.instrument_dock.rva_ideal_button.setChecked(True)
            self.window.instrument_dock.rva_ideal_button.setEnabled(False)
            self._set_and_confirm_field(self.window.instrument_dock.rva_edit, ideal['rva'])
        self.update_ideal_bending_buttons()

    def apply_ideal_bending_values(self):
        """Apply ideal bending values to all fields."""
        ideal = self._compute_ideal_bending_values()
        if not ideal:
            return
        self._set_and_confirm_field(self.window.instrument_dock.rhm_edit, ideal['rhm'])
        self._set_and_confirm_field(self.window.instrument_dock.rvm_edit, ideal['rvm'])
        self._set_and_confirm_field(self.window.instrument_dock.rha_edit, ideal['rha'])
        self._set_and_confirm_field(self.window.instrument_dock.rva_edit, ideal['rva'])

    def unlock_ideal_bending(self, key):
        """Unlock ideal bending button when user edits the field."""
        if key == "rhm":
            self.window.instrument_dock.rhm_ideal_button.setChecked(False)
            self.window.instrument_dock.rhm_ideal_button.setEnabled(True)
        elif key == "rvm":
            self.window.instrument_dock.rvm_ideal_button.setChecked(False)
            self.window.instrument_dock.rvm_ideal_button.setEnabled(True)
        elif key == "rha":
            self.window.instrument_dock.rha_ideal_button.setChecked(False)
            self.window.instrument_dock.rha_ideal_button.setEnabled(True)
        elif key == "rva":
            self.window.instrument_dock.rva_ideal_button.setChecked(False)
            # Unlike the other three, rva's button may legitimately be
            # unavailable for the selected analyser (fixed, or no established
            # focusing model) -- re-enable it only when the descriptor says
            # autofocus is actually offered here.
            rva_axis = self._current_rva_axis()
            self.window.instrument_dock.rva_ideal_button.setEnabled(
                rva_axis.driven and rva_axis.focusing_known
            )

    def is_bending_locked(self, key):
        """Return True if a bending field is locked to ideal."""
        if key == "rhm":
            return self.window.instrument_dock.rhm_ideal_button.isChecked() and not self.window.instrument_dock.rhm_ideal_button.isEnabled()
        if key == "rvm":
            return self.window.instrument_dock.rvm_ideal_button.isChecked() and not self.window.instrument_dock.rvm_ideal_button.isEnabled()
        if key == "rha":
            return self.window.instrument_dock.rha_ideal_button.isChecked() and not self.window.instrument_dock.rha_ideal_button.isEnabled()
        if key == "rva":
            return self.window.instrument_dock.rva_ideal_button.isChecked() and not self.window.instrument_dock.rva_ideal_button.isEnabled()
        return False

    def _set_and_confirm_field(self, line_edit, value, force=False):
        """Set a field programmatically and flash accepted state."""
        if self.updating and not force:
            return
        try:
            self._set_and_confirm_text(
                line_edit, self._format_field_value(value), force=force
            )
        except (ValueError, TypeError):
            pass

    def _set_and_confirm_text(self, line_edit, text, force=False):
        """Set text through the committed programmatic-update lifecycle."""
        if self.updating and not force:
            return
        try:
            self.updating = True
            line_edit.setText(str(text))
            self._commit_programmatic_feedback([line_edit], flash=True)
        finally:
            self.updating = False

    def _format_field_value(self, value, precision=4):
        """Format numeric field value consistently."""
        return format_editable_number(value, precision)

    def _update_locked_field_if_needed(self, line_edit, value):
        """Update locked field only if the value changed."""
        try:
            formatted = self._format_field_value(value)
        except (ValueError, TypeError):
            return
        if line_edit.text() == formatted:
            return
        self._set_and_confirm_field(line_edit, value, force=True)

    def _flash_field_saved(self, line_edit):
        """Flash field to indicate programmatic update accepted.

        Every flash timer is bound to its field (``singleShot`` with the field
        as context), so a field deleted mid-flash cancels them."""
        original_style = line_edit.property("original_style") or ""
        flash_token = int(line_edit.property("feedback_flash_token") or 0) + 1
        line_edit.setProperty("feedback_flash_token", flash_token)
        line_edit.setStyleSheet("QLineEdit { border: 2px solid #FF8C00; }")

        def _restore_if_still_committed():
            if line_edit.property("feedback_flash_token") != flash_token:
                return
            if line_edit.text() != line_edit.property("original_value"):
                # A human edit arrived while the accepted-change animation was
                # pending.  Keep its unsaved state visible rather than letting
                # this older timer erase it.
                line_edit.setStyleSheet("QLineEdit { border: 2px solid #FF8C00; }")
                return
            line_edit.setStyleSheet(original_style)

        def _bold_then_reset():
            if line_edit.property("feedback_flash_token") != flash_token:
                return
            if line_edit.text() != line_edit.property("original_value"):
                _restore_if_still_committed()
                return
            line_edit.setStyleSheet("QLineEdit { border: 3px solid #000000; }")
            QTimer.singleShot(300, line_edit, _restore_if_still_committed)

        QTimer.singleShot(150, line_edit, _bold_then_reset)

    def _load_bending_parameters(self, parameters):
        """Load absolute bending radii from the saved parameter block."""
        self.window.instrument_dock.rhm_edit.setText(format_editable_number(parameters.get("mono_horizontal_radius_m", "0")))
        self.window.instrument_dock.rvm_edit.setText(format_editable_number(parameters.get("mono_vertical_radius_m", "0")))
        self.window.instrument_dock.rha_edit.setText(format_editable_number(parameters.get("analyzer_horizontal_radius_m", "0")))
        self.window.instrument_dock.rva_edit.setText(format_editable_number(parameters.get("analyzer_vertical_radius_m", "0")))

    def _normalise_loaded_numbers(self, parameters):
        """Replace malformed saved numeric values with documented defaults.

        The subsequent loader can keep direct widget writes while malformed or
        null JSON values become visible warnings rather than startup crashes.
        """
        mtt, stt, omega, att = self._reference_angles(
            self._saved_crystal_id(parameters.get("monocris_var"), self.descriptor.mono_crystals),
            self._saved_crystal_id(parameters.get("anacris_var"), self.descriptor.ana_crystals),
        )
        defaults = {
            "mono_horizontal_radius_m": 0, "mono_vertical_radius_m": 0, "analyzer_horizontal_radius_m": 0, "analyzer_vertical_radius_m": 0,
            "mono_two_theta_deg": mtt, "sample_two_theta_deg": stt, "sample_rotation_deg": omega,
            "sample_lower_arc_deg": 0, "sample_upper_arc_deg": 0,
            "analyzer_two_theta_deg": att, "incident_wavevector_inv_angstrom": 2.6634, "final_wavevector_inv_angstrom": 2.6634,
            "incident_energy_mev": 14.7, "final_energy_mev": 14.7, "source_dE_var": 2, "fixed_E_var": 14.7,
            "q_instrument_x_inv_angstrom": 3.1028, "q_instrument_y_inv_angstrom": 0, "q_instrument_z_inv_angstrom": 0, "h": 2, "k": 0,
            "l": 0, "energy_transfer_mev": 0,
            "lattice_a_angstrom": 4.05, "lattice_b_angstrom": 4.05, "lattice_c_angstrom": 4.05,
            "lattice_alpha_deg": 90, "lattice_beta_deg": 90, "lattice_gamma_deg": 90,
        }
        result = dict(parameters)
        for key, default in defaults.items():
            if key not in result:
                continue
            try:
                number = float(result[key])
                if not math.isfinite(number):
                    raise ValueError("non-finite value")
            except (TypeError, ValueError):
                self.print_to_message_center(f"Parameters load: invalid {key}; using {default}")
                result[key] = default
        return result

    def _apply_bending_lock_state(self, rhm_locked, rvm_locked, rha_locked, rva_locked):
        """Apply lock state for ideal bending buttons.

        ``rva``'s enabled state set here is provisional: ``update_ideal_bending_buttons``
        (called below, and always again once loading finishes) re-applies the
        descriptor's own policy over it -- a saved lock the current analyser
        no longer offers (fixed, or no established focusing model) does not
        survive that call.
        """
        self.window.instrument_dock.rhm_ideal_button.setChecked(bool(rhm_locked))
        self.window.instrument_dock.rhm_ideal_button.setEnabled(not bool(rhm_locked))
        self.window.instrument_dock.rvm_ideal_button.setChecked(bool(rvm_locked))
        self.window.instrument_dock.rvm_ideal_button.setEnabled(not bool(rvm_locked))
        self.window.instrument_dock.rha_ideal_button.setChecked(bool(rha_locked))
        self.window.instrument_dock.rha_ideal_button.setEnabled(not bool(rha_locked))
        self.window.instrument_dock.rva_ideal_button.setChecked(bool(rva_locked))
        self.window.instrument_dock.rva_ideal_button.setEnabled(not bool(rva_locked))

        if any([rhm_locked, rvm_locked, rha_locked, rva_locked]):
            self.update_ideal_bending_buttons()
    
    def on_mtt_changed(self):
        """Update energies when mono 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        
        # Check if value actually changed
        if not self._field_value_changed('mtt', vals['mtt']):
            return
        
        try:
            self.updating = True
            # Update Ki and Ei from mtt
            Ki = angle2k(vals['mtt'] / (2 * self.instrument_state.sense_mono), self.monocris_info['dm'])
            Ei = k2energy(Ki)
            
            self.window.instrument_dock.Ki_edit.setText(format_editable_number(Ki))
            self.window.instrument_dock.Ei_edit.setText(format_editable_number(Ei))
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(Ei))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Ki', Ki)
            self._update_tracked_value('Ei', Ei)
            self._update_tracked_value('fixed_E', Ei if vals['K_fixed'] == "Ki Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_att_changed(self):
        """Update energies when analyzer 2theta changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        
        # Check if value actually changed
        if not self._field_value_changed('att', vals['att']):
            return
        
        try:
            self.updating = True
            # Update Kf and Ef from att
            Kf = angle2k(vals['att'] / (2 * self.instrument_state.sense_ana), self.anacris_info['da'])
            Ef = k2energy(Kf)
            
            self.window.instrument_dock.Kf_edit.setText(format_editable_number(Kf))
            self.window.instrument_dock.Ef_edit.setText(format_editable_number(Ef))
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(Ef))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Kf', Kf)
            self._update_tracked_value('Ef', Ef)
            self._update_tracked_value('fixed_E', Ef if vals['K_fixed'] == "Kf Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ki_changed(self):
        """Update Ei and mtt when Ki changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        if not self._field_value_changed('Ki', vals['Ki']):
            return
        
        try:
            self.updating = True
            Ei = k2energy(vals['Ki'])
            mtt = self._signed_mtt(vals['Ki'])
            
            self.window.instrument_dock.Ei_edit.setText(format_editable_number(Ei))
            self._set_tracked_angle_text('mtt', self.window.instrument_dock.mtt_edit, mtt)
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(Ei))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Ei', Ei)
            self._update_tracked_value('fixed_E', Ei if vals['K_fixed'] == "Ki Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ei_changed(self):
        """Update Ki and mtt when Ei changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.monocris_info:
            return
        if not self._field_value_changed('Ei', vals['Ei']):
            return
        
        try:
            self.updating = True
            Ki = energy2k(vals['Ei'])
            mtt = self._signed_mtt(Ki)
            
            self.window.instrument_dock.Ki_edit.setText(format_editable_number(Ki))
            self._set_tracked_angle_text('mtt', self.window.instrument_dock.mtt_edit, mtt)
            
            # Update fixed_E if Ki Fixed mode
            if vals['K_fixed'] == "Ki Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(vals['Ei']))
            
            # Update deltaE
            Ef = float(self.window.instrument_dock.Ef_edit.text() or 0)
            deltaE = vals['Ei'] - Ef
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Ki', Ki)
            self._update_tracked_value('fixed_E', vals['Ei'] if vals['K_fixed'] == "Ki Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Kf_changed(self):
        """Update Ef and att when Kf changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        if not self._field_value_changed('Kf', vals['Kf']):
            return
        
        try:
            self.updating = True
            Ef = k2energy(vals['Kf'])
            att = self._signed_att(vals['Kf'])
            
            self.window.instrument_dock.Ef_edit.setText(format_editable_number(Ef))
            self._set_tracked_angle_text('att', self.window.instrument_dock.att_edit, att)
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(Ef))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - Ef
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Ef', Ef)
            self._update_tracked_value('fixed_E', Ef if vals['K_fixed'] == "Kf Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_Ef_changed(self):
        """Update Kf and att when Ef changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals or not self.anacris_info:
            return
        if not self._field_value_changed('Ef', vals['Ef']):
            return
        
        try:
            self.updating = True
            Kf = energy2k(vals['Ef'])
            att = self._signed_att(Kf)
            
            self.window.instrument_dock.Kf_edit.setText(format_editable_number(Kf))
            self._set_tracked_angle_text('att', self.window.instrument_dock.att_edit, att)
            
            # Update fixed_E if Kf Fixed mode
            if vals['K_fixed'] == "Kf Fixed":
                self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(vals['Ef']))
            
            # Update deltaE
            Ei = float(self.window.instrument_dock.Ei_edit.text() or 0)
            deltaE = Ei - vals['Ef']
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
            self._update_tracked_value('Kf', Kf)
            self._update_tracked_value('fixed_E', vals['Ef'] if vals['K_fixed'] == "Kf Fixed" else vals['fixed_E'])
            self._update_tracked_value('deltaE', deltaE)
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def on_K_fixed_changed(self):
        """Update all when K fixed mode changes."""
        self.update_all_variables()
        self.update_angles_from_q()
        self.request_reciprocal_snapshot()
    
    def on_fixed_E_changed(self):
        """Update all when fixed E changes."""
        vals = self.get_gui_values()
        if not vals or not self._field_value_changed('fixed_E', vals['fixed_E']):
            return
        self.update_all_variables()
        self.update_angles_from_q()
    
    def on_deltaE_changed(self):
        """Update energies when deltaE changes."""
        vals = self.get_gui_values()
        if not vals or not self._field_value_changed('deltaE', vals['deltaE']):
            return
        self.update_all_variables()
        # Keep sample angles in sync with updated deltaE
        self.update_angles_from_q()
    
    def on_stt_changed(self):
        """Handle sample 2theta (stt) change."""
        if self.updating:
            return
        try:
            stt = float(self.window.instrument_dock.stt_edit.text() or 0)
            # Only update if value actually changed (avoid spurious editingFinished signals)
            if not self._field_value_changed('stt', stt):
                return
            # Trigger angle-based updates
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid sample 2θ value")
    
    def on_angles_changed(self):
        """Update Q-space when angles change."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return

        try:
            self.updating = True
            mtt = float(self.window.instrument_dock.mtt_edit.text() or 0)
            stt = float(self.window.instrument_dock.stt_edit.text() or 0)
            sth = float(self.window.instrument_dock.omega_edit.text() or 0)
            att = float(self.window.instrument_dock.att_edit.text() or 0)
            sgl = float(self.window.instrument_dock.sgl_edit.text() or 0)
            sgu = float(self.window.instrument_dock.sgu_edit.text() or 0)

            q_vals, error_flags = self.instrument_state.calculate_q_and_deltaE(
                mtt, stt, sth, sgl, att,
                vals['fixed_E'], vals['K_fixed'],
                vals['monocris'], vals['anacris'], sgu=sgu,
            )
            if not error_flags:
                qx, qy, qz, deltaE = q_vals
                self._set_angles_stale(None)     # Q now follows the angles
                self.window.scattering_dock.qx_edit.setText(format_editable_number(qx))
                self.window.scattering_dock.qy_edit.setText(format_editable_number(qy))
                self.window.scattering_dock.qz_edit.setText(format_editable_number(qz))
                self.window.scattering_dock.deltaE_edit.setText(format_editable_number(deltaE))
                # Update tracked Q values since we just set them
                self._update_tracked_value('qx', qx)
                self._update_tracked_value('qy', qy)
                self._update_tracked_value('qz', qz)
        except Exception as exc:
            self.print_to_message_center(f"Q update from angles failed: {exc}")
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            # Update HKL based on new Q values, but skip recalculating angles
            # since the angles are the source of truth here
            self.on_Q_changed(skip_angle_update=True)
            # Update energies based on updated deltaE, but don't recalculate mtt/att
            # since crystal angles are part of the input and shouldn't change
            self.update_all_variables(skip_crystal_angles=True)
    
    def on_Q_changed(self, skip_angle_update=False):
        """Update HKL when Q changes.
        
        This is called either:
        1. Directly by user editing Q fields (skip_angle_update=False)
        2. From on_angles_changed when angles are source of truth (skip_angle_update=True)
        """
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        # Check if any Q value actually changed (avoid spurious editingFinished triggers)
        qx_changed = self._field_value_changed('qx', vals['qx'])
        qy_changed = self._field_value_changed('qy', vals['qy'])
        qz_changed = self._field_value_changed('qz', vals['qz'])
        
        if not skip_angle_update and not (qx_changed or qy_changed or qz_changed):
            # No actual change and not called from angles - skip update
            return
        
        try:
            self.updating = True
            H, K, L = self._sample_q_to_hkl(vals['qx'], vals['qy'], vals['qz'], vals)
            self.window.scattering_dock.H_edit.setText(format_editable_number(H))
            self.window.scattering_dock.K_edit.setText(format_editable_number(K))
            self.window.scattering_dock.L_edit.setText(format_editable_number(L))
            # Update tracked values for HKL since we just set them
            self._update_tracked_value('H', H)
            self._update_tracked_value('K', K)
            self._update_tracked_value('L', L)
        except Exception as exc:
            self.print_to_message_center(f"HKL update from Q failed: {exc}")
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            # Update sample/instrument angles based on Q (skip if change originated from angles)
            if not skip_angle_update:
                self.update_angles_from_q()
    
    def on_HKL_changed(self):
        """Update Q when HKL changes."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        
        try:
            H = float(self.window.scattering_dock.H_edit.text() or 0)
            K = float(self.window.scattering_dock.K_edit.text() or 0)
            L = float(self.window.scattering_dock.L_edit.text() or 0)
            
            # Check if any HKL value actually changed (avoid spurious editingFinished triggers)
            h_changed = self._field_value_changed('H', H)
            k_changed = self._field_value_changed('K', K)
            l_changed = self._field_value_changed('L', L)
            
            if not (h_changed or k_changed or l_changed):
                # No actual change - skip update
                return
            
            self.updating = True
            qx, qy, qz = self._hkl_to_sample_q(H, K, L, vals)
            self.window.scattering_dock.qx_edit.setText(format_editable_number(qx))
            self.window.scattering_dock.qy_edit.setText(format_editable_number(qy))
            self.window.scattering_dock.qz_edit.setText(format_editable_number(qz))
            # Update tracked values for Q since we just set them
            self._update_tracked_value('qx', qx)
            self._update_tracked_value('qy', qy)
            self._update_tracked_value('qz', qz)
        except Exception as exc:
            self.print_to_message_center(f"Q update from HKL failed: {exc}")
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            # Update sample/instrument angles based on Q
            self.update_angles_from_q()
    
    def on_lattice_changed(self):
        """Update HKL when lattice parameters change. Q stays constant (machine config)."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            self.print_to_message_center(
                "Lattice not applied: a GUI field does not read as a number, "
                "so the UB was not moved to the lattice fields.")
            return
        
        try:
            # Q is fixed (machine configuration), recalculate HKL for new lattice
            qx = float(self.window.scattering_dock.qx_edit.text() or 0)
            qy = float(self.window.scattering_dock.qy_edit.text() or 0)
            qz = float(self.window.scattering_dock.qz_edit.text() or 0)
            
            self.updating = True
            # Update UB matrix B when lattice changes
            self.ub_matrix.set_lattice(
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma']
            )
            # The fields are now the UB's lattice: an open edit (a sample swap,
            # Refine Lattice or the API mid-edit) must not Discard back past it.
            self.window.sample_dock.end_lattice_edit()
            H, K, L = self._sample_q_to_hkl(qx, qy, qz, vals)
            self.window.scattering_dock.H_edit.setText(format_editable_number(H))
            self.window.scattering_dock.K_edit.setText(format_editable_number(K))
            self.window.scattering_dock.L_edit.setText(format_editable_number(L))
            # Update tracked values for HKL since we just set them
            self._update_tracked_value('H', H)
            self._update_tracked_value('K', K)
            self._update_tracked_value('L', L)
            
            self.print_to_message_center(
                f"Lattice updated: HKL = ({H:.4f}, {K:.4f}, {L:.4f}) for Q = ({qx:.4f}, {qy:.4f}, {qz:.4f}) Å⁻¹"
            )
            self.request_reciprocal_snapshot()
        except Exception as e:
            self.print_to_message_center(f"Error updating HKL from lattice: {e}")
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
        # The lattice is belief too: the UB display and the lock's stale mark
        # follow it.
        self._update_ub_display()

    def update_angles_from_q(self):
        """Update instrument/sample angles based on current Q and deltaE."""
        if self.updating:
            return
        vals = self.get_gui_values()
        if not vals:
            return
        try:
            self.updating = True
            angles_array, error_flags = self.instrument_state.calculate_stage_angles(
                vals['qx'], vals['qy'], vals['qz'], vals['deltaE'],
                vals['fixed_E'], vals['K_fixed'],
                vals['monocris'], vals['anacris'],
                locked=self.instrument_state.plane_lock,
            )
            if not error_flags:
                mtt, stt, sth, sgl, att, sgu = angles_array
                self._set_tracked_angle_text('mtt', self.window.instrument_dock.mtt_edit, mtt)
                self.window.instrument_dock.stt_edit.setText(format_editable_number(stt))
                self.window.instrument_dock.omega_edit.setText(format_editable_number(sth))
                self.window.instrument_dock.sgl_edit.setText(format_editable_number(sgl))
                self.window.instrument_dock.sgu_edit.setText(format_editable_number(sgu))
                self._set_tracked_angle_text('att', self.window.instrument_dock.att_edit, att)
                # Update tracked values for angles since we just set them
                self._update_tracked_value('omega', sth)
                self._update_tracked_value('sgl', sgl)
                self._update_tracked_value('sgu', sgu)
                self._update_tracked_value('stt', stt)
                self._set_angles_stale(None)
            else:
                # A stage refusal is new with the arcs' travel: say why the
                # angles were left as they were, in the solver's words, and
                # mark them stale until a solve succeeds or an angle is edited.
                stage = [f for f in error_flags if f.startswith(STAGE_FLAG_PREFIX)]
                if stage:
                    reason = describe_scan_error_flags(stage)
                    self.print_to_message_center(f"Angles not updated: {reason}")
                    self._set_angles_stale(reason)
        except Exception as exc:
            self.print_to_message_center(f"Angle update from Q failed: {exc}")
        finally:
            self._commit_programmatic_feedback()
            self.updating = False
            self.update_ideal_bending_buttons()
    
    def _set_angles_stale(self, reason):
        """Mark the angle fields as not matching Q/HKL (``reason``, the
        stage's refusal) or clear the mark (None). Take Position refuses
        while they are stale."""
        self._angles_stale = reason
        label = self.window.instrument_dock.angles_stale_label
        if reason:
            label.setText(f"Angles above are stale (they do not match Q/HKL): {reason}")
        label.setVisible(bool(reason))

    def update_monocris_info(self):
        """Update monochromator crystal information."""
        monocris = self.window.instrument_dock.selected_mono_id()
        anacris = self.window.instrument_dock.selected_ana_id()
        self.monocris_info, _ = self.instrument.crystal_info(monocris, anacris)
        self.update_all_variables()

    def update_anacris_info(self):
        """Update analyzer crystal information."""
        monocris = self.window.instrument_dock.selected_mono_id()
        anacris = self.window.instrument_dock.selected_ana_id()
        _, self.anacris_info = self.instrument.crystal_info(monocris, anacris)
        self.update_all_variables()
    
    def validate_scan_commands(self):
        """Validate scan commands for errors, typos, and parameter conflicts.
        
        This checks:
        1. Unknown/invalid variable names (typos)
        2. Malformed commands (wrong number of parts, invalid numbers)
        3. Suspicious parameters (e.g., > 1000 scan points)
        4. Whether the pair compiles: the plan Run would build now refuses a
           command its calculation computes or another setting holds, in the
           plan's own words (``rules.build_plan``)
        """
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        
        # Clear all previous warnings
        self.window.simulation_dock.clear_all_scan_warnings()
        
        # Validate each command individually, against the crystals the dock
        # currently shows -- this path exists to annotate those widgets.
        dock = self.window.instrument_dock
        monocris, anacris = dock.selected_mono_id(), dock.selected_ana_id()
        modules = dock.module_values()
        curvature_axes = self._curvature_axis_specs(monocris, anacris, modules=modules)
        relative_1 = self.window.simulation_dock.relative_1_button.isChecked()
        relative_2 = self.window.simulation_dock.relative_2_button.isChecked()
        current_values = self._current_curvature_field_values()
        var1, warning1 = self._validate_single_scan_command(
            cmd1, curvature_axes, relative=relative_1,
            current_values=current_values,
        )
        var2, warning2 = self._validate_single_scan_command(
            cmd2, curvature_axes, relative=relative_2,
            current_values=current_values,
        )

        if warning1:
            self.window.simulation_dock.set_scan_command_warning(1, warning1)
        if warning2:
            self.window.simulation_dock.set_scan_command_warning(2, warning2)
        
        # Each command read alone: the scan (a pair, or a lone command an engine or a
        # setting cannot honour) is the plan's to judge.
        if (var1 or var2) and (var1 or not warning1) and (var2 or not warning2):
            try:
                self._preview_launch(cmd1, cmd2)
            except PlanRefused as refused:
                self.window.simulation_dock.set_scan_conflict_warning(
                    str(refused), refused.command)
    
    def _curvature_axis_specs(self, monocris, anacris, modules=None):
        """{axis: (CurvatureAxis, crystal display name)} for the two named
        crystals, resolved against the current (or supplied) module state.

        The crystal resolution the scan-command gate reads, keeping each
        axis's full resolved declaration -- fixed radius AND
        mechanical travel -- rather than reducing it to fixed-axis
        membership. ``curvature_command_error`` needs both: a HELD radius or
        a scan-range endpoint can be refused for either reason, and the
        refusal must judge it against the identical declaration the scan will
        actually run with, not the GUI's live selection (an API request can
        name different crystals or modules).

        Resolution runs through ``self.instrument_state.
        effective_curvature_axis`` -- the one place a crystal's declaration
        and the live module state (e.g. a nested mirror optic) are folded
        together -- rather than reading ``CrystalSpec.curvature`` directly,
        which would recreate the raw, module-blind view this method used to
        return.
        ``modules`` mirrors that resolver's own override argument: ``None``
        reads live module state; an explicit mapping (e.g. from a frozen API
        request) wins over it.
        """
        specs = {}
        for selected_id, crystal_specs, label in (
            (monocris, self.descriptor.mono_crystals, "monochromator"),
            (anacris, self.descriptor.ana_crystals, "analyser"),
        ):
            for spec in crystal_specs:
                if spec.id == selected_id:
                    for axis in ("rhm", "rvm") if label == "monochromator" else ("rha", "rva"):
                        specs[axis] = (
                            self.instrument_state.effective_curvature_axis(
                                axis, spec, modules=modules
                            ),
                            f"{spec.display_name} {label}",
                        )
                    break
        return specs

    def _askable_curvature_axes(self, monocris, anacris, modules=None):
        """Axes the GUI's advisory Ideal labels may ask a radius for.

        One caller, on purpose: ``_compute_ideal_bending_values`` wants an
        answer for every axis that HAS a focusing model so that an
        unrelated axis with none (IN12's Heusler ``rva``, driven with
        ``focusing_known=False``) does not blank the other three labels.
        That is an advisory-display question. The API's launch refresh
        (``build_api_launch_state``, ``_default_parameter_values``) asks a
        different one -- which axes this launch will actually AUTOFOCUS --
        and deliberately does NOT filter through here: an unaskable axis
        that is genuinely AUTOFOCUS, unpinned and unscanned must reach
        ``ideal_curvature`` and be refused naming the axis, because there
        is no radius to run with. The GUI can never put such an axis into
        AUTOFOCUS (its Ideal button is disabled), so the two paths do not
        disagree on any reachable launch; they answer different questions.
        """
        axis_specs = self._curvature_axis_specs(monocris, anacris, modules=modules)
        return {
            axis for axis in ('rhm', 'rvm', 'rha', 'rva')
            if not (axis_specs.get(axis) and axis_specs[axis][0].driven
                    and not axis_specs[axis][0].focusing_known)
        }

    def _scan_named_curvature_axes(self, cmd1, cmd2):
        """{axis} named by either scan command's first token, normalized.

        Shared by ``_held_curvature_issues`` (GUI) and
        ``build_api_launch_state``'s HELD loop (API): a scan command that
        names a curvature axis is about to promote it to SCANNED --
        ``compute_scan_snapshot`` drives it point by point -- so a HELD
        refusal on that axis's CURRENT field/patch value would refuse a
        number the scan never actually uses. An unlocked rhm field at 1.0
        (below a driven axis's declared minimum) plus a legal absolute
        "rhm 3.0 4.0 0.5" must not be refused for the 1.0 the scan
        overrides at every point.
        """
        named = set()
        for cmd in (cmd1, cmd2):
            cmd = (cmd or "").strip()
            if not cmd:
                continue
            axis = self._RADIUS_AXES.get(self.normalize_scan_variable(cmd.split()[0]))
            if axis:
                named.add(axis)
        return named

    def _held_curvature_issues(self, monocris, anacris, scan_named_axes=None):
        """Hard-refusal messages for a HELD curvature radius, straight from
        the instrument-dock widgets.

        Only an axis the operator actually commanded is checked -- one whose
        Ideal lock is off, i.e. HELD, not AUTOFOCUS (``is_bending_locked``
        mirrors the same read ``get_gui_values`` uses to set
        ``curvature_modes``) -- AND not named by a non-empty scan command
        (``scan_named_axes``, from ``_scan_named_curvature_axes``): that axis
        is about to be promoted to SCANNED, so its current field value is not
        what the scan will actually run with (D21). Refusing an AUTOFOCUS
        ideal would break a legitimate scan whose optimum leaves the
        bender's reach; nobody chose that number, so there is nothing to
        refuse. Runs the identical ``curvature_command_error`` check
        ``build_api_launch_state`` runs on a patched value, so an operator
        and an API client see the same sentence for the same out-of-travel
        value.
        """
        from instruments.tas_runtime import curvature_command_error

        idock = self.window.instrument_dock
        axis_edits = {
            "rhm": idock.rhm_edit, "rvm": idock.rvm_edit, "rha": idock.rha_edit,
            "rva": idock.rva_edit,
        }
        curvature_axis_specs = self._curvature_axis_specs(
            monocris, anacris, modules=idock.module_values()
        )
        scan_named_axes = scan_named_axes or set()
        issues = []
        for axis, edit in axis_edits.items():
            if self.is_bending_locked(axis) or axis in scan_named_axes:
                continue
            axis_spec = curvature_axis_specs.get(axis)
            if axis_spec is None:
                continue
            curvature_axis, crystal_name = axis_spec
            try:
                value = float(edit.text())
            except ValueError:
                # A non-numeric radius cannot reach a launch at all:
                # get_gui_values() returns None for any unparseable field and
                # _collect_simulation_launch_state bails on that, so there is
                # no commanded value here to accept or refuse and skipping is
                # not a hole. An empty field is missing, not 0 (flat): the
                # launch snapshot leaves it out and the plan refuses naming it.
                continue
            error = curvature_command_error(axis, value, curvature_axis, crystal_name)
            if error:
                issues.append(error)
        return issues

    def _validate_single_scan_command(self, command: str, curvature_axes=None,
                                      relative=False, current_values=None) -> tuple:
        """Validate a single scan command and return (variable_name, warning_message).

        ``curvature_axes`` is the {axis: (CurvatureAxis, crystal)} mapping from
        ``_curvature_axis_specs`` for the crystals this scan will actually run
        with; omitted means no scan range is checked against mechanical travel.
        A fixed axis is not checked here: the plan refuses it, naming the
        hardware. A commanded scan endpoint
        outside a driven axis's declared travel is refused the same as a HELD
        value would be, via ``curvature_scan_error`` -- the operator asked for
        the whole range, so every value it expands to is checked, not just the
        two endpoints (an absolute ``"rhm 0 2 1"`` on an axis with a 2.0 m
        declared minimum has legal endpoints and an illegal interior point at
        1.0 m).

        ``relative`` is THIS command's own relative-mode flag (a 2D scan's two
        commands set it independently). For a relative command the literal
        start/end are offsets from the current radius, not the requested radii
        themselves; ``current_values`` (an {axis: float-or-None} mapping of the
        launch's current curvature values, from the GUI's instrument-dock
        fields or the API's frozen ``vals``) supplies the base a relative
        command is expanded against. A relative command on an axis whose
        current value is missing or non-numeric is a hard issue naming the
        field -- there is no base to expand the offsets against.

        A returned variable of ``None`` alongside a warning is a *hard*
        rejection -- the command cannot run as written. Callers must treat it
        as blocking; see ``_validate_scan_commands_text``.

        Returns:
            tuple: (normalized_variable_name or None, warning_message or None)
        """
        from gui.docks.unified_simulation_dock import (
            SCAN_VARIABLE_SHORT_NAMES, VALID_SCAN_VARIABLES)

        if not command:
            return (None, None)
        
        parts = command.split()
        
        # Check for minimum parts (variable, start, end, step)
        if len(parts) < 4:
            return (None, "Incomplete: needs 'variable start end step'")
        
        if len(parts) > 4:
            return (None, "Too many parts: use 'variable start end step'")
        
        var_name = parts[0]
        try:
            var_id = resolve_quantity(var_name, "scan").id
        except UnknownQuantity:
            var_lower = var_name.lower()
            suggestions = [v for v in sorted(VALID_SCAN_VARIABLES)
                           if var_lower in v or v in var_lower]
            if suggestions:
                return (None, f"Unknown variable '{var_name}'. Did you mean: {', '.join(suggestions)}?")
            return (None, f"Unknown variable '{var_name}'. Valid: "
                          f"{', '.join(SCAN_VARIABLE_SHORT_NAMES)}")
        except QuantityRefused as refused:
            # Derived angles, retired names, old slit names: the registry's words.
            return (None, str(refused))

        axis = self._RADIUS_AXES.get(var_id)

        # Validate numeric parts
        try:
            start = float(parts[1])
            end = float(parts[2])
            step = float(parts[3])
        except ValueError:
            return (None, "Invalid numbers. Check start, end, and step values.")

        range_error = scan_range_error(start, end, step)
        if range_error:
            return (None, range_error)

        # After the step guards: the expansion below divides by the step and
        # calls parse_scan_steps, so a zero or wrong-sign step must have been
        # refused already -- mid-keystroke text like 'rhm 2 4 0' reaches
        # this validator from textChanged.
        # A commanded scan range on a driven curvature axis is refused, not
        # clamped, when any value it expands to falls outside its declared
        # mechanical travel -- the operator wrote the range deliberately.
        # Absolute and relative commands are both checked here now: a
        # relative command's real requested radii are the current value plus
        # every offset ``parse_scan_steps`` would produce, which needs a base
        # value from ``current_values``.
        axis_spec = (curvature_axes or {}).get(axis)
        # A fixed axis is the plan's refusal (it names the hardware), not a travel check.
        if axis_spec is not None and axis_spec[0].driven:
            curvature_axis, crystal_name = axis_spec
            base_value = None
            if relative:
                base_value = (current_values or {}).get(axis)
                if base_value is None:
                    return (None, f"'{var_name}' is a relative curvature scan "
                                  f"but its current value is not numeric.")
            from instruments.tas_runtime import curvature_scan_error

            error = curvature_scan_error(
                axis, start, end, step, relative, base_value,
                curvature_axis, crystal_name,
            )
            if error:
                return (None, error)

        # Calculate number of points and warn if too many or too few
        import numpy as np
        num_points = int(np.floor(abs(end - start) / abs(step) + 0.5)) + 1
        
        if num_points > 1000:
            return (var_id, f"⚠ {num_points} points - this may take a very long time!")
        elif num_points > 500:
            return (var_id, f"Warning: {num_points} scan points. Consider fewer steps.")
        elif num_points == 1:
            return (var_id, f"⚠ Only 1 scan point! Step ({step}) larger than range ({start} to {end}).")
        elif num_points <= 0:
            return (None, "Invalid range: no points would be generated.")
        
        return (var_id, None)
    
    # A requested-radius quantity -> the curvature axis (state field) it drives.
    _RADIUS_AXES = {qid: _to_internal(qid) for qid in RADIUS_CRYSTAL}

    def _trigger_scan_update(self):
        """Trigger a debounced update of scan estimates."""
        self._scan_update_timer.start()

    def _pending_needs_compile(self):
        """Whether the next McStas scan would compile (no binary reuse).

        Mirrors the pre-scan reuse check so the debounced GUI estimate can drop
        compile time when the current binary will be reused. Degrades to True
        (assume a rebuild, matching the pre-rework behavior of always adding
        compile time) on any failure or when reuse state is unavailable.
        """
        try:
            vals = self.get_gui_values()
            if not vals:
                return True
            diagnostic_mode = bool(vals.get('diagnostic_mode'))
            effective = self.diagnostic_settings if diagnostic_mode else {}
            try:
                sample_key = self.window.sample_dock.get_selected_sample_key()
            except Exception:
                sample_key = None
            scan_config = self.instrument.scan_config(
                self.instrument_state, vals, sample_key, self.diagnostic_settings,
                self._build_sample_mount(vals),
            )
            fingerprint = self.instrument.build_fingerprint(
                scan_config, diagnostic_mode, effective,
            )
            return not self._can_reuse_binary(
                self._binary_reuse_cache, fingerprint, diagnostic_mode,
            )
        except Exception:
            return True

    def set_mpi_count(self, n):
        """Persist and apply the MPI process count (Config menu).

        Saves first, so a failed write (``OSError``, propagated to the caller)
        leaves the in-memory count unchanged. Applies from the next scan.
        """
        save_mpi_count(n)
        self.mpi_count = int(n)
        self.print_to_message_center(
            f"MPI processes set to {n}; applies from the next scan."
        )
        self.runtime_data_updated.emit()

    def _estimate_total_and_compile(self, instrument_name, num_points,
                                    num_neutrons, needs_compile,
                                    engine="mcstas"):
        """Total-seconds + compile-seconds for the GUI estimate labels.

        Uses the machine-aware estimator for the selected ``engine``. The
        deterministic engine has no compilation, so ``needs_compile`` is forced
        off and no compile label is surfaced. Otherwise compile is surfaced only
        when a rebuild is pending; it is derived as the estimate for zero scan
        points (compile only). Returns ``(total_seconds|None,
        compile_seconds|None)``.
        """
        if engine == "deterministic":
            needs_compile = False
        est = self.runtime_tracker.estimate_scan_seconds(
            instrument_name, num_points, num_neutrons,
            needs_compile=needs_compile, engine=engine,
            mpi_count=self.mpi_count,
        )
        total = est.get("estimated_seconds")
        compile_seconds = None
        if total is not None and needs_compile:
            compile_seconds = self.runtime_tracker.estimate_scan_seconds(
                instrument_name, 0, num_neutrons,
                needs_compile=True, engine=engine, mpi_count=self.mpi_count,
            ).get("estimated_seconds")
        return total, compile_seconds

    def _update_scan_estimates(self):
        """Update all scan time estimates based on current settings.
        
        This is called after a debounce delay when scan commands or neutron count change.
        It updates:
        1. Time per point estimate (next to neutron count)
        2. Point count breakdown (below scan commands)
        3. Total time estimate (below point count)
        """
        import numpy as np
        
        # Get current values
        try:
            num_neutrons = self.window.simulation_dock.get_number_neutrons()
        except ValueError:
            num_neutrons = 1000000
        
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()

        # The plan compiles the boxes as typed (a lone command 2 keeps its box
        # and its relative flag); the counts shown put a lone command first.
        boxes = (cmd1, cmd2)
        if cmd2 and not cmd1:
            cmd1, cmd2 = cmd2, ""

        # Get instrument name
        instrument_name = self.instrument.id

        # GUI-selected execution engine drives which timing history is read and
        # how the labels read (the analytic engine is fast and never compiles).
        try:
            engine = self.window.simulation_dock.get_selected_engine()
        except Exception:
            engine = 'mcstas'

        # Whether the next McStas run would compile (drops compile time from the
        # total estimate when the current binary will be reused). The
        # deterministic engine never compiles.
        needs_compile = (False if engine == "deterministic"
                         else self._pending_needs_compile())

        # Update time per point estimate (affine per-point cost for the engine).
        run_time_per_point = self.runtime_tracker.estimate_scan_seconds(
            instrument_name, 1, num_neutrons, needs_compile=False, engine=engine,
            mpi_count=self.mpi_count,
        ).get("per_point_seconds")
        if engine == "deterministic":
            # Analytic cost is ~independent of ncount and sub-second; never show
            # an hours-scale mcstas figure or a "No timing data" scare for it.
            if run_time_per_point is None or run_time_per_point < 1.0:
                time_str = "< 1s/point (analytic)"
            else:
                time_str = f"~{RuntimeTracker.format_time(run_time_per_point)}/point"
            self.window.simulation_dock.update_time_per_point(time_str)
        elif run_time_per_point is not None:
            time_str = f"~{RuntimeTracker.format_time(run_time_per_point)}/point"
            self.window.simulation_dock.update_time_per_point(time_str)
        else:
            self.window.simulation_dock.update_time_per_point("No timing data")
        
        # Calculate point counts
        count1, count2 = 0, 0
        valid_count = 0
        invalid_count = 0
        single_point_invalid = False
        
        if cmd1:
            try:
                _, array1 = parse_scan_steps(cmd1)
                count1 = len(array1)
            except Exception:
                count1 = 0
        
        if cmd2:
            try:
                _, array2 = parse_scan_steps(cmd2)
                count2 = len(array2)
            except Exception:
                count2 = 0
        
        # Calculate total points for determining if precalculation should be skipped
        total_potential_points = count1 * count2 if (count1 > 0 and count2 > 0) else max(count1, count2)
        
        # If >1000 points, defer validation to avoid GUI hang
        if total_potential_points > 1000:
            self.print_to_message_center(f"⚠ {total_potential_points} scan points - validation deferred until simulation starts")
            self.window.simulation_dock.update_point_count_display_deferred(count1, count2)
            # Still show time estimate based on total points (assume all valid for estimate)
            total_time, compile_time = self._estimate_total_and_compile(
                instrument_name, total_potential_points, num_neutrons,
                needs_compile, engine=engine
            )
            if total_time is not None:
                total_str = RuntimeTracker.format_time(total_time)
                compile_str = RuntimeTracker.format_time(compile_time) if compile_time else ""
                self.window.simulation_dock.update_total_time_estimate(total_str, compile_str)
            else:
                self.window.simulation_dock.update_total_time_estimate("")
            return
        
        # Calculate valid/invalid counts
        if count1 > 0 or count2 > 0:
            valid_count, invalid_count = self._count_valid_scan_points(*boxes)
        else:
            # Single point mode - check if current position is valid
            valid, _ = self._check_current_point_validity()
            if valid:
                valid_count = 1
                invalid_count = 0
            else:
                valid_count = 0
                invalid_count = 1
                single_point_invalid = True
        
        total_points = valid_count + invalid_count
        all_invalid = (valid_count == 0 and total_points > 0)
        
        # Update point count display
        self.window.simulation_dock.update_point_count_display(
            count1, count2, valid_count, invalid_count, all_invalid or single_point_invalid
        )
        
        # Update total time estimate
        total_time, compile_time = self._estimate_total_and_compile(
            instrument_name, valid_count, num_neutrons, needs_compile,
            engine=engine
        )
        if total_time is not None:
            total_str = RuntimeTracker.format_time(total_time)
            compile_str = RuntimeTracker.format_time(compile_time) if compile_time else ""
            self.window.simulation_dock.update_total_time_estimate(total_str, compile_str)
        else:
            self.window.simulation_dock.update_total_time_estimate("")
    
    def _preview_launch(self, cmd1, cmd2):
        """``(launch_state, plan, expansion)`` that pressing Run now would compile.

        The launch is collected exactly as Run collects it (dock fields,
        relative flags, engine) with ``cmd1``/``cmd2`` as the commands, then
        compiled by the one compile-and-expand. Raises ``PlanRefused``.
        """
        launch_state = self._collect_simulation_launch_state()
        if not launch_state:
            raise PlanRefused("A field does not hold a number, so nothing can be planned.")
        launch_state['vals']['scan_command1'] = cmd1
        launch_state['vals']['scan_command2'] = cmd2
        plan, expansion = self._compile_launch(launch_state)
        return launch_state, plan, expansion

    def _count_valid_scan_points(self, cmd1: str, cmd2: str) -> tuple:
        """``(valid, invalid)`` points of the scan Run would compile now.

        A command the plan refuses counts nothing: ``(0, 0)``.
        """
        try:
            launch_state, plan, expansion = self._preview_launch(cmd1, cmd2)
        except PlanRefused:
            return (0, 0)
        state = launch_state['scan_config']
        valid = sum(self._point_runs(plan, point, state) for point in expansion.points)
        return (valid, len(expansion.points) - valid)

    def _point_runs(self, plan, point, state) -> bool:
        """True when the run would execute this point: the one validity rule of
        the GUI point count, the time estimate and the run's 1D/2D valid masks.
        It is the plan's own guard (``rules.check_point``: the run's per-point
        solve on a private copy of ``state``, then the engine's), so every
        calculation is judged as the run judges it. No axis limits are applied,
        as the GUI Run applies none (the API validation adds them).
        """
        try:
            return check_point(plan, point, state).feasible
        except Exception as exc:
            log.warning("Scan point %s (%s) could not be checked: %s",
                        point, plan.calculation, exc)
            return False

    def _check_current_point_validity(self) -> tuple:
        """Whether the point a Run with no scan command would run is valid: that
        plan's one point (ruling 5: the motors as the docks show them), judged
        as the scan count judges its points (``_point_runs``).

        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            launch_state, plan, expansion = self._preview_launch("", "")
            check = check_point(plan, expansion.points[0], launch_state['scan_config'])
            return (check.feasible, check.reason or "")
        except PlanRefused as refused:
            return (False, str(refused))
        except Exception as e:
            log.warning("Current point could not be checked: %s", e)
            return (False, str(e))

    def on_omega_changed(self):
        """Handle omega (ω) change - sample in-plane rotation."""
        if self.updating:
            return
        try:
            omega = float(self.window.instrument_dock.omega_edit.text() or 0)
            # Only update if value actually changed (avoid spurious editingFinished signals)
            if not self._field_value_changed('omega', omega):
                return
            self.print_to_message_center(f"Sample A3 updated: {omega}°")
            # Trigger angle-based updates
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid omega value")
    
    def on_arc_changed(self):
        """Handle an arc readout (sgl / sgu) edit: the arcs move Q out of the
        plane, so Q is read back from the angles."""
        if self.updating:
            return
        try:
            idock = self.window.instrument_dock
            sgl = float(idock.sgl_edit.text() or 0)
            sgu = float(idock.sgu_edit.text() or 0)
            if not (math.isfinite(sgl) and math.isfinite(sgu)):
                # Refused outright (unlike a value past travel): the fields
                # go back to the arcs the instrument holds.
                reason = describe_scan_error_flags(
                    self.instrument_state.arc_travel_flags({"sgl": sgl, "sgu": sgu}))
                self.print_to_message_center(f"Arc refused: {reason}")
                self._set_and_confirm_field(idock.sgl_edit, self.instrument_state.sgl, force=True)
                self._set_and_confirm_field(idock.sgu_edit, self.instrument_state.sgu, force=True)
                return
            # Evaluate both: an unchanged pair is a spurious editingFinished.
            changed = [self._field_value_changed('sgl', sgl),
                       self._field_value_changed('sgu', sgu)]
            if not any(changed):
                return
            self.instrument_state.sgl, self.instrument_state.sgu = sgl, sgu
            self.print_to_message_center(f"Sample arcs updated: sgl = {sgl}°, sgu = {sgu}°")
            # The field keeps the value; an angle-mode run refuses it.
            past = self.instrument_state.arc_travel_flags({"sgl": sgl, "sgu": sgu})
            if past:
                self.print_to_message_center(
                    f"Arc outside travel: {describe_scan_error_flags(past)}")
            self.on_angles_changed()
        except ValueError:
            self.print_to_message_center("Invalid arc (sgl/sgu) value")
    
    # ===== The true mount and the one loaded exercise =====
    # U_true = R_hidden @ U_described is the truth the McStas sample arm and
    # the analytic engine read; the operator's UB is belief and none of the
    # paths below write it except to reset it to U_described (I3).

    def _set_true_mount(self, U_described=None, R_hidden=None):
        """The one writer of ``instrument_state.U_true`` (R_hidden @ U_described)."""
        if U_described is not None:
            self.U_described = np.array(U_described, dtype=float)
        if R_hidden is not None:
            self.R_hidden = np.array(R_hidden, dtype=float)
        self.instrument_state.U_true = self.R_hidden @ self.U_described

    def _exercise_reach_error(self, rotation, u_described, sample_key, monocris, anacris,
                              K_fixed, fixed_E):
        """Why a hidden mount ``rotation`` cannot be observed (None when it
        can), judged on the sample, described mount, crystals and fixed
        energy GIVEN: the live ones for a generation or a load, a saved
        file's for a restore. Never the live ones by default."""
        spec = next((s for s in self.descriptor.samples if s.id == sample_key), None)
        if spec is None or spec.lattice is None:
            return "no sample with a crystal is selected, so there is nothing to observe"
        if spec.reflection_source is None and spec.space_group is None:
            # reference_hkls would fall back to every hkl here (no centering rule to apply).
            return "this sample has no Bragg reflections to align on; choose a Bragg sample"
        state = self.instrument.default_state()
        state.monocris, state.anacris = monocris, anacris
        state.K_fixed, state.fixed_E = K_fixed, fixed_E
        hkls = reference_hkls(spec.reflection_source, spec.space_group, COMPONENTS_DIR)
        return training_reach_error(state, rotation @ np.asarray(u_described, dtype=float),
                                    compute_B_matrix(*spec.lattice), hkls,
                                    self.descriptor.axis_limits)

    def _live_reach_error(self, rotation):
        """``_exercise_reach_error`` on what the windows show now."""
        vals = self.get_gui_values()
        if not vals:
            return "a field does not read as a number"
        return self._exercise_reach_error(
            rotation, self.U_described, self.window.sample_dock.get_selected_sample_key(),
            vals['monocris'], vals['anacris'], vals['K_fixed'], vals['fixed_E'])

    def _apply_exercise(self, hash_str, rotation):
        """The loaded exercise becomes ``hash_str`` with hidden rotation
        ``rotation``: R_hidden and the docks' display, nothing else -- no UB
        write, no lock check, no judgement (callers have made it)."""
        self._set_true_mount(R_hidden=rotation)
        self._exercise = hash_str
        self._show_exercise()

    def _install_exercise(self, hash_str):
        """Make ``hash_str`` the loaded exercise. Raises ValueError, before
        anything changes, for a code that is not a mount-only exercise (see
        ``decode_mount_exercise``) or that this instrument cannot observe."""
        rotation = decode_mount_exercise(hash_str)
        reason = self._live_reach_error(rotation)
        if reason:
            raise ValueError(f"the instrument cannot observe this exercise: {reason}")
        self._apply_exercise(hash_str, rotation)

    def _clear_exercise(self):
        """No exercise: R_hidden = I."""
        self._exercise = None
        self._set_true_mount(R_hidden=np.eye(3))
        self._show_exercise()

    def _show_exercise(self):
        """The UB dock shows the controller's exercise state (hash field and
        status); it holds no hidden value."""
        ub_dock = self.window.ub_matrix_dock
        ub_dock.load_hash_edit.setText(self._exercise or "")
        ub_dock.update_training_status(self._exercise is not None)

    def _exercise_refusal(self, action):
        """Why ``action`` ("load"/"clear") of the exercise is refused, or
        None. A locked plane's physical tilt never moves: release it first."""
        if self._lock_text():
            return (f"Cannot {action} the exercise: it would move "
                    f"{self._lock_text()}. Release the lock first.")
        return None

    def _reset_ub_to_described(self):
        """The operator's UB back to the sample as described, peaks kept."""
        self.ub_matrix.set_U(self.U_described)
        self._update_ub_display()
        self.on_Q_changed()

    def _true_B(self):
        """The selected sample's own B (its baked ``SampleSpec.lattice``, the
        one McStas diffracts from), never the lattice fields. ValueError with
        the reason when no crystal is selected."""
        key = self.window.sample_dock.get_selected_sample_key()
        spec = next((s for s in self.descriptor.samples if s.id == key), None)
        if spec is None or spec.lattice is None:
            raise ValueError("no sample is selected, so there is no crystal to mount")
        return compute_B_matrix(*spec.lattice)

    def _remount(self, plane):
        """I2: a description change, not a UB write. ``plane`` is
        ((h k l) along x, (h k l) in plane), or None for the standard setting.
        Sets U_described (R_hidden kept), resets the operator's UB to it,
        peaks kept. Raises ValueError, changing nothing, when refused --
        under a lock too (amendment 7): a remount moves the locked plane."""
        if self._lock_text():
            raise ValueError(f"it would move {self._lock_text()}; release the lock first")
        if plane is None:
            described = np.eye(3)
        else:
            described = u_from_plane(self._true_B(), *plane)
        self.mount_plane = plane
        self._set_true_mount(U_described=described)
        self._show_mount_plane()
        self._reset_ub_to_described()

    def _show_mount_plane(self):
        """The sample dock shows the controller's described mount."""
        self.window.sample_dock.show_mount_plane(
            self.mount_plane, standard=np.array_equal(self.U_described, np.eye(3)))

    def on_apply_mount_plane(self):
        """Apply the sample dock's mounting plane (both fields empty = Clear)."""
        dock = self.window.sample_dock
        texts = (dock.mount_u_edit.text().strip(), dock.mount_v_edit.text().strip())
        if not any(texts):
            self.on_clear_mount_plane()
            return
        try:
            plane = tuple(self._parse_hkl_triple(text) for text in texts)
            self._remount(plane)
        except ValueError as e:
            self.print_to_message_center(f"Mounting plane refused: {e}")
            self._show_mount_plane()
            return
        u_text, v_text = (" ".join(f"{x:g}" for x in hkl) for hkl in plane)
        self.print_to_message_center(
            f"Sample remounted with ({u_text}) along x and ({v_text}) in the horizontal "
            "plane; the UB starts at the new mount (peaks kept)")

    def on_clear_mount_plane(self):
        """Back to the standard setting; the UB starts at it (peaks kept)."""
        try:
            self._remount(None)
        except ValueError as e:
            self.print_to_message_center(f"Mounting plane refused: {e}")
            self._show_mount_plane()
            return
        self.print_to_message_center(
            "Sample remounted in the standard setting; the UB starts at it (peaks kept)")

    @staticmethod
    def _parse_hkl_triple(text):
        """'1 0 0' or '1, 0, 0' -> (1.0, 0.0, 0.0); ValueError otherwise."""
        parts = text.replace(",", " ").split()
        try:
            values = tuple(float(p) for p in parts)
        except ValueError:
            values = ()
        if len(values) != 3 or not all(math.isfinite(v) for v in values):
            raise ValueError(f"'{text}' is not three numbers h k l")
        return values

    def _mount_plane_fields(self):
        """Read-only API view of the described mount: the plane's two HKL
        vectors, or null when the mount is not from a plane."""
        u, v = self.mount_plane or (None, None)
        return {'mount_plane_u': list(u) if u is not None else None,
                'mount_plane_v': list(v) if v is not None else None}

    def _lock_text(self):
        """The locked plane in the solver's words ('the locked scattering
        plane (1 0 0)/(0 1 0) (sgl = 0°, sgu = 0°)'), or None when free."""
        lock = self.instrument_state.plane_lock
        if lock is None:
            return None
        return locked_plane_text(lock["tilts"], (lock["hkl_u"], lock["hkl_v"]))

    # ===== Lock plane (2.3): the tilts held for an experiment =====
    # The lock is operator state on instrument_state.plane_lock (C6 reads it
    # per point); _set_plane_lock is its one writer.

    # The programme's lock convention: the lock is stale once the operator's
    # UB no longer levels the locked plane at the locked tilts within this.
    LOCK_STALE_DEG = 0.05

    def _default_lock_plane(self):
        """The plane a Lock with empty fields takes: the mounting plane, else
        the first two peaks with an (h k l), else (1 0 0)/(0 1 0)."""
        if self.mount_plane is not None:
            return self.mount_plane
        hkls = [tuple(float(x) for x in p.hkl) for p in self._peaks_from_dock() if any(p.hkl)]
        return tuple(hkls[:2]) if len(hkls) >= 2 else ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))

    def _lock_for(self, plane, vals=None):
        """A plane_lock holding ``plane`` where the operator's UB levels it
        (``lock_plane``, inside travel). Raises ValueError (StageUnreachable
        included) with the reason."""
        vals = vals or self.get_gui_values()
        if not vals:
            raise ValueError("a field does not read as a number")
        tilts = lock_plane(self.instrument_state.goniometer,
                           self._build_sample_mount(vals).mounted_basis, *plane)
        return {"hkl_u": [float(x) for x in plane[0]], "hkl_v": [float(x) for x in plane[1]],
                "tilts": tilts}

    def _set_plane_lock(self, lock):
        """The one writer of the lock (None releases). Locking puts the arc
        readouts at the lock's tilts (one source for GUI and API launches, a
        restore included); while locked the arc fields are read-only with a
        tooltip naming the lock. The caller re-solves the angles
        (``_update_ub_display``)."""
        state = self.instrument_state
        state.plane_lock = lock
        idock = self.window.instrument_dock
        if lock is not None:
            state.sgl, state.sgu = lock["tilts"]["sgl"], lock["tilts"]["sgu"]
            idock.sgl_edit.setText(format_editable_number(state.sgl))
            idock.sgu_edit.setText(format_editable_number(state.sgu))
        held = f"Held by {self._lock_text()}; release the lock to change it." if lock else None
        for edit in (idock.sgl_edit, idock.sgu_edit):
            if edit.property("free_tooltip") is None:
                edit.setProperty("free_tooltip", edit.toolTip())
            edit.setReadOnly(lock is not None)
            edit.setToolTip(held or edit.property("free_tooltip"))
        self._show_plane_lock()

    def lock_stale(self, vals=None):
        """The one stale function (the UB dock and /state read it): True when
        the operator's UB no longer levels the locked plane at the locked
        tilts within LOCK_STALE_DEG, None when free or the fields do not read."""
        lock = self.instrument_state.plane_lock
        if lock is None:
            return None
        vals = vals or self.get_gui_values()
        if not vals:
            return None
        gonio = self.instrument_state.goniometer
        basis = self._build_sample_mount(vals).mounted_basis
        normal = stage_rotation(gonio[1:], lock["tilts"]) @ np.cross(
            basis @ np.asarray(lock["hkl_u"], dtype=float),
            basis @ np.asarray(lock["hkl_v"], dtype=float))
        up = np.asarray(gonio[0].axis, dtype=float)
        tilt = math.degrees(math.atan2(np.linalg.norm(np.cross(normal, up)), abs(normal @ up)))
        return bool(tilt > self.LOCK_STALE_DEG)

    def _lock_fields(self):
        """API view of the lock: orientation_mode, lock_plane."""
        lock = self.instrument_state.plane_lock
        return {
            'orientation_mode': "locked" if lock else "free",
            'lock_plane': {'u': list(lock["hkl_u"]), 'v': list(lock["hkl_v"])} if lock else None,
        }

    def _show_plane_lock(self, refusal=None):
        """The UB dock shows the controller's lock: plane, tilts, stale mark."""
        lock = self.instrument_state.plane_lock
        dock = self.window.ub_matrix_dock
        if lock is None:
            dock.show_plane_lock(None, f"Lock refused: {refusal}" if refusal
                                 else "Free: the arcs follow each Q")
            return
        plane = (lock["hkl_u"], lock["hkl_v"])
        tilts = ", ".join(f"{name} = {value:.4g}°" for name, value in lock["tilts"].items())
        stale = bool(self.lock_stale())
        status = f"Locked on {plane_text(plane)}: {tilts}"
        if stale:
            status += (f". STALE: the UB no longer levels this plane within "
                       f"{self.LOCK_STALE_DEG}°; release and lock again")
        dock.show_plane_lock(plane, status, stale)

    def on_lock_plane(self):
        """UB dock Lock: hold the plane of its two (h k l) fields (empty: the
        default plane) where the operator's UB levels it."""
        if self.instrument_state.plane_lock is not None:
            self.print_to_message_center(f"{self._lock_text()} is in force; release it first")
            return
        dock = self.window.ub_matrix_dock
        texts = (dock.lock_u_edit.text().strip(), dock.lock_v_edit.text().strip())
        try:
            plane = (tuple(self._parse_hkl_triple(text) for text in texts) if any(texts)
                     else self._default_lock_plane())
            lock = self._lock_for(plane)
        except ValueError as e:
            self.print_to_message_center(f"Lock refused: {e}")
            self._show_plane_lock(refusal=str(e))
            return
        self._set_plane_lock(lock)
        self._update_ub_display()
        self.print_to_message_center(
            f"Scattering plane locked: {self._lock_text()}; the tilts stay put")

    def on_release_plane(self):
        """UB dock Release: back to free mode, the arcs solved per Q."""
        if self.instrument_state.plane_lock is None:
            self.print_to_message_center("No scattering plane is locked")
            return
        self._set_plane_lock(None)
        self._update_ub_display()
        self.print_to_message_center("Scattering plane released: the arcs follow each Q again")

    def _restore_plane_lock(self, parameters):
        """Restore a saved lock after the hidden truth (an absent one means
        free). No interactive refusal runs; its tilts are re-checked against
        this stage's axes and travel (the solver's guard), and a lock that
        fails is released with a message."""
        raw = parameters.get("plane_lock")
        if raw is None:
            return
        try:
            lock = {"hkl_u": [float(x) for x in raw["hkl_u"]],
                    "hkl_v": [float(x) for x in raw["hkl_v"]],
                    "tilts": {str(name): float(v) for name, v in raw["tilts"].items()}}
            if len(lock["hkl_u"]) != 3 or len(lock["hkl_v"]) != 3:
                raise ValueError("the plane needs two (h k l) vectors")
            inner = self.instrument_state.goniometer[1:]
            missing = [ax.name for ax in inner if ax.name not in lock["tilts"]]
            if missing:
                raise ValueError(f"the lock does not set {', '.join(missing)}")
            check_travel(inner, lock["tilts"], " for the locked scattering plane")
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            self.print_to_message_center(f"Saved plane lock released: {e}")
            return
        self._set_plane_lock(lock)
        self._update_ub_display()
        self.print_to_message_center(f"Plane lock restored: {self._lock_text()}")

    def release_lock_for_switch(self):
        """I4: the confirmed instrument switch releases the lock and rewrites
        only the outgoing block's lock key (no full save, so the switch's
        "unsaved changes are lost" holds). Nothing is written when that
        block is absent or carries no lock. A failed write is reported and
        the switch goes ahead."""
        self._set_plane_lock(None)

        def drop_lock(document):
            block = document.get(self.instrument.id)
            if not isinstance(block, dict) or block.get("plane_lock") is None:
                return False
            block["plane_lock"] = None
            return True

        try:
            self._edit_parameters_file(drop_lock)
        except OSError as exc:
            self.print_to_message_center(
                f"Could not drop the plane lock from parameters.json ({exc}); "
                "it may be restored on the next start of this instrument")

    def _load_exercise(self, hash_str):
        """Interactive load (I3): refused under a lock and for a code that is
        not an observable mount-only exercise; then the hidden truth, and the
        operator's UB reset to U_described."""
        if not hash_str:
            self.print_to_message_center("No exercise hash entered")
            return False
        refusal = self._exercise_refusal("load")
        if refusal:
            self.print_to_message_center(refusal)
            return False
        try:
            self._install_exercise(hash_str)
        except ValueError as e:
            self.print_to_message_center(f"Exercise refused: {e}")
            return False
        self._reset_ub_to_described()
        return True

    def _unload_exercise(self):
        """Interactive clear (I3)."""
        refusal = self._exercise_refusal("clear")
        if refusal:
            self.print_to_message_center(refusal)
            return False
        if self._exercise is None:
            self.print_to_message_center("No exercise loaded")
            return False
        self._clear_exercise()
        self._reset_ub_to_described()
        return True

    def _grade_alignment(self):
        """The grader (``tavi.ub_matrix.grade_alignment``):
        the operator's peaks' HKLs plus three reflections of the mounting
        plane (u, v, u+v; with no plane described, the described mount's x
        and z as small (h k l) and their sum, else (1 0 0), (0 1 0),
        (1 1 0)), commanded by the operator's UB and lattice fields, against
        the truth (U_true, the sample's own B). Names the skipped reflections
        and the result in the message center; returns the grade, or None when
        it could not run."""
        try:
            vals = self.get_gui_values()
            state = self.instrument_state
            gonio = state.goniometer
            try:
                b_true = self._true_B()
            except ValueError:
                b_true = None           # graded "cannot assess", naming no sample
            hkls = [p.hkl for p in self._peaks_from_dock() if any(p.hkl)]
            if self.mount_plane is not None:
                u, v = (np.asarray(hkl, dtype=float) for hkl in self.mount_plane)
                hkls += [tuple(u), tuple(v), tuple(u + v)]
            else:
                # The described mount's horizontal x and z as small (h k l),
                # and their sum; the standard set when either has none.
                n1, n2 = ((small_integer_indices(axis, self.U_described @ b_true)
                           for axis in (np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])))
                          if b_true is not None else (None, None))
                if n1 is not None and n2 is not None:
                    hkls += [n1, n2, tuple(a + b for a, b in zip(n1, n2))]
                else:
                    hkls += [(1, 0, 0), (0, 1, 0), (1, 1, 0)]
                    if b_true is not None:
                        self.print_to_message_center(
                            "Alignment check grades (1 0 0), (0 1 0), (1 1 0): the described "
                            "mount's horizontal axes have no small (h k l)")
            grade = grade_alignment(
                gonio, state.sense_sample, vals['Ki'], vals['Kf'],
                self._build_sample_mount(vals).mounted_basis,
                state.U_true, b_true,
                hkls,
                # Commanded as the operator would drive: at the lock's tilts
                # when a plane is locked, else the free solve.
                locked=(state.plane_lock or {}).get("tilts"),
            )
        except Exception as e:
            self.print_to_message_center(f"Alignment check failed: {e}")
            return None
        for skipped in grade["skipped"]:
            self.print_to_message_center(f"Alignment check skipped {skipped}")
        self.print_to_message_center(f"Alignment check: {grade['summary']}")
        return grade

    # ===== UB Matrix Controller Methods =====

    def on_calculate_ub(self):
        """Calculate UB matrix from observed peaks in the UB dock."""
        # The lattice sync runs before the fit: a failed fit puts the
        # operator's UB and lattice back as they were (C3).
        belief = copy.deepcopy(self.ub_matrix)
        try:
            self.ub_matrix.peaks = self._peaks_from_dock()

            # Sync lattice from GUI
            vals = self.get_gui_values()
            if vals:
                self.ub_matrix.set_lattice(
                    vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                    vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
                )

            U = self.ub_matrix.calculate_U_from_peaks()
            belief = None
            self._update_ub_display()
            self.print_to_message_center(
                f"UB matrix calculated from {len([p for p in self.ub_matrix.peaks if p.is_valid])} peaks"
            )
            # How the peaks agree with the new UB and with each other (3.1).
            residuals = alignment_residuals(self.ub_matrix.UB, self.ub_matrix.peaks)
            self.window.ub_matrix_dock.show_residuals(residuals, self.ub_matrix.UB)
            self.print_to_message_center(residuals["summary"])
            # Refresh HKL/angles for current Q
            self.on_Q_changed()
        except Exception as e:
            if belief is not None:
                belief.peaks = self.ub_matrix.peaks
                self.ub_matrix = belief
            self.window.ub_matrix_dock.clear_residuals()
            self.print_to_message_center(f"UB calculation failed: {e}")

    def on_refine_lattice(self):
        """Refine the lattice fields from the observed peaks, by the crystal
        system of the sample dock's space group; the default group #1 (P1)
        counts as unset, and then the system the lattice fields have is
        refined (D13), named in the dialog and the message center. A set of
        peaks that cannot decide the system's parameters is refused."""
        try:
            self.ub_matrix.peaks = self._peaks_from_dock()
            vals = self.get_gui_values()
            if not vals:
                raise ValueError("a field does not read as a number")
            current = (
                vals['lattice_a'], vals['lattice_b'], vals['lattice_c'],
                vals['lattice_alpha'], vals['lattice_beta'], vals['lattice_gamma'],
            )
            group = self.window.sample_dock.get_selected_space_group()
            from_group = group is not None and group.number != 1
            result = refine_lattice_from_peaks(
                self.ub_matrix.peaks, current, group.crystal_system if from_group else None)
            refined, system = result['lattice'], result['crystal_system']
            if from_group:
                source = f"{system}, from space group {group.number} {group.short_name}"
            else:
                unset = ("no space group set" if group is None
                         else "space group 1 (P1, the default) taken as unset")
                source = f"{system}, from the lattice fields; {unset}"
                self.print_to_message_center(
                    f"{unset[0].upper()}{unset[1:]}; refining as {system} from the lattice fields")

            # Show refinement dialog
            from gui.docks.ub_matrix_dock import LatticeRefinementDialog
            dlg = LatticeRefinementDialog(current, refined, result['residuals'],
                                          result['rms_error'], self.window, system=source)
            if dlg.exec():
                # Apply refined lattice to sample dock
                a, b, c, alpha, beta, gamma = refined
                self.window.sample_dock.lattice_a_edit.setText(format_editable_number(a, 6))
                self.window.sample_dock.lattice_b_edit.setText(format_editable_number(b, 6))
                self.window.sample_dock.lattice_c_edit.setText(format_editable_number(c, 6))
                self.window.sample_dock.lattice_alpha_edit.setText(format_editable_number(alpha, 6))
                self.window.sample_dock.lattice_beta_edit.setText(format_editable_number(beta, 6))
                self.window.sample_dock.lattice_gamma_edit.setText(format_editable_number(gamma, 6))
                self.on_lattice_changed()
                self.print_to_message_center(
                    f"Refined lattice applied: a={a:.4f}, b={b:.4f}, c={c:.4f}, "
                    f"α={alpha:.2f}, β={beta:.2f}, γ={gamma:.2f}"
                )
            else:
                self.print_to_message_center("Lattice refinement not applied")
        except ValueError as e:
            self.print_to_message_center(f"Lattice refinement refused: {e}")
        except Exception as e:
            self.print_to_message_center(f"Lattice refinement failed: {e}")

    def on_reset_ub(self):
        """Reset the UB to the sample as described (identity on the standard setting)."""
        self._reset_ub_to_described()
        self.print_to_message_center("UB matrix reset to the sample as described")

    def on_ub_matrix_edited(self, is_non_identity: bool):
        """Handle manual editing of UB matrix in the dock."""
        try:
            UB = self.window.ub_matrix_dock.get_ub_matrix_from_fields()
            self.ub_matrix.set_UB(UB)
            self._update_ub_display()
            self.print_to_message_center("UB matrix updated from manual edit")
            self.on_Q_changed()
        except Exception as e:
            self.print_to_message_center(f"Invalid UB matrix: {e}")

    def on_take_peak_position(self, peak_index: int):
        """Take Position: record the stage readouts of every goniometer axis,
        ki, kf and the sense into the peak's stage record. The readouts are
        the dock fields (A3 is the ω field)."""
        if self._angles_stale:
            self.print_to_message_center(
                f"Take Position refused for peak {peak_index + 1}: the angles do not match "
                f"Q/HKL ({self._angles_stale}). Choose a reachable Q/HKL or edit an angle.")
            return
        vals = self.get_gui_values()
        if not vals:
            return
        pw = self.window.ub_matrix_dock.get_peak_widget(peak_index)
        if pw:
            readouts = {"A3": vals['omega'], "sgl": vals['sgl'], "sgu": vals['sgu']}
            record = stage_record(
                self.instrument_state.goniometer, readouts,
                ki=vals['Ki'], kf=vals['Kf'], sense=self.instrument_state.sense_sample,
            )
            pw.set_angles_from_position(record, vals['stt'], vals['Ki'], vals['Kf'])
            shown = ", ".join(f"{name}={value:.2f}°" for name, value in record["angles"].items())
            self.print_to_message_center(
                f"Peak {peak_index + 1}: position taken "
                f"({shown}, 2θ={vals['stt']:.2f}°, "
                f"ki={vals['Ki']:.4f}, kf={vals['Kf']:.4f})"
            )

    def _peaks_from_dock(self):
        """The UB dock's peak entries as ObservedPeaks (stage record and sense
        included; a peak without a record is a legacy peak)."""
        return [ObservedPeak.from_dict(pd)
                for pd in self.window.ub_matrix_dock.get_all_peak_data() if pd is not None]

    def _on_peak_added(self):
        """Connect signals for newly added peak widget."""
        self._reconnect_peak_signals()

    def _on_peak_removed(self, index: int):
        """Handle peak removal."""
        self.window.ub_matrix_dock.remove_peak_entry(index)
        self._reconnect_peak_signals()

    def _reconnect_peak_signals(self):
        """Reconnect take_position and remove signals for all peak widgets."""
        for pw in self.window.ub_matrix_dock._peak_widgets:
            try:
                pw.take_position_requested.disconnect()
            except RuntimeError:
                pass
            try:
                pw.remove_requested.disconnect()
            except RuntimeError:
                pass
            pw.take_position_requested.connect(self.on_take_peak_position)
            pw.remove_requested.connect(self._on_peak_removed)

    def _update_ub_display(self):
        """Update UB matrix display and scattering plane info in the dock."""
        self.window.ub_matrix_dock.update_ub_display(
            self.ub_matrix.UB, self.ub_matrix.is_identity
        )
        try:
            plane_info = self.ub_matrix.get_plane_info()
            self.window.ub_matrix_dock.update_plane_info(plane_info)
        except Exception as exc:
            self.print_to_message_center(f"Scattering-plane refresh failed: {exc}")
        # Update sample dock indicator
        if hasattr(self.window, 'sample_dock'):
            self.window.sample_dock.update_ub_indicator(not self.ub_matrix.is_identity)
        # Refresh angles from Q since UB affects the mapping (at the lock's
        # tilts when a plane is locked), and the lock's stale mark.
        self.update_angles_from_q()
        self._show_plane_lock()
        self.request_reciprocal_snapshot()

    # ===== UB Training Methods =====

    def on_generate_training(self):
        """Generate a mount-only training exercise hash: a hidden rotation of
        the crystal in its mount that this instrument can observe (redrawn a
        bounded number of times; otherwise the reason is said)."""
        try:
            dock = self.window.ub_matrix_dock
            hash_str = generate_training_exercise(
                max_ori_angle=dock.max_ori_spin.value(),
                accept=self._live_reach_error,
            )
            dock.training_hash_display.setText(hash_str)
            self.print_to_message_center("Training exercise generated - share the hash with students")
        except ValueError as e:
            self.print_to_message_center(f"Failed to generate training: {e}")
        except Exception as e:
            log.exception("Training exercise generation failed")
            self.print_to_message_center(f"Failed to generate training: {e}")

    def on_load_training(self):
        """Load a training exercise: the hidden mount rotation goes to the
        truth; the operator's UB starts at the sample as described."""
        hash_str = self.window.ub_matrix_dock.load_hash_edit.text().strip()
        if self._load_exercise(hash_str):
            self.print_to_message_center("Training exercise loaded - hidden mount rotation applied")

    def on_clear_training(self):
        """Clear the training exercise: R_hidden = I."""
        if self._unload_exercise():
            self.print_to_message_center("Training exercise cleared")

    def on_check_training(self):
        """Grade the alignment against the training exercise (the one grader)."""
        if self._exercise is None:
            self.print_to_message_center("No training exercise loaded")
            return
        grade = self._grade_alignment()
        if grade is not None:
            self.window.ub_matrix_dock.update_check_results(grade)

    def configure_diagnostics(self):
        """Open diagnostics configuration window."""
        dialog = DiagnosticConfigDialog(
            self.window, self.diagnostic_settings, monitors=self.descriptor.monitors
        )
        if dialog.exec():
            # User clicked Save and Close
            self.diagnostic_settings = dialog.get_settings()
            # Update the live instrument state with new settings
            self.instrument_state.update_diagnostic_settings(self.diagnostic_settings)
            # Save parameters to persist the settings
            self.save_parameters()
            self.print_to_message_center("Diagnostic settings saved")
        else:
            self.print_to_message_center("Diagnostic configuration cancelled")
    
    def configure_sample(self):
        """Open sample configuration window."""
        # TODO: Implement sample configuration dialog
        self.print_to_message_center("Sample configuration window not yet implemented")
    
    def clear_runtime_data(self):
        """Clear the current instrument's cached runtime data, after confirmation."""
        from PySide6.QtWidgets import QMessageBox

        # Get current record count for the message
        record_count = self.runtime_tracker.get_record_count(self.instrument.id)
        name = self.instrument.display_name

        reply = QMessageBox.question(
            self.window,
            "Clear Runtime Data",
            f"Are you sure you want to clear the cached runtime data for {name}?\n\n"
            f"This will delete {record_count} {name} scan timing records used to estimate\n"
            f"scan durations. New estimates will be generated as you run more scans.\n\n"
            f"Use this if time estimates seem incorrect.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            cleared = self.runtime_tracker.clear_records(self.instrument.id)
            self.print_to_message_center(f"Cleared {cleared} {name} runtime records. Time estimates will be recalculated from new scans.")
            # Clear displayed estimates
            self.window.simulation_dock.update_total_time_estimate("")
        else:
            self.print_to_message_center("Runtime data clearing cancelled.")
    
    def load_and_display_data(self):
        """Load and display existing data in the display dock."""
        folder = self.window.data_control_dock.load_folder_edit.text()
        if folder and os.path.exists(folder):
            self.print_to_message_center(f"Loading data from: {folder}")
            try:
                # Read parameters to get scan commands
                scan_parameters = read_parameters_from_file(folder)
                require_output_version(scan_parameters, folder)
                scan_cmd1 = scan_parameters.get('scan_command1', '')
                scan_cmd2 = scan_parameters.get('scan_command2', '')
                
                # Build metadata for info panel
                metadata = self._build_scan_metadata_from_parameters(scan_parameters)
                
                # Load data into display dock
                self.window.display_dock.load_existing_data(folder, scan_cmd1, scan_cmd2, metadata)
                self.print_to_message_center("Data loaded into display dock")
            except Exception as e:
                self.print_to_message_center(f"Error loading data: {str(e)}")
        else:
            self.print_to_message_center("Invalid folder path for loading data")
    
    def _build_scan_metadata_from_parameters(self, params):
        """Build scan metadata dict from loaded parameters (canonical IDs on disk)."""
        params = {_to_internal(key): value for key, value in params.items()}
        metadata = {}
        
        # Number of neutrons
        if 'number_neutrons' in params:
            try:
                metadata['number_neutrons'] = int(float(params['number_neutrons']))
            except (ValueError, TypeError):
                pass
        
        # Ki/Kf fixed mode
        if 'K_fixed' in params:
            metadata['K_fixed'] = params['K_fixed']
        
        # Fixed E
        if 'fixed_E' in params:
            try:
                metadata['fixed_E'] = float(params['fixed_E'])
            except (ValueError, TypeError):
                pass
        
        # Collimations
        for key in ['alpha_1', 'alpha_2', 'alpha_3', 'alpha_4']:
            if key in params:
                metadata[key] = params[key]
        
        # Crystals
        if 'monocris' in params:
            metadata['monocris'] = params['monocris']
        if 'anacris' in params:
            metadata['anacris'] = params['anacris']
        
        # Q-space coordinates
        for key in ['qx', 'qy', 'qz']:
            if key in params:
                try:
                    metadata[key] = float(params[key])
                except (ValueError, TypeError):
                    pass
        
        # HKL coordinates
        for key in ['H', 'K', 'L']:
            if key in params:
                try:
                    metadata[key] = float(params[key])
                except (ValueError, TypeError):
                    pass
        
        # Energy transfer -- undetermined at a direct-transmission point
        # (``read_parameters_from_file`` maps the file's literal "None" to
        # ``None``; a raw params dict may still carry the string).
        if 'deltaE' in params:
            if params['deltaE'] is None or params['deltaE'] == 'None':
                metadata['deltaE'] = None
            else:
                try:
                    metadata['deltaE'] = float(params['deltaE'])
                except (ValueError, TypeError):
                    pass

        # Direct-transmission marker, when the saved point recorded one.
        if 'transmission' in params:
            metadata['transmission'] = params['transmission']

        # NMO and velocity selector
        if 'NMO_installed' in params:
            metadata['NMO_installed'] = params['NMO_installed']
        if 'V_selector_installed' in params:
            metadata['V_selector_installed'] = params.get('V_selector_installed', False)
        
        return metadata

    # -------- persistence helpers (descriptor-driven categories)

    @staticmethod
    def _saved_crystal_id(saved, crystals):
        """Resolve a saved crystal id, falling back to the instrument default."""
        for spec in crystals:
            if saved == spec.id:
                return spec.id
        return crystals[0].id

    @staticmethod
    def _saved_module_values(parameters):
        return parameters.get("modules", {})

    @staticmethod
    def _saved_collimation_values(parameters):
        # JSON round-trips multi-select sets as lists
        return {
            slot_id: set(value) if isinstance(value, list) else value
            for slot_id, value in parameters.get("collimation", {}).items()
        }

    def _saved_slit_values(self, parameters):
        """{slit_id: gaps} read from each gap's own key; a missing gap keeps its descriptor default."""
        defaults = self._descriptor_slit_defaults()
        values = {}
        for slit in self.descriptor.slits:
            # The key names public_values writes for the API, so save and load share one mapping.
            flat = _public_values({"slits_mm": {slit.id: defaults[slit.id]}}, [slit])
            gaps = tuple(parameters.get(key, gap) for key, gap in flat.items())
            values[slit.id] = gaps if slit.has_height else gaps[0]
        return values

    def _slit_values_for_save(self):
        try:
            slit_values = self.window.instrument_dock.slit_values_mm()
        except ValueError:
            # Malformed text in a slit field; persist nothing so load falls
            # back to the descriptor defaults.
            return {}
        return _public_values({"slits_mm": slit_values}, self.descriptor.slits)

    def save_parameters(self):
        """Save all parameters to JSON file."""
        parameters = {
            "mono_two_theta_deg": self.window.instrument_dock.mtt_edit.text(),
            "sample_two_theta_deg": self.window.instrument_dock.stt_edit.text(),
            "sample_rotation_deg": self.window.instrument_dock.omega_edit.text(),
            "sample_lower_arc_deg": self.window.instrument_dock.sgl_edit.text(),
            "sample_upper_arc_deg": self.window.instrument_dock.sgu_edit.text(),
            "analyzer_two_theta_deg": self.window.instrument_dock.att_edit.text(),
            "incident_wavevector_inv_angstrom": self.window.instrument_dock.Ki_edit.text(),
            "final_wavevector_inv_angstrom": self.window.instrument_dock.Kf_edit.text(),
            "incident_energy_mev": self.window.instrument_dock.Ei_edit.text(),
            "final_energy_mev": self.window.instrument_dock.Ef_edit.text(),
            "number_neutrons_var": self.window.simulation_dock.get_number_neutrons(),
            "K_fixed_var": self.window.scattering_dock.K_fixed_combo.currentText(),
            "source_type_var": self.window.instrument_dock.selected_source_id(),
            "source_dE_var": self.window.instrument_dock.source_dE_edit.text(),
            "modules": self.window.instrument_dock.module_values(),
            "mono_horizontal_radius_m": self.window.instrument_dock.rhm_edit.text(),
            "mono_vertical_radius_m": self.window.instrument_dock.rvm_edit.text(),
            "analyzer_horizontal_radius_m": self.window.instrument_dock.rha_edit.text(),
            "analyzer_vertical_radius_m": self.window.instrument_dock.rva_edit.text(),
            "rhm_ideal_locked": self.is_bending_locked("rhm"),
            "rvm_ideal_locked": self.is_bending_locked("rvm"),
            "rha_ideal_locked": self.is_bending_locked("rha"),
            "rva_ideal_locked": self.is_bending_locked("rva"),
            "fixed_E_var": self.window.scattering_dock.fixed_E_edit.text(),
            "q_instrument_x_inv_angstrom": self.window.scattering_dock.qx_edit.text(),
            "q_instrument_y_inv_angstrom": self.window.scattering_dock.qy_edit.text(),
            "q_instrument_z_inv_angstrom": self.window.scattering_dock.qz_edit.text(),
            # HKL values
            "h": self.window.scattering_dock.H_edit.text(),
            "k": self.window.scattering_dock.K_edit.text(),
            "l": self.window.scattering_dock.L_edit.text(),
            "energy_transfer_mev": self.window.scattering_dock.deltaE_edit.text(),
            "monocris_var": self.window.instrument_dock.selected_mono_id(),
            "anacris_var": self.window.instrument_dock.selected_ana_id(),
            "collimation": {
                slot_id: sorted(value) if isinstance(value, set) else value
                for slot_id, value in
                self.window.instrument_dock.collimation_values().items()
            },
            # Slit apertures (stored in mm)
            **self._slit_values_for_save(),
            "diagnostic_mode_var": self.window.simulation_dock.diagnostic_mode_check.isChecked(),
            "lattice_a_angstrom": self.window.sample_dock.lattice_a_edit.text(),
            "lattice_b_angstrom": self.window.sample_dock.lattice_b_edit.text(),
            "lattice_c_angstrom": self.window.sample_dock.lattice_c_edit.text(),
            "lattice_alpha_deg": self.window.sample_dock.lattice_alpha_edit.text(),
            "lattice_beta_deg": self.window.sample_dock.lattice_beta_edit.text(),
            "lattice_gamma_deg": self.window.sample_dock.lattice_gamma_edit.text(),
            "scan_command_var1": self.window.simulation_dock.scan_command_1_edit.text(),
            "scan_command_var2": self.window.simulation_dock.scan_command_2_edit.text(),
            "save_folder_var": self.window.data_control_dock.save_folder_edit.text(),
            "load_folder_var": self.window.data_control_dock.load_folder_edit.text(),
            "diagnostic_settings": self.diagnostic_settings,
            "current_sample_settings": self.current_sample_settings,
            # Background profile request spec (tavi/background.py); absent in
            # files written before background support -> default-off on load.
            "background_profile": copy.deepcopy(self.background_profile),
            "space_group_number_var": self.window.sample_dock.spacegroup_combo.currentData() if hasattr(self.window.sample_dock, 'spacegroup_combo') else None,
            "use_sample_reflection_table_var": bool(
                getattr(self.window.sample_dock, "use_sample_reflection_table_check", None)
                and self.window.sample_dock.use_sample_reflection_table_check.isChecked()
            ),
            # UB matrix state (the operator's belief)
            "ub_matrix_state": self.ub_matrix.to_dict(),
            # The sample as described. R_hidden is never saved in clear: the
            # training hash below is its only record.
            "true_mount": {
                "U_described": self.U_described.tolist(),
                "mount_plane": ([list(hkl) for hkl in self.mount_plane]
                                if self.mount_plane is not None else None),
            },
            # The loaded exercise, by its hash only (values stay hidden).
            "ub_training_hash": self._exercise or "",
            # The locked scattering plane (null = free).
            "plane_lock": copy.deepcopy(self.instrument_state.plane_lock),
        }
        # An exercise these values cannot observe would be written with its
        # fitted UB but no hidden mount, and restore would not match. The file is
        # not replaced: the last consistent save stays on disk.
        reason = self._saved_exercise_refusal(parameters) if parameters["ub_training_hash"] else None
        if reason:
            if self._unsaved_exercise_report != (self._exercise, reason):
                self._unsaved_exercise_report = (self._exercise, reason)
                self.print_to_message_center(
                    "Parameters not saved: the loaded exercise cannot be observed with the "
                    "current sample, fixed energy or crystals. Restore those settings or "
                    "clear the exercise, and saving resumes.")
            return
        self._unsaved_exercise_report = None
        # Namespace by instrument id with a schema version (design record §9,
        # §16.8): {"<instrument_id>": {"_schema": 1, ...}}.
        parameters["_schema"] = self.PARAMETERS_SCHEMA_VERSION

        def put_block(document):
            document[self.instrument.id] = parameters
            return True

        self._edit_parameters_file(put_block)
        self.print_to_message_center("Parameters saved successfully")

    def _edit_parameters_file(self, edit):
        """The one writer of parameters.json. Reads the document (only the
        per-instrument ``{"_schema": N, ...}`` blocks survive; anything else is
        discarded), lets ``edit(document)`` change it in place, and writes it
        back when ``edit`` returns True. Other instruments' blocks are kept."""
        document = {}
        unreadable = None
        parameters_path = local_config_path("parameters.json")
        if os.path.exists(parameters_path):
            try:
                with open(parameters_path, "r", encoding="utf-8") as file:
                    existing = json.load(file)
                if isinstance(existing, dict):
                    document = {
                        block_id: block for block_id, block in existing.items()
                        if isinstance(block, dict) and "_schema" in block
                    }
            except (json.JSONDecodeError, OSError) as exc:
                unreadable = f"parameters.json was unreadable ({exc})"
                document = {}
        write = edit(document)
        if unreadable:
            self.print_to_message_center(
                unreadable + ("; writing a fresh one" if write else "; left as it is"))
        if write:
            with open(parameters_path, "w", encoding="utf-8", newline="\n") as file:
                json.dump(document, file)

    # v2: rva joined rhm/rvm/rha as a real GUI field with its own saved
    # radius and Ideal lock.
    # v3: the true mount apart from the operator's UB -- "true_mount"
    # {U_described, mount_plane}.
    # v4: the psi/kappa corrections, the hidden zero errors and the
    # Misalignment dock are gone (no correction or misalignment-hash
    # variables; a plane lock carries no correction).
    # v5: physical quantities are saved under their canonical IDs
    # (tavi/quantities.py) and A2/A4/A6 count the ILL way; a v4 file would
    # read its angles under the wrong meaning. The version is enforced: a
    # file with a block of any other version (or a flat legacy file) is
    # refused whole, never converted (_saved_parameters_refusal).
    PARAMETERS_SCHEMA_VERSION = 5

    @staticmethod
    def _read_saved_parameters(path):
        """``(document, refusal)``: the saved file parsed once, or why it cannot
        be read. ``load_parameters`` judges and applies that one document."""
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file), None
        except ValueError as exc:
            return None, f"it is not readable JSON ({exc})"
        except OSError as exc:
            return None, f"it could not be read ({exc})"

    def _saved_parameters_refusal(self, document):
        """Why this saved document cannot be restored, or None.

        Judges the whole document before anything is applied: every top-level
        entry must be an instrument block of this version, so a flat legacy file,
        or a block of another version beside a current one, refuses the file
        (otherwise a later start on that other instrument would rename this block
        away with it). Then this instrument's block: each saved peak's stage
        record and the saved exercise (a mount-only code this instrument, sample,
        crystals, energy and described mount IN THE FILE can still observe --
        never the live ones). Unreadable files never get here:
        ``_read_saved_parameters`` refuses them.
        """
        if not isinstance(document, dict):
            return "it is not a settings file"
        for block in document.values():
            version = block.get("_schema") if isinstance(block, dict) else None
            if version != self.PARAMETERS_SCHEMA_VERSION:
                return (f"it was saved by another TAVI (file version "
                        f"{'none' if version is None else version}; this one reads "
                        f"{self.PARAMETERS_SCHEMA_VERSION})")
        parameters = self._parameters_block(document)
        if not parameters:
            return None
        ub_state = parameters.get("ub_matrix_state")
        peaks = ub_state.get("peaks") if isinstance(ub_state, dict) else None
        for index, peak in enumerate(peaks if isinstance(peaks, list) else []):
            stage = peak.get("stage") if isinstance(peak, dict) else None
            if stage is None:
                continue
            try:
                record_angles(stage)
            except (ValueError, AttributeError, TypeError, KeyError) as exc:
                return f"saved peak {index + 1} cannot be read: {exc}"
        return self._saved_exercise_refusal(parameters)

    def _saved_exercise_refusal(self, parameters):
        """Why a block's saved exercise cannot be restored, or None. The code
        must decode, and this instrument must observe it with the block's own
        sample, crystals, energy and described mount -- never the live ones.
        ``save_parameters`` judges what it writes with this same rule, so a file
        it writes is never refused for its exercise."""
        hash_str = str(parameters.get("ub_training_hash") or "")
        if not hash_str or hash_str == "None":
            return None
        try:
            rotation = decode_mount_exercise(hash_str)
        except ValueError as exc:
            return f"its saved exercise is refused: {exc}"
        described, _plane, _problem = self._saved_mount(parameters)
        sample_key = (parameters.get("current_sample_settings") or {}).get(
            "sample_key", "Al_bragg")
        if sample_key is None:  # "No sample" is saved as null
            sample_key = "none"
        if not any(s.id == sample_key for s in self.descriptor.samples):
            sample_key = "Al_bragg"
        try:
            fixed_E = float(parameters.get("fixed_E_var", 14.7))
        except (TypeError, ValueError):
            fixed_E = 14.7
        reason = self._exercise_reach_error(
            rotation, described, sample_key,
            self._saved_crystal_id(parameters.get("monocris_var"), self.descriptor.mono_crystals),
            self._saved_crystal_id(parameters.get("anacris_var"), self.descriptor.ana_crystals),
            parameters.get("K_fixed_var", "Kf Fixed"), fixed_E)
        if reason:
            return f"its saved exercise cannot be observed here: {reason}"
        return None

    @staticmethod
    def _free_backup_path(path):
        """``path.bak``, else ``path.bak2``, ``path.bak3``, ... : the first
        name nothing is using, so no backup is ever overwritten."""
        path = os.fspath(path)
        candidate, number = path + ".bak", 1
        while os.path.exists(candidate):
            number += 1
            candidate = f"{path}.bak{number}"
        return candidate

    def _refuse_parameters_file(self, path, reason, keep_current):
        """A saved file that cannot be restored: set it aside as a backup,
        load the defaults (``keep_current``: leave the session exactly as it
        is, for File > Load Parameters), and say why in one message-centre
        line that names the backup."""
        backup = self._free_backup_path(path)
        try:
            os.rename(path, backup)
            kept = f"The file was renamed {backup}."
        except OSError as exc:
            log.warning("Could not rename %s to %s: %s", path, backup, exc)
            kept = f"It could not be renamed ({exc}), so it will be refused again."
        if not keep_current:
            self.set_default_parameters()
        self.print_to_message_center(
            f"Saved parameters not restored: {reason}. {kept} "
            + ("The current settings are unchanged." if keep_current else "Defaults loaded."))

    def _parameters_block(self, document):
        """This instrument's block from ``{"<id>": {"_schema": N, ...}}``.

        Missing/malformed block -> empty dict (every field read falls back to
        its default).
        """
        if not isinstance(document, dict):
            return {}
        block = document.get(self.instrument.id, {})
        return block if isinstance(block, dict) else {}

    @staticmethod
    def _dominant_execution_mode(point_stage_timings):
        """Dominant McStas execution mode across recorded points (schema v2).

        Returns "mixed" when both backengine and direct points ran, else
        whichever single mode is present, else None (no point recorded a
        backengine/direct mode -- e.g. all skipped).
        """
        num_backengine = sum(
            1 for record in (point_stage_timings or [])
            if record.get('execution_mode') == 'backengine'
        )
        num_direct = sum(
            1 for record in (point_stage_timings or [])
            if record.get('execution_mode') == 'direct'
        )
        if num_backengine and num_direct:
            return "mixed"
        if num_backengine:
            return "backengine"
        if num_direct:
            return "direct"
        return None

    @staticmethod
    def _can_reuse_binary(cache, fingerprint, diagnostic_mode,
                          force_rebuild=False):
        """Whether the previous scan's compiled binary satisfies this scan.

        Diagnostic-mode scans always rebuild: their first point must run
        ``backengine()`` so McStasData is available for the diagnostic plots
        (design record §18.5). ``force_rebuild`` (threaded from the launch
        state) unconditionally forces a rebuild -- the benchmarker's cold stage
        uses it to measure a genuine compile.
        """
        if force_rebuild or diagnostic_mode or not cache:
            return False
        execution_state = cache.get("execution_state")
        return bool(
            cache.get("fingerprint") == fingerprint
            and execution_state is not None
            and execution_state.first_backengine_succeeded
            and execution_state.binary_path
            and os.path.isfile(execution_state.binary_path)
        )

    @staticmethod
    def _updated_binary_cache(cache, reused, fingerprint, instrument,
                              execution_state, instr_archive_path):
        """Next value of the cross-scan binary cache after a scan finishes.

        A scan that compiled (first backengine succeeded) owns the on-disk
        binary and replaces the cache. A reused or aborted-before-compile scan
        leaves the previous entry in place -- the binary on disk is unchanged.
        """
        if reused:
            return cache
        if (
            execution_state.first_backengine_succeeded
            and execution_state.binary_path
            and os.path.isfile(execution_state.binary_path)
        ):
            return {
                "fingerprint": fingerprint,
                "instrument": instrument,
                "execution_state": execution_state,
                "instr_path": (
                    instr_archive_path
                    if instr_archive_path and os.path.isfile(instr_archive_path)
                    else None
                ),
            }
        return cache

    # Default-off gate with the complete realistic catalog prepared at x1.
    DEFAULT_BACKGROUND_PROFILE = _background.default_spec()

    def _saved_background_profile(self, parameters):
        """Background profile from a saved block, defaulting off on any problem.

        Only the current catalog is accepted. Pre-catalog, old-version, and
        malformed state is visibly discarded and replaced by the safe
        default-off configuration; no released background campaign depends on
        preserving those experimental settings.
        """
        default = copy.deepcopy(self.DEFAULT_BACKGROUND_PROFILE)
        spec = parameters.get("background_profile")
        if spec is None:
            return default
        try:
            return _background.normalized_spec(_background.resolve(spec))
        except (ValueError, TypeError) as exc:
            self.print_to_message_center(
                "Saved background profile is incompatible with the current "
                f"catalog ({exc}); reset to safe defaults with background disabled"
            )
            return default

    @staticmethod
    def _saved_mount(parameters):
        """``(U_described, mount_plane, problem)`` of a saved block: the mount
        the sample is described with, its optional plane, and None or why the
        saved mount is unreadable (then the standard setting)."""
        true_mount = parameters.get("true_mount")
        if isinstance(true_mount, dict):
            described = true_mount.get("U_described")
            plane = true_mount.get("mount_plane")
        else:
            # A block without a true mount, best effort: its UB is taken as
            # the mount, so it diffracts where its UB says.
            described, plane = (parameters.get("ub_matrix_state") or {}).get("U"), None
        try:
            described = validate_rotation_matrix(np.eye(3) if described is None else described)
            if plane is not None:
                plane = tuple(tuple(float(x) for x in hkl) for hkl in plane)
                if len(plane) != 2 or any(len(hkl) != 3 for hkl in plane):
                    raise ValueError("the mounting plane needs two (h k l) vectors")
        except (ValueError, TypeError) as e:
            return np.eye(3), None, str(e)
        return described, plane, None

    def _restore_hidden_truth(self, parameters):
        """Restore is a full replace of the hidden truth, in this order:
        the described mount, then the one exercise (absent hashes mean
        R_hidden = I); the saved plane lock goes after both
        (``_restore_plane_lock``). The exercise was judged before anything was
        applied (``_saved_parameters_refusal``), so it installs without a
        second look. No interactive refusal runs, the operator's UB is not
        touched, and no file is written."""
        described, plane, problem = self._saved_mount(parameters)
        if problem:
            self.print_to_message_center(
                f"Saved sample mount unreadable ({problem}); the standard setting is used")
        self.mount_plane = plane
        self._set_true_mount(U_described=described)
        self._show_mount_plane()

        self._clear_exercise()
        hash_str = str(parameters.get("ub_training_hash") or "")
        if hash_str and hash_str != "None":
            self._apply_exercise(hash_str, decode_mount_exercise(hash_str))
            self.print_to_message_center("Training exercise restored from saved parameters")

    def load_parameters(self, keep_current_on_refusal=False):
        """Load parameters from JSON file.

        A file this TAVI cannot restore whole (another version, a peak or an
        exercise it refuses; ``_saved_parameters_refusal``) is set aside as a
        backup and changes nothing else. At start-up the defaults load; for
        File > Load Parameters, ``keep_current_on_refusal``, the session stays
        exactly as the operator left it, and a valid file with no block for
        this instrument is left in place and changes nothing either.
        """
        parameters_path = local_config_path("parameters.json")
        if os.path.exists(parameters_path):
            document, refusal = self._read_saved_parameters(parameters_path)
            refusal = refusal or self._saved_parameters_refusal(document)
            if refusal:
                self._refuse_parameters_file(parameters_path, refusal, keep_current_on_refusal)
                return
            parameters = self._parameters_block(document)
            parameters = self._normalise_loaded_numbers(parameters)

            # No saved block for this instrument (fresh install or a file
            # saved only for other instruments): use the full default path so
            # derived values like ideal bending radii are applied, not left at 0.
            if not parameters and keep_current_on_refusal:
                self.print_to_message_center(
                    f"{parameters_path} holds no settings for '{self.instrument.id}'; "
                    "the current settings are unchanged")
                return
            if not parameters:
                self.set_default_parameters()
                self.print_to_message_center(
                    f"No saved parameters for '{self.instrument.id}'; defaults loaded"
                )
                return

            # Restore replaces the lock too: free until the saved one (if
            # any) goes back on after the hidden truth, below.
            self._set_plane_lock(None)

            # Block signals during loading to prevent premature validation
            self.window.simulation_dock.scan_command_1_edit.blockSignals(True)
            self.window.simulation_dock.scan_command_2_edit.blockSignals(True)

            # Set GUI values from parameters (saved crystal values may be
            # legacy display labels or CrystalSpec ids; both resolve)
            self.window.instrument_dock.set_mono_id(self._saved_crystal_id(
                parameters.get("monocris_var"), self.descriptor.mono_crystals
            ))
            self.window.instrument_dock.set_ana_id(self._saved_crystal_id(
                parameters.get("anacris_var"), self.descriptor.ana_crystals
            ))
            mtt, stt, omega, att = self._reference_angles(
                self.window.instrument_dock.selected_mono_id(),
                self.window.instrument_dock.selected_ana_id(),
            )
            self._set_tracked_angle_text(
                'mtt', self.window.instrument_dock.mtt_edit,
                parameters.get("mono_two_theta_deg", mtt),
            )
            self.window.instrument_dock.stt_edit.setText(format_editable_number(parameters.get("sample_two_theta_deg", stt)))
            self.window.instrument_dock.omega_edit.setText(format_editable_number(parameters.get("sample_rotation_deg", omega)))
            self.window.instrument_dock.sgl_edit.setText(format_editable_number(
                parameters.get("sample_lower_arc_deg", 0)))
            self.window.instrument_dock.sgu_edit.setText(format_editable_number(parameters.get("sample_upper_arc_deg", 0)))
            self._set_tracked_angle_text(
                'att', self.window.instrument_dock.att_edit,
                parameters.get("analyzer_two_theta_deg", att),
            )
            self.window.instrument_dock.Ki_edit.setText(format_editable_number(parameters.get("incident_wavevector_inv_angstrom", "2.6634")))
            self.window.instrument_dock.Kf_edit.setText(format_editable_number(parameters.get("final_wavevector_inv_angstrom", "2.6634")))
            self.window.instrument_dock.Ei_edit.setText(format_editable_number(parameters.get("incident_energy_mev", "14.7")))
            self.window.instrument_dock.Ef_edit.setText(format_editable_number(parameters.get("final_energy_mev", "14.7")))
            self.window.instrument_dock.set_source_id(
                parameters.get("source_type_var", self.descriptor.source_types[0].id)
            )
            self.window.instrument_dock.source_dE_edit.setText(format_editable_number(parameters.get("source_dE_var", "2")))
            # Descriptor-driven categories (nested containers; legacy flat
            # keys from pre-Phase-2 files migrate through the fallbacks)
            self.window.instrument_dock.set_module_values(
                self._saved_module_values(parameters)
            )
            self.window.instrument_dock.set_collimation_values(
                self._saved_collimation_values(parameters)
            )
            self.window.instrument_dock.set_slit_values_mm(
                self._saved_slit_values(parameters)
            )

            # Absolute bending radii, then the ideal locks
            self._load_bending_parameters(parameters)
            self._apply_bending_lock_state(
                parameters.get("rhm_ideal_locked", False),
                parameters.get("rvm_ideal_locked", False),
                parameters.get("rha_ideal_locked", False),
                parameters.get("rva_ideal_locked", False),
            )
            
            self.window.simulation_dock.set_number_neutrons(parameters.get("number_neutrons_var", 1000000))
            self.window.scattering_dock.K_fixed_combo.setCurrentText(parameters.get("K_fixed_var", "Kf Fixed"))
            self.window.scattering_dock.fixed_E_edit.setText(format_editable_number(parameters.get("fixed_E_var", 14.7)))
            self.window.scattering_dock.qx_edit.setText(format_editable_number(parameters.get("q_instrument_x_inv_angstrom", "3.1028")))
            self.window.scattering_dock.qy_edit.setText(format_editable_number(parameters.get("q_instrument_y_inv_angstrom", 0)))
            self.window.scattering_dock.qz_edit.setText(format_editable_number(parameters.get("q_instrument_z_inv_angstrom", 0)))
            # HKL values
            self.window.scattering_dock.H_edit.setText(format_editable_number(parameters.get("h", 2)))
            self.window.scattering_dock.K_edit.setText(format_editable_number(parameters.get("k", 0)))
            self.window.scattering_dock.L_edit.setText(format_editable_number(parameters.get("l", 0)))
            self.window.scattering_dock.deltaE_edit.setText(format_editable_number(parameters.get("energy_transfer_mev", 0)))
            self.window.simulation_dock.diagnostic_mode_check.setChecked(parameters.get("diagnostic_mode_var", True))
            # Default scan: H-scan around Al (200) Bragg peak
            self.window.simulation_dock.scan_command_1_edit.setText(parameters.get("scan_command_var1", "H 1.9 2.1 0.01"))
            self.window.simulation_dock.scan_command_2_edit.setText(parameters.get("scan_command_var2", ""))
            # Restore sample selection by persisted sample id (default Al
            # Bragg). The mounting plane is replaced from the block below,
            # so the sample swap's plane clear (I5) has nothing to clear.
            self.mount_plane = None
            try:
                saved_sample = parameters.get("current_sample_settings", {})
                if not self.window.sample_dock.set_sample_by_key(
                    saved_sample.get("sample_key", "Al_bragg")
                ):
                    self.window.sample_dock.set_sample_by_key("Al_bragg")
            except Exception:
                pass
            # Saved lattice values are applied AFTER the sample restore: the
            # sample-change handler adopts the sample's own lattice, and the
            # user's saved (possibly hand-edited) values must win on reload.
            self.window.sample_dock.lattice_a_edit.setText(format_editable_number(parameters.get("lattice_a_angstrom", "4.05"), 6))
            self.window.sample_dock.lattice_b_edit.setText(format_editable_number(parameters.get("lattice_b_angstrom", "4.05"), 6))
            self.window.sample_dock.lattice_c_edit.setText(format_editable_number(parameters.get("lattice_c_angstrom", "4.05"), 6))
            self.window.sample_dock.lattice_alpha_edit.setText(format_editable_number(parameters.get("lattice_alpha_deg", "90"), 6))
            self.window.sample_dock.lattice_beta_edit.setText(format_editable_number(parameters.get("lattice_beta_deg", "90"), 6))
            self.window.sample_dock.lattice_gamma_edit.setText(format_editable_number(parameters.get("lattice_gamma_deg", "90"), 6))
            # Restore space group selection
            try:
                sg_number = parameters.get("space_group_number_var")
                if sg_number is not None and hasattr(self.window.sample_dock, 'spacegroup_combo'):
                    idx = self.window.sample_dock.spacegroup_combo.findData(int(sg_number))
                    if idx >= 0:
                        self.window.sample_dock.spacegroup_combo.setCurrentIndex(idx)
            except Exception:
                pass
            reflection_table_check = getattr(
                self.window.sample_dock,
                "use_sample_reflection_table_check",
                None,
            )
            if reflection_table_check is not None:
                reflection_table_check.setChecked(
                    bool(parameters.get("use_sample_reflection_table_var", False))
                )
            # Restore UB matrix state
            ub_state = parameters.get("ub_matrix_state")
            if ub_state:
                try:
                    self.ub_matrix = UBMatrix.from_dict(ub_state)
                    self._update_ub_display()
                    # Restore peak entries in dock
                    peaks_data = []
                    for p in self.ub_matrix.peaks:
                        peaks_data.append(p.to_dict())
                    if peaks_data:
                        self.window.ub_matrix_dock.set_peak_entries(peaks_data)
                    self._reconnect_peak_signals()
                    self.print_to_message_center("UB matrix state restored")
                    # Peaks without a sense predate the sample-sense fix:
                    # on a +1 instrument that UB was fitted turned 180 deg
                    # about the vertical. Say so; never refit silently.
                    if self.instrument_state.sense_sample > 0 and any(
                            p.get("sense_sample") is None
                            for p in ub_state.get("peaks", [])):
                        self.print_to_message_center(
                            "This UB was saved before the sample-sense fix and may be "
                            "turned 180° about the vertical on this instrument: press "
                            "Calculate UB to refit it from its peaks.")
                except Exception as e:
                    self.print_to_message_center(f"Failed to restore UB matrix: {e}")
            # The hidden truth, after the sample and the UB: the operator's
            # UB stays as saved above.
            self._restore_hidden_truth(parameters)
            # Then the saved lock, on the truth it was locked on.
            self._restore_plane_lock(parameters)
            # Set display and folder fields (use sensible defaults if missing)
            folder_suggestion = os.path.join(self.output_directory, "initial_testing")
            self.window.data_control_dock.save_folder_edit.setText(parameters.get("save_folder_var", folder_suggestion))
            self.window.data_control_dock.load_folder_edit.setText(parameters.get("load_folder_var", folder_suggestion))
            
            # Load diagnostic settings with defaults for any missing keys
            default_diag = DiagnosticConfigDialog.get_default_settings(
                self.descriptor.monitors
            )
            loaded_diag = parameters.get("diagnostic_settings", {})
            # Merge: use loaded value if present, else default
            self.diagnostic_settings = {**default_diag, **loaded_diag}
            self.current_sample_settings = parameters.get("current_sample_settings", {})
            self.background_profile = self._saved_background_profile(parameters)
            self._refresh_background_row()

            self.update_ideal_bending_buttons()
            
            # Unblock signals after all parameters are loaded
            self.window.simulation_dock.scan_command_1_edit.blockSignals(False)
            self.window.simulation_dock.scan_command_2_edit.blockSignals(False)
            loaded_values = self.get_gui_values() or {}
            for key in ("Ki", "Kf", "Ei", "Ef", "fixed_E", "deltaE"):
                if key in loaded_values:
                    self._update_tracked_value(key, loaded_values[key])
            # Loading replaces the complete controller state.  All tracked
            # fields therefore have a new committed baseline, without the
            # per-field flash reserved for direct commands/API patches.
            self._commit_programmatic_feedback(
                getattr(self, "_feedback_line_edits", ())
            )
            
            self.print_to_message_center("Parameters loaded successfully")
        else:
            self.set_default_parameters()
    
    def _ideal_bending_from_modules(self, mtt, att, monocris, anacris, modules,
                                     requested_axes=None):
        """Widget-free ideal bending radii for the NAMED crystals.

        Thin caller of the shared producer, mirroring
        ``_compute_ideal_bending_values`` minus every widget read: crystals
        come from the caller's frozen values (a patched API request), never
        from live GUI selection, which can name a different pair.

        ``requested_axes`` passes straight through to ``ideal_curvature``:
        ``None`` (the default) asks for all four, same as every caller before
        this parameter existed. A caller that only wants some axes (e.g. the
        ones actually AUTOFOCUS right now) should narrow it, so an unrelated
        axis with no established focusing model (IN12's Heusler ``rva``)
        cannot refuse an answer nobody asked it for.

        Returns None for a degenerate geometry (zero take-off angle) -- the
        caller leaves the radii at their prior value, same as before. A
        REQUESTED crystal/axis whose focusing model is unknown for a driven
        axis (IN12's Heusler ``rva``) is NOT swallowed: ``ValueError``
        propagates so the API path (``build_api_launch_state``) can surface
        it as a 400 instead of silently keeping a stale radius.
        """
        try:
            return _operator_magnitudes(self.instrument_state.ideal_curvature(
                monocris, anacris, crystal_theta(mtt), crystal_theta(att), modules=modules,
                requested_axes=requested_axes,
            ))
        except ZeroDivisionError:
            return None

    def _descriptor_collimation_defaults(self):
        """{slot_id: default} for every collimation slot the descriptor declares.

        A multi-select slot's value is a set, matching what the GUI's
        ``collimation_values`` returns for one.
        """
        defaults = {}
        for slot in self.descriptor.collimation:
            if slot.multi_select:
                defaults[slot.id] = {slot.default} if slot.default else set()
            else:
                defaults[slot.id] = slot.default
        return defaults

    def _descriptor_module_defaults(self):
        """{module_id: default} for every module the descriptor declares.

        Twin of ``_descriptor_collimation_defaults`` for the same reason: a
        patched ``modules`` dict replaces the previous one wholesale, and the
        plugin indexes every id the descriptor declares (e.g.
        ``modules['nmo']``, ``modules['v_selector']`` in
        ``instruments/puma/plugin.py``), so an omitted id must be refilled
        rather than left missing.
        """
        from instruments.descriptor import ModuleKind

        defaults = {}
        for module in self.descriptor.modules:
            if module.kind is ModuleKind.CHOICE:
                defaults[module.id] = str(module.default)
            else:
                defaults[module.id] = bool(module.default)
        return defaults

    def _descriptor_slit_defaults(self):
        """{slit_id: default} for every slit the descriptor declares.

        Twin of ``_descriptor_collimation_defaults`` for the same reason: a
        patched ``slits_mm`` dict replaces the previous one wholesale, and the
        plugins index every id the descriptor declares (e.g.
        ``slits_mm['pbl']``, ``slits_mm['vbl_hgap']`` in
        ``instruments/puma/plugin.py``), so an omitted id must be refilled
        rather than left missing. A two-gap slit's value is a
        ``(width, height)`` tuple, matching what the plugins' indexing
        depends on; a single-gap slit's value is a bare scalar.
        """
        defaults = {}
        for slit in self.descriptor.slits:
            width = float(slit.default_width_mm or 0)
            if slit.has_width and slit.has_height:
                defaults[slit.id] = (width, float(slit.default_height_mm or 0))
            else:
                defaults[slit.id] = width
        return defaults

    def _reference_angles(self, monocris, anacris):
        """(mtt, stt, omega, att) for the Al(200) reference point, this instrument's own branch.

        Solved from the active instrument (``calculate_angles`` applies its
        declared mono/sample/analyser senses -- instruments/tas_runtime.py:783),
        not one instrument's hard-coded literals: an unpatched API launch on
        any other instrument used to start from those
        (docs/audits/release-1-3.md entry 2). ``calculate_angles`` reads
        instrument-fixed crystal geometry and senses only and does not mutate
        the state it is called on, so the live ``self.instrument_state`` is
        safe to reuse here.

        Mirrors the qx/qy/qz/deltaE/fixed_E/K_fixed defaults set in
        ``_default_parameter_values`` (Al (2,0,0), deltaE=0, Kf-fixed at
        14.7 meV). On a solve error (e.g. a hand-built descriptor with
        incompatible crystals), the zeroed solve is returned as-is -- no
        literal fallback, since a wrong-instrument default is exactly the bug
        this closes; the caller sees zeros and the validation path refuses
        them visibly instead of silently defaulting to another instrument.
        """
        angles, error_flags = self.instrument_state.calculate_angles(
            3.1028, 0.0, 0.0, 0.0, 14.7, "Kf Fixed", monocris, anacris,
        )
        if error_flags:
            log.warning(
                "reference angle solve failed for %s (mono=%s, ana=%s): %s",
                self.descriptor.id, monocris, anacris, error_flags,
            )
        mtt, stt, sth, _sgl, att = angles
        return mtt, stt, sth, att

    def _default_parameter_values(self):
        """Widget-free defaults dict with exactly get_gui_values()'s key set.

        The API scan/validate path builds its launch state from these
        self-consistent Al(200) defaults overlaid with the caller's patch
        (:meth:`build_api_launch_state`), so a submission never reads live GUI
        widgets. Divergence from the GUI defaults: diagnostic_mode is False
        (matches the benchmark launch path) and the scan commands start empty
        (an API scan must supply its own).
        """
        from instruments.descriptor import ModuleKind

        d = self.descriptor

        modules = {}
        for m in d.modules:
            if m.kind is ModuleKind.CHOICE:
                modules[m.id] = str(m.default)
            else:
                modules[m.id] = bool(m.default)

        collimation = self._descriptor_collimation_defaults()

        slits_mm = self._descriptor_slit_defaults()

        sample_ids = {s.id for s in d.samples}
        mtt, stt, omega, att = self._reference_angles(
            d.mono_crystals[0].id, d.ana_crystals[0].id,
        )
        vals = {
            'mtt': mtt, 'stt': stt, 'omega': omega, 'sgl': 0.0, 'sgu': 0.0,
            'att': att,
            'Ki': 2.6634, 'Ei': 14.7, 'Kf': 2.6634, 'Ef': 14.7,
            'K_fixed': "Kf Fixed", 'fixed_E': 14.7,
            'qx': 3.1028, 'qy': 0.0, 'qz': 0.0,
            'H': 2.0, 'K': 0.0, 'L': 0.0, 'deltaE': 0.0,
            'lattice_a': 4.05, 'lattice_b': 4.05, 'lattice_c': 4.05,
            'lattice_alpha': 90.0, 'lattice_beta': 90.0, 'lattice_gamma': 90.0,
            'sample': "Al_bragg" if "Al_bragg" in sample_ids else "none",
            # Read-only description of the session's mount, which every launch
            # uses (the true mount rides on instrument_state, never on vals).
            **self._mount_plane_fields(),
            'monocris': d.mono_crystals[0].id,
            'anacris': d.ana_crystals[0].id,
            'rhm': 0.0, 'rvm': 0.0, 'rha': 0.0, 'rva': 0.0,
            # An API request that never names a radius gets one focused for
            # its own point, not this launch state's reference-geometry
            # default -- an explicit rhm/rvm/rha patch pins that axis to
            # HELD below.
            'curvature_modes': {
                'rhm': CurvatureMode.AUTOFOCUS, 'rvm': CurvatureMode.AUTOFOCUS,
                'rha': CurvatureMode.AUTOFOCUS, 'rva': CurvatureMode.AUTOFOCUS,
            },
            'source_type': d.source_types[0].id,
            'source_dE': 2.0,
            'modules': modules,
            'collimation': collimation,
            'slits_mm': slits_mm,
            'number_neutrons': 1000000,
            'scan_command1': "",
            'scan_command2': "",
            'diagnostic_mode': False,
        }

        try:
            # All four are AUTOFOCUS in the defaults set just above; naming
            # them explicitly (rather than passing requested_axes=None) makes
            # that rule visible here rather than implicit in "ask for
            # everything".
            ideal = self._ideal_bending_from_modules(
                vals['mtt'], vals['att'], vals['monocris'], vals['anacris'],
                modules, requested_axes=('rhm', 'rvm', 'rha', 'rva'),
            )
        except ValueError as exc:
            # The default crystals are always focusing-known; a refusal here
            # would mean a hand-built descriptor with no valid default pair.
            # Leave the flat fallbacks above rather than fail every request,
            # but never swallow it silently -- a hand-built descriptor that
            # hits this is a wiring bug worth seeing in the log.
            log.warning(
                "default ideal bending unavailable for %s/%s: %s",
                vals['monocris'], vals['anacris'], exc,
            )
            ideal = None
        if ideal:
            # Per axis, honouring the modes set just above -- the same rule
            # build_api_launch_state applies. Every axis is AUTOFOCUS in the
            # defaults, so today this fills all four either way; writing it
            # per-axis means a caller that reuses these defaults after
            # adjusting a mode does not silently overwrite a HELD axis.
            for axis in ('rhm', 'rvm', 'rha', 'rva'):
                if vals['curvature_modes'][axis] == CurvatureMode.AUTOFOCUS:
                    vals[axis] = ideal[axis]
        # The session's plane lock rides on instrument_state into every launch
        # and holds the arcs, so a launch starts from them.
        lock = self.instrument_state.plane_lock
        if lock is not None:
            vals['sgl'], vals['sgu'] = lock["tilts"]["sgl"], lock["tilts"]["sgu"]
        vals.update(self._lock_fields())
        return vals

    def set_default_parameters(self):
        """Set default parameters."""
        # Defaults is the one exception to the lock's refusals: it releases
        # the lock itself, then clears the rest (amend6 item 3).
        self._set_plane_lock(None)
        # Block signals during loading to prevent premature validation
        self.window.simulation_dock.scan_command_1_edit.blockSignals(True)
        self.window.simulation_dock.scan_command_2_edit.blockSignals(True)
        
        self.window.instrument_dock.set_mono_id(self.descriptor.mono_crystals[0].id)
        self.window.instrument_dock.set_ana_id(self.descriptor.ana_crystals[0].id)
        mtt, stt, omega, att = self._reference_angles(
            self.descriptor.mono_crystals[0].id, self.descriptor.ana_crystals[0].id,
        )
        self._set_tracked_angle_text('mtt', self.window.instrument_dock.mtt_edit, mtt)
        self.window.instrument_dock.stt_edit.setText(format_editable_number(stt))
        self.window.instrument_dock.omega_edit.setText(format_editable_number(omega))
        self.window.instrument_dock.sgl_edit.setText("0")
        self.window.instrument_dock.sgu_edit.setText("0")
        self._set_tracked_angle_text('att', self.window.instrument_dock.att_edit, att)
        self.window.instrument_dock.Ki_edit.setText("2.6634")
        self.window.instrument_dock.Kf_edit.setText("2.6634")
        self.window.instrument_dock.Ei_edit.setText("14.7")
        self.window.instrument_dock.Ef_edit.setText("14.7")
        # Descriptor defaults for modules/collimation/slits (empty dict = defaults)
        self.window.instrument_dock.set_module_values({})
        self.window.instrument_dock.set_source_id(self.descriptor.source_types[0].id)
        self.window.instrument_dock.source_dE_edit.setText("2")
        self.window.instrument_dock.set_collimation_values({})
        # Slit apertures - descriptor defaults (SlitSpec.default_*_mm)
        self.window.instrument_dock.set_slit_values_mm({})

        # Set default absolute bending to ideal values
        self.update_ideal_bending_buttons()
        self.apply_ideal_bending_values()
        
        self.window.simulation_dock.set_number_neutrons(1000000)
        self.window.scattering_dock.K_fixed_combo.setCurrentText("Kf Fixed")
        self.window.scattering_dock.fixed_E_edit.setText("14.7")
        self.window.scattering_dock.qx_edit.setText("3.1028")
        self.window.scattering_dock.qy_edit.setText("0")
        self.window.scattering_dock.qz_edit.setText("0")
        # Set HKL defaults - Al (200) Bragg peak
        self.window.scattering_dock.H_edit.setText("2")
        self.window.scattering_dock.K_edit.setText("0")
        self.window.scattering_dock.L_edit.setText("0")
        self.window.scattering_dock.deltaE_edit.setText("0")
        self.window.simulation_dock.diagnostic_mode_check.setChecked(True)
        
        self.window.sample_dock.lattice_a_edit.setText(format_editable_number(4.05, 6))
        self.window.sample_dock.lattice_b_edit.setText(format_editable_number(4.05, 6))
        self.window.sample_dock.lattice_c_edit.setText(format_editable_number(4.05, 6))
        self.window.sample_dock.lattice_alpha_edit.setText(format_editable_number(90, 6))
        self.window.sample_dock.lattice_beta_edit.setText(format_editable_number(90, 6))
        self.window.sample_dock.lattice_gamma_edit.setText(format_editable_number(90, 6))
        # Default scan: H-scan around Al (200) Bragg peak - quick 21 point scan
        self.window.simulation_dock.scan_command_1_edit.setText("H 1.9 2.1 0.01")
        self.window.simulation_dock.scan_command_2_edit.setText("")
        
        # Set default folder paths
        folder_suggestion = os.path.join(self.output_directory, "initial_testing")
        self.window.data_control_dock.save_folder_edit.setText(folder_suggestion)
        self.window.data_control_dock.load_folder_edit.setText(folder_suggestion)
        
        self.diagnostic_settings = DiagnosticConfigDialog.get_default_settings(
            self.descriptor.monitors
        )
        self.current_sample_settings = {}
        # The truth back to defaults (I3): no exercise (R_hidden = I, no training
        # code), the standard setting, no mounting plane, and the operator's UB
        # equal to it. Never refused (the lock was released
        # above): Defaults is the way out of any exercise state.
        self._clear_exercise()
        self.mount_plane = None
        self._set_true_mount(U_described=np.eye(3))
        self._show_mount_plane()
        self.ub_matrix = UBMatrix()
        self._update_ub_display()
        self._reconnect_peak_signals()
        # Default sample to Al: Bragg for easy testing
        try:
            self.window.sample_dock.set_sample_by_key("Al_bragg")
        except Exception:
            pass
        
        # Unblock signals after all parameters are set
        self.window.simulation_dock.scan_command_1_edit.blockSignals(False)
        self.window.simulation_dock.scan_command_2_edit.blockSignals(False)
        self._commit_programmatic_feedback(
            getattr(self, "_feedback_line_edits", ())
        )
        
        self.print_to_message_center("Default parameters loaded")
    
    def run_simulation_thread(self):
        """Start simulation in a separate thread."""
        # Pre-flight validation - check for scan command issues
        hard_issues, soft_issues = self._preflight_scan_validation()
        from PySide6.QtWidgets import QMessageBox
        if hard_issues:
            # Not a question: the command does not describe a scan that can
            # run. Offering "continue anyway" here would launch a scan over
            # a refused axis and silently overwrite the radius it pins.
            message = "\n".join(hard_issues)
            QMessageBox.critical(
                self.window, "Scan Command Rejected",
                f"{message}\n\nFix the scan command and try again."
            )
            self.print_to_message_center(f"Simulation refused: {message}")
            return
        if soft_issues:
            # Judgement calls, so they stay the operator's to make.
            reply = QMessageBox.warning(
                self.window,
                "Scan Command Issues",
                "\n".join(soft_issues)
                + "\n\nDo you want to continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self.print_to_message_center("Simulation cancelled due to scan command issues")
                return
        
        launch_state = self._collect_simulation_launch_state()
        if not launch_state:
            self.print_to_message_center("Error: Could not get GUI values")
            return
        # The one compile-and-expand, from what the docks hold at this instant.
        try:
            self._compile_launch(launch_state)
        except PlanRefused as refused:
            QMessageBox.critical(self.window, "Scan Command Rejected",
                                 f"{refused}\n\nFix the scan and try again.")
            self.print_to_message_center(f"Simulation refused: {refused}")
            return

        self.stop_event.clear()

        # Reset progress bar and show initializing state
        self.window.simulation_dock.progress_bar.setValue(0)
        self.window.simulation_dock.progress_label.setText("Initializing...")
        self.window.simulation_dock.remaining_time_label.setText("Estimated Remaining Time: calculating...")
        self.pre_scan_estimate_updated.emit("")

        self.save_parameters()
        self.window.display_dock.set_scan_metadata(self._build_scan_metadata(launch_state['vals']))

        # Route the GUI Run through the shared job queue instead of spawning a
        # bare thread: this serializes runs (fixes the concurrent double-click
        # race) and gives GUI and API submissions one execution path.
        self.submit_scan_job(launch_state, 'gui')

    def submit_scan_job(self, launch_state, source):
        """Create, register, and enqueue a scan job. GUI-thread-only entry."""
        # The job's public parameters (GET /scan/{id}) are canonical IDs; the plugins
        # keep reading the internal 'vals'.
        launch_state['public_vals'] = self.public_values(launch_state['vals'])
        job = ScanJob(
            job_id=self._job_registry.next_id(),
            source=source,
            launch_state=launch_state,
            submitted_at=time.time(),
        )
        self._job_registry.add(job)
        # Announce before enqueueing: once put() lands, the idle worker can pop
        # the job and publish job_started immediately, so publishing job_queued
        # first is the only way to guarantee queued -> started event order.
        self.job_state_changed.emit(job.job_id, JobState.QUEUED.value)
        self.print_to_message_center(f"Scan job {job.job_id} queued (source: {source})")
        self._journal.record("job", f"{job.job_id}: queued (source: {source})")
        self._publish_api_event('job_queued', {
            'job_id': job.job_id,
            'source': source,
            'position': self._job_queue.qsize(),
        })
        self._job_queue.put(job)
        return job

    def _job_worker_loop(self):
        """Persistent daemon worker: run queued scan jobs one at a time."""
        while True:
            job = self._job_queue.get()
            if job is None:
                # Sentinel from shutdown() -- exit the loop.
                break

            with job.lock:
                if job.state == JobState.CANCELLED:
                    # Cancelled before it ran; keep the registry record, skip it.
                    skip = True
                else:
                    skip = False
            if skip:
                self.job_state_changed.emit(job.job_id, JobState.CANCELLED.value)
                continue

            # Clear the shared stop event AFTER popping and BEFORE marking the
            # job RUNNING, so a Stop pressed between jobs cannot leak into the
            # next one (see docs/API_SERVER_DESIGN.md sec 7.2).
            self.stop_event.clear()
            with job.lock:
                job.state = JobState.RUNNING
                job.started_at = time.time()
                job.notify_state_change()
            self._active_job = job
            self.job_state_changed.emit(job.job_id, JobState.RUNNING.value)
            self._journal.record("job", f"{job.job_id}: started")
            self._publish_api_event('job_started', {
                'job_id': job.job_id,
                'source': job.source,
            })

            try:
                self.run_simulation(job.launch_state, job)
            except Exception as exc:
                # Unexpected failure escaping run_simulation: mark FAILED and
                # surface it -- never swallow silently.
                with job.lock:
                    job.state = JobState.FAILED
                    job.error = str(exc)
                    if job.finished_at is None:
                        job.finished_at = time.time()
                    job.notify_state_change()
                self.message_printed.emit(f"Scan job {job.job_id} failed: {exc}")
            finally:
                self._active_job = None

            with job.lock:
                final_state = job.state.value
                final_error = job.error
                final_result = job.result
            self.job_state_changed.emit(job.job_id, final_state)
            self._journal.record(
                "job",
                self._format_job_finished_summary(
                    job.job_id, final_state, final_error, final_result
                ),
            )
            # Covers both the normal-return and except (FAILED) paths, since
            # both funnel through the terminal state read above.
            self._publish_api_event('job_finished', {
                'job_id': job.job_id,
                'state': final_state,
                'error': final_error,
            })

    @Slot(str, str)
    def _on_job_state_changed(self, job_id, state):
        """GUI-thread reaction to job-queue transitions.

        Resets the progress display when a queued job actually starts, and
        keeps the Run button disabled while any job is queued or running.
        """
        if state == JobState.RUNNING.value:
            # Reset the progress display for the starting job (mirrors the prep
            # done in run_simulation_thread at submission time, so a job that
            # waited in the queue still gets a clean start).
            try:
                self.window.simulation_dock.progress_bar.setValue(0)
                self.window.simulation_dock.progress_label.setText("Initializing...")
                self.window.simulation_dock.remaining_time_label.setText(
                    "Estimated Remaining Time: calculating..."
                )
            except Exception:
                pass

        # Disable Run while work is pending/active; re-enable once idle.
        busy = self._has_pending_jobs()
        dock = getattr(self.window, 'simulation_dock', None)
        if dock is not None and hasattr(dock, 'run_button'):
            dock.run_button.setEnabled(not busy)

        # Benchmark completion hook: once every stage of the in-flight plan has
        # reached a terminal state, recompute + store this machine's speed index.
        if (job_id in self._benchmark_job_ids
                and state in _JOB_TERMINAL_STATE_VALUES
                and self._all_benchmark_jobs_terminal()):
            self._advance_benchmark()

    def _has_pending_jobs(self):
        """True if any job is currently QUEUED or RUNNING."""
        for job in self._job_registry.all_jobs():
            with job.lock:
                if job.state in (JobState.QUEUED, JobState.RUNNING):
                    return True
        return False

    # ==================================================================
    # Scan-time benchmarker (Utilities -> Scan-time benchmark)
    # ==================================================================

    def _deterministic_supported(self):
        """Whether the active instrument can run the deterministic engine.

        The analytic branch needs the plugin's ``resolution_config`` to build a
        per-point resolution kernel; without it the deterministic stage is
        omitted from the benchmark plan.
        """
        return callable(getattr(self.instrument, "resolution_config", None))

    def build_benchmark_plan(self, ncounts=None):
        """Return the benchmark plan for the current instrument.

        Delegates the plan shape to :mod:`tavi.benchmark` (Qt-free), then
        enriches each stage with ``predicted_seconds`` (the current machine-aware
        estimate for that stage) so the dialog can show a predicted duration.
        ``ncounts`` overrides the mcstas ncounts as ``(low, high)``.
        """
        from tavi.benchmark import build_benchmark_plan as _build

        plan = _build(
            ncounts=ncounts,
            deterministic_supported=self._deterministic_supported(),
        )
        for stage in plan:
            est = self.runtime_tracker.estimate_scan_seconds(
                self.instrument.id, stage["points"], stage["ncount"],
                needs_compile=stage["force_rebuild"], engine=stage["engine"],
                mpi_count=self.mpi_count,
            )
            stage["predicted_seconds"] = est.get("estimated_seconds")
        return plan

    def _benchmark_scan_command(self, points):
        """Build a tiny centred scan command around the current GUI position.

        Picks the scan variable from the first current scan command (H when
        there is none) and centres a ``points``-point sweep on that variable's
        current field value with a small fixed step. The result is a valid
        absolute scan command; ``run_benchmark`` runs it with relative mode off
        and feasibility filtering, so no point is ever driven out of range.
        """
        vals = self.get_gui_values() or {}
        commands = [(vals.get(key) or "").strip() for key in ("scan_command1", "scan_command2")]
        first = next((cmd for cmd in commands if cmd), "")
        var = self.normalize_scan_variable(first.split()[0]) if first else "h"
        try:
            center = float(self.public_values(vals).get(var, 0.0))
        except (TypeError, ValueError):
            center = 0.0

        step = 0.01
        n = max(1, int(points))
        half = step * (n - 1) / 2.0
        start = center - half
        end = center + half
        return f"{var} {start:.4f} {end:.4f} {step}"

    def run_benchmark(self, plan):
        """Queue every stage of ``plan`` as a benchmark scan job.

        Each stage re-freezes the current launch state, overrides the scan
        command with a tiny centred scan, sets the stage's engine / ncount /
        force-rebuild flag, tags it ``source="benchmark"``, and submits it
        through the existing job worker (stages run sequentially). Infeasible
        points are pre-filtered (never driven to). Refuses to start while any
        scan job is already QUEUED/RUNNING. Returns the submitted job ids.
        """
        if self._has_pending_jobs():
            self.print_to_message_center(
                "Benchmark: a scan is already running or queued; try again once idle."
            )
            return []
        if not plan:
            return []

        self.save_parameters()
        self._benchmark_plan = list(plan)
        self._benchmark_mpi_count = self.mpi_count
        self._benchmark_job_ids = []
        # Adaptive-phase bookkeeping: ncounts already submitted (loop guard) and
        # the finalize latch (cleared here so a fresh run re-arms it).
        self._benchmark_adaptive_ncounts = set()
        self._benchmark_finalized = False

        for i, stage in enumerate(plan):
            job = self._submit_benchmark_stage(stage, i)
            if job is None:
                break

        self.print_to_message_center(
            f"Benchmark: queued {len(self._benchmark_job_ids)} stage(s)."
        )
        return list(self._benchmark_job_ids)

    def _submit_benchmark_stage(self, stage, index):
        """Freeze the launch state for one benchmark ``stage`` and submit it.

        Re-freezes the current GUI launch state, overrides the scan command with
        a tiny centred scan, applies the stage's engine / ncount / force-rebuild
        flag, tags it ``source="benchmark"``, pre-filters infeasible points, and
        submits it through the job worker. Appends the new job id to
        ``_benchmark_job_ids``. Returns the submitted job, or ``None`` when the
        GUI launch state could not be read or its plan was refused.
        """
        launch_state = self._collect_simulation_launch_state()
        if not launch_state:
            self.print_to_message_center(
                "Benchmark: could not read GUI values; aborting."
            )
            return None

        vals = launch_state["vals"]
        vals["scan_command1"] = self._benchmark_scan_command(stage["points"])
        vals["scan_command2"] = ""
        vals["number_neutrons"] = int(stage["ncount"])
        # A benchmark is a machine baseline, not a diagnostic run: diagnostic
        # mode forces a rebuild every point and would break the warm stages.
        vals["diagnostic_mode"] = False

        launch_state["engine"] = stage["engine"]
        launch_state["benchmark"] = True
        launch_state["force_rebuild"] = bool(stage["force_rebuild"])
        launch_state["mpi_count"] = self._benchmark_mpi_count
        launch_state["relative_mode_1"] = False
        launch_state["relative_mode_2"] = False
        launch_state["save_folder_input"] = os.path.join(
            self.output_directory,
            f"benchmark_{stage['engine']}_{int(stage['ncount'])}_{index + 1}",
        )

        # Pre-filter infeasible points so a tiny scan near an edge geometry
        # skips rather than fails (reuses the API allow_partial machinery).
        try:
            self._compile_launch(launch_state)
            validation = self.validate_scan_launch_state(launch_state)
        except PlanRefused as refused:
            self.print_to_message_center(f"Benchmark: stage {index + 1} refused: {refused}")
            return None
        infeasible = validation.get("infeasible", [])
        if infeasible:
            launch_state["skipped_indices"] = [e["index"] for e in infeasible]
            launch_state["skipped_points"] = infeasible

        job = self.submit_scan_job(launch_state, "benchmark")
        self._benchmark_job_ids.append(job.job_id)
        return job

    def cancel_benchmark(self):
        """Cancel every in-flight benchmark stage (queued or running)."""
        self.stop_event.set()
        for job_id in list(self._benchmark_job_ids):
            self.cancel_job(job_id)

    def _all_benchmark_jobs_terminal(self):
        """True if every tracked benchmark job has reached a terminal state."""
        if not self._benchmark_job_ids:
            return False
        for job_id in self._benchmark_job_ids:
            job = self._job_registry.get(job_id)
            if job is None:
                continue
            with job.lock:
                if job.state in (JobState.QUEUED, JobState.RUNNING):
                    return False
        return True

    def _benchmark_records(self, mpi_count=None):
        """This machine's benchmark records for the active instrument.

        Only records at ``mpi_count`` (default: the configured count) or with
        no recorded count, so runs at another count never mix into a fit.
        """
        if mpi_count is None:
            mpi_count = self.mpi_count
        machine_id = machine_fingerprint()["machine_id"]
        return [
            r for r in self.runtime_tracker.records.get(self.instrument.id, [])
            if getattr(r, "machine_id", None) == machine_id
            and getattr(r, "source", "organic") == "benchmark"
            and getattr(r, "mpi_count", None) in (mpi_count, None)
        ]

    def _benchmark_adaptive_inputs(self):
        """Derive ``next_rate_stage`` inputs from this machine's benchmark records.

        Returns ``(overhead_s, last_ncount, last_spp, elapsed_adaptive_s)`` from
        the mcstas benchmark records, or ``None`` when none are usable. Overhead
        is the warm per-point time at the smallest ncount; the "last" values come
        from the highest-ncount record; elapsed is the summed wall-clock of the
        adaptive stages (ncount at or above the sweep start) recorded so far.
        """
        from tavi.benchmark import DEFAULT_ADAPTIVE_START_NCOUNT

        def spp(rec):
            return (rec.avg_subsequent_time if rec.num_points > 1
                    else rec.first_scan_time)

        recs = [
            r for r in self._benchmark_records(self._benchmark_mpi_count)
            if getattr(r, "engine", "mcstas") == "mcstas"
            and getattr(r, "num_neutrons", 0)
            and spp(r) and spp(r) > 0
        ]
        if not recs:
            return None

        lo = min(recs, key=lambda r: r.num_neutrons)
        hi = max(recs, key=lambda r: r.num_neutrons)
        elapsed = sum(
            r.total_time for r in recs
            if r.num_neutrons >= DEFAULT_ADAPTIVE_START_NCOUNT and r.total_time
        )
        return (spp(lo), hi.num_neutrons, spp(hi), elapsed)

    def _advance_benchmark(self):
        """Drive the adaptive rate sweep, or finalize when it is complete.

        Called whenever every tracked benchmark job is terminal. Submits the
        next adaptive rate stage (appending it to the growing plan) when
        :func:`tavi.benchmark.next_rate_stage` asks for one and its ncount has
        not already been attempted (loop guard); otherwise finalizes.
        """
        from tavi.benchmark import next_rate_stage

        if self._benchmark_finalized:
            return

        stage = None
        inputs = self._benchmark_adaptive_inputs()
        if inputs is not None:
            overhead_s, last_ncount, last_spp, elapsed = inputs
            candidate = next_rate_stage(overhead_s, last_ncount, last_spp, elapsed)
            # Loop guard: never resubmit an ncount already attempted (e.g. a
            # failed stage produced no record, so inputs would repeat).
            if candidate is not None and \
                    int(candidate["ncount"]) not in self._benchmark_adaptive_ncounts:
                stage = candidate

        if stage is not None:
            self._benchmark_adaptive_ncounts.add(int(stage["ncount"]))
            self._benchmark_plan = list(self._benchmark_plan or []) + [stage]
            job = self._submit_benchmark_stage(stage, len(self._benchmark_plan) - 1)
            if job is not None:
                self.print_to_message_center(
                    f"Benchmark: adaptive rate stage at {int(stage['ncount'])} neutrons."
                )
                return
            # Submission failed (no GUI state): fall through to finalize.

        self._finalize_benchmark()

    def _finalize_benchmark(self):
        """Fit + store this machine's affine time model, then signal the dialog.

        Runs once the base plan and the adaptive rate sweep are complete. The
        model is the affine ``{overhead, rate}`` fit over this machine's
        benchmark records (:func:`tavi.machine_profile.machine_time_model`),
        stored as a v2 machine profile; it anchors cross-machine scaling in the
        estimator.
        """
        from tavi.machine_profile import machine_time_model

        self._benchmark_finalized = True
        fp = machine_fingerprint()
        machine_id = fp["machine_id"]
        # Ceiling: one stored profile per machine, not per MPI count; after a
        # count change it keeps this fit until the benchmark is re-run. It only
        # anchors cross-machine scaling; same-count local history wins.
        model = machine_time_model(self._benchmark_records(self._benchmark_mpi_count))
        overhead = model["overhead"] if model else None
        rate = model["rate"] if model else None
        try:
            self.runtime_tracker.set_machine_profile(
                machine_id=machine_id,
                hostname=fp.get("hostname", ""),
                cpu_name=fp.get("cpu_name", ""),
                cpu_count=fp.get("cpu_count", 0),
                overhead_seconds=overhead,
                rate_per_neutron=rate,
            )
        except Exception as exc:
            self.print_to_message_center(
                f"Benchmark: could not store machine profile ({exc})."
            )

        # Clear the in-flight tracking so a later normal scan cannot re-trigger.
        self._benchmark_job_ids = []
        if model:
            self.print_to_message_center(
                "Benchmark complete. Machine time model: "
                f"overhead {overhead:.3g} s, rate {rate:.3e} s/neutron."
            )
        else:
            self.print_to_message_center(
                "Benchmark complete. Machine time model unavailable "
                "(insufficient ncount spread)."
            )
        self.runtime_data_updated.emit()
        self.benchmark_finished.emit()

    def benchmark_crosscheck(self, plan=None):
        """Cross-check the latest benchmark against organic-history predictions.

        For each stage, pairs the measured benchmark time (from this machine's
        benchmark records) with the estimate the organic history alone would
        have produced for the same config, and reports the signed drift percent.
        Headless-testable; feeds the dialog's cross-check table. Returns a list
        of ``{label, measured, predicted, drift_pct}`` rows.
        """
        from tavi.benchmark import crosscheck_rows

        if plan is None:
            plan = self._benchmark_plan or self.build_benchmark_plan()

        # The last benchmark's own count, even if the setting changed since.
        mpi_count = self._benchmark_mpi_count or self.mpi_count
        recs = self._benchmark_records(mpi_count)

        stage_results = []
        for stage in plan:
            measured = self._latest_benchmark_measured(recs, stage)
            predicted = self.runtime_tracker.estimate_scan_seconds(
                self.instrument.id, stage["points"], stage["ncount"],
                needs_compile=stage["force_rebuild"], engine=stage["engine"],
                source="organic", mpi_count=mpi_count,
            ).get("estimated_seconds")
            stage_results.append({
                "label": stage["label"],
                "measured": measured,
                "predicted": predicted,
            })
        return crosscheck_rows(stage_results)

    @staticmethod
    def _latest_benchmark_measured(records, stage):
        """Total time of the most recent benchmark record matching ``stage``.

        Matches on engine + neutron count (points may differ when infeasible
        points were skipped). Returns ``None`` when no record matches.
        """
        engine = stage["engine"]
        ncount = int(stage["ncount"])
        match = [
            r for r in records
            if getattr(r, "engine", "mcstas") == engine
            and getattr(r, "num_neutrons", None) == ncount
        ]
        if not match:
            return None
        return match[-1].total_time

    def _publish_api_event(self, event: str, data: dict):
        """Publish an SSE event to API clients, if a server is attached.

        No-op when no API server is running. Thread-safe -- the ``SseBroker``
        does its own locking -- so this may be called from the scan worker
        thread beside the corresponding Qt signal emits (see
        docs/API_SERVER_DESIGN.md sec 9). Publish failures are surfaced once to
        the message center; identical consecutive errors are suppressed so a
        persistent fault cannot spam the log.
        """
        server = getattr(self, 'api_server', None)
        if server is None:
            return
        try:
            server.publish(event, dict(data, api_version=API_VERSION))
            self._api_publish_last_error = None
        except Exception as exc:
            msg = f"API: failed to publish '{event}' event: {exc}"
            if msg != getattr(self, '_api_publish_last_error', None):
                self._api_publish_last_error = msg
                self.message_printed.emit(msg)


    def _format_job_finished_summary(self, job_id, state, error, result):
        """Build the one-line journal summary for a finished job.

        DONE jobs get a data summary (variable, range, point count, peak);
        failed/stopped/cancelled jobs get the terminal state plus any reason.
        Best-effort and defensive -- a summary failure must never break the
        worker loop, so any unexpected shape degrades to the bare state line.
        """
        try:
            if state == JobState.DONE.value and result is not None:
                return self._format_scan_result_summary(job_id, result)
            if error:
                return f"{job_id}: {state} ({error})"
            return f"{job_id}: {state}"
        except Exception:
            return f"{job_id}: {state}"

    @staticmethod
    def _format_scan_result_summary(job_id, result):
        """One-line human summary of a finished ScanResult (1D or 2D)."""
        var = getattr(result, "variable_1", None) or "scan"
        parts = [f"{job_id}: {var} scan"]
        values = list(getattr(result, "scan_values_1", None) or [])
        if values:
            parts[0] += f" {values[0]:.3f} to {values[-1]:.3f}"

        # Peak location: 1D uses counts[], 2D uses counts_grid[row=y][col=x].
        counts = getattr(result, "counts", None)
        grid = getattr(result, "counts_grid", None)
        npts = 0
        peak = None  # (counts, description)
        if counts is not None:
            npts = len(counts)
            for i, c in enumerate(counts):
                if c is None:
                    continue
                if peak is None or c > peak[0]:
                    label = values[i] if i < len(values) else i
                    peak = (c, f"{var}={label:.3f}" if isinstance(label, float)
                            else f"{var}={label}")
        elif grid is not None:
            values2 = list(getattr(result, "scan_values_2", None) or [])
            var2 = getattr(result, "variable_2", None) or "scan2"
            for iy, row in enumerate(grid):
                for ix, c in enumerate(row or []):
                    npts += 1 if c is not None else 0
                    if c is None:
                        continue
                    if peak is None or c > peak[0]:
                        xl = values[ix] if ix < len(values) else ix
                        yl = values2[iy] if iy < len(values2) else iy
                        peak = (c, f"{var}={xl}, {var2}={yl}")

        parts.append(f"{npts} pts")
        if peak is not None:
            parts.append(f"max {int(peak[0])} counts at {peak[1]}")
        return ", ".join(parts)

    def _preflight_scan_validation(self):
        """Check scan commands before running simulation (GUI wrapper).

        Reads the scan-command widgets and delegates to the pure
        ``_scan_command_issues`` so the GUI Run path and the API path share
        one validation implementation.

        Also folds in ``_held_curvature_issues`` (a HELD radius outside its
        declared travel, or off a fixed axis's declared radius): that check
        has no scan-command text to attach to, so it belongs beside this
        wrapper's other pre-launch gate rather than inside
        ``_scan_command_issues``, which is parameterized on command strings
        alone.

        Returns:
            tuple: (hard, soft) issue lists. Hard cannot be overridden --
            the command does not describe a scan that can run. Soft is the
            operator's judgement to make.
        """
        cmd1 = self.window.simulation_dock.scan_command_1_edit.text().strip()
        cmd2 = self.window.simulation_dock.scan_command_2_edit.text().strip()
        dock = self.window.instrument_dock
        monocris, anacris = dock.selected_mono_id(), dock.selected_ana_id()
        modules = dock.module_values()
        relative_1 = self.window.simulation_dock.relative_1_button.isChecked()
        relative_2 = self.window.simulation_dock.relative_2_button.isChecked()
        hard, soft = self._scan_command_issues(
            cmd1, cmd2, monocris, anacris, modules,
            relative_1=relative_1, relative_2=relative_2,
            current_values=self._current_curvature_field_values(),
        )
        scan_named_axes = self._scan_named_curvature_axes(cmd1, cmd2)
        hard = hard + self._held_curvature_issues(
            monocris, anacris, scan_named_axes=scan_named_axes
        )
        return hard, soft

    def _current_curvature_field_values(self):
        """{axis: float-or-None} read straight from the instrument-dock
        curvature fields -- the base a relative scan command expands
        against. ``None`` for a field that does not parse as a number,
        matching ``_held_curvature_issues``'s own read of the same widgets.
        """
        idock = self.window.instrument_dock
        axis_edits = {
            "rhm": idock.rhm_edit, "rvm": idock.rvm_edit,
            "rha": idock.rha_edit, "rva": idock.rva_edit,
        }
        values = {}
        for axis, edit in axis_edits.items():
            try:
                values[axis] = float(edit.text())
            except ValueError:
                values[axis] = None   # empty or not a number: no base to step from
        return values

    def _scan_command_issues(self, cmd1: str, cmd2: str,
                             monocris=None, anacris=None, modules=None,
                             relative_1=False, relative_2=False,
                             current_values=None):
        """(hard, soft) issue lists for two scan-command strings.

        Hard means the command cannot run as written -- an unknown or
        refused variable, a malformed command. Soft means it can run but
        probably should not, which is the operator's call. Whether the two
        commands can run together is the plan's judgement, made when the
        launch compiles (``_compile_launch``), never here.

        Parameterized on strings only -- reads no widgets -- so both the GUI
        Run button and the remote API can call it. ``monocris``/``anacris`` name
        the crystals the scan will run with, and ``modules`` the module state
        (e.g. a nested mirror optic combo), which together decide whether a
        curvature axis is refused; the API passes the frozen request's, not
        the GUI's. ``relative_1``/``relative_2`` are each command's own
        relative-mode flag (independent per command, exactly like a 2D scan's
        two commands run under independent modes); ``current_values`` is the
        {axis: float-or-None} mapping of the launch's current curvature
        values a relative command expands against -- see
        ``_validate_single_scan_command``.
        Returns an empty string when the commands are acceptable, or a
        newline-joined description of the blocking issues.

        A command that came back with no variable is a hard rejection and
        always blocks. Sniffing the message text for a warning marker used to
        decide this, so every rejection whose wording lacked the marker --
        an incomplete command, unparseable numbers, a refused fixed curvature
        axis -- was reported to the operator and then launched anyway.
        """
        cmd1 = (cmd1 or "").strip()
        cmd2 = (cmd2 or "").strip()
        curvature_axes = self._curvature_axis_specs(monocris, anacris, modules=modules)

        hard = []
        soft = []

        for label, cmd, relative in (
            ("Command 1", cmd1, relative_1), ("Command 2", cmd2, relative_2)
        ):
            var, warning = self._validate_single_scan_command(
                cmd, curvature_axes, relative=relative,
                current_values=current_values,
            )
            if not warning:
                continue
            # var is None -> the command cannot run as written, whatever the
            # wording. Anything else marked serious is a judgement the
            # operator is allowed to overrule (a very long scan, say).
            if var is None:
                hard.append(f"{label}: {warning}")
            elif "⚠" in warning:
                soft.append(f"{label}: {warning}")

        return hard, soft

    def _validate_scan_commands_text(self, cmd1: str, cmd2: str,
                                     monocris=None, anacris=None,
                                     modules=None) -> str:
        """Hard and soft issues joined as one string, or "" when there are none.

        For callers that only want the text. The API gate reads
        ``_scan_command_issues`` itself, because ``force`` may clear the soft
        issues only (``TaviApiBackend._blocking_scan_issues``).
        """
        hard, soft = self._scan_command_issues(cmd1, cmd2, monocris, anacris, modules)
        return "\n".join(hard + soft)

    # ------------------------------------------------------------- remote API
    #
    # Parameter writes coming from the remote API (docs/API_SERVER_DESIGN.md
    # sec 8). The field map mirrors get_gui_values() exactly; apply_parameters()
    # parses/validates every field first, then applies valid ones in dependency
    # order and fires each after-handler once. All of this runs on the GUI
    # thread (the backend invokes it via ApiBridge.call_on_gui).

    @staticmethod
    def _api_fmt(v) -> str:
        """Format a numeric value for a QLineEdit (compact, round-trippable)."""
        return "%.10g" % float(v)

    def _api_field_map(self):
        """Return ``{field: (parse_fn, setter_fn, after_handler_or_None)}``.

        Keyed by canonical ID for every quantity (the GUI values' internal names
        are renamed at the end; the slit gaps of this instrument are one key each)
        and by its own name for every other setting.

        Covers every WRITABLE key ``get_gui_values()`` returns. ``parse_fn(value)``
        validates/coerces the incoming JSON value (raising ``ValueError`` with a
        human message on bad input), ``setter_fn(parsed)`` writes the widget,
        and ``after_handler`` (zero-arg or ``None``) recomputes derived state --
        the same handler the user's Enter key would trigger.

        Deliberately excluded, though ``get_gui_values()``/``GET /parameters``/
        ``GET /state`` all expose it: ``curvature_modes``, read-only derived
        state (``build_api_schema`` declares it with ``readOnly: True``). It is
        computed from the Ideal locks and from which axes a scan command names
        -- a second way to set it here would be a new twin of that logic, not a
        convenience.
        """
        w = self.window
        idock = w.instrument_dock
        sdock = w.scattering_dock
        sam = w.sample_dock
        sim = w.simulation_dock

        # --- parse helpers ---
        def p_float(v):
            return float(v)

        def p_int_pos(v):
            n = int(float(v))
            if n <= 0:
                raise ValueError("must be a positive integer")
            return n

        def p_str(v):
            if not isinstance(v, str):
                raise ValueError("must be a string")
            return v

        def p_bool(v):
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return bool(v)
            raise ValueError("must be a boolean")

        def p_dict(v):
            if not isinstance(v, dict):
                raise ValueError("must be an object/dict")
            return v

        def p_choice(valid, label):
            valid = set(valid)

            def _parse(v):
                if v not in valid:
                    raise ValueError(
                        "%s must be one of %s" % (label, sorted(valid))
                    )
                return v
            return _parse

        def p_modules(v):
            """Validate a ``modules`` patch against this instrument's own
            descriptor -- a CHOICE value must be a declared option, a TOGGLE
            value must be a bool (``p_bool``'s leniency), and an id not on the
            descriptor is an error. An omitted id is not an error: it is left
            out of the returned dict entirely, and stays accepted (today's
            PATCH behaviour, preserved -- ``set_module_values`` and
            ``build_api_launch_state``'s refill both fall back to the
            descriptor default for whatever this omits).
            """
            from instruments.descriptor import ModuleKind

            if not isinstance(v, dict):
                raise ValueError("must be an object/dict")
            declared = {m.id: m for m in self.descriptor.modules}
            unknown = set(v) - set(declared)
            if unknown:
                raise ValueError(
                    "unknown module(s) %s; declared: %s"
                    % (sorted(unknown), sorted(declared))
                )
            parsed = {}
            for module_id, value in v.items():
                module = declared[module_id]
                if module.kind is ModuleKind.CHOICE:
                    if value not in module.options:
                        raise ValueError(
                            "%s must be one of %s" % (module_id, sorted(module.options))
                        )
                    parsed[module_id] = value
                else:
                    try:
                        parsed[module_id] = p_bool(value)
                    except ValueError as exc:
                        raise ValueError("%s %s" % (module_id, exc))
            return parsed

        mono_ids = [c.id for c in self.descriptor.mono_crystals]
        ana_ids = [c.id for c in self.descriptor.ana_crystals]
        source_ids = [s.id for s in self.descriptor.source_types]
        sample_ids = [s.id for s in self.descriptor.samples]

        # --- sample setter: select the sample combo by library id -----------
        # "none" maps to the internal key None (no sample component). Setting the
        # combo emits currentTextChanged -> on_sample_changed, so the same GUI
        # bookkeeping (instrument_state.sample_key, lattice adoption) the user's
        # click triggers runs here too -- no separate after-handler needed.
        def set_sample(sample_id):
            key = None if sample_id == "none" else sample_id
            if not sam.set_sample_by_key(key):
                raise ValueError("unknown sample %r" % (sample_id,))

        # --- line-edit setter factory (numeric) ---
        def set_text(edit):
            return lambda v: self._set_and_confirm_text(edit, self._api_fmt(v))

        # --- bending setter factory (write the field, then unlock ideal) ---
        # The unlock must happen in the SETTER phase, not the after-handler:
        # apply_parameters() runs every setter before any after-handler runs,
        # so a batch naming several radii would otherwise have one field's
        # after-handler (which also refreshes all four locked fields) fire
        # while a sibling radius is still AUTOFOCUS-locked and overwrite the
        # value that was just written. Unlocking here means every commanded
        # axis is already unlocked by the time any refresh happens.
        def set_bend(key, edit):
            def _set(v):
                self._set_and_confirm_text(edit, self._api_fmt(v))
                self.unlock_ideal_bending(key)
            return _set

        # --- curvature parser: finite, because PATCH writes straight to the
        # widget. `p_float` is bare float(), so "nan" parses and lands in the
        # line edit; a later read path (compute_resolution, behind GET
        # /resolution) copies GUI values into a config by direct assignment,
        # never crossing curvature_command_error, so neither the submission
        # gate nor set_crystal_bending's backstop ever sees it. Launch already
        # refuses a non-finite radius -- refusing it here is what stops PATCH
        # and launch disagreeing. Scoped to the four radius fields on purpose:
        # p_float's acceptance of "nan" for the ~30 other numeric fields is a
        # wider, separately tracked gap.
        def p_curvature(v):
            value = float(v)
            if not math.isfinite(value):
                raise ValueError("must be a finite number")
            return value

        # --- arc parser: a readout outside the arc's travel is refused with
        # the words an angle-mode point past travel gets.
        def p_arc(name):
            def parse(v):
                value = p_float(v)
                past = self.instrument_state.arc_travel_flags({name: value})
                if past:
                    raise ValueError(describe_scan_error_flags(past))
                return value
            return parse

        # --- lock plane: {"u": [h, k, l], "v": [h, k, l]} ---
        def p_lock_plane(v):
            if not isinstance(v, dict) or set(v) != {"u", "v"}:
                raise ValueError('must be an object {"u": [h, k, l], "v": [h, k, l]}')
            plane = []
            for key in ("u", "v"):
                hkl = v[key]
                if (not isinstance(hkl, list) or len(hkl) != 3
                        or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                   and math.isfinite(x) for x in hkl)):
                    raise ValueError(f"{key} must be three finite numbers [h, k, l]")
                plane.append(tuple(float(x) for x in hkl))
            return tuple(plane)

        fields = {
            # the scattering-plane lock: applied by apply_parameters itself,
            # which validates the whole body first (_lock_refusals/_lock_action)
            'orientation_mode': (p_choice(["free", "locked"], "orientation_mode"), None, None),
            'lock_plane': (p_lock_plane, None, None),
            # angles
            'mtt': (p_float, set_text(idock.mtt_edit), self.on_mtt_changed),
            'stt': (p_float, set_text(idock.stt_edit), self.on_stt_changed),
            'omega': (p_float, set_text(idock.omega_edit), self.on_omega_changed),
            'sgl': (p_arc('sgl'), set_text(idock.sgl_edit), self.on_arc_changed),
            'sgu': (p_arc('sgu'), set_text(idock.sgu_edit), self.on_arc_changed),
            'att': (p_float, set_text(idock.att_edit), self.on_att_changed),
            # energies
            'Ki': (p_float, set_text(idock.Ki_edit), self.on_Ki_changed),
            'Ei': (p_float, set_text(idock.Ei_edit), self.on_Ei_changed),
            'Kf': (p_float, set_text(idock.Kf_edit), self.on_Kf_changed),
            'Ef': (p_float, set_text(idock.Ef_edit), self.on_Ef_changed),
            # energy mode
            'K_fixed': (
                p_choice(["Ki Fixed", "Kf Fixed"], "K_fixed"),
                sdock.K_fixed_combo.setCurrentText,
                self.on_K_fixed_changed,
            ),
            'fixed_E': (p_float, set_text(sdock.fixed_E_edit), self.on_fixed_E_changed),
            # Q
            'qx': (p_float, set_text(sdock.qx_edit), self.on_Q_changed),
            'qy': (p_float, set_text(sdock.qy_edit), self.on_Q_changed),
            'qz': (p_float, set_text(sdock.qz_edit), self.on_Q_changed),
            # HKL
            'H': (p_float, set_text(sdock.H_edit), self.on_HKL_changed),
            'K': (p_float, set_text(sdock.K_edit), self.on_HKL_changed),
            'L': (p_float, set_text(sdock.L_edit), self.on_HKL_changed),
            'deltaE': (p_float, set_text(sdock.deltaE_edit), self.on_deltaE_changed),
            # lattice
            'lattice_a': (p_float, set_text(sam.lattice_a_edit), self.on_lattice_changed),
            'lattice_b': (p_float, set_text(sam.lattice_b_edit), self.on_lattice_changed),
            'lattice_c': (p_float, set_text(sam.lattice_c_edit), self.on_lattice_changed),
            'lattice_alpha': (p_float, set_text(sam.lattice_alpha_edit), self.on_lattice_changed),
            'lattice_beta': (p_float, set_text(sam.lattice_beta_edit), self.on_lattice_changed),
            'lattice_gamma': (p_float, set_text(sam.lattice_gamma_edit), self.on_lattice_changed),
            # sample selection (drives instrument_state.sample_key + lattice)
            'sample': (p_choice(sample_ids, "sample"), set_sample, None),
            # crystals
            'monocris': (
                p_choice(mono_ids, "monocris"),
                idock.set_mono_id,
                self.update_monocris_info,
            ),
            'anacris': (
                p_choice(ana_ids, "anacris"),
                idock.set_ana_id,
                self.update_anacris_info,
            ),
            # bending radii
            'rhm': (p_curvature, set_bend('rhm', idock.rhm_edit), self.update_ideal_bending_buttons),
            'rvm': (p_curvature, set_bend('rvm', idock.rvm_edit), self.update_ideal_bending_buttons),
            'rha': (p_curvature, set_bend('rha', idock.rha_edit), self.update_ideal_bending_buttons),
            'rva': (p_curvature, set_bend('rva', idock.rva_edit), self.update_ideal_bending_buttons),
            # source
            'source_type': (p_choice(source_ids, "source_type"), idock.set_source_id, None),
            'source_dE': (p_float, set_text(idock.source_dE_edit), None),
            # descriptor-driven containers
            'modules': (p_modules, idock.set_module_values, self.update_ideal_bending_buttons),
            'collimation': (p_dict, idock.set_collimation_values, None),
            # simulation control
            'number_neutrons': (p_int_pos, sim.set_number_neutrons, None),
            'scan_command1': (p_str, lambda v: self._set_and_confirm_text(sim.scan_command_1_edit, v), self.validate_scan_commands),
            'scan_command2': (p_str, lambda v: self._set_and_confirm_text(sim.scan_command_2_edit, v), self.validate_scan_commands),
            'diagnostic_mode': (p_bool, sim.diagnostic_mode_check.setChecked, None),
        }
        fields = {_to_public(name): spec for name, spec in fields.items()}
        # Slit gaps: only this instrument's own apertures, one key per gap, in mm.
        for qid, edit in self._slit_gap_edits().items():
            fields[qid] = (p_float, set_text(edit), None)
        return fields

    def _api_resolve_patch(self, patch, field_map):
        """Resolve the names of one write: ``({key: value}, {key: name as sent}, {name: refusal})``.

        Canonical IDs and registry aliases (any case) both work; two names for one
        quantity, a retired or derived-only name, an unknown name and a slit of another
        instrument are refusals, found before anything is applied.
        """
        keys, errors = normalize_write_names(
            patch, set(field_map) | set(self._API_READ_ONLY_FIELDS))
        return ({key: patch[name] for name, key in keys.items()},
                {key: name for name, key in keys.items()}, errors)

    # Dependency order for applying API parameter writes (sec 8 step b): lattice
    # first, then energy mode, then Q/HKL, then angles. Fields not listed are
    # applied afterward in patch order.
    _API_APPLY_ORDER = tuple(_to_public(name) for name in (
        # Sample first: selecting it adopts the sample's own lattice, so an
        # explicit lattice_* in the same patch (applied next) still wins.
        'sample',
        'lattice_a', 'lattice_b', 'lattice_c',
        'lattice_alpha', 'lattice_beta', 'lattice_gamma',
        'K_fixed', 'fixed_E', 'Ki', 'Ei', 'Kf', 'Ef',
        'qx', 'qy', 'qz', 'H', 'K', 'L', 'deltaE',
        'mtt', 'stt', 'omega', 'sgl', 'sgu', 'att',
    ))

    # Keys the API reports that no write may set (declared readOnly in
    # build_api_schema): derived curvature policy, the mounting plane, which
    # only the Sample dock's Apply/Clear remounts, and the lock's stale mark
    # (``lock_stale``, in /state only).
    _API_READ_ONLY_FIELDS = ('curvature_modes', 'mount_plane_u', 'mount_plane_v', 'lock_stale')

    # The lock's request fields, and the fields a locked plane holds.
    _LOCK_FIELDS = ('orientation_mode', 'lock_plane')
    _LOCK_HELD_FIELDS = ('sample_lower_arc_deg', 'sample_upper_arc_deg')

    def _lock_refusals(self, body):
        """{field: reason} for the fields of one request body a lock refuses:
        sgl or sgu beside orientation_mode/lock_plane (whichever way it
        switches: two requests instead); any other field beside a lock request
        (orientation_mode "locked" or lock_plane), so the lock is computed on
        the state as it stands, never on a lattice or UB the same body
        changes; and sgl or sgu while locked."""
        held = [n for n in body if n in self._LOCK_HELD_FIELDS]
        mode = [n for n in body if n in self._LOCK_FIELDS]
        if held and mode:
            reason = ("orientation_mode/lock_plane cannot be combined with "
                      "sample_lower_arc_deg or sample_upper_arc_deg in one request; send two")
            return {n: reason for n in held + mode}
        other = [n for n in body if n not in self._LOCK_FIELDS]
        if other and (body.get('orientation_mode') == "locked" or 'lock_plane' in body):
            reason = ('a lock request (orientation_mode "locked" or lock_plane) must stand '
                      "alone; send two PATCHes instead")
            return {n: reason for n in mode + other}
        if held and self._lock_text():
            return {n: f"{self._lock_text()} holds {n}; release it first "
                       f"(orientation_mode \"free\")" for n in held}
        return {}

    def _lock_action(self, mode, plane):
        """What a valid lock request does: ("release", None), ("keep", lock)
        or ("lock", new lock). ``mode`` "locked", or a ``plane`` alone, asks
        for a lock (the default plane when none is given). ValueError with the
        reason when refused (a lock past travel included)."""
        lock = self.instrument_state.plane_lock
        if mode == "free":
            if plane is not None:
                raise ValueError('lock_plane needs orientation_mode "locked"')
            return ("release", None)
        if lock is not None:
            if plane is None or [list(plane[0]), list(plane[1])] == [lock["hkl_u"], lock["hkl_v"]]:
                return ("keep", lock)
            raise ValueError(f"{self._lock_text()} is in force; release it first")
        return ("lock", self._lock_for(plane or self._default_lock_plane()))

    def _scan_busy(self):
        """True when any scan job is queued or running.

        Single source of truth for the "don't move the instrument now" guard,
        shared by the API's PATCH /parameters busy check
        (``TaviApiBackend._has_active_or_queued``) and the GUI-side goto. A
        RUNNING job is exactly ``self._active_job``, so scanning the registry
        covers both.
        """
        for job in self._job_registry.all_jobs():
            with job.lock:
                if job.state in (JobState.QUEUED, JobState.RUNNING):
                    return True
        return False

    def goto_scan_variable(self, variable, value, label="goto"):
        """Move the instrument by setting the scanned variable's parameter field.

        Policy (which variables are goto-able, what refusals say, how the
        result is worded) lives in ``tavi.scan_fits``; this method only does
        the widget work: snapshot the old reading, patch the one field through
        ``apply_parameters``, and report.

        ``label`` names the origin of the target ("goto CEN", "goto FIT", ...)
        and opens every message this call produces.

        Returns ``(ok: bool, message: str)``. GUI-thread only.
        """
        plan = scan_fits.plan_goto(variable, value, busy=self._scan_busy())
        if not plan.ok:
            message = f"{label} refused: {plan.reason}"
            self.print_to_message_center(message)
            return False, message

        # get_gui_values() returns None when a widget will not parse. Either
        # way the old reading may be unavailable: the goto still runs, but
        # there is then nothing to revert to.
        current = self.get_gui_values()
        old_value = self.public_values(current).get(plan.field) if current else None

        applied, errors = self.apply_parameters({plan.field: plan.value})
        if errors or plan.field not in applied:
            detail = errors.get(plan.field) or "field was not applied"
            message = f"{label} failed: {plan.field}: {detail}"
            self.print_to_message_center(message)
            return False, message

        self._last_goto = {
            "field": plan.field,
            "old_value": old_value,
            "variable": plan.variable,
        }

        message = scan_fits.format_goto_message(
            label, plan.variable, plan.field, old_value, plan.value
        )
        self.print_to_message_center(message)
        self._journal.record("parameter", "goto: " + message)
        return True, message

    def revert_last_goto(self):
        """Restore the field value from before the last goto.

        Single level only: one goto, one revert. Returns ``(ok, message)``.
        GUI-thread only.
        """
        snapshot = self._last_goto
        if snapshot is None:
            message = "revert refused: nothing to revert"
            self.print_to_message_center(message)
            return False, message
        if self._scan_busy():
            message = "revert refused: a scan is running or queued"
            self.print_to_message_center(message)
            return False, message

        field = snapshot["field"]
        old_value = snapshot["old_value"]
        if old_value is None:
            # Nothing to restore to; drop the snapshot so the button stops
            # offering an action that cannot work.
            self._last_goto = None
            message = f"revert refused: previous value of {field} unknown"
            self.print_to_message_center(message)
            return False, message

        applied, errors = self.apply_parameters({field: old_value})
        if errors or field not in applied:
            detail = errors.get(field) or "field was not applied"
            message = f"revert failed: {field}: {detail}"
            self.print_to_message_center(message)
            return False, message  # snapshot kept: the user may retry

        self._last_goto = None
        message = scan_fits.format_revert_message(field, old_value)
        self.print_to_message_center(message)
        self._journal.record("parameter", message)
        return True, message

    def can_revert_goto(self):
        """True when :meth:`revert_last_goto` has a value to restore."""
        return bool(self._last_goto) and self._last_goto.get("old_value") is not None

    def apply_parameters(self, patch: dict):
        """Apply a parameter patch to the GUI widgets. GUI-thread only.

        Steps (docs/API_SERVER_DESIGN.md sec 8):
          a) parse/validate every field first, collecting per-field errors;
             the plane lock is judged on the whole body, and a refused lock
             request or a field the lock holds applies nothing at all;
          b) apply the lock request (only a release can share a body, as a
             lock request stands alone), then valid fields in dependency order
             (lattice -> energy mode -> Q/HKL -> angles -> the rest in patch order);
          c) fire each field's after-handler once (deduped, order preserved);
          d) log a summary to the message center;
          e) return (applied, errors).
        """
        field_map = self._api_field_map()
        applied = {}

        if not isinstance(patch, dict):
            return applied, {"_": "patch must be a JSON object"}

        # (0) Names first: a retired, unknown, derived-only or twice-assigned name
        # refuses the whole request, so a client cannot mistake a partial write for
        # one that honoured the name it still sends. Read-only fields are known
        # names (declared readOnly in build_api_schema; see _api_field_map's
        # docstring) and refuse the request the same way.
        patch, submitted, errors = self._api_resolve_patch(patch, field_map)
        errors.update({submitted[name]: "read-only field"
                       for name in patch if name in self._API_READ_ONLY_FIELDS})
        if errors:
            return applied, errors

        # (a) Parse/validate everything first; never partially apply a field.
        parsed = {}
        for name, value in patch.items():
            try:
                parsed[name] = field_map[name][0](value)
            except (ValueError, TypeError) as exc:
                errors[submitted[name]] = "invalid value: %s" % exc

        # (a') The lock is validated over the whole body; a refused lock
        # request, or a field the lock holds, applies nothing at all.
        lock_errors = {submitted[name]: reason
                       for name, reason in self._lock_refusals(patch).items()}
        errors.update(lock_errors)
        lock_request = any(n in patch for n in self._LOCK_FIELDS)
        lock_action = None
        if lock_request and not errors:
            try:
                lock_action = self._lock_action(parsed.get('orientation_mode'),
                                                parsed.get('lock_plane'))
            except ValueError as exc:
                field = 'lock_plane' if 'lock_plane' in parsed else 'orientation_mode'
                errors[submitted[field]] = "refused: %s" % exc
        if lock_errors or (lock_request and errors):
            return applied, errors

        after_handlers = []  # deduped-by-identity, order preserved
        if lock_action is not None:
            # A lock request stands alone (_lock_refusals), so only a release
            # shares a body: released first, the other fields solve free.
            action, lock = lock_action
            if action != "keep":
                self._set_plane_lock(lock)
            for name in self._LOCK_FIELDS:
                if name in parsed:
                    applied[name] = patch[name]
                    parsed.pop(name)
            after_handlers.append(self._update_ub_display)

        # (b) Apply valid fields in dependency order, then leftover patch order.
        ordered = [n for n in self._API_APPLY_ORDER if n in parsed]
        ordered += [n for n in patch.keys() if n in parsed and n not in ordered]

        for name in ordered:
            _parse_fn, setter_fn, after = field_map[name]
            value = parsed[name]
            try:
                setter_fn(value)
            except Exception as exc:  # setter failure: surface, do not swallow
                errors[submitted[name]] = "could not apply: %s" % exc
                continue
            applied[name] = value
            if after is not None and after not in after_handlers:
                after_handlers.append(after)

        # (c) Fire each after-handler once, in dependency order.
        for handler in after_handlers:
            try:
                handler()
            except Exception as exc:
                self.print_to_message_center(
                    f"API: after-update handler {getattr(handler, '__name__', handler)} "
                    f"failed: {exc}"
                )

        # Direct writes already flashed through _set_and_confirm_text().  The
        # handlers may have written dependent fields while ``updating`` was
        # true; make those baselines current without giving every derived
        # value a separate success flash.
        self._commit_programmatic_feedback()

        # (d) Summary to the message center.
        if applied:
            parts = []
            for k, v in applied.items():
                if isinstance(v, (dict, set)):
                    parts.append(k)
                else:
                    parts.append(f"{k}={v}")
            self.print_to_message_center("API: set " + ", ".join(parts))
            self._publish_api_event('parameters_changed', {
                'fields': list(applied),
                'source': 'api',
            })
            self._journal.record(
                "parameter", "api: set " + ", ".join(str(k) for k in applied)
            )

        # (e) Report back for the HTTP response.
        return applied, errors

    def _count_scan_points(self, scan_command1: str, scan_command2: str) -> int:
        """Number of points a scan will run, mirroring run_simulation's logic.

        Blank/single command -> 1; a single command -> len(values); both
        commands -> product. Used for API budget enforcement.
        """
        c1 = (scan_command1 or "").strip()
        c2 = (scan_command2 or "").strip()

        def npts(cmd):
            _, values = parse_scan_steps(cmd)
            return len(values)

        if not c1 and not c2:
            return 1
        if c1 and not c2:
            return npts(c1)
        if c2 and not c1:
            return npts(c2)
        return npts(c1) * npts(c2)

    def _compile_launch(self, launch_state):
        """The launch's one compile-and-expand: ``build_plan``, then ``expand``.

        Run, the API's ``/scan`` and ``/validate``, the GUI point-count preview
        and the benchmark all compile here, each from the snapshot its own
        collection took at the instant of launch (``launch_state['snapshot']``,
        canonical IDs). The plan and its points are stored on the launch state
        (``'plan'``, ``'expansion'``) and ride it into the queued job: nothing
        downstream re-reads command text or chooses a calculation. Raises
        ``PlanRefused`` naming why the scan cannot run as written.
        """
        vals = launch_state['vals']
        context = context_from_state(launch_state['scan_config'], vals,
                                     self.instrument.capabilities(),
                                     launch_state.get('engine') or 'mcstas')
        plan = build_plan(
            [(vals.get('scan_command1') or "", bool(launch_state.get('relative_mode_1'))),
             (vals.get('scan_command2') or "", bool(launch_state.get('relative_mode_2')))],
            context)
        expansion = expand(plan, launch_state['snapshot'])
        launch_state['plan'], launch_state['expansion'] = plan, expansion
        return plan, expansion

    def validate_scan_launch_state(self, launch_state):
        """Check each point of a launch's compiled plan for feasibility.

        Reads the plan and points of the launch's one compile-and-expand
        (``_compile_launch``, run here when the caller has not yet) and judges
        each point with the instrument's ``check_point_feasibility``: the run's
        own solve, then the plan's engine and plane-lock guards. Never touches
        the GUI.

        Returns a point-level feasibility manifest where ``per_command`` is a
        list of ``{"variable", "count", "values"}`` and ``infeasible`` a list
        of ``{"index", "values", "kind", "reason"}`` in run order (the linear
        index is ``run_simulation``'s point order, so the skip-filter drops
        exactly those points). Raises ``PlanRefused`` when the plan does not
        compile or the instrument cannot judge feasibility: a scan that cannot
        be checked is refused, never assumed feasible.
        """
        if 'plan' not in launch_state:
            self._compile_launch(launch_state)
        plan, expansion = launch_state['plan'], launch_state['expansion']
        scan_config = launch_state['scan_config']
        feasibility = getattr(self.instrument, "check_point_feasibility", None)
        if not callable(feasibility):
            raise PlanRefused(f"{self.descriptor.display_name} cannot check point feasibility, "
                              "so its scans cannot be validated.")

        result = {
            "requested_points": len(expansion.points),
            "per_command": [
                {"variable": command.quantity, "count": len(expansion.values[command.number]),
                 "values": list(expansion.values[command.number])}
                for command in plan.commands
            ],
            "infeasible": [],
            "point_manifest": [],
        }
        for index, point in enumerate(expansion.points):
            values = {command.quantity: point[command.quantity] for command in plan.commands}
            axes = ()
            requested_q = realized_q = None
            try:
                check = feasibility(scan_config, plan, point)
                feasible, reason, kind = bool(check.feasible), check.reason, check.kind
                axes = check.transmission
                requested_q, realized_q = check.requested_q, check.realized_q
            except Exception as exc:
                feasible, reason, kind = False, f"angle solve error: {exc}", "geometry_solver_error"
            entry = {"index": index, "values": values, "feasible": feasible,
                     "kind": kind, "reason": reason}
            if requested_q is not None:
                # A plane-locked Q point: the Q asked for beside the in-plane Q the stage reaches.
                entry["requested_q_inv_angstrom"] = list(requested_q)
                entry["realized_q_inv_angstrom"] = list(realized_q)
            if kind == "transmission":
                # The axes travel with the entry: a preflight-skipped point
                # never reaches the run loop, so this is where
                # ScanResult.transmission_points learns about it.
                entry["axes"] = list(axes)
            result["point_manifest"].append(entry)
            if not feasible:
                result["infeasible"].append({key: value for key, value in entry.items()
                                             if key != "feasible"})

        mask = [bool(entry["feasible"]) for entry in result["point_manifest"]]
        segments = []
        start = None
        for index, feasible in enumerate(mask + [False]):
            if feasible and start is None:
                start = index
            elif not feasible and start is not None:
                segments.append({"start_index": start, "end_index": index - 1})
                start = None
        result["planned_feasible_mask"] = mask
        result["feasible_points"] = sum(mask)
        result["partial"] = 0 < result["feasible_points"] < result["requested_points"]
        result["feasible_segments"] = segments

        return result

    def build_api_schema(self):
        """Return a machine-readable self-description of the API surface.

        Generated at request time from live data: the field set comes from the
        live ``_api_field_map`` (no hand-maintained duplicate), allowed values
        from the descriptor (crystals/source) and the static choice maps
        ``apply_parameters`` enforces. GUI-thread only (reads the field map).
        """
        # Live field names (order preserved) drive the schema so it can never
        # drift from what apply_parameters actually accepts.
        field_names = list(self._api_field_map().keys())

        # Static type/units metadata for the settings only; a registry quantity takes its
        # type and unit from tavi/quantities.py. Unknowns default to number/None.
        meta = {_to_public(name): spec for name, spec in {
            'orientation_mode': ('string', None), 'lock_plane': ('object', 'r.l.u.'),
            'K_fixed': ('string', None), 'fixed_E': ('number', 'meV'),
            'sample': ('string', None),
            'monocris': ('string', None), 'anacris': ('string', None),
            'source_type': ('string', None), 'source_dE': ('number', 'meV'),
            'modules': ('object', None), 'collimation': ('object', None),
            'number_neutrons': ('integer', 'count'),
            'scan_command1': ('string', None), 'scan_command2': ('string', None),
            'diagnostic_mode': ('boolean', None),
        }.items()}

        # Allowed values pulled live from the descriptor / static choice maps.
        allowed = {
            'orientation_mode': ["free", "locked"],
            'K_fixed': ["Ki Fixed", "Kf Fixed"],
            # Sample ids from the shared sample library (includes "none"); the
            # same set apply_parameters validates a 'sample' write against.
            'sample': [s.id for s in self.descriptor.samples],
            'monocris': [c.id for c in self.descriptor.mono_crystals],
            'anacris': [c.id for c in self.descriptor.ana_crystals],
            'source_type': [s.id for s in self.descriptor.source_types],
        }

        fields = []
        for name in field_names:
            ftype, units = meta.get(name, ('number', 'mm' if name.startswith("slit.") else None))
            units = schema_unit(name) or units
            entry = {"name": name, "type": ftype}
            if units is not None:
                entry["units"] = units
            if name in allowed:
                entry["allowed"] = allowed[name]
            fields.append(entry)

        # curvature_modes is NOT in _api_field_map (see its docstring): it is
        # read-only derived state, not a hand-maintained duplicate of a
        # writable field, so it is declared here by hand rather than sourced
        # from field_names. get_gui_values()/GET /parameters/GET /state all
        # return it; PATCH /parameters refuses a write against it.
        fields.append({
            "name": "curvature_modes",
            "type": "object",
            "readOnly": True,
            "description": (
                "Per-axis curvature policy (mono/analyzer horizontal/vertical radius "
                "ID -> '%s'/'%s'/'%s'), derived from the Ideal locks and from which "
                "axes the scan command names. Read-only." % (
                    CurvatureMode.AUTOFOCUS.value, CurvatureMode.HELD.value,
                    CurvatureMode.SCANNED.value,
                )
            ),
        })
        for name, role in (("mount_plane_u", "along the mount x axis"),
                           ("mount_plane_v", "in the horizontal plane")):
            fields.append({
                "name": name,
                "type": "array",
                "units": "r.l.u.",
                "readOnly": True,
                "description": (
                    f"The (h k l) the sample is mounted with {role}, as the "
                    "operator described it in the Sample dock; null when the "
                    "mount is not from a plane. Read-only."
                ),
            })
        fields.append({
            "name": "lock_stale",
            "type": "boolean",
            "readOnly": True,
            "description": (
                "True when the operator's UB no longer levels the locked plane "
                "at the locked tilts within %g degrees; null when free. "
                "Read-only." % self.LOCK_STALE_DEG
            ),
        })

        limits = getattr(self, "_api_limits", None)

        return {
            "api_version": API_VERSION,
            "instrument": self.descriptor.id,
            "fields": fields,
            # Selectable execution backends for POST /scan (§6.4). "mcstas" is
            # the default full Monte-Carlo engine; "deterministic" is the fast
            # analytic S(Q,w) x resolution + seeded-Poisson tier.
            "engines": list(ALLOWED_ENGINES),
            # Optional top-level POST /scan body fields beyond "parameters".
            "scan_body_fields": [
                {"name": "engine", "type": "string", "allowed": list(ALLOWED_ENGINES),
                 "default": "mcstas",
                 "description": "Execution backend for this scan."},
                {"name": "seed", "type": "integer", "default": None,
                 "description": "Deterministic-engine RNG seed; default is a "
                                "stable hash of the job id."},
                {"name": "noiseless", "type": "boolean", "default": False,
                 "description": "Deterministic engine only: return exact means "
                                "(no Poisson noise)."},
                {"name": "background", "type": "object", "default": None,
                 "description": "Per-scan background profile; replaces the "
                                "configured profile wholesale (never merges). "
                                "See the top-level 'background' block."},
            ],
            "scan_variables": [q.id for q in QUANTITIES if q.scannable],
            "scan_command_grammar": (
                "VARIABLE start stop STEP. The third number (the last token) is "
                "the STEP SIZE, not the number of points. "
                "'H 1.99 2.01 0.01' produces 3 points (1.99, 2.00, 2.01). A step "
                "larger than the range is a validation error. Two non-empty "
                "commands make a 2D scan (point counts multiply); one command is "
                "1D; none is a single point at the current settings."
            ),
            "limits": limits,
            "endpoints": [
                {"method": "GET", "path": "/health", "description": "Liveness probe (no auth)."},
                {"method": "GET", "path": "/state", "description": "Full instrument state, parameters, queue, budget."},
                {"method": "GET", "path": "/parameters", "description": "Current parameter dict."},
                {"method": "PATCH", "path": "/parameters", "description": "Partial parameter write."},
                {"method": "POST", "path": "/scan", "description": "Validate and queue a scan job (optional 'engine'/'seed'/'noiseless' body fields)."},
                {"method": "POST", "path": "/validate", "description": "Run scan validation only; never queues."},
                {"method": "GET", "path": "/scan/{id}", "description": "Job status (optionally ?wait=N long-poll)."},
                {"method": "GET", "path": "/scan/{id}/data", "description": "Job status plus full scan arrays."},
                {"method": "POST", "path": "/scan/{id}/stop", "description": "Stop or cancel one job."},
                {"method": "POST", "path": "/stop", "description": "Stop the running job (optionally clear the queue)."},
                {"method": "GET", "path": "/jobs", "description": "Recent job snapshots."},
                {"method": "GET", "path": "/schema", "description": "This machine-readable API self-description."},
                {"method": "GET", "path": "/events", "description": "Server-Sent Events live stream."},
                {"method": "GET", "path": "/background", "description": "Configured background profile (spec + resolved)."},
                {"method": "PUT", "path": "/background", "description": "Replace the background profile wholesale."},
            ],
            # Generated background truth (tavi/background.py).  Clients pin the
            # catalog version and request each stable source id independently.
            "background": {
                "background_schema": _background.BACKGROUND_SCHEMA,
                "catalog_version": _background.CATALOG_VERSION,
                "categories": list(_background.CATEGORIES),
                "sources": _background.source_catalog(),
                "request": {
                    "catalog_version": "required integer matching catalog_version",
                    "enabled": "required boolean global gate",
                    "sources": {
                        "<source id>": {
                            "enabled": "required boolean",
                            "scale": "required finite number >= 0",
                        }
                    },
                    "omitted_sources": "disabled at scale 1.0",
                    "replacement_semantics": "wholesale; never merges",
                },
                "spec_fields": sorted(BACKGROUND_SPEC_KEYS),
            },
            "examples": [
                "align-on-bragg-peak",
                "elastic-h-scan",
                "constant-q-energy-scan",
                "quick-look-vs-production",
            ],
        }

    def on_sample_changed(self, label):
        """Handle sample selection changes from the GUI."""
        try:
            key = self.window.sample_dock.get_selected_sample_key()
            swapped = key != getattr(self.instrument_state, "sample_key", None)
            self.instrument_state.sample_key = key
            self.current_sample_settings = {"sample_label": label, "sample_key": key}
            self.print_to_message_center(f"Sample selection changed: {label} ({key})")
            # I5: a physical sample swap keeps the mount (U_described as a
            # matrix), the exercise and the peaks; only the plane's
            # description, which named the previous sample's HKLs, goes.
            if swapped and self.mount_plane is not None:
                self.mount_plane = None
                self._show_mount_plane()
                self.print_to_message_center(
                    "Mounting-plane description cleared: it named reflections of the "
                    "previous sample. The mount itself is unchanged.")
            if swapped:
                # D11: the residuals were of the previous sample's peaks, even
                # when its lattice (so the UB) is the same.
                self.window.ub_matrix_dock.clear_residuals()
            self._adopt_sample_lattice(key)
            # Allowed under a lock (amendment 7); the stale mark reports it.
            self._show_plane_lock()
            self.request_reciprocal_snapshot()
        except Exception as e:
            self.print_to_message_center(f"Sample selection change failed: {e}")

    def _adopt_sample_lattice(self, sample_key):
        """Set the lattice fields from the selected sample's own lattice.

        Samples carry their lattice constants (SampleSpec.lattice) because the
        McStas components bake them in -- driving e.g. Phonon_DFT (a=4.03893)
        with a mismatched GUI lattice misses its Bragg condition entirely.
        The parameter-restore path re-applies saved lattice values afterwards,
        so hand-edited lattices survive a reload. Ends through
        ``on_lattice_changed``, as the lattice Save does, so the operator's UB
        moves to the new sample's lattice.
        """
        spec = next((s for s in self.descriptor.samples if s.id == sample_key), None)
        if spec is None or spec.lattice is None:
            return
        a, b, c, alpha, beta, gamma = spec.lattice
        dock = self.window.sample_dock
        for edit, value in ((dock.lattice_a_edit, a), (dock.lattice_b_edit, b),
                            (dock.lattice_c_edit, c), (dock.lattice_alpha_edit, alpha),
                            (dock.lattice_beta_edit, beta), (dock.lattice_gamma_edit, gamma)):
            edit.setText(f"{value:g}")
        self.print_to_message_center(
            f"Lattice set from sample '{spec.display_name}': "
            f"a={a:g}, b={b:g}, c={c:g}"
        )
        self.on_lattice_changed()

    def stop_simulation(self):
        """Stop the running simulation.

        Sets the shared stop event; the worker's run_simulation completion path
        marks the active job STOPPED once it drains.
        """
        self.stop_event.set()
        self.print_to_message_center("Stop requested...")

    def shutdown(self):
        """Stop work and tear down the job worker. Safe to call repeatedly."""
        if self._shutdown_called:
            return
        self._shutdown_called = True

        # Stop accepting remote requests first (idempotent; closes SSE clients).
        server = getattr(self, "api_server", None)
        if server is not None:
            server.stop()

        # Signal any running scan to drain out.
        self.stop_event.set()

        # Cancel every still-queued job so the worker skips them on drain.
        for job in self._job_registry.all_jobs():
            with job.lock:
                if job.state == JobState.QUEUED:
                    job.state = JobState.CANCELLED
                    if job.finished_at is None:
                        job.finished_at = time.time()
                    job.notify_state_change()

        # Wake the worker with the exit sentinel and give it a moment to stop.
        self._job_queue.put(None)
        if self._job_worker is not None:
            self._job_worker.join(timeout=2)

    def _prep_worker(self, scan_parameter_input, plan, scan_config, vals, data_folder,
                     snapshot_queue, stop_event):
        """Compute per-point snapshots of the plan's points ahead of the simulation thread."""
        try:
            for scan_index, (point, indices) in enumerate(scan_parameter_input):
                if stop_event.is_set():
                    break

                prep_stage_start = time.perf_counter()
                snapshot = self.instrument.compute_snapshot(
                    plan, point, scan_index, scan_config, vals, data_folder,
                    indices=indices,
                )
                prep_compute_duration = time.perf_counter() - prep_stage_start
                queue_wait_start = time.perf_counter()

                while not stop_event.is_set():
                    try:
                        snapshot_queue.put(snapshot, timeout=0.1)
                        # The queued PointSnapshot is shared by reference; stamping
                        # timing after put() is visible to the consumer loop.
                        queue_wait_duration = time.perf_counter() - queue_wait_start
                        snapshot.timing['prep_compute_duration_s'] = prep_compute_duration
                        snapshot.timing['prep_queue_wait_duration_s'] = queue_wait_duration
                        snapshot.timing['prep_duration_s'] = prep_compute_duration + queue_wait_duration
                        break
                    except queue.Full:
                        continue
        except Exception as exc:
            failure = PrepFailure(str(exc))
            while not stop_event.is_set():
                try:
                    snapshot_queue.put(failure, timeout=0.1)
                    break
                except queue.Full:
                    continue
        finally:
            while True:
                try:
                    snapshot_queue.put(None, timeout=0.1)
                    break
                except queue.Full:
                    if stop_event.is_set():
                        break
                    continue
    
    @staticmethod
    def _mark_executed_result_point(result, *, is_2d_scan,
                                    is_single_point_scan, idx_1d, idx_x, idx_y):
        """Mark one successfully stored point in original request order."""
        if result is None or not result.executed_feasible_mask:
            return
        if is_2d_scan:
            original_index = idx_y * len(result.scan_values_1) + idx_x
        elif is_single_point_scan:
            original_index = 0
        else:
            original_index = idx_1d
        if 0 <= original_index < len(result.executed_feasible_mask):
            result.executed_feasible_mask[original_index] = True

    @staticmethod
    def _scan_point_linear_index(*, is_2d_scan, is_single_point_scan,
                                 idx_1d, idx_x, idx_y, values_1_len):
        """Same flattening ``_mark_executed_result_point`` and
        ``applied_curvature`` use: row-major for a 2D scan, 0 for a single
        point, the raw request-order index otherwise."""
        if is_2d_scan:
            return idx_y * values_1_len + idx_x
        if is_single_point_scan:
            return 0
        return idx_1d

    @staticmethod
    def _scan_point_values(*, is_2d_scan, is_single_point_scan, idx_1d, idx_x, idx_y,
                           variable_name1, variable_name2, array_values1, array_values2):
        """``{variable: value}`` naming one scan point, matching the shape
        ``validate_scan_launch_state``'s ``_record`` builds for the same
        request-order point."""
        if is_2d_scan:
            values = {}
            if 0 <= idx_x < len(array_values1):
                values[variable_name1] = float(array_values1[idx_x])
            if 0 <= idx_y < len(array_values2):
                values[variable_name2] = float(array_values2[idx_y])
            return values
        if is_single_point_scan:
            return {}
        if 0 <= idx_1d < len(array_values1):
            return {variable_name1: float(array_values1[idx_1d])}
        return {}

    def _run_scan_deterministic(self, launch_state, job, scan_parameter_input,
                                plan, scan_config, is_2d_scan,
                                is_single_point_scan, variable_name1,
                                variable_name2, array_values1, array_values2,
                                vals, data_folder, number_neutrons, start_time):
        """Fast analytic engine branch of ``run_simulation`` (§6.4).

        Called only when ``launch_state['engine'] == 'deterministic'``. Point
        generation, feasibility masks, the ScanResult, and the scan_initialized
        SSE were already produced by the shared code in ``run_simulation``; this
        method REUSES those and replaces the McStas build/prep/run machinery with
        the analytic S(Q,w) x resolution engine (``tavi.deterministic_engine``).

        What is reused vs reimplemented:
          * REUSED: ``self.instrument.compute_snapshot`` -- the exact per-point
            Q/angle solve + feasibility flags the McStas prep thread runs, so a
            point skipped here is skipped for the same reason with the same
            geometry; the pre-sized ``job.result``; the identical per-point
            progress / point / point_invalid signals + SSE events.
          * NEW: per-point resolution kernel (``resolution_config`` + ``tavi.
            resolution.resolution``) and analytic evaluation
            (``deterministic_engine.evaluate_point``) with a per-point RNG stream
            ``default_rng((seed, i))`` so a skipped point never shifts a later
            point's noise. No compilation, no per-point output folders.

        The final job terminal state is set here (mirrors the McStas path), and
        ``result.metadata`` is stamped with the engine provenance (engine, seed,
        noiseless, cn_valid, invalidations) even when ``cn_valid`` is false
        ("run + stamp", §6.5).
        """
        import numpy as np
        import zlib
        from tavi.resolution import resolution as _resolution
        from tavi import background as _background
        from tavi import deterministic_engine as _det

        # -- seed: explicit body seed, else a stable hash of the job id so a
        #    re-run of the same job reproduces bit-identically (crc32 is
        #    deterministic across processes, unlike Python's salted hash()).
        seed = launch_state.get('seed')
        if seed is None:
            job_id = getattr(job, 'job_id', '') or ''
            seed = int(zlib.crc32(job_id.encode('utf-8')))
        noiseless = bool(launch_state.get('noiseless', False))

        # -- ground truth: keyed by the frozen sample id. Unknown sample ->
        #    fail the job cleanly (API clients see a failed job with a reason,
        #    not a crash), reusing the same terminal-state path as success.
        sample_key = launch_state.get('sample_key')
        spec = None
        try:
            spec = next(
                (s for s in self.descriptor.samples if s.id == sample_key), None
            )
        except Exception:
            spec = None
        analytic_model_error = None
        try:
            sqw = _det.ground_truth(spec) if spec is not None else None
        except Exception as exc:
            sqw = None
            analytic_model_error = str(exc)
        if sqw is None:
            reason = (
                "failed to load analytic ground truth for sample %r: %s"
                % (sample_key, analytic_model_error)
                if analytic_model_error
                else "no analytic ground truth for sample %r" % (sample_key,)
            )
            self.message_printed.emit(
                "Deterministic engine: %s -- job failed." % reason
            )
            if job is not None:
                with job.lock:
                    job.state = JobState.FAILED
                    job.error = reason
                    job.finished_at = time.time()
                    job.notify_state_change()
            # Every other exit of this method (and the McStas path) emits
            # scan_completed even on failure; without it display_dock never
            # leaves its in-progress state.
            self.scan_completed.emit()
            return data_folder

        self.message_printed.emit(
            "Deterministic engine: sample '%s', seed %d%s"
            % (getattr(sqw, 'sample_id', '?'), seed,
               ", noiseless" if noiseless else "")
        )
        # The model sees the crystal as it really sits: the sample's own
        # lattice (true B) through the true mount on the
        # frozen scan_config. "No sample" has no crystal, so no HKL.
        from instruments.tas_runtime import true_point_hkl
        B_true = compute_B_matrix(*spec.lattice) if spec.lattice is not None else None

        # -- background: planted truth resolved once for the whole scan. A
        #    per-scan override replaces the controller configuration wholesale
        #    (never merges); all source strengths are independent of the sample.
        background_spec = (
            launch_state['background'] if 'background' in launch_state
            else getattr(self, 'background_profile', None)
        )
        background_source = (
            launch_state.get('background_source') or 'config_default'
        )
        try:
            background = _background.resolve(background_spec)
        except ValueError as exc:
            reason = "invalid background profile: %s" % exc
            self.message_printed.emit(
                "Deterministic engine: %s -- job failed." % reason
            )
            if job is not None:
                with job.lock:
                    job.state = JobState.FAILED
                    job.error = reason
                    job.finished_at = time.time()
                    job.notify_state_change()
            self.scan_completed.emit()
            return data_folder
        # Marginal widths require a 4x4 inversion per point, so compute them
        # only when an active smooth source consumes one.
        active_mean_shapes = {
            state.definition.shape
            for state in _background.active_mean_sources(background)
        }
        background_needs_sigma_e = bool(
            active_mean_shapes & {'elastic_incoherent', 'powder_elastic'}
        )
        background_needs_sigma_q = 'powder_elastic' in active_mean_shapes
        background_has_events = bool(
            _background.active_event_sources(background)
        )

        total_scans = len(scan_parameter_input)
        # Pre-scan estimate from tracked deterministic history (engine-filtered).
        # The analytic engine never compiles, so needs_compile is False. Keep the
        # "< 1s" string only when there is no data or the estimate is sub-second.
        det_estimate = self.runtime_tracker.estimate_scan_seconds(
            self.instrument.id, total_scans, number_neutrons,
            needs_compile=False, engine="deterministic",
        )
        det_seconds = det_estimate.get("estimated_seconds")
        if det_seconds is None or det_seconds < 1.0:
            self.pre_scan_estimate_updated.emit("< 1s (deterministic)")
        else:
            self.pre_scan_estimate_updated.emit(
                RuntimeTracker.format_time(det_seconds)
            )

        total_counts = 0.0
        max_counts = 0.0
        processed_points = 0
        meta_res = None
        simulation_stopped = False
        simulation_error_message = None
        realized_background_events = []

        # Accumulators for the output data file (parity with the McStas path).
        if is_2d_scan:
            counts_grid = np.full((len(array_values2), len(array_values1)), np.nan)
        else:
            scan_x_values = []
            scan_counts = []

        try:
            for i, (point, indices) in enumerate(scan_parameter_input):
                if self.stop_event.is_set():
                    simulation_stopped = True
                    break

                idx_1d, idx_x, idx_y = indices['idx_1d'], indices['idx_x'], indices['idx_y']

                # REUSE the exact per-point Q/angle solve + feasibility flags.
                snapshot = self.instrument.compute_snapshot(
                    plan, point, i, scan_config, vals, data_folder, indices=indices,
                )
                md = snapshot.metadata
                error_flags = list(snapshot.error_flags)
                w = float(snapshot.deltaE)

                if is_2d_scan:
                    self.scan_current_index_2d.emit(idx_x, idx_y)
                else:
                    self.scan_current_index_1d.emit(idx_1d)

                if error_flags:
                    self.message_printed.emit(
                        "Point %d: skipped, error flags: %s" % (i, error_flags)
                    )
                    if is_2d_scan:
                        self.scan_point_invalid_2d.emit(idx_x, idx_y)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id, 'ix': idx_x, 'iy': idx_y,
                                'value_1': float(array_values1[idx_x]),
                                'value_2': float(array_values2[idx_y]),
                            })
                    elif not is_single_point_scan and idx_1d >= 0:
                        self.scan_point_invalid_1d.emit(idx_1d)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id, 'index': idx_1d,
                                'value': (float(array_values1[idx_1d])
                                          if idx_1d < len(array_values1) else None),
                            })
                    if not is_2d_scan and not is_single_point_scan \
                            and 0 <= idx_1d < len(array_values1):
                        scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(np.nan)
                    if job is not None and job.result is not None:
                        from instruments.tas_runtime import describe_scan_error_flags
                        point_values = self._scan_point_values(
                            is_2d_scan=is_2d_scan, is_single_point_scan=is_single_point_scan,
                            idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            variable_name1=variable_name1, variable_name2=variable_name2,
                            array_values1=array_values1, array_values2=array_values2,
                        )
                        point_index = self._scan_point_linear_index(
                            is_2d_scan=is_2d_scan, is_single_point_scan=is_single_point_scan,
                            idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            values_1_len=len(array_values1),
                        )
                        with job.lock:
                            job.result.skipped_points.append({
                                "index": point_index, "values": point_values,
                                "kind": "infeasible",
                                "reason": describe_scan_error_flags(error_flags),
                            })
                elif md.get('transmission'):
                    # Same shape as the error-flag skip above -- the analytic
                    # engine assumes every crystal reflects and enforces it
                    # (ruling 3): no |Q|, resolution, background or
                    # ground-truth evaluation for a marked point.
                    reason = (
                        "direct transmission (%s); the analytic engine makes "
                        "no claim" % ", ".join(md['transmission'])
                    )
                    self.message_printed.emit("Point %d: %s" % (i, reason))
                    if is_2d_scan:
                        self.scan_point_invalid_2d.emit(idx_x, idx_y)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id, 'ix': idx_x, 'iy': idx_y,
                                'value_1': float(array_values1[idx_x]),
                                'value_2': float(array_values2[idx_y]),
                            })
                    elif not is_single_point_scan and idx_1d >= 0:
                        self.scan_point_invalid_1d.emit(idx_1d)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id, 'index': idx_1d,
                                'value': (float(array_values1[idx_1d])
                                          if idx_1d < len(array_values1) else None),
                            })
                    if not is_2d_scan and not is_single_point_scan \
                            and 0 <= idx_1d < len(array_values1):
                        scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(np.nan)
                    if job is not None and job.result is not None:
                        point_values = self._scan_point_values(
                            is_2d_scan=is_2d_scan, is_single_point_scan=is_single_point_scan,
                            idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            variable_name1=variable_name1, variable_name2=variable_name2,
                            array_values1=array_values1, array_values2=array_values2,
                        )
                        point_index = self._scan_point_linear_index(
                            is_2d_scan=is_2d_scan, is_single_point_scan=is_single_point_scan,
                            idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            values_1_len=len(array_values1),
                        )
                        with job.lock:
                            job.result.skipped_points.append({
                                "index": point_index, "values": point_values,
                                "kind": "transmission", "reason": reason,
                            })
                            job.result.transmission_points.append({
                                "index": point_index,
                                "axes": list(md['transmission']),
                            })
                else:
                    # (H,K,L) for the ground-truth model, in every mode: where
                    # this point's physical angles put the true crystal, not
                    # the requested HKL or the operator's UB. Feeds the model
                    # evaluation only -- never md or the result (hidden truth).
                    hkl = (true_point_hkl(scan_config, md, B_true)
                           if B_true is not None else None)
                    q0 = _background_q_magnitude(md)

                    # Resolution kernel for this point (cheap: one config + solve).
                    # Uses THIS point's own applied radii AND kinematics (md),
                    # not the frozen launch vals -- an AUTOFOCUS axis or a
                    # curvature scan point runs with radii that differ
                    # point-to-point, and a direct-angle scan's own Ei/Ki/Ef/Kf
                    # can differ from the launch's (D23).
                    rr = None
                    try:
                        cfg = self.instrument.resolution_config(
                            _vals_with_point_state(vals, md), q0, w,
                            point_angles=_point_angles(md['mtt'], md['stt'], md['att']),
                        )
                        rr = _resolution(cfg)
                        meta_res = rr
                    except Exception as exc:
                        self.message_printed.emit(
                            "Point %d: resolution unavailable (%s); signal counts=0"
                            % (i, exc)
                        )

                    sigma_q = (
                        _det.marginal_sigma(rr, 'dq_par')
                        if background_needs_sigma_q else None
                    )
                    sigma_e = (
                        _det.marginal_sigma(rr, 'dE')
                        if background_needs_sigma_e else None
                    )
                    background_context = _background.BackgroundPointContext(
                        q_inv_ang=q0,
                        w_meV=w,
                        sigma_q_inv_ang=sigma_q,
                        sigma_e_meV=sigma_e,
                        number_neutrons=number_neutrons,
                    )
                    bg_mean, _ = _background.mean_counts(
                        background, background_context
                    )

                    rng = None if noiseless else np.random.default_rng((int(seed), i))
                    out = _det.evaluate_point(
                        rr, sqw, hkl, w, number_neutrons,
                        rng=rng, noiseless=noiseless,
                        background_mean=bg_mean,
                    )
                    counts = float(out['counts'])
                    if background_has_events:
                        event_counts, point_events = (
                            _background.draw_event_overlay(
                                background,
                                background_context,
                                seed,
                                i,
                            )
                        )
                        counts += event_counts
                        realized_background_events.extend(point_events)
                    self.message_printed.emit(
                        "Final counts (analytic): %s" % (counts,)
                    )

                    total_counts += counts
                    max_counts = max(max_counts, counts)

                    if is_2d_scan:
                        self.scan_point_updated_2d.emit(idx_x, idx_y, counts)
                        counts_grid[idx_y, idx_x] = counts
                    elif not is_single_point_scan:
                        if idx_1d >= 0:
                            self.scan_point_updated_1d.emit(idx_1d, counts)
                        if 0 <= idx_1d < len(array_values1):
                            scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(counts)

                    if job is not None and job.result is not None:
                        # THIS point's own applied radii (md), signed -- see
                        # ScanResult.applied_curvature. The deterministic
                        # engine writes no per-point files, so this is the
                        # only place its truth can live.
                        point_curvature = {
                            axis: md[axis] for axis in ("rhm", "rvm", "rha", "rva")
                        }
                        with job.lock:
                            res = job.result
                            if is_2d_scan:
                                if res.counts_grid is not None:
                                    res.counts_grid[idx_y][idx_x] = counts
                                if res.applied_curvature:
                                    orig_idx = idx_y * len(res.scan_values_1) + idx_x
                                    if 0 <= orig_idx < len(res.applied_curvature):
                                        res.applied_curvature[orig_idx] = point_curvature
                            elif is_single_point_scan:
                                if res.counts:
                                    res.counts[0] = counts
                                if res.applied_curvature:
                                    res.applied_curvature[0] = point_curvature
                            elif idx_1d >= 0 and res.counts is not None \
                                    and idx_1d < len(res.counts):
                                res.counts[idx_1d] = counts
                                if res.applied_curvature and idx_1d < len(res.applied_curvature):
                                    res.applied_curvature[idx_1d] = point_curvature
                            res.total_counts = float(total_counts)
                            res.max_counts = float(max_counts)
                            self._mark_executed_result_point(
                                res,
                                is_2d_scan=is_2d_scan,
                                is_single_point_scan=is_single_point_scan,
                                idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            )
                        if is_2d_scan:
                            self._publish_api_event('point', {
                                'job_id': job.job_id, 'ix': idx_x, 'iy': idx_y,
                                'value_1': float(array_values1[idx_x]),
                                'value_2': float(array_values2[idx_y]),
                                'counts': counts,
                            })
                        elif is_single_point_scan:
                            self._publish_api_event('point', {
                                'job_id': job.job_id, 'index': 0,
                                'value': None, 'counts': counts,
                            })
                        elif idx_1d >= 0:
                            self._publish_api_event('point', {
                                'job_id': job.job_id, 'index': idx_1d,
                                'value': (float(array_values1[idx_1d])
                                          if idx_1d < len(array_values1) else None),
                                'counts': counts,
                            })

                processed_points += 1
                self.progress_updated.emit(processed_points, total_scans)
                self.counts_updated.emit(max_counts, total_counts)
                if job is not None:
                    with job.lock:
                        job.progress_done = processed_points
                    self._publish_api_event('progress', {
                        'job_id': job.job_id, 'done': processed_points,
                        'total': total_scans, 'elapsed': time.time() - start_time,
                    })
        except Exception as exc:
            simulation_error_message = "Deterministic engine failed: %s" % exc
            self.message_printed.emit(simulation_error_message)

        if simulation_stopped or self.stop_event.is_set():
            self.message_printed.emit("Simulation stopped by user.")

        # Stamp engine provenance into result.metadata (run + stamp, §6.5), so
        # cn_valid / invalidations reach every reader even when cn_valid is false.
        if job is not None and job.result is not None \
                and simulation_error_message is None:
            with job.lock:
                job.result.metadata.update(
                    _det.engine_metadata(
                        seed, meta_res, method="analytic", sqw=sqw
                    )
                )
                job.result.metadata['noiseless'] = noiseless
                # Stamped even when the profile is disabled and even when
                # cn_valid is false: absence of background is provenance too.
                job.result.metadata['background'] = _background.metadata_block(
                    background,
                    background_source,
                    background_seed=(
                        seed
                        if background_has_events and number_neutrons > 0
                        else None
                    ),
                    realized_events=realized_background_events,
                )

        # One data file (parity with McStas output; the folder already exists and
        # its parameters file was written by the shared section). No per-point
        # McStas artifacts are produced.
        if simulation_error_message is None and not self.stop_event.is_set() \
                and not is_single_point_scan:
            try:
                if is_2d_scan:
                    x_label = variable_name1 or 'scan1'
                    y_label = variable_name2 or 'scan2'
                    write_2D_scan(
                        np.array(array_values1), np.array(array_values2),
                        counts_grid, data_folder, "2D_scan_data.txt",
                        x_label=x_label, y_label=y_label,
                    )
                elif scan_x_values and scan_counts:
                    order = np.argsort(scan_x_values)
                    sorted_x = np.array(scan_x_values)[order]
                    sorted_counts = np.array(scan_counts)[order]
                    x_label = variable_name1 or 'scan'
                    write_1D_scan(sorted_x, sorted_counts, data_folder,
                                  "1D_scan_data.txt", x_label=x_label,
                                  y_label='counts')
            except Exception as exc:
                self.message_printed.emit(
                    "Warning: Failed to write deterministic scan data: %s" % exc
                )

        if simulation_error_message is None and not self.stop_event.is_set():
            self.message_printed.emit(
                "Deterministic scan complete. Total counts: %s, Max counts: %s"
                % (total_counts, max_counts)
            )

        # Record deterministic runtime for future ETAs (schema v2). Clean
        # completion only (non-cancelled, non-error) and at least one point.
        # The analytic engine has no compilation and its per-point cost is flat
        # (not neutron-scaled), so first == avg == total / points.
        if (simulation_error_message is None and not simulation_stopped
                and not self.stop_event.is_set() and processed_points > 0):
            det_total_time = time.time() - start_time
            det_per_point = det_total_time / processed_points
            record_source = (
                "benchmark"
                if (job is not None and getattr(job, "source", None) == "benchmark")
                else "organic"
            )
            self.runtime_tracker.add_record(
                instrument_name=self.instrument.id,
                num_points=processed_points,
                num_neutrons=number_neutrons,
                first_scan_time=det_per_point,
                avg_subsequent_time=det_per_point,
                total_time=det_total_time,
                compilation_time=0.0,
                machine_id=machine_fingerprint()["machine_id"],
                engine="deterministic",
                execution_mode=None,
                binary_reused=None,
                build_fp_hash=None,
                source=record_source,
                mpi_count=None,
            )
            self.runtime_data_updated.emit()

        # Display completion signals (mirror the McStas finalization).
        if simulation_error_message is not None or self.stop_event.is_set():
            self.scan_completed.emit()
        elif is_single_point_scan:
            self.single_point_result.emit(max_counts, total_counts)
        else:
            self.scan_completed.emit()
            self.scan_auto_save.emit()

        # Finalize job bookkeeping (same terminal-state selection as McStas).
        if job is not None:
            if simulation_error_message is not None:
                final_state = JobState.FAILED
            elif self.stop_event.is_set():
                final_state = JobState.STOPPED
            else:
                final_state = JobState.DONE
            with job.lock:
                job.state = final_state
                job.error = simulation_error_message
                job.finished_at = time.time()
                self.last_scan_result = job.result
                job.notify_state_change()

        return data_folder

    def run_simulation(self, launch_state, job=None):
        """Run the full simulation.

        When ``job`` is provided (job-queue path), scan geometry and per-point
        counts are recorded into ``job.result`` under ``job.lock`` for readers
        (API snapshots) and the final job state is set here. When ``job`` is
        None, behavior is unchanged from the pre-queue code path.
        """
        self.message_printed.emit("Starting simulation...")

        vals = launch_state['vals']
        scan_config = launch_state['scan_config']
        diagnostic_settings = launch_state['diagnostic_settings']
        number_neutrons = vals['number_neutrons']
        diagnostic_mode = vals['diagnostic_mode']
        compact_save_enabled = launch_state['compact_save_enabled']
        # The plan and points compiled at launch (_compile_launch): the only
        # description of what runs. No command text is read from here on.
        if 'plan' not in launch_state:
            raise RuntimeError("the launch state carries no compiled plan")
        plan, expansion = launch_state['plan'], launch_state['expansion']

        data_folder = launch_state['save_folder_input']
        # If the folder already exists, increment instead
        new_data_folder = incremented_path_writing(self.output_directory, data_folder)
        data_folder = new_data_folder

        self.actual_output_folder_updated.emit(data_folder)
        
        # Write parameters to file, with each command's absolute axis: a relative command's
        # text holds offsets, and the Display reload places points on these values.
        write_parameters_to_file(data_folder, self.output_parameters({
            **vals, **{f"scan_values_{c.number}": [float(v) for v in expansion.values[c.number]]
                       for c in plan.commands}}))
        
        # The plan's axes: command 1 inner, command 2 outer; a lone command
        # (in either box) is the only axis.
        commands = plan.commands
        is_single_point_scan = not commands
        is_2d_scan = len(commands) == 2
        variable_name1 = commands[0].quantity if commands else ""
        variable_name2 = commands[1].quantity if is_2d_scan else ""
        array_values1 = list(expansion.values[commands[0].number]) if commands else []
        array_values2 = list(expansion.values[commands[1].number]) if is_2d_scan else []
        for command in commands:
            if command.relative:
                self.message_printed.emit(
                    f"Relative scan {command.number}: {command.quantity} base = "
                    f"{expansion.bases[command.number]}")

        # (point, indices) in run order; the indices place a point in the result arrays.
        scan_parameter_input = []
        for linear, point in enumerate(expansion.points):
            if is_2d_scan:
                indices = {'idx_1d': -1, 'idx_x': linear % len(array_values1),
                           'idx_y': linear // len(array_values1)}
            else:
                indices = {'idx_1d': 0 if is_single_point_scan else linear,
                           'idx_x': -1, 'idx_y': -1}
            scan_parameter_input.append((point, indices))

        # Arrays to track requested scan geometry for display
        valid_mask_1d = []
        valid_mask_2d = None

        # Single scan command
        if commands and not is_2d_scan:
            valid_mask_1d = [self._point_runs(plan, point, scan_config)
                             for point, _ in scan_parameter_input]
            # Initialize display dock for 1D scan
            self.scan_initialized.emit('1D', list(array_values1), valid_mask_1d,
                                       variable_name1, "", [], [])

            if job is not None:
                # Pre-size the result so readers see per-index None until measured.
                n_points = len(array_values1)
                # Build the plain lists once so the ScanResult and the SSE
                # event share the same objects (no needless re-copy).
                scan_values_1_list = [float(v) for v in array_values1]
                valid_mask_1_list = [bool(v) for v in valid_mask_1d]
                with job.lock:
                    job.result = ScanResult(
                        mode='1D',
                        variable_1=variable_name1,
                        variable_2=None,
                        scan_values_1=scan_values_1_list,
                        scan_values_2=None,
                        valid_mask_1=valid_mask_1_list,
                        valid_mask_2d=None,
                        counts=[None] * n_points,
                        counts_grid=None,
                        output_folder=data_folder,
                        metadata=self.public_values(vals),
                        applied_curvature=[None] * n_points,
                    )
                    job.progress_total = len(scan_parameter_input)
                self._publish_api_event('scan_initialized', {
                    'job_id': job.job_id,
                    'mode': '1D',
                    'variable_1': variable_name1,
                    'variable_2': None,
                    'scan_values_1': scan_values_1_list,
                    'scan_values_2': None,
                    'valid_mask_1': valid_mask_1_list,
                    'valid_mask_2d': None,
                })

        # Double scan command
        if is_2d_scan:
            # Build a full validity mask for display, but still enqueue every requested point.
            valid = [self._point_runs(plan, point, scan_config)
                     for point, _ in scan_parameter_input]
            width = len(array_values1)
            valid_mask_2d = [valid[row * width:(row + 1) * width]
                             for row in range(len(array_values2))]
            # Initialize display dock for 2D scan
            self.scan_initialized.emit('2D', list(array_values1), [], variable_name1,
                                       variable_name2, list(array_values2), valid_mask_2d)

            if job is not None:
                n_cols = len(array_values1)
                n_rows = len(array_values2)
                scan_values_1_list = [float(v) for v in array_values1]
                scan_values_2_list = [float(v) for v in array_values2]
                valid_mask_2d_list = [[bool(v) for v in row] for row in valid_mask_2d]
                with job.lock:
                    job.result = ScanResult(
                        mode='2D',
                        variable_1=variable_name1,
                        variable_2=variable_name2,
                        scan_values_1=scan_values_1_list,
                        scan_values_2=scan_values_2_list,
                        valid_mask_1=[],
                        valid_mask_2d=valid_mask_2d_list,
                        counts=None,
                        counts_grid=[[None] * n_cols for _ in range(n_rows)],
                        output_folder=data_folder,
                        metadata=self.public_values(vals),
                        # Flat, row-major (idx_y * n_cols + idx_x) -- the same
                        # linear order _mark_executed_result_point already uses
                        # to flatten a 2D scan for planned/executed_feasible_mask.
                        applied_curvature=[None] * (n_cols * n_rows),
                    )
                    job.progress_total = len(scan_parameter_input)
                self._publish_api_event('scan_initialized', {
                    'job_id': job.job_id,
                    'mode': '2D',
                    'variable_1': variable_name1,
                    'variable_2': variable_name2,
                    'scan_values_1': scan_values_1_list,
                    'scan_values_2': scan_values_2_list,
                    'valid_mask_1': [],
                    'valid_mask_2d': valid_mask_2d_list,
                })

        if job is not None and job.result is None:
            # Neither the 1D nor 2D branch ran -> single-point scan.
            with job.lock:
                job.result = ScanResult(
                    mode='single',
                    variable_1="",
                    variable_2=None,
                    scan_values_1=[],
                    scan_values_2=None,
                    valid_mask_1=[],
                    valid_mask_2d=None,
                    counts=[None],
                    counts_grid=None,
                    output_folder=data_folder,
                    metadata=self.public_values(vals),
                    applied_curvature=[None],
                )
                job.progress_total = len(scan_parameter_input)
            self._publish_api_event('scan_initialized', {
                'job_id': job.job_id,
                'mode': 'single',
                'variable_1': "",
                'variable_2': None,
                'scan_values_1': [],
                'scan_values_2': None,
                'valid_mask_1': [],
                'valid_mask_2d': None,
            })

        # API feasibility: submission pre-determined some points infeasible.
        # Drop those points so
        # the prep thread never queues a snapshot for them; the result arrays
        # keep their None placeholders and job.result.skipped_points documents
        # exactly what was omitted (never silent gaps). The linear index matches
        # this expansion's order (see validate_scan_launch_state). GUI jobs never
        # set skipped_indices, so this is a no-op for them.
        skipped_indices = set(launch_state.get('skipped_indices') or [])
        skipped_points = launch_state.get('skipped_points') or []
        if skipped_indices and scan_parameter_input:
            scan_parameter_input = [
                item for k, item in enumerate(scan_parameter_input)
                if k not in skipped_indices
            ]
            self.message_printed.emit(
                f"Skipping {len(skipped_indices)} infeasible point(s) "
                f"from the frozen feasibility manifest; running "
                f"{len(scan_parameter_input)}."
            )
        if job is not None:
            with job.lock:
                if job.result is not None:
                    job.result.skipped_points = list(skipped_points)
                    # A transmission point the preflight skipped is filtered
                    # out of scan_parameter_input above and never reaches the
                    # run loop's writer, so seed the per-point trace from the
                    # manifest here; executed points append later.
                    job.result.transmission_points = [
                        {"index": p["index"], "axes": list(p.get("axes") or [])}
                        for p in skipped_points if p.get("kind") == "transmission"
                    ]
                    planned = list(launch_state.get('planned_feasible_mask') or [])
                    job.result.planned_feasible_mask = planned
                    job.result.executed_feasible_mask = [False] * len(planned)
                    job.result.feasible_segments = list(
                        launch_state.get('feasible_segments') or [])
                job.progress_total = len(scan_parameter_input)

        if is_2d_scan:
            estimated_runtime_points = int(sum(sum(1 for value in row if value) for row in valid_mask_2d))
        elif is_single_point_scan:
            estimated_runtime_points = 1
        else:
            estimated_runtime_points = int(sum(1 for value in valid_mask_1d if value))
        estimated_runtime_points = max(estimated_runtime_points, 1)

        # Deterministic-engine branch (docs/CONTROL_FEATURES_DESIGN.md §6.4).
        # Everything above -- point generation, feasibility masks, ScanResult
        # init, the scan_initialized SSE -- is SHARED with the McStas path. From
        # here the analytic engine replaces the McStas build/prep/run machinery
        # entirely: no compilation, no per-point output folders, milliseconds per
        # point. seed/noiseless come from the POST /scan body via launch_state.
        if launch_state.get('engine') == 'deterministic':
            return self._run_scan_deterministic(
                launch_state, job, scan_parameter_input, plan, scan_config,
                is_2d_scan, is_single_point_scan, variable_name1, variable_name2,
                array_values1, array_values2, vals, data_folder, number_neutrons,
                start_time=time.time(),
            )

        # -- background (McStas path): planted truth resolved once for the whole
        #    scan, exactly as the deterministic branch does, then overlaid on the
        #    ray-traced counts as an additive analytic Poisson term. No ray
        #    tracing of the background itself -- that is the schema-reserved
        #    method "simulated". A per-scan override replaces the controller
        #    profile wholesale (never merges); its absence means config default.
        import zlib
        background_spec = (
            launch_state['background'] if 'background' in launch_state
            else getattr(self, 'background_profile', None)
        )
        background_source = (
            launch_state.get('background_source') or 'config_default'
        )
        # An explicit body seed wins, else a stable hash of the job id (crc32 is
        # deterministic across processes, unlike Python's salted hash()),
        # mirroring the deterministic branch. Keep the derived value local:
        # ScanJob owns a write-once launch snapshot once it enters the queue.
        background_seed = launch_state.get('seed')
        if background_seed is None:
            _job_id = getattr(job, 'job_id', '') if job is not None else ''
            background_seed = int(zlib.crc32((_job_id or '').encode('utf-8')))
        background_seed = int(background_seed)
        try:
            background = _background.resolve(background_spec)
        except ValueError as exc:
            reason = "invalid background profile: %s" % exc
            self.message_printed.emit("McStas engine: %s -- job failed." % reason)
            if job is not None:
                with job.lock:
                    job.state = JobState.FAILED
                    job.error = reason
                    job.finished_at = time.time()
                    job.notify_state_change()
            # Every other exit of this method emits scan_completed even on
            # failure; without it display_dock never leaves its in-progress state.
            self.scan_completed.emit()
            return data_folder
        # A McStas point has no resolution matrix of its own. Solve and invert
        # only when an active smooth source consumes a marginalized width.
        active_mean_shapes = {
            state.definition.shape
            for state in _background.active_mean_sources(background)
        }
        background_needs_sigma_e = bool(
            active_mean_shapes & {'elastic_incoherent', 'powder_elastic'}
        )
        background_needs_sigma_q = 'powder_elastic' in active_mean_shapes
        background_has_events = bool(
            _background.active_event_sources(background)
        )
        if background.enabled:
            enabled_sources = sum(
                1 for state in background.sources if state.enabled
            )
            self.message_printed.emit(
                "Background overlay: sources=%d, seed=%d, fingerprint=%s"
                % (enabled_sources, background_seed,
                   _background.profile_fingerprint(background))
            )

        # Run the scans
        start_time = time.time()
        total_scans = len(scan_parameter_input)
        self.message_printed.emit(f"Running {total_scans} scan points...")
        
        # Resolve binary reuse before estimating: a reused binary skips the
        # rebuild, so the pre-scan estimate must not add compile time.
        effective_diagnostic_settings = diagnostic_settings if diagnostic_mode else {}
        build_fingerprint = self.instrument.build_fingerprint(
            scan_config, diagnostic_mode, effective_diagnostic_settings
        )
        reuse_binary = self._can_reuse_binary(
            self._binary_reuse_cache, build_fingerprint, diagnostic_mode,
            force_rebuild=bool(launch_state.get("force_rebuild")),
        )

        # Show pre-scan estimate based on historical data (machine-aware,
        # mcstas engine; compile time included only when a rebuild is pending).
        instrument_name = self.instrument.id
        # Frozen at launch; never re-read from settings or self mid-scan.
        mpi_count = int(launch_state.get('mpi_count', DEFAULT_MPI_COUNT))
        estimate = self.runtime_tracker.estimate_scan_seconds(
            instrument_name, estimated_runtime_points, number_neutrons,
            needs_compile=not reuse_binary, engine="mcstas", mpi_count=mpi_count,
        )
        total_est = estimate.get("estimated_seconds")
        if total_est is not None:
            est_str = RuntimeTracker.format_time(total_est)
            self.pre_scan_estimate_updated.emit(est_str)
            self.message_printed.emit(f"Estimated total time: {est_str}")
        else:
            self.pre_scan_estimate_updated.emit("")
        
        total_counts = 0
        max_counts = 0
        realized_background_events = []
        
        # Track individual scan times for runtime recording
        executed_scan_times = []
        simulation_stage_durations = []
        point_stage_timings = []
        first_successful_stage_record_index = None
        
        # Data collection for output files
        import numpy as np
        if is_2d_scan:
            # For 2D scans: store counts in a 2D grid
            counts_grid = np.full((len(array_values2), len(array_values1)), np.nan)
        else:
            # For 1D scans: store x values and counts as parallel arrays
            scan_x_values = []
            scan_counts = []
        
        # build_fingerprint / reuse_binary were resolved above for the pre-scan
        # estimate; reuse them here to build (or skip building) the instrument.
        if reuse_binary:
            instrument = self._binary_reuse_cache["instrument"]
            execution_state = self._binary_reuse_cache["execution_state"]
            self.message_printed.emit(
                "Build settings unchanged; reusing compiled instrument from previous scan"
            )
        else:
            instrument = self.instrument.build(
                scan_config,
                diagnostic_mode,
                effective_diagnostic_settings,
                number_neutrons,
            )
            execution_state = RunExecutionState()
        retained_diagnostic_data = None

        if diagnostic_mode and diagnostic_settings.get('Show Instrument Diagram', False):
            self.instrument_diagram_requested.emit(instrument)

        snapshot_queue = queue.Queue()
        prep_thread = threading.Thread(
            target=self._prep_worker,
            args=(
                scan_parameter_input,
                plan,
                scan_config,
                vals,
                data_folder,
                snapshot_queue,
                self.stop_event,
            ),
            daemon=True,
        )
        prep_thread.start()

        processed_points = 0
        remaining_runtime_points = estimated_runtime_points
        data = None
        simulation_stopped = False
        simulation_error_message = None

        try:
            while True:
                if self.stop_event.is_set():
                    simulation_stopped = True
                    break

                try:
                    snapshot = snapshot_queue.get(timeout=0.1)
                except queue.Empty:
                    if prep_thread.is_alive():
                        continue
                    break

                if snapshot is None:
                    break

                if isinstance(snapshot, PrepFailure):
                    simulation_error_message = f"Preparation thread failed: {snapshot.message}"
                    self.message_printed.emit(simulation_error_message)
                    break

                scan_start_time = time.time()
                i = snapshot.scan_index
                self.message_printed.emit(snapshot.log_message)
                indices = snapshot.indices
                idx_1d = indices['idx_1d']
                idx_x = indices['idx_x']
                idx_y = indices['idx_y']
                scan_folder = snapshot.output_folder
                error_flags = list(snapshot.error_flags)
                metadata = snapshot.metadata
                deltaE = snapshot.deltaE
                qx = metadata['qx']
                qy = metadata['qy']
                qz = metadata['qz']
                H = metadata['H']
                K = metadata['K']
                L = metadata['L']
                mtt = metadata['mtt']
                stt = metadata['stt']
                sth = metadata['sth']
                att = metadata['att']
                rhm = metadata['rhm']
                rvm = metadata['rvm']
                rha = metadata['rha']
                rva = metadata['rva']
                omega_scan = metadata['omega']
                timing = snapshot.timing
                prep_duration = float(timing.get('prep_duration_s', 0.0))
                prep_compute_duration = float(timing.get('prep_compute_duration_s', 0.0))
                prep_queue_wait_duration = float(timing.get('prep_queue_wait_duration_s', 0.0))
                simulation_duration = 0.0

                if is_2d_scan:
                    self.scan_current_index_2d.emit(idx_x, idx_y)
                else:
                    self.scan_current_index_1d.emit(idx_1d)

                execution_info = {
                    'mode': 'skipped',
                    'returncode': None,
                    'stdout': None,
                    'binary_path': execution_state.binary_path,
                    'output_folder': scan_folder,
                    'error_message': None,
                    'launcher_argv': list(execution_state.mpi_launcher_argv or []),
                    'armed_direct_run': False,
                }

                if not error_flags and snapshot.params is not None:
                    simulation_stage_start = time.perf_counter()
                    data, error_flags, execution_info = self.instrument.run_point(
                        instrument,
                        snapshot,
                        scan_folder,
                        number_neutrons,
                        execution_state,
                        mpi_count=mpi_count,
                    )
                    simulation_duration = time.perf_counter() - simulation_stage_start
                    simulated_point = True
                else:
                    data = math.nan
                    self.message_printed.emit(f"Point {i}: skipped, error flags: {error_flags}")
                    simulated_point = False

                if execution_info.get('armed_direct_run'):
                    launcher_text = " ".join(execution_info.get('launcher_argv', [])) or "unresolved"
                    self.message_printed.emit(
                        f"Direct run armed: binary={execution_info.get('binary_path')}, "
                        f"launcher={launcher_text}, point={i}"
                    )

                if execution_info.get('mode') == 'direct' and not error_flags:
                    self.message_printed.emit(f"Point {i} executed via direct binary")

                if retained_diagnostic_data is None and data is not None and data is not math.nan:
                    retained_diagnostic_data = data

                postprocessing_stage_start = time.perf_counter()

                # On the first scan point, copy the .instr file to the parent folder
                # (it's the same for every point since only parameters change, not the compiled
                # instrument structure; rewriting it per-point would be redundant).
                if i == 0:
                    instr_src = os.path.join(scan_folder, f"{self._mcstas_name}.instr")
                    instr_dst = os.path.join(data_folder, f"{self._mcstas_name}.instr")
                    # Direct binary runs write no .instr into the scan folder;
                    # a reused-binary scan archives the compiling scan's copy.
                    if not os.path.exists(instr_src) and reuse_binary:
                        cached_instr = self._binary_reuse_cache.get("instr_path")
                        if cached_instr and os.path.isfile(cached_instr):
                            instr_src = cached_instr
                    if os.path.exists(instr_src):
                        try:
                            shutil.copy2(instr_src, instr_dst)
                        except Exception as e:
                            self.print_to_message_center(
                                f"Warning: Failed to copy .instr file: {e}\n"
                                f"  Source: {instr_src}\n  Dest: {instr_dst}"
                            )

                # Compact save mode: remove large intermediate files from the scan sub-folder.
                # detector.dat and scan_parameters.txt are kept; everything else is transient.
                if compact_save_enabled:
                    for _fname in (f"{self._mcstas_name}.c", f"{self._mcstas_name}.instr", "mccode.sim"):
                        _fpath = os.path.join(scan_folder, _fname)
                        if os.path.exists(_fpath):
                            try:
                                os.remove(_fpath)
                            except Exception as e:
                                self.print_to_message_center(
                                    f"Warning: Failed to delete {_fname}: {e}\n  Path: {_fpath}"
                                )

                # Check for errors
                if error_flags:
                    if execution_info.get('error_message'):
                        self.message_printed.emit(
                            f"Point {i} {execution_info.get('mode')} error: {execution_info['error_message']}"
                        )
                    if execution_info.get('stdout'):
                        stdout_text = execution_info['stdout'].strip()
                        if stdout_text:
                            self.message_printed.emit(
                                f"Point {i} direct output:\n{stdout_text}"
                            )
                    message = f"Scan failed, error flags: {error_flags}"
                    self.message_printed.emit(message)
                    if is_2d_scan:
                        self.scan_point_invalid_2d.emit(idx_x, idx_y)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id,
                                'ix': idx_x,
                                'iy': idx_y,
                                'value_1': float(array_values1[idx_x]),
                                'value_2': float(array_values2[idx_y]),
                            })
                    elif not is_single_point_scan and idx_1d >= 0:
                        self.scan_point_invalid_1d.emit(idx_1d)
                        if job is not None:
                            self._publish_api_event('point_invalid', {
                                'job_id': job.job_id,
                                'index': idx_1d,
                                'value': (float(array_values1[idx_1d])
                                          if idx_1d < len(array_values1) else None),
                            })

                    if not is_2d_scan and not is_single_point_scan and idx_1d >= 0 and idx_1d < len(array_values1):
                        scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(np.nan)
                else:
                    # Build scan-specific parameters for this point. The
                    # per-point file takes metadata's own deltaE (None at a
                    # marked point) -- not the numeric McStas input -- so the
                    # saved record and the API result cannot disagree with
                    # each other about what was determined.
                    write_parameters_to_file(scan_folder, self.point_output_parameters(
                        vals, metadata, i, number_neutrons))

                    if metadata.get('transmission'):
                        self.message_printed.emit(
                            "Point %d: direct transmission (%s); %s, McStas "
                            "counts as simulated"
                            % (i, ", ".join(metadata['transmission']),
                               "Ei/Ef/deltaE not recorded"
                               if metadata.get('deltaE') is None
                               else "forward scattering, energies recorded, "
                                    "no analytic resolution here")
                        )

                    # Read detector file to get counts. `intensity` (McStas I) is
                    # an independent weighted reading, not derived from `counts`
                    # (N), so the background overlay below leaves it untouched.
                    intensity, intensity_error, counts = read_1Ddetector_file(scan_folder)

                    # Add smooth background through its dedicated Poisson stream,
                    # then sparse events through a source-keyed event stream.
                    # Both alter detector counts only; weighted intensity stays
                    # the unmodified McStas reading.
                    if background.enabled and counts is not None:
                        q0 = _background_q_magnitude(metadata)
                        if q0 is None:
                            self.message_printed.emit(
                                "Point %d: background not planted: |Q| "
                                "undetermined at a direct-transmission point"
                                % i
                            )
                        else:
                            sigma_q = None
                            sigma_e = None
                            if background_needs_sigma_q or background_needs_sigma_e:
                                try:
                                    from tavi.deterministic_engine import marginal_sigma as _marginal_sigma
                                    from tavi.resolution import resolution as _resolution
                                    # THIS point's own applied radii AND kinematics
                                    # (metadata), not the frozen launch vals -- see
                                    # the deterministic engine's identical fix above.
                                    background_resolution = _resolution(
                                        self.instrument.resolution_config(
                                            _vals_with_point_state(vals, metadata),
                                            q0, float(deltaE),
                                            point_angles=_point_angles(
                                                metadata['mtt'], metadata['stt'], metadata['att']
                                            ),
                                        )
                                    )
                                    if background_needs_sigma_q:
                                        sigma_q = _marginal_sigma(
                                            background_resolution, 'dq_par'
                                        )
                                    if background_needs_sigma_e:
                                        sigma_e = _marginal_sigma(
                                            background_resolution, 'dE'
                                        )
                                except Exception as exc:
                                    self.message_printed.emit(
                                        f"Point {i}: background resolution widths "
                                        f"unavailable ({exc}); using catalog "
                                        f"fallback widths"
                                    )
                            background_context = _background.BackgroundPointContext(
                                q_inv_ang=q0,
                                w_meV=float(deltaE),
                                sigma_q_inv_ang=sigma_q,
                                sigma_e_meV=sigma_e,
                                number_neutrons=number_neutrons,
                            )
                            bg_counts = _background.poisson_overlay(
                                background,
                                background_context,
                                background_seed,
                                i,
                            )
                            if bg_counts:
                                counts = counts + bg_counts
                            if background_has_events:
                                event_counts, point_events = (
                                    _background.draw_event_overlay(
                                        background,
                                        background_context,
                                        background_seed,
                                        i,
                                    )
                                )
                                if event_counts:
                                    counts = counts + event_counts
                                realized_background_events.extend(point_events)

                    message = f"Final counts at detector: {int(counts)}"
                    self.message_printed.emit(message)

                    # Update counts
                    total_counts += counts
                    max_counts = max(max_counts, counts)
                    
                    # Emit display update signal
                    if is_2d_scan:
                        self.scan_point_updated_2d.emit(idx_x, idx_y, counts)
                        # Store in grid for output file
                        counts_grid[idx_y, idx_x] = counts
                    elif not is_single_point_scan:
                        # 1D scan with actual scan values
                        if idx_1d >= 0:
                            self.scan_point_updated_1d.emit(idx_1d, counts)
                        # Store in arrays for output file
                        if idx_1d >= 0 and idx_1d < len(array_values1):
                            scan_x_values.append(array_values1[idx_1d])
                        scan_counts.append(counts)
                    # For single-point scans, we don't update scan arrays (handled separately)

                    # Record the measured count into the job result for readers.
                    if job is not None and job.result is not None:
                        # THIS point's own applied radii (metadata), signed --
                        # see ScanResult.applied_curvature. The McStas
                        # per-point files already carry this; this is the
                        # HTTP/GUI-facing record of the same truth.
                        point_curvature = {
                            axis: metadata[axis] for axis in ("rhm", "rvm", "rha", "rva")
                        }
                        with job.lock:
                            res = job.result
                            if is_2d_scan:
                                if res.counts_grid is not None:
                                    res.counts_grid[idx_y][idx_x] = float(counts)
                                if res.applied_curvature:
                                    orig_idx = idx_y * len(res.scan_values_1) + idx_x
                                    if 0 <= orig_idx < len(res.applied_curvature):
                                        res.applied_curvature[orig_idx] = point_curvature
                            elif is_single_point_scan:
                                if res.counts:
                                    res.counts[0] = float(counts)
                                if res.applied_curvature:
                                    res.applied_curvature[0] = point_curvature
                            elif idx_1d >= 0 and res.counts is not None and idx_1d < len(res.counts):
                                res.counts[idx_1d] = float(counts)
                                if res.applied_curvature and idx_1d < len(res.applied_curvature):
                                    res.applied_curvature[idx_1d] = point_curvature
                            res.total_counts = float(total_counts)
                            res.max_counts = float(max_counts)
                            self._mark_executed_result_point(
                                res,
                                is_2d_scan=is_2d_scan,
                                is_single_point_scan=is_single_point_scan,
                                idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                            )
                            if metadata.get('transmission'):
                                point_index = self._scan_point_linear_index(
                                    is_2d_scan=is_2d_scan,
                                    is_single_point_scan=is_single_point_scan,
                                    idx_1d=idx_1d, idx_x=idx_x, idx_y=idx_y,
                                    values_1_len=len(res.scan_values_1),
                                )
                                res.transmission_points.append({
                                    "index": point_index,
                                    "axes": list(metadata['transmission']),
                                })

                        # Publish the per-point SSE event (outside the lock).
                        if is_2d_scan:
                            self._publish_api_event('point', {
                                'job_id': job.job_id,
                                'ix': idx_x,
                                'iy': idx_y,
                                'value_1': float(array_values1[idx_x]),
                                'value_2': float(array_values2[idx_y]),
                                'counts': float(counts),
                            })
                        elif is_single_point_scan:
                            self._publish_api_event('point', {
                                'job_id': job.job_id,
                                'index': 0,
                                'value': None,
                                'counts': float(counts),
                            })
                        elif idx_1d >= 0:
                            self._publish_api_event('point', {
                                'job_id': job.job_id,
                                'index': idx_1d,
                                'value': (float(array_values1[idx_1d])
                                          if idx_1d < len(array_values1) else None),
                                'counts': float(counts),
                            })
                
                # Record scan time for this point
                scan_elapsed = time.time() - scan_start_time
                if simulated_point and not error_flags:
                    executed_scan_times.append(scan_elapsed)
                    if remaining_runtime_points > 0:
                        remaining_runtime_points -= 1
                processed_points += 1
                
                # Emit progress signals
                self.progress_updated.emit(processed_points, total_scans)
                self.counts_updated.emit(max_counts, total_counts)

                # Mirror progress into the job (covers valid and invalid points,
                # since processed_points increments for every drained point).
                if job is not None:
                    with job.lock:
                        job.progress_done = processed_points
                    self._publish_api_event('progress', {
                        'job_id': job.job_id,
                        'done': processed_points,
                        'total': total_scans,
                        'elapsed': time.time() - start_time,
                    })
                
                # Calculate elapsed time and remaining time - ignore first scan (compilation overhead)
                elapsed_time = time.time() - start_time
                # Emit elapsed time for UI
                try:
                    elapsed_str = RuntimeTracker.format_time(elapsed_time)
                    self.elapsed_time_updated.emit(elapsed_str)
                except Exception:
                    pass
                if len(executed_scan_times) <= 1:
                    # After first scan, use historical data for estimation if
                    # available. Engine-filtered to mcstas so tiny deterministic
                    # records never poison the McStas per-point estimate.
                    hist = self.runtime_tracker.estimate_scan_seconds(
                        instrument_name, 1, number_neutrons,
                        needs_compile=False, engine="mcstas", mpi_count=mpi_count,
                    )
                    run_time_per_point = hist.get("estimated_seconds")
                    if run_time_per_point is not None and remaining_runtime_points > 0:
                        remaining_time = run_time_per_point * remaining_runtime_points
                    elif executed_scan_times and remaining_runtime_points > 0:
                        remaining_time = executed_scan_times[0] * remaining_runtime_points
                    else:
                        remaining_time = 0
                else:
                    # For subsequent scans, use average of scans 2+ (excluding first/compile scan)
                    subsequent_times = executed_scan_times[1:]  # Exclude first executed/compile scan
                    avg_time_per_scan = sum(subsequent_times) / len(subsequent_times)
                    remaining_time = avg_time_per_scan * remaining_runtime_points
                
                hours = int(remaining_time // 3600)
                minutes = int((remaining_time % 3600) // 60)
                seconds = int(remaining_time % 60)
                time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                self.remaining_time_updated.emit(time_str)

                postprocessing_duration = time.perf_counter() - postprocessing_stage_start
                if simulated_point and not error_flags:
                    simulation_stage_durations.append(simulation_duration)

                point_stage_timings.append({
                    'scan_index': i,
                    'prep_duration_s': prep_duration,
                    'prep_compute_duration_s': prep_compute_duration,
                    'prep_queue_wait_duration_s': prep_queue_wait_duration,
                    'simulation_duration_s': simulation_duration,
                    'postprocessing_duration_s': postprocessing_duration,
                    'execution_mode': execution_info.get('mode'),
                    'direct_returncode': execution_info.get('returncode'),
                    'direct_binary_path': execution_info.get('binary_path'),
                    'simulated': bool(simulated_point and not error_flags),
                    'error_flags': list(error_flags),
                })
                if simulated_point and not error_flags and first_successful_stage_record_index is None:
                    first_successful_stage_record_index = len(point_stage_timings) - 1
        except Exception as e:
            simulation_error_message = f"Simulation failed: {e}"
            self.message_printed.emit(simulation_error_message)
            self.stop_event.set()
        finally:
            if simulation_error_message is not None:
                self.stop_event.set()
            prep_thread.join(timeout=1)

        if simulation_stopped:
            self.message_printed.emit("Simulation stopped by user.")

        self._binary_reuse_cache = self._updated_binary_cache(
            self._binary_reuse_cache,
            reuse_binary,
            build_fingerprint,
            instrument,
            execution_state,
            os.path.join(data_folder, f"{self._mcstas_name}.instr"),
        )

        inferred_compile_duration = None
        if len(simulation_stage_durations) > 1:
            avg_subsequent_simulation_duration = sum(simulation_stage_durations[1:]) / len(simulation_stage_durations[1:])
            inferred_compile_duration = max(0.0, simulation_stage_durations[0] - avg_subsequent_simulation_duration)
        if inferred_compile_duration is not None and first_successful_stage_record_index is not None:
            point_stage_timings[first_successful_stage_record_index]['inferred_compile_duration_s'] = inferred_compile_duration

        if point_stage_timings:
            prep_durations = [record['prep_duration_s'] for record in point_stage_timings]
            prep_compute_durations = [record['prep_compute_duration_s'] for record in point_stage_timings]
            prep_queue_wait_durations = [record['prep_queue_wait_duration_s'] for record in point_stage_timings]
            postprocessing_durations = [record['postprocessing_duration_s'] for record in point_stage_timings]
            stage_summary = {
                'completed_normally': simulation_error_message is None and not self.stop_event.is_set(),
                'stopped': simulation_stopped or self.stop_event.is_set(),
                'simulation_error_message': simulation_error_message,
                'total_requested_points': total_scans,
                'total_simulated_points': len(executed_scan_times),
                'num_backengine_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'backengine'
                ),
                'num_direct_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'direct'
                ),
                'num_skipped_points': sum(
                    1 for record in point_stage_timings if record.get('execution_mode') == 'skipped'
                ),
                'compile_duration_s': inferred_compile_duration,
                'compile_duration_inferred': inferred_compile_duration is not None,
                'avg_prep_duration_s': sum(prep_durations) / len(prep_durations),
                'avg_prep_compute_duration_s': sum(prep_compute_durations) / len(prep_compute_durations),
                'avg_prep_queue_wait_duration_s': sum(prep_queue_wait_durations) / len(prep_queue_wait_durations),
                'avg_simulation_duration_s': (
                    sum(simulation_stage_durations) / len(simulation_stage_durations)
                    if simulation_stage_durations else 0.0
                ),
                'avg_postprocessing_duration_s': sum(postprocessing_durations) / len(postprocessing_durations),
                'point_timings': point_stage_timings,
            }
            try:
                summary_path = self._write_stage_timing_summary(data_folder, stage_summary)
                compile_message = (
                    f"compile={inferred_compile_duration:.3f}s"
                    if inferred_compile_duration is not None else "compile=unavailable"
                )
                self.message_printed.emit(
                    "Stage timings recorded: "
                    f"{compile_message}, avg prep={stage_summary['avg_prep_duration_s']:.3f}s "
                    f"(compute={stage_summary['avg_prep_compute_duration_s']:.3f}s, "
                    f"queue_wait={stage_summary['avg_prep_queue_wait_duration_s']:.3f}s), "
                    f"avg sim={stage_summary['avg_simulation_duration_s']:.3f}s, "
                    f"avg post={stage_summary['avg_postprocessing_duration_s']:.3f}s"
                )
                self.message_printed.emit(f"Stage timing summary written to: {summary_path}")
            except Exception as e:
                self.message_printed.emit(f"Warning: Failed to write stage timing summary: {e}")
        
        # Record runtime data for future estimates (only if scan completed normally)
        if executed_scan_times and simulation_error_message is None and not self.stop_event.is_set():
            total_time = time.time() - start_time
            first_scan_time = executed_scan_times[0]
            
            # Calculate average time for subsequent scans (excluding first)
            if len(executed_scan_times) > 1:
                avg_subsequent_time = sum(executed_scan_times[1:]) / len(executed_scan_times[1:])
                # A reused binary skips compilation, so first - avg is not a
                # compile time; record 0 and suppress the inference (schema v2).
                if reuse_binary:
                    compilation_time = 0.0
                else:
                    compilation_time = inferred_compile_duration if inferred_compile_duration is not None else max(0.0, first_scan_time - avg_subsequent_time)
            else:
                # Only one scan point - use first scan time as both
                avg_subsequent_time = first_scan_time
                compilation_time = 0.0

            # Dominant execution mode over the simulated points (schema v2).
            execution_mode = self._dominant_execution_mode(point_stage_timings)

            build_fp_hash = hashlib.sha1(
                repr(build_fingerprint).encode('utf-8')
            ).hexdigest()[:12]
            record_source = (
                "benchmark"
                if (job is not None and getattr(job, "source", None) == "benchmark")
                else "organic"
            )

            self.runtime_tracker.add_record(
                instrument_name=instrument_name,
                num_points=len(executed_scan_times),
                num_neutrons=number_neutrons,
                first_scan_time=first_scan_time,
                avg_subsequent_time=avg_subsequent_time,
                total_time=total_time,
                compilation_time=compilation_time,
                machine_id=machine_fingerprint()["machine_id"],
                engine="mcstas",
                execution_mode=execution_mode,
                binary_reused=reuse_binary,
                build_fp_hash=build_fp_hash,
                source=record_source,
                mpi_count=mpi_count,
            )
            self.message_printed.emit(
                f"Timing data recorded: {len(executed_scan_times)} simulated points in {RuntimeTracker.format_time(total_time)}"
            )
            # Trigger update of scan time estimates on main thread
            self.runtime_data_updated.emit()
        
        # Simulation complete
        if simulation_error_message is None and not self.stop_event.is_set():
            self.message_printed.emit(f"Simulation complete! Data saved to: {data_folder}")
            self.message_printed.emit(f"Total counts: {total_counts}, Max counts: {max_counts}")
        
        # Write scan data to output files
        if not is_single_point_scan and simulation_error_message is None and not self.stop_event.is_set():
            try:
                if is_2d_scan:
                    # Write 2D scan data (include parameter labels if available)
                    x_label = variable_name1 if 'variable_name1' in locals() and variable_name1 else 'scan1'
                    y_label = variable_name2 if 'variable_name2' in locals() and variable_name2 else 'scan2'
                    write_2D_scan(
                        np.array(array_values1),
                        np.array(array_values2),
                        counts_grid,
                        data_folder,
                        "2D_scan_data.txt",
                        x_label=x_label,
                        y_label=y_label,
                    )
                    self.message_printed.emit(f"2D scan data written to: {os.path.join(data_folder, '2D_scan_data.txt')}")
                else:
                    # Write 1D scan data
                    if scan_x_values and scan_counts:
                        # Sort by x values for proper ordering
                        sorted_indices = np.argsort(scan_x_values)
                        sorted_x = np.array(scan_x_values)[sorted_indices]
                        sorted_counts = np.array(scan_counts)[sorted_indices]
                        x_label = variable_name1 if 'variable_name1' in locals() and variable_name1 else 'scan'
                        write_1D_scan(sorted_x, sorted_counts, data_folder, "1D_scan_data.txt", x_label=x_label, y_label='counts')
                        self.message_printed.emit(f"1D scan data written to: {os.path.join(data_folder, '1D_scan_data.txt')}")
            except Exception as e:
                self.message_printed.emit(f"Warning: Failed to write scan data file: {e}")
        
        # Handle display based on scan type
        if simulation_error_message is not None or self.stop_event.is_set():
            self.scan_completed.emit()
        elif is_single_point_scan:
            # For single-point scans, show results as text instead of plot
            self.single_point_result.emit(max_counts, total_counts)
        else:
            # For 1D/2D scans, signal completion and auto-save the plot
            self.scan_completed.emit()
            self.scan_auto_save.emit()
        
        # Display diagnostic subplots if in diagnostic mode and any monitors were enabled
        if diagnostic_mode and simulation_error_message is None and not self.stop_event.is_set():
            # Check if any diagnostic monitors were enabled (excluding Show Instrument Diagram)
            monitors_enabled = any(
                enabled for key, enabled in diagnostic_settings.items() 
                if key != "Show Instrument Diagram" and enabled
            )
            if monitors_enabled and retained_diagnostic_data is not None and retained_diagnostic_data is not math.nan:
                # Emit signal to display plots on main thread (matplotlib requires this)
                self.diagnostic_plot_requested.emit(retained_diagnostic_data)

        # Stamp the background provenance into result.metadata via the shared
        # helper, so a McStas scan record carries the same block a deterministic
        # one does. Stamped even when the profile is disabled -- absence of
        # background is provenance too -- and covers the single-point branch,
        # which finalizes here like every other scan mode. The seed is recorded
        # only when something was actually drawn.
        if job is not None and job.result is not None \
                and simulation_error_message is None:
            with job.lock:
                job.result.metadata['background'] = _background.metadata_block(
                    background, background_source,
                    background_seed=(
                        background_seed
                        if number_neutrons > 0 and (
                            _background.active_mean_sources(background)
                            or background_has_events
                        )
                        else None
                    ),
                    realized_events=realized_background_events,
                )

        # Finalize job bookkeeping: pick the terminal state from the same flags
        # the display/output paths above already used. The worker loop emits the
        # job_state_changed signal after this returns.
        if job is not None:
            if simulation_error_message is not None:
                final_state = JobState.FAILED
            elif self.stop_event.is_set():
                final_state = JobState.STOPPED
            else:
                final_state = JobState.DONE
            with job.lock:
                job.state = final_state
                job.error = simulation_error_message
                job.finished_at = time.time()
                self.last_scan_result = job.result
                job.notify_state_change()

        return data_folder


def main():
    """Main entry point for the application.

    Instrument selection (docs/CONFIGURABLE_INSTRUMENTS.md §7.1, §17.1): the
    --instrument CLI flag always wins; a picker dialog appears only when more
    than one instrument is registered and no flag was given; with a single
    registered instrument, startup is identical to the pre-registry app. The
    selection is fixed for the session.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="TAVI")
    parser.add_argument(
        "--instrument", metavar="ID", default=None,
        help="Instrument id to load (e.g. 'puma'); skips the startup picker.",
    )
    parser.add_argument(
        "--api-port", metavar="N", type=int, default=None,
        help="Enable the remote API server on port N (overrides config port).",
    )
    parser.add_argument(
        "--no-api", action="store_true",
        help="Disable the remote API server regardless of config.",
    )
    args, qt_args = parser.parse_known_args()  # leftover args go to Qt

    # Remote-API CLI overrides handed to the controller (see _start_api_server).
    api_overrides = {}
    if args.no_api:
        api_overrides["disabled"] = True
    if args.api_port is not None:
        api_overrides["port"] = args.api_port

    import instruments.builtin  # noqa: F401  (explicit built-in registration)
    from instruments.registry import (available_instruments, get_instrument,
                                       load_last_instrument, save_last_instrument)

    infos = available_instruments()
    valid_ids = {info.id for info in infos}

    instrument_id = None
    if args.instrument is not None:
        instrument_id = args.instrument.lower()
        if instrument_id not in valid_ids:
            print(
                f"Unknown instrument '{args.instrument}'. Available: "
                + ", ".join(info.id for info in infos),
                file=sys.stderr,
            )
            sys.exit(2)

    app = QApplication([sys.argv[0], *qt_args])

    # Precedence: --instrument flag > saved last_instrument (if still registered)
    # > single-instrument shortcut > picker dialog. A stale/unknown saved id is
    # ignored (load_last_instrument filters against valid_ids).
    if instrument_id is None:
        saved_id = load_last_instrument(valid_ids=valid_ids)
        if saved_id is not None:
            instrument_id = saved_id
        elif len(infos) == 1:
            instrument_id = infos[0].id
        else:
            from gui.dialogs.instrument_picker_dialog import InstrumentPickerDialog

            instrument_id = InstrumentPickerDialog.pick(infos)
            if instrument_id is None:
                sys.exit(0)

    # Remember the resolved instrument so the next launch reopens it.
    save_last_instrument(instrument_id)

    instrument = get_instrument(instrument_id)

    # Fail fast, with readable errors, if the registered descriptor is unrunnable.
    from instruments.validation import assert_valid_capabilities, assert_valid_descriptor
    assert_valid_descriptor(instrument.descriptor(), runnable=True)
    assert_valid_capabilities(instrument.capabilities(), instrument.id)

    window = TAVIMainWindow(
        instrument.descriptor(),
        instrument_infos=infos,
        current_instrument_id=instrument_id,
        save_selection=save_last_instrument,
    )
    controller = TAVIController(window, instrument, api_overrides=api_overrides)
    # Store controller reference on window so closeEvent can access it
    window.controller = controller
    window.show()
    exit_code = app.exec()

    # If the user chose a different instrument via the Instrument menu, the window
    # saved the new id and closed. Relaunch a detached process with that id.
    restart_id = getattr(window, "_restart_instrument_id", None)
    if restart_id is not None:
        import subprocess

        # Rebuild argv robustly (argv[0] may be the script path) and strip any
        # existing --instrument pair so only the new id applies; keep everything
        # else (--api-port, --no-api, leftover Qt args).
        script_path = os.path.abspath(__file__)
        filtered_args = []
        skip_next = False
        for arg in sys.argv[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg == "--instrument":
                skip_next = True
                continue
            if arg.startswith("--instrument="):
                continue
            filtered_args.append(arg)
        new_argv = [sys.executable, script_path, "--instrument", restart_id,
                    *filtered_args]
        # The old process must fully exit before the new one binds the API port;
        # the new process's slow imports (Qt/McStasScript) make this safe in
        # practice. close_fds detaches so the child outlives this process.
        subprocess.Popen(new_argv, close_fds=True)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
