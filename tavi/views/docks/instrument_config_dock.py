"""
Instrument Configuration Dock - Controls for instrument settings.

Includes:
- Instrument angles (mtt, stt, psi, att)
- Ki/Ei and Kf/Ef values
- Monochromator and analyzer crystal selections
- Collimations and slit sizes
- Focusing parameters
- Experimental modules (NMO, velocity selector)
"""
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Callable

from .base_dock import BaseDock


class InstrumentConfigDock(BaseDock):
    """Dock for instrument configuration controls."""
    
    def __init__(self, parent: tk.Widget, **kwargs):
        # Create tk variables before calling super().__init__
        # which will call _create_widgets
        self.mtt_var = tk.StringVar()
        self.stt_var = tk.DoubleVar()
        self.psi_var = tk.DoubleVar()
        self.att_var = tk.StringVar()
        self.Ki_var = tk.StringVar()
        self.Ei_var = tk.StringVar()
        self.Kf_var = tk.StringVar()
        self.Ef_var = tk.StringVar()
        self.monocris_var = tk.StringVar()
        self.anacris_var = tk.StringVar()
        self.alpha_1_var = tk.DoubleVar()
        self.alpha_2_30_var = tk.BooleanVar()
        self.alpha_2_40_var = tk.BooleanVar()
        self.alpha_2_60_var = tk.BooleanVar()
        self.alpha_3_var = tk.DoubleVar()
        self.alpha_4_var = tk.DoubleVar()
        self.rhmfac_var = tk.DoubleVar()
        self.rvmfac_var = tk.DoubleVar()
        self.rhafac_var = tk.DoubleVar()
        self.NMO_installed_var = tk.StringVar()
        self.V_selector_installed_var = tk.BooleanVar()
        
        super().__init__(parent, **kwargs)
    
    def _create_widgets(self):
        """Create instrument configuration widgets."""
        # Main container
        main_frame = ttk.Frame(self.frame)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Section: Angles
        angles_frame = ttk.LabelFrame(main_frame, text="Instrument Angles", padding="5")
        angles_frame.pack(fill=tk.X, pady=5)
        
        # Mono 2-theta
        ttk.Label(angles_frame, text="Mono 2θ:").grid(row=0, column=0, sticky="w")
        self.mtt_entry = ttk.Entry(angles_frame, textvariable=self.mtt_var, width=8)
        self.mtt_entry.grid(row=0, column=1, padx=2, pady=2)
        
        # Sample 2-theta
        ttk.Label(angles_frame, text="Sample 2θ:").grid(row=0, column=2, sticky="w")
        self.stt_entry = ttk.Entry(angles_frame, textvariable=self.stt_var, width=8)
        self.stt_entry.grid(row=0, column=3, padx=2, pady=2)
        
        # Sample psi
        ttk.Label(angles_frame, text="Sample Ψ:").grid(row=0, column=4, sticky="w")
        self.psi_entry = ttk.Entry(angles_frame, textvariable=self.psi_var, width=8)
        self.psi_entry.grid(row=0, column=5, padx=2, pady=2)
        
        # Analyzer 2-theta
        ttk.Label(angles_frame, text="Ana 2θ:").grid(row=0, column=6, sticky="w")
        self.att_entry = ttk.Entry(angles_frame, textvariable=self.att_var, width=8)
        self.att_entry.grid(row=0, column=7, padx=2, pady=2)
        
        # Section: Energies
        energy_frame = ttk.LabelFrame(main_frame, text="Wavevector & Energy", padding="5")
        energy_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(energy_frame, text="Ki (1/Å):").grid(row=0, column=0, sticky="w")
        self.Ki_entry = ttk.Entry(energy_frame, textvariable=self.Ki_var, width=8)
        self.Ki_entry.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(energy_frame, text="Ei (meV):").grid(row=0, column=2, sticky="w")
        self.Ei_entry = ttk.Entry(energy_frame, textvariable=self.Ei_var, width=8)
        self.Ei_entry.grid(row=0, column=3, padx=2, pady=2)
        
        ttk.Label(energy_frame, text="Kf (1/Å):").grid(row=0, column=4, sticky="w")
        self.Kf_entry = ttk.Entry(energy_frame, textvariable=self.Kf_var, width=8)
        self.Kf_entry.grid(row=0, column=5, padx=2, pady=2)
        
        ttk.Label(energy_frame, text="Ef (meV):").grid(row=0, column=6, sticky="w")
        self.Ef_entry = ttk.Entry(energy_frame, textvariable=self.Ef_var, width=8)
        self.Ef_entry.grid(row=0, column=7, padx=2, pady=2)
        
        # Section: Crystals
        crystals_frame = ttk.LabelFrame(main_frame, text="Crystals", padding="5")
        crystals_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(crystals_frame, text="Monochromator:").grid(row=0, column=0, sticky="w")
        self.monocris_combo = ttk.Combobox(crystals_frame, textvariable=self.monocris_var,
                                            values=["PG[002]", "PG[002] test"], width=15)
        self.monocris_combo.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(crystals_frame, text="Analyzer:").grid(row=0, column=2, sticky="w")
        self.anacris_combo = ttk.Combobox(crystals_frame, textvariable=self.anacris_var,
                                           values=["PG[002]"], width=15)
        self.anacris_combo.grid(row=0, column=3, padx=2, pady=2)
        
        # Section: Collimation
        collim_frame = ttk.LabelFrame(main_frame, text="Collimation (arcmin)", padding="5")
        collim_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(collim_frame, text="α1:").grid(row=0, column=0, sticky="w")
        self.alpha_1_combo = ttk.Combobox(collim_frame, textvariable=self.alpha_1_var,
                                           values=[0, 20, 40, 60], width=6)
        self.alpha_1_combo.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(collim_frame, text="α2:").grid(row=0, column=2, sticky="w")
        alpha2_frame = ttk.Frame(collim_frame)
        alpha2_frame.grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(alpha2_frame, text="30'", variable=self.alpha_2_30_var).pack(side=tk.LEFT)
        ttk.Checkbutton(alpha2_frame, text="40'", variable=self.alpha_2_40_var).pack(side=tk.LEFT)
        ttk.Checkbutton(alpha2_frame, text="60'", variable=self.alpha_2_60_var).pack(side=tk.LEFT)
        
        ttk.Label(collim_frame, text="α3:").grid(row=1, column=0, sticky="w")
        self.alpha_3_combo = ttk.Combobox(collim_frame, textvariable=self.alpha_3_var,
                                           values=[0, 10, 20, 30, 45, 60], width=6)
        self.alpha_3_combo.grid(row=1, column=1, padx=2, pady=2)
        
        ttk.Label(collim_frame, text="α4:").grid(row=1, column=2, sticky="w")
        self.alpha_4_combo = ttk.Combobox(collim_frame, textvariable=self.alpha_4_var,
                                           values=[0, 10, 20, 30, 45, 60], width=6)
        self.alpha_4_combo.grid(row=1, column=3, padx=2, pady=2)
        
        # Section: Focusing
        focus_frame = ttk.LabelFrame(main_frame, text="Focusing", padding="5")
        focus_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(focus_frame, text="rhm factor:").grid(row=0, column=0, sticky="w")
        ttk.Entry(focus_frame, textvariable=self.rhmfac_var, width=8).grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Label(focus_frame, text="rvm factor:").grid(row=0, column=2, sticky="w")
        ttk.Entry(focus_frame, textvariable=self.rvmfac_var, width=8).grid(row=0, column=3, padx=2, pady=2)
        
        ttk.Label(focus_frame, text="rha factor:").grid(row=0, column=4, sticky="w")
        ttk.Entry(focus_frame, textvariable=self.rhafac_var, width=8).grid(row=0, column=5, padx=2, pady=2)
        
        # Section: Experimental Modules
        modules_frame = ttk.LabelFrame(main_frame, text="Experimental Modules", padding="5")
        modules_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(modules_frame, text="NMO:").grid(row=0, column=0, sticky="w")
        self.NMO_combo = ttk.Combobox(modules_frame, textvariable=self.NMO_installed_var,
                                       values=["None", "Vertical", "Horizontal", "Both"], width=12)
        self.NMO_combo.grid(row=0, column=1, padx=2, pady=2)
        
        ttk.Checkbutton(modules_frame, text="Velocity Selector", 
                        variable=self.V_selector_installed_var).grid(row=0, column=2, padx=10, sticky="w")
        ttk.Label(modules_frame, text="(Ki fixed mode)").grid(row=0, column=3, sticky="w")
    
    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the dock."""
        return {
            "mtt": self.mtt_var.get(),
            "stt": self.stt_var.get(),
            "psi": self.psi_var.get(),
            "att": self.att_var.get(),
            "Ki": self.Ki_var.get(),
            "Ei": self.Ei_var.get(),
            "Kf": self.Kf_var.get(),
            "Ef": self.Ef_var.get(),
            "monocris": self.monocris_var.get(),
            "anacris": self.anacris_var.get(),
            "alpha_1": self.alpha_1_var.get(),
            "alpha_2_30": self.alpha_2_30_var.get(),
            "alpha_2_40": self.alpha_2_40_var.get(),
            "alpha_2_60": self.alpha_2_60_var.get(),
            "alpha_3": self.alpha_3_var.get(),
            "alpha_4": self.alpha_4_var.get(),
            "rhmfac": self.rhmfac_var.get(),
            "rvmfac": self.rvmfac_var.get(),
            "rhafac": self.rhafac_var.get(),
            "NMO_installed": self.NMO_installed_var.get(),
            "V_selector_installed": self.V_selector_installed_var.get(),
        }
    
    def set_values(self, values: Dict[str, Any]):
        """Set values in the dock from a dictionary."""
        if "mtt" in values:
            self.mtt_var.set(str(values["mtt"]))
        if "stt" in values:
            self.stt_var.set(values["stt"])
        if "psi" in values:
            self.psi_var.set(values["psi"])
        if "att" in values:
            self.att_var.set(str(values["att"]))
        if "Ki" in values:
            self.Ki_var.set(str(values["Ki"]))
        if "Ei" in values:
            self.Ei_var.set(str(values["Ei"]))
        if "Kf" in values:
            self.Kf_var.set(str(values["Kf"]))
        if "Ef" in values:
            self.Ef_var.set(str(values["Ef"]))
        if "monocris" in values:
            self.monocris_var.set(values["monocris"])
        if "anacris" in values:
            self.anacris_var.set(values["anacris"])
        if "alpha_1" in values:
            self.alpha_1_var.set(values["alpha_1"])
        if "alpha_2_30" in values:
            self.alpha_2_30_var.set(values["alpha_2_30"])
        if "alpha_2_40" in values:
            self.alpha_2_40_var.set(values["alpha_2_40"])
        if "alpha_2_60" in values:
            self.alpha_2_60_var.set(values["alpha_2_60"])
        if "alpha_3" in values:
            self.alpha_3_var.set(values["alpha_3"])
        if "alpha_4" in values:
            self.alpha_4_var.set(values["alpha_4"])
        if "rhmfac" in values:
            self.rhmfac_var.set(values["rhmfac"])
        if "rvmfac" in values:
            self.rvmfac_var.set(values["rvmfac"])
        if "rhafac" in values:
            self.rhafac_var.set(values["rhafac"])
        if "NMO_installed" in values:
            self.NMO_installed_var.set(values["NMO_installed"])
        if "V_selector_installed" in values:
            self.V_selector_installed_var.set(values["V_selector_installed"])
