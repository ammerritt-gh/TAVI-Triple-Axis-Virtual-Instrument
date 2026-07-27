"""Fast analytic S(Q,omega) convolved with TAS resolution and Poisson noise.

``Phonon_DFT`` samples consume the same configured regular dispersion grid and
LAU/LAZ reflection table as McStas. Every branch in a valid grid is interpolated
without an engine change. Phonon and elastic channels are convolved and calibrated
independently before their means are summed.

At Gamma, modes with ``|E| < 1e-10`` are skipped exactly as in
``components/Phonon_DFT.comp``; the table-backed Bragg channel supplies the
resolution-limited elastic peak. The engine remains an idealized fast tier: it
does not reproduce the full one-phonon structure factor, sample geometry,
``delta_d_d`` Ewald weighting, or finite Bragg mosaic.

Background is never inferred from the sample model. It arrives as an already
computed per-point mean (``background_mean``, from ``tavi/background.py``) and is
added to the signal mean after the signal's own validity clamp, so a disabled
profile leaves every count bit-identical to a background-free engine.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from instruments.descriptor import AnalyticCalibration
from tavi.dispersion_map import DispersionMap, load_dispersion_map
from tavi.reflection_catalog import Reflection, centering_allowed, load_reflections


_KB_MEV_PER_K = 1.0 / 11.605
_TWO_PI = 2.0 * math.pi
_S2F = 2.0 * math.sqrt(2.0 * math.log(2.0))
_ZERO_ENERGY_TOLERANCE = 1.0e-10
_MC_SAMPLES = 256
_COMPONENTS_DIRECTORY = Path(__file__).resolve().parent.parent / "components"

MCSTAS_ANCHOR = {
    "sample_id": "Al_phonon_DFT",
    "hkl": (2.15, 0.0, 0.0),
    "w": 1.5,
    "number_neutrons": 1.0e8,
    "counts": 61.0,
}


@dataclass(frozen=True)
class Branch:
    """One dispersing spectral feature linearized at the requested Q."""

    omega0: float
    weight: float
    grad: tuple
    gamma: float


@dataclass(frozen=True)
class Elastic:
    """One resolution-limited elastic feature."""

    weight: float
    dq: tuple


class AnalyticSQW:
    """Base analytic model with model-owned channel calibration."""

    sample_id: str = ""
    calibration = AnalyticCalibration(phonon=0.0, elastic=0.0)

    def branches(self, hkl) -> list[Branch]:
        return []

    def elastic(self, hkl) -> list[Elastic]:
        return []

    def elastic_arrays(self, hkl) -> tuple[np.ndarray, np.ndarray]:
        features = self.elastic(hkl)
        if not features:
            return np.empty(0, dtype=float), np.empty((0, 3), dtype=float)
        return (
            np.asarray([feature.weight for feature in features], dtype=float),
            np.asarray([feature.dq for feature in features], dtype=float),
        )

    def analytic_metadata(self) -> dict:
        return {
            "channels": [],
            "branch_count": 0,
            "reflection_count": 0,
            "calibration": {
                "phonon": float(self.calibration.phonon),
                "elastic": float(self.calibration.elastic),
            },
            "reflection_mode": "none",
            "zero_energy_policy": None,
        }


class ZeroSQW(AnalyticSQW):
    """The no-sample model."""

    def __init__(self, sample_id: str = "none"):
        self.sample_id = sample_id
        self.calibration = AnalyticCalibration(phonon=0.0, elastic=0.0)


class PhononSQW(AnalyticSQW):
    """All branches from one validated ``Phonon_DFT`` dispersion map."""

    def __init__(
        self,
        dispersion_map: DispersionMap,
        *,
        a: float,
        temperature: float,
        phonon_gamma_fwhm: float,
        tessellate: bool,
        sample_id: str,
        calibration: AnalyticCalibration,
        configured_filename: str,
    ):
        self.dispersion_map = dispersion_map
        self.a = float(a)
        self.temperature = float(temperature)
        self.global_gamma_fwhm = float(phonon_gamma_fwhm)
        self.tessellate = bool(tessellate)
        self.sample_id = sample_id
        self.calibration = calibration
        self.configured_filename = configured_filename
        self._rlu_to_inv_ang = _TWO_PI / self.a

    @property
    def branch_count(self) -> int:
        return self.dispersion_map.branch_count

    def _bose_n(self, omega0: float) -> float:
        kt = self.temperature * _KB_MEV_PER_K
        if kt <= 0.0 or omega0 <= 0.0:
            return 0.0
        argument = omega0 / kt
        if argument > 700.0:
            return 0.0
        return 1.0 / math.expm1(argument)

    def branches(self, hkl) -> list[Branch]:
        branches: list[Branch] = []
        for mode in self.dispersion_map.evaluate(
            hkl, tessellate=self.tessellate
        ):
            omega0 = float(mode.energy_mev)
            if mode.intensity <= 0.0 or abs(omega0) < _ZERO_ENERGY_TOLERANCE:
                continue
            linewidth_fwhm = (
                mode.linewidth_fwhm_mev
                if mode.linewidth_fwhm_mev > 0.0
                else self.global_gamma_fwhm
            )
            gamma_hwhm = 0.5 * max(0.0, linewidth_fwhm)
            gradient = np.asarray(mode.gradient_rlu, dtype=float) / self._rlu_to_inv_ang
            bose = self._bose_n(omega0)
            weight = float(mode.intensity)
            branches.append(
                Branch(
                    omega0=omega0,
                    weight=weight * (bose + 1.0),
                    grad=tuple(gradient),
                    gamma=gamma_hwhm,
                )
            )
            branches.append(
                Branch(
                    omega0=-omega0,
                    weight=weight * bose,
                    grad=tuple(-gradient),
                    gamma=gamma_hwhm,
                )
            )
        return branches

    def analytic_metadata(self) -> dict:
        return {
            "channels": ["phonon"],
            "branch_count": self.branch_count,
            "reflection_count": 0,
            "dispersion": {
                "configured_filename": self.configured_filename,
                "resolved_path": str(self.dispersion_map.path),
                "sha256": self.dispersion_map.sha256,
            },
            "calibration": {
                "phonon": float(self.calibration.phonon),
                "elastic": float(self.calibration.elastic),
            },
            "reflection_mode": "none",
            "zero_energy_policy": "match_phonon_dft_skip",
        }


class BraggSQW(AnalyticSQW):
    """Table-backed Bragg deltas or the legacy centering/unit-F2 fallback."""

    def __init__(
        self,
        *,
        a: float,
        sample_id: str,
        calibration: AnalyticCalibration,
        reflections: Sequence[Reflection] | None,
        space_group: int | None,
        reflection_mode: str,
        configured_filename: str | None,
        resolved_path: Path | None,
        sha256: str | None,
    ):
        self.a = float(a)
        self.sample_id = sample_id
        self.calibration = calibration
        self.space_group = space_group
        self.reflection_mode = reflection_mode
        self.configured_filename = configured_filename
        self.resolved_path = resolved_path
        self.sha256 = sha256
        self._rlu_to_inv_ang = _TWO_PI / self.a
        self._reflections = tuple(
            (
                int(reflection.h),
                int(reflection.k),
                int(reflection.l),
                float(reflection.f_squared),
            )
            for reflection in (reflections or ())
            if reflection.f_squared is not None and reflection.f_squared > 0.0
        )
        self._reflection_weights: dict[tuple[int, int, int], float] = {}
        for h, k, l, f_squared in self._reflections:
            key = (h, k, l)
            self._reflection_weights[key] = (
                self._reflection_weights.get(key, 0.0) + f_squared
            )
        self._reflection_hkl = np.asarray(
            tuple(self._reflection_weights), dtype=float
        ).reshape((-1, 3))
        self._reflection_f2 = np.asarray(
            tuple(self._reflection_weights.values()), dtype=float
        )

    @property
    def reflection_count(self) -> int:
        return len(self._reflections)

    def elastic(self, hkl) -> list[Elastic]:
        point = np.asarray(tuple(hkl), dtype=float)
        if self.reflection_mode == "table_f2":
            weights, offsets = self.elastic_arrays(point)
            return [
                Elastic(weight=float(weight), dq=tuple(offset))
                for weight, offset in zip(weights, offsets)
            ]
        if self.reflection_mode == "centering_unit_f2_fallback":
            tau = tuple(int(round(value)) for value in point)
            if not centering_allowed(*tau, self.space_group):
                return []
            return [
                Elastic(
                    weight=1.0,
                    dq=tuple(
                        (np.asarray(tau, dtype=float) - point)
                        * self._rlu_to_inv_ang
                    ),
                )
            ]
        return []

    def elastic_arrays(self, hkl) -> tuple[np.ndarray, np.ndarray]:
        point = np.asarray(tuple(hkl), dtype=float)
        if self.reflection_mode == "table_f2":
            return (
                self._reflection_f2,
                (self._reflection_hkl - point) * self._rlu_to_inv_ang,
            )
        return super().elastic_arrays(point)

    def analytic_metadata(self) -> dict:
        reflections = {
            "configured_filename": self.configured_filename,
            "resolved_path": (
                str(self.resolved_path) if self.resolved_path is not None else None
            ),
            "sha256": self.sha256,
        }
        return {
            "channels": ["elastic"] if self.reflection_mode != "none" else [],
            "branch_count": 0,
            "reflection_count": self.reflection_count,
            "reflections": reflections,
            "calibration": {
                "phonon": float(self.calibration.phonon),
                "elastic": float(self.calibration.elastic),
            },
            "reflection_mode": self.reflection_mode,
            "zero_energy_policy": None,
        }


class PhononDFTSQW(AnalyticSQW):
    """Composite file-backed phonon plus Bragg model."""

    def __init__(
        self,
        phonon: PhononSQW,
        bragg: BraggSQW,
        *,
        calibration: AnalyticCalibration,
        sample_id: str,
    ):
        self._phonon = phonon
        self._bragg = bragg
        self.calibration = calibration
        self.sample_id = sample_id

    def branches(self, hkl) -> list[Branch]:
        return self._phonon.branches(hkl)

    def elastic(self, hkl) -> list[Elastic]:
        return self._bragg.elastic(hkl)

    def elastic_arrays(self, hkl) -> tuple[np.ndarray, np.ndarray]:
        return self._bragg.elastic_arrays(hkl)

    def analytic_metadata(self) -> dict:
        phonon = self._phonon.analytic_metadata()
        bragg = self._bragg.analytic_metadata()
        return {
            "channels": ["phonon", "elastic"],
            "branch_count": self._phonon.branch_count,
            "reflection_count": self._bragg.reflection_count,
            "dispersion": phonon["dispersion"],
            "reflections": bragg["reflections"],
            "calibration": {
                "phonon": float(self.calibration.phonon),
                "elastic": float(self.calibration.elastic),
            },
            "reflection_mode": self._bragg.reflection_mode,
            "zero_energy_policy": "match_phonon_dft_skip",
        }


def _configured_filename(value) -> str | None:
    if value is None:
        return None
    filename = str(value).strip().strip('"').strip("'").strip()
    if not filename or filename.upper() == "NULL" or filename == "0":
        return None
    return filename


def _resolve_asset(filename: str, asset_root: Path) -> Path:
    candidate = Path(filename).expanduser()
    if not candidate.is_absolute():
        candidate = asset_root / candidate
    return candidate.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_calibration(sample_spec) -> AnalyticCalibration:
    calibration = getattr(sample_spec, "analytic_calibration", None)
    if calibration is None:
        raise ValueError(
            f"analytic calibration is not configured for sample "
            f"{getattr(sample_spec, 'id', None)!r}"
        )
    values = (float(calibration.phonon), float(calibration.elastic))
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise ValueError("analytic calibration values must be finite and non-negative")
    # The background scaling channel is optional and must survive the rebuild:
    # dropping it would silently turn a calibrated sample into one whose
    # sample-origin background terms are skipped or refused. An unusable value
    # becomes None rather than an exception, so a bad diffuse_background never
    # kills a signal-only scan -- background then refuses explicitly through
    # SampleScaleUnavailable ("sample_background_scale_unavailable").
    diffuse = getattr(calibration, "diffuse_background", None)
    if diffuse is not None:
        diffuse = float(diffuse)
        if not math.isfinite(diffuse) or diffuse < 0.0:
            diffuse = None
    return AnalyticCalibration(
        phonon=values[0], elastic=values[1], diffuse_background=diffuse
    )


def _load_reflection_asset(
    configured: str | None,
    *,
    asset_root: Path,
) -> tuple[list[Reflection], Path, str] | None:
    if configured is None:
        return None
    path = _resolve_asset(configured, asset_root)
    reflections = load_reflections(path)
    return reflections, path, _sha256(path)


def ground_truth(
    sample_spec,
    *,
    asset_root: str | Path | None = None,
) -> Optional[AnalyticSQW]:
    """Build an analytic model by McStas component type.

    Relative component assets resolve beneath TAVI's ``components`` directory;
    callers may provide an alternate root for tests, and absolute paths are kept.
    A configured ``Phonon_DFT`` asset failure is fatal. ``Single_crystal`` alone
    preserves its centering-rule/unit-F2 fallback when its McStas-owned table is
    unavailable.
    """
    if sample_spec is None:
        return None
    sample_id = getattr(sample_spec, "id", "") or "none"
    component_type = getattr(sample_spec, "component_type", None)
    properties = getattr(sample_spec, "properties", None) or {}
    if component_type is None:
        return ZeroSQW(sample_id)
    if component_type not in {"Phonon_DFT", "Single_crystal"}:
        return None

    root = (
        Path(asset_root).expanduser().resolve()
        if asset_root is not None
        else _COMPONENTS_DIRECTORY
    )
    lattice = getattr(sample_spec, "lattice", None)
    a = float(properties.get("a", lattice[0] if lattice else 4.05))
    calibration = _validated_calibration(sample_spec)
    reflection_config = _configured_filename(
        properties.get("reflections", getattr(sample_spec, "reflection_source", None))
    )

    if component_type == "Phonon_DFT":
        dispersion_config = _configured_filename(properties.get("dispersion"))
        if dispersion_config is None:
            raise ValueError(
                f"Phonon_DFT sample {sample_id!r} has no dispersion file configured"
            )
        dispersion_path = _resolve_asset(dispersion_config, root)
        dispersion_map = load_dispersion_map(dispersion_path)
        reflection_asset = _load_reflection_asset(
            reflection_config, asset_root=root
        )
        if reflection_asset is None:
            reflections = []
            reflection_path = None
            reflection_hash = None
            reflection_mode = "none"
        else:
            reflections, reflection_path, reflection_hash = reflection_asset
            reflection_mode = "table_f2"
        phonon = PhononSQW(
            dispersion_map,
            a=a,
            temperature=float(properties.get("T", 0.0)),
            phonon_gamma_fwhm=float(properties.get("phonon_gamma", 0.0)),
            tessellate=bool(properties.get("tessellate", 0)),
            sample_id=sample_id,
            calibration=calibration,
            configured_filename=dispersion_config,
        )
        bragg = BraggSQW(
            a=a,
            sample_id=sample_id,
            calibration=calibration,
            reflections=reflections,
            space_group=getattr(sample_spec, "space_group", None),
            reflection_mode=reflection_mode,
            configured_filename=reflection_config,
            resolved_path=reflection_path,
            sha256=reflection_hash,
        )
        return PhononDFTSQW(
            phonon, bragg, calibration=calibration, sample_id=sample_id
        )

    if component_type == "Single_crystal":
        reflection_asset = None
        if reflection_config is not None:
            try:
                reflection_asset = _load_reflection_asset(
                    reflection_config, asset_root=root
                )
            except FileNotFoundError:
                reflection_asset = None
        if reflection_asset is None:
            reflections = None
            reflection_path = None
            reflection_hash = None
            reflection_mode = "centering_unit_f2_fallback"
        else:
            reflections, reflection_path, reflection_hash = reflection_asset
            reflection_mode = "table_f2"
        return BraggSQW(
            a=a,
            sample_id=sample_id,
            calibration=calibration,
            reflections=reflections,
            space_group=getattr(sample_spec, "space_group", None),
            reflection_mode=reflection_mode,
            configured_filename=reflection_config,
            resolved_path=reflection_path,
            sha256=reflection_hash,
        )
    return None


def _covariance(res_result) -> np.ndarray:
    matrix = np.asarray(res_result.matrix, dtype=float)
    return np.linalg.inv(matrix)


def sigma_e_mev(res_result) -> Optional[float]:
    """Marginalized resolution width in energy, or ``None`` when unavailable.

    The width background terms need is the *marginalized* one,
    ``sqrt(inv(M)[3,3])`` -- not ``1/sqrt(M[3,3])``, which is the conditional
    width at zero momentum offset and is narrower. Callers compute this only
    when a shape actually needs it: the matrix inversion is not free.
    """
    if res_result is None or not getattr(res_result, "ok", False) \
            or getattr(res_result, "matrix", None) is None:
        return None
    try:
        variance = float(_covariance(res_result)[3, 3])
    except np.linalg.LinAlgError:
        return None
    if not math.isfinite(variance) or variance <= 0.0:
        return None
    return math.sqrt(variance)


def _gaussian(delta: float, sigma: float) -> float:
    return math.exp(-0.5 * (delta / sigma) ** 2) / (
        sigma * math.sqrt(_TWO_PI)
    )


def _lorentzian(delta: float, gamma: float) -> float:
    return (gamma / math.pi) / (gamma * gamma + delta * delta)


def _voigt(delta: float, sigma: float, gamma: float) -> float:
    """Area-normalized Thompson-Cox-Hastings pseudo-Voigt."""
    if sigma <= 0.0 and gamma <= 0.0:
        return 0.0
    if gamma <= 0.0:
        return _gaussian(delta, sigma)
    if sigma <= 0.0:
        return _lorentzian(delta, gamma)
    gaussian_fwhm = _S2F * sigma
    lorentzian_fwhm = 2.0 * gamma
    total_fwhm = (
        gaussian_fwhm**5
        + 2.69269 * gaussian_fwhm**4 * lorentzian_fwhm
        + 2.42843 * gaussian_fwhm**3 * lorentzian_fwhm**2
        + 4.47163 * gaussian_fwhm**2 * lorentzian_fwhm**3
        + 0.07842 * gaussian_fwhm * lorentzian_fwhm**4
        + lorentzian_fwhm**5
    ) ** 0.2
    ratio = lorentzian_fwhm / total_fwhm
    eta = 1.36603 * ratio - 0.47719 * ratio**2 + 0.11116 * ratio**3
    return eta * _lorentzian(delta, total_fwhm / 2.0) + (
        1.0 - eta
    ) * _gaussian(delta, total_fwhm / _S2F)


def _convolved_channels(res_result, sqw, hkl, w) -> tuple[float, float]:
    matrix = np.asarray(res_result.matrix, dtype=float)
    covariance = np.linalg.inv(matrix)
    phonon = 0.0
    elastic = 0.0
    for branch in sqw.branches(hkl):
        gradient = np.asarray(branch.grad, dtype=float)
        projection = np.array(
            [-gradient[0], -gradient[1], -gradient[2], 1.0]
        )
        variance = float(projection @ covariance @ projection)
        sigma = math.sqrt(variance) if variance > 0.0 else 0.0
        phonon += branch.weight * _voigt(
            w - branch.omega0, sigma, branch.gamma
        )
    elastic_weights, elastic_offsets = sqw.elastic_arrays(hkl)
    if len(elastic_weights):
        offsets = np.column_stack(
            (
                elastic_offsets,
                np.full(len(elastic_weights), -float(w), dtype=float),
            )
        )
        exponents = np.einsum(
            "ni,ij,nj->n", offsets, matrix, offsets, optimize=True
        )
        elastic = float(np.sum(elastic_weights * np.exp(-0.5 * exponents)))
    return phonon, elastic


def _convolved_intensity(res_result, sqw, hkl, w) -> float:
    """Compatibility helper returning the uncalibrated sum of both channels."""
    return sum(_convolved_channels(res_result, sqw, hkl, w))


def _convolved_channels_mc(
    res_result,
    sqw,
    hkl,
    w,
    rng=None,
    n_samples: int = _MC_SAMPLES,
) -> tuple[float, float]:
    if rng is None:
        rng = np.random.default_rng(0)
    covariance = _covariance(res_result)
    cholesky = np.linalg.cholesky(0.5 * (covariance + covariance.T))
    samples = (
        cholesky @ rng.standard_normal((4, n_samples))
    ).T
    branches = sqw.branches(hkl)
    phonon = 0.0
    for row in samples:
        dq = row[:3]
        delta_energy = row[3]
        sample_intensity = 0.0
        for branch in branches:
            ridge_energy = branch.omega0 + float(
                np.asarray(branch.grad, dtype=float) @ dq
            )
            delta = (w + delta_energy) - ridge_energy
            gamma = branch.gamma if branch.gamma > 0.0 else 1.0e-3
            sample_intensity += branch.weight * _lorentzian(delta, gamma)
        phonon += sample_intensity
    phonon /= n_samples

    matrix = np.asarray(res_result.matrix, dtype=float)
    elastic = 0.0
    elastic_weights, elastic_offsets = sqw.elastic_arrays(hkl)
    if len(elastic_weights):
        offsets = np.column_stack(
            (
                elastic_offsets,
                np.full(len(elastic_weights), -float(w), dtype=float),
            )
        )
        exponents = np.einsum(
            "ni,ij,nj->n", offsets, matrix, offsets, optimize=True
        )
        elastic = float(np.sum(elastic_weights * np.exp(-0.5 * exponents)))
    return phonon, elastic


def _convolved_intensity_mc(
    res_result,
    sqw,
    hkl,
    w,
    rng=None,
    n_samples: int = _MC_SAMPLES,
) -> float:
    return sum(
        _convolved_channels_mc(
            res_result, sqw, hkl, w, rng=rng, n_samples=n_samples
        )
    )


def evaluate_point(
    res_result,
    sqw,
    hkl,
    w,
    number_neutrons,
    rng=None,
    noiseless=False,
    method="analytic",
    *,
    background_mean=0.0,
) -> dict:
    """Evaluate one point using the selected model's channel calibration.

    ``background_mean`` is planted truth computed by the caller
    (``tavi.background.mean_counts``) and added to the signal mean. It defaults
    to zero, which reproduces the background-free counts exactly. A point whose
    resolution solve failed still carries background -- a real instrument counts
    background wherever it counts at all -- so only the signal channels drop to
    zero there; a point that was never executed never reaches this function.
    """
    background_mean = float(background_mean)
    if not getattr(res_result, "ok", False) or res_result.matrix is None:
        counts = (
            background_mean
            if noiseless or rng is None
            else int(rng.poisson(background_mean))
        )
        return {
            "mean": background_mean,
            "counts": counts,
            "channel_means": {
                "phonon": 0.0,
                "elastic": 0.0,
                "background": background_mean,
            },
        }
    if method == "mc":
        phonon, elastic = _convolved_channels_mc(
            res_result, sqw, hkl, w, rng=rng
        )
    else:
        phonon, elastic = _convolved_channels(res_result, sqw, hkl, w)
    phonon_mean = (
        float(number_neutrons) * float(sqw.calibration.phonon) * phonon
    )
    elastic_mean = (
        float(number_neutrons) * float(sqw.calibration.elastic) * elastic
    )
    signal_mean = phonon_mean + elastic_mean
    # The validity clamp guards the SIGNAL only: background is already validated
    # non-negative and finite by tavi.background, and must not be discarded by a
    # signal-side failure.
    if not math.isfinite(signal_mean) or signal_mean < 0.0:
        signal_mean = 0.0
        phonon_mean = 0.0
        elastic_mean = 0.0
    mean = signal_mean + background_mean
    counts = (
        mean
        if noiseless or rng is None
        else int(rng.poisson(mean))
    )
    return {
        "mean": mean,
        "counts": counts,
        "channel_means": {
            "phonon": phonon_mean,
            "elastic": elastic_mean,
            "background": background_mean,
        },
    }


def anchor_convolved_intensity(res_result, sqw=None) -> float:
    """Return the uncalibrated phonon-channel convolution at the saved anchor."""
    if sqw is None:
        from tavi.sample_library import default_sample_library

        spec = next(
            sample
            for sample in default_sample_library()
            if sample.id == MCSTAS_ANCHOR["sample_id"]
        )
        sqw = ground_truth(spec)
    return _convolved_channels(
        res_result, sqw, MCSTAS_ANCHOR["hkl"], MCSTAS_ANCHOR["w"]
    )[0]


def run_deterministic_scan(
    points: Sequence,
    res_results,
    sqw,
    number_neutrons,
    seed,
    noiseless=False,
    method="analytic",
    background_means: Optional[Sequence[float]] = None,
) -> list:
    """Run a scan with an index-keyed RNG stream for every point.

    ``background_means`` is the per-point planted background, positionally
    aligned with ``points``; ``None`` means no background at all, which yields
    the same counts as an explicit sequence of zeros.
    """
    counts = []
    for index, (hkl, w) in enumerate(points):
        resolution = (
            res_results[index]
            if isinstance(res_results, (list, tuple))
            else res_results
        )
        rng = (
            None
            if noiseless
            else np.random.default_rng((int(seed), index))
        )
        result = evaluate_point(
            resolution,
            sqw,
            hkl,
            w,
            number_neutrons,
            rng=rng,
            noiseless=noiseless,
            method=method,
            background_mean=(
                0.0 if background_means is None else float(background_means[index])
            ),
        )
        counts.append(result["counts"])
    return counts


def engine_metadata(seed, res_result, method="analytic", sqw=None) -> dict:
    """Return additive deterministic-engine and analytic-model provenance."""
    if res_result is None:
        metadata = {
            "engine": "deterministic",
            "seed": int(seed),
            "method": method,
            "cn_valid": None,
            "invalidations": [],
            "resolution_method": None,
            "resolution_ok": False,
        }
    else:
        metadata = {
            "engine": "deterministic",
            "seed": int(seed),
            "method": method,
            "cn_valid": bool(getattr(res_result, "cn_valid", False)),
            "invalidations": list(
                getattr(res_result, "invalidations", ()) or ()
            ),
            "resolution_method": getattr(res_result, "method", None),
            "resolution_ok": bool(getattr(res_result, "ok", False)),
        }
    if sqw is not None:
        metadata["analytic_model"] = sqw.analytic_metadata()
    return metadata
