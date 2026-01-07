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

__version__ = "2.0.0"

# Lazy imports to avoid loading tkinter when not needed
def _get_application():
    from .application import Application
    return Application

def _get_main():
    from .application import main
    return main

def _get_application_model():
    from .models import ApplicationModel
    return ApplicationModel

def _get_main_view():
    from .views import MainView
    return MainView

def _get_scan_controller():
    from .controllers import ScanController
    return ScanController

def _get_puma_instrument():
    from .instruments import PUMAInstrument
    return PUMAInstrument

# For convenience, expose as module-level attributes via __getattr__
def __getattr__(name):
    if name == "Application":
        return _get_application()
    elif name == "main":
        return _get_main()
    elif name == "ApplicationModel":
        return _get_application_model()
    elif name == "MainView":
        return _get_main_view()
    elif name == "ScanController":
        return _get_scan_controller()
    elif name == "PUMAInstrument":
        return _get_puma_instrument()
    raise AttributeError(f"module 'tavi' has no attribute '{name}'")

__all__ = [
    "Application",
    "main",
    "ApplicationModel",
    "MainView",
    "ScanController",
    "PUMAInstrument",
]
