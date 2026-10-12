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
