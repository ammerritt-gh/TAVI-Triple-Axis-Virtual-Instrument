"""
Scan Controls Dock - Controls for scan configuration and execution.

Includes:
- Number of neutrons
- Ki/Kf fixed mode selection
- Fixed energy value
- Scan command entries
- Run/Stop buttons
- Diagnostic mode toggle
"""
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Callable

from .base_dock import BaseDock


class ScanControlsDock(BaseDock):
    """Dock for scan control settings."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create tk variables
        self.number_neutrons_var = tk.IntVar()
        self.K_fixed_var = tk.StringVar()
        self.fixed_E_var = tk.StringVar()
        self.scan_command1_var = tk.StringVar()
        self.scan_command2_var = tk.StringVar()
        self.diagnostic_mode_var = tk.BooleanVar()
        
        # Callbacks
        self._run_callback: Optional[Callable] = None
        self._stop_callback: Optional[Callable] = None
        self._validate_callback: Optional[Callable] = None
        self._configure_diagnostics_callback: Optional[Callable] = None
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create scan control widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Scan Controls", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Neutrons
        neutron_frame = ttk.LabelFrame(main_frame, text="Simulation", padding="5")
        neutron_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(neutron_frame, text="# Neutrons:").grid(row=0, column=0, sticky="w")
        self.neutrons_entry = ttk.Entry(neutron_frame, textvariable=self.number_neutrons_var, width=12)
        self.neutrons_entry.grid(row=0, column=1, padx=2, pady=2)
        
        # Fixed mode
        mode_frame = ttk.LabelFrame(main_frame, text="Fixed Mode", padding="5")
        mode_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(mode_frame, text="Mode:").grid(row=0, column=0, sticky="w")
        self.mode_combo = ttk.Combobox(mode_frame, textvariable=self.K_fixed_var,
                                        values=["Ki Fixed", "Kf Fixed"], width=12)
        self.mode_combo.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(mode_frame, text="Fixed E:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.fixed_E_entry = ttk.Entry(mode_frame, textvariable=self.fixed_E_var, width=10)
        self.fixed_E_entry.grid(row=0, column=3, padx=2, pady=2)
        ttk.Label(mode_frame, text="meV").grid(row=0, column=4, sticky="w")
        
        # Scan commands
        scan_frame = ttk.LabelFrame(main_frame, text="Scan Commands", padding="5")
        scan_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(scan_frame, text="Scan 1:").grid(row=0, column=0, sticky="w")
        self.scan1_entry = ttk.Entry(scan_frame, textvariable=self.scan_command1_var, width=25)
        self.scan1_entry.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(scan_frame, text="Scan 2:").grid(row=1, column=0, sticky="w")
        self.scan2_entry = ttk.Entry(scan_frame, textvariable=self.scan_command2_var, width=25)
        self.scan2_entry.grid(row=1, column=1, padx=2, pady=2)
        
        # Help text
        help_text = "Format: variable start end step (e.g., 'qx 2 2.5 0.1')"
        ttk.Label(scan_frame, text=help_text, font=("Arial", 8)).grid(row=2, column=0, columnspan=2, sticky="w")
        
        # Diagnostic mode
        diag_frame = ttk.Frame(main_frame)
        diag_frame.pack(fill=tk.X, pady=5)
        
        self.diag_check = ttk.Checkbutton(
            diag_frame, 
            text="Diagnostic Mode",
            variable=self.diagnostic_mode_var
        )
        self.diag_check.pack(side=tk.LEFT)
        
        self.diag_config_button = ttk.Button(
            diag_frame,
            text="Configure...",
            command=self._on_configure_diagnostics
        )
        self.diag_config_button.pack(side=tk.LEFT, padx=10)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.run_button = ttk.Button(
            button_frame,
            text="Run Simulation",
            command=self._on_run
        )
        self.run_button.pack(side=tk.LEFT, padx=2)
        
        self.stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self._on_stop
        )
        self.stop_button.pack(side=tk.LEFT, padx=2)
        
        self.validate_button = ttk.Button(
            button_frame,
            text="Validate",
            command=self._on_validate
        )
        self.validate_button.pack(side=tk.LEFT, padx=2)
    
    def _on_run(self):
        """Handle run button click."""
        self._trigger_callback("run")
        if self._run_callback:
            self._run_callback()
    
    def _on_stop(self):
        """Handle stop button click."""
        self._trigger_callback("stop")
        if self._stop_callback:
            self._stop_callback()
    
    def _on_validate(self):
        """Handle validate button click."""
        self._trigger_callback("validate")
        if self._validate_callback:
            self._validate_callback()
    
    def _on_configure_diagnostics(self):
        """Handle configure diagnostics button click."""
        self._trigger_callback("configure_diagnostics")
        if self._configure_diagnostics_callback:
            self._configure_diagnostics_callback()
    
    def set_run_callback(self, callback: Callable):
        """Set the callback for the run button."""
        self._run_callback = callback
    
    def set_stop_callback(self, callback: Callable):
        """Set the callback for the stop button."""
        self._stop_callback = callback
    
    def set_validate_callback(self, callback: Callable):
        """Set the callback for the validate button."""
        self._validate_callback = callback
    
    def set_configure_diagnostics_callback(self, callback: Callable):
        """Set the callback for the configure diagnostics button."""
        self._configure_diagnostics_callback = callback
    
    def set_running_state(self, running: bool):
        """Update UI state based on whether simulation is running."""
        if running:
            self.run_button.config(state="disabled")
            self.stop_button.config(state="normal")
        else:
            self.run_button.config(state="normal")
            self.stop_button.config(state="disabled")
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the dock."""
        return {
            "number_neutrons": self.number_neutrons_var.get(),
            "K_fixed": self.K_fixed_var.get(),
            "fixed_E": self.fixed_E_var.get(),
            "scan_command1": self.scan_command1_var.get(),
            "scan_command2": self.scan_command2_var.get(),
            "diagnostic_mode": self.diagnostic_mode_var.get(),
        }
    
    def set_values(self, values: Dict[str, Any]):
        """Set values in the dock from a dictionary."""
        if "number_neutrons" in values:
            self.number_neutrons_var.set(int(values["number_neutrons"]))
        if "K_fixed" in values:
            self.K_fixed_var.set(values["K_fixed"])
        if "fixed_E" in values:
            self.fixed_E_var.set(str(values["fixed_E"]))
        if "scan_command1" in values:
            self.scan_command1_var.set(values["scan_command1"])
        if "scan_command2" in values:
            self.scan_command2_var.set(values["scan_command2"])
        if "diagnostic_mode" in values:
            self.diagnostic_mode_var.set(values["diagnostic_mode"])
