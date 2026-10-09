"""TAVI's one registry of public quantity names: canonical IDs, aliases, units and flags.

Scan commands and API writes resolve names through resolve(). Aliases import
names only: no other facility's encoder signs or zero offsets are applied here.
Qt-free and stdlib-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

SLIT_SCAN_REFUSAL = "slit scans arrive with the point plan"
LATTICE_REFUSAL = "lattice parameters are set over the API, never scanned"
APPLIED_REFUSAL = "applied radii are derived by the take-off branch; no input sets them"


class QuantityRefused(ValueError):
    """A name that cannot be used in this context; str() is the user-facing refusal."""


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
    ill: str = ""                   # ILL A-number, angles only
    nicos: str = ""                 # NICOS motor name, angles only


_SLITS = (("post_mono", "Post-mono"), ("pre_sample", "Pre-sample"), ("detector", "Detector"),
          ("virtual_source", "Virtual source"), ("sample_exit", "Sample-exit"))
_SLIT_ROWS = tuple(
    Quantity(f"slit.{sid}.{axis}_gap_mm", "mm", f"{name} slit {axis} gap (mm)",
             f"{axis} gap of the {name.lower()} slit", "full gap width, millimetres",
             aliases=(f"{sid}_{short}gap",), writable=True, refusal=SLIT_SCAN_REFUSAL)
    for sid, name in _SLITS
    for axis, short in (("horizontal", "h"), ("vertical", "v"))
)

QUANTITIES: tuple[Quantity, ...] = (
    Quantity("mono_theta_deg", "°", "Mono θ — A1 (°)", "monochromator Bragg angle, θ = 2θ/2",
             "derived: A1 = A2/2, signed as A2", aliases=("A1", "mth"), derived_only=True,
             refusal="independent crystal rocking is not modelled yet; scan A2 (mono 2θ)",
             ill="A1", nicos="mth"),
    Quantity("mono_two_theta_deg", "°", "Mono 2θ — A2 (°)", "monochromator scattering angle 2θ",
             "signed as the diffraction angle", aliases=("A2", "mtt"), scannable=True,
             writable=True, ill="A2", nicos="mtt"),
    Quantity("sample_rotation_deg", "°", "Sample rotation — A3 (°)",
             "sample turntable rotation about the vertical axis; not a Bragg angle",
             "sets the sample orientation", aliases=("A3", "sth", "omega", "psi"),
             scannable=True, writable=True, ill="A3", nicos="sth"),
    Quantity("sample_two_theta_deg", "°", "Sample 2θ — A4 (°)", "scattering angle at the sample",
             "signed as the diffraction angle", aliases=("A4", "stt", "2theta"),
             scannable=True, writable=True, ill="A4", nicos="stt"),
    Quantity("analyzer_theta_deg", "°", "Analyzer θ — A5 (°)", "analyzer Bragg angle, θ = 2θ/2",
             "derived: A5 = A6/2, signed as A6", aliases=("A5", "ath"), derived_only=True,
             refusal="independent crystal rocking is not modelled yet; scan A6 (analyzer 2θ)",
             ill="A5", nicos="ath"),
    Quantity("analyzer_two_theta_deg", "°", "Analyzer 2θ — A6 (°)", "analyzer scattering angle 2θ",
             "signed as the diffraction angle", aliases=("A6", "att"), scannable=True,
             writable=True, ill="A6", nicos="att"),
    Quantity("sample_lower_arc_deg", "°", "Lower arc sgl (°)", "lower sample tilt arc",
             "tilt of the sample stage; not a four-circle chi", aliases=("sgl",),
             scannable=True, writable=True),
    Quantity("sample_upper_arc_deg", "°", "Upper arc sgu (°)", "upper sample tilt arc",
             "tilt of the sample stage; not a four-circle chi", aliases=("sgu",),
             scannable=True, writable=True),
    Quantity("h", "r.l.u.", "H (r.l.u.)", "Miller index h", "reciprocal-lattice units",
             aliases=("H",), scannable=True, writable=True),
    Quantity("k", "r.l.u.", "K (r.l.u.)", "Miller index k", "reciprocal-lattice units",
             aliases=("K",), scannable=True, writable=True),
    Quantity("l", "r.l.u.", "L (r.l.u.)", "Miller index l", "reciprocal-lattice units",
             aliases=("L",), scannable=True, writable=True),
    Quantity("q_instrument_x_inv_angstrom", "Å⁻¹", "Q x, instrument frame (Å⁻¹)",
             "momentum transfer, x component", "public Q frame; z is vertical",
             aliases=("qx",), scannable=True, writable=True),
    Quantity("q_instrument_y_inv_angstrom", "Å⁻¹", "Q y, instrument frame (Å⁻¹)",
             "momentum transfer, y component", "public Q frame; z is vertical",
             aliases=("qy",), scannable=True, writable=True),
    Quantity("q_instrument_z_inv_angstrom", "Å⁻¹", "Q z, instrument frame (Å⁻¹)",
             "momentum transfer, z component", "public Q frame; z is vertical",
             aliases=("qz",), scannable=True, writable=True),
    Quantity("energy_transfer_mev", "meV", "Energy transfer ΔE (meV)",
             "energy the sample takes from the neutron, Ei − Ef",
             "positive = neutron energy loss (ki > kf)", aliases=("deltaE",),
             scannable=True, writable=True),
    Quantity("incident_energy_mev", "meV", "Incident energy Ei (meV)",
             "neutron energy before the sample", "E = ħ²k²/2m, as Ki", aliases=("Ei",),
             writable=True),
    Quantity("final_energy_mev", "meV", "Final energy Ef (meV)",
             "neutron energy after the sample", "E = ħ²k²/2m, as Kf", aliases=("Ef",),
             writable=True),
    Quantity("incident_wavevector_inv_angstrom", "Å⁻¹", "Incident wavevector Ki (Å⁻¹)",
             "neutron wavevector magnitude before the sample", "|k| = 2π/λ", aliases=("Ki",),
             writable=True),
    Quantity("final_wavevector_inv_angstrom", "Å⁻¹", "Final wavevector Kf (Å⁻¹)",
             "neutron wavevector magnitude after the sample", "|k| = 2π/λ", aliases=("Kf",),
             writable=True),
    Quantity("mono_horizontal_radius_m", "m", "Mono horizontal radius (m)",
             "requested horizontal bending radius of the monochromator", "requested magnitude; 0 = flat",
             aliases=("rhm",), scannable=True, writable=True),
    Quantity("mono_vertical_radius_m", "m", "Mono vertical radius (m)",
             "requested vertical bending radius of the monochromator", "requested magnitude; 0 = flat",
             aliases=("rvm",), scannable=True, writable=True),
    Quantity("analyzer_horizontal_radius_m", "m", "Analyzer horizontal radius (m)",
             "requested horizontal bending radius of the analyzer", "requested magnitude; 0 = flat",
             aliases=("rha",), scannable=True, writable=True),
    Quantity("analyzer_vertical_radius_m", "m", "Analyzer vertical radius (m)",
             "requested vertical bending radius of the analyzer", "requested magnitude; 0 = flat",
             aliases=("rva",), scannable=True, writable=True),
    Quantity("applied_mono_horizontal_radius_m", "m", "Applied mono horizontal radius (m)",
             "horizontal radius applied to the monochromator", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL),
    Quantity("applied_mono_vertical_radius_m", "m", "Applied mono vertical radius (m)",
             "vertical radius applied to the monochromator", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL),
    Quantity("applied_analyzer_horizontal_radius_m", "m", "Applied analyzer horizontal radius (m)",
             "horizontal radius applied to the analyzer", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL),
    Quantity("applied_analyzer_vertical_radius_m", "m", "Applied analyzer vertical radius (m)",
             "vertical radius applied to the analyzer", "signed by the take-off branch",
             derived_only=True, refusal=APPLIED_REFUSAL),
    *_SLIT_ROWS,
    Quantity("lattice_a_angstrom", "Å", "Lattice a (Å)", "sample lattice parameter a",
             "API writes only", aliases=("a",), writable=True, refusal=LATTICE_REFUSAL),
    Quantity("lattice_b_angstrom", "Å", "Lattice b (Å)", "sample lattice parameter b",
             "API writes only", aliases=("b",), writable=True, refusal=LATTICE_REFUSAL),
    Quantity("lattice_c_angstrom", "Å", "Lattice c (Å)", "sample lattice parameter c",
             "API writes only", aliases=("c",), writable=True, refusal=LATTICE_REFUSAL),
    Quantity("lattice_alpha_deg", "°", "Lattice alpha (°)", "sample lattice angle alpha",
             "API writes only", aliases=("alpha",), writable=True, refusal=LATTICE_REFUSAL),
    Quantity("lattice_beta_deg", "°", "Lattice beta (°)", "sample lattice angle beta",
             "API writes only", aliases=("beta",), writable=True, refusal=LATTICE_REFUSAL),
    Quantity("lattice_gamma_deg", "°", "Lattice gamma (°)", "sample lattice angle gamma",
             "API writes only", aliases=("gamma",), writable=True, refusal=LATTICE_REFUSAL),
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


def resolve(name: str, context: str) -> Quantity:
    """Return the quantity a name means as a scan command ("scan") or API write ("write")."""
    key = name.casefold()
    q = _INDEX.get(key)
    if q is None:
        if key in _RETIRED:
            raise QuantityRefused(_RETIRED[key])
        raise QuantityRefused(f"unknown quantity {name!r}")
    if q.derived_only or not {"scan": q.scannable, "write": q.writable}[context]:
        raise QuantityRefused(q.refusal or f"{q.id} cannot be {_VERB[context]}")
    return q
