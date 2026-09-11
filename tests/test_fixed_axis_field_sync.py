"""Regression: a fixed curvature axis's field must sync and disable for all
four axes, not just rva (D16).

``update_ideal_bending_buttons`` disabled and synced a fixed axis's field
only for rva. PUMA's NMO fixes rhm/rvm flat while leaving their Ideal locks
off (HELD, not AUTOFOCUS) -- with the locks off, a stale non-zero value
typed into rhm/rvm before NMO was fitted stayed in the field, with no
disabled cue, and ``_held_curvature_issues`` (which resolves the same
policy) hard-blocked Run for a value the scan never actually uses (NMO
pins rhm/rvm to 0 regardless of the field).
"""
import contextlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def test_nmo_fitted_zeroes_and_disables_rhm_rvm_fields_and_clears_held_refusal():
    with _controller("puma") as ctrl:
        idock = ctrl.window.instrument_dock

        # Locks off (default), a stale non-zero value in each field.
        idock.rhm_edit.setText("2.5")
        idock.rvm_edit.setText("1.5")
        ctrl.update_ideal_bending_buttons()
        assert idock.rhm_edit.isEnabled() is True
        assert idock.rvm_edit.isEnabled() is True

        mono = idock.selected_mono_id()
        ana = idock.selected_ana_id()

        idock.nmo_combo.setCurrentText("Vertical")
        ctrl.update_ideal_bending_buttons()

        assert float(idock.rhm_edit.text()) == pytest.approx(0.0)
        assert float(idock.rvm_edit.text()) == pytest.approx(0.0)
        assert idock.rhm_edit.isEnabled() is False
        assert idock.rvm_edit.isEnabled() is False
        assert ctrl._held_curvature_issues(mono, ana) == []

        # Deselect NMO: fields become editable again.
        idock.nmo_combo.setCurrentText("None")
        ctrl.update_ideal_bending_buttons()
        assert idock.rhm_edit.isEnabled() is True
        assert idock.rvm_edit.isEnabled() is True


def test_in8_rva_behaves_like_rha_unaffected_by_the_generalised_loop():
    """rha/rva on a driven, focusing-known analyser stay editable and
    unlocked -- the generalised field loop must not disable a driven axis."""
    with _controller("in8") as ctrl:
        idock = ctrl.window.instrument_dock
        ctrl.update_ideal_bending_buttons()
        assert idock.rha_edit.isEnabled() is True
        assert idock.rva_edit.isEnabled() is True
