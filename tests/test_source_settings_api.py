"""The moderator source as a public contract: API fields, saved parameters, Run, outputs.

The nine canonical IDs (tavi/quantities.py) replace source_type and source_dE. The old
names are refused naming the new ones. A profile write loads its entry's T/I and the same
request's own T/I stand over it in either key order. An invalid source is refused (API 400,
Run blocked) before any state changes. Every scan file and result carries the provenance.
All of it runs offscreen on the real controller, the HTTP cases through the real server.
"""
import json
import os
import re
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as cm  # noqa: E402
from instruments import source as moderator  # noqa: E402
from tavi import deterministic_engine as det  # noqa: E402
from tavi.data_processing import write_parameters_to_file  # noqa: E402
from tavi.quantities import API_VERSION  # noqa: E402
from tavi.scan_jobs import JobState, ScanJob  # noqa: E402

from test_api_canonical_names import _patch, _state, api, fresh  # noqa: E402,F401  (the real-server fixtures)
from test_saved_parameters import _log, _write_block, saved_file  # noqa: E402,F401
from test_training_exercise import _controller_for  # noqa: E402

SCAN = {"scan_command1": "deltaE 0 1 1"}
NINE = moderator.FIELD_IDS


def _source(call):
    """The nine source values GET /parameters reports."""
    status, parameters = call("GET", "/parameters")
    assert status == 200, parameters
    return {key: parameters[key] for key in NINE}


def _dock_text(controller):
    """What the facility combo shows: the entry, with '(modified)' once the fields differ."""
    return controller.window.instrument_dock.source_profile_combo.currentText()


# --- the old names are refused, in any letter case, naming the new ones -------------------

@pytest.mark.parametrize("old, must_name", [
    ("source_type", ["moderator_mode", "moderator_profile", "moderator_t1_k"]),
    ("SOURCE_TYPE", ["moderator_mode", "moderator_profile"]),
    ("Source_Type", ["moderator_mode", "moderator_profile"]),
    ("source_dE", ["flat_band_half_width_mev"]),
    ("source_de", ["flat_band_half_width_mev"]),
    ("SOURCE_DE", ["flat_band_half_width_mev"]),
])
def test_an_old_name_is_refused_in_any_case_naming_the_new_ones(fresh, old, must_name):
    _controller, call = fresh
    before = _state(call)

    status, reply = _patch(call, {old: "Mono" if "type" in old.lower() else 2.0, "H": 1.5})

    assert status == 400, reply
    message = reply["error"]["details"]["errors"][old]
    assert all(name in message for name in must_name), message
    assert reply["error"]["details"]["applied"] == []          # the valid H beside it is not applied either
    assert _state(call) == before

    for path in ("/validate", "/scan"):                         # the scan body is guarded the same way
        status, reply = call("POST", path, {"api_version": API_VERSION,
                                            "parameters": {**SCAN, old: 2.0}})
        assert status == 400 and old in reply["error"]["details"]["errors"], (path, reply)
        assert _state(call) == before


def test_the_nine_names_are_writable_and_listed_by_get_parameters(fresh):
    controller, call = fresh
    assert set(_source(call)) == set(NINE)
    defaults = _source(call)
    assert defaults["moderator_mode"] == "full_spectrum"
    assert defaults["moderator_profile"] == controller.descriptor.default_moderator_profile
    assert defaults["flat_band_half_width_mev"] == 2.0
    status, reply = _patch(call, {name: value for name, value in defaults.items()})
    assert status == 200, reply
    assert set(reply["applied"]) == set(NINE)


# --- a profile write loads the entry's T/I; the request's own T/I stand over it -----------

def test_a_profile_write_fills_t_and_i_and_leaves_the_entry_unmodified(fresh):
    controller, call = fresh
    status, reply = _patch(call, {"moderator_profile": "frm2_cold"})
    assert status == 200 and reply["applied"] == ["moderator_profile"], reply
    state = _source(call)
    assert state["moderator_profile"] == "frm2_cold"
    assert {key: state[key] for key in moderator.TI_IDS} == moderator.profile_values("frm2_cold")
    assert "(modified)" not in _dock_text(controller)


