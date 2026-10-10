"""Packet slice 7: a relative scan cannot smuggle a radius past the refusal.

A relative command's literal numbers are offsets; the radii it requests are
its base plus every offset. The plan's expansion (``instruments.rules.expand``,
the one compile-and-expand every launch runs) reads the base once from the
launch snapshot and checks every expanded radius against the assembly's
travel through ``curvature_scan_error``; one radius out of travel refuses the
whole scan. On PUMA with rhm = 2.5 m (declared 2.0 m minimum), the relative
command ``rhm -2.4 -2.0 0.2`` requests 0.1 m to 0.5 m and is refused.
``test_curvature_relative_preflight.py`` and ``test_curvature_scan_travel_check.py``
pin the GUI preflight side.
"""
import pytest

from instruments.contract import CurvatureMode
from instruments.descriptor import CurvatureAxis
from instruments.rules import (
    ARCS, ATT, DE, HKL, MTT, Q, STH, STT, AxisPolicy, PlanContext, PlanRefused, build_plan,
    expand,
)

RHM = "mono_horizontal_radius_m"


def _context(min_radius_m=2.0):
    axis = CurvatureAxis(driven=True, min_radius_m=min_radius_m)
    return PlanContext(
        engine="mcstas", fixed_side="Kf", fixed_energy_mev=14.7, monocris="pg002",
        anacris="pg002", plane_lock=None,
        curvature={RHM: AxisPolicy(CurvatureMode.HELD, axis, "PG(002) monochromator")},
        inputs=frozenset({*HKL, *Q, DE, MTT, STT, STH, ATT, *ARCS, RHM}),
        observables=frozenset())


def _snapshot(rhm=2.5):
    return {**dict.fromkeys(HKL, 0.0), "h": 1.0, **dict(zip(Q, (1.5, 0.0, 0.0))), DE: 0.0,
            MTT: 41.167, STT: -60.0, STH: 30.0, ATT: 41.167, **dict.fromkeys(ARCS, 0.0),
            RHM: rhm}


def _expand(cmd1, rel1=False, cmd2="", rel2=False, min_radius_m=2.0):
    plan = build_plan([(cmd1, rel1), (cmd2, rel2)], _context(min_radius_m))
    return expand(plan, _snapshot())


def test_relative_command_that_expands_below_the_minimum_is_refused():
    """The worked example: rhm=2.5, relative 'rhm -2.4 -2.0 0.2' literally
    looks fine (magnitudes 2.4, 2.0 >= 2.0) but expands to 0.1..0.5, all below
    the 2.0 m minimum."""
    with pytest.raises(PlanRefused, match="mechanical minimum of 2 m") as refused:
        _expand("rhm -2.4 -2.0 0.2", rel1=True)
    assert "rhm" in str(refused.value) and refused.value.command == 1


def test_the_same_literal_command_not_relative_is_unaffected():
    """Not relative, 'rhm -2.4 -2.0 0.2' requests -2.4..-2.0 (magnitudes 2.4,
    2.0), legitimately >= the 2.0 m minimum."""
    assert _expand("rhm -2.4 -2.0 0.2").values[1] == pytest.approx((-2.4, -2.2, -2.0))


def test_a_relative_curvature_scan_that_stays_inside_travel_is_accepted():
    """rhm=2.5, relative 'rhm 0.5 1.0 0.5' expands to 3.0..3.5."""
    expansion = _expand("rhm 0.5 1.0 0.5", rel1=True)
    assert expansion.values[1] == pytest.approx((3.0, 3.5))
    assert expansion.bases == {1: 2.5}


def test_a_relative_scan_reaching_exactly_zero_is_flat_and_accepted():
    """Exact 0 always means FLAT, real hardware -- the refusal must not eat it:
    rhm=2.5, relative 'rhm -2.5 -2.5 1' is 0.0. Stepping on to 0.5 is refused,
    naming the radius that is."""
    assert _expand("rhm -2.5 -2.5 1", rel1=True).values[1] == pytest.approx((0.0,))
    with pytest.raises(PlanRefused, match="0.5 m is tighter"):
        _expand("rhm -2.5 -2.0 0.5", rel1=True)


def test_a_relative_mono_two_theta_scan_steps_from_its_own_field():
    """'A2' is the mono 2θ: its base is that field's value in the snapshot."""
    assert _expand("A2 -1 1 1", rel1=True).values[1] == pytest.approx((40.167, 41.167, 42.167))


def test_an_instrument_declaring_no_travel_refuses_nothing_relative_or_not():
    """A driven axis with no declared min/max (IN8, PANDA) refuses nothing."""
    for relative in (True, False):
        assert len(_expand("rhm -2.4 -2.0 0.2", rel1=relative, min_radius_m=None).points) == 3


def test_a_two_command_scan_checks_each_command_against_its_own_relative_mode():
    """Only the second command is relative: the absolute deltaE command is left
    alone, the relative rhm command lands at 0.1-0.5 m and refuses the scan."""
    with pytest.raises(PlanRefused, match="mechanical minimum") as refused:
        _expand("deltaE 0 2 1", cmd2="rhm -2.4 -2.0 0.2", rel2=True)
    assert refused.value.command == 2


def test_a_two_command_scan_with_an_in_travel_relative_curvature_is_accepted():
    """The same shape, landing inside travel: all nine points run."""
    expansion = _expand("deltaE 0 2 1", cmd2="rhm 0.0 0.4 0.2", rel2=True)
    assert len(expansion.points) == 9
    assert sorted({round(point[RHM], 9) for point in expansion.points}) == [2.5, 2.7, 2.9]
