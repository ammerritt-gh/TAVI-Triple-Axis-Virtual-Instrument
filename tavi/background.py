"""Sample-independent background profiles for TAVI-generated scans.

Pure Python + numpy, no Qt imports -- this module is the single contract both
engines, the API server, and the GUI consume. It owns four things and nothing
else:

* the **term model** (:class:`BackgroundTerm`, the shape/origin/method
  vocabularies and their per-parameter units),
* the **preset registry** (:data:`PRESETS`) plus :func:`resolve`, which turns a
  request spec -- preset+overrides *or* a frozen numeric term list -- into a
  fully numeric :class:`ResolvedBackground`,
* the profile-level **strength knob** ``scale``, one number multiplying every
  term's rate uniformly, so a user dials signal-to-background without editing
  per-term numerics,
* the **identity fingerprints** (:func:`profile_fingerprint`,
  :func:`effective_fingerprint`), which hash the numerics and deliberately not
  the delivery source or the preset label, so a config default and a per-scan
  override describing the same physics are the same background, and
* the **count math** (:func:`mean_counts`) and the shared metadata stamping
  helper (:func:`metadata_block`) that both engines must use, so a scan record
  never depends on which engine produced it.

Backgrounds are *generated truth*: TAVI plants them from configuration and
never infers them from measured data. Term ``origin`` fixes the scaling base --
``instrument`` and ``sample_environment`` terms scale as ``N * rate``, while
``sample`` terms additionally scale by the sample's explicit
``AnalyticCalibration.diffuse_background`` channel, never by the phonon factor.

Background terms are planted *without* resolution convolution: the elastic
Gaussian is written directly at the per-point resolution width ``sigma_E`` (or
a preset fallback when the resolution matrix is invalid), and the elastic tail
is a bare Lorentzian pinned at ``E = 0``.

Every preset is anchored to a **signal-to-background ratio of about 10:1**: the
``Al_phonon_DFT`` sample peaks at ~4e-8 counts per monitor count, so a preset's
characteristic background rate is ~4e-9. ``scale`` moves that anchor without
touching the numbers -- ``scale = 0.1`` is a 100:1 experiment, ``scale = 10`` a
1:1 one. It is applied at *evaluation* time and never folded into the term
params, so a stamped scan record reads "the preset's numbers, times 2.5" rather
than an opaque retuned term list.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np

# Wire-format identity of the background contract. Consumers (ISAR) key on this.
BACKGROUND_SCHEMA = "tavi.background/1"

# Bumped whenever a preset's numerics change, so a stored fingerprint that no
# longer matches a preset name can be explained rather than silently re-tuned.
# v2 (2026-07-27): roster re-anchored to S/N ~10:1 and 'flat_low'/'flat_high'
# merged into a single 'flat' preset, the strength knob having replaced them.
PRESET_REGISTRY_VERSION = 2

# Anchor for every preset magnitude: the Al_phonon_DFT sample peaks at about
# 4 counts per 1e8 neutrons (see tavi/api_server.py limits note), i.e. a peak
# signal rate of ~4e-8 counts per monitor count.
PEAK_SIGNAL_RATE = 4.0e-8

# Default signal-to-background ratio the roster is tuned to at ``scale = 1``:
# a preset's characteristic background rate is PEAK_SIGNAL_RATE / 10.
DEFAULT_SIGNAL_TO_BACKGROUND = 10.0

# The rate every preset is anchored on (4.0e-9 counts per monitor count).
ANCHOR_BACKGROUND_RATE = PEAK_SIGNAL_RATE / DEFAULT_SIGNAL_TO_BACKGROUND

# Neutral value of the profile-level strength knob: multiply nothing.
DEFAULT_SCALE = 1.0

# Origin fixes the scaling base (see module docstring); it is not decoration.
ORIGINS = ("instrument", "sample_environment", "sample")

# ``simulated`` is schema-reserved for a future Monte-Carlo-generated term; v1
# rejects it rather than silently treating it as analytic.
METHODS = ("analytic", "simulated")

SHAPES = ("flat", "linear_e", "elastic_incoherent", "elastic_tail")

# Distinctive stream key for the Monte-Carlo background overlay's per-point RNG,
# seeded as ``(background_seed, BACKGROUND_STREAM, point_index)``. The middle
# element exists so a background draw can never collide with a plain
# ``(seed, index)`` stream (the deterministic engine's signal noise uses that
# two-element form); the value itself is arbitrary but must stay fixed, because
# changing it changes every previously drawn overlay.
BACKGROUND_STREAM = 0x6B67

# Explicit zero point of the linear-in-E shape. Named so nobody has to guess
# whether the slope is anchored at the scan's first point.
REFERENCE_ENERGY_MEV = 0.0

# Per-parameter units, not one blanket string per shape: a reader of a stamped
# scan record must be able to tell counts/monitor from counts/monitor/meV.
PARAMETER_UNITS: Dict[str, Dict[str, str]] = {
    "flat": {
        "rate": "counts per monitor count",
    },
    "linear_e": {
        "rate0": "counts per monitor count at E_ref = 0 meV",
        "slope_per_meV": "counts per monitor count per meV",
    },
    "elastic_incoherent": {
        # Integrated area of the Gaussian: contribution(E) =
        # rate_integrated * N(E; 0, sigma_E), so integrating the planted rate
        # over all E returns rate_integrated exactly.
        "rate_integrated": "counts per monitor count (integrated over E, meV)",
        "sigma_fallback_meV": "meV (Gaussian sigma used when resolution sigma_E is unavailable)",
    },
    "elastic_tail": {
        # Integrated area of the Lorentzian, same convention as above.
        "rate_integrated": "counts per monitor count (integrated over E, meV)",
        "gamma_meV": "meV (Lorentzian half-width at half-maximum)",
    },
}

# Required and defaulted-optional parameters per shape. Anything else is an
# error: a typo'd parameter must never be silently ignored.
_REQUIRED_PARAMS: Dict[str, Tuple[str, ...]] = {
    "flat": ("rate",),
    "linear_e": ("rate0", "slope_per_meV"),
    "elastic_incoherent": ("rate_integrated",),
    "elastic_tail": ("rate_integrated", "gamma_meV"),
}

_DEFAULT_PARAMS: Dict[str, Dict[str, float]] = {
    "flat": {},
    "linear_e": {},
    "elastic_incoherent": {"sigma_fallback_meV": 0.5},
    "elastic_tail": {},
}

# Parameters that may not be negative (a negative rate would subtract counts)
# and parameters that must be strictly positive (widths).
_NON_NEGATIVE_PARAMS = frozenset({"rate", "rate0", "rate_integrated"})
_POSITIVE_PARAMS = frozenset({"sigma_fallback_meV", "gamma_meV"})


class SampleScaleUnavailable(ValueError):
    """A required ``sample``-origin term had no ``diffuse_background`` scale.

    Raised by :func:`mean_counts` when the selected sample carries no explicit
    diffuse-background calibration and the profile contains a non-optional
    sample-origin term. Callers surface this as the validation refusal
    ``sample_background_scale_unavailable``; there is deliberately no implicit
    fallback, because guessing a sample scale would silently invent truth.
    """

    def __init__(self, terms: Sequence[str]):
        self.terms: Tuple[str, ...] = tuple(terms)
        super().__init__(
            "sample-origin background terms require a sample diffuse_background "
            f"calibration, which is unavailable: {', '.join(self.terms)}"
        )


@dataclass(frozen=True, slots=True)
class BackgroundTerm:
    """One additive background component.

    ``params`` is copied into a plain ``dict`` of floats at construction, so a
    term cannot be mutated through the mapping the caller passed in. Frozen
    dataclasses are not hashable with a dict field; identity is carried by the
    fingerprints, not by ``hash()``.
    """

    name: str
    shape: str
    origin: str
    method: str = "analytic"
    params: Dict[str, float] = field(default_factory=dict)
    optional: bool = False

    def __post_init__(self):
        object.__setattr__(self, "params", {k: v for k, v in dict(self.params).items()})

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dict view (fingerprint payload and metadata alike)."""
        return {
            "name": self.name,
            "shape": self.shape,
            "origin": self.origin,
            "method": self.method,
            "params": dict(self.params),
            "optional": bool(self.optional),
        }

    def units(self) -> Dict[str, str]:
        """Per-parameter units for this term's shape."""
        return dict(PARAMETER_UNITS[self.shape])


