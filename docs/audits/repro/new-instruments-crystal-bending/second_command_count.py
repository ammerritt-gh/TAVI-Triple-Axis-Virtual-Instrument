"""The preview must count a lone command 2 as the same 1D scan it executes."""
import contextlib
import io
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    from instruments.registry import get_instrument, available_instruments
    import TAVI_PySide6 as cm
    app = QApplication.instance() or QApplication([])
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        plugin = get_instrument("in8")
        window = cm.TAVIMainWindow(
            plugin.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id="in8", save_selection=lambda _id: None)
        ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
        try:
            dock = window.simulation_dock
            dock.scan_command_1_edit.setText("")
            dock.scan_command_2_edit.setText("rva 1 1.2 0.1")
            dock.relative_2_button.setChecked(False)
            ctrl._update_scan_estimates()
            label = dock.point_count_label.text()
            preview = ctrl._count_valid_scan_points("", "rva 1 1.2 0.1")
            reference = ctrl._count_valid_scan_points("rva 1 1.2 0.1", "")
            launch = ctrl._collect_simulation_launch_state()
            assert launch is not None, "Unrelated launch failure"
            ctrl.output_directory = str(Path.cwd() / "output")
            launch["save_folder_input"] = str(Path.cwd() / "output" / "count-probe")
            launch["engine"] = "deterministic"
            emitted = []
            ctrl.scan_initialized.connect(lambda *args: emitted.append(args))
            prepared = []
            ctrl._run_scan_deterministic = lambda *args, **kwargs: prepared.extend(args[2])
            ctrl.run_simulation(launch)
            assert emitted and prepared, "Runtime expansion was not reached"
            mode, values, mask = emitted[-1][:3]
            actual = (sum(mask), len(mask) - sum(mask))
        finally:
            ctrl.shutdown()
            window.deleteLater()
            app.processEvents()
    print(f"IN8 preview label: {label}")
    print(f"command 1 preview={reference}; command 2 preview={preview}")
    print(f"runtime mode={mode}; rva={list(values)}; validity={list(mask)}")
    assert len(prepared) == 3 and actual == (3, 0), "Expected three feasible runtime points"
    assert preview == actual, f"Preview reports {preview}, execution prepares {actual}"


if __name__ == "__main__":
    run(check)
