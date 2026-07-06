"""Runtime tracker for recording and estimating scan times.

This module provides functionality to:
1. Track historical scan runtimes per instrument
2. Separate compile time (first scan) from run time (subsequent scans)
3. Estimate scan times based on neutron count
4. Persist data across sessions in config/runtimes.json
"""
import json
import os
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict, fields as dataclass_fields

from tavi.time_model import (
    fit_affine_time_model,
    per_point_estimate,
    reference_ncount,
    scale_per_point,
    weighted_median,
)


@dataclass
class ScanRecord:
    """Record of a single scan execution."""
    instrument_name: str
    num_points: int
    num_neutrons: int
    first_scan_time: float  # Time for first point (includes compile time)
    avg_subsequent_time: float  # Average time per point for points 2+
    total_time: float  # Total scan time
    timestamp: str  # ISO format timestamp
    compilation_time: float = 0.0  # Explicit compile-time estimate when available
    # --- Schema v2 fields (all defaulted so v1 records load unchanged) ---
    machine_id: Optional[str] = None      # None => legacy/unknown machine
    engine: str = "mcstas"                # "mcstas" | "deterministic"
    execution_mode: Optional[str] = None  # "backengine" | "direct" | "mixed"
    binary_reused: Optional[bool] = None  # True => compilation_time not meaningful
    build_fp_hash: Optional[str] = None   # sha1(repr(build_fingerprint))[:12]
    source: str = "organic"               # "organic" | "benchmark"
    mpi_count: Optional[int] = None       # MPI worker count (None => unknown)