@dataclass(frozen=True, slots=True)
class ResolvedBackground:
    """A fully numeric background profile.

    ``preset`` is the registry name when the profile came from the preset form
    and ``None`` for the frozen numeric form -- a resolved profile always knows
    whether a label can still explain it. ``overrides_applied`` echoes exactly
    what was merged, so a scan record shows the deviation from the preset
    without the reader having to diff numbers.

    ``scale`` is the profile-level strength knob. It is deliberately *not*
    folded into ``terms``: the terms stay the preset's published numbers and the
    multiplier is reported beside them, so a reader sees "realistic x 2.5"
    instead of a term list nobody can trace back to a preset.
    """

    enabled: bool
    preset: Optional[str]
    overrides_applied: Dict[str, Dict[str, float]]
    terms: Tuple[BackgroundTerm, ...]
    scale: float = DEFAULT_SCALE


def _preset(*terms: BackgroundTerm) -> Tuple[BackgroundTerm, ...]:
    return tuple(terms)


# Preset roster, registry version 2. Every magnitude below is anchored on
# ANCHOR_BACKGROUND_RATE = 4.0e-9 counts per monitor count -- 10% of the
# Al_phonon_DFT peak rate, i.e. a default signal-to-background of 10:1. There is
# deliberately no "low"/"high" variant of any preset: the profile-level ``scale``
# knob covers that axis, so a preset chooses the *character* of a background and
# the knob chooses its strength.
PRESETS: Dict[str, Dict[str, Any]] = {
    "none": {
        "description": "No background terms (enabled or not, this profile plants nothing).",
        "terms": _preset(),
    },
    "flat": {
        "description": (
            "Featureless flat instrument background at 10% of the Al_phonon_DFT peak "
            "rate (signal-to-background 10:1). Use the profile 'scale' knob to make "
            "it weaker or stronger -- there is no separate low/high preset."
        ),
        "terms": _preset(
            BackgroundTerm(
                name="instrument_flat",
                shape="flat",
                origin="instrument",
                # ANCHOR_BACKGROUND_RATE exactly: S/N = 10:1 at scale = 1.
                params={"rate": 4.0e-9},
            ),
        ),
    },
    "sloped": {
        "description": (
            "Flat instrument floor plus a sample-environment term falling linearly "
            "with energy transfer; the slope clamps the term to zero above 25 meV. "
            "Sums to the 10:1 anchor rate at E = 0."
        ),
        "terms": _preset(
            BackgroundTerm(
                name="instrument_flat",
                shape="flat",
                origin="instrument",
                params={"rate": 1.0e-9},
            ),
            BackgroundTerm(
                name="environment_slope",
                shape="linear_e",
                origin="sample_environment",
                # 3.0e-9 + 1.0e-9 = the 4.0e-9 anchor at E = 0; the slope still
                # reaches zero at 25 meV.
                params={"rate0": 3.0e-9, "slope_per_meV": -1.2e-10},
            ),
        ),
    },
    "strong_elastic": {
        "description": (
            "Incoherent elastic line at every q (sample environment) plus a broad "
            "instrument elastic tail. The tail carries the 10:1 anchor rate; the "
            "elastic line is dominant by design, peaking ~30% of the Al_phonon_DFT "
            "peak rate at sigma_E = 0.5 meV."
        ),
        "terms": _preset(
            BackgroundTerm(
                name="environment_elastic",
                shape="elastic_incoherent",
                origin="sample_environment",
                # Peak = rate_integrated / (sigma * sqrt(2 pi)) = 1.2e-8 at
                # sigma = 0.5 meV, i.e. 3x the anchor: the line is meant to dominate.
                params={"rate_integrated": 1.5e-8, "sigma_fallback_meV": 0.5},
            ),
            BackgroundTerm(
                name="instrument_elastic_tail",
                shape="elastic_tail",
                origin="instrument",
                # Peak = rate_integrated / (pi * gamma) = 3.98e-9 at gamma = 2 meV,
                # i.e. the anchor rate.
                params={"rate_integrated": 2.5e-8, "gamma_meV": 2.0},
            ),
        ),
    },
    "sample_diffuse": {
        "description": (
            "Flat diffuse scattering from the sample itself, scaled by the sample's "
            "AnalyticCalibration.diffuse_background channel; optional, so samples "
            "without that calibration skip it instead of refusing the scan."
        ),
        "terms": _preset(
            BackgroundTerm(
                name="sample_diffuse",
                shape="flat",
                origin="sample",
                # Multiplies diffuse_background: 0.4 * 1e-8 = 4.0e-9 counts/monitor
                # for Al_phonon_DFT, i.e. the 10:1 anchor rate.
                params={"rate": 0.4},
                optional=True,
            ),
        ),
    },
    "realistic": {
        "description": (
            "Combination profile: weak flat instrument floor, mild sample-environment "
            "slope, incoherent elastic line, broad elastic tail, and an optional "
            "sample diffuse term. Away from the elastic line the mix sums to about "
            "the 10:1 anchor rate (~3.9e-9 at E = 10 meV with the Al_phonon_DFT "
            "diffuse channel); the elastic line rides above it."
        ),
        "terms": _preset(
            BackgroundTerm(
                name="instrument_flat",
                shape="flat",
                origin="instrument",
                params={"rate": 6.0e-10},
            ),
            BackgroundTerm(
                name="environment_slope",
                shape="linear_e",
                origin="sample_environment",
                params={"rate0": 2.4e-9, "slope_per_meV": -6.0e-11},
            ),
            BackgroundTerm(
                name="environment_elastic",
                shape="elastic_incoherent",
                origin="sample_environment",
                params={"rate_integrated": 4.5e-9, "sigma_fallback_meV": 0.5},
            ),
            BackgroundTerm(
                name="instrument_elastic_tail",
                shape="elastic_tail",
                origin="instrument",
                params={"rate_integrated": 6.0e-9, "gamma_meV": 2.0},
            ),
            BackgroundTerm(
                name="sample_diffuse",
                shape="flat",
                origin="sample",
                # 0.15 * 1e-8 = 1.5e-9 for Al_phonon_DFT.
                params={"rate": 0.15},
                optional=True,
            ),
        ),
    },
}


