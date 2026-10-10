"""The point plan (instruments/rules.py): compatibility, provenance, expansion, feasibility.

Most tests build the frozen context by hand and need no instrument. Those
marked with the ``puma`` fixture solve on PUMA's real state (cubic a = 4.05 A,
14.7 meV fixed energy), so they check the rule model against the solver.
"""
import dataclasses
import importlib.util
import itertools
import math
import time
from pathlib import Path

import pytest

from instruments import rules
from instruments.contract import CurvatureMode
from instruments.descriptor import CurvatureAxis
from instruments.rules import (
    ARCS, ATH, ATT, DE, EF, EI, HKL, HKL_CALC, KF, KI, MOTORS, MTH, MTT, NOT_READ, Q,
    Q_CALC, SCANNED, SET_PER_POINT, SGL, SGU, STH, STT, USED_AS_TYPED, AxisPolicy,
    PlanContext, PlanRefused, build_plan, check_point, context_from_state, evaluate, expand,
)
from tavi.quantities import QUANTITIES, public_values
from tavi.utilities import scan_stop_note

RADII = tuple(rules.RADIUS_CRYSTAL)
RHM, RVA = "mono_horizontal_radius_m", "analyzer_vertical_radius_m"
GAP = "slit.pre_sample.horizontal_gap_mm"
LOCK = {"hkl_u": [1.0, 0.0, 0.0], "hkl_v": [0.0, 1.0, 0.2], "tilts": {"sgl": 11.31, "sgu": 0.0}}


def _context(curvature=None, **overrides):
    policies = {qid: AxisPolicy(CurvatureMode.HELD, CurvatureAxis()) for qid in RADII}
    policies.update(curvature or {})
    fields = dict(
        engine="mcstas", fixed_side="Kf", fixed_energy_mev=14.7, monocris="pg002",
        anacris="pg002", plane_lock=None, curvature=policies,
        inputs=frozenset({*HKL, *Q, DE, MTT, STT, STH, ATT, SGL, SGU, *RADII, GAP}),
        observables=frozenset({MTH, ATH, EI, EF, KI, KF, *(f"applied_{q}" for q in RADII)}),
        slit_bindings=frozenset({GAP}))
    fields.update(overrides)
    return PlanContext(**fields)


def _plan(c1="", c2="", ctx=None, rel1=False, rel2=False):
    return build_plan([(c1, rel1), (c2, rel2)], ctx or _context())


def _refused(c1="", c2="", ctx=None):
    with pytest.raises(PlanRefused) as caught:
        _plan(c1, c2, ctx)
    return caught.value


def _roles(plan, *qids):
    return {qid: (plan.provenance[qid].role, plan.provenance[qid].commands,
                  plan.provenance[qid].policies) for qid in qids}


def _snapshot(**values):
    """Every input any calculation reads, finite, under its canonical ID."""
    snap = {**dict.fromkeys(HKL, 0.0), "h": 1.0, **dict(zip(Q, (1.5, 0.0, 0.0))), DE: 0.0,
            MTT: 40.0, STT: -60.0, STH: 30.0, ATT: 40.0, SGL: 0.0, SGU: 0.0,
            **dict.fromkeys(RADII, 2.0), GAP: 20.0}
    snap.update(values)
    return snap


# ---------------------------------------------------------------- compatibility

def test_h_with_k_is_compatible():
    plan = _plan("H 0.9 1.1 0.1", "K 0 0.2 0.1")
    assert plan.calculation == HKL_CALC
    assert _roles(plan, "h", "k", "l") == {
        "h": (SCANNED, (1,), ()), "k": (SCANNED, (2,), ()), "l": (USED_AS_TYPED, (), ())}


SPP = SET_PER_POINT


