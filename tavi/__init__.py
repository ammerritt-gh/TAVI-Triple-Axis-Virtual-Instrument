"""
TAVI - Triple-Axis Virtual Instrument

A virtual instrument simulation package for triple-axis spectrometers.
This package uses an MVVM (Model-View-ViewModel) architecture for clean
separation of concerns.

Modules:
- models: State management classes
- views: GUI components
- viewmodels: Data binding and presentation logic
- controllers: Business logic and command handling
- instruments: Instrument definitions

Usage:
    from tavi import Application
    app = Application()
    app.run()
"""

from .application import Application, main
from .models import ApplicationModel
from .views import MainView
from .controllers import ScanController
from .instruments import PUMAInstrument

__version__ = "2.0.0"
__all__ = [
    "Application",
    "main",
    "ApplicationModel",
    "MainView",
    "ScanController",
    "PUMAInstrument",
]
