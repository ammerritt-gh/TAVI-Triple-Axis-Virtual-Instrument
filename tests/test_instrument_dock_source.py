"""Offscreen-Qt checks of the Instrument dock's Source Control section.

The real ``InstrumentDock`` is built from the PUMA and PANDA descriptors (no main window, no
controller, no McStas). ``QT_QPA_PLATFORM=offscreen``: nothing is shown on the desktop. A user's
pick of a facility entry is simulated as QComboBox does it: the index changes, then ``activated``
fires (and fires alone for a re-pick of the shown entry).
"""
import logging
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
from gui.docks.instrument_dock import InstrumentDock  # noqa: E402
from instruments import source  # noqa: E402
from instruments.registry import get_instrument  # noqa: E402

FLAT = "flat band (unphysical)"
EI_LINE, EI4_LINE = "Ei", "4·Ei (λ/2)"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([sys.argv[0]])


@pytest.fixture(params=["puma", "panda"])
def dock(request, qapp):
    d = InstrumentDock(descriptor=get_instrument(request.param).descriptor())
    d.changes = []
    d.source_changed.connect(lambda: d.changes.append(d.source_settings()))
    yield d
    d.deleteLater()
    qapp.processEvents()


def pick(dock, profile_id):
    """The operator picks a facility entry from the list."""
    combo = dock.source_profile_combo
    index = combo.findData(profile_id)
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def repick(dock):
    """The operator picks the entry already shown: the index does not change."""
    combo = dock.source_profile_combo
    combo.activated.emit(combo.currentIndex())


def fields(dock):
    return {key: edit.text() for key, edit in dock.source_ti_edits.items()}


def label(profile_id):
    return source.PROFILES[profile_id].label


def named_lines(dock):
    return {line.get_label(): line for line in dock.source_ax.lines}


def curve(dock):
    return named_lines(dock).get("moderator spectrum")


def band(dock):
    return [p for p in dock.source_ax.patches if p.get_label() == FLAT]


def test_dock_starts_on_the_descriptor_default_unmarked(dock):
    default = dock.descriptor.default_moderator_profile
    s = dock.source_settings()
    assert s["moderator_profile"] == default and s["moderator_mode"] == "full_spectrum"
    assert {k: s[k] for k in source.TI_IDS} == source.profile_values(default)
    assert dock.source_profile_combo.currentText() == label(default)
    assert not source.is_modified(s)
    assert dock.changes == []


def test_picking_an_entry_fills_the_six_fields_unmarked(dock):
    pick(dock, "ill_hot")  # has an unused pair, written 0
    assert fields(dock) == {k: f"{v:g}" for k, v in source.profile_values("ill_hot").items()}
    assert dock.source_profile_combo.currentText() == label("ill_hot")
    assert not source.is_modified(dock.source_settings())
    assert len(dock.changes) == 1  # one user change, however many signals the fill raised
    assert dock.changes[0]["moderator_profile"] == "ill_hot"


def test_an_edit_shows_modified_and_repicking_clears_it(dock):
    pick(dock, "hzb_cold")
    dock.source_ti_edits["moderator_t1_k"].setText("50")
    assert dock.source_profile_combo.currentText() == label("hzb_cold") + " (modified)"
    assert dock.source_settings()["moderator_profile"] == "hzb_cold"  # the entry itself is unchanged
    assert "(modified)" in dock.collapsible_groups["instrument.source"].summary_label.text()
    assert dock.changes[-1]["moderator_t1_k"] == 50.0

    repick(dock)
    assert dock.source_ti_edits["moderator_t1_k"].text() == "43.7"
    assert dock.source_profile_combo.currentText() == label("hzb_cold")
    assert "(modified)" not in dock.collapsible_groups["instrument.source"].summary_label.text()
    assert dock.changes[-1]["moderator_t1_k"] == 43.7


def test_editing_back_to_the_entry_values_clears_the_mark(dock):
    pick(dock, "hzb_cold")
    edit = dock.source_ti_edits["moderator_i2"]
    edit.setText("1e12")
    assert dock.source_profile_combo.currentText().endswith("(modified)")
    edit.setText("2.08e12")
    assert dock.source_profile_combo.currentText() == label("hzb_cold")


