"""The ``InstrumentPlugin`` contract + shared run-execution state.

Part of the configurable-instruments effort (``docs/CONFIGURABLE_INSTRUMENTS.md``
§5, §17). A registered instrument is any object satisfying ``InstrumentPlugin``;
PUMA is the first implementation (``instruments/puma_plugin.py``, wrapping the
existing ``build_PUMA_instrument`` / ``compute_scan_snapshot`` /
``run_PUMA_point``); IN8 will be the second. The contract is intentionally free
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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from instruments.descriptor import InstrumentDescriptor

if TYPE_CHECKING:  # avoid importing heavy modules just for type hints
    import mcstasscript as ms

    from tavi.sample_mount import SampleMount


# The opaque per-session/per-run state object (today: PUMA_Instrument, a
# TAS_Instrument subclass). Kept opaque so this module imports no concrete
# instrument. The controller may set generic TAS_Instrument base attributes
# (monocris/anacris/K_fixed/fixed_E/sample_mount/omega/...) on it directly.
InstrumentState = Any


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


@runtime_checkable
class InstrumentPlugin(Protocol):
    """Contract every instrument plugin satisfies.

    Methods mirror the original PUMA functions, lifted behind a stable interface:
      - ``build``            <- ``build_PUMA_instrument``
      - ``compute_snapshot`` <- ``compute_scan_snapshot``
      - ``run_point``        <- ``run_PUMA_point``
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
    ) -> dict:
        """Compute one scan point's runtime snapshot.

        Returns a dict shaped like today's PUMA snapshot::

            {
                "params": {<scannable_parameters> -> value} | None,
                "output_folder": str,
                "scan_index": int,
                "deltaE": float,
                "error_flags": list[str],
                "metadata": dict,
                "indices": {"idx_1d", "idx_x", "idx_y"},
                "log_message": str,
            }

        ``params`` keys are this instrument's ``scannable_parameters`` -- **not** a
        fixed PUMA set. ``None`` params means the point errored and is skipped.
        """
        ...

    def run_point(
        self,
        instrument: "ms.McStas_instr",
        snapshot: dict,
        output_folder: str,
        number_neutrons: int,
        execution_state: RunExecutionState,
        mpi_count: int = 30,
    ) -> tuple[Any, list[str], dict]:
        """Run one prepared point. Returns ``(data, error_flags, execution_info)``.

        ``data`` is McStasData on the compile point, ``None`` on a successful direct
        run (detector read from disk), or ``math.nan`` when skipped/failed.
        """
        ...
