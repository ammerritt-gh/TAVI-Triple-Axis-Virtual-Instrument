"""Cross-scan binary reuse decision helpers (design record §18.5).

The decision logic lives in two static methods on TAVIController so it can be
tested without Qt: `_can_reuse_binary` (may this scan skip the rebuild?) and
`_updated_binary_cache` (what does the cache hold after a scan?). Importing
TAVI_PySide6 needs PySide6 + mcstasscript, so the module skips when either is
unavailable.
"""
import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as controller_module
from instruments.contract import RunExecutionState

FINGERPRINT = "abc123"


def _armed_state(binary_path):
    return RunExecutionState(
        first_backengine_succeeded=True,
        direct_run_ready=True,
        binary_path=str(binary_path),
        binary_cwd=str(binary_path.parent) if hasattr(binary_path, "parent") else None,
    )


def _cache(binary_path, fingerprint=FINGERPRINT):
    return {
        "fingerprint": fingerprint,
        "instrument": object(),
        "execution_state": _armed_state(binary_path),
        "instr_path": None,
    }


def test_reuse_requires_matching_fingerprint_and_existing_binary(tmp_path):
    can_reuse = controller_module.TAVIController._can_reuse_binary
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")

    assert can_reuse(_cache(binary), FINGERPRINT, False)
    assert not can_reuse(_cache(binary), "other-fingerprint", False)
    assert not can_reuse(None, FINGERPRINT, False)

    binary.unlink()
    assert not can_reuse(_cache(binary), FINGERPRINT, False)  # binary gone


def test_diagnostic_mode_never_reuses(tmp_path):
    can_reuse = controller_module.TAVIController._can_reuse_binary
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    assert not can_reuse(_cache(binary), FINGERPRINT, True)


def test_reuse_requires_successful_compile(tmp_path):
    can_reuse = controller_module.TAVIController._can_reuse_binary
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    cache = _cache(binary)
    cache["execution_state"].first_backengine_succeeded = False
    assert not can_reuse(cache, FINGERPRINT, False)


def test_compiling_scan_replaces_cache(tmp_path):
    update = controller_module.TAVIController._updated_binary_cache
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    instr_archive = tmp_path / "PUMA_McScript.instr"
    instr_archive.write_text("DEFINE INSTRUMENT", encoding="utf-8")

    previous = _cache(binary, fingerprint="stale")
    instrument = object()
    state = _armed_state(binary)

    cache = update(previous, False, FINGERPRINT, instrument, state, str(instr_archive))
    assert cache["fingerprint"] == FINGERPRINT
    assert cache["instrument"] is instrument
    assert cache["execution_state"] is state
    assert cache["instr_path"] == str(instr_archive)


def test_reused_scan_keeps_previous_cache(tmp_path):
    update = controller_module.TAVIController._updated_binary_cache
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    previous = _cache(binary)
    cache = update(previous, True, FINGERPRINT, object(), previous["execution_state"], None)
    assert cache is previous


def test_scan_without_compile_keeps_previous_cache(tmp_path):
    """Aborted before the first backengine: the on-disk binary is unchanged."""
    update = controller_module.TAVIController._updated_binary_cache
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    previous = _cache(binary)
    fresh_state = RunExecutionState()
    cache = update(previous, False, "new-fingerprint", object(), fresh_state, None)
    assert cache is previous


def test_missing_instr_archive_recorded_as_none(tmp_path):
    update = controller_module.TAVIController._updated_binary_cache
    binary = tmp_path / "PUMA_McScript.exe"
    binary.write_bytes(b"")
    cache = update(None, False, FINGERPRINT, object(), _armed_state(binary),
                   str(tmp_path / "does_not_exist.instr"))
    assert cache["instr_path"] is None
