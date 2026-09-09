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
        "rhm": 3.0, "rvm": 1.2, "rha": 1.5,
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
