"""Shared McStas component-tree emitters for TAS instruments.

Phase 3 of the configurable-instruments effort (design record
``docs/CONFIGURABLE_INSTRUMENTS.md`` §11, §19): the repetitive categories of an
instrument's ``build()`` -- diagnostic monitors, the sample, the sample
orientation hierarchy, crystal assemblies, slits, and collimators -- are
emitted here from descriptor data instead of copy-pasted blocks, so a second
instrument reuses the common TAS backbone.

Instrument-agnostic by design: no PUMA imports, no mcstasscript import (the
``instrument`` argument is the already-created ``McStas_instr`` object, duck-
typed). Component ORDER is physics in McStas -- callers invoke these emitters
at the exact insertion points of their component tree; nothing here reorders.

Emission detail that matters for reproducibility: McStasScript renders AT /
ROTATED values with ``str()``, so ``0`` (int) and ``0.0`` (float) produce
different ``.instr`` text. ``_mcstas_number`` coerces integral floats so
descriptor tuples like ``(0.0, 0.0, 0.144)`` emit as the legacy ``(0, 0,
0.144)``.
"""
from __future__ import annotations


def _mcstas_number(value):
    """Coerce integral floats to int so emitted .instr text matches legacy."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _placement(triple):
    return [_mcstas_number(v) for v in triple]


def emit_monitors(instrument, specs, enabled, *, size_overrides=None):
    """Add each enabled diagnostic monitor from an ordered group of MonitorSpecs.

    ``specs`` is the consecutive run of monitors at one insertion point, in beam
    order. ``enabled`` is the diagnostic-settings mapping (spec.id -> bool).
    ``size_overrides`` maps a spec's ``component_name`` to parameter overrides
    applied over ``spec.settings`` -- used for monitors sized from the selected
    crystal's slab geometry at build time.

    Returns the list of added components.
    """
    added = []
    for spec in specs:
        if not enabled.get(spec.id):
            continue
        component = instrument.add_component(
            spec.component_name or spec.id,
            spec.component_type,
            AT=_placement(spec.at),
            ROTATED=_placement(spec.rotated),
            RELATIVE=spec.relative,
        )
        settings = dict(spec.settings)
        if size_overrides:
            settings.update(size_overrides.get(spec.component_name, {}))
        for key, value in settings.items():
            setattr(component, key, value)
        added.append(component)
    return added


def emit_sample(instrument, spec, *, relative, at=(0.0, 0.0, 0.0),
                rotated=(0.0, 0.0, 0.0)):
    """Add a SampleSpec's component under ``relative`` (e.g. "sample_mount").

    Returns the component, or None when ``spec.component_type`` is None (the
    "no sample" path -- the caller decides how to report it).
    """
    if spec.component_type is None:
        return None
    component = instrument.add_component(
        spec.component_name or spec.id,
        spec.component_type,
        AT=_placement(at),
        ROTATED=_placement(rotated),
        RELATIVE=relative,
    )
    for key, value in spec.properties.items():
        setattr(component, key, value)
    if spec.split is not None:
        component.set_SPLIT(spec.split)
    if spec.extend:
        component.append_EXTEND(spec.extend)
    return component


def emit_sample_orientation_arms(instrument, *, relative, distance,
                                 saz_param="saz_param",
                                 chi_expr="chi_total",
                                 omega_expr="A3_param + omega_offset_total",
                                 mount_params=("mount_rx_param",
                                               "mount_ry_param",
                                               "mount_rz_param")):
    """The generic TAS sample orientation hierarchy.

    sample_gonio (saz) -> sample_chi_arm (chi) -> sample_cradle (omega) ->
    sample_mount (static mount rotations). Component names are fixed -- they are
    part of the shared-parameter contract every instrument's ParameterSpec block
    declares. Returns the mount component name.
    """
    instrument.add_component("sample_gonio", "Arm",
                             AT=[0, 0, distance], ROTATED=[saz_param, 0, 0],
                             RELATIVE=relative)
    instrument.add_component("sample_chi_arm", "Arm",
                             AT=[0, 0, 0], ROTATED=[chi_expr, 0, 0],
                             RELATIVE="sample_gonio")
    instrument.add_component("sample_cradle", "Arm",
                             AT=[0, 0, 0], ROTATED=[0, omega_expr, 0],
                             RELATIVE="sample_chi_arm")
    instrument.add_component("sample_mount", "Arm",
                             AT=[0, 0, 0], ROTATED=list(mount_params),
                             RELATIVE="sample_cradle")
    return "sample_mount"


def emit_crystal_assembly(instrument, *, cradle_name, crystal_name, relative,
                          distance, rotation_expr, info, d_key,
                          rv_param, rh_param, split, extend=None):
    """A crystal cradle Arm plus a Monochromator_curved read from a crystal-info dict.

    ``info`` is the legacy crystal-info dict (``mono_ana_crystals_setup`` shape);
    ``d_key`` selects its d-spacing key ('dm' for a monochromator, 'da' for an
    analyzer). Returns the crystal component.
    """
    instrument.add_component(cradle_name, "Arm",
                             AT=[0, 0, distance],
                             ROTATED=[0, rotation_expr, 0],
                             RELATIVE=relative)
    crystal = instrument.add_component(crystal_name, "Monochromator_curved",
                                       AT=[0, 0, 0], RELATIVE=cradle_name)
    crystal.zwidth = info['slabwidth']
    crystal.yheight = info['slabheight']
    crystal.gap = info['gap']
    crystal.NH = info['ncolumns']
    crystal.NV = info['nrows']
    crystal.r0 = info['r0']
    crystal.DM = info[d_key]
    crystal.RV = rv_param
    crystal.RH = rh_param
    crystal.mosaic = info['mosaic']
    crystal.order = 0  # all orders
    crystal.reflect = info['reflect']
    crystal.transmit = info['transmit']
    if extend:
        crystal.append_EXTEND(extend)
    crystal.set_SPLIT(split)
    return crystal


def emit_slit(instrument, name, *, relative, at, xwidth, yheight, rotated=None):
    """A Slit. ``rotated=None`` omits the ROTATED clause entirely -- legacy
    instruments differ per slit on this and the emitted text must match."""
    kwargs = {"AT": _placement(at), "RELATIVE": relative}
    if rotated is not None:
        kwargs["ROTATED"] = _placement(rotated)
    slit = instrument.add_component(name, "Slit", **kwargs)
    slit.xwidth = xwidth
    slit.yheight = yheight
    return slit


def emit_collimator(instrument, name, *, relative, at, divergence, length,
                    xwidth, yheight=None, ymin=None, ymax=None):
    """A Collimator_linear. Sets whichever of yheight vs ymin/ymax is given;
    never emits ROTATED (no legacy collimator does)."""
    collimator = instrument.add_component(name, "Collimator_linear",
                                          AT=_placement(at), RELATIVE=relative)
    collimator.xwidth = xwidth
    if yheight is not None:
        collimator.yheight = yheight
    if ymin is not None:
        collimator.ymin = ymin
    if ymax is not None:
        collimator.ymax = ymax
    collimator.length = length
    collimator.divergence = divergence
    return collimator


def crystal_spec_to_info(spec, d_key):
    """Legacy crystal-info dict from a descriptor CrystalSpec.

    ``reflect``/``transmit`` carry embedded quotes because they are emitted
    verbatim as McStas string literals by build(). The McStas sentinel
    ``"NULL"`` (no reflectivity file, constant r0) passes through unchanged.
    """
    return {
        d_key: spec.d_spacing,
        'slabwidth': spec.slab_width,
        'slabheight': spec.slab_height,
        'ncolumns': spec.n_columns,
        'nrows': spec.n_rows,
        'gap': spec.gap,
        'mosaic': spec.mosaic,
        'r0': spec.r0,
        'reflect': f'"{spec.reflect_file}"',
        'transmit': f'"{spec.transmit_file}"',
    }


def find_crystal_spec(specs, crystal_id):
    for spec in specs:
        if spec.id == crystal_id:
            return spec
    return None


def crystal_info_from_descriptor(descriptor, monocris, anacris):
    """(monochromator_info, analyzer_info) dicts looked up in a descriptor.

    Lookups are by CrystalSpec id ("pg002"); unknown ids return empty dicts,
    matching the historical mono_ana_crystals_setup contract.
    """
    mono_spec = find_crystal_spec(descriptor.mono_crystals, monocris)
    ana_spec = find_crystal_spec(descriptor.ana_crystals, anacris)
    monochromator_info = crystal_spec_to_info(mono_spec, 'dm') if mono_spec else {}
    analyzer_info = crystal_spec_to_info(ana_spec, 'da') if ana_spec else {}
    return monochromator_info, analyzer_info
