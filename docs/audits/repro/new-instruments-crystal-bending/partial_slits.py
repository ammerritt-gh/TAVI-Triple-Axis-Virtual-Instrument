"""A partial slits_mm patch is accepted, then raises KeyError at launch."""
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

    # One declared slit per instrument, patched alone; every other declared
    # slit is omitted. collimation and modules both refill an omitted id from
    # the descriptor before the plugin indexes it -- slits_mm does not.
    one_slit = {"puma": {"vbl_hgap": 50.0}, "in8": {"dbl_hgap": 50.0},
                "in12": {"dbl_hgap": 50.0}, "panda": {"ms1": 50.0}}
    failures = []
    for name in ("puma", "in8", "in12", "panda"):
        instrument = get_instrument(name)
        window = cm.TAVIMainWindow(
            instrument.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id=name, save_selection=lambda _id: None)
        ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
        try:
            patch = {"H": 1.0, "scan_command1": "deltaE 0 1 1",
                     "slits_mm": one_slit[name]}
            try:
                ctrl.build_api_launch_state(patch)
            except ApiError as exc:
                print(f"{name}: refused cleanly ({exc.status} {exc.code})")
                continue
            except KeyError as exc:
                print(f"{name}: KeyError {exc} -- accepted by the parser, "
                      f"unhandled at launch")
                failures.append(name)
                continue
            print(f"{name}: accepted and launched with the omitted slits")
        finally:
            ctrl.shutdown()
            window.deleteLater()
            app.processEvents()

    assert not failures, (
        f"A partial slits_mm patch raises KeyError at launch on {failures}; "
        f"the same shape of request is refilled for collimation and modules"
    )


if __name__ == "__main__":
    run(check)
