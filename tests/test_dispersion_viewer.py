"""Offscreen acceptance for the dispersion viewer widget (real Qt, real canvas)."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.dispersion_viewer import DispersionViewerWidget  # noqa: E402

COMPONENTS = Path(__file__).resolve().parents[1] / "components"
AL_MAP = COMPONENTS / "Al_test_phonons_centered.dat"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    # Keep the test from reading or writing the operator's remembered state.
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr(QSettings, "value", lambda self, key, default=None, *a, **k: default)
    monkeypatch.setattr(QSettings, "setValue", lambda self, key, value: None)


def test_widget_plots_and_saves_png(app, tmp_path, isolated_settings):
    widget = DispersionViewerWidget(components_dir=COMPONENTS)
    messages = []
    widget.set_status_sink(messages.append)
    widget.set_map(AL_MAP)
    widget.set_overlay(None)
    widget.set_path_text("Γ X W K Γ L")
    widget.plot()

    assert widget.trace is not None
    assert widget.trace.energies.shape[1] == 2
    assert widget.overlay_trace is None
    assert messages[-1].startswith("Al_test_phonons_centered.dat: 2 branches")

    out = widget.save_png(tmp_path / "figures" / "al.png")
    assert out.is_file() and out.stat().st_size > 10_000


def test_widget_overlay_follows_the_same_path(app, isolated_settings):
    widget = DispersionViewerWidget(components_dir=COMPONENTS)
    widget.set_map(AL_MAP)
    widget.set_overlay(AL_MAP)
    widget.set_path_text("Γ X")
    widget.plot()
    assert widget.overlay_trace is not None
    assert widget.overlay_trace.energies.shape == widget.trace.energies.shape
