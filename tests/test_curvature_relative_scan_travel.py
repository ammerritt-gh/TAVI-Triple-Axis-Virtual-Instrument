"""Packet slice 7: a relative scan cannot smuggle a radius past the refusal.

Since 714e77a5 both the GUI preflight (``_validate_single_scan_command`` with
``relative`` and ``current_values``) and the API manifest
(``validate_scan_launch_state``) expand a command through one shared helper,
``instruments.tas_runtime.curvature_scan_error``, and check every expanded
radius. On PUMA with rhm = 2.5 m (declared 2.0 m minimum), the relative
command ``rhm -2.4 -2.0 0.2`` requests 0.1 m to 0.5 m and is refused on both
paths; before that commit only the manifest saw the expanded values and the
GUI Run path never called it, so the scan ran silently clamped to 2.0 m.
These tests pin the manifest side; ``test_curvature_relative_preflight.py``
and ``test_curvature_scan_travel_check.py`` pin the preflight side.
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
        # Delegates to the real controller's name-canonicalising method
        # (TAVI_PySide6.py:4337): a naive vals.get(var_name, 0) diverges the
        # moment the normalized variable name is not vals's own key spelling
        # (e.g. "A1" reads vals['mtt'], not a nonexistent vals['A1']) --
        # invisible here only because every earlier test scans "rhm", whose
        # vals key happens to equal the normalized name already.
        return controller_module.TAVIController._get_current_value_for_variable(
            self, var_name, vals, template)

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


def test_relative_a1_scan_uses_the_real_current_value_lookup_not_a_naive_vals_get():
    """D19: the stub's ``_get_current_value_for_variable`` must not diverge
    from the real controller's name-canonicalising method. Every other test
    here scans "rhm", whose vals key happens to already equal the normalized
    variable name, so a naive ``vals.get(var_name, 0)`` looked right by
    accident. "A1" exposes it: ``normalize_scan_variable`` returns "A1", but
    the real lookup reads ``vals['mtt']`` for A1 -- there is no ``vals['A1']``
    -- so the naive version silently uses 0 as the relative base instead of
    the instrument's actual current angle."""
    launch_state = {
        "vals": {
            "scan_command1": "A1 -1 1 1", "scan_command2": "",
            "mtt": 41.167, "rhm": 2.5,
            "monocris": "pg002", "anacris": "pg002",
        },
        "scan_config": object(),
        "relative_mode_1": True, "relative_mode_2": False,
    }

    result = controller_module.TAVIController.validate_scan_launch_state(
        _CurvatureManifestController(), launch_state)

    assert result["per_command"][0]["values"] == pytest.approx(
        [40.167, 41.167, 42.167]
    )


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
