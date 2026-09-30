"""Manual McStas gate: does a solved tilted setting really put the reflection in the beam?

The unit tests compose McStas's rotation rule themselves; only a real McStas
run can falsify that understanding. This tool is that run. It is manual and
never collected by pytest (it lives outside ``tests/``). Run it from the
repository root in the tavi-dev environment:

    micromamba run -n tavi-dev python tools/check_tilted_reflection.py
    micromamba run -n tavi-dev python tools/check_tilted_reflection.py --dry-run

Setup: IN8 (sample sense +1), the ``Al_bragg`` Single_crystal sample (cubic
Al, 4.05 A), kf fixed at 2.662 1/A, elastic, flat crystals, open collimation.
The crystal is turned 45 deg about the vertical and tilted 4 deg out of the
plane about the horizontal axis n = (sin 45, 0, cos 45), so (2,0,0) sits 4 deg
above the plane at 45 deg azimuth on the stage and levelling it needs both
arcs (about 2.8 deg each). The operator's UB is the truth. The setting is
solved through the real runtime (``calculate_stage_angles`` ->
``tavi.orientation.solve_stage``); the scans go through IN8's own
``scan_config``, ``build``, ``compute_snapshot`` (angle mode, arcs from
``sgl``/``sgu``) and ``run_point``, exactly the path the application uses.

Scans: 13 A3 points around the predicted A3 at the solved arcs, then the same
13 points with both arcs at zero. Counts are the detector's N; errors are
Poisson (sqrt N); McStas's weighted I +/- I_err is printed beside them.

Pass (plan item 1.6 with amendment A8), all three:
  1. |fitted centre - predicted A3| <= 0.1 deg. The centre is the Fitting
     dock's fit (``tavi.scan_fits.fit_peak``: pseudo-Voigt plus flat
     background); centre of mass when that fit does not converge. Printed.
  2. the tilted scan's maximum >= 10 x the arcs-zeroed scan's maximum;
  3. the tilted maximum stands >= 5 sigma above its own tails (the three
     outermost points on each side), sigma = sqrt(N_max + var(tail mean)).
Exit code 0 on PASS, 1 on FAIL, 2 when the runs themselves failed.

Windows hygiene: the repository conftest's CREATE_NO_WINDOW guard is
installed before McStasScript is imported, NoDefaultCurrentDirectoryInExePath
is removed from the environment before any child starts (mcrun launches the
compiled binary by bare name), and MCSTAS is set as conftest sets it. All
output -- the compiled instrument, every point folder, TAVI's local state --
lands in a temporary directory printed at the start: the tool runs on a copy
of ``instruments/``, ``tavi/``, ``components/`` and ``config/`` there. As on
every TAVI start, importing ``tavi.mcstas_config`` re-applies the detected
McStas paths to McStasScript's own configuration.
"""
import argparse
import copy
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
POINTS = 13
HKL = (2.0, 0.0, 0.0)
KF = 2.662
IN8_VALS = {
    "K_fixed": "Kf Fixed", "source_type": "Maxwellian", "source_dE": 2.0,
    "rhm": 0.0, "rvm": 0.0, "rha": 0.0, "rva": 0.0,
    "monocris": "pg002", "anacris": "pg002", "modules": {},
    "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "0", "alpha_4": "0"},
    "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
    "deltaE": 0.0, "chi": 0.0,
}


