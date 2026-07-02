"""Golden sign-convention tests (design record §16.7, Phase 4).

TAVI's angle solvers historically bake one sign convention: monochromator and
analyzer two-theta positive, sample two-theta negative — senses (+1, -1, +1)
in vTAS notation. IN8 flips sample AND analyzer (+1, +1, -1), so before any
sense threading lands these goldens freeze the PUMA-era behavior exactly.
Values below were generated from the unmodified code (gen_sign_goldens.py,
2026-07-02); tolerance 1e-3 deg. Signs are asserted explicitly — a sign
regression must fail loudly even if a magnitude happens to match.

The pure-solver tests need only tavi/; the TAS_Instrument tests import the
PUMA instrument definition and therefore skip without mcstasscript.
"""
import math

import numpy as np
import pytest

from tavi.neutron_conversions import energy2k
from tavi.tas_geometry import q_instrument_from_angles, solve_instrument_angles

AL_A = 4.05
TAU = 2 * math.pi / AL_A          # (1 0 0) in inverse Angstroms
KI_14P7 = energy2k(14.7)          # 2.663442


# ---------------------------------------------------------------------------
# Pure solver goldens (no mcstasscript required)
# ---------------------------------------------------------------------------

def test_solver_elastic_200_signs_and_values():
    angles = solve_instrument_angles(np.array([2 * TAU, 0.0, 0.0]), KI_14P7, KI_14P7)
    assert angles.stt == pytest.approx(-71.250440, abs=1e-3)
    assert angles.sth == pytest.approx(-35.625220, abs=1e-3)
    assert angles.saz == pytest.approx(0.0, abs=1e-6)
    # The baked convention: sample two-theta branch is negative.
    assert angles.stt < 0
    assert angles.sth < 0


def test_solver_skew_q_sth_sign_flips_across_quadrants():
    angles = solve_instrument_angles(np.array([TAU, TAU, 0.0]), KI_14P7, KI_14P7)
    assert angles.stt == pytest.approx(-48.645490, abs=1e-3)
    assert angles.sth == pytest.approx(20.677255, abs=1e-3)
    assert angles.stt < 0
    assert angles.sth > 0


def test_solver_out_of_plane_saz_sign():
    angles = solve_instrument_angles(np.array([1.55, 0.0, 0.3]), KI_14P7, KI_14P7)
    assert angles.stt == pytest.approx(-34.480243, abs=1e-3)
    assert angles.sth == pytest.approx(-17.240121, abs=1e-3)
    # saz = -atan2(qz, |q_horizontal|): positive qz tilts negative.
    assert angles.saz == pytest.approx(-10.954063, abs=1e-3)


def test_solver_roundtrip_recovers_q():
    q_target = np.array([TAU, TAU, 0.0])
    angles = solve_instrument_angles(q_target, KI_14P7, KI_14P7)
    q_back = q_instrument_from_angles(angles.sth, angles.saz, angles.stt, KI_14P7, KI_14P7)
    assert q_back == pytest.approx(q_target, abs=1e-9)


# ---------------------------------------------------------------------------
# Sense threading (Phase 4): defaults must be bit-identical to the baked
# convention; explicit senses must flip signs AND stay physical.
# ---------------------------------------------------------------------------

def test_solver_default_equals_explicit_baked_sense():
    for q in ([2 * TAU, 0.0, 0.0], [TAU, TAU, 0.0], [1.55, 0.0, 0.3]):
        implicit = solve_instrument_angles(np.array(q), KI_14P7, KI_14P7)
        explicit = solve_instrument_angles(
            np.array(q), KI_14P7, KI_14P7, sense_sample=-1
        )
        assert implicit == explicit  # bit-for-bit, not approx


def test_solver_positive_sample_sense_follows_vtas_friedel_convention():
    """The +1 branch aligns the Friedel partner -Q with the scattered beam
    (vTAS convention, verified live against IN8 2026-07-02), so the raw
    inverse recovers -Q and instrument-level callers negate it back."""
    q_target = np.array([TAU, TAU, 0.0])
    left = solve_instrument_angles(q_target, KI_14P7, KI_14P7, sense_sample=1)
    right = solve_instrument_angles(q_target, KI_14P7, KI_14P7, sense_sample=-1)
    assert left.stt == pytest.approx(-right.stt, abs=1e-12)
    assert left.stt > 0
    assert left.sth == pytest.approx(69.322745, abs=1e-3)
    q_back = q_instrument_from_angles(left.sth, left.saz, left.stt, KI_14P7, KI_14P7)
    assert q_back == pytest.approx(-q_target, abs=1e-9)   # Friedel partner