@pytest.mark.parametrize("body", [
    {"moderator_profile": "frm2_cold", "moderator_t1_k": 500.0, "moderator_i3": 1e12},
    {"moderator_t1_k": 500.0, "moderator_i3": 1e12, "moderator_profile": "frm2_cold"},
    {"moderator_i3": 1e12, "moderator_profile": "frm2_cold", "moderator_t1_k": 500.0},
], ids=["profile-first", "profile-last", "profile-between"])
def test_the_requests_own_t_and_i_override_the_profile_in_either_key_order(fresh, body):
    controller, call = fresh
    _patch(call, {"moderator_profile": "frm2_thermal"})        # start from another entry

    status, reply = _patch(call, body)

    assert status == 200, reply
    state = _source(call)
    cold = moderator.profile_values("frm2_cold")
    assert state["moderator_profile"] == "frm2_cold"
    assert state["moderator_t1_k"] == 500.0 and state["moderator_i3"] == 1e12
    for key in set(moderator.TI_IDS) - {"moderator_t1_k", "moderator_i3"}:
        assert state[key] == cold[key], key                    # the rest is the entry's
    assert _dock_text(controller).endswith("(modified)")       # the edit shows, as it would by hand


def test_a_scan_body_loads_a_profile_under_its_own_t_and_i_too(fresh):
    controller, _call = fresh
    launch = controller.build_api_launch_state({
        **SCAN, "moderator_t2_k": 111.0, "moderator_profile": "hzb_bispectral"})
    vals = launch["vals"]
    expected = {**moderator.profile_values("hzb_bispectral"), "moderator_t2_k": 111.0}
    assert {key: vals[key] for key in moderator.TI_IDS} == expected
    assert launch["scan_config"].source_values()["moderator_profile"] == "hzb_bispectral"


# --- an invalid source is refused before anything changes --------------------------------

@pytest.mark.parametrize("body, names", [
    ({"moderator_t1_k": -5.0}, ["moderator_t1_k"]),
    ({"moderator_i2": -1.0}, ["moderator_i2"]),
    ({"moderator_t1_k": "abc"}, ["moderator_t1_k"]),
    ({"moderator_i1": float("nan")}, ["moderator_i1"]),
    ({"moderator_mode": "sideways"}, ["moderator_mode"]),
    ({"moderator_profile": "nowhere"}, ["moderator_profile"]),
    ({"moderator_i1": 0.0, "moderator_i2": 0.0, "moderator_i3": 0.0}, ["moderator_i1"]),
    ({"moderator_mode": "flat_band", "flat_band_half_width_mev": 0.0}, ["flat_band_half_width_mev"]),
    ({"flat_band_half_width_mev": "wide"}, ["flat_band_half_width_mev"]),
])
def test_an_invalid_source_is_refused_with_no_state_change(fresh, body, names):
    controller, call = fresh
    before = _state(call)
    dock_before = controller.window.instrument_dock.source_settings()

    status, reply = _patch(call, {**body, "H": 1.5})           # the valid H beside it is not applied

    assert status == 400, reply
    assert set(names) <= set(reply["error"]["details"]["errors"]), reply
    assert reply["error"]["details"]["applied"] == []
    assert _state(call) == before
    assert controller.window.instrument_dock.source_settings() == dock_before

    status, reply = call("POST", "/validate", {"api_version": API_VERSION,
                                               "parameters": {**SCAN, **body}})
    assert status == 400 and set(names) <= set(reply["error"]["details"]["errors"]), reply
    assert _state(call) == before


def test_a_flat_band_write_over_a_blank_de_is_refused_while_full_spectrum_ignores_it(fresh):
    """The dock's dE is judged as it stands: blank is refused in flat band, allowed in full spectrum."""
    controller, call = fresh
    controller.window.instrument_dock.flat_band_edit.setText("")
    before = _state(call)

    status, reply = _patch(call, {"moderator_mode": "flat_band"})

    assert status == 400, reply
    assert "flat_band_half_width_mev" in reply["error"]["details"]["errors"]["moderator_mode"]
    assert _state(call) == before
    assert _source(call)["moderator_mode"] == "full_spectrum"

    status, reply = _patch(call, {"moderator_t1_k": 300.0})     # dE is unused in full spectrum
    assert status == 200, reply

    status, reply = _patch(call, {"moderator_mode": "flat_band", "flat_band_half_width_mev": 2.5})
    assert status == 200, reply
    assert _source(call)["moderator_mode"] == "flat_band"


