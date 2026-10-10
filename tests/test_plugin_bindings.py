"""Plugin capabilities and backend bindings, on all four instruments.

A binding says which McStas parameter carries a canonical quantity and how
its unit converts. These tests hold each binding against what the plugin
actually emits at the solver baseline's points, and each slit binding
against the built tree, so a binding cannot name the wrong parameter, axis or
unit without failing here.
"""
import dataclasses
import importlib
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("mcstasscript")

from instruments.contract import InstrumentPlugin
from instruments.rules import (
    ATT, MTT, SGL, SGU, STH, STT, context_from_state, tas_capabilities,
)
from instruments.validation import validate_descriptor
from tavi.quantities import public_values, slit_gap_ids

_spec = importlib.util.spec_from_file_location(
    "solver_baseline_cases", Path(__file__).resolve().parent / "data" / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)

LABELS = tuple(cases.PLUGINS)


def _plugin(label):
    module, cls = cases.PLUGINS[label]
    return getattr(importlib.import_module(module), cls)()


def _named(snap, descriptor):
    """The point's bound quantities by canonical ID, read from its metadata and launch slits."""
    meta = snap.metadata
    named = {MTT: meta["mtt"], STT: meta["stt"], STH: meta["sth"], ATT: meta["att"],
             SGL: meta["sgl"], SGU: meta["sgu"]}
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


@pytest.mark.parametrize("label", LABELS)
def test_each_slit_binding_is_a_runtime_parameter_of_a_slit(label):
    """Scans change runtime parameters: each bound gap is a Slit's width or height."""
    plugin = _plugin(label)
    descriptor = plugin.descriptor()
    base = plugin.default_state()
    vals = cases._launch_vals(descriptor)
    config = plugin.scan_config(base, vals, None, {}, base.sample_mount)
    instrument = plugin.build(config, False, {}, 1000)
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
