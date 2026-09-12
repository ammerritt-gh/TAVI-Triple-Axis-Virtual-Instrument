"""Ledger entry 3 (P1) in docs/audits/new-instruments-crystal-bending.md: a
batched radius PATCH silently discarded one of the commanded radii.

Each radius field's after-handler used to unlock its own Ideal-focusing lock
and then refresh all four fields from ``_sync_curvature_fields`` (which
overwrites any axis still locked to AUTOFOCUS). ``apply_parameters`` runs
every SETTER before any after-handler, so with both monochromator axes
AUTOFOCUS-locked, ``apply_parameters({"rhm": 9.0, "rvm": 8.0})`` wrote both
values, then the first after-handler unlocked its own axis and refreshed --
overwriting the sibling axis, still locked at that instant, with its ideal
value instead of the just-applied number. The fix moves the unlock into the
setter itself, so every commanded axis is already unlocked before any
refresh runs.
"""
import math
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

_INSTRUMENT_IDS = [info.id for info in available_instruments()]


def _make_controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture(params=_INSTRUMENT_IDS)
def controller(request):
    yield from _make_controller(request.param)


@pytest.mark.parametrize("order", [("rhm", "rvm"), ("rvm", "rhm")])
def test_a_batched_patch_holds_both_autofocus_locked_radii(controller, order):
    """The headline case: lock both monochromator axes to their ideal, then
    PATCH both explicitly in each key order. Both must land exactly on the
    requested values and finish unlocked (HELD), in either order."""
    ctrl = controller
    ctrl.apply_ideal_bending_value("rhm")
    ctrl.apply_ideal_bending_value("rvm")
    assert ctrl.is_bending_locked("rhm") and ctrl.is_bending_locked("rvm")

    values = {"rhm": 9.0, "rvm": 8.0}
    patch = {key: values[key] for key in order}
    applied, errors = ctrl.apply_parameters(patch)
    assert not errors
    assert applied == patch

    vals = ctrl.get_gui_values()
    assert math.isclose(vals["rhm"], 9.0)
    assert math.isclose(vals["rvm"], 8.0)
    assert not ctrl.is_bending_locked("rhm")
    assert not ctrl.is_bending_locked("rvm")


def test_a_single_radius_patch_leaves_the_other_three_axes_untouched(controller):
    """Naming one radius must hold THAT axis only -- the other three keep
    whatever lock state and value they had before the patch."""
    ctrl = controller
    ctrl.apply_ideal_bending_value("rhm")
    ctrl.apply_ideal_bending_value("rvm")
    before = {
        key: (ctrl.is_bending_locked(key), ctrl.get_gui_values()[key])
        for key in ("rvm", "rha", "rva")
    }

    applied, errors = ctrl.apply_parameters({"rhm": 9.0})
    assert not errors
    assert applied == {"rhm": 9.0}
    assert math.isclose(ctrl.get_gui_values()["rhm"], 9.0)
    assert not ctrl.is_bending_locked("rhm")

    after = {
        key: (ctrl.is_bending_locked(key), ctrl.get_gui_values()[key])
        for key in ("rvm", "rha", "rva")
    }
    for key in ("rvm", "rha", "rva"):
        locked_before, value_before = before[key]
        locked_after, value_after = after[key]
        assert locked_after == locked_before
        assert math.isclose(value_after, value_before)


def test_a_four_radius_patch_keeps_every_driven_radius(controller):
    """One PATCH naming every driven radius must land all of them, even with
    each one AUTOFOCUS-locked beforehand. A non-driven (fixed) axis is
    excluded here: the GUI always pins its field to the fixed radius
    regardless of lock bookkeeping (see ``_sync_curvature_fields``), so a
    commanded value on that axis is not expected to stick -- that is
    unrelated to this ordering bug."""
    ctrl = controller
    idock = ctrl.window.instrument_dock
    axis_specs = ctrl._curvature_axis_specs(
        idock.selected_mono_id(), idock.selected_ana_id(),
        modules=idock.module_values(),
    )
    def _unlockable(key):
        spec = axis_specs[key][0]
        if key == "rva":
            # unlock_ideal_bending's rva branch only re-enables the button
            # when the analyser also has a known focusing model -- unrelated
            # to this ordering fix (see the packet's constraints).
            return spec.driven and spec.focusing_known
        return spec.driven

    keys = [k for k in ("rhm", "rvm", "rha", "rva") if _unlockable(k)]
    assert {"rhm", "rvm"} <= set(keys)  # the headline axes are always driven

    for key in keys:
        ctrl.apply_ideal_bending_value(key)

    values = {"rhm": 9.0, "rvm": 8.0, "rha": 7.0, "rva": 6.0}
    patch = {key: values[key] for key in keys}
    applied, errors = ctrl.apply_parameters(patch)
    assert not errors
    assert applied == patch

    vals = ctrl.get_gui_values()
    for key in keys:
        assert math.isclose(vals[key], values[key])
        assert not ctrl.is_bending_locked(key)


def test_a_batched_patch_refreshes_the_bending_buttons_exactly_once(controller):
    """The dedupe claim: four distinct radius fields all reuse the SAME
    bound after-handler (``update_ideal_bending_buttons``), so a patch
    naming several of them collapses to one refresh, not one per field."""
    ctrl = controller
    ctrl.apply_ideal_bending_value("rhm")
    ctrl.apply_ideal_bending_value("rvm")

    original = ctrl.update_ideal_bending_buttons
    calls = []

    def counted():
        calls.append(1)
        original()

    ctrl.update_ideal_bending_buttons = counted
    try:
        applied, errors = ctrl.apply_parameters({"rhm": 9.0, "rvm": 8.0})
        assert not errors
        assert applied == {"rhm": 9.0, "rvm": 8.0}
        assert len(calls) == 1
    finally:
        del ctrl.update_ideal_bending_buttons
