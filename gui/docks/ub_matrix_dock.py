"""UB Matrix Dock for TAVI application.

Provides UB matrix display, Bragg peak entry, UB calculation, lattice refinement,
and integrated alignment training in a dockable panel.
"""
import numpy as np
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout,
                                QLabel, QLineEdit, QGroupBox, QPushButton,
                                QGridLayout, QMessageBox, QCheckBox,
                                QScrollArea, QWidget, QDialog,
                                QDialogButtonBox, QSpinBox, QDoubleSpinBox,
                                QFrame, QTextEdit)
from PySide6.QtCore import Qt, Signal

from gui.docks.base_dock import BaseDockWidget
from instruments.descriptor import tas_goniometer
from tavi.orientation import legacy_triple, stage_record


class LatticeRefinementDialog(QDialog):
    """Dialog showing lattice refinement results with option to apply."""

    def __init__(self, current_lattice, refined_lattice, residuals, rms_error, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lattice Refinement Results")
        self.setMinimumSize(450, 350)
        self.accepted_lattice = None

        layout = QVBoxLayout(self)

        # Comparison table
        layout.addWidget(QLabel("<b>Lattice Parameter Comparison:</b>"))

        labels = ['a', 'b', 'c', '\u03b1', '\u03b2', '\u03b3']
        units = ['\u00c5', '\u00c5', '\u00c5', '\u00b0', '\u00b0', '\u00b0']

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Param</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Current</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Refined</b>"), 0, 2)
        grid.addWidget(QLabel("<b>Diff</b>"), 0, 3)

        for i, (name, unit) in enumerate(zip(labels, units)):
            grid.addWidget(QLabel(f"{name} ({unit}):"), i + 1, 0)
            grid.addWidget(QLabel(f"{current_lattice[i]:.4f}"), i + 1, 1)
            grid.addWidget(QLabel(f"{refined_lattice[i]:.4f}"), i + 1, 2)
            diff = refined_lattice[i] - current_lattice[i]
            diff_label = QLabel(f"{diff:+.4f}")
            if abs(diff) > 0.01:
                diff_label.setStyleSheet("color: red;")
            grid.addWidget(diff_label, i + 1, 3)

        layout.addLayout(grid)

        # RMS error
        layout.addWidget(QLabel(f"\n<b>RMS |Q| error:</b> {rms_error:.6f} \u00c5\u207b\u00b9"))

        # Per-peak residuals
        if residuals:
            layout.addWidget(QLabel("\n<b>Per-Peak Residuals:</b>"))
            res_text = QTextEdit()
            res_text.setReadOnly(True)
            res_text.setMaximumHeight(120)
            lines = []
            for r in residuals:
                h, k, l = r['hkl']
                lines.append(
                    f"({h:.0f} {k:.0f} {l:.0f}): "
                    f"|Q|_obs={r['q_obs']:.4f}, |Q|_calc={r['q_calc']:.4f}, "
                    f"\u0394Q={r['delta_q']:+.4f}"
                )
            res_text.setPlainText("\n".join(lines))
            layout.addWidget(res_text)

        # Buttons
        button_layout = QHBoxLayout()
        apply_button = QPushButton("Apply Refined Lattice")
        apply_button.setStyleSheet("background-color: #4CAF50; color: white;")
        apply_button.clicked.connect(lambda: self._accept_refinement(refined_lattice))
        button_layout.addWidget(apply_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

    def _accept_refinement(self, lattice):
        self.accepted_lattice = lattice
        self.accept()


class PeakEntryWidget(QFrame):
    """Widget for a single observed Bragg peak entry.

    The angle columns follow the goniometer description: one readout per
    stage axis, then the sample two-theta. A peak taken with Take Position
    carries a stage record (``tavi.orientation.stage_record``: readouts,
    corrections in force, ki, kf, sense). A peak without one (a save from
    before the goniometer, a TAS_MCP peak) keeps the legacy (omega, chi, 2theta)
    triple and its meaning, and is marked "legacy" -- derived from the missing
    record, never stored.
    """

    # Signals
    take_position_requested = Signal(int)  # peak index
    remove_requested = Signal(int)  # peak index
    peak_data_changed = Signal(int)  # peak index

    def __init__(self, index: int, gonio, parent=None):
        super().__init__(parent)
        self.index = index
        self._locked = False
        self._gonio = tuple(gonio)
        self._stage = None      # the stage record, or None when legacy
        self._legacy = False
        self._sense = None      # sense_sample as loaded (legacy peaks)

        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(3)

        # Header row: Peak label + legacy mark + lock + remove
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4)
        self.peak_label = QLabel(f"<b>Peak {index + 1}</b>")
        header_layout.addWidget(self.peak_label)
        self.legacy_label = QLabel("legacy")
        self.legacy_label.setStyleSheet("color: #8a6d00; font-style: italic;")
        self.legacy_label.setToolTip(
            "Recorded before the sample goniometer: its angles are the old "
            "(ω, χ, 2θ) triple and are read with that meaning. "
            "Take Position again to record it on the stage."
        )
        self.legacy_label.setVisible(False)
        header_layout.addWidget(self.legacy_label)
        header_layout.addStretch()

        self.valid_indicator = QLabel("⚠")  # warning by default
        self.valid_indicator.setToolTip("Peak incomplete")
        header_layout.addWidget(self.valid_indicator)

        self.lock_check = QCheckBox("Lock")
        self.lock_check.toggled.connect(self._on_lock_toggled)
        header_layout.addWidget(self.lock_check)

        self.remove_button = QPushButton("✗")
        self.remove_button.setMaximumWidth(25)
        self.remove_button.setToolTip("Remove this peak")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.index))
        header_layout.addWidget(self.remove_button)

        main_layout.addLayout(header_layout)

        # Fields grid: aligns HKL, angles, and ki/kf in consistent columns
        fields_grid = QGridLayout()
        fields_grid.setSpacing(4)
        fields_grid.setColumnStretch(1, 1)
        fields_grid.setColumnStretch(3, 1)
        fields_grid.setColumnStretch(5, 1)

        # Row 0: HKL
        fields_grid.addWidget(QLabel("H:"), 0, 0)
        self.h_edit = QLineEdit("0")
        fields_grid.addWidget(self.h_edit, 0, 1)
        fields_grid.addWidget(QLabel("K:"), 0, 2)
        self.k_edit = QLineEdit("0")
        fields_grid.addWidget(self.k_edit, 0, 3)
        fields_grid.addWidget(QLabel("L:"), 0, 4)
        self.l_edit = QLineEdit("0")
        fields_grid.addWidget(self.l_edit, 0, 5)

        # Row 1: one readout per goniometer axis (at most three: the
        # validator's ceiling), labelled by the description.
        self.axis_labels = []
        self.axis_edits = []
        for column, ax in enumerate(self._gonio):
            label = QLabel(f"{ax.name}:")
            edit = QLineEdit("0")
            edit.setToolTip(f"Stage readout {ax.name} when the peak was taken")
            fields_grid.addWidget(label, 1, 2 * column)
            fields_grid.addWidget(edit, 1, 2 * column + 1)
            self.axis_labels.append(label)
            self.axis_edits.append(edit)

        # Row 2: 2theta, ki, kf
        fields_grid.addWidget(QLabel("2θ:"), 2, 0)
        self.stt_edit = QLineEdit("0")
        self.stt_edit.setToolTip("Sample two-theta")
        fields_grid.addWidget(self.stt_edit, 2, 1)
        fields_grid.addWidget(QLabel("ki:"), 2, 2)
        self.ki_edit = QLineEdit("0")
        fields_grid.addWidget(self.ki_edit, 2, 3)
        fields_grid.addWidget(QLabel("kf:"), 2, 4)
        self.kf_edit = QLineEdit("0")
        fields_grid.addWidget(self.kf_edit, 2, 5)

        # Row 3: Take Position
        self.take_position_button = QPushButton("\U0001f4cd Take Position")
        self.take_position_button.setToolTip(
            "Record the current stage readouts, the corrections in force, ki, kf "
            "and the scattering sense"
        )
        self.take_position_button.clicked.connect(lambda: self.take_position_requested.emit(self.index))
        fields_grid.addWidget(self.take_position_button, 3, 4, 1, 2)

        main_layout.addLayout(fields_grid)

        # Connect field changes to validation
        for field in self._fields():
            field.textChanged.connect(lambda _: self.peak_data_changed.emit(self.index))
        self.peak_data_changed.connect(lambda _: self._validate_self())

    def _fields(self):
        return [self.h_edit, self.k_edit, self.l_edit, *self.axis_edits,
                self.stt_edit, self.ki_edit, self.kf_edit]

    @staticmethod
    def _fmt(value):
        return f"{value:.4f}".rstrip('0').rstrip('.')

    @property
    def is_legacy(self) -> bool:
        return self._legacy

    def _set_legacy(self, legacy: bool):
        """Show the legacy triple (omega, chi in the first two columns) or the
        stage readouts."""
        self._legacy = legacy
        self.legacy_label.setVisible(legacy)
        names = ("ω", "χ")
        for column, (label, edit) in enumerate(zip(self.axis_labels, self.axis_edits)):
            if legacy:
                label.setText(f"{names[column]}:" if column < 2 else "")
                edit.setVisible(column < 2)
            else:
                label.setText(f"{self._gonio[column].name}:")
                edit.setVisible(True)

    def _on_lock_toggled(self, locked):
        self._locked = locked
        for field in self._fields():
            field.setReadOnly(locked)
            if locked:
                field.setStyleSheet("background-color: #f0f0f0; color: #666;")
            else:
                field.setStyleSheet("")
        self.take_position_button.setEnabled(not locked)
        self.remove_button.setEnabled(not locked)

    def _validate_self(self):
        """Validate own fields and update the validity indicator."""
        data = self.get_peak_data()
        if data is None:
            self.update_valid_indicator(False)
            return
        h, k, l = data['hkl']
        ki, kf = data['ki'], data['kf']
        self.update_valid_indicator(
            not (h == 0 and k == 0 and l == 0) and ki > 0 and kf > 0
        )

    def get_peak_data(self) -> dict:
        """Return peak data from UI fields (``ObservedPeak.to_dict`` shape).

        A stage peak's record takes the readouts from the axis fields; a peak
        typed in by hand gets a record without corrections, read in the frame
        of the moment. A legacy peak keeps its triple and no record.
        """
        try:
            values = [float(edit.text() or 0) for edit in self.axis_edits]
            stt = float(self.stt_edit.text() or 0)
            data = {
                'hkl': (float(self.h_edit.text() or 0),
                        float(self.k_edit.text() or 0),
                        float(self.l_edit.text() or 0)),
                'ki': float(self.ki_edit.text() or 0),
                'kf': float(self.kf_edit.text() or 0),
                'locked': self._locked,
            }
        except ValueError:
            return None
        if self._legacy:
            data.update(angles=(values[0], values[1], stt), stage=None,
                        sense_sample=self._sense)
            return data
        readouts = {ax.name: value for ax, value in zip(self._gonio, values)}
        stage = dict(self._stage) if self._stage else stage_record(self._gonio, readouts)
        stage["angles"] = {**stage["angles"], **readouts}
        # The saved triple keeps its legacy meaning for readers that ignore
        # the record; an incomplete entry (no ki/kf or 2theta, so not
        # fittable) has no Q and keeps the turntable readout.
        if data['ki'] > 0 and data['kf'] > 0 and stt != 0:
            sense = stage.get("sense") or (1 if stt > 0 else -1)
            angles = legacy_triple(stage, stt, data['ki'], data['kf'], sense)
        else:
            angles = (readouts[self._gonio[0].name], 0.0, stt)
        data.update(angles=angles, stage=stage, sense_sample=stage.get("sense"))
        return data

    def set_peak_data(self, hkl, angles, ki, kf, locked=False, stage=None,
                      sense_sample=None):
        """Set peak data in UI fields; no ``stage`` record means a legacy peak."""
        h, k, l = hkl
        self._stage = dict(stage) if stage else None
        self._sense = sense_sample
        self._set_legacy(stage is None)
        self.h_edit.setText(self._fmt(h))
        self.k_edit.setText(self._fmt(k))
        self.l_edit.setText(self._fmt(l))
        if stage is None:
            omega, chi, _stt = angles
            for edit, value in zip(self.axis_edits, (omega, chi, 0.0)):
                edit.setText(self._fmt(value))
        else:
            for ax, edit in zip(self._gonio, self.axis_edits):
                edit.setText(self._fmt(stage["angles"][ax.name]))
        self.stt_edit.setText(self._fmt(angles[2]))
        self.ki_edit.setText(self._fmt(ki))
        self.kf_edit.setText(self._fmt(kf))
        self.lock_check.setChecked(locked)

    def set_angles_from_position(self, record, stt, ki, kf):
        """Take Position: store the stage record and fill the fields."""
        if self._locked:
            return
        self._stage = dict(record)
        self._sense = record.get("sense")
        self._set_legacy(False)
        for ax, edit in zip(self._gonio, self.axis_edits):
            edit.setText(self._fmt(record["angles"][ax.name]))
        self.stt_edit.setText(self._fmt(stt))
        self.ki_edit.setText(self._fmt(ki))
        self.kf_edit.setText(self._fmt(kf))

    def update_valid_indicator(self, is_valid: bool):
        """Update the validity indicator."""
        if is_valid:
            self.valid_indicator.setText("✓")
            self.valid_indicator.setStyleSheet("color: green; font-weight: bold;")
            self.valid_indicator.setToolTip("Peak valid")
        else:
            self.valid_indicator.setText("⚠")
            self.valid_indicator.setStyleSheet("color: orange;")
            self.valid_indicator.setToolTip("Peak incomplete")


