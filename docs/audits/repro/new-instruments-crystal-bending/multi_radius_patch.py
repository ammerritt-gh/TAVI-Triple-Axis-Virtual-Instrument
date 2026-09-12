"""A parameter patch must preserve every explicitly commanded held radius."""
import contextlib
import io
import math
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    from instruments.registry import get_instrument, available_instruments
    import TAVI_PySide6 as cm
    app = QApplication.instance() or QApplication([])
    failures = []
    for name in ("puma", "in8", "in12", "panda"):
        with contextlib.redirect_stdout(io.StringIO()):
            plugin = get_instrument(name)
            window = cm.TAVIMainWindow(
                plugin.descriptor(), instrument_infos=available_instruments(),
                current_instrument_id=name, save_selection=lambda _id: None)
            ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
            try:
                for patch in ({"rhm": 9.0, "rvm": 8.0}, {"rvm": 8.0, "rhm": 9.0}):
                    ctrl.apply_ideal_bending_value("rhm")
                    ctrl.apply_ideal_bending_value("rvm")
                    assert all(ctrl.is_bending_locked(k) for k in patch)
                    direct = ctrl.build_api_launch_state(dict(
                        patch, H=1.0, scan_command1="deltaE 0 1 1"))
                    assert all(direct["vals"][k] == v for k, v in patch.items())
                    applied, errors = ctrl.apply_parameters(patch)
                    assert not errors and applied == patch, (applied, errors)
                    vals = ctrl.get_gui_values()
                    actual = {k: vals[k] for k in patch}
                    assert not any(ctrl.is_bending_locked(k) for k in patch)
                    print(f"{name}: requested={patch}; reported={applied}; held={actual}",
                          file=sys.__stdout__)
                    if not all(math.isclose(actual[k], v) for k, v in patch.items()):
                        failures.append((name, patch, actual))
            finally:
                ctrl.shutdown()
                window.deleteLater()
                app.processEvents()
    assert not failures, f"Explicit radii overwritten while applying one patch: {failures}"


if __name__ == "__main__":
    run(check)
