"""
Diagnostics Dock - Controls for diagnostic monitor settings.

A popup window for configuring which diagnostic monitors are enabled.
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Callable, Optional, List

from .base_dock import BaseDock


class DiagnosticsDock(BaseDock):
    """Dock for diagnostics configuration (usually shown as a dialog)."""
    
    # Default diagnostic options
    DIAGNOSTIC_OPTIONS = [
        "Source PSD",
        "Source DSD",
        "Postcollimation PSD",
        "Postcollimation DSD",
        "Premono Emonitor",
        "Postmono Emonitor",
        "Pre-sample collimation PSD",
        "Sample PSD @ L2-0.5",
        "Sample PSD @ L2-0.3",
        "Sample PSD @ Sample",
        "Sample DSD @ Sample",
        "Sample EMonitor @ Sample",
        "Pre-analyzer collimation PSD",
        "Pre-analyzer EMonitor",
        "Pre-analyzer PSD",
        "Post-analyzer EMonitor",
        "Post-analyzer PSD",
        "Detector PSD"
    ]
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create variables for each diagnostic option
        self.diagnostic_vars: Dict[str, tk.BooleanVar] = {}
        for option in self.DIAGNOSTIC_OPTIONS:
            self.diagnostic_vars[option] = tk.BooleanVar(value=False)
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create diagnostics widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Diagnostic Options", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Explanation
        explanation = (
            "Select diagnostic monitors to enable:\n"
            "PSD: Position Sensitive Detector\n"
            "DSD: Divergence Sensitive Detector\n"
            "Emonitor: Energy Monitor"
        )
        ttk.Label(main_frame, text=explanation, justify="left").pack(anchor="w", pady=5)
        
        # Checkboxes in a scrollable frame
        canvas = tk.Canvas(main_frame, height=300)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Create checkboxes for each option
        for i, option in enumerate(self.DIAGNOSTIC_OPTIONS):
            var = self.diagnostic_vars[option]
            check = ttk.Checkbutton(scrollable_frame, text=option, variable=var)
            check.grid(row=i, column=0, sticky="w", pady=2)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.select_all_button = ttk.Button(
            button_frame,
            text="Select All",
            command=self._select_all
        )
        self.select_all_button.pack(side=tk.LEFT, padx=2)
        
        self.clear_all_button = ttk.Button(
            button_frame,
            text="Clear All",
            command=self._clear_all
        )
        self.clear_all_button.pack(side=tk.LEFT, padx=2)
    
    def _select_all(self):
        """Select all diagnostic options."""
        for var in self.diagnostic_vars.values():
            var.set(True)
    
    def _clear_all(self):
        """Clear all diagnostic options."""
        for var in self.diagnostic_vars.values():
            var.set(False)
    
    def get_values(self) -> Dict[str, bool]:
        """Get all diagnostic settings."""
        return {name: var.get() for name, var in self.diagnostic_vars.items()}
    
    def set_values(self, values: Dict[str, bool]):
        """Set diagnostic settings from a dictionary."""
        for name, value in values.items():
            if name in self.diagnostic_vars:
                self.diagnostic_vars[name].set(value)
    
    def get_enabled_diagnostics(self) -> List[str]:
        """Get a list of enabled diagnostic options."""
        return [name for name, var in self.diagnostic_vars.items() if var.get()]


class DiagnosticsDialog:
    """
    A dialog window for configuring diagnostic settings.
    
    This is used when the user clicks "Configure..." in the scan controls.
    """
    
    def __init__(self, parent: tk.Widget, title: str = "Diagnostic Options"):
        self.parent = parent
        self.title = title
        self.result: Optional[Dict[str, bool]] = None
        self._window: Optional[tk.Toplevel] = None
        self._dock: Optional[DiagnosticsDock] = None
    
    def show(self, initial_values: Dict[str, bool] = None) -> Optional[Dict[str, bool]]:
        """
        Show the dialog and return the result.
        
        Args:
            initial_values: Initial diagnostic settings
            
        Returns:
            Dictionary of diagnostic settings, or None if cancelled
        """
        self._window = tk.Toplevel(self.parent)
        self._window.title(self.title)
        self._window.transient(self.parent)
        self._window.grab_set()
        
        # Create dock
        self._dock = DiagnosticsDock(self._window)
        self._dock.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        if initial_values:
            self._dock.set_values(initial_values)
        
        # Save/Cancel buttons
        button_frame = ttk.Frame(self._window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Save", command=self._on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).pack(side=tk.LEFT, padx=5)
        
        # Center the window
        self._window.update_idletasks()
        width = self._window.winfo_width()
        height = self._window.winfo_height()
        x = (self._window.winfo_screenwidth() // 2) - (width // 2)
        y = (self._window.winfo_screenheight() // 2) - (height // 2)
        self._window.geometry(f'+{x}+{y}')
        
        # Wait for window to close
        self._window.wait_window()
        
        return self.result
    
    def _on_save(self):
        """Handle save button."""
        self.result = self._dock.get_values()
        self._window.destroy()
    
    def _on_cancel(self):
        """Handle cancel button."""
        self.result = None
        self._window.destroy()