def test_solver_positive_sample_sense_out_of_plane():
    q_target = np.array([1.55, 0.0, 0.3])
    flipped = solve_instrument_angles(q_target, KI_14P7, KI_14P7, sense_sample=1)
    assert flipped.stt == pytest.approx(+34.480243, abs=1e-3)
    assert flipped.sth == pytest.approx(+17.240121, abs=1e-3)
    assert flipped.saz == pytest.approx(+10.954063, abs=1e-3)  # -q flips saz too
    q_back = q_instrument_from_angles(flipped.sth, flipped.saz, flipped.stt,
                                      KI_14P7, KI_14P7)
    assert q_back == pytest.approx(-q_target, abs=1e-9)


# ---------------------------------------------------------------------------
# TAS_Instrument goldens (full angle pipeline through crystal lookup)
# ---------------------------------------------------------------------------

pytest.importorskip("mcstasscript")


@pytest.fixture(scope="module")
def tas():
    # PUMA_Instrument: crystal_info() dispatches through the state object, so
    # the goldens exercise a concrete instrument (bare TAS_Instrument raises).
    from instruments.PUMA_instrument_definition import PUMA_Instrument

    return PUMA_Instrument()


def _angles(tas, qx, qy, qz, deltaE, fixed_E, k_fixed):
    angles, error_flags = tas.calculate_angles(
        qx, qy, qz, deltaE, fixed_E, k_fixed, "pg002", "pg002"
    )
    assert error_flags == []
    return angles


def test_p1_elastic_200_ki_fixed(tas):
    mtt, stt, sth, saz, att = _angles(tas, 2 * TAU, 0.0, 0.0, 0.0, 14.7, "Ki Fixed")
    assert mtt == pytest.approx(41.166977, abs=1e-3)
    assert stt == pytest.approx(-71.250440, abs=1e-3)
    assert sth == pytest.approx(-35.625220, abs=1e-3)
    assert saz == pytest.approx(0.0, abs=1e-6)
    assert att == pytest.approx(41.166977, abs=1e-3)
    # Baked sign triple: (mtt, stt, att) signs are (+, -, +).
    assert mtt > 0 and stt < 0 and att > 0


def test_p2_inelastic_ki_fixed(tas):
    q = 1.7 * 2 * math.pi / 4.03893
    mtt, stt, sth, saz, att = _angles(tas, q, 0.0, 0.0, 2.0, 16.7, "Ki Fixed")
    assert mtt == pytest.approx(38.519165, abs=1e-3)
    assert stt == pytest.approx(-57.347828, abs=1e-3)
    assert sth == pytest.approx(-32.010030, abs=1e-3)
    assert att == pytest.approx(41.166977, abs=1e-3)


def test_p3_skew_q_elastic(tas):
    mtt, stt, sth, saz, att = _angles(tas, TAU, TAU, 0.0, 0.0, 14.7, "Ki Fixed")
    assert stt == pytest.approx(-48.645490, abs=1e-3)
    assert sth == pytest.approx(20.677255, abs=1e-3)
    assert stt < 0 and sth > 0


def test_p4_out_of_plane_saz(tas):
    mtt, stt, sth, saz, att = _angles(tas, 1.55, 0.0, 0.3, 0.0, 14.7, "Ki Fixed")
    assert saz == pytest.approx(-10.954063, abs=1e-3)


def test_p6_inelastic_kf_fixed(tas):
    mtt, stt, sth, saz, att = _angles(tas, 2 * TAU, 0.0, 0.0, 5.0, 14.7, "Kf Fixed")
    assert mtt == pytest.approx(35.359510, abs=1e-3)
    assert stt == pytest.approx(-64.876553, abs=1e-3)
    assert sth == pytest.approx(-38.996100, abs=1e-3)
    assert att == pytest.approx(41.166977, abs=1e-3)


