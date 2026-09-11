"""Descriptor + GUI-values -> :class:`tavi.resolution.ResolutionConfig` adapter.

Shared implementation behind every plugin's optional ``resolution_config`` method
(``instruments/contract.py``). It is a **pure function of its inputs**: it reads
only an :class:`~instruments.descriptor.InstrumentDescriptor` and the instrument's
GUI/launch ``vals`` dict, and never imports mcstasscript or touches McStas state,
so it stays testable without the heavy simulation stack (Qt/mcstasscript-free).

Mapping conventions mirror ISAR's TAVI parser (``isar/parsers/tavi.py``):
* d-spacings / mosaics / senses come from the descriptor, keyed by the selected
  crystal ids -- the transitional ``crystal_info`` table is NOT grown.
* ``kfix``/``fx`` follow ISAR ``_kfix`` (FX=1 pins ki, FX=2 pins kf; the fixed
  wavevector is derived from ``fixed_E`` when a direct k is not carried).
* a multi-select collimation slot collapses to its tightest (min non-zero) blade
  (ISAR "tightest-blade" rule); an open / zero / missing blade substitutes a
  documented 60 arcmin effective divergence, adds a warning, and records the
  substitution in provenance ("never silently assume").

Import-light: only numpy-free stdlib + ``tavi.resolution`` (numpy-only). Plugins
import this lazily (function-local) so the instrument registry's lazy-listing
guarantee is preserved.

Targets Python 3.11 syntax.
"""
from __future__ import annotations

import math

# meV = _EK * k^2 (k in Angstrom^-1); k = sqrt(E / _EK). Matches ISAR
# isar/parsers/tavi.py:_EK and tavi.resolution._EMEV_PER_K2.
_EK = 2.072142

# Documented effective divergence substituted for an open/zero collimation blade
# (arcmin, FWHM). See CONTROL_FEATURES_DESIGN.md §5.5 "never silently assume".
_OPEN_ALPHA_ARCMIN = 60.0

# Fallback when the descriptor supplies no vertical_divergence (arcmin, FWHM).
_DEFAULT_BET_ARCMIN = (120.0, 120.0, 120.0, 120.0)

# Fallback mosaic (arcmin) if a selected crystal carries no mosaic value.
_DEFAULT_MOSAIC_ARCMIN = 30.0