def test_h_with_delta_e_at_fixed_kf_attributes_every_field():
    plan = _plan("H 0.9 1.1 0.1", "deltaE 0 4 1")
    assert plan.energy == "fixed Kf"
    assert _roles(plan, "h", DE, "k", "l", *Q, *ARCS, STH, STT, MTT, MTH, EI, KI,
                  ATT, ATH, EF, KF) == {
        "h": (SCANNED, (1,), ()), DE: (SCANNED, (2,), ()),
        "k": (USED_AS_TYPED, (), ()), "l": (USED_AS_TYPED, (), ()),
        **{q: (SPP, (1,), ()) for q in Q},
        # The solver levels the mounted Q: the arcs follow H alone.
        SGL: (SPP, (1,), ()), SGU: (SPP, (1,), ()),
        STH: (SPP, (1, 2), ()), STT: (SPP, (1, 2), ()),
        MTT: (SPP, (2,), ()), MTH: (SPP, (2,), ()), EI: (SPP, (2,), ()), KI: (SPP, (2,), ()),
        # The fixed side's crystal is set by the setting, not by a command.
        ATT: (SPP, (), ("fixed Kf",)), ATH: (SPP, (), ("fixed Kf",)),
        EF: (SPP, (), ("fixed Kf",)), KF: (SPP, (), ("fixed Kf",)),
    }


def test_h_with_delta_e_at_fixed_ki_attributes_every_field():
    plan = _plan("H 0.9 1.1 0.1", "deltaE 0 4 1", _context(fixed_side="Ki"))
    assert plan.energy == "fixed Ki"
    assert _roles(plan, *ARCS, STH, STT, MTT, MTH, EI, KI, ATT, ATH, EF, KF) == {
        SGL: (SPP, (1,), ()), SGU: (SPP, (1,), ()),
        STH: (SPP, (1, 2), ()), STT: (SPP, (1, 2), ()),
        MTT: (SPP, (), ("fixed Ki",)), MTH: (SPP, (), ("fixed Ki",)),
        EI: (SPP, (), ("fixed Ki",)), KI: (SPP, (), ("fixed Ki",)),
        ATT: (SPP, (2,), ()), ATH: (SPP, (2,), ()), EF: (SPP, (2,), ()), KF: (SPP, (2,), ()),
    }


@pytest.mark.parametrize("mode", [CurvatureMode.HELD, CurvatureMode.AUTOFOCUS])
def test_h_with_a_radius_promotes_the_axis_to_scanned(mode):
    ctx = _context({RHM: AxisPolicy(mode, CurvatureAxis())})
    plan = _plan("H 0.9 1.1 0.1", "rhm 2 3 0.5", ctx)
    assert plan.provenance[RHM] == rules.Provenance(SCANNED, (2,))
    assert not any(rule.name.startswith("autofocus") for rule in plan.rules)
    alone = _plan("H 0.9 1.1 0.1", ctx=ctx)
    expected = USED_AS_TYPED if mode == CurvatureMode.HELD else SPP
    assert alone.provenance[RHM].role == expected


@pytest.mark.parametrize("holder", ["fixed on the PG(002) analyzer",
                                    "NMO installed: this axis is fixed flat"])
def test_h_with_a_radius_is_refused_on_a_hardware_or_module_fixed_axis(holder):
    fixed = AxisPolicy(CurvatureMode.HELD, CurvatureAxis(driven=False, fixed_radius_m=0.05),
                       holder)
    refusal = _refused("H 0.9 1.1 0.1", "rva 1 2 0.5", _context({RVA: fixed}))
    assert str(refusal) == (f"The hardware holds rva (analyzer vertical radius) at 0.05 m "
                            f"({holder}), so it cannot be scanned.")
    assert (refusal.command, refusal.quantity) == (2, RVA)


def test_a_radius_scan_alone_is_refused_on_a_fixed_assembly():
    fixed = AxisPolicy(CurvatureMode.HELD, CurvatureAxis(driven=False, fixed_radius_m=0.05),
                       "fixed on the PG(002) analyzer")
    assert "The hardware holds rva" in str(_refused("rva 1 2 0.5", ctx=_context({RVA: fixed})))


def test_h_with_a_bound_slit_is_compatible_and_an_unbound_one_refused():
    plan = _plan("H 0.9 1.1 0.1", "pre_sample_hgap 10 30 10")
    assert plan.provenance[GAP] == rules.Provenance(SCANNED, (2,))
    refusal = _refused("H 0.9 1.1 0.1", "pre_sample_hgap 10 30 10",
                       _context(slit_bindings=frozenset()))
    assert "has no per-point binding" in str(refusal) and refusal.command == 2
    assert "has no post-mono" in str(_refused("post_mono_hgap 10 30 10"))


