"""One API update applies in dependency order; contradictory writes are refused (PUMA, offscreen).

The reply's applied list must be literally true of the state afterwards: a later
explicit value is never overwritten by an earlier group's derivation, and a write
whose values cannot all hold (a position beside a stage motor, an angle beside
another energy) is refused before anything changes. The launch (POST /scan patch)
follows the same rules; a crystal-motor or energy patch there keeps the stage and
derives the position from the motors.
"""
import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from test_orientation_gui import _controller_for  # noqa: E402
from tavi.neutron_conversions import energy2k, k2energy  # noqa: E402

TOL = 2e-3   # the docks show four decimals
SCAN = "rhm 2 3 1"


@pytest.fixture
def ctrl():
    yield from _controller_for("puma")


@pytest.fixture(scope="module")
def launcher():
    """A controller that is only asked for launch states (it never changes)."""
    yield from _controller_for("puma")


def _forward(ctrl, p):
    """Q and deltaE of the instrument's own forward kinematics at the motors in ``p``."""
    vals = ctrl.get_gui_values()
    q, errors = ctrl.instrument_state.calculate_q_and_deltaE(
        p["mono_two_theta_deg"], p["sample_two_theta_deg"], p["sample_rotation_deg"],
        p["sample_lower_arc_deg"], p["analyzer_two_theta_deg"],
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"],
        sgu=p["sample_upper_arc_deg"])
    assert not errors, errors
    return q


def _assert_follows_motors(ctrl):
    p = ctrl.api_parameters()
    qx, qy, qz, dE = _forward(ctrl, p)
    assert [p["q_instrument_x_inv_angstrom"], p["q_instrument_y_inv_angstrom"],
            p["q_instrument_z_inv_angstrom"], p["energy_transfer_mev"]] == pytest.approx(
        [qx, qy, qz, dE], abs=TOL)
    hkl = ctrl._sample_q_to_hkl(qx, qy, qz, ctrl.get_gui_values())
    assert [p["h"], p["k"], p["l"]] == pytest.approx(list(hkl), abs=TOL)


def _assert_read_back(ctrl, applied):
    """Every key the reply lists as applied holds the value it was sent."""
    state = ctrl.api_parameters()
    for key, value in applied.items():
        if isinstance(value, (int, float)):
            assert state[key] == pytest.approx(value, abs=TOL), key
        else:
            assert state[key] == value, key


def _fixed_energy(ctrl):
    return ctrl.get_gui_values()["fixed_E"]


# ---------------------------------------------------------------- grouped apply

def test_a_lattice_constant_beside_h_leaves_h_as_sent(ctrl):
    applied, errors = ctrl.apply_parameters({"lattice_a_angstrom": 4.2, "h": 1.0})
    assert not errors
    state = ctrl.api_parameters()
    assert state["lattice_a_angstrom"] == pytest.approx(4.2)
    assert state["h"] == pytest.approx(1.0, abs=TOL)   # 2.05 before: the lattice callback ran last


def test_an_energy_transfer_beside_a4_gives_the_energies_and_the_motors(ctrl):
    applied, errors = ctrl.apply_parameters({"deltaE": 3.0, "A4": 60.0})
    assert not errors
    state = ctrl.api_parameters()
    assert state["energy_transfer_mev"] == pytest.approx(3.0, abs=TOL)
    assert state["sample_two_theta_deg"] == pytest.approx(60.0, abs=TOL)
    assert state["incident_energy_mev"] - state["final_energy_mev"] == pytest.approx(3.0, abs=TOL)
    _assert_follows_motors(ctrl)


def _agreeing_energies(ctrl):
    held = _fixed_energy(ctrl)   # Kf is fixed on the dock's default state
    return {"Ei": held + 3.0, "deltaE": 3.0}


def _agreeing_wavevector(ctrl):
    k = 2.5
    return {"Ki": k, "Ei": k2energy(k)}


