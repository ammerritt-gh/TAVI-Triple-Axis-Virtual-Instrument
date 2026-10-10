"""Output folders carry the naming contract's version: written with it, refused without it.

scan_parameters.txt is keyed by canonical IDs and starts with ``api_version: 2``. A folder
written before the A2/A4/A6 renumbering (tests/data/old_*_scan, the shape the old code
wrote) is refused whole by the one loading path the Display dock, the Fitting dock and
goto CEN read from: matching its old names against canonical ones would silently drop its
counts, and its A2 meant another axis.
"""
import contextlib
import os
import re
import shutil
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.data_processing import (OutputVersionError, read_parameters_from_file,  # noqa: E402
                                  require_output_version, write_1D_scan, write_2D_scan,
                                  write_parameters_to_file)
from tavi.quantities import API_VERSION  # noqa: E402
from tavi.scan_jobs import ScanJob  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OLD_NAMES = {
    "mtt", "stt", "omega", "att", "sgl", "sgu", "sth", "H", "K", "L", "qx", "qy", "qz",
    "deltaE", "Ki", "Ei", "Kf", "Ef", "rhm", "rvm", "rha", "rva", "slits_mm",
    "lattice_a", "lattice_b", "lattice_c", "lattice_alpha", "lattice_beta", "lattice_gamma",
}


@contextlib.contextmanager
def _controller(instrument_id="puma"):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    plugin = get_instrument(instrument_id)
    window = cm.TAVIMainWindow(
        plugin.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id=instrument_id, save_selection=lambda _id: None)
    ctrl = cm.TAVIController(window, plugin, api_overrides={"disabled": True})
    try:
        yield ctrl
    finally:
        ctrl.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture(scope="module")
def ctrl():
    with _controller() as controller:
        yield controller


def _log(controller):
    return controller.window.output_dock.message_text.toPlainText()


def _load(controller, folder):
    controller.window.output_dock.message_text.clear()   # the controller is shared by the tests
    controller.window.data_control_dock.load_folder_edit.setText(str(folder))
    controller.load_and_display_data()


# --- the writer ------------------------------------------------------------------------

def test_scan_parameters_are_canonical_and_start_with_the_version(ctrl, tmp_path):
    vals = ctrl.get_gui_values()
    params = ctrl.output_parameters({**vals, "sth": vals["omega"], "scan_index": 3})
    write_parameters_to_file(str(tmp_path), params)

    with open(tmp_path / "scan_parameters.txt", encoding="utf-8") as handle:
        assert handle.readline() == f"api_version: {API_VERSION}\n"
    written = read_parameters_from_file(str(tmp_path))
    assert written["api_version"] == API_VERSION
    assert not OLD_NAMES & set(written), sorted(OLD_NAMES & set(written))
    assert written["mono_two_theta_deg"] == pytest.approx(vals["mtt"])
    assert written["sample_two_theta_deg"] == pytest.approx(vals["stt"])
    assert written["sample_rotation_deg"] == pytest.approx(vals["omega"])
    assert written["analyzer_two_theta_deg"] == pytest.approx(vals["att"])
    assert written["h"] == pytest.approx(vals["H"])
    assert written["incident_energy_mev"] == pytest.approx(vals["Ei"])
    assert written["lattice_a_angstrom"] == pytest.approx(vals["lattice_a"])
    assert "slit.post_mono.horizontal_gap_mm" in written
    assert written["scan_index"] == 3
    require_output_version(written, str(tmp_path))


def test_scan_data_files_carry_the_version_as_a_comment(tmp_path):
    """The column files a consumer may receive apart from scan_parameters.txt name their version too."""
    write_1D_scan([1.0, 2.0], [10.0, 20.0], str(tmp_path), "1D_scan_data.txt",
                  x_label="sample_rotation_deg")
    write_2D_scan([1.0], [2.0], [[3.0]], str(tmp_path), "2D_scan_data.txt", x_label="h", y_label="k")
    for name in ("1D_scan_data.txt", "2D_scan_data.txt"):
        with open(tmp_path / name, encoding="utf-8") as handle:
            assert f"# api_version: {API_VERSION}\n" in handle.readlines()[:2], name


