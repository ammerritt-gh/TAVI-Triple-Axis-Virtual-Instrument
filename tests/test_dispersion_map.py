"""Regular-grid loading and interpolation for analytic ``Phonon_DFT``."""
from __future__ import annotations

from pathlib import Path

import pytest

from tavi.dispersion_map import DispersionMapError, load_dispersion_map


_PB_MAP = Path(__file__).resolve().parents[1] / "components" / "Pb_dft_phonons.dat"


@pytest.mark.skipif(
    not _PB_MAP.is_file(),
    reason="Pb DFT map is local-only until the data may be published",
)
def test_pb_dft_map_has_fcc_zone_centres_and_period_two():
    dispersion = load_dispersion_map(_PB_MAP)
    assert dispersion.branch_count == 3
    assert dispersion.grid_shape == (51, 51, 51)

    def energies(hkl):
        return [mode.energy_mev for mode in dispersion.evaluate(hkl, tessellate=True)]

    assert energies((0.0, 0.0, 0.0)) == [0.0, 0.0, 0.0]
    # fcc zone centre; the Al toy (period 2 per axis) puts its maximum here instead.
    assert energies((1.0, 1.0, 1.0)) == [0.0, 0.0, 0.0]
    # X point straight off the DFT node (0, .5, .5) in primitive internal coordinates.
    assert energies((1.0, 0.0, 0.0)) == pytest.approx([3.34454, 3.34454, 7.79182])
    assert energies((3.0, 0.0, 0.0)) == pytest.approx(energies((1.0, 0.0, 0.0)))


def _grid_text(branches: int = 2, *, energy_offset: float = 0.0) -> str:
    lines = [
        "# grid_nx 2",
        "# grid_ny 2",
        "# grid_nz 2",
        f"# num_branches {branches}",
    ]
    for h in (0.0, 1.0):
        for k in (0.0, 1.0):
            for l in (0.0, 1.0):
                for branch in range(branches):
                    energy = energy_offset + 10.0 * branch + h + 2.0 * k + 3.0 * l
                    intensity = 1.0 + branch + h + k + l
                    linewidth = 0.2 + 0.1 * branch + 0.01 * (h + k + l)
                    lines.append(
                        f"{h:g} {k:g} {l:g} {energy:g} {intensity:g} "
                        f"{branch} {linewidth:g}"
                    )
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_two_and_three_branch_grids(tmp_path):
    two = load_dispersion_map(_write(tmp_path / "two.dat", _grid_text(2)))
    three = load_dispersion_map(_write(tmp_path / "three.dat", _grid_text(3)))
    assert two.branch_count == 2
    assert three.branch_count == 3
    assert [mode.branch for mode in three.evaluate((0.5, 0.5, 0.5), tessellate=False)] == [
        0,
        1,
        2,
    ]


def test_interpolates_energy_intensity_linewidth_and_gradient(tmp_path):
    dispersion = load_dispersion_map(_write(tmp_path / "linear.dat", _grid_text()))
    modes = dispersion.evaluate((0.25, 0.5, 0.75), tessellate=False)
    assert modes[0].energy_mev == pytest.approx(3.5)
    assert modes[1].energy_mev == pytest.approx(13.5)
    assert modes[0].intensity == pytest.approx(2.5)
    assert modes[1].intensity == pytest.approx(3.5)
    assert modes[0].linewidth_fwhm_mev == pytest.approx(0.215)
    assert modes[1].linewidth_fwhm_mev == pytest.approx(0.315)
    assert modes[0].gradient_rlu == pytest.approx((1.0, 2.0, 3.0))
    assert modes[1].gradient_rlu == pytest.approx((1.0, 2.0, 3.0))


def test_linewidth_column_is_optional(tmp_path):
    without_linewidth = "\n".join(
        " ".join(line.split()[:6]) if not line.startswith("#") else line
        for line in _grid_text().splitlines()
    ) + "\n"
    dispersion = load_dispersion_map(
        _write(tmp_path / "no-linewidth.dat", without_linewidth)
    )
    assert not dispersion.has_point_linewidths
    assert all(
        mode.linewidth_fwhm_mev == 0.0
        for mode in dispersion.evaluate((0.5, 0.5, 0.5), tessellate=False)
    )


def test_tessellates_and_refuses_out_of_range_without_tessellation(tmp_path):
    dispersion = load_dispersion_map(_write(tmp_path / "periodic.dat", _grid_text()))
    folded = dispersion.evaluate((1.25, -0.5, 2.75), tessellate=True)
    direct = dispersion.evaluate((0.25, 0.5, 0.75), tessellate=False)
    assert folded == direct
    assert dispersion.evaluate((1.25, 0.5, 0.5), tessellate=False) == ()


@pytest.mark.parametrize(
    "mutator, match",
    [
        (
            lambda text: text.replace(
                "0 0 0 0 1 0 0.2\n", "0 0 0 0 1 0 0.2\n0 0 0 0 1 0 0.2\n"
            ),
            "duplicate grid cell",
        ),
        (
            lambda text: text.replace("1 1 1 6 4 0 0.23\n", ""),
            "grid requires",
        ),
        (
            lambda text: "\n".join(
                line
                for line in _grid_text(3).splitlines()
                if line.startswith("#") or line.split()[5] != "1"
            )
            + "\n",
            "contiguous",
        ),
        (
            lambda text: text.replace("# grid_nx 2", "# grid_nx 3"),
            "header declares",
        ),
        (
            lambda text: text.replace("0 0 0 0 1 0 0.2", "0 0 0 nan 1 0 0.2"),
            "finite",
        ),
        (
            lambda text: text.replace(
                "0 0 0 0 1 0 0.2", "0 0 0 0 1 0 0.2 unexpected"
            ),
            "at most seven",
        ),
        (
            lambda text: text.replace("# grid_nx 2", "# grid_nx 2 unexpected"),
            "malformed grid header",
        ),
    ],
)
def test_rejects_malformed_grids(tmp_path, mutator, match):
    path = _write(tmp_path / "bad.dat", mutator(_grid_text()))
    with pytest.raises(DispersionMapError, match=match):
        load_dispersion_map(path)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="dispersion map not found"):
        load_dispersion_map(tmp_path / "missing.dat")


def test_cache_invalidates_on_file_change(tmp_path):
    path = _write(tmp_path / "changing.dat", _grid_text(energy_offset=0.0))
    first = load_dispersion_map(path)
    assert first.evaluate((0.5, 0.5, 0.5), tessellate=False)[0].energy_mev == 3.0

    _write(path, _grid_text(energy_offset=100.0))
    second = load_dispersion_map(path)
    assert second is not first
    assert second.evaluate((0.5, 0.5, 0.5), tessellate=False)[0].energy_mev == 103.0
