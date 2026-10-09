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

from gui.docks.base_dock import (BaseDockWidget, CollapsibleGroup, NoScrollComboBox, pack_grid,
                                 COLLIMATION_OPEN_TOOLTIP, collimation_label)
from instruments.descriptor import ModuleKind
from gui import metrics
from tavi import quantities


def _half(text):
    """A 2θ field's text as its θ readout: half the value, same sign; '--' if not a number."""
    try:
        return f"{float(text) / 2:g}"
    except ValueError:
        return "--"


class InstrumentDock(BaseDockWidget):
    """Dock widget for instrument configuration (descriptor-driven)."""

    def __init__(self, parent=None, descriptor=None):
        super().__init__("Instrument Configuration", parent, use_scroll_area=True,
                         blocks=True)
        self.setObjectName("InstrumentDock")
        if descriptor is None:
            raise ValueError("InstrumentDock requires the active InstrumentDescriptor")
        self.descriptor = descriptor


        # Usage order: angles and energies, then what one changes (collimation,
        # slits), the crystals, and last the rarely touched blocks, folded
        # with a summary of what they hold (keyed for view_layout.json).
        self.collapsible_groups = {}

        # Angles section
        angles_group = QGroupBox("Instrument Angles")
        angles_layout = QGridLayout()
        angles_layout.setSpacing(3)  # tight rows keep the whole block in view on short screens
        angles_group.setLayout(angles_layout)

        # One angle per row so the registry's long labels fit a block: labels
        # are the registry's (physical words, ILL number, unit), the NICOS name
        # is in the tooltip. Row order follows the beam: mono, sample, analyzer,
        # then the arcs. A1 and A5 are read-only readouts of 2theta/2, inline
        # beside their 2theta field under the mark "θ" (the registry label is
        # their tooltip and accessible name) so all angles stay in view.
        def angle_row(row, quantity_id, edit=None, tip="", theta=None):
            q = quantities.by_id(quantity_id)
            tip = f"{tip} NICOS name: {q.nicos}." if tip else f"NICOS name: {q.nicos}."
            label = QLabel(q.label)
            label.setToolTip(tip)
            if edit is None:
                edit = QLineEdit()
            edit.setMaximumWidth(metrics.ANGLE_FIELD_WIDTH)
            edit.setToolTip(tip)
            angles_layout.addWidget(label, row, 0)
            if theta is None:
                angles_layout.addWidget(edit, row, 1)
                return label, edit
            tq = quantities.by_id(theta)
            ttip = (f"{tq.label}. Derived, read-only: half of the 2θ beside it, "
                    f"signed as it. NICOS name: {tq.nicos}.")
            mark, readout = QLabel("θ"), QLineEdit()
            readout.setMaximumWidth(metrics.ANGLE_FIELD_WIDTH)
            readout.setReadOnly(True)
            readout.setStyleSheet("background-color: #f0f0f0; color: #444;")  # as a locked UB field
            readout.setAccessibleName(tq.label)
            for widget in (mark, readout):
                widget.setToolTip(ttip)
            edit.textChanged.connect(lambda text: readout.setText(_half(text)))
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)
            for widget in (edit, mark, readout):
                cell_layout.addWidget(widget)
            angles_layout.addWidget(cell, row, 1)
            return label, edit, mark, readout

        self.mtt_label, self.mtt_edit, self.mono_theta_label, self.mono_theta_edit = angle_row(
            0, "mono_two_theta_deg", theta="mono_theta_deg")
        self.omega_label, self.omega_edit = angle_row(
            1, "sample_rotation_deg",
            tip="Sample turntable: in-plane rotation about the vertical. "
                "Also called omega or psi in scan commands.")
        self.stt_label, self.stt_edit = angle_row(2, "sample_two_theta_deg")
        (self.att_label, self.att_edit,
         self.analyzer_theta_label, self.analyzer_theta_edit) = angle_row(
            3, "analyzer_two_theta_deg", theta="analyzer_theta_deg")

        # Rows 4-5: the sample tilt arcs (descriptor goniometer): solved from
        # Q/HKL, operator-set for angle-mode scans. Travel from the descriptor.
        travel = {ax.name: ax for ax in self.descriptor.goniometer}
        self.sgl_edit = QLineEdit()
        self.sgu_edit = QLineEdit()
        for row, quantity_id, name, edit, text in (
            (4, "sample_lower_arc_deg", "sgl", self.sgl_edit,
             "Lower sample tilt arc sgl: turns about the horizontal axis "
             "perpendicular to the beam at A3 = 0 (stage x); rides on A3"),
            (5, "sample_upper_arc_deg", "sgu", self.sgu_edit,
             "Upper sample tilt arc sgu: turns about the beam axis at A3 = 0 "
             "(stage z); rides on sgl"),
        ):
            ax = travel.get(name)
            if ax is None or math.isinf(ax.lower):
                limits = "travel undocumented (unlimited)"
            else:
                limits = f"travel {ax.lower:g}° to {ax.upper:g}°"
            tip = f"{text}. Solved from Q/HKL; set it here for angle-mode scans; {limits}."
            setattr(self, f"{name}_label", angle_row(row, quantity_id, edit, tip)[0])

        # Row 6: shown while the angle fields do not match Q/HKL (the stage
        # refused the last Q/HKL edit); the controller sets and clears it.
        self.angles_stale_label = QLabel()
        self.angles_stale_label.setWordWrap(True)
        self.angles_stale_label.setStyleSheet("color: #c1121f;")
        self.angles_stale_label.hide()
        angles_layout.addWidget(self.angles_stale_label, 6, 0, 1, 2)

        pack_grid(angles_layout)
        self.add_block(angles_group)

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

        pack_grid(energies_layout)
        self.add_block(energies_group)

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

            pack_grid(collimations_layout)
            self.add_block(collimations_group)

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

            pack_grid(slits_layout)
            self.add_block(slits_group)


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

        self.add_block(crystals_group)

        # Focusing section (bending is generic TAS mono/ana state; stays static)
        focusing_group = CollapsibleGroup("Crystal Focusing (Absolute Radii, m)")
        focusing_layout = QGridLayout()
        focusing_layout.setSpacing(5)
        focusing_group.set_body_layout(focusing_layout)

        focusing_layout.addWidget(QLabel("rhm:"), 0, 0)
        self.rhm_edit = QLineEdit()
        self.rhm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rhm_edit, 0, 1)
        self.rhm_ideal_button = QPushButton("Ideal: --")
        self.rhm_ideal_button.setCheckable(True)
        self.rhm_ideal_button.setMaximumWidth(140)
        self.rhm_ideal_button.setToolTip("Set rhm to the calculated ideal value")
        focusing_layout.addWidget(self.rhm_ideal_button, 0, 2)

        # One radius per row, its Ideal readout beside it, so the group fits
        # one block: the monochromator's pair, then the analyser's.
        focusing_layout.addWidget(QLabel("rvm:"), 1, 0)
        self.rvm_edit = QLineEdit()
        self.rvm_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rvm_edit, 1, 1)
        self.rvm_ideal_button = QPushButton("Ideal: --")
        self.rvm_ideal_button.setCheckable(True)
        self.rvm_ideal_button.setMaximumWidth(140)
        self.rvm_ideal_button.setToolTip("Set rvm to the calculated ideal value")
        focusing_layout.addWidget(self.rvm_ideal_button, 1, 2)

        focusing_layout.addWidget(QLabel("rha:"), 2, 0)
        self.rha_edit = QLineEdit()
        self.rha_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rha_edit, 2, 1)
        self.rha_ideal_button = QPushButton("Ideal: --")
        self.rha_ideal_button.setCheckable(True)
        self.rha_ideal_button.setMaximumWidth(140)
        self.rha_ideal_button.setToolTip("Set rha to the calculated ideal value")
        focusing_layout.addWidget(self.rha_ideal_button, 2, 2)

        # Under rha, so the analyser's two axes read as a pair the way the
        # monochromator's rhm/rvm do. Enable state (editable/disabled) and
        # whether the Ideal button is offered at all are set per selected
        # analyser by the controller -- rva is the one axis whose declared
        # policy (fixed / no established focusing model / ordinary) actually
        # differs between crystals.
        focusing_layout.addWidget(QLabel("rva:"), 3, 0)
        self.rva_edit = QLineEdit()
        self.rva_edit.setMaximumWidth(70)
        focusing_layout.addWidget(self.rva_edit, 3, 1)
        self.rva_ideal_button = QPushButton("Ideal: --")
        self.rva_ideal_button.setCheckable(True)
        self.rva_ideal_button.setMaximumWidth(140)
        self.rva_ideal_button.setToolTip("Set rva to the calculated ideal value")
        focusing_layout.addWidget(self.rva_ideal_button, 3, 2)

        pack_grid(focusing_layout)
        self.add_block(focusing_group)
        self.collapsible_groups["instrument.focusing"] = focusing_group

        # Optional modules section (generated from descriptor.modules)
        self.module_widgets = {}
        if descriptor.modules:
            optics_group = CollapsibleGroup("Experimental Modules")
            optics_layout = QFormLayout()
            optics_group.set_body_layout(optics_layout)

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

            self.add_block(optics_group)
            self.collapsible_groups["instrument.modules"] = optics_group

        # Legacy attribute aliases for controller signal wiring (PUMA-specific
        # couplings guard with getattr, so absence is fine on other instruments).
        self.nmo_combo = self.module_widgets.get("nmo")
        self.v_selector_check = self.module_widgets.get("v_selector")

        # Source Control section (types + extra-param rows from descriptor)
        source_group = CollapsibleGroup("Source Control")
        source_layout = QFormLayout()
        source_group.set_body_layout(source_layout)

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

        self.add_block(source_group)
        self.collapsible_groups["instrument.source"] = source_group

        # Each folded block's summary follows its fields.
        for edit, button in self._focusing_axes().values():
            edit.textChanged.connect(self._refresh_focusing_summary)
            button.toggled.connect(self._refresh_focusing_summary)
        self._refresh_focusing_summary()
        for widget in self.module_widgets.values():
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._refresh_modules_summary)
            else:
                widget.toggled.connect(self._refresh_modules_summary)
        self._refresh_modules_summary()
        self.source_type_combo.currentIndexChanged.connect(self._refresh_source_summary)
        self.source_dE_edit.textChanged.connect(self._refresh_source_summary)
        self._refresh_source_summary()


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

    def _source_needs_dE(self):
        source_id = self.source_type_combo.currentData()
        for source_type in self.descriptor.source_types:
            if source_type.id == source_id:
                return "source_dE" in source_type.extra_params
        return False

    def _update_source_extra_visibility(self):
        needs_dE = self._source_needs_dE()
        self.source_dE_label.setVisible(needs_dE)
        self.source_dE_edit.setVisible(needs_dE)

    def _on_source_type_changed(self, _source_type):
        """Show/hide extra source fields based on the selected source type."""
        self._update_source_extra_visibility()

    def _focusing_axes(self):
        return {"rhm": (self.rhm_edit, self.rhm_ideal_button),
                "rvm": (self.rvm_edit, self.rvm_ideal_button),
                "rha": (self.rha_edit, self.rha_ideal_button),
                "rva": (self.rva_edit, self.rva_ideal_button)}

    # The folded blocks' summaries: the values the simulation will use, as typed.

    def _refresh_focusing_summary(self, *_):
        parts = []
        for name, (edit, ideal_button) in self._focusing_axes().items():
            locked = " ideal" if ideal_button.isChecked() else ""  # held at the ideal
            parts.append(f"{name} {edit.text() or 'empty'}{locked}")
        self.collapsible_groups["instrument.focusing"].set_summary(", ".join(parts))

    def _refresh_modules_summary(self, *_):
        group = self.collapsible_groups.get("instrument.modules")
        if group is None:
            return
        fitted = []
        for module in self.descriptor.modules:
            widget = self.module_widgets[module.id]
            if isinstance(widget, QComboBox):
                if widget.currentText().lower() != "none":  # a CHOICE's not-fitted option
                    fitted.append(f"{module.display_name}: {widget.currentText()}")
            elif widget.isChecked():
                fitted.append(module.display_name)
        group.set_summary(", ".join(fitted) if fitted else "none fitted")

    def _refresh_source_summary(self, *_):
        text = self.source_type_combo.currentText()
        if self._source_needs_dE():
            text += f", dE {self.source_dE_edit.text() or 'empty'} meV"
        self.collapsible_groups["instrument.source"].set_summary(text)