READ_BACK = {
    "lattice and h": lambda ctrl: {"lattice_a_angstrom": 4.2, "h": 1.0},
    "energy transfer and a4": lambda ctrl: {"deltaE": 3.0, "A4": 60.0},
    "q beside a2": lambda ctrl: {"qx": 2.0, "qy": 1.0, "qz": 0.0, "A2": 30.0},
    "a2 alone": lambda ctrl: {"A2": 30.0},
    "ei alone": lambda ctrl: {"Ei": 20.0},
    "ki fixed and ei": lambda ctrl: {"K_fixed": "Ki Fixed", "Ei": 20.0},
    "fixed energy and h": lambda ctrl: {"fixed_E": 12.0, "H": 1.0},
    "fixed energy and the free side": lambda ctrl: {"fixed_E": 12.0, "Ei": 20.0},
    "ki fixed and ef": lambda ctrl: {"K_fixed": "Ki Fixed", "Ef": 12.0},
    "ei and the transfer it implies": _agreeing_energies,
    "ki and the ei it implies": _agreeing_wavevector,
    "a3 and an arc": lambda ctrl: {"A3": 10.0, "sgl": 1.0},
    "a2 and its crystal": lambda ctrl: {
        "monocris": ctrl.descriptor.mono_crystals[-1].id, "A2": 40.0},
}


@pytest.mark.parametrize("case", sorted(READ_BACK))
def test_every_applied_key_reads_back(ctrl, case):
    patch = READ_BACK[case](ctrl)
    applied, errors = ctrl.apply_parameters(patch)
    assert not errors, errors
    assert applied
    _assert_read_back(ctrl, applied)


def test_a2_beside_q_reads_back_as_sent(ctrl):
    # A2 sets the energy; the stage then reaches Q at that energy, so both hold.
    applied, errors = ctrl.apply_parameters({"qx": 2.0, "qy": 1.0, "qz": 0.0, "A2": 30.0})
    assert not errors
    state = ctrl.api_parameters()
    assert state["mono_two_theta_deg"] == pytest.approx(30.0, abs=TOL)   # 41.167 before
    assert [state["q_instrument_x_inv_angstrom"], state["q_instrument_y_inv_angstrom"],
            state["q_instrument_z_inv_angstrom"]] == pytest.approx([2.0, 1.0, 0.0], abs=TOL)
    _assert_follows_motors(ctrl)


# ----------------------------------------------- the PATCH half of "follow the motors"

@pytest.mark.parametrize("patch", [{"A2": 40.0}, {"A6": 50.0}, {"Ei": 20.0}, {"Kf": 2.0}])
def test_a_motor_or_energy_patch_leaves_q_hkl_and_the_transfer_at_the_motors(ctrl, patch):
    applied, errors = ctrl.apply_parameters(patch)
    assert not errors
    _assert_follows_motors(ctrl)


# -------------------------------------------------- position beside a stage motor

@pytest.mark.parametrize("position", ["h", "qx"])
@pytest.mark.parametrize("motor", ["sample_lower_arc_deg", "A3", "A4", "sgu"])
def test_a_position_beside_a_stage_motor_is_refused_and_changes_nothing(ctrl, position, motor):
    before = copy.deepcopy(ctrl.get_gui_values())
    applied, errors = ctrl.apply_parameters({position: 1.0, motor: 2.0})
    assert applied == {}
    assert set(errors) == {position, motor}
    for message in errors.values():
        assert "decides the stage" in message
        assert position in message or cm._to_public(position) in message
    assert ctrl.get_gui_values() == before


def test_the_launch_refuses_a_position_beside_a_stage_motor(launcher):
    with pytest.raises(cm.ApiError) as refused:
        launcher.build_api_launch_state({"h": 1.0, "A3": 12.0, "scan_command1": SCAN})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    assert "h" in refused.value.message
    assert "sample_rotation_deg" in refused.value.message
    assert set(refused.value.details["errors"]) == {"h", "A3"}


