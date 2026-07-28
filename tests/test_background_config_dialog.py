"""Focused offscreen tests for the staged background configuration dialog."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.dialogs.background_config_dialog import (  # noqa: E402
    BackgroundConfigDialog,
)
from tavi import background  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    yield app


def test_untouched_scales_round_trip_exactly_and_edited_scale_uses_widget(qapp):
    values = {
        "environment_flat": 4.0e-13,
        "environment_slope": 2.0e12,
        "environment_cosmic_spikes": 0.0004,
        "instrument_aluminum_powder": 1.23456,
    }
    spec = {
        "catalog_version": background.CATALOG_VERSION,
        "enabled": True,
        "sources": {
            source_id: {"enabled": True, "scale": scale}
            for source_id, scale in values.items()
        },
    }
    dialog = BackgroundConfigDialog(spec)
    try:
        untouched = dialog.background_spec()
        for source_id, scale in values.items():
            assert untouched["sources"][source_id]["scale"] == scale

        edited_spin = dialog._source_widgets["environment_cosmic_spikes"][1]
        edited_spin.setValue(2.34567)
        edited = dialog.background_spec()
        assert edited["sources"]["environment_cosmic_spikes"]["scale"] == 2.34567
        assert edited["sources"]["environment_flat"]["scale"] == 4.0e-13
        assert edited["sources"]["environment_slope"]["scale"] == 2.0e12
        assert edited["sources"]["instrument_aluminum_powder"]["scale"] == 1.23456
    finally:
        dialog.close()