def _num(x):
    """Best-effort float, else None (handles GUI strings / None / junk)."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _find_crystal(crystals, crystal_id):
    """Descriptor CrystalSpec for ``crystal_id`` (case/space-insensitive); first
    crystal as the documented fallback when unmatched."""
    cid = str(crystal_id or "").lower().replace(" ", "")
    for c in crystals:
        if c.id.lower().replace(" ", "") == cid:
            return c, True
    return crystals[0], False


def _kfix(vals, prov):
    """(kfix, fx) mirroring ISAR ``_kfix``: FX=1 pins ki, FX=2 pins kf.

    Prefers the mode-appropriate direct wavevector (``Ki`` when ki-fixed, ``Kf``
    when kf-fixed) when carried and positive; otherwise derives the fixed k from
    ``fixed_E`` (TAVI's canonical fixed energy), then the mode-appropriate energy.
    """
    mode = str(vals.get("K_fixed", "")).lower()
    if "ki" in mode:
        fx = 1
        direct = _num(vals.get("Ki"))
        e_fallback = _num(vals.get("Ei"))
    else:  # default / "Kf Fixed"
        fx = 2
        direct = _num(vals.get("Kf"))
        e_fallback = _num(vals.get("Ef"))

    k = direct if (direct is not None and direct > 0) else None
    source = "direct k" if k is not None else None
    if k is None:
        e = _num(vals.get("fixed_E"))
        source = "fixed_E"
        if e is None or e <= 0:
            e = e_fallback
            source = "fixed energy fallback"
        k = math.sqrt(e / _EK) if (e is not None and e > 0) else None
        if k is None:
            source = None
    prov["kfix_fx"] = {
        "mode": vals.get("K_fixed"), "fx": fx, "kfix": k, "kfix_source": source,
    }
    return k, fx


def _collimations(coll, prov, warnings):
    """Effective ALF1..ALF4 (arcmin) from a ``collimation`` dict.

    A list/tuple/set slot (PUMA's stacked alpha_2) -> tightest (min) non-zero
    blade. An open / zero / missing / non-numeric slot substitutes
    ``_OPEN_ALPHA_ARCMIN`` with a warning + provenance record.
    """
    substitutions = {}
    effective = []
    coll = coll if isinstance(coll, dict) else {}
    for i, slot in enumerate(("alpha_1", "alpha_2", "alpha_3", "alpha_4"), start=1):
        raw = coll.get(slot, None)
        if isinstance(raw, (list, tuple, set)):
            nums = [v for v in (_num(z) for z in raw) if v is not None and v > 0]
            val = min(nums) if nums else 0.0
        else:
            val = _num(raw)
            if val is None:
                val = 0.0
        if val <= 0:
            substitutions[slot] = {"raw": _serialize(raw), "effective": _OPEN_ALPHA_ARCMIN}
            warnings.append(
                f"{slot} open: effective {_OPEN_ALPHA_ARCMIN:g} arcmin assumed"
            )
            effective.append(_OPEN_ALPHA_ARCMIN)
        else:
            effective.append(val)
    prov["collimation_effective"] = list(effective)
    if substitutions:
        prov["collimation_substitutions"] = substitutions
    return effective


def _serialize(raw):
    """JSON-friendly echo of a possibly set/tuple collimation value."""
    if isinstance(raw, (list, tuple, set)):
        return sorted(str(x) for x in raw)
    return raw


def _sample_mosaic(descriptor, sample_key, prov):
    """Sample horizontal mosaic (arcmin) from ``SampleSpec.properties['mosaic']``.

    Returns None (module reuses eta_m) when no sample is selected or the sample
    has no mosaic property. The resolution path is recorded in provenance.
    """
    if not sample_key:
        prov["eta_s_source"] = "no sample selected -> reuse eta_m"
        return None
    spec = next((s for s in descriptor.samples if s.id == sample_key), None)
    if spec is None:
        prov["eta_s_source"] = f"sample '{sample_key}' not in library -> reuse eta_m"
        return None
    mosaic = _num((spec.properties or {}).get("mosaic"))
    if mosaic is None or mosaic <= 0:
        prov["eta_s_source"] = f"sample '{sample_key}' has no mosaic -> reuse eta_m"
        return None
    prov["eta_s_source"] = f"sample '{sample_key}' properties.mosaic = {mosaic:g}"
    return mosaic


def _axis_sense(descriptor_sense, angle):
    """Point-local scattering sense for one axis, or the descriptor's when
    there is no point (or the take-off angle is degenerate).

    ``Sense``'s value IS the sign of that axis' two-theta readout
    (``instruments/descriptor.py``), so a solved point's own sense is just
    the sign of its own two-theta -- a direct-angle command can cross onto
    the opposite branch from the one the descriptor declares as normal
    (``set_crystal_bending`` signs curvature the same way, for the same
    reason). ``angle == 0`` has no branch to read (no solve happened, or the
    point sits exactly on the degenerate angle) and falls back to the
    declared sense, exactly like ``set_crystal_bending``'s own zero guard.

    Returns ``(sense, source)`` for provenance.
    """
    if angle is None:
        return int(descriptor_sense), "descriptor Geometry (no solved point)"
    if angle == 0:
        return int(descriptor_sense), "descriptor Geometry (degenerate zero two-theta)"
    return (1 if angle > 0 else -1), f"point-local sign of two-theta={angle:g}"


def build_resolution_config(descriptor, vals, q0, w, point_angles=None):
    """Assemble a :class:`tavi.resolution.ResolutionConfig` from descriptor + vals.

    Instrument-agnostic; plugins pass their own ``descriptor()``. NMO / velocity
    selector / monochromatic-source flags are read from ``vals`` when present and
    recorded as invalidations (NMO) or warnings, never silently dropped.

    ``point_angles`` is an optional ``{"mtt": ..., "stt": ..., "att": ...}``
    dict of THIS point's own solved two-theta angles (degrees) -- the same
    snapshot metadata that already carries them. When given, each axis'
    scattering sense is read off that point's own angle instead of always
    being rebuilt from the descriptor's declared (normal-branch) sense --
    Popovici uses that sense for both the crystal's Bragg angle and its
    curvature sign, so a caller with no solved point (``point_angles=None``)
    keeps today's descriptor-only behaviour; a missing individual angle key
    falls back per-axis the same way.
    """
    from tavi.resolution import ResolutionConfig

    prov: dict = {}
    warnings: list = []
    invalidations: list = []

    geo = descriptor.geometry
    point_angles = point_angles or {}
    sm, sm_src = _axis_sense(geo.sense_mono, point_angles.get("mtt"))
    ss, ss_src = _axis_sense(geo.sense_sample, point_angles.get("stt"))
    sa, sa_src = _axis_sense(geo.sense_ana, point_angles.get("att"))
    prov["senses"] = {
        "sm": sm, "ss": ss, "sa": sa,
        "source": {"sm": sm_src, "ss": ss_src, "sa": sa_src},
    }

    mono, mono_ok = _find_crystal(descriptor.mono_crystals, vals.get("monocris"))
    ana, ana_ok = _find_crystal(descriptor.ana_crystals, vals.get("anacris"))
    dm, da = mono.d_spacing, ana.d_spacing
    prov["dm"] = {"crystal": mono.id, "matched": mono_ok, "d_spacing": dm}
    prov["da"] = {"crystal": ana.id, "matched": ana_ok, "d_spacing": da}

    eta_m = mono.mosaic if mono.mosaic is not None else _DEFAULT_MOSAIC_ARCMIN
    eta_a = ana.mosaic if ana.mosaic is not None else _DEFAULT_MOSAIC_ARCMIN
    if mono.mosaic is None:
        warnings.append(f"mono crystal '{mono.id}' has no mosaic: {eta_m:g} arcmin assumed")
    if ana.mosaic is None:
        warnings.append(f"ana crystal '{ana.id}' has no mosaic: {eta_a:g} arcmin assumed")
    eta_m_v = mono.mosaic_v            # None -> module reuses eta_m vertically
    eta_a_v = ana.mosaic_v

    eta_s = _sample_mosaic(descriptor, vals.get("sample_key"), prov)

    kfix, fx = _kfix(vals, prov)

    alf = _collimations(vals.get("collimation"), prov, warnings)

    bet = descriptor.vertical_divergence or _DEFAULT_BET_ARCMIN
    prov["bet"] = {"value": list(bet), "source": "descriptor default"}

    def _magnitude(name):
        """A curvature magnitude from vals, enforced at this boundary.

        This is where the operator-surface contract (magnitudes) meets the
        physics model, and tavi/resolution.py applies the scattering sense
        itself -- `anarv = radius_cm(cfg.rva) * sa`. A signed value arriving
        here is therefore signed twice, and the resulting resolution describes
        a crystal bent the wrong way. That is not hypothetical: it was live on
        this repository's negative-branch instruments for three commits, and
        it was invisible, because the emitted McStas geometry stayed correct
        and only the analytic half was wrong.

        So the radius is taken as a magnitude and the violation is logged
        rather than raised: a bad value must not take down a resolution
        display mid-session, and it must not pass unseen either.
        """
        value = _num(vals.get(name))
        if value is not None and value < 0:
            warnings.append(
                f"{name} arrived signed ({value:g} m); the resolution model "
                "applies the scattering sense itself, so its magnitude is used"
            )
            return abs(value)
        return value

    rhm, rvm, rha = _magnitude("rhm"), _magnitude("rvm"), _magnitude("rha")
    rva = _magnitude("rva")
    prov["curvature"] = {
        "rhm": rhm, "rvm": rvm, "rha": rha, "rva": rva,
        "source": "vals rhm/rvm/rha/rva (metres, magnitudes); "
                  "tavi/resolution.py applies the scattering sense itself",
    }

    modules = vals.get("modules")
    if isinstance(modules, dict):
        nmo = modules.get("nmo")
        if nmo not in (None, "None", "none", ""):
            invalidations.append(
                "NMO installed: nested mirror optics replace the Soller-collimator "
                "divergence model; Cooper-Nathans/Popovici not applicable"
            )
            prov["nmo_installed"] = nmo
        if modules.get("v_selector"):
            warnings.append(
                "velocity selector installed: its band-pass is not part of the "
                "Cooper-Nathans/Popovici divergence model"
            )
            prov["v_selector_installed"] = True
    if str(vals.get("source_type", "")).lower() == "mono":
        warnings.append(
            "monochromatic source selected: the incident distribution differs "
            "from the Maxwellian source assumed by the resolution model"
        )
        prov["source_type"] = vals.get("source_type")

    return ResolutionConfig(
        dm=dm, da=da,
        eta_m=eta_m, eta_a=eta_a, eta_s=eta_s,
        eta_m_v=eta_m_v, eta_a_v=eta_a_v,
        sm=sm, ss=ss, sa=sa,
        kfix=kfix, fx=fx,
        alf=tuple(alf), bet=tuple(bet),
        q0=q0, w=w,
        rhm=rhm, rvm=rvm, rha=rha, rva=rva,
        warnings=tuple(warnings),
        invalidations=tuple(invalidations),
        provenance=prov,
    )
