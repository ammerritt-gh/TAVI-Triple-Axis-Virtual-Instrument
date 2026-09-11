"""Packet slice 10, defect 2: the literal travel check does not know about
relative mode.

``_validate_single_scan_command``'s curvature-travel check compares a scan
command's LITERAL start/end text to a driven axis's declared mechanical
travel. That is correct for an absolute command but wrong for a relative one,
whose literal numbers are OFFSETS from the current radius, not the requested
radii themselves. On PUMA (rhm min_radius_m = 2.0, current rhm = 2.5), the
relative command ``rhm 0.5 1.0 0.5`` requests 3.0-3.5 m (legal, and the
expanded manifest correctly accepts it) but the literal check sees 0.5/1.0,
below the 2.0 m minimum, and hard-refused it -- a false reject, introduced by
the same commit that fixed the mirror-image false ACCEPT
(``tests/test_curvature_relative_scan_travel.py``).

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
    """RED FIRST: today the literal check sees the bare offsets 0.5/1.0,
    below PUMA's 2.0 m minimum, and hard-refuses a scan that is actually
    perfectly legal (it expands to 3.0-3.5 m). Fixed: a relative command's
    literal endpoints are never compared to mechanical travel here."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id

        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_IN_TRAVEL, "", mono, ana, relative_1=True,
        )
        assert hard == [], (
            f"a relative command whose real expansion (3.0-3.5 m off "
            f"rhm={_CURRENT_RHM}) is well inside PUMA's 2.0 m minimum must "
            f"not be hard-blocked by a check comparing its bare offsets to "
            f"that minimum: {hard}"
        )


def test_7_the_same_command_absolute_is_still_refused_on_its_literal_values():
    """Not relative: 0.5 and 1.0 ARE the requested radii, both below PUMA's
    2.0 m minimum -- the literal check must still hard-block, exactly as
    before. The false-reject fix must not weaken the absolute case, which has
    no other check while the operator is typing."""
    with _controller("puma") as ctrl:
        mono, ana = ctrl.descriptor.mono_crystals[0].id, ctrl.descriptor.ana_crystals[0].id

        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_IN_TRAVEL, "", mono, ana, relative_1=False,
        )
        assert hard, "an absolute rhm 0.5..1.0 m must still be hard-blocked"
        assert "rhm" in hard[0]


def test_8_the_branch_original_worked_example_is_still_refused():
    """The false-accept this branch already fixed (packet slice 7): relative
    'rhm -2.4 -2.0 0.2' off rhm=2.5 really requests 0.1-0.5 m, well below
    PUMA's 2.0 m minimum. That refusal lives in the expanded manifest
    (``validate_scan_launch_state`` / ``_curvature_violation``), which this
    slice's fix does not touch -- only ``_validate_single_scan_command``'s
    literal check changed. Pinned here through the REAL PUMA controller (not
    the manifest unit test's fake stand-in) so the two fixes are proven to
    coexist, not merely asserted to.

    The false-accept fix and the false-reject fix are the two directions of
    one rule: a change that silently traded one for the other would still
    pass every OTHER test in this module while failing this one.
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

        # And the literal-only preflight is, by construction, blind to it --
        # pinned so a future change cannot "fix" this by mistake and hide
        # the fact that the manifest is what is actually doing the work.
        hard, _ = ctrl._scan_command_issues(
            _RELATIVE_CMD_OUT_OF_TRAVEL, "", mono, ana, relative_1=True,
        )
        assert hard == [], (
            "the real preflight's literal check is not the mechanism that "
            "refuses this -- the manifest is; this pins that assumption"
        )
