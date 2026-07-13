"""Phase-0 DRAFT: declarative description of a TAS instrument's GUI-facing knobs.

This is a design sketch for the configurable-instruments effort
(see ``docs/CONFIGURABLE_INSTRUMENTS.md`` §4-§5). **Nothing imports it yet and it
changes no runtime behavior.**

The descriptor is the *only* part of an instrument the GUI binds to: crystals,
samples, monitors, optional modules, collimation, slits, source types, scannable
parameters, geometry, and axis limits. The component tree itself is **not** here --
it stays as imperative Python in each instrument's ``build()`` (decided: instruments
are Python modules, not data files). The descriptor is deliberately small and
serialization-friendly so a JSON export could be added later if ever needed.

Field values in this file's docstrings reference the two reference instruments:
PUMA (``instruments/PUMA_instrument_definition.py``) and IN8
(``examples/vtas_reference/instruments_repository.xml``, from ILL vTAS).

ID convention (review §16.3): every ``id`` is a stable slug used for config keys,
filenames, and Qt ``objectName()``s -- restrict to ``[a-z0-9_]`` (e.g. ``pg002``).
``display_name`` is the free-text label shown in the GUI (e.g. ``PG[002]``). Never
use a display label as an id. (Sample ids are the exception: they intentionally
match the existing PUMA ``sample_key`` strings so the wiring stays 1:1.)

Targets Python 3.11 syntax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Sense(int, Enum):
    """Scattering sense (handedness) at an axis. vTAS records these as sm/ss/sa.

    The value IS the numeric sign of that axis' two-theta readout: LEFT = +1
    means a positive angle (McStas +y rotation, beam deflecting toward +x when
    looking downstream), RIGHT = -1 a negative one. This matches vTAS's
    sm/ss/sa convention exactly. The angle solvers consume these through
    ``TAS_Instrument.sense_mono/sense_sample/sense_ana``; TAVI-PUMA's
    historical behavior is (+1, -1, +1), IN8's verified senses are
    (+1, +1, -1). See §12.5 / §14 / §20.
    """

    LEFT = 1
    RIGHT = -1


class ChangeImpact(str, Enum):
    """What changing a descriptor-controlled setting costs (design record §16.4).

    BUILD: the setting affects McStas topology or component properties fixed at
    build time -- changing it invalidates the compiled binary (recompile).
    RUNTIME: the setting maps to a McStas instrument parameter -- safe to change
    between points/scans without recompiling.

    Groundwork for cross-scan binary reuse: a fingerprint over the BUILD-impact
    state (see ``PUMAPlugin.build_fingerprint``) will let the run loop skip
    ``force_compile`` when nothing build-relevant changed. No consumer yet.
    """

    BUILD = "build"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class Geometry:
    """Fixed arm lengths along the beam, in metres, plus scattering senses.

    vTAS supplies L2/L3/L4 (its srr/arr/drr = DMS/DSA/DAD) but **not** L1; the
    source->mono distance must come from the instrument's own docs because the
    McStas source needs it even though it does not affect angles.
    """

    l1_source_mono: float           # PUMA 2.150; IN8 from docs (vTAS omits)
    l2_mono_sample: float           # PUMA 2.290; IN8 2.5
    l3_sample_ana: float            # PUMA 0.880; IN8 1.35
    l4_ana_det: float               # PUMA 0.750; IN8 0.65
    sense_mono: Sense = Sense.LEFT
    sense_sample: Sense = Sense.LEFT
    sense_ana: Sense = Sense.LEFT
    sample_table_radius: float | None = None    # vTAS str (drawing/physical only)
    analyser_table_radius: float | None = None  # vTAS atr


@dataclass(frozen=True, slots=True)
class AxisLimits:
    """Lower / default / upper travel for an instrument axis, in degrees."""

    lower: float
    default: float
    upper: float


@dataclass(frozen=True, slots=True)
class CrystalSpec:
    """A selectable monochromator or analyser crystal.

    ``d_spacing`` is the only field vTAS records; the rest are the McStas
    ``Monochromator_curved`` slab geometry PUMA needs. The optional fields default
    to ``None`` so a purely-kinematic descriptor (d-spacing only) is still valid --
    useful while IN8's slab geometry is still TODO.
    """

    id: str
    display_name: str
    d_spacing: float                # Angstrom (PG[002] = 3.355)
    slab_width: float | None = None
    slab_height: float | None = None
    n_columns: int | None = None
    n_rows: int | None = None
    gap: float | None = None
    mosaic: float | None = None     # arcmin (horizontal mosaic, FWHM)
    mosaic_v: float | None = None   # arcmin (vertical mosaic, FWHM); None -> use horizontal
    r0: float | None = None
    reflect_file: str | None = None
    transmit_file: str | None = None
    change_impact: ChangeImpact = ChangeImpact.BUILD  # crystal props are baked into build()


@dataclass(frozen=True, slots=True)
class SampleSpec:
    """A selectable sample component: id -> McStas component type + properties.

    ``component_type=None`` represents the "no sample" path (run without a sample
    component). Samples are physical objects moved between instruments, so the
    shared table lives in ``tavi/sample_library.py`` and instruments mount it
    (``samples=default_sample_library()``) rather than owning their own copies;
    an instrument may still filter or extend the tuple (design record §19).
    """

    id: str
    display_name: str
    component_type: str | None
    properties: dict = field(default_factory=dict)
    split: int | None = None        # McStas SPLIT
    extend: str | None = None       # McStas EXTEND snippet
    component_name: str | None = None   # McStas instance name (None -> use id)
    # Sample's own lattice (a, b, c, alpha, beta, gamma); the GUI adopts it into
    # the lattice fields on user sample selection so instrument angles match the
    # component's internal crystal (e.g. Phonon_DFT bakes a=4.03893).
    lattice: tuple[float, float, float, float, float, float] | None = None
    # Optional crystallographic display data.  It is intentionally separate
    # from ``properties``: GUI code must not infer reflection provenance from a
    # McStas component's arbitrary parameter dictionary.
    reflection_source: str | None = None
    space_group: int | None = None
    change_impact: ChangeImpact = ChangeImpact.BUILD  # sample choice changes the tree


@dataclass(frozen=True, slots=True)
class MonitorSpec:
    """An optional diagnostic monitor. Replaces the literal ``DIAGNOSTIC_OPTIONS``.

    The GUI only needs ``id`` / ``component_type`` / ``tags`` (checkboxes + quick-
    select groups). The placement fields (``at`` / ``rotated`` / ``relative`` /
    ``settings``) are **build data** kept here only so one definition feeds both the
    GUI toggle and ``build()``'s placement loop, avoiding drift. This is the one
    sanctioned exception to "the descriptor is GUI-facing only" (review §16.5):
    monitors are genuinely both a GUI toggle and a uniformly-placed component, so
    co-locating beats splitting them into two tables that could disagree.
    """

    id: str                         # GUI label and diagnostic-settings key
    component_type: str             # E_monitor, PSD_monitor, Divergence_monitor, ...
    at: tuple[float, float, float]
    relative: str
    rotated: tuple[float, float, float] = (0.0, 0.0, 0.0)
    settings: dict = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    component_name: str | None = None   # McStas component instance name in build()


class ModuleKind(str, Enum):
    CHOICE = "choice"   # pick one option (e.g. NMO None/Vertical/Horizontal/Both)
    TOGGLE = "toggle"   # on/off (e.g. velocity selector)


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    """An optional module that changes the component tree (adds/removes components).

    Changing one of these generally forces recompilation; ``change_impact``
    documents that for the GUI. PUMA: NMO (CHOICE), velocity selector (TOGGLE).
    IN8: FlatCone / IMPS exist but are multi-detector and **deferred** past v1.
    """

    id: str
    display_name: str
    kind: ModuleKind
    options: tuple[str, ...] = ()           # for CHOICE
    default: str | bool = False
    change_impact: ChangeImpact = ChangeImpact.BUILD  # modules add/remove components


@dataclass(frozen=True, slots=True)
class CollimationSlot:
    """A collimation position with selectable divergence value(s), in arcmin."""

    id: str
    label: str
    allowed: tuple[str, ...]                # e.g. ("0", "20", "40", "60")
    multi_select: bool = False              # PUMA alpha_2 stacks several in series
    default: str = "0"
    change_impact: ChangeImpact = ChangeImpact.BUILD  # divergence/gating fixed at build


@dataclass(frozen=True, slots=True)
class SlitSpec:
    """A scannable slit aperture (entered in mm in the GUI, metres in McStas)."""

    id: str                                 # maps to a scannable parameter
    label: str
    has_width: bool = True
    has_height: bool = False
    default_width_mm: float | None = None
    default_height_mm: float | None = None
    change_impact: ChangeImpact = ChangeImpact.RUNTIME  # slits are McStas parameters


@dataclass(frozen=True, slots=True)
class SourceType:
    """A selectable source model (PUMA: Maxwellian, Mono)."""

    id: str
    display_name: str
    extra_params: tuple[str, ...] = ()      # e.g. ("source_dE",) for Mono
    change_impact: ChangeImpact = ChangeImpact.BUILD  # source model is a build choice


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """A McStas instrument parameter that ``build()`` declares and the per-point
    snapshot fills.

    The collection of these **is** the per-point parameter-dict shape. Keeping it
    in the descriptor (instead of hard-coding PUMA's keys in the contract) is what
    stops the framework being PUMA-shaped -- see §12.5.
    """

    name: str                               # e.g. "A1_param"
    comment: str = ""
    default: float | None = None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class InstrumentDescriptor:
    """Everything the GUI needs to render itself for one instrument.

    Required fields first; everything optional defaults to empty so a minimal
    instrument is easy to declare. ``axis_limits`` is keyed by TAVI angle name
    ("A1" = mono 2theta, "A2" = sample 2theta, "A4" = analyser 2theta); note vTAS
    names the same axes a2/a4/a6.
    """

    id: str
    display_name: str
    geometry: Geometry
    mono_crystals: tuple[CrystalSpec, ...]
    ana_crystals: tuple[CrystalSpec, ...]
    samples: tuple[SampleSpec, ...]
    scannable_parameters: tuple[ParameterSpec, ...]
    primary_detector: str                   # component that writes the detector file
    # Detector output contract (review §16.9): name the file build() guarantees and
    # how tavi/data_processing.py should read it. v1 only supports a single 1-D
    # monitor written to detector.dat; richer/multi-detector output is deferred.
    detector_output_file: str = "detector.dat"
    detector_parser: str = "1d_monitor"
    monitors: tuple[MonitorSpec, ...] = ()
    modules: tuple[ModuleSpec, ...] = ()
    collimation: tuple[CollimationSlot, ...] = ()
    slits: tuple[SlitSpec, ...] = ()
    source_types: tuple[SourceType, ...] = ()
    axis_limits: dict[str, AxisLimits] = field(default_factory=dict)
    institute: str = ""
    description: str = ""
    component_path: str | None = None        # extra McStas input_path for custom comps
    mcstas_name: str | None = None           # e.g. "PUMA_McScript"; default derives from id
    # Per-instrument vertical (out-of-plane) Soller divergences BET1..BET4 in
    # arcmin (FWHM), consumed by the theoretical resolution adapter
    # (``resolution_config``). vTAS payloads and the McStas definitions do not
    # record per-blade vertical Soller data, so these are documented defaults
    # (the adapter records the source as "descriptor default" in provenance).
    # None -> the adapter falls back to a uniform 120 arcmin default.
    vertical_divergence: tuple[float, float, float, float] | None = None
