"""Focused formatting policy tests without importing McStas GUI dependencies."""
import ast
import math
from pathlib import Path


_module = ast.parse(Path("TAVI_PySide6.py").read_text(encoding="utf-8"))
_function = next(node for node in _module.body if isinstance(node, ast.FunctionDef) and node.name == "format_editable_number")
_namespace = {"math": math}
exec(compile(ast.Module(body=[_function], type_ignores=[]), "TAVI_PySide6.py", "exec"), _namespace)
format_editable_number = _namespace["format_editable_number"]


def test_editable_number_uses_four_places_without_negative_zero():
    assert format_editable_number(1.23456) == "1.2346"
    assert format_editable_number(0.412397068) == "0.4124"
    assert format_editable_number(4.49555034) == "4.4956"
    assert format_editable_number(3.0) == "3"
    assert format_editable_number(-0.00001) == "0"


def test_editable_number_handles_nonfinite_explicitly():
    assert format_editable_number(float("nan")) == "nan"
    assert format_editable_number(float("inf")) == "inf"
    assert format_editable_number(float("-inf")) == "-inf"
    assert format_editable_number(4.1234567, 6) == "4.123457"
    assert format_editable_number(90.0, 6) == "90"


def test_numeric_parameter_loads_route_through_the_shared_formatter():
    source = Path("TAVI_PySide6.py").read_text(encoding="utf-8")
    assert "setText(str(parameters.get(" not in source
    assert source.count("format_editable_number(parameters.get(") >= 20
    assert source.count("format_editable_number(parameters.get(\"lattice_") == 6


def test_linked_energy_handlers_use_formatter_and_tracking_updates():
    source = Path("TAVI_PySide6.py").read_text(encoding="utf-8")
    for name in ("on_Ki_changed", "on_Ei_changed", "on_Kf_changed", "on_Ef_changed"):
        block = source[source.index(f"def {name}"):source.index("\n    def ", source.index(f"def {name}") + 1)]
        assert "format_editable_number(" in block
        assert "_update_tracked_value(" in block


def test_load_normalization_and_api_precision_contract_are_present():
    source = Path("TAVI_PySide6.py").read_text(encoding="utf-8")
    assert "def _normalise_loaded_numbers" in source
    assert "except (TypeError, ValueError):" in source
    assert "if not math.isfinite(number):" in source
    assert "parameters = self._normalise_loaded_numbers(parameters)" in source
    assert 'open("config/parameters.json", "r", encoding="utf-8")' in source
    assert 'return "%.10g" % float(v)' in source


def test_reciprocal_and_angle_updates_track_the_text_they_display():
    source = Path("TAVI_PySide6.py").read_text(encoding="utf-8")
    tracked = source[source.index("def _update_tracked_value"):source.index("\n    def ", source.index("def _update_tracked_value") + 1)]
    assert "displayed_text: str | None = None" in tracked
    assert "text = displayed_text if displayed_text is not None" in tracked
    assert "self._previous_values[field_name] = float(text)" in tracked

    reciprocal = source[source.index("def _apply_reciprocal_state"):source.index("\n    @Slot", source.index("def _apply_reciprocal_state") + 1)]
    assert "format_editable_number(state.qx)" in reciprocal
    assert "qz belongs to the physical point" in reciprocal
    assert "field.setText(text)" in reciprocal

    for name, fields in (
        ("on_mtt_changed", ("'Ki'", "'Ei'", "'fixed_E'", "'deltaE'")),
        ("on_att_changed", ("'Kf'", "'Ef'", "'fixed_E'", "'deltaE'")),
    ):
        start = source.index(f"def {name}")
        block = source[start:source.index("\n    def ", start + 1)]
        for field in fields:
            assert f"_update_tracked_value({field}" in block


def test_reciprocal_snapshot_and_live_paths_are_separate_and_covered():
    source = Path("TAVI_PySide6.py").read_text(encoding="utf-8")
    assert "def request_reciprocal_snapshot" in source
    assert "live_move_requested.connect(self.apply_reciprocal_live_move)" in source
    assert "reciprocal_live_result.connect(reciprocal_dock.set_live_result)" in source
    assert "def _apply_reciprocal_state" in source
    assert "qz belongs to the physical point" in source
    for handler in ("on_K_fixed_changed", "on_lattice_changed", "on_sample_changed", "_update_ub_display"):
        start = source.index(f"def {handler}")
        block = source[start:source.index("\n    def ", start + 1)]
        assert "request_reciprocal_snapshot()" in block


def test_snapshot_request_is_not_lost_inside_a_controller_transaction():
    controller = next(
        node for node in _module.body
        if isinstance(node, ast.ClassDef) and node.name == "TAVIController"
    )
    method = next(
        node for node in controller.body
        if isinstance(node, ast.FunctionDef) and node.name == "request_reciprocal_snapshot"
    )
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "TAVI_PySide6.py", "exec"), namespace)

    class Timer:
        def __init__(self):
            self.intervals = []

        def start(self, interval):
            self.intervals.append(interval)

    class Controller:
        def __init__(self):
            self.updating = True
            self._reciprocal_snapshot_timer = Timer()

    controller = Controller()
    namespace["request_reciprocal_snapshot"](controller)
    assert controller._reciprocal_snapshot_timer.intervals == [0]
