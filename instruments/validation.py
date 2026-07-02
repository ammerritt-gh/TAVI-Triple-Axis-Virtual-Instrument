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

Error messages are human-readable and prefixed with the offending field/id; they
double as authoring feedback (§11).
"""
from __future__ import annotations

import math
import os
import re

from instruments.descriptor import InstrumentDescriptor, ModuleKind, Sense

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")
_C_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# v1 detector contract (design record §16.9): a single 1-D monitor written to
# detector.dat is the only combination tavi/data_processing.py can read.
_V1_DETECTOR_FILE = "detector.dat"
_V1_DETECTOR_PARSER = "1d_monitor"

# Optional CrystalSpec fields that a *runnable* instrument must fill in.
_CRYSTAL_REQUIRED_FIELDS = (
    "slab_width", "slab_height", "n_columns", "n_rows",
    "gap", "mosaic", "r0", "reflect_file", "transmit_file",
)


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
    for axis, lim in d.axis_limits.items():
        if not all(_finite(v) for v in (lim.lower, lim.default, lim.upper)):
            errors.append(f"axis_limits[{axis!r}]: values must be finite")
        elif not (lim.lower <= lim.default <= lim.upper):
            errors.append(
                f"axis_limits[{axis!r}]: expected lower <= default <= upper, "
                f"got {lim.lower} / {lim.default} / {lim.upper}"
            )

    # --- S11: senses -------------------------------------------------------------------
    for name in ("sense_mono", "sense_sample", "sense_ana"):
        if not isinstance(getattr(g, name), Sense):
            errors.append(f"geometry.{name}: must be a Sense enum member")

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

    return errors


def assert_valid_descriptor(d: InstrumentDescriptor, *, runnable: bool = False) -> None:
    """Raise ``DescriptorValidationError`` (with all messages) if invalid."""
    errors = validate_descriptor(d, runnable=runnable)
    if errors:
        raise DescriptorValidationError(
            f"Instrument descriptor {d.id!r} failed validation:\n  - "
            + "\n  - ".join(errors)
        )
