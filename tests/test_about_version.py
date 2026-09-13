"""The About dialog shows the package version, never a separately-typed literal.

Offscreen Qt acceptance test: constructs the real main window and reads the
About text `_show_about` builds, with `QMessageBox.about` stubbed so the modal
never blocks. `tavi.__version__` is monkeypatched to a value distinct from the
current release so a hardcoded literal in the dialog (rather than a read of the
constant) shows up as a mismatch, not an accidental pass.
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import tavi  # noqa: E402
import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


def _make_window():
    """A real TAVIMainWindow on an offscreen Qt platform."""
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    iid = infos[0].id
    instrument = get_instrument(iid)
    return cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=iid, save_selection=lambda _id: None,
    ), app


def test_about_shows_the_package_version(monkeypatch):
    monkeypatch.setattr(tavi, "__version__", "9.9.9")
    window, _app = _make_window()
    captured = {}

    def fake_about(parent, title, text):
        captured["text"] = text

    monkeypatch.setattr(QMessageBox, "about", fake_about)
    window._show_about()

    text = captured["text"]
    assert tavi.__version__ in text
    assert len(re.findall(r"\d+\.\d+\.\d+", text)) == 1
