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
import contextlib
import json
import math
import os
import sys
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.in8.plugin import IN8Plugin
from instruments.registry import get_instrument  # noqa: E402
from instruments.tas_runtime import compute_scan_snapshot
from tavi.api_server import TaviApiServer, API_PREFIX, VALIDATE_BODY_KEYS  # noqa: E402
from tavi.data_processing import read_parameters_from_file  # noqa: E402
from tavi.neutron_conversions import angle2k, energy2k, k2angle, k2energy
from tavi.scan_jobs import ScanJob  # noqa: E402

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


# ---------------------------------------------------------------------------
# Slice 2: every consumer makes no claim at a marked point.
# ---------------------------------------------------------------------------
#
# The saved per-point McStas file (``TAVI_PySide6.py``'s ``scan_point_params``
# build, ~line 9079) is not separately unit-tested here: it was not factored
# into a standalone pure helper (the surrounding McStas per-point loop reads
# many other locals it would need to take as arguments, for no behavioural
# gain), so it is verified by reading the code region instead -- the
# ``'deltaE': deltaE`` override onto ``{**metadata, ...}`` was deleted, so the
# saved file's ``deltaE`` is exactly ``metadata['deltaE']`` (``None`` at a
# marked point) with nothing left to overwrite it.

@contextlib.contextmanager
def _controller(instrument_id):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=[],
        current_instrument_id=instrument_id, save_selection=lambda _id: None,
    )
    ctrl = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


class _SyncBridge:
    """Stand-in for ApiBridge: run the marshalled call inline (no GUI thread)."""

    def call_on_gui(self, fn, timeout=5.0):
        return fn()


def _in8_mtt_for_ei(ei):
    """The A1 that selects the given Ei -- same construction as the
    reproducer and the slice 1 tests above."""
    plugin = IN8Plugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    return 2 * state.sense_mono * k2angle(energy2k(ei), state.crystal_info(
        state.monocris, state.anacris)[0]['dm'])


# --- _background_q_magnitude -----------------------------------------------

def test_background_q_magnitude_none_for_a_marked_angle_point():
    """The reproducer's exact input (A above)."""
    result = cm._background_q_magnitude({
        'qx': None, 'qy': None, 'qz': None,
        'Ki': 2.66, 'Kf': None, 'stt': 30.0, 'transmission': ['ana'],
    })
    assert result is None


def test_background_q_magnitude_none_for_sample_transmission_with_both_k():
    """A sample-only transmission still has both Ki and Kf -- |Q| would
    otherwise compute (critic finding) -- but the point is still marked."""
    result = cm._background_q_magnitude({
        'qx': None, 'qy': None, 'qz': None,
        'Ki': 2.5, 'Kf': 2.3, 'stt': 0.0, 'transmission': ['sample'],
    })
    assert result is None


def test_background_q_magnitude_returns_a_number_for_an_ordinary_point():
    result = cm._background_q_magnitude({
        'qx': None, 'qy': None, 'qz': None,
        'Ki': 2.66, 'Kf': 2.3, 'stt': 30.0, 'transmission': [],
    })
    assert isinstance(result, float)
    assert result > 0


# --- Deterministic engine, real controller rig ------------------------------

