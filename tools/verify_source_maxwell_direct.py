"""Manual McStas gate: does Source_Maxwell_direct emit Source_gen's spectrum with one weight?

The component samples the Source_gen flux spectrum directly in energy and gives
every ray the same weight. Only a real McStas run can show that. This tool is
that run. It is manual and never collected by pytest (it lives outside
``tests/``). Run it from the repository root in the tavi-dev environment, and
run it before any change to ``components/Source_Maxwell_direct.comp`` ships:

    micromamba run -n tavi-dev python tools/verify_source_maxwell_direct.py

It compiles ``Test_Source_Maxwell_direct.instr`` once with ``mcrun`` into a
scratch folder, runs the executable many times in parallel (no MPI, fixed
seeds, a timeout that kills and reports), and reads the monitors' ``I``,
``I_err`` and ``N`` arrays. Seven checks, each with its negative control where
a check could silently be unable to fail:

  1. Spectrum equals Source_gen's, for each of the 12 facility rows and the
     single-temperature entry, in both the wavelength and the energy monitor.
     Pull per bin z = (I_direct - I_gen) / sqrt(s_direct^2 + s_gen^2) over the
     bins wholly inside Source_gen's [Lmin, Lmax] where both N >= 20;
     chi2 = sum z^2 must lie in n +- 4 sqrt(2 n). A test with fewer than 50 such
     bins raises its ray count and reruns once, then fails; the band is never
     widened and no test is skipped. Control: the FRM2 thermal row with I2
     doubled must fail the band.
  2. Absolute total in [Lmin, Lmax] equals the analytic sum of I_i * (Gamma(2)
     mass in range) * 1e4 * xwidth * yheight * Omega, within 4 sigma.
  3. One weight: I/N equals the predicted weight to 1e-4 in every non-empty bin
     of every monitor, and I_err^2 N = I^2. Control: Source_gen's own output
     (weights vary) must fail.
  4. Full spectrum ignores E0 and dE: identical monitor arrays for different
     E0 and dE. Control: a different seed must differ.
  5. Flat band: counts only inside [E0-dE, E0+dE], level = flux * 1e4 * area *
     Omega per meV, uniform in energy.
  6. Refusals: bad input stops the run with a message naming the parameter;
     the same values are accepted where the mode does not read them.
  7. Uniform per steradian: a 60 x 120 deg window fills the divergence
     monitor. McStas's Divergence_monitor measures the vertical angle as
     atan2(vy, vz), not the latitude asin(vy/v) the source draws uniformly, so
     the exact expectation for that variable is derived (see ``_cdf_vertical``).
     Controls: the same data must fail the sampler-uniform-in-angle and the
     sampler-uniform-in-latitude expectations.

The report goes to ``output/source_verification/<timestamp>/report.md`` (the
folder is gitignored); its path is printed; the exit code is non-zero on any
failure. About 18 s on a 16-core machine (the recorded run).
"""
from __future__ import annotations

import datetime
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
COMP = REPO / "components" / "Source_Maxwell_direct.comp"
INSTR = (REPO / "components" / "examples" / "Tests_sources"
         / "Test_Source_Maxwell_direct" / "Test_Source_Maxwell_direct.instr")
OUT_ROOT = REPO / "output" / "source_verification"

# Windows gives a child of a console-less parent its own console window.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

RUN_TIMEOUT = 300       # s, one McStas run (a hung run is killed and reported)
COMPILE_TIMEOUT = 300   # s
TOTAL_TIMEOUT = 900     # s, the whole tool
ROW_RAYS = 20_000_000   # spectrum comparison, one run per facility row and source
BASE_RAYS = 5_000_000   # flat band and wide window
RAISED_FACTOR = 4       # ray multiplier for a test that finds fewer than 50 bins
MIN_BINS = 50
MIN_COUNT = 20
SEED_DIRECT, SEED_GEN, SEED_OTHER = 1000, 2000, 3000

# McStas mcstas-r.h: VS2E, K2V (= AA2MS). C converts E = C / L^2 (meV, Angstrom).
VS2E = 5.22703725e-6
K2V = 629.622368
C_E = VS2E * K2V ** 2 * 4 * math.pi ** 2
XW = YH = 0.05          # the test instrument fixes the source rectangle (m)
ONE_WEIGHT_TOL = 1e-4   # McStas prints about ten significant digits per bin
MONITORS = ("L_mon", "E_mon", "PSD_mon", "Div_mon")
MON_BINS = 500          # bins of the L and E monitors in the spectrum comparison


# ---------------------------------------------------------------- environment

def child_env() -> dict:
    # dict(os.environ) has upper-cased keys on Windows, so drop the variable case-insensitively;
    # defined, even empty, counts as set, and mcrun's bare name.exe launch then fails
    env = {k: v for k, v in os.environ.items() if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    if "MCSTAS" not in env:
        prefix = env.get("CONDA_PREFIX") or str(
            Path.home() / "AppData" / "Roaming" / "mamba" / "envs" / "tavi-dev")
        for cand in (Path(prefix) / "share" / "mcstas" / "resources",
                     Path(prefix) / "Library" / "share" / "mcstas" / "resources"):
            if cand.is_dir():
                env["MCSTAS"] = str(cand)
                break
    return env


def mcstas_resources(env: dict) -> Path:
    path = Path(env.get("MCSTAS", ""))
    if not (path / "sources" / "Source_gen.comp").is_file():
        raise RuntimeError(f"cannot find McStas resources (MCSTAS={path}); run inside the tavi-dev env")
    return path


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=CREATE_NO_WINDOW)


