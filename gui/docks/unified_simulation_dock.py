"""Unified Simulation Dock for TAVI application.

Run/Stop with progress and counts first, then the scan commands (neutron
count on their first row), then diagnostic mode.
"""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QComboBox, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QProgressBar,
                                QWidget, QSizePolicy)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget, pack_grid


# Define linked parameter groups - parameters within a group control the same thing
# and should not be scanned together
LINKED_PARAMETER_GROUPS = {
    # Sample 2theta - A2 and 2theta are the same angle
    "sample_2theta": {"a2", "2theta"},
    # Sample theta - A3 is the calculated angle; omega/psi are in-plane offsets
    "sample_theta": {"omega", "a3"},
    # A3, omega, and psi all affect in-plane sample rotation
    "sample_in_plane_offset": {"omega", "a3", "psi"},
    # The lower arc sgl and its correction kappa move the same axis
    "sample_out_plane": {"sgl", "kappa"},
}

# Define mode conflicts - scanning orientation angles conflicts with momentum/HKL scans
# (an arc with a Q/HKL variable is refused outright; see TAVIController._is_arc_in_q_mode)
MODE_CONFLICTS = {
    # Orientation angles conflict with momentum/HKL because they change the Q-to-angle mapping
    "orientation_vs_q": ({"omega", "a3", "psi", "kappa"}, {"qx", "qy", "qz", "h", "k", "l"}),
}

# Known valid scan variables with descriptions
VALID_SCAN_VARIABLES = {
    "qx", "qy", "qz", "deltae", "h", "k", "l",
    "a1", "a2", "a3", "a4", "2theta",
    "omega", "sgl", "sgu", "kappa", "psi",
    "rhm", "rvm", "rha", "rva",
    "vbl_hgap", "pbl_hgap", "pbl_vgap", "dbl_hgap"
}

# The refusal for a scan over the retired chi (the old beam-fixed tilt under
# the turntable), shared by the GUI and the API.
SCAN_CHI_REFUSAL = ("'chi' is no longer a scan variable: scan the arcs 'sgl' (lower) "
                    "or 'sgu' (upper) in angle mode, or 'kappa', the lower-arc correction")

# Descriptions for each scan variable (for help dialog)
SCAN_VARIABLE_DESCRIPTIONS = {
    "h": "H index in reciprocal lattice units (r.l.u.)",
    "k": "K index in reciprocal lattice units (r.l.u.)",
    "l": "L index in reciprocal lattice units (r.l.u.)",
    "qx": "Momentum transfer x-component (Å⁻¹)",
    "qy": "Momentum transfer y-component (Å⁻¹)",
    "qz": "Momentum transfer z-component (Å⁻¹)",
    "deltae": "Energy transfer ΔE (meV)",
    "a1": "Monochromator 2θ angle (degrees)",
    "a2": "Sample 2θ scattering angle (degrees)",
    "2theta": "Sample 2θ scattering angle (degrees) - alias for A2",
    "a3": "Sample θ rotation angle (degrees) - same as ω (omega)",
    "a4": "Analyzer 2θ angle (degrees)",
    "omega": "Sample θ rotation angle (degrees) - alias for A3",
    "sgl": "Lower goniometer arc (degrees) - angle-mode scans only; Q/HKL scans solve it",
    "sgu": "Upper goniometer arc (degrees) - angle-mode scans only; Q/HKL scans solve it",
    "psi": "Correction of the turntable A3 (degrees)",
    "kappa": "Correction of the lower arc sgl (degrees)",
    "rhm": "Monochromator horizontal bending radius (m)",
    "rvm": "Monochromator vertical bending radius (m)",
    "rha": "Analyzer horizontal bending radius (m)",
    "rva": "Analyzer vertical bending radius (m)",
    "vbl_hgap": "Post-mono slit width (m) - between monochromator and sample",
    "pbl_hgap": "Pre-sample slit width (m) - horizontal aperture before sample",
    "pbl_vgap": "Pre-sample slit height (m) - vertical aperture before sample",
    "dbl_hgap": "Detector slit width (m) - before detector",
}


