"""The physics baseline: every case in tests/data/solver_baseline.json, recomputed.

Numbers agree to 1e-9 (relative or absolute); enums, strings and lists compare by
==. Each case must also emit no parameter the baseline does not record, so a new
emitted parameter is added on purpose. Later units translate names through the
role column and the tables in tests/data/solver_baseline_cases.py, never the numbers.
"""
import importlib.util
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("mcstasscript")

DATA = Path(__file__).resolve().parent / "data"
_spec = importlib.util.spec_from_file_location("solver_baseline_cases",
                                               DATA / "solver_baseline_cases.py")
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)

BASELINE = json.loads((DATA / "solver_baseline.json").read_text(encoding="utf-8"))
TOLERANCE = BASELINE["tolerance"]


@pytest.fixture(scope="module")
def recomputed():
    """Every baseline case solved once with today's code, keyed like the JSON."""
    out = {}
    for label in cases.PLUGINS:
        for name, (_note, snap) in cases.build_cases(label).items():
            out[f"{label}/{name}"] = snap
    return out


def _same(actual, expected):
    if isinstance(expected, float):
        return math.isclose(float(actual), expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)
    return actual == expected


def test_every_case_is_recomputed(recomputed):
    assert set(recomputed) == set(BASELINE["cases"])


@pytest.mark.parametrize("key", sorted(BASELINE["cases"]))
def test_case_matches_baseline(key, recomputed):
    recorded = BASELINE["cases"][key]
    snap = recomputed[key]
    assert snap.params is not None and not snap.error_flags, snap.error_flags
    for entry in recorded["params"]:
        assert entry["name"] in snap.params, f"{key}: {entry['name']} no longer emitted"
        assert _same(snap.params[entry["name"]], entry["value"]), (
            f"{key}: {entry['name']} ({entry['role']}) = {snap.params[entry['name']]!r}, "
            f"baseline {entry['value']!r}")
    for entry in recorded["metadata"]:
        assert entry["name"] in snap.metadata, f"{key}: metadata {entry['name']} missing"
        assert _same(snap.metadata[entry["name"]], entry["value"]), (
            f"{key}: metadata {entry['name']} ({entry['role']}) = "
            f"{snap.metadata[entry['name']]!r}, baseline {entry['value']!r}")
    recorded_names = {entry["name"] for entry in recorded["params"]}
    unrecorded = set(snap.params) - recorded_names
    assert not unrecorded, f"{key}: emitted but not in the baseline: {sorted(unrecorded)}"


def test_roles_follow_the_table():
    for key, case in BASELINE["cases"].items():
        for entry in case["params"]:
            assert entry["role"] == cases.param_role(entry["name"]), key
        for entry in case["metadata"]:
            assert entry["role"] == cases.meta_role(entry["name"]), key
