"""Solver baseline cases, shared by make_solver_baseline.py (writes the JSON) and
test_solver_baseline.py (recomputes and compares).

Every case is solved from the plugin's own descriptor and default state, the
default crystals, a cubic a = 4.05 A sample and the GUI launch state's 14.7 meV
fixed energy (the one value no plugin declares). Nothing here reads config/.
"""
import copy
import importlib
import math
import numbers

from instruments.contract import CurvatureMode
from instruments.rules import context_from_state, point_plan
from instruments.tas_runtime import (
    ATT, DE, HKL, HKL_CALC, MOTORS, MTT, Q, Q_CALC, SGL, SGU, STH, STT, compute_scan_snapshot,
)
from tavi.orientation import lock_plane
from tavi.sample_mount import SampleMount

PLUGINS = {
    "PUMA": ("instruments.puma.plugin", "PUMAPlugin"),
    "IN8": ("instruments.in8.plugin", "IN8Plugin"),
    "IN12": ("instruments.in12.plugin", "IN12Plugin"),
    "PANDA": ("instruments.panda.plugin", "PANDAPlugin"),
}

FIXED_E_MEV = 14.7
RADII = ("rhm", "rvm", "rha", "rva")
RLU_CASES = (
    ("rlu_100_dE0", (1.0, 0.0, 0.0), 0.0, "Kf Fixed"),
    ("rlu_110_dE+5_kf", (1.0, 1.0, 0.0), 5.0, "Kf Fixed"),
    ("rlu_100_dE-3_ki", (1.0, 0.0, 0.0), -3.0, "Ki Fixed"),
    ("rlu_100p2_arcs", (1.0, 0.0, 0.2), 0.0, "Kf Fixed"),
)

# Today's emitted parameter and metadata names -> canonical role (S2.1 table).
# Names not listed keep their own name as the role.
PARAM_ROLE = {
    "A1_param": "mono_two_theta_deg",
    "A2_param": "sample_two_theta_deg",
    "A3_param": "sample_rotation_deg",
    "A4_param": "analyzer_two_theta_deg",
    "sgl_param": "sample_lower_arc_deg",
    "sgu_param": "sample_upper_arc_deg",
    "rhm_param": "applied_mono_horizontal_radius_m",
    "rvm_param": "applied_mono_vertical_radius_m",
    "rha_param": "applied_analyzer_horizontal_radius_m",
    "rva_param": "applied_analyzer_vertical_radius_m",
    "vbl_hgap_param": "slit.post_mono.horizontal_gap",
    "pbl_hgap_param": "slit.pre_sample.horizontal_gap",
    "pbl_vgap_param": "slit.pre_sample.vertical_gap",
    "dbl_hgap_param": "slit.detector.horizontal_gap",
    "sbl_wgap_param": "slit.pre_sample.horizontal_gap",
    "sbl_hgap_param": "slit.pre_sample.vertical_gap",
    "ms1_wgap_param": "slit.virtual_source.horizontal_gap",
    "ss1_wgap_param": "slit.pre_sample.horizontal_gap",
    "ss1_hgap_param": "slit.pre_sample.vertical_gap",
    "ss2_wgap_param": "slit.sample_exit.horizontal_gap",
    "ss2_hgap_param": "slit.sample_exit.vertical_gap",
}
# McStas parameters renamed since the baseline was recorded: recorded name -> emitted name.
# The JSON keeps the recorded names; the test translates them, never the numbers.
RENAMED_PARAMS = {
    "A1_param": "mono_two_theta_param",
    "A2_param": "sample_two_theta_param",
    "A3_param": "sample_rotation_param",
    "A4_param": "analyzer_two_theta_param",
}
PARAM_ROLE.update({new: PARAM_ROLE[old] for old, new in RENAMED_PARAMS.items()})
# Emitted since the baseline was recorded: the crystal θ the cradles now rotate by, each
# held to half its recorded 2θ, which is the rotation the cradle had (McStas "2θ/2").
THETA_PARAMS = {"mono_theta_param": "A1_param", "analyzer_theta_param": "A4_param"}
META_ROLE = {
    "mtt": "mono_two_theta_deg",
    "stt": "sample_two_theta_deg",
    "sth": "sample_rotation_deg",
    "att": "analyzer_two_theta_deg",
    "sgl": "sample_lower_arc_deg",
    "sgu": "sample_upper_arc_deg",
    "H": "h",
    "K": "k",
    "L": "l",
    "qx": "q_instrument_x_inv_angstrom",
    "qy": "q_instrument_y_inv_angstrom",
    "qz": "q_instrument_z_inv_angstrom",
    "deltaE": "energy_transfer_mev",
    "Ei": "incident_energy_mev",
    "Ef": "final_energy_mev",
    "Ki": "incident_wavevector_inv_angstrom",
    "Kf": "final_wavevector_inv_angstrom",
    "rhm": "applied_mono_horizontal_radius_m",
    "rvm": "applied_mono_vertical_radius_m",
    "rha": "applied_analyzer_horizontal_radius_m",
    "rva": "applied_analyzer_vertical_radius_m",
}
META_NAMES = ("mtt", "stt", "sth", "att", "sgl", "sgu", "omega", "H", "K", "L",
              "qx", "qy", "qz", "deltaE", "Ei", "Ef", "Ki", "Kf",
              "rhm", "rvm", "rha", "rva", "curvature_modes", "curvature_clamped")


