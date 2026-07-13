"""Fast, Qt-free coverage for reciprocal dock interaction maths."""
import math
import itertools
import pytest

from tavi.reciprocal_interaction import (LiveReciprocalResult, LockState, ReachOverlay,
                                         ReciprocalInteractionModel,
                                         ReciprocalState, tiny_zero, format_small,
                                         triangle_can_close)
from tavi.reflection_catalog import load_reflections
from tavi.reflection_catalog import plane_filtered_unique, ProjectedReflection, primitive_miller


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


def test_external_snapshot_cancels_preview_and_tiny_formatting_helpers():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1., 0.))
    model.begin_drag(); model.drag_p1((1.2, .2))
    external = ReciprocalState(2.66, 2.3, .8, .1)
    model.cancel_external_update(external)
    assert model.preview == external and model.committed == external
    assert tiny_zero(1e-12) == 0.0
    assert primitive_miller(4, -2, 0) == (2, -1, 0)
    assert primitive_miller(.5, 2, -2) == (1, 4, -4)
    assert primitive_miller(1, math.sqrt(2), 0) == (0.707107, 1.0, 0.0)
    assert format_small(1e-12) == "0"
    assert format_small(-1e-14) == "0"
    assert format_small(1.00000000001) == "1"


def test_live_ack_updates_visible_state_without_changing_drag_pivot():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1., 0.))
    model.begin_drag()
    pivot = model._drag_start
    local = model.drag_p1((1.2, .2)).state
    normalised = ReciprocalState(local.ki, local.kf, .4124, .2, local.qz,
                                 local.p2x, local.p2y)
    model.accept_live_update(normalised)
    assert model.committed == normalised
    assert model.preview == normalised
    assert model._drag_start == pivot
    assert LiveReciprocalResult(normalised, False, "limit").applied


def test_live_ack_does_not_replace_full_precision_active_preview():
    model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1., 0.))
    model.begin_drag("p1")
    local = model.drag_p1((1.23456789, .2)).state
    acknowledged = ReciprocalState(local.ki, local.kf, 1.2346, .2, local.qz,
                                   local.p2x, local.p2y)
    model.accept_live_update(acknowledged)
    assert model.committed == acknowledged
    assert model.preview == local


def test_numeric_triangle_closure_rejects_impossible_q():
    assert triangle_can_close(2.66, 2.66, 5.32)
    assert not triangle_can_close(2.66, 2.66, 10.0)
    assert not triangle_can_close(1.0, 3.0, 1.5)


def test_exact_gesture_mode_lock_tables():
    p1 = {
        "0000": "free_q", "1000": "free_q", "0010": "q_circle", "1010": "q_circle",
        "0001": "delta_e_annulus", "0101": "delta_e_annulus", "1001": "delta_e_annulus",
        "0100": "kf_circle", "1100": "kf_circle", "1101": "kf_circle",
    }
    p2 = {
        "0000": "free_p2", "0010": "free_p2", "1000": "ki_circle", "1010": "ki_circle",
        "0100": "kf_circle", "0110": "kf_circle", "0001": "delta_e_line", "0011": "delta_e_line",
    }
    for bits in itertools.product((False, True), repeat=4):
        mask = "".join("1" if bit else "0" for bit in bits)
        model = ReciprocalInteractionModel(ReciprocalState(2.66, 2.3, 1., .2), LockState(*bits))
        assert model.gesture_mode("p1").kind == p1.get(mask, "rigid_rotation")
        assert model.gesture_mode("p2").kind == p2.get(mask, "rigid_rotation")


def test_delta_e_annulus_preserves_both_arm_lengths_and_branch():
    start = ReciprocalState(2.66, 2.3, 1., .2)
    model = ReciprocalInteractionModel(start, LockState(delta_e=True))
    model.begin_drag("p1")
    result = model.drag_p1((20., 0.))
    assert result.valid
    assert math.isclose(result.state.actual_ki, start.actual_ki, rel_tol=1e-9)
    assert math.isclose(result.state.actual_kf, start.actual_kf, rel_tol=1e-9)
    assert result.state.p2x * result.state.qy - result.state.p2y * result.state.qx > 0


def test_delta_e_p2_line_keeps_energy_identity_exactly():
    start = ReciprocalState(2.66, 2.3, 1., .2)
    model = ReciprocalInteractionModel(start, LockState(delta_e=True))
    model.begin_drag("p2")
    result = model.drag_p2((.4, 1.8))
    assert result.valid
    assert math.isclose(result.state.delta_e, start.delta_e, rel_tol=1e-10)
    assert model.gesture_mode("p2").line_direction is not None


def test_state_reconstruction_uses_snapshot_scattering_sense():
    state = ReciprocalState(2.66, 2.3, 1., 0., p2x=None, p2y=None, sense=-1)
    assert state.p2x * state.qy - state.p2y * state.qx < 0