def _negative_branch_radius_point(tmp_path):
    """A PANDA point scanning rhm to 2.0 m on a negative-branch mono."""
    from instruments.panda.plugin import PANDAPlugin
    from instruments.tas_runtime import MOTORS, compute_scan_snapshot
    from plan_helpers import motors_point, plan_for

    plugin, vals, rhm = PANDAPlugin(), {"deltaE": 0.0}, "mono_horizontal_radius_m"
    state = plugin.default_state()
    return compute_scan_snapshot(
        plan_for(plugin, state, vals, MOTORS, scanned=(rhm,)),
        {**motors_point(-80.0, -100.0, 0.0, -80.0), rhm: 2.0}, 1, state, vals, str(tmp_path),
    )


def test_public_values_of_a_point_publishes_requested_and_applied_radii_apart(tmp_path):
    """Every publishing path inherits it: the requested magnitude under the radius ID, the
    signed applied radius under applied_*, and no internal sth or requested_radii."""
    from tavi.quantities import public_values

    metadata = _negative_branch_radius_point(tmp_path).metadata
    published = public_values(metadata)
    assert published["mono_horizontal_radius_m"] == pytest.approx(2.0)
    assert published["applied_mono_horizontal_radius_m"] == metadata["rhm"] < 0
    assert published["sample_rotation_deg"] == metadata["omega"]
    assert not {"rhm", "sth", "requested_radii"} & set(published)


def test_a_scanned_radius_is_written_as_requested_and_its_applied_sign_apart(tmp_path):
    """On a negative-branch mono the point keeps the scanned magnitude under its ID, so the
    Display reload matches it, and the signed take-off radius under applied_*."""
    snapshot = _negative_branch_radius_point(tmp_path)
    with _controller("panda") as controller:
        point = controller.point_output_parameters(controller.get_gui_values(), snapshot.metadata, 1, 1000)
    write_parameters_to_file(str(tmp_path), point)
    written = read_parameters_from_file(str(tmp_path))
    assert written["mono_horizontal_radius_m"] == pytest.approx(2.0)
    assert written["applied_mono_horizontal_radius_m"] < 0
    assert not {"rhm", "requested_radii"} & set(written)


def test_both_scan_parameter_writers_go_through_output_parameters():
    """The McStas path's two writers (the scan, then each point) cannot be run without
    McStas: pin that neither can hand the writer the controller's internal names."""
    with open(os.path.join(os.path.dirname(DATA), "..", "TAVI_PySide6.py"), encoding="utf-8") as handle:
        source = handle.read()
    calls = re.findall(r"write_parameters_to_file\(([^\n]*)", source)
    assert len(calls) == 2, calls
    assert all("output_parameters(" in call for call in calls), calls


# --- the loading path ------------------------------------------------------------------

def _current_folder(controller, tmp_path, relative=False, lone_box_2=False):
    """A post-break scan folder: the scan-level file from a real (deterministic) run, then
    the per-point folders as the McStas path writes them, with the old fixture's detector
    files for their counts. ``relative``: the scan is 'omega -1 1 1' stepped from A3 = 30.
    ``lone_box_2``: the scan is typed in box 2 only, so scan_command1 is empty."""
    controller.output_directory = str(tmp_path)   # before the launch state names its folder
    key = "scan_command2" if lone_box_2 else "scan_command1"
    if relative:
        start = 29.0
        launch = controller.build_api_launch_state({
            "scan_command1": "omega -1 1 1", "sample_rotation_deg": 30.0,
            "number_neutrons": 1000})
        launch["relative_mode_1"] = True
    else:
        start = controller.get_gui_values()["omega"]
        launch = controller.build_api_launch_state({
            key: f"omega {start} {start + 2} 1", "number_neutrons": 1000})
    launch["engine"] = "deterministic"
    controller._compile_launch(launch)
    controller.run_simulation(launch, job=ScanJob(job_id="t-output", source="api", launch_state=launch))
    folders = [p for p in tmp_path.iterdir() if (p / "scan_parameters.txt").exists()]
    assert len(folders) == 1, folders
    folder = folders[0]
    for index, value in enumerate((start, start + 1, start + 2)):
        point = folder / f"scan_{index:04d}"
        write_parameters_to_file(str(point), controller.output_parameters(
            {**launch["vals"], "omega": value, "sth": value, "scan_index": index,
             key: launch["vals"][key]}))
        shutil.copy(os.path.join(DATA, "old_omega_scan", f"scan_{index:04d}", "detector.dat"),
                    point / "detector.dat")
    return folder, start


