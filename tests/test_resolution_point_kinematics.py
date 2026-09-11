"""D23 / L2c: the point's own kinematics (Ei/Ki/Ef/Kf), not just its radii,
must reach the analytic resolution model.

``_vals_with_point_state`` (formerly ``_vals_with_point_curvature``)
overlaid only rhm/rvm/rha/rva onto the frozen launch ``vals``, while
``resolution_adapter._kfix`` prefers ``vals['Ki']``/``vals['Kf']`` -- the
LAUNCH wavevector. In angle-scan mode neither Ei nor Ef is held at
``fixed_E`` (``nominal_energies_from_angles``'s docstring): a direct A4 scan
moves the analyser away from the take-off angle ``fixed_E`` predicted, so the
snapshot's own Ei/Ki/Ef/Kf differ from what the launch ``vals`` carries. Only
the overlay now includes them.

Pure numpy/plugin-level tests through ``PANDAPlugin.compute_snapshot`` (real
snapshot metadata) and ``PANDAPlugin.resolution_config`` -- no Qt, no
mcstasscript execution.
"""
import math

import pytest

from instruments.contract import PointSnapshot
from instruments.panda.plugin import PANDAPlugin
from tavi.neutron_conversions import energy2k


def _panda_vals(**overrides):
    """Same shape as ``tests/test_resolution_point_sense.py::_panda_vals``."""
    vals = {
        "K_fixed": "Kf Fixed",
        "source_type": "Maxwellian",
        "source_dE": 2.0,
        "rhm": 4.0, "rvm": 1.8, "rha": 1.65, "rva": 0.60,
        "fixed_E": 4.978451631466585,
        "Ei": 4.978451631466585, "Ki": energy2k(4.978451631466585),
        "Ef": 4.978451631466585, "Kf": energy2k(4.978451631466585),
        "deltaE": 0.0,
        "monocris": "pg002",
        "anacris": "pg002",
        "modules": {},
        "collimation": {"alpha_1": "0", "alpha_2": "40", "alpha_3": "0",
                        "alpha_4": "0"},
        "slits_mm": {"ms1": 40.0, "ss1": (40.0, 80.0), "ss2": (40.0, 80.0)},
    }
    vals.update(overrides)
    return vals


def _angle_snapshot(plugin, mtt, stt, sth, att, tmp_path, K_fixed="Kf Fixed"):
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    state.K_fixed = K_fixed
    state.fixed_E = 4.978451631466585
    scans = [mtt, stt, sth, att, 4.0, 1.8, 1.65, 0.60, 0.0, 0.0, 0.0]
    snapshot = plugin.compute_snapshot(
        (scans, 0), 0, "angle", state,
        {"deltaE": 0.0, "chi": 0.0, "omega": 0.0}, str(tmp_path),
    )
    assert isinstance(snapshot, PointSnapshot)
    assert snapshot.error_flags == [], snapshot.error_flags
    return snapshot


def test_kf_fixed_angle_point_uses_its_own_kf_not_the_launch_kf(tmp_path):
    """A1 = -74.332, A4 = +50 (PANDA's opposite-branch A4,
    ``test_resolution_point_sense.py``'s ``_OPPOSITE_BRANCH_ATT``), nominally
    Kf-fixed at 4.97845 meV. In angle mode the analyser take-off (A4=+50)
    does not sit where fixed_E predicts, so the point's own Kf/Ei must reach
    the resolution model -- not the launch's fixed_E-derived Kf."""
    from TAVI_PySide6 import _vals_with_point_state

    plugin = PANDAPlugin()
    snapshot = _angle_snapshot(plugin, -74.332, 120.180, 60.090, 50.0, tmp_path)

    launch_vals = _panda_vals()
    launch_kf = launch_vals["Kf"]

    # The point's own kinematics differ from the launch's fixed_E-derived Kf
    # -- this is the hole D23 closes, pinned directly on the metadata first.
    assert snapshot.metadata["Kf"] != pytest.approx(launch_kf)
    assert snapshot.metadata["Ei"] > 0

    point_vals = _vals_with_point_state(launch_vals, snapshot.metadata)
    cfg = plugin.resolution_config(
        point_vals, q0=2.0, w=snapshot.metadata["deltaE"],
    )
    # The config's fixed wavevector is the POINT's own Kf, not the launch's.
    assert cfg.kfix == pytest.approx(snapshot.metadata["Kf"])
    assert cfg.kfix != pytest.approx(launch_kf)


def test_ki_fixed_angle_point_uses_its_own_ki_not_the_launch_ki(tmp_path):
    """Mirror case: Ki-fixed, A1 scanned away from where fixed_E predicts."""
    from TAVI_PySide6 import _vals_with_point_state

    plugin = PANDAPlugin()
    snapshot = _angle_snapshot(
        plugin, 50.0, 120.180, 60.090, -74.332, tmp_path, K_fixed="Ki Fixed"
    )

    launch_vals = _panda_vals(K_fixed="Ki Fixed")
    launch_ki = launch_vals["Ki"]

    assert snapshot.metadata["Ki"] != pytest.approx(launch_ki)
    assert snapshot.metadata["Ef"] > 0

    point_vals = _vals_with_point_state(launch_vals, snapshot.metadata)
    cfg = plugin.resolution_config(
        point_vals, q0=2.0, w=snapshot.metadata["deltaE"],
    )
    assert cfg.kfix == pytest.approx(snapshot.metadata["Ki"])
    assert cfg.kfix != pytest.approx(launch_ki)
