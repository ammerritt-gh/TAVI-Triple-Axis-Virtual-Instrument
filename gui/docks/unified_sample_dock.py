"""Unified Sample Dock for TAVI application.

Combines sample parameters and lattice configuration into a single dockable panel.
"""
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QComboBox, QFrame,
                                QCompleter, QDialog, QTextEdit, QDialogButtonBox)
from PySide6.QtCore import Qt, Signal, QStringListModel

from gui.docks.base_dock import BaseDockWidget
from tavi.space_groups import (SPACE_GROUPS, CRYSTAL_SYSTEMS, EXTINCTION_RULES,
                                get_space_group, get_extinction_rule_text)


class ReflectionRulesDialog(QDialog):
    """Dialog showing reflection rules for the current space group."""
    
    def __init__(self, space_group, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reflection Rules - {space_group.short_name}")
        self.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Space group info
        info_label = QLabel(
            f"<b>Space Group:</b> {space_group.number} - {space_group.short_name}<br>"
            f"<b>Crystal System:</b> {space_group.crystal_system.capitalize()}<br>"
            f"<b>Bravais Lattice:</b> {space_group.centering} ({EXTINCTION_RULES[space_group.centering]['name']})"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Lattice constraints
        constraints = CRYSTAL_SYSTEMS.get(space_group.crystal_system, {}).get("constraints", "")
        if constraints:
            constraint_label = QLabel(f"<b>Lattice Constraints:</b> {constraints}")
            constraint_label.setWordWrap(True)
            layout.addWidget(constraint_label)
        
        # Extinction rules
        layout.addWidget(QLabel("<b>Systematic Absence Rules:</b>"))
        
        centering_name, forbidden, allowed = get_extinction_rule_text(space_group.centering)
        
        rules_text = QTextEdit()
        rules_text.setReadOnly(True)
        rules_text.setHtml(f"""
        <p><b>Allowed reflections (h k l):</b><br>{allowed}</p>
        <p><b>Forbidden reflections:</b><br>{forbidden}</p>
        <p style="color: gray; font-size: 10px;">
        Note: These are centering-based systematic absences. Additional absences 
        may apply due to glide planes and screw axes in the specific space group.
        </p>
        """)
        layout.addWidget(rules_text)
        
        # OK button
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)


class UnifiedSampleDock(BaseDockWidget):
    """Unified dock widget for sample configuration."""
    
    # Signal to request opening the misalignment dock
    open_misalignment_dock_requested = Signal()
    
    # Signal emitted when lattice parameters are saved
    lattice_parameters_changed = Signal()
    
    # Signal emitted when space group changes
    space_group_changed = Signal(int)  # emits space group number
    
    def __init__(self, parent=None):
        super().__init__("Sample", parent, use_scroll_area=True)
        self.setObjectName("SampleDock")
        
        # Track lock state (always start locked)
        self._lattice_locked = True
        self._saved_lattice_values = {}  # Store values when unlocking        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Sample Selection Section =====
        sample_select_group = QGroupBox("Sample Selection")
        sample_select_layout = QVBoxLayout()
        sample_select_layout.setSpacing(5)
        sample_select_group.setLayout(sample_select_layout)
        
        # Sample selection combo box
        sample_combo_layout = QHBoxLayout()
        sample_combo_layout.setContentsMargins(0, 0, 0, 0)
        sample_combo_layout.setSpacing(6)
        sample_combo_layout.addWidget(QLabel("Sample:"))
        self.sample_combo = QComboBox()
        self.sample_map = {
            "None": None,
            "AL: acoustic phonon": "Al_rod_phonon",
            "Al: optic phonon": "Al_rod_phonon_optic",
            "AL: Bragg": "Al_bragg",
        }
        self.sample_combo.addItems(list(self.sample_map.keys()))
        sample_combo_layout.addWidget(self.sample_combo)
        sample_select_layout.addLayout(sample_combo_layout)
        
        # Sample configuration button
        self.config_sample_button = QPushButton("Sample Configuration")
        sample_select_layout.addWidget(self.config_sample_button)
        
        main_layout.addWidget(sample_select_group)
        
        # ===== Space Group Section =====
        spacegroup_group = QGroupBox("Space Group")
        spacegroup_layout = QVBoxLayout()
        spacegroup_layout.setSpacing(5)
        spacegroup_group.setLayout(spacegroup_layout)
        
        # Space group selector with search
        sg_combo_layout = QHBoxLayout()
        sg_combo_layout.setContentsMargins(0, 0, 0, 0)
        self.spacegroup_combo = QComboBox()
        self.spacegroup_combo.setEditable(True)
        self.spacegroup_combo.setInsertPolicy(QComboBox.NoInsert)
        self.spacegroup_combo.lineEdit().setPlaceholderText("Search or select space group...")
        
        # Populate with all space groups
        self._space_group_items = []
        for sg in SPACE_GROUPS:
            display_text = sg.display_name
            self._space_group_items.append(display_text)
            self.spacegroup_combo.addItem(display_text, sg.number)
        
        # Set up completer for searching
        completer = QCompleter(self._space_group_items)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.spacegroup_combo.setCompleter(completer)
        
        sg_combo_layout.addWidget(self.spacegroup_combo)
        spacegroup_layout.addLayout(sg_combo_layout)
        
        # Crystal system info label
        self.crystal_system_label = QLabel("Crystal System: —")
        self.crystal_system_label.setStyleSheet("color: gray; font-size: 10px;")
        spacegroup_layout.addWidget(self.crystal_system_label)
        
        # View reflection rules button
        self.view_rules_button = QPushButton("View Reflection Rules...")
        self.view_rules_button.setEnabled(True)
        spacegroup_layout.addWidget(self.view_rules_button)
        
        main_layout.addWidget(spacegroup_group)
        
        # ===== Lattice Parameters Section =====
        self.lattice_group = QGroupBox("Lattice Parameters")
        lattice_main_layout = QVBoxLayout()
        lattice_main_layout.setSpacing(5)
        self.lattice_group.setLayout(lattice_main_layout)
        
        # Lock/unlock button row
        lock_layout = QHBoxLayout()
        lock_layout.setContentsMargins(0, 0, 0, 0)
        self.lattice_lock_button = QPushButton("🔒 Unlock to Edit")
        self.lattice_lock_button.setToolTip("Click to unlock lattice parameters for editing")
        self.lattice_lock_button.setCheckable(True)
        self.lattice_lock_button.setChecked(False)  # Not unlocked
        lock_layout.addWidget(self.lattice_lock_button)
        lock_layout.addStretch()
        lattice_main_layout.addLayout(lock_layout)
        
        # Lattice parameter grid
        lattice_layout = QGridLayout()
        lattice_layout.setSpacing(5)
        
        # Row 0: a, b, c with individual Å symbols
        lattice_layout.addWidget(QLabel("a:"), 0, 0)
        self.lattice_a_edit = QLineEdit()
        self.lattice_a_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_a_edit, 0, 1)
        lattice_layout.addWidget(QLabel("Å"), 0, 2)
        
        lattice_layout.addWidget(QLabel("b:"), 0, 3)
        self.lattice_b_edit = QLineEdit()
        self.lattice_b_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_b_edit, 0, 4)
        lattice_layout.addWidget(QLabel("Å"), 0, 5)
        
        lattice_layout.addWidget(QLabel("c:"), 0, 6)
        self.lattice_c_edit = QLineEdit()
        self.lattice_c_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_c_edit, 0, 7)
        lattice_layout.addWidget(QLabel("Å"), 0, 8)
        
        # Row 1: alpha, beta, gamma with individual ° symbols
        lattice_layout.addWidget(QLabel("α:"), 1, 0)
        self.lattice_alpha_edit = QLineEdit()
        self.lattice_alpha_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_alpha_edit, 1, 1)
        lattice_layout.addWidget(QLabel("°"), 1, 2)
        
        lattice_layout.addWidget(QLabel("β:"), 1, 3)
        self.lattice_beta_edit = QLineEdit()
        self.lattice_beta_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_beta_edit, 1, 4)
        lattice_layout.addWidget(QLabel("°"), 1, 5)
        
        lattice_layout.addWidget(QLabel("γ:"), 1, 6)
        self.lattice_gamma_edit = QLineEdit()
        self.lattice_gamma_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_gamma_edit, 1, 7)
        lattice_layout.addWidget(QLabel("°"), 1, 8)
        
        lattice_main_layout.addLayout(lattice_layout)
        
        # Validation warning label (hidden when valid)
        self.lattice_warning_label = QLabel("")
        self.lattice_warning_label.setStyleSheet("color: #ff6600; font-size: 10px;")
        self.lattice_warning_label.setWordWrap(True)
        self.lattice_warning_label.setVisible(False)
        lattice_main_layout.addWidget(self.lattice_warning_label)
        
        # Save/Discard buttons (hidden when locked)
        self.lattice_buttons_layout = QHBoxLayout()
        self.lattice_buttons_layout.setContentsMargins(0, 5, 0, 0)
        self.lattice_save_button = QPushButton("✓ Save Changes")
        self.lattice_save_button.setStyleSheet("background-color: #4CAF50; color: white;")
        self.lattice_discard_button = QPushButton("✗ Discard")
        self.lattice_discard_button.setStyleSheet("background-color: #f44336; color: white;")
        self.lattice_buttons_layout.addWidget(self.lattice_save_button)
        self.lattice_buttons_layout.addWidget(self.lattice_discard_button)
        lattice_main_layout.addLayout(self.lattice_buttons_layout)
        
        main_layout.addWidget(self.lattice_group)
        
        # ===== Sample Alignment Offsets Section =====
        orientation_group = QGroupBox("Sample Alignment Offsets")
        orientation_layout = QGridLayout()
        orientation_layout.setSpacing(5)
        orientation_group.setLayout(orientation_layout)
        
        # Row 0: psi (ψ) - offset for omega, kappa (κ) - offset for chi
        orientation_layout.addWidget(QLabel("ψ:"), 0, 0)
        self.psi_edit = QLineEdit()
        self.psi_edit.setMaximumWidth(70)
        self.psi_edit.setToolTip("Alignment offset for ω (omega) - in-plane")
        orientation_layout.addWidget(self.psi_edit, 0, 1)
        orientation_layout.addWidget(QLabel("°"), 0, 2)
        
        orientation_layout.addWidget(QLabel("κ:"), 0, 3)
        self.kappa_edit = QLineEdit()
        self.kappa_edit.setMaximumWidth(70)
        self.kappa_edit.setToolTip("Alignment offset for χ (chi) - out-of-plane")
        orientation_layout.addWidget(self.kappa_edit, 0, 4)
        orientation_layout.addWidget(QLabel("°"), 0, 5)
        
        # Info label
        orientation_info = QLabel("ψ: offset for ω, κ: offset for χ")
        orientation_info.setStyleSheet("color: gray; font-size: 10px;")
        orientation_layout.addWidget(orientation_info, 1, 0, 1, 6)
        
        main_layout.addWidget(orientation_group)
        
        # ===== Separator =====
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)
        
        # ===== Misalignment Training Section =====
        misalignment_group = QGroupBox("Misalignment Training")
        misalignment_layout = QVBoxLayout()
        misalignment_layout.setSpacing(8)
        misalignment_group.setLayout(misalignment_layout)
        
        # Button to open misalignment dock
        self.open_misalignment_button = QPushButton("Open Misalignment Training...")
        self.open_misalignment_button.setMinimumHeight(30)
        misalignment_layout.addWidget(self.open_misalignment_button)
        
        # Status indicator
        self.misalignment_indicator_label = QLabel("⚪ No misalignment loaded")
        self.misalignment_indicator_label.setStyleSheet("color: gray; font-size: 11px;")
        self.misalignment_indicator_label.setAlignment(Qt.AlignCenter)
        misalignment_layout.addWidget(self.misalignment_indicator_label)
        
        main_layout.addWidget(misalignment_group)
        
        # Add stretch at the end
        main_layout.addStretch()
        
        # Connect internal signals
        self.open_misalignment_button.clicked.connect(self._on_open_misalignment_dock)
        self.lattice_lock_button.clicked.connect(self._on_lattice_lock_toggled)
        self.lattice_save_button.clicked.connect(self._on_lattice_save)
        self.lattice_discard_button.clicked.connect(self._on_lattice_discard)
        self.spacegroup_combo.currentIndexChanged.connect(self._on_spacegroup_changed)
        self.view_rules_button.clicked.connect(self._on_view_rules)
        
        # Connect lattice field changes to validation (only when unlocked)
        for field in [self.lattice_a_edit, self.lattice_b_edit, self.lattice_c_edit,
                      self.lattice_alpha_edit, self.lattice_beta_edit, self.lattice_gamma_edit]:
            field.textChanged.connect(self._validate_lattice_for_spacegroup)
        
        # Initialize lock state
        self._apply_lattice_lock_state()
        self._update_spacegroup_info()
    
    def get_selected_sample_key(self):
        """Return the internal sample key for the currently selected sample."""
        label = self.sample_combo.currentText()
        return self.sample_map.get(label, None)
    
    def _on_open_misalignment_dock(self):
        """Handle button click to open misalignment dock."""
        self.open_misalignment_dock_requested.emit()
    
    def update_misalignment_indicator(self, has_misalignment: bool):
        """Update the indicator to show if misalignment is loaded.
        
        Args:
            has_misalignment: True if misalignment is loaded, False otherwise
        """
        if has_misalignment:
            self.misalignment_indicator_label.setText("🟢 Misalignment loaded")
            self.misalignment_indicator_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
        else:
            self.misalignment_indicator_label.setText("⚪ No misalignment loaded")
            self.misalignment_indicator_label.setStyleSheet("color: gray; font-size: 11px;")
    
    # ===== Lattice Lock/Unlock Methods =====
    
    def _get_lattice_fields(self):
        """Return list of all lattice parameter QLineEdit widgets."""
        return [
            self.lattice_a_edit,
            self.lattice_b_edit,
            self.lattice_c_edit,
            self.lattice_alpha_edit,
            self.lattice_beta_edit,
            self.lattice_gamma_edit,
        ]
    
    def _get_current_lattice_values(self) -> dict:
        """Get current lattice values from UI."""
        return {
            'a': self.lattice_a_edit.text(),
            'b': self.lattice_b_edit.text(),
            'c': self.lattice_c_edit.text(),
            'alpha': self.lattice_alpha_edit.text(),
            'beta': self.lattice_beta_edit.text(),
            'gamma': self.lattice_gamma_edit.text(),
        }
    
    def _set_lattice_values(self, values: dict):
        """Set lattice values in UI."""
        self.lattice_a_edit.setText(values.get('a', ''))
        self.lattice_b_edit.setText(values.get('b', ''))
        self.lattice_c_edit.setText(values.get('c', ''))
        self.lattice_alpha_edit.setText(values.get('alpha', ''))
        self.lattice_beta_edit.setText(values.get('beta', ''))
        self.lattice_gamma_edit.setText(values.get('gamma', ''))
    
    def _apply_lattice_lock_state(self):
        """Apply the current lock state to UI elements."""
        locked = self._lattice_locked
        
        # Enable/disable lattice fields
        for field in self._get_lattice_fields():
            field.setReadOnly(locked)
            if locked:
                field.setStyleSheet("background-color: #f0f0f0; color: #666;")
            else:
                field.setStyleSheet("background-color: #ffffcc;")  # Light yellow for editable
        
        # Update lock button text
        if locked:
            self.lattice_lock_button.setText("🔒 Unlock to Edit")
            self.lattice_lock_button.setChecked(False)
        else:
            self.lattice_lock_button.setText("🔓 Editing...")
            self.lattice_lock_button.setChecked(True)
        
        # Show/hide save/discard buttons
        self.lattice_save_button.setVisible(not locked)
        self.lattice_discard_button.setVisible(not locked)
    
    def _on_lattice_lock_toggled(self):
        """Handle lattice lock button toggle."""
        if self._lattice_locked:
            # Unlocking - save current values for potential discard
            self._saved_lattice_values = self._get_current_lattice_values()
            self._lattice_locked = False
        else:
            # Re-locking without explicit save - treat as discard
            self._on_lattice_discard()
            return
        
        self._apply_lattice_lock_state()
    
    def _on_lattice_save(self):
        """Save lattice changes and re-lock."""
        self._lattice_locked = True
        self._apply_lattice_lock_state()
        # Clear saved values
        self._saved_lattice_values = {}
        # Emit signal for controller to update calculations
        self.lattice_parameters_changed.emit()
    
    def _on_lattice_discard(self):
        """Discard lattice changes and re-lock."""
        # Restore saved values
        if self._saved_lattice_values:
            self._set_lattice_values(self._saved_lattice_values)
        self._lattice_locked = True
        self._apply_lattice_lock_state()
        self._saved_lattice_values = {}
    
    def is_lattice_locked(self) -> bool:
        """Return current lattice lock state."""
        return self._lattice_locked
    
    # ===== Space Group Methods =====
    
    def _on_spacegroup_changed(self, index):
        """Handle space group selection change."""
        self._update_spacegroup_info()
        self._validate_lattice_for_spacegroup()
        sg_number = self.spacegroup_combo.currentData()
        if sg_number:
            self.space_group_changed.emit(sg_number)
    
    def _validate_lattice_for_spacegroup(self):
        """Check if current lattice parameters match the space group constraints."""
        sg = self.get_selected_space_group()
        if not sg:
            self.lattice_warning_label.setVisible(False)
            return
        
        warnings = []
        try:
            a = float(self.lattice_a_edit.text() or 0)
            b = float(self.lattice_b_edit.text() or 0)
            c = float(self.lattice_c_edit.text() or 0)
            alpha = float(self.lattice_alpha_edit.text() or 0)
            beta = float(self.lattice_beta_edit.text() or 0)
            gamma = float(self.lattice_gamma_edit.text() or 0)
        except ValueError:
            self.lattice_warning_label.setText("⚠ Invalid numeric values")
            self.lattice_warning_label.setVisible(True)
            return
        
        system = sg.crystal_system
        tol = 0.01  # Tolerance for floating point comparison
        
        if system == "cubic":
            if abs(a - b) > tol or abs(b - c) > tol:
                warnings.append("Cubic requires a = b = c")
            if abs(alpha - 90) > tol or abs(beta - 90) > tol or abs(gamma - 90) > tol:
                warnings.append("Cubic requires α = β = γ = 90°")
        
        elif system == "tetragonal":
            if abs(a - b) > tol:
                warnings.append("Tetragonal requires a = b")
            if abs(alpha - 90) > tol or abs(beta - 90) > tol or abs(gamma - 90) > tol:
                warnings.append("Tetragonal requires α = β = γ = 90°")
        
        elif system == "orthorhombic":
            if abs(alpha - 90) > tol or abs(beta - 90) > tol or abs(gamma - 90) > tol:
                warnings.append("Orthorhombic requires α = β = γ = 90°")
        
        elif system == "hexagonal":
            if abs(a - b) > tol:
                warnings.append("Hexagonal requires a = b")
            if abs(alpha - 90) > tol or abs(beta - 90) > tol:
                warnings.append("Hexagonal requires α = β = 90°")
            if abs(gamma - 120) > tol:
                warnings.append("Hexagonal requires γ = 120°")
        
        elif system == "trigonal":
            # Trigonal can be hexagonal or rhombohedral setting
            if sg.centering == "R":
                # Rhombohedral setting: a = b = c, α = β = γ
                if abs(a - b) > tol or abs(b - c) > tol:
                    warnings.append("Rhombohedral requires a = b = c")
                if abs(alpha - beta) > tol or abs(beta - gamma) > tol:
                    warnings.append("Rhombohedral requires α = β = γ")
            else:
                # Hexagonal setting
                if abs(a - b) > tol:
                    warnings.append("Trigonal (hex) requires a = b")
                if abs(alpha - 90) > tol or abs(beta - 90) > tol:
                    warnings.append("Trigonal (hex) requires α = β = 90°")
                if abs(gamma - 120) > tol:
                    warnings.append("Trigonal (hex) requires γ = 120°")
        
        elif system == "monoclinic":
            if abs(alpha - 90) > tol or abs(gamma - 90) > tol:
                warnings.append("Monoclinic requires α = γ = 90°")
        
        # Triclinic has no constraints
        
        if warnings:
            self.lattice_warning_label.setText("⚠ " + "; ".join(warnings))
            self.lattice_warning_label.setStyleSheet("color: #ff6600; font-size: 10px;")
            self.lattice_warning_label.setVisible(True)
        else:
            self.lattice_warning_label.setVisible(False)
    
    def _update_spacegroup_info(self):
        """Update crystal system label based on current selection."""
        sg_number = self.spacegroup_combo.currentData()
        if sg_number:
            sg = get_space_group(sg_number)
            if sg:
                system = sg.crystal_system.capitalize()
                centering = sg.centering
                constraints = CRYSTAL_SYSTEMS.get(sg.crystal_system, {}).get("constraints", "")
                self.crystal_system_label.setText(
                    f"Crystal System: {system} ({centering}) — {constraints}"
                )
                return
        self.crystal_system_label.setText("Crystal System: —")
    
    def _on_view_rules(self):
        """Show reflection rules dialog."""
        sg_number = self.spacegroup_combo.currentData()
        if sg_number:
            sg = get_space_group(sg_number)
            if sg:
                dialog = ReflectionRulesDialog(sg, self)
                dialog.exec()
    
    def get_selected_space_group(self):
        """Return the currently selected SpaceGroup object, or None."""
        sg_number = self.spacegroup_combo.currentData()
        if sg_number:
            return get_space_group(sg_number)
        return None
    
    def set_space_group(self, number: int):
        """Set the space group by number."""
        index = self.spacegroup_combo.findData(number)
        if index >= 0:
            self.spacegroup_combo.setCurrentIndex(index)
