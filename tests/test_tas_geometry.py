import math
from pathlib import Path

import numpy as np

from tavi.sample_mount import SampleMount
from tavi.tas_geometry import (
    component_q_to_instrument_q,
    instrument_q_to_component_q,
    mccode_euler_from_matrix,
    mccode_rotation_matrix,
    q_instrument_from_angles,
    solve_sample_angles,
    solve_instrument_angles,
    q_sample_from_angles,
)
from tavi.ub_matrix import ObservedPeak, UBMatrix, calculate_U_two_peaks, compute_B_matrix


N_MASS = 1.67492749804e-27
E_CHARGE = 1.602176634e-19
HBAR = 1.05459e-34


def energy2k(energy):
    return math.sqrt(energy * 1e-3 * E_CHARGE * 2 * N_MASS) * 1e-10 / HBAR


def assert_vec_close(actual, expected, tol=1e-8):
    assert np.allclose(actual, expected, atol=tol), f"{actual} != {expected}"


def test_elastic_geometry_reduces_to_half_angle():
    ki = kf = energy2k(14.7)
    q = np.array([2.0 * 2.0 * math.pi / 4.039, 0.0, 0.0])

    angles = solve_sample_angles(q, ki, kf)

    assert math.isclose(angles.sth, angles.stt / 2.0, abs_tol=1e-10)
    assert math.isclose(angles.saz, 0.0, abs_tol=1e-10)


def test_inelastic_al_h_scan_corrected_sth_values():
    ki = energy2k(16.7)
    kf = energy2k(14.7)
    qscale = 2.0 * math.pi / 4.039

    h17 = solve_sample_angles(np.array([1.7 * qscale, 0.0, 0.0]), ki, kf)
    h23 = solve_sample_angles(np.array([2.3 * qscale, 0.0, 0.0]), ki, kf)

    assert math.isclose(h17.sth, -32.0096, abs_tol=5e-4)
    assert math.isclose(h23.sth, -42.6631, abs_tol=5e-4)


def test_instrument_q_legacy_h_scan_corrected_sth_values():
    ki = energy2k(16.7)
    kf = energy2k(14.7)
    qscale = 2.0 * math.pi / 4.039

    h17 = solve_instrument_angles(np.array([1.7 * qscale, 0.0, 0.0]), ki, kf)
    h23 = solve_instrument_angles(np.array([2.3 * qscale, 0.0, 0.0]), ki, kf)

    assert math.isclose(h17.sth, -32.0096, abs_tol=5e-4)
    assert math.isclose(h23.sth, -42.6631, abs_tol=5e-4)


def test_angle_roundtrip_across_quadrants_and_vertical_component():
    ki = energy2k(30.0)
    kf = energy2k(25.0)
    targets = [
        np.array([1.2, 0.0, 0.7]),
        np.array([-1.1, 0.0, 0.4]),
        np.array([0.9, 0.25, 0.6]),
        np.array([0.9, -0.25, -0.6]),
    ]

    for q in targets:
        angles = solve_sample_angles(q, ki, kf)
        roundtrip = q_sample_from_angles(angles.sth, angles.saz, angles.stt, ki, kf)
        assert_vec_close(roundtrip, q)


def test_instrument_angle_roundtrip_preserves_legacy_q_convention():
    ki = energy2k(30.0)
    kf = energy2k(25.0)
    targets = [
        np.array([1.2, 0.7, 0.0]),
        np.array([-1.1, 0.4, 0.0]),
        np.array([0.9, 0.6, 0.25]),
        np.array([0.9, -0.6, -0.25]),
    ]

    for q in targets:
        angles = solve_instrument_angles(q, ki, kf)
        roundtrip = q_instrument_from_angles(angles.sth, angles.saz, angles.stt, ki, kf)
        assert_vec_close(roundtrip, q)


def test_default_tas_mount_maps_hk0_to_horizontal_plane():
    mount = SampleMount.from_lattice_tas(4.0, 4.0, 4.0, 90, 90, 90)

    assert_vec_close(mount.hkl_to_q(1, 0, 0), (math.pi / 2, 0.0, 0.0))
    assert_vec_close(mount.hkl_to_q(0, 1, 0), (0.0, 0.0, math.pi / 2))
    assert_vec_close(mount.hkl_to_q(0, 0, 1), (0.0, math.pi / 2, 0.0))


