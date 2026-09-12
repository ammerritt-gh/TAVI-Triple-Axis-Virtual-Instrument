"""An invalid module option must not produce flat crystals with missing optics."""
import contextlib
import io
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from PySide6.QtWidgets import QApplication
    import instruments.builtin
    from instruments.registry import get_instrument, available_instruments
    from tavi.api_server import ApiError
    import TAVI_PySide6 as cm
    app = QApplication.instance() or QApplication([])
    with contextlib.redirect_stdout(io.StringIO()):
        plugin = get_instrument("puma")
        window = cm.TAVIMainWindow(
            plugin.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id="puma", save_selection=lambda _id: None)
        ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
        try:
            request = {"H": 1.0, "scan_command1": "deltaE 0 1 1",
                       "modules": {"nmo": "vertical", "v_selector": False}}
            try:
                launch = ctrl.build_api_launch_state(request)
            except ApiError as exc:
                assert exc.status == 400, f"Unrelated API error: {exc}"
                print(f"Invalid NMO option refused: {exc}", file=sys.__stdout__)
                return
            cfg = launch["scan_config"]
            radii = cfg.ideal_curvature("pg002", "pg002", 20.5835, 20.5835)
            built = plugin.build(cfg, False, {}, 1000)
            names = [component.name for component in built.component_list]
            requested_state = cfg.NMO_installed
            mono_flat = radii["rhm"] == radii["rvm"] == 0.0
            mirrors = [n for n in names if n in
                       ("vertical_focusing_NMO", "horizontal_focusing_NMO")]
            slit = "NMO_slit" in names
        finally:
            ctrl.shutdown()
            window.deleteLater()
            app.processEvents()
    print(f"Accepted nmo={requested_state!r}; rhm={radii['rhm']}; rvm={radii['rvm']}")
    print(f"NMO slit present={slit}; focusing mirrors={mirrors}")
    assert not (mono_flat and slit and not mirrors), (
        "Invalid module option accepted: NMO policy flattens both monochromator planes, "
        "but build contains the aperture and no focusing optic")


if __name__ == "__main__":
    run(check)
