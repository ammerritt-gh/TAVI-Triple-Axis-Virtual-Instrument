"""End-to-end gate for packet slice 3a: every path reaches the one producer.

Slice 2 built one producer (``TAS_Instrument.ideal_curvature``) and one
applier (``set_crystal_bending``). Slice 3a deleted the two hard-coded
GUI/API copies of PUMA's formula that used to decide the radii every
instrument actually ran with. These tests exercise the real controller and
plugin surfaces -- not the producer directly (``test_curvature_producer.py``
already pins that) -- so a regression in the GUI/API wiring around it (the
halving, the crystal names, the pass-through) fails here even when the
producer itself is untouched.
"""
import contextlib
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from instruments.in8.plugin import IN8Plugin  # noqa: E402

# instrument id, mth (theta, deg), ath (theta, deg), expected (rhm, rvm, rha, rva)
# -- identical to test_curvature_producer.py's REFERENCE_TABLE. mtt/att (what
# the GUI widgets and the API 'mtt'/'att' fields hold) are TWO-THETA, so the
# controller under test must pass 2*mth / 2*ath through.
REFERENCE_TABLE = [
    ("puma", 20.5835, 20.5835, (13.0272, 1.6102, 2.3034, 0.8000)),
    ("in8", 20.59, -20.59, (6.7556, 0.8355, -2.3885, -0.2954)),
    ("in12", -27.917234, -27.917234, (-3.8445, -0.8428, -1.9794, -1.4000)),
    ("panda", -37.166, -37.166, (-3.9848, -1.7869, -1.6511, -0.6000)),
]


@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    infos = available_instruments()
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=infos,
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("instrument_id, mth, ath, expected", REFERENCE_TABLE,
                          ids=[t[0] for t in REFERENCE_TABLE])
def test_api_default_curvature_halves_two_theta_and_matches_pinned_table(
        instrument_id, mth, ath, expected):
    """_default_parameter_values (widget-free API defaults) must reproduce
    the pinned ideal_curvature table when mtt/att are patched to the
    reference TWO-THETA values. This is the exact halving packet slice3a
    names as the likely mistake: pass mtt/2, att/2, not mtt, att, and not
    mtt/2 twice."""
    with _controller(instrument_id) as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        launch = ctrl.build_api_launch_state({
            "mtt": 2 * mth, "att": 2 * ath,
            "monocris": mono, "anacris": ana,
            "scan_command1": "deltaE 0 1 0.5",
        })
        vals = launch["vals"]
        # MAGNITUDES, not the signed table. `vals` is the operator/API
        # contract -- how tightly the crystal is bent, which is what an
        # operator types and an API client sends. Which side it bends toward
        # is instrument geometry, derived at the physical boundary where the
        # McStas parameters are emitted (that is what the *_param assertions
        # below pin, and they stay signed).
        #
        # This is not bookkeeping: tavi/resolution.py reads these same vals
        # and applies the scattering sense ITSELF -- `monorh = radius_cm(
        # cfg.rhm) * sm`. A signed value here gets signed twice, and the
        # analytic resolution then describes a crystal bent the wrong way,
        # silently, because the emitted McStas geometry is still correct.
        rhm, rvm, rha, rva = (abs(v) for v in expected)
        assert (vals["rhm"], vals["rvm"], vals["rha"], vals["rva"]) == \
            pytest.approx((rhm, rvm, rha, rva), abs=5e-4)


@pytest.mark.parametrize("instrument_id, mth, ath, expected", REFERENCE_TABLE,
                          ids=[t[0] for t in REFERENCE_TABLE])
def test_gui_ideal_bending_halves_two_theta_and_matches_pinned_table(
        instrument_id, mth, ath, expected):
    """_compute_ideal_bending_values (the GUI Ideal-button path) must
    reproduce the same pinned table for the same reference two-theta
    widget values and the descriptor's default crystals."""
    with _controller(instrument_id) as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        ctrl.window.instrument_dock.set_mono_id(mono)
        ctrl.window.instrument_dock.set_ana_id(ana)
        ideal = ctrl._compute_ideal_bending_values(mtt=2 * mth, att=2 * ath)
        assert ideal is not None
        # Magnitudes, for the same reason as the API path above: this value is
        # written straight into a widget the operator reads and edits.
        rhm, rvm, rha, rva = (abs(v) for v in expected)
        assert (ideal["rhm"], ideal["rvm"], ideal["rha"], ideal["rva"]) == \
            pytest.approx((rhm, rvm, rha, rva), abs=5e-4)