def param_role(name):
    return PARAM_ROLE.get(name, name)


def emitted_name(recorded):
    """The name today's code emits for a parameter the baseline recorded."""
    return RENAMED_PARAMS.get(recorded, recorded)


def meta_role(name):
    return META_ROLE.get(name, name)


def _modes(**overrides):
    return {**{axis: CurvatureMode.HELD for axis in RADII}, **overrides}


def _launch_vals(descriptor, **overrides):
    """The GUI launch state's defaults, read from the plugin's descriptor."""
    vals = {
        "K_fixed": "Kf Fixed", "fixed_E": FIXED_E_MEV, "deltaE": 0.0,
        "monocris": descriptor.mono_crystals[0].id,
        "anacris": descriptor.ana_crystals[0].id,
        "source_type": descriptor.source_types[0].id, "source_dE": 2.0,
        "modules": {m.id: m.default for m in descriptor.modules},
        "collimation": {c.id: c.default for c in descriptor.collimation},
        "slits_mm": {s.id: ((s.default_width_mm, s.default_height_mm) if s.has_height
                            else s.default_width_mm) for s in descriptor.slits},
        "rhm": 0.0, "rvm": 0.0, "rha": 0.0, "rva": 0.0,
        "curvature_modes": _modes(),
    }
    vals.update(overrides)
    return vals


def _fixed_axis(descriptor):
    """The first curvature axis the default crystals declare not driven, or None."""
    for crystal in (descriptor.mono_crystals[0], descriptor.ana_crystals[0]):
        for axis, spec in crystal.curvature.items():
            if not spec.driven:
                return axis
    return None


# Each calculation's named inputs, in the order the cases list them.
_HEAD = {HKL_CALC: (*HKL, DE), Q_CALC: (*Q, DE), MOTORS: (MTT, STT, STH, ATT)}


def _point(calculation, head, sgl=0.0, sgu=0.0):
    """A named scan point: the calculation's four coordinates, plus the arcs it reads."""
    point = dict(zip(_HEAD[calculation], head))
    if calculation == MOTORS:
        point.update({SGL: sgl, SGU: sgu})
    return point


