"""Slit gaps are written one key each, ``slit.<stable_id>.<axis>_gap_mm``, in millimetres.

Ledger entry 10 (P2) in docs/audits/new-instruments-crystal-bending.md: every plugin
indexes each slit id it declares directly (e.g. ``instruments/puma/plugin.py``'s
``slits_mm['pbl']``), so a request naming one gap must still leave every other
aperture at its descriptor default, and a gap the instrument lacks must be refused.
The old ``slits_mm`` object is refused with the replacement named.
"""
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
from dataclasses import replace  # noqa: E402

from instruments.validation import validate_descriptor  # noqa: E402
from tavi.api_server import ApiError  # noqa: E402

_INSTRUMENT_IDS = [info.id for info in available_instruments()]


@pytest.fixture(params=_INSTRUMENT_IDS)
def controller(request):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(request.param)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=request.param, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


def _defaults(descriptor):
    """{slit.id: default} in the form the plugins index: scalar, or (width, height)."""
    out = {}
    for slit in descriptor.slits:
        width = float(slit.default_width_mm or 0)
        out[slit.id] = (width, float(slit.default_height_mm or 0)) if slit.has_height else width
    return out


def test_one_named_gap_leaves_every_other_aperture_at_its_default(controller):
    slits = controller.descriptor.slits
    named = slits[0]
    key = f"slit.{named.stable_id}.horizontal_gap_mm"

    state = controller.build_api_launch_state({"scan_command1": "deltaE 0 1 1", key: 50.0})

    expected = _defaults(controller.descriptor)
    expected[named.id] = (50.0, expected[named.id][1]) if named.has_height else 50.0
    assert state["vals"]["slits_mm"] == expected
    assert state["scan_config"] is not None  # the plugin indexed every slit id without a KeyError


def test_the_two_gaps_of_a_two_gap_aperture_are_independent(controller):
    two_gap = next((s for s in controller.descriptor.slits if s.has_height), None)
    assert two_gap is not None
    height_key = f"slit.{two_gap.stable_id}.vertical_gap_mm"

    state = controller.build_api_launch_state({"scan_command1": "deltaE 0 1 1", height_key: 33.0})

    width, height = state["vals"]["slits_mm"][two_gap.id]
    assert height == 33.0
    assert width == float(two_gap.default_width_mm)


def test_get_parameters_lists_only_this_instruments_gaps(controller):
    public = controller.api_parameters()
    gaps = {k for k in public if k.startswith("slit.")}
    expected = set()
    for slit in controller.descriptor.slits:
        expected.add(f"slit.{slit.stable_id}.horizontal_gap_mm")
        if slit.has_height:
            expected.add(f"slit.{slit.stable_id}.vertical_gap_mm")
    assert gaps == expected
    assert "slits_mm" not in public


def test_a_patch_writes_one_gap_and_keeps_the_rest(controller):
    slit = next(s for s in controller.descriptor.slits if s.has_height)
    before = controller.api_parameters()
    key = f"slit.{slit.stable_id}.vertical_gap_mm"
    other = f"slit.{slit.stable_id}.horizontal_gap_mm"

    applied, errors = controller.apply_parameters({key: 41.0})

    assert errors == {} and applied == {key: 41.0}
    after = controller.api_parameters()
    assert after[key] == 41.0
    assert after[other] == before[other]
    assert {k: v for k, v in after.items() if k.startswith("slit.") and k != key} == \
           {k: v for k, v in before.items() if k.startswith("slit.") and k != key}


def test_an_aperture_this_instrument_lacks_is_refused_and_nothing_is_written(controller):
    own = {s.stable_id for s in controller.descriptor.slits}
    absent = next(sid for sid in ("post_mono", "virtual_source", "sample_exit") if sid not in own)
    before = controller.api_parameters()

    applied, errors = controller.apply_parameters({
        "sample_lower_arc_deg": 0.0, f"slit.{absent}.horizontal_gap_mm": 10.0})

    assert applied == {}
    assert f"slit.{absent}.horizontal_gap_mm" in errors
    assert controller.api_parameters() == before
    with pytest.raises(ApiError) as caught:
        controller.build_api_launch_state({
            "scan_command1": "deltaE 0 1 1", f"slit.{absent}.horizontal_gap_mm": 10.0})
    assert f"slit.{absent}.horizontal_gap_mm" in caught.value.details["errors"]


def test_a_vertical_gap_on_a_one_gap_aperture_is_refused(controller):
    one_gap = next((s for s in controller.descriptor.slits if not s.has_height), None)
    assert one_gap is not None
    key = f"slit.{one_gap.stable_id}.vertical_gap_mm"

    applied, errors = controller.apply_parameters({key: 10.0})

    assert applied == {} and key in errors


def test_the_old_slits_object_and_old_slit_names_are_refused_with_the_replacement(controller):
    named = controller.descriptor.slits[0]
    before = controller.api_parameters()

    applied, errors = controller.apply_parameters({"slits_mm": {named.id: 50.0}})
    assert applied == {}
    assert "slit.<stable_id>.horizontal_gap_mm" in errors["slits_mm"]

    applied, errors = controller.apply_parameters({"sbl_hgap": 50.0})
    assert applied == {}
    assert "pre_sample_vgap" in errors["sbl_hgap"]

    assert controller.api_parameters() == before


def test_every_slit_has_a_stable_id_the_registry_knows_and_a_missing_one_fails(controller):
    descriptor = controller.descriptor
    assert validate_descriptor(descriptor, runnable=True) == []

    for stable_id in ("", "not_a_registered_aperture"):
        broken = replace(descriptor, slits=(replace(descriptor.slits[0], stable_id=stable_id),)
                         + descriptor.slits[1:])
        assert any("stable_id" in error for error in validate_descriptor(broken, runnable=True))
