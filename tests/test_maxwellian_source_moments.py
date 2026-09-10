"""``Source_div_Maxwellian_v2`` must sample the distribution it documents.

The component declares P(E) ~ sqrt(E) exp(-E/kT), i.e. Gamma(3/2, kT), and
samples it as Gamma(1) + Gamma(1/2). The Gamma(1/2) half is ``kT * N^2 / 2``
(chi^2_1 = N^2 is Gamma(1/2, scale 2)); the component shipped ``N^2 / 4`` until
2026-09, giving <E> = 1.25 kT instead of 1.5 kT -- a source colder than every
instrument's status record claims, inherited by all four instruments.

McStas is not compiled here: the coefficient is read out of the component
source and the moments checked against the closed form, so the guard is on the
number that was wrong.
"""
import io
import os
import re

import numpy as np
import pytest

from instruments.paths import COMPONENTS_DIR

_SOURCE = os.path.join(COMPONENTS_DIR, "Source_div_Maxwellian_v2.comp")
_SAMPLER = re.compile(r"E\s*=\s*kT\s*\*\s*\(\s*-log\(u1\)\s*\+\s*([0-9.]+)\s*\*\s*n1\s*\*\s*n1\s*\)\s*;")


def _coefficient():
    match = _SAMPLER.search(io.open(_SOURCE, encoding="utf-8").read())
    assert match, f"Maxwellian sampling line not found in {_SOURCE}"
    return float(match.group(1))


def test_gamma_half_coefficient_is_one_half():
    assert _coefficient() == 0.5


def test_sampled_moments_match_gamma_three_halves():
    """Gamma(3/2, kT) has mean 1.5 kT and variance 1.5 kT^2."""
    rng = np.random.default_rng(20260909)
    n = 1_000_000
    kT = 1.0
    u1 = np.clip(rng.random(n), 1e-10, None)
    n1 = rng.standard_normal(n)
    energy = kT * (-np.log(u1) + _coefficient() * n1 * n1)

    assert energy.mean() == pytest.approx(1.5 * kT, abs=0.01)
    assert energy.var() == pytest.approx(1.5 * kT**2, abs=0.03)


def test_peak_sits_at_e0():
    """kT = 2*E0 is what puts the Gamma(3/2) mode at E0; the fix must not move it."""
    text = io.open(_SOURCE, encoding="utf-8").read()
    assert "double kT = 2.0 * E0;" in text
