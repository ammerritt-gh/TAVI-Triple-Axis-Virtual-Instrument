"""Pure benchmark-plan and cross-check logic for the scan-time benchmarker.

Qt-free by design: the controller orchestration (TAVI_PySide6.py) and the GUI
dialog (gui/dialogs/benchmark_dialog.py) both delegate the plan shape and the
drift math here so the logic stays headless-testable. The controller owns the
job-queue wiring; this module owns only data.

The benchmarker gives a fresh machine a clean speed baseline: a short, fixed
sweep of tiny scans around the current GUI position whose measured timings feed
``machine_speed_index`` and the per-machine estimate. See section 4 of the
scan-time rework plan.
"""
from typing import Dict, List, Optional, Sequence

# Default mcstas ncounts: a low count (compile + warm samples) and a higher
# count (per-neutron scaling sample). Overridable via ``build_benchmark_plan``.
DEFAULT_LOW_NCOUNT = 10000     # 1e4
DEFAULT_HIGH_NCOUNT = 100000   # 1e5

# Deterministic stage neutron count is nominal only: the analytic engine's cost
# is ~independent of ncount, so this value just travels with the record.
DEFAULT_DETERMINISTIC_NCOUNT = 100000

# The dialog highlights a cross-check row whose |drift| exceeds this percentage.
DRIFT_HIGHLIGHT_THRESHOLD = 30.0


def build_benchmark_plan(ncounts: Optional[Sequence[int]] = None,
                         deterministic_supported: bool = True) -> List[Dict]:
    """Return the ordered benchmark stage plan.

    Stages (defaults):
      1. mcstas, low ncount, 3 points, force rebuild -> compile + cold cost.
      2. mcstas, low ncount, 5 points, reuse binary  -> warm per-point cost.
      3. mcstas, high ncount, 5 points, reuse binary -> per-neutron scaling.
      4. deterministic, 20 points (only when ``deterministic_supported``).

    ``ncounts`` overrides the mcstas ncounts as ``(low, high)``; a falsy or
    missing entry keeps the corresponding default. Each stage dict carries
    ``label``, ``engine``, ``ncount``, ``points`` and ``force_rebuild``.
    """
    low = DEFAULT_LOW_NCOUNT
    high = DEFAULT_HIGH_NCOUNT
    if ncounts:
        seq = list(ncounts)
        if len(seq) >= 1 and seq[0]:
            low = int(seq[0])
        if len(seq) >= 2 and seq[1]:
            high = int(seq[1])

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
        {
            "label": "mcstas warm (scaling)",
            "engine": "mcstas",
            "ncount": high,
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
