"""Packet slice 10, defect 1: the resolution model reads the point's own
scattering sense, not the descriptor's declared (normal-branch) one.

``set_crystal_bending`` already signs curvature off the ACTUAL LOCAL take-off
angle because a direct-angle command can cross onto the opposite branch --
PANDA's analyser sense is normally negative (``sense_ana = RIGHT = -1``) while
its declared A4 travel runs -130..+100 deg, so a direct-angle point can sit at
a *positive* A4, on the opposite branch from the one the descriptor calls
normal. ``build_resolution_config`` used to rebuild ``sm``/``ss``/``sa``
unconditionally from ``descriptor.geometry``, so such a point was emitted on
its real (opposite) branch but analysed by Popovici on the descriptor's
(normal) one -- a silently wrong resolution matrix, no crash, nothing visibly
broken.

Pure numpy-only tests: no Qt, no mcstasscript.
"""
import math

import pytest

from instruments.panda.plugin import PANDAPlugin, panda_descriptor
from instruments.resolution_adapter import build_resolution_config
from tavi.resolution import resolution


def _panda_vals(**overrides):
    """Same shape as ``tests/test_panda_plugin.py::_gui_vals`` -- all four
    curvature axes non-zero, so ``resolution()`` dispatches to Popovici."""
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 4.0, "rvm": 1.8, "rha": 1.65, "rva": 0.60,
        "fixed_E": 4.978451631466585,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "40", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"ms1": 40.0, "ss1": (40.0, 80.0), "ss2": (40.0, 80.0)},
    }
    vals.update(overrides)
    return vals


# PANDA declares sense_ana = RIGHT (-1), but A4 travel spans -130..+100 deg --
# a positive A4 is a real, reachable, opposite-branch point.
_OPPOSITE_BRANCH_ATT = 50.0
_NORMAL_BRANCH_ATT = -74.332   # PANDA's own default A4 (descriptor normal branch)


def test_1_opposite_branch_point_gets_its_own_analyser_sense_matrix_differs():
    """RED FIRST (pre-fix): both configs below produced the identical matrix,
    because the descriptor's sa=-1 was used regardless of the point's own att.
    POST-FIX: the opposite-branch point's sa flips to +1 and the Popovici
    matrix -- and the coherent (bragg) widths derived from it -- differ."""
    plugin = PANDAPlugin()
    cfg_descriptor_branch = plugin.resolution_config(_panda_vals(), q0=2.0, w=0.0)
    cfg_point_local = plugin.resolution_config(
        _panda_vals(), q0=2.0, w=0.0,
        point_angles={"mtt": None, "stt": None, "att": _OPPOSITE_BRANCH_ATT},
    )

    # The point-local config must carry the OPPOSITE analyser sense from the
    # descriptor's declared normal branch -- this is the fix, checked directly.
    assert cfg_descriptor_branch.sa == -1
    assert cfg_point_local.sa == 1
    # sm/ss are untouched: only att was given as a point angle.
    assert cfg_point_local.sm == cfg_descriptor_branch.sm
    assert cfg_point_local.ss == cfg_descriptor_branch.ss

    res_descriptor_branch = resolution(cfg_descriptor_branch)
    res_point_local = resolution(cfg_point_local)
    assert res_descriptor_branch.ok and res_point_local.ok

    # THE RED-FIRST CLAIM: pre-fix, these two matrices were identical (the
    # adapter never saw the point's own att). Post-fix they must differ.
    assert res_descriptor_branch.matrix != res_point_local.matrix
    print(
        "\nPANDA opposite-branch point (att=%.1f) Popovici bragg widths:\n"
        "  descriptor-branch (BUG, sa=-1): %r\n"
        "  point-local       (FIX, sa=+1): %r"
        % (_OPPOSITE_BRANCH_ATT, res_descriptor_branch.bragg, res_point_local.bragg)
    )
    assert res_descriptor_branch.bragg["dE"] != pytest.approx(res_point_local.bragg["dE"])


def test_2_normal_branch_point_is_unchanged():
    """A point sitting on the descriptor's own normal branch (att<0, matching
    sense_ana=-1) must reproduce the exact descriptor-only config -- this fix
    must not move any existing number for the branch every instrument already
    runs on."""
    plugin = PANDAPlugin()
    cfg_no_point = plugin.resolution_config(_panda_vals(), q0=2.0, w=0.0)
    cfg_normal_branch = plugin.resolution_config(
        _panda_vals(), q0=2.0, w=0.0,
        point_angles={"mtt": -74.332, "stt": 120.180, "att": _NORMAL_BRANCH_ATT},
    )

    assert (cfg_normal_branch.sm, cfg_normal_branch.ss, cfg_normal_branch.sa) == \
        (cfg_no_point.sm, cfg_no_point.ss, cfg_no_point.sa)

    res_no_point = resolution(cfg_no_point)
    res_normal_branch = resolution(cfg_normal_branch)
    assert res_no_point.matrix == res_normal_branch.matrix
    assert res_no_point.bragg == res_normal_branch.bragg


def test_3_caller_with_no_solved_point_falls_back_to_descriptor():
    """``point_angles=None`` (the default) is today's behaviour, unconditionally."""
    geo = panda_descriptor().geometry
    cfg = build_resolution_config(panda_descriptor(), _panda_vals(), q0=2.0, w=0.0)
    assert (cfg.sm, cfg.ss, cfg.sa) == (
        int(geo.sense_mono), int(geo.sense_sample), int(geo.sense_ana)
    )


def test_4_degenerate_zero_two_theta_falls_back_to_declared_sense():
    """A zero take-off angle has no branch to read -- same treatment
    ``set_crystal_bending`` gives its own degenerate zero-angle case."""
    geo = panda_descriptor().geometry
    cfg = build_resolution_config(
        panda_descriptor(), _panda_vals(), q0=2.0, w=0.0,
        point_angles={"mtt": 0.0, "stt": 0.0, "att": 0.0},
    )
    assert (cfg.sm, cfg.ss, cfg.sa) == (
        int(geo.sense_mono), int(geo.sense_sample), int(geo.sense_ana)
    )
    # Not a flipped or zeroed sense -- exactly the declared one.
    assert cfg.sa != 0


def test_twin_both_popovici_uses_of_the_analyser_sense_move_together():
    """The trap named in the packet: threading the point-local sense into the
    crystal-angle use but not the curvature-sign use (or vice versa) inside
    Popovici would be the thirteenth instance of this branch's defect class.
    Both uses read ``cfg.sa`` directly (``tavi/resolution.py``), so this test
    pins that a single point-local override reaches both by checking the
    provenance the adapter records for both mono and ana together."""
    plugin = PANDAPlugin()
    cfg = plugin.resolution_config(
        _panda_vals(), q0=2.0, w=0.0,
        point_angles={"mtt": 60.0, "stt": None, "att": _OPPOSITE_BRANCH_ATT},
    )
    # mtt=60 is also opposite PANDA's declared sense_mono=RIGHT(-1).
    assert cfg.sm == 1
    assert cfg.sa == 1
    # Both senses are point-local in provenance (not both silently descriptor).
    sources = cfg.provenance["senses"]["source"]
    assert "point-local" in sources["sm"]
    assert "point-local" in sources["sa"]
