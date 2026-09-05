"""Build the Pb ``Phonon_DFT`` assets from the collaborator's DFT phonon grid.

Input ``pb_pdisp_3d_nq50`` (repo root, gitignored, not redistributable yet):
``nq**3`` rows of ``index om1 om2 om3`` (meV, sorted per row), looped as
``x`` outer, ``y``, ``z`` inner, each over ``0, 1/nq, ..., 1-1/nq``.  These are
internal coordinates of the primitive reciprocal basis, ``q = x*b1 + y*b2 + z*b3``
with ``b1=(-1,1,1)``, ``b2=(1,-1,1)``, ``b3=(1,1,-1)`` in conventional rlu.

Outputs (``components/``):

* ``Pb_dft_phonons.dat`` -- the shared ``Phonon_DFT`` map on the conventional
  ``(H,K,L)`` cube ``[-1,1]^3`` with step ``2/nq``.  Every conventional node
  maps exactly onto a DFT node (``x=(K+L)/2`` etc.), so no interpolation is
  done.  Gitignored with its source.
* ``Pb_Fm-3m.laz`` -- the Bragg reflection table (public constants only, so
  it is committed).

Run from the repo root: ``python tools/make_pb_assets.py``.  The self-check at
the end asserts the fcc zone centres and the period-2 wrap.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pb_pdisp_3d_nq50"
MAP_OUT = ROOT / "components" / "Pb_dft_phonons.dat"
LAZ_OUT = ROOT / "components" / "Pb_Fm-3m.laz"

NQ = 50
LATTICE_A = 4.9508      # Angstrom, room-temperature Pb; the DFT value is not known
B_COH_FM = 9.405        # fm, Pb coherent scattering length
HKL_MAX = 8

# Conventional (H,K,L) -> primitive internal (x,y,z); inverse of the b1,b2,b3 matrix.
_CONVENTIONAL_TO_INTERNAL = 0.5 * np.array([[0, 1, 1], [1, 0, 1], [1, 1, 0]], dtype=float)


def load_dft_grid(path: Path = SOURCE) -> np.ndarray:
    """Return the DFT frequencies as ``(NQ, NQ, NQ, 3)`` indexed ``[ix, iy, iz]``."""
    data = np.loadtxt(path)
    if data.shape != (NQ**3, 4):
        raise ValueError(f"{path}: expected {NQ**3} rows of 4 columns, got {data.shape}")
    return data[:, 1:].reshape(NQ, NQ, NQ, 3)


def resample_conventional(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map the DFT grid onto conventional ``[-1,1]^3`` nodes (step ``2/NQ``), no interpolation."""
    axis = np.linspace(-1.0, 1.0, NQ + 1)
    H, K, L = np.meshgrid(axis, axis, axis, indexing="ij")
    hkl = np.stack([H, K, L], axis=-1)
    internal = hkl @ _CONVENTIONAL_TO_INTERNAL.T * NQ      # node index, possibly negative
    nodes = np.rint(internal)
    if not np.allclose(internal, nodes, atol=1e-9):
        raise ValueError("conventional grid does not land on DFT nodes; keep step = 2/NQ")
    ix, iy, iz = (nodes[..., d].astype(int) % NQ for d in range(3))
    # ponytail: step 2/NQ lands on every other DFT node per axis (1 in 8 overall); the DFT
    # nodes at odd multiples of 0.02 rlu (e.g. the L point (.5,.5,.5)) are then linearly
    # interpolated by the consumers. Step 1/NQ would use every node at 3.1M rows.
    energies = grid[ix, iy, iz]
    # DFT noise near Gamma gives a few |E| < 0.07 meV negatives; the map convention is E >= 0.
    energies = np.where(energies < 0.0, 0.0, energies) + 0.0   # + 0.0 turns -0.0 into 0.0
    return axis, energies


def write_map(axis: np.ndarray, energies: np.ndarray, path: Path = MAP_OUT) -> None:
    n = len(axis)
    branches = energies.shape[-1]
    H, K, L, B = np.meshgrid(axis, axis, axis, np.arange(branches), indexing="ij")
    rows = np.column_stack([
        H.ravel(), K.ravel(), L.ravel(), energies.ravel(),
        np.ones(H.size), B.ravel(),
    ])
    header = "\n".join([
        "Pb phonon dispersion for Phonon_DFT, resampled from a collaborator's DFT grid",
        f"Source: {SOURCE.name} (50^3 primitive-reciprocal grid, 3 branches, meV); not redistributable yet",
        "Resampling: conventional (H,K,L) nodes on [-1,1] step 0.04 land exactly on DFT nodes via",
        "  x=(K+L)/2, y=(H+L)/2, z=(H+K)/2 for b1=(-1,1,1), b2=(1,-1,1), b3=(1,1,-1); no interpolation,",
        "  one DFT node in eight is used (the source is twice as fine along each primitive axis)",
        "Intensity: 1.0 on every mode (the source carries no eigenvectors or structure factors)",
        "Negative DFT frequencies (|E| < 0.07 meV, numerical, near Gamma) clamped to 0",
        f"lattice_a {LATTICE_A}",
        f"grid_nx {n}",
        f"grid_ny {n}",
        f"grid_nz {n}",
        f"num_branches {branches}",
        "Columns: H(rlu) K(rlu) L(rlu) E(meV) Intensity Branch",
    ])
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        np.savetxt(handle, rows, fmt=["%.6f", "%.6f", "%.6f", "%.6f", "%.6f", "%d"],
                   header=header, comments="# ")


