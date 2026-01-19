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
from dataclasses import dataclass, asdict


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
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the runtime tracker.
        
        Args:
            config_path: Path to config file, defaults to config/runtimes.json
        """
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.max_records = self.MAX_RECORDS
        self.records: Dict[str, List[ScanRecord]] = {}
        self._load()
    
    def _load(self) -> None:
        """Load runtime records from config file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                
                self.records = {}
                for instrument, record_list in data.get('records', {}).items():
                    self.records[instrument] = [
                        ScanRecord(**rec) for rec in record_list
                    ]
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"Warning: Could not load runtimes.json: {e}")
                self.records = {}
        else:
            self.records = {}
    
    def _save(self) -> None:
        """Save runtime records to config file."""
        # Ensure config directory exists
        os.makedirs(os.path.dirname(self.config_path) or '.', exist_ok=True)
        
        data = {
            'records': {
                instrument: [asdict(rec) for rec in record_list]
                for instrument, record_list in self.records.items()
            }
        }
        
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_record(self, 
                   instrument_name: str,
                   num_points: int,
                   num_neutrons: int,
                   first_scan_time: float,
                   avg_subsequent_time: float,
                   total_time: float) -> None:
        """Add a new scan record.
        
        Args:
            instrument_name: Name of the instrument (e.g., 'PUMA')
            num_points: Total number of scan points
            num_neutrons: Number of neutrons per point
            first_scan_time: Time for first point (compile + run)
            avg_subsequent_time: Average time for subsequent points (run only)
            total_time: Total scan time
        """
        from datetime import datetime
        
        record = ScanRecord(
            instrument_name=instrument_name,
            num_points=num_points,
            num_neutrons=num_neutrons,
            first_scan_time=first_scan_time,
            avg_subsequent_time=avg_subsequent_time,
            total_time=total_time,
            timestamp=datetime.now().isoformat()
        )
        
        if instrument_name not in self.records:
            self.records[instrument_name] = []
        
        self.records[instrument_name].append(record)
        
        # Trim old records if exceeding max
        if len(self.records[instrument_name]) > self.max_records:
            self.records[instrument_name] = self.records[instrument_name][-self.max_records:]
        
        self._save()
    
    def get_estimates(self, instrument_name: str, num_neutrons: int) -> Tuple[Optional[float], Optional[float]]:
        """Get estimated compile time and per-point run time.
        
        Compile time is estimated as: first_scan_time - avg_subsequent_time
        Run time is normalized by neutron count assuming linear scaling.
        
        Args:
            instrument_name: Name of the instrument
            num_neutrons: Number of neutrons for the upcoming scan
            
        Returns:
            Tuple of (compile_time_estimate, run_time_per_point_estimate).
            Returns (None, None) if no historical data available.
        """
        if instrument_name not in self.records or not self.records[instrument_name]:
            return (None, None)
        
        records = self.records[instrument_name]
        
        # Calculate averages from all records
        compile_times = []
        normalized_run_times = []  # Run time per neutron
        
        for rec in records:
            if rec.num_neutrons > 0 and rec.num_points > 0:
                # Compile time = first scan time - average subsequent time
                # This is the overhead of first compilation
                compile_time = rec.first_scan_time - rec.avg_subsequent_time
                if compile_time > 0:  # Only use positive compile times
                    compile_times.append(compile_time)
                
                # Normalize run time by neutron count
                # run_time_per_neutron = avg_subsequent_time / num_neutrons
                normalized_run_time = rec.avg_subsequent_time / rec.num_neutrons
                normalized_run_times.append(normalized_run_time)
        
        if not compile_times and not normalized_run_times:
            return (None, None)
        
        # Average compile time (not dependent on neutrons)
        avg_compile_time = sum(compile_times) / len(compile_times) if compile_times else 0.0
        
        # Average normalized run time, then scale by requested neutrons
        if normalized_run_times:
            avg_normalized_run_time = sum(normalized_run_times) / len(normalized_run_times)
            run_time_per_point = avg_normalized_run_time * num_neutrons
        else:
            run_time_per_point = None
        
        return (avg_compile_time, run_time_per_point)
    
    def estimate_total_time(self, 
                           instrument_name: str, 
                           num_points: int, 
                           num_neutrons: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Estimate total scan time including compile time.
        
        Args:
            instrument_name: Name of the instrument
            num_points: Number of scan points
            num_neutrons: Number of neutrons per point
            
        Returns:
            Tuple of (total_time, compile_time, run_time_per_point).
            Any value may be None if no historical data.
        """
        compile_time, run_time_per_point = self.get_estimates(instrument_name, num_neutrons)
        
        if compile_time is None or run_time_per_point is None:
            return (None, None, None)
        
        # Total = compile_time + (num_points * run_time_per_point)
        # Note: First point includes compile, so we don't double-count
        total_time = compile_time + (num_points * run_time_per_point)
        
        return (total_time, compile_time, run_time_per_point)
    
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
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        elif minutes > 0:
            return f"{minutes}m {secs:02d}s"
        else:
            return f"{secs}s"
