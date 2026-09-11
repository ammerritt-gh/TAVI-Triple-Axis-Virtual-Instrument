"""Packet slice 4: rva becomes a real operator surface.

Until this branch ``rva`` had no widget and no API field -- three call sites
read PUMA's fixed 0.8 m as a universal default. This module pins the three
declared cases the operator must actually see and react to, on real
instruments:

- fixed (IN12's PG(002) analyser): the field shows the declared radius and
  cannot be edited; the Ideal button is disabled -- the operator has no say.
- driven but focusing_known=False (IN12's Heusler): the field is editable
  (a typed value is legitimate/HELD), but the Ideal button stays disabled --
  there is no established focusing model to autofocus from.
- driven and focusing-known (IN8): behaves exactly like rha.

Plus the request surface (API field + fixed-axis refusal) and persistence
(round-trip, and a pre-rva save resetting visibly rather than silently
accepting a half-populated curvature block).
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


# ------------------------------------------------------------- case 1: fixed


def test_fixed_rva_shows_the_declared_radius_and_is_not_editable():
    """IN12's conventional PG(002) analyser: rva is fixed at 1.40 m."""
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono = d.mono_crystals[0].id
        pg002 = next(c for c in d.ana_crystals if c.id == "pg002")
        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(pg002.id)
        ctrl.update_ideal_bending_buttons()

        idock = ctrl.window.instrument_dock
        assert idock.rva_edit.isEnabled() is False
        assert idock.rva_ideal_button.isEnabled() is False
        assert abs(float(idock.rva_edit.text())) == pytest.approx(1.40)


def test_switching_to_a_driven_analyser_re_enables_the_fixed_field():
    """The field must react to the analyser selection changing, not just the
    initial state."""
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono = d.mono_crystals[0].id
        pg002 = next(c for c in d.ana_crystals if c.id == "pg002")
        heusler = next(c for c in d.ana_crystals if c.id == "heusler111")
        idock = ctrl.window.instrument_dock

        idock.set_mono_id(mono)
        idock.set_ana_id(pg002.id)
        assert idock.rva_edit.isEnabled() is False

        idock.set_ana_id(heusler.id)
        assert idock.rva_edit.isEnabled() is True    # driven now
        assert idock.rva_ideal_button.isEnabled() is False  # still no model


# ---------------------------------------------- case 2: no focusing model


def test_heusler_rva_is_editable_with_no_ideal_button():
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono = d.mono_crystals[0].id
        heusler = next(c for c in d.ana_crystals if c.id == "heusler111")
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(heusler.id)

        assert idock.rva_edit.isEnabled() is True
        assert idock.rva_ideal_button.isEnabled() is False
        assert "no established focusing model" in idock.rva_ideal_button.toolTip().lower()


def test_typed_rva_is_honoured_as_held_under_no_focusing_model():
    """A typed value is legitimate (HELD) even though autofocus is not."""
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono = d.mono_crystals[0].id
        heusler = next(c for c in d.ana_crystals if c.id == "heusler111")
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(heusler.id)
        idock.rva_edit.setText("2.5")

        vals = ctrl.get_gui_values()
        assert vals is not None
        assert vals["rva"] == pytest.approx(2.5)
        assert vals["curvature_modes"]["rva"] == cm.CurvatureMode.HELD


def test_unlock_ideal_bending_does_not_re_enable_rva_with_no_focusing_model():
    """Editing rva's field (textEdited) must not resurrect an Ideal button
    the descriptor never offered for this analyser."""
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono = d.mono_crystals[0].id
        heusler = next(c for c in d.ana_crystals if c.id == "heusler111")
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(heusler.id)

        ctrl.unlock_ideal_bending("rva")
        assert idock.rva_ideal_button.isEnabled() is False
        assert idock.rva_ideal_button.isChecked() is False


# -------------------------------------------------- case 3: ordinary (IN8)


def test_in8_rva_behaves_like_rha():
    with _controller("in8") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(ana)

        assert idock.rva_edit.isEnabled() is True
        assert idock.rva_ideal_button.isEnabled() is True

        ctrl.apply_ideal_bending_value("rva")
        assert idock.rva_ideal_button.isChecked() is True
        assert idock.rva_ideal_button.isEnabled() is False
        assert ctrl.is_bending_locked("rva") is True

        vals = ctrl.get_gui_values()
        assert vals["curvature_modes"]["rva"] == cm.CurvatureMode.AUTOFOCUS

        ctrl.unlock_ideal_bending("rva")
        assert idock.rva_ideal_button.isEnabled() is True
        assert ctrl.is_bending_locked("rva") is False


# ---------------------------------------------------------- request surface


def test_rva_is_a_patchable_api_field():
    with _controller("in8") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rva": 1.5,
            "scan_command1": "deltaE 0 1 0.5",
        })
        vals = launch["vals"]
        assert vals["rva"] == pytest.approx(1.5)
        assert vals["curvature_modes"]["rva"] == cm.CurvatureMode.HELD
        # rhm/rvm/rha stay AUTOFOCUS -- naming one axis holds only that axis.
        assert vals["curvature_modes"]["rha"] == cm.CurvatureMode.AUTOFOCUS