def _hygiene():
    """The conftest guards, reused from the repository root, before McStasScript."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        import conftest
    finally:
        sys.path.remove(str(REPO_ROOT))
    conftest.install_no_window_guard()
    # mcrun starts the compiled instrument by bare name; with this variable
    # set, Windows will not look in the current directory for it.
    os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)
    if "MCSTAS" not in os.environ:
        resources = conftest._resolve_mcstas_resources()
        if resources:
            os.environ["MCSTAS"] = resources


def _sandbox():
    """Copy the code and data the run needs into a temporary root."""
    root = Path(tempfile.mkdtemp(prefix="tavi-tilted-reflection-"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "Pb_dft_phonons.dat",
                                    "*_McScript*")
    for name in ("instruments", "tavi", "components", "config"):
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(source, root / name, ignore=ignore)
    os.environ["TAVI_CONFIG_DIR"] = str(root / "config")
    return root


def _rot(axis, deg):
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k)


def _significance(counts):
    tails = np.concatenate([counts[:3], counts[-3:]])
    tail_mean = float(np.mean(tails))
    tail_var = float(np.sum(tails)) / len(tails) ** 2     # Poisson variance of the mean
    peak = float(np.max(counts))
    sigma = math.sqrt(max(peak, 1.0) + tail_var)
    return (peak - tail_mean) / sigma, tail_mean


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the solved setting and the planned points; run nothing")
    parser.add_argument("--ncount", type=float, default=1e6,
                        help="neutrons per point (default 1e6)")
    parser.add_argument("--mpi", type=int, default=4, help="MPI processes (default 4)")
    parser.add_argument("--step", type=float, default=0.2,
                        help="A3 step in degrees (default 0.2)")
    args = parser.parse_args()

    _hygiene()
    root = REPO_ROOT if args.dry_run else _sandbox()
    sys.path.insert(0, str(root))
    if not args.dry_run:
        print(f"Output directory: {root}")

    from instruments.contract import RunExecutionState
    from instruments.in8.plugin import IN8Plugin
    from tavi.data_processing import read_1Ddetector_file
    from tavi.neutron_conversions import k2energy
    from tavi.sample_mount import SampleMount
    from tavi.scan_fits import com, fit_peak
    from tavi.tas_geometry import component_q_to_instrument_q

    fixed_e = k2energy(KF)
    u_true = _rot((1, 0, 1), 4.0) @ _rot((0, 1, 0), 45.0)
    mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90, R_mount=u_true)
    plugin = IN8Plugin()
    vals = dict(IN8_VALS, fixed_E=fixed_e)
    config = plugin.scan_config(plugin.default_state(), vals, "Al_bragg", {}, mount)

    q = component_q_to_instrument_q(np.array(mount.hkl_to_q(*HKL)))
    angles, flags = copy.deepcopy(config).calculate_stage_angles(
        *q, 0.0, fixed_e, "Kf Fixed", "pg002", "pg002")
    if flags:
        print(f"Setup error: the stage solve refused (2,0,0): {flags}")
        return 2
    mtt, stt, a3, sgl, att, sgu = angles
    elevation = math.degrees(math.asin(mount.hkl_to_q(*HKL)[1] / np.linalg.norm(q)))
    print(f"IN8, sense {config.sense_sample:+d}, Al_bragg, kf = {KF} 1/A, (2,0,0), "
          f"|Q| = {np.linalg.norm(q):.4f} 1/A, {elevation:.3f} deg above the plane")
    print(f"Solved setting (readouts): A1 = {mtt:.4f}  A2 = {stt:.4f}  A3 = {a3:.4f}  "
          f"A4 = {att:.4f}  sgl = {sgl:.4f}  sgu = {sgu:.4f}")
    if min(abs(sgl), abs(sgu)) < 0.5:
        print("Setup error: the misorientation does not need both arcs.")
        return 2
    a3_points = a3 + args.step * (np.arange(POINTS) - POINTS // 2)
    scans = {"tilted": (sgl, sgu), "arcs zeroed": (0.0, 0.0)}
    print(f"Planned: {POINTS} points per scan, A3 = "
          + ", ".join(f"{v:.3f}" for v in a3_points))
    for label, (arc_l, arc_u) in scans.items():
        snapshot = plugin.compute_snapshot(
            ([mtt, stt, a3, att, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0), 0, "angle",
            config, dict(vals, sgl=arc_l, sgu=arc_u), str(root / "plan"))
        p = snapshot.params
        print(f"  {label:12s} sgl = {arc_l:8.4f}  sgu = {arc_u:8.4f}  centre-point sample arm "
              f"ROTATED = ({p['sample_rx_param']:.4f}, {p['sample_ry_param']:.4f}, "
              f"{p['sample_rz_param']:.4f})")
    if args.dry_run:
        print(f"Dry run: nothing launched. A full run is {2 * POINTS} points of "
              f"{args.ncount:.3g} neutrons on {args.mpi} MPI processes.")
        return 0

    ncount = int(args.ncount)
    instrument = plugin.build(config, False, {}, ncount)
    execution = RunExecutionState()
    results = {}
    for label, (arc_l, arc_u) in scans.items():
        print(f"\n{label} scan (sgl = {arc_l:.4f}, sgu = {arc_u:.4f})")
        print(f"  {'A3':>9s} {'N':>9s} {'sqrt(N)':>8s} {'I':>11s} {'I_err':>11s} {'s':>6s}")
        counts = []
        folder = root / label.replace(" ", "_")
        folder.mkdir(parents=True, exist_ok=True)   # McStasScript needs the parent to exist
        for index, a3_value in enumerate(a3_points):
            snapshot = plugin.compute_snapshot(
                ([mtt, stt, float(a3_value), att, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], index),
                index, "angle", config, dict(vals, sgl=arc_l, sgu=arc_u), str(folder))
            started = time.perf_counter()
            _data, run_flags, info = plugin.run_point(
                instrument, snapshot, snapshot.output_folder, ncount, execution,
                mpi_count=args.mpi)
            intensity, error, n = read_1Ddetector_file(snapshot.output_folder)
            if run_flags or n is None:
                print(f"Run failed at A3 = {a3_value:.3f}: flags {run_flags}, "
                      f"{info.get('error_message')}\n{info.get('stdout') or ''}")
                return 2
            counts.append(n)
            print(f"  {a3_value:9.3f} {n:9.0f} {math.sqrt(n):8.1f} {intensity:11.4g} "
                  f"{error:11.4g} {time.perf_counter() - started:6.1f}")
        results[label] = np.array(counts, dtype=float)

    tilted, zeroed = results["tilted"], results["arcs zeroed"]
    fit = fit_peak(a3_points, tilted)
    if fit.converged:
        centre, method = fit.center, (f"pseudo-Voigt fit (fwhm {fit.fwhm:.3f} deg, "
                                      f"centre +/- {fit.center_err or float('nan'):.3f})")
    else:
        estimate = com(a3_points, tilted)
        centre, method = estimate.x, f"centre of mass (fit did not converge: {fit.reason})"
        if centre is None:
            print(f"\nFAIL: no centre (fit: {fit.reason}; centre of mass: {estimate.reason})"
                  f" (output in {root})")
            return 1
    sigmas, tail_mean = _significance(tilted)
    checks = [
        (f"|centre - predicted| = |{centre:.4f} - {a3:.4f}| = {abs(centre - a3):.4f} deg "
         f"<= 0.1 deg", abs(centre - a3) <= 0.1),
        (f"tilted max {tilted.max():.0f} >= 10 x arcs-zeroed max {zeroed.max():.0f}",
         tilted.max() >= 10.0 * zeroed.max()),
        (f"tilted max stands {sigmas:.1f} sigma above its tails (mean {tail_mean:.1f}) >= 5",
         sigmas >= 5.0),
    ]
    print(f"\nCentre by {method}: {centre:.4f} deg; predicted A3 {a3:.4f} deg")
    for text, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    passed = all(ok for _, ok in checks)
    print(f"\n{'PASS' if passed else 'FAIL'} (output in {root})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
