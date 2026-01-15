"""Dock widgets for TAVI application."""
from gui.docks.instrument_dock import InstrumentDock
from gui.docks.reciprocal_space_dock import ReciprocalSpaceDock
from gui.docks.sample_dock import SampleDock
from gui.docks.scan_controls_dock import ScanControlsDock, SimulationControlDock
from gui.docks.diagnostics_dock import DiagnosticsDock
from gui.docks.output_dock import OutputDock
from gui.docks.data_control_dock import DataControlDock
from gui.docks.misalignment_dock import MisalignmentDock

__all__ = [
    'InstrumentDock',
    'ReciprocalSpaceDock', 
    'SampleDock',
    'ScanControlsDock',
    'SimulationControlDock',
    'DiagnosticsDock',
    'OutputDock',
    'DataControlDock',
    'MisalignmentDock',
]