@pytest.mark.parametrize("cmd, qid, side, name", [
    ("rhm 2 3 0.5", RHM, "mono", "rhm (mono horizontal radius)"),
    ("rva 2 3 0.5", RVA, "analyzer", "rva (analyzer vertical radius)"),
])
def test_a_radius_on_an_unselected_crystal_names_the_missing_crystal(cmd, qid, side, name):
    """context_from_state drops such a radius: the refusal says no crystal is selected, not
    that the instrument has no radius."""
    ctx = _context()
    unselected = dataclasses.replace(
        ctx, inputs=ctx.inputs - {qid},
        curvature={q: p for q, p in ctx.curvature.items() if q != qid})
    assert str(_refused(cmd, ctx=unselected)) == (
        f"No {side} crystal this instrument installs is selected, so there is no {name} to scan.")


def test_a_slit_scan_is_refused_on_the_analytic_engine():
    refusal = _refused("pre_sample_hgap 10 30 10", ctx=_context(engine="deterministic"))
    assert "the analytic engine has no aperture model" in str(refusal)


def test_a3_with_a4_is_direct_motors():
    plan = _plan("A3 30 32 1", "A4 -60 -58 1")
    assert plan.calculation == MOTORS and plan.energy == "from the crystal angles"
    assert _roles(plan, STH, STT, MTT, ATT, *ARCS) == {
        STH: (SCANNED, (1,), ()), STT: (SCANNED, (2,), ()),
        **{q: (USED_AS_TYPED, (), ()) for q in (MTT, ATT, *ARCS)}}
    assert all(plan.provenance[q].role == NOT_READ for q in (*HKL, *Q))
    # Set at each point from fields used as typed: neither a command nor a setting.
    assert _roles(plan, EI)[EI] == (SPP, (), ())


def test_a2_with_a6_takes_both_energies_from_the_crystals():
    plan = _plan("A2 38 42 1", "A6 38 42 1")
    assert _roles(plan, EI, EF, DE, MTH, ATH) == {
        EI: (SPP, (1,), ()), EF: (SPP, (2,), ()), DE: (SPP, (1, 2), ()),
        MTH: (SPP, (1,), ()), ATH: (SPP, (2,), ())}
    assert not any(p.policies for p in plan.provenance.values())
    assert "fixed_energy" not in {rule.name for rule in plan.rules}


@pytest.mark.parametrize("c1, c2, name", [
    ("A3 30 31 1", "omega 30 31 1", "A3 (sample rotation)"),
    ("A2 30 31 1", "mtt 30 31 1", "A2 (mono 2θ)"),
])
def test_two_spellings_of_one_quantity_are_refused(c1, c2, name):
    first, second = c1.split()[0], c2.split()[0]
    assert str(_refused(c1, c2)) == (f"Both commands scan {name}, as {first!r} and as "
                                     f"{second!r}; scan it once. "
                                     "force does not override a command conflict.")


def test_an_arc_scan_under_a_plane_lock_is_refused():
    refusal = _refused("sgl 0 2 1", ctx=_context(plane_lock=LOCK))
    assert str(refusal).startswith("The plane lock holds sgl (lower arc): the locked "
                                   "scattering plane (1 0 0)/(0 1 0.2)")
    assert "The plane lock holds sgu" in str(_refused("H 1 2 1", "sgu 0 2 1",
                                                      _context(plane_lock=LOCK)))


def test_h_with_a4_is_refused_naming_the_ownership():
    refusal = _refused("H 0.9 1.1 0.1", "A4 40 42 1")
    assert str(refusal) == ("A4 (sample 2θ) is calculated from H in the HKL calculation, "
                            "so it cannot also be scanned. "
                            "force does not override a command conflict.")
    assert (refusal.command, refusal.quantity) == (2, STT)


def test_a_command_on_the_fixed_side_names_the_setting():
    assert str(_refused("H 0.9 1.1 0.1", "A6 40 42 1")) == (
        "A6 (analyzer 2θ) is set by fixed Kf in the HKL calculation, so it cannot also "
        "be scanned. force does not override a command conflict.")


