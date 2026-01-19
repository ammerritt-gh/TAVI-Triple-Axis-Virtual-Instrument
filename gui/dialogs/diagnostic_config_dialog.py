"""Diagnostic Configuration Dialog for TAVI application.

Provides a dialog window to configure diagnostic monitors and settings
for the McStas simulation.
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                QCheckBox, QGroupBox, QPushButton, QGridLayout,
                                QScrollArea, QWidget)
from PySide6.QtCore import Qt


# List of diagnostic options to display with checkboxes
# These correspond to the monitors available in the PUMA instrument definition
DIAGNOSTIC_OPTIONS = [
    "Source EMonitor",
    "Source PSD",
    "Source DSD",
    "Postcollimation PSD",
    "Postcollimation DSD",
    "Premono Emonitor",
    "Postmono Emonitor",
    "Pre-sample collimation PSD",
    "Sample PSD @ L2-0.5",
    "Sample PSD @ L2-0.3",
    "Sample PSD @ Sample",
    "Sample DSD @ Sample",
    "Sample EMonitor @ Sample",
    "Pre-analyzer collimation PSD",
    "Pre-analyzer EMonitor",
    "Pre-analyzer PSD",
    "Post-analyzer EMonitor",
    "Post-analyzer PSD",
    "Detector PSD",
]

# Additional diagnostic options not related to detectors
ADDITIONAL_OPTIONS = [
    "Show Instrument Diagram",  # Controls instrument.show_diagram() call
]


class DiagnosticConfigDialog(QDialog):
    """Dialog for configuring diagnostic monitor options."""
    
    def __init__(self, parent=None, current_settings=None):
        """Initialize the diagnostic configuration dialog.
        
        Args:
            parent: Parent widget
            current_settings: Dictionary of current diagnostic settings (option name -> bool)
        """
        super().__init__(parent)
        self.setWindowTitle("Diagnostic Options Configuration")
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)
        
        # Store current settings (copy to avoid mutation)
        self.current_settings = dict(current_settings) if current_settings else {}
        
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
            "EMonitor: Energy Monitor"
        )
        explanation_label = QLabel(explanation_text)
        explanation_label.setWordWrap(True)
        main_layout.addWidget(explanation_label)
        
        # Create scrollable area for checkboxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Group: Detector Monitors
        monitors_group = QGroupBox("Detector Monitors")
        monitors_layout = QGridLayout()
        monitors_layout.setSpacing(5)
        monitors_group.setLayout(monitors_layout)
        
        # Create checkboxes for each diagnostic option
        for i, option in enumerate(DIAGNOSTIC_OPTIONS):
            checkbox = QCheckBox(option)
            checkbox.setChecked(self.current_settings.get(option, False))
            self.checkboxes[option] = checkbox
            
            # Arrange in 2 columns
            row = i // 2
            col = i % 2
            monitors_layout.addWidget(checkbox, row, col)
        
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
        
        # Quick selection buttons
        quick_group = QGroupBox("Quick Selection")
        quick_layout = QHBoxLayout()
        quick_group.setLayout(quick_layout)
        
        select_all_btn = QPushButton("Select All Monitors")
        select_all_btn.clicked.connect(self._select_all_monitors)
        quick_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All Monitors")
        deselect_all_btn.clicked.connect(self._deselect_all_monitors)
        quick_layout.addWidget(deselect_all_btn)
        
        select_sample_btn = QPushButton("Sample Region Only")
        select_sample_btn.clicked.connect(self._select_sample_region)
        quick_layout.addWidget(select_sample_btn)
        
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
    
    def _select_all_monitors(self):
        """Select all detector monitor checkboxes."""
        for option in DIAGNOSTIC_OPTIONS:
            if option in self.checkboxes:
                self.checkboxes[option].setChecked(True)
    
    def _deselect_all_monitors(self):
        """Deselect all detector monitor checkboxes."""
        for option in DIAGNOSTIC_OPTIONS:
            if option in self.checkboxes:
                self.checkboxes[option].setChecked(False)
    
    def _select_sample_region(self):
        """Select only monitors in the sample region."""
        sample_monitors = [
            "Sample PSD @ L2-0.5",
            "Sample PSD @ L2-0.3",
            "Sample PSD @ Sample",
            "Sample DSD @ Sample",
            "Sample EMonitor @ Sample",
        ]
        for option in DIAGNOSTIC_OPTIONS:
            if option in self.checkboxes:
                self.checkboxes[option].setChecked(option in sample_monitors)
    
    def get_settings(self):
        """Get the current diagnostic settings from the dialog.
        
        Returns:
            Dictionary mapping option names to boolean values
        """
        settings = {}
        for option, checkbox in self.checkboxes.items():
            settings[option] = checkbox.isChecked()
        return settings
    
    @staticmethod
    def get_default_settings():
        """Get default diagnostic settings (all disabled).
        
        Returns:
            Dictionary mapping all option names to False
        """
        settings = {}
        for option in DIAGNOSTIC_OPTIONS:
            settings[option] = False
        for option in ADDITIONAL_OPTIONS:
            settings[option] = False
        return settings
