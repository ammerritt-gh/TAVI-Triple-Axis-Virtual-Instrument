"""Unified Simulation Dock for TAVI application.

Combines scan parameters, control buttons, diagnostic mode, counts display,
and progress tracking into a single dockable panel.
"""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QComboBox, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QFormLayout, QProgressBar,
                                QWidget, QSizePolicy)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


# Define linked parameter groups - parameters within a group control the same thing
# and should not be scanned together
LINKED_PARAMETER_GROUPS = {
    # Q components - qx, qy, qz are the same as H, K, L (in transformed coordinates)
    # Scanning qx AND H together is a conflict (both set the x-component of Q)
    "q_x_component": {"qx", "h"},
    "q_y_component": {"qy", "k"},
    "q_z_component": {"qz", "l"},
    # Sample 2theta - A2 and 2theta are the same angle
    "sample_2theta": {"a2", "2theta"},
    # Sample theta - omega and A3 are the same angle; psi is the alignment offset
    "sample_theta": {"omega", "a3"},
    # Omega/psi both affect in-plane rotation
    "sample_in_plane_offset": {"omega", "a3", "psi"},
    # Sample orientation - chi/kappa both control out-of-plane tilt
    "sample_out_plane": {"chi", "kappa"},
}

# Define mode conflicts - scanning orientation angles conflicts with momentum/HKL scans
MODE_CONFLICTS = {
    # Orientation angles conflict with momentum/HKL because they change the Q-to-angle mapping
    "orientation_vs_q": ({"omega", "a3", "chi", "psi", "kappa"}, {"qx", "qy", "qz", "h", "k", "l"}),
}