def test_panda_switches_from_frm2_cold_to_frm2_thermal(qapp):
    d = InstrumentDock(descriptor=get_instrument("panda").descriptor())
    assert d.source_settings()["moderator_profile"] == "frm2_cold"
    assert d.source_profile_combo.currentText() == label("frm2_cold")
    pick(d, "frm2_thermal")
    s = d.source_settings()
    assert s["moderator_profile"] == "frm2_thermal"
    assert {k: s[k] for k in source.TI_IDS} == source.profile_values("frm2_thermal")
    assert d.source_profile_combo.currentText() == label("frm2_thermal")
    assert "FRM2 thermal, full spectrum" == d.collapsible_groups["instrument.source"].summary_label.text()
    d.deleteLater()


def test_flat_band_shows_dE_and_shades_ei_plus_minus_dE_over_the_full_height(dock):
    dock.set_source_preview_ei(10.0)
    assert dock.flat_band_edit.isHidden() and dock.flat_band_label.isHidden()
    assert band(dock) == []
    full_curve = curve(dock)
    assert full_curve.get_alpha() == 1.0

    dock.source_mode_combo.setCurrentIndex(dock.source_mode_combo.findData("flat_band"))
    assert not dock.flat_band_edit.isHidden() and not dock.flat_band_label.isHidden()
    assert dock.changes[-1]["moderator_mode"] == "flat_band"
    (shade,) = band(dock)
    assert shade.get_x() == pytest.approx(8.0) and shade.get_width() == pytest.approx(4.0)
    assert (shade.get_y(), shade.get_height()) == (0, 1)  # axes fraction: the full plot height
    assert FLAT in [t.get_text() for t in dock.source_ax.texts]
    assert curve(dock).get_alpha() < 1.0  # the profile curve is faded beside the band
    assert "flat band ±2 meV" in dock.collapsible_groups["instrument.source"].summary_label.text()

    dock.flat_band_edit.setText("0.5")
    (shade,) = band(dock)
    assert shade.get_x() == pytest.approx(9.5) and shade.get_width() == pytest.approx(1.0)
    assert dock.changes[-1]["flat_band_half_width_mev"] == 0.5

    dock.set_source_preview_ei(None)  # no Ei: no band
    assert band(dock) == []


def test_preview_marks_ei_and_four_ei_and_spans_them(dock):
    spectrum_only = dock.source_ax.get_xlim()
    energies = curve(dock).get_xdata()
    assert spectrum_only == pytest.approx((energies[0], energies[-1]))  # no Ei: the spectrum alone
    assert EI_LINE not in named_lines(dock) and EI4_LINE not in named_lines(dock)

    dock.set_source_preview_ei(14.7)
    lines = named_lines(dock)
    assert list(lines[EI_LINE].get_xdata()) == [14.7, 14.7]
    assert list(lines[EI4_LINE].get_xdata()) == pytest.approx([58.8, 58.8])
    assert lines[EI4_LINE].get_linestyle() == "--"
    assert {EI_LINE, EI4_LINE} <= {t.get_text() for t in dock.source_ax.texts}
    lo, hi = dock.source_ax.get_xlim()
    assert lo <= min(14.7, spectrum_only[0]) and hi >= max(58.8, spectrum_only[1])
    assert dock.source_ax.get_xscale() == "log"

    dock.set_source_preview_ei(None)
    assert EI_LINE not in named_lines(dock) and EI4_LINE not in named_lines(dock)
    assert dock.source_ax.get_xlim() == pytest.approx(spectrum_only)


def test_every_change_redraws_the_preview(dock):
    def snapshot():
        line = curve(dock)
        return None if line is None else (line.get_alpha(), tuple(line.get_ydata()[:50]))

    before = snapshot()
    dock.source_ti_edits["moderator_t1_k"].setText("77")
    after_field = snapshot()
    assert after_field != before
    pick(dock, dock.descriptor.default_moderator_profile)
    assert snapshot() == before
    dock.source_mode_combo.setCurrentIndex(dock.source_mode_combo.findData("flat_band"))
    assert snapshot() != before