def test_p5_reverse_recovers_q_and_deltaE(tas):
    mtt, stt, sth, saz, att = _angles(tas, 2 * TAU, 0.0, 0.0, 0.0, 14.7, "Ki Fixed")
    q_and_e, error_flags = tas.calculate_q_and_deltaE(
        mtt, stt, sth, saz, att, 14.7, "Ki Fixed", "pg002", "pg002"
    )
    assert error_flags == []
    qx, qy, qz, deltaE = q_and_e
    assert qx == pytest.approx(2 * TAU, abs=1e-6)
    assert qy == pytest.approx(0.0, abs=1e-6)
    assert qz == pytest.approx(0.0, abs=1e-6)
    assert deltaE == pytest.approx(0.0, abs=1e-6)


def test_instrument_senses_flip_mtt_att_and_recover_q():
    """A TAS state with IN8-style senses (+1, +1, -1) negates the affected
    angles and the reverse path still recovers (Q, deltaE)."""
    from instruments.PUMA_instrument_definition import PUMA_Instrument

    flipped = PUMA_Instrument()
    flipped.sense_mono = 1
    flipped.sense_sample = 1
    flipped.sense_ana = -1
    angles, error_flags = flipped.calculate_angles(
        2 * TAU, 0.0, 0.0, 0.0, 14.7, "Ki Fixed", "pg002", "pg002"
    )
    assert error_flags == []
    mtt, stt, sth, saz, att = angles
    assert mtt == pytest.approx(41.166977, abs=1e-3)
    assert stt == pytest.approx(+71.250440, abs=1e-3)
    # Friedel/vTAS convention for the flipped branch: -Q aligned with the
    # scattered beam, which lands sth on the mirror of the baked -35.63.
    assert sth == pytest.approx(+35.625220, abs=1e-3)
    assert att == pytest.approx(-41.166977, abs=1e-3)

    q_and_e, error_flags = flipped.calculate_q_and_deltaE(
        mtt, stt, sth, saz, att, 14.7, "Ki Fixed", "pg002", "pg002"
    )
    assert error_flags == []
    assert q_and_e[0] == pytest.approx(2 * TAU, abs=1e-6)
    assert q_and_e[1] == pytest.approx(0.0, abs=1e-6)
    assert q_and_e[2] == pytest.approx(0.0, abs=1e-6)
    assert q_and_e[3] == pytest.approx(0.0, abs=1e-6)


def test_default_instrument_senses_are_baked_convention():
    from instruments.PUMA_instrument_definition import PUMA_Instrument, TAS_Instrument

    for state in (TAS_Instrument(), PUMA_Instrument()):
        assert (state.sense_mono, state.sense_sample, state.sense_ana) == (1, -1, 1)


# ---------------------------------------------------------------------------
# IN8 goldens -- vTAS-verified 2026-07-02 (live run; magnitudes within 0.02
# deg, signs exact: a2 +, a4 +, a6 -, i.e. senses (+1, +1, -1)). Setup: cubic
# a=4.05, plane (1,0,0)/(0,1,0); kf fixed 2.662 (V1-V3), ki fixed 4.1 (V4).
# Mapping: TAVI A1 = vTAS a2, A2 = a4, A4 = a6, A3 = a3 (Friedel/-Q branch).
# The a3 convention is ALSO vTAS-verified: the user's live a3(V3) = 69.337
# matches TAVI's sth to three decimals, and a3(V1) = 125.647 is TAVI's value
# +90.000 exactly -- vTAS displayed the cubic-equivalent (0,2,0) setting for
# that point.
# ---------------------------------------------------------------------------

E_KF_2P662 = 14.684089   # k2energy(2.662)
E_KI_4P1 = 34.833620     # k2energy(4.1)


@pytest.fixture(scope="module")
def in8():
    from instruments.IN8_instrument_definition import IN8_Instrument

    return IN8_Instrument()


def _in8_angles(in8, qx, qy, qz, deltaE, fixed_E, k_fixed, mono="pg002"):
    angles, error_flags = in8.calculate_angles(
        qx, qy, qz, deltaE, fixed_E, k_fixed, mono, "pg002"
    )
    assert error_flags == []
    return angles


