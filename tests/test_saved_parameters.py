"""Saved parameters, version 5: a file this TAVI cannot restore whole is set
aside and changes nothing else.

Both entry points: start-up (the defaults load) and File > Load Parameters
mid-session (the session stays exactly as it is). Refused: another file
version (a version-4 file included: its A2/A4 count the old way), an unreadable
saved peak, an exercise code with motor-zero errors or from the retired Misalignment
dock, and an exercise the
instrument, sample, crystals, energy and described mount IN THE FILE cannot
observe -- judged on the file's values, never the live ones.
"""
import base64
import glob
import json
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as cm  # noqa: E402
from tavi.local_state import config_path  # noqa: E402
from tavi.tas_geometry import mccode_rotation_matrix  # noqa: E402
from tavi.ub_matrix import MOTOR_ZERO_REFUSAL, encode_training  # noqa: E402

from test_training_exercise import _controller_for, _same  # noqa: E402

GOOD_CODE = encode_training(mccode_rotation_matrix(3.0, 5.0, -2.0), 0.0, 0.0)


@pytest.fixture(scope="module")
def in8():
    yield from _controller_for("in8")


@pytest.fixture
def saved_file():
    """The shared config dir's parameters.json, with no file and no backup
    before and after; whatever was there is put back."""
    path = os.fspath(config_path("parameters.json"))

    def clear():
        for name in glob.glob(path + "*"):
            os.remove(name)

    original = open(path, "rb").read() if os.path.exists(path) else None
    clear()
    try:
        yield path
    finally:
        clear()
        if original is not None:
            with open(path, "wb") as fh:
                fh.write(original)


def _write_block(ctrl, path, edit):
    """Save ``ctrl``'s state, let ``edit`` change its block, write the file
    back; return the bytes written."""
    ctrl.save_parameters()
    with open(path, "r", encoding="utf-8") as fh:
        document = json.load(fh)
    edit(document[ctrl.instrument.id])
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh)
    return open(path, "rb").read()


def _state(ctrl):
    """Everything a restore could touch, comparable."""
    return (json.dumps(ctrl.get_gui_values(), sort_keys=True, default=str),
            ctrl.U_described.copy(), ctrl.R_hidden.copy(), ctrl.instrument_state.U_true.copy(),
            ctrl.ub_matrix.UB.copy(), ctrl._exercise, json.dumps(ctrl.instrument_state.plane_lock),
            json.dumps(ctrl.mount_plane))


def _log(ctrl):
    return ctrl.window.output_dock.message_text.toPlainText()


def _fresh_start(instrument_id="in8"):
    """A controller built while parameters.json is on disk: the start-up path."""
    generator = _controller_for(instrument_id)
    return generator, next(generator)


# --- the whole document: flat files, other instruments' blocks -------------------------

FLAT_LEGACY = {"monocris_var": "pg002", "sample_rotation_deg": "33.3", "sample_lower_arc_deg": "1.5"}


