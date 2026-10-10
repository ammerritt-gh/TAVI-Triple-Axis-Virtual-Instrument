"""An API patch of position or energy beside a motor-held scan reaches the stage motors.

A scan that selects no geometry holds the motors (``rules.build_plan``), so a
request that patches H beside ``rhm``/``A3``/a slit scan used to run at whatever
motors the GUI held while its metadata echoed the patched H.
``build_api_launch_state`` now solves the stage from the patched geometry first,
with the solver an H-only scan uses; each test compares against the snapshot of
that H-only scan at the same point.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from instruments.tas_runtime import compute_scan_snapshot  # noqa: E402

INSTRUMENT_IDS = [info.id for info in available_instruments()]
STAGE = ("mtt", "stt", "sth", "sgl", "sgu", "att")


@pytest.fixture(scope="module", params=INSTRUMENT_IDS)
def ctrl(request):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument(request.param)
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=request.param, save_selection=lambda _id: None,
    )
    controller = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    try:
        yield controller
    finally:
        controller.shutdown()
        del window


def _run(controller, patch, command):
    """The metadata of each point the request would run, by the launch's own plan."""
    launch = controller.build_api_launch_state({**patch, "scan_command1": command})
    plan, expansion = controller._compile_launch(launch)
    return [compute_scan_snapshot(plan, point, index, launch["scan_config"], launch["vals"],
                                  "unused").metadata
            for index, point in enumerate(expansion.points)]


def _assert_stage(metadata, reference, skip=()):
    for key in STAGE:
        if key not in skip:
            assert metadata[key] == pytest.approx(reference[key], abs=1e-9), key


def test_a_radius_scan_runs_at_the_stage_the_patched_h_solves(ctrl):
    reference = _run(ctrl, {"K": 0.0, "L": 0.0}, "H 1.2 1.2 1")[0]
    held = _run(ctrl, {}, "rhm 2 3 1")[0]
    assert held["stt"] != pytest.approx(reference["stt"], abs=0.5)   # H=1.2 is not the default
    points = _run(ctrl, {"H": 1.2, "K": 0.0, "L": 0.0}, "rhm 2 3 1")
    assert len(points) == 2
    for metadata in points:
        _assert_stage(metadata, reference)


def test_a_rocking_scan_keeps_the_solved_two_theta_and_scans_the_rotation(ctrl):
    reference = _run(ctrl, {"K": 0.0, "L": 0.0}, "H 1.2 1.2 1")[0]
    points = _run(ctrl, {"H": 1.2, "K": 0.0, "L": 0.0}, "A3 10 12 1")
    assert [m["sth"] for m in points] == [10.0, 11.0, 12.0]
    for metadata in points:
        _assert_stage(metadata, reference, skip=("sth",))


def test_an_energy_transfer_alone_moves_the_stage(ctrl):
    reference = _run(ctrl, {}, "deltaE 3 3 1")[0]
    held = _run(ctrl, {}, "rhm 2 3 1")[0]
    assert held["stt"] != pytest.approx(reference["stt"], abs=0.1)
    for metadata in _run(ctrl, {"deltaE": 3.0}, "rhm 2 3 1"):
        _assert_stage(metadata, reference)


def test_a_patched_energy_is_solved_with_the_same_stage(ctrl):
    reference = _run(ctrl, {"fixed_E": 12.0, "H": 1.2}, "H 1.2 1.2 1")[0]
    for metadata in _run(ctrl, {"fixed_E": 12.0, "H": 1.2}, "rhm 2 3 1"):
        _assert_stage(metadata, reference)


def test_an_unreachable_position_is_refused(ctrl):
    with pytest.raises(cm.ApiError) as refused:
        ctrl.build_api_launch_state({"H": 20.0, "scan_command1": "rhm 2 3 1"})
    assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")
    assert "cannot be reached" in refused.value.message
    assert "triangle" in refused.value.message   # the solver's own reason


def test_validate_and_scan_refuse_it_the_same_way(ctrl):
    class SyncBridge:
        def call_on_gui(self, fn, timeout=5.0):
            return fn()

    backend = cm.TaviApiBackend(ctrl, SyncBridge())
    body = {"parameters": {"H": 20.0, "scan_command1": "rhm 2 3 1"}}
    for submit in (backend.submit_validate, backend.submit_scan):
        with pytest.raises(cm.ApiError) as refused:
            submit(body)
        assert (refused.value.status, refused.value.code) == (400, "invalid_parameters")


def test_a_patched_stage_motor_keeps_the_stage_the_callers(ctrl):
    held = ctrl.build_api_launch_state({"scan_command1": "rhm 2 3 1"})["vals"]
    vals = ctrl.build_api_launch_state({"H": 1.2, "A4": 40.0, "scan_command1": "rhm 2 3 1"})["vals"]
    assert vals["stt"] == 40.0
    # The stage is then the caller's whole: nothing else is solved for a 2-theta they did not choose.
    assert (vals["omega"], vals["sgl"], vals["sgu"]) == (held["omega"], held["sgl"], held["sgu"])


def test_a_position_beside_an_hkl_scan_is_left_to_the_points(ctrl):
    held = ctrl.build_api_launch_state({"scan_command1": "K 0 0.5 0.5"})["vals"]
    vals = ctrl.build_api_launch_state({"H": 1.2, "scan_command1": "K 0 0.5 0.5"})["vals"]
    assert (vals["stt"], vals["omega"]) == (held["stt"], held["omega"])


def test_a_plane_lock_owns_the_solved_arcs(ctrl):
    from tavi.orientation import StageUnreachable, lock_plane

    plane = ((1, 0, 1), (0, 1, 0))   # h = l: the arcs tilt to level it
    state = ctrl.instrument_state
    mount = ctrl._build_sample_mount(ctrl._default_parameter_values())
    try:
        tilts = lock_plane(state.goniometer, mount.mounted_basis, *plane)
    except StageUnreachable:
        pytest.skip("this stage cannot level the h = l plane")
    state.plane_lock = {"hkl_u": list(plane[0]), "hkl_v": list(plane[1]), "tilts": tilts}
    patch = {"H": 1.2, "K": 0.0, "L": 1.2}
    try:
        reference = _run(ctrl, {"K": 0.0, "L": 1.2}, "H 1.2 1.2 1")[0]
        for metadata in _run(ctrl, patch, "rhm 2 3 1"):
            _assert_stage(metadata, reference)
            assert (metadata["sgl"], metadata["sgu"]) == (tilts["sgl"], tilts.get("sgu", 0.0))
        # A position off the locked plane is refused in the solver's words.
        with pytest.raises(cm.ApiError) as refused:
            ctrl.build_api_launch_state({"H": 1.2, "L": 0.0, "scan_command1": "rhm 2 3 1"})
        assert refused.value.code == "invalid_parameters"
        assert "locked scattering plane" in refused.value.message
    finally:
        state.plane_lock = None
