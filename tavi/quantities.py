"""TAVI's one registry of public quantity names: canonical IDs, aliases, units and flags.

Scan commands and API writes resolve names through resolve(). Aliases import
names only: no other facility's encoder signs or zero offsets are applied here.
Qt-free and stdlib-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

API_VERSION = 2   # every mutating API request names it; it marks the A2/A4/A6 renumbering
LATTICE_REFUSAL = "lattice parameters are set over the API, never scanned"
APPLIED_REFUSAL = "applied radii are derived by the take-off branch; no input sets them"


class QuantityRefused(ValueError):
    """A name that cannot be used in this context; str() is the user-facing refusal."""


class UnknownQuantity(QuantityRefused):
    """A name that is in no row of the registry and not a retired name either."""


@dataclass(frozen=True)
class Quantity:
    id: str                         # canonical ID: saved state, API output, metadata
    unit: str
    label: str                      # GUI label text
    description: str                # physical meaning
    convention: str                 # sign, frame or zero convention
    aliases: tuple[str, ...] = ()   # case-insensitive input names
    scannable: bool = False         # may be a scan command
    writable: bool = False          # may be set over the API or in a dock
    derived_only: bool = False      # an observable no input may set
    refusal: str = ""               # message when a context's flags refuse it
    write_refusal: str = ""         # the same for an API write, where "scan" would mislead
    ill: str = ""                   # ILL A-number, angles only
    nicos: str = ""                 # NICOS motor name, angles only
    name: str = ""                  # the quantity in a message: "A4 (sample 2θ)", "H"


def crystal_theta(two_theta):
    """A crystal's θ from its 2θ (θ = 2θ/2, signed as 2θ): the one producer of A1 and A5.

    The point plan's ``crystal_theta`` rule, the four models' crystal rotation and every
    curvature branch and autofocus call it; a rocking rule may replace it one day.
    """
    return two_theta / 2


def slit_gap_id(stable_id: str, axis: str) -> str:
    """The canonical ID of one slit gap; ``axis`` is "horizontal" or "vertical"."""
    return f"slit.{stable_id}.{axis}_gap_mm"


def slit_gap_ids(slit) -> tuple[str, ...]:
    """A descriptor SlitSpec's gap IDs: horizontal, and vertical where it has a height."""
    axes = ("horizontal", "vertical") if slit.has_height else ("horizontal",)
    return tuple(slit_gap_id(slit.stable_id, axis) for axis in axes)


_SLITS = (("post_mono", "Post-mono"), ("pre_sample", "Pre-sample"), ("detector", "Detector"),
          ("virtual_source", "Virtual source"), ("sample_exit", "Sample-exit"))
_SLIT_ROWS = tuple(
    Quantity(slit_gap_id(sid, axis), "mm", f"{name} slit {axis} gap (mm)",
             f"{axis} gap of the {name.lower()} slit", "full gap width, millimetres",
             aliases=(f"{sid}_{short}gap",), scannable=True, writable=True,
             name=f"{name.lower()} slit {axis} gap")
    for sid, name in _SLITS
    for axis, short in (("horizontal", "h"), ("vertical", "v"))
)