def test_derived_theta_is_never_an_input():
    assert "rocking is not modelled" in str(_refused("A1 10 20 1"))


def test_a_lock_with_an_h_by_k_grid_is_compatible_and_the_lock_sets_the_arcs():
    plan = _plan("H 1 1.1 0.1", "K 0 1 0.5", _context(plane_lock=LOCK))
    assert _roles(plan, *ARCS) == {SGL: (SPP, (), ("plane lock",)),
                                   SGU: (SPP, (), ("plane lock",))}


# ------------------------------------------------------------------ expansion

def test_relative_bases_come_from_each_command_own_field():
    plan = _plan("A3 -2 4 2", "A4 -1 1 1", rel1=True, rel2=True)
    expansion = expand(plan, _snapshot(**{STH: 30.0, STT: -50.0}))
    assert expansion.bases == {1: 30.0, 2: -50.0}
    assert expansion.values == {1: (28.0, 30.0, 32.0, 34.0), 2: (-51.0, -50.0, -49.0)}
    # Command 2 is the outer loop.
    assert [(p[STH], p[STT]) for p in expansion.points[:5]] == [
        (28.0, -51.0), (30.0, -51.0), (32.0, -51.0), (34.0, -51.0), (28.0, -50.0)]
    assert len(expansion.points) == 12


def test_a_mixed_pair_steps_only_the_relative_command():
    plan = _plan("H -0.1 0.1 0.1", "deltaE 0 2 2", rel1=True)
    expansion = expand(plan, _snapshot(h=2.0, **{DE: 7.0}))
    assert expansion.values == {1: (1.9, 2.0, 2.1), 2: (0.0, 2.0)}
    assert expansion.bases == {1: 2.0}


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, ""])
def test_a_relative_command_without_a_finite_base_refuses_at_expand(bad):
    plan = _plan("A3 -1 1 1", rel1=True)
    snapshot = _snapshot()
    if bad is None:
        del snapshot[STH]
    else:
        snapshot[STH] = bad
    with pytest.raises(PlanRefused, match="steps relative to A3") as caught:
        expand(plan, snapshot)
    assert caught.value.command == 1


def test_a_field_used_as_typed_without_a_number_refuses():
    snapshot = _snapshot()
    del snapshot["k"]
    with pytest.raises(PlanRefused, match="K is used as typed"):
        expand(_plan("H 1 2 1"), snapshot)


def test_a_lone_command_2_is_the_only_axis_and_keeps_its_number():
    plan = _plan("", "A3 0 2 1")
    assert [c.number for c in plan.commands] == [2]
    assert plan.provenance[STH] == rules.Provenance(SCANNED, (2,))
    expansion = expand(plan, _snapshot())
    assert expansion.values == {2: (0.0, 1.0, 2.0)}
    assert [p[STH] for p in expansion.points] == [0.0, 1.0, 2.0]


def test_a_step_that_does_not_divide_the_range_stops_short_of_the_end():
    expansion = expand(_plan("A3 0 10 4"), _snapshot())
    assert expansion.values == {1: (0.0, 4.0, 8.0)}
    assert "stops at 8" in scan_stop_note(0.0, 10.0, 4.0)


@pytest.mark.parametrize("cmd", ["A3 0 10 0", "A3 0 10 -1", "A3 10 0 1", "A3 0 10 15",
                                 "A3 0 nan 1", "A3 0 10", "A3 0 10 1 2"])
def test_zero_wrong_sign_and_too_long_steps_are_refused(cmd):
    assert _refused("", cmd).command == 2


def test_a_step_too_small_for_its_range_is_refused_not_overflowed():
    """(end - start) / step overflows to inf: refused by name before any step count is taken."""
    assert str(_refused("A3 0 1 1e-309")) == "Step (1e-309) is too small for the range 0 to 1."


@pytest.mark.parametrize("c1, c2", [("", ""), ("pre_sample_hgap 10 30 10", ""),
                                    ("", "rhm 2 3 0.5")])
