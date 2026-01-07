"""
Reciprocal Space Dock - Controls for reciprocal lattice space.

Includes:
- Absolute momentum transfer (qx, qy, qz in 1/Å)
- Relative HKL units
- Energy transfer (deltaE)
"""
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict

from .base_dock import BaseDock


class ReciprocalSpaceDock(BaseDock):
    """Dock for reciprocal space controls."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create tk variables
        self.qx_var = tk.DoubleVar()
        self.qy_var = tk.DoubleVar()
        self.qz_var = tk.DoubleVar()
        self.H_var = tk.StringVar()
        self.K_var = tk.StringVar()
        self.L_var = tk.StringVar()
        self.deltaE_var = tk.StringVar()
        self.sample_frame_mode_var = tk.BooleanVar()
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create reciprocal space widgets."""
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Reciprocal Space", 
                  font=("Arial", 10, "bold")).pack(anchor="w")
        
        # Mode selection
        mode_frame = ttk.Frame(main_frame)
        mode_frame.pack(fill=tk.X, pady=5)
        
        self.sample_mode_check = ttk.Checkbutton(
            mode_frame, text="Sample Frame Mode (HKL)", 
            variable=self.sample_frame_mode_var,
            command=self._on_mode_change
        )
        self.sample_mode_check.pack(side=tk.LEFT)
        
        # Q-space section
        q_frame = ttk.LabelFrame(main_frame, text="Absolute (1/Å)", padding="5")
        q_frame.pack(fill=tk.X, pady=5)
        
        # qx
        ttk.Label(q_frame, text="qx:").grid(row=0, column=0, sticky="w")
        self.qx_entry = ttk.Entry(q_frame, textvariable=self.qx_var, width=10)
        self.qx_entry.grid(row=0, column=1, padx=2, pady=2)
        ttk.Label(q_frame, text="1/Å").grid(row=0, column=2, sticky="w")
        
        # qy
        ttk.Label(q_frame, text="qy:").grid(row=1, column=0, sticky="w")
        self.qy_entry = ttk.Entry(q_frame, textvariable=self.qy_var, width=10)
        self.qy_entry.grid(row=1, column=1, padx=2, pady=2)
        ttk.Label(q_frame, text="1/Å").grid(row=1, column=2, sticky="w")
        
        # qz
        ttk.Label(q_frame, text="qz:").grid(row=2, column=0, sticky="w")
        self.qz_entry = ttk.Entry(q_frame, textvariable=self.qz_var, width=10)
        self.qz_entry.grid(row=2, column=1, padx=2, pady=2)
        ttk.Label(q_frame, text="1/Å").grid(row=2, column=2, sticky="w")
        
        # HKL section
        hkl_frame = ttk.LabelFrame(main_frame, text="Relative (r.l.u.)", padding="5")
        hkl_frame.pack(fill=tk.X, pady=5)
        
        # H
        ttk.Label(hkl_frame, text="H:").grid(row=0, column=0, sticky="w")
        self.H_entry = ttk.Entry(hkl_frame, textvariable=self.H_var, width=10)
        self.H_entry.grid(row=0, column=1, padx=2, pady=2)
        
        # K
        ttk.Label(hkl_frame, text="K:").grid(row=0, column=2, sticky="w")
        self.K_entry = ttk.Entry(hkl_frame, textvariable=self.K_var, width=10)
        self.K_entry.grid(row=0, column=3, padx=2, pady=2)
        
        # L
        ttk.Label(hkl_frame, text="L:").grid(row=0, column=4, sticky="w")
        self.L_entry = ttk.Entry(hkl_frame, textvariable=self.L_var, width=10)
        self.L_entry.grid(row=0, column=5, padx=2, pady=2)
        
        # Energy transfer
        energy_frame = ttk.LabelFrame(main_frame, text="Energy Transfer", padding="5")
        energy_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(energy_frame, text="ΔE:").grid(row=0, column=0, sticky="w")
        self.deltaE_entry = ttk.Entry(energy_frame, textvariable=self.deltaE_var, width=10)
        self.deltaE_entry.grid(row=0, column=1, padx=2, pady=2)
        ttk.Label(energy_frame, text="meV").grid(row=0, column=2, sticky="w")
        
        # Initialize mode state
        self._on_mode_change()
    
    def _on_mode_change(self):
        """Handle mode change between Q and HKL modes."""
        if self.sample_frame_mode_var.get():
            # HKL mode - enable HKL, disable Q
            self.H_entry.config(state="normal")
            self.K_entry.config(state="normal")
            self.L_entry.config(state="normal")
            self.qx_entry.config(state="disabled")
            self.qy_entry.config(state="disabled")
            self.qz_entry.config(state="disabled")
        else:
            # Q mode - enable Q, disable HKL
            self.H_entry.config(state="disabled")
            self.K_entry.config(state="disabled")
            self.L_entry.config(state="disabled")
            self.qx_entry.config(state="normal")
            self.qy_entry.config(state="normal")
            self.qz_entry.config(state="normal")
        
        self._trigger_callback("mode_changed", self.sample_frame_mode_var.get())
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the dock."""
        return {
            "qx": self.qx_var.get(),
            "qy": self.qy_var.get(),
            "qz": self.qz_var.get(),
            "H": self.H_var.get(),
            "K": self.K_var.get(),
            "L": self.L_var.get(),
            "deltaE": self.deltaE_var.get(),
            "sample_frame_mode": self.sample_frame_mode_var.get(),
        }
    
    def set_values(self, values: Dict[str, Any]):
        """Set values in the dock from a dictionary."""
        if "qx" in values:
            self.qx_var.set(values["qx"])
        if "qy" in values:
            self.qy_var.set(values["qy"])
        if "qz" in values:
            self.qz_var.set(values["qz"])
        if "H" in values:
            self.H_var.set(str(values["H"]))
        if "K" in values:
            self.K_var.set(str(values["K"]))
        if "L" in values:
            self.L_var.set(str(values["L"]))
        if "deltaE" in values:
            self.deltaE_var.set(str(values["deltaE"]))
        if "sample_frame_mode" in values:
            self.sample_frame_mode_var.set(values["sample_frame_mode"])
            self._on_mode_change()
