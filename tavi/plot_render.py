"""Off-thread PNG rendering of a scan job's stored result arrays.

Pure Python + matplotlib **Agg**, **no Qt imports**. This is the render path for
``GET /api/v1/scan/{id}/plot.png``: the API backend hands it the JSON-safe
result dict (from ``ScanResult.to_dict(include_data=True)``) and gets back raw
PNG bytes, rendered in the HTTP handler thread.

Design notes
------------
- We import ``matplotlib.figure.Figure`` and
  ``matplotlib.backends.backend_agg.FigureCanvasAgg`` directly and never touch
  the ``pyplot`` state machine or call ``matplotlib.use()``. Creating a
  ``Figure`` with an explicit ``FigureCanvasAgg`` is fully independent of the
  process-wide backend, so this is thread-safe and -- crucially -- does **not**
  rebind the GUI's live Qt matplotlib backend when imported into the running
  application. (Calling ``matplotlib.use("Agg")`` at import time *would* clobber
  the GUI backend, so we deliberately do not; the Agg canvas is selected
  per-figure instead.) See the task notes and ``docs/API_USER_GUIDE.md``.
- Images are exactly 512x512 px (figsize 5.12x5.12 at dpi 100).
"""
import io
import math

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg


# Exact output geometry: 5.12 in * 100 dpi = 512 px on each side.
_FIGSIZE = (5.12, 5.12)
_DPI = 100


class NoPlotData(Exception):
    """Raised when a job has no renderable data yet (maps to HTTP 409 no_data)."""


def _finite(value):
    """True if ``value`` is a real, finite number (not None / NaN / inf)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def render_scan_plot_png(result, job_id):
    """Render ``result`` (a JSON-safe scan-result dict) to PNG bytes.

    ``result`` is the dict produced by ``ScanResult.to_dict(include_data=True)``.
    Raises ``NoPlotData`` when there is nothing measurable to draw (no result,
    or every count is missing/invalid). Returns ``bytes`` of a 512x512 PNG.
    """
    if not result:
        raise NoPlotData("job has no result data yet")

    mode = result.get("mode")
    fig = Figure(figsize=_FIGSIZE, dpi=_DPI)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)

    var1 = result.get("variable_1") or "scan"
    if mode == "2D":
        _render_2d(fig, ax, result, job_id, var1)
    else:
        _render_1d(ax, result, job_id, var1)

    fig.tight_layout()
    buf = io.BytesIO()
    canvas.print_png(buf)
    return buf.getvalue()


def _render_1d(ax, result, job_id, var1):
    """Errorbar plot (sqrt-counts uncertainty), markers + connecting line."""
    xs = result.get("scan_values_1") or []
    ys = result.get("counts") or []
    px, py = [], []
    for x, y in zip(xs, ys):
        if _finite(x) and _finite(y):
            px.append(float(x))
            py.append(float(y))
    if not px:
        raise NoPlotData("no measured points to plot")

    yerr = [math.sqrt(v) if v > 0 else 0.0 for v in py]
    ax.errorbar(px, py, yerr=yerr, fmt="o-", capsize=3)
    ax.set_xlabel(var1)
    ax.set_ylabel("counts")
    ax.set_title("%s — %s scan" % (job_id, var1))


def _render_2d(fig, ax, result, job_id, var1):
    """Heatmap (pcolormesh) with a colorbar; missing points render blank."""
    xs = result.get("scan_values_1") or []
    ys = result.get("scan_values_2") or []
    grid = result.get("counts_grid") or []
    var2 = result.get("variable_2") or "scan2"

    if not xs or not ys or not grid:
        raise NoPlotData("no measured points to plot")

    # counts_grid is indexed [row=y][col=x] -> shape (len(ys), len(xs)); None
    # (unmeasured/invalid) becomes NaN so it shows as a blank cell.
    z = np.array(
        [[np.nan if not _finite(c) else float(c) for c in row] for row in grid],
        dtype=float,
    )
    if not np.isfinite(z).any():
        raise NoPlotData("no measured points to plot")

    x = np.array([float(v) for v in xs], dtype=float)
    y = np.array([float(v) for v in ys], dtype=float)
    mesh = ax.pcolormesh(x, y, z, shading="auto")
    fig.colorbar(mesh, ax=ax, label="counts")
    ax.set_xlabel(var1)
    ax.set_ylabel(var2)
    ax.set_title("%s — %s/%s scan" % (job_id, var1, var2))
