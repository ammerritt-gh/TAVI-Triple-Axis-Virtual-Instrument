"""Pre-PR reviewer P1/P2: a zero or wrong-sign step on a curvature axis must be
refused with the existing step message, never expanded (ZeroDivisionError /
negative linspace) -- the GUI validator runs on every keystroke and the API
path turns an exception into a 500."""
import pytest

from test_rva_gui_axis_policy import _controller


@pytest.mark.parametrize("command, expected", [
    ("rhm 2 4 0", "Step size cannot be zero."),
    ("rhm 4 2 0.5", "Step sign doesn't match direction"),
])
def test_step_guards_run_before_the_curvature_expansion(command, expected):
    with _controller("puma") as ctrl:
        mono = ctrl.descriptor.mono_crystals[0].id
        ana = ctrl.descriptor.ana_crystals[0].id
        # The single-command validator is what textChanged and the preflight
        # both call; before the fix this raised instead of returning.
        var, warning = ctrl._validate_single_scan_command(
            command, fixed_axes=None,
            curvature_axes=ctrl._curvature_axis_specs(mono, ana),
        )
        assert var == "rhm" and expected in (warning or ""), (var, warning)


def test_fixed_axis_policy_survives_a_degenerate_take_off_angle():
    """External reader P2: with no ideal to compute (att = 0), a module-fixed
    axis must still be disabled and show its resolved radius."""
    with _controller("puma") as ctrl:
        idock = ctrl.window.instrument_dock
        idock.rhm_edit.setText("2.5")
        idock.att_edit.setText("0")
        idock.nmo_combo.setCurrentText("Vertical")
        ctrl.update_ideal_bending_buttons()
        assert idock.rhm_edit.isEnabled() is False
        assert float(idock.rhm_edit.text()) == 0.0
        assert ctrl._held_curvature_issues(
            idock.selected_mono_id(), idock.selected_ana_id()) == []
