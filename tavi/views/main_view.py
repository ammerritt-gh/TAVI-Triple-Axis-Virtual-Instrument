"""
Main View - The main application window that composes all docks.
"""
import tkinter as tk
from tkinter import ttk
import sys
from typing import Optional, Callable

from .docks import (
    InstrumentConfigDock,
    ReciprocalSpaceDock,
    SampleControlDock,
    ScanControlsDock,
    OutputDock,
    DataControlDock,
    DiagnosticsDialog,
)


class MainView:
    """
    The main application window.
    
    Composes all the dock widgets into a unified interface.
    """
    
    def __init__(self, title: str = "TAVI - Triple-Axis Virtual Instrument"):
        # Create main window
        self.root = tk.Tk()
        self.root.title(title)
        
        # Configure grid weights for resizing
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Create docks
        self._create_docks()
        
        # Quit callback
        self._quit_callback: Optional[Callable] = None
    
    def _create_docks(self):
        """Create all dock widgets."""
        # Left column: Instrument configuration
        left_frame = ttk.Frame(self.root)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        self.instrument_dock = InstrumentConfigDock(left_frame)
        self.instrument_dock.pack(fill=tk.BOTH, expand=True)
        
        # Middle column: Scan controls and reciprocal space
        middle_frame = ttk.Frame(self.root)
        middle_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        
        # Reciprocal space at top
        self.reciprocal_dock = ReciprocalSpaceDock(middle_frame)
        self.reciprocal_dock.pack(fill=tk.X)
        
        # Sample control
        self.sample_dock = SampleControlDock(middle_frame)
        self.sample_dock.pack(fill=tk.X, pady=10)
        
        # Scan controls
        self.scan_dock = ScanControlsDock(middle_frame)
        self.scan_dock.pack(fill=tk.X, pady=10)
        
        # Quit button at bottom of middle
        quit_frame = ttk.Frame(middle_frame)
        quit_frame.pack(fill=tk.X, pady=10)
        
        self.quit_button = ttk.Button(
            quit_frame,
            text="Quit",
            command=self._on_quit
        )
        self.quit_button.pack(side=tk.LEFT, padx=5)
        
        # Right column: Output and data control
        right_frame = ttk.Frame(self.root)
        right_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        
        # Output dock
        self.output_dock = OutputDock(right_frame)
        self.output_dock.pack(fill=tk.BOTH, expand=True)
        
        # Data control
        self.data_dock = DataControlDock(right_frame)
        self.data_dock.pack(fill=tk.X, pady=10)
    
    def _on_quit(self):
        """Handle quit button click."""
        if self._quit_callback:
            self._quit_callback()
        self.root.quit()
        sys.exit()
    
    def set_quit_callback(self, callback: Callable):
        """Set the callback for quit button."""
        self._quit_callback = callback
    
    def show_diagnostics_dialog(self, initial_values: dict = None) -> Optional[dict]:
        """
        Show the diagnostics configuration dialog.
        
        Args:
            initial_values: Initial diagnostic settings
            
        Returns:
            Updated diagnostic settings, or None if cancelled
        """
        dialog = DiagnosticsDialog(self.root)
        return dialog.show(initial_values)
    
    def log(self, message: str, target: str = 'both'):
        """Log a message to the output dock."""
        self.output_dock.log(message, target)
    
    def update_progress(self, current: int, total: int):
        """Update progress display."""
        self.output_dock.update_progress(current, total)
    
    def update_remaining_time(self, time_str: str):
        """Update remaining time display."""
        self.output_dock.update_remaining_time(time_str)
    
    def update_counts(self, max_counts: float, total_counts: float):
        """Update counts display."""
        self.output_dock.update_counts(max_counts, total_counts)
    
    def update_actual_folder(self, folder: str):
        """Update the actual output folder display."""
        self.data_dock.update_actual_folder(folder)
    
    def set_running_state(self, running: bool):
        """Update UI state based on whether simulation is running."""
        self.scan_dock.set_running_state(running)
    
    def run(self):
        """Start the main event loop."""
        self.root.mainloop()
    
    def update(self):
        """Force an update of the GUI."""
        self.root.update()
