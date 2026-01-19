"""Unified Sample Dock for TAVI application.

Combines sample parameters, lattice configuration, and misalignment training
into a single dockable panel.
"""
import base64
import struct
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QCheckBox, QComboBox, QFrame,
                                QMessageBox)
from PySide6.QtCore import Qt

from gui.docks.base_dock import BaseDockWidget


# Simple XOR key for obfuscation (not secure, but sufficient for educational use)
_OBFUSCATION_KEY = b'TAVI_ALIGN_2026'


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with repeating key."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def encode_misalignment(omega: float, chi: float, psi: float) -> str:
    """Encode misalignment angles into a portable hash string."""
    packed = struct.pack('<fff', omega, chi, psi)
    obfuscated = _xor_bytes(packed, _OBFUSCATION_KEY)
    encoded = base64.urlsafe_b64encode(obfuscated).decode('ascii')
    return encoded


def decode_misalignment(hash_str: str) -> tuple:
    """Decode a misalignment hash string back to angles."""
    try:
        obfuscated = base64.urlsafe_b64decode(hash_str.encode('ascii'))
        packed = _xor_bytes(obfuscated, _OBFUSCATION_KEY)
        omega, chi, psi = struct.unpack('<fff', packed)
        return omega, chi, psi
    except Exception as e:
        raise ValueError(f"Invalid misalignment hash: {e}")


def check_alignment_quality(user_omega: float, user_chi: float, user_psi: float,
                            mis_omega: float, mis_chi: float, mis_psi: float,
                            tolerance_good: float = 0.2, tolerance_close: float = 1.0) -> dict:
    """Check how well the user has aligned the sample."""
    y_axis_error = abs(user_omega + user_psi - (-mis_omega - mis_psi))
    x_axis_error = abs(user_chi - (-mis_chi))
    
    def status_for_error(err):
        if err <= tolerance_good:
            return "aligned"
        elif err <= tolerance_close:
            return "close"
        else:
            return "way_off"
    
    omega_psi_status = status_for_error(y_axis_error)
    chi_status = status_for_error(x_axis_error)
    
    status_priority = {"aligned": 0, "close": 1, "way_off": 2}
    overall = max([omega_psi_status, chi_status], key=lambda s: status_priority[s])
    
    return {
        "y_axis": omega_psi_status,
        "y_axis_hint": _get_hint(y_axis_error, tolerance_good, tolerance_close),
        "x_axis": chi_status,
        "x_axis_hint": _get_hint(x_axis_error, tolerance_good, tolerance_close),
        "overall": overall
    }


def _get_hint(error: float, tol_good: float, tol_close: float) -> str:
    """Generate a hint based on error magnitude."""
    if error <= tol_good:
        return "Well aligned!"
    elif error <= tol_close:
        return f"Close (~{error:.1f}° off)"
    elif error <= 5.0:
        return f"Getting there (~{error:.1f}° off)"
    else:
        return f"Way off (>{error:.0f}°)"