def _allowed(values: Iterable[str]) -> str:
    return ", ".join(sorted(values))


def _as_float(value: Any, *, term: str, param: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise ValueError(
            f"background term {term!r} parameter {param!r} must be a number, "
            f"got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(
            f"background term {term!r} parameter {param!r} must be finite, got {number!r}"
        )
    return number


def _validate_scale(value: Any) -> float:
    """Check the profile-level strength knob.

    Same rules as a rate parameter -- a number, finite, and not negative, since
    a negative multiplier would subtract counts. Booleans are rejected outright:
    ``True`` silently meaning 1.0 would hide a client bug.
    """
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.floating, np.integer)
    ):
        raise ValueError(
            f"background 'scale' must be a number, got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"background 'scale' must be finite, got {number!r}")
    if number < 0.0:
        raise ValueError(
            "background 'scale' must be >= 0 (a negative scale would subtract "
            f"counts), got {number!r}"
        )
    return number


def _validate_params(shape: str, term_name: str,
                     params: Mapping[str, Any]) -> Dict[str, float]:
    """Return the checked, defaulted numeric parameter set for one term."""
    required = _REQUIRED_PARAMS[shape]
    defaults = _DEFAULT_PARAMS[shape]
    allowed = set(required) | set(defaults)
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ValueError(
            f"unknown parameter(s) {', '.join(unknown)} for background term "
            f"{term_name!r} of shape {shape!r}; allowed parameters: {_allowed(allowed)}"
        )
    missing = [name for name in required if name not in params]
    if missing:
        raise ValueError(
            f"background term {term_name!r} of shape {shape!r} is missing required "
            f"parameter(s) {', '.join(missing)}; required parameters: {_allowed(required)}"
        )
    resolved: Dict[str, float] = dict(defaults)
    for key, value in params.items():
        resolved[key] = _as_float(value, term=term_name, param=key)
    for key, value in resolved.items():
        if key in _NON_NEGATIVE_PARAMS and value < 0.0:
            raise ValueError(
                f"background term {term_name!r} parameter {key!r} must be >= 0 "
                f"(a negative rate would subtract counts), got {value!r}"
            )
        if key in _POSITIVE_PARAMS and value <= 0.0:
            raise ValueError(
                f"background term {term_name!r} parameter {key!r} must be > 0, got {value!r}"
            )
    return resolved


def _validate_term(name: str, shape: Any, origin: Any, method: Any,
                   params: Mapping[str, Any], optional: Any) -> BackgroundTerm:
    if not isinstance(name, str) or not name:
        raise ValueError("every background term needs a non-empty string 'name'")
    if shape not in SHAPES:
        raise ValueError(
            f"unknown background shape {shape!r} for term {name!r}; "
            f"allowed shapes: {_allowed(SHAPES)}"
        )
    if origin not in ORIGINS:
        raise ValueError(
            f"unknown background origin {origin!r} for term {name!r}; "
            f"allowed origins: {_allowed(ORIGINS)}"
        )
    if method not in METHODS:
        raise ValueError(
            f"unknown background method {method!r} for term {name!r}; "
            f"allowed methods: {_allowed(METHODS)}"
        )
    if method != "analytic":
        raise ValueError(
            f"background method {method!r} is reserved by {BACKGROUND_SCHEMA} but not "
            f"implemented for term {name!r}; the only method available in this version "
            f"is 'analytic'"
        )
    if not isinstance(optional, bool):
        raise ValueError(
            f"background term {name!r} field 'optional' must be a boolean, "
            f"got {type(optional).__name__}"
        )
    if not isinstance(params, Mapping):
        raise ValueError(
            f"background term {name!r} field 'params' must be a mapping, "
            f"got {type(params).__name__}"
        )
    return BackgroundTerm(
        name=name,
        shape=shape,
        origin=origin,
        method=method,
        params=_validate_params(shape, name, params),
        optional=optional,
    )


def _resolve_preset_form(spec: Mapping[str, Any], enabled: bool,
                         scale: float) -> ResolvedBackground:
    preset_name = spec.get("preset", "none")
    if not isinstance(preset_name, str) or preset_name not in PRESETS:
        raise ValueError(
            f"unknown background preset {preset_name!r}; "
            f"allowed presets: {_allowed(PRESETS)}"
        )
    overrides = spec.get("overrides", {}) or {}
    if not isinstance(overrides, Mapping):
        raise ValueError(
            f"background 'overrides' must be a mapping of term name -> parameters, "
            f"got {type(overrides).__name__}"
        )
    base_terms = PRESETS[preset_name]["terms"]
    by_name = {term.name: term for term in base_terms}
    unknown = sorted(set(overrides) - set(by_name))
    if unknown:
        raise ValueError(
            f"unknown background term(s) {', '.join(unknown)} in overrides for preset "
            f"{preset_name!r}; allowed terms: "
            f"{_allowed(by_name) if by_name else '(this preset has no terms)'}"
        )
    applied: Dict[str, Dict[str, float]] = {}
    resolved_terms = []
    for term in base_terms:
        override = overrides.get(term.name)
        if override is None:
            resolved_terms.append(term)
            continue
        if not isinstance(override, Mapping):
            raise ValueError(
                f"background override for term {term.name!r} must be a mapping of "
                f"parameter -> number, got {type(override).__name__}"
            )
        # Deep-merge numerics: unspecified parameters keep their preset value.
        merged = dict(term.params)
        merged.update(override)
        resolved = _validate_term(
            term.name, term.shape, term.origin, term.method, merged, term.optional
        )
        resolved_terms.append(resolved)
        applied[term.name] = {
            key: resolved.params[key] for key in override
        }
    return ResolvedBackground(
        enabled=enabled,
        preset=preset_name,
        overrides_applied=applied,
        terms=tuple(resolved_terms),
        scale=scale,
    )


def _resolve_frozen_form(spec: Mapping[str, Any], enabled: bool,
                         scale: float) -> ResolvedBackground:
    raw_terms = spec.get("terms")
    if not isinstance(raw_terms, (list, tuple)):
        raise ValueError(
            f"background 'terms' must be a list of term objects, "
            f"got {type(raw_terms).__name__}"
        )
    terms = []
    seen = set()
    for index, raw in enumerate(raw_terms):
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"background term at index {index} must be a mapping, "
                f"got {type(raw).__name__}"
            )
        allowed_keys = {"name", "shape", "origin", "method", "params", "optional"}
        unknown = sorted(set(raw) - allowed_keys)
        if unknown:
            raise ValueError(
                f"unknown field(s) {', '.join(unknown)} on background term at index "
                f"{index}; allowed fields: {_allowed(allowed_keys)}"
            )
        term = _validate_term(
            raw.get("name", ""),
            raw.get("shape"),
            raw.get("origin"),
            raw.get("method", "analytic"),
            raw.get("params", {}),
            raw.get("optional", False),
        )
        if term.name in seen:
            raise ValueError(f"duplicate background term name {term.name!r}")
        seen.add(term.name)
        terms.append(term)
    return ResolvedBackground(
        enabled=enabled,
        preset=None,
        overrides_applied={},
        terms=tuple(terms),
        scale=scale,
    )


