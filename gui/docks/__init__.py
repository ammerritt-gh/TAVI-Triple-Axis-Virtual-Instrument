"""Dock widgets for TAVI application."""
from gui.docks.instrument_dock import InstrumentDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock
from gui.docks.unified_scattering_dock import UnifiedScatteringDock
from gui.docks.unified_sample_dock import UnifiedSampleDock
from gui.docks.unified_simulation_dock import UnifiedSimulationDock

__all__ = [
    'InstrumentDock',
    'OutputDock',
    'DataControlDock',
    'UnifiedScatteringDock',
    'UnifiedSampleDock', 
    'UnifiedSimulationDock',
]