def test_an_api_source_write_refreshes_the_scan_verdict_once(fresh, monkeypatch):
    """The GUI's source_changed refreshes the scan-command verdict; an API write does the same, once."""
    controller, call = fresh
    refreshes = []
    monkeypatch.setattr(controller, "validate_scan_commands", lambda: refreshes.append(True))

    status, reply = _patch(call, {"moderator_profile": "frm2_cold", "moderator_t2_k": 300.0,
                                  "moderator_mode": "flat_band", "flat_band_half_width_mev": 2.0})

    assert status == 200, reply
    assert len(refreshes) == 1


def test_a_valid_source_that_would_leave_no_pair_is_judged_on_the_result(fresh):
    """A zero I is fine while another pair stays active: validation sees the source the write leaves."""
    _controller, call = fresh
    status, reply = _patch(call, {"moderator_profile": "frm2_cold", "moderator_i2": 0.0, "moderator_i3": 0.0})
    assert status == 200, reply
    assert _source(call)["moderator_i2"] == 0.0


# --- /schema publishes types, units and the choices --------------------------------------

def test_schema_publishes_types_units_and_choices(fresh):
    _controller, call = fresh
    status, schema = call("GET", "/schema")
    assert status == 200
    fields = {f["name"]: f for f in schema["fields"]}
    assert set(NINE) <= set(fields)
    assert not {"source_type", "source_dE"} & set(fields)
    assert fields["moderator_mode"]["type"] == "string"
    assert fields["moderator_mode"]["allowed"] == list(moderator.MODES)
    assert fields["moderator_profile"]["type"] == "string"
    assert fields["moderator_profile"]["allowed"] == list(moderator.PROFILES)
    for n in (1, 2, 3):
        assert fields[f"moderator_t{n}_k"]["type"] == "number" and fields[f"moderator_t{n}_k"]["units"] == "K"
        assert fields[f"moderator_i{n}"]["units"] == "n/cm^2/s/sr"
    assert fields["flat_band_half_width_mev"]["units"] == "meV"


# --- the outputs carry the full provenance -----------------------------------------------

def _file_values(folder):
    """scan_parameters.txt as text pairs (a hash can look like a float, so nothing is parsed)."""
    with open(os.path.join(folder, "scan_parameters.txt"), encoding="utf-8") as handle:
        return dict(line.rstrip("\n").split(": ", 1) for line in handle if ": " in line)


def _assert_provenance(written, vals):
    expected = moderator.provenance({key: vals[key] for key in NINE})
    assert set(expected) <= set(written), sorted(set(expected) - set(written))
    for key, value in expected.items():
        assert written[key] == str(value), (key, written[key], value)
    assert expected["source_component"] == "Source_Maxwell_direct"
    assert re.fullmatch(r"[0-9a-f]{12}", expected["source_component_sha256"])


def test_scan_and_point_parameter_files_carry_the_source_provenance(fresh, tmp_path):
    controller, call = fresh
    _patch(call, {"moderator_profile": "ill_hot", "moderator_t2_k": 700.0, "moderator_mode": "flat_band"})
    vals = controller.get_gui_values()

    scan_folder, point_folder = tmp_path / "scan", tmp_path / "point"
    write_parameters_to_file(str(scan_folder), controller.output_parameters(vals))
    snapshot = {"deltaE": 0.5}
    write_parameters_to_file(str(point_folder), controller.point_output_parameters(vals, snapshot, 2, 1000))

    for folder in (scan_folder, point_folder):
        written = _file_values(str(folder))
        _assert_provenance(written, vals)
        assert written["moderator_profile"] == "ill_hot"
        assert written["moderator_profile_modified"] == "True"
        assert written["moderator_mode"] == "flat_band"


