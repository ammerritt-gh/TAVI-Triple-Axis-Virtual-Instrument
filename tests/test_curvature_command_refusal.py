"""Packet slice 3c: an explicit command is refused, not rewritten.

Slice 3b left ``set_crystal_bending`` clamping every out-of-travel radius,
right for an AUTOFOCUS ideal (nobody chose that number) and wrong for a value
a person or an API client explicitly asked for (a HELD radius, or a scan
range), which used to be silently rewritten into a different instrument. This
module pins the resolution: ``curvature_command_error`` (``instruments.
tas_runtime``) refuses an explicit command at submission, before anything
runs, while the clamp remains the backstop for AUTOFOCUS.

``test_curvature_producer.py`` and ``test_curvature_autofocus.py`` pin the
clamp side (unchanged by this slice); this module pins the refusal side and,
above all, that the GUI and API submission paths refuse an identical value
with an identical sentence -- the recurring defect this branch keeps
producing on other axes.
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from instruments.descriptor import CurvatureAxis
from instruments.tas_runtime import curvature_command_error

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import contextlib  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402


# ---------------------------------------------------------------- unit level


def test_zero_survives_a_driven_axes_declared_minimum():
    """FLAT is real hardware: a minimum radius bounds how tightly a bender
    may bend, not whether it may be straight."""
    axis = CurvatureAxis(driven=True, min_radius_m=2.0)
    assert curvature_command_error("rhm", 0.0, axis) is None


def test_zero_survives_a_driven_axes_declared_maximum():
    axis = CurvatureAxis(driven=True, max_radius_m=5.0)
    assert curvature_command_error("rhm", 0.0, axis) is None


def test_a_value_below_the_declared_minimum_is_refused_naming_axis_crystal_value_limit():
    axis = CurvatureAxis(driven=True, min_radius_m=2.0)
    error = curvature_command_error("rhm", 1.0, axis, "PG(002) monochromator")
    assert error is not None
    assert "rhm" in error
    assert "PG(002) monochromator" in error
    assert "1" in error
    assert "2" in error


def test_a_value_above_the_declared_maximum_is_refused():
    axis = CurvatureAxis(driven=True, max_radius_m=5.0)
    error = curvature_command_error("rha", 8.0, axis, "PG(002) analyser")
    assert error is not None
    assert "rha" in error and "PG(002) analyser" in error


def test_a_driven_axis_with_no_declared_travel_refuses_nothing():
    axis = CurvatureAxis(driven=True)
    assert curvature_command_error("rhm", 1e6, axis) is None
    assert curvature_command_error("rhm", 0.0, axis) is None


def test_an_explicit_value_on_a_fixed_axis_is_refused_naming_the_declared_radius():
    axis = CurvatureAxis(driven=False, fixed_radius_m=0.8)
    error = curvature_command_error("rva", 0.5, axis, "PG(002) analyser")
    assert error is not None
    assert "0.8" in error and "0.5" in error and "PG(002) analyser" in error


def test_a_fixed_axis_commanded_at_its_own_declared_radius_is_not_refused():
    axis = CurvatureAxis(driven=False, fixed_radius_m=0.8)
    assert curvature_command_error("rva", 0.8, axis) is None
    assert curvature_command_error("rva", -0.8, axis) is None  # signed value


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_driven_axis_with_declared_travel_refuses_every_non_finite_magnitude(bad):
    """The three magnitude comparisons (==0, <min, >max) are each False
    against NaN, so without an explicit finiteness guard a NaN reaches
    McStas untouched; inf and -inf must be caught the same way."""
    axis = CurvatureAxis(driven=True, min_radius_m=2.0, max_radius_m=5.0)
    error = curvature_command_error("rhm", bad, axis)
    assert error is not None
    assert "finite" in error


def test_a_driven_axis_with_no_declared_maximum_still_refuses_infinity():
    """With no declared max_radius_m the ``value > max_m`` comparison never
    runs at all, so inf used to escape even where NaN might coincidentally
    be caught elsewhere -- this is that exact hole."""
    axis = CurvatureAxis(driven=True, min_radius_m=2.0)
    error = curvature_command_error("rhm", float("inf"), axis)
    assert error is not None
    assert "finite" in error


def test_a_fixed_axis_refuses_nan_with_the_finite_message_not_the_fixed_radius_one():
    """A fixed axis already refuses NaN by accident (``value != fixed`` is
    True for NaN) -- but only when ``fixed_radius_m`` is set, and with the
    wrong sentence. The finiteness guard must fire first, for both."""
    axis = CurvatureAxis(driven=False, fixed_radius_m=0.8)
    error = curvature_command_error("rva", float("nan"), axis, "PG(002) analyser")
    assert error is not None
    assert "finite" in error
    assert "0.8" not in error  # not the fixed-radius mismatch sentence


# ------------------------------------------------------------- integration


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


def test_both_submission_paths_refuse_the_same_out_of_travel_value_identically():
    """THE test the packet cares most about: a PUMA rhm commanded below its
    2.0 m minimum is refused on the API launch-assembly path and on the GUI
    launch-assembly path, with the identical sentence -- not merely "both
    refuse", but the same wording, so an operator reading a GUI dialog and a
    campaign client reading a 400 body learn the same thing."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        out_of_travel = 1.0  # PUMA rhm min_radius_m = 2.0

        with pytest.raises(cm.ApiError) as excinfo:
            ctrl.build_api_launch_state({
                "monocris": mono, "anacris": ana,
                "rhm": out_of_travel,
                "scan_command1": "deltaE 0 1 0.5",
            })
        assert excinfo.value.status == 400
        assert excinfo.value.code == "curvature_out_of_travel"
        api_message = excinfo.value.message

        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.instrument_dock.rhm_edit.setText(str(out_of_travel))
        # setText is programmatic, so it does not fire textEdited and does not
        # clear the Ideal lock the way a user typing here would. Establish the
        # HELD precondition explicitly: _held_curvature_issues inspects only
        # unlocked axes, so a controller built on a machine whose
        # config/parameters.json last saved rhm_ideal_locked=true starts
        # locked and reports no issue at all.
        ctrl.unlock_ideal_bending("rhm")
        assert ctrl.is_bending_locked("rhm") is False
        gui_issues = ctrl._held_curvature_issues(mono, ana)

        assert gui_issues == [api_message], (
            f"GUI and API must refuse the identical PUMA rhm={out_of_travel} "
            f"with the identical sentence; got GUI={gui_issues!r} "
            f"API={api_message!r}"
        )
        # Read the actual wording -- not a description of it.
        assert "rhm" in api_message
        assert "2" in api_message  # names the mechanical minimum