def write_laz(path: Path = LAZ_OUT) -> int:
    """Write the fcc Pb reflection table (all-even or all-odd hkl, |hkl| <= HKL_MAX)."""
    f2_barn = (4.0 * B_COH_FM) ** 2 / 100.0      # fm^2 -> barn
    reflections = [
        (h, k, l)
        for h in range(-HKL_MAX, HKL_MAX + 1)
        for k in range(-HKL_MAX, HKL_MAX + 1)
        for l in range(-HKL_MAX, HKL_MAX + 1)
        if (h, k, l) != (0, 0, 0) and len({h % 2, k % 2, l % 2}) == 1
    ]
    reflections.sort(key=lambda hkl: (sum(v * v for v in hkl), hkl))
    lines = [
        "# TITLE Pb-FCC (Fm-3m), reflection table from tabulated constants",
        f"# CELL {LATTICE_A} {LATTICE_A} {LATTICE_A} 90.000000 90.000000 90.000000",
        "# SPCGRP F M -3 M   CUBIC STRUCTURE",
        "# ATOM PB 1 0.000000 0.000000 0.000000",
        "#",
        "# Physical parameters:",
        "# sigma_coh 11.115  coherent scattering cross section (single atom) in [barn]",
        "# sigma_inc 0.003   incoherent scattering cross section (single atom) in [barn]",
        "# sigma_abs 0.171   absorption scattering cross section (single atom) in [barn]",
        "# density   11.35   in [g/cm^3]",
        "# weight    207.2   in [g/mol] (single atom)",
        "# multiplicity 4    in [atoms/unit cell]",
        f"# Vc        {LATTICE_A**3:.2f}  volume of unit cell in [A^3]",
        f"# lattice_a {LATTICE_A}",
        f"# lattice_b {LATTICE_A}",
        f"# lattice_c {LATTICE_A}",
        "#",
        "# Format parameters:",
        "# column_h  1",
        "# column_k  2",
        "# column_l  3",
        "# column_F2 4       norm of scattering factor |F|^2 in [barn]",
        "# column_d  5       d-spacing in [Angs]",
        "#",
        "# Generated by tools/make_pb_assets.py",
        "# FCC selection rule: h,k,l all even or all odd",
        f"# b_coh(Pb) = {B_COH_FM} fm, F(hkl) = 4*b = {4 * B_COH_FM:.3f} fm, F2 = {f2_barn:.6f} barn",
        "#",
        "# h   k   l   F2[barn]   d[Angs]",
    ]
    for h, k, l in reflections:
        d = LATTICE_A / np.sqrt(h * h + k * k + l * l)
        lines.append(f"{h:4d} {k:4d} {l:4d}   {f2_barn:.6f}   {d:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(reflections)


def main() -> None:
    grid = load_dft_grid()
    axis, energies = resample_conventional(grid)
    write_map(axis, energies)
    n_refl = write_laz()

    # Self-check: fcc zone centres, X point, period-2 wrap, cubic symmetry.
    at = {value: index for index, value in enumerate(np.round(axis, 6))}
    gamma = energies[at[0.0], at[0.0], at[0.0]]
    zone_111 = energies[at[1.0], at[1.0], at[1.0]]
    x_point = energies[at[1.0], at[0.0], at[0.0]]
    assert np.all(gamma == 0.0), gamma
    assert np.all(zone_111 == 0.0), zone_111          # the Al toy puts its maximum here
    assert np.allclose(x_point, grid[0, 25, 25]), x_point
    assert np.array_equal(energies[0], energies[-1])   # H=-1 and H=+1 coincide (period 2)
    assert np.array_equal(energies, np.transpose(energies, (1, 0, 2, 3)))
    assert np.array_equal(energies, np.transpose(energies, (2, 1, 0, 3)))
    assert n_refl == 1240, n_refl
    print(f"wrote {MAP_OUT.name}: grid {energies.shape[:3]}, {energies.shape[-1]} branches, "
          f"E max {energies.max():.3f} meV; X point {np.round(x_point, 3)}")
    print(f"wrote {LAZ_OUT.name}: {n_refl} reflections")


if __name__ == "__main__":
    main()
