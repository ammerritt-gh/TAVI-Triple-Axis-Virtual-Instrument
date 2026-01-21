"""Misalignment Training Dock for TAVI application.

Provides teacher/student misalignment generation and alignment checking
in a separate dockable panel.
"""
import base64
import struct
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QMessageBox)
from PySide6.QtCore import Qt, Signal

from gui.docks.base_dock import BaseDockWidget


# Simple XOR key for obfuscation (not secure, but sufficient for educational use)
_OBFUSCATION_KEY = b'TAVI_ALIGN_2026'


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR data with repeating key."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def encode_misalignment(omega: float, chi: float) -> str:
    """Encode misalignment angles into a portable hash string.
    
    Args:
        omega: In-plane misalignment angle (degrees)
        chi: Out-of-plane misalignment angle (degrees)
    """
    packed = struct.pack('<ff', omega, chi)
    obfuscated = _xor_bytes(packed, _OBFUSCATION_KEY)
    encoded = base64.urlsafe_b64encode(obfuscated).decode('ascii')
    return encoded


def decode_misalignment(hash_str: str) -> tuple:
    """Decode a misalignment hash string back to angles.
    
    Returns:
        tuple: (omega, chi) misalignment angles in degrees
    """
    try:
        obfuscated = base64.urlsafe_b64decode(hash_str.encode('ascii'))
        packed = _xor_bytes(obfuscated, _OBFUSCATION_KEY)
        omega, chi = struct.unpack('<ff', packed)
        return omega, chi
    except Exception as e:
        raise ValueError(f"Invalid misalignment hash: {e}")