def test_a_deterministic_scan_stamps_its_folder_and_result_metadata(fresh):
    _controller, call = fresh
    status, reply = call("POST", "/scan", {
        "api_version": API_VERSION,
        # an API launch starts from the defaults, not the GUI: the source it runs is the one it names
        "parameters": {"scan_command1": "A4 30 31 1", "number_neutrons": 1000,
                       "moderator_profile": "psi_cold", "moderator_i2": 4.0e11},
        "engine": "deterministic", "noiseless": True})
    assert status == 202, reply
    for _ in range(600):
        _status, job = call("GET", "/scan/%s/data" % reply["job_id"])
        if job["state"] in ("done", "failed", "cancelled", "stopped"):
            break
        time.sleep(0.05)
    assert job["state"] == "done", job

    stamp = job["result"]["metadata"]["source"]
    assert stamp["moderator_profile"] == "psi_cold" and stamp["moderator_t1_k"] == 296.2
    assert stamp["moderator_i2"] == 4.0e11 and stamp["moderator_profile_modified"] is True
    assert stamp["source_component"] == "Source_Maxwell_direct"
    assert stamp == moderator.provenance(stamp)                # every key the stamp lists, and no other
    assert "source_component_version" in stamp and "source_component_sha256" in stamp
    assert "background" in job["result"]["metadata"]           # next to the background block

    written = _file_values(job["result"]["output_folder"])     # the scan's own scan_parameters.txt
    assert written["moderator_profile"] == "psi_cold" and written["moderator_i2"] == "400000000000.0"
    assert written["source_component"] == "Source_Maxwell_direct"
    assert written["source_component_sha256"] == stamp["source_component_sha256"]


def test_both_result_paths_stamp_the_source_beside_the_background():
    """The McStas path cannot run in the suite (no McStas): its stamp is read from the source.
    The source is stamped once, at the result both engines share, before the engine split."""
    with open(cm.__file__, encoding="utf-8") as handle:
        text = handle.read()
    background = len(re.findall(r"result\.metadata\['background'\] = ", text))
    stamp = text.index("result.metadata['source'] = launch_state['source']")
    assert background == 2 and text.count("result.metadata['source'] = ") == 1
    assert stamp < text.index("return self._run_scan_deterministic(")


def _raise(_spec):
    raise RuntimeError("no analytic truth in this test")


def test_a_failed_scan_still_carries_the_source_stamp(fresh, monkeypatch):
    """The stamp is made at launch, so a run that fails before its points keeps it."""
    controller, _call = fresh
    monkeypatch.setattr(det, "ground_truth", _raise)
    launch = controller.build_api_launch_state({**SCAN, "moderator_profile": "psi_cold"})
    launch["engine"] = "deterministic"
    controller._compile_launch(launch)
    job = ScanJob(job_id="t-source-failed", source="api", launch_state=launch)

    controller.run_simulation(launch, job=job)

    assert job.state == JobState.FAILED, job.state
    assert job.result.metadata["source"] == moderator.provenance(launch["vals"])


def test_the_stamp_is_the_hash_read_at_launch_not_when_the_run_ends(fresh, monkeypatch):
    """A component edited during a run does not change the hash the run's result records."""
    controller, _call = fresh
    launch = controller.build_api_launch_state(SCAN)
    launch["engine"] = "deterministic"
    controller._compile_launch(launch)
    at_launch = moderator.component_stamp()
    monkeypatch.setattr(moderator, "component_stamp",
                        lambda *args, **kwargs: {**at_launch, "source_component_sha256": "0" * 12})
    job = ScanJob(job_id="t-source-hash", source="api", launch_state=launch)

    controller.run_simulation(launch, job=job)

    assert job.result.metadata["source"]["source_component_sha256"] == at_launch["source_component_sha256"]


# --- the GUI: what is shown is what is saved, restored and sent to the plugin ------------

@pytest.fixture(scope="module")
def in12():
    yield from _controller_for("in12")


def _shown(controller):
    return controller.window.instrument_dock.source_settings()


def _sent_to_the_plugin(controller):
    """The nine values the plugin's scan_config puts on its state for the current GUI."""
    return controller._collect_simulation_launch_state()["scan_config"].source_values()


def test_gui_values_survive_save_and_load_and_equal_what_the_plugin_gets(in12, saved_file):
    dock = in12.window.instrument_dock
    in12.set_default_parameters()
    assert _shown(in12)["moderator_profile"] == in12.descriptor.default_moderator_profile == "ill_vcs_cold"

    dock.set_source_settings({"moderator_profile": "llb_cold", **moderator.profile_values("llb_cold")})
    dock.set_source_settings({"moderator_t2_k": 77.5, "moderator_i3": 2.5e12,
                              "moderator_mode": "flat_band", "flat_band_half_width_mev": 3.25})
    shown = _shown(in12)
    assert _dock_text(in12).endswith("(modified)")
    assert in12.get_gui_values()["moderator_t2_k"] == 77.5
    assert {key: in12.get_gui_values()[key] for key in NINE} == shown == _sent_to_the_plugin(in12)

    in12.save_parameters()
    in12.set_default_parameters()
    assert _shown(in12) != shown                               # the reset really moved them
    in12.load_parameters(keep_current_on_refusal=True)

    assert _shown(in12) == shown
    assert {key: in12.get_gui_values()[key] for key in NINE} == shown == _sent_to_the_plugin(in12)
    assert _dock_text(in12).endswith("(modified)")             # the mark is derived, so it returns too
    with open(saved_file, encoding="utf-8") as handle:
        block = json.load(handle)["in12"]
    assert {key: block[f"{key}_var"] for key in NINE} == shown   # canonical IDs with the file's _var suffix
    assert "source_type_var" not in block and "source_dE_var" not in block
    in12.set_default_parameters()


