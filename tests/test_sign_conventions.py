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


def test_solver_positive_sample_sense_flips_stt_and_roundtrips():
    q_target = np.array([TAU, TAU, 0.0])
    left = solve_instrument_angles(q_target, KI_14P7, KI_14P7, sense_sample=1)
    right = solve_instrument_angles(q_target, KI_14P7, KI_14P7, sense_sample=-1)
    assert left.stt == pytest.approx(-right.stt, abs=1e-12)
    assert left.stt > 0
    # A flipped branch is still real physics: the angles must reproduce Q.
    q_back = q_instrument_from_angles(left.sth, left.saz, left.stt, KI_14P7, KI_14P7)
    assert q_back == pytest.approx(q_target, abs=1e-9)


# ---------------------------------------------------------------------------
# TAS_Instrument goldens (full angle pipeline through crystal lookup)
# ---------------------------------------------------------------------------

pytest.importorskip("mcstasscript")


@pytest.fixture(scope="module")
def tas():
    from instruments.PUMA_instrument_definition import TAS_Instrument

    return TAS_Instrument()


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
    from instruments.PUMA_instrument_definition import TAS_Instrument

    flipped = TAS_Instrument()
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
    # NOT the mirror of the baked -35.63: the sample rotation axis does not
    # flip with the scattering side, so sth = phi_target - (180 - phi_lab),
    # i.e. -144.37 (== +215.63 mod 360). The round-trip below is the proof
    # that this branch is physical.
    assert sth == pytest.approx(-144.374780, abs=1e-3)
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