def test_a_scan_range_out_of_travel_is_rejected_on_both_routes():
    """A scan endpoint outside a driven axis's declared travel is refused at
    validation -- the identical ``_scan_command_issues`` gate the GUI Run
    button and the API scan submission both call."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        # rhm's declared minimum is 2.0 m; 1.0 is below it.
        cmd = "rhm 1.0 3.0 0.5"

        hard_api, _ = ctrl._scan_command_issues(cmd, "", mono, ana)
        assert hard_api, "an out-of-travel scan endpoint must hard-block"
        assert "rhm" in hard_api[0]

        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.simulation_dock.scan_command_1_edit.setText(cmd)
        ctrl.window.simulation_dock.scan_command_2_edit.setText("")
        hard_gui, _ = ctrl._preflight_scan_validation()
        assert hard_gui, "the GUI Run gate must refuse the identical range"
        assert "rhm" in hard_gui[0]

        # A range fully inside travel still launches clean.
        ok_cmd = "rhm 3.0 5.0 0.5"
        hard_ok, _ = ctrl._scan_command_issues(ok_cmd, "", mono, ana)
        assert hard_ok == []


def test_zero_is_still_accepted_as_a_held_radius_and_as_a_scan_endpoint():
    """Commanded flat is legal everywhere the minimum-radius refusal applies
    -- the refusal must not eat it."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        # HELD at exactly 0, via the API.
        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rhm": 0.0,
            "scan_command1": "deltaE 0 1 0.5",
        })
        assert launch["vals"]["rhm"] == 0.0

        # HELD at exactly 0, via the GUI widget.
        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.instrument_dock.rhm_edit.setText("0")
        assert ctrl._held_curvature_issues(mono, ana) == []

        # A scan range with a 0 endpoint. Every expanded value is checked
        # (not just the endpoints), so both values here (0 and 2.0) must be
        # individually legal -- 0 exempt as FLAT, 2.0 exactly the minimum.
        hard, _ = ctrl._scan_command_issues("rhm 0 2 2", "", mono, ana)
        assert hard == []