class Deadline:
    def __init__(self, seconds: float):
        self.end = time.time() + seconds

    def left(self) -> float:
        return self.end - time.time()


def run_child(cmd, cwd, env, timeout, deadline):
    """Run a child with no console window; kill its whole tree on timeout."""
    timeout = max(1.0, min(timeout, deadline.left()))
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=CREATE_NO_WINDOW)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        out, err = proc.communicate()
    return (proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"),
            time.time() - t0, timed_out)


# ----------------------------------------------------------------- the runner

class Run:
    def __init__(self, key, params, rays, seed, rc, out, err, wall, timed_out, path):
        self.key, self.params, self.rays, self.seed = key, params, rays, seed
        self.rc, self.out, self.err, self.wall, self.timed_out, self.path = rc, out, err, wall, timed_out, path
        self._mon = {}

    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out

    def mon(self, name):
        if not self.ok():
            raise RuntimeError(f"run {self.key} failed (rc={self.rc}, timed_out={self.timed_out}): {self.err[-400:]}")
        if name not in self._mon:
            f = self.path / f"{name}.dat"
            self._mon[name] = read_1d(f) if name in ("L_mon", "E_mon") else read_2d(f)
        return self._mon[name]


class Runner:
    def __init__(self, exe: Path, work: Path, env: dict, deadline: Deadline, workers: int):
        self.exe, self.work, self.env, self.deadline = exe, work, env, deadline
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.futures = {}

    def submit(self, key, params, rays, seed=SEED_DIRECT):
        assert key not in self.futures, key
        self.futures[key] = self.pool.submit(self._run, key, dict(params), int(rays), seed)

    def get(self, key) -> Run:
        return self.futures[key].result()

    def _run(self, key, params, rays, seed) -> Run:
        d = self.work / "runs" / key
        if d.exists():
            shutil.rmtree(d)
        d.parent.mkdir(parents=True, exist_ok=True)
        # at least one parameter must be on the command line, or the exe prompts for all
        cmd = [str(self.exe), "-n", str(rays), "-s", str(seed), "-d", str(d)]
        cmd += [f"{k}={v!r}" if isinstance(v, float) else f"{k}={v}" for k, v in params.items()]
        rc, out, err, wall, to = run_child(cmd, self.work, self.env, RUN_TIMEOUT, self.deadline)
        return Run(key, params, rays, seed, rc, out, err, wall, to, d)


# -------------------------------------------------------------- monitor files

def read_1d(path: Path) -> dict:
    rows = [ln.split() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]
    a = np.array(rows, dtype=float)
    return {"x": a[:, 0], "I": a[:, 1], "E": a[:, 2], "N": a[:, 3]}