def resolve(spec: Optional[Mapping[str, Any]]) -> ResolvedBackground:
    """Resolve a background request spec into a fully numeric profile.

    Two accepted forms, and only two:

    * **preset form** ``{"enabled": bool, "preset": str, "overrides": {term: {param: value}}}``
      -- overrides deep-merge into the named preset's terms, so an unspecified
      parameter keeps its preset value, and the merge is echoed back in
      ``overrides_applied``.
    * **frozen numeric form** ``{"enabled": bool, "terms": [term dicts]}`` -- the
      self-contained form campaigns stamp onto every scan so they never depend
      on a mutable server-side default or on preset retuning.

    Both forms accept the optional top-level ``"scale"`` (float, finite, >= 0,
    default ``1.0``): the strength knob, applied uniformly to every term's rate
    at evaluation time.

    ``None`` resolves to the disabled ``none`` preset. Every rejection raises
    ``ValueError`` with a message naming the allowed values, which the API layer
    turns into a 400. ``enabled=False`` still resolves and validates the terms,
    so a disabled profile has a meaningful fingerprint.
    """
    if spec is None:
        return ResolvedBackground(
            enabled=False, preset="none", overrides_applied={}, terms=()
        )
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"background spec must be a mapping, got {type(spec).__name__}"
        )
    allowed_keys = {"enabled", "preset", "overrides", "terms", "scale"}
    unknown = sorted(set(spec) - allowed_keys)
    if unknown:
        raise ValueError(
            f"unknown background spec field(s) {', '.join(unknown)}; "
            f"allowed fields: {_allowed(allowed_keys)}"
        )
    if "terms" in spec and ("preset" in spec or "overrides" in spec):
        raise ValueError(
            "background spec mixes the frozen numeric form ('terms') with the preset "
            "form ('preset'/'overrides'); supply exactly one of them"
        )
    enabled_raw = spec.get("enabled", True)
    if not isinstance(enabled_raw, bool):
        raise ValueError(
            f"background 'enabled' must be a boolean, got {type(enabled_raw).__name__}"
        )
    scale = _validate_scale(spec.get("scale", DEFAULT_SCALE))
    if "terms" in spec:
        return _resolve_frozen_form(spec, enabled_raw, scale)
    return _resolve_preset_form(spec, enabled_raw, scale)


