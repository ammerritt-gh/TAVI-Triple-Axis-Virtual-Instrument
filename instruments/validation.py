"""Descriptor validation (Phase 1.5 of ``docs/CONFIGURABLE_INSTRUMENTS.md`` §17.6).

``validate_descriptor(d)`` applies structural rules every descriptor (including
the illustrative examples in ``instruments/_descriptor_examples.py``) must pass.
``validate_descriptor(d, runnable=True)`` additionally applies the rules a
*registered, runnable* instrument must pass: no ``nan`` placeholders, complete
crystal data, an explicit ``mcstas_name``, existing component paths, non-empty
libraries.

ID slug rule (``^[a-z0-9_]+$``) applies to the instrument id and to crystal,
module, collimation-slot, and slit ids. Documented exceptions -- checked only for
non-empty + unique -- are ids that intentionally equal existing GUI/config
strings for the 1:1 Phase-1 wiring: ``SampleSpec.id`` (legacy ``sample_key``
strings), ``MonitorSpec.id`` (diagnostic-settings display keys), and
``SourceType.id`` (the GUI source-type combo strings, e.g. ``"Maxwellian"``).
Phase 2 revisits these when the GUI binds to the descriptor.

``validate_capabilities(caps, id, descriptor)`` applies the same quantity rules to a plugin's
declared inputs, observables and bindings (instrument extras, derived-only inputs), and
checks each slit binding against the descriptor's ParameterSpecs, which the runtime reads.

Error messages are human-readable and prefixed with the offending field/id; they
double as authoring feedback (§11).
"""
from __future__ import annotations

import math
import os
import re

from instruments.descriptor import InstrumentDescriptor, ModuleKind, Sense
from tavi.quantities import QUANTITIES, by_id, slit_gap_id, slit_gap_ids

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_C_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# v1 detector contract (design record §16.9): a single 1-D monitor written to
# detector.dat is the only combination tavi/data_processing.py can read.
_V1_DETECTOR_FILE = "detector.dat"
_V1_DETECTOR_PARSER = "1d_monitor"

# axis_limits keys: the canonical IDs, and the retired TAVI "A<n>" key each one replaces
# (TAVI's old numbering: A2 was sample 2theta, not ILL's mono A2).
_AXIS_LIMIT_KEYS = ("mono_two_theta_deg", "sample_two_theta_deg", "analyzer_two_theta_deg")
_RETIRED_AXIS_KEYS = {"A1": "mono_two_theta_deg", "A2": "sample_two_theta_deg",
                      "A4": "analyzer_two_theta_deg"}

# Optional CrystalSpec fields that a *runnable* instrument must fill in.
_CRYSTAL_REQUIRED_FIELDS = (
    "slab_width", "slab_height", "n_columns", "n_rows",
    "gap", "mosaic", "r0", "reflect_file", "transmit_file",
)


# The TAS runtime's stage (rule R6): its axis names, in order.
_TAS_STAGE_AXES = ("A3", "sgl", "sgu")


class DescriptorValidationError(ValueError):
    """Raised by ``assert_valid_descriptor`` with all messages joined."""


def _finite(value) -> bool:
    try:
        return math.isfinite(value)
    except TypeError:
        return False


def _check_unique(errors, items, list_name):
    seen = set()
    for item in items:
        if item.id in seen:
            errors.append(f"{list_name}: duplicate id {item.id!r}")
        seen.add(item.id)


def _check_ids(errors, items, list_name, *, slug):
    for item in items:
        if not item.id:
            errors.append(f"{list_name}: empty id")
        elif slug and not _SLUG_RE.match(item.id):
            errors.append(
                f"{list_name}[{item.id!r}]: id must match [a-z0-9_]+ "
                f"(display names belong in display_name/label)"
            )
    _check_unique(errors, items, list_name)


# The curvature axes each side of the spectrometer owns, as lowercase
# scan-command names. A crystal can only hold fixed an axis it actually has:
# "rva" on a monochromator is a typo, and a typo here fails open -- the scan
# allowed, the pin bypassed.
_MONO_CURVATURE = frozenset({"rhm", "rvm"})
_ANA_CURVATURE = frozenset({"rha", "rva"})


