"""An API angle scan's unpatched angles must describe its active instrument."""
import sys

sys.dont_write_bytecode = True
from _sandbox import run


def check():
    import contextlib
    import io
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    import TAVI_PySide6 as cm
    from instruments.registry import available_instruments, get_instrument

    app = QApplication.instance() or QApplication([])
    failures = []
    for instrument_id in ("in12", "in8"):
        plugin = get_instrument(instrument_id)
        with contextlib.redirect_stdout(io.StringIO()):
            window = cm.TAVIMainWindow(plugin.descriptor(),
                instrument_infos=available_instruments(),
                current_instrument_id=instrument_id, save_selection=lambda _: None)
            ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                launch = ctrl.build_api_launch_state({"scan_command1": "A3 35 36 1"})
                validation = ctrl.validate_scan_launch_state(launch)
            vals = launch["vals"]
            print(instrument_id, "unpatched angles:", {k: vals[k] for k in ("mtt", "stt", "att")})
            print(instrument_id, "infeasible:", validation["infeasible"])
            geo = plugin.descriptor().geometry
            actual = tuple(1 if vals[k] > 0 else -1 for k in ("mtt", "stt", "att"))
            expected = (int(geo.sense_mono), int(geo.sense_sample), int(geo.sense_ana))
            if actual != expected or validation["infeasible"]:
                failures.append((instrument_id, actual, expected))
        finally:
            with contextlib.redirect_stdout(io.StringIO()):
                ctrl.shutdown()
                window.deleteLater()
                app.processEvents()
    assert not failures, f"API angle defaults carry another instrument's branches: {failures}"


if __name__ == "__main__":
    run(check)
