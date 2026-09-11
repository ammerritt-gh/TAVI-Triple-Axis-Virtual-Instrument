"""Packet slice 10 / D14 / D22: the preflight now expands a relative curvature
command against its current value instead of comparing its literal offsets
(or ignoring it) -- one check for both absolute and relative commands.

``_validate_single_scan_command``'s curvature-travel check used to compare a
scan command's LITERAL start/end text to a driven axis's declared mechanical
travel, correct only for an absolute command: a relative command's literal
numbers are OFFSETS from the current radius, not the requested radii
themselves. On PUMA (rhm min_radius_m = 2.0, current rhm = 2.5), the relative
command ``rhm 0.5 1.0 0.5`` requests 3.0-3.5 m (legal) while
``rhm -2.4 -2.0 0.2`` requests 0.1-0.5 m (illegal) -- a check that only ever
saw the literal numbers could not tell these apart and used to skip relative
commands entirely (D22), leaving the second case unblocked on the GUI Run
path.

These tests exercise the REAL preflight gate (``_scan_command_issues`` /
``_validate_single_scan_command``), shared verbatim by the GUI Run button and
the remote API, through the real PUMA controller and descriptor -- not a
manifest-level unit stub.
"""
import contextlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


# PUMA declares rhm min_radius_m = 2.0.
_RELATIVE_CMD_IN_TRAVEL = "rhm 0.5 1.0 0.5"      # current 2.5 -> expands to 3.0-3.5
_RELATIVE_CMD_OUT_OF_TRAVEL = "rhm -2.4 -2.0 0.2"  # current 2.5 -> expands to 0.1-0.5
_CURRENT_RHM = 2.5


def test_6_relative_command_that_expands_in_travel_is_accepted_by_the_real_preflight():
    """A relative command whose real expansion (3.0-3.5 m off rhm=2.5) is
    inside PUMA's 2.0 m minimum must not be hard-blocked, given the current
    radius to expand against."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id

        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_IN_TRAVEL, "", mono, ana, relative_1=True,
            current_values={"rhm": _CURRENT_RHM},
        )
        assert hard == [], (
            f"a relative command whose real expansion (3.0-3.5 m off "
            f"rhm={_CURRENT_RHM}) is well inside PUMA's 2.0 m minimum must "
            f"not be hard-blocked: {hard}"
        )


def test_7_the_same_command_absolute_is_still_refused_on_its_literal_values():
    """Not relative: 0.5 and 1.0 ARE the requested radii, both below PUMA's
    2.0 m minimum -- the literal check must still hard-block, exactly as
    before."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id

        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_IN_TRAVEL, "", mono, ana, relative_1=False,
        )
        assert hard, "an absolute rhm 0.5..1.0 m must still be hard-blocked"
        assert "rhm" in hard[0]


def test_8_the_branch_original_worked_example_is_refused_by_the_preflight_too():
    """D14/D22: relative 'rhm -2.4 -2.0 0.2' off rhm=2.5 really requests
    0.1-0.5 m, well below PUMA's 2.0 m minimum. RED FIRST (D22): the
    preflight (``_scan_command_issues``, shared by the GUI Run button and the
    API) used to be blind to this -- it skipped a relative command's
    curvature check entirely and only the expanded manifest
    (``validate_scan_launch_state``) caught it. Now both refuse it, given the
    current radius to expand against.
    """
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id

        launch_state = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rhm": _CURRENT_RHM,
            "scan_command1": _RELATIVE_CMD_OUT_OF_TRAVEL,
        })
        # build_api_launch_state hard-codes API launches as absolute; this
        # test asks the question a relative GUI/API request would actually
        # pose, so the flag is set the way a relative request would set it.
        launch_state["relative_mode_1"] = True

        result = ctrl.validate_scan_launch_state(launch_state)

        assert result["feasible_points"] == 0, result
        assert result["infeasible"], "the worked example must still be refused"
        assert all(
            e["kind"] == "curvature_out_of_travel" for e in result["infeasible"]
        ), result["infeasible"]
        assert "rhm" in result["infeasible"][0]["reason"]

        # The preflight itself now refuses the same command, given the
        # current radius -- it is no longer blind to the relative case.
        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_OUT_OF_TRAVEL, "", mono, ana, relative_1=True,
            current_values={"rhm": _CURRENT_RHM},
        )
        assert hard, (
            "the real preflight must refuse a relative command whose "
            "expansion is out of travel, not defer entirely to the manifest"
        )
        assert "rhm" in hard[0]
