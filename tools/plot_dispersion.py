"""Plot a ``Phonon_DFT`` map along the fcc high-symmetry path G-X-W-K-G-L.

Evaluates the shared map exactly as the analytic engine does (trilinear,
tessellated) and draws every branch; a second map may be overlaid dashed for
comparison. Run from the repo root::

    python tools/plot_dispersion.py                  # Pb DFT with the Al toy overlaid
    python tools/plot_dispersion.py --no-overlay     # Pb alone
    python tools/plot_dispersion.py --map components/Al_test_phonons_centered.dat --no-overlay

The figure lands in ``output/plots/`` and the path is printed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tavi.dispersion_map import load_dispersion_map  # noqa: E402

DEFAULT_MAP = ROOT / "components" / "Pb_dft_phonons.dat"
DEFAULT_OVERLAY = ROOT / "components" / "Al_test_phonons_centered.dat"
OUT_DIR = ROOT / "output" / "plots"

# Conventional-rlu coordinates of the fcc special points.
FCC_PATH = [
    ("Γ", (0.0, 0.0, 0.0)),
    ("X", (1.0, 0.0, 0.0)),
    ("W", (1.0, 0.5, 0.0)),
    ("K", (0.75, 0.75, 0.0)),
    ("Γ", (0.0, 0.0, 0.0)),
    ("L", (0.5, 0.5, 0.5)),
]
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
POINTS_PER_SEGMENT = 200


def path_energies(dispersion, path=FCC_PATH, n=POINTS_PER_SEGMENT):
    """Return (distance_rlu, energies[point, branch], tick_positions)."""
    distance, energies, ticks = [], [], [0.0]
    s = 0.0
    for (_, start), (_, end) in zip(path, path[1:]):
        start, end = np.asarray(start), np.asarray(end)
        length = float(np.linalg.norm(end - start))
        for t in np.linspace(0.0, 1.0, n, endpoint=False):
            hkl = start + t * (end - start)
            distance.append(s + t * length)
            energies.append([m.energy_mev for m in dispersion.evaluate(hkl, tessellate=True)])
        s += length
        ticks.append(s)
    last = np.asarray(path[-1][1])
    distance.append(s)
    energies.append([m.energy_mev for m in dispersion.evaluate(last, tessellate=True)])
    return np.asarray(distance), np.asarray(energies), ticks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    primary = load_dispersion_map(args.map)
    x, e, ticks = path_energies(primary)
    labels = [name for name, _ in FCC_PATH]

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    for b in range(primary.branch_count):
        ax.plot(x, e[:, b], color=SERIES[b % len(SERIES)], lw=2,
                label=f"{args.map.stem}: branch {b + 1}")
    if not args.no_overlay:
        overlay = load_dispersion_map(args.overlay)
        xo, eo, _ = path_energies(overlay)
        for b in range(overlay.branch_count):
            ax.plot(xo, eo[:, b], color="#8a8a86", lw=1.2, ls="--",
                    label=f"{args.overlay.stem}: branch {b + 1}")

    for tick in ticks[1:-1]:
        ax.axvline(tick, color="#d5d4cf", lw=0.8, zorder=0)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.set_xlim(ticks[0], ticks[-1])
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Energy (meV)")
    ax.set_title(f"{args.map.name} along Γ–X–W–K–Γ–L")
    ax.grid(axis="y", color="#e6e5e0", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper center",
              bbox_to_anchor=(0.5, -0.08), ncol=3)
    fig.tight_layout()

    out = args.out or OUT_DIR / f"{args.map.stem}_dispersion.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