def build_cases(label):
    """``{case name: (note, PointSnapshot)}`` for one instrument.

    Raises RuntimeError on the first case that does not solve: a baseline records
    only successful solves, so a failing case is changed, never dropped.
    """
    module, cls = PLUGINS[label]
    plugin = getattr(importlib.import_module(module), cls)()
    descriptor = plugin.descriptor()
    base = plugin.default_state()
    base.sample_mount = SampleMount.from_lattice_tas(4.05, 4.05, 4.05, 90, 90, 90)
    results = {}

    def solve(name, calculation, point, vals, note="", state=base):
        config = plugin.scan_config(state, vals, None, {}, state.sample_mount)
        plan = point_plan(context_from_state(config, vals, plugin.capabilities()), calculation)
        snap = compute_scan_snapshot(plan, point, 0, config, vals, data_folder=".")
        if snap.params is None or snap.error_flags:
            raise RuntimeError(f"{label}/{name} does not solve: {snap.error_flags}")
        results[name] = (note, snap)
        return snap

    for name, hkl, d_e, side in RLU_CASES:
        vals = _launch_vals(descriptor, K_fixed=side, deltaE=d_e)
        note = "arcs tilt about 11.3 deg to level (1,0,0.2)" if name == "rlu_100p2_arcs" else ""
        solve(name, HKL_CALC, _point(HKL_CALC, [*hkl, d_e]), vals, note)

    for name, _, d_e, side in RLU_CASES:
        meta = results[name][1].metadata
        vals = _launch_vals(descriptor, K_fixed=side, deltaE=d_e)
        solve("q_" + name[len("rlu_"):], Q_CALC,
              _point(Q_CALC, [meta["qx"], meta["qy"], meta["qz"], d_e]), vals)

    vals = _launch_vals(descriptor, K_fixed="Kf Fixed", deltaE=5.0)
    meta = results["rlu_110_dE+5_kf"][1].metadata
    head = [meta["mtt"], meta["stt"], meta["sth"], meta["att"]]
    solve("angle_110", MOTORS, _point(MOTORS, head, meta["sgl"], meta["sgu"]), vals)
    stepped = head[:3] + [head[3] + math.copysign(2.0, head[3])]
    solve("angle_ana_step", MOTORS, _point(MOTORS, stepped, meta["sgl"], meta["sgu"]), vals,
          "analyser 2theta moved by 2 deg, mono held")

    fixed = _fixed_axis(descriptor)
    hkl_point = [1.0, 0.0, 0.0, 0.0]
    vals = _launch_vals(descriptor, curvature_modes=_modes(rhm=CurvatureMode.AUTOFOCUS))
    solve("curv_autofocus", HKL_CALC, _point(HKL_CALC, hkl_point), vals,
          "rhm autofocused from the solved two-theta at this point")
    vals = _launch_vals(descriptor, rhm=3.0)
    solve("curv_held", HKL_CALC, _point(HKL_CALC, hkl_point), vals,
          "" if fixed else "no driven=False axis on the default crystals: curv_fixed omitted")
    if fixed:
        vals = _launch_vals(descriptor, **{fixed: 0.31})
        solve("curv_fixed", HKL_CALC, _point(HKL_CALC, hkl_point), vals,
              f"{fixed} is driven=False: the requested 0.31 m is pinned to its declared radius")

    locked = copy.deepcopy(base)
    tilts = lock_plane(locked.goniometer, locked.sample_mount.mounted_basis,
                       (1, 0, 0), (0, 1, 0.2))
    locked.plane_lock = {"hkl_u": [1.0, 0.0, 0.0], "hkl_v": [0.0, 1.0, 0.2],
                         "tilts": tilts}
    vals = _launch_vals(descriptor)
    solve("plane_lock_01p2", HKL_CALC, _point(HKL_CALC, [0.0, 1.0, 0.2, 0.0]), vals,
          "plane (1,0,0)/(0,1,0.2) held by lock_plane", state=locked)
    return results


def _plain(label, value):
    """A JSON-ready value; refuses None and non-finite numbers."""
    if value is None:
        raise ValueError(f"{label} is None")
    if isinstance(value, (bool, str)):
        return value
    if isinstance(value, numbers.Real):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{label} is {number}")
        return number
    if isinstance(value, dict):
        return {str(k): _plain(f"{label}[{k}]", v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(f"{label}[{i}]", v) for i, v in enumerate(value)]
    raise TypeError(f"{label}: unsupported type {type(value).__name__}")


def _absent_in_mode(name, calculation):
    return ((name in ("H", "K", "L") and calculation != HKL_CALC)
            or (name in ("qx", "qy", "qz") and calculation == MOTORS))


def record(snap):
    """The JSON body (``params``, ``metadata``) for one successful snapshot."""
    if snap.params is None or snap.error_flags:
        raise ValueError("refusing to record a point that did not solve")
    mode = snap.metadata["calculation"]
    params = [{"name": name, "role": param_role(name),
               "value": _plain(f"param {name}", snap.params[name])}
              for name in sorted(snap.params)]
    metadata = []
    for name in META_NAMES:
        if snap.metadata.get(name) is None and _absent_in_mode(name, mode):
            continue
        metadata.append({"name": name, "role": meta_role(name),
                         "value": _plain(f"metadata {name}", snap.metadata.get(name))})
    return {"params": params, "metadata": metadata}
