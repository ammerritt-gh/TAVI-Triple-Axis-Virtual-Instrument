"""The saved per-point energies must agree with the emitted crystal angles.

``calculate_angles`` picks the nominal Ei/Ef from ``K_fixed`` alone.
``point_energy_metadata`` used to consult ``source_type`` as well, so a
fixed-Ef point on the default (Maxwellian) source got angles for
(Ei = Ef + dE, Ef) alongside metadata for (Ei = fixed_E, Ef = fixed_E - dE).
Anything reconstructing kinematics or resolution from the saved Ki/Kf then
disagreed with the monochromator and analyser.

Both branches coincide at dE = 0, which is why the elastic smoke run could not
see it -- so every case here carries a nonzero transfer of both signs.
"""
import math

import pytest

pytest.importorskip("mcstasscript")

from instruments.in8.plugin import IN8Plugin
from instruments.tas_runtime import compute_scan_snapshot
from tavi.neutron_conversions import angle2k, k2energy

# qx qy qz dE | rhm rvm rha rva | chi kappa psi
_SCAN_POINT = ([2.0, 0.0, 0.5, None, 3.0, 1.2, 1.5, 0.31, 0.0, 0.0, 0.0], 0)

_FIXED_E = 14.68  # meV, the standard IN8 kf = 2.662 setting


