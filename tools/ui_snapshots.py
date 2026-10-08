"""Screenshots of the real TAVI window at the laptop and monitor reference sizes.

Builds the real ``TAVIMainWindow`` and ``TAVIController`` offscreen, resizes
the window to 1108x851 and to 2560x1392, chooses View > Layout (2, 3 or 4
columns) and View > Column Width (Narrow, Wide), and writes one PNG per size
and combination, named ``<instrument>_<w>x<h>_<N>col_<narrow|wide>.png``.
``--columns auto`` shoots, at each size, what first start would pick for a
screen that wide, and names the picked combination. Run it from the
repository root in the tavi-dev environment (importing Qt directly hits the
delay-load fault noted in AGENTS.md):

    micromamba run -n tavi-dev python tools/ui_snapshots.py --instrument puma --columns all

It never touches the real ``config/``: ``TAVI_CONFIG_DIR`` points at a
temporary copy before any ``tavi``/``gui`` import, and the run stops if the
config path does not resolve there. The copy leaves out ``view_layout.json``,
so the shots show the presets, not a locally saved layout. Text is measured
and drawn in Segoe UI 9 pt, the real window's font on Windows (the offscreen
platform has no font database of its own), and widgets in the style a real
QApplication gets on this machine (``windows11`` on Windows 11), asked of the
platform in a child process; if that fails the shots fall back to the
offscreen default, Fusion, and say so. A preset that cannot fit a size
(4 columns need about 1140 px) grows the window to its minimum, as on screen;
the shot is kept, at the grown size, with a printed note. Exit code 0 when
every PNG was written, 1 when the window did not build or a grab was null or
of a size the window did not have.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIZES = ((1108, 851), (2560, 1392))


def _isolate_config():
    """Point TAVI_CONFIG_DIR at a temp copy of config/ (empty if there is none), less any saved layout."""
    tmp = Path(tempfile.mkdtemp(prefix="tavi-ui-snapshots-")) / "config"
    real = REPO_ROOT / "config"
    if real.is_dir():
        shutil.copytree(real, tmp)
        (tmp / "view_layout.json").unlink(missing_ok=True)  # shoot the presets
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


# Run in a child on the default platform: the style and palette a real
# QApplication gets here, as JSON. It shows nothing.
_PLATFORM_LOOK = """
import json
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
app = QApplication([])
palette = app.palette()
colors = {f"{group.name}.{role.name}": palette.color(group, role).name(QColor.HexArgb)
          for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled)
          for role in QPalette.ColorRole if role != QPalette.NColorRoles}
print(json.dumps({"style": app.style().name(), "palette": colors}))
"""


def _platform_look():
    """(style name, {"<group>.<role>": "#aarrggbb"}) a real QApplication gets here, or (None, None)."""
    env = {key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORM"}
    try:
        done = subprocess.run([sys.executable, "-c", _PLATFORM_LOOK], env=env,
                              capture_output=True, text=True, timeout=120, check=True)
        look = json.loads(done.stdout.strip().splitlines()[-1])
        return look["style"], look["palette"]
    except (subprocess.SubprocessError, OSError, IndexError, ValueError, KeyError) as exc:
        print(f"note: could not ask the platform for its widget style ({exc!r})")
        return None, None


def _text_shows(app):
    """Whether a push button's label is visible in the app's current style, offscreen.

    windows11 draws its controls' text in dark-scheme colours when the
    platform reports no colour scheme, as offscreen does: white on light.
    """
    from PySide6.QtWidgets import QPushButton

    button = QPushButton("Ag Ag Ag")
    button.resize(button.sizeHint())
    image = button.grab().toImage()
    light = [image.pixelColor(x, image.height() // 2).lightness() for x in range(image.width())]
    return max(light) - min(light) > 100  # dark glyphs on a light face


def _apply_look(app, style, colors):
    """Give the offscreen app the platform's style, then its palette (setStyle resets the palette).

    A style that cannot draw readable text offscreen falls back to Fusion,
    with the platform palette, and says so.
    """
    from PySide6.QtGui import QColor, QPalette

    def set_palette():
        if colors:
            palette = app.palette()
            for key, value in colors.items():
                group, role = key.split(".")
                palette.setColor(QPalette.ColorGroup[group], QPalette.ColorRole[role], QColor(value))
            app.setPalette(palette)

    if style is not None and app.setStyle(style) is None:
        print(f"note: style {style!r} is not available offscreen")
    set_palette()
    if not _text_shows(app):
        print(f"note: the {app.style().name()} style draws its controls' text unreadably "
              f"offscreen; shooting in Fusion with the platform palette instead")
        app.setStyle("Fusion")
        set_palette()
    print(f"widget style: {app.style().name()}" + ("" if colors else " (offscreen palette)"))


def _combinations(width, columns, column_width):
    """(columns, column width) pairs to shoot at a window ``width`` px wide."""
    from gui.main_window import LAYOUT_COLUMNS, initial_layout_for_width

    if columns == "auto":
        return [initial_layout_for_width(width)]
    counts = LAYOUT_COLUMNS if columns == "all" else (int(columns),)
    widths = ("narrow", "wide") if column_width == "both" else (column_width,)
    return [(count, mode) for count in counts for mode in widths]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instrument", default="puma", help="instrument id (default puma)")
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "ui_snapshots"),
                        help="output folder (default output/ui_snapshots)")
    parser.add_argument("--columns", choices=("2", "3", "4", "auto", "all"), default="auto",
                        help="View > Layout to shoot; auto: first start's pick at each size "
                             "(default auto)")
    parser.add_argument("--column-width", choices=("narrow", "wide", "both"), default="both",
                        help="View > Column Width to shoot (default both; auto picks its own)")
    args = parser.parse_args()

    tmp_config = _isolate_config()
    _hygiene()
    style, colors = _platform_look()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
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
    _apply_look(app, style, colors)

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

    def trigger(action):
        action.trigger()  # as the View menu does
        for _ in range(3):  # the dock moves and sizes, then each panel's reflow
            app.processEvents()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    try:
        window.show()
        app.processEvents()  # lets the startup timer fire before any resize
        for width, height in SIZES:
            for columns, column_width in _combinations(width, args.columns, args.column_width):
                trigger(window.layout_actions[columns])  # first: the old preset's minimum goes
                window.resize(width, height)
                app.processEvents()
                trigger(window.column_width_actions[column_width])
                trigger(window.layout_actions[columns])  # sized at this window size
                name = f"{instrument.id}_{width}x{height}_{columns}col_{column_width}"
                if (window.width(), window.height()) != (width, height):
                    minimum = window.minimumSizeHint()
                    if minimum.width() <= width and minimum.height() <= height:
                        print(f"bad size for {name}: {window.width()}x{window.height()}")
                        failures += 1
                        continue
                    print(f"note: {name}: the window cannot be {width}x{height} in {columns} "
                          f"columns; its minimum makes it {window.width()}x{window.height()}")
                pixmap = window.grab()
                if pixmap.isNull() or (pixmap.width(), pixmap.height()) != (window.width(),
                                                                              window.height()):
                    print(f"bad grab for {name}: null={pixmap.isNull()} "
                          f"size={pixmap.width()}x{pixmap.height()}")
                    failures += 1
                    continue
                path = out / f"{name}.png"
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