def test_panda_api_hkl_request_emits_expected_signed_curvature(tmp_path):
    """POST /scan-shaped request (an H/K/L patch) all the way to the McStas
    *_param values: solved point angles -> AUTOFOCUS (the API default for an
    axis no one pinned) recomputed from THIS point's own solved angles ->
    the SIGNED params set_crystal_bending emits at the angles THIS request
    actually solves to.

    Packet slice3a documented a known limitation here: an H/K/L request never
    retriggered the launch-state recompute, so it focused for PUMA's
    reference-geometry default (mtt=att=41.167) regardless of the sample's
    real Bragg geometry. Slice 3b removes it -- curvature is no longer frozen
    at launch at all, so this is no longer a limitation to route around; it
    is the ordinary per-point path. The regression this guards: rhm/rha must
    come from PANDA's OWN solved two-theta, not from the frozen launch
    values agreeing by construction with what compute_snapshot re-derives.
    """
    with _controller("panda") as ctrl:
        launch = ctrl.build_api_launch_state({
            "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "deltaE 0 0.5 0.5",
        })
        vals = launch["vals"]
        scan_config = launch["scan_config"]
        instrument = get_instrument("panda")

        scans = [
            vals["qx"], vals["qy"], vals["qz"], 0.0,
            vals["rhm"], vals["rvm"], vals["rha"], vals["rva"],
            0.0, vals.get("kappa", 0.0), vals.get("psi", 0.0),
        ]
        snapshot = instrument.compute_snapshot(
            (scans, 0), 0, "momentum", scan_config, vals, str(tmp_path),
        )
        assert snapshot.error_flags == []
        assert snapshot.params is not None

        solved_mtt = snapshot.metadata["mtt"]
        solved_att = snapshot.metadata["att"]
        # PANDA's real (H,K,L)=(1,0,0) Bragg geometry is nowhere near PUMA's
        # 41.167 reference default -- proof this point actually solved its
        # own angles rather than inheriting the launch-state frozen ones.
        assert solved_mtt != pytest.approx(41.167, abs=1.0)

        # Ground truth: the producer, called directly at THIS point's own
        # solved two-theta (halved once into theta) -- exactly what AUTOFOCUS
        # is specified to do, not a value re-derived by the assertion.
        expected = scan_config.ideal_curvature(
            scan_config.monocris, scan_config.anacris,
            solved_mtt / 2, solved_att / 2,
        )

        assert snapshot.params["rhm_param"] == pytest.approx(expected["rhm"])
        assert snapshot.params["rvm_param"] == pytest.approx(expected["rvm"])
        assert snapshot.params["rha_param"] == pytest.approx(expected["rha"])
        assert snapshot.params["rva_param"] == pytest.approx(expected["rva"])

        # The snapshot's metadata must record what was actually emitted, and
        # its provenance.
        assert snapshot.metadata["rhm"] == pytest.approx(expected["rhm"])
        assert snapshot.metadata["rvm"] == pytest.approx(expected["rvm"])
        assert snapshot.metadata["rha"] == pytest.approx(expected["rha"])
        assert snapshot.metadata["rva"] == pytest.approx(expected["rva"])
        assert snapshot.metadata["curvature_modes"] == {
            "rhm": "autofocus", "rvm": "autofocus",
            "rha": "autofocus", "rva": "autofocus",
        }
        assert snapshot.metadata["curvature_clamped"] == []


def test_single_pass_hkl_request_matches_the_two_pass_workaround(tmp_path):
    """Acceptance test for the whole slice.

    The pre-slice smoke-run harness had to solve a plain H/K/L request's
    angles once, then submit a SECOND request with those solved angles
    re-patched back in as mtt/att, purely to make the launch-state ideal
    recompute fire -- otherwise "ideal focusing" was the default angle's.
    With AUTOFOCUS honoured per point, a single H/K/L request must now focus
    exactly as well as that two-pass workaround did. If this ever regresses
    to needing the second pass again, this is the test that catches it.
    """
    with _controller("panda") as ctrl:
        instrument = get_instrument("panda")

        def _run_once(patch):
            launch = ctrl.build_api_launch_state(dict(
                patch, scan_command1="deltaE 0 0.5 0.5",
            ))
            vals = launch["vals"]
            scan_config = launch["scan_config"]
            scans = [
                vals["qx"], vals["qy"], vals["qz"], 0.0,
                vals["rhm"], vals["rvm"], vals["rha"], vals["rva"],
                0.0, vals.get("kappa", 0.0), vals.get("psi", 0.0),
            ]
            snapshot = instrument.compute_snapshot(
                (scans, 0), 0, "momentum", scan_config, vals, str(tmp_path),
            )
            assert snapshot.error_flags == []
            return snapshot

        # Pass 1 -- the production path today: submit the bare H/K/L request.
        single_pass = _run_once({"H": 1.0, "K": 0.0, "L": 0.0})

        # Pass 2 -- the historical workaround: re-solve, then resubmit with
        # the solved angles patched in as mtt/att so the OLD launch-state
        # recompute would have fired on them.
        two_pass = _run_once({
            "H": 1.0, "K": 0.0, "L": 0.0,
            "mtt": single_pass.metadata["mtt"],
            "att": single_pass.metadata["att"],
        })

        for axis in ("rhm", "rvm", "rha", "rva"):
            assert single_pass.metadata[axis] == pytest.approx(
                two_pass.metadata[axis]
            ), axis