def _quantity_problem(qid: str, instrument_id: str) -> str | None:
    """Why a quantity an instrument declares is unusable, or None.

    A registry canonical ID is always usable. Any other ID is an instrument extra: it must
    be ``instrument.<instrument_id>.<name>`` and collide with no registry ID or alias.
    """
    try:
        by_id(qid)
        return None
    except KeyError:
        pass
    if qid.casefold() in {n.casefold() for q in QUANTITIES for n in (q.id, *q.aliases)}:
        return f"{qid!r} collides with a registry ID or alias"
    prefix = f"instrument.{instrument_id}."
    if not qid.startswith(prefix) or not _SLUG_RE.match(qid[len(prefix):]):
        return f"{qid!r} is no canonical ID; an instrument extra must be named {prefix}<name>"
    return None


def validate_capabilities(capabilities, instrument_id: str, descriptor) -> list[str]:
    """Problems with a plugin's declared inputs, observables and bindings (empty = valid).

    Every declared quantity is a canonical ID or an instrument extra (``_quantity_problem``),
    no derived-only quantity is an input (a plugin never takes A1 or A5 as input), and every
    slit binding is carried by a descriptor ParameterSpec, the one the runtime reads.
    """
    qids = {*capabilities.inputs, *capabilities.observables, *capabilities.bindings}
    errors = [p for p in (_quantity_problem(q, instrument_id) for q in sorted(qids)) if p]
    for qid in sorted(capabilities.inputs):
        try:
            derived = by_id(qid).derived_only
        except KeyError:
            continue   # an extra or unknown name: reported above
        if derived:
            errors.append(f"{qid!r} is derived and cannot be an input")
    tagged = {p.quantity for p in descriptor.scannable_parameters}
    errors += [f"{qid!r} is a slit binding that no descriptor ParameterSpec carries"
               for qid in sorted(capabilities.slit_bindings - tagged)]
    return errors


def assert_valid_capabilities(capabilities, instrument_id: str, descriptor) -> None:
    """Raise ``DescriptorValidationError`` if a plugin's declared quantities are invalid."""
    errors = validate_capabilities(capabilities, instrument_id, descriptor)
    if errors:
        raise DescriptorValidationError(
            f"Instrument {instrument_id!r} declares unusable quantities:\n  - "
            + "\n  - ".join(errors)
        )