def test_canvas_release_accepts_or_rolls_back_synchronous_snapshot(qapp):
    from gui.docks.reciprocal_space_dock import ReciprocalCanvas

    def snapshot(state):
        return {
            "ki": state.actual_ki, "kf": state.actual_kf,
            "qx": state.qx, "qy": state.qy, "qz": state.qz,
            "p2": (state.p2x, state.p2y),
            "basis_u": state.basis_u, "basis_v": state.basis_v,
        }

    canvas = ReciprocalCanvas()
    start = canvas.model.committed
    canvas.model.locks = LockState(kf=True)
    canvas.model.begin_drag()
    accepted = canvas.model.drag_p1((1.5, .4)).state
    canvas._drag = "p1"
    canvas.move_committed.connect(lambda state: canvas.set_snapshot(snapshot(state)))
    canvas.mouseReleaseEvent(None)
    assert canvas.model.committed == accepted
    canvas.model.begin_drag()
    assert canvas.model.preview == accepted

    canvas.move_committed.disconnect()
    canvas.model.begin_drag()
    canvas.model.drag_p1((1.8, .2))
    canvas._drag = "p1"
    canvas.move_committed.connect(lambda _state: canvas.set_snapshot(snapshot(accepted)))
    canvas.mouseReleaseEvent(None)
    assert canvas.model.committed == accepted
    assert canvas.model.preview == accepted


def test_canvas_coalesces_live_requests_and_flushes_final_preview(qapp):
    from gui.docks.reciprocal_space_dock import ReciprocalCanvas

    canvas = ReciprocalCanvas()
    received = []
    canvas.live_preview_requested.connect(received.append)
    first = ReciprocalState(2.66, 2.3, 1.1, .1)
    last = ReciprocalState(2.66, 2.3, 1.2, .2)
    canvas._queue_live_preview(first)
    canvas._queue_live_preview(last)
    canvas._flush_live_preview(force=True)
    assert received == [last]


def test_external_snapshot_discards_queued_live_preview(qapp):
    from gui.docks.reciprocal_space_dock import ReciprocalCanvas

    canvas = ReciprocalCanvas()
    emitted = []
    canvas.live_preview_requested.connect(emitted.append)
    canvas._queue_live_preview(ReciprocalState(2.66, 2.3, 1.3, .1))
    external = ReciprocalState(2.66, 2.3, .8, .1)
    canvas.set_snapshot({
        "ki": external.ki, "kf": external.kf, "qx": external.qx,
        "qy": external.qy, "qz": external.qz,
        "p2": (external.p2x, external.p2y),
        "basis_u": external.basis_u, "basis_v": external.basis_v,
    })
    canvas._flush_live_preview(force=True)
    assert emitted == []
    assert canvas.model.committed == external


def test_dock_clears_external_advisory_but_retains_release_advisory(qapp):
    from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock

    dock = ReciprocalSpaceDock()
    state = ReciprocalState(2.66, 2.3, 1., .1)
    snapshot = {
        "ki": state.ki, "kf": state.kf, "qx": state.qx, "qy": state.qy,
        "qz": state.qz, "p2": (state.p2x, state.p2y),
        "basis_u": state.basis_u, "basis_v": state.basis_v,
        "plane_u_hkl": (1., 0., 0.), "plane_v_hkl": (0., 1., 0.),
        "K_fixed": "Ki Fixed",
    }
    rejected = LiveReciprocalResult(state, False, "outside limits")
    dock.set_snapshot(dict(snapshot, reciprocal_advisory=rejected))
    assert "stale" in dock.status.text()
    assert "#c1121f" in dock.fields["q"].styleSheet()
    dock.set_snapshot(snapshot)
    assert dock.status.text() == "Ready"
    assert dock.fields["q"].styleSheet() == ""
    assert not dock.canvas._has_advisory
    dock.set_live_result(LiveReciprocalResult(state, True))
    assert dock.status.text() == "Angles current"


def test_canvas_snapshot_carries_reach_metadata_and_standard_cursors(qapp):
    from PySide6.QtCore import Qt
    from gui.docks.reciprocal_space_dock import ReciprocalCanvas

    canvas = ReciprocalCanvas()
    reach = ReachOverlay(.9, 1.1, 1.2, 1.4)
    canvas.set_snapshot({
        "ki": 2.66, "kf": 2.3, "qx": 1., "qy": .2, "qz": 0.,
        "p2": (None, None), "basis_u": (1., 0.), "basis_v": (0., 1.),
        "sense": -1, "reach_overlay": reach,
    })
    assert canvas.reach_overlay == reach
    assert canvas.model.committed.sense == -1
    assert canvas._gesture_cursor(None) == Qt.ArrowCursor
    assert canvas._gesture_cursor("p1") == Qt.OpenHandCursor


