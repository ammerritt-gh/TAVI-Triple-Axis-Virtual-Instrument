"""Plugin capabilities and backend bindings, on all four instruments.

A binding says which McStas parameter carries a canonical quantity and how
its unit converts. These tests hold each binding against what the plugin
actually emits at the solver baseline's points, and each slit binding
against the built tree, so a binding cannot name the wrong parameter, axis or
unit without failing here. The built trees also pin the crystal cradles'
rotation to the crystal θ parameters.
"""
import dataclasses
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("mcstasscript")

from instruments.contract import InstrumentPlugin
from instruments.rules import (
    ATH, ATT, MTH, MTT, SGL, SGU, STH, STT, context_from_state, crystal_theta, tas_capabilities,
)
from instruments.validation import validate_descriptor
from tavi.quantities import public_values, slit_gap_ids

_spec = importlib.util.spec_from_file_location(
    "solver_baseline_cases", Path(__file__).resolve().parent / "data" / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)
BASELINE = json.loads((Path(__file__).resolve().parent / "data" / "solver_baseline.json")
                      .read_text(encoding="utf-8"))

LABELS = tuple(cases.PLUGINS)


def _plugin(label):
    module, cls = cases.PLUGINS[label]
    return getattr(importlib.import_module(module), cls)()


def _named(snap, descriptor):
    """The point's bound quantities by canonical ID, read from its metadata and launch slits."""
    meta = snap.metadata
    named = {MTT: meta["mtt"], STT: meta["stt"], STH: meta["sth"], ATT: meta["att"],
             SGL: meta["sgl"], SGU: meta["sgu"],
             MTH: crystal_theta(meta["mtt"]), ATH: crystal_theta(meta["att"])}
    for axis, qid in (("rhm", "mono_horizontal_radius_m"), ("rvm", "mono_vertical_radius_m"),
                      ("rha", "analyzer_horizontal_radius_m"),
                      ("rva", "analyzer_vertical_radius_m")):
        named[f"applied_{qid}"] = meta[axis]
    named.update((k, v) for k, v in public_values(cases._launch_vals(descriptor),
                                                    descriptor.slits).items()
                 if k.startswith("slit."))
    return named


@pytest.mark.parametrize("label", LABELS)
def test_capabilities_bind_every_aperture_and_satisfy_the_contract(label):
    plugin = _plugin(label)
    descriptor = plugin.descriptor()
    caps = plugin.capabilities()
    assert isinstance(plugin, InstrumentPlugin)
    assert caps == tas_capabilities(descriptor)
    gaps = {qid for slit in descriptor.slits for qid in slit_gap_ids(slit)}
    assert caps.slit_bindings == gaps
    assert gaps <= caps.inputs
    assert {spec.name for spec in caps.bindings.values()} <= {
        p.name for p in descriptor.scannable_parameters}


@pytest.mark.parametrize("label", LABELS)
def test_every_binding_matches_what_the_plugin_emits(label):
    plugin = _plugin(label)
    descriptor = plugin.descriptor()
    bindings = plugin.capabilities().bindings
    for name, (_note, snap) in cases.build_cases(label).items():
        named = _named(snap, descriptor)
        assert set(bindings) <= set(named), sorted(set(bindings) - set(named))
        for qid, spec in bindings.items():
            assert snap.params[spec.name] == pytest.approx(spec.scale * named[qid], abs=1e-12), (
                name, qid, spec.name)


@pytest.fixture(scope="module")
def built():
    """Each instrument's plain tree, built once from its baseline launch state."""
    trees = {}

    def tree(label):
        if label not in trees:
            plugin = _plugin(label)
            base = plugin.default_state()
            vals = cases._launch_vals(plugin.descriptor())
            config = plugin.scan_config(base, vals, None, {}, base.sample_mount)
            trees[label] = plugin.build(config, False, {}, 1000)
        return trees[label]
    return tree


@pytest.mark.parametrize("label", LABELS)
def test_each_slit_binding_is_a_runtime_parameter_of_a_slit(label, built):
    """Scans change runtime parameters: each bound gap is a Slit's width or height."""
    plugin = _plugin(label)
    instrument = built(label)
    declared = {p.name for p in instrument.parameters}
    apertures = {}
    for component in instrument.component_list:
        if component.component_name == "Slit":
            apertures[component.xwidth] = (component.name, "horizontal")
            apertures[component.yheight] = (component.name, "vertical")
    for qid in plugin.capabilities().slit_bindings:
        spec = plugin.capabilities().bindings[qid]
        assert spec.name in declared, qid
        assert spec.name in apertures, (qid, spec.name)
        assert qid.split(".")[2].startswith(apertures[spec.name][1]), (qid, apertures[spec.name])


@pytest.mark.parametrize("label", LABELS)
def test_crystal_cradles_turn_by_theta_as_before_at_a_point(label, built):
    """Each crystal cradle rotates by its θ parameter, which at a solved point equals
    half the baseline's recorded 2θ: the rotation the cradle had as McStas "2θ/2"."""
    by_name = {c.name: c for c in built(label).component_list}
    case = "rlu_110_dE+5_kf"
    recorded = {e["name"]: e["value"] for e in BASELINE["cases"][f"{label}/{case}"]["params"]}
    params = cases.build_cases(label)[case][1].params
    for cradle, theta, two_theta in (("mono_cradle", "mono_theta_param", "A1_param"),
                                     ("analyzer_cradle", "analyzer_theta_param", "A4_param")):
        rx, ry, rz = by_name[cradle].ROTATED_data
        assert (rx, ry, rz) == (0, theta, 0), (cradle, by_name[cradle].ROTATED_data)
        assert params[theta] == pytest.approx(recorded[two_theta] / 2, rel=1e-12, abs=1e-12)
        assert abs(params[theta]) > 1.0, "the point must turn the crystal"


def test_context_takes_the_slit_bindings_from_the_plugin():
    plugin = _plugin("IN8")
    base = plugin.default_state()
    vals = cases._launch_vals(plugin.descriptor())
    state = plugin.scan_config(base, vals, None, {}, base.sample_mount)
    ctx = context_from_state(state, vals, plugin.capabilities())
    assert ctx.slit_bindings == {"slit.pre_sample.horizontal_gap_mm",
                                 "slit.pre_sample.vertical_gap_mm",
                                 "slit.detector.horizontal_gap_mm"}


@pytest.mark.parametrize("change, message", [
    (dict(quantity="no_such_quantity"), "is no canonical ID"),
    (dict(quantity="slit.sample_exit.horizontal_gap_mm", scale=1e-3),
     "is not a gap of this instrument's slits"),
    (dict(quantity="sample_two_theta_deg"), "is already bound"),
    (dict(quantity="h", scale=0.0), "scale must be finite and non-zero"),
])
def test_validation_refuses_a_bad_binding(change, message):
    descriptor = _plugin("IN8").descriptor()
    params = list(descriptor.scannable_parameters)
    index = next(i for i, p in enumerate(params) if p.name == "E0_param")
    params[index] = dataclasses.replace(params[index], **change)
    bad = dataclasses.replace(descriptor, scannable_parameters=tuple(params))
    assert any(message in error for error in validate_descriptor(bad)), validate_descriptor(bad)
