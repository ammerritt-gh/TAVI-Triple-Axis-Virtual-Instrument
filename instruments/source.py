"""Facility moderator profiles and the flux spectrum they imply (Qt-free).

The (T, I) numbers are McStas's Source_gen facility table, the authority for the
spectral form; components/Source_Maxwell_direct.comp samples the same spectrum.
A profile is up to three Maxwellians (T in K, I in n/cm2/s/sr); a pair is active
when T > 0 and I > 0, and an unused pair is written as 0.
"""
import math
import numbers
from typing import NamedTuple

import numpy as np

K2V = 629.622368     # McStas mcstas-r.h: AA2MS, k [1/A] -> v [m/s]
VS2E = 5.22703725e-6  # McStas mcstas-r.h: v^2 [(m/s)^2] -> E [meV]
C_E = VS2E * K2V ** 2 * 4 * math.pi ** 2  # meV A^2: E = C_E / lambda^2, as Source_gen's kernel implies
A_OVER_T = 949.0     # Source_gen: a = 949/T with T in K and lambda in A

MODES = {"full_spectrum": "Full spectrum", "flat_band": "Flat band (unphysical)"}
SINGLE_TEMPERATURE = "single_temperature"


class Profile(NamedTuple):
    label: str
    ti: tuple  # (T1, I1, T2, I2, T3, I3), 0 = unused


PROFILES = {
    "frm2_cold": Profile("FRM2 cold source, 20 MW", (35.0, 9.38e12, 547.5, 2.23e12, 195.4, 1.26e13)),
    "frm2_thermal": Profile("FRM2 thermal source, 20 MW", (285.6, 3.06e13, 300.0, 1.68e12, 429.9, 6.77e12)),
    "ill_vcs_cold": Profile("ILL VCS cold source (H1, 58 MW)", (216.8, 1.24e13, 33.9, 1.02e13, 16.7, 3.0423e12)),
    "ill_hcs_cold": Profile("ILL HCS cold source (H5, 58 MW)", (413.5, 10.22e12, 145.8, 3.44e13, 40.1, 2.78e13)),
    "ill_thermal_h12": Profile("ILL thermal tube (H12, 58 MW)", (683.7, 0.5874e13, 257.7, 2.5099e13, 16.7, 1.0343e12)),
    "ill_hot": Profile("ILL hot source, 58 MW", (1695.0, 1.74e13, 708.0, 3.9e12, 0.0, 0.0)),
    "psi_cold": Profile("PSI cold source", (296.2, 8.5e11, 40.68, 5.2e11, 0.0, 0.0)),
    "hzb_cold": Profile("HZB cold source, 10 MW", (43.7, 1.4e12, 137.2, 2.08e12, 0.0, 0.0)),
    "hzb_bispectral": Profile("HZB bi-spectral source", (43.7, 1.4e12, 137.2, 2.08e12, 293.0, 1.77e12)),
    "hzb_thermal": Profile("HZB thermal tube, 10 MW", (293.0, 2.64e12, 0.0, 0.0, 0.0, 0.0)),
    "llb_cold": Profile("LLB cold source, 14 MW", (220.0, 2.09e12, 60.0, 3.83e12, 20.0, 1.04e12)),
    "triga_thermal": Profile("TRIGA thermal source, 1 MW", (300.0, 3.5e11, 0.0, 0.0, 0.0, 0.0)),
    SINGLE_TEMPERATURE: Profile("Single temperature", (300.0, 1e13, 0.0, 0.0, 0.0, 0.0)),
}

DEFAULT_FLAT_BAND_DE = 2.0   # meV, the half-width every fresh source starts with

TI_IDS = ("moderator_t1_k", "moderator_i1", "moderator_t2_k", "moderator_i2", "moderator_t3_k", "moderator_i3")
FIELD_IDS = ("moderator_mode", "moderator_profile") + TI_IDS + ("flat_band_half_width_mev",)


def profile_values(profile_id):
    """The six T/I values of a facility entry, by canonical ID."""
    return dict(zip(TI_IDS, PROFILES[profile_id].ti))


def default_values(profile_id):
    """The nine source values a fresh source, GUI Reset and the API's defaults start from."""
    return {"moderator_mode": "full_spectrum", "moderator_profile": profile_id,
            **profile_values(profile_id), "flat_band_half_width_mev": DEFAULT_FLAT_BAND_DE}


def _number(x):
    """A finite real number; bool is refused although Python counts it as an int."""
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def active_pairs(values):
    """The (T key, I key) pairs of ``values`` that are active: both numbers (None is not), both above 0.

    The one place the rule lives; it is where the component departs from Source_gen.
    """
    return [(t_key, i_key) for t_key, i_key in zip(TI_IDS[::2], TI_IDS[1::2])
            if _number(values.get(t_key)) and _number(values.get(i_key))
            and values[t_key] > 0 and values[i_key] > 0]


def _known(x, table):
    return isinstance(x, str) and x in table


def is_modified(values):
    """True when any T/I value differs from the facility entry the values started from."""
    start = profile_values(values["moderator_profile"])
    return any(values[key] != start[key] for key in TI_IDS)


def validate(values):
    """One message per problem, in the component's rules; an empty list is valid."""
    problems = []
    for key in TI_IDS:
        v = values.get(key)
        if not _number(v):
            problems.append(f"{key} must be a finite number, got {v!r}")
        elif v < 0:
            problems.append(f"{key} must be >= 0, got {v:g}")
    active = []  # I keys of the active pairs, as the component's INITIALIZE refuses them
    for t_key, i_key in active_pairs(values):
        active.append(i_key)
        if not math.isfinite(C_E * values[t_key] / A_OVER_T):
            problems.append(f"{t_key} gives an energy scale that is not finite, got {values[t_key]:g}")
    if not active:
        problems.append("no active pair: at least one (T, I) needs T > 0 and I > 0")
    elif not math.isfinite(sum(values[i_key] for i_key in active)):
        problems.append(f"{', '.join(active)}: the sum of the active I is not finite")
    mode = values.get("moderator_mode")
    if not _known(mode, MODES):
        problems.append(f"unknown moderator_mode {mode!r}; choose one of {', '.join(MODES)}")
    if not _known(values.get("moderator_profile"), PROFILES):
        problems.append(f"unknown moderator_profile {values.get('moderator_profile')!r}")
    dE = values.get("flat_band_half_width_mev")
    if not _number(dE):
        problems.append(f"flat_band_half_width_mev must be a finite number, got {dE!r}")
    elif mode == "flat_band" and dE <= 0:
        problems.append(f"flat_band_half_width_mev must be > 0 in flat-band mode, got {dE:g}")
    return problems


def flux_per_mev(energies, values):
    """Facility flux, n/cm2/s/sr/meV, at energies in meV; the profile's, whatever the mode."""
    E = np.asarray(energies, dtype=float)
    out = np.zeros_like(E)
    for t_key, i_key in active_pairs(values):
        T, I = values[t_key], values[i_key]
        theta = C_E * T / A_OVER_T  # Gamma(2, theta) scale in meV; I * E e^(-E/theta) / theta^2
        out += I * E * np.exp(-E / theta) / theta ** 2
    return out
