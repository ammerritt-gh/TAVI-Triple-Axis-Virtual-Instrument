"""Controller source-scan tests: "PUMA is not special" (design record §16.11).

Pure text scans of TAVI_PySide6.py -- no imports of the controller (which would
pull in PySide6/mcstasscript). The Phase-1 exit criterion is that nothing in the
controller says "PUMA" except via the registry/plugin.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")


def _controller_source():
    with open(CONTROLLER_PATH, encoding="utf-8") as f:
        return f.read()


def test_no_puma_literal_in_controller():
    """Case-sensitive 'PUMA' must not appear anywhere (code, strings, comments)."""
    source = _controller_source()
    offending = [
        f"line {i}: {line.strip()}"
        for i, line in enumerate(source.splitlines(), 1)
        if "PUMA" in line
    ]
    assert not offending, "controller still mentions PUMA:\n" + "\n".join(offending)


def test_no_direct_puma_import_in_controller():
    assert "PUMA_instrument_definition" not in _controller_source()


def test_controller_routes_through_plugin():
    """Positive assertion: the plugin seam is actually used, not just renamed away."""
    source = _controller_source()
    for needle in (
        "self.instrument.build(",
        "self.instrument.compute_snapshot(",
        "self.instrument.run_point(",
        "self.instrument.scan_config(",
        "self.instrument.default_state()",
        "self.instrument.crystal_info(",
        "self.instrument.id",
    ):
        assert needle in source, f"expected controller to use {needle!r}"
