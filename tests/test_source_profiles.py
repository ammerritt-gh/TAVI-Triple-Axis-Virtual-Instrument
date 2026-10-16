"""instruments/source.py: facility table, flux spectrum, validation.

Pure Python. The McStas reference files are read from the MCSTAS resources
folder that the repo conftest.py sets; no McStas run happens here. The spectrum
is checked against Source_gen's kernel, the authority named in the design, with
the McStas constants parsed from McStas's own header rather than copied.
"""
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest

from instruments import source as src

MCSTAS = Path(os.environ["MCSTAS"])
COMPONENT = src.COMPONENT_PATH
KEYS = ("T1", "I1", "T2", "I2", "T3", "I3")


def _rows(text, start, end):
    """{row label: (T1, I1, T2, I2, T3, I3)} for each facility row of a McStas header table between two markers."""
    block = text.split(start, 1)[1].split(end, 1)[0]
    bodies = []
    for line in block.splitlines():
        s = line.strip().lstrip("*").strip()
        if "T1=" in s:
            bodies.append([s])
        elif s and bodies:
            bodies[-1].append(s)
    rows = {}
    for parts in bodies:
        label = parts[0].split("T1=", 1)[0].strip()
        found = dict(re.findall(r"\b([TI][123])\s*=\s*([-+0-9.eE]+)", " ".join(parts)))
        rows[label] = tuple(float(found.get(k, 0)) for k in KEYS)
    return rows


def _mcstas_constant(name):
    header = (MCSTAS / "share" / "mcstas-r.h").read_text(encoding="utf-8")
    return float(re.search(rf"#define\s+{name}\s+([0-9.eE+-]+)", header).group(1))


C_MCSTAS = _mcstas_constant("VS2E") * _mcstas_constant("AA2MS") ** 2 * 4 * math.pi ** 2


def _source_gen_energy_flux(E, T, I):
    """Source_gen's SG kernel in wavelength, times I, carried to energy by |dlambda/dE|."""
    L = np.sqrt(C_MCSTAS / E)
    a = 949.0 / T
    sg = 2 * a * a * np.exp(-a / L ** 2) / L ** 5
    return I * sg * L / (2 * E)


def _density_form(E, T, I):
    """sqrt(E) exp(-E/kT), normalised to I: the density form the design rejects, same total."""
    kT = 8.617333262e-2 * T
    return I * np.sqrt(E) * np.exp(-E / kT) / ((math.sqrt(math.pi) / 2) * kT ** 1.5)


def _active(profile_id):
    return [(T, I) for T, I in zip(src.PROFILES[profile_id].ti[::2], src.PROFILES[profile_id].ti[1::2]) if T > 0 and I > 0]


def _trapezoid(y, x):
    return float((y[1:] + y[:-1]).sum() * np.diff(x).mean() / 2)


def _values(profile="frm2_thermal", mode="full_spectrum", dE=2.0, **over):
    values = {
        "moderator_mode": mode,
        "moderator_profile": profile,
        "flat_band_half_width_mev": dE,
        **src.profile_values(profile),
    }
    values.update(over)
    return values


# profile id -> its row label in Source_gen's table and in the component's %D table (same text in both)
LABELS = {
    "frm2_cold": "FRM2 cold,20MW",
    "frm2_thermal": "FRM2 thermal,20MW",
    "ill_vcs_cold": "ILL VCS cold source",
    "ill_hcs_cold": "ILL HCS cold source",
    "ill_thermal_h12": "ILL Thermal tube",
    "ill_hot": "ILL Hot source",
    "psi_cold": "PSI cold source",
    "hzb_cold": "HZB cold source",
    "hzb_bispectral": "HZB bi-spectral",
    "hzb_thermal": "HZB thermal tube",
    "llb_cold": "LLB cold,14MW",
    "triga_thermal": "TRIGA thermal 1MW",
}


def test_table_matches_source_gen_and_component_per_profile():
    gen = _rows((MCSTAS / "sources" / "Source_gen.comp").read_text(encoding="utf-8"),
                "Some neutron facility parameters", "%VALIDATION")
    comp = _rows(COMPONENT.read_text(encoding="utf-8"),
                 "Facility parameters (the table", "Usage example")
    assert len(gen) == len(comp) == 12
    assert set(LABELS) == set(src.PROFILES) - {src.SINGLE_TEMPERATURE}
    # per id, not by position or as a set: a swapped pair of rows must fail here
    for pid, label in LABELS.items():
        assert src.PROFILES[pid].ti == gen[label] == comp[label], (pid, label)
    assert list(src.PROFILES) == [
        "frm2_cold", "frm2_thermal", "ill_vcs_cold", "ill_hcs_cold", "ill_thermal_h12", "ill_hot",
        "psi_cold", "hzb_cold", "hzb_bispectral", "hzb_thermal", "llb_cold", "triga_thermal",
        "single_temperature",
    ]
    assert src.profile_values(src.SINGLE_TEMPERATURE) == {
        "moderator_t1_k": 300.0, "moderator_i1": 1e13, "moderator_t2_k": 0.0,
        "moderator_i2": 0.0, "moderator_t3_k": 0.0, "moderator_i3": 0.0,
    }