def test_dense_circle_and_rigid_gestures_are_continuous():
    start = ReciprocalState(2.66, 2.3, 1., .2)
    cases = (
        ("p1", LockState(q=True), lambda angle: (start.q*math.cos(angle), start.q*math.sin(angle)), "q"),
        ("p2", LockState(ki=True), lambda angle: (start.ki*math.cos(angle), start.ki*math.sin(angle)), "ki"),
        ("p2", LockState(kf=True), lambda angle: (start.qx + start.kf*math.cos(angle), start.qy + start.kf*math.sin(angle)), "kf"),
        ("p1", LockState(ki=True, kf=True, q=True, delta_e=True), lambda angle: (start.q*math.cos(angle), start.q*math.sin(angle)), "rigid"),
    )
    angles = [index * 2*math.pi / 72 for index in range(73)]
    for handle, locks, candidate, kind in cases:
        model = ReciprocalInteractionModel(start, locks)
        model.begin_drag(handle)
        states = [(model.drag_p1(point) if handle == "p1" else model.drag_p2(point)).state for point in map(candidate, angles)]
        assert all(math.isfinite(state.qx) and math.isfinite(state.p2x) for state in states)
        assert max(math.dist((a.qx, a.qy), (b.qx, b.qy)) for a, b in zip(states, states[1:])) < 0.35
        if kind == "q":
            assert all(math.isclose(state.q, start.q, rel_tol=1e-8) for state in states)
        elif kind == "ki":
            assert all(math.isclose(state.actual_ki, start.actual_ki, rel_tol=1e-8) for state in states)
        elif kind == "kf":
            assert all(math.isclose(state.actual_kf, start.actual_kf, rel_tol=1e-8) for state in states)
        else:
            assert all(math.isclose(state.actual_ki, start.actual_ki, rel_tol=1e-8) for state in states)


def test_delta_annulus_clamps_both_boundaries_and_direct_circle_crosses_sense():
    start = ReciprocalState(2.66, 2.3, 1., .2)
    model = ReciprocalInteractionModel(start, LockState(delta_e=True))
    model.begin_drag("p1")
    low = model.drag_p1((0., 0.)).state
    high = model.drag_p1((100., 0.)).state
    assert abs(start.actual_ki-start.actual_kf) <= low.q <= start.actual_ki+start.actual_kf
    assert abs(start.actual_ki-start.actual_kf) <= high.q <= start.actual_ki+start.actual_kf
    circle = ReciprocalInteractionModel(start, LockState(ki=True))
    circle.begin_drag("p2")
    senses = set()
    for angle in [index * 2*math.pi / 24 for index in range(25)]:
        senses.add(circle.drag_p2((start.ki*math.cos(angle), start.ki*math.sin(angle))).state.sense)
    assert senses == {-1, 1}


def test_camera_preserves_physical_geometry_with_skewed_uv_basis():
    state = ReciprocalState(2.66, 2.3, 1., .2,
                            basis_u=(2., 0.), basis_v=(1., 3.))
    model = ReciprocalInteractionModel(state)
    centre = (400., 300.)
    a, b = (.2, .7), (1.6, -.1)
    assert math.isclose(
        math.dist(model.world_to_screen(a, centre), model.world_to_screen(b, centre)),
        math.dist(a, b) * model.scale,
        rel_tol=1e-12,
    )
    assert primitive_miller(.5, 0, 0) == (1, 0, 0)
    assert primitive_miller(2, -2, 0) == (1, -1, 0)


@pytest.mark.parametrize("bits", itertools.product((False, True), repeat=4))
def test_handle_affordances_are_defined_for_every_lock_mask(bits):
    model = ReciprocalInteractionModel(
        ReciprocalState(2.66, 2.3, 1., .2), LockState(*bits)
    )
    for handle in ("p1", "p2"):
        cue = model.handle_affordance(handle)
        assert cue.handle == handle and cue.movable
        assert isinstance(cue.radial, bool) and isinstance(cue.tangential, bool)
    if model.locks.q:
        cue = model.handle_affordance("p1")
        assert not cue.radial and cue.tangential
    if model.locks.ki:
        cue = model.handle_affordance("p2")
        assert not cue.radial and cue.tangential


def test_kf_only_projects_each_dragged_endpoint_to_fixed_kf_circle():
    start = ReciprocalState(2.66, 2.3, 1., .2)
    model = ReciprocalInteractionModel(start, LockState(kf=True))
    model.begin_drag(); p1 = model.drag_p1((2., 1.))
    assert p1.valid and math.isclose(p1.state.actual_kf, start.actual_kf, rel_tol=1e-8)
    assert math.isclose(p1.state.actual_ki, start.actual_ki, rel_tol=1e-8)
    model.begin_drag(); p2 = model.drag_p2((2., 1.))
    assert p2.valid and math.isclose(p2.state.actual_kf, start.actual_kf, rel_tol=1e-8)


def test_reconstructed_state_stays_on_supplied_scattering_branch():
    base = ReciprocalState(2.66, 2.3, 1., 0.)
    opposite = (base.p2x, -abs(base.p2y))
    rebuilt = ReciprocalState(
        base.ki + 2e-6, base.kf + 2e-6, base.qx, base.qy,
        p2x=opposite[0], p2y=opposite[1],
    )
    assert math.dist((rebuilt.p2x, rebuilt.p2y), opposite) < 1e-4


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
