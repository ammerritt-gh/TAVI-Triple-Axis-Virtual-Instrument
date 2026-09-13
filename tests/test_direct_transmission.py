"""A zero two-theta records a marked, partial point -- never an invented energy.

``calculate_angles`` inverts each crystal's two-theta to a k independently.
At exactly zero the crystal is transmitting (it selects nothing), and
``angle2k`` returns exactly 0 for that angle. Before this fix,
``nominal_energies_from_angles`` returned ``None`` for the WHOLE pair the
moment either crystal was degenerate, so the caller fell back to inventing
the missing energy from ``fixed_E`` -- see
``docs/audits/repro/new-instruments-crystal-bending/direct_beam_energy.py``.
Now each crystal's slot is ``None`` independently, and the point is marked
via ``metadata['transmission']``: a list, in the fixed order
``("mono", "sample", "ana")``, naming which crystal(s) selected nothing (or
that the solved sample two-theta was exactly 0 -- forward scattering, in any
scan mode). No error flag; McStas parameters are still built.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.in8.plugin import IN8Plugin
from instruments.tas_runtime import compute_scan_snapshot
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy

_FIXED_E = 14.68  # meV, the standard IN8 kf = 2.662 setting
_D_PG002 = 3.355


def _base_vals(k_fixed, source_type, deltaE_field=0.0):
    return {
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


def _angle_snapshot(k_fixed, source_type, mtt, att, deltaE_field=0.0, stt=-71.25):
    """One ``angle``-mode point: the user drives A1..A4 directly.

    Same rig as ``tests/test_point_energy_metadata.py``'s ``_angle_snapshot``.
    """
    plugin = IN8Plugin()
    vals = _base_vals(k_fixed, source_type, deltaE_field)
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
    # A1 A2 A3 A4 | rhm rvm rha rva | chi kappa psi
    scans = [mtt, stt, -35.63, att, 3.0, 1.2, 1.5, 0.31, 0.0, 0.0, 0.0]
    return compute_scan_snapshot((scans, 0), 0, "angle", config, vals,
                                 data_folder=".")


def _momentum_snapshot(k_fixed, source_type, qx, qy, qz, deltaE, fixed_E=_FIXED_E):
    plugin = IN8Plugin()
    vals = _base_vals(k_fixed, source_type)
    vals["fixed_E"] = fixed_E
    state = plugin.default_state()
    config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
    scans = [qx, qy, qz, deltaE, 3.0, 1.2, 1.5, 0.31, 0.0, 0.0, 0.0]
    return compute_scan_snapshot((scans, 0), 0, "momentum", config, vals,
                                 data_folder=".")


def _mtt_for_ei(state, ei):
    """The A1 that selects the given Ei, the same construction the reproducer
    (``direct_beam_energy.py``) uses."""
    mono_info, _ = state.crystal_info(state.monocris, state.anacris)
    return 2 * state.sense_mono * k2angle(energy2k(ei), mono_info['dm'])


def test_att_zero_records_ana_transmission_and_keeps_e0_continuous():
    """The reproducer's construction: a Mono source stays on A1's real Ei
    across a zero-crossing A4 scan instead of jumping to fixed_E."""
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    mtt = _mtt_for_ei(state, 20.0)
    ei_from_a1 = k2energy(angle2k(mtt / (2 * state.sense_mono), _D_PG002))

    results = {}
    for att in (-1.0, 0.0, 1.0):
        snap = _angle_snapshot("Kf Fixed", "Mono", mtt, att, deltaE_field=0.0)
        assert not snap.error_flags
        results[att] = snap.metadata

    zero = results[0.0]
    assert zero["Ei"] == pytest.approx(ei_from_a1, rel=1e-9)
    assert zero["Ki"] == pytest.approx(energy2k(ei_from_a1), rel=1e-9)
    assert zero["Ef"] is None
    assert zero["Kf"] is None
    assert zero["deltaE"] is None
    assert zero["transmission"] == ["ana"]
    assert not _angle_snapshot("Kf Fixed", "Mono", mtt, 0.0).error_flags
    assert _angle_snapshot("Kf Fixed", "Mono", mtt, 0.0).params is not None

    # Continuity: the source tracks A1's Ei across the zero crossing, not a
    # jump to fixed_E and back.
    assert zero["E0_param"] == pytest.approx(results[-1.0]["E0_param"], rel=1e-9)
    assert zero["E0_param"] == pytest.approx(results[1.0]["E0_param"], rel=1e-9)
    assert zero["E0_param"] == pytest.approx(ei_from_a1, rel=1e-9)


def test_mtt_zero_records_mono_transmission():
    """The monochromator transmits; the analyser still selects Ef."""
    att = -41.19  # a real, non-degenerate analyser angle (existing test rig)
    deltaE_field = 1.5
    snap = _angle_snapshot("Kf Fixed", "Mono", 0.0, att, deltaE_field=deltaE_field)
    meta = snap.metadata
    assert not snap.error_flags

    kf = angle2k(abs(att) / 2, _D_PG002)
    assert meta["Ei"] is None
    assert meta["Ki"] is None
    assert meta["Ef"] == pytest.approx(k2energy(kf), rel=1e-9)
    assert meta["Kf"] == pytest.approx(kf, rel=1e-9)
    assert meta["transmission"] == ["mono"]
    assert meta["deltaE"] is None

    # E0_param falls back exactly as it did before this fix touched anything:
    # with the monochromator's slot absent, e0_param_value cannot read Ei off
    # the crystals and uses the existing K_fixed fallback on the frozen
    # deltaE field (fixed_E + deltaE for a Mono source in Kf-fixed mode).
    assert meta["E0_param"] == pytest.approx(_FIXED_E + deltaE_field, rel=1e-9)


def test_both_zero_records_full_transmission():
    snap = _angle_snapshot("Kf Fixed", "Maxwellian", 0.0, 0.0, deltaE_field=1.5)
    meta = snap.metadata
    assert not snap.error_flags
    assert snap.params is not None
    assert meta["Ei"] is None
    assert meta["Ki"] is None
    assert meta["Ef"] is None
    assert meta["Kf"] is None
    assert meta["deltaE"] is None
    assert meta["transmission"] == ["mono", "ana"]


def test_stt_zero_in_angle_mode_marks_forward_scattering():
    """Both crystals reflect; the sample take-off itself is zero."""
    mtt, att = 41.19, -41.19
    snap = _angle_snapshot("Kf Fixed", "Maxwellian", mtt, att,
                           deltaE_field=0.0, stt=0.0)
    meta = snap.metadata
    assert not snap.error_flags

    ki = angle2k(abs(mtt) / 2, _D_PG002)
    kf = angle2k(abs(att) / 2, _D_PG002)
    assert meta["Ei"] == pytest.approx(k2energy(ki), rel=1e-9)
    assert meta["Ef"] == pytest.approx(k2energy(kf), rel=1e-9)
    assert meta["deltaE"] == pytest.approx(meta["Ei"] - meta["Ef"], rel=1e-9)
    assert meta["transmission"] == ["sample"]


def test_qspace_forward_scattering_marks_sample_transmission():
    """|Q| = |ki - kf| exactly: forward scattering in momentum mode."""
    fixed_E = 14.68
    deltaE = 5.0
    Ef = fixed_E
    Ei = Ef + deltaE
    ki = energy2k(Ei)
    kf = energy2k(Ef)
    snap = _momentum_snapshot("Kf Fixed", "Maxwellian", ki - kf, 0.0, 0.0,
                              deltaE, fixed_E=fixed_E)
    assert not snap.error_flags
    assert snap.metadata["transmission"] == ["sample"]


def test_ordinary_point_transmission_is_empty():
    """Preservation check: an ordinary point is untouched by this change."""
    snap = _momentum_snapshot("Kf Fixed", "Maxwellian", 2.0, 0.0, 0.5, 2.0)
    meta = snap.metadata
    assert not snap.error_flags
    assert meta["transmission"] == []
    assert meta["Ef"] == pytest.approx(_FIXED_E, rel=1e-9)
    assert meta["Ei"] == pytest.approx(_FIXED_E + 2.0, rel=1e-9)
    assert meta["Ki"] == pytest.approx(energy2k(_FIXED_E + 2.0), rel=1e-9)
    assert meta["Kf"] == pytest.approx(energy2k(_FIXED_E), rel=1e-9)
    assert meta["deltaE"] == pytest.approx(2.0, rel=1e-9)


def test_flagged_qspace_point_has_empty_transmission():
    """A flagged point (dead transfer) is never marked transmitting.

    Same construction as
    ``tests/test_point_energy_metadata.py::test_feasibility_agrees_with_the_snapshot_on_a_dead_transfer``:
    a Ki-fixed transfer that leaves Ef <= 0 trips the "energy" guard before
    any angle is solved.
    """
    snap = _momentum_snapshot("Ki Fixed", "Maxwellian", 2.0, 0.0, 0.5,
                              _FIXED_E + 3.0)
    assert snap.error_flags
    assert "energy" in snap.error_flags
    assert snap.metadata["transmission"] == []