ENERGIES = np.geomspace(0.01, 400.0, 400)


@pytest.mark.parametrize("profile_id", list(src.PROFILES))
def test_flux_is_source_gen_kernel_carried_to_energy(profile_id):
    values = src.profile_values(profile_id)
    ref = sum(_source_gen_energy_flux(ENERGIES, T, I) for T, I in _active(profile_id))
    np.testing.assert_allclose(src.flux_per_mev(ENERGIES, values), ref, rtol=1e-12, atol=0)


@pytest.mark.parametrize("profile_id", list(src.PROFILES))
def test_flux_integrates_to_sum_of_i(profile_id):
    # integrate in u = ln E, where a uniform grid resolves the low-energy end
    theta_max = max(C_MCSTAS * T / 949.0 for T, _ in _active(profile_id))
    u = np.linspace(math.log(1e-4), math.log(60 * theta_max), 200_001)
    E = np.exp(u)
    total = _trapezoid(src.flux_per_mev(E, src.profile_values(profile_id)) * E, u)
    assert total == pytest.approx(sum(I for _, I in _active(profile_id)), rel=1e-6)


def test_density_form_fails_the_spectrum_and_integral_checks():
    ref = src.flux_per_mev(ENERGIES, src.profile_values("frm2_thermal"))
    density = sum(_density_form(ENERGIES, T, I) for T, I in _active("frm2_thermal"))
    assert np.max(np.abs(density - ref) / ref) > 1e-2  # shape differs, not just the normalisation
    # un-normalised density form: its integral over energy is not sum(I)
    T, I = _active(src.SINGLE_TEMPERATURE)[0]
    u = np.linspace(math.log(1e-4), math.log(60 * 300 * 8.617333262e-2), 200_001)
    E = np.exp(u)
    raw_total = _trapezoid(I * np.sqrt(E) * np.exp(-E / (8.617333262e-2 * T)) * E, u)
    assert abs(raw_total / I - 1) > 1e-3


def test_validate_accepts_every_facility_entry_and_flat_band():
    for pid in src.PROFILES:
        assert src.validate(_values(pid)) == []
    assert src.validate(_values("frm2_thermal", mode="flat_band", dE=0.5)) == []
    assert src.validate(_values("frm2_thermal", mode="full_spectrum", dE=0)) == []  # dE unread in full spectrum


@pytest.mark.parametrize("bad, names", [
    ({"moderator_t1_k": float("nan")}, "moderator_t1_k"),
    ({"moderator_i2": float("inf")}, "moderator_i2"),
    ({"moderator_t3_k": "300"}, "moderator_t3_k"),
    ({"moderator_i1": True}, "moderator_i1"),
    ({"moderator_t1_k": -1.0}, "moderator_t1_k"),
    ({"moderator_i3": -5.0}, "moderator_i3"),
])
def test_validate_names_each_bad_number(bad, names):
    problems = src.validate(_values(**bad))
    assert problems and any(names in p for p in problems)


def test_validate_refuses_energy_scale_overflow_per_active_pair():
    problems = src.validate(_values(moderator_t1_k=1e307))  # C*T/949 overflows; one problem, one message
    assert len(problems) == 1 and "moderator_t1_k" in problems[0] and "energy scale" in problems[0]
    assert src.validate(_values(moderator_t1_k=1e307, moderator_i1=0.0)) == []  # an inactive pair is not read


def test_validate_refuses_active_i_sum_overflow():
    problems = src.validate(_values(moderator_i1=1e308, moderator_i2=1e308))
    assert len(problems) == 1 and "moderator_i1" in problems[0] and "moderator_i2" in problems[0]
    assert "sum" in problems[0]


def test_validate_no_active_pair_and_unknown_names():
    none = dict(moderator_t2_k=0.0, moderator_i2=0.0, moderator_t3_k=0.0, moderator_i3=0.0)
    assert any("no active pair" in p for p in src.validate(_values(
        moderator_t1_k=0.0, moderator_i1=0.0, moderator_t2_k=300.0, moderator_i2=0.0,
        moderator_t3_k=0.0, moderator_i3=0.0)))
    assert any("no active pair" in p for p in src.validate(_values(
        moderator_t1_k=float("nan"), moderator_i1=1.0, **none)))
    assert any("moderator_mode" in p for p in src.validate(_values(mode="cold")))
    assert any("moderator_mode" in p for p in src.validate(_values(mode=["full_spectrum"])))
    assert any("moderator_profile" in p for p in src.validate(
        dict(_values("frm2_thermal"), moderator_profile="nowhere")))


def test_validate_flat_band_needs_positive_dE():
    for dE in (0.0, -1.0, float("nan")):
        assert any("flat_band_half_width_mev" in p for p in src.validate(_values(mode="flat_band", dE=dE)))


def test_is_modified_tracks_only_the_six_values():
    assert src.is_modified(_values("frm2_thermal")) is False
    assert src.is_modified(_values("frm2_thermal", moderator_t2_k=301.0)) is True
    assert src.is_modified(_values("frm2_thermal", moderator_i3=6.77e12 * 1.0000001)) is True
    assert src.is_modified(_values("frm2_thermal", mode="flat_band", dE=9.0)) is False
