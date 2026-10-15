"""Output folders McStas can receive: short names, the metacharacter refusal, the message.

No McStas and no Qt. The routing of run_tas_point through mcstas_path is tested at the end.
"""
import os
import sys

import pytest

from tavi import mcstas_paths as mp

MULLER = "M\u00fcller_Stra\u00dfe"          # u-umlaut and sharp s: both in cp1252
LODZ = "\u0141\u00f3d\u017a_\u03a9"         # Lodz_Omega: Ł, ź and Ω are outside cp1252, ó is inside


def _no_short_names(monkeypatch):
    monkeypatch.setattr(mp, "_short_path", lambda path: path)


def test_plain_ascii_path_is_unchanged_without_a_windows_call(monkeypatch):
    def no_call(path):
        raise AssertionError(f"short name asked for a plain path: {path}")
    monkeypatch.setattr(mp, "_short_path", no_call)
    plain = os.path.join("C:\\", "Users", "AMM", "plain")
    assert mp.mcstas_path(plain) == plain


def test_spaced_existing_folder_gets_its_short_name(tmp_path, monkeypatch):
    folder = tmp_path / "with space"
    folder.mkdir()
    monkeypatch.setattr(mp, "_short_path", lambda path: "C:\\WITHSP~1")
    assert mp.mcstas_path(str(folder)) == "C:\\WITHSP~1"


def test_missing_point_folder_gets_its_parents_short_name_and_its_leaf(tmp_path, monkeypatch):
    parent = tmp_path / "with space"
    parent.mkdir()
    monkeypatch.setattr(mp, "_short_path", lambda path: "C:\\WITHSP~1")
    assert mp.mcstas_path(str(parent / "scan_0000")) == os.path.join("C:\\WITHSP~1", "scan_0000")


def test_spaced_or_outside_code_page_path_is_none_without_short_names(tmp_path, monkeypatch):
    _no_short_names(monkeypatch)
    spaced = tmp_path / "with space"
    spaced.mkdir()
    assert mp.mcstas_path(str(spaced)) is None
    assert mp.mcstas_path(str(tmp_path / LODZ)) is None


def test_code_page_name_without_space_is_kept(tmp_path, monkeypatch):
    if mp._ansi_encoding() != "cp1252":
        pytest.skip(f"ANSI code page is {mp._ansi_encoding()}, not cp1252; the umlaut case is not checkable here")
    _no_short_names(monkeypatch)
    target = str(tmp_path / MULLER)
    assert mp.mcstas_path(target) == target


@pytest.mark.parametrize("char", ["&", "^", "%"])
def test_metacharacter_refused_without_short_names(tmp_path, monkeypatch, char):
    _no_short_names(monkeypatch)
    folder = tmp_path / f"a{char}b"
    folder.mkdir()
    assert mp.mcstas_path(str(folder)) is None
    assert char in mp.offending_characters(str(folder))
    assert f"the {char} sign" in mp.refusal_message(str(folder))


@pytest.mark.parametrize("char", ["&", "^", "%"])
def test_metacharacter_surviving_a_fake_short_name_is_refused(tmp_path, monkeypatch, char):
    folder = tmp_path / f"a{char}b"
    folder.mkdir()
    monkeypatch.setattr(mp, "_short_path", lambda path: f"C:\\SAVE~1{char}")
    assert mp.mcstas_path(str(folder)) is None
    assert char in mp.offending_characters(str(folder))
    assert f"the {char} sign" in mp.refusal_message(str(folder))


def test_offending_characters_and_message_name_space_and_code_page_characters():
    folder = "D:\\Probe " + LODZ
    assert mp.offending_characters(folder) == ["space", "\u0141", "\u017a", "\u03a9"]
    text = mp.refusal_message(folder)
    assert folder in text
    assert "cannot use a folder path containing spaces and the characters \u0141, \u017a and \u03a9 on drive D:." in text
    assert "or choose a save folder on the C: drive" in text


def test_refusal_on_c_drive_keeps_only_the_rename_advice():
    text = mp.refusal_message("C:\\Probe &x")
    assert "the & sign" in text
    assert "choose a save folder" not in text
    assert "Rename the folder" in text


@pytest.mark.skipif(sys.platform != "win32", reason="8.3 short names are a Windows feature")
def test_real_spaced_folder_gets_a_short_name_naming_the_same_folder(tmp_path):
    folder = tmp_path / "Müller Probe"
    folder.mkdir()
    if mp._short_path(str(folder)) == str(folder):
        pytest.skip("this volume has no 8.3 short names, so the spaced folder is refused, not shortened")
    form = mp.mcstas_path(str(folder))
    assert form is not None and mp.is_mcstas_safe(form)
    assert os.path.samefile(form, folder)