class RuntimeTracker:
    """Tracks and estimates scan runtimes based on historical data.
    
    This class maintains a history of scan executions, separating compile time
    (included in the first scan) from pure run time (subsequent scans).
    Time estimates are normalized by neutron count assuming linear scaling.
    
    Attributes:
        config_path: Path to the runtimes.json config file
        max_records: Maximum number of records to keep per instrument
        records: Dictionary mapping instrument names to list of ScanRecords
    """
    
    DEFAULT_CONFIG_PATH = "config/runtimes.json"
    MAX_RECORDS = 100

    # One-time key migration: scans recorded before the instrument registry
    # existed were keyed by the literal "PUMA"; the registry id is "puma".
    # Merged on load (legacy records first); the next save persists the new key.
    LEGACY_INSTRUMENT_KEYS = {"PUMA": "puma"}


    def __init__(self, config_path: Optional[str] = None):
        """Initialize the runtime tracker.
        
        Args:
            config_path: Path to config file, defaults to config/runtimes.json
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.max_records = self.MAX_RECORDS
        self.records: Dict[str, List[ScanRecord]] = {}
        # Schema v2: per-machine profiles keyed by machine_id.
        self.machines: Dict[str, dict] = {}
        self._load()

    @staticmethod
    def _record_from_dict(rec: dict) -> ScanRecord:
        """Build a ScanRecord from a dict, ignoring unknown/future keys.

        Filtering to known dataclass fields keeps a single unknown key from
        tripping the TypeError catch in ``_load`` (which would wipe ALL
        history). Forward-compatible with schema fields we do not yet know.
        """
        known = {f.name for f in dataclass_fields(ScanRecord)}
        filtered = {k: v for k, v in rec.items() if k in known}
        return ScanRecord(**filtered)

    def _load(self) -> None:
        """Load runtime records from config file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                self.records = {}
                for instrument, record_list in data.get('records', {}).items():
                    self.records[instrument] = [
                        self._record_from_dict(rec) for rec in record_list
                    ]
                # v2 machines block; absent in v1 files (stays empty).
                machines = data.get('machines', {})
                self.machines = dict(machines) if isinstance(machines, dict) else {}
                self._migrate_legacy_keys()
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"Warning: Could not load runtimes.json: {e}")
                self.records = {}
                self.machines = {}
        else:
            self.records = {}
            self.machines = {}
    
    def _migrate_legacy_keys(self) -> None:
        """Merge records stored under legacy instrument keys into their new key."""
        for legacy_key, new_key in self.LEGACY_INSTRUMENT_KEYS.items():
            legacy_records = self.records.pop(legacy_key, None)
            if not legacy_records:
                continue
            for record in legacy_records:
                record.instrument_name = new_key
            merged = legacy_records + self.records.get(new_key, [])
            self.records[new_key] = merged[-self.max_records:]

    def _save(self) -> None:
        """Save runtime records to config file."""
        # Ensure config directory exists
        os.makedirs(os.path.dirname(self.config_path) or '.', exist_ok=True)
        
        data = {
            'version': 2,
            'records': {
                instrument: [asdict(rec) for rec in record_list]
                for instrument, record_list in self.records.items()
            },
            'machines': self.machines,
        }

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def set_machine_profile(self,
                            machine_id: str,
                            hostname: str = "",
                            cpu_name: str = "",
                            cpu_count: int = 0,
                            speed_index: Optional[float] = None,
                            benchmarked_at: Optional[str] = None) -> None:
        """Record/refresh a machine profile in the ``machines`` block and save.

        Args:
            machine_id: Stable machine identity (from ``machine_fingerprint``).
            hostname: Machine hostname.
            cpu_name: Best-effort CPU name.
            cpu_count: Logical CPU count.
            speed_index: Median per-neutron seconds (cross-machine anchor).
            benchmarked_at: ISO timestamp of the benchmark; defaults to now.
        """
        from datetime import datetime

        self.machines[machine_id] = {
            "hostname": hostname,
            "cpu_name": cpu_name,
            "cpu_count": cpu_count,
            "speed_index": speed_index,
            "benchmarked_at": benchmarked_at or datetime.now().isoformat(),
        }
        self._save()
    
    def add_record(self,
                   instrument_name: str,
                   num_points: int,
                   num_neutrons: int,
                   first_scan_time: float,
                   avg_subsequent_time: float,
                   total_time: float,
                   compilation_time: float = 0.0,
                   machine_id: Optional[str] = None,
                   engine: str = "mcstas",
                   execution_mode: Optional[str] = None,
                   binary_reused: Optional[bool] = None,
                   build_fp_hash: Optional[str] = None,
                   source: str = "organic",
                   mpi_count: Optional[int] = None) -> None:
        """Add a new scan record.

        Args:
            instrument_name: Name of the instrument (e.g., 'PUMA')
            num_points: Total number of scan points
            num_neutrons: Number of neutrons per point
            first_scan_time: Time for first point (compile + run)
            avg_subsequent_time: Average time for subsequent points (run only)
            total_time: Total scan time
            compilation_time: Explicit compile-time estimate for this run
            machine_id: Machine identity (None => legacy/unknown)
            engine: "mcstas" | "deterministic"
            execution_mode: "backengine" | "direct" | "mixed"
            binary_reused: True => compilation_time is not meaningful
            build_fp_hash: sha1(repr(build_fingerprint))[:12], diagnostics only
            source: "organic" | "benchmark"
            mpi_count: MPI worker count for this run (None => unknown)
        """
        from datetime import datetime

        record = ScanRecord(
            instrument_name=instrument_name,
            num_points=num_points,
            num_neutrons=num_neutrons,
            first_scan_time=first_scan_time,
            avg_subsequent_time=avg_subsequent_time,
            total_time=total_time,
            timestamp=datetime.now().isoformat(),
            compilation_time=compilation_time,
            machine_id=machine_id,
            engine=engine,
            execution_mode=execution_mode,
            binary_reused=binary_reused,
            build_fp_hash=build_fp_hash,
            source=source,
            mpi_count=mpi_count,
        )

        if instrument_name not in self.records:
            self.records[instrument_name] = []
        
        self.records[instrument_name].append(record)
        
        # Trim old records if exceeding max
        if len(self.records[instrument_name]) > self.max_records:
            self.records[instrument_name] = self.records[instrument_name][-self.max_records:]
        
        self._save()
    
    def get_estimates(self, instrument_name: str, num_neutrons: int,
                      engine: str = "mcstas"
                      ) -> Tuple[Optional[float], Optional[float]]:
        """Get estimated compile time and per-point run time.

        Thin engine-aware wrapper over :meth:`estimate_scan_seconds`: the
        per-point time comes from the affine cost model (``per_point_seconds``)
        and the compile estimate from the non-reused compile samples of the same
        machine pool. Records are filtered to ``engine`` (default ``"mcstas"``).

        Args:
            instrument_name: Name of the instrument.
            num_neutrons: Number of neutrons for the upcoming scan.
            engine: "mcstas" | "deterministic".

        Returns:
            Tuple of (compile_time_estimate, run_time_per_point_estimate).
            Returns (None, None) if no historical data for the engine.
        """
        records = [r for r in (self.records.get(instrument_name, []) or [])
                   if getattr(r, "engine", "mcstas") == engine]
        if not records:
            return (None, None)

        est = self.estimate_scan_seconds(
            instrument_name, n_points=1, num_neutrons=num_neutrons,
            needs_compile=False, engine=engine)
        run_time_per_point = est.get("per_point_seconds")

        pairs, _ = self._select_pool(records)
        compile_time = self._compile_seconds(pairs)
        return (compile_time, run_time_per_point)

    def estimate_total_time(self,
                            instrument_name: str,
                            num_points: int,
                            num_neutrons: int,
                            engine: str = "mcstas"
                            ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Estimate total scan time including compile time.

        Args:
            instrument_name: Name of the instrument.
            num_points: Number of scan points.
            num_neutrons: Number of neutrons per point.
            engine: "mcstas" | "deterministic".

        Returns:
            Tuple of (total_time, compile_time, run_time_per_point).
            Any value may be None if no historical data.
        """
        compile_time, run_time_per_point = self.get_estimates(
            instrument_name, num_neutrons, engine=engine)

        if compile_time is None or run_time_per_point is None:
            return (None, None, None)

        # Total = compile_time + (num_points * run_time_per_point)
        # Note: First point includes compile, so we don't double-count.
        total_time = compile_time + (num_points * run_time_per_point)

        return (total_time, compile_time, run_time_per_point)
    
    @staticmethod
    def _confidence_from_samples(n: int) -> str:
        """Map a sample count to a confidence tier.

        0 -> 'none', 1-2 -> 'low', 3-9 -> 'medium', 10+ -> 'high'.
        """
        if n <= 0:
            return "none"
        if n <= 2:
            return "low"
        if n <= 9:
            return "medium"
        return "high"

    # Recency weighting: a sample's weight halves every 30 days of age.
    RECENCY_HALF_LIFE_DAYS = 30.0
    # Benchmark records are clean machine baselines; they never decay below
    # this floor weight so a single fresh-install benchmark keeps anchoring
    # estimates even after months of no benchmarking.
    BENCHMARK_FLOOR_WEIGHT = 0.25
    # Predictions beyond this factor of the observed ncount range are
    # confidence-capped (see ``_cap_confidence_for_fit``).
    EXTRAPOLATION_FACTOR = 10.0
    # Confidence caps applied per selection basis (None => no cap).
    _BASIS_CONFIDENCE_CAP = {"scaled": "low", "pooled": "low"}
    _CONFIDENCE_ORDER = ["none", "low", "medium", "high"]

    def _select_pool(self, records: List[ScanRecord]
                     ) -> Tuple[List[Tuple[ScanRecord, float]], Optional[str]]:
        """Choose the sample pool for the current machine and its basis.

        Returns ``(pairs, basis)`` where ``pairs`` is a list of
        ``(record, speed_scale)`` and ``basis`` is one of
        ``"local"|"legacy"|"scaled"|"pooled"`` (``None`` when ``records`` is
        empty). ``speed_scale`` is the cross-machine speed ratio applied to a
        foreign record (1.0 for same-machine/legacy/pooled records).

        Chain: local (this machine) -> legacy (unknown machine, pre-v2) ->
        scaled (foreign machine, both benchmarked) -> pooled (everything).
        """
        from tavi.machine_profile import machine_fingerprint

        if not records:
            return ([], None)

        me = machine_fingerprint()["machine_id"]

        local = [r for r in records if r.machine_id == me]
        if local:
            return ([(r, 1.0) for r in local], "local")

        legacy = [r for r in records if r.machine_id is None]
        if legacy:
            return ([(r, 1.0) for r in legacy], "legacy")

        foreign = [r for r in records if r.machine_id is not None]
        local_si = (self.machines.get(me) or {}).get("speed_index")
        if local_si:
            scaled: List[Tuple[ScanRecord, float]] = []
            for r in foreign:
                foreign_si = (self.machines.get(r.machine_id) or {}).get("speed_index")
                if foreign_si:
                    scaled.append((r, local_si / foreign_si))
            if scaled:
                return (scaled, "scaled")

        return ([(r, 1.0) for r in records], "pooled")

    def _recency_weight(self, timestamp: str, now) -> float:
        """Weight in (0, 1]: halves every ``RECENCY_HALF_LIFE_DAYS`` of age.

        Unparseable timestamps are treated as fresh (weight 1.0). The result is
        floored at a tiny epsilon so every sample stays usable.
        """
        from datetime import datetime
        try:
            ts = datetime.fromisoformat(timestamp)
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            weight = 0.5 ** (age_days / self.RECENCY_HALF_LIFE_DAYS)
        except (ValueError, TypeError):
            weight = 1.0
        return max(weight, 1e-9)

    def _record_weight(self, rec: ScanRecord, now) -> float:
        """Recency weight, floored for benchmark anchors."""
        weight = self._recency_weight(rec.timestamp, now)
        if getattr(rec, "source", "organic") == "benchmark":
            return max(weight, self.BENCHMARK_FLOOR_WEIGHT)
        return weight

    def _per_point_model(self, pairs: List[Tuple[ScanRecord, object]],
                         num_neutrons: int, engine: str) -> Dict[str, object]:
        """Per-point seconds at ``num_neutrons`` plus the affine-model diagnostics.

        Builds ``(ncount, per_point_seconds, weight)`` samples from the pool,
        each per-point value cross-machine-corrected (a scalar speed ratio for
        legacy/pooled bases, or the component-wise :func:`scale_per_point` when
        the pool carries a ``("scaled", local_model, foreign_model)`` tag). The
        mcstas engine fits the affine cost model and predicts at ``num_neutrons``;
        the deterministic engine (analytic cost ~independent of ncount) takes a
        flat weighted median instead.

        Returns ``{"per_point", "overhead", "rate", "fit", "ref_ncount"}`` with
        ``per_point`` ``None`` when no usable sample exists.
        """
        from datetime import datetime
        now = datetime.now()
        samples: List[Tuple[float, float, float]] = []  # (ncount, value, weight)
        for rec, scale in pairs:
            if not (rec.num_neutrons and rec.num_neutrons > 0 and rec.num_points > 0):
                continue
            spp = rec.avg_subsequent_time if rec.num_points > 1 else rec.first_scan_time
            if not spp or spp <= 0:
                continue
            if isinstance(scale, tuple) and scale and scale[0] == "scaled":
                _, local_model, foreign_model = scale
                value = scale_per_point(spp, rec.num_neutrons,
                                        local_model, foreign_model)
            else:
                value = spp * (1.0 if isinstance(scale, tuple) else scale)
            weight = self._record_weight(rec, now)
            samples.append((float(rec.num_neutrons), value, weight))

        empty = {"per_point": None, "overhead": None, "rate": None,
                 "fit": None, "ref_ncount": None}
        if not samples:
            return empty

        if engine == "deterministic":
            per_point = weighted_median([(v, w) for _, v, w in samples])
            return {"per_point": per_point, "overhead": None, "rate": None,
                    "fit": "flat", "ref_ncount": None}

        model = fit_affine_time_model(samples)
        per_point, tag = per_point_estimate(model, samples, num_neutrons)
        return {"per_point": per_point,
                "overhead": model.get("overhead") if model else None,
                "rate": model.get("rate") if model else None,
                "fit": tag,
                "ref_ncount": reference_ncount(model, samples)}

    def _compile_seconds(self, pairs: List[Tuple[ScanRecord, float]]) -> float:
        """Median compile time from non-reused records only (0.0 if none).

        Reused-binary records never contribute (their first point skips
        compilation, so ``first - avg`` would fabricate a compile time).
        Explicit ``compilation_time`` samples are preferred; only when none
        exist do we fall back to the ``first - avg`` inference. Each sample is
        scaled by its cross-machine speed ratio.
        """
        explicit: List[float] = []
        inferred: List[float] = []
        for rec, scale in pairs:
            if getattr(rec, "binary_reused", None) is True:
                continue
            if rec.compilation_time and rec.compilation_time > 0:
                explicit.append(rec.compilation_time * scale)
            elif rec.num_points > 1:
                value = rec.first_scan_time - rec.avg_subsequent_time
                if value > 0:
                    inferred.append(value * scale)
        comps = explicit if explicit else inferred
        if not comps:
            return 0.0
        comps.sort()
        mid = len(comps) // 2
        if len(comps) % 2:
            return comps[mid]
        return (comps[mid - 1] + comps[mid]) / 2.0

    def _cap_to(self, confidence: str, cap: str) -> str:
        """Lower ``confidence`` to ``cap`` when it exceeds it (never raises it)."""
        order = self._CONFIDENCE_ORDER
        return confidence if order.index(confidence) <= order.index(cap) else cap

    def _cap_confidence(self, confidence: str, basis: Optional[str]) -> str:
        """Apply the per-basis confidence cap (scaled/pooled capped 'low')."""
        cap = self._BASIS_CONFIDENCE_CAP.get(basis)
        if cap is None:
            return confidence
        return self._cap_to(confidence, cap)

    def _cap_confidence_for_fit(self, confidence: str,
                                model: Dict[str, object],
                                num_neutrons: int) -> str:
        """Cap confidence when predicting outside the observed ncount range.

        Degenerate extrapolation beyond ``EXTRAPOLATION_FACTOR`` of the anchor is
        forced 'low'; extrapolation within it, and affine prediction beyond the
        fitted range, are capped 'medium'.
        """
        ref = model.get("ref_ncount")
        fit = model.get("fit")
        far = bool(ref) and num_neutrons > self.EXTRAPOLATION_FACTOR * ref
        if fit == "extrapolated":
            return self._cap_to(confidence, "low" if far else "medium")
        if fit == "affine" and far:
            return self._cap_to(confidence, "medium")
        return confidence

    def estimate_scan_seconds(self,
                              instrument_name: str,
                              n_points: int,
                              num_neutrons: int,
                              needs_compile: bool = True,
                              engine: str = "mcstas",
                              source: Optional[str] = None,
                              mpi_count: Optional[int] = None) -> Dict[str, object]:
        """Estimate wall-clock seconds for a scan, with a confidence tier.

        Records are filtered to ``instrument_name`` + ``engine`` (and, when
        ``source`` is given, to that record source), then a machine selection
        chain (local -> legacy -> scaled -> pooled) picks the sample pool.
        Per-point time is a recency-weighted median over the K nearest ncount
        samples (linear ncount scaling for mcstas, flat for deterministic);
        compile time (from non-reused records) is added when ``needs_compile``.

        ``source`` is an optional filter (``"organic"`` | ``"benchmark"``); the
        default ``None`` pools both sources unchanged. It exists so the
        benchmark cross-check can compare a fresh benchmark measurement against
        the estimate organic history alone would have produced.

        Returns ``{"estimated_seconds": float|None, "confidence": str,
        "samples": int, "basis": str, "machine_samples": int}``. The ``basis``
        and ``machine_samples`` keys are additive (absent only on the no-data /
        invalid-input early return). ``estimated_seconds`` is ``None`` when
        there is no usable historical data or the inputs are invalid.
        """
        records = [r for r in (self.records.get(instrument_name, []) or [])
                   if getattr(r, "engine", "mcstas") == engine
                   and (source is None
                        or getattr(r, "source", "organic") == source)]
        samples = len(records)
        confidence = self._confidence_from_samples(samples)

        if (samples == 0 or num_neutrons is None or num_neutrons <= 0
                or n_points is None or n_points < 0):
            return {"estimated_seconds": None, "confidence": confidence,
                    "samples": samples}

        pairs, basis = self._select_pool(records)
        confidence = self._cap_confidence(confidence, basis)
        machine_samples = len(pairs)

        # MPI prefer-match: keep records whose worker count matches the request
        # (or is unknown). If none match, fall back to the full pool at low
        # confidence rather than blanking the estimate.
        preferred = [(r, s) for (r, s) in pairs
                     if getattr(r, "mpi_count", None) in (mpi_count, None)]
        if preferred:
            pairs = preferred
        else:
            confidence = self._cap_to(confidence, "low")

        model = self._per_point_model(pairs, num_neutrons, engine)
        per_point = model["per_point"]
        extra = {"per_point_seconds": per_point,
                 "overhead_seconds": model["overhead"],
                 "rate_per_neutron": model["rate"],
                 "fit": model["fit"]}
        if per_point is None:
            return {"estimated_seconds": None, "confidence": confidence,
                    "samples": samples, "basis": basis,
                    "machine_samples": machine_samples, **extra}

        confidence = self._cap_confidence_for_fit(confidence, model, num_neutrons)
        total = per_point * n_points
        if needs_compile:
            total += self._compile_seconds(pairs)
        return {"estimated_seconds": total, "confidence": confidence,
                "samples": samples, "basis": basis,
                "machine_samples": machine_samples, **extra}

    def has_data(self, instrument_name: str) -> bool:
        """Check if there is historical data for an instrument.
        
        Args:
            instrument_name: Name of the instrument
            
        Returns:
            True if at least one record exists for this instrument
        """
        return instrument_name in self.records and len(self.records[instrument_name]) > 0
    
    def get_record_count(self, instrument_name: str) -> int:
        """Get the number of records for an instrument.
        
        Args:
            instrument_name: Name of the instrument
            
        Returns:
            Number of scan records
        """
        return len(self.records.get(instrument_name, []))
    
    def clear_records(self, instrument_name: Optional[str] = None) -> int:
        """Clear runtime records.
        
        Args:
            instrument_name: Name of instrument to clear, or None to clear all
            
        Returns:
            Number of records cleared
        """
        if instrument_name is not None:
            count = len(self.records.get(instrument_name, []))
            if instrument_name in self.records:
                del self.records[instrument_name]
        else:
            count = sum(len(recs) for recs in self.records.values())
            self.records = {}
        
        self._save()
        return count
    
    @staticmethod
    def format_time(seconds: Optional[float]) -> str:
        """Format time in seconds to human-readable string.
        
        Args:
            seconds: Time in seconds, or None
            
        Returns:
            Formatted string like "1h 23m 45s" or "N/A" if None
        """
        if seconds is None:
            return "N/A"

        if seconds < 0:
            return "N/A"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60

        # For durations >= 1 hour, keep minutes and integer seconds
        if hours > 0:
            return f"{hours}h {minutes:02d}m {int(secs):02d}s"
        # For durations >= 1 minute but < 1 hour, show minutes and integer seconds
        elif minutes > 0:
            return f"{minutes}m {int(secs):02d}s"
        # For durations < 1 minute, show seconds with one decimal place
        else:
            return f"{secs:.1f}s"
