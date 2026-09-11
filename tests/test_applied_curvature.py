"""Slice 8: ``ScanResult.applied_curvature`` records what each point actually
ran with, not what the scan launched with.

Before this slice, curvature was constant for a whole scan, so recording it
once in the run header (``ScanResult.metadata``) was correct -- the header
genuinely described every point. Autofocus ended that: a fixed-kf scan sweeps
the mono take-off (hence rhm) point to point while the analyser take-off
(hence rha) holds. ``metadata['rhm']`` still reports only the launch value;
``applied_curvature`` is the per-point record of what the physical boundary
actually emitted at each point, SIGNED (the same convention as the McStas
per-point files -- the opposite of the operator/API ``vals``, which are
magnitudes).

The deterministic engine writes no per-point files at all, so it is exercised
here end to end (fast: no McStas compile/run) through a real ``ScanJob`` --
this is the ONLY place its truth can live. The McStas per-point-file path is
already pinned by ``test_emitted_curvature.py`` at the ``compute_snapshot``
level; the per-point job.result wiring added here is identical code run from
the same per-point metadata dict, verified by reading (see PR diff).
"""
import contextlib
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
from tavi.scan_jobs import ScanJob  # noqa: E402


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


def test_deterministic_engine_applied_curvature_tracks_each_point(tmp_path):
    """PUMA, fixed kf: rhm (mono side) must differ point to point across a
    deltaE scan; rha (analyser side, constant kf) must not. This is test #1
    and #3 from the packet at once -- the deterministic engine is the path
    under test, and it is the only path with no other record.
    """
    with _controller("puma") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "K_fixed": "Kf Fixed", "fixed_E": 14.7,
            "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "deltaE -3 6 3",
        })
        launch["engine"] = "deterministic"
        launch_rhm = launch["vals"]["rhm"]

        job = ScanJob(job_id="t-applied-curvature-det", source="api",
                       launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        result = job.result
        assert result is not None
        # "deltaE -3 6 3" (start stop STEP) is 4 points: -3, 0, 3, 6.
        assert len(result.applied_curvature) == 4, result.applied_curvature
        assert all(pt is not None for pt in result.applied_curvature), \
            result.applied_curvature

        rhm_values = [pt["rhm"] for pt in result.applied_curvature]
        rha_values = [pt["rha"] for pt in result.applied_curvature]
        print("applied_curvature rhm across points:", rhm_values)
        print("applied_curvature (full):", result.applied_curvature)

        assert len({round(v, 6) for v in rhm_values}) == 4, (
            f"rhm must track this point's own mono take-off (ki sweeps with "
            f"deltaE at fixed kf); got {rhm_values}"
        )
        assert len({round(v, 6) for v in rha_values}) == 1, (
            f"rha must not move: kf is fixed, so the analyser take-off is "
            f"constant across the scan; got {rha_values}"
        )

        # metadata (test #2): the launch reference is untouched.
        assert result.metadata["rhm"] == pytest.approx(launch_rhm)


def test_deterministic_engine_leaves_skipped_point_as_none(tmp_path):
    """An infeasible/skipped point leaves ``None`` in applied_curvature, like
    the other index-parallel lists -- never a zero that reads as a flat
    crystal (packet test #4).
    """
    with _controller("puma") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "H": 1.0, "K": 0.0, "L": 0.0,
            # A wildly out-of-range deltaE point is expected to fail the
            # angle solve (error_flags) alongside two feasible ones.
            "scan_command1": "deltaE -3 3 3",
        })
        launch["engine"] = "deterministic"

        job = ScanJob(job_id="t-applied-curvature-skip", source="api",
                       launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        result = job.result
        assert result is not None
        # Whatever the feasibility of these particular points, every entry is
        # either None (unmeasured/invalid) or a full signed radii dict --
        # never a bare 0.0 masquerading as a flat crystal.
        for pt in result.applied_curvature:
            assert pt is None or (
                isinstance(pt, dict) and set(pt) == {"rhm", "rvm", "rha", "rva"}
            ), result.applied_curvature


def test_curvature_modes_is_read_only_in_schema_and_refused_on_write(tmp_path):
    """``curvature_modes`` is declared in the API schema as read-only state,
    and PATCH /parameters refuses a write against it rather than silently
    dropping it or accepting it as a no-op (packet test #5).
    """
    with _controller("puma") as ctrl:
        schema = ctrl.build_api_schema()
        entry = next(
            (f for f in schema["fields"] if f["name"] == "curvature_modes"), None
        )
        assert entry is not None, "curvature_modes missing from GET /schema"
        assert entry.get("readOnly") is True

        applied, errors = ctrl.apply_parameters({"curvature_modes": {"rhm": "held"}})
        assert "curvature_modes" not in applied
        assert "curvature_modes" in errors
        assert errors["curvature_modes"] == "read-only field"


def test_a_2d_scan_indexes_applied_curvature_the_same_way_as_its_counts(tmp_path):
    """A 2D scan stores applied_curvature flat, row-major, at the same linear
    index its feasibility masks use (idx_y * len(scan_values_1) + idx_x) --
    while counts_grid is nested. Two index conventions over one scan is the
    shape of defect this branch keeps removing, and the flat one is untested
    by the 1D cases above: a wrong formula there does not crash, it silently
    attributes one point's geometry to another.

    Pinned by physics rather than by arithmetic: at fixed kf the mono take-off
    depends on deltaE alone, so every point sharing a deltaE must share an rhm,
    and points at different deltaE must not. If the linear index were
    transposed or off, that grouping would break.
    """
    with _controller("puma") as ctrl:
        ctrl.output_directory = str(tmp_path)
        launch = ctrl.build_api_launch_state({
            "K_fixed": "Kf Fixed", "fixed_E": 14.7,
            "H": 1.0, "K": 0.0, "L": 0.0,
            "scan_command1": "qx 1.0 1.2 0.1",   # 3 points, no effect on mono take-off
            "scan_command2": "deltaE 0 4 2",     # 3 points, sweeps ki and so rhm
        })
        launch["engine"] = "deterministic"

        job = ScanJob(job_id="t-applied-curvature-2d", source="api",
                       launch_state=launch)
        ctrl.run_simulation(launch, job=job)

        result = job.result
        assert result is not None
        n_x = len(result.scan_values_1)
        n_y = len(result.scan_values_2)
        assert (n_x, n_y) == (3, 3), (n_x, n_y)
        assert len(result.applied_curvature) == n_x * n_y, result.applied_curvature

        rows = []
        for iy in range(n_y):
            row = [result.applied_curvature[iy * n_x + ix] for ix in range(n_x)]
            assert all(pt is not None for pt in row), (iy, row)
            rows.append([round(pt["rhm"], 6) for pt in row])

        for iy, row in enumerate(rows):
            assert len(set(row)) == 1, (
                f"row {iy} shares one deltaE, so every point in it must share "
                f"an rhm; got {row} -- the linear index is wrong"
            )
        first_of_each_row = [row[0] for row in rows]
        assert len(set(first_of_each_row)) == n_y, (
            f"each row is a different deltaE and so a different mono take-off; "
            f"got {first_of_each_row} -- the linear index is wrong"
        )