def test_a_current_folder_loads_and_shows_its_counts(ctrl, tmp_path):
    folder, start = _current_folder(ctrl, tmp_path)
    assert read_parameters_from_file(str(folder))["api_version"] == API_VERSION
    with open(folder / "1D_scan_data.txt", encoding="utf-8") as handle:     # the scanned axis, by ID
        assert handle.readline().split() == ["#", "sample_rotation_deg", "counts"]

    _load(ctrl, folder)

    shown = ctrl.window.display_dock.scan_snapshot()
    assert shown["mode"] == "1D" and shown["variable_name"] == "sample_rotation_deg"
    assert shown["n_measured"] == 3
    assert list(shown["counts"]) == [120, 480, 150]
    assert list(shown["x"]) == pytest.approx([start, start + 1, start + 2], abs=1e-3)
    assert "Data loaded into display dock" in _log(ctrl)


def test_a_relative_scan_reloads_onto_its_absolute_axis(ctrl, tmp_path):
    """'omega -1 1 1' stepped from A3 = 30 ran 29, 30, 31: the folder records that axis and
    the reload puts each point's counts on it, not on the command's offsets."""
    folder, start = _current_folder(ctrl, tmp_path, relative=True)

    _load(ctrl, folder)

    shown = ctrl.window.display_dock.scan_snapshot()
    assert "Data loaded into display dock" in _log(ctrl)
    assert (list(shown["x"]), shown["n_measured"]) == ([29.0, 30.0, 31.0], 3)
    assert list(shown["counts"]) == [120, 480, 150]
    assert read_parameters_from_file(str(folder))["scan_values_1"] == [29.0, 30.0, 31.0]


def test_a_lone_command_2_folder_reloads_on_its_axis(ctrl, tmp_path):
    """A scan typed only in box 2 leaves scan_command1 empty; command 2 is the folder's axis."""
    folder, start = _current_folder(ctrl, tmp_path, lone_box_2=True)

    _load(ctrl, folder)

    shown = ctrl.window.display_dock.scan_snapshot()
    assert "Data loaded into display dock" in _log(ctrl), _log(ctrl)
    assert shown["variable_name"] == "sample_rotation_deg"
    assert (list(shown["x"]), shown["n_measured"]) == (
        pytest.approx([start, start + 1, start + 2], abs=1e-3), 3)
    assert list(shown["counts"]) == [120, 480, 150]


def _radius_folder(controller, tmp_path):
    """A deterministic run of 'rhm -2.4 -2.0 0.2' and its point folders, each written from
    the point's own snapshot metadata as the run writes it (requested magnitude under the ID)."""
    from instruments.tas_runtime import compute_scan_snapshot

    controller.output_directory = str(tmp_path)
    launch = controller.build_api_launch_state({
        "scan_command1": "rhm -2.4 -2.0 0.2", "number_neutrons": 1000})
    launch["engine"] = "deterministic"
    plan, expansion = controller._compile_launch(launch)
    controller.run_simulation(launch, job=ScanJob(job_id="t-radius", source="api", launch_state=launch))
    folder = next(p for p in tmp_path.iterdir() if (p / "scan_parameters.txt").exists())
    for index, point in enumerate(expansion.points):
        snapshot = compute_scan_snapshot(plan, point, index, launch["scan_config"],
                                         launch["vals"], str(folder))
        target = folder / f"scan_{index:04d}"
        write_parameters_to_file(str(target), controller.point_output_parameters(
            launch["vals"], snapshot.metadata, index, 1000))
        shutil.copy(os.path.join(DATA, "old_omega_scan", f"scan_{index:04d}", "detector.dat"),
                    target / "detector.dat")
    return folder


def test_a_negative_radius_scan_reloads_on_the_typed_axis(ctrl, tmp_path):
    """The axis keeps the signs typed; each point publishes the radius magnitude it asked for,
    so the reload matches by magnitude instead of rejecting every point."""
    folder = _radius_folder(ctrl, tmp_path)
    assert read_parameters_from_file(str(folder))["scan_values_1"] == pytest.approx(
        [-2.4, -2.2, -2.0])

    _load(ctrl, folder)

    shown = ctrl.window.display_dock.scan_snapshot()
    assert "Data loaded into display dock" in _log(ctrl), _log(ctrl)
    assert (list(shown["x"]), shown["n_measured"]) == (pytest.approx([-2.4, -2.2, -2.0]), 3)
    assert list(shown["counts"]) == [120, 480, 150]