QUANTITIES: tuple[Quantity, ...] = (
    Quantity("mono_theta_deg", "°", "Mono θ — A1 (°)", "monochromator Bragg angle, θ = 2θ/2",
             "derived: A1 = A2/2, signed as A2", aliases=("A1", "mth"), derived_only=True,
             refusal="independent crystal rocking is not modelled yet; scan A2 (mono 2θ)",
             write_refusal="independent crystal rocking is not modelled yet; set A2 (mono 2θ)",
             ill="A1", nicos="mth", name="A1 (mono θ)"),
    Quantity("mono_two_theta_deg", "°", "Mono 2θ — A2 (°)", "monochromator scattering angle 2θ",
             "signed as the diffraction angle", aliases=("A2", "mtt"), scannable=True,
             writable=True, ill="A2", nicos="mtt", name="A2 (mono 2θ)"),
    Quantity("sample_rotation_deg", "°", "Sample rotation — A3 (°)",
             "sample turntable rotation about the vertical axis; not a Bragg angle",
             "sets the sample orientation", aliases=("A3", "sth", "omega", "psi"),
             scannable=True, writable=True, ill="A3", nicos="sth",
             name="A3 (sample rotation)"),
    Quantity("sample_two_theta_deg", "°", "Sample 2θ — A4 (°)", "scattering angle at the sample",
             "signed as the diffraction angle", aliases=("A4", "stt", "2theta"),
             scannable=True, writable=True, ill="A4", nicos="stt", name="A4 (sample 2θ)"),
    Quantity("analyzer_theta_deg", "°", "Analyzer θ — A5 (°)", "analyzer Bragg angle, θ = 2θ/2",
             "derived: A5 = A6/2, signed as A6", aliases=("A5", "ath"), derived_only=True,
             refusal="independent crystal rocking is not modelled yet; scan A6 (analyzer 2θ)",
             write_refusal="independent crystal rocking is not modelled yet; set A6 (analyzer 2θ)",
             ill="A5", nicos="ath", name="A5 (analyzer θ)"),
    Quantity("analyzer_two_theta_deg", "°", "Analyzer 2θ — A6 (°)", "analyzer scattering angle 2θ",
             "signed as the diffraction angle", aliases=("A6", "att"), scannable=True,
             writable=True, ill="A6", nicos="att", name="A6 (analyzer 2θ)"),
    Quantity("sample_lower_arc_deg", "°", "Lower arc sgl (°)", "lower sample tilt arc",
             "tilt of the sample stage; not a four-circle chi", aliases=("sgl",),
             scannable=True, writable=True, nicos="sgl", name="sgl (lower arc)"),
    Quantity("sample_upper_arc_deg", "°", "Upper arc sgu (°)", "upper sample tilt arc",
             "tilt of the sample stage; not a four-circle chi", aliases=("sgu",),
             scannable=True, writable=True, nicos="sgu", name="sgu (upper arc)"),
    Quantity("h", "r.l.u.", "H (r.l.u.)", "Miller index h", "reciprocal-lattice units",
             aliases=("H",), scannable=True, writable=True, name="H"),
    Quantity("k", "r.l.u.", "K (r.l.u.)", "Miller index k", "reciprocal-lattice units",
             aliases=("K",), scannable=True, writable=True, name="K"),
    Quantity("l", "r.l.u.", "L (r.l.u.)", "Miller index l", "reciprocal-lattice units",
             aliases=("L",), scannable=True, writable=True, name="L"),
    Quantity("q_instrument_x_inv_angstrom", "Å⁻¹", "Q x, instrument frame (Å⁻¹)",
             "momentum transfer, x component", "public Q frame; z is vertical",
             aliases=("qx",), scannable=True, writable=True, name="Q x"),
    Quantity("q_instrument_y_inv_angstrom", "Å⁻¹", "Q y, instrument frame (Å⁻¹)",
             "momentum transfer, y component", "public Q frame; z is vertical",
             aliases=("qy",), scannable=True, writable=True, name="Q y"),
    Quantity("q_instrument_z_inv_angstrom", "Å⁻¹", "Q z, instrument frame (Å⁻¹)",
             "momentum transfer, z component", "public Q frame; z is vertical",
             aliases=("qz",), scannable=True, writable=True, name="Q z"),
    Quantity("energy_transfer_mev", "meV", "Energy transfer ΔE (meV)",
             "energy the sample takes from the neutron, Ei − Ef",
             "positive = neutron energy loss (ki > kf)", aliases=("deltaE",),
             scannable=True, writable=True, name="ΔE (energy transfer)"),
    Quantity("incident_energy_mev", "meV", "Incident energy Ei (meV)",
             "neutron energy before the sample", "E = ħ²k²/2m, as Ki", aliases=("Ei",),
             writable=True, name="Ei"),
    Quantity("final_energy_mev", "meV", "Final energy Ef (meV)",
             "neutron energy after the sample", "E = ħ²k²/2m, as Kf", aliases=("Ef",),
             writable=True, name="Ef"),
    Quantity("incident_wavevector_inv_angstrom", "Å⁻¹", "Incident wavevector Ki (Å⁻¹)",
             "neutron wavevector magnitude before the sample", "|k| = 2π/λ", aliases=("Ki",),
             writable=True, name="Ki"),
    Quantity("final_wavevector_inv_angstrom", "Å⁻¹", "Final wavevector Kf (Å⁻¹)",
             "neutron wavevector magnitude after the sample", "|k| = 2π/λ", aliases=("Kf",),
             writable=True, name="Kf"),
    Quantity("mono_horizontal_radius_m", "m", "Mono horizontal radius (m)",
             "requested horizontal bending radius of the monochromator", "requested magnitude; 0 = flat",
             aliases=("rhm",), scannable=True, writable=True,
             name="rhm (mono horizontal radius)"),
    Quantity("mono_vertical_radius_m", "m", "Mono vertical radius (m)",
             "requested vertical bending radius of the monochromator", "requested magnitude; 0 = flat",
             aliases=("rvm",), scannable=True, writable=True,
             name="rvm (mono vertical radius)"),
    Quantity("analyzer_horizontal_radius_m", "m", "Analyzer horizontal radius (m)",
             "requested horizontal bending radius of the analyzer", "requested magnitude; 0 = flat",
             aliases=("rha",), scannable=True, writable=True,
             name="rha (analyzer horizontal radius)"),
    Quantity("analyzer_vertical_radius_m", "m", "Analyzer vertical radius (m)",
             "requested vertical bending radius of the analyzer", "requested magnitude; 0 = flat",
             aliases=("rva",), scannable=True, writable=True,
             name="rva (analyzer vertical radius)"),
    Quantity("applied_mono_horizontal_radius_m", "m", "Applied mono horizontal radius (m)",
             "horizontal radius applied to the monochromator", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL, name="applied mono horizontal radius"),
    Quantity("applied_mono_vertical_radius_m", "m", "Applied mono vertical radius (m)",
             "vertical radius applied to the monochromator", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL, name="applied mono vertical radius"),
    Quantity("applied_analyzer_horizontal_radius_m", "m", "Applied analyzer horizontal radius (m)",
             "horizontal radius applied to the analyzer", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL, name="applied analyzer horizontal radius"),
    Quantity("applied_analyzer_vertical_radius_m", "m", "Applied analyzer vertical radius (m)",
             "vertical radius applied to the analyzer", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL, name="applied analyzer vertical radius"),
    *_SLIT_ROWS,
    Quantity("lattice_a_angstrom", "Å", "Lattice a (Å)", "sample lattice parameter a",
             "API writes only", aliases=("a",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice a"),
    Quantity("lattice_b_angstrom", "Å", "Lattice b (Å)", "sample lattice parameter b",
             "API writes only", aliases=("b",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice b"),
    Quantity("lattice_c_angstrom", "Å", "Lattice c (Å)", "sample lattice parameter c",
             "API writes only", aliases=("c",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice c"),
    Quantity("lattice_alpha_deg", "°", "Lattice alpha (°)", "sample lattice angle alpha",
             "API writes only", aliases=("alpha",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice alpha"),
    Quantity("lattice_beta_deg", "°", "Lattice beta (°)", "sample lattice angle beta",
             "API writes only", aliases=("beta",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice beta"),
    Quantity("lattice_gamma_deg", "°", "Lattice gamma (°)", "sample lattice angle gamma",
             "API writes only", aliases=("gamma",), writable=True, refusal=LATTICE_REFUSAL,
             name="lattice gamma"),
)

# Old metre-valued slit names, refused with their millimetre replacement.
_OLD_SLITS = {
    "vbl_hgap": "post_mono_hgap",
    "pbl_hgap": "pre_sample_hgap", "pbl_vgap": "pre_sample_vgap",
    "dbl_hgap": "detector_hgap",
    "sbl_wgap": "pre_sample_hgap", "sbl_hgap": "pre_sample_vgap",
    "ms1_wgap": "virtual_source_hgap",
    "ss1_wgap": "pre_sample_hgap", "ss1_hgap": "pre_sample_vgap",
    "ss2_wgap": "sample_exit_hgap", "ss2_hgap": "sample_exit_vgap",
}
_RETIRED = {
    "chi": "chi is a four-circle tilt axis that TAVI does not model; its sample tilt arcs are sgl and sgu",
    "phi": "phi is a diffraction-goniometer axis that TAVI does not have",
    "kappa": "kappa is a diffraction-goniometer axis that TAVI does not have",
    **{old: f"{old} is retired: it was in metres; use {new}, which is in millimetres"
       for old, new in _OLD_SLITS.items()},
    "slits_mm": "slits_mm is retired: set each gap by its own key, "
                "slit.<stable_id>.horizontal_gap_mm or .vertical_gap_mm (millimetres)",
    **{f"lattice_{axis}": f"lattice_{axis} is retired: use lattice_{axis}_{unit} (or {axis})"
       for axis, unit in (("a", "angstrom"), ("b", "angstrom"), ("c", "angstrom"),
                          ("alpha", "deg"), ("beta", "deg"), ("gamma", "deg"))},
}


def index_table(table: Sequence[Quantity]) -> dict[str, Quantity]:
    """Index every canonical ID and alias by case-folded name; raise ValueError on a collision."""
    by_id: dict[str, Quantity] = {}
    for q in table:
        if q.id.casefold() in by_id:
            raise ValueError(f"canonical IDs collide: {q.id}")
        by_id[q.id.casefold()] = q
    index = dict(by_id)
    owner: dict[str, Quantity] = {}
    for q in table:
        for alias in q.aliases:
            key = alias.casefold()
            if key in by_id:
                if by_id[key] is not q:
                    raise ValueError(f"alias {alias!r} of {q.id} is the canonical ID of {by_id[key].id}")
                continue
            if key in owner:
                raise ValueError(f"alias {alias!r} is on both {owner[key].id} and {q.id}")
            owner[key] = index[key] = q
    return index


_INDEX = index_table(QUANTITIES)
_BY_ID = {q.id: q for q in QUANTITIES}
_VERB = {"scan": "scanned", "write": "set"}


def by_id(canonical_id: str) -> Quantity:
    return _BY_ID[canonical_id]


# GET /schema publishes ASCII unit spellings; the registry keeps the typographic ones.
_SCHEMA_UNIT = {"°": "degrees", "Å⁻¹": "angstrom^-1", "Å": "angstrom"}


def schema_unit(canonical_id: str):
    """A registry quantity's unit in the schema's spelling; None when no row has this ID."""
    q = _BY_ID.get(canonical_id)
    return None if q is None else _SCHEMA_UNIT.get(q.unit, q.unit)


def resolve(name: str, context: str) -> Quantity:
    """Return the quantity a name means as a scan command ("scan") or API write ("write")."""
    key = name.casefold()
    q = _INDEX.get(key)
    if q is None:
        if key in _RETIRED:
            raise QuantityRefused(_RETIRED[key])
        raise UnknownQuantity(f"unknown quantity {name!r}")
    if q.derived_only or not {"scan": q.scannable, "write": q.writable}[context]:
        raise QuantityRefused((q.write_refusal if context == "write" else "") or q.refusal
                              or f"{q.id} cannot be {_VERB[context]}")
    return q


# Interim (U3 deletes the internal names): the field the controller, the plugins and the
# frozen parameter dict still use for each public quantity. Slit gaps are not here: their
# internal form is the nested slits_mm dict, flattened by public_values().
_INTERNAL = {
    "mono_two_theta_deg": "mtt", "sample_two_theta_deg": "stt", "sample_rotation_deg": "omega",
    "analyzer_two_theta_deg": "att", "sample_lower_arc_deg": "sgl", "sample_upper_arc_deg": "sgu",
    "h": "H", "k": "K", "l": "L",
    "q_instrument_x_inv_angstrom": "qx", "q_instrument_y_inv_angstrom": "qy",
    "q_instrument_z_inv_angstrom": "qz", "energy_transfer_mev": "deltaE",
    "incident_energy_mev": "Ei", "final_energy_mev": "Ef",
    "incident_wavevector_inv_angstrom": "Ki", "final_wavevector_inv_angstrom": "Kf",
    "mono_horizontal_radius_m": "rhm", "mono_vertical_radius_m": "rvm",
    "analyzer_horizontal_radius_m": "rha", "analyzer_vertical_radius_m": "rva",
    "lattice_a_angstrom": "lattice_a", "lattice_b_angstrom": "lattice_b",
    "lattice_c_angstrom": "lattice_c", "lattice_alpha_deg": "lattice_alpha",
    "lattice_beta_deg": "lattice_beta", "lattice_gamma_deg": "lattice_gamma",
}
_PUBLIC = {internal: canonical for canonical, internal in _INTERNAL.items()}


def to_internal(canonical_id: str) -> str:
    return _INTERNAL.get(canonical_id, canonical_id)


def to_public(internal_name: str) -> str:
    return _PUBLIC.get(internal_name, internal_name)


def public_applied_radii(applied: dict) -> dict:
    """A point's applied radii ({"rhm": ...}) under their derived-only canonical IDs."""
    return {"applied_" + to_public(axis): value for axis, value in applied.items()}


def public_values(vals: dict, slits=()) -> dict:
    """An internal parameter dict under canonical IDs; names that are no quantity pass through.

    ``slits`` are the active descriptor's SlitSpecs (id, stable_id, has_height): the nested
    ``slits_mm`` becomes one flat key per gap, and only this instrument's own appear.
    """
    out = {}
    for key, value in vals.items():
        if key == "slits_mm":
            for slit in slits:
                if slit.id not in value:
                    continue
                gaps = value[slit.id]
                out.update(zip(slit_gap_ids(slit), gaps if slit.has_height else (gaps,),
                               strict=True))
        elif key == "curvature_modes":
            out[key] = {to_public(axis): mode for axis, mode in value.items()}
        elif key == "curvature_clamped":
            out[key] = [to_public(axis) for axis in value]
        else:
            out[to_public(key)] = value
    return out


def normalize_write_names(names, accept):
    """Resolve the names of one API write; return ({name: key}, {name: refusal}).

    ``accept`` is every key the caller can set: canonical IDs of quantities it has plus the
    exact names of its other settings. Any refusal means the whole request is refused: a
    retired, unknown, derived or absent name, or two names for one quantity (both reported).
    """
    settings = set(accept) - _BY_ID.keys()
    keys, errors, first = {}, {}, {}
    for name in names:
        if name in settings:
            key = name
        else:
            try:
                key = resolve(name, "write").id
            except UnknownQuantity:
                errors[name] = "unknown field"
                continue
            except QuantityRefused as exc:
                errors[name] = str(exc)
                continue
            if key not in accept:
                errors[name] = f"{key} does not exist on this instrument"
                continue
        if key in first:
            errors[name] = errors[first[key]] = (
                f"{key} is assigned twice, as {first[key]!r} and {name!r}; send it once")
            continue
        first[key] = name
        keys[name] = key
    return keys, errors