def test_old_saved_source_keys_are_ignored_with_one_message(in12, saved_file):
    in12.set_default_parameters()
    in12.window.instrument_dock.set_source_settings({"moderator_profile": "psi_cold"})   # not the default

    def old_file(block):
        for key in NINE:
            block.pop(f"{key}_var", None)
        block["source_type_var"], block["source_dE_var"] = "Mono", "7"

    _write_block(in12, saved_file, old_file)
    in12.window.instrument_dock.set_source_settings({"moderator_mode": "flat_band"})
    before = _log(in12)
    in12.load_parameters(keep_current_on_refusal=True)

    shown = _shown(in12)
    default = in12._default_source_values()
    assert shown == default                                    # the instrument's default source, not the old file's
    assert shown["flat_band_half_width_mev"] == 2.0            # the old "7" was not read
    new = _log(in12)[len(before):]
    lines = [line for line in new.splitlines() if "source_type_var" in line or "source_dE_var" in line]
    assert len(lines) == 1, new
    assert "source_type_var and source_dE_var are retired and ignored" in lines[0]
    assert "default source" in lines[0] and "ILL VCS cold" in lines[0]


def test_reset_fills_the_default_profile_in_full_spectrum_with_de_2(in12):
    dock = in12.window.instrument_dock
    dock.set_source_settings({"moderator_mode": "flat_band", "flat_band_half_width_mev": 9.0,
                              "moderator_profile": "ill_hot", **moderator.profile_values("ill_hot")})
    in12.set_default_parameters()
    assert _shown(in12) == {"moderator_mode": "full_spectrum", "moderator_profile": "ill_vcs_cold",
                            **moderator.profile_values("ill_vcs_cold"), "flat_band_half_width_mev": 2.0}
    assert "(modified)" not in _dock_text(in12)


def test_the_preview_follows_the_ei_the_gui_shows(in12):
    in12.set_default_parameters()
    dock = in12.window.instrument_dock
    lines = {line.get_label(): line for line in dock.source_ax.lines}
    assert list(lines["Ei"].get_xdata()) == [14.7, 14.7]       # the default Ei, pushed at start and by Reset
    dock.Ei_edit.setText("20")
    lines = {line.get_label(): line for line in dock.source_ax.lines}
    assert list(lines["Ei"].get_xdata()) == [20.0, 20.0]
    dock.Ei_edit.setText("")
    assert "Ei" not in {line.get_label() for line in dock.source_ax.lines}
    in12.set_default_parameters()


def test_run_is_blocked_with_the_messages_when_the_source_is_invalid(in12, monkeypatch):
    submitted = []
    monkeypatch.setattr(in12, "submit_scan_job", lambda *args: submitted.append(args))
    in12.set_default_parameters()
    in12.window.simulation_dock.scan_command_1_edit.setText("deltaE 0 1 1")
    dock = in12.window.instrument_dock
    dock.set_source_settings({"moderator_i1": 0.0, "moderator_i2": 0.0, "moderator_i3": 0.0})
    before = _log(in12)

    in12.run_simulation_thread()

    assert submitted == []
    assert "Simulation refused: no active pair" in _log(in12)[len(before):]

    dock.set_source_settings({"moderator_profile": "ill_vcs_cold", **moderator.profile_values("ill_vcs_cold"),
                              "moderator_mode": "flat_band", "flat_band_half_width_mev": 0.0})
    before = _log(in12)
    in12.run_simulation_thread()
    assert submitted == []
    assert "flat_band_half_width_mev must be > 0" in _log(in12)[len(before):]
    in12.set_default_parameters()