def test_default_tas_mount_converts_hk0_to_instrument_horizontal_q():
    mount = SampleMount.from_lattice_tas(4.0, 4.0, 4.0, 90, 90, 90)

    q_component = mount.hkl_to_q(1, 2, 0)
    q_instrument = component_q_to_instrument_q(q_component)

    assert_vec_close(q_instrument, (math.pi / 2, math.pi, 0.0))
    assert_vec_close(instrument_q_to_component_q(q_instrument), q_component)


def test_custom_mount_can_put_h0l_plane_horizontal():
    mount = SampleMount.from_lattice_tas(
        4.0, 4.0, 4.0, 90, 90, 90,
        R_mount=mccode_rotation_matrix(-90, 0, 0),
    )

    h_axis = np.array(mount.hkl_to_q(1, 0, 0))
    l_axis = np.array(mount.hkl_to_q(0, 0, 1))

    assert abs(h_axis[1]) < 1e-8
    assert abs(l_axis[1]) < 1e-8


def test_mount_rotation_roundtrips_to_mccode_euler_angles():
    rotation = mccode_rotation_matrix(-30, 10, 20)
    rx, ry, rz = mccode_euler_from_matrix(rotation)

    assert_vec_close(mccode_rotation_matrix(rx, ry, rz), rotation)


def test_ub_from_observed_peaks_recovers_mount_matrix():
    ki = kf = energy2k(30.0)
    B = compute_B_matrix(4.0, 4.0, 4.0, 90, 90, 90)
    U_expected = mccode_rotation_matrix(-30, 10, 0)
    peaks = []

    for hkl in [(1, 0, 0), (0, 1, 0)]:
        q_sample = U_expected @ B @ np.array(hkl, dtype=float)
        q_instrument = component_q_to_instrument_q(q_sample)
        angles = solve_instrument_angles(q_instrument, ki, kf)
        peaks.append(ObservedPeak(hkl=hkl, angles=(angles.sth, angles.saz, angles.stt), ki=ki, kf=kf))

    U_actual = calculate_U_two_peaks(peaks[0], peaks[1], B)

    assert_vec_close(U_actual, U_expected)


def test_manual_ub_rejects_non_rotation_mount():
    ub = UBMatrix()
    bad_ub = ub.B.copy()
    bad_ub[0, 0] *= 1.2

    try:
        ub.set_UB(bad_ub)
    except ValueError as exc:
        assert "orthogonal" in str(exc) or "proper rotation" in str(exc)
    else:
        raise AssertionError("Non-orthogonal UB edit should be rejected")


def test_phonon_dft_reciprocal_basis_uses_oriented_volume():
    source = Path(__file__).resolve().parents[1] / "components" / "Phonon_DFT.comp"
    text = source.read_text(encoding="utf-8")

    assert "oriented_V0 = scalar_prod" in text
    assert "2*PI/oriented_V0" in text
    assert "2*PI/lat->V0 * tmp" not in text


def test_centered_phonon_grid_keeps_h2_inside_interpolation_cell():
    grid = Path(__file__).resolve().parents[1] / "components" / "Al_test_phonons_centered.dat"
    rows = []
    for line in grid.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            h, k, l, e, intensity, branch = line.split()[:6]
            if float(k) == 0 and float(l) == 0 and int(branch) == 0:
                rows.append((float(h), float(e)))

    h_values = [h for h, _ in rows]
    assert min(h_values) == -1.0
    assert max(h_values) == 1.0

    energies = dict(rows)
    assert math.isclose(energies[0.0], 0.0, abs_tol=1e-12)
    assert math.isclose(energies[-0.3], energies[0.3], abs_tol=1e-12)


def test_phonon_dft_lorentzian_sampler_uses_root_based_targets():
    source = Path(__file__).resolve().parents[1] / "components" / "Phonon_DFT.comp"
    text = source.read_text(encoding="utf-8")

    assert "Build importance-sampling targets for each real phonon root" in text
    assert "ph_root_vf = pdft_zridd" in text
    assert "Estimate Q at elastic limit" not in text
