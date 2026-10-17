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
import logging
import math
import re
from dataclasses import dataclass

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QComboBox,
                                QCheckBox, QGroupBox, QFormLayout, QGridLayout,
                                QSizePolicy, QWidget)
from PySide6.QtCore import QSignalBlocker, Qt, Signal

from gui.docks.base_dock import (BaseDockWidget, CollapsibleGroup, NoScrollComboBox, pack_grid,
                                 COLLIMATION_OPEN_TOOLTIP, collimation_label)
from instruments import source
from instruments.descriptor import ModuleKind
from gui import metrics, theme
from tavi import quantities


def _half(text):
    """A 2θ field's text as its θ readout: half the value, same sign; '--' if not a number."""
    try:
        return f"{quantities.crystal_theta(float(text)):g}"
    except ValueError:
        return "--"


log = logging.getLogger(__name__)

# The scan boxes' refused state (UnifiedSimulationDock.STYLE_WARNING), for a source field that cannot be used.
SOURCE_INVALID_STYLE = "background-color: #ffcccc; border: 1px solid #cc0000;"
NO_PAIR_NOTE = "No active pair: at least one T and I must both be above 0."
ZERO_BAND_NOTE = "Flat band reaches 0 meV (Ei - dE <= 0): Run refuses this point."


def _parse_number(text):
    """A finite number from a field's text, or None."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _field_text(value):
    """A source field's text for ``value``: the shortest that parses back to the same number; '' for None."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    value = float(value)
    for digits in range(6, 18):
        text = f"{value:.{digits}g}"
        if float(text) == value:
            break
    return text


def _short_label(label):
    """A facility label without its power or tube detail: 'FRM2 thermal source, 20 MW' -> 'FRM2 thermal'."""
    return re.sub(r"\s+source$", "", re.sub(r"\s*\(.*$|,.*$", "", label))


FOCUSING_AXES = ("rhm", "rvm", "rha", "rva")

# What the Crystal Focusing block says about a radius that does not follow the ideal.
FOCUSING_HELP = ("Tracked radii follow the ideal at every scan point. Held radii (Track ideal "
                 "off, or a value typed) stay at their value for the whole scan. A radius "
                 "named in a scan command is scanned instead.")


def _sentence(text):
    """``text`` as a sentence: capital first, full stop last."""
    return text[:1].upper() + text[1:].rstrip(".") + "."


def _radius_cell(text):
    """A typed radius as a folded cell shows it: 'flat' at zero, 'empty' when blank."""
    if not text:
        return "empty"
    try:
        return "flat" if float(text) == 0 else f"{text} m"
    except ValueError:   # not a number: show it as typed
        return f"{text} m"


@dataclass
class _FocusingAxis:
    """What one radius row knows. ``track`` is the operator's choice (what is saved);
    the rest is pushed by the controller from the instrument and the scan commands."""

    track: bool = True
    fixed: str | None = None        # the reason the hardware fixes it, or None
    declared_fixed: bool = False    # fixed by the crystal itself, not by a fitted module
    no_model: str | None = None     # the reason no ideal exists for it, or None
    command: int | None = None      # the scan command number that steps it, or None
    ideal: float | None = None      # the ideal radius in metres, or None when there is none