def test_in8_v1_elastic_200(in8):
    mtt, stt, sth, saz, att = _in8_angles(in8, 2 * TAU, 0.0, 0.0, 0.0,
                                          E_KF_2P662, "Kf Fixed")
    # vTAS live run: a2 = +41.19, a4 = +71.30, a6 = -41.19; a3 = 125.647
    # (= this sth + the cubic 90-deg setting vTAS happened to display).
    assert mtt == pytest.approx(41.190287, abs=1e-3)
    assert stt == pytest.approx(71.294923, abs=1e-3)
    assert att == pytest.approx(-41.190287, abs=1e-3)
    assert mtt > 0 and stt > 0 and att < 0
    assert sth == pytest.approx(+35.647462, abs=1e-3)


def test_in8_v2_inelastic_kf_fixed(in8):
    mtt, stt, sth, saz, att = _in8_angles(in8, 2 * TAU, 0.0, 0.0, 5.0,
                                          E_KF_2P662, "Kf Fixed")
    # vTAS live run: a2 = +35.37, a4 = +64.92, a6 = -41.19.
    assert mtt == pytest.approx(35.374270, abs=1e-3)
    assert stt == pytest.approx(64.910358, abs=1e-3)
    assert att == pytest.approx(-41.190287, abs=1e-3)


def test_in8_v3_skew_q(in8):
    mtt, stt, sth, saz, att = _in8_angles(in8, TAU, TAU, 0.0, 0.0,
                                          E_KF_2P662, "Kf Fixed")
    # vTAS live run: a4 = +48.69 (within 0.02 of the computed +48.674) and
    # a3 = 69.337 -- an exact three-decimal match to this sth.
    assert stt == pytest.approx(48.673546, abs=1e-3)
    assert sth == pytest.approx(+69.336773, abs=1e-3)


def test_in8_v4_cu200_ki_fixed(in8):
    mtt, stt, sth, saz, att = _in8_angles(in8, 2 * TAU, 0.0, 0.0, 10.0,
                                          E_KI_4P1, "Ki Fixed", mono="cu200")
    # vTAS live run: a2 = +50.18, a4 = +47.53, a6 = -31.39.
    assert mtt == pytest.approx(50.179956, abs=1e-3)
    assert stt == pytest.approx(47.530501, abs=1e-3)
    assert att == pytest.approx(-31.386970, abs=1e-3)


def test_in8_v1_reverse_recovers_q(in8):
    mtt, stt, sth, saz, att = _in8_angles(in8, 2 * TAU, 0.0, 0.0, 0.0,
                                          E_KF_2P662, "Kf Fixed")
    q_and_e, error_flags = in8.calculate_q_and_deltaE(
        mtt, stt, sth, saz, att, E_KF_2P662, "Kf Fixed", "pg002", "pg002"
    )
    assert error_flags == []
    assert q_and_e[0] == pytest.approx(2 * TAU, abs=1e-6)
    assert q_and_e[3] == pytest.approx(0.0, abs=1e-6)


def test_base_state_requires_instrument_dispatch():
    """The TAS base class must not silently resolve crystals against PUMA."""
    from instruments.PUMA_instrument_definition import TAS_Instrument

    with pytest.raises(NotImplementedError):
        TAS_Instrument().crystal_info("pg002", "pg002")
    with pytest.raises(NotImplementedError):
        TAS_Instrument().build_point_params(0.0)


def test_crystal_info_dict_shape_frozen():
    """The crystal-info dicts feed both the angle math and build(); the Phase-4
    dispatch refactor must not change their shape or the pg002 d-spacings."""
    from instruments.PUMA_instrument_definition import mono_ana_crystals_setup

    mono_info, ana_info = mono_ana_crystals_setup("pg002", "pg002")
    assert sorted(mono_info) == [
        "dm", "gap", "mosaic", "ncolumns", "nrows",
        "r0", "reflect", "slabheight", "slabwidth", "transmit",
    ]
    assert mono_info["dm"] == 3.355
    assert ana_info["da"] == 3.355