# Known valid scan variables with descriptions
VALID_SCAN_VARIABLES = {
    "qx", "qy", "qz", "deltae", "h", "k", "l",
    "a1", "a2", "a3", "a4", "2theta",
    "omega", "chi", "kappa", "psi",
    "rhm", "rvm", "rha", "rva",
    "vbl_hgap", "pbl_hgap", "pbl_vgap", "dbl_hgap"
}

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
    "chi": "Sample out-of-plane tilt χ (degrees)",
    "psi": "Alignment offset for ω (degrees)",
    "kappa": "Alignment offset for χ (degrees)",
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
        super().__init__("Simulation", parent, use_scroll_area=True)
        self.setObjectName("SimulationDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Scan Parameters Section =====
        params_group = QGroupBox("Scan Parameters")
        params_layout = QGridLayout()
        params_layout.setSpacing(5)
        params_group.setLayout(params_layout)
        
        # Number of neutrons as mantissa × 10^exponent
        params_layout.addWidget(QLabel("# neutrons:"), 0, 0)
        
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
        
        params_layout.addWidget(neutron_input_widget, 0, 1)
        
        # Legacy compatibility: create a hidden edit that mirrors the combined value
        # This allows existing code to use number_neutrons_edit.text() transparently
        self.number_neutrons_edit = QLineEdit()
        self.number_neutrons_edit.hide()  # Hidden, just for compatibility
        self._connect_neutron_sync()
        
        # Time per point estimate (updated dynamically based on neutron count)
        self.time_per_point_label = QLabel("")
        self.time_per_point_label.setStyleSheet("color: #666666; font-size: 10px;")
        params_layout.addWidget(self.time_per_point_label, 0, 2)
        
        main_layout.addWidget(params_group)
        
        # ===== Scan Commands Section =====
        scan_group = QGroupBox("Scan Commands")
        scan_layout = QVBoxLayout()
        scan_group.setLayout(scan_layout)
        
        # Scan Command 1 with Relative button
        scan_layout.addWidget(QLabel("Scan Command 1:"))
        scan_1_row = QHBoxLayout()
        self.scan_command_1_edit = QLineEdit()
        self.scan_command_1_edit.setPlaceholderText("e.g., qx 2 2.2 0.1")
        scan_1_row.addWidget(self.scan_command_1_edit)
        self.relative_1_button = QPushButton("Relative")
        self.relative_1_button.setCheckable(True)
        self.relative_1_button.setMaximumWidth(70)
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
        self.relative_2_button.setMaximumWidth(70)
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
        scan_layout.addWidget(self.point_count_label)
        
        # Total time estimate label
        self.total_time_estimate_label = QLabel("")
        self.total_time_estimate_label.setStyleSheet("color: #666666; font-size: 10px;")
        scan_layout.addWidget(self.total_time_estimate_label)
        
        main_layout.addWidget(scan_group)
        
        # ===== Control Buttons Section =====
        buttons_group = QGroupBox("Control Buttons")
        buttons_layout = QGridLayout()
        buttons_group.setLayout(buttons_layout)
        
        self.run_button = QPushButton("Run Simulation")
        buttons_layout.addWidget(self.run_button, 0, 0)
        
        self.stop_button = QPushButton("Stop Simulation")
        buttons_layout.addWidget(self.stop_button, 0, 1)
        
        self.quit_button = QPushButton("Quit")
        buttons_layout.addWidget(self.quit_button, 1, 0)
        
        self.validation_button = QPushButton("Open Validation GUI")
        buttons_layout.addWidget(self.validation_button, 1, 1)
        
        main_layout.addWidget(buttons_group)
        
        # ===== Parameter Management Section =====
        param_buttons_group = QGroupBox("Parameter Management")
        param_buttons_layout = QGridLayout()
        param_buttons_group.setLayout(param_buttons_layout)
        
        self.save_button = QPushButton("Save Parameters")
        param_buttons_layout.addWidget(self.save_button, 0, 0)
        
        self.load_button = QPushButton("Load Parameters")
        param_buttons_layout.addWidget(self.load_button, 0, 1)
        
        self.defaults_button = QPushButton("Load Defaults")
        param_buttons_layout.addWidget(self.defaults_button, 0, 2)
        
        main_layout.addWidget(param_buttons_group)
        
        # ===== Counts Display Section =====
        counts_group = QGroupBox("Counts")
        counts_layout = QFormLayout()
        counts_group.setLayout(counts_layout)
        
        self.max_counts_label = QLabel("0")
        counts_layout.addRow("Max counts:", self.max_counts_label)
        
        self.total_counts_label = QLabel("0")
        counts_layout.addRow("Total counts:", self.total_counts_label)
        
        main_layout.addWidget(counts_group)
        
        # ===== Diagnostic Mode Section =====
        mode_group = QGroupBox("Diagnostic Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.diagnostic_mode_check = QCheckBox("Enable Diagnostic Mode")
        mode_layout.addWidget(self.diagnostic_mode_check)
        
        self.config_diagnostics_button = QPushButton("Configuration")
        mode_layout.addWidget(self.config_diagnostics_button)
        
        main_layout.addWidget(mode_group)
        
        # ===== Progress Section =====
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_group.setLayout(progress_layout)
        
        # Estimated time before scan starts (from historical data)
        self.pre_scan_estimate_label = QLabel("")
        self.pre_scan_estimate_label.setStyleSheet("color: #0066cc; font-size: 10px;")
        progress_layout.addWidget(self.pre_scan_estimate_label)
        
        # Progress bar and label
        progress_widget = QWidget()
        progress_widget_layout = QHBoxLayout()
        progress_widget_layout.setContentsMargins(0, 0, 0, 0)
        progress_widget.setLayout(progress_widget_layout)
        
        self.progress_bar = QProgressBar()
        progress_widget_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("0% (0/0)")
        progress_widget_layout.addWidget(self.progress_label)
        
        progress_layout.addWidget(progress_widget)
        
        # Remaining time label
        self.remaining_time_label = QLabel("Remaining Time: ")
        progress_layout.addWidget(self.remaining_time_label)

        # Elapsed time label
        self.elapsed_time_label = QLabel("Elapsed Time: ")
        progress_layout.addWidget(self.elapsed_time_label)
        
        main_layout.addWidget(progress_group)
        
        # Add stretch at the end to push everything up
        main_layout.addStretch()
    
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
            ("Sample Orientation", ["omega", "chi", "psi", "kappa"]),
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