def _fingerprint_payload(resolved: ResolvedBackground) -> Dict[str, Any]:
    """Canonical, source-independent payload: schema, enabled flag, numerics.

    Deliberately excludes the preset name and the delivery source -- two specs
    that resolve to identical physics must fingerprint identically whether they
    arrived as a config default or a per-scan override. ``scale`` *is* included:
    a different multiplier is different planted physics, so it must be a
    different background identity.
    """
    return {
        "background_schema": BACKGROUND_SCHEMA,
        "enabled": bool(resolved.enabled),
        "scale": float(resolved.scale),
        "terms": [
            term.to_dict()
            for term in sorted(resolved.terms, key=lambda t: t.name)
        ],
    }


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def profile_fingerprint(resolved: ResolvedBackground) -> str:
    """Stable 16-hex-char identity of the pre-sample-scaling profile numerics."""
    return _digest(_fingerprint_payload(resolved))


def effective_fingerprint(resolved: ResolvedBackground,
                          sample_scale: Optional[float],
                          skipped_terms: Sequence[str] = ()) -> str:
    """Identity of the background as actually applied -- the pooling identity.

    Adds the sample scale that was really used and the set of terms skipped for
    want of one, so two scans that share a profile but differ in effective
    sample scaling never pool together.
    """
    payload = _fingerprint_payload(resolved)
    payload["sample_scale"] = (
        None if sample_scale is None else float(sample_scale)
    )
    payload["skipped"] = sorted(str(name) for name in skipped_terms)
    return _digest(payload)