def read_2d(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    out, key = {}, None
    for ln in lines:
        if ln.startswith("# Data"):
            key = "I"
        elif ln.startswith("# Errors"):
            key = "E"
        elif ln.startswith("# Events"):
            key = "N"
        elif ln.startswith("#") or not ln.strip():
            continue
        elif key:
            out.setdefault(key, []).append([float(v) for v in ln.split()])
    return {k: np.array(v) for k, v in out.items()}


# ----------------------------------------------------- facility table (parsing)

def parse_facility_rows(text: str) -> list:
    """Rows of the 'facility parameters' block of a McStas comp header: (label, {T1..I3})."""
    rows, cur, in_table, started = [], None, False, False
    for ln in text.splitlines():
        s = ln.strip().lstrip("*").strip() if ln.lstrip().startswith("*") else ln.strip()
        if not started:
            started = "facility parameters" in s.lower()
            continue
        if not in_table:
            if "T1=" in s:
                in_table = True
            else:
                continue
        if not s:
            break
        if "T1=" in s:
            cur = [s[:s.index("T1=")].strip(), s]
            rows.append(cur)
        elif cur is not None:
            cur[1] += " " + s
    out = []
    for label, body in rows:
        vals = {f"{k}{i}": 0.0 for k in "TI" for i in (1, 2, 3)}
        for k, i, v in re.findall(r"\b([TI])([123])\s*=\s*([-+0-9.eE]+)", body):
            vals[f"{k}{i}"] = float(v)
        out.append((label, vals))
    return out


def facility_rows(env) -> list:
    text = (mcstas_resources(env) / "sources" / "Source_gen.comp").read_text(encoding="utf-8", errors="replace")
    rows = parse_facility_rows(text)
    assert len(rows) == 12, f"expected 12 Source_gen facility rows, parsed {len(rows)}"
    return rows


def active_pairs(v: dict) -> list:
    return [(v[f"T{i}"], v[f"I{i}"]) for i in (1, 2, 3) if v[f"T{i}"] > 0 and v[f"I{i}"] > 0]


def row_params(vals: dict) -> dict:
    """T/I plus a wavelength range that carries the bulk of every active pair's spectrum.

    Gamma(2, th): the mass below 0.02 th is 2e-4 and above 15 th is 5e-6.
    """
    th = [C_E * T / 949.0 for T, _ in active_pairs(vals)]
    e_lo, e_hi = 0.02 * min(th), 15 * max(th)
    lmin = math.sqrt(C_E / e_hi)
    lmax = math.sqrt(C_E / e_lo)
    # the energy monitor spans exactly the energy range Source_gen samples
    return dict(vals, Lmin=lmin, Lmax=lmax, Emin=C_E / lmax ** 2, Emax=C_E / lmin ** 2, nL=MON_BINS, nE=MON_BINS)


def slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()


# ----------------------------------------------------------- physics (analytic)

def omega_sr(aw_deg: float, ah_deg: float) -> float:
    return 2 * math.radians(aw_deg) * math.sin(math.radians(ah_deg) / 2)


def full_weight(vals: dict, rays: int, aw=4.0, ah=4.0) -> float:
    return sum(i for _, i in active_pairs(vals)) * 1e4 * XW * YH * omega_sr(aw, ah) / rays


def flat_weight(flux, dE, rays, aw=4.0, ah=4.0) -> float:
    return flux * 2 * dE * 1e4 * XW * YH * omega_sr(aw, ah) / rays


def gamma2_mass(T: float, lmin: float, lmax: float) -> float:
    """Integral of Source_gen's SG(L, T) over [lmin, lmax]: 2 a^2 e^(-a/L^2)/L^5, a = 949/T."""
    a = 949.0 / T
    u1, u2 = a / lmax ** 2, a / lmin ** 2
    return (1 + u1) * math.exp(-u1) - (1 + u2) * math.exp(-u2)


def analytic_total(vals: dict, lmin: float, lmax: float, aw=4.0, ah=4.0) -> float:
    return sum(i * gamma2_mass(t, lmin, lmax) for t, i in active_pairs(vals)) * 1e4 * XW * YH * omega_sr(aw, ah)


def band(n: int) -> tuple:
    return n - 4 * math.sqrt(2 * n), n + 4 * math.sqrt(2 * n)


# ------------------------------------------------------------ results & report

class Check:
    def __init__(self, name):
        self.name, self.ok, self.lines, self.wall, self.headline = name, True, [], 0.0, ""

    def note(self, line=""):
        self.lines.append(line)

    def need(self, cond: bool, line: str):
        """Record a line and fail the check when cond is false."""
        self.lines.append(("PASS  " if cond else "FAIL  ") + line)
        if not cond:
            self.ok = False
        return cond


def pull_test(dm, gm, edges, lo, hi):
    """Pull test of two 1D monitors over the bins wholly inside [lo, hi] with N >= MIN_COUNT in both."""
    inside = (edges[:-1] >= lo * (1 - 1e-9)) & (edges[1:] <= hi * (1 + 1e-9))
    use = inside & (dm["N"] >= MIN_COUNT) & (gm["N"] >= MIN_COUNT)
    n = int(use.sum())
    z = (dm["I"][use] - gm["I"][use]) / np.sqrt(dm["E"][use] ** 2 + gm["E"][use] ** 2)
    chi2 = float((z ** 2).sum())
    lo_b, hi_b = band(n)
    carried = float(dm["I"][use].sum() / max(dm["I"].sum(), 1e-300))
    return dict(n=n, chi2=chi2, lo=lo_b, hi=hi_b, enough=n >= MIN_BINS, inband=lo_b <= chi2 <= hi_b,
                carried=carried)


def fmt_pull(r) -> str:
    return (f"n={r['n']} chi2={r['chi2']:.1f} band=[{r['lo']:.1f}, {r['hi']:.1f}] "
            f"bulk carried={r['carried']:.4f}")


# ---------------------------------------------------------------------- checks

def compare_row(d: Run, g: Run, rp: dict) -> dict:
    le = np.linspace(rp["Lmin"], rp["Lmax"], rp["nL"] + 1)
    ee = np.linspace(rp["Emin"], rp["Emax"], rp["nE"] + 1)
    # only bins wholly inside the range Source_gen samples are compared: [Lmin, Lmax], and its energy image
    return {"L": pull_test(d.mon("L_mon"), g.mon("L_mon"), le, rp["Lmin"], rp["Lmax"]),
            "E": pull_test(d.mon("E_mon"), g.mon("E_mon"), ee, rp["Emin"], rp["Emax"])}


def check1_and_2(runner, rows, rp_of, results, same_table):
    """Spectrum vs Source_gen (check 1) and the absolute total (check 2) for every row."""
    c1, c2 = Check("1. Spectrum equals Source_gen's"), Check("2. Absolute total in [Lmin, Lmax]")
    final = {}
    c1.need(same_table, "the component's facility table (%D) equals Source_gen's: labels, order and numbers")
    for label, vals in rows:
        rp = rp_of[label]
        d, g = runner.get(f"row_{slug(label)}_direct"), runner.get(f"row_{slug(label)}_gen")
        cmp_ = compare_row(d, g, rp)
        if not (cmp_["L"]["enough"] and cmp_["E"]["enough"]):
            c1.note(f"  {label}: fewer than {MIN_BINS} bins at {d.rays} rays "
                    f"(L n={cmp_['L']['n']}, E n={cmp_['E']['n']}); rerunning once at {RAISED_FACTOR}x rays")
            rays = d.rays * RAISED_FACTOR
            runner.submit(f"row_{slug(label)}_direct_x", dict(d.params), rays, SEED_DIRECT)
            runner.submit(f"row_{slug(label)}_gen_x", dict(g.params), rays, SEED_GEN)
            d, g = runner.get(f"row_{slug(label)}_direct_x"), runner.get(f"row_{slug(label)}_gen_x")
            cmp_ = compare_row(d, g, rp)
        final[label] = (d, g, cmp_)
    for label, vals in rows:
        d, g, cmp_ = final[label]
        for mon in ("L", "E"):
            r = cmp_[mon]
            c1.need(r["enough"] and r["inband"], f"{label} [{mon}, {d.rays:.0e} rays]: {fmt_pull(r)}")
            c1.need(r["carried"] >= 0.95, f"{label} [{mon}]: compared bins carry {r['carried']:.4f} of the direct spectrum (>= 0.95)")
    # negative control: the FRM2 thermal row with I2 doubled must fail the band
    base = next(l for l, _ in rows if l.startswith("FRM2 thermal"))
    cd = runner.get("ctl_i2x2_direct")
    gbase = runner.get(f"row_{slug(base)}_gen")
    ctl = compare_row(cd, gbase, rp_of[base])
    c1.note("  negative control (FRM2 thermal, I2 doubled in the direct source, vs Source_gen):")
    for mon in ("L", "E"):
        r = ctl[mon]
        c1.need(not r["inband"], f"control [{mon}] fails the band as designed: {fmt_pull(r)}")
    ratios = [final[l][2][m]["chi2"] / final[l][2][m]["n"] for l, _ in rows for m in ("L", "E")]
    c1.headline = (f"{len(rows)} rows x (L, E): chi2/n {min(ratios):.2f}..{max(ratios):.2f}, n >= "
                   f"{min(final[l][2][m]['n'] for l, _ in rows for m in ('L', 'E'))}; "
                   f"control (I2 doubled): chi2 L {ctl['L']['chi2']:.0f} (n={ctl['L']['n']}), E {ctl['E']['chi2']:.0f} (n={ctl['E']['n']})")
    # check 2
    for label, vals in rows:
        d, g, _ = final[label]
        rp = rp_of[label]
        a = analytic_total(vals, rp["Lmin"], rp["Lmax"])
        for tag, run in (("direct", d), ("Source_gen", g)):
            m = run.mon("L_mon")
            tot, sig = float(m["I"].sum()), math.sqrt(float((m["E"] ** 2).sum()))
            z = (tot - a) / sig
            c2.need(abs(z) <= 4, f"{label} [{tag}]: total {tot:.5e} vs analytic {a:.5e} "
                                 f"(ratio {tot / a:.5f}, {z:+.2f} sigma, sigma={sig / a:.2e} relative)")
    results["final_rows"] = final
    zs = []
    for label, vals in rows:
        rp = rp_of[label]
        a = analytic_total(vals, rp["Lmin"], rp["Lmax"])
        for run in final[label][:2]:
            m = run.mon("L_mon")
            zs.append(((float(m["I"].sum()) - a) / math.sqrt(float((m["E"] ** 2).sum()))))
    c2.headline = f"{len(zs)} totals vs analytic: largest |z| = {max(abs(z) for z in zs):.2f} sigma"
    return c1, c2


def check3(runner, rows, results):
    c = Check("3. One weight per ray")
    worst = {m: (0.0, 0.0) for m in MONITORS}
    tested = []
    for label, vals in rows:
        d = results["final_rows"][label][0]
        tested.append((f"{label} (full spectrum)", d, full_weight(vals, d.rays)))
    for key in ("flat_a", "flat_b"):
        r = runner.get(key)
        tested.append((key, r, flat_weight(r.params["flux"], r.params["dE"], r.rays)))
    wide = runner.get("wide")
    tested.append(("wide window 60x120 deg", wide, full_weight(wide.params, wide.rays, 60.0, 120.0)))

    def dev(run, p):
        out = {}
        for m in MONITORS:
            mon = run.mon(m)
            I, E, N = np.ravel(mon["I"]), np.ravel(mon["E"]), np.ravel(mon["N"])
            sel = N > 0
            out[m] = (float(np.max(np.abs(I[sel] / N[sel] - p) / p)),
                      float(np.max(np.abs(E[sel] ** 2 * N[sel] - I[sel] ** 2) / I[sel] ** 2)))
        return out

    for name, run, p in tested:
        dv = dev(run, p)
        for m in MONITORS:
            worst[m] = (max(worst[m][0], dv[m][0]), max(worst[m][1], dv[m][1]))
        ok = all(a < ONE_WEIGHT_TOL and b < ONE_WEIGHT_TOL for a, b in dv.values())
        c.need(ok, f"{name}: p={p:.6e}; max |I/N-p|/p " + ", ".join(f"{m} {dv[m][0]:.1e}" for m in MONITORS))
    c.note("  worst case over all runs, per monitor: |I/N-p|/p and |I_err^2 N - I^2|/I^2:")
    for m in MONITORS:
        c.note(f"    {m}: {worst[m][0]:.2e}, {worst[m][1]:.2e}  (tolerance {ONE_WEIGHT_TOL:.0e})")
    # control: Source_gen's weights vary with wavelength, so the same test must fail on its output
    base = next(l for l, _ in rows if l.startswith("FRM2 thermal"))
    g = results["final_rows"][base][1]
    dv = dev(g, full_weight(dict(rows)[base], g.rays))
    c.need(not all(a < ONE_WEIGHT_TOL for a, _ in dv.values()),
           "control: the same test fails on Source_gen's output (weights vary): "
           + ", ".join(f"{m} {dv[m][0]:.1e}" for m in MONITORS))
    c.headline = (f"worst |I/N-p|/p = {max(w[0] for w in worst.values()):.1e}, worst |I_err^2 N-I^2|/I^2 = "
                  f"{max(w[1] for w in worst.values()):.1e} (tolerance {ONE_WEIGHT_TOL:.0e}); "
                  f"Source_gen control deviates by {max(a for a, _ in dv.values()):.1e}")
    return c


def same_arrays(a: Run, b: Run) -> bool:
    for m in MONITORS:
        x, y = a.mon(m), b.mon(m)
        for k in ("I", "E", "N"):
            if not np.array_equal(x[k], y[k]):
                return False
    return True


def check4(runner, results):
    c = Check("4. Full spectrum ignores E0 and dE")
    base = runner.get("fs_base")
    for key in ("fs_e0_5", "fs_e0_50", "fs_de_05", "fs_odd"):
        r = runner.get(key)
        c.need(same_arrays(base, r), f"{key} ({', '.join(f'{k}={v}' for k, v in r.params.items() if k in ('E0', 'dE'))}) "
                                     "gives monitor arrays identical to the baseline (E0=25, dE=5)")
    ctl = runner.get("fs_seed")
    c.need(not same_arrays(base, ctl), "control: a different seed gives different arrays (the comparison can see a difference)")
    c.note(f"  baseline: {base.rays:.0e} rays, seed {base.seed}; total I = {float(base.mon('PSD_mon')['I'].sum()):.6e}")
    c.headline = "4 runs with other E0/dE are bit-identical to the baseline; a different seed differs" if c.ok else "see lines"
    return c


def check5(runner, results):
    c = Check("5. The flat band")
    heads = []
    for key in ("flat_a", "flat_b"):
        r = runner.get(key)
        P = r.params
        E0, dE, flux = P["E0"], P["dE"], P["flux"]
        m = r.mon("E_mon")
        edges = np.linspace(0.0, P["Emax"], len(m["x"]) + 1)
        lo_e, hi_e = edges[:-1], edges[1:]
        inb = (lo_e >= E0 - dE - 1e-9) & (hi_e <= E0 + dE + 1e-9)
        # the band edges must sit on bin edges for these parameters, or bins would straddle them
        assert math.isclose(lo_e[inb][0], E0 - dE, abs_tol=1e-9) and math.isclose(hi_e[inb][-1], E0 + dE, abs_tol=1e-9), key
        out_ok = bool(np.all(m["N"][~inb] == 0) and np.all(m["I"][~inb] == 0))
        c.need(out_ok, f"{key} (E0={E0}, dE={dE}, flux={flux}): no counts in any of the {int((~inb).sum())} bins outside [{E0 - dE}, {E0 + dE}]")
        c.need(bool(np.all(m["N"][inb] > 0)), f"{key}: all {int(inb.sum())} bins inside the band are filled")
        tot, sig = float(m["I"][inb].sum()), math.sqrt(float((m["E"][inb] ** 2).sum()))
        per_mev = tot / (2 * dE)
        expect = flux * 1e4 * XW * YH * omega_sr(4.0, 4.0)
        z = (tot / (2 * dE) - expect) / (sig / (2 * dE))
        c.need(abs(z) <= 4, f"{key}: intensity per meV {per_mev:.5e} vs flux*1e4*area*Omega {expect:.5e} (ratio {per_mev / expect:.6f}, {z:+.2f} sigma)")
        k, N = int(inb.sum()), m["N"][inb]
        chi2 = float(((N - N.mean()) ** 2 / (N.mean() * (1 - 1 / k))).sum())
        lo, hi = band(k)
        c.need(k >= MIN_BINS and lo <= chi2 <= hi, f"{key}: uniform in energy: n={k} bins, chi2={chi2:.1f}, band=[{lo:.1f}, {hi:.1f}]")
        heads.append(f"{key}: level ratio {per_mev / expect:.6f}, uniformity chi2 {chi2:.1f} (n={k})")
    c.headline = "; ".join(heads)
    return c


def check6(runner, results):
    c = Check("6. Refusals")
    for key, names in REFUSALS:
        r = runner.get(key)
        ok = (not r.timed_out) and r.rc != 0 and "Source_Maxwell_direct" in r.err and all(n in r.err for n in names)
        c.need(ok, f"{key}: rc={r.rc}, stderr: {r.err.strip().splitlines()[-1] if r.err.strip() else '(empty)'}")
    for key in ("accept_flat_values_in_full_spectrum", "accept_valid"):
        r = runner.get(key)
        c.need(r.ok(), f"{key}: accepted, rc={r.rc} (the refusals are not over-broad)")
    c.headline = f"{len(REFUSALS)} invalid inputs refused with the parameter named; 2 valid inputs accepted" if c.ok else "see lines"
    return c


REFUSALS = [  # (run key, strings the message must contain)
    ("refuse_T1_neg", ["T1=-1"]),
    ("refuse_I1_neg", ["I1=-1"]),
    ("refuse_T2_nan", ["T2="]),
    ("refuse_no_pair", ["no pair has T>0 and I>0"]),
    ("refuse_I_all_zero", ["no pair has T>0 and I>0"]),
    ("refuse_flat_E0_le_dE", ["E0=", "dE=", "E0 - dE > 0"]),
    ("refuse_flat_dE_zero", ["dE=0"]),
    ("refuse_flat_flux_zero", ["flux=0"]),
    ("refuse_flat_band_2", ["flat_band=2"]),
    ("refuse_focus_aw_zero", ["focus_aw=0"]),
    ("refuse_focus_ah_181", ["focus_ah=181"]),
]


def _cdf_vertical(kind: str, edges_deg, aw_deg: float, ah_deg: float, steps=20000):
    """P(atan2(vy, vz) <= b) for the window drawn by three samplers.

    Directions are (cos(th) sin(ph), sin(th), cos(th) cos(ph)), so
    atan2(vy, vz) = atan(tan(th) / cos(ph)). With ph uniform in +-aw/2:
      'steradian' (the component): sin(th) uniform in +-sin(ah/2).
      'latitude'  (wrong):          th uniform in +-ah/2.
      'angle'     (the old sampler, uniform in angle then tan): th = atan2(vy, vz)
                  itself is uniform in +-ah/2, independent of ph.
    """
    ah, aw = math.radians(ah_deg), math.radians(aw_deg)
    b = np.radians(np.clip(np.asarray(edges_deg, dtype=float), -89.9, 89.9))
    if kind == "angle":
        return np.clip((b + ah / 2) / ah, 0, 1)
    ph = (np.arange(steps) + 0.5) / steps * aw - aw / 2
    t = np.tan(b)[:, None] * np.cos(ph)[None, :]          # tan(th*) at which atan2 == b
    if kind == "steradian":
        g = np.clip((1 + t / np.sqrt(1 + t * t) / math.sin(ah / 2)) / 2, 0, 1)
    elif kind == "latitude":
        g = np.clip((np.arctan(t) + ah / 2) / ah, 0, 1)
    else:
        raise ValueError(kind)
    return g.mean(axis=1)


def vert_test(counts, edges_deg, kind, aw_deg, ah_deg):
    cdf = _cdf_vertical(kind, edges_deg, aw_deg, ah_deg)
    q = np.diff(cdf)
    ntot = counts.sum()
    exp = ntot * q
    use = exp >= MIN_COUNT
    n = int(use.sum())
    z = (counts[use] - exp[use]) / np.sqrt(exp[use] * (1 - q[use]))
    chi2 = float((z ** 2).sum())
    lo, hi = band(n)
    return dict(n=n, chi2=chi2, lo=lo, hi=hi, inband=lo <= chi2 <= hi, enough=n >= MIN_BINS)


def check7(runner, results):
    c = Check("7. Uniform per steradian")
    r = runner.get("wide")
    aw, ah, nd = 60.0, 120.0, r.params["Ndiv"]
    N = r.mon("Div_mon")["N"]
    assert N.shape == (nd, nd), N.shape
    # McStas writes the monitor with rows = vertical bins, columns = horizontal bins; assert it
    # from the support, since a transposed reading would test the wrong axis.
    v, h = N.sum(axis=1), N.sum(axis=0)
    vspan = (np.nonzero(v)[0][-1] - np.nonzero(v)[0][0] + 1) * (2 * ah / nd)
    hspan = (np.nonzero(h)[0][-1] - np.nonzero(h)[0][0] + 1) * (2 * aw / nd)
    c.need(hspan <= aw + 2 * aw / nd and vspan > aw + 2 * aw / nd,
           f"axis check: horizontal support {hspan:.1f} deg (window {aw:g}), vertical support {vspan:.1f} deg (window {ah:g}, wider after atan2)")
    ev = np.linspace(-ah, ah, nd + 1)
    ntot = int(N.sum())
    c.note(f"  {ntot} rays, window {aw:g} x {ah:g} deg, {nd} x {nd} bins; vertical angle measured as atan2(vy, vz)")
    rs = vert_test(v, ev, "steradian", aw, ah)
    c.need(rs["enough"] and rs["inband"], f"vertical vs the exact per-steradian expectation: n={rs['n']} chi2={rs['chi2']:.1f} band=[{rs['lo']:.1f}, {rs['hi']:.1f}]")
    for kind, what in (("angle", "a sampler uniform in angle (the old one)"), ("latitude", "a sampler uniform in latitude")):
        w = vert_test(v, ev, kind, aw, ah)
        c.need(not (w["enough"] and w["inband"]), f"control: the same data fails {what}: n={w['n']} chi2={w['chi2']:.1f} band=[{w['lo']:.1f}, {w['hi']:.1f}]")
        results[f"ctl7_{kind}"] = w
    eh = np.linspace(-aw, aw, nd + 1)
    inside = (eh[:-1] >= -aw / 2 - 1e-9) & (eh[1:] <= aw / 2 + 1e-9)
    c.need(bool(np.all(h[~inside] == 0)), "horizontal: no counts outside the +-30 deg longitude window")
    k = int(inside.sum())
    e = ntot / k
    z = (h[inside] - e) / math.sqrt(e * (1 - 1 / k))
    chi2 = float((z ** 2).sum())
    lo, hi = band(k)
    c.need(k >= MIN_BINS and lo <= chi2 <= hi, f"horizontal uniform in longitude: n={k} chi2={chi2:.1f} band=[{lo:.1f}, {hi:.1f}]")
    c.headline = (f"vertical chi2 {rs['chi2']:.1f} (n={rs['n']}, band {rs['lo']:.0f}..{rs['hi']:.0f}); fails uniform-in-angle "
                  f"(chi2 {results['ctl7_angle']['chi2']:.0f}) and uniform-in-latitude (chi2 {results['ctl7_latitude']['chi2']:.0f})")
    return c


# --------------------------------------------------------------------- driver

def component_stamp(path: Path) -> tuple:
    """(version, first 12 hex of SHA-256 over the bytes with CRLF normalised to LF)."""
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    m = re.search(rb"^\s*\*\s*Version:\s*(\S+)", raw, re.M)
    return (m.group(1).decode() if m else "?", hashlib.sha256(raw).hexdigest()[:12])


def compile_instrument(work: Path, env: dict, deadline: Deadline) -> tuple:
    work.mkdir(parents=True, exist_ok=True)
    inst = work / INSTR.name
    shutil.copy(INSTR, inst)
    mcrun = shutil.which("mcrun", path=env.get("PATH"))
    if not mcrun:
        raise RuntimeError("mcrun not found on PATH; run inside the tavi-dev environment")
    cmd = [mcrun, "-I", str(COMP.parent), "-n", "100", "-s", "1", "-d", str(work / "compile_smoke"), str(inst), "SRC=0"]
    rc, out, err, wall, to = run_child(cmd, work, env, COMPILE_TIMEOUT, deadline)
    exe = work / (INSTR.stem + ".exe")
    if to or rc != 0 or not exe.is_file():
        raise RuntimeError(f"compile failed (rc={rc}, timed_out={to}):\n{out[-1500:]}\n{err[-1500:]}")
    ver = "unknown"
    mcstas = shutil.which("mcstas", path=env.get("PATH"))
    if mcstas:
        rc2, o2, e2, _, _ = run_child([mcstas, "--version"], work, env, 60, deadline)
        lines = [ln.strip() for ln in (o2 + "\n" + e2).splitlines() if ln.strip()]
        ver = lines[0] if lines else "unknown"
    return exe, wall, ver, mcrun


def submit_all(runner, rows, rp_of):
    full_ti = dict(T1=285.6, I1=3.06e13, T2=300.0, I2=1.68e12, T3=429.9, I3=6.77e12)  # FRM2 thermal
    # check 1/2/3: every row, both sources
    for label, vals in rows:
        rp = rp_of[label]
        runner.submit(f"row_{slug(label)}_direct", dict(rp, SRC=0), ROW_RAYS, SEED_DIRECT)
        runner.submit(f"row_{slug(label)}_gen", dict(rp, SRC=1), ROW_RAYS, SEED_GEN)
    base = next(l for l, _ in rows if l.startswith("FRM2 thermal"))
    rp = rp_of[base]
    doubled = dict(dict(rows)[base])
    doubled["I2"] *= 2
    runner.submit("ctl_i2x2_direct", dict(rp, **doubled, SRC=0), ROW_RAYS, SEED_DIRECT)
    # check 4
    n4 = 1_000_000
    for key, extra in (("fs_base", {}), ("fs_e0_5", {"E0": 5.0}), ("fs_e0_50", {"E0": 50.0}),
                       ("fs_de_05", {"dE": 0.5}), ("fs_odd", {"E0": -5.0, "dE": -3.0})):
        runner.submit(key, dict(full_ti, SRC=0, flat_band=0, **{"E0": 25.0, "dE": 5.0, **extra}), n4, SEED_DIRECT)
    runner.submit("fs_seed", dict(full_ti, SRC=0, flat_band=0, E0=25.0, dE=5.0), n4, SEED_OTHER)
    # check 5: band edges sit on E-monitor bin edges (Emax=100, 200 bins of 0.5 meV)
    runner.submit("flat_a", dict(full_ti, SRC=0, flat_band=1, E0=25.0, dE=15.0, flux=1.0, Emax=100.0), BASE_RAYS, SEED_DIRECT)
    runner.submit("flat_b", dict(full_ti, SRC=0, flat_band=1, E0=40.0, dE=25.0, flux=3.0, Emax=100.0), BASE_RAYS, SEED_DIRECT)
    # check 6
    bad = [
        ("refuse_T1_neg", dict(full_ti, T1=-1.0)),
        ("refuse_I1_neg", dict(full_ti, I1=-1.0)),
        ("refuse_T2_nan", dict(full_ti, T2="nan")),
        ("refuse_no_pair", dict(full_ti, T1=0.0, T2=0.0, T3=0.0)),
        ("refuse_I_all_zero", dict(full_ti, I1=0.0, I2=0.0, I3=0.0)),
        ("refuse_flat_E0_le_dE", dict(full_ti, flat_band=1, E0=3.0, dE=5.0)),
        ("refuse_flat_dE_zero", dict(full_ti, flat_band=1, E0=25.0, dE=0.0)),
        ("refuse_flat_flux_zero", dict(full_ti, flat_band=1, E0=25.0, dE=5.0, flux=0.0)),
        ("refuse_flat_band_2", dict(full_ti, flat_band=2)),
        ("refuse_focus_aw_zero", dict(full_ti, focus_aw=0.0)),
        ("refuse_focus_ah_181", dict(full_ti, focus_ah=181.0)),
    ]
    for key, p in bad:
        runner.submit(key, dict(p, SRC=0), 100, SEED_DIRECT)
    runner.submit("accept_flat_values_in_full_spectrum", dict(full_ti, SRC=0, flat_band=0, E0=3.0, dE=5.0), 1000, SEED_DIRECT)
    runner.submit("accept_valid", dict(full_ti, SRC=0), 1000, SEED_DIRECT)
    # check 7
    runner.submit("wide", dict(full_ti, SRC=0, focus_aw=60.0, focus_ah=120.0, Ndiv=240), BASE_RAYS, SEED_DIRECT)


def write_report(path, meta, checks, runs, total_wall):
    L = [f"# Source_Maxwell_direct verification report", "",
         f"- Result: **{'PASS' if all(c.ok for c in checks) else 'FAIL'}**",
         f"- Date: {meta['date']}",
         f"- Component: {meta['comp']} version {meta['version']}, sha256[:12] {meta['sha']} (CRLF normalised to LF)",
         f"- McStas: {meta['mcstas']}; compiler step {meta['compile_wall']:.1f} s ({meta['mcrun']})",
         f"- Test instrument: {INSTR.relative_to(REPO).as_posix()}",
         f"- Rays per run: {ROW_RAYS:.0e} (spectrum rows), {BASE_RAYS:.0e} (flat band, wide window), 1e6 (check 4), 100 (refusals); "
         f"raised x{RAISED_FACTOR} only when fewer than {MIN_BINS} bins qualified",
         f"- Seeds: direct {SEED_DIRECT}, Source_gen {SEED_GEN}, seed control {SEED_OTHER}",
         f"- Timeouts: {RUN_TIMEOUT} s per run, {COMPILE_TIMEOUT} s compile, {TOTAL_TIMEOUT} s overall (a run past its limit is killed and reported)",
         f"- Total wall time: {total_wall:.1f} s", ""]
    for c in checks:
        L += [f"## {c.name}: {'PASS' if c.ok else 'FAIL'}", "", f"Summary: {c.headline}", "", f"Evaluation {c.wall:.2f} s.", "", "```"] + c.lines + ["```", ""]
    L += ["## Runs", "", "| run | rays | seed | wall s | rc |", "|---|---|---|---|---|"]
    seen = set()
    for r in runs:
        if r.key in seen:
            continue
        seen.add(r.key)
        L.append(f"| {r.key} | {r.rays} | {r.seed} | {r.wall:.2f} | {r.rc}{' TIMEOUT' if r.timed_out else ''} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    t_start = time.time()
    deadline = Deadline(TOTAL_TIMEOUT)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = OUT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "report.md"
    print(f"Source_Maxwell_direct verification; report: {report}", flush=True)
    checks, results = [], {}
    try:
        env = child_env()
        rows = facility_rows(env) + [("Single temperature", {"T1": 300.0, "I1": 1e13, "T2": 0.0, "I2": 0.0, "T3": 0.0, "I3": 0.0})]
        ver, sha = component_stamp(COMP)
        comp_rows = parse_facility_rows(COMP.read_text(encoding="utf-8"))
        same_table = comp_rows == rows[:12]  # ordered (label, values): a label swap fails too
        exe, cwall, mcver, mcrun = compile_instrument(out_dir / "build", env, deadline)
        print(f"compiled in {cwall:.1f} s with {mcver}", flush=True)
        workers = max(2, min(16, os.cpu_count() or 4))
        runner = Runner(exe, out_dir / "build", env, deadline, workers)
        rp_of = {label: row_params(vals) for label, vals in rows}
        submit_all(runner, rows, rp_of)
        meta = dict(date=datetime.datetime.now().isoformat(timespec="seconds"), comp=COMP.name, version=ver, sha=sha,
                    mcstas=mcver, compile_wall=cwall, mcrun=mcrun)
        steps = [("1+2", lambda: check1_and_2(runner, rows, rp_of, results, same_table)),
                 ("3", lambda: check3(runner, rows, results)),
                 ("4", lambda: check4(runner, results)),
                 ("5", lambda: check5(runner, results)),
                 ("6", lambda: check6(runner, results)),
                 ("7", lambda: check7(runner, results))]
        for tag, fn in steps:
            t0 = time.time()
            try:
                got = fn()
                got = list(got) if isinstance(got, tuple) else [got]
            except Exception:
                c = Check(f"check {tag}")
                c.need(False, "raised an exception:\n" + traceback.format_exc())
                got = [c]
            for c in got:
                c.wall = time.time() - t0
                checks.append(c)
                print(f"{'PASS' if c.ok else 'FAIL'}  {c.name}" + (f"\n        {c.headline}" if c.headline else ""), flush=True)
        bad_runs = [r for r in runner.futures.values() if r.result().timed_out]
        if bad_runs:
            c = Check("Timeouts")
            c.need(False, "runs killed at the timeout: " + ", ".join(r.result().key for r in bad_runs))
            checks.append(c)
            print(f"FAIL  {c.name}: {c.lines[-1]}", flush=True)
        write_report(report, meta, checks, [f.result() for f in runner.futures.values()], time.time() - t_start)
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        report.write_text(f"# Source_Maxwell_direct verification report\n\nFAIL: the tool stopped early.\n\n```\n{tb}\n```\n",
                          encoding="utf-8", newline="\n")
        print(f"FAIL (tool error); report: {report}")
        return 2
    ok = all(c.ok for c in checks)
    print(f"\n{'ALL CHECKS PASSED' if ok else 'FAILED'} in {time.time() - t_start:.1f} s; report: {report}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
