"""Independent generated-background sources for TAVI scans.

This Qt-free module is the single background interface used by the GUI,
remote interface, deterministic engine, and Monte Carlo overlay. Background is
planted truth: TAVI never fits or subtracts it.

The wire contract remains ``tavi.background/2``. Catalog version 2 separates
smooth mean sources from sparse event sources and gives the aluminum powder
lines McStas-derived relative strengths. Callers provide one immutable point
context; this module owns all catalog shapes, source scaling, and event
randomness.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np


BACKGROUND_SCHEMA = "tavi.background/2"
CATALOG_VERSION = 2
DEFAULT_SOURCE_SCALE = 1.0
BACKGROUND_STREAM = 0x6B67
BACKGROUND_EVENT_STREAM = 0xC05C
REFERENCE_ENERGY_MEV = 0.0

ALUMINUM_LATTICE_A_ANG = 4.0495
ALUMINUM_REFLECTIONS = (
    # hkl, powder multiplicity j, |F| in sqrt(barn), from McStas Al.laz.
    ((1, 1, 1), 8, 1.32),
    ((2, 0, 0), 6, 1.30),
    ((2, 2, 0), 12, 1.22),
    ((3, 1, 1), 24, 1.17),
    ((2, 2, 2), 8, 1.15),
    ((4, 0, 0), 6, 1.08),
)

CATEGORIES = ("environment", "instrument", "sample")
CATEGORY_LABELS: Mapping[str, str] = MappingProxyType({
    "environment": "Environment",
    "instrument": "Instrument",
    "sample": "Sample",
})
MEAN_SHAPES = (
    "flat",
    "linear_e",
    "powder_elastic",
    "elastic_incoherent",
    "elastic_tail",
)
EVENT_SHAPES = ("cosmic_spike",)
SHAPES = MEAN_SHAPES + EVENT_SHAPES


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-like catalog values."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_safe(value: Any) -> Any:
    """Return a detached JSON-safe view of a frozen catalog value."""
    if isinstance(value, Mapping):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _aluminum_lines() -> Tuple[Mapping[str, Any], ...]:
    scale = 2.0 * math.pi / ALUMINUM_LATTICE_A_ANG
    raw_weights = tuple(
        multiplicity * structure_factor ** 2
        / (scale * math.sqrt(sum(index * index for index in hkl)))
        for hkl, multiplicity, structure_factor in ALUMINUM_REFLECTIONS
    )
    reference_weight = raw_weights[0]
    return tuple(
        MappingProxyType({
            "hkl": tuple(hkl),
            "label": f"Al ({hkl[0]}{hkl[1]}{hkl[2]})",
            "q_inv_ang": scale * math.sqrt(sum(index * index for index in hkl)),
            "multiplicity": multiplicity,
            "structure_factor_sqrt_barn": structure_factor,
            "relative_weight": raw_weight / reference_weight,
        })
        for (
            (hkl, multiplicity, structure_factor),
            raw_weight,
        ) in zip(ALUMINUM_REFLECTIONS, raw_weights)
    )


@dataclass(frozen=True, slots=True)
class BackgroundPointContext:
    """Physics and exposure values needed to evaluate one executed point."""

    q_inv_ang: float
    w_meV: float
    sigma_q_inv_ang: Optional[float]
    sigma_e_meV: Optional[float]
    number_neutrons: float

    def __post_init__(self) -> None:
        q_value = float(self.q_inv_ang)
        w_value = float(self.w_meV)
        neutrons = float(self.number_neutrons)
        if not math.isfinite(q_value) or q_value < 0.0:
            raise ValueError(
                "background |Q| must be finite and >= 0, "
                f"got {q_value!r}"
            )
        if not math.isfinite(w_value):
            raise ValueError(
                f"background energy transfer must be finite, got {w_value!r}"
            )
        if not math.isfinite(neutrons) or neutrons < 0.0:
            raise ValueError(
                "background monitor counts must be finite and >= 0, "
                f"got {neutrons!r}"
            )
        object.__setattr__(self, "q_inv_ang", q_value)
        object.__setattr__(self, "w_meV", w_value)
        object.__setattr__(self, "number_neutrons", neutrons)
        for field_name in ("sigma_q_inv_ang", "sigma_e_meV"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, float(value))


@dataclass(frozen=True, slots=True)
class BackgroundSource:
    """One immutable catalog source definition."""

    source_id: str
    category: str
    label: str
    description: str
    scale_meaning: str
    shape: str
    base_numerics: Mapping[str, Any]
    units: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown background category {self.category!r}")
        if self.shape not in SHAPES:
            raise ValueError(f"unknown background shape {self.shape!r}")
        object.__setattr__(self, "base_numerics", _freeze(self.base_numerics))
        object.__setattr__(self, "units", _freeze(self.units))

    @property
    def is_event(self) -> bool:
        return self.shape in EVENT_SHAPES

    def to_catalog_dict(self) -> Dict[str, Any]:
        """Return the JSON-safe discovery view."""
        return {
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "scale_meaning": self.scale_meaning,
            "shape": self.shape,
            "base_numerics": _json_safe(self.base_numerics),
            "units": _json_safe(self.units),
        }


def _source(
    source_id: str,
    category: str,
    label: str,
    description: str,
    scale_meaning: str,
    shape: str,
    base_numerics: Mapping[str, Any],
    units: Mapping[str, str],
) -> BackgroundSource:
    return BackgroundSource(
        source_id=source_id,
        category=category,
        label=label,
        description=description,
        scale_meaning=scale_meaning,
        shape=shape,
        base_numerics=base_numerics,
        units=units,
    )


SOURCES: Mapping[str, BackgroundSource] = MappingProxyType({
    "environment_flat": _source(
        "environment_flat",
        "environment",
        "Flat floor",
        (
            "Featureless ambient counting floor, assumed independent of "
            "instrument and sample."
        ),
        "Scale multiplies the ambient floor rate.",
        "flat",
        {"rate": 6.0e-10},
        {"rate": "counts per monitor count"},
    ),
    "environment_slope": _source(
        "environment_slope",
        "environment",
        "Energy-dependent slope",
        (
            "Ambient background that falls with energy transfer and clamps to "
            "zero above 40 meV; instrument- and sample-independent."
        ),
        "Scale multiplies the complete energy-dependent ambient rate.",
        "linear_e",
        {"rate0": 2.4e-9, "slope_per_meV": -6.0e-11},
        {
            "rate0": "counts per monitor count at E_ref = 0 meV",
            "slope_per_meV": "counts per monitor count per meV",
        },
    ),
    "environment_cosmic_spikes": _source(
        "environment_cosmic_spikes",
        "environment",
        "Cosmic-ray spikes",
        (
            "Sparse high-count detector events attributed to cosmic rays. "
            "They are planted after ordinary counting noise, including in "
            "noiseless deterministic scans."
        ),
        (
            "Scale changes event incidence only; it does not change the "
            "amplitude distribution of individual spikes."
        ),
        "cosmic_spike",
        {
            "events_per_1e10_monitor": 0.005,
            "amplitude_median_counts": 1000.0,
            "amplitude_log_sigma": 0.8,
            "amplitude_cap_counts": 100000,
        },
        {
            "events_per_1e10_monitor": "expected events per 1e10 monitor counts",
            "amplitude_median_counts": "detector counts per event (log-normal median)",
            "amplitude_log_sigma": "natural-log standard deviation",
            "amplitude_cap_counts": "detector counts per event",
        },
    ),
    "instrument_aluminum_powder": _source(
        "instrument_aluminum_powder",
        "instrument",
        "Aluminum powder lines",
        (
            "Six synthetic fcc-aluminum powder reflections from aluminum "
            "mounting or machinery caught in the beam. Their relative "
            "strengths follow the McStas Al.laz/PowderN j|F|²/Q convention, "
            "normalized to Al (111). At ×1, N=1e8, sigma_E=0.5 meV, and the "
            "Al (111) Q/E center, the source contributes about 500 counts "
            "(about 1% of TAVI's current 50000-count Bragg reference). This "
            "visibility is not transferable or cross-section calibrated, and "
            "Q-E covariance is intentionally ignored."
        ),
        (
            "One scale multiplies all six aluminum lines together, preserving "
            "their McStas-derived relative weights."
        ),
        "powder_elastic",
        {
            "lattice_a_ang": ALUMINUM_LATTICE_A_ANG,
            "lines": _aluminum_lines(),
            "rate_integrated_111": 6.25e-6,
            "sigma_q_fallback_inv_ang": 0.03,
            "sigma_e_fallback_meV": 0.5,
        },
        {
            "lattice_a_ang": "angstrom",
            "lines": (
                "hkl labels, centers in inverse angstrom, powder multiplicity, "
                "|F| in barn^0.5, and dimensionless j|F|^2/Q weight relative "
                "to Al (111)"
            ),
            "rate_integrated_111": (
                "counts per monitor count (integrated over E, meV) at Al (111)"
            ),
            "sigma_q_fallback_inv_ang": "inverse angstrom (Gaussian sigma)",
            "sigma_e_fallback_meV": "meV (Gaussian sigma)",
        },
    ),
    "sample_elastic": _source(
        "sample_elastic",
        "sample",
        "Elastic incoherent line",
        (
            "Resolution-width elastic scattering centered at zero energy and "
            "attributed to the sample."
        ),
        "Scale multiplies the integrated elastic-line rate.",
        "elastic_incoherent",
        {"rate_integrated": 4.5e-9, "sigma_fallback_meV": 0.5},
        {
            "rate_integrated": (
                "counts per monitor count (integrated over E, meV)"
            ),
            "sigma_fallback_meV": (
                "meV (Gaussian sigma used when resolution sigma_E is unavailable)"
            ),
        },
    ),
    "sample_elastic_tail": _source(
        "sample_elastic_tail",
        "sample",
        "Broad elastic tail",
        (
            "Broad Lorentzian tail around zero energy and attributed to the "
            "sample."
        ),
        "Scale multiplies the integrated broad-tail rate.",
        "elastic_tail",
        {"rate_integrated": 6.0e-9, "gamma_meV": 2.0},
        {
            "rate_integrated": (
                "counts per monitor count (integrated over E, meV)"
            ),
            "gamma_meV": "meV (Lorentzian half-width at half-maximum)",
        },
    ),
})


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """Remembered state for one catalog source."""

    source_id: str
    enabled: bool
    scale: float

    @property
    def definition(self) -> BackgroundSource:
        return SOURCES[self.source_id]

    def to_spec_dict(self) -> Dict[str, Any]:
        return {"enabled": bool(self.enabled), "scale": float(self.scale)}


@dataclass(frozen=True, slots=True)
class ResolvedBackground:
    """Complete normalized background configuration."""

    catalog_version: int
    enabled: bool
    sources: Tuple[ResolvedSource, ...]

    def source(self, source_id: str) -> ResolvedSource:
        """Return one normalized source state."""
        if source_id not in SOURCES:
            raise KeyError(source_id)
        return self.sources[tuple(SOURCES).index(source_id)]


def source_catalog() -> Dict[str, Dict[str, Any]]:
    """Return the full JSON-safe catalog keyed by stable source ID."""
    return {
        source_id: source.to_catalog_dict()
        for source_id, source in SOURCES.items()
    }


def default_spec() -> Dict[str, Any]:
    """New-session state: existing smooth mixture prepared behind an off gate."""
    prepared = {
        "environment_flat",
        "environment_slope",
        "sample_elastic",
        "sample_elastic_tail",
    }
    return {
        "catalog_version": CATALOG_VERSION,
        "enabled": False,
        "sources": {
            source_id: {
                "enabled": source_id in prepared,
                "scale": DEFAULT_SOURCE_SCALE,
            }
            for source_id in SOURCES
        },
    }


def normalized_spec(resolved: ResolvedBackground) -> Dict[str, Any]:
    """Return the complete canonical request form."""
    return {
        "catalog_version": int(resolved.catalog_version),
        "enabled": bool(resolved.enabled),
        "sources": {
            state.source_id: state.to_spec_dict()
            for state in resolved.sources
        },
    }


def _validate_scale(value: Any, source_id: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, (int, float, np.floating, np.integer)
    ):
        raise ValueError(
            f"background source {source_id!r} field 'scale' must be a number, "
            f"got {type(value).__name__}"
        )
    scale = float(value)
    if not math.isfinite(scale):
        raise ValueError(
            f"background source {source_id!r} field 'scale' must be finite, "
            f"got {scale!r}"
        )
    if scale < 0.0:
        raise ValueError(
            f"background source {source_id!r} field 'scale' must be >= 0, "
            f"got {scale!r}"
        )
    return scale


def resolve(spec: Optional[Mapping[str, Any]]) -> ResolvedBackground:
    """Validate and normalize one catalog-v2 request.

    Explicit requests must contain exactly ``catalog_version``, ``enabled``,
    and ``sources``. Source entries must contain exactly ``enabled`` and
    ``scale``. Omitted source IDs normalize as disabled at scale 1.0.
    """
    if spec is None:
        spec = default_spec()
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"background spec must be a mapping, got {type(spec).__name__}"
        )
    required = {"catalog_version", "enabled", "sources"}
    unknown = sorted(set(spec) - required)
    missing = sorted(required - set(spec))
    if unknown:
        raise ValueError(
            "unknown background spec field(s) "
            f"{', '.join(unknown)}; allowed fields: "
            "catalog_version, enabled, sources"
        )
    if missing:
        raise ValueError(
            f"background spec is missing required field(s) {', '.join(missing)}"
        )

    version = spec["catalog_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(
            "background 'catalog_version' must be integer "
            f"{CATALOG_VERSION}, got {version!r}"
        )
    if version != CATALOG_VERSION:
        raise ValueError(
            f"background catalog version mismatch: expected {CATALOG_VERSION}, "
            f"got {version}"
        )

    enabled = spec["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError(
            f"background 'enabled' must be a boolean, got {type(enabled).__name__}"
        )
    raw_sources = spec["sources"]
    if not isinstance(raw_sources, Mapping):
        raise ValueError(
            "background 'sources' must be a mapping of source ID to state, "
            f"got {type(raw_sources).__name__}"
        )
    unknown_sources = sorted(set(raw_sources) - set(SOURCES))
    if unknown_sources:
        raise ValueError(
            f"unknown background source(s) {', '.join(unknown_sources)}; "
            f"allowed sources: {', '.join(SOURCES)}"
        )

    states = []
    for source_id in SOURCES:
        raw_state = raw_sources.get(source_id)
        if raw_state is None:
            states.append(
                ResolvedSource(source_id, False, DEFAULT_SOURCE_SCALE)
            )
            continue
        if not isinstance(raw_state, Mapping):
            raise ValueError(
                f"background source {source_id!r} must be a mapping, "
                f"got {type(raw_state).__name__}"
            )
        state_fields = {"enabled", "scale"}
        unknown_state = sorted(set(raw_state) - state_fields)
        missing_state = sorted(state_fields - set(raw_state))
        if unknown_state:
            raise ValueError(
                f"unknown field(s) {', '.join(unknown_state)} for background "
                f"source {source_id!r}; allowed fields: enabled, scale"
            )
        if missing_state:
            raise ValueError(
                f"background source {source_id!r} is missing required field(s) "
                f"{', '.join(missing_state)}"
            )
        source_enabled = raw_state["enabled"]
        if not isinstance(source_enabled, bool):
            raise ValueError(
                f"background source {source_id!r} field 'enabled' must be a "
                f"boolean, got {type(source_enabled).__name__}"
            )
        states.append(
            ResolvedSource(
                source_id=source_id,
                enabled=source_enabled,
                scale=_validate_scale(raw_state["scale"], source_id),
            )
        )
    return ResolvedBackground(
        catalog_version=CATALOG_VERSION,
        enabled=enabled,
        sources=tuple(states),
    )


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _definition_fingerprint_view(definition: BackgroundSource) -> Dict[str, Any]:
    return {
        "category": definition.category,
        "shape": definition.shape,
        "base_numerics": _json_safe(definition.base_numerics),
    }


def profile_fingerprint(resolved: ResolvedBackground) -> str:
    """Identity of all remembered settings and their catalog definitions."""
    return _digest({
        "background_schema": BACKGROUND_SCHEMA,
        **normalized_spec(resolved),
        "definitions": {
            source_id: _definition_fingerprint_view(definition)
            for source_id, definition in SOURCES.items()
        },
    })


def _active_sources(resolved: ResolvedBackground) -> Tuple[ResolvedSource, ...]:
    if not resolved.enabled:
        return ()
    return tuple(
        state
        for state in resolved.sources
        if state.enabled and state.scale > 0.0
    )


def active_mean_sources(
    resolved: ResolvedBackground,
) -> Tuple[ResolvedSource, ...]:
    """Return active smooth sources in stable catalog order."""
    return tuple(
        state for state in _active_sources(resolved)
        if not state.definition.is_event
    )


def active_event_sources(
    resolved: ResolvedBackground,
) -> Tuple[ResolvedSource, ...]:
    """Return active event sources in stable catalog order."""
    return tuple(
        state for state in _active_sources(resolved)
        if state.definition.is_event
    )


def effective_fingerprint(resolved: ResolvedBackground) -> str:
    """Identity of only the source physics actually eligible to plant counts."""
    sources = {}
    for state in _active_sources(resolved):
        sources[state.source_id] = {
            "scale": float(state.scale),
            **_definition_fingerprint_view(state.definition),
        }
    return _digest({
        "background_schema": BACKGROUND_SCHEMA,
        "catalog_version": CATALOG_VERSION,
        "sources": sources,
    })


def _positive_width(value: Optional[float], fallback: float) -> float:
    if value is None:
        return float(fallback)
    width = float(value)
    if not math.isfinite(width) or width <= 0.0:
        return float(fallback)
    return width


def _gaussian_pdf(value: float, sigma: float) -> float:
    """Unit-area Gaussian centered at zero."""
    return float(
        np.exp(-0.5 * (value / sigma) ** 2)
        / (sigma * math.sqrt(2.0 * math.pi))
    )


def _lorentzian_pdf(value: float, gamma: float) -> float:
    """Unit-area Lorentzian centered at zero (gamma is HWHM)."""
    return float(gamma / (math.pi * (value ** 2 + gamma ** 2)))


def source_rate(
    source: BackgroundSource,
    context: BackgroundPointContext,
) -> float:
    """Smooth rate in counts per monitor count for one fixed source."""
    params = source.base_numerics
    if source.shape in EVENT_SHAPES:
        raise ValueError(
            f"event source {source.source_id!r} has no smooth mean rate"
        )
    if source.shape == "flat":
        return float(params["rate"])
    if source.shape == "linear_e":
        value = params["rate0"] + params["slope_per_meV"] * (
            context.w_meV - REFERENCE_ENERGY_MEV
        )
        return max(0.0, float(value))
    if source.shape == "elastic_incoherent":
        sigma_e = _positive_width(
            context.sigma_e_meV, params["sigma_fallback_meV"]
        )
        return float(params["rate_integrated"]) * _gaussian_pdf(
            context.w_meV, sigma_e
        )
    if source.shape == "elastic_tail":
        return float(params["rate_integrated"]) * _lorentzian_pdf(
            context.w_meV, float(params["gamma_meV"])
        )
    if source.shape == "powder_elastic":
        sigma_q = _positive_width(
            context.sigma_q_inv_ang, params["sigma_q_fallback_inv_ang"]
        )
        sigma_e = _positive_width(
            context.sigma_e_meV, params["sigma_e_fallback_meV"]
        )
        q_factor = sum(
            float(line["relative_weight"]) * math.exp(
                -0.5 * (
                    (context.q_inv_ang - float(line["q_inv_ang"])) / sigma_q
                ) ** 2
            )
            for line in params["lines"]
        )
        return (
            float(params["rate_integrated_111"])
            * q_factor
            * _gaussian_pdf(context.w_meV, sigma_e)
        )
    raise ValueError(
        f"unknown background shape {source.shape!r}; "
        f"allowed mean shapes: {', '.join(MEAN_SHAPES)}"
    )


def term_rate(
    source: BackgroundSource,
    context: BackgroundPointContext,
) -> float:
    """Compatibility name for :func:`source_rate`."""
    return source_rate(source, context)


def mean_counts(
    resolved: ResolvedBackground,
    context: BackgroundPointContext,
) -> Tuple[float, Dict[str, float]]:
    """Return ``(total, per_source)`` smooth mean at one executed point."""
    per_source = {
        state.source_id: (
            context.number_neutrons
            * float(state.scale)
            * source_rate(state.definition, context)
        )
        for state in active_mean_sources(resolved)
    }
    return float(sum(per_source.values())), per_source


def poisson_overlay(
    resolved: ResolvedBackground,
    context: BackgroundPointContext,
    seed: int,
    index: int,
    stream: int = BACKGROUND_STREAM,
    rng_factory=np.random.default_rng,
) -> int:
    """Draw the smooth additive overlay from its dedicated RNG stream."""
    mean, _ = mean_counts(resolved, context)
    if mean <= 0.0:
        return 0
    rng = rng_factory((int(seed), int(stream), int(index)))
    return int(rng.poisson(mean))


def stable_source_key(source_id: str) -> int:
    """Stable 32-bit event-stream key for a source ID."""
    digest = hashlib.sha256(source_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big", signed=False)


def draw_event_overlay(
    resolved: ResolvedBackground,
    context: BackgroundPointContext,
    seed: int,
    index: int,
    stream: int = BACKGROUND_EVENT_STREAM,
    rng_factory=np.random.default_rng,
) -> Tuple[int, list[Dict[str, Any]]]:
    """Draw sparse source-keyed events and return counts plus provenance rows."""
    added_total = 0
    realized = []
    if context.number_neutrons <= 0.0:
        return 0, realized

    for state in active_event_sources(resolved):
        source = state.definition
        params = source.base_numerics
        if source.shape != "cosmic_spike":
            raise ValueError(
                f"unknown background event shape {source.shape!r}; "
                f"allowed event shapes: {', '.join(EVENT_SHAPES)}"
            )
        expected_events = (
            float(state.scale)
            * float(params["events_per_1e10_monitor"])
            * context.number_neutrons
            / 1.0e10
        )
        if expected_events <= 0.0:
            continue
        rng = rng_factory((
            int(seed),
            int(stream),
            int(index),
            stable_source_key(state.source_id),
        ))
        event_count = int(rng.poisson(expected_events))
        if event_count <= 0:
            continue
        amplitudes = np.asarray(
            rng.lognormal(
                mean=math.log(float(params["amplitude_median_counts"])),
                sigma=float(params["amplitude_log_sigma"]),
                size=event_count,
            ),
            dtype=float,
        )
        cap = int(params["amplitude_cap_counts"])
        rounded = np.clip(np.rint(amplitudes), 1, cap).astype(np.int64)
        added_counts = int(np.sum(rounded, dtype=np.int64))
        added_total += added_counts
        realized.append({
            "point_index": int(index),
            "source_id": state.source_id,
            "event_count": event_count,
            "added_counts": added_counts,
        })
    return added_total, realized


def metadata_block(
    resolved: ResolvedBackground,
    delivery_source: str,
    background_seed: Optional[int] = None,
    realized_events: Optional[list[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the engine-independent ``tavi.background/2`` provenance block."""
    sources: Dict[str, Dict[str, Any]] = {}
    for state in resolved.sources:
        definition = state.definition
        sources[state.source_id] = {
            "enabled": bool(state.enabled),
            "scale": float(state.scale),
            **definition.to_catalog_dict(),
        }
    block: Dict[str, Any] = {
        "background_schema": BACKGROUND_SCHEMA,
        "catalog_version": CATALOG_VERSION,
        "enabled": bool(resolved.enabled),
        "delivery_source": str(delivery_source),
        "sources": sources,
        "profile_fingerprint": profile_fingerprint(resolved),
        "effective_fingerprint": effective_fingerprint(resolved),
    }
    if background_seed is not None:
        block["background_seed"] = int(background_seed)
    sparse_events = [
        {
            "point_index": int(row["point_index"]),
            "source_id": str(row["source_id"]),
            "event_count": int(row["event_count"]),
            "added_counts": int(row["added_counts"]),
        }
        for row in (realized_events or ())
        if int(row.get("event_count", 0)) > 0
        and int(row.get("added_counts", 0)) > 0
    ]
    if sparse_events:
        block["realized_events"] = sparse_events
    return block
