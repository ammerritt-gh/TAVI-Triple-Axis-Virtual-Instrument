"""
Data Control Dock - Controls for data input/output.

Includes:
- Output folder selection
- Data loading
- Save/Load parameters
"""
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Any, Dict, Optional, Callable
import os

from .base_dock import BaseDock


class DataControlDock(BaseDock):
    """Dock for data input/output controls."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create tk variables
        self.output_folder_var = tk.StringVar()
        self.actual_folder_var = tk.StringVar()
        self.load_folder_var = tk.StringVar()
        
        # Callbacks
        self._save_params_callback: Optional[Callable] = None
        self._load_params_callback: Optional[Callable] = None
        self._load_defaults_callback: Optional[Callable] = None
        self._load_data_callback: Optional[Callable] = None
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create data control widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Data Control", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Output folder section
        output_frame = ttk.LabelFrame(main_frame, text="Output", padding="5")
        output_frame.pack(fill=tk.X, pady=5)
        
        # Target folder
        target_row = ttk.Frame(output_frame)
        target_row.pack(fill=tk.X, pady=2)
        
        ttk.Label(target_row, text="Target folder:").pack(side=tk.LEFT)
        self.browse_button = ttk.Button(
            target_row,
            text="Browse",
            command=self._on_browse_output
        )
        self.browse_button.pack(side=tk.LEFT, padx=10)
        
        self.output_entry = ttk.Entry(output_frame, textvariable=self.output_folder_var, width=80)
        self.output_entry.pack(fill=tk.X, pady=2)
        
        # Actual folder
        actual_row = ttk.Frame(output_frame)
        actual_row.pack(fill=tk.X, pady=2)
        
        ttk.Label(actual_row, text="Actual folder:").pack(side=tk.LEFT)
        self.actual_label = ttk.Label(actual_row, textvariable=self.actual_folder_var, 
                                       relief="sunken", width=70)
        self.actual_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        # Load data section
        load_frame = ttk.LabelFrame(main_frame, text="Load Data", padding="5")
        load_frame.pack(fill=tk.X, pady=5)
        
        load_row = ttk.Frame(load_frame)
        load_row.pack(fill=tk.X, pady=2)
        
        ttk.Label(load_row, text="Folder:").pack(side=tk.LEFT)
        self.load_browse_button = ttk.Button(
            load_row,
            text="Browse",
            command=self._on_browse_load
        )
        self.load_browse_button.pack(side=tk.LEFT, padx=10)
        
        self.load_button = ttk.Button(
            load_row,
            text="Load",
            command=self._on_load_data
        )
        self.load_button.pack(side=tk.LEFT, padx=5)
        
        self.load_entry = ttk.Entry(load_frame, textvariable=self.load_folder_var, width=80)
        self.load_entry.pack(fill=tk.X, pady=2)
        
        # Parameters section
        params_frame = ttk.LabelFrame(main_frame, text="Parameters", padding="5")
        params_frame.pack(fill=tk.X, pady=5)
        
        button_row = ttk.Frame(params_frame)
        button_row.pack(fill=tk.X, pady=2)
        
        self.save_params_button = ttk.Button(
            button_row,
            text="Save Parameters",
            command=self._on_save_params
        )
        self.save_params_button.pack(side=tk.LEFT, padx=2)
        
        self.load_params_button = ttk.Button(
            button_row,
            text="Load Parameters",
            command=self._on_load_params
        )
        self.load_params_button.pack(side=tk.LEFT, padx=2)
        
        self.defaults_button = ttk.Button(
            button_row,
            text="Load Defaults",
            command=self._on_load_defaults
        )
        self.defaults_button.pack(side=tk.LEFT, padx=2)
    
    def _on_browse_output(self):
        """Handle browse output folder button."""
        default_folder = os.getcwd()
        folder = filedialog.askdirectory(initialdir=default_folder)
        if folder:
            self.output_folder_var.set(folder)
    
    def _on_browse_load(self):
        """Handle browse load folder button."""
        default_folder = os.getcwd()
        folder = filedialog.askdirectory(initialdir=default_folder)
        if folder:
            self.load_folder_var.set(folder)
    
    def _on_load_data(self):
        """Handle load data button."""
        self._trigger_callback("load_data")
        if self._load_data_callback:
            self._load_data_callback(self.load_folder_var.get())
    
    def _on_save_params(self):
        """Handle save parameters button."""
        self._trigger_callback("save_params")
        if self._save_params_callback:
            self._save_params_callback()
    
    def _on_load_params(self):
        """Handle load parameters button."""
        self._trigger_callback("load_params")
        if self._load_params_callback:
            self._load_params_callback()
    
    def _on_load_defaults(self):
        """Handle load defaults button."""
        self._trigger_callback("load_defaults")
        if self._load_defaults_callback:
            self._load_defaults_callback()
    
    def set_save_params_callback(self, callback: Callable):
        """Set the callback for save parameters."""
        self._save_params_callback = callback
    
    def set_load_params_callback(self, callback: Callable):
        """Set the callback for load parameters."""
        self._load_params_callback = callback
    
    def set_load_defaults_callback(self, callback: Callable):
        """Set the callback for load defaults."""
        self._load_defaults_callback = callback
    
    def set_load_data_callback(self, callback: Callable):
        """Set the callback for load data."""
        self._load_data_callback = callback
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the dock."""
        return {
            "output_folder": self.output_folder_var.get(),
            "load_folder": self.load_folder_var.get(),
        }
    
    def set_values(self, values: Dict[str, Any]):
        """Set values in the dock from a dictionary."""
        if "output_folder" in values:
            self.output_folder_var.set(values["output_folder"])
        if "actual_folder" in values:
            self.actual_folder_var.set(values["actual_folder"])
        if "load_folder" in values:
            self.load_folder_var.set(values["load_folder"])
    
    def update_actual_folder(self, folder: str):
        """Update the actual output folder display."""
        self.actual_folder_var.set(folder)