def test_metadata_matches_emitted_params_for_a_scanned_curvature_axis(tmp_path):
    """A scanned curvature axis carries a bare magnitude the way a scan
    command names it (e.g. ``rha 1.0 3.0 0.5``); set_crystal_bending signs
    it onto the real take-off branch. The snapshot's metadata must record
    what was actually emitted, not the pre-setter magnitude -- for a scanned
    axis those used to disagree in sign."""
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.K_fixed = "Kf Fixed"
    state.fixed_E = 14.68

    vals = {"deltaE": 0.0, "chi": 0.0}
    # Angle mode: IN8's positive mono / negative analyzer take-off branch.
    # rha is the scanned variable, supplied as a bare positive magnitude.
    scans = [41.18, 0.0, 0.0, -41.18, 0.0, 0.0, 1.75, 0.0, 0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state, vals, str(tmp_path),
        variable_name1="rha",
    )
    assert snapshot.error_flags == []
    expected_rha = -1.75   # IN8's analyzer take-off is the negative branch
    assert snapshot.params["rha_param"] == pytest.approx(expected_rha)
    assert snapshot.metadata["rha"] == pytest.approx(expected_rha)


def test_heusler_refusal_disables_the_ideal_button_not_a_crash():
    """IN12's Heusler analyser declares rva focusing_known=False.
    ideal_curvature refuses to invent a radius for it; the GUI must not
    crash on that -- it degrades to the same 'Ideal: --' state a degenerate
    geometry already produces."""
    with _controller("in12") as ctrl:
        dock = ctrl.window.instrument_dock
        d = ctrl.descriptor
        heusler = next(c.id for c in d.ana_crystals if c.id != "pg002")
        dock.set_mono_id("pg002")
        dock.set_ana_id(heusler)
        dock.mtt_edit.setText("-55.834468")
        dock.att_edit.setText("-55.834468")

        ideal = ctrl._compute_ideal_bending_values()
        assert ideal is None

        ctrl.update_ideal_bending_buttons()
        assert dock.rhm_ideal_button.text() == "Ideal: --"
        assert dock.rvm_ideal_button.text() == "Ideal: --"
        assert dock.rha_ideal_button.text() == "Ideal: --"


def test_operator_surface_holds_magnitudes_while_emitted_geometry_stays_signed():
    """The two curvature contracts, pinned together rather than apart.

    A negative-branch instrument is the only place they can be told apart:
    IN12 takes off negative at both crystals, so its emitted radii are
    negative while everything an operator or an API client touches must stay
    a positive magnitude.

    They are asserted in one test on purpose. Five separate times in this
    branch a rule has been enforced in one place and not its twin, and this
    particular pair failed exactly that way: ideal_curvature returns signed
    radii, the GUI Ideal button wrote them straight into the field, and
    tavi/resolution.py applies the scattering sense a second time
    (`monorh = radius_cm(cfg.rhm) * sm`). The emitted McStas geometry stayed
    correct throughout, so nothing visible broke -- only the analytic
    resolution, which a headless campaign consumes without ever seeing a
    radius.
    """
    with _controller("in12") as ctrl:
        d = ctrl.descriptor
        mono, ana = d.mono_crystals[0].id, d.ana_crystals[0].id
        launch = ctrl.build_api_launch_state({
            "mtt": -55.834, "att": -55.834,
            "monocris": mono, "anacris": ana,
            "scan_command1": "deltaE 0 1 0.5",
        })
        vals = launch["vals"]

        for axis in ("rhm", "rvm", "rha", "rva"):
            assert vals[axis] >= 0.0, (
                f"{axis} reached the operator/API surface signed ({vals[axis]}); "
                "tavi/resolution.py will apply the branch sense to it again"
            )

        # ...and the same configuration still emits a negative radius to
        # McStas, where the curvature centre must sit on the take-off side.
        ideal = ctrl.instrument_state.ideal_curvature(
            mono, ana, -55.834 / 2, -55.834 / 2,
        )
        for axis in ("rhm", "rvm", "rha", "rva"):
            assert ideal[axis] < 0.0, (
                f"{axis} lost its take-off branch sign on the physical path"
            )