class UnifiedSampleDock(BaseDockWidget):
    """Unified dock widget for sample configuration and misalignment training."""
    
    def __init__(self, parent=None):
        super().__init__("Sample", parent, use_scroll_area=True)
        self.setObjectName("SampleDock")
        
        # Store loaded misalignment (hidden from user)
        self._loaded_misalignment = None
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # ===== Sample Selection Section =====
        sample_select_group = QGroupBox("Sample Selection")
        sample_select_layout = QVBoxLayout()
        sample_select_layout.setSpacing(5)
        sample_select_group.setLayout(sample_select_layout)
        
        # Sample frame mode checkbox
        self.sample_frame_mode_check = QCheckBox("Sample frame mode")
        sample_select_layout.addWidget(self.sample_frame_mode_check)
        
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
        
        # ===== Lattice Parameters Section =====
        lattice_group = QGroupBox("Lattice Parameters")
        lattice_layout = QGridLayout()
        lattice_layout.setSpacing(5)
        lattice_group.setLayout(lattice_layout)
        
        # Row 0: a, b, c
        lattice_layout.addWidget(QLabel("a:"), 0, 0)
        self.lattice_a_edit = QLineEdit()
        self.lattice_a_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_a_edit, 0, 1)
        
        lattice_layout.addWidget(QLabel("b:"), 0, 2)
        self.lattice_b_edit = QLineEdit()
        self.lattice_b_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_b_edit, 0, 3)
        
        lattice_layout.addWidget(QLabel("c:"), 0, 4)
        self.lattice_c_edit = QLineEdit()
        self.lattice_c_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_c_edit, 0, 5)
        
        lattice_layout.addWidget(QLabel("(Å)"), 0, 6)
        
        # Row 1: alpha, beta, gamma
        lattice_layout.addWidget(QLabel("α:"), 1, 0)
        self.lattice_alpha_edit = QLineEdit()
        self.lattice_alpha_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_alpha_edit, 1, 1)
        
        lattice_layout.addWidget(QLabel("β:"), 1, 2)
        self.lattice_beta_edit = QLineEdit()
        self.lattice_beta_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_beta_edit, 1, 3)
        
        lattice_layout.addWidget(QLabel("γ:"), 1, 4)
        self.lattice_gamma_edit = QLineEdit()
        self.lattice_gamma_edit.setMaximumWidth(60)
        lattice_layout.addWidget(self.lattice_gamma_edit, 1, 5)
        
        lattice_layout.addWidget(QLabel("(deg)"), 1, 6)
        
        main_layout.addWidget(lattice_group)
        
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
        
        # ===== Misalignment Training: Teacher Section =====
        teacher_group = QGroupBox("Teacher: Generate Misalignment")
        teacher_layout = QGridLayout()
        teacher_layout.setSpacing(5)
        teacher_group.setLayout(teacher_layout)
        
        # Misalignment inputs
        teacher_layout.addWidget(QLabel("ω mis:"), 0, 0)
        self.mis_omega_edit = QLineEdit()
        self.mis_omega_edit.setMaximumWidth(60)
        self.mis_omega_edit.setPlaceholderText("0.0")
        teacher_layout.addWidget(self.mis_omega_edit, 0, 1)
        teacher_layout.addWidget(QLabel("°"), 0, 2)
        
        teacher_layout.addWidget(QLabel("χ mis:"), 0, 3)
        self.mis_chi_edit = QLineEdit()
        self.mis_chi_edit.setMaximumWidth(60)
        self.mis_chi_edit.setPlaceholderText("0.0")
        teacher_layout.addWidget(self.mis_chi_edit, 0, 4)
        teacher_layout.addWidget(QLabel("°"), 0, 5)
        
        teacher_layout.addWidget(QLabel("ψ mis:"), 1, 0)
        self.mis_psi_edit = QLineEdit()
        self.mis_psi_edit.setMaximumWidth(60)
        self.mis_psi_edit.setPlaceholderText("0.0")
        teacher_layout.addWidget(self.mis_psi_edit, 1, 1)
        teacher_layout.addWidget(QLabel("°"), 1, 2)
        
        # Generate button
        self.generate_hash_button = QPushButton("Generate Hash")
        teacher_layout.addWidget(self.generate_hash_button, 1, 3, 1, 3)
        
        # Generated hash display
        teacher_layout.addWidget(QLabel("Hash:"), 2, 0)
        self.generated_hash_edit = QLineEdit()
        self.generated_hash_edit.setReadOnly(True)
        self.generated_hash_edit.setPlaceholderText("Click 'Generate Hash'")
        teacher_layout.addWidget(self.generated_hash_edit, 2, 1, 1, 5)
        
        # Copy button
        self.copy_hash_button = QPushButton("Copy")
        self.copy_hash_button.setMaximumWidth(50)
        teacher_layout.addWidget(self.copy_hash_button, 2, 6)
        
        main_layout.addWidget(teacher_group)
        
        # ===== Misalignment Training: Student Section =====
        student_group = QGroupBox("Student: Load Misalignment")
        student_layout = QVBoxLayout()
        student_group.setLayout(student_layout)
        
        # Hash input
        hash_input_layout = QHBoxLayout()
        hash_input_layout.addWidget(QLabel("Hash:"))
        self.load_hash_edit = QLineEdit()
        self.load_hash_edit.setPlaceholderText("Paste misalignment hash here")
        hash_input_layout.addWidget(self.load_hash_edit)
        student_layout.addLayout(hash_input_layout)
        
        # Load and Clear buttons
        load_buttons_layout = QHBoxLayout()
        self.load_hash_button = QPushButton("Load Misalignment")
        load_buttons_layout.addWidget(self.load_hash_button)
        self.clear_misalignment_button = QPushButton("Clear Misalignment")
        load_buttons_layout.addWidget(self.clear_misalignment_button)
        student_layout.addLayout(load_buttons_layout)
        
        # Status indicator
        self.misalignment_status_label = QLabel("No misalignment loaded")
        self.misalignment_status_label.setStyleSheet("color: gray;")
        student_layout.addWidget(self.misalignment_status_label)
        
        main_layout.addWidget(student_group)
        
        # ===== Check Alignment Section =====
        check_group = QGroupBox("Check Alignment")
        check_layout = QVBoxLayout()
        check_group.setLayout(check_layout)
        
        self.check_alignment_button = QPushButton("Check My Alignment")
        self.check_alignment_button.setEnabled(False)
        check_layout.addWidget(self.check_alignment_button)
        
        # Alignment feedback labels
        self.y_axis_feedback_label = QLabel("Y-axis (ω): ---")
        check_layout.addWidget(self.y_axis_feedback_label)
        
        self.x_axis_feedback_label = QLabel("X-axis (χ): ---")
        check_layout.addWidget(self.x_axis_feedback_label)
        
        self.overall_feedback_label = QLabel("Overall: ---")
        self.overall_feedback_label.setStyleSheet("font-weight: bold;")
        check_layout.addWidget(self.overall_feedback_label)
        
        main_layout.addWidget(check_group)
        
        # Add stretch at the end
        main_layout.addStretch()
        
        # Connect internal signals
        self.generate_hash_button.clicked.connect(self._on_generate_hash)
        self.copy_hash_button.clicked.connect(self._on_copy_hash)
        self.load_hash_button.clicked.connect(self._on_load_hash)
        self.clear_misalignment_button.clicked.connect(self._on_clear_misalignment)
    
    def get_selected_sample_key(self):
        """Return the internal sample key for the currently selected sample."""
        label = self.sample_combo.currentText()
        return self.sample_map.get(label, None)
    
    def _on_generate_hash(self):
        """Generate hash from teacher's misalignment inputs."""
        try:
            omega = float(self.mis_omega_edit.text() or 0)
            chi = float(self.mis_chi_edit.text() or 0)
            psi = float(self.mis_psi_edit.text() or 0)
            
            hash_str = encode_misalignment(omega, chi, psi)
            self.generated_hash_edit.setText(hash_str)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", 
                              "Please enter valid numbers for misalignment angles.")
    
    def _on_copy_hash(self):
        """Copy generated hash to clipboard."""
        from PySide6.QtWidgets import QApplication
        hash_text = self.generated_hash_edit.text()
        if hash_text:
            QApplication.clipboard().setText(hash_text)
    
    def _on_load_hash(self):
        """Load misalignment from hash (without revealing values)."""
        hash_str = self.load_hash_edit.text().strip()
        if not hash_str:
            QMessageBox.warning(self, "No Hash", "Please enter a misalignment hash.")
            return
        
        try:
            omega, chi, psi = decode_misalignment(hash_str)
            self._loaded_misalignment = (omega, chi, psi)
            self.misalignment_status_label.setText("✓ Misalignment loaded (hidden)")
            self.misalignment_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.check_alignment_button.setEnabled(True)
            self._reset_feedback()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Hash", str(e))
    
    def _on_clear_misalignment(self):
        """Clear loaded misalignment."""
        self._loaded_misalignment = None
        # Clear any pasted hash so it isn't saved back to parameters
        try:
            self.load_hash_edit.clear()
        except Exception:
            pass
        self.misalignment_status_label.setText("No misalignment loaded")
        self.misalignment_status_label.setStyleSheet("color: gray;")
        self.check_alignment_button.setEnabled(False)
        self._reset_feedback()
    
    def _reset_feedback(self):
        """Reset alignment feedback labels."""
        self.y_axis_feedback_label.setText("Y-axis (ω): ---")
        self.y_axis_feedback_label.setStyleSheet("")
        self.x_axis_feedback_label.setText("X-axis (χ): ---")
        self.x_axis_feedback_label.setStyleSheet("")
        self.overall_feedback_label.setText("Overall: ---")
        self.overall_feedback_label.setStyleSheet("font-weight: bold;")
    
    def get_loaded_misalignment(self) -> tuple:
        """Return loaded misalignment angles, or (0,0,0) if none loaded."""
        return self._loaded_misalignment if self._loaded_misalignment else (0, 0, 0)
    
    def has_misalignment(self) -> bool:
        """Return True if a misalignment is currently loaded."""
        return self._loaded_misalignment is not None
    
    def update_alignment_feedback(self, user_omega: float, user_chi: float, user_psi: float):
        """Update the alignment feedback display based on current user angles."""
        if not self._loaded_misalignment:
            return
        
        mis_omega, mis_chi, mis_psi = self._loaded_misalignment
        result = check_alignment_quality(user_omega, user_chi, user_psi,
                                         mis_omega, mis_chi, mis_psi)
        
        # Update Y-axis feedback
        y_status = result["y_axis"]
        y_hint = result["y_axis_hint"]
        self.y_axis_feedback_label.setText(f"Y-axis (ω/ψ): {y_hint}")
        self.y_axis_feedback_label.setStyleSheet(self._status_style(y_status))
        
        # Update X-axis feedback
        x_status = result["x_axis"]
        x_hint = result["x_axis_hint"]
        self.x_axis_feedback_label.setText(f"X-axis (χ): {x_hint}")
        self.x_axis_feedback_label.setStyleSheet(self._status_style(x_status))
        
        # Update overall feedback
        overall = result["overall"]
        overall_text = {"aligned": "✓ Well Aligned!", "close": "◐ Getting Close", "way_off": "✗ Keep Trying"}
        self.overall_feedback_label.setText(f"Overall: {overall_text[overall]}")
        self.overall_feedback_label.setStyleSheet(f"font-weight: bold; {self._status_style(overall)}")
    
    def _status_style(self, status: str) -> str:
        """Return CSS style for alignment status."""
        if status == "aligned":
            return "color: green;"
        elif status == "close":
            return "color: orange;"
        else:
            return "color: red;"