class UnifiedSimulationDock(BaseDockWidget):
    """Unified dock widget for simulation control and parameters."""
    
    # Style for warning state (light red background)
    STYLE_WARNING = "background-color: #ffcccc; border: 1px solid #cc0000;"
    STYLE_NORMAL = ""
    
    def __init__(self, parent=None):
        super().__init__("Simulation", parent, use_scroll_area=True, blocks=True)
        self.setObjectName("SimulationDock")
        
        
        # ===== Run and Progress: the control block, first so it is in view =====
        control_group = QGroupBox("Run and Progress")
        control_layout = QVBoxLayout()
        control_group.setLayout(control_layout)

        buttons_row = QHBoxLayout()
        self.run_button = QPushButton("Run Simulation")
        self.run_button.setDefault(True)  # the one primary action in this dock
        buttons_row.addWidget(self.run_button)
        self.stop_button = QPushButton("Stop Simulation")
        buttons_row.addWidget(self.stop_button)
        control_layout.addLayout(buttons_row)

        # Estimated time before scan starts (from historical data)
        self.pre_scan_estimate_label = QLabel("")
        self.pre_scan_estimate_label.setStyleSheet("color: #0066cc; font-size: 10px;")
        control_layout.addWidget(self.pre_scan_estimate_label)

        # Progress bar and label
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        progress_row.addWidget(self.progress_bar)
        self.progress_label = QLabel("0% (0/0)")
        progress_row.addWidget(self.progress_label)
        control_layout.addLayout(progress_row)

        # Remaining and elapsed time
        time_row = QHBoxLayout()
        self.remaining_time_label = QLabel("Remaining Time: ")
        time_row.addWidget(self.remaining_time_label)
        time_row.addSpacing(12)
        self.elapsed_time_label = QLabel("Elapsed Time: ")
        time_row.addWidget(self.elapsed_time_label)
        time_row.addStretch()
        control_layout.addLayout(time_row)

        # Counts, both on one row
        counts_row = QHBoxLayout()
        counts_row.addWidget(QLabel("Max counts:"))
        self.max_counts_label = QLabel("0")
        counts_row.addWidget(self.max_counts_label)
        counts_row.addSpacing(12)
        counts_row.addWidget(QLabel("Total counts:"))
        self.total_counts_label = QLabel("0")
        counts_row.addWidget(self.total_counts_label)
        counts_row.addStretch()
        control_layout.addLayout(counts_row)

        self.add_block(control_group)

        # ===== Scan Commands Section =====
        scan_group = QGroupBox("Scan Commands")
        scan_layout = QVBoxLayout()
        scan_group.setLayout(scan_layout)

        # First row: number of neutrons as mantissa × 10^exponent, with the
        # time-per-point estimate beside it
        neutrons_layout = QGridLayout()
        neutrons_layout.setSpacing(5)
        neutrons_layout.addWidget(QLabel("# neutrons:"), 0, 0)

        # Container for mantissa × 10^exponent layout
        neutron_input_widget = QWidget()
        neutron_layout = QHBoxLayout()
        neutron_layout.setContentsMargins(0, 0, 0, 0)
        neutron_layout.setSpacing(2)
        neutron_layout.setAlignment(Qt.AlignLeft)
        neutron_input_widget.setLayout(neutron_layout)
        neutron_input_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

        self.neutron_mantissa_edit = QLineEdit()
        self.neutron_mantissa_edit.setMaximumWidth(50)
        self.neutron_mantissa_edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.neutron_mantissa_edit.setPlaceholderText("1.0")
        self.neutron_mantissa_edit.setToolTip("Mantissa (e.g., 1.0, 5.0, 50)")
        neutron_layout.addWidget(self.neutron_mantissa_edit)

        label_exp = QLabel("×10^")
        label_exp.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        neutron_layout.addWidget(label_exp)

        self.neutron_exponent_edit = QLineEdit()
        self.neutron_exponent_edit.setMaximumWidth(35)
        self.neutron_exponent_edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.neutron_exponent_edit.setPlaceholderText("6")
        self.neutron_exponent_edit.setToolTip("Exponent (e.g., 6 for 10^6 = 1,000,000)")
        neutron_layout.addWidget(self.neutron_exponent_edit)

        neutrons_layout.addWidget(neutron_input_widget, 0, 1)

        # Legacy compatibility: create a hidden edit that mirrors the combined value
        # This allows existing code to use number_neutrons_edit.text() transparently
        self.number_neutrons_edit = QLineEdit()
        self.number_neutrons_edit.hide()  # Hidden, just for compatibility
        self._connect_neutron_sync()

        # Time per point estimate (updated dynamically based on neutron count)
        self.time_per_point_label = QLabel("")
        self.time_per_point_label.setStyleSheet("color: #666666; font-size: 10px;")
        neutrons_layout.addWidget(self.time_per_point_label, 0, 2)

        pack_grid(neutrons_layout)
        scan_layout.addLayout(neutrons_layout)
        
        # Scan Command 1 with Relative button
        scan_layout.addWidget(QLabel("Scan Command 1:"))
        scan_1_row = QHBoxLayout()
        self.scan_command_1_edit = QLineEdit()
        self.scan_command_1_edit.setPlaceholderText("e.g., qx 2 2.2 0.1")
        scan_1_row.addWidget(self.scan_command_1_edit)
        self.relative_1_button = QPushButton("Relative")
        self.relative_1_button.setCheckable(True)
        self.relative_1_button.setToolTip("Scan values are offsets from current value")
        self.relative_1_button.setStyleSheet("")
        scan_1_row.addWidget(self.relative_1_button)
        scan_layout.addLayout(scan_1_row)
        
        # Warning label for command 1
        self.scan_warning_1_label = QLabel("")
        self.scan_warning_1_label.setStyleSheet("color: #cc0000; font-size: 10px;")
        self.scan_warning_1_label.setWordWrap(True)
        self.scan_warning_1_label.hide()
        scan_layout.addWidget(self.scan_warning_1_label)
        
        # Scan Command 2 with Relative button
        scan_layout.addWidget(QLabel("Scan Command 2:"))
        scan_2_row = QHBoxLayout()
        self.scan_command_2_edit = QLineEdit()
        self.scan_command_2_edit.setPlaceholderText("e.g., deltaE 3 7 0.25")
        scan_2_row.addWidget(self.scan_command_2_edit)
        self.relative_2_button = QPushButton("Relative")
        self.relative_2_button.setCheckable(True)
        self.relative_2_button.setToolTip("Scan values are offsets from current value")
        self.relative_2_button.setStyleSheet("")
        scan_2_row.addWidget(self.relative_2_button)
        scan_layout.addLayout(scan_2_row)
        
        # Warning label for command 2
        self.scan_warning_2_label = QLabel("")
        self.scan_warning_2_label.setStyleSheet("color: #cc0000; font-size: 10px;")
        self.scan_warning_2_label.setWordWrap(True)
        self.scan_warning_2_label.hide()
        scan_layout.addWidget(self.scan_warning_2_label)
        
        # Conflict warning label (for conflicts between the two commands)
        self.scan_conflict_label = QLabel("")
        self.scan_conflict_label.setStyleSheet("color: #cc0000; font-weight: bold; font-size: 10px;")
        self.scan_conflict_label.setWordWrap(True)
        self.scan_conflict_label.hide()
        scan_layout.addWidget(self.scan_conflict_label)
        
        # Help button row
        scan_options_layout = QHBoxLayout()
        self.show_commands_button = QPushButton("Valid Commands...")
        self.show_commands_button.setMaximumWidth(120)
        self.show_commands_button.setToolTip("Show list of valid scan variables")
        self.show_commands_button.clicked.connect(self._show_valid_commands)
        scan_options_layout.addWidget(self.show_commands_button)
        scan_options_layout.addStretch()
        scan_layout.addLayout(scan_options_layout)
        
        # Point count breakdown label (shows "N × M = Z (valid/invalid)")
        self.point_count_label = QLabel("1 point")
        self.point_count_label.setStyleSheet("font-weight: bold;")
        self.point_count_label.setWordWrap(True)  # a 2D breakdown can pass a block's width
        scan_layout.addWidget(self.point_count_label)

        # Total time estimate label
        self.total_time_estimate_label = QLabel("")
        self.total_time_estimate_label.setStyleSheet("color: #666666; font-size: 10px;")
        self.total_time_estimate_label.setWordWrap(True)
        scan_layout.addWidget(self.total_time_estimate_label)

        # Execution engine selector (docs/CONTROL_FEATURES_DESIGN.md §6.4).
        # McStas = full Monte-Carlo (default); Deterministic = fast analytic
        # S(Q,w) x resolution + seeded Poisson. Read in the controller's
        # _collect_simulation_launch_state as launch_state['engine'].
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        # userData carries the API engine id; the label is human-facing.
        self.engine_combo.addItem("McStas (Monte Carlo)", "mcstas")
        self.engine_combo.addItem("Deterministic (analytic)", "deterministic")
        self.engine_combo.setToolTip(
            "McStas: full Monte-Carlo simulation.\n"
            "Deterministic: fast analytic S(Q,ω) ⊗ resolution with seeded "
            "Poisson counts (validator; see the API guide)."
        )
        engine_row.addWidget(self.engine_combo)
        engine_row.addStretch()
        scan_layout.addLayout(engine_row)

        # Background is configured globally, on the row under the engine
        # selector (one row would not fit a block).  The checkbox is the
        # immediate master gate; individual source switches and scales live
        # in a staged modal dialog opened by the button.
        background_row = QHBoxLayout()
        background_row.addWidget(QLabel("Background:"))
        self.background_enable_check = QCheckBox()
        self.background_enable_check.setToolTip(
            "Plant the configured background sources into generated scans.\n"
            "Off: scans contain signal only (identical counts to a "
            "background-free engine)."
        )
        background_row.addWidget(self.background_enable_check)
        self.background_config_button = QPushButton("Background configuration…")
        self.background_config_button.setToolTip(
            "Choose and scale the available background sources."
        )
        background_row.addWidget(self.background_config_button)
        background_row.addStretch()
        scan_layout.addLayout(background_row)

        self.add_block(scan_group)
        
        # ===== Diagnostic Mode Section: one row =====
        mode_group = QGroupBox("Diagnostic Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)

        self.diagnostic_mode_check = QCheckBox("Enable Diagnostic Mode")
        mode_layout.addWidget(self.diagnostic_mode_check)

        self.config_diagnostics_button = QPushButton("Configuration")
        mode_layout.addWidget(self.config_diagnostics_button)
        mode_layout.addStretch()

        self.add_block(mode_group)
        
    
    def set_scan_command_warning(self, command_num: int, message: str):
        """Set or clear a warning for a scan command.
        
        Args:
            command_num: 1 or 2 for which command
            message: Warning message, or empty string to clear
        """
        if command_num == 1:
            edit = self.scan_command_1_edit
            label = self.scan_warning_1_label
        else:
            edit = self.scan_command_2_edit
            label = self.scan_warning_2_label
        
        if message:
            edit.setStyleSheet(self.STYLE_WARNING)
            label.setText(message)
            label.show()
        else:
            edit.setStyleSheet(self.STYLE_NORMAL)
            label.setText("")
            label.hide()
    
    def set_scan_conflict_warning(self, message: str):
        """Set or clear the conflict warning between commands.
        
        Args:
            message: Conflict message, or empty string to clear
        """
        if message:
            self.scan_conflict_label.setText(message)
            self.scan_conflict_label.show()
        else:
            self.scan_conflict_label.setText("")
            self.scan_conflict_label.hide()
    
    def clear_all_scan_warnings(self):
        """Clear all scan-related warnings."""
        self.set_scan_command_warning(1, "")
        self.set_scan_command_warning(2, "")
        self.set_scan_conflict_warning("")
    
    def _show_valid_commands(self):
        """Show a dialog with valid scan commands and their descriptions."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Valid Scan Commands")
        dialog.setMinimumSize(450, 400)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        
        # Build help text
        help_text = """<h3>Scan Command Format</h3>
<p><b>variable start end step</b></p>
<p>Example: <code>qx 2 2.2 0.1</code> scans qx from 2 to 2.2 in steps of 0.1</p>

<h3>Relative Mode</h3>
<p>When "Relative to current" is checked, start and end are offsets from the current value.</p>
<p>Example: <code>omega -5 5 0.5</code> with relative mode scans ±5° around current omega.</p>

<h3>Valid Scan Variables</h3>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Variable</th><th>Description</th></tr>
"""
        # Sort variables by category
        categories = [
            ("Reciprocal Space", ["h", "k", "l", "qx", "qy", "qz", "deltae"]),
            ("Instrument Angles", ["a1", "a2", "2theta", "a3", "a4"]),
            ("Sample Orientation", ["omega", "sgl", "sgu", "psi", "kappa"]),
            ("Crystal Focusing", ["rhm", "rvm", "rha", "rva"]),
            ("Slit Apertures", ["vbl_hgap", "pbl_hgap", "pbl_vgap", "dbl_hgap"]),
        ]
        
        for category, vars in categories:
            help_text += f'<tr><td colspan="2"><b>{category}</b></td></tr>\n'
            for var in vars:
                desc = SCAN_VARIABLE_DESCRIPTIONS.get(var, "")
                help_text += f'<tr><td><code>{var}</code></td><td>{desc}</td></tr>\n'
        
        help_text += "</table>"
        
        text_edit.setHtml(help_text)
        layout.addWidget(text_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)
        
        dialog.exec()

    def update_time_per_point(self, time_str: str):
        """Update the time per point estimate display.
        
        Args:
            time_str: Formatted time string (e.g., "~5s/point") or empty to hide
        """
        if time_str:
            self.time_per_point_label.setText(time_str)
            self.time_per_point_label.show()
        else:
            self.time_per_point_label.setText("")
            self.time_per_point_label.hide()
    
    def update_point_count_display(self, count1: int, count2: int, valid: int, invalid: int, 
                                    all_invalid: bool = False):
        """Update the point count breakdown display.
        
        Args:
            count1: Number of points in scan command 1 (0 if no scan)
            count2: Number of points in scan command 2 (0 if no 2D scan)
            valid: Number of valid scan points
            invalid: Number of invalid scan points
            all_invalid: If True, highlight in red to warn user
        """
        total = valid + invalid
        
        if count1 == 0 and count2 == 0:
            # Single point mode (no scan commands)
            if all_invalid:
                self.point_count_label.setText("1 point (invalid)")
                self.point_count_label.setStyleSheet(
                    "font-weight: bold; color: #cc0000; background-color: #ffcccc; padding: 2px;"
                )
            else:
                self.point_count_label.setText("1 point")
                self.point_count_label.setStyleSheet("font-weight: bold;")
        elif count2 == 0:
            # 1D scan
            text = f"{total} points ({valid} valid / {invalid} invalid)"
            if all_invalid:
                self.point_count_label.setStyleSheet(
                    "font-weight: bold; color: #cc0000; background-color: #ffcccc; padding: 2px;"
                )
            elif invalid > 0:
                self.point_count_label.setStyleSheet("font-weight: bold; color: #cc6600;")
            else:
                self.point_count_label.setStyleSheet("font-weight: bold; color: #006600;")
            self.point_count_label.setText(text)
        else:
            # 2D scan
            text = f"{count1} × {count2} = {total} points ({valid} valid / {invalid} invalid)"
            if all_invalid:
                self.point_count_label.setStyleSheet(
                    "font-weight: bold; color: #cc0000; background-color: #ffcccc; padding: 2px;"
                )
            elif invalid > 0:
                self.point_count_label.setStyleSheet("font-weight: bold; color: #cc6600;")
            else:
                self.point_count_label.setStyleSheet("font-weight: bold; color: #006600;")
            self.point_count_label.setText(text)
    
    def update_total_time_estimate(self, total_time_str: str, compile_time_str: str = ""):
        """Update the total time estimate display.
        
        Args:
            total_time_str: Formatted total time string or empty to hide
            compile_time_str: Formatted compile time string (optional)
        """
        if total_time_str:
            if compile_time_str:
                text = f"Est. total time: {total_time_str} (Compile: {compile_time_str})"
            else:
                text = f"Est. total time: {total_time_str}"
            self.total_time_estimate_label.setText(text)
            self.total_time_estimate_label.show()
        else:
            self.total_time_estimate_label.setText("No timing data")
            self.total_time_estimate_label.show()
    
    def update_pre_scan_estimate(self, estimate_str: str):
        """Update the pre-scan estimate in the progress section.
        
        Args:
            estimate_str: Formatted estimate string or empty to hide
        """
        if estimate_str:
            self.pre_scan_estimate_label.setText(f"Estimated: {estimate_str}")
            self.pre_scan_estimate_label.show()
        else:
            self.pre_scan_estimate_label.setText("")
            self.pre_scan_estimate_label.hide()

    def update_elapsed_time(self, elapsed_str: str):
        """Update the elapsed time display in the progress section.

        Args:
            elapsed_str: Formatted elapsed time string or empty to hide
        """
        if elapsed_str:
            self.elapsed_time_label.setText(f"Elapsed Time: {elapsed_str}")
            self.elapsed_time_label.show()
        else:
            self.elapsed_time_label.setText("")
            self.elapsed_time_label.hide()
    
    def update_point_count_display_deferred(self, count1: int, count2: int):
        """Update the point count display when precalculation is deferred (>1000 points).
        
        Args:
            count1: Number of points in scan command 1
            count2: Number of points in scan command 2 (0 if no 2D scan)
        """
        total = count1 * count2 if count2 > 0 else count1
        
        if count2 == 0:
            text = f"{total} points (validation deferred - too many points)"
        else:
            text = f"{count1} × {count2} = {total} points (validation deferred)"
        
        self.point_count_label.setText(text)
        self.point_count_label.setStyleSheet("font-weight: bold; color: #cc6600;")

    def _connect_neutron_sync(self):
        """Connect mantissa and exponent changes to sync the hidden combined value."""
        self.neutron_mantissa_edit.textChanged.connect(self._sync_neutron_value)
        self.neutron_exponent_edit.textChanged.connect(self._sync_neutron_value)
    
    def _sync_neutron_value(self):
        """Sync the hidden number_neutrons_edit with the combined mantissa × 10^exponent value."""
        combined = self.get_number_neutrons()
        self.number_neutrons_edit.blockSignals(True)
        self.number_neutrons_edit.setText(str(combined))
        self.number_neutrons_edit.blockSignals(False)
        # Emit textChanged manually so connected slots are notified
        self.number_neutrons_edit.textChanged.emit(str(combined))
    
    def get_selected_engine(self) -> str:
        """Return the selected execution engine id ('mcstas' | 'deterministic').

        Reads the engine selector's userData; falls back to 'mcstas' (the
        default) if the widget is unavailable. Consumed by the controller's
        _collect_simulation_launch_state.
        """
        try:
            data = self.engine_combo.currentData()
            return data if data in ("mcstas", "deterministic") else "mcstas"
        except Exception:
            return "mcstas"

    def set_background_display(self, enabled, summary: str):
        """Sync the master gate and configuration tooltip without signalling."""
        self.background_enable_check.blockSignals(True)
        try:
            self.background_enable_check.setChecked(bool(enabled))
        finally:
            self.background_enable_check.blockSignals(False)
        detail = summary or "No background sources are active."
        self.background_config_button.setToolTip(
            "Choose and scale the available background sources.\n\n" + detail
        )

    def get_number_neutrons(self) -> int:
        """Get the combined number of neutrons from mantissa × 10^exponent.
        
        Returns:
            The integer number of neutrons. Handles flexible inputs like:
            - 50 × 10^0 = 50
            - 5.0 × 10^1 = 50
            - 1.0 × 10^6 = 1000000
        """
        try:
            mantissa_text = self.neutron_mantissa_edit.text().strip()
            exponent_text = self.neutron_exponent_edit.text().strip()
            
            # Default values if empty
            mantissa = float(mantissa_text) if mantissa_text else 1.0
            exponent = int(float(exponent_text)) if exponent_text else 6
            
            return int(mantissa * (10 ** exponent))
        except (ValueError, OverflowError):
            return 1000000  # Default fallback
    
    def set_number_neutrons(self, value):
        """Set the neutron count by decomposing into mantissa × 10^exponent.
        
        Args:
            value: Number of neutrons (int or float, or string like "1e8" or "1000000")
        """
        try:
            # Convert to float first to handle scientific notation strings
            num = float(value)
            if num <= 0:
                num = 1000000
            
            # Find the exponent (order of magnitude)
            import math
            if num >= 1:
                exponent = int(math.floor(math.log10(num)))
            else:
                exponent = 0
            
            # Calculate mantissa
            mantissa = num / (10 ** exponent) if exponent > 0 else num
            
            # Format nicely - if mantissa is close to integer, show as integer
            if abs(mantissa - round(mantissa)) < 0.001:
                mantissa_str = str(int(round(mantissa)))
            else:
                mantissa_str = f"{mantissa:.2f}".rstrip('0').rstrip('.')
            
            # Block signals during update to avoid recursive calls
            self.neutron_mantissa_edit.blockSignals(True)
            self.neutron_exponent_edit.blockSignals(True)
            
            self.neutron_mantissa_edit.setText(mantissa_str)
            self.neutron_exponent_edit.setText(str(exponent))
            
            self.neutron_mantissa_edit.blockSignals(False)
            self.neutron_exponent_edit.blockSignals(False)
            
            # Sync the hidden combined field
            self._sync_neutron_value()
            
        except (ValueError, TypeError):
            # Default to 1 × 10^6 if parsing fails
            self.neutron_mantissa_edit.setText("1")
            self.neutron_exponent_edit.setText("6")
            self._sync_neutron_value()