def test_an_explicit_value_on_a_fixed_axis_is_refused_via_the_api():
    """PUMA's rva is fixed at 0.8 m; even though the API has no rva field
    (a later slice), the checker itself refuses a fixed-axis mismatch --
    exercised here through ``_curvature_axis_specs`` + ``curvature_command_error``
    the same way ``build_api_launch_state`` would for any future HELD axis,
    and already the path the GUI's Ideal-lock bypass takes for rva."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        specs = ctrl._curvature_axis_specs(mono, ana)
        curvature_axis, crystal_name = specs["rva"]
        assert curvature_axis.driven is False

        error = curvature_command_error("rva", 0.3, curvature_axis, crystal_name)
        assert error is not None
        assert "0.8" in error and "rva" in error


def test_an_autofocus_ideal_outside_travel_is_still_clamped_not_refused():
    """Refusing an AUTOFOCUS ideal would break a legitimate scan whose
    optimum leaves the bender's reach -- nobody chose that number. PUMA's
    rha ideal at ath=60 deg two-theta clamps up to its 2.0 m declared
    minimum (pinned directly at the producer level by
    test_curvature_autofocus.py); this pins that build_api_launch_state
    still emits the clamped value instead of raising."""
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "mtt": 41.167, "att": 60.0,
            "scan_command1": "deltaE 0 1 0.5",
        })
        vals = launch["vals"]
        assert vals["curvature_modes"]["rha"] == cm.CurvatureMode.AUTOFOCUS
        assert abs(vals["rha"]) == pytest.approx(2.0)


def test_puma_nmo_refuses_a_scanned_rhm_naming_the_nmo():
    """Packet slice 9, defect A, test 1: a nested mirror optic (NMO) fixes
    PUMA's rhm/rvm flat -- a legal-looking 'rhm 2.5 3.0 0.5' scan command
    must be REFUSED, not silently run against a monochromator the rest of
    the code insists must stay flat.

    Red first: before this slice, ``PUMAPlugin.scan_config`` and
    ``PUMA_Instrument.optical_radii`` each zeroed rhm/rvm independently, and
    neither is reached by a SCANNED axis -- so this exact command ran and
    bent the "flat" monochromator, on both the API and GUI submission paths.
    """
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        modules = {"nmo": "Vertical", "v_selector": False}

        hard, _ = ctrl._scan_command_issues(
            "rhm 2.5 3.0 0.5", "", mono, ana, modules
        )
        assert hard, "a scan over an NMO-fixed rhm must hard-block"
        assert "rhm" in hard[0] and "fixed" in hard[0]

        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.instrument_dock.set_module_values(modules)
        ctrl.window.simulation_dock.scan_command_1_edit.setText("rhm 2.5 3.0 0.5")
        ctrl.window.simulation_dock.scan_command_2_edit.setText("")
        hard_gui, _ = ctrl._preflight_scan_validation()
        assert hard_gui, "the GUI Run gate must refuse the identical scan"
        assert "rhm" in hard_gui[0]

        # Without the NMO, the identical command is a perfectly legal scan --
        # the refusal is the NMO's doing, not an accident of the axis name.
        hard_flat, _ = ctrl._scan_command_issues(
            "rhm 2.5 3.0 0.5", "", mono, ana, {"nmo": "None", "v_selector": False}
        )
        assert hard_flat == []


def test_a_non_finite_commanded_radius_is_refused_at_the_api_launch_path():
    """The wiring test: a NaN reaching ``build_api_launch_state`` -- exactly
    how a real API client's JSON string field arrives -- must be refused, not
    accepted and forwarded to McStas as ``rhm_param=nan``.

    It is refused at the PARSE boundary (``invalid_parameters``) rather than
    by ``curvature_command_error`` (``curvature_out_of_travel``), because the
    radius fields' parser rejects a non-finite value before the command
    checker is ever reached. That is the earlier and more precise of the two:
    "your numeric value is invalid" is a different thing from "this radius
    conflicts with the mechanical travel", and a client can now tell them
    apart without parsing prose.
    """
    with _controller("puma") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        with pytest.raises(cm.ApiError) as excinfo:
            ctrl.build_api_launch_state({
                "monocris": mono, "anacris": ana,
                "rhm": "nan",
                "scan_command1": "deltaE 0 1 0.5",
            })
        assert excinfo.value.status == 400
        assert excinfo.value.code == "invalid_parameters"
        assert "finite" in excinfo.value.details["errors"]["rhm"]


@pytest.mark.parametrize("cmd", ["rhm nan 4 1", "rhm 0 inf 1", "rhm 0 4 nan",
                                 "deltaE nan 4 1"])
def test_a_non_finite_scan_bound_is_refused_not_raised(cmd):
    """A structured refusal, not a 500.

    ``float()`` accepts "nan"/"inf", and every guard after the conversion
    compares magnitudes -- all False against NaN -- so a non-finite bound used
    to reach ``parse_scan_steps``, whose ``int()`` of the step count raises
    ``ValueError``/``OverflowError``. Uncaught, a client submitting
    ``"rhm nan 4 1"`` got a 500 where it should have got the documented scan
    rejection. Covers a non-curvature variable too: the hole was in the shared
    numeric conversion, not in the curvature branch.
    """
    with _controller("puma") as ctrl:
        var, error = ctrl._validate_single_scan_command(cmd)
        assert error is not None
        assert "finite" in error


@pytest.mark.parametrize("axis", ["rhm", "rvm", "rha", "rva"])
def test_a_typed_non_finite_radius_is_refused_by_the_resolution_gate(axis):
    """The GUI twin of the API's parse-time refusal.

    The radius line edits are unrestricted, so an operator can type "nan".
    ``compute_resolution`` builds its check state through ``scan_config``,
    which assigns the value straight onto a fresh state -- upstream of
    ``set_crystal_bending``'s backstop, which preserves the EXISTING radius
    and so cannot help once that radius is itself the NaN.
    """
    with _controller("puma") as ctrl:
        edit = getattr(ctrl.window.instrument_dock, f"{axis}_edit")
        edit.setText("nan")

        result = ctrl.compute_resolution(H=1.0, K=0.0, L=0.0, deltaE=0.0)
        assert result["ok"] is False
        assert "finite" in result["reason"]
        assert axis in result["reason"]


def test_a_toggle_module_accepts_pythons_ordinary_bool_leniency():
    """Pinned, not accidental: ``p_bool`` accepts any int and coerces it, so
    a TOGGLE module takes ``1``/``0`` as well as ``true``/``false``.

    That leniency is ``p_bool``'s contract for EVERY boolean field in this API
    (``diagnostic_mode`` included), so tightening it for modules alone would
    trade one inconsistency for another. Tightening it API-wide is a separate
    decision; this test exists so the behaviour is deliberate and a future
    change to it is visible.
    """
    with _controller("puma") as ctrl:
        applied, errors = ctrl.apply_parameters({"modules": {"v_selector": 1}})
        assert errors == {}
        assert applied["modules"]["v_selector"] is True

        _, bad = ctrl.apply_parameters({"modules": {"v_selector": "yes"}})
        assert "modules" in bad


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_a_non_finite_radius_never_reaches_the_widget_through_patch(bad):
    """PATCH must refuse what launch refuses.

    ``p_float`` is a bare ``float()``, so a PATCH of ``{"rhm": "nan"}`` used
    to parse and land in the line edit. Nothing downstream caught it:
    ``compute_resolution`` (behind ``GET /resolution``) copies GUI values
    into a config by direct assignment, never crossing
    ``curvature_command_error``, and ``set_crystal_bending``'s backstop only
    refuses a non-finite it is HANDED -- it cannot undo one already sitting
    in the field. So the refusal has to happen at the parse boundary.
    """
    with _controller("puma") as ctrl:
        before = ctrl.window.instrument_dock.rhm_edit.text()

        applied, errors = ctrl.apply_parameters({"rhm": bad})

        assert "rhm" not in applied
        assert "finite" in errors["rhm"]
        assert ctrl.window.instrument_dock.rhm_edit.text() == before


@pytest.mark.parametrize("instrument_id", ["in8", "panda"])
def test_instruments_with_no_declared_travel_refuse_nothing(instrument_id):
    """IN8 and PANDA declare no mechanical travel at all -- that asymmetry
    with PUMA/IN12 is correct and must not be "fixed" by inventing limits."""
    with _controller(instrument_id) as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id

        launch = ctrl.build_api_launch_state({
            "monocris": mono, "anacris": ana,
            "rhm": 1000.0,
            "scan_command1": "deltaE 0 1 0.5",
        })
        assert launch["vals"]["rhm"] == 1000.0

        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ctrl.window.instrument_dock.rhm_edit.setText("1000")
        assert ctrl._held_curvature_issues(mono, ana) == []

        hard, _ = ctrl._scan_command_issues("rhm 0.01 1000.0 10", "", mono, ana)
        assert hard == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("instrument_id", ["puma", "in8", "in12", "panda"])
def test_the_applier_refuses_a_non_finite_radius_too(instrument_id, bad):
    """The APPLICATION half of the finite invariant.

    ``curvature_command_error`` closes the three submission gates, but
    ``set_crystal_bending``'s own docstring calls itself the backstop for
    "any caller that reaches this setter directly without going through a
    submission gate" -- and a non-finite value survives every magnitude
    comparison in it (``abs``, the clamp, the sign), so it used to be stored
    and emitted as a non-finite McStas parameter. The existing radius is kept
    instead, exactly as the zero-take-off guard does: there is no meaningful
    radius here to apply.
    """
    instrument = get_instrument(instrument_id)
    d = instrument.descriptor()
    state = instrument.default_state()
    state.monocris = d.mono_crystals[0].id
    state.anacris = d.ana_crystals[0].id
    state.set_angles(A1=41.167, A2=0.0, A3=0.0, A4=41.167)

    state.set_crystal_bending(rhm=5.0)
    kept = state.rhm
    assert math.isfinite(kept)

    state.set_crystal_bending(rhm=bad)
    assert state.rhm == kept, "a non-finite radius must not replace a real one"
    assert math.isfinite(state.rhm)