def test_a_flat_legacy_file_is_refused_at_start(in8, saved_file):
    """Pre-namespacing fields at the top level and no instrument block: set aside,
    not read as defaults that leave the file in place."""
    in8.set_default_parameters()
    with open(saved_file, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(FLAT_LEGACY, fh)
    written = open(saved_file, "rb").read()

    generator, fresh = _fresh_start()
    try:
        assert not os.path.exists(saved_file)
        with open(saved_file + ".bak", "rb") as fh:
            assert fh.read() == written
        assert ("Saved parameters not restored: it was saved by another TAVI (file version "
                f"none; this one reads 5). The file was renamed {saved_file}.bak. "
                "Defaults loaded.") in _log(fresh), _log(fresh)
    finally:
        generator.close()
    in8.set_default_parameters()


def test_a_flat_legacy_file_is_refused_mid_session_and_changes_nothing(in8, saved_file):
    in8.set_default_parameters()
    in8.window.instrument_dock.omega_edit.setText("41.5")
    in8.on_omega_changed()
    with open(saved_file, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(FLAT_LEGACY, fh)
    written = open(saved_file, "rb").read()
    before = _state(in8)

    in8.window.load_parameters_action.trigger()

    assert _same(before, _state(in8))
    assert not os.path.exists(saved_file)
    with open(saved_file + ".bak", "rb") as fh:
        assert fh.read() == written
    assert ("Saved parameters not restored: it was saved by another TAVI (file version "
            f"none; this one reads 5). The file was renamed {saved_file}.bak. "
            "The current settings are unchanged.") in _log(in8), _log(in8)
    in8.set_default_parameters()


def test_a_block_of_another_version_for_another_instrument_refuses_the_whole_file(
        in8, saved_file):
    """The live block is current, but puma's is version 3: the file is refused
    whole, so a later start on puma cannot rename this block away with it."""
    in8.set_default_parameters()
    _write_block(in8, saved_file, lambda block: None)
    with open(saved_file, "r", encoding="utf-8") as fh:
        document = json.load(fh)
    document["puma"] = {"_schema": 3, "sample_rotation_deg": "5"}
    with open(saved_file, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh)
    written = open(saved_file, "rb").read()
    in8.window.instrument_dock.omega_edit.setText("33.3")
    in8.on_omega_changed()
    before = _state(in8)

    in8.window.load_parameters_action.trigger()

    assert _same(before, _state(in8))
    assert not os.path.exists(saved_file)
    with open(saved_file + ".bak", "rb") as fh:
        assert fh.read() == written
    assert "file version 3; this one reads 5" in _log(in8), _log(in8)
    in8.set_default_parameters()


def test_a_valid_file_without_this_instruments_block_leaves_the_session_alone(in8, saved_file):
    in8.set_default_parameters()
    with open(saved_file, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"puma": {"_schema": 5}}, fh)
    in8.window.instrument_dock.omega_edit.setText("41.5")
    in8.on_omega_changed()
    before = _state(in8)

    in8.window.load_parameters_action.trigger()

    assert _same(before, _state(in8))
    assert os.path.exists(saved_file) and not os.path.exists(saved_file + ".bak")
    assert "holds no settings for 'in8'" in _log(in8), _log(in8)
    in8.set_default_parameters()


@pytest.mark.parametrize("entry", ["start-up", "mid-session"])
def test_a_truncated_file_is_set_aside_at_both_entry_points(in8, saved_file, entry):
    """A file cut off mid-write is refused like any other: it cannot stop TAVI
    starting, nor make File > Load Parameters raise."""
    in8.set_default_parameters()
    in8.window.instrument_dock.omega_edit.setText("41.5")
    in8.on_omega_changed()
    with open(saved_file, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"in8": ')
    written = open(saved_file, "rb").read()

    if entry == "start-up":
        generator, fresh = _fresh_start()
        try:
            assert fresh.window.instrument_dock.omega_edit.text() != "41.5"
            assert fresh._exercise is None
            log = _log(fresh)
            assert "Defaults loaded." in log, log
        finally:
            generator.close()
    else:
        before = _state(in8)
        in8.window.load_parameters_action.trigger()
        assert _same(before, _state(in8))
        log = _log(in8)
        assert "The current settings are unchanged." in log, log
    assert not os.path.exists(saved_file)
    with open(saved_file + ".bak", "rb") as fh:
        assert fh.read() == written
    assert "Saved parameters not restored: it is not readable JSON" in log, log
    in8.set_default_parameters()


# --- another version: refused whole ----------------------------------------------------

@pytest.mark.parametrize("version", [3, 4, 6, None], ids=["v3", "v4", "v6", "no-version"])
def test_a_file_of_another_version_is_set_aside_and_the_defaults_load_at_start(
        in8, saved_file, version):
    in8.set_default_parameters()
    in8.window.instrument_dock.omega_edit.setText("33.3")

    def edit(block):
        if version is None:
            del block["_schema"]
        else:
            block["_schema"] = version
        block["kappa_var"] = "0.5"                         # what a v3 block carried

    written = _write_block(in8, saved_file, edit)

    generator, fresh = _fresh_start()
    try:
        assert not os.path.exists(saved_file)
        with open(saved_file + ".bak", "rb") as fh:
            assert fh.read() == written
        log = _log(fresh)
        shown = "none" if version is None else version
        assert (f"Saved parameters not restored: it was saved by another TAVI (file version "
                f"{shown}; this one reads 5). The file was renamed {saved_file}.bak. "
                "Defaults loaded.") in log, log
        assert fresh.window.instrument_dock.omega_edit.text() != "33.3"
        assert fresh._exercise is None
    finally:
        generator.close()
    in8.set_default_parameters()


CANONICAL_KEYS = {
    "mono_two_theta_deg", "sample_two_theta_deg", "sample_rotation_deg", "analyzer_two_theta_deg",
    "sample_lower_arc_deg", "sample_upper_arc_deg", "incident_wavevector_inv_angstrom",
    "final_wavevector_inv_angstrom", "incident_energy_mev", "final_energy_mev",
    "mono_horizontal_radius_m", "mono_vertical_radius_m", "analyzer_horizontal_radius_m",
    "analyzer_vertical_radius_m", "q_instrument_x_inv_angstrom", "q_instrument_y_inv_angstrom",
    "q_instrument_z_inv_angstrom", "h", "k", "l", "energy_transfer_mev",
    "lattice_a_angstrom", "lattice_b_angstrom", "lattice_c_angstrom",
    "lattice_alpha_deg", "lattice_beta_deg", "lattice_gamma_deg",
}


def test_a_saved_block_is_keyed_by_canonical_ids_and_reads_nothing_else(in8, saved_file):
    """Version 5 saves every physical quantity under its registry ID and a load reads
    those: an old *_var key beside them is not a value, so a file that mixes the two
    cannot half-restore."""
    from tavi.quantities import by_id

    in8.set_default_parameters()
    in8.save_parameters()
    with open(saved_file, "r", encoding="utf-8") as fh:
        block = json.load(fh)["in8"]
    assert block["_schema"] == 5
    assert CANONICAL_KEYS <= set(block)
    assert all(by_id(key) for key in CANONICAL_KEYS)               # each is a registry ID
    quantity_vars = {key for key in block if key.endswith("_var")
                     and key[:-4] in {"mtt", "stt", "omega", "sgl", "sgu", "att", "Ki", "Kf", "Ei",
                                      "Ef", "rhm", "rvm", "rha", "rva", "qx", "qy", "qz", "H", "K",
                                      "L", "deltaE", "lattice_a", "lattice_b", "lattice_c",
                                      "lattice_alpha", "lattice_beta", "lattice_gamma"}}
    assert not quantity_vars, quantity_vars

    def edit(saved):
        saved["lattice_a_angstrom"] = "4.321"
        saved["mono_horizontal_radius_m"] = "9.5"
        saved["analyzer_vertical_radius_m"] = "1.25"
        saved["lattice_b_var"] = "9.99"                             # an old key: ignored

    _write_block(in8, saved_file, edit)
    in8.window.sample_dock.lattice_b_edit.setText("4.05")
    in8.load_parameters(keep_current_on_refusal=True)
    assert float(in8.window.sample_dock.lattice_a_edit.text()) == pytest.approx(4.321)
    assert float(in8.window.sample_dock.lattice_b_edit.text()) == pytest.approx(4.05)
    assert float(in8.window.instrument_dock.rhm_edit.text()) == pytest.approx(9.5)
    assert float(in8.window.instrument_dock.rva_edit.text()) == pytest.approx(1.25)
    in8.set_default_parameters()


def test_a_refused_file_changes_nothing_when_loaded_mid_session(in8, saved_file):
    in8.set_default_parameters()
    in8._set_true_mount(U_described=mccode_rotation_matrix(0.0, 12.0, 0.0))
    in8._reset_ub_to_described()
    in8.window.instrument_dock.omega_edit.setText("41.5")
    in8.on_omega_changed()
    in8.window.scattering_dock.deltaE_edit.setText("1.5")

    written = _write_block(in8, saved_file, lambda block: block.update(_schema=3))
    before = _state(in8)

    in8.window.load_parameters_action.trigger()           # File > Load Parameters

    assert _same(before, _state(in8))
    assert in8.window.instrument_dock.omega_edit.text() == "41.5"
    assert not os.path.exists(saved_file)
    with open(saved_file + ".bak", "rb") as fh:
        assert fh.read() == written
    log = _log(in8)
    assert ("Saved parameters not restored: it was saved by another TAVI (file version 3; "
            f"this one reads 5). The file was renamed {saved_file}.bak. "
            "The current settings are unchanged.") in log, log
    in8.set_default_parameters()


def test_a_backup_is_never_overwritten(in8, saved_file):
    in8.set_default_parameters()
    for turn in range(3):
        in8.window.instrument_dock.omega_edit.setText(str(30 + turn))
        _write_block(in8, saved_file, lambda block: block.update(_schema=3))
        in8.load_parameters(keep_current_on_refusal=True)
    names = sorted(os.path.basename(n) for n in glob.glob(saved_file + "*"))
    assert names == ["parameters.json.bak", "parameters.json.bak2", "parameters.json.bak3"]
    omegas = []
    for name in ("", "2", "3"):
        with open(f"{saved_file}.bak{name}", "r", encoding="utf-8") as fh:
            omegas.append(float(json.load(fh)["in8"]["sample_rotation_deg"]))
    assert omegas == [30.0, 31.0, 32.0]
    in8.set_default_parameters()


# --- the file's own contents: peaks and the exercise -------------------------------------

def _file_with_peak(ctrl, path, stage):
    """A v5 file whose first saved peak carries ``stage`` as its stage record."""
    from tavi.ub_matrix import ObservedPeak

    ctrl.set_default_parameters()
    peak = ObservedPeak(hkl=(2, 0, 0), angles=(35.0, 0.0, 71.0), ki=2.66, kf=2.66).to_dict()
    peak["stage"] = stage
    ctrl.ub_matrix.peaks = []

    def edit(block):
        block["ub_matrix_state"]["peaks"] = [peak]

    return _write_block(ctrl, path, edit)


@pytest.mark.parametrize("readable", [True, False], ids=["readable-stage", "no-angles"])
def test_a_saved_peak_with_an_unreadable_stage_record_refuses_the_file(
        in8, saved_file, readable):
    record = {"axes": [[ax.name, list(ax.axis)] for ax in in8.instrument_state.goniometer],
              "angles": {"A3": 35.0, "sgl": 0.0, "sgu": 0.0}, "ki": 2.66, "kf": 2.66, "sense": 1}
    if not readable:
        del record["angles"]
    _file_with_peak(in8, saved_file, record)
    in8.window.instrument_dock.omega_edit.setText("33.3")
    in8.on_omega_changed()
    before = _state(in8)

    in8.window.load_parameters_action.trigger()

    log = _log(in8)
    if readable:
        assert os.path.exists(saved_file) and not os.path.exists(saved_file + ".bak")
        assert [p.hkl for p in in8.ub_matrix.peaks] == [(2, 0, 0)]
    else:
        assert _same(before, _state(in8))
        assert "Saved parameters not restored: saved peak 1 cannot be read" in log
        assert os.path.exists(saved_file + ".bak")
    in8.set_default_parameters()


def _exercise_file(ctrl, path, **block_edits):
    ctrl.set_default_parameters()
    return _write_block(ctrl, path, lambda block: block.update(block_edits))


RETIRED_DOCK_CODE = base64.urlsafe_b64encode(bytes(
    b ^ b"TAVI_ALIGN_2026"[i % 15] for i, b in enumerate(struct.pack("<ff", 1.5, -0.75)))
).decode("ascii")


@pytest.mark.parametrize("edits, words", [
    ({"ub_training_hash": encode_training(mccode_rotation_matrix(3.0, 5.0, -2.0), 1.0, 0.0)},
     MOTOR_ZERO_REFUSAL),
    ({"ub_training_hash": RETIRED_DOCK_CODE}, "no longer simulated"),
    ({"ub_training_hash": "garbage"}, "cannot be read"),
], ids=["zero-errors", "retired-dock-code", "garbage"])
def test_a_refused_exercise_in_a_file_applies_nothing_at_start_or_mid_session(
        in8, saved_file, edits, words):
    in8.set_default_parameters()
    _exercise_file(in8, saved_file, **edits)
    before = _state(in8)

    in8.window.load_parameters_action.trigger()                    # mid-session
    assert _same(before, _state(in8)) and in8._exercise is None
    assert words in _log(in8)
    assert os.path.exists(saved_file + ".bak")
    os.replace(saved_file + ".bak", saved_file)                     # the same file again

    generator, fresh = _fresh_start()                              # start-up
    try:
        assert fresh._exercise is None and np.array_equal(fresh.R_hidden, np.eye(3))
        assert words in _log(fresh) and "Defaults loaded." in _log(fresh)
        assert os.path.exists(saved_file + ".bak") and not os.path.exists(saved_file)
    finally:
        generator.close()
    in8.set_default_parameters()


def test_the_exercise_is_judged_on_the_files_sample_not_the_live_one(in8, saved_file):
    """A file whose sample has no crystal refuses an exercise the live session
    (Al) could observe; a file on Al restores it over a live session with no
    sample."""
    in8.set_default_parameters()
    # The file names "none" as its sample; the live session is on Al.
    _exercise_file(in8, saved_file, ub_training_hash=GOOD_CODE,
                   current_sample_settings={"sample_key": "none"})
    assert in8.window.sample_dock.get_selected_sample_key() == "Al_bragg"
    before = _state(in8)
    in8.load_parameters(keep_current_on_refusal=True)
    assert _same(before, _state(in8)) and in8._exercise is None
    assert ("its saved exercise cannot be observed here: no sample with a crystal is "
            "selected") in _log(in8)
    os.remove(saved_file + ".bak")

    # The file names Al; the live session has no sample.
    _exercise_file(in8, saved_file, ub_training_hash=GOOD_CODE,
                   current_sample_settings={"sample_key": "Al_bragg"})
    assert in8.window.sample_dock.set_sample_by_key(None)
    in8.load_parameters(keep_current_on_refusal=True)
    assert in8._exercise == GOOD_CODE
    assert in8.window.sample_dock.get_selected_sample_key() == "Al_bragg"
    assert os.path.exists(saved_file) and not os.path.exists(saved_file + ".bak")
    in8.set_default_parameters()


@pytest.mark.parametrize("change", ["fixed energy", "sample"])
def test_an_unobservable_exercise_stops_the_save_and_keeps_the_file(
        in8, saved_file, change):
    """Every Run saves. Once the fixed energy (or the sample) can no longer
    observe the loaded exercise, the file on disk stays byte-identical to the
    last consistent save, so it restores with the exercise and its fitted UB
    together. One line says why, once; observing it again resumes saving."""
    in8.set_default_parameters()
    in8._set_true_mount(U_described=mccode_rotation_matrix(0.0, 12.0, 0.0))
    in8._reset_ub_to_described()
    in8._install_exercise(GOOD_CODE)
    in8.save_parameters()
    with open(saved_file, "rb") as fh:
        consistent = fh.read()
    expected = _state(in8)

    log_before = len(_log(in8))
    if change == "fixed energy":
        in8.window.scattering_dock.fixed_E_edit.setText("4.0")   # closes no Al reflection
    else:
        assert in8.window.sample_dock.set_sample_by_key(None)     # "No sample"
    in8.save_parameters()
    in8.save_parameters()                                       # the next Run
    with open(saved_file, "rb") as fh:
        on_disk = fh.read()
    assert on_disk == consistent
    assert in8._exercise == GOOD_CODE
    assert _log(in8)[log_before:].count("Parameters not saved") == 1, _log(in8)
    assert ("the loaded exercise cannot be observed with the current sample, fixed energy "
            "or crystals") in _log(in8)

    in8.set_default_parameters()
    in8.window.load_parameters_action.trigger()                 # the file is restored whole
    assert _same(expected, _state(in8))
    assert os.path.exists(saved_file) and not os.path.exists(saved_file + ".bak")

    if change == "fixed energy":                                # observable again
        in8.window.scattering_dock.fixed_E_edit.setText("14.7")
    else:
        assert in8.window.sample_dock.set_sample_by_key("Al_bragg")
    log_before = len(_log(in8))
    in8.save_parameters()
    assert "Parameters saved successfully" in _log(in8)[log_before:], _log(in8)
    with open(saved_file, "r", encoding="utf-8") as fh:
        assert json.load(fh)["in8"]["ub_training_hash"] == GOOD_CODE
    in8.set_default_parameters()


def test_an_observable_exercise_is_written_and_restored(in8, saved_file):
    in8.set_default_parameters()
    in8._install_exercise(GOOD_CODE)
    in8.save_parameters()
    with open(saved_file, "r", encoding="utf-8") as fh:
        assert json.load(fh)["in8"]["ub_training_hash"] == GOOD_CODE
    in8.set_default_parameters()
    in8.load_parameters(keep_current_on_refusal=True)
    assert in8._exercise == GOOD_CODE
    in8.set_default_parameters()


def test_a_valid_file_loads_as_before(in8, saved_file):
    in8.set_default_parameters()
    in8._set_true_mount(U_described=mccode_rotation_matrix(0.0, 12.0, 0.0))
    in8._reset_ub_to_described()
    in8._install_exercise(GOOD_CODE)
    in8.save_parameters()
    expected = _state(in8)
    in8.set_default_parameters()
    assert in8._exercise is None

    in8.window.load_parameters_action.trigger()

    assert _same(expected, _state(in8))
    assert os.path.exists(saved_file) and not os.path.exists(saved_file + ".bak")
    in8.set_default_parameters()


@pytest.mark.parametrize("instrument_id", ["puma", "in8", "in12", "panda"])
def test_two_slit_gaps_are_saved_under_their_canonical_keys_and_restored(instrument_id, saved_file):
    """Each gap is saved under its own API name, with no slits_mm block, and a fresh start restores it."""
    generator, ctrl = _fresh_start(instrument_id)
    try:
        dock = ctrl.window.instrument_dock
        first, second = ctrl.descriptor.slits[:2]
        dock.slit_widgets[first.id]["width"].setText("33.5")
        dock.slit_widgets[second.id]["width"].setText("21.5")
        expected = dock.slit_values_mm()
        ctrl.save_parameters()
        with open(saved_file, "r", encoding="utf-8") as fh:
            block = json.load(fh)[instrument_id]
    finally:
        generator.close()
    assert "slits_mm" not in block
    assert block[f"slit.{first.stable_id}.horizontal_gap_mm"] == 33.5
    assert block[f"slit.{second.stable_id}.horizontal_gap_mm"] == 21.5
    generator, restored = _fresh_start(instrument_id)
    try:
        assert restored.window.instrument_dock.slit_values_mm() == expected
    finally:
        generator.close()
