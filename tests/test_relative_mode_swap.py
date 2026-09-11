"""D20: the relative-mode flag must move with a promoted lone command 2.

``run_simulation``'s single-command swap ("only command 2 given -> it
becomes command 1") moved the scan TEXT into command 1's slot but left
``relative_mode_1``/``relative_mode_2`` untouched, so a promoted command ran
under command 1's flag (default False) instead of its own.
``validate_scan_launch_state`` already swapped both; this pins that
``run_simulation`` does the identical swap, through the deterministic
engine (fast: no McStas compile/run) so the actual per-point radius
delivered to snapshot preparation can be read back from
``ScanResult.applied_curvature``.
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
from tavi.scan_jobs import ScanJob  # noqa: E402


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


def test_d20_relative_flag_moves_with_a_promoted_lone_command_2(tmp_path):
    """PUMA rhm=2.5, command 1 empty, command 2 'rhm 0.5 1.0 0.5' with
    Relative-2 on: the real requested values are 3.0, 3.5 (the same values
    ``validate_scan_launch_state`` reports for the command written directly
    into command 1). Covers both settings of the irrelevant Relative-1
    toggle -- it must never matter once command 2 is promoted."""
    with _controller("puma") as ctrl:
        ctrl.output_directory = str(tmp_path)

        # The reference: the identical command run directly as command 1,
        # relative, so its expansion is authoritative for what "correct"
        # looks like.
        reference_launch = ctrl.build_api_launch_state({
            "rhm": 2.5, "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "rhm 0.5 1.0 0.5",
        })
        reference_launch["relative_mode_1"] = True
        manifest = ctrl.validate_scan_launch_state(reference_launch)
        expected_values = manifest["per_command"][0]["values"]
        assert expected_values == pytest.approx([3.0, 3.5])

        for relative_1 in (False, True):
            launch = ctrl.build_api_launch_state({
                "rhm": 2.5, "H": 1.0, "K": 0.0, "L": 0.0,
                "scan_command1": "", "scan_command2": "rhm 0.5 1.0 0.5",
            })
            launch["relative_mode_1"] = relative_1
            launch["relative_mode_2"] = True
            launch["engine"] = "deterministic"

            job = ScanJob(job_id=f"t-d20-rel1-{relative_1}", source="api",
                           launch_state=launch)
            ctrl.run_simulation(launch, job=job)

            result = job.result
            assert result is not None
            rhm_values = [abs(pt["rhm"]) for pt in result.applied_curvature]
            assert rhm_values == pytest.approx(expected_values), (
                f"relative_mode_1={relative_1}: promoted command 2 must run "
                f"under ITS OWN relative flag, not command 1's; got "
                f"{rhm_values}, expected {expected_values}"
            )
