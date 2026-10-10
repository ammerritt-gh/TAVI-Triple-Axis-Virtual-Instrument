"""The PUMA velocity selector is tuned to the incident energy the point really uses.

In angle mode the monochromator selects Ei and the analyser selects Ef, so an
analyser 2theta step at fixed Kf moves Ef but leaves Ei, and the selector,
where it was. The selector frequency must follow the mono's Ei, not fixed_E.
"""
import importlib.util
import math
from pathlib import Path

import pytest

pytest.importorskip("mcstasscript")

from tavi.neutron_conversions import energy2lambda

DATA = Path(__file__).resolve().parent / "data"
_spec = importlib.util.spec_from_file_location("solver_baseline_cases",
                                               DATA / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)


def _selector_nu(ei):
    """nu_param for an incident energy, as instruments/puma/model.py computes it."""
    return 3956 * math.radians(48.3) / 2 / math.pi / 0.25 / energy2lambda(ei)


@pytest.fixture(scope="module")
def puma():
    return {name: snap for name, (_note, snap) in cases.build_cases("PUMA").items()}


def test_analyser_step_leaves_selector_on_the_mono_ei(puma):
    held, stepped = puma["angle_110"], puma["angle_ana_step"]
    assert stepped.metadata["Ei"] == pytest.approx(held.metadata["Ei"], rel=1e-9)
    assert stepped.params["nu_param"] == pytest.approx(held.params["nu_param"], rel=1e-9)
    assert stepped.params["nu_param"] == pytest.approx(
        _selector_nu(stepped.metadata["Ei"]), rel=1e-9)
