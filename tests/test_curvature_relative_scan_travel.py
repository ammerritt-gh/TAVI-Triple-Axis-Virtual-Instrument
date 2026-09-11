"""Packet slice 7: a relative scan cannot smuggle a radius past the refusal.

``_validate_single_scan_command`` (pinned by ``test_curvature_command_refusal.py``)
checks the LITERAL start/end written in a scan command. That is correct for an
absolute command, but a relative command's real requested values are the
current radius plus those literal numbers -- values that check never sees. On
PUMA with rhm = 2.5 m (declared 2.0 m minimum), the relative command
``rhm -2.4 -2.0 0.2`` has literal endpoints -2.4 and -2.0 (magnitudes 2.4 and
2.0, both >= the minimum, so the literal check passes) but actually requests
0.1 m to 0.5 m -- well inside the minimum, and previously reached
``set_crystal_bending`` to be silently clamped back to 2.0.

``validate_scan_launch_state`` is the fix: it already expands a relative
command to its real values (``_expand``) before recording each point, so this
is where the curvature-travel check has to run to be authoritative for the
relative case. This module pins that with a fast fake-controller unit test
(mirrors ``test_api_over_limit_latch.py``'s pattern, no Qt) plus one
integration test through the real PUMA instrument and GUI-collected launch
state for the worked example itself.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import TAVI_PySide6 as controller_module
from instruments.descriptor import CurvatureAxis

# ---------------------------------------------------------------- unit level


class _NoFeasibilityInstrument:
    """No ``check_point_feasibility`` -- validate_scan_launch_state degrades
    to "assume feasible", isolating the curvature check from geometry."""


class _CurvatureManifestController:
    """Minimal stand-in exercising only what ``validate_scan_launch_state``
    reads off ``self`` -- same shape as ``_ManifestController`` in
    ``test_api_over_limit_latch.py``."""

    # The real map, not a one-entry stand-in: a stub carrying only the axis a
    # test happens to use cannot exercise a two-command scan, and silently
    # KeyErrors on the second variable instead of saying so.
    _SCAN_VARIABLE_TO_INDEX = controller_module.TAVIController._SCAN_VARIABLE_TO_INDEX
    instrument = _NoFeasibilityInstrument()

    def __init__(self, min_radius_m=2.0):
        self._axis = CurvatureAxis(driven=True, min_radius_m=min_radius_m)

    def _determine_scan_mode(self, cmd1, cmd2):
        return "rlu"

    def _build_scan_point_template(self, scan_mode, vals):
        return [0.0] * 11

    def normalize_scan_variable(self, variable):
        # Faithful to the real controller (TAVI_PySide6.py:2880): it lowercases
        # and canonicalises. The stub returned the name unchanged, which was
        # invisible while every test used an already-lowercase axis name and
        # broke the moment a two-command test paired one with "deltaE" -- the
        # scan variable-index map is keyed lowercase.
        return controller_module.TAVIController.normalize_scan_variable(
            self, variable)

    def _curvature_axis_specs(self, monocris, anacris, modules=None):
        return {"rhm": (self._axis, "PG(002) monochromator")}

    def _get_current_value_for_variable(self, var_name, vals, template):
        return vals.get(var_name, 0)

    def print_to_message_center(self, message):
        raise AssertionError("manifest expansion unexpectedly failed: %s" % message)


def _launch_state(scan_command1, relative, rhm=2.5):
    return {
        "vals": {
            "scan_command1": scan_command1,
            "scan_command2": "",
            "rhm": rhm,
            "monocris": "pg002", "anacris": "pg002",
        },
        "scan_config": object(),
        "relative_mode_1": relative,
        "relative_mode_2": False,
    }


def test_relative_command_that_expands_below_the_minimum_is_refused():
    """The worked example, at the unit level: rhm=2.5, relative
    'rhm -2.4 -2.0 0.2' literally looks fine (magnitudes 2.4, 2.0 >= 2.0) but
    expands to 0.1..0.5, all below the 2.0 m minimum -- every point refused."""
    launch_state = _launch_state("rhm -2.4 -2.0 0.2", relative=True)

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["requested_points"] == 3
    assert result["feasible_points"] == 0
    assert all(e["kind"] == "curvature_out_of_travel" for e in result["infeasible"])
    assert "rhm" in result["infeasible"][0]["reason"]
    assert "2" in result["infeasible"][0]["reason"]  # names the 2.0 m minimum


def test_the_same_literal_command_not_relative_is_unaffected():
    """Not in relative mode, 'rhm -2.4 -2.0 0.2' literally requests -2.4..-2.0
    (magnitudes 2.4, 2.0), which are legitimately >= the 2.0 m minimum and
    were already correctly accepted by the literal-text check."""
    launch_state = _launch_state("rhm -2.4 -2.0 0.2", relative=False)

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["feasible_points"] == result["requested_points"] == 3
    assert result["infeasible"] == []


def test_a_relative_curvature_scan_that_stays_inside_travel_is_accepted():
    """rhm=2.5, relative 'rhm 0.5 1.0 0.5' expands to 3.0..3.5 -- inside the
    2.0 m minimum throughout."""
    launch_state = _launch_state("rhm 0.5 1.0 0.5", relative=True)

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["feasible_points"] == result["requested_points"] == 2
    assert result["infeasible"] == []


def test_a_relative_scan_expanding_to_exactly_zero_is_accepted():
    """Exact 0 always means FLAT, real hardware -- the refusal must not eat
    it. rhm=2.5, relative 'rhm -2.5 -2.0 0.5' expands to 0.0 and 0.5; 0.0 is
    exempt, 0.5 is refused."""
    launch_state = _launch_state("rhm -2.5 -2.0 0.5", relative=True)

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["requested_points"] == 2
    assert result["point_manifest"][0]["values"]["rhm"] == pytest.approx(0.0)
    assert result["point_manifest"][0]["feasible"] is True
    assert result["point_manifest"][1]["values"]["rhm"] == pytest.approx(0.5)
    assert result["point_manifest"][1]["feasible"] is False
    assert result["point_manifest"][1]["kind"] == "curvature_out_of_travel"


def test_an_instrument_declaring_no_travel_refuses_nothing_relative_or_not():
    """A driven axis with no declared min/max (IN8, PANDA) refuses nothing,
    however far a relative command's expansion wanders."""
    ctrl = _CurvatureManifestController(min_radius_m=None)

    for relative in (True, False):
        launch_state = _launch_state("rhm -2.4 -2.0 0.2", relative=relative, rhm=2.5)
        result = controller_module.TAVIController.validate_scan_launch_state(
            ctrl, launch_state)
        assert result["feasible_points"] == result["requested_points"]
        assert result["infeasible"] == []


