"""Machine fingerprinting for machine-aware runtime estimation.

Scan-time history blends timings from every computer the user runs TAVI on.
To keep estimates keyed to the current machine we need a stable, cheap machine
identity plus a cross-machine speed anchor.

This module provides:
- ``machine_fingerprint()``: a stable identity dict for the current machine.
- ``machine_time_model(records)``: the affine ``{overhead, rate}`` cost model
  fitted over a machine's benchmark records, used to scale foreign history.
- ``machine_speed_index(records)``: deprecated alias returning the model rate.

Fingerprinting never shells out: CPU name is best-effort from stdlib and the
Linux ``/proc/cpuinfo`` file, degrading to ``""`` on any failure.
"""
import hashlib
import os
import platform
from typing import Optional, List, Dict

# Cached module-level fingerprint (identity is stable for a process lifetime).
_FINGERPRINT_CACHE: Optional[dict] = None


def _cpu_name() -> str:
    """Best-effort human CPU name; ``""`` on failure. Never shells out."""
    try:
        system = platform.system()
        if system == "Windows":
            # platform.processor() returns the CPU brand string on Windows.
            return (platform.processor() or "").strip()
        if system == "Linux":
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.lower().startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except OSError:
                return ""
            return ""
        # macOS / other: platform.processor() is often a coarse arch string,
        # but it is the only non-shell option available.
        return (platform.processor() or "").strip()
    except Exception:
        return ""


def machine_fingerprint() -> dict:
    """Return a stable identity dict for the current machine.

    Keys: ``machine_id`` (sha1-hex[:12] over hostname/arch/cpu_count/cpu_name),
    ``hostname``, ``machine`` (arch), ``cpu_count``, ``cpu_name``. The result is
    cached module-level; identity is stable for the process lifetime.
    """
    global _FINGERPRINT_CACHE
    if _FINGERPRINT_CACHE is not None:
        return dict(_FINGERPRINT_CACHE)

    hostname = platform.node() or ""
    machine = platform.machine() or ""
    cpu_count = os.cpu_count() or 0
    cpu_name = _cpu_name()

    fingerprint_source = "|".join([hostname, machine, str(cpu_count), cpu_name])
    machine_id = hashlib.sha1(
        fingerprint_source.encode("utf-8")).hexdigest()[:12]

    _FINGERPRINT_CACHE = {
        "machine_id": machine_id,
        "hostname": hostname,
        "machine": machine,
        "cpu_count": cpu_count,
        "cpu_name": cpu_name,
    }
    return dict(_FINGERPRINT_CACHE)


def machine_time_model(records: List) -> Optional[Dict[str, float]]:
    """Affine ``{"overhead", "rate"}`` cost model for a machine, or ``None``.

    Fits ``per_point = overhead + rate * ncount`` over a machine's clean
    benchmark samples (``source == "benchmark"`` mcstas records). Each record
    contributes its warm per-point time (``avg_subsequent_time`` when more than
    one point, else ``first_scan_time``) at its neutron count. The fit needs at
    least two distinct ncounts with a >=10x spread (see
    :func:`tavi.time_model.fit_affine_time_model`); otherwise -- a single-ncount
    benchmark carries no rate information -- this returns ``None``.
    """
    from tavi.time_model import fit_affine_time_model

    samples: List = []
    for rec in records or []:
        if getattr(rec, "source", "organic") != "benchmark":
            continue
        if getattr(rec, "engine", "mcstas") != "mcstas":
            continue
        num_neutrons = getattr(rec, "num_neutrons", 0)
        num_points = getattr(rec, "num_points", 0)
        if not num_neutrons or num_neutrons <= 0 or not num_points or num_points <= 0:
            continue
        spp = (rec.avg_subsequent_time if num_points > 1
               else rec.first_scan_time)
        if spp and spp > 0:
            samples.append((num_neutrons, spp, 1.0))

    model = fit_affine_time_model(samples)
    if model.get("kind") == "affine":
        return {"overhead": model["overhead"], "rate": model["rate"]}
    return None


def machine_speed_index(records: List) -> Optional[float]:
    """Deprecated: the per-neutron rate from :func:`machine_time_model`.

    Retained as a thin alias for callers that still store a scalar
    ``speed_index``; it returns the affine model's ``rate`` (the per-neutron
    cost), or ``None`` when no affine model can be fitted. Prefer
    :func:`machine_time_model`, which also exposes the fixed overhead.
    """
    model = machine_time_model(records)
    return model["rate"] if model else None
