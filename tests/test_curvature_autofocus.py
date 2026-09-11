"""Packet slice 3b: curvature follows the measurement.

Curvature used to be computed once, at launch, from whatever geometry the
launch state happened to hold, then frozen for the whole scan while the
take-off angles moved point by point. This module pins the fix: a per-axis
curvature mode (AUTOFOCUS / HELD / SCANNED, ``instruments.contract.
CurvatureMode``) travels in launch state, and ``compute_scan_snapshot``
honours it inside the per-point loop, after the point's own angles are
solved and before ``set_crystal_bending``.

Deliberately spells the modes as the plain strings ``"autofocus"``/``"held"``/
``"scanned"`` rather than importing the enum: ``CurvatureMode`` does not exist
before this slice, and a module-level import failure would collect-error the
whole file instead of failing each test on its own numeric assertion -- the
red-first evidence the operator asked to see. ``CurvatureMode`` subclasses
``str``, so a plain string compares equal to it either way; the round-trip
through ``compute_scan_snapshot``'s ``vals['curvature_modes']`` accepts either.

``test_curvature_producer.py`` pins the producer (``ideal_curvature``) in
isolation; ``test_emitted_curvature.py`` pins the GUI/API wiring around it.
This module pins the NEW per-point policy layer between them.
"""
import pytest

pytest.importorskip("mcstasscript")

from instruments.in8.plugin import IN8Plugin
from instruments.puma.model import PUMA_Instrument
from instruments.tas_runtime import compute_scan_snapshot

AUTOFOCUS, HELD, SCANNED = "autofocus", "held", "scanned"


def _puma_state():
    state = PUMA_Instrument()
    state.monocris = state.anacris = "pg002"
    return state


def _autofocus_vals(**overrides):
    modes = {"rhm": AUTOFOCUS, "rvm": AUTOFOCUS, "rha": AUTOFOCUS, "rva": AUTOFOCUS}
    modes.update(overrides.pop("curvature_modes", {}))
    vals = {"deltaE": 0.0, "chi": 0.0, "curvature_modes": modes}
    vals.update(overrides)
    return vals


