"""
Sample Control Dock - Controls for sample configuration.

Includes:
- Lattice parameters (a, b, c, alpha, beta, gamma)
- Space group (for future Bragg peak calculations)
- Sample configuration button
"""
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Callable

from .base_dock import BaseDock


class SampleControlDock(BaseDock):
    """Dock for sample control settings."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create tk variables
        self.lattice_a_var = tk.DoubleVar()
        self.lattice_b_var = tk.DoubleVar()
        self.lattice_c_var = tk.DoubleVar()
        self.lattice_alpha_var = tk.DoubleVar()
        self.lattice_beta_var = tk.DoubleVar()
        self.lattice_gamma_var = tk.DoubleVar()
        self.space_group_var = tk.StringVar()
        
        self._configure_sample_callback: Optional[Callable] = None
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create sample control widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Sample Control", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Lattice parameters
        lattice_frame = ttk.LabelFrame(main_frame, text="Lattice Parameters", padding="5")
        lattice_frame.pack(fill=tk.X, pady=5)
        
        # Lengths row
        lengths_frame = ttk.Frame(lattice_frame)
        lengths_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(lengths_frame, text="a:").pack(side=tk.LEFT)
        self.a_entry = ttk.Entry(lengths_frame, textvariable=self.lattice_a_var, width=8)
        self.a_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(lengths_frame, text="b:").pack(side=tk.LEFT, padx=(10, 0))
        self.b_entry = ttk.Entry(lengths_frame, textvariable=self.lattice_b_var, width=8)
        self.b_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(lengths_frame, text="c:").pack(side=tk.LEFT, padx=(10, 0))
        self.c_entry = ttk.Entry(lengths_frame, textvariable=self.lattice_c_var, width=8)
        self.c_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(lengths_frame, text="(Å)").pack(side=tk.LEFT, padx=5)
        
        # Angles row
        angles_frame = ttk.Frame(lattice_frame)
        angles_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(angles_frame, text="α:").pack(side=tk.LEFT)
        self.alpha_entry = ttk.Entry(angles_frame, textvariable=self.lattice_alpha_var, width=8)
        self.alpha_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(angles_frame, text="β:").pack(side=tk.LEFT, padx=(10, 0))
        self.beta_entry = ttk.Entry(angles_frame, textvariable=self.lattice_beta_var, width=8)
        self.beta_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(angles_frame, text="γ:").pack(side=tk.LEFT, padx=(10, 0))
        self.gamma_entry = ttk.Entry(angles_frame, textvariable=self.lattice_gamma_var, width=8)
        self.gamma_entry.pack(side=tk.LEFT, padx=2)
        
        ttk.Label(angles_frame, text="(deg)").pack(side=tk.LEFT, padx=5)
        
        # Space group
        spacegroup_frame = ttk.LabelFrame(main_frame, text="Space Group", padding="5")
        spacegroup_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(spacegroup_frame, text="Space Group:").pack(side=tk.LEFT)
        self.spacegroup_entry = ttk.Entry(spacegroup_frame, textvariable=self.space_group_var, width=15)
        self.spacegroup_entry.pack(side=tk.LEFT, padx=5)
        
        # Sample configuration button
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.config_button = ttk.Button(
            button_frame, 
            text="Sample Configuration...",
            command=self._on_configure_sample
        )
        self.config_button.pack(side=tk.LEFT)
    
    def _on_configure_sample(self):
        """Handle sample configuration button click."""
        self._trigger_callback("configure_sample")
        if self._configure_sample_callback:
            self._configure_sample_callback()
    
    def set_configure_sample_callback(self, callback: Callable):
        """Set the callback for the configure sample button."""
        self._configure_sample_callback = callback
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the dock."""
        return {
            "lattice_a": self.lattice_a_var.get(),
            "lattice_b": self.lattice_b_var.get(),
            "lattice_c": self.lattice_c_var.get(),
            "lattice_alpha": self.lattice_alpha_var.get(),
            "lattice_beta": self.lattice_beta_var.get(),
            "lattice_gamma": self.lattice_gamma_var.get(),
            "space_group": self.space_group_var.get(),
        }
    
    def set_values(self, values: Dict[str, Any]):
        """Set values in the dock from a dictionary."""
        if "lattice_a" in values:
            self.lattice_a_var.set(values["lattice_a"])
        if "lattice_b" in values:
            self.lattice_b_var.set(values["lattice_b"])
        if "lattice_c" in values:
            self.lattice_c_var.set(values["lattice_c"])
        if "lattice_alpha" in values:
            self.lattice_alpha_var.set(values["lattice_alpha"])
        if "lattice_beta" in values:
            self.lattice_beta_var.set(values["lattice_beta"])
        if "lattice_gamma" in values:
            self.lattice_gamma_var.set(values["lattice_gamma"])
        if "space_group" in values:
            self.space_group_var.set(values["space_group"])