def test_a_scan_that_selects_no_geometry_holds_the_motors(c1, c2):
    plan = _plan(c1, c2)
    assert plan.calculation == MOTORS
    assert all(plan.provenance[q].role == USED_AS_TYPED for q in (MTT, STT, STH, ATT, *ARCS))
    snapshot = _snapshot()
    for point in expand(plan, snapshot).points:
        assert all(point[q] == snapshot[q] for q in (MTT, STT, STH, ATT, *ARCS))


def test_a_relative_radius_range_is_checked_against_travel_from_its_base():
    driven = AxisPolicy(CurvatureMode.HELD, CurvatureAxis(min_radius_m=1.5, max_radius_m=5.0))
    plan = _plan("rhm -1 1 1", ctx=_context({RHM: driven}), rel1=True)
    with pytest.raises(PlanRefused, match="mechanical minimum"):
        expand(plan, _snapshot(**{RHM: 2.0}))
    assert "mechanical minimum" in str(_refused("rhm 1 2 0.5", ctx=_context({RHM: driven})))


def test_check_runs_judges_a_relative_run_from_its_base_and_ends_without_building_it(monkeypatch):
    """A 10,001-point relative run is refused, or passed, from its base and ends: no run is built."""
    def no_run(*_args):
        raise AssertionError("check_runs built the run")

    monkeypatch.setattr(rules, "parse_scan_steps", no_run)
    empty = _snapshot()
    del empty[STH]
    with pytest.raises(PlanRefused, match="steps relative to A3") as caught:
        rules.check_runs(_plan("A3 0 100 0.01", rel1=True), empty)
    assert caught.value.command == 1
    driven = AxisPolicy(CurvatureMode.HELD, CurvatureAxis(min_radius_m=1.5, max_radius_m=5.0))
    with pytest.raises(PlanRefused, match="mechanical minimum"):
        rules.check_runs(_plan("rhm -1 9 0.001", ctx=_context({RHM: driven}), rel1=True),
                         _snapshot(**{RHM: 2.0}))
    rules.check_runs(_plan("rhm -1 1 0.5", ctx=_context({RHM: driven}), rel1=True),
                     _snapshot(**{RHM: 3.0}))   # 2.0 .. 4.0 m: inside the travel


def test_check_runs_judges_the_value_beside_zero_as_expand_does():
    """A run starting at zero exempts zero itself, not the nonzero values beside it."""
    driven = AxisPolicy(CurvatureMode.HELD, CurvatureAxis(min_radius_m=1.5, max_radius_m=5.0))
    plan = _plan("rhm -2 3 0.001", ctx=_context({RHM: driven}), rel1=True)
    snapshot = _snapshot(**{RHM: 2.0})
    with pytest.raises(PlanRefused) as judged:
        rules.check_runs(plan, snapshot)
    with pytest.raises(PlanRefused) as ran:
        expand(plan, snapshot)
    assert str(judged.value) == str(ran.value)
    assert "0.001 m is tighter than the mechanical minimum of 1.5 m" in str(judged.value)


# ------------------------------------------------- the pre-plan pair judgements

# The 68 pairs (of 153) the controller's hand pair rules refused before the plan
# replaced them (_check_scan_parameter_conflict, deleted in S3.2b), recorded from
# those rules as a table: one row per first command, by its first alias. Every
# other pair of these 17 scannable quantities they allowed.
SCANNABLE_ORDER = ("A2", "A3", "A4", "A6", "sgl", "sgu", "H", "K", "L", "qx", "qy", "qz",
                   "deltaE", "rhm", "rvm", "rha", "rva")