def validate_descriptor(d: InstrumentDescriptor, *, runnable: bool = False) -> list[str]:
    """Return a list of problems (empty = valid).

    Structural rules always apply; ``runnable=True`` adds the rules a registered
    instrument must satisfy (examples may fail those).
    """
    errors: list[str] = []

    # --- S1: instrument identity -------------------------------------------------
    if not d.id or not _SLUG_RE.match(d.id):
        errors.append(f"id: {d.id!r} must match [a-z0-9_]+")
    if not d.display_name:
        errors.append("display_name: must be non-empty")

    # --- S2/S3: per-list ids -----------------------------------------------------
    _check_ids(errors, d.mono_crystals, "mono_crystals", slug=True)
    _check_ids(errors, d.ana_crystals, "ana_crystals", slug=True)
    _check_ids(errors, d.modules, "modules", slug=True)
    _check_ids(errors, d.collimation, "collimation", slug=True)
    _check_ids(errors, d.slits, "slits", slug=True)
    # Documented exceptions: legacy-string ids, non-empty + unique only.
    _check_ids(errors, d.samples, "samples", slug=False)
    _check_ids(errors, d.monitors, "monitors", slug=False)
    _check_ids(errors, d.source_types, "source_types", slug=False)

    # --- S4: scannable parameter names -------------------------------------------
    seen_params = set()
    for p in d.scannable_parameters:
        if not _C_IDENT_RE.match(p.name):
            errors.append(f"scannable_parameters: {p.name!r} is not a valid C identifier")
        if p.name in seen_params:
            errors.append(f"scannable_parameters: duplicate name {p.name!r}")
        seen_params.add(p.name)

    # --- S4b: backend bindings (ParameterSpec.quantity) ----------------------------
    own_slits = {qid for slit in d.slits for qid in slit_gap_ids(slit)}
    bound = {}
    for p in d.scannable_parameters:
        if not p.quantity:
            continue
        where = f"scannable_parameters[{p.name!r}]"
        problem = _quantity_problem(p.quantity, d.id)
        if problem:
            errors.append(f"{where}: {problem}")
        if p.quantity.startswith("slit.") and p.quantity not in own_slits:
            errors.append(f"{where}: {p.quantity!r} is not a gap of this instrument's slits")
        if p.quantity in bound:
            errors.append(f"{where}: {p.quantity!r} is already bound to {bound[p.quantity]!r}")
        bound[p.quantity] = p.name
        if not _finite(p.scale) or p.scale == 0:
            errors.append(f"{where}: scale must be finite and non-zero")

    # --- S5/S6: detector contract -------------------------------------------------
    if not d.primary_detector:
        errors.append("primary_detector: must name the detector component")
    if d.detector_output_file != _V1_DETECTOR_FILE:
        errors.append(
            f"detector_output_file: {d.detector_output_file!r} unsupported; "
            f"v1 only supports {_V1_DETECTOR_FILE!r}"
        )
    if d.detector_parser != _V1_DETECTOR_PARSER:
        errors.append(
            f"detector_parser: {d.detector_parser!r} unsupported; "
            f"v1 only supports {_V1_DETECTOR_PARSER!r}"
        )

    # --- S7: module defaults -------------------------------------------------------
    for m in d.modules:
        if m.kind is ModuleKind.CHOICE:
            if not m.options:
                errors.append(f"modules[{m.id!r}]: CHOICE module needs options")
            elif m.default not in m.options:
                errors.append(
                    f"modules[{m.id!r}]: default {m.default!r} not in options {m.options!r}"
                )
        elif m.kind is ModuleKind.TOGGLE:
            if not isinstance(m.default, bool):
                errors.append(f"modules[{m.id!r}]: TOGGLE default must be a bool")

    # --- S8: collimation defaults ---------------------------------------------------
    # multi_select slots may default to "" = nothing pre-selected (e.g. PUMA's
    # alpha_2 checkboxes); single-select slots must default to an allowed value.
    for slot in d.collimation:
        if not slot.allowed:
            errors.append(f"collimation[{slot.id!r}]: allowed values must be non-empty")
        elif slot.multi_select:
            if slot.default and slot.default not in slot.allowed:
                errors.append(
                    f"collimation[{slot.id!r}]: default {slot.default!r} "
                    f"not in allowed {slot.allowed!r} (use \"\" for no pre-selection)"
                )
        elif slot.default not in slot.allowed:
            errors.append(
                f"collimation[{slot.id!r}]: default {slot.default!r} "
                f"not in allowed {slot.allowed!r}"
            )

    # --- S9: geometry (kinematic minimum) ------------------------------------------
    g = d.geometry
    for name in ("l2_mono_sample", "l3_sample_ana", "l4_ana_det"):
        value = getattr(g, name)
        if not _finite(value) or value <= 0:
            errors.append(f"geometry.{name}: must be finite and > 0 (got {value!r})")
    # l1_source_mono is exempt structurally (vTAS omits it); checked under R1.

    # --- S10: axis limits -------------------------------------------------------------
    # Keys are canonical IDs; a retired "A<n>" key is refused by name, never remapped by its number.
    for axis, lim in d.axis_limits.items():
        if axis in _RETIRED_AXIS_KEYS:
            errors.append(
                f"axis_limits[{axis!r}]: retired TAVI numbering; use {_RETIRED_AXIS_KEYS[axis]!r} "
                f"(the keys are {', '.join(_AXIS_LIMIT_KEYS)})"
            )
        elif axis not in _AXIS_LIMIT_KEYS:
            errors.append(
                f"axis_limits[{axis!r}]: not a limit key; use {', '.join(_AXIS_LIMIT_KEYS)}"
            )
        if not all(_finite(v) for v in (lim.lower, lim.default, lim.upper)):
            errors.append(f"axis_limits[{axis!r}]: values must be finite")
        elif not (lim.lower <= lim.default <= lim.upper):
            errors.append(
                f"axis_limits[{axis!r}]: expected lower <= default <= upper, "
                f"got {lim.lower} / {lim.default} / {lim.upper}"
            )

    # --- S10b: curvature axes -----------------------------------------------------
    for side, specs, allowed in (
        ("mono_crystals", d.mono_crystals, _MONO_CURVATURE),
        ("ana_crystals", d.ana_crystals, _ANA_CURVATURE),
    ):
        for spec in specs:
            for name, axis in spec.curvature.items():
                prefix = f"{side}[{spec.id!r}].curvature[{name!r}]"
                if name not in allowed:
                    errors.append(
                        f"{prefix}: {name!r} is not one of {sorted(allowed)}"
                    )
                    continue
                numbers = [
                    v for v in (axis.fixed_radius_m, axis.min_radius_m, axis.max_radius_m)
                    if v is not None
                ]
                # Zero is legal and means FLAT, which is why this is >= 0 and
                # not > 0. It is the repo-wide convention: tavi/resolution.py's
                # radius_cm maps 0 (and None) to _FLAT_RADIUS_CM, and McStas
                # Monochromator_curved reads a zero radius as an unbent crystal.
                # A flat assembly is real hardware, so rejecting 0 here would
                # refuse a truthful declaration.
                for value in numbers:
                    if not _finite(value) or value < 0:
                        errors.append(
                            f"{prefix}: radius must be finite and >= 0 (got {value!r})"
                        )
                if axis.driven:
                    if axis.fixed_radius_m is not None:
                        errors.append(
                            f"{prefix}: fixed_radius_m must be unset when driven is True"
                        )
                else:
                    if axis.fixed_radius_m is None:
                        errors.append(
                            f"{prefix}: fixed_radius_m is required when driven is False"
                        )
                    if axis.min_radius_m is not None or axis.max_radius_m is not None:
                        errors.append(
                            f"{prefix}: min_radius_m/max_radius_m only apply to a driven axis"
                        )
                if (
                    axis.min_radius_m is not None
                    and axis.max_radius_m is not None
                    and axis.min_radius_m > axis.max_radius_m
                ):
                    errors.append(f"{prefix}: min_radius_m must be <= max_radius_m")
                if numbers and not axis.provenance:
                    errors.append(
                        f"{prefix}: provenance is required whenever a radius is declared"
                    )

    # --- S11: senses -------------------------------------------------------------------
    for name in ("sense_mono", "sense_sample", "sense_ana"):
        if not isinstance(getattr(g, name), Sense):
            errors.append(f"geometry.{name}: must be a Sense enum member")

    # --- S12: goniometer -----------------------------------------------------------------
    # Undocumented travel is declared as +/-inf (descriptor.UNDOCUMENTED), so
    # infinite bounds are legal here; NaN and an unordered range are not.
    if len(d.goniometer) > 3:
        errors.append(
            "goniometer: at most three axes (turntable plus two arcs); "
            "the stage solver handles no more"
        )
    seen_axes = set()
    for index, ax in enumerate(d.goniometer):
        prefix = f"goniometer[{ax.name!r}]"
        if not ax.name or not _C_IDENT_RE.match(ax.name):
            errors.append(f"{prefix}: name must be a valid identifier")
        if ax.name in seen_axes:
            errors.append(f"goniometer: duplicate axis name {ax.name!r}")
        seen_axes.add(ax.name)
        vector = tuple(ax.axis)
        if len(vector) != 3 or not all(_finite(v) for v in vector):
            errors.append(f"{prefix}: axis must be three finite numbers")
            continue
        if abs(math.sqrt(sum(v * v for v in vector)) - 1.0) > 1e-9:
            errors.append(f"{prefix}: axis must be a unit vector (got {vector!r})")
        elif index == 0 and abs(abs(vector[1]) - 1.0) > 1e-9:
            errors.append(
                f"{prefix}: the first axis is the turntable and must be vertical (y)"
            )
        lim = ax.limits
        if any(math.isnan(v) for v in (lim.lower, lim.default, lim.upper)) or not (
            _finite(lim.default) and lim.lower <= lim.default <= lim.upper
        ):
            errors.append(
                f"{prefix}: expected lower <= default <= upper with a finite "
                f"default, got {lim.lower} / {lim.default} / {lim.upper}"
            )

    if not runnable:
        return errors

    # --- R1: no nan/inf placeholders ----------------------------------------------------
    if not _finite(g.l1_source_mono) or g.l1_source_mono <= 0:
        errors.append(
            f"geometry.l1_source_mono: runnable instrument needs a finite positive "
            f"source-mono distance (got {g.l1_source_mono!r})"
        )
    for p in d.scannable_parameters:
        if p.default is not None and not _finite(p.default):
            errors.append(f"scannable_parameters[{p.name!r}]: default must be finite")

    # --- R2: crystal completeness ---------------------------------------------------------
    for list_name, crystals in (("mono_crystals", d.mono_crystals),
                                ("ana_crystals", d.ana_crystals)):
        for c in crystals:
            if not _finite(c.d_spacing) or c.d_spacing <= 0:
                errors.append(f"{list_name}[{c.id!r}]: d_spacing must be finite and > 0")
            for field_name in _CRYSTAL_REQUIRED_FIELDS:
                value = getattr(c, field_name)
                if value is None:
                    errors.append(
                        f"{list_name}[{c.id!r}]: {field_name} is required for a "
                        f"runnable instrument"
                    )
                elif field_name not in ("reflect_file", "transmit_file") and (
                    not _finite(value) or value <= 0
                ):
                    errors.append(
                        f"{list_name}[{c.id!r}]: {field_name} must be finite and > 0 "
                        f"(got {value!r})"
                    )

    # --- R3: mcstas_name --------------------------------------------------------------------
    if not d.mcstas_name:
        errors.append("mcstas_name: runnable instrument must set it explicitly "
                      "(it drives the .instr/.c/.exe filenames)")
    elif not _C_IDENT_RE.match(d.mcstas_name):
        errors.append(f"mcstas_name: {d.mcstas_name!r} is not a valid C identifier")

    # --- R4: component path exists --------------------------------------------------------------
    if d.component_path is not None and not os.path.isdir(d.component_path):
        errors.append(f"component_path: directory not found: {d.component_path!r}")

    # --- R5: non-empty libraries -----------------------------------------------------------------
    for list_name, items in (
        ("mono_crystals", d.mono_crystals),
        ("ana_crystals", d.ana_crystals),
        ("samples", d.samples),
        ("source_types", d.source_types),
        ("scannable_parameters", d.scannable_parameters),
    ):
        if not items:
            errors.append(f"{list_name}: runnable instrument needs at least one entry")

    # --- R5b: public slit names ---------------------------------------------------------------------
    for slit in d.slits:
        axes = ("horizontal", "vertical") if slit.has_height else ("horizontal",)
        for axis in axes:
            try:
                by_id(slit_gap_id(slit.stable_id, axis))
            except KeyError:
                errors.append(
                    f"slits: {slit.id!r} needs a stable_id the quantity registry has "
                    f"a {axis} gap for, got {slit.stable_id!r}"
                )

    # --- R6: a stage the TAS runtime drives ---------------------------------------------------------
    # Every runnable instrument runs on instruments/tas_runtime.py, which drives
    # the stage by these axis names (arc fields, McStas parameters).
    # Any other stage is legal as data (structural rules) but refused here, not
    # per point.
    if not d.goniometer:
        errors.append("goniometer: runnable instrument must declare its sample stage")
    else:
        names = tuple(ax.name for ax in d.goniometer)
        if names != _TAS_STAGE_AXES:
            errors.append(
                f"goniometer: a runnable instrument (TAS runtime) must declare the axes "
                f"{', '.join(_TAS_STAGE_AXES)} in that order, got {', '.join(names)}"
            )

    return errors


def assert_valid_descriptor(d: InstrumentDescriptor, *, runnable: bool = False) -> None:
    """Raise ``DescriptorValidationError`` (with all messages) if invalid."""
    errors = validate_descriptor(d, runnable=runnable)
    if errors:
        raise DescriptorValidationError(
            f"Instrument descriptor {d.id!r} failed validation:\n  - "
            + "\n  - ".join(errors)
        )
