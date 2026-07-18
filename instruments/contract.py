"""The ``InstrumentPlugin`` contract + shared run-execution state.

Part of the configurable-instruments effort (``docs/CONFIGURABLE_INSTRUMENTS.md``
§5, §17). A registered instrument is any object satisfying ``InstrumentPlugin``;
PUMA is the first implementation (``instruments/puma/plugin.py``, wrapping its
package-local builder plus the shared TAS preparation/execution runtime); IN8
is the second. The contract is intentionally free
of PUMA-specific parameter names -- the parameter *set* lives in the descriptor,
and a snapshot's ``params`` is just "this instrument's parameters".

Adjusted from the Phase-0 draft (2026-07-02, see §17.2 of the design record):
``new_state(gui_values)`` is replaced by ``default_state()`` + ``scan_config(...)``
because a scan config is a deep copy of *live session state* (which carries
hidden training misalignments absent from the GUI values), and a transitional
``crystal_info(...)`` hook covers the controller's live crystal-parameter needs
until Phase 2 sources them from the descriptor.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from instruments.descriptor import InstrumentDescriptor

if TYPE_CHECKING:  # avoid importing heavy modules just for type hints
    import mcstasscript as ms

    from tavi.resolution import ResolutionConfig
    from tavi.sample_mount import SampleMount


# The opaque per-session/per-run state object (today: PUMA_Instrument, a
# TAS_Instrument subclass). Kept opaque so this module imports no concrete
# instrument. The controller may set generic TAS_Instrument base attributes
# (monocris/anacris/K_fixed/fixed_E/sample_mount/omega/...) on it directly.
InstrumentState = Any

# Default MPI worker count for a McStas point run. There is no GUI knob for this
# today; the fan-out width is fixed here and referenced by the run-point sites
# (and recorded on mcstas scan records for future-proofing).
DEFAULT_MPI_COUNT = 30


@dataclass
class RunExecutionState:
    """Generalised run-execution state -- no hard-coded binary name.

    Tracks the compile-once / run-direct optimisation: after the first
    ``backengine()`` compiles the binary, subsequent points invoke it directly via
    the resolved MPI launcher. ``binary_path`` is derived from the built
    instrument's name rather than assuming a fixed instrument binary.
    """

    first_backengine_succeeded: bool = False
    direct_run_ready: bool = False
    binary_path: str | None = None
    binary_cwd: str | None = None
    mpi_launcher_argv: list[str] | None = None
    last_execution_mode: str | None = None


@dataclass
class PointSnapshot:
    """One scan point's prepared runtime state (returned by ``compute_snapshot``).

    Replaces the raw snapshot dict (design record §16.6) so keys cannot silently
    drift. Deliberately **non-frozen**: the controller's prep thread stamps
    ``timing`` onto the instance *after* it is queued (the queued object is
    shared by reference with the consumer loop). ``metadata`` stays a plain dict
    because it is ``**``-spread into ``scan_parameters.txt``.
    """

    params: dict | None             # {<scannable_parameters> -> value}; None = point errored
    output_folder: str
    scan_index: int
    deltaE: float
    error_flags: list
    metadata: dict
    indices: dict                   # {"idx_1d", "idx_x", "idx_y"}
    log_message: str
    timing: dict = field(default_factory=dict)  # controller-stamped stage timings


@dataclass(frozen=True, slots=True)
class PrepFailure:
    """Sentinel the prep thread queues when ``compute_snapshot`` raises.

    Replaces the legacy ``{'fatal_error': str}`` dict; the simulation loop
    aborts the scan when it dequeues one.
    """

    message: str


@runtime_checkable
class InstrumentPlugin(Protocol):
    """Contract every instrument plugin satisfies.

    Methods mirror the original PUMA functions, lifted behind a stable interface:
      - ``build``            <- the package-local McStas tree builder
      - ``compute_snapshot`` <- ``compute_scan_snapshot``
      - ``run_point``        <- shared ``run_tas_point`` execution
    plus ``descriptor`` (the GUI knobs), ``default_state`` (fresh state),
    ``scan_config`` (frozen GUI -> scan config), and the transitional
    ``crystal_info``.
    """

    id: str
    display_name: str

    def descriptor(self) -> InstrumentDescriptor:
        """Return the static GUI-facing description (libraries, modules, params)."""
        ...

    def default_state(self) -> InstrumentState:
        """Return a fresh instrument state with the instrument's defaults.

        Used for (a) the controller's live per-session state at startup and
        (b) throwaway states for scan-point validation prepasses.
        """
        ...

    def scan_config(
        self,
        base_state: InstrumentState,
        gui_values: dict,
        sample_key: str | None,
        diagnostic_settings: dict,
        sample_mount: "SampleMount",
    ) -> InstrumentState:
        """Build the frozen scan-launch config.

        Deep-copies ``base_state`` *inside the plugin*, then applies the
        instrument's GUI-value mapping. Replaces the controller's hand-written
        ``_build_scan_puma_config`` -- each instrument owns the mapping from its
        GUI fields to its config object. ``base_state`` (the live session state)
        is required because it carries state that is deliberately absent from
        ``gui_values`` (e.g. hidden training misalignments). ``sample_mount`` is
        built by the controller (it depends on the session UB matrix) and passed
        in so the plugin stays free of UB coupling.
        """
        ...

    def crystal_info(self, mono_label: str, ana_label: str) -> tuple[dict, dict]:
        """TRANSITIONAL (Phase 1 only): crystal parameter dicts for live GUI math.

        Returns ``(monochromator_info, analyzer_info)`` shaped exactly like the
        legacy ``mono_ana_crystals_setup()`` output (``'dm'``/``'da'``, slab
        geometry, mosaic, reflectivity files...). Phase 2 replaces this with
        descriptor ``CrystalSpec`` lookups; do not grow new callers.
        """
        ...

    def build(
        self,
        config: InstrumentState,
        diagnostic_mode: bool,
        diagnostic_settings: dict,
        number_neutrons: int,
    ) -> "ms.McStas_instr":
        """One-time imperative construction of the McStasScript instrument."""
        ...

    def build_fingerprint(
        self,
        config: InstrumentState,
        diagnostic_mode: bool = False,
        diagnostic_settings: dict | None = None,
    ) -> str:
        """Stable hash of everything that affects the compiled binary.

        Must cover the same effective inputs as ``build``. The controller
        reuses the previous scan's compiled binary when this matches the
        fingerprint captured at the last compile and the binary still exists
        (design record §18.5); diagnostic-mode scans always rebuild.
        """
        ...

    def compute_snapshot(
        self,
        scan_item: Any,
        scan_index: int,
        scan_mode: str,
        config: InstrumentState,
        vals: dict,
        data_folder: str,
        *,
        is_2d_scan: bool = False,
        variable_name1: str = "",
        variable_name2: str = "",
        scan_command1: str = "",
        scan_command2: str = "",
    ) -> PointSnapshot:
        """Compute one scan point's runtime snapshot (a ``PointSnapshot``).

        ``params`` keys are this instrument's ``scannable_parameters`` -- **not** a
        fixed PUMA set. ``None`` params means the point errored and is skipped.
        """
        ...

    def run_point(
        self,
        instrument: "ms.McStas_instr",
        snapshot: PointSnapshot,
        output_folder: str,
        number_neutrons: int,
        execution_state: RunExecutionState,
        mpi_count: int = DEFAULT_MPI_COUNT,
    ) -> tuple[Any, list[str], dict]:
        """Run one prepared point. Returns ``(data, error_flags, execution_info)``.

        ``data`` is McStasData on the compile point, ``None`` on a successful direct
        run (detector read from disk), or ``math.nan`` when skipped/failed.
        """
        ...

    def check_point_feasibility(
        self,
        config: InstrumentState,
        scan_mode: str,
        scan_point: Any,
        vals: dict,
    ) -> tuple[bool, "str | None"]:
        """Return ``(feasible, reason)`` for one scan point without running it.

        Reuses the same angle/Q solve as ``compute_snapshot`` so an infeasible
        result is exactly a point the real scan would skip. ``reason`` is a
        short limiting-constraint string when infeasible, else ``None``. Used by
        the remote API's always-on scan validation (reject, or skip under
        ``allow_partial``). Optional for a plugin; the API degrades to
        "assume feasible" when absent.
        """
        ...

    def resolution_config(
        self,
        vals: dict,
        q0: float,
        w: float,
    ) -> "ResolutionConfig":
        """Build a theoretical-resolution config for one ``(q0, w)`` point.

        Maps this instrument's launch/GUI parameter dict (the same ``vals`` shape
        ``scan_config`` consumes -- ``monocris``/``anacris``/``K_fixed``/
        ``fixed_E``/``collimation``/``modules``/``source_type``/``rhm``... plus an
        optional ``sample_key``) onto the instrument-independent
        :class:`tavi.resolution.ResolutionConfig` (ISAR Cooper-Nathans vocabulary
        + Popovici extensions): d-spacings, mosaics and senses from the
        descriptor; horizontal collimations from ``vals`` (tightest non-zero
        blade of a multi-select slot; an open/zero blade substitutes a documented
        60 arcmin effective divergence and records a warning); vertical
        divergences from the descriptor default; ``kfix``/``fx`` from ``K_fixed``/
        ``fixed_E``. ``q0`` (Angstrom^-1) and ``w`` (meV) pass straight through.

        A **pure function of its inputs**: it reads only the descriptor and
        ``vals`` and must not import mcstasscript or touch any McStas state.
        Components that break the analytic assumptions (PUMA's NMO) are recorded
        as *invalidations* on the returned config (so ``cn_valid`` becomes False)
        rather than silently ignored. Optional for a plugin, mirroring
        ``check_point_feasibility``; callers degrade gracefully when absent.
        """
        ...
