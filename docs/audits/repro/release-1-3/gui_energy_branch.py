"""Energy edits must keep IN8/IN12 on their declared crystal branches.

Run: python docs/audits/repro/release-1-3/gui_energy_branch.py
The adjacent audit sandbox copies production source and confines writes to TEMP.
"""
import sys

sys.dont_write_bytecode = True
from _sandbox import run


def check():
    import contextlib
    import io
    import math
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    import TAVI_PySide6 as cm
    from instruments.registry import available_instruments, get_instrument
    from tavi.neutron_conversions import energy2k, k2angle

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
            for energy_field, angle_field, sense in (
                ("Ei", "mtt", int(plugin.descriptor().geometry.sense_mono)),
                ("Ef", "att", int(plugin.descriptor().geometry.sense_ana)),
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    ctrl.update_angles_from_q()
                    edit = getattr(window.instrument_dock, energy_field + "_edit")
                    edit.setText("12")
                    edit.editingFinished.emit()
                vals = ctrl.get_gui_values()
                actual = vals[angle_field]
                expected = sense * 2 * k2angle(energy2k(12), 3.355)
                print(f"{instrument_id} {energy_field}=12: {angle_field}={actual}, expected {expected:.6f}")
                if not math.isclose(actual, expected, abs_tol=0.001):
                    failures.append((instrument_id, energy_field, actual, expected))
        finally:
            with contextlib.redirect_stdout(io.StringIO()):
                ctrl.shutdown()
                window.deleteLater()
                app.processEvents()
    assert not failures, f"GUI energy edits select the wrong crystal branch: {failures}"


if __name__ == "__main__":
    run(check)
