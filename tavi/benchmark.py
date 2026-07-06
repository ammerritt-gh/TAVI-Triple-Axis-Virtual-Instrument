"""Pure benchmark-plan and cross-check logic for the scan-time benchmarker.

Qt-free by design: the controller orchestration (TAVI_PySide6.py) and the GUI
dialog (gui/dialogs/benchmark_dialog.py) both delegate the plan shape and the
drift math here so the logic stays headless-testable. The controller owns the
job-queue wiring; this module owns only data.

The benchmarker gives a fresh machine a clean speed baseline: a short base
sweep of tiny scans around the current GUI position (compile + warm overhead)
followed by an adaptive rate sweep, whose measured timings feed
``machine_time_model`` (affine overhead + rate) and the per-machine estimate.
See section 4 of the scan-time rework plan.
"""
from typing import Dict, List, Optional, Sequence

# Default mcstas low ncount: the cold (compile) and warm (overhead) stages both
# run here. A single low count carries no rate information -- the per-neutron
# slope comes from the adaptive rate sweep below. Overridable via
# ``build_benchmark_plan``.
DEFAULT_LOW_NCOUNT = 10000     # 1e4

# Deterministic stage neutron count is nominal only: the analytic engine's cost
# is ~independent of ncount, so this value just travels with the record.
DEFAULT_DETERMINISTIC_NCOUNT = 100000

# The dialog highlights a cross-check row whose |drift| exceeds this percentage.
DRIFT_HIGHLIGHT_THRESHOLD = 30.0

# Adaptive rate-sweep defaults (see :func:`next_rate_stage`). The sweep starts
# at ``DEFAULT_ADAPTIVE_START_NCOUNT`` and escalates x10 until the warm
# per-point time stands clear of overhead, the time budget is spent, or the
# ncount ceiling is reached.
DEFAULT_ADAPTIVE_START_NCOUNT = 1_000_000   # 1e6
DEFAULT_ADAPTIVE_MAX_NCOUNT = 10 ** 9       # 1e9
DEFAULT_ADAPTIVE_BUDGET_S = 75.0
DEFAULT_ADAPTIVE_TARGET_RATIO = 3.0
# Each adaptive rate stage runs this many warm points.
ADAPTIVE_STAGE_POINTS = 2
# ncount escalation factor between successive adaptive stages.
ADAPTIVE_ESCALATION = 10


def build_benchmark_plan(ncounts: Optional[Sequence[int]] = None,
                         deterministic_supported: bool = True) -> List[Dict]:
    """Return the ordered base benchmark stage plan.

    Base stages (defaults):
      1. mcstas, low ncount, 3 points, force rebuild -> compile + cold cost.
      2. mcstas, low ncount, 5 points, reuse binary  -> warm per-point overhead.
      3. deterministic, 20 points (only when ``deterministic_supported``).

    Per-neutron rate is measured separately by the adaptive sweep
    (:func:`next_rate_stage`), driven by the controller once these base stages
    complete; the old fixed high-ncount "scaling" stage is dropped because a
    single high count over-/under-shoots depending on the machine.

    ``ncounts`` overrides the mcstas low ncount as ``(low,)`` (extra entries are
    ignored); a falsy or missing entry keeps the default. Each stage dict
    carries ``label``, ``engine``, ``ncount``, ``points`` and ``force_rebuild``.
    """
    low = DEFAULT_LOW_NCOUNT
    if ncounts:
        seq = list(ncounts)
        if len(seq) >= 1 and seq[0]:
            low = int(seq[0])

    plan: List[Dict] = [
        {
            "label": "mcstas cold (compile)",
            "engine": "mcstas",
            "ncount": low,
            "points": 3,
            "force_rebuild": True,
        },
        {
            "label": "mcstas warm",
            "engine": "mcstas",
            "ncount": low,
            "points": 5,
            "force_rebuild": False,
        },
    ]
    if deterministic_supported:
        plan.append({
            "label": "deterministic",
            "engine": "deterministic",
            "ncount": DEFAULT_DETERMINISTIC_NCOUNT,
            "points": 20,
            "force_rebuild": False,
        })
    return plan


