"""Executed feasibility records only points whose counts were stored."""
import inspect

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

import TAVI_PySide6 as controller_module
from tavi.scan_jobs import ScanResult


def _result(*, two_dimensional=False):
    return ScanResult(
        mode="2D" if two_dimensional else "1D",
        variable_1="H", variable_2="K" if two_dimensional else None,
        scan_values_1=[0.0, 1.0, 2.0],
        scan_values_2=[0.0, 1.0] if two_dimensional else None,
        valid_mask_1=[True, True, True], valid_mask_2d=None,
        counts=None, counts_grid=None,
        planned_feasible_mask=[True] * (6 if two_dimensional else 3),
        executed_feasible_mask=[False] * (6 if two_dimensional else 3),
    )


def test_successful_1d_points_preserve_failed_and_unprocessed_indices():
    result = _result()
    mark = controller_module.TAVIController._mark_executed_result_point

    mark(result, is_2d_scan=False, is_single_point_scan=False,
         idx_1d=0, idx_x=-1, idx_y=-1)
    # Index 1 represents a failed point; index 2 is a cancelled/unprocessed tail.
    assert result.executed_feasible_mask == [True, False, False]


def test_2d_points_use_original_row_major_index():
    result = _result(two_dimensional=True)
    mark = controller_module.TAVIController._mark_executed_result_point

    mark(result, is_2d_scan=True, is_single_point_scan=False,
         idx_1d=-1, idx_x=2, idx_y=1)
    assert result.executed_feasible_mask == [False, False, False, False, False, True]


def test_single_point_maps_to_index_zero():
    result = _result()
    mark = controller_module.TAVIController._mark_executed_result_point
    mark(result, is_2d_scan=False, is_single_point_scan=True,
         idx_1d=-1, idx_x=-1, idx_y=-1)
    assert result.executed_feasible_mask == [True, False, False]


def test_both_engines_mark_only_after_storing_counts():
    source = inspect.getsource(controller_module.TAVIController)
    assert source.count("self._mark_executed_result_point(") == 2
    positions = []
    start = 0
    while True:
        position = source.find("self._mark_executed_result_point(", start)
        if position < 0:
            break
        positions.append(position)
        start = position + 1
    for position in positions:
        preceding_storage_block = source[max(0, position - 900):position]
        assert "res.counts" in preceding_storage_block
