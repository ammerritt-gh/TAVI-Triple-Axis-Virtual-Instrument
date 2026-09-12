"""A zero take-off angle is the direct-beam position, not an error.

Audit `docs/audits/new-instruments-crystal-bending.md` entry 2 (now deleted)
found that an accepted A4 scan crossing zero raised ``ZeroDivisionError``
during autofocus. The operator ruled: a zero take-off is not refused -- it is
the direct-beam position (the crystal is pointing the wrong way, nothing is
reflected) -- so the instrument runs it and returns FLAT. These tests pin
that ruling at both layers it is enforced: the shared policy in
``ideal_curvature`` (authoritative, even against a misbehaving
``optical_radii`` override) and the default formula in ``optical_radii``
itself (so the shipped formula stays total, never dividing by zero on its
own). They also pin the applier, ``set_crystal_bending``, which must now
STORE a zero-take-off magnitude rather than leave a stale radius in place.

Follows the conventions of ``test_curvature_producer.py`` (direct producer
calls, pinned reference table) and ``test_curvature_autofocus.py``
(``compute_scan_snapshot``/``compute_snapshot`` through the plugin surface).
No real offscreen Qt is needed -- this is shared runtime physics.
"""
import math

import pytest

pytest.importorskip("mcstasscript")

from instruments.in8.model import IN8_Instrument
from instruments.in12.model import IN12_Instrument
from instruments.panda.model import PANDA_Instrument
from instruments.panda.plugin import PANDAPlugin
from instruments.puma.model import PUMA_Instrument

INSTRUMENT_CLASSES = [PUMA_Instrument, IN8_Instrument, IN12_Instrument, PANDA_Instrument]


# --- optical_radii: the default formula stays total ------------------------

@pytest.mark.parametrize("cls", INSTRUMENT_CLASSES, ids=[c.__name__ for c in INSTRUMENT_CLASSES])
def test_optical_radii_returns_flat_for_the_crystal_at_zero_takeoff(cls):
    """Zero mono take-off flattens both mono axes and leaves the analyser
    axes exactly as an ordinary nonzero-theta call would; zero analyser
    take-off is the mirror image. Neither branch divides by zero."""
    state = cls()

    radii_zero_mth = state.optical_radii(0.0, 20.0)
    assert radii_zero_mth["mono_h"] == 0.0
    assert radii_zero_mth["mono_v"] == 0.0
    ana_only = state.optical_radii(41.0, 20.0)  # mth irrelevant to ana_h/ana_v
    assert radii_zero_mth["ana_h"] == pytest.approx(ana_only["ana_h"])
    assert radii_zero_mth["ana_v"] == pytest.approx(ana_only["ana_v"])
    assert radii_zero_mth["ana_h"] != 0.0
    assert radii_zero_mth["ana_v"] != 0.0

    radii_zero_ath = state.optical_radii(20.0, 0.0)
    assert radii_zero_ath["ana_h"] == 0.0
    assert radii_zero_ath["ana_v"] == 0.0
    mono_only = state.optical_radii(20.0, 41.0)  # ath irrelevant to mono_h/mono_v
    assert radii_zero_ath["mono_h"] == pytest.approx(mono_only["mono_h"])
    assert radii_zero_ath["mono_v"] == pytest.approx(mono_only["mono_v"])
    assert radii_zero_ath["mono_h"] != 0.0
    assert radii_zero_ath["mono_v"] != 0.0


# --- ideal_curvature: the shared policy is authoritative --------------------

def test_ideal_curvature_flattens_a_driven_axis_at_zero_takeoff_even_if_optical_radii_lies(monkeypatch):
    """Pins the rule to the SHARED POLICY layer, not the overridable formula:
    even when ``optical_radii`` is monkeypatched to hand back a nonzero
    magnitude for every axis, a requested driven axis at zero take-off must
    still come back flat. IN8 (every axis driven, no declared clamp) keeps
    this test isolated from mechanical-minimum clamping, which is a separate
    rule pinned elsewhere."""
    state = IN8_Instrument()
    monkeypatch.setattr(
        state, "optical_radii",
        lambda mth, ath, modules=None: {
            "mono_h": 9.0, "mono_v": 9.0, "ana_h": 9.0, "ana_v": 9.0,
        },
    )

    radii = state.ideal_curvature("pg002", "pg002", 20.0, 0.0, requested_axes=("rha", "rva"))
    assert radii["rha"] == 0.0
    assert radii["rva"] == 0.0

    radii_mono = state.ideal_curvature("pg002", "pg002", 0.0, 20.0, requested_axes=("rhm", "rvm"))
    assert radii_mono["rhm"] == 0.0
    assert radii_mono["rvm"] == 0.0


# --- set_crystal_bending: the applier stores, never inherits ---------------

