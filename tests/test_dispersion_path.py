"""Path parsing and tracing through a ``Phonon_DFT`` map."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tavi.dispersion_map import load_dispersion_map
from tavi.dispersion_path import PRESET_PATHS, PathError, parse_path, trace_path

AL_MAP = Path(__file__).resolve().parents[1] / "components" / "Al_test_phonons_centered.dat"


def test_parse_path_accepts_names_aliases_and_tuples():
    path = parse_path("G - X → (1,1,0) gamma")
    assert [label for label, _ in path] == ["Γ", "X", "(1,1,0)", "Γ"]
    assert path[2][1] == (1.0, 1.0, 0.0)
    for text in PRESET_PATHS.values():
        assert len(parse_path(text)) >= 2


@pytest.mark.parametrize("text", ["Γ", "Γ Q", "Γ (1,two,0)"])
def test_parse_path_rejects_bad_text(text):
    with pytest.raises(PathError):
        parse_path(text)


def test_trace_path_follows_the_toy_map():
    trace = trace_path(load_dispersion_map(AL_MAP), parse_path("Γ X W K Γ L"), 50)
    assert trace.energies.shape == (5 * 50 + 1, 2)
    assert trace.labels == ["Γ", "X", "W", "K", "Γ", "L"]
    segment_lengths = [0, 1, 0.5, 0.25 * np.sqrt(2), 0.75 * np.sqrt(2), 0.5 * np.sqrt(3)]
    assert trace.ticks == pytest.approx(list(np.cumsum(segment_lengths)))
    gamma_rows = (0, 4 * 50)
    assert trace.energies[gamma_rows, 0] == pytest.approx([0.0, 0.0])      # acoustic gapless
    assert trace.energies[gamma_rows, 1] == pytest.approx([6.0, 6.0])      # toy optic gap
    assert trace.energies[50, 0] == pytest.approx(6.0)                     # X point of the toy
    assert np.all(np.diff(trace.distance) > 0)
