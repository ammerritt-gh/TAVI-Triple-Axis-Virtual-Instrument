"""Screenshots of the real TAVI window at the laptop and monitor reference sizes.

Builds the real ``TAVIMainWindow`` and ``TAVIController`` offscreen, resizes
the window to 1108x851 and to 2560x1392, and writes one PNG per size. Run it
from the repository root in the tavi-dev environment (importing Qt directly
hits the delay-load fault noted in AGENTS.md):

    micromamba run -n tavi-dev python tools/ui_snapshots.py --instrument puma

It never touches the real ``config/``: ``TAVI_CONFIG_DIR`` points at a
temporary copy before any ``tavi``/``gui`` import, and the run stops if the
config path does not resolve there. Text is measured and drawn in Segoe UI
9 pt, the real window's font on Windows; the offscreen platform has no font
database of its own. Exit code 0 when every PNG was written, 1 when the window
did not build or a grab was null or the wrong size.
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIZES = ((1108, 851), (2560, 1392))


def _isolate_config():
    """Point TAVI_CONFIG_DIR at a temp copy of config/ (empty if there is none)."""
    tmp = Path(tempfile.mkdtemp(prefix="tavi-ui-snapshots-")) / "config"
    real = REPO_ROOT / "config"
    if real.is_dir():
        shutil.copytree(real, tmp)
    else:
        tmp.mkdir(parents=True)
    os.environ["TAVI_CONFIG_DIR"] = str(tmp)
    return tmp


def _hygiene():
    """The conftest guards, reused from the repository root (as tools/check_tilted_reflection.py)."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        import conftest
    finally:
        sys.path.remove(str(REPO_ROOT))
    conftest.install_no_window_guard()
    if "MCSTAS" not in os.environ:
        resources = conftest._resolve_mcstas_resources()
        if resources:
            os.environ["MCSTAS"] = resources


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instrument", default="puma", help="instrument id (default puma)")
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "ui_snapshots"),
                        help="output folder (default output/ui_snapshots)")
    args = parser.parse_args()

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp_config = _isolate_config()
    _hygiene()
    sys.path.insert(0, str(REPO_ROOT))

    from tavi.local_state import config_path
    resolved = config_path("view_layout.json").resolve()
    if tmp_config.resolve() not in resolved.parents:
        print(f"refusing to run: config resolves to {resolved}, not under {tmp_config}")
        return 1

    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
    if sys.platform == "win32" and font_path.exists():
        if QFontDatabase.addApplicationFont(str(font_path)) < 0:
            print(f"could not load {font_path}")
            return 1
        app.setFont(QFont("Segoe UI", 9))

    import instruments.builtin  # noqa: F401  (registers the built-in instruments)
    import TAVI_PySide6 as cm
    from instruments.registry import available_instruments, get_instrument

    try:
        instrument = get_instrument(args.instrument.lower())
        window = cm.TAVIMainWindow(
            instrument.descriptor(), instrument_infos=available_instruments(),
            current_instrument_id=instrument.id, save_selection=lambda _id: None,
        )
        controller = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
        window.controller = controller
    except Exception as exc:
        print(f"window did not build for {args.instrument!r}: {exc!r}")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    try:
        window.show()
        app.processEvents()  # lets the startup geometry timer fire before any resize
        for width, height in SIZES:
            window.resize(width, height)
            app.processEvents()
            pixmap = window.grab()
            if pixmap.isNull() or (pixmap.width(), pixmap.height()) != (width, height):
                print(f"bad grab at {width}x{height}: null={pixmap.isNull()} "
                      f"size={pixmap.width()}x{pixmap.height()}")
                failures += 1
                continue
            path = out / f"{instrument.id}_{width}x{height}.png"
            if not pixmap.save(str(path)):
                print(f"could not write {path}")
                failures += 1
                continue
            print(path)
    finally:
        controller.shutdown()
        window.deleteLater()
        app.processEvents()
    print(f"output folder: {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