def test_a_relative_folder_without_its_axis_is_refused_not_mislabelled(ctrl, tmp_path):
    """A folder written before the axis was recorded: its points lie on none of the command's
    offsets, so it is refused with a message instead of piling counts into one bin."""
    folder, _start = _current_folder(ctrl, tmp_path, relative=True)
    path = folder / "scan_parameters.txt"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(l for l in lines if not l.startswith("scan_values_")),
                    encoding="utf-8")
    ctrl.window.display_dock.initialize_scan("1D", [1.0, 2.0], [True, True], "h")
    before = ctrl.window.display_dock.scan_snapshot()

    _load(ctrl, folder)

    log = _log(ctrl)
    assert "Data loaded into display dock" not in log
    assert "sample_rotation_deg = 29 lies on none of the scan's axis values" in log, log
    shown = ctrl.window.display_dock.scan_snapshot()
    assert shown["variable_name"] == before["variable_name"] == "h"
    assert list(shown["x"]) == list(before["x"])


@pytest.mark.parametrize("fixture", ["old_omega_scan", "old_a2_scan"])
def test_a_pre_break_folder_is_refused_and_nothing_is_loaded_or_driven(ctrl, tmp_path, fixture):
    folder = tmp_path / fixture
    shutil.copytree(os.path.join(DATA, fixture), folder)
    before_files = sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))
    ctrl.set_default_parameters()
    ctrl.window.display_dock.initialize_scan("1D", [1.0, 2.0], [True, True], "h")  # something shown
    shown_before = ctrl.window.display_dock.scan_snapshot()
    gui_before = ctrl.get_gui_values()
    driven = []
    real_apply = ctrl.apply_parameters
    ctrl.apply_parameters = lambda *a, **k: driven.append(a) or real_apply(*a, **k)
    try:
        _load(ctrl, folder)

        # Nothing was loaded: the plot still shows what it showed, not the folder's scan.
        shown = ctrl.window.display_dock.scan_snapshot()
        assert shown["variable_name"] == shown_before["variable_name"] == "h"
        assert shown["n_measured"] == shown_before["n_measured"]
        log = _log(ctrl)
        assert "older TAVI with the old angle numbering" in log and str(folder) in log, log
        assert "Data loaded into display dock" not in log

        # The Fitting dock has no scan of the folder to fit, so goto CEN has nothing to
        # drive: no field is written, whichever axis the old scan was on.
        ctrl.window.fitting_dock._on_goto_clicked("cen")
        assert driven == []
        assert ctrl.get_gui_values() == gui_before
    finally:
        ctrl.apply_parameters = real_apply
    assert sorted(str(p.relative_to(folder)) for p in folder.rglob("*")) == before_files


def test_the_dock_refuses_before_it_resolves_any_name(ctrl, tmp_path):
    """A caller that skips the controller (the Display dock's own loader) is refused too:
    A2 would otherwise resolve to the mono 2theta and match no key of the old files."""
    folder = tmp_path / "old_a2_scan"
    shutil.copytree(os.path.join(DATA, "old_a2_scan"), folder)
    with pytest.raises(OutputVersionError, match="older TAVI"):
        ctrl.window.display_dock.load_existing_data(str(folder), "A2 70 72 1")


def test_another_version_is_named_not_called_old(tmp_path):
    (tmp_path / "scan_parameters.txt").write_text("api_version: 3\nscan_command1: h 1 2 1\n", encoding="utf-8")
    with pytest.raises(OutputVersionError, match=r"api_version 3\.0; this TAVI reads 2"):
        require_output_version(read_parameters_from_file(str(tmp_path)), str(tmp_path))


def test_a_folder_without_a_parameter_file_keeps_its_old_answer(ctrl, tmp_path):
    """No scan_parameters.txt is not a pre-break folder: it has no scan command to load."""
    require_output_version(read_parameters_from_file(str(tmp_path)), str(tmp_path))
    _load(ctrl, tmp_path)
    assert "older TAVI" not in _log(ctrl)
