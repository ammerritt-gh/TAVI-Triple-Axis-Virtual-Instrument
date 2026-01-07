"""
TAVI Docks - Dock widgets for the GUI.
"""
from .base_dock import BaseDock, DockSection
from .instrument_config_dock import InstrumentConfigDock
from .reciprocal_space_dock import ReciprocalSpaceDock
from .sample_control_dock import SampleControlDock
from .scan_controls_dock import ScanControlsDock
from .output_dock import OutputDock
from .data_control_dock import DataControlDock
from .diagnostics_dock import DiagnosticsDock, DiagnosticsDialog

__all__ = [
    "BaseDock",
    "DockSection",
    "InstrumentConfigDock",
    "ReciprocalSpaceDock",
    "SampleControlDock",
    "ScanControlsDock",
    "OutputDock",
    "DataControlDock",
    "DiagnosticsDock",
    "DiagnosticsDialog",
]
