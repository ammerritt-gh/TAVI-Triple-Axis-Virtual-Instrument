"""Cross-instrument tests for the ideal-curvature producer (packet slice2).

``TAS_Instrument.ideal_curvature`` (and the ``optical_radii`` /
``curvature_object_distances`` / ``curvature_limits`` seams under it) replaces
the deleted per-model ``calculate_crystal_bending``. The pinned literal table
below is the SPECIFICATION handed down with the slice -- derived from each
instrument's declared arm lengths, not from this code -- so a disagreement
here means the implementation is wrong, not the table.
"""
import math

import pytest

pytest.importorskip("mcstasscript")

from instruments.in8.model import IN8_Instrument
from instruments.in12.model import IN12_Instrument
from instruments.panda.model import PANDA_Instrument
from instruments.puma.model import PUMA_Instrument

# instrument-class, mth, ath, expected (rhm, rvm, rha, rva)
REFERENCE_TABLE = [
    (PUMA_Instrument,  20.5835,    20.5835,    (13.0272, 1.6102, 2.3034, 0.8000)),
    (IN8_Instrument,   20.59,     -20.59,      (6.7556,  0.8355, -2.3885, -0.2954)),
    (IN12_Instrument, -27.917234, -27.917234,  (-3.8445, -0.8428, -1.9794, -1.4000)),
    (PANDA_Instrument, -37.166,   -37.166,     (-3.9848, -1.7869, -1.6511, -0.6000)),
]


@pytest.mark.parametrize("cls, mth, ath, expected", REFERENCE_TABLE,
                          ids=[c.__name__ for c, *_ in REFERENCE_TABLE])
def test_ideal_curvature_matches_pinned_reference_table(cls, mth, ath, expected):
    state = cls()
    radii = state.ideal_curvature("pg002", "pg002", mth, ath)
    rhm, rvm, rha, rva = expected
    assert radii["rhm"] == pytest.approx(rhm, abs=5e-5)
    assert radii["rvm"] == pytest.approx(rvm, abs=5e-5)
    assert radii["rha"] == pytest.approx(rha, abs=5e-5)
    assert radii["rva"] == pytest.approx(rva, abs=5e-5)


def test_in12_vertical_mono_clamps_at_the_provisional_minimum():
    """At mth = -10 the ideal RV (-0.3126 m) falls below MONO_MIN_RV (0.5 m)."""
    from instruments.in12.model import MONO_MIN_RV

    state = IN12_Instrument()
    radii = state.ideal_curvature("pg002", "pg002", -10.0, -30.0)
    ideal = -2 * 0.9 * math.sin(math.radians(10.0))
    assert abs(ideal) < MONO_MIN_RV                    # the clamp really engages
    assert radii["rvm"] == pytest.approx(-MONO_MIN_RV)  # clamped, sign preserved


def test_puma_analyser_horizontal_clamps_at_the_provisional_minimum():
    """At ath = +30 the ideal RH (~1.6154 m) falls below PUMA's 2.0 m minimum."""
    state = PUMA_Instrument()
    radii = state.ideal_curvature("pg002", "pg002", 20.5835, 30.0)
    assert radii["rha"] == pytest.approx(2.0)


def test_ideal_curvature_refuses_the_heusler_analyser_rva():
    """IN12's Heusler declares rva focusing_known=False -- no invented radius."""
    from instruments.in12.plugin import in12_descriptor

    heusler_id = next(
        spec.id for spec in in12_descriptor().ana_crystals if spec.id != "pg002"
    )
    state = IN12_Instrument()
    with pytest.raises(ValueError, match="focusing_known"):
        state.ideal_curvature("pg002", heusler_id, -27.917234, -27.917234)


def test_set_crystal_bending_overrides_a_supplied_value_on_a_fixed_axis():
    """PUMA's rva is fixed at 0.8 m; a scanned value must not stick."""
    state = PUMA_Instrument()
    state.monocris = state.anacris = "pg002"
    state.set_angles(A1=41.167, A4=41.167)  # two-theta = 2 * 20.5835

    state.set_crystal_bending(rva=3.0)
    assert state.rva == pytest.approx(0.8)