def test_deterministic_engine_a4_scan_skips_only_the_transmission_point(tmp_path):
    """A 3-point angle-mode A4 scan through 0 on IN8: the neighbours produce
    finite counts, the zero point is NaN, the message names direct
    transmission, and no exception is raised."""
    mtt = _in8_mtt_for_ei(20.0)
    with _controller("in8") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "K_fixed": "Kf Fixed", "fixed_E": _FIXED_E,
            "monocris": "pg002", "anacris": "pg002", "source_type": "Mono",
            "mtt": mtt, "stt": -71.25, "omega": -35.63,
            "scan_command1": "A4 -1 1 1",
        })
        launch["engine"] = "deterministic"

        job = ScanJob(job_id="t-transmission-a4", source="api", launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        result = job.result
        assert result is not None
        assert len(result.counts) == 3
        assert math.isfinite(result.counts[0]), result.counts
        # A skipped point leaves the pre-sized ``None`` placeholder untouched
        # -- the same convention as ``applied_curvature`` (see scan_jobs.py):
        # never a stray 0.0 or NaN that could be mistaken for a measurement.
        assert result.counts[1] is None, result.counts
        assert math.isfinite(result.counts[2]), result.counts

        assert result.skipped_points == [{
            "index": 1, "values": {"A4": 0.0}, "kind": "transmission",
            "reason": "direct transmission (ana); the analytic engine makes "
                      "no claim",
        }]
        assert result.transmission_points == [{"index": 1, "axes": ["ana"]}]


def test_deterministic_engine_stt_scan_skips_forward_scattering_point(tmp_path):
    """Both crystals reflect; only the sample take-off is zero (ruling 7)."""
    with _controller("in8") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "K_fixed": "Kf Fixed", "fixed_E": _FIXED_E,
            "monocris": "pg002", "anacris": "pg002", "source_type": "Maxwellian",
            "mtt": 41.19, "stt": -1.0, "omega": -35.63, "att": -41.19,
            "scan_command1": "A2 -1 1 1",
        })
        launch["engine"] = "deterministic"

        job = ScanJob(job_id="t-transmission-stt", source="api", launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        result = job.result
        assert result is not None
        assert len(result.counts) == 3
        assert math.isfinite(result.counts[0]), result.counts
        assert result.counts[1] is None, result.counts
        assert math.isfinite(result.counts[2]), result.counts

        assert result.skipped_points == [{
            "index": 1, "values": {"A2": 0.0}, "kind": "transmission",
            "reason": "direct transmission (sample); the analytic engine "
                      "makes no claim",
        }]
        assert result.transmission_points == [{"index": 1, "axes": ["sample"]}]


# --- Validation: /scan and /validate ----------------------------------------

def test_deterministic_scan_command_at_a4_zero_needs_allow_partial(monkeypatch, tmp_path):
    """A deterministic job with an A4 = 0 point is rejected 400 without
    ``allow_partial``; with it, the submission's validation block lists the
    point ``kind == "transmission"``. The same body under engine ``mcstas``
    validates clean (ruling 1: legal there). ``submit_scan_job`` is
    monkeypatched to run synchronously in this thread instead of the real
    background worker/queue -- no sleep or polling needed to observe the
    result.
    """
    mtt = _in8_mtt_for_ei(20.0)
    patch = {
        "K_fixed": "Kf Fixed", "fixed_E": _FIXED_E,
        "monocris": "pg002", "anacris": "pg002", "source_type": "Mono",
        "mtt": mtt, "stt": -71.25, "omega": -35.63,
        "scan_command1": "A4 -1 1 1",
    }
    with _controller("in8") as ctrl:
        ctrl.output_directory = str(tmp_path)

        def _run_now(launch_state, source):
            job = ScanJob(job_id="t-vt-a4", source=source, launch_state=launch_state)
            ctrl.run_simulation(launch_state, job=job)
            return job

        monkeypatch.setattr(ctrl, "submit_scan_job", _run_now)
        backend = cm.TaviApiBackend(ctrl, _SyncBridge())

        body = {"parameters": patch, "engine": "deterministic"}
        with pytest.raises(cm.ApiError) as excinfo:
            backend.submit_scan(body)
        assert excinfo.value.code == "infeasible_points"

        result = backend.submit_scan({**body, "allow_partial": True})
        infeasible = result["validation"]["infeasible"]
        assert any(p["kind"] == "transmission" for p in infeasible), infeasible

        clean = backend.submit_validate({"parameters": patch, "engine": "mcstas"})
        assert clean["would_queue"] is True
        assert clean["infeasible"] == []


class _DeadTransferInstrument:
    def check_point_feasibility(self, scan_config, scan_mode, point, vals):
        return False, "scattering triangle cannot close for this (Q, E) and fixed-k setup"


class _DeadTransferManifestController:
    """Duck-typed stub, same shape as
    ``tests/test_api_over_limit_latch.py``'s ``_ManifestController`` -- the
    direct ``validate_scan_launch_state`` call shape, no real controller."""
    _SCAN_VARIABLE_TO_INDEX = {"deltaE": 3}
    instrument = _DeadTransferInstrument()

    def _determine_scan_mode(self, cmd1, cmd2):
        return "momentum"

    def _build_scan_point_template(self, scan_mode, vals):
        return [2.0, 0.0, 0.5, 0.0]

    def normalize_scan_variable(self, variable):
        return variable

    def _curvature_axis_specs(self, monocris, anacris, modules=None):
        return {}

    def print_to_message_center(self, message):
        raise AssertionError("unexpected message: %s" % message)


def test_deterministic_engine_never_relabels_an_already_infeasible_point():
    """A point infeasible for its OWN reason keeps that kind/reason under a
    deterministic launch state -- never relabelled ``transmission`` (the
    plan-verifier's second-pass blocker)."""
    launch_state = {
        "vals": {"scan_command1": "deltaE 3.0 3.0 1.0", "scan_command2": ""},
        "scan_config": object(),
        "relative_mode_1": False,
        "relative_mode_2": False,
        "engine": "deterministic",
    }
    result = cm.TAVIController.validate_scan_launch_state(
        _DeadTransferManifestController(), launch_state)
    assert result["infeasible"] == [{
        "index": 0,
        "values": {"deltaE": pytest.approx(3.0)},
        "kind": "physical_infeasible",
        "reason": "scattering triangle cannot close for this (Q, E) and fixed-k setup",
    }]


def test_validate_body_keys_include_engine_seed_noiseless():
    assert {"engine", "seed", "noiseless"} <= VALIDATE_BODY_KEYS


def test_validate_http_endpoint_accepts_engine_seed_noiseless_body():
    """Fake-backend HTTP rig, same shape as ``test_api_validation_schema.py``."""

    class _FakeBackend:
        def submit_validate(self, body):
            return {"would_queue": True, "blockers": [], "infeasible": [],
                    "requested_points": 0, "feasible_points": 0}

    srv = TaviApiServer(host="127.0.0.1", port=0, token=None, mode="allow",
                        backend=_FakeBackend())
    srv.start()
    try:
        port = srv._httpd.server_address[1]
        url = "http://127.0.0.1:%d%s/validate" % (port, API_PREFIX)
        data = json.dumps(
            {"engine": "deterministic", "seed": 7, "noiseless": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        assert resp.getcode() == 200
    finally:
        srv.stop()


# --- compute_resolution ------------------------------------------------------

def test_compute_resolution_refuses_forward_scattering(monkeypatch):
    """A geometry that solves to stt == 0 is refused by its own solved
    angles -- ``_hkl_to_sample_q`` is stubbed to isolate that refusal from
    the (unrelated) sample-mount HKL solve."""
    fixed_E = 14.68
    deltaE = 5.0
    Ef = fixed_E
    Ei = Ef + deltaE
    ki = energy2k(Ei)
    kf = energy2k(Ef)
    with _controller("in8") as ctrl:
        ctrl.apply_parameters({
            "K_fixed": "Kf Fixed", "fixed_E": fixed_E,
            "monocris": "pg002", "anacris": "pg002",
        })
        monkeypatch.setattr(
            ctrl, "_hkl_to_sample_q",
            lambda H, K, L, vals: (ki - kf, 0.0, 0.0),
        )
        result = ctrl.compute_resolution(H=0.0, K=0.0, L=0.0, deltaE=deltaE)
        assert result == {
            "ok": False,
            "reason": "direct transmission (sample): the analytic engine makes no claim",
        }

    with _controller("in8") as ctrl:
        ctrl.apply_parameters({
            "K_fixed": "Kf Fixed", "fixed_E": fixed_E,
            "monocris": "pg002", "anacris": "pg002",
        })
        result = ctrl.compute_resolution(H=1.0, K=0.0, L=0.0, deltaE=2.0)
        assert result.get("ok") is not False, result


# --- tavi.data_processing.read_parameters_from_file --------------------------

def test_read_parameters_from_file_handles_none_and_transmission_list(tmp_path):
    folder = str(tmp_path)
    with open(os.path.join(folder, "scan_parameters.txt"), "w", encoding="utf-8") as f:
        f.write("deltaE: None\n")
        f.write("transmission: ['ana']\n")
        f.write("fixed_E: 14.68\n")

    params = read_parameters_from_file(folder)
    assert params["deltaE"] is None
    assert params["transmission"] == ["ana"]
    assert params["fixed_E"] == pytest.approx(14.68)


def test_read_parameters_from_file_empty_transmission_list(tmp_path):
    folder = str(tmp_path)
    with open(os.path.join(folder, "scan_parameters.txt"), "w", encoding="utf-8") as f:
        f.write("transmission: []\n")

    params = read_parameters_from_file(folder)
    assert params["transmission"] == []


# --- Reload metadata builder --------------------------------------------------

def test_reload_metadata_builder_marks_undetermined_deltaE():
    with _controller("in8") as ctrl:
        metadata = ctrl._build_scan_metadata_from_parameters({
            "deltaE": "None", "transmission": ["ana"],
        })
    assert metadata["deltaE"] is None
    assert metadata["transmission"] == ["ana"]


# --- Display dock info panel --------------------------------------------------

def test_delta_e_info_line_reports_undetermined_at_a_marked_point():
    from gui.docks.display_dock import _delta_e_info_line

    line = _delta_e_info_line({"deltaE": None, "transmission": ["ana"]})
    assert line is not None
    assert "undetermined" in line

    ordinary = _delta_e_info_line({"deltaE": 1.5})
    assert ordinary == "ΔE = 1.500 meV"


def test_display_dock_full_info_panel_handles_undetermined_deltaE():
    from matplotlib.figure import Figure

    with _controller("in8") as ctrl:
        dock = ctrl.window.display_dock
        dock._scan_metadata = {"deltaE": None, "transmission": ["ana"]}
        fig = Figure()
        ax = fig.add_subplot(111)
        dock._add_full_info_panel_to_figure(ax)  # must not raise
        texts = [t.get_text() for t in ax.texts]
        assert any("undetermined" in t for t in texts), texts