def test_applier_stores_a_positive_magnitude_at_zero_takeoff_instead_of_the_stale_radius():
    """An axis commanded again at zero take-off must reflect what was JUST
    commanded, not whatever the previous (nonzero take-off) point left
    behind -- and the stored value must carry the operator's magnitude with
    a positive sign, since there is no branch to sign it onto. IN8's rha has
    no declared mechanical clamp, so the commanded magnitude below is stored
    exactly rather than adjusted by an unrelated rule."""
    state = IN8_Instrument()
    state.monocris = state.anacris = "pg002"

    state.set_angles(A1=41.167, A2=0.0, A3=0.0, A4=41.167)
    state.set_crystal_bending(rha=9.999)
    previous = state.rha
    assert math.isfinite(previous) and previous != 0.0

    state.set_angles(A1=41.167, A2=0.0, A3=0.0, A4=0.0)  # ana take-off now zero
    state.set_crystal_bending(rha=1.234)
    assert state.rha == pytest.approx(1.234), (
        "a zero-take-off point must store the newly commanded magnitude, "
        f"not the previous point's stored radius ({previous})"
    )
    assert state.rha > 0.0, "no branch to sign onto: the magnitude is stored positive"


def test_applier_flattens_an_autofocus_magnitude_of_zero_at_zero_takeoff():
    """The other half of the same guard: an AUTOFOCUS axis arrives at
    ``set_crystal_bending`` already carrying magnitude 0.0 (from
    ``ideal_curvature``'s flat answer) and must be stored flat, not left at
    whatever radius predates it."""
    state = PUMA_Instrument()
    state.monocris = state.anacris = "pg002"

    state.set_angles(A1=41.167, A2=0.0, A3=0.0, A4=41.167)
    state.set_crystal_bending(rha=9.999)
    assert state.rha != 0.0

    state.set_angles(A1=41.167, A2=0.0, A3=0.0, A4=0.0)
    state.set_crystal_bending(rha=0.0)
    assert state.rha == 0.0


# --- end to end: an accepted scan crossing zero take-off ------------------

def _panda_autofocus_snapshot(att, tmp_path):
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    vals = {
        "deltaE": 0.0, "chi": 0.0,
        "curvature_modes": {axis: "autofocus" for axis in ("rhm", "rvm", "rha", "rva")},
    }
    scans = [-74.332, 30.0, 0.0, att, 0, 0, 0, 0, 0, 0, 0]
    feasible, reason = plugin.check_point_feasibility(state, "angle", scans, vals)
    assert feasible, f"A4={att} was refused: {reason}"
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state, vals, str(tmp_path), variable_name1="A4",
    )
    return snapshot


def test_a4_zero_is_feasible_and_the_snapshot_succeeds_flat(tmp_path):
    """The ruled acceptance, replacing the audit reproducer's assumed
    refusal: A4 = 0 is feasible and the snapshot succeeds with no error
    flags -- the driven singular (analyser horizontal) crystal goes flat,
    the mono does not. PANDA's rva is a FIXED axis (declared radius,
    ignores mode and angle entirely, per
    ``test_fixed_axis_ignores_mode_and_stays_at_its_declared_radius``), so it
    is deliberately not asserted flat here -- only rha is driven and
    actually reaches the zero-take-off rule."""
    snapshot = _panda_autofocus_snapshot(0.0, tmp_path)
    assert snapshot.error_flags == []
    assert snapshot.params["rha_param"] == 0.0
    assert snapshot.params["rhm_param"] != 0.0
    assert snapshot.params["rvm_param"] != 0.0


def test_a4_scan_crossing_zero_keeps_the_opposite_branch_signs(tmp_path):
    """The +/-1 degree neighbours of a scan crossing zero keep their ordinary
    signed autofocus radii, on opposite branches, end to end through the
    snapshot -- the zero take-off fix must not disturb them."""
    minus = _panda_autofocus_snapshot(-1.0, tmp_path)
    zero = _panda_autofocus_snapshot(0.0, tmp_path)
    plus = _panda_autofocus_snapshot(1.0, tmp_path)

    assert minus.error_flags == [] and plus.error_flags == []
    rha_minus = minus.params["rha_param"]
    rha_plus = plus.params["rha_param"]
    assert rha_minus != 0.0 and rha_plus != 0.0
    assert math.copysign(1.0, rha_minus) != math.copysign(1.0, rha_plus), (
        f"opposite-branch neighbours must keep opposite signs; got {rha_minus}, {rha_plus}"
    )
    assert zero.params["rha_param"] == 0.0

    # The mono, unaffected by A4, must not move across the scan.
    assert minus.params["rhm_param"] == pytest.approx(zero.params["rhm_param"])
    assert zero.params["rhm_param"] == pytest.approx(plus.params["rhm_param"])


def test_a4_zero_held_radius_is_stored_at_its_commanded_magnitude(tmp_path):
    """A HELD (explicitly commanded) radius at A4 = 0 is stored at its
    commanded magnitude -- not flattened like the AUTOFOCUS axes, because the
    operator asked for that bend."""
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.rha = 1.234  # explicitly commanded magnitude
    vals = {
        "deltaE": 0.0, "chi": 0.0,
        "curvature_modes": {
            "rhm": "autofocus", "rvm": "autofocus", "rha": "held", "rva": "autofocus",
        },
    }
    scans = [-74.332, 30.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0]
    feasible, reason = plugin.check_point_feasibility(state, "angle", scans, vals)
    assert feasible, reason

    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state, vals, str(tmp_path), variable_name1="A4",
    )
    assert snapshot.error_flags == []
    assert abs(snapshot.params["rha_param"]) == pytest.approx(1.234)
    assert snapshot.metadata["curvature_modes"]["rha"] == "held"