def test_puma_nmo_installed_forces_a_flat_monochromator():
    """A fitted NMO does the mono's focusing itself: both mono planes must
    come back exactly flat (0), and the clamp (min_radius_m=2.0/0.5 on
    rhm/rvm) must not pull that back up to a mechanical minimum. The
    analyser is untouched -- still the pinned point-source values."""
    state = PUMA_Instrument()
    state.NMO_installed = "Both"
    radii = state.ideal_curvature("pg002", "pg002", 20.5835, 20.5835)
    assert radii["rhm"] == 0.0
    assert radii["rvm"] == 0.0
    assert radii["rha"] == pytest.approx(2.3034, abs=5e-5)
    assert radii["rva"] == pytest.approx(0.8000, abs=5e-5)


def test_puma_no_nmo_still_matches_the_pinned_reference_row():
    """Without an NMO, PUMA's row is unchanged from the general pinned table."""
    state = PUMA_Instrument()
    assert state.NMO_installed == "None"
    radii = state.ideal_curvature("pg002", "pg002", 20.5835, 20.5835)
    assert radii["rhm"] == pytest.approx(13.0272, abs=5e-5)
    assert radii["rvm"] == pytest.approx(1.6102, abs=5e-5)
    assert radii["rha"] == pytest.approx(2.3034, abs=5e-5)
    assert radii["rva"] == pytest.approx(0.8000, abs=5e-5)


def test_puma_nmo_via_modules_dict_overrides_instrument_state():
    """A caller with no state object yet (e.g. a frozen API request) can pass
    ``modules={'nmo': ...}`` instead of mutating NMO_installed; it wins."""
    state = PUMA_Instrument()
    assert state.NMO_installed == "None"
    radii = state.ideal_curvature(
        "pg002", "pg002", 20.5835, 20.5835, modules={"nmo": "Horizontal"},
    )
    assert radii["rhm"] == 0.0
    assert radii["rvm"] == 0.0


def test_optical_radii_seam_supports_a_non_point_source_instrument():
    """A stub instrument overriding optical_radii proves the seam a fifth
    instrument (not a simple (L_in, L_out) pair) would use."""

    class FlatMonoInstrument(PUMA_Instrument):
        """A monochromator with a fixed 4 m radius on both planes -- not
        derivable from any object-distance pair, exercising the ONE seam
        `optical_radii` documents for exactly this case."""

        def optical_radii(self, mth, ath, modules=None):
            radii = super().optical_radii(mth, ath, modules=modules)
            radii["mono_h"] = 4.0
            radii["mono_v"] = 4.0
            return radii

    state = FlatMonoInstrument()
    radii = state.ideal_curvature("pg002", "pg002", 20.5835, 20.5835)
    assert radii["rhm"] == pytest.approx(4.0)
    assert radii["rvm"] == pytest.approx(4.0)
    # The analyser is untouched -- still the base point-source formula.
    assert radii["rha"] == pytest.approx(2.3034, abs=5e-5)


def test_a_commanded_flat_radius_is_not_clamped_up_when_it_is_applied():
    """The flat sentinel must survive the APPLY path, not just the produce path.

    ``ideal_curvature`` skips the clamp for an exact 0, but PUMA-with-an-NMO
    reaches the instrument by a different route: the GUI stores rhm = 0, and
    ``compute_scan_snapshot`` hands that straight to ``set_crystal_bending``
    without going near the producer. If only the producer honoured the
    sentinel, PUMA's declared 2.0 m / 0.5 m monochromator minima would bend a
    deliberately flat monochromator back up -- reintroducing, one path over,
    the exact regression the NMO override exists to prevent.
    """
    state = PUMA_Instrument()
    state.monocris = "pg002"
    state.anacris = "pg002"
    state.set_angles(A1=41.167, A4=41.167)

    state.set_crystal_bending(rhm=0.0, rvm=0.0)
    assert state.rhm == 0.0
    assert state.rvm == 0.0

    # ...while a genuinely out-of-travel nonzero command still clamps.
    state.set_crystal_bending(rhm=0.5)
    assert state.rhm == pytest.approx(2.0)
