"""Diagnostic Configuration Dialog for TAVI application.

Provides a dialog window to configure diagnostic monitors and settings for the
McStas simulation. The monitor list comes from the active instrument
descriptor's ``MonitorSpec`` entries (Phase 2 of
docs/CONFIGURABLE_INSTRUMENTS.md); the settings-dict keys are the monitor ids,
which are also the exact gate strings build() checks.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                QCheckBox, QGroupBox, QPushButton, QGridLayout,
                                QScrollArea, QWidget, QRadioButton, QButtonGroup)
from PySide6.QtCore import Qt

from tavi.instrument_helpers import WAVELENGTH_MONITORS_KEY


# App-level extras that are not instrument monitors ("Show Instrument Diagram"
# is controller behavior: it emits the instrument diagram after build()).
ADDITIONAL_OPTIONS = [
    "Show Instrument Diagram",
]


def _tag_button_label(tag):
    """'sample_region' -> 'Sample Region Only'."""
    return f"{tag.replace('_', ' ').title()} Only"


class DiagnosticConfigDialog(QDialog):
    """Dialog for configuring diagnostic monitor options."""

    def __init__(self, parent=None, current_settings=None, monitors=()):
        """Initialize the diagnostic configuration dialog.

        Args:
            parent: Parent widget
            current_settings: Dictionary of current diagnostic settings (option name -> bool)
            monitors: MonitorSpec tuple from the active instrument descriptor
        """
        super().__init__(parent)
        self.setWindowTitle("Diagnostic Options Configuration")
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)

        # Store current settings (copy to avoid mutation)
        self.current_settings = dict(current_settings) if current_settings else {}
        self.monitors = tuple(monitors)
        self.monitor_ids = [monitor.id for monitor in self.monitors]

        # Dictionary to store checkbox widgets
        self.checkboxes = {}

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        main_layout = QVBoxLayout(self)

        # Explanation text at the top
        explanation_text = (
            "Select the diagnostic monitors to enable during simulation.\n"
            "These settings will be applied when running in Diagnostic Mode.\n\n"
            "PSD: Position Sensitive Detector\n"
            "DSD: Divergence Sensitive Detector\n"
            "EMonitor: Energy Monitor\n"
            "LMonitor: Wavelength Monitor"
        )
        explanation_label = QLabel(explanation_text)
        explanation_label.setWordWrap(True)
        main_layout.addWidget(explanation_label)

        # Energy monitors record energy (E_monitor) or wavelength (L_monitor)
        choice_label = QLabel("Energy monitors record:")
        self.energy_radio = QRadioButton("Energy (EMonitor)")
        self.wavelength_radio = QRadioButton("Wavelength (LMonitor)")
        group = QButtonGroup(self)
        group.addButton(self.energy_radio)
        group.addButton(self.wavelength_radio)
        wavelength = bool(self.current_settings.get(WAVELENGTH_MONITORS_KEY, False))
        self.energy_radio.setChecked(not wavelength)
        self.wavelength_radio.setChecked(wavelength)
        tooltip = ("Converts the energy monitors between E and L monitors. Both record the same "
                   "neutron spectrum, binned in energy E or in wavelength λ = 9.045/√E Å.")
        choice_row = QHBoxLayout()
        for widget in (choice_label, self.energy_radio, self.wavelength_radio):
            widget.setToolTip(tooltip)
            choice_row.addWidget(widget)
        choice_row.addStretch()
        main_layout.addLayout(choice_row)

        # Create scrollable area for checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Group: Detector Monitors (from the descriptor)
        monitors_group = QGroupBox("Detector Monitors")
        monitors_layout = QGridLayout()
        monitors_layout.setSpacing(5)
        monitors_group.setLayout(monitors_layout)

        for i, monitor in enumerate(self.monitors):
            option = monitor.id
            checkbox = QCheckBox(self._monitor_label(monitor))
            checkbox.setChecked(self.current_settings.get(option, False))
            self.checkboxes[option] = checkbox

            # Arrange in 2 columns
            row = i // 2
            col = i % 2
            monitors_layout.addWidget(checkbox, row, col)

        self.wavelength_radio.toggled.connect(self._relabel_monitors)
        scroll_layout.addWidget(monitors_group)

        # Group: Additional Options
        additional_group = QGroupBox("Additional Options")
        additional_layout = QVBoxLayout()
        additional_group.setLayout(additional_layout)

        for option in ADDITIONAL_OPTIONS:
            checkbox = QCheckBox(option)
            checkbox.setChecked(self.current_settings.get(option, False))
            self.checkboxes[option] = checkbox
            additional_layout.addWidget(checkbox)

        # Add note about show_diagram
        note_label = QLabel(
            "<i>Note: 'Show Instrument Diagram' will display a McStas instrument diagram "
            "after each scan point completes. This can be useful for debugging but may "
            "slow down the simulation.</i>"
        )
        note_label.setWordWrap(True)
        additional_layout.addWidget(note_label)

        scroll_layout.addWidget(additional_group)

        # Quick selection buttons (tag groups come from MonitorSpec.tags)
        quick_group = QGroupBox("Quick Selection")
        quick_layout = QHBoxLayout()
        quick_group.setLayout(quick_layout)

        select_all_btn = QPushButton("Select All Monitors")
        select_all_btn.clicked.connect(self._select_all_monitors)
        quick_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All Monitors")
        deselect_all_btn.clicked.connect(self._deselect_all_monitors)
        quick_layout.addWidget(deselect_all_btn)

        for tag in self._monitor_tags():
            tag_btn = QPushButton(_tag_button_label(tag))
            tag_btn.clicked.connect(lambda _checked=False, t=tag: self._select_tag_only(t))
            quick_layout.addWidget(tag_btn)

        scroll_layout.addWidget(quick_group)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        # Buttons at the bottom
        button_layout = QHBoxLayout()

        save_btn = QPushButton("Save and Close")
        save_btn.clicked.connect(self.accept)
        button_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        main_layout.addLayout(button_layout)

    def _monitor_label(self, monitor):
        """Checkbox text; E_monitors read LMonitor while wavelength is chosen."""
        if monitor.component_type != "E_monitor" or not self.wavelength_radio.isChecked():
            return monitor.id
        return monitor.id.replace("EMonitor", "LMonitor").replace("Emonitor", "LMonitor")

    def _relabel_monitors(self):
        """Follow the energy/wavelength choice in the monitor checkbox texts."""
        for monitor in self.monitors:
            self.checkboxes[monitor.id].setText(self._monitor_label(monitor))

    def _monitor_tags(self):
        """Distinct tags in descriptor order."""
        tags = []
        for monitor in self.monitors:
            for tag in monitor.tags:
                if tag not in tags:
                    tags.append(tag)
        return tags

    def _select_all_monitors(self):
        """Select all detector monitor checkboxes."""
        for option in self.monitor_ids:
            self.checkboxes[option].setChecked(True)

    def _deselect_all_monitors(self):
        """Deselect all detector monitor checkboxes."""
        for option in self.monitor_ids:
            self.checkboxes[option].setChecked(False)

    def _select_tag_only(self, tag):
        """Select only the monitors carrying ``tag``; deselect the rest."""
        tagged = {monitor.id for monitor in self.monitors if tag in monitor.tags}
        for option in self.monitor_ids:
            self.checkboxes[option].setChecked(option in tagged)

    def get_settings(self):
        """Get the current diagnostic settings from the dialog.

        Returns:
            Dictionary mapping option names to boolean values
        """
        settings = {}
        for option, checkbox in self.checkboxes.items():
            settings[option] = checkbox.isChecked()
        settings[WAVELENGTH_MONITORS_KEY] = self.wavelength_radio.isChecked()
        return settings

    @staticmethod
    def get_default_settings(monitors=()):
        """Default diagnostic settings (all disabled) for the given monitors.

        Returns:
            Dictionary mapping all option names to False
        """
        settings = {monitor.id: False for monitor in monitors}
        for option in ADDITIONAL_OPTIONS:
            settings[option] = False
        settings[WAVELENGTH_MONITORS_KEY] = False
        return settings