def _gaussian_pdf(w_meV: float, sigma: float) -> float:
    """Unit-area Gaussian centred at E = 0."""
    return float(
        np.exp(-0.5 * (w_meV / sigma) ** 2) / (sigma * math.sqrt(2.0 * math.pi))
    )


def _lorentzian_pdf(w_meV: float, gamma: float) -> float:
    """Unit-area Lorentzian centred at E = 0 (``gamma`` is the HWHM)."""
    return float(gamma / (math.pi * (w_meV ** 2 + gamma ** 2)))


def term_rate(term: BackgroundTerm, w_meV: float,
              sigma_e_meV: Optional[float] = None) -> float:
    """Rate (counts per monitor count) of one term at energy transfer ``w_meV``.

    ``sigma_e_meV`` is the point's marginalized resolution width; ``None`` (an
    invalid resolution matrix) makes ``elastic_incoherent`` fall back to its
    ``sigma_fallback_meV`` parameter rather than dropping the term.
    """
    params = term.params
    if term.shape == "flat":
        return float(params["rate"])
    if term.shape == "linear_e":
        value = params["rate0"] + params["slope_per_meV"] * (
            float(w_meV) - REFERENCE_ENERGY_MEV
        )
        return max(0.0, float(value))
    if term.shape == "elastic_incoherent":
        sigma = sigma_e_meV
        if sigma is None or not math.isfinite(float(sigma)) or float(sigma) <= 0.0:
            sigma = params["sigma_fallback_meV"]
        return params["rate_integrated"] * _gaussian_pdf(float(w_meV), float(sigma))
    if term.shape == "elastic_tail":
        return params["rate_integrated"] * _lorentzian_pdf(
            float(w_meV), params["gamma_meV"]
        )
    raise ValueError(
        f"unknown background shape {term.shape!r}; allowed shapes: {_allowed(SHAPES)}"
    )


