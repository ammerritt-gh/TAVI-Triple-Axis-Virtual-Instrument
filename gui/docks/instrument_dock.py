"""Instrument Configuration Dock for TAVI application.

Phase 2 (docs/CONFIGURABLE_INSTRUMENTS.md §7): option lists and the
collimation/slit/module rows are generated from the active instrument's
``InstrumentDescriptor`` instead of hard-coded literals. Widgets fall into two
groups:

- "live-linked" widgets (angles, energies, crystal combos, bending) keep their
  historical attribute names because the controller binds signals to them.
- "static config" widgets (source, modules, collimation, slits) are generated
  from descriptor lists and reached through the accessor methods below; the
  controller no longer touches them by attribute name.
"""
import math

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QComboBox,
                                QCheckBox, QGroupBox, QFormLayout, QGridLayout,
                                QPushButton, QWidget)
from PySide6.QtCore import Qt

from gui.docks.base_dock import (BaseDockWidget, NoScrollComboBox,
                                 COLLIMATION_OPEN_TOOLTIP, collimation_label)
from instruments.descriptor import ModuleKind


class InstrumentDock(BaseDockWidget):
    """Dock widget for instrument configuration (descriptor-driven)."""

    def __init__(self, parent=None, descriptor=None):
        super().__init__("Instrument Configuration", parent, use_scroll_area=True)
        self.setObjectName("InstrumentDock")
        if descriptor is None:
            raise ValueError("InstrumentDock requires the active InstrumentDescriptor")
        self.descriptor = descriptor

        # Get the content layout from base class
        main_layout = self.content_layout

        # Source Control section (types + extra-param rows from descriptor)
        source_group = QGroupBox("Source Control")
        source_layout = QFormLayout()
        source_group.setLayout(source_layout)

        self.source_type_combo = NoScrollComboBox()
        self.source_type_combo.setObjectName("source_type_combo")
        for source_type in descriptor.source_types:
            self.source_type_combo.addItem(source_type.display_name, source_type.id)
        self.source_type_combo.setToolTip("Maxwellian: thermal distribution peaking at E0 = 25 meV\nMono: narrow, uniform energy distribution centered on E_i")
        source_layout.addRow("Source type:", self.source_type_combo)

        # Source dE input (shown for source types declaring the extra param)
        self.source_dE_label = QLabel("Source dE (meV):")
        self.source_dE_edit = QLineEdit()
        self.source_dE_edit.setMaximumWidth(70)
        self.source_dE_edit.setText("2")
        self.source_dE_edit.setToolTip("Energy half-spread for Mono source (E0 ± dE)")
        source_layout.addRow(self.source_dE_label, self.source_dE_edit)

        self._update_source_extra_visibility()
        self.source_type_combo.currentTextChanged.connect(self._on_source_type_changed)

        main_layout.addWidget(source_group)

        # Angles section
        angles_group = QGroupBox("Instrument Angles")
        angles_layout = QGridLayout()
        angles_layout.setSpacing(5)
        angles_group.setLayout(angles_layout)

        # Row 0: Mono 2theta, Sample 2theta
        angles_layout.addWidget(QLabel("Mono 2θ:"), 0, 0)
        self.mtt_edit = QLineEdit()
        self.mtt_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.mtt_edit, 0, 1)

        angles_layout.addWidget(QLabel("Sample 2θ:"), 0, 2)
        self.stt_edit = QLineEdit()
        self.stt_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.stt_edit, 0, 3)

        # Row 1: the sample turntable A3 (the API's and saved files' omega),
        # Analyzer 2theta
        a3_tip = ("Sample turntable A3: in-plane rotation about the vertical. "
                  "Called omega in the API, saved files and scan commands.")
        a3_label = QLabel("A3:")
        a3_label.setToolTip(a3_tip)
        angles_layout.addWidget(a3_label, 1, 0)
        self.omega_edit = QLineEdit()
        self.omega_edit.setMaximumWidth(70)
        self.omega_edit.setToolTip(a3_tip)
        angles_layout.addWidget(self.omega_edit, 1, 1)

        angles_layout.addWidget(QLabel("Ana 2θ:"), 1, 2)
        self.att_edit = QLineEdit()
        self.att_edit.setMaximumWidth(70)
        angles_layout.addWidget(self.att_edit, 1, 3)

        # Row 2: the sample tilt arcs (descriptor goniometer), side by side:
        # solved from Q/HKL, operator-set for angle-mode scans. Travel from
        # the descriptor.
        travel = {ax.name: ax for ax in self.descriptor.goniometer}
        self.sgl_edit = QLineEdit()
        self.sgu_edit = QLineEdit()
        for column, name, edit, text in (
            (0, "sgl", self.sgl_edit,
             "Lower sample tilt arc sgl: turns about the horizontal axis "
             "perpendicular to the beam at A3 = 0 (stage x); rides on A3"),
            (2, "sgu", self.sgu_edit,
             "Upper sample tilt arc sgu: turns about the beam axis at A3 = 0 "
             "(stage z); rides on sgl"),
        ):
            ax = travel.get(name)
            if ax is None or math.isinf(ax.lower):
                limits = "travel undocumented (unlimited)"
            else:
                limits = f"travel {ax.lower:g}° to {ax.upper:g}°"
            tip = f"{text}. Solved from Q/HKL; set it here for angle-mode scans; {limits}."
            label = QLabel(f"Tilt {name}:")
            label.setToolTip(tip)
            edit.setMaximumWidth(70)
            edit.setToolTip(tip)
            angles_layout.addWidget(label, 2, column)
            angles_layout.addWidget(edit, 2, column + 1)

        # Row 3: shown while the angle fields do not match Q/HKL (the stage
        # refused the last Q/HKL edit); the controller sets and clears it.
        self.angles_stale_label = QLabel()
        self.angles_stale_label.setWordWrap(True)
        self.angles_stale_label.setStyleSheet("color: #c1121f;")
        self.angles_stale_label.hide()
        angles_layout.addWidget(self.angles_stale_label, 3, 0, 1, 4)

        main_layout.addWidget(angles_group)

        # Energies section
        energies_group = QGroupBox("Energies and Wave Vectors")
        energies_layout = QGridLayout()
        energies_layout.setSpacing(5)
        energies_group.setLayout(energies_layout)

        energies_layout.addWidget(QLabel("Ki (1/Å):"), 0, 0)
        self.Ki_edit = QLineEdit()
        self.Ki_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ki_edit, 0, 1)

        energies_layout.addWidget(QLabel("Ei (meV):"), 0, 2)
        self.Ei_edit = QLineEdit()
        self.Ei_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ei_edit, 0, 3)

        energies_layout.addWidget(QLabel("Kf (1/Å):"), 1, 0)
        self.Kf_edit = QLineEdit()
        self.Kf_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Kf_edit, 1, 1)

        energies_layout.addWidget(QLabel("Ef (meV):"), 1, 2)
        self.Ef_edit = QLineEdit()
        self.Ef_edit.setMaximumWidth(70)
        energies_layout.addWidget(self.Ef_edit, 1, 3)

        main_layout.addWidget(energies_group)

        # Crystals section (items from descriptor; ids stored as item data)
        crystals_group = QGroupBox("Monochromator and Analyzer Crystals")
        crystals_layout = QFormLayout()
        crystals_group.setLayout(crystals_layout)

        self.monocris_combo = NoScrollComboBox()
        self.monocris_combo.setObjectName("monocris_combo")
        for crystal in descriptor.mono_crystals:
            self.monocris_combo.addItem(crystal.display_name, crystal.id)
        crystals_layout.addRow("Monochromator crystal:", self.monocris_combo)

        self.anacris_combo = NoScrollComboBox()
        self.anacris_combo.setObjectName("anacris_combo")
        for crystal in descriptor.ana_crystals:
            self.anacris_combo.addItem(crystal.display_name, crystal.id)
        crystals_layout.addRow("Analyzer crystal:", self.anacris_combo)

        main_layout.addWidget(crystals_group)

        # Optional modules section (generated from descriptor.modules)
        self.module_widgets = {}
        if descriptor.modules:
            optics_group = QGroupBox("Experimental Modules")
            optics_layout = QFormLayout()
            optics_group.setLayout(optics_layout)

            for module in descriptor.modules:
                if module.kind is ModuleKind.CHOICE:
                    combo = NoScrollComboBox()
                    combo.setObjectName(f"module_{module.id}")
                    combo.addItems(list(module.options))
                    combo.setCurrentText(str(module.default))
                    optics_layout.addRow(f"{module.display_name}:", combo)
                    self.module_widgets[module.id] = combo
                else:  # TOGGLE
                    check = QCheckBox(module.display_name)
                    check.setObjectName(f"module_{module.id}")
                    check.setChecked(bool(module.default))
                    optics_layout.addRow(check)
                    self.module_widgets[module.id] = check

            main_layout.addWidget(optics_group)

        # Legacy attribute aliases for controller signal wiring (PUMA-specific
        # couplings guard with getattr, so absence is fine on other instruments).
        self.nmo_combo = self.module_widgets.get("nmo")
        self.v_selector_check = self.module_widgets.get("v_selector")

        # Focusing section (bending is generic TAS mono/ana state; stays static)
        focusing_group = QGroupBox("Crystal Focusing (Absolute Radii, m)")
        focusing_layout = QGridLayout()
        focusing_layout.setSpacing(5)
        focusing_group.setLayout(focusing_layout)

        focusing_layout.addWidget(QLabel("rhm:"), 0, 0)
        self.rhm_edit = QLineEdit()
        self.rhm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rhm_edit, 0, 1)
        self.rhm_ideal_button = QPushButton("Ideal: --")
        self.rhm_ideal_button.setCheckable(True)
        self.rhm_ideal_button.setMaximumWidth(140)
        self.rhm_ideal_button.setToolTip("Set rhm to the calculated ideal value")
        focusing_layout.addWidget(self.rhm_ideal_button, 0, 2)

        focusing_layout.addWidget(QLabel("rvm:"), 0, 3)
        self.rvm_edit = QLineEdit()
        self.rvm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rvm_edit, 0, 4)
        self.rvm_ideal_button = QPushButton("Ideal: --")
        self.rvm_ideal_button.setCheckable(True)
        self.rvm_ideal_button.setMaximumWidth(140)
        self.rvm_ideal_button.setToolTip("Set rvm to the calculated ideal value")
        focusing_layout.addWidget(self.rvm_ideal_button, 0, 5)

        focusing_layout.addWidget(QLabel("rha:"), 1, 0)
        self.rha_edit = QLineEdit()
        self.rha_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rha_edit, 1, 1)
        self.rha_ideal_button = QPushButton("Ideal: --")
        self.rha_ideal_button.setCheckable(True)
        self.rha_ideal_button.setMaximumWidth(140)
        self.rha_ideal_button.setToolTip("Set rha to the calculated ideal value")
        focusing_layout.addWidget(self.rha_ideal_button, 1, 2)

        # Beside rha, so the analyser's two axes read as a pair the way the
        # monochromator's rhm/rvm do. Enable state (editable/disabled) and
        # whether the Ideal button is offered at all are set per selected
        # analyser by the controller -- rva is the one axis whose declared
        # policy (fixed / no established focusing model / ordinary) actually
        # differs between crystals.
        focusing_layout.addWidget(QLabel("rva:"), 1, 3)
        self.rva_edit = QLineEdit()
        self.rva_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rva_edit, 1, 4)
        self.rva_ideal_button = QPushButton("Ideal: --")
        self.rva_ideal_button.setCheckable(True)
        self.rva_ideal_button.setMaximumWidth(140)
        self.rva_ideal_button.setToolTip("Set rva to the calculated ideal value")
        focusing_layout.addWidget(self.rva_ideal_button, 1, 5)

        main_layout.addWidget(focusing_group)

        # Collimations section (rows generated from descriptor.collimation)
        self.collimation_widgets = {}
        if descriptor.collimation:
            collimations_group = QGroupBox("Collimations")
            collimations_layout = QGridLayout()
            collimations_layout.setSpacing(5)
            collimations_group.setLayout(collimations_layout)

            for row, slot in enumerate(descriptor.collimation):
                collimations_layout.addWidget(QLabel(f"{slot.label}:"), row, 0)
                if slot.multi_select:
                    slot_widget = QWidget()
                    slot_layout = QHBoxLayout()
                    slot_layout.setContentsMargins(0, 0, 0, 0)
                    slot_layout.setSpacing(3)
                    checks = {}
                    for value in slot.allowed:
                        check = QCheckBox(collimation_label(value))
                        check.setObjectName(f"collimation_{slot.id}_{value}")
                        check.setToolTip(COLLIMATION_OPEN_TOOLTIP)
                        slot_layout.addWidget(check)
                        checks[value] = check
                    # Nothing checked is an open position: show it, display
                    # only (the stored selection stays the empty set).
                    open_label = QLabel("Open")
                    open_label.setToolTip(COLLIMATION_OPEN_TOOLTIP)
                    slot_layout.addWidget(open_label)

                    def _sync(_=None, checks=checks, open_label=open_label):
                        open_label.setHidden(
                            any(c.isChecked() for c in checks.values()))

                    for check in checks.values():
                        check.toggled.connect(_sync)
                    _sync()
                    slot_widget.setLayout(slot_layout)
                    collimations_layout.addWidget(slot_widget, row, 1, 1, 2)
                    self.collimation_widgets[slot.id] = checks
                else:
                    combo = NoScrollComboBox()
                    combo.setObjectName(f"collimation_{slot.id}")
                    for value in slot.allowed:
                        combo.addItem(collimation_label(value), value)
                    combo.setCurrentIndex(max(combo.findData(slot.default), 0))
                    combo.setToolTip(COLLIMATION_OPEN_TOOLTIP)
                    combo.setMaximumWidth(80)
                    collimations_layout.addWidget(combo, row, 1)
                    self.collimation_widgets[slot.id] = combo

            main_layout.addWidget(collimations_group)

        # Slit Apertures section (rows generated from descriptor.slits)
        self.slit_widgets = {}
        if descriptor.slits:
            slits_group = QGroupBox("Slit Apertures (mm)")
            slits_layout = QGridLayout()
            slits_layout.setSpacing(5)
            slits_group.setLayout(slits_layout)

            for row, slit in enumerate(descriptor.slits):
                widgets = {}
                if slit.has_width and slit.has_height:
                    slits_layout.addWidget(QLabel(f"{slit.label}:"), row, 0)
                    pair_widget = QWidget()
                    pair_layout = QHBoxLayout()
                    pair_layout.setContentsMargins(0, 0, 0, 0)
                    pair_layout.setSpacing(3)
                    width_edit = QLineEdit()
                    width_edit.setObjectName(f"slit_{slit.id}_width")
                    width_edit.setMaximumWidth(50)
                    pair_layout.addWidget(width_edit)
                    pair_layout.addWidget(QLabel("×"))
                    height_edit = QLineEdit()
                    height_edit.setObjectName(f"slit_{slit.id}_height")
                    height_edit.setMaximumWidth(50)
                    pair_layout.addWidget(height_edit)
                    pair_widget.setLayout(pair_layout)
                    slits_layout.addWidget(pair_widget, row, 1)
                    widgets["width"] = width_edit
                    widgets["height"] = height_edit
                else:
                    slits_layout.addWidget(QLabel(f"{slit.label}:"), row, 0)
                    width_edit = QLineEdit()
                    width_edit.setObjectName(f"slit_{slit.id}_width")
                    width_edit.setMaximumWidth(70)
                    slits_layout.addWidget(width_edit, row, 1)
                    widgets["width"] = width_edit
                self.slit_widgets[slit.id] = widgets

            main_layout.addWidget(slits_group)

        # Add stretch at the end to push everything up
        main_layout.addStretch()

    # ------------------------------------------------------------- accessors

    def selected_mono_id(self):
        return self.monocris_combo.currentData()

    def selected_ana_id(self):
        return self.anacris_combo.currentData()

    def set_mono_id(self, crystal_id):
        index = self.monocris_combo.findData(crystal_id)
        if index >= 0:
            self.monocris_combo.setCurrentIndex(index)

    def set_ana_id(self, crystal_id):
        index = self.anacris_combo.findData(crystal_id)
        if index >= 0:
            self.anacris_combo.setCurrentIndex(index)

    def selected_source_id(self):
        return self.source_type_combo.currentData()

    def set_source_id(self, source_id):
        index = self.source_type_combo.findData(source_id)
        if index >= 0:
            self.source_type_combo.setCurrentIndex(index)

    def module_values(self):
        """{module_id: current value} -- str for CHOICE, bool for TOGGLE."""
        values = {}
        for module_id, widget in self.module_widgets.items():
            if isinstance(widget, QComboBox):
                values[module_id] = widget.currentText()
            else:
                values[module_id] = widget.isChecked()
        return values

    def set_module_values(self, values):
        for module in self.descriptor.modules:
            widget = self.module_widgets[module.id]
            value = values.get(module.id, module.default)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
            else:
                widget.setChecked(bool(value))

    def collimation_values(self):
        """{slot_id: selection} -- str for single-select, set[str] for multi."""
        values = {}
        for slot_id, widget in self.collimation_widgets.items():
            if isinstance(widget, dict):
                values[slot_id] = {
                    value for value, check in widget.items() if check.isChecked()
                }
            else:
                values[slot_id] = widget.currentData()
        return values

    def set_collimation_values(self, values):
        for slot in self.descriptor.collimation:
            widget = self.collimation_widgets[slot.id]
            if isinstance(widget, dict):
                if slot.id in values:
                    selected = values[slot.id]
                else:
                    selected = {slot.default} if slot.default else set()
                for value, check in widget.items():
                    check.setChecked(value in selected)
            else:
                idx = widget.findData(str(values.get(slot.id, slot.default)))
                if idx >= 0:
                    widget.setCurrentIndex(idx)

    def slit_values_mm(self):
        """{slit_id: width | (width, height)} in mm.

        Empty fields fall back to the descriptor defaults; malformed numbers
        raise ValueError (matching get_gui_values' historical behavior).
        """
        values = {}
        for slit in self.descriptor.slits:
            widgets = self.slit_widgets[slit.id]
            width = float(widgets["width"].text() or slit.default_width_mm or 0)
            if "height" in widgets:
                height = float(widgets["height"].text() or slit.default_height_mm or 0)
                values[slit.id] = (width, height)
            else:
                values[slit.id] = width
        return values

    def set_slit_values_mm(self, values):
        for slit in self.descriptor.slits:
            widgets = self.slit_widgets[slit.id]
            value = values.get(slit.id)
            if "height" in widgets:
                if value is None:
                    width, height = slit.default_width_mm, slit.default_height_mm
                else:
                    width, height = value
                widgets["width"].setText(str(width))
                widgets["height"].setText(str(height))
            else:
                width = slit.default_width_mm if value is None else value
                widgets["width"].setText(str(width))

    def line_edits_for_feedback(self):
        """All value-bearing QLineEdits, for the controller's visual feedback."""
        edits = [
            self.mtt_edit, self.stt_edit, self.omega_edit, self.sgl_edit, self.sgu_edit,
            self.att_edit, self.Ki_edit, self.Ei_edit, self.Kf_edit, self.Ef_edit,
            self.rhm_edit, self.rvm_edit, self.rha_edit, self.rva_edit,
        ]
        for widgets in self.slit_widgets.values():
            edits.extend(widgets.values())
        return edits

    # ------------------------------------------------------------- internals

    def _update_source_extra_visibility(self):
        source_id = self.source_type_combo.currentData()
        extra_params = ()
        for source_type in self.descriptor.source_types:
            if source_type.id == source_id:
                extra_params = source_type.extra_params
                break
        needs_dE = "source_dE" in extra_params
        self.source_dE_label.setVisible(needs_dE)
        self.source_dE_edit.setVisible(needs_dE)

    def _on_source_type_changed(self, _source_type):
        """Show/hide extra source fields based on the selected source type."""
        self._update_source_extra_visibility()
