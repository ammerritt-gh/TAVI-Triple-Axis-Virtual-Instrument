"""Phase-0 DRAFT: the ``InstrumentPlugin`` contract + run-execution state.

Design sketch for the configurable-instruments effort
(see ``docs/CONFIGURABLE_INSTRUMENTS.md`` §5). **Nothing implements or imports this
yet; it changes no runtime behavior.**

A registered instrument is any object satisfying ``InstrumentPlugin``. PUMA will be
the first implementation (wrapping today's ``build_PUMA_instrument`` /
``compute_scan_snapshot`` / ``run_PUMA_point``); IN8 the second. The contract is
intentionally free of PUMA-specific parameter names -- the parameter *set* lives in
the descriptor, and a snapshot's ``params`` is just "this instrument's parameters".

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from instruments.descriptor import InstrumentDescriptor

if TYPE_CHECKING:  # avoid importing McStasScript just to type a return value
    import mcstasscript as ms


# The per-run config object (today: PUMA_Instrument, a TAS_Instrument subclass).
# Kept opaque so this module imports no concrete instrument.
InstrumentConfig = Any


@dataclass
class RunExecutionState:
    """Generalised ``PUMARunExecutionState`` -- no hard-coded binary name.

    Tracks the compile-once / run-direct optimisation: after the first
    ``backengine()`` compiles the binary, subsequent points invoke it directly via
    the resolved MPI launcher. ``binary_path`` is derived from the built
    instrument's name rather than assuming ``PUMA_McScript.exe``.
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

    Methods mirror today's PUMA functions, lifted behind a stable interface:
      - ``build``          <- ``build_PUMA_instrument``
      - ``compute_snapshot`` <- ``compute_scan_snapshot``
      - ``run_point``      <- ``run_PUMA_point``
    plus ``descriptor`` (the GUI knobs) and ``new_state`` (frozen GUI -> config).
    """

    id: str
    display_name: str

    def descriptor(self) -> InstrumentDescriptor:
        """Return the static GUI-facing description (libraries, modules, params)."""
        ...

    def new_state(self, gui_values: dict) -> InstrumentConfig:
        """Build the per-run config object from frozen GUI launch state.

        Replaces the controller's hand-written ``_build_scan_puma_config`` -- each
        instrument owns the mapping from its GUI fields to its config object.
        """
        ...

    def build(
        self,
        config: InstrumentConfig,
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
        config: InstrumentConfig,
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
