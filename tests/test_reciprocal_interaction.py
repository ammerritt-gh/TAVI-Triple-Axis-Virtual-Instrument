"""Fast, Qt-free coverage for reciprocal dock interaction maths."""
import math
import itertools
import pytest

from tavi.reciprocal_interaction import LockState, ReciprocalInteractionModel, ReciprocalState
from tavi.reflection_catalog import load_reflections
from tavi.reflection_catalog import plane_filtered_unique, ProjectedReflection


def test_p1_drag_preserves_out_of_plane_component_and_grid_snaps():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1.0, 0.0, 0.42))
    model.begin_drag()
    result = model.drag_p1((1.14, 0.36), snap_grid=0.1)
    assert result.valid
    assert result.state.qz == 0.42
    assert math.isclose(result.state.qx, 1.1)
    assert math.isclose(result.state.qy, 0.4)


def test_locked_delta_e_preserves_energy_difference_while_rotating_triangle():
    model = ReciprocalInteractionModel(
        ReciprocalState(2.66, 2.3, 1.0, 0.0), LockState(delta_e=True)
    )
    model.begin_drag()
    result = model.drag_p1((1.4, 0.0))
    assert result.valid
    assert math.isclose(result.state.delta_e, model.committed.delta_e, rel_tol=1e-10)


@pytest.mark.parametrize("bits", itertools.product((False, True), repeat=4))
def test_every_lock_mask_has_a_safe_result_for_both_handles(bits):
    locks = LockState(*bits)
    initial = ReciprocalState(2.66, 2.3, 1.0, 0.2)
    model = ReciprocalInteractionModel(initial, locks)
    model.begin_drag(); p1 = model.drag_p1((1.1, .3))
    assert isinstance(p1.valid, bool)
    model.begin_drag(); p2 = model.drag_p2((2.0, .5))
    assert isinstance(p2.valid, bool)
    for result in (p1, p2):
        assert math.isfinite(result.state.qz)
        if not result.valid:
            continue
        if locks.ki:
            assert math.isclose(result.state.actual_ki, initial.actual_ki, rel_tol=1e-8)
        if locks.kf:
            assert math.isclose(result.state.actual_kf, initial.actual_kf, rel_tol=1e-8)
        if locks.delta_e:
            assert math.isclose(result.state.delta_e, initial.delta_e, rel_tol=1e-8)
        if locks.q and result is p1:
            assert math.isclose(result.state.q, initial.q, rel_tol=1e-8)


def test_uv_basis_grid_is_in_rlu_not_raw_q():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1., 0., basis_u=(2., 0.), basis_v=(0., 3.)))
    model.begin_drag()
    result = model.drag_p1((.91, 1.63), snap_grid=.5)
    assert result.valid
    # 0.455, 0.543 r.l.u. rounds to (0.5, 0.5), hence (1, 1.5) Å^-1.
    assert math.isclose(result.state.qx, 1.)
    assert math.isclose(result.state.qy, 1.5)


def test_state_retains_real_triangle_endpoints_and_energy_identity():
    state = ReciprocalState(2.66, 2.3, 1.0, 0.2)
    assert math.isclose(math.hypot(state.p2x, state.p2y), state.ki)
    assert math.isclose(math.hypot(state.p2x-state.qx, state.p2y-state.qy), state.kf)
    assert math.isclose(state.delta_e, 2.072 * (state.ki**2-state.kf**2), rel_tol=.01)


def test_stale_external_p2_is_reconstructed_against_new_scalar_state():
    state = ReciprocalState(2.66, 2.3, 1.0, .2, p2x=9., p2y=9.)
    assert math.isclose(state.actual_ki, state.ki, rel_tol=1e-8)
    assert math.isclose(state.actual_kf, state.kf, rel_tol=1e-8)


def test_floating_dock_gives_canvas_the_available_height(qapp):
    from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock
    dock = ReciprocalSpaceDock()
    dock.resize(1100, 750)
    dock.show()
    qapp.processEvents()
    try:
        assert dock.canvas.height() > 500
    finally:
        dock.close()


def test_reflection_snap_beats_grid_snap():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1.0, 0.0))
    model.begin_drag()
    result = model.drag_p1((1.16, 0.04), snap_grid=0.1, reflections=[(1.17, 0.03)], capture=0.1)
    assert result.valid
    assert result.snapped == (1.17, 0.03)


def test_lau_parser_accepts_comments_and_f_squared(tmp_path):
    path = tmp_path / "test.lau"
    path.write_text("# h k l F2\n1 1 1 42\n2 0 0 3\n", encoding="utf-8")
    result = load_reflections(path)
    assert [(item.h, item.k, item.l, item.f_squared) for item in result] == [
        (1.0, 1.0, 1.0, 42.0), (2.0, 0.0, 0.0, 3.0)
    ]


def test_reflection_plane_filter_and_dedup_preserves_first_row():
    rows = [ProjectedReflection(1., 2., 4., "(1,0,0)", .3), ProjectedReflection(1., 2., 9., "(9,9,9)", .3),
            ProjectedReflection(3., 4., 1., "(2,0,0)", .31)]
    assert plane_filtered_unique(rows, .3) == [rows[0]]