def test_fixed_kf_energy_scan_tracks_the_mono_and_leaves_the_analyser(tmp_path):
    """THE DEFECT, pinned directly: at fixed kf, ki (and the mono take-off)
    sweeps with deltaE while kf (and the analyser take-off) does not. With
    every axis AUTOFOCUS, rhm must differ point to point across a deltaE
    scan; rha (a pure function of the constant analyser two-theta) must not.

    Before the fix this fails: curvature was computed once from the launch
    state's frozen A1/A4 and never touched again, so rhm was identical at
    every point (the assertion below rejects a single distinct value).
    """
    state = _puma_state()
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 14.7
    vals = _autofocus_vals()

    rhm_values = []
    rha_values = []
    for deltaE in (-3.0, 0.0, 3.0):
        scans = [3.0, 0.0, 0.0, deltaE, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        snapshot = compute_scan_snapshot(
            (scans, 0), 0, "momentum", state, vals, str(tmp_path),
        )
        assert snapshot.error_flags == [], snapshot.error_flags
        rhm_values.append(snapshot.metadata["rhm"])
        rha_values.append(snapshot.metadata["rha"])

    assert len({round(v, 6) for v in rhm_values}) == 3, (
        f"rhm must track this point's own mono take-off angle (ki sweeps "
        f"with deltaE at fixed kf); got {rhm_values}"
    )
    assert len({round(v, 6) for v in rha_values}) == 1, (
        f"rha must not move: kf is fixed, so the analyser take-off is "
        f"constant across the scan; got {rha_values}"
    )


def test_angle_convention_halves_two_theta_exactly_once(tmp_path):
    """A1/A4 are two-theta; ideal_curvature takes theta. The autofocus call
    site must halve exactly once: comparing against ideal_curvature called
    directly with the SAME halved angles is the ground truth."""
    state = _puma_state()
    vals = _autofocus_vals()
    A1, A4 = 41.167, 50.0  # two-theta values, deliberately different from A1

    scans = [A1, 0.0, 0.0, A4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    snapshot = compute_scan_snapshot(
        (scans, 0), 0, "angle", state, vals, str(tmp_path),
    )
    assert snapshot.error_flags == []

    expected = state.ideal_curvature("pg002", "pg002", A1 / 2, A4 / 2)
    for axis in ("rhm", "rvm", "rha", "rva"):
        assert snapshot.metadata[axis] == pytest.approx(expected[axis]), axis


def test_held_axis_does_not_move_across_the_scan(tmp_path):
    """A HELD axis keeps its declared magnitude across a scan even while the
    analyser take-off angle -- and therefore the ideal -- moves a lot."""
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.rha = 1.0  # declared magnitude, within IN8's undeclared (open) travel

    vals = {
        "deltaE": 0.0, "chi": 0.0,
        "curvature_modes": {"rha": HELD},
    }

    magnitudes = []
    for A4 in (30.0, 60.0):  # same sign, very different ideal rha
        scans = [41.18, 0.0, 0.0, A4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        snapshot = compute_scan_snapshot(
            (scans, 0), 0, "angle", state, vals, str(tmp_path),
        )
        assert snapshot.error_flags == []
        magnitudes.append(abs(snapshot.metadata["rha"]))
        assert snapshot.metadata["curvature_modes"]["rha"] == "held"

    assert magnitudes == pytest.approx([1.0, 1.0])


def test_scanned_axis_follows_its_command(tmp_path):
    """A curvature axis named by the scan command is SCANNED: the point's
    bare scan value (as signed by set_crystal_bending) is what is applied,
    regardless of any mode recorded in launch state -- the scan command is
    the authority for the axis it names."""
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    vals = {
        "deltaE": 0.0, "chi": 0.0,
        # Deliberately AUTOFOCUS: SCANNED must win anyway for this axis.
        "curvature_modes": {"rha": AUTOFOCUS},
    }

    for rha_command, expected_magnitude in ((1.0, 1.0), (2.5, 2.5)):
        scans = [41.18, 0.0, 0.0, -41.18, 0.0, 0.0, rha_command, 0.0,
                 0.0, 0.0, 0.0]
        snapshot = plugin.compute_snapshot(
            (scans, 0), 0, "angle", state, vals, str(tmp_path),
            variable_name1="rha",
        )
        assert snapshot.error_flags == []
        assert snapshot.metadata["curvature_modes"]["rha"] == "scanned"
        assert abs(snapshot.metadata["rha"]) == pytest.approx(expected_magnitude)


def test_fixed_axis_ignores_mode_and_stays_at_its_declared_radius(tmp_path):
    """PUMA's rva is fixed at 0.8 m. AUTOFOCUS (and even naming it as a scan
    variable) must not move it -- FIXED is a property of the assembly, not a
    mode, and the operator has no say over it."""
    state = _puma_state()
    vals = _autofocus_vals()

    for A1, A4 in ((41.167, 41.167), (30.0, 50.0)):
        scans = [A1, 0.0, 0.0, A4, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0]
        snapshot = compute_scan_snapshot(
            (scans, 0), 0, "angle", state, vals, str(tmp_path),
            variable_name1="rva",  # even commanded as a bare 3.0, it must not stick
        )
        assert snapshot.error_flags == []
        assert abs(snapshot.metadata["rva"]) == pytest.approx(0.8)


def test_error_flagged_point_does_not_autofocus_off_stale_angles(tmp_path):
    """A point whose geometry did not solve must leave AUTOFOCUS axes alone
    rather than recompute off whatever stale/zero angle is lying around --
    the same degenerate-angle guard ``set_crystal_bending`` already applies
    to a supplied value."""
    state = _puma_state()
    state.rhm, state.rvm, state.rha, state.rva = 5.0, 5.0, 5.0, 5.0
    vals = _autofocus_vals()

    # Zero momentum transfer -> calculate_angles refuses with "zero_q" before
    # any angle is solved.
    scans = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    snapshot = compute_scan_snapshot(
        (scans, 0), 0, "momentum", state, vals, str(tmp_path),
    )
    assert snapshot.error_flags == ["zero_q"]
    # Held at the launch-state value, not recomputed off a zero/stale angle.
    assert snapshot.metadata["rhm"] == pytest.approx(5.0)
    assert snapshot.metadata["rha"] == pytest.approx(5.0)


def test_metadata_records_mode_and_a_clamped_autofocus_radius_is_flagged(tmp_path):
    """Per-axis mode and applied radius are recorded on every point; when a
    mechanical limit clips an AUTOFOCUS radius, ``curvature_clamped`` names
    the axis so a headless campaign client can tell focused from clamped
    without a log line a human might never see. ath=30 clamps PUMA's rha
    ideal (~1.615 m) up to its declared 2.0 m minimum -- the exact scenario
    ``test_puma_analyser_horizontal_clamps_at_the_provisional_minimum`` pins
    at the producer level."""
    state = _puma_state()
    vals = _autofocus_vals()

    scans = [41.167, 0.0, 0.0, 60.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    snapshot = compute_scan_snapshot(
        (scans, 0), 0, "angle", state, vals, str(tmp_path),
    )
    assert snapshot.error_flags == []

    assert snapshot.metadata["curvature_modes"] == {
        "rhm": "autofocus", "rvm": "autofocus",
        "rha": "autofocus", "rva": "autofocus",
    }
    assert snapshot.metadata["curvature_clamped"] == ["rha"]
    assert abs(snapshot.metadata["rha"]) == pytest.approx(2.0)

    # The ordinary case (nothing clamped) reports an empty list, not the
    # absence of a key -- a client should never need to guess.
    snapshot_ok = compute_scan_snapshot(
        (scans[:3] + [41.167] + scans[4:], 0), 0, "angle", state, vals,
        str(tmp_path),
    )
    assert snapshot_ok.error_flags == []
    assert snapshot_ok.metadata["curvature_clamped"] == []


def test_autofocus_does_not_bend_a_flat_nmo_monochromator(tmp_path):
    """An NMO does the monochromator's focusing itself, so PUMA's mono must
    stay flat at EVERY point of a scan -- not just at launch.

    This is the one interaction per-point autofocus could have broken and
    nothing else covers: the flat override lives in
    ``PUMA_Instrument.optical_radii``, which reads ``self.NMO_installed`` off
    the state. It is correct here only because ``PUMAPlugin.scan_config``
    propagates that flag onto the state the per-point loop deep-copies. If
    that propagation were ever dropped, autofocus would silently bend a
    deliberately flat monochromator once per point, which is the same class
    of regression as the clamp that used to pull the flat override back up
    to PUMA's 2.0 m minimum -- twice now on different paths.

    The analyser is untouched by the NMO and must still track.
    """
    state = _puma_state()
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 14.7
    state.NMO_installed = "Both"
    vals = _autofocus_vals()

    mono_values = []
    for deltaE in (-3.0, 0.0, 3.0):
        scans = [3.0, 0.0, 0.0, deltaE, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        snapshot = compute_scan_snapshot(
            (scans, 0), 0, "momentum", state, vals, str(tmp_path),
        )
        assert snapshot.error_flags == [], snapshot.error_flags
        mono_values.append((snapshot.metadata["rhm"], snapshot.metadata["rvm"]))
        assert snapshot.metadata["rha"] != 0.0, (
            "the NMO focuses the monochromator, not the analyser"
        )

    assert all(rhm == 0.0 and rvm == 0.0 for rhm, rvm in mono_values), (
        f"an NMO-fitted monochromator must stay flat at every point; "
        f"got {mono_values}"
    )
