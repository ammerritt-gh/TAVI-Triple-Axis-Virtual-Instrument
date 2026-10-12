"""A scan launched with A2 or A6 at exactly zero runs: the crystal transmits, its energy is absent.

TAVI's standing rule (docs/CONFIGURABLE_INSTRUMENTS.md 22.4): a crystal at exactly zero
take-off selects no energy, so that energy is recorded absent (None), never invented, and the
point runs through the transmission path. ``build_api_launch_state`` used to invert the zero
angle to a zero energy and refuse it as "both must be positive". It now keeps the raw zero
motor, records that side's energy and wavevector as None, lets the other side follow the fixed
mode, skips the stage-from-Q solve and the forward position derivation (both need both
energies), and says so in the launch's warnings. A scan that re-solves the crystal angles per
point (an H, K, L or Q scan) cannot keep the zero and is refused.

A launch whose forward derivation from the motors flags keeps the previous position and says
so in the same warnings; forward scattering (A4 = 0 at equal energies, Q = 0 exactly) is a
position, recorded as Q = 0 and H, K, L = 0 with a warning that names it.
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from instruments.tas_runtime import compute_scan_snapshot  # noqa: E402
from tavi.neutron_conversions import energy2k, k2angle  # noqa: E402

INSTRUMENT_IDS = [info.id for info in available_instruments()]
DIRECT_SCAN = "A4 20 22 1"   # a direct-motor scan: no calculation, the crystals stay as patched


@pytest.fixture(scope="module", params=INSTRUMENT_IDS)
def ctrl(request):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(request.param)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=request.param, save_selection=lambda _id: None,
    )
    controller = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield controller
    finally:
        controller.shutdown()
        del window


def _launch(controller, patch, command=DIRECT_SCAN):
    return controller.build_api_launch_state({**patch, "scan_command1": command})


def _first_point(controller, launch):
    plan, expansion = controller._compile_launch(launch)
    return compute_scan_snapshot(plan, expansion.points[0], 0, launch["scan_config"],
                                 launch["vals"], "unused").metadata


def _warnings(controller, launch):
    return controller._scan_command_warnings(launch)


def test_a_zero_mono_two_theta_launches_with_the_incident_energy_absent(ctrl):
    default = ctrl._default_parameter_values()
    launch = _launch(ctrl, {"A2": 0.0})   # refused today: "both must be positive"
    vals = launch["vals"]
    assert vals["mtt"] == 0.0
    assert vals["Ei"] is None and vals["Ki"] is None
    # The analyser side follows the fixed mode exactly as it did before the patch.
    assert vals["Ef"] == pytest.approx(default["Ef"]) and vals["Kf"] == pytest.approx(energy2k(default["Ef"]))
    assert vals["fixed_E"] == default["fixed_E"]
    metadata = _first_point(ctrl, launch)
    assert "mono" in metadata["transmission"]
    assert metadata["mtt"] == 0.0 and metadata["Ei"] is None and metadata["Ki"] is None
    assert metadata["Ef"] == pytest.approx(default["Ef"])
    # No energy to carry Q: the position keeps its previous value and the launch says so.
    assert (vals["qx"], vals["qy"], vals["qz"]) == (default["qx"], default["qy"], default["qz"])
    said = " ".join(_warnings(ctrl, launch))
    assert "Q, H, K, L" in said and "energy transfer" in said and "A2" in said


def test_a_zero_analyser_two_theta_launches_with_the_final_energy_absent(ctrl):
    default = ctrl._default_parameter_values()
    launch = _launch(ctrl, {"A6": 0.0})
    vals = launch["vals"]
    assert vals["att"] == 0.0
    assert vals["Ef"] is None and vals["Kf"] is None
    assert vals["Ei"] == pytest.approx(default["Ei"]) and vals["Ki"] == pytest.approx(energy2k(default["Ei"]))
    assert vals["fixed_E"] == default["fixed_E"]
    metadata = _first_point(ctrl, launch)
    assert "ana" in metadata["transmission"]
    assert metadata["att"] == 0.0 and metadata["Ef"] is None and metadata["Kf"] is None
    assert metadata["Ei"] == pytest.approx(default["Ei"])
    said = " ".join(_warnings(ctrl, launch))
    assert "Q, H, K, L" in said and "energy transfer" in said and "A6" in said


def test_a_zero_take_off_beside_a_named_energy_is_still_a_disagreement(ctrl):
    with pytest.raises(cm.ApiError) as refused:
        _launch(ctrl, {"A2": 0.0, "Ei": 12.0})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    assert "disagree" in refused.value.message


def test_an_energy_that_would_be_non_positive_is_still_refused(ctrl):
    default = ctrl._default_parameter_values()
    reach = default["fixed_E"] + 100.0   # leaves the free side far below zero
    delta = reach if default["K_fixed"] == "Ki Fixed" else -reach
    with pytest.raises(cm.ApiError) as refused:
        _launch(ctrl, {"deltaE": delta})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    assert "must be positive" in refused.value.message


def test_a_zero_take_off_beside_a_scan_that_re_solves_the_crystals_is_refused(ctrl):
    with pytest.raises(cm.ApiError) as refused:
        _launch(ctrl, {"A2": 0.0}, "H 1 2 0.5")
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    message = refused.value.message
    assert "mono_two_theta_deg" in message or "A2" in message
    assert "H 1 2 0.5" in message
    assert "re-solves" in message


def _equal_energy_mono_angle(controller, default):
    """An A2 whose Ki equals the fixed Kf bit for bit, so Q is exactly 0 at A4 = 0."""
    state = controller.instrument_state
    mono_info, _ = controller.instrument.crystal_info(default["monocris"], default["anacris"])
    angle = state.sense_mono * 2 * k2angle(energy2k(default["fixed_E"]), mono_info["dm"])
    for step in range(-6, 7):
        candidate = angle
        for _ in range(abs(step)):
            candidate = math.nextafter(candidate, math.inf if step > 0 else -math.inf)
        _, flags = state.calculate_q_and_deltaE(
            candidate, 0.0, default["omega"], default["sgl"], default["att"],
            default["fixed_E"], default["K_fixed"], default["monocris"], default["anacris"],
            sgu=default["sgu"])
        if flags:
            return candidate
    pytest.fail("no A2 within a few ulps gives exactly zero Q at A4 = 0")


def test_forward_scattering_at_equal_energies_is_recorded_as_zero_q(ctrl):
    default = ctrl._default_parameter_values()
    if default["K_fixed"] != "Kf Fixed":
        pytest.skip("the equal-energy A2 is built for the Kf-fixed default")
    a2 = _equal_energy_mono_angle(ctrl, default)
    launch = _launch(ctrl, {"A2": a2, "A4": 0.0})
    vals = launch["vals"]
    assert [vals["qx"], vals["qy"], vals["qz"]] == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
    assert [vals["H"], vals["K"], vals["L"]] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    assert vals["deltaE"] == pytest.approx(0.0, abs=1e-9)
    said = " ".join(_warnings(ctrl, launch))
    assert "forward scattering" in said and "A4" in said


def test_a_launch_whose_derivation_flags_keeps_the_previous_position_and_says_so(ctrl, monkeypatch):
    default = ctrl._default_parameter_values()
    monkeypatch.setattr(ctrl.instrument_state, "calculate_q_and_deltaE",
                        lambda *args, **kwargs: ([0, 0, 0, 0], ["invalid_crystal"]))
    launch = _launch(ctrl, {"A4": 40.0})
    vals = launch["vals"]
    assert (vals["qx"], vals["qy"], vals["qz"]) == (default["qx"], default["qy"], default["qz"])
    assert (vals["H"], vals["K"], vals["L"]) == (default["H"], default["K"], default["L"])
    assert vals["deltaE"] == default["deltaE"]
    said = " ".join(_warnings(ctrl, launch))
    assert "Q, H, K, L" in said and "energy transfer" in said
    assert "crystal" in said   # the derivation's own reason


@pytest.mark.parametrize("crystal", ["A2", "A6"])
@pytest.mark.parametrize("position", [{"h": 1.0}, {"K": 0.5}, {"qx": 1.0}, {"qz": 0.1}])
def test_a_position_beside_a_zero_take_off_is_refused(ctrl, crystal, position):
    """A transmitting crystal selects no energy, so no stage can be solved from the position."""
    with pytest.raises(cm.ApiError) as refused:
        _launch(ctrl, {crystal: 0.0, **position})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    message = refused.value.message
    assert crystal in message and next(iter(position)) in message
    assert "selects no energy" in message
    assert set(refused.value.details["errors"]) == {crystal, next(iter(position))}