class UBMatrixDock(BaseDockWidget):
    """Dock widget for UB matrix operations."""

    # Signals
    ub_matrix_changed = Signal(bool)  # True if non-identity UB
    lattice_refinement_requested = Signal(tuple)  # (a, b, c, alpha, beta, gamma)
    training_changed = Signal(bool)  # True if training loaded
    misalignment_from_training = Signal(float, float)  # (mis_omega, mis_chi)

    def __init__(self, parent=None, descriptor=None):
        super().__init__("UB Matrix", parent, use_scroll_area=True)
        self.setObjectName("UBMatrixDock")

        # The peak angle columns follow the active instrument's goniometer.
        self._gonio = tuple(descriptor.goniometer) if descriptor is not None else tas_goniometer()
        self._ub_locked = True
        self._saved_ub_values = {}
        self._peak_widgets = []

        main_layout = self.content_layout

        try:
            self.setMinimumSize(540, 500)
        except Exception:
            pass

        # ===== UB Matrix Display Section =====
        ub_group = QGroupBox("UB Matrix")
        ub_layout = QVBoxLayout()
        ub_layout.setSpacing(5)
        ub_group.setLayout(ub_layout)

        # Lock/unlock button
        lock_layout = QHBoxLayout()
        lock_layout.setContentsMargins(0, 0, 0, 0)
        self.ub_lock_button = QPushButton("\U0001f512 Locked")
        self.ub_lock_button.setToolTip("Click to unlock UB matrix for manual editing")
        self.ub_lock_button.setCheckable(True)
        self.ub_lock_button.setChecked(False)
        self.ub_lock_button.clicked.connect(self._on_ub_lock_toggled)
        lock_layout.addWidget(self.ub_lock_button)

        self.ub_status_label = QLabel("\u26aa UB = Identity (no orientation)")
        self.ub_status_label.setStyleSheet("color: gray; font-size: 10px;")
        lock_layout.addWidget(self.ub_status_label)
        lock_layout.addStretch()
        ub_layout.addLayout(lock_layout)

        # 3x3 matrix grid
        self.ub_grid = QGridLayout()
        self.ub_grid.setSpacing(3)
        self.ub_edits = []
        for row in range(3):
            row_edits = []
            for col in range(3):
                value = "1" if row == col else "0"
                edit = QLineEdit(value)
                edit.setMaximumWidth(80)
                edit.setReadOnly(True)
                edit.setStyleSheet("background-color: #f0f0f0; color: #666;")
                self.ub_grid.addWidget(edit, row, col)
                row_edits.append(edit)
            self.ub_edits.append(row_edits)
        ub_layout.addLayout(self.ub_grid)

        # Save/Discard buttons (hidden when locked)
        ub_buttons_layout = QHBoxLayout()
        ub_buttons_layout.setContentsMargins(0, 3, 0, 0)
        self.ub_save_button = QPushButton("\u2713 Save UB")
        self.ub_save_button.setStyleSheet("background-color: #4CAF50; color: white;")
        self.ub_save_button.clicked.connect(self._on_ub_save)
        self.ub_save_button.setVisible(False)
        self.ub_discard_button = QPushButton("\u2717 Discard")
        self.ub_discard_button.setStyleSheet("background-color: #f44336; color: white;")
        self.ub_discard_button.clicked.connect(self._on_ub_discard)
        self.ub_discard_button.setVisible(False)
        ub_buttons_layout.addWidget(self.ub_save_button)
        ub_buttons_layout.addWidget(self.ub_discard_button)
        ub_layout.addLayout(ub_buttons_layout)

        main_layout.addWidget(ub_group)

        # ===== Scattering Plane Section =====
        plane_group = QGroupBox("Scattering Plane")
        plane_layout = QGridLayout()
        plane_layout.setSpacing(3)
        plane_group.setLayout(plane_layout)

        plane_layout.addWidget(QLabel("Plane normal (HKL):"), 0, 0)
        self.plane_normal_label = QLabel("--")
        plane_layout.addWidget(self.plane_normal_label, 0, 1)

        plane_layout.addWidget(QLabel("\u03c7 tilt:"), 1, 0)
        self.chi_mis_label = QLabel("--")
        plane_layout.addWidget(self.chi_mis_label, 1, 1)

        plane_layout.addWidget(QLabel("\u03c9 offset:"), 2, 0)
        self.omega_offset_label = QLabel("--")
        plane_layout.addWidget(self.omega_offset_label, 2, 1)

        # Lock plane (2.3): hold the arcs for an experiment. The controller
        # owns the lock; this row shows it.
        plane_layout.addWidget(QLabel("Lock plane:"), 3, 0)
        lock_row = QHBoxLayout()
        lock_row.setSpacing(4)
        self.lock_u_edit = QLineEdit()
        self.lock_v_edit = QLineEdit()
        for edit in (self.lock_u_edit, self.lock_v_edit):
            edit.setPlaceholderText("h k l")
            edit.setMaximumWidth(70)
            edit.setToolTip("Two (h k l) spanning the plane to lock. Empty: the mounting "
                            "plane, else the first two peaks, else (1 0 0)/(0 1 0).")
            lock_row.addWidget(edit)
        self.lock_plane_button = QPushButton("Lock")
        self.lock_plane_button.setToolTip(
            "Put the arcs where the UB levels this plane and keep them (and kappa) there")
        self.release_plane_button = QPushButton("Release")
        self.release_plane_button.setToolTip("Back to free mode: the arcs follow each Q")
        self.release_plane_button.setEnabled(False)
        lock_row.addWidget(self.lock_plane_button)
        lock_row.addWidget(self.release_plane_button)
        lock_row.addStretch()
        plane_layout.addLayout(lock_row, 3, 1)
        self.lock_status_label = QLabel("Free: the arcs follow each Q")
        self.lock_status_label.setWordWrap(True)
        self.lock_status_label.setStyleSheet("color: gray; font-size: 10px;")
        plane_layout.addWidget(self.lock_status_label, 4, 0, 1, 2)

        main_layout.addWidget(plane_group)

        # ===== Observed Bragg Peaks Section =====
        peaks_group = QGroupBox("Observed Bragg Peaks")
        peaks_main_layout = QVBoxLayout()
        peaks_main_layout.setSpacing(5)
        peaks_group.setLayout(peaks_main_layout)

        # Scrollable peak list
        self.peaks_scroll = QScrollArea()
        self.peaks_scroll.setWidgetResizable(True)
        self.peaks_scroll.setMinimumHeight(400)
        self.peaks_container = QWidget()
        self.peaks_layout = QVBoxLayout(self.peaks_container)
        self.peaks_layout.setSpacing(5)
        self.peaks_layout.addStretch()
        self.peaks_scroll.setWidget(self.peaks_container)
        peaks_main_layout.addWidget(self.peaks_scroll)

        # Add Peak button
        self.add_peak_button = QPushButton("\u2795 Add Peak")
        self.add_peak_button.clicked.connect(self.add_peak_entry)
        peaks_main_layout.addWidget(self.add_peak_button)

        main_layout.addWidget(peaks_group)

        # ===== Calculation Buttons =====
        calc_group = QGroupBox("Calculations")
        calc_layout = QHBoxLayout()
        calc_layout.setSpacing(5)
        calc_group.setLayout(calc_layout)

        self.calculate_ub_button = QPushButton("Calculate UB")
        self.calculate_ub_button.setToolTip("Calculate UB matrix from observed peaks (\u22652 required)")
        calc_layout.addWidget(self.calculate_ub_button)

        self.refine_lattice_button = QPushButton("Refine Lattice")
        self.refine_lattice_button.setToolTip("Refine lattice parameters from peak observations")
        calc_layout.addWidget(self.refine_lattice_button)

        self.reset_ub_button = QPushButton("Reset to Identity")
        self.reset_ub_button.setToolTip("Clear orientation (set U = I)")
        calc_layout.addWidget(self.reset_ub_button)

        main_layout.addWidget(calc_group)

        # ===== Separator =====
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(separator)

        # ===== Alignment Training Section =====
        training_group = QGroupBox("Alignment Training")
        training_layout = QVBoxLayout()
        training_layout.setSpacing(8)
        training_group.setLayout(training_layout)

        # Teacher sub-section
        teacher_label = QLabel("<b>Teacher: Generate Exercise</b>")
        training_layout.addWidget(teacher_label)

        teacher_grid = QGridLayout()
        teacher_grid.setSpacing(4)

        teacher_grid.addWidget(QLabel("Max orientation:"), 0, 0)
        self.max_ori_spin = QDoubleSpinBox()
        self.max_ori_spin.setRange(0, 45)
        self.max_ori_spin.setValue(10)
        self.max_ori_spin.setSuffix("\u00b0")
        self.max_ori_spin.setMaximumWidth(80)
        teacher_grid.addWidget(self.max_ori_spin, 0, 1)

        teacher_grid.addWidget(QLabel("Max misalignment:"), 0, 2)
        self.max_mis_spin = QDoubleSpinBox()
        self.max_mis_spin.setRange(0, 20)
        self.max_mis_spin.setValue(5)
        self.max_mis_spin.setSuffix("\u00b0")
        self.max_mis_spin.setMaximumWidth(80)
        teacher_grid.addWidget(self.max_mis_spin, 0, 3)

        self.include_orientation_check = QCheckBox("Orientation")
        self.include_orientation_check.setChecked(True)
        teacher_grid.addWidget(self.include_orientation_check, 1, 0)
        self.include_misalignment_check = QCheckBox("Misalignment")
        self.include_misalignment_check.setChecked(True)
        teacher_grid.addWidget(self.include_misalignment_check, 1, 1)

        self.generate_training_button = QPushButton("Generate")
        teacher_grid.addWidget(self.generate_training_button, 1, 2, 1, 2)

        training_layout.addLayout(teacher_grid)

        # Hash display
        hash_display_layout = QHBoxLayout()
        hash_display_layout.setSpacing(4)
        hash_display_layout.addWidget(QLabel("Hash:"))
        self.training_hash_display = QLineEdit()
        self.training_hash_display.setReadOnly(True)
        self.training_hash_display.setPlaceholderText("Generated hash will appear here")
        hash_display_layout.addWidget(self.training_hash_display)
        self.copy_hash_button = QPushButton("Copy")
        self.copy_hash_button.setMaximumWidth(50)
        self.copy_hash_button.clicked.connect(self._copy_hash)
        hash_display_layout.addWidget(self.copy_hash_button)
        training_layout.addLayout(hash_display_layout)

        # Student sub-section
        student_label = QLabel("<b>Student: Load Exercise</b>")
        training_layout.addWidget(student_label)

        student_layout = QHBoxLayout()
        student_layout.setSpacing(4)
        self.load_hash_edit = QLineEdit()
        self.load_hash_edit.setPlaceholderText("Paste training hash here...")
        student_layout.addWidget(self.load_hash_edit)
        self.load_training_button = QPushButton("Load")
        self.load_training_button.setMaximumWidth(50)
        student_layout.addWidget(self.load_training_button)
        self.clear_training_button = QPushButton("Clear")
        self.clear_training_button.setMaximumWidth(50)
        student_layout.addWidget(self.clear_training_button)
        training_layout.addLayout(student_layout)

        self.training_status_label = QLabel("\u26aa No training exercise loaded")
        self.training_status_label.setStyleSheet("color: gray; font-size: 11px;")
        training_layout.addWidget(self.training_status_label)

        # Check sub-section
        check_label = QLabel("<b>Check Alignment</b>")
        training_layout.addWidget(check_label)

        self.check_training_button = QPushButton("Check My Alignment")
        self.check_training_button.setEnabled(False)
        training_layout.addWidget(self.check_training_button)

        self.check_miss_label = QLabel("Worst miss: --")
        self.check_miss_label.setStyleSheet("font-size: 11px;")
        self.check_miss_label.setWordWrap(True)
        training_layout.addWidget(self.check_miss_label)

        self.check_overall_label = QLabel("Overall: --")
        self.check_overall_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        training_layout.addWidget(self.check_overall_label)

        main_layout.addWidget(training_group)

        # Stretch at end
        main_layout.addStretch()

        # Add 2 default peak entries
        self.add_peak_entry()
        self.add_peak_entry()

    # ===== UB Lock/Unlock =====

    def _on_ub_lock_toggled(self):
        if self._ub_locked:
            # Save current values for discard
            self._saved_ub_values = self._get_ub_values()
            self._ub_locked = False
        else:
            self._on_ub_discard()
            return
        self._apply_ub_lock_state()

    def _on_ub_save(self):
        self._ub_locked = True
        self._apply_ub_lock_state()
        self._saved_ub_values = {}
        try:
            UB = self.get_ub_matrix_from_fields()
            is_non_identity = not np.allclose(UB, np.eye(3), atol=1e-6)
        except ValueError:
            is_non_identity = False
        self.ub_matrix_changed.emit(is_non_identity)

    def _on_ub_discard(self):
        if self._saved_ub_values:
            self._set_ub_values(self._saved_ub_values)
        self._ub_locked = True
        self._apply_ub_lock_state()
        self._saved_ub_values = {}

    def _apply_ub_lock_state(self):
        locked = self._ub_locked
        for row in self.ub_edits:
            for edit in row:
                edit.setReadOnly(locked)
                if locked:
                    edit.setStyleSheet("background-color: #f0f0f0; color: #666;")
                else:
                    edit.setStyleSheet("background-color: #ffffcc;")
        if locked:
            self.ub_lock_button.setText("\U0001f512 Locked")
            self.ub_lock_button.setChecked(False)
        else:
            self.ub_lock_button.setText("\U0001f513 Editing...")
            self.ub_lock_button.setChecked(True)
        self.ub_save_button.setVisible(not locked)
        self.ub_discard_button.setVisible(not locked)

    def _get_ub_values(self) -> dict:
        values = {}
        for i in range(3):
            for j in range(3):
                values[f'{i}{j}'] = self.ub_edits[i][j].text()
        return values

    def _set_ub_values(self, values: dict):
        for i in range(3):
            for j in range(3):
                self.ub_edits[i][j].setText(values.get(f'{i}{j}', '0'))

    def get_ub_matrix_from_fields(self) -> np.ndarray:
        """Read UB matrix from the 3x3 grid fields.

        Raises:
            ValueError: If any field contains a non-numeric value.
        """
        UB = np.zeros((3, 3))
        for i in range(3):
            for j in range(3):
                text = self.ub_edits[i][j].text() or "0"
                try:
                    UB[i, j] = float(text)
                except ValueError:
                    raise ValueError(
                        f"Non-numeric value at row {i} col {j}: '{text}'"
                    )
        return UB

    # ===== UB Display Update =====

    def update_ub_display(self, UB: np.ndarray, is_identity: bool):
        """Update the 3x3 UB matrix display."""
        for i in range(3):
            for j in range(3):
                self.ub_edits[i][j].setText(f"{UB[i, j]:.4f}")
        if is_identity:
            self.ub_status_label.setText("\u26aa UB = Identity (no orientation)")
            self.ub_status_label.setStyleSheet("color: gray; font-size: 10px;")
        else:
            self.ub_status_label.setText("\U0001f7e2 UB matrix active")
            self.ub_status_label.setStyleSheet("color: green; font-weight: bold; font-size: 10px;")

    def update_plane_info(self, plane_info: dict):
        """Update scattering plane display."""
        normal = plane_info.get('plane_normal_hkl', (0, 0, 0))
        chi_mis = plane_info.get('chi_misalignment_deg', 0)
        omega_off = plane_info.get('omega_offset_deg', 0)

        self.plane_normal_label.setText(
            f"[{normal[0]:.2f}, {normal[1]:.2f}, {normal[2]:.2f}]"
        )
        self.chi_mis_label.setText(f"{chi_mis:.2f}\u00b0")
        self.omega_offset_label.setText(f"{omega_off:.2f}\u00b0")

    def show_plane_lock(self, plane, status, stale=False):
        """Show the controller's lock: ``plane`` its two (h k l) (None: free),
        ``status`` the status line, ``stale`` the stale mark. Holds no lock
        state of its own."""
        locked = plane is not None
        if locked:
            for edit, hkl in zip((self.lock_u_edit, self.lock_v_edit), plane):
                edit.setText(" ".join(f"{float(x):g}" for x in hkl))
        for edit in (self.lock_u_edit, self.lock_v_edit):
            edit.setReadOnly(locked)
        self.lock_plane_button.setEnabled(not locked)
        self.release_plane_button.setEnabled(locked)
        self.lock_status_label.setText(status)
        self.lock_status_label.setStyleSheet(
            "color: #c62828; font-weight: bold; font-size: 10px;" if stale
            else "color: gray; font-size: 10px;")

    # ===== Peak Management =====

    def add_peak_entry(self):
        """Add a new peak entry widget."""
        index = len(self._peak_widgets)
        peak_widget = PeakEntryWidget(index, self._gonio, self)
        # Insert before the stretch
        self.peaks_layout.insertWidget(self.peaks_layout.count() - 1, peak_widget)
        self._peak_widgets.append(peak_widget)
        return peak_widget

    def remove_peak_entry(self, index: int):
        """Remove a peak entry by index."""
        if len(self._peak_widgets) <= 2:
            return  # Keep minimum 2 peaks
        if 0 <= index < len(self._peak_widgets):
            widget = self._peak_widgets.pop(index)
            self.peaks_layout.removeWidget(widget)
            widget.deleteLater()
            # Re-index remaining widgets
            for i, pw in enumerate(self._peak_widgets):
                pw.index = i
                pw.peak_label.setText(f"<b>Peak {i + 1}</b>")

    def get_all_peak_data(self) -> list:
        """Get data from all peak entry widgets."""
        peaks = []
        for pw in self._peak_widgets:
            data = pw.get_peak_data()
            if data:
                peaks.append(data)
        return peaks

    def set_peak_entries(self, peaks_data: list):
        """Set peak entries from a list of peak data dicts."""
        # Clear existing
        while self._peak_widgets:
            widget = self._peak_widgets.pop()
            self.peaks_layout.removeWidget(widget)
            widget.deleteLater()

        # Add new
        for data in peaks_data:
            pw = self.add_peak_entry()
            pw.set_peak_data(
                data.get('hkl', (0, 0, 0)),
                data.get('angles', (0, 0, 0)),
                data.get('ki', 0),
                data.get('kf', 0),
                data.get('locked', False),
                stage=data.get('stage'),
                sense_sample=data.get('sense_sample'),
            )

        # Ensure minimum 2
        while len(self._peak_widgets) < 2:
            self.add_peak_entry()

    def get_peak_widget(self, index: int):
        """Return peak widget by index."""
        if 0 <= index < len(self._peak_widgets):
            return self._peak_widgets[index]
        return None

    # ===== Training =====

    def _copy_hash(self):
        """Copy training hash to clipboard."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.training_hash_display.text())

    def update_training_status(self, loaded: bool):
        """Update training status display."""
        if loaded:
            self.training_status_label.setText("\u2714 Training exercise loaded (hidden)")
            self.training_status_label.setStyleSheet("color: green; font-weight: bold; font-size: 11px;")
            self.check_training_button.setEnabled(True)
        else:
            self.training_status_label.setText("\u26aa No training exercise loaded")
            self.training_status_label.setStyleSheet("color: gray; font-size: 11px;")
            self.check_training_button.setEnabled(False)
            # Clear check results
            self.check_miss_label.setText("Worst miss: --")
            self.check_miss_label.setStyleSheet("font-size: 11px;")
            self.check_overall_label.setText("Overall: --")

    def update_check_results(self, results: dict):
        """Show a grade from ``tavi.ub_matrix.grade_alignment``: the worst
        miss and its HKL, and the overall status."""
        status_colors = {
            'aligned': 'green',
            'close': '#FF8C00',
            'way_off': 'red',
        }

        overall = results.get('status', 'way_off')
        self.check_miss_label.setText(results.get('summary', '--'))
        self.check_miss_label.setStyleSheet(
            f"color: {status_colors.get(overall, 'gray')}; font-size: 11px;"
        )
        overall_text = {
            'aligned': '\u2705 Fully Aligned!',
            'close': '\U0001f7e1 Getting Close...',
            'way_off': '\u274c Not Yet Aligned',
            'cannot_assess': 'Cannot assess',
        }
        self.check_overall_label.setText(f"Overall: {overall_text.get(overall, '--')}")
        self.check_overall_label.setStyleSheet(
            f"color: {status_colors.get(overall, 'gray')}; font-weight: bold; font-size: 12px;"
        )
