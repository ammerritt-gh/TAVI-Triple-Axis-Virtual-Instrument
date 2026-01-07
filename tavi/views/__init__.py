"""
TAVI Views - GUI components for the application.
"""
from .main_view import MainView
from .docks import (
    BaseDock,
    DockSection,
    InstrumentConfigDock,
    ReciprocalSpaceDock,
    SampleControlDock,
    ScanControlsDock,
    OutputDock,
    DataControlDock,
    DiagnosticsDock,
    DiagnosticsDialog,
)

__all__ = [
    "MainView",
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
