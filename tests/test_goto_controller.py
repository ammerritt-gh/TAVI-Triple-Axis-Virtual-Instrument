"""Source-scan tests for the controller's goto/revert methods.

Pure text scans of ``TAVI_PySide6.py`` -- importing the controller would pull
in PySide6/mcstasscript, which this suite forbids (see
``test_controller_is_instrument_agnostic.py`` and ``test_scan_fits.py``).

What these guard is the *boundary*, not the arithmetic: the goto policy must
stay in ``tavi/scan_fits.py`` (Qt-free, unit-tested there) and the controller
must stay a thin adapter onto ``apply_parameters``. The failure this prevents
is a second, drifting copy of the scan-variable -> field mapping growing inside
the controller.

Every scan is anchored on a literal it also asserts, so a rename fails loudly
here instead of silently scanning an empty string.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")


def _controller_source():
    with open(CONTROLLER_PATH, encoding="utf-8") as handle:
        return handle.read()


def _method_body(source, name, next_name):
    """Source of ``def <name>(`` up to ``def <next_name>(``."""
    start_marker = "def %s(" % name
    end_marker = "def %s(" % next_name
    start = source.find(start_marker)
    assert start != -1, "controller has no %s -- the scan anchor broke" % start_marker
    end = source.find(end_marker, start)
    assert end != -1, (
        "could not find %s after %s -- the scan anchor broke" % (end_marker, start_marker)
    )
    body = source[start:end]
    assert body.strip(), "empty method body scanned for %s" % name
    return body


def test_goto_and_revert_methods_exist():
    source = _controller_source()
    for signature in (
        "def goto_scan_variable(self, variable, value, label=\"goto\"):",
        "def revert_last_goto(self):",
        "def can_revert_goto(self):",
    ):
        assert signature in source, "controller is missing: %s" % signature


def test_goto_routes_policy_through_scan_fits_and_apply_parameters():
    body = _method_body(_controller_source(), "goto_scan_variable", "revert_last_goto")
    assert "scan_fits.plan_goto(" in body
    assert "scan_fits.format_goto_message(" in body
    assert "self.apply_parameters(" in body
    # The plan is what decides: its field is used, and the refusal path returns
    # before anything is applied.
    assert "plan.field" in body
    assert "if not plan.ok:" in body
    assert body.index("if not plan.ok:") < body.index("self.apply_parameters("), (
        "the ok check must gate the apply, not follow it"
    )


def test_goto_does_not_hand_roll_the_field_mapping():
    """MAINTAINERS: the scan-variable -> field table lives in
    ``tavi/scan_fits.py`` only. Copying it into the controller is what this
    test exists to stop."""
    source = _controller_source()
    assert "SCAN_VARIABLE_TO_FIELD" not in source, (
        "the scan-variable field map must not be declared or inlined in the "
        "controller; use tavi.scan_fits.plan_goto instead"
    )
    body = _method_body(source, "goto_scan_variable", "revert_last_goto")
    assert "field_for_scan_variable" not in body, (
        "goto_scan_variable must take its field from the GotoPlan, not look it "
        "up itself"
    )


def test_goto_records_a_journal_entry_and_a_revert_snapshot():
    body = _method_body(_controller_source(), "goto_scan_variable", "revert_last_goto")
    assert "self._journal.record(" in body
    assert "self.print_to_message_center(" in body
    assert "self._last_goto" in body


def test_revert_applies_through_apply_parameters_and_clears_its_snapshot():
    body = _method_body(_controller_source(), "revert_last_goto", "can_revert_goto")
    assert "self.apply_parameters(" in body
    assert "self._last_goto = None" in body
    assert "self.print_to_message_center(" in body
    assert "self._journal.record(" in body


def test_busy_check_has_a_single_source_of_truth():
    """The API's PATCH guard and the GUI goto must agree about "busy"."""
    source = _controller_source()
    assert "def _scan_busy(self):" in source
    assert source.count("def _scan_busy(self):") == 1
    api_body = _method_body(source, "_has_active_or_queued", "patch_parameters")
    assert "_scan_busy()" in api_body, (
        "TaviApiBackend._has_active_or_queued should delegate to the "
        "controller's _scan_busy"
    )
    goto_body = _method_body(source, "goto_scan_variable", "revert_last_goto")
    assert "busy=self._scan_busy()" in goto_body, (
        "goto must hand the busy state to plan_goto rather than deciding itself"
    )
    revert_body = _method_body(source, "revert_last_goto", "can_revert_goto")
    assert "self._scan_busy()" in revert_body, "revert must honour the same guard"


def test_last_goto_state_is_initialized_in_the_constructor():
    """Anchored on the surrounding job-queue state block, so the assertion
    cannot be satisfied by an occurrence elsewhere in the file."""
    source = _controller_source()
    start = source.index("self._job_registry = JobRegistry()")
    end = source.index("self._job_worker.start()", start)
    init_block = source[start:end]
    assert "self._last_goto = None" in init_block