PRE_PLAN_REFUSED = {
    "A2": ("A2", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "A3": ("A3", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "A4": ("A4", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "A6": ("A6", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "sgl": ("sgl", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "sgu": ("sgu", "H", "K", "L", "qx", "qy", "qz", "deltaE"),
    "H": ("H", "qx", "qy", "qz"),
    "K": ("K", "qx", "qy", "qz"),
    "L": ("L", "qx", "qy", "qz"),
    "qx": ("qx",), "qy": ("qy",), "qz": ("qz",), "deltaE": ("deltaE",),
    "rhm": ("rhm",), "rvm": ("rvm",), "rha": ("rha",), "rva": ("rva",),
}


def test_every_pair_refused_before_the_plan_is_refused_and_nothing_allowed_newly_is():
    """Every scannable pair through build_plan, against the pre-plan verdicts.

    No deliberate difference: the old slot conflicts (Q with HKL, an arc or an
    angle beside a Q-side command, one quantity twice) are exactly the pairs
    whose second command is a calculation's output or a duplicate.
    """
    assert SCANNABLE_ORDER == tuple(q.aliases[0] for q in QUANTITIES
                                    if q.scannable and not q.id.startswith("slit."))
    refused = {frozenset((a, b)) for a, row in PRE_PLAN_REFUSED.items() for b in row}
    assert sum(len(row) for row in PRE_PLAN_REFUSED.values()) == len(refused) == 68
    for a, b in itertools.combinations_with_replacement(SCANNABLE_ORDER, 2):
        try:
            _plan(f"{a} 1 2 1", f"{b} 1 2 1")
            new = None
        except PlanRefused as refusal:
            new = str(refusal)
        assert (frozenset((a, b)) in refused) == bool(new), (a, b, new)


def test_slit_scans_are_the_one_deliberate_difference():
    """Before the plan every slit scan was refused; a bound one now sits beside any command."""
    for other in ("H 1 2 1", "A3 1 2 1", "rhm 1 2 1", "qx 1 2 1", "A2 1 2 1", ""):
        _plan(other, "pre_sample_hgap 10 30 10")
    with pytest.raises(PlanRefused, match="pre_sample_hgap"):
        _plan("pbl_hgap 0.01 0.03 0.01")   # the old metre-valued name, refused with its replacement


# --------------------------------------------- against PUMA's solver and state

def _solver(instrument_id):
    """(build, snapshot) for one instrument's real solver: the state, vals and context of a launch."""
    pytest.importorskip("mcstasscript")
    import instruments.builtin  # noqa: F401  (registers the built-in instruments)
    from instruments.registry import get_instrument
    from tavi.orientation import lock_plane
    from tavi.sample_mount import SampleMount

    spec = importlib.util.spec_from_file_location(
        "solver_baseline_cases", Path(__file__).resolve().parent / "data" / "solver_baseline_cases.py")
    cases = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cases)
    plugin = get_instrument(instrument_id)
    descriptor = plugin.descriptor()

    def build(lock=False, engine="mcstas", **overrides):
        base = plugin.default_state()
        base.sample_mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90)
        if lock:
            tilts = lock_plane(base.goniometer, base.sample_mount.mounted_basis,
                               (1, 0, 0), (0, 1, 0.2))
            base.plane_lock = {"hkl_u": [1.0, 0.0, 0.0], "hkl_v": [0.0, 1.0, 0.2],
                               "tilts": tilts}
        vals = cases._launch_vals(descriptor, rhm=3.0, rvm=1.0, rha=2.0, rva=1.0, **overrides)
        state = plugin.scan_config(base, vals, None, {}, base.sample_mount)
        return state, vals, context_from_state(state, vals, plugin.capabilities(), engine)

    def snapshot(vals, **fields):
        """The launch snapshot as S3.2 will take it: the vals under canonical IDs."""
        internal = {"H": 1.0, "K": 0.3, "L": 0.2, "deltaE": 2.0, "qx": 1.5, "qy": 0.3,
                    "qz": 0.2, "mtt": 41.0, "stt": -70.0, "omega": 20.0, "att": 41.0,
                    "sgl": 1.0, "sgu": -1.0, **vals, **fields}
        return public_values(internal, descriptor.slits)

    return build, snapshot


@pytest.fixture(scope="module")
def puma():
    return _solver("puma")


@pytest.fixture(scope="module", params=["puma", "in8", "in12", "panda"])
def solver(request):
    return _solver(request.param)


def _reached(plan, qid):
    producer = {out: rule for rule in plan.rules for out in rule.outputs}
    return {out for out in producer if qid in rules._closure(out, producer)[0]}


def _bump(qid):
    if qid in HKL or qid in Q:
        return 0.05
    if qid.endswith("_m"):
        return 0.4
    return 1.5


@pytest.mark.parametrize("cmds, overrides", [
    (("H 1 1.1 0.1", "deltaE 1 3 2"), {"K_fixed": "Kf Fixed"}),
    (("H 1 1.1 0.1", "deltaE 1 3 2"), {"K_fixed": "Ki Fixed"}),
    (("qx 1.4 1.6 0.2", ""), {"curvature_modes": {"rhm": CurvatureMode.AUTOFOCUS,
                                                  "rha": CurvatureMode.AUTOFOCUS}}),
    (("A3 19 21 1", "A6 40 42 2"), {}),
])
def test_declared_dependencies_hold_on_the_real_solver(solver, cmds, overrides):
    """Moving one input changes only the outputs whose declared dependencies reach it, and
    moves at least one of them."""
    build, snapshot = solver
    state, vals, ctx = build(**overrides)
    plan = build_plan([(cmds[0], False), (cmds[1], False)], ctx)
    point = expand(plan, snapshot(vals)).points[0]
    before = evaluate(plan, point, state)
    outputs = [out for rule in plan.rules for out in rule.outputs]
    for qid in point:
        after = evaluate(plan, {**point, qid: point[qid] + _bump(qid)}, state)
        moved = {out for out in outputs
                 if not math.isclose(after[out], before[out], rel_tol=1e-9, abs_tol=1e-9)}
        reached = _reached(plan, qid)
        assert moved <= reached, (qid, moved - reached)
        if reached:
            assert moved, (qid, "reaches outputs it does not move")


def test_arcs_follow_q_alone_and_the_fixed_side_holds_its_crystal(puma):
    build, snapshot = puma
    for side, held in (("Kf Fixed", ATT), ("Ki Fixed", MTT)):
        state, vals, ctx = build(K_fixed=side)
        plan = build_plan([("H 1 1.1 0.1", False), ("deltaE 1 3 2", False)], ctx)
        a, b = expand(plan, snapshot(vals)).points[:3:2]   # same H, transfer 1 then 3
        before, after = evaluate(plan, a, state), evaluate(plan, b, state)
        assert max(abs(before[SGL]), abs(before[SGU])) > 1.0, "the point must tilt the arcs"
        for qid in (SGL, SGU, held):
            assert after[qid] == pytest.approx(before[qid], abs=1e-9), (side, qid)
        assert after[STH] != pytest.approx(before[STH], abs=1e-6)


def test_context_from_state_reads_the_module_fixing_puma_mono_radii(puma):
    build, _snapshot_ = puma
    state, vals, ctx = build(modules={"nmo": "Both", "v_selector": False})
    assert ctx.fixed_side == "Kf" and ctx.fixed_energy_mev == 14.7
    assert {"slit.post_mono.horizontal_gap_mm", GAP, "slit.pre_sample.vertical_gap_mm",
            "slit.detector.horizontal_gap_mm"} <= ctx.inputs
    assert not ctx.curvature[RHM].hardware.driven
    refusal = _refused("rhm 2 3 0.5", ctx=ctx)
    assert str(refusal).startswith("The hardware holds rhm (mono horizontal radius) at 0 m "
                                   "(NMO installed")
    # Every PUMA aperture is bound (its plugin's ParameterSpec bindings), so it plans.
    assert ctx.slit_bindings == {"slit.post_mono.horizontal_gap_mm", GAP,
                                 "slit.pre_sample.vertical_gap_mm",
                                 "slit.detector.horizontal_gap_mm"}
    plan = build_plan([("pre_sample_hgap 10 20 10", False), ("", False)], ctx)
    assert (plan.calculation, plan.provenance[GAP].role) == (MOTORS, SCANNED)


def test_the_lock_relation_not_travel_refuses_grid_points_off_the_plane(puma):
    build, snapshot = puma
    state, vals, ctx = build(lock=True)
    plan = build_plan([("H 1 1.1 0.1", False), ("K 0 1 0.5", False)], ctx)
    points = expand(plan, snapshot(vals, L=0.1, deltaE=0.0)).points
    checks = [check_point(plan, p, state) for p in points]
    for point, check in zip(points, checks):
        on_plane = math.isclose(point["l"], 0.2 * point["k"])
        assert check.feasible == on_plane, (point["h"], point["k"], check.reason)
        if on_plane:
            assert check.requested_q is not None
            assert check.realized_q == pytest.approx(check.requested_q, abs=1e-6)
        else:
            assert "out of the locked scattering plane (1 0 0)/(0 1 0.2)" in check.reason
            assert "travel" not in check.reason
    assert sum(c.feasible for c in checks) == 2


def test_a_locked_point_within_tolerance_records_the_q_asked_and_the_q_realized(puma, tmp_path):
    """Off the plane by less than the lock tolerance: it runs at its projection, and both the
    check and the saved point keep the Q asked for beside the in-plane Q the stage reaches."""
    from instruments.tas_runtime import compute_scan_snapshot
    from tavi.orientation import LOCKED_PLANE_TOLERANCE_Q

    build, snapshot = puma
    state, vals, ctx = build(lock=True)
    plan = build_plan([("H 1 1 1", False), ("", False)], ctx)
    point = expand(plan, snapshot(vals, K=0.5, L=0.1001, deltaE=0.0)).points[0]
    check = check_point(plan, point, state)
    assert check.feasible
    gap = max(abs(a - b) for a, b in zip(check.requested_q, check.realized_q))
    assert 1e-6 < gap < LOCKED_PLANE_TOLERANCE_Q
    metadata = compute_scan_snapshot(plan, point, 0, state, vals, str(tmp_path)).metadata
    assert metadata["requested_q_inv_angstrom"] == pytest.approx(check.requested_q)
    assert metadata["realized_q_inv_angstrom"] == pytest.approx(check.realized_q)


def test_check_point_solves_a_locked_point_once(puma, monkeypatch):
    """Feasibility and the lock's realized Q come from one solve of the point's geometry."""
    from instruments import tas_runtime

    build, snapshot = puma
    state, vals, ctx = build(lock=True)
    plan = build_plan([("H 1 1 1", False), ("", False)], ctx)
    point = expand(plan, snapshot(vals, K=0.5, L=0.1, deltaE=0.0)).points[0]
    solves = []
    real = tas_runtime._solve_point_geometry

    def counting(*args, **kwargs):
        solves.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(tas_runtime, "_solve_point_geometry", counting)
    monkeypatch.setattr(rules, "_solve_point_geometry", counting)
    assert check_point(plan, point, state).feasible
    assert len(solves) == 1, len(solves)


def test_the_analytic_engine_refuses_a_transmitting_point_mcstas_runs_it(puma):
    build, snapshot = puma
    for engine, feasible in (("mcstas", True), ("deterministic", False)):
        state, vals, ctx = build(engine=engine)
        plan = build_plan([("A3 20 21 1", False), ("", False)], ctx)
        point = expand(plan, snapshot(vals, stt=0.0)).points[0]
        check = check_point(plan, point, state)
        assert check.feasible is feasible, engine
        if not feasible:
            assert check.kind == "transmission" and check.transmission == ("sample",)


def test_a_scan_at_the_maximum_plans_without_expanding(monkeypatch):
    """100,000 points is the largest plan: built from the commands' closed-form counts, never run."""
    def no_run(*_args):
        raise AssertionError("a plan at the maximum built its run")

    monkeypatch.setattr(rules, "parse_scan_steps", no_run)
    assert _plan("A3 0 999 1", "A4 0 99 1").calculation == MOTORS      # 1000 x 100
    assert _plan("A3 0 99999 1").calculation == MOTORS                 # 100,000 alone


def test_a_scan_over_the_maximum_is_refused_naming_the_count_before_any_run(monkeypatch):
    def no_run(*_args):
        raise AssertionError("a refused scan built its run")

    monkeypatch.setattr(rules, "parse_scan_steps", no_run)
    started = time.perf_counter()
    single = _refused("A3 0 100 0.000001")
    assert time.perf_counter() - started < 1.0
    assert str(single) == "This scan has 100,000,001 points; the maximum is 100,000."
    assert single.command == 1 and single.quantity == "sample_rotation_deg"
    assert _refused("", "A3 0 100000 1").command == 2
    assert str(_refused("A3 0 100000 1")) == "This scan has 100,001 points; the maximum is 100,000."
    product = _refused("A3 0 999 1", "A4 0 100 1")                     # 1000 x 101, each command under
    assert product.command is None
    assert str(product) == "This scan has 101,000 points; the maximum is 100,000."
