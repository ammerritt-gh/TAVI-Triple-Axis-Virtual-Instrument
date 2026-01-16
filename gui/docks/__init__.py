"""Dock widgets for TAVI application."""
from gui.docks.instrument_dock import InstrumentDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock

# Unified docks (new architecture)
from gui.docks.unified_scattering_dock import UnifiedScatteringDock
from gui.docks.unified_sample_dock import UnifiedSampleDock
from gui.docks.unified_simulation_dock import UnifiedSimulationDock

# Legacy docks (kept for backward compatibility)
from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock
from gui.docks.sample_dock import SampleDock
from gui.docks.scan_controls_dock import ScanControlsDock, SimulationControlDock
from gui.docks.diagnostics_dock import DiagnosticsDock
from gui.docks.misalignment_dock import MisalignmentDock

__all__ = [
    # Core docks
    'InstrumentDock',
    'OutputDock',
    'DataControlDock',
    # Unified docks (new)
    'UnifiedScatteringDock',
    'UnifiedSampleDock', 
    'UnifiedSimulationDock',
    # Legacy docks
    'ReciprocalSpaceDock', 
    'SampleDock',
    'ScanControlsDock',
    'SimulationControlDock',
    'DiagnosticsDock',
    'MisalignmentDock',
]