class InstrumentDock(BaseDockWidget):
    """Dock widget for instrument configuration (descriptor-driven)."""

    # A click on a Track ideal box (the operator, never a render): axis, ticked.
    track_clicked = Signal(str, bool)
    # Some axis's track/hold choice changed (not a scan, fixed or no-model update).
    tracking_changed = Signal()
    # The operator changed the source: mode, entry, a T/I field or dE (never a programmatic set).
    source_changed = Signal()

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
            edit.setAccessibleName(q.label)
            label.setBuddy(edit)
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

        # One radius per row so the group fits one block: the monochromator's
        # pair, then the analyser's. Each row is the radius field, a Track ideal
        # box and the ideal radius. The box shows the effective mode and stores
        # nothing: whether the axis tracks is the dock's state (mode()). The mode
        # per selected analyser (fixed / no established focusing model / ordinary)
        # is pushed by the controller; rva is the one axis whose declared policy
        # actually differs between crystals.
        self._focus = {axis: _FocusingAxis() for axis in FOCUSING_AXES}
        self._focusing_rows = self._focusing_flag = None   # what the folded summary last showed
        for row, axis in enumerate(FOCUSING_AXES):
            focusing_layout.addWidget(QLabel(f"{axis}:"), 2 * row, 0)
            edit = QLineEdit()
            edit.setMaximumWidth(70)
            setattr(self, f"{axis}_edit", edit)
            focusing_layout.addWidget(edit, 2 * row, 1)
            check = QCheckBox("Track ideal")
            check.setObjectName(f"{axis}_track_check")
            check.setAccessibleName(f"Track ideal radius, {axis}")
            check.clicked.connect(lambda checked, axis=axis: self.track_clicked.emit(axis, checked))
            setattr(self, f"{axis}_track_check", check)
            focusing_layout.addWidget(check, 2 * row, 2)
            ideal = QLabel()
            ideal.setAccessibleName(f"Ideal radius, {axis}")
            setattr(self, f"{axis}_ideal_label", ideal)
            focusing_layout.addWidget(ideal, 2 * row, 3)

        pack_grid(focusing_layout)
        # Under each row, why it is not tracking (hidden while it tracks), then one
        # help line for the block. Both span the block, wrapped: nothing is clipped.
        for row, axis in enumerate(FOCUSING_AXES):
            status = QLabel()
            status.setWordWrap(True)
            status.setStyleSheet(f"color: {theme.NOTE_TEXT};")
            status.hide()
            setattr(self, f"{axis}_status_label", status)
            focusing_layout.addWidget(status, 2 * row + 1, 1, 1, 4)   # under its field
        self.focusing_help_label = QLabel(FOCUSING_HELP)
        self.focusing_help_label.setWordWrap(True)
        self.focusing_help_label.setStyleSheet(f"color: {theme.NOTE_TEXT}; padding-top: 3px;")
        focusing_layout.addWidget(self.focusing_help_label, 2 * len(FOCUSING_AXES), 0, 1, 5)
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

        self._build_source_section()

        # Each folded block's summary follows its fields.
        for axis in FOCUSING_AXES:
            edit = getattr(self, f"{axis}_edit")
            edit.textChanged.connect(lambda _text, axis=axis: self._render_focusing_axis(axis))
        for axis in FOCUSING_AXES:
            self._render_focusing_axis(axis)   # also draws the summary
        for widget in self.module_widgets.values():
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._refresh_modules_summary)
            else:
                widget.toggled.connect(self._refresh_modules_summary)
        self._refresh_modules_summary()

        # Canonical ID -> the field that shows it, for the scan-field marks.
        self._quantity_fields = {
            "mono_two_theta_deg": self.mtt_edit, "mono_theta_deg": self.mono_theta_edit,
            "sample_rotation_deg": self.omega_edit, "sample_two_theta_deg": self.stt_edit,
            "analyzer_two_theta_deg": self.att_edit,
            "analyzer_theta_deg": self.analyzer_theta_edit,
            "sample_lower_arc_deg": self.sgl_edit, "sample_upper_arc_deg": self.sgu_edit,
            "incident_wavevector_inv_angstrom": self.Ki_edit,
            "incident_energy_mev": self.Ei_edit,
            "final_wavevector_inv_angstrom": self.Kf_edit, "final_energy_mev": self.Ef_edit,
            "mono_horizontal_radius_m": self.rhm_edit, "mono_vertical_radius_m": self.rvm_edit,
            "analyzer_horizontal_radius_m": self.rha_edit,
            "analyzer_vertical_radius_m": self.rva_edit,
        }
        for slit in descriptor.slits:
            widgets = self.slit_widgets[slit.id]
            for qid, key in zip(quantities.slit_gap_ids(slit), ("width", "height")):
                self._quantity_fields[qid] = widgets[key]


    # ------------------------------------------------------------- accessors

    def field_for(self, quantity_id):
        """The field that shows ``quantity_id`` (a canonical ID, slit gaps included), or None."""
        return self._quantity_fields.get(quantity_id)

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

    # ------------------------------------------------------- Source Control state

    def source_settings(self):
        """The nine source values as the widgets show them, by canonical ID.

        A T/I or dE field that is not a finite number is None; the entry is the
        facility entry's ID whether or not its fields were edited.
        """
        values = {"moderator_mode": self.source_mode_combo.currentData(),
                  "moderator_profile": self.source_profile_combo.currentData()}
        for key, edit in self.source_ti_edits.items():
            values[key] = _parse_number(edit.text())
        values["flat_band_half_width_mev"] = _parse_number(self.flat_band_edit.text())
        return values

    def set_source_settings(self, values):
        """Show ``values`` (any of the nine IDs; None clears a field), without emitting source_changed."""
        unknown = set(values) - set(source.FIELD_IDS)
        if unknown:
            raise ValueError(f"unknown source setting(s): {', '.join(sorted(unknown))}")
        for key, table in (("moderator_mode", source.MODES), ("moderator_profile", source.PROFILES)):
            if key in values and values[key] not in table:
                raise ValueError(f"unknown {key} {values[key]!r}; choose one of {', '.join(table)}")
        self._source_filling = True
        try:
            for key, combo in (("moderator_mode", self.source_mode_combo),
                               ("moderator_profile", self.source_profile_combo)):
                if key in values:
                    combo.setCurrentIndex(combo.findData(values[key]))
            for key, edit in (*self.source_ti_edits.items(),
                              ("flat_band_half_width_mev", self.flat_band_edit)):
                if key in values:
                    edit.setText(_field_text(values[key]))
        finally:
            self._source_filling = False
        self._refresh_source()
        self._source_shown = self.source_settings()

    def set_source_preview_ei(self, ei_mev):
        """The Ei (meV) the preview marks; None (or anything but a positive number) marks nothing."""
        ei = _parse_number(str(ei_mev)) if ei_mev is not None else None
        ei = ei if ei is not None and ei > 0 else None
        if ei != self._source_ei:
            self._source_ei = ei
            self._update_source_note(self.source_settings())
            self._redraw_source_preview()

    def _update_source_note(self, values):
        """The red note under the fields: no active pair, and/or a flat band the run refuses (Ei - dE <= 0)."""
        notes = []
        if not source.active_pairs(values):
            notes.append(NO_PAIR_NOTE)
        dE, ei = values["flat_band_half_width_mev"], self._source_ei
        if values["moderator_mode"] == "flat_band" and dE is not None and dE > 0 and ei is not None and ei - dE <= 0:
            notes.append(ZERO_BAND_NOTE)
        self.source_note_label.setText(" ".join(notes))
        self.source_note_label.setVisible(bool(notes))

    def _fill_source_profile(self):
        """Put the shown entry's six values in the fields (callers set _source_filling)."""
        for key, value in source.profile_values(self.source_profile_combo.currentData()).items():
            self.source_ti_edits[key].setText(_field_text(value))

    def _on_source_profile_picked(self, *_):
        if self._source_filling:
            return
        self._source_filling = True
        try:
            self._fill_source_profile()
        finally:
            self._source_filling = False
        self._on_source_edit()

    def _on_source_edit(self, *_):
        """A user change: redraw, and tell the controller if the settings differ from the last shown."""
        if self._source_filling:
            return
        self._refresh_source()
        settings = self.source_settings()
        if settings != self._source_shown:
            self._source_shown = settings
            self.source_changed.emit()

    def _refresh_source(self):
        """Everything derived from the widgets: marks, note, dE row, entry text, summary, preview."""
        values = self.source_settings()
        flat = values["moderator_mode"] == "flat_band"
        modified = source.is_modified(values)
        combo = self.source_profile_combo
        for index, (_pid, profile) in enumerate(source.PROFILES.items()):
            combo.setItemText(index, profile.label)
        if modified:
            combo.setItemText(combo.currentIndex(), combo.currentText() + " (modified)")
        self.flat_band_label.setVisible(flat)
        self.flat_band_edit.setVisible(flat)
        for key, edit in self.source_ti_edits.items():
            v = values[key]
            edit.setStyleSheet(SOURCE_INVALID_STYLE if v is None or v < 0 else "")
        dE = values["flat_band_half_width_mev"]
        self.flat_band_edit.setStyleSheet(SOURCE_INVALID_STYLE if dE is None or dE <= 0 else "")
        self._update_source_note(values)
        short = _short_label(source.PROFILES[values["moderator_profile"]].label)
        text = short + (" (modified)" if modified else "")
        text += f", flat band ±{self.flat_band_edit.text() or 'empty'} meV" if flat else ", full spectrum"
        self.collapsible_groups["instrument.source"].set_summary(text)
        self._redraw_source_preview()

    def _redraw_source_preview(self):
        ax = self.source_ax
        try:
            self._draw_source_preview(ax)
        except Exception:   # the preview is a nicety: show an empty plot, say why in the log
            log.exception("source preview could not be drawn")
            ax.clear()
        self.source_canvas.draw_idle()

    def _draw_source_preview(self, ax):
        values = self.source_settings()
        flat = values["moderator_mode"] == "flat_band"
        dE, ei = values["flat_band_half_width_mev"], self._source_ei
        ax.clear()
        ax.set_xscale("log")
        ax.tick_params(labelsize=6, length=2)
        ax.yaxis.get_offset_text().set_fontsize(6)
        ax.set_xlabel("E (meV)", fontsize=6, labelpad=1)
        ax.set_ylabel("Φ (n/cm²/s/sr/meV)", fontsize=6, labelpad=1)

        # The spectrum's own span: from well below its coldest scale to well above its hottest.
        scales = [source.C_E * values[t_key] / source.A_OVER_T for t_key, _i in source.active_pairs(values)]
        lo, hi = (min(scales) / 50, max(scales) * 20) if scales else (None, None)
        if ei is not None:   # a margin of 1.5 either side of Ei and 4·Ei
            lo = ei / 1.5 if lo is None else min(lo, ei / 1.5)
            hi = 6 * ei if hi is None else max(hi, 6 * ei)
        if lo is None or not (0 < lo < hi < math.inf):
            lo, hi = 0.1, 100.0   # nothing to span: an empty plot, not an error
        ymax = 1.0
        if scales:
            energies = np.logspace(math.log10(lo), math.log10(hi), 240)
            numbers = {k: (v if v is not None else 0.0) for k, v in values.items() if k in source.TI_IDS}
            with np.errstate(all="ignore"):
                flux = source.flux_per_mev(energies, numbers)
            if np.all(np.isfinite(flux)) and flux.max() > 0:
                ax.plot(energies, flux, color=theme.COMMAND_COLORS[1], lw=1.2,
                        alpha=0.3 if flat else 1.0, label="moderator spectrum")
                ymax = 1.05 * flux.max()
        ax.set_ylim(0, ymax)
        ax.set_xlim(lo, hi)
        if ei is None:
            return
        edge = ax.get_xaxis_transform()   # x in data, y as a fraction of the plot height
        if flat and dE is not None and dE > 0:
            left, right = max(ei - dE, lo), ei + dE
            if right > left:
                ax.axvspan(left, right, color=theme.WARNING_FILL, alpha=0.5, lw=0,
                           label="flat band (unphysical)")
                # a caption above the axes: on the band it sat over the Ei label and line at the default width
                ax.set_title("shaded: flat band (unphysical)", loc="right", fontsize=6, pad=2, color=theme.NOTE_TEXT)
        for x, text, color, style in ((ei, "Ei", theme.COMMAND_COLORS[2], "-"),
                                      (4 * ei, "4·Ei (λ/2)", theme.DERIVED_OUTLINE, "--")):
            ax.axvline(x, color=color, ls=style, lw=1.2, label=text)
            ax.text(x, 0.97, text, transform=edge, rotation=90, ha="right", va="top",
                    fontsize=6, color=color)

    # ------------------------------------------------- Crystal Focusing state
    # Effective mode, in precedence order: fixed (the hardware fixes it), scanned
    # (a scan command steps it), no_model (driven, no ideal exists), track (the
    # choice is on), held. The Track ideal box renders the mode and stores nothing.

    def mode(self, axis):
        state = self._focus[axis]
        if state.fixed is not None:
            return "fixed"
        if state.command is not None:
            return "scanned"
        if state.no_model is not None:
            return "no_model"
        return "track" if state.track else "held"

    def choice(self, axis):
        """The operator's track/hold choice, kept while a scan, a fixed axis or a missing model overrides it."""
        return self._focus[axis].track

    def is_tracking(self, axis):
        """Whether a launch follows the ideal: the choice, unless the axis can never track."""
        state = self._focus[axis]
        return state.track and not (state.declared_fixed or state.no_model is not None)

    def set_choice(self, axis, track):
        state = self._focus[axis]
        changed = state.track != bool(track)
        state.track = bool(track)
        self._render_focusing_axis(axis)
        if changed:
            self.tracking_changed.emit()

    def set_ideal(self, axis, value):
        self._focus[axis].ideal = value
        self._render_focusing_axis(axis)

    def set_fixed(self, axis, reason, declared=False):
        """``reason`` None clears; ``declared`` marks a crystal-fixed axis (never tracks), not a module-fixed one."""
        state = self._focus[axis]
        state.fixed, state.declared_fixed = reason, bool(declared and reason is not None)
        self._render_focusing_axis(axis)

    def set_no_model(self, axis, reason):
        self._focus[axis].no_model = reason
        self._render_focusing_axis(axis)

    def set_scanned(self, commands):
        """{axis: scan command number} for every axis a command steps; the rest are cleared."""
        for axis in FOCUSING_AXES:
            self._focus[axis].command = commands.get(axis)
            self._render_focusing_axis(axis)

    def scanned_command(self, axis):
        return self._focus[axis].command

    def _render_focusing_axis(self, axis):
        """Draw one row from its state: the box ticked in track mode, enabled while it can be clicked."""
        state, mode = self._focus[axis], self.mode(axis)
        check = getattr(self, f"{axis}_track_check")
        with QSignalBlocker(check):
            check.setChecked(mode == "track")
            check.setEnabled(mode in ("track", "held"))
        label = getattr(self, f"{axis}_ideal_label")
        shown = None if mode == "fixed" else state.ideal   # a fixed radius is not an ideal
        label.setText("\u2014" if shown is None else "flat" if shown == 0 else f"{shown:.3f} m")
        status, tips = self._focusing_texts(axis)
        line = getattr(self, f"{axis}_status_label")
        line.setText(status)
        line.setVisible(bool(status))
        check.setToolTip(tips[0])
        getattr(self, f"{axis}_edit").setToolTip(tips[1])
        label.setToolTip(tips[2])
        check.setAccessibleDescription(status or "tracking the ideal")
        self._refresh_focusing_summary()

    def _focusing_texts(self, axis):
        """(status line, (checkbox, field, ideal readout tooltips)) for ``axis`` in its mode.

        The status line is empty while the axis tracks. Radii and differences are in metres.
        """
        state, mode = self._focus[axis], self.mode(axis)
        ideal = state.ideal
        if ideal is None:
            ideal_is = "There is no ideal radius for the present angles."
        elif ideal == 0:
            ideal_is = "The ideal is flat."
        else:
            ideal_is = f"The ideal is {ideal:.3f} m."
        follows = ("It follows the calculated ideal, recomputed whenever the angles change "
                   "and at every scan point.")
        holds = "It stays at the value in the field for the whole scan."
        readout = ("The ideal radius for the present angles and crystals, in metres, as TAVI "
                   "calculates it.")
        if ideal is None:
            readout = "No ideal radius can be calculated for the present angles."
        elif ideal == 0:
            readout = "The ideal radius for the present angles and crystals is flat (no bending)."
        if mode == "track":
            status = ""
            tips = (f"Track ideal is on. {follows} Untick it, or type a value in the field, to hold it.",
                    f"{follows} Type a value here to hold it instead.",
                    f"{readout} A tracking radius follows it at every scan point.")
        elif mode == "held":
            status = self._held_status(axis)
            tips = (f"Track ideal is off. {holds} {ideal_is} Tick Track ideal to follow it again.",
                    f"This radius stays at this value for the whole scan. {ideal_is} Tick Track ideal to follow it again.",
                    f"{readout} This radius is held, not following it.")
        elif mode == "scanned":
            status = (f"scanned by command {state.command}; remove {axis} from the command "
                      "to restore your setting")
            why = (f"Scan command {state.command} steps this radius point by point, "
                   "whatever Track ideal says.")
            back = (f"Your choice (Track ideal {'on' if state.track else 'off'}) applies again "
                    "when no scan command names this radius.")
            tips = (f"{why} The box is disabled meanwhile. {back}", f"{why} {back}",
                    f"{readout} This radius is scanned instead.")
        elif mode == "fixed":
            status = state.fixed if state.fixed.startswith("fixed") else f"fixed, {state.fixed}"
            why = f"{_sentence(state.fixed)} The hardware fixes this radius, so it cannot follow the ideal."
            tips = (why, f"{why} The field shows the fixed value.",
                    f"No ideal is shown: {why}")
        else:
            status = f"held: tracking unavailable, {state.no_model}"
            why = (f"Tracking is unavailable: {state.no_model}. The value typed in the field "
                   "is held for the whole scan.")
            tips = (why, why, f"No ideal radius exists: {state.no_model}.")
        return status, tips

    def _held_status(self, axis):
        """'held, 0.120 m above ideal': the field minus the ideal, in metres; or at the ideal."""
        ideal = self._focus[axis].ideal
        if ideal is None:
            return "held, no ideal for these angles"
        try:
            value = float(getattr(self, f"{axis}_edit").text())
        except ValueError:
            return "held, the field is not a number"
        if ideal == 0:
            return "held at the ideal" if value == 0 else "held, the ideal is flat"
        shown = f"{abs(value - ideal):.3f}"
        if shown == "0.000":
            return "held at the ideal"
        return f"held, {shown} m {'above' if value > ideal else 'below'} ideal"

    # The folded blocks' summaries: the values the simulation will use, as typed.

    def _refresh_focusing_summary(self, *_):
        """Two rows (monochromator, analyser) of 'rhm track 15.081 m' cells, and the not-tracking flag."""
        words = {"track": "track", "held": "held", "scanned": "scanned", "fixed": "fixed",
                 "no_model": "held"}   # no model: the typed value is held
        cells = {}
        for name in FOCUSING_AXES:
            text = getattr(self, f"{name}_edit").text()
            # the mode word before the value: a long value elides, never the mode
            cells[name] = f"{name} {words[self.mode(name)]} {_radius_cell(text)}"
        group = self.collapsible_groups["instrument.focusing"]
        rows = [[cells["rhm"], cells["rvm"]], [cells["rha"], cells["rva"]]]
        if rows != self._focusing_rows:
            self._focusing_rows = rows
            group.set_summary(rows)
        # Fixed axes are not counted: nothing the operator can do about them.
        loose = [a for a in FOCUSING_AXES if self.mode(a) in ("held", "scanned", "no_model")]
        flag = f"\u25cf {len(loose)} not tracking" if loose else ""
        tip = ("Not following the ideal radius. " + " ".join(self._not_tracking_note(a) for a in loose)
               if loose else "")
        if (flag, tip) != self._focusing_flag:
            self._focusing_flag = (flag, tip)
            group.set_flag(flag, tip)

    def _not_tracking_note(self, axis):
        """One sentence: why ``axis`` is not following the ideal, and what changes it."""
        mode = self.mode(axis)
        if mode == "scanned":   # the box is disabled: only its scan command changes it
            return (f"{axis} is scanned by command {self.scanned_command(axis)}; it returns to its own "
                    "setting when no command names it.")
        if mode == "no_model":
            return f"{axis} held: {self._focus[axis].no_model}, so it cannot track."
        return f"{axis} held: tick Track ideal in the open block to follow the ideal."

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

    def _build_source_section(self):
        """Source Control: mode, facility entry, six T/I fields, dE and the spectrum preview."""
        if self.descriptor.default_moderator_profile not in source.PROFILES:
            raise ValueError("InstrumentDock needs the descriptor's default_moderator_profile, got "
                             f"{self.descriptor.default_moderator_profile!r}")
        group = CollapsibleGroup("Source Control")
        layout = QGridLayout()
        layout.setSpacing(3)
        group.set_body_layout(layout)
        self._source_filling = False    # a programmatic fill is not an edit
        self._source_ei = None          # the preview's Ei, pushed by the controller

        self.source_mode_combo = NoScrollComboBox()
        self.source_mode_combo.setObjectName("source_mode_combo")
        for mode_id, label in source.MODES.items():
            self.source_mode_combo.addItem(label, mode_id)
        self.source_mode_combo.setToolTip(
            "Full spectrum: neutrons follow the moderator spectrum below.\n"
            "Flat band (unphysical): uniform in energy over Ei ± dE, for tests only.")
        self.source_profile_combo = NoScrollComboBox()
        self.source_profile_combo.setObjectName("source_profile_combo")
        for profile_id, profile in source.PROFILES.items():
            self.source_profile_combo.addItem(profile.label, profile_id)
        self.source_profile_combo.setToolTip(
            "Facility moderator entry. Picking one fills the six T/I fields; "
            "editing a field marks it (modified); picking it again restores it.")
        for combo in (self.source_mode_combo, self.source_profile_combo):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(18)
        layout.addWidget(QLabel("Mode:"), 0, 0)
        layout.addWidget(self.source_mode_combo, 0, 1, 1, 3)
        layout.addWidget(QLabel("Facility:"), 1, 0, 1, 4)
        layout.addWidget(self.source_profile_combo, 2, 0, 1, 4)  # full width: "<label> (modified)" is long

        self.source_ti_edits = {}
        for pair in range(3):
            for col, (key, text) in enumerate((
                    (source.TI_IDS[2 * pair], f"T{pair + 1} (K)"),
                    (source.TI_IDS[2 * pair + 1], f"I{pair + 1} (n/cm²/s/sr)"))):
                edit = QLineEdit()
                edit.setObjectName(f"source_{key}_edit")
                edit.setMaximumWidth(64)
                edit.setAccessibleName(text)
                label = QLabel(text)
                label.setBuddy(edit)
                label.setToolTip("A pair is active when T > 0 and I > 0; 0 leaves it unused.")
                layout.addWidget(label, 3 + pair, 2 * col)
                layout.addWidget(edit, 3 + pair, 2 * col + 1)
                self.source_ti_edits[key] = edit

        self.source_note_label = QLabel(NO_PAIR_NOTE)
        self.source_note_label.setWordWrap(True)
        self.source_note_label.setStyleSheet("color: #c1121f;")
        layout.addWidget(self.source_note_label, 6, 0, 1, 4)

        self.flat_band_label = QLabel("Flat-band half-width dE (meV):")
        self.flat_band_edit = QLineEdit(_field_text(source.DEFAULT_FLAT_BAND_DE))
        self.flat_band_edit.setObjectName("flat_band_edit")
        self.flat_band_edit.setMaximumWidth(64)
        self.flat_band_edit.setAccessibleName("Flat-band half-width dE (meV)")
        self.flat_band_label.setBuddy(self.flat_band_edit)
        layout.addWidget(self.flat_band_label, 7, 0, 1, 3)
        layout.addWidget(self.flat_band_edit, 7, 3)

        self.source_figure = Figure(figsize=(3.0, 1.9), dpi=100)
        self.source_figure.subplots_adjust(left=0.2, right=0.97, bottom=0.24, top=0.86)   # top: room for the band caption
        self.source_canvas = FigureCanvasQTAgg(self.source_figure)
        self.source_canvas.setFixedHeight(150)
        self.source_canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)  # its width is the block's, not the figure's
        self.source_ax = self.source_figure.add_subplot(111)
        layout.addWidget(self.source_canvas, 8, 0, 1, 4)

        # The initial entry, from the descriptor's default.
        self._source_filling = True
        self.source_profile_combo.setCurrentIndex(
            self.source_profile_combo.findData(self.descriptor.default_moderator_profile))
        self._fill_source_profile()
        self._source_filling = False
        self.source_mode_combo.currentIndexChanged.connect(self._on_source_edit)
        # activated fires on a re-pick of the shown entry (no index change), currentIndexChanged on
        # any other change; both firing on one pick is harmless, the second fill changes nothing.
        self.source_profile_combo.activated.connect(self._on_source_profile_picked)
        self.source_profile_combo.currentIndexChanged.connect(self._on_source_profile_picked)
        for edit in (*self.source_ti_edits.values(), self.flat_band_edit):
            edit.textChanged.connect(self._on_source_edit)

        self.add_block(group)
        self.collapsible_groups["instrument.source"] = group
        self._refresh_source()
        self._source_shown = self.source_settings()