def test_source_settings_is_exactly_what_the_widgets_show(dock):
    s = dock.source_settings()
    assert tuple(s) == source.FIELD_IDS
    assert s["moderator_mode"] == dock.source_mode_combo.currentData()
    for key, edit in dock.source_ti_edits.items():
        assert s[key] == float(edit.text())
    assert s["flat_band_half_width_mev"] == float(dock.flat_band_edit.text())

    dock.source_ti_edits["moderator_t2_k"].setText("abc")
    dock.source_ti_edits["moderator_i2"].setText("")
    dock.source_ti_edits["moderator_t3_k"].setText("nan")
    dock.flat_band_edit.setText("1e")
    s = dock.source_settings()
    assert s["moderator_t2_k"] is None and s["moderator_i2"] is None and s["moderator_t3_k"] is None
    assert s["flat_band_half_width_mev"] is None
    assert s["moderator_t1_k"] == float(dock.source_ti_edits["moderator_t1_k"].text())
    for key in ("moderator_t2_k", "moderator_i2", "moderator_t3_k"):
        assert "cc0000" in dock.source_ti_edits[key].styleSheet()  # the invalid-field style
    assert dock.source_ti_edits["moderator_t1_k"].styleSheet() == ""


def test_a_negative_field_takes_the_invalid_style_until_fixed(dock):
    edit = dock.source_ti_edits["moderator_i1"]
    edit.setText("-1")
    assert "cc0000" in edit.styleSheet()
    edit.setText("1e12")
    assert edit.styleSheet() == ""


SETTINGS = {
    "moderator_mode": "flat_band", "moderator_profile": "ill_hot",
    "moderator_t1_k": 1234.5678901, "moderator_i1": 3.3333e13, "moderator_t2_k": 0.0,
    "moderator_i2": 1e12, "moderator_t3_k": 0.000123, "moderator_i3": 7e11,
    "flat_band_half_width_mev": 0.37,
}


def test_set_source_settings_round_trips_without_emitting(dock):
    dock.set_source_settings(SETTINGS)
    assert dock.source_settings() == SETTINGS
    assert dock.changes == []
    assert dock.source_profile_combo.currentText() == label("ill_hot") + " (modified)"
    assert not dock.flat_band_edit.isHidden()

    # an entry's own values are not a modification, and a partial set leaves the rest alone
    dock.set_source_settings({"moderator_profile": "psi_cold", "moderator_mode": "full_spectrum",
                              **source.profile_values("psi_cold")})
    assert dock.source_profile_combo.currentText() == label("psi_cold")
    assert dock.source_settings()["flat_band_half_width_mev"] == 0.37
    assert dock.flat_band_edit.isHidden()

    unparsed = {**dock.source_settings(), "moderator_t3_k": None}
    dock.set_source_settings(unparsed)
    assert dock.source_settings() == unparsed
    assert dock.changes == []


def test_set_source_settings_refuses_unknown_names_and_changes_nothing(dock):
    before = dock.source_settings()
    for bad in ({"moderator_mode": "sideways"}, {"moderator_profile": "nowhere"}, {"source_dE": 2}):
        with pytest.raises(ValueError):
            dock.set_source_settings({**SETTINGS, **bad})
    assert dock.source_settings() == before


def test_no_active_pair_shows_the_note_and_draws_no_curve(dock):
    assert dock.source_note_label.isHidden()
    for key in source.TI_IDS[::2]:
        dock.source_ti_edits[key].setText("0")
    assert not dock.source_note_label.isHidden()
    dock.set_source_preview_ei(10.0)  # must not raise
    assert curve(dock) is None and EI_LINE in named_lines(dock)


def test_an_absurd_temperature_draws_no_curve_and_logs(dock, caplog):
    assert source.validate({**dock.source_settings(), "moderator_t1_k": 1e157}) == []  # the component accepts it
    with caplog.at_level(logging.ERROR, logger="gui.docks.instrument_dock"):
        dock.source_ti_edits["moderator_t1_k"].setText("1e157")  # flux_per_mev overflows here
        dock.set_source_preview_ei(10.0)
    assert curve(dock) is None
    assert any("source preview" in r.getMessage() for r in caplog.records)
    dock.source_ti_edits["moderator_t1_k"].setText("300")
    assert curve(dock) is not None and math.isfinite(dock.source_ax.get_ylim()[1])


def test_the_old_source_api_is_gone(dock):
    for name in ("source_type_combo", "selected_source_id", "set_source_id"):
        assert not hasattr(dock, name)