def next_rate_stage(overhead_s: Optional[float],
                    last_ncount: Optional[float],
                    last_spp: Optional[float],
                    elapsed_adaptive_s: float,
                    budget_s: float = DEFAULT_ADAPTIVE_BUDGET_S,
                    target_ratio: float = DEFAULT_ADAPTIVE_TARGET_RATIO,
                    start_ncount: int = DEFAULT_ADAPTIVE_START_NCOUNT,
                    max_ncount: int = DEFAULT_ADAPTIVE_MAX_NCOUNT
                    ) -> Optional[Dict]:
    """Return the next adaptive rate-benchmark stage, or ``None`` to stop.

    The adaptive phase measures the per-neutron rate by escalating the neutron
    count until the warm per-point time carries enough rate signal to separate
    slope from overhead. It is a pure function of the last stage's measurement:

    - ``overhead_s``: warm per-point time at the low ncount (pure overhead).
    - ``last_ncount`` / ``last_spp``: the previous stage's ncount and measured
      warm per-point seconds. On the first adaptive call these are the base warm
      stage's (``last_ncount < start_ncount``), so the sweep jumps straight to
      ``start_ncount``; later stages escalate x``ADAPTIVE_ESCALATION``.
    - ``elapsed_adaptive_s``: wall-clock already spent in the adaptive phase.

    Stop rules (return ``None``):
      1. ``last_spp >= target_ratio * overhead_s`` -- the last stage already
         stands clear of overhead, so an affine fit has a lever arm.
      2. The next ncount would exceed ``max_ncount``.
      3. The projected next-stage cost (``ADAPTIVE_STAGE_POINTS * last_spp *
         ADAPTIVE_ESCALATION``, i.e. the per-point time grown by the escalation
         factor over the stage's points) would overflow the remaining budget.

    Otherwise returns a stage dict (``label``, ``engine``, ``ncount``,
    ``points``, ``force_rebuild``).
    """
    # Rule 1: enough rate signal already -> stop.
    if (overhead_s is not None and overhead_s > 0
            and last_spp is not None
            and last_spp >= target_ratio * overhead_s):
        return None

    # First adaptive stage jumps to start_ncount; later stages escalate x10.
    if last_ncount is None or last_ncount < start_ncount:
        next_ncount = int(start_ncount)
    else:
        next_ncount = int(last_ncount) * ADAPTIVE_ESCALATION

    # Rule 2: ncount ceiling.
    if next_ncount > max_ncount:
        return None

    # Rule 3: budget guard. A ~x10 ncount step costs ~x10 the per-point time,
    # spread over the stage's points; stop if that overflows what remains.
    if last_spp is not None and last_spp > 0:
        remaining = budget_s - (elapsed_adaptive_s or 0.0)
        projected = ADAPTIVE_STAGE_POINTS * last_spp * ADAPTIVE_ESCALATION
        if projected > remaining:
            return None

    return {
        "label": f"mcstas rate ({next_ncount:g})",
        "engine": "mcstas",
        "ncount": next_ncount,
        "points": ADAPTIVE_STAGE_POINTS,
        "force_rebuild": False,
    }


def drift_percent(measured: Optional[float],
                  predicted: Optional[float]) -> Optional[float]:
    """Signed percent drift of ``measured`` from ``predicted``.

    ``(measured - predicted) / predicted * 100``. Returns ``None`` when either
    value is missing or ``predicted`` is zero (no baseline to drift from).
    """
    if measured is None or predicted is None or predicted == 0:
        return None
    return (measured - predicted) / predicted * 100.0


def crosscheck_rows(stage_results: Sequence[Dict]) -> List[Dict]:
    """Build cross-check rows from ``{label, measured, predicted}`` dicts.

    Each output row adds ``drift_pct`` (see :func:`drift_percent`). Preserves
    input order so the dialog table lines up with the plan.
    """
    rows: List[Dict] = []
    for s in stage_results:
        measured = s.get("measured")
        predicted = s.get("predicted")
        rows.append({
            "label": s.get("label"),
            "measured": measured,
            "predicted": predicted,
            "drift_pct": drift_percent(measured, predicted),
        })
    return rows
