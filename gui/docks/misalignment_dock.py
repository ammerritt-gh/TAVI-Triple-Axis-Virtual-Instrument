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


class MisalignmentDock(BaseDockWidget):
    """Dock widget for misalignment training operations."""
    
    # Signal emitted when misalignment is loaded or cleared
    misalignment_changed = Signal(bool)  # True if loaded, False if cleared
    
    def __init__(self, parent=None):
        super().__init__("Misalignment Training", parent, use_scroll_area=True)
        self.setObjectName("MisalignmentDock")

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
        
        teacher_layout.addWidget(QLabel("sgl mis:"), 0, 3)
        self.mis_chi_edit = QLineEdit()
        self.mis_chi_edit.setMaximumWidth(60)
        self.mis_chi_edit.setPlaceholderText("0.0")
        self.mis_chi_edit.setToolTip("Out-of-plane misalignment of the lower arc sgl (corrected by κ)")
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
        self.miss_feedback_label = QLabel("Worst miss: ---")
        self.miss_feedback_label.setWordWrap(True)
        check_layout.addWidget(self.miss_feedback_label)

        self.overall_feedback_label = QLabel("Overall: ---")
        self.overall_feedback_label.setStyleSheet("font-weight: bold;")
        check_layout.addWidget(self.overall_feedback_label)
        
        main_layout.addWidget(check_group)
        
        # Add stretch at the end
        main_layout.addStretch()
        
        # Connect internal signals
        self.generate_hash_button.clicked.connect(self._on_generate_hash)
        self.copy_hash_button.clicked.connect(self._on_copy_hash)
        # Load / Clear are the controller's (it holds the one loaded exercise
        # and refuses while the other exercise is loaded); this dock shows it.

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
    
    def show_misalignment(self, hash_str: str):
        """Show the controller's misalignment exercise: its hash, or "" for
        none. The values stay hidden (the controller holds them)."""
        loaded = bool(hash_str)
        self.load_hash_edit.setText(hash_str)
        if loaded:
            self.misalignment_status_label.setText("✓ Misalignment loaded (hidden)")
            self.misalignment_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.misalignment_status_label.setText("No misalignment loaded")
            self.misalignment_status_label.setStyleSheet("color: gray;")
        self.check_alignment_button.setEnabled(loaded)
        self._reset_feedback()
        self.misalignment_changed.emit(loaded)
    
    def _reset_feedback(self):
        """Reset alignment feedback labels."""
        self.miss_feedback_label.setText("Worst miss: ---")
        self.miss_feedback_label.setStyleSheet("")
        self.overall_feedback_label.setText("Overall: ---")
        self.overall_feedback_label.setStyleSheet("font-weight: bold;")

    def update_alignment_feedback(self, grade: dict):
        """Show a grade from ``tavi.ub_matrix.grade_alignment`` (the one
        grader both docks use): the worst miss and its HKL, and the status."""
        overall = grade["status"]
        self.miss_feedback_label.setText(grade["summary"])
        self.miss_feedback_label.setStyleSheet(self._status_style(overall))
        overall_text = {"aligned": "✓ Well Aligned!", "close": "◐ Getting Close",
                        "way_off": "✗ Keep Trying", "cannot_assess": "Cannot assess"}
        self.overall_feedback_label.setText(f"Overall: {overall_text[overall]}")
        self.overall_feedback_label.setStyleSheet(f"font-weight: bold; {self._status_style(overall)}")
    
    def _status_style(self, status: str) -> str:
        """Return CSS style for alignment status."""
        if status == "aligned":
            return "color: green;"
        elif status == "close":
            return "color: orange;"
        elif status == "way_off":
            return "color: red;"
        return "color: gray;"
