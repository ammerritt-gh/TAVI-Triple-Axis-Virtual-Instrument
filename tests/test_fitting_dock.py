"""Source-scan tests for the Fitting dock.

Pure text scans of ``gui/docks/fitting_dock.py``, ``gui/docks/display_dock.py``
and ``gui/main_window.py`` -- importing them would pull in PySide6 and
matplotlib, which this suite forbids (no GUI in tests, see ``tests/README.md``
and the sibling ``test_goto_controller.py``).

What these guard is the *boundary*, not the widget behaviour:

* the arithmetic stays in ``tavi/scan_fits.py`` -- no second copy of the
  scan-variable -> field mapping, no hand-rolled COM inside a dock;
* the instrument is moved only through ``TAVIController.goto_scan_variable``,
  never by writing widgets directly with ``apply_parameters``;
* the dock reads the displayed scan through the one public accessor
  ``DisplayDock.scan_snapshot()``, so the private plot arrays stay private.

Every scan is anchored on a literal it also asserts, so a rename fails loudly
here instead of silently scanning an empty string.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FITTING_DOCK_PATH = os.path.join(REPO_ROOT, "gui", "docks", "fitting_dock.py")
DISPLAY_DOCK_PATH = os.path.join(REPO_ROOT, "gui", "docks", "display_dock.py")
MAIN_WINDOW_PATH = os.path.join(REPO_ROOT, "gui", "main_window.py")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    assert source.strip(), "empty source scanned: %s" % path
    return source


def _fitting_source():
    return _read(FITTING_DOCK_PATH)


def test_fitting_dock_class_and_object_name():
    source = _fitting_source()
    assert "class FittingDock(BaseDockWidget):" in source
    assert 'self.setObjectName("FittingDock")' in source, (
        "the object name is what the saved layout keys on; it must be "
        "FittingDock"
    )


def test_main_window_registers_the_fitting_dock():
    source = _read(MAIN_WINDOW_PATH)
    assert "from gui.docks.fitting_dock import FittingDock" in source
    # Created in _create_docks and listed in _all_docks (which is built at the
    # end of the same method, so one scan covers both).
    start = source.index("def _create_docks(self):")
    end = source.index("def _connect_dock_signals(self):", start)
    body = source[start:end]
    assert "self.fitting_dock = FittingDock(" in body, (
        "_create_docks must construct the fitting dock"
    )
    assert "self.fitting_dock," in body, (
        "the fitting dock must be listed in _all_docks, or the View menu and "
        "the layout persistence skip it"
    )
    # And placed in the default layout.
    layout_start = source.index("def _setup_dock_layout(self):")
    layout_end = source.index("def _create_menus(self):", layout_start)
    layout_body = source[layout_start:layout_end]
    assert "self.fitting_dock" in layout_body, (
        "the fitting dock must be given a default dock area"
    )


def test_goto_goes_through_the_controller_not_the_widgets():
    """MAINTAINERS: the dock must not write parameter widgets itself. The
    refusal policy, the message-centre entry and the journal record all live in
    ``TAVIController.goto_scan_variable``; bypassing it loses all three."""
    source = _fitting_source()
    assert "goto_scan_variable(" in source
    assert "revert_last_goto(" in source
    assert "can_revert_goto(" in source
    assert "apply_parameters" not in source, (
        "the fitting dock must not call apply_parameters directly; route the "
        "move through controller.goto_scan_variable"
    )


def test_reductions_come_from_scan_fits():
    source = _fitting_source()
    assert "from tavi import scan_fits" in source
    for call in ("scan_fits.com(", "scan_fits.peak_max(", "scan_fits.fit_peak(",
                 "scan_fits.field_for_scan_variable("):
        assert call in source, "the fitting dock must use %s" % call


def test_fitting_dock_does_not_copy_the_field_mapping():
    """MAINTAINERS: the scan-variable -> field table lives in
    ``tavi/scan_fits.py`` only."""
    source = _fitting_source()
    assert "SCAN_VARIABLE_TO_FIELD" not in source, (
        "the fitting dock must look the field up via "
        "scan_fits.field_for_scan_variable, not inline the table"
    )


def test_display_dock_exposes_the_snapshot_accessor():
    source = _read(DISPLAY_DOCK_PATH)
    assert "def scan_snapshot(self):" in source
    for key in ("'mode'", "'variable_name'", "'x'", "'counts'", "'mask'"):
        assert key in source, (
            "scan_snapshot must report %s -- the fitting dock reads it" % key
        )


def test_fitting_dock_reads_the_scan_only_through_the_accessor():
    """MAINTAINERS: no private plot state may be read from here. The display
    dock is free to rename ``_counts``/``_scan_values_1``; ``scan_snapshot()``
    is the contract."""
    source = _fitting_source()
    assert "scan_snapshot()" in source
    for private in ("._counts", "._scan_values", "._measured_mask",
                    "._valid_mask", "._variable_name_1"):
        assert private not in source, (
            "the fitting dock reaches into display-dock private state (%s); "
            "extend scan_snapshot() instead" % private
        )


def test_fit_is_never_triggered_automatically():
    """The fit runs on the operator's Fit press only -- a live scan must not
    refit itself point by point."""
    source = _fitting_source()
    assert "self.fit_button.clicked.connect(self._on_fit_clicked)" in source
    start = source.index("def on_scan_finished(self):")
    end = source.index("def refresh_gating(self", start)
    body = source[start:end]
    assert "fit_peak" not in body and "_on_fit_clicked" not in body, (
        "scan completion must refresh COM/MAX and gating only, never refit"
    )
