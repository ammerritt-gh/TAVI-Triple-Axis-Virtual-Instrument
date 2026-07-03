"""Tests for remembered-instrument-selection persistence helpers.

Only the Qt-free registry helpers are exercised here: importing TAVI_PySide6 or
mcstasscript crashes this interpreter, so the GUI wiring and main() precedence
are covered by manual/integration launch instead.
"""
import json

import pytest

from instruments.registry import load_last_instrument, save_last_instrument


def _path(tmp_path):
    return tmp_path / "instrument_selection.json"


def test_save_then_load_roundtrip(tmp_path):
    path = _path(tmp_path)
    save_last_instrument("puma", config_path=path)
    assert load_last_instrument(config_path=path) == "puma"


def test_save_writes_expected_shape(tmp_path):
    path = _path(tmp_path)
    save_last_instrument("in8", config_path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"last_instrument": "in8"}


def test_save_creates_missing_parent_dir(tmp_path):
    path = tmp_path / "nested" / "config" / "instrument_selection.json"
    save_last_instrument("puma", config_path=path)
    assert load_last_instrument(config_path=path) == "puma"


def test_missing_file_returns_none(tmp_path):
    assert load_last_instrument(config_path=_path(tmp_path)) is None


def test_corrupt_json_warns_and_returns_none(tmp_path, capsys):
    path = _path(tmp_path)
    path.write_text("{not valid json", encoding="utf-8")
    assert load_last_instrument(config_path=path) is None
    captured = capsys.readouterr()
    assert "Warning" in captured.out


def test_non_object_json_warns_and_returns_none(tmp_path, capsys):
    path = _path(tmp_path)
    path.write_text('["puma"]', encoding="utf-8")
    assert load_last_instrument(config_path=path) is None
    assert "Warning" in capsys.readouterr().out


def test_missing_key_returns_none(tmp_path):
    path = _path(tmp_path)
    path.write_text('{"other": "puma"}', encoding="utf-8")
    assert load_last_instrument(config_path=path) is None


def test_non_string_id_returns_none(tmp_path):
    path = _path(tmp_path)
    path.write_text('{"last_instrument": 42}', encoding="utf-8")
    assert load_last_instrument(config_path=path) is None


def test_valid_ids_filters_stale_saved_id(tmp_path):
    path = _path(tmp_path)
    save_last_instrument("removed_instrument", config_path=path)
    # Unknown saved id is ignored (no error) when valid_ids is supplied.
    assert load_last_instrument(valid_ids={"puma", "in8"}, config_path=path) is None
    # A known saved id passes the filter.
    save_last_instrument("puma", config_path=path)
    assert load_last_instrument(valid_ids={"puma", "in8"}, config_path=path) == "puma"


def test_stale_id_filtering_is_silent(tmp_path, capsys):
    path = _path(tmp_path)
    save_last_instrument("gone", config_path=path)
    assert load_last_instrument(valid_ids={"puma"}, config_path=path) is None
    assert "Warning" not in capsys.readouterr().out