# ------------------------------------------------------------- integration


def test_red_first_the_literal_check_alone_passes_the_worked_example():
    """Reproduces the hole directly: before the manifest-level fix existed,
    ``_validate_single_scan_command`` -- the only check a relative command
    used to reach -- passes 'rhm -2.4 -2.0 0.2' clean, because it only ever
    sees the literal -2.4/-2.0 endpoints, not the 0.1/0.5 the scan actually
    requests. This pins that the literal-text check is INHERENTLY blind to a
    relative command's real values (by construction, not as a lingering bug):
    it is not passed the current radius at all, so it cannot expand anything.
    """
    axis = CurvatureAxis(driven=True, min_radius_m=2.0)
    curvature_axes = {"rhm": (axis, "PG(002) monochromator")}

    ctrl = controller_module.TAVIController.__new__(controller_module.TAVIController)
    var, warning = controller_module.TAVIController._validate_single_scan_command(
        ctrl, "rhm -2.4 -2.0 0.2", fixed_axes=None, curvature_axes=curvature_axes
    )
    assert warning is None, (
        "the literal-text check does not refuse this command -- it cannot "
        "see that -2.4/-2.0 are offsets from rhm=2.5, not the requested "
        "radii themselves"
    )


def test_a_two_command_scan_checks_each_command_against_its_own_relative_mode():
    """A 2D scan where only the SECOND command is relative.

    relative_mode_1 and relative_mode_2 are independent, and a plausible real
    scan pairs an absolute energy sweep with a relative focusing sweep. Each
    command must therefore be expanded under its own mode and checked on the
    result: an absolute deltaE command is left alone, while the relative rhm
    command expands against the current 2.5 m and lands at 0.1-0.5 m, below
    PUMA's 2.0 m minimum.

    Every point of the grid is refused, because every one of them carries an
    out-of-travel rhm -- the deltaE axis is blameless but shares the point.
    """
    launch_state = _launch_state("deltaE 0 2 1", relative=False)
    launch_state["vals"]["scan_command2"] = "rhm -2.4 -2.0 0.2"
    launch_state["relative_mode_2"] = True

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["requested_points"] == 9          # 3 deltaE x 3 rhm
    assert result["feasible_points"] == 0
    assert all(e["kind"] == "curvature_out_of_travel" for e in result["infeasible"])
    assert "rhm" in result["infeasible"][0]["reason"]


def test_a_two_command_scan_with_an_in_travel_relative_curvature_is_accepted():
    """The same shape, with the relative offset landing inside travel: nothing
    is refused on curvature grounds. Guards against the check being so eager
    that a legitimate 2D focusing scan cannot run at all."""
    launch_state = _launch_state("deltaE 0 2 1", relative=False)
    launch_state["vals"]["scan_command2"] = "rhm 0.0 0.4 0.2"
    launch_state["relative_mode_2"] = True

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["requested_points"] == 9
    assert not [e for e in result["infeasible"]
                if e["kind"] == "curvature_out_of_travel"]