def _snapshot(k_fixed, source_type, deltaE):
    plugin = IN8Plugin()
    vals = {
        "K_fixed": k_fixed,
        "source_type": source_type,
        "source_dE": 2,
        "rhm": 3.0, "rvm": 1.2, "rha": 1.5, "rva": 0.31,
        "fixed_E": _FIXED_E,
        "monocris": "pg002", "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
    scans, idx = _SCAN_POINT
    scans = list(scans)
    scans[3] = deltaE
    return compute_scan_snapshot((scans, idx), 0, "momentum", config, vals,
                                 data_folder=".")


@pytest.mark.parametrize("k_fixed", ["Ki Fixed", "Kf Fixed"])
@pytest.mark.parametrize("source_type", ["Maxwellian", "Mono"])
@pytest.mark.parametrize("deltaE", [-3.0, 2.0])
def test_saved_energies_match_the_crystal_angles(k_fixed, source_type, deltaE):
    meta = _snapshot(k_fixed, source_type, deltaE).metadata
    assert not _snapshot(k_fixed, source_type, deltaE).error_flags

    d_pg002 = 3.355
    # mtt/att are signed two-theta; k2angle returns theta, so halve and unsign.
    ki_from_angle = angle2k(abs(meta["mtt"]) / 2, d_pg002)
    kf_from_angle = angle2k(abs(meta["att"]) / 2, d_pg002)

    assert meta["Ki"] == pytest.approx(ki_from_angle, rel=1e-9)
    assert meta["Kf"] == pytest.approx(kf_from_angle, rel=1e-9)
    assert meta["Ei"] == pytest.approx(k2energy(ki_from_angle), rel=1e-9)
    assert meta["Ef"] == pytest.approx(k2energy(kf_from_angle), rel=1e-9)
    # ...and the pair actually encodes the requested transfer.
    assert meta["Ei"] - meta["Ef"] == pytest.approx(deltaE, rel=1e-9)
    assert meta["Ef"] > 0


@pytest.mark.parametrize("source_type", ["Maxwellian", "Mono"])
def test_fixed_ef_holds_ef_and_fixed_ki_holds_ei(source_type):
    """Which energy is held constant is a property of K_fixed, not the source."""
    for deltaE in (-3.0, 2.0):
        assert _snapshot("Kf Fixed", source_type, deltaE).metadata["Ef"] == _FIXED_E
        assert _snapshot("Ki Fixed", source_type, deltaE).metadata["Ei"] == _FIXED_E


def test_e0_param_stays_a_source_parameter():
    """E0_param describes the source, not the nominal energies.

    A "Mono" source is a narrow band steered onto the selected Ei; a Maxwellian
    source is a broadband moderator whose peak does not move with the scan.
    """
    assert _snapshot("Kf Fixed", "Mono", 2.0).metadata["E0_param"] == _FIXED_E + 2.0
    assert _snapshot("Kf Fixed", "Maxwellian", 2.0).metadata["E0_param"] == _FIXED_E
    assert _snapshot("Ki Fixed", "Mono", 2.0).metadata["E0_param"] == _FIXED_E


def _angle_snapshot(k_fixed, source_type, mtt, att, deltaE_field):
    """One ``angle``-mode point: the user drives A1..A4 directly."""
    plugin = IN8Plugin()
    vals = {
        "K_fixed": k_fixed,
        "source_type": source_type,
        "source_dE": 2,
        "rhm": 3.0, "rvm": 1.2, "rha": 1.5, "rva": 0.31,
        "fixed_E": _FIXED_E,
        "monocris": "pg002", "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
        "deltaE": deltaE_field,
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
    # A1 A2 A3 A4 | rhm rvm rha rva | chi kappa psi
    scans = [mtt, -71.25, -35.63, att, 3.0, 1.2, 1.5, 0.31, 0.0, 0.0, 0.0]
    return compute_scan_snapshot((scans, 0), 0, "angle", config, vals,
                                 data_folder=".")


@pytest.mark.parametrize("source_type", ["Maxwellian", "Mono"])
def test_angle_mode_reads_both_crystals(source_type):
    """In angle mode NEITHER energy is held at fixed_E.

    The user drives A1 and A4 directly, so Ei comes from the monochromator and
    Ef from the analyser, both of them, every point. Deriving only one from its
    angle and leaving the other at fixed_E made an A4 scan record a constant Ef
    while the analyser was visibly moving -- the same class of error as the
    momentum-mode fix, one crystal further along.
    """
    d = 3.355
    for mtt, att in ((41.19, -41.19), (50.0, -41.19), (41.19, -50.0),
                     (55.0, -60.0)):
        meta = _angle_snapshot("Kf Fixed", source_type, mtt, att,
                               deltaE_field=0.0).metadata
        ki = angle2k(abs(mtt) / 2, d)
        kf = angle2k(abs(att) / 2, d)
        assert meta["Ei"] == pytest.approx(k2energy(ki), rel=1e-9)
        assert meta["Ef"] == pytest.approx(k2energy(kf), rel=1e-9)
        assert meta["Ki"] == pytest.approx(ki, rel=1e-9)
        assert meta["Kf"] == pytest.approx(kf, rel=1e-9)
        assert meta["deltaE"] == pytest.approx(meta["Ei"] - meta["Ef"], rel=1e-9)


def test_angle_mode_an_analyser_scan_moves_ef():
    """The specific case that was wrong: Kf-fixed, scanning A4."""
    transfers, finals = [], []
    for att in (-41.19, -50.0, -60.0):
        meta = _angle_snapshot("Kf Fixed", "Maxwellian", 41.19, att,
                               deltaE_field=0.0).metadata
        transfers.append(meta["deltaE"])
        finals.append(meta["Ef"])

    assert len(set(finals)) == 3, "Ef must track the analyser angle"
    assert len(set(transfers)) == 3
    assert finals[0] != pytest.approx(_FIXED_E, rel=1e-6) or finals[1] != finals[0]


def test_angle_mode_a_monochromator_scan_moves_ei():
    incidents = []
    for mtt in (41.19, 50.0, 60.0):
        meta = _angle_snapshot("Ki Fixed", "Maxwellian", mtt, -41.19,
                               deltaE_field=0.0).metadata
        incidents.append(meta["Ei"])
    assert len(set(incidents)) == 3, "Ei must track the monochromator angle"


def test_angle_mode_falls_back_when_the_angle_is_degenerate():
    """A1 = 0 has no Bragg inverse; the frozen field is used rather than a crash."""
    meta = _angle_snapshot("Kf Fixed", "Maxwellian", 0.0, -41.19,
                           deltaE_field=1.5).metadata
    assert meta["deltaE"] == 1.5


@pytest.mark.parametrize("k_fixed,deltaE", [
    ("Ki Fixed", _FIXED_E),          # Ef exactly zero
    ("Ki Fixed", _FIXED_E + 3.0),    # Ef negative
    ("Kf Fixed", -_FIXED_E),         # Ei exactly zero
    ("Kf Fixed", -_FIXED_E - 3.0),   # Ei negative
])
def test_a_transfer_that_leaves_no_neutron_is_rejected(k_fixed, deltaE):
    """A non-positive nominal energy must be an error, not a NaN angle.

    ``energy2k`` is ``np.sqrt``, so a negative energy returns NaN rather than
    raising. ``k2angle`` propagates it, ``math.isinf`` does not catch it, and
    every axis-limit comparison against NaN is False -- so the point used to
    pass feasibility and the scan ran with NaN motor angles.
    """
    snap = _snapshot(k_fixed, "Maxwellian", deltaE)
    assert "energy" in snap.error_flags
    assert snap.params is None
    assert all(math.isfinite(snap.metadata[k]) for k in ("mtt", "att"))


def test_a_positive_final_energy_never_trips_the_guard():
    """The rejection must fire on the sign only, not on hard-to-reach points.

    A transfer leaving Ef = 0.01 meV is still infeasible -- the analyser cannot
    reach that Bragg condition and the triangle does not close -- but it must
    fail for those reasons, not be swallowed by the energy guard.
    """
    snap = _snapshot("Ki Fixed", "Maxwellian", _FIXED_E - 0.01)
    assert "energy" not in snap.error_flags
    assert not _snapshot("Ki Fixed", "Maxwellian", 5.0).error_flags


def test_feasibility_agrees_with_the_snapshot_on_a_dead_transfer():
    """check_point_feasibility reuses the same solve, so it must reject it too."""
    from instruments.tas_runtime import check_point_feasibility

    plugin = IN8Plugin()
    vals = {
        "K_fixed": "Ki Fixed", "source_type": "Maxwellian", "source_dE": 2,
        "rhm": 3.0, "rvm": 1.2, "rha": 1.5, "rva": 0.31, "fixed_E": _FIXED_E,
        "monocris": "pg002", "anacris": "pg002", "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "0", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"sbl": (40.0, 100.0), "dbl_hgap": 40.0},
    }
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
    scans = list(_SCAN_POINT[0])
    scans[3] = _FIXED_E + 3.0
    feasible, reason = check_point_feasibility(
        config, "momentum", scans, vals,
        axis_limits=plugin.descriptor().axis_limits,
    )
    assert feasible is False
    assert "no neutron" in reason


def test_angle_mode_mono_source_follows_the_monochromator():
    """E0 for a Mono source is the energy A1 selects, not fixed_E + deltaE.

    That arithmetic is only equal to Ei while the other crystal is held at
    fixed_E. In angle mode neither is, so an A4 scan would have walked the
    source band away from the energy the monochromator was still selecting,
    starving the beam while every angle stayed valid.
    """
    d = 3.355
    for att in (-41.19, -50.0, -60.0):
        snap = _angle_snapshot("Kf Fixed", "Mono", 41.19, att, deltaE_field=0.0)
        meta = snap.metadata
        ei = k2energy(angle2k(41.19 / 2, d))
        assert meta["Ei"] == pytest.approx(ei, rel=1e-9)
        assert meta["E0_param"] == pytest.approx(ei, rel=1e-9)
        # The transfer moves with A4 while E0 stays on the monochromator.
        assert meta["Ef"] == pytest.approx(k2energy(angle2k(abs(att) / 2, d)),
                                           rel=1e-9)


def test_momentum_mode_mono_source_is_unchanged():
    """The override must not touch the modes that were already right."""
    assert _snapshot("Kf Fixed", "Mono", 2.0).metadata["E0_param"] == _FIXED_E + 2.0
    assert _snapshot("Ki Fixed", "Mono", 2.0).metadata["E0_param"] == _FIXED_E
    assert _snapshot("Kf Fixed", "Maxwellian", 2.0).metadata["E0_param"] == _FIXED_E