def mean_counts(resolved: ResolvedBackground,
                w_meV: float,
                sigma_e_meV: Optional[float],
                number_neutrons: float,
                sample_scale: Optional[float] = None
                ) -> Tuple[float, Dict[str, float], Tuple[str, ...]]:
    """Mean background counts at one point.

    Returns ``(total, per_term, skipped)``. ``instrument`` and
    ``sample_environment`` terms contribute ``N * rate(E)``; ``sample`` terms
    contribute ``N * sample_scale * rate(E)`` using the sample's explicit
    ``diffuse_background`` channel. A missing ``sample_scale`` skips terms
    declared ``optional`` (recorded in ``skipped``) and raises
    :class:`SampleScaleUnavailable` for the rest -- there is no implicit
    fallback scale. A disabled profile contributes nothing at all.

    The profile-level ``resolved.scale`` multiplies *every* term uniformly,
    whatever its origin or shape -- it is the last factor applied here, and it
    is never folded back into the term parameters.
    """
    if not resolved.enabled:
        return 0.0, {}, ()
    neutrons = float(number_neutrons)
    strength = float(resolved.scale)
    per_term: Dict[str, float] = {}
    skipped: list[str] = []
    missing_required: list[str] = []
    for term in resolved.terms:
        if term.origin == "sample":
            if sample_scale is None:
                (skipped if term.optional else missing_required).append(term.name)
                continue
            scale = neutrons * float(sample_scale)
        else:
            scale = neutrons
        per_term[term.name] = strength * scale * term_rate(term, w_meV, sigma_e_meV)
    if missing_required:
        raise SampleScaleUnavailable(missing_required)
    return float(sum(per_term.values())), per_term, tuple(skipped)