def test_a_stage_motor_alone_keeps_the_stage_at_the_callers(launcher):
    held = launcher.build_api_launch_state({"scan_command1": SCAN})["vals"]
    vals = launcher.build_api_launch_state({"A3": 12.0, "scan_command1": SCAN})["vals"]
    assert vals["omega"] == 12.0
    assert (vals["stt"], vals["sgl"], vals["sgu"], vals["mtt"], vals["att"]) == (
        held["stt"], held["sgl"], held["sgu"], held["mtt"], held["att"])


# --------------------------------------------- the launch follows the motors

def _launch_follows_motors(launcher, patch):
    state = launcher.build_api_launch_state({**patch, "scan_command1": SCAN})
    vals = state["vals"]
    q, errors = launcher.instrument_state.calculate_q_and_deltaE(
        vals["mtt"], vals["stt"], vals["omega"], vals["sgl"], vals["att"],
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"], sgu=vals["sgu"])
    assert not errors, errors
    assert [vals["qx"], vals["qy"], vals["qz"], vals["deltaE"]] == pytest.approx(list(q), abs=1e-9)
    hkl = launcher._sample_q_to_hkl(q[0], q[1], q[2], vals)
    assert [vals["H"], vals["K"], vals["L"]] == pytest.approx(list(hkl), abs=1e-9)
    return vals


@pytest.mark.parametrize("patch", [
    {"A4": 40.0}, {"A2": 40.0, "A4": 40.0}, {"A2": 40.0}, {"A6": 50.0}, {"Ei": 20.0},
    {"Ki": 2.0}, {"Ef": 12.0}, {"Kf": 2.0}, {"A3": 20.0}, {"sgl": 1.0, "A2": 40.0},
])
def test_a_motor_or_energy_launch_patch_derives_the_position_from_its_motors(launcher, patch):
    default = launcher.build_api_launch_state({"scan_command1": SCAN})["vals"]
    vals = _launch_follows_motors(launcher, patch)
    named = {cm._to_internal(name) for name in launcher._api_resolve_patch(
        patch, launcher._api_field_map())[0]}
    # The stage is the default state's except for the motors the caller named.
    for key in ("stt", "omega", "sgl", "sgu"):
        if key not in named:
            assert vals[key] == default[key], key


@pytest.mark.parametrize("route", ["dock", "patch"])
@pytest.mark.parametrize("field, edit, value", [
    ("A2", "mtt_edit", 40.0), ("A6", "att_edit", 50.0), ("Ei", "Ei_edit", 20.0),
    ("Kf", "Kf_edit", 2.0),
])
def test_the_dock_patch_and_launch_give_one_answer_for_the_same_motors(ctrl, route, field, edit, value):
    launch = ctrl.build_api_launch_state({field: value, "scan_command1": SCAN})["vals"]
    if route == "dock":
        widget = getattr(ctrl.window.instrument_dock, edit)
        widget.setText(cm.format_editable_number(value))
        widget.editingFinished.emit()
    else:
        applied, errors = ctrl.apply_parameters({field: value})
        assert not errors
    state = ctrl.api_parameters()
    expected = {"mono_two_theta_deg": launch["mtt"], "sample_two_theta_deg": launch["stt"],
                "sample_rotation_deg": launch["omega"], "analyzer_two_theta_deg": launch["att"],
                "q_instrument_x_inv_angstrom": launch["qx"], "q_instrument_y_inv_angstrom": launch["qy"],
                "q_instrument_z_inv_angstrom": launch["qz"], "energy_transfer_mev": launch["deltaE"],
                "h": launch["H"], "k": launch["K"], "l": launch["L"],
                "incident_energy_mev": launch["Ei"], "final_energy_mev": launch["Ef"]}
    assert {key: state[key] for key in expected} == pytest.approx(expected, abs=TOL)


def test_a_named_energy_beside_the_fixed_energy_wins_in_the_launch(launcher):
    vals = launcher.build_api_launch_state(
        {"fixed_E": 12.0, "Ei": 20.0, "scan_command1": SCAN})["vals"]
    assert (vals["Ei"], vals["Ef"], vals["fixed_E"]) == pytest.approx((20.0, 12.0, 12.0))
    assert vals["deltaE"] == pytest.approx(8.0)
    vals = launcher.build_api_launch_state(
        {"K_fixed": "Ki Fixed", "Ef": 12.0, "scan_command1": SCAN})["vals"]
    assert (vals["Ef"], vals["fixed_E"], vals["Ei"]) == pytest.approx((12.0, vals["Ei"], vals["Ei"]))
    assert vals["deltaE"] == pytest.approx(vals["Ei"] - 12.0)


def test_a_named_position_beside_a_crystal_motor_still_solves_the_stage(launcher):
    vals = launcher.build_api_launch_state(
        {"qx": 2.0, "qy": 1.0, "qz": 0.0, "A2": 30.0, "scan_command1": SCAN})["vals"]
    assert vals["mtt"] == 30.0
    assert [vals["qx"], vals["qy"], vals["qz"]] == [2.0, 1.0, 0.0]
    q, errors = launcher.instrument_state.calculate_q_and_deltaE(
        vals["mtt"], vals["stt"], vals["omega"], vals["sgl"], vals["att"],
        vals["fixed_E"], vals["K_fixed"], vals["monocris"], vals["anacris"], sgu=vals["sgu"])
    assert not errors
    assert list(q[:3]) == pytest.approx([2.0, 1.0, 0.0], abs=1e-6)


# ------------------------------------------------------------- contradictions

def _contradictions(ctrl):
    held = _fixed_energy(ctrl)
    return {
        "ki beside ei": {"Ki": 2.5, "Ei": 20.0},
        "transfer beside a2, kf held": {"deltaE": 99.0, "A2": 40.0},
        "a2 beside another ei": {"A2": 40.0, "Ei": 10.0},
        "q beside another h": {"qx": 2.0, "qy": 0.0, "qz": 0.0, "h": 5.0},
        "ei beside a transfer it does not make": {"Ei": held + 3.0, "deltaE": 7.0},
        "ef beside a6 elsewhere": {"A6": 50.0, "Ef": 3.0},
    }


CONTRADICTION_CASES = ["ki beside ei", "transfer beside a2, kf held", "a2 beside another ei",
                       "q beside another h", "ei beside a transfer it does not make",
                       "ef beside a6 elsewhere"]


@pytest.mark.parametrize("case", CONTRADICTION_CASES)
def test_contradicting_values_in_one_patch_are_refused_and_change_nothing(ctrl, case):
    patch = _contradictions(ctrl)[case]
    before = copy.deepcopy(ctrl.get_gui_values())
    applied, errors = ctrl.apply_parameters(patch)
    assert applied == {}
    assert len(errors) == 2
    assert set(errors) <= set(patch)
    assert ctrl.get_gui_values() == before


@pytest.mark.parametrize("case", CONTRADICTION_CASES)
def test_the_launch_refuses_the_same_contradictions(launcher, case):
    patch = _contradictions(launcher)[case]
    if case == "ei beside a transfer it does not make":
        patch = {"Ei": launcher._default_parameter_values()["fixed_E"] + 3.0, "deltaE": 7.0}
    with pytest.raises(cm.ApiError) as refused:
        launcher.build_api_launch_state({**patch, "scan_command1": SCAN})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")


def test_an_agreeing_launch_patch_is_accepted_and_every_value_holds(launcher):
    held = launcher._default_parameter_values()["fixed_E"]
    vals = launcher.build_api_launch_state(
        {"Ei": held + 3.0, "deltaE": 3.0, "scan_command1": SCAN})["vals"]
    assert vals["Ei"] == pytest.approx(held + 3.0)
    assert vals["deltaE"] == pytest.approx(3.0, abs=1e-6)
    vals = launcher.build_api_launch_state(
        {"Ki": energy2k(20.0), "Ei": 20.0, "scan_command1": SCAN})["vals"]
    assert vals["Ei"] == pytest.approx(20.0, abs=1e-6)