def check_alignment_quality(user_psi: float, user_kappa: float,
                            mis_omega: float, mis_chi: float,
                            tolerance_good: float = 0.2, tolerance_close: float = 1.0) -> dict:
    """Check how well the user has aligned the sample.
    
    Args:
        user_psi: User's in-plane offset (ψ) to correct omega misalignment
        user_kappa: User's out-of-plane offset (κ) to correct chi misalignment
        mis_omega: Hidden in-plane misalignment angle
        mis_chi: Hidden out-of-plane misalignment angle
        tolerance_good: Tolerance for "aligned" status (degrees)
        tolerance_close: Tolerance for "close" status (degrees)
    """
    # To correct misalignment, user offset should be negative of misalignment
    in_plane_error = abs(user_psi - (-mis_omega))
    out_of_plane_error = abs(user_kappa - (-mis_chi))
    
    def status_for_error(err):
        if err <= tolerance_good:
            return "aligned"
        elif err <= tolerance_close:
            return "close"
        else:
            return "way_off"
    
    in_plane_status = status_for_error(in_plane_error)
    out_of_plane_status = status_for_error(out_of_plane_error)
    
    status_priority = {"aligned": 0, "close": 1, "way_off": 2}
    overall = max([in_plane_status, out_of_plane_status], key=lambda s: status_priority[s])
    
    return {
        "in_plane": in_plane_status,
        "in_plane_hint": _get_hint(in_plane_error, tolerance_good, tolerance_close),
        "out_of_plane": out_of_plane_status,
        "out_of_plane_hint": _get_hint(out_of_plane_error, tolerance_good, tolerance_close),
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


class MisalignmentDock(BaseDockWidget):
    """Dock widget for misalignment training operations."""
    
    # Signal emitted when misalignment is loaded or cleared
    misalignment_changed = Signal(bool)  # True if loaded, False if cleared
    
    def __init__(self, parent=None):
        super().__init__("Misalignment Training", parent, use_scroll_area=True)
        self.setObjectName("MisalignmentDock")
        
        # Store loaded misalignment (hidden from user)
        self._loaded_misalignment = None
        
        # Get the content layout from base class
        main_layout = self.content_layout
        # Prefer a larger default size so contents are visible when opened
        # This gives enough room to display teacher/student/check sections
        try:
            self.setMinimumSize(520, 320)
        except Exception:
            pass
        
        # ===== Misalignment Training: Teacher Section =====
        teacher_group = QGroupBox("Teacher: Generate Misalignment")
        teacher_layout = QGridLayout()
        teacher_layout.setSpacing(5)
        teacher_group.setLayout(teacher_layout)
        
        # Misalignment inputs - omega (in-plane) and chi (out-of-plane)
        teacher_layout.addWidget(QLabel("ω mis:"), 0, 0)
        self.mis_omega_edit = QLineEdit()
        self.mis_omega_edit.setMaximumWidth(60)
        self.mis_omega_edit.setPlaceholderText("0.0")
        self.mis_omega_edit.setToolTip("In-plane misalignment (corrected by ψ)")
        teacher_layout.addWidget(self.mis_omega_edit, 0, 1)
        teacher_layout.addWidget(QLabel("°"), 0, 2)
        
        teacher_layout.addWidget(QLabel("χ mis:"), 0, 3)
        self.mis_chi_edit = QLineEdit()
        self.mis_chi_edit.setMaximumWidth(60)
        self.mis_chi_edit.setPlaceholderText("0.0")
        self.mis_chi_edit.setToolTip("Out-of-plane misalignment (corrected by κ)")
        teacher_layout.addWidget(self.mis_chi_edit, 0, 4)
        teacher_layout.addWidget(QLabel("°"), 0, 5)
        
        # Generate button
        self.generate_hash_button = QPushButton("Generate Hash")
        teacher_layout.addWidget(self.generate_hash_button, 0, 6)
        
        # Generated hash display
        teacher_layout.addWidget(QLabel("Hash:"), 1, 0)
        self.generated_hash_edit = QLineEdit()
        self.generated_hash_edit.setReadOnly(True)
        self.generated_hash_edit.setPlaceholderText("Click 'Generate Hash'")
        teacher_layout.addWidget(self.generated_hash_edit, 1, 1, 1, 5)
        
        # Copy button
        self.copy_hash_button = QPushButton("Copy")
        self.copy_hash_button.setMaximumWidth(50)
        teacher_layout.addWidget(self.copy_hash_button, 1, 6)
        
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
        self.in_plane_feedback_label = QLabel("In-plane (ψ → ω): ---")
        check_layout.addWidget(self.in_plane_feedback_label)
        
        self.out_of_plane_feedback_label = QLabel("Out-of-plane (κ → χ): ---")
        check_layout.addWidget(self.out_of_plane_feedback_label)
        
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
    
    def _on_generate_hash(self):
        """Generate hash from teacher's misalignment inputs."""
        try:
            omega = float(self.mis_omega_edit.text() or 0)
            chi = float(self.mis_chi_edit.text() or 0)
            
            hash_str = encode_misalignment(omega, chi)
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
            omega, chi = decode_misalignment(hash_str)
            self._loaded_misalignment = (omega, chi)
            self.misalignment_status_label.setText("✓ Misalignment loaded (hidden)")
            self.misalignment_status_label.setStyleSheet("color: green; font-weight: bold;")
            self.check_alignment_button.setEnabled(True)
            self._reset_feedback()
            # Emit signal that misalignment was loaded
            self.misalignment_changed.emit(True)
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
        # Emit signal that misalignment was cleared
        self.misalignment_changed.emit(False)
    
    def _reset_feedback(self):
        """Reset alignment feedback labels."""
        self.in_plane_feedback_label.setText("In-plane (ψ → ω): ---")
        self.in_plane_feedback_label.setStyleSheet("")
        self.out_of_plane_feedback_label.setText("Out-of-plane (κ → χ): ---")
        self.out_of_plane_feedback_label.setStyleSheet("")
        self.overall_feedback_label.setText("Overall: ---")
        self.overall_feedback_label.setStyleSheet("font-weight: bold;")
    
    def get_loaded_misalignment(self) -> tuple:
        """Return loaded misalignment angles (omega, chi), or (0, 0) if none loaded."""
        return self._loaded_misalignment if self._loaded_misalignment else (0, 0)
    
    def has_misalignment(self) -> bool:
        """Return True if a misalignment is currently loaded."""
        return self._loaded_misalignment is not None
    
    def update_alignment_feedback(self, user_psi: float, user_kappa: float):
        """Update the alignment feedback display based on current user offsets.
        
        Args:
            user_psi: User's in-plane offset (ψ) to correct omega misalignment
            user_kappa: User's out-of-plane offset (κ) to correct chi misalignment
        """
        if not self._loaded_misalignment:
            return
        
        mis_omega, mis_chi = self._loaded_misalignment
        result = check_alignment_quality(user_psi, user_kappa, mis_omega, mis_chi)
        
        # Update in-plane feedback (psi corrects omega misalignment)
        in_plane_status = result["in_plane"]
        in_plane_hint = result["in_plane_hint"]
        self.in_plane_feedback_label.setText(f"In-plane (ψ → ω): {in_plane_hint}")
        self.in_plane_feedback_label.setStyleSheet(self._status_style(in_plane_status))
        
        # Update out-of-plane feedback (kappa corrects chi misalignment)
        out_of_plane_status = result["out_of_plane"]
        out_of_plane_hint = result["out_of_plane_hint"]
        self.out_of_plane_feedback_label.setText(f"Out-of-plane (κ → χ): {out_of_plane_hint}")
        self.out_of_plane_feedback_label.setStyleSheet(self._status_style(out_of_plane_status))
        
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
