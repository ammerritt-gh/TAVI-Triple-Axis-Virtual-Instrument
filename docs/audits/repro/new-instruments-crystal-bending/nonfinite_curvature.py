"""Non-finite held curvature must be refused before McStas parameters exist."""
import contextlib
import io
import math
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    from instruments.registry import get_instrument, available_instruments
    import TAVI_PySide6 as cm
    from tavi.api_server import ApiError
    app = QApplication.instance() or QApplication([])
    failures = []
    for name in ("puma", "in8", "in12", "panda"):
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            instrument = get_instrument(name)
            window = cm.TAVIMainWindow(
                instrument.descriptor(), instrument_infos=available_instruments(),
                current_instrument_id=name, save_selection=lambda _id: None)
            ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
            try:
                ctrl.build_api_launch_state(
                    {"H": 1.0, "rhm": 5.0, "scan_command1": "deltaE 0 1 1"})
                try:
                    launch = ctrl.build_api_launch_state(
                        {"H": 1.0, "rhm": "nan", "scan_command1": "deltaE 0 1 1"})
                except ApiError as exc:
                    assert exc.status == 400, f"Unrelated API failure: {exc}"
                    print(f"{name}: refused {exc}", file=sys.__stdout__)
                    continue
                vals = launch["vals"]
                scans = [vals["qx"], vals["qy"], vals["qz"], 0.0,
                         vals["rhm"], vals["rvm"], vals["rha"], vals["rva"], 0, 0, 0]
                feasible, reason = instrument.check_point_feasibility(
                    launch["scan_config"], "momentum", scans, vals)
                assert feasible, reason
                snapshot = instrument.compute_snapshot(
                    (scans, 0), 0, "momentum", launch["scan_config"], vals,
                    str(Path.cwd()), variable_name1="deltaE")
                assert not snapshot.error_flags, snapshot.error_flags
                observed = snapshot.params["rhm_param"]
            finally:
                ctrl.shutdown()
                window.deleteLater()
                app.processEvents()
        print(f"{name}: accepted rhm='nan'; feasible={feasible}; emitted rhm_param={observed}")
        if not math.isfinite(observed):
            failures.append(name)
    assert not failures, f"Non-finite commanded radii reached McStas parameters on {failures}"


if __name__ == "__main__":
    run(check)