def poisson_overlay(resolved: ResolvedBackground,
                    w_meV: float,
                    sigma_e_meV: Optional[float],
                    number_neutrons: float,
                    sample_scale: Optional[float],
                    seed: int,
                    index: int,
                    stream: int = BACKGROUND_STREAM,
                    rng_factory=np.random.default_rng) -> int:
    """Integer background counts to add to one Monte-Carlo point.

    The Monte-Carlo engine plants background as an *analytic additive Poisson
    overlay* on the ray-traced counts: the mean comes from :func:`mean_counts`,
    the draw from a dedicated per-point stream
    ``rng_factory((seed, stream, index))``. ``stream`` keys that draw away from
    every other ``(seed, index)`` stream in the codebase, so a background draw
    can never consume a signal stream's numbers or vice versa; ``index`` keys it
    per point, so a skipped point never shifts a later point's overlay.

    The profile's ``scale`` reaches the draw through :func:`mean_counts`, so a
    scaled overlay is a differently-drawn overlay, not a rescaled one.

    Zero cost when there is nothing to plant: a disabled profile, ``scale = 0``,
    or any other non-positive mean returns ``0`` **without** constructing an
    RNG, which is what keeps a background-free Monte-Carlo scan bit-identical to
    a pre-background one.

    The draw is always Poisson, never a bare mean added to integer counts --
    ``noiseless`` is a deterministic-engine concept that McStas ignores.
    """
    if not resolved.enabled:
        return 0
    mean, _, _ = mean_counts(
        resolved, w_meV, sigma_e_meV, number_neutrons, sample_scale
    )
    if not math.isfinite(mean) or mean <= 0.0:
        return 0
    rng = rng_factory((int(seed), int(stream), int(index)))
    return int(rng.poisson(mean))


def metadata_block(resolved: ResolvedBackground,
                   source: str,
                   sample_scale: Optional[float] = None,
                   skipped_terms: Sequence[str] = (),
                   background_seed: Optional[int] = None) -> Dict[str, Any]:
    """Build the scan-metadata background block -- the one stamping helper.

    Both engines must call this, so a scan record's background provenance never
    depends on which engine produced it. ``source`` is the delivery tag
    (``config_default`` | ``per_scan_override``); it is recorded but excluded
    from both fingerprints. A disabled profile still stamps a short block --
    absence of background is provenance too.

    ``scale`` is reported beside the terms rather than multiplied into them, so
    the block reads "these preset numbers, times this knob". It appears in the
    disabled short block too, for the same reason ``preset`` does: it is a
    spec-level property of the profile, not a per-term detail.
    """
    profile = profile_fingerprint(resolved)
    effective = effective_fingerprint(resolved, sample_scale, skipped_terms)
    if not resolved.enabled:
        return {
            "background_schema": BACKGROUND_SCHEMA,
            "enabled": False,
            "preset": resolved.preset,
            "scale": float(resolved.scale),
            "source": source,
            "profile_fingerprint": profile,
            "effective_fingerprint": effective,
        }
    terms = []
    for term in resolved.terms:
        entry = term.to_dict()
        entry["units"] = term.units()
        terms.append(entry)
    block: Dict[str, Any] = {
        "background_schema": BACKGROUND_SCHEMA,
        "preset_registry_version": PRESET_REGISTRY_VERSION,
        "enabled": True,
        "preset": resolved.preset,
        "scale": float(resolved.scale),
        "source": source,
        "overrides_applied": {
            name: dict(params)
            for name, params in resolved.overrides_applied.items()
        },
        "terms": terms,
        "parameter_units": {
            shape: dict(units) for shape, units in PARAMETER_UNITS.items()
        },
        "sample_scale": None if sample_scale is None else float(sample_scale),
        "skipped_terms": sorted(str(name) for name in skipped_terms),
        "profile_fingerprint": profile,
        "effective_fingerprint": effective,
    }
    if background_seed is not None:
        block["background_seed"] = int(background_seed)
    return block


def preset_catalog() -> Dict[str, Any]:
    """Registry view for ``GET /schema``: every preset with full numerics."""
    return {
        name: {
            "description": entry["description"],
            "terms": [term.to_dict() for term in entry["terms"]],
        }
        for name, entry in PRESETS.items()
    }