def test_rva_appears_in_get_schema_fields():
    with _controller("in8") as ctrl:
        names = {f["name"] for f in ctrl.build_api_schema()["fields"]}
        assert "rva" in names


def test_an_explicit_rva_on_a_fixed_axis_is_refused_by_the_api():
    """PUMA's rva is fixed at 0.8 m. Requirement #4: this refusal could not
    be reached before rva was a request field; it must work now."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        with pytest.raises(cm.ApiError) as excinfo:
            ctrl.build_api_launch_state({
                "monocris": mono, "anacris": ana,
                "rva": 0.5,
                "scan_command1": "deltaE 0 1 0.5",
            })
        assert excinfo.value.status == 400
        assert excinfo.value.code == "curvature_out_of_travel"
        assert "0.8" in excinfo.value.message and "0.5" in excinfo.value.message

        # The GUI's equivalent gate refuses the identical value the same way.
        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.instrument_dock.rva_edit.setText("0.5")
        gui_issues = ctrl._held_curvature_issues(mono, ana)
        assert gui_issues == [excinfo.value.message]


def test_rva_at_its_own_fixed_radius_is_accepted_by_the_api():
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rva": 0.8,
            "scan_command1": "deltaE 0 1 0.5",
        })
        assert abs(launch["vals"]["rva"]) == pytest.approx(0.8)


# ------------------------------------------------------------- persistence


def _controller_stub():
    from types import SimpleNamespace
    controller = cm.TAVIController.__new__(cm.TAVIController)
    controller.instrument = SimpleNamespace(id="puma")
    controller.messages = []
    controller.print_to_message_center = controller.messages.append
    return controller


def test_saved_curvature_state_round_trips_when_complete():
    controller = _controller_stub()
    saved = {
        "rhm_var": "13.0", "rvm_var": "1.6", "rha_var": "2.3", "rva_var": "0.8",
        "rhm_ideal_locked": True, "rvm_ideal_locked": False,
        "rha_ideal_locked": True, "rva_ideal_locked": False,
    }
    state = controller._saved_curvature_state(saved)
    assert state == saved
    assert controller.messages == []


def test_saved_curvature_state_resets_visibly_when_rva_keys_are_missing():
    """A pre-slice-4 save has rhm/rvm/rha but never rva -- the whole block
    must reset to safe defaults, not load three real values next to a
    phantom flat, unlocked rva."""
    controller = _controller_stub()
    legacy = {
        "rhm_var": "13.0", "rvm_var": "1.6", "rha_var": "2.3",
        "rhm_ideal_locked": True, "rvm_ideal_locked": False,
        "rha_ideal_locked": True,
    }
    state = controller._saved_curvature_state(legacy)
    assert state == {
        "rhm_var": "0", "rvm_var": "0", "rha_var": "0", "rva_var": "0",
        "rhm_ideal_locked": False, "rvm_ideal_locked": False,
        "rha_ideal_locked": False, "rva_ideal_locked": False,
    }
    assert len(controller.messages) == 1
    assert "reset to safe defaults" in controller.messages[0]


def test_saved_curvature_state_defaults_quietly_when_entirely_absent():
    """A fresh instrument (no curvature keys saved at all) is not the
    incomplete-schema case -- no warning, just the safe defaults."""
    controller = _controller_stub()
    state = controller._saved_curvature_state({"mtt_var": "41.167"})
    assert state["rva_var"] == "0"
    assert state["rva_ideal_locked"] is False
    assert controller.messages == []


def test_all_four_radii_and_locks_round_trip_through_save_and_load(tmp_path):
    with _controller("in8") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        idock = ctrl.window.instrument_dock
        idock.set_mono_id(mono)
        idock.set_ana_id(ana)

        idock.rhm_edit.setText("11.0")
        idock.rvm_edit.setText("1.1")
        idock.rha_edit.setText("2.2")
        idock.rva_edit.setText("3.3")
        ctrl.apply_ideal_bending_value("rha")  # lock rha only

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            ctrl.save_parameters()
            # Mutate every field so load_parameters' effect is observable.
            idock.rhm_edit.setText("0")
            idock.rvm_edit.setText("0")
            idock.rha_edit.setText("0")
            idock.rva_edit.setText("0")
            ctrl.unlock_ideal_bending("rha")

            ctrl.load_parameters()

            assert float(idock.rhm_edit.text()) == pytest.approx(11.0)
            assert float(idock.rvm_edit.text()) == pytest.approx(1.1)
            assert ctrl.is_bending_locked("rha") is True
            assert ctrl.is_bending_locked("rva") is False
            assert float(idock.rva_edit.text()) == pytest.approx(3.3)
        finally:
            os.chdir(old_cwd)
