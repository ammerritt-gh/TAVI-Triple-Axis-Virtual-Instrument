"""Angle labels in the docks come from the registry, on every instrument (U2 S2.2b).

Offscreen Qt, the real docks. The Instrument dock's angle labels equal the
registry's label text, the NICOS name is in each tooltip, and the A1/A5
readouts follow their 2theta fields.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from instruments.registry import get_instrument  # noqa: E402
from tavi import quantities  # noqa: E402
from test_compact_layout import INSTRUMENTS, _standalone_instrument_dock  # noqa: E402

# dock attribute -> canonical ID, for the labels (sgl/sgu labels are `sgl_label`/`sgu_label`).
LABELS = {
    "mtt_label": "mono_two_theta_deg",
    "mono_theta_label": "mono_theta_deg",
    "omega_label": "sample_rotation_deg",
    "stt_label": "sample_two_theta_deg",
    "att_label": "analyzer_two_theta_deg",
    "analyzer_theta_label": "analyzer_theta_deg",
    "sgl_label": "sample_lower_arc_deg",
    "sgu_label": "sample_upper_arc_deg",
}


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([sys.argv[0]])
    font = app.font()
    yield app
    app.setFont(font)


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_instrument_dock_angle_labels_are_the_registry_labels(app, instrument_id):
    dock, _descriptor = _standalone_instrument_dock(instrument_id)
    try:
        for attribute, quantity_id in LABELS.items():
            q = quantities.by_id(quantity_id)
            label = getattr(dock, attribute)
            assert label.text() == q.label, attribute
            assert q.nicos and f"NICOS name: {q.nicos}" in label.toolTip(), attribute
        assert dock.omega_edit.toolTip() == dock.omega_label.toolTip()
        assert "psi" in dock.omega_label.toolTip()  # the turntable's explanation is kept
        assert "travel" in dock.sgl_label.toolTip()  # so is the arcs' travel text
        # The words the old labels used are gone: A-numbers follow the ILL numbering.
        texts = [getattr(dock, name).text() for name in LABELS]
        assert "Sample rotation — A3 (°)" in texts and "Sample 2θ — A4 (°)" in texts
        assert not any(t in {"A3:", "Ana 2θ:", "Mono 2θ:", "Sample 2θ:"} for t in texts)
    finally:
        dock.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_theta_readouts_follow_their_two_theta_fields(app, instrument_id):
    dock, _descriptor = _standalone_instrument_dock(instrument_id)
    try:
        assert dock.mono_theta_edit.isReadOnly() and dock.analyzer_theta_edit.isReadOnly()
        assert dock.mono_theta_label.text() == "Mono θ — A1 (°)"
        assert dock.analyzer_theta_label.text() == "Analyzer θ — A5 (°)"
        for two_theta, readout in ((dock.mtt_edit, dock.mono_theta_edit),
                                   (dock.att_edit, dock.analyzer_theta_edit)):
            for text, expected in (("90", "45"), ("-80.5", "-40.25"), ("0", "0"), ("", "--")):
                two_theta.setText(text)  # typing, a solve and a restore all end here
                assert readout.text() == expected, (text, readout.text())
    finally:
        dock.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("instrument_id", INSTRUMENTS)
def test_ub_peak_row_sample_two_theta_label(app, instrument_id):
    from gui.docks.ub_matrix_dock import UBMatrixDock

    dock = UBMatrixDock(descriptor=get_instrument(instrument_id).descriptor())
    try:
        peak = dock.add_peak_entry()
        q = quantities.by_id("sample_two_theta_deg")
        assert peak.stt_label.text() == q.label
        assert f"NICOS name: {q.nicos}" in peak.stt_edit.toolTip()
    finally:
        dock.deleteLater()
        app.processEvents()
