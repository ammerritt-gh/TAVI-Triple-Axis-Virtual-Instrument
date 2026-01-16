"""Display Dock for TAVI application - Real-time 1D/2D plot visualization."""
import os
import numpy as np

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                                QFileDialog, QWidget, QSizePolicy, QDialog,
                                QLineEdit, QCheckBox, QGroupBox, QGridLayout,
                                QDialogButtonBox, QScrollArea, QFrame, QSplitter)
from PySide6.QtCore import Qt, Slot

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.colors import ListedColormap
import matplotlib.patches as mpatches

from gui.docks.base_dock import BaseDockWidget


class SavePlotDialog(QDialog):
    """Dialog for saving plots with preview and customizable information panel."""
    
    def __init__(self, parent_dock, parent=None):
        super().__init__(parent)
        self.parent_dock = parent_dock
        self.setWindowTitle("Save Plot")
        self.setMinimumSize(900, 700)
        
        self._setup_ui()
        self._update_preview()
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        main_layout = QVBoxLayout(self)
        
        # Create splitter for preview and options
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Preview
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        
        preview_label = QLabel("<b>Preview</b>")
        preview_layout.addWidget(preview_label)
        
        # Preview figure
        self.preview_figure = Figure(figsize=(6, 5), dpi=100)
        self.preview_canvas = FigureCanvas(self.preview_figure)
        self.preview_canvas.setMinimumSize(400, 350)
        preview_layout.addWidget(self.preview_canvas, 1)
        
        splitter.addWidget(preview_widget)
        
        # Right side: Options (scrollable)
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.NoFrame)
        
        options_widget = QWidget()
        options_layout = QVBoxLayout(options_widget)
        options_layout.setContentsMargins(5, 5, 5, 5)
        
        # Save Location
        save_group = QGroupBox("Save Location")
        save_layout = QHBoxLayout(save_group)
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("Enter file path...")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        save_layout.addWidget(self.save_path_edit, 1)
        save_layout.addWidget(browse_btn)
        options_layout.addWidget(save_group)
        
        # Title Options
        title_group = QGroupBox("Title")
        title_layout = QVBoxLayout(title_group)
        title_row = QHBoxLayout()
        self.title_check = QCheckBox("Include title")
        self.title_check.setChecked(True)
        self.title_check.toggled.connect(self._on_option_changed)
        title_row.addWidget(self.title_check)
        title_layout.addLayout(title_row)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Enter plot title...")
        self.title_edit.textChanged.connect(self._on_option_changed)
        title_layout.addWidget(self.title_edit)
        options_layout.addWidget(title_group)
        
        # Information Panel Options
        info_group = QGroupBox("Information Panel")
        info_layout = QGridLayout(info_group)
        
        row = 0
        self.info_neutrons_check = QCheckBox("Number of neutrons")
        self.info_neutrons_check.setChecked(True)
        self.info_neutrons_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_neutrons_check, row, 0)
        
        self.info_ki_kf_check = QCheckBox("Ki/Kf fixed mode")
        self.info_ki_kf_check.setChecked(True)
        self.info_ki_kf_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_ki_kf_check, row, 1)
        
        row += 1
        self.info_fixed_e_check = QCheckBox("Fixed E")
        self.info_fixed_e_check.setChecked(True)
        self.info_fixed_e_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_fixed_e_check, row, 0)
        
        self.info_collimations_check = QCheckBox("Collimations")
        self.info_collimations_check.setChecked(True)
        self.info_collimations_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_collimations_check, row, 1)
        
        row += 1
        self.info_crystals_check = QCheckBox("Mono/Analyzer crystals")
        self.info_crystals_check.setChecked(True)
        self.info_crystals_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_crystals_check, row, 0)
        
        self.info_alignment_check = QCheckBox("Sample alignment offsets")
        self.info_alignment_check.setChecked(True)
        self.info_alignment_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_alignment_check, row, 1)
        
        row += 1
        self.info_q_hkl_check = QCheckBox("Q/HKL + ΔE")
        self.info_q_hkl_check.setChecked(True)
        self.info_q_hkl_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_q_hkl_check, row, 0)
        
        self.info_nmo_vs_check = QCheckBox("NMO / Velocity selector")
        self.info_nmo_vs_check.setChecked(True)
        self.info_nmo_vs_check.toggled.connect(self._on_option_changed)
        info_layout.addWidget(self.info_nmo_vs_check, row, 1)
        
        options_layout.addWidget(info_group)
        
        # Stretch to push buttons to bottom
        options_layout.addStretch()
        
        options_scroll.setWidget(options_widget)
        splitter.addWidget(options_scroll)
        
        # Set splitter sizes (60% preview, 40% options)
        splitter.setSizes([540, 360])
        
        main_layout.addWidget(splitter, 1)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        
        # Set default save path
        self._set_default_save_path()
        
        # Set default title
        self._set_default_title()
    
    def _set_default_save_path(self):
        """Set default save path to the scan data folder."""
        if self.parent_dock._data_folder and os.path.isdir(self.parent_dock._data_folder):
            default_path = os.path.join(self.parent_dock._data_folder, "scan_plot.png")
        else:
            default_path = "scan_plot.png"
        self.save_path_edit.setText(default_path)
    
    def _set_default_title(self):
        """Set default title based on scan type."""
        if self.parent_dock._mode == '1D':
            title = f"{self.parent_dock._variable_name_1} Scan"
        elif self.parent_dock._mode == '2D':
            title = f"{self.parent_dock._variable_name_1} vs {self.parent_dock._variable_name_2} Scan"
        else:
            title = "Scan Plot"
        self.title_edit.setText(title)
    
    def _on_browse(self):
        """Handle browse button click."""
        current_path = self.save_path_edit.text()
        if current_path:
            start_dir = os.path.dirname(current_path)
            start_name = os.path.basename(current_path)
        else:
            start_dir = ""
            start_name = "scan_plot.png"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", os.path.join(start_dir, start_name),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Image (*.svg);;All Files (*)"
        )
        
        if file_path:
            self.save_path_edit.setText(file_path)
    
    def _on_option_changed(self):
        """Handle option checkbox changes - update preview."""
        self._update_preview()
    
    def _update_preview(self):
        """Update the preview figure with current options."""
        self.preview_figure.clear()
        
        # Create subplot with space for info text
        if self._any_info_checked():
            self.preview_ax = self.preview_figure.add_axes([0.1, 0.25, 0.85, 0.65])
            self.preview_info_ax = self.preview_figure.add_axes([0.1, 0.02, 0.85, 0.18])
            self.preview_info_ax.axis('off')
        else:
            self.preview_ax = self.preview_figure.add_subplot(111)
        
        # Copy the main plot to preview
        self._copy_plot_to_preview()
        
        # Add title if enabled
        if self.title_check.isChecked() and self.title_edit.text():
            self.preview_ax.set_title(self.title_edit.text(), fontsize=11, fontweight='bold')
        
        # Add information panel
        if self._any_info_checked():
            self._add_info_panel()
        
        self.preview_figure.tight_layout()
        self.preview_canvas.draw()
    
    def _any_info_checked(self):
        """Check if any info option is enabled."""
        return any([
            self.info_neutrons_check.isChecked(),
            self.info_ki_kf_check.isChecked(),
            self.info_fixed_e_check.isChecked(),
            self.info_collimations_check.isChecked(),
            self.info_crystals_check.isChecked(),
            self.info_alignment_check.isChecked(),
            self.info_q_hkl_check.isChecked(),
            self.info_nmo_vs_check.isChecked()
        ])
    
    def _copy_plot_to_preview(self):
        """Copy the main display plot to the preview axes."""
        parent = self.parent_dock
        
        if parent._mode == '1D':
            self._copy_1d_plot()
        elif parent._mode == '2D':
            self._copy_2d_plot()
        else:
            self.preview_ax.text(0.5, 0.5, "No data", ha='center', va='center')
    
    def _copy_1d_plot(self):
        """Copy 1D plot to preview."""
        parent = self.parent_dock
        ax = self.preview_ax
        
        # Plot measured data
        measured_mask = parent._measured_mask & parent._valid_mask
        if np.any(measured_mask):
            x_measured = parent._scan_values_1[measured_mask]
            y_measured = parent._counts[measured_mask]
            sort_idx = np.argsort(x_measured)
            ax.plot(x_measured[sort_idx], y_measured[sort_idx], 'b-o', 
                   markersize=5, linewidth=1.5, label='Measured')
        
        # Mark impossible points
        impossible_x = parent._scan_values_1[~parent._valid_mask]
        if len(impossible_x) > 0:
            ax.scatter(impossible_x, np.zeros(len(impossible_x)), 
                      marker='x', color='black', s=40, linewidths=2, 
                      label='Impossible', zorder=5)
        
        # Set labels
        ax.set_xlabel(parent._get_axis_label(parent._variable_name_1))
        ax.set_ylabel('Counts')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper right', fontsize='small')
    
    def _copy_2d_plot(self):
        """Copy 2D plot to preview."""
        parent = self.parent_dock
        ax = self.preview_ax
        
        # Calculate extent
        dx = (parent._scan_values_1[-1] - parent._scan_values_1[0]) / (len(parent._scan_values_1) - 1) if len(parent._scan_values_1) > 1 else 1
        dy = (parent._scan_values_2[-1] - parent._scan_values_2[0]) / (len(parent._scan_values_2) - 1) if len(parent._scan_values_2) > 1 else 1
        
        extent = [
            parent._scan_values_1[0] - dx/2, parent._scan_values_1[-1] + dx/2,
            parent._scan_values_2[0] - dy/2, parent._scan_values_2[-1] + dy/2
        ]
        
        # Create heatmap
        im = ax.imshow(parent._counts, cmap='viridis', origin='lower',
                       extent=extent, aspect='auto', interpolation='nearest')
        
        # Add colorbar
        self.preview_figure.colorbar(im, ax=ax, label='Counts')
        
        # Mark impossible points
        for i, y_val in enumerate(parent._scan_values_2):
            for j, x_val in enumerate(parent._scan_values_1):
                if not parent._valid_mask[i, j]:
                    rect = Rectangle((x_val - dx/2, y_val - dy/2), dx, dy,
                                    facecolor='black', edgecolor='black')
                    ax.add_patch(rect)
        
        # Set labels
        ax.set_xlabel(parent._get_axis_label(parent._variable_name_1))
        ax.set_ylabel(parent._get_axis_label(parent._variable_name_2))
    
    def _add_info_panel(self):
        """Add information panel text to the preview."""
        info_lines = []
        meta = self.parent_dock._scan_metadata
        
        if self.info_neutrons_check.isChecked() and 'number_neutrons' in meta:
            n = meta['number_neutrons']
            # Format with scientific notation if large
            if n >= 1e6:
                info_lines.append(f"Neutrons: {n:.2e}")
            else:
                info_lines.append(f"Neutrons: {n:,}")
        
        if self.info_ki_kf_check.isChecked() and 'K_fixed' in meta:
            info_lines.append(f"Mode: {meta['K_fixed']}")
        
        if self.info_fixed_e_check.isChecked() and 'fixed_E' in meta:
            info_lines.append(f"Fixed E: {meta['fixed_E']:.3f} meV")
        
        if self.info_collimations_check.isChecked():
            coll_parts = []
            if 'alpha_1' in meta:
                coll_parts.append(f"α1={meta['alpha_1']}")
            if 'alpha_2' in meta:
                coll_parts.append(f"α2={meta['alpha_2']}")
            if 'alpha_3' in meta:
                coll_parts.append(f"α3={meta['alpha_3']}")
            if 'alpha_4' in meta:
                coll_parts.append(f"α4={meta['alpha_4']}")
            if coll_parts:
                info_lines.append("Coll: " + ", ".join(coll_parts))
        
        if self.info_crystals_check.isChecked():
            crystal_parts = []
            if 'monocris' in meta:
                crystal_parts.append(f"Mono={meta['monocris']}")
            if 'anacris' in meta:
                crystal_parts.append(f"Ana={meta['anacris']}")
            if crystal_parts:
                info_lines.append("Crystals: " + ", ".join(crystal_parts))
        
        if self.info_alignment_check.isChecked():
            align_parts = []
            if 'kappa' in meta and meta['kappa'] != 0:
                align_parts.append(f"κ={meta['kappa']:.2f}°")
            if 'psi' in meta and meta['psi'] != 0:
                align_parts.append(f"ψ={meta['psi']:.2f}°")
            if align_parts:
                info_lines.append("Alignment: " + ", ".join(align_parts))
            elif 'kappa' in meta or 'psi' in meta:
                info_lines.append("Alignment: none")
        
        if self.info_q_hkl_check.isChecked():
            if 'sample_frame_mode' in meta and meta['sample_frame_mode'] == 'HKL':
                if all(k in meta for k in ['H', 'K', 'L']):
                    info_lines.append(f"(H,K,L) = ({meta['H']:.3f}, {meta['K']:.3f}, {meta['L']:.3f})")
            else:
                if all(k in meta for k in ['qx', 'qy', 'qz']):
                    info_lines.append(f"Q = ({meta['qx']:.4f}, {meta['qy']:.4f}, {meta['qz']:.4f}) Å⁻¹")
            if 'deltaE' in meta:
                info_lines.append(f"ΔE = {meta['deltaE']:.3f} meV")
        
        if self.info_nmo_vs_check.isChecked():
            nmo_vs_parts = []
            if 'NMO_installed' in meta:
                nmo_vs_parts.append(f"NMO: {meta['NMO_installed']}")
            if 'V_selector_installed' in meta:
                vs_status = "On" if meta['V_selector_installed'] else "Off"
                nmo_vs_parts.append(f"VS: {vs_status}")
            if nmo_vs_parts:
                info_lines.append(" | ".join(nmo_vs_parts))
        
        # Display info text
        if info_lines:
            # Join lines - use two columns if many lines
            if len(info_lines) <= 4:
                info_text = "  |  ".join(info_lines)
            else:
                # Split into two rows
                mid = (len(info_lines) + 1) // 2
                row1 = "  |  ".join(info_lines[:mid])
                row2 = "  |  ".join(info_lines[mid:])
                info_text = row1 + "\n" + row2
            
            self.preview_info_ax.text(0.5, 0.5, info_text, ha='center', va='center',
                                       fontsize=8, transform=self.preview_info_ax.transAxes,
                                       bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.3))
    
    def _on_save(self):
        """Handle save button click."""
        file_path = self.save_path_edit.text()
        if not file_path:
            return
        
        try:
            # Create a new figure for saving (to preserve the preview settings)
            save_fig = Figure(figsize=(8, 6), dpi=150)
            
            # Create axes with same layout as preview
            if self._any_info_checked():
                save_ax = save_fig.add_axes([0.1, 0.22, 0.85, 0.68])
                save_info_ax = save_fig.add_axes([0.1, 0.02, 0.85, 0.15])
                save_info_ax.axis('off')
            else:
                save_ax = save_fig.add_subplot(111)
            
            # Copy plot to save figure
            self._copy_plot_to_save_figure(save_ax, save_fig)
            
            # Add title if enabled
            if self.title_check.isChecked() and self.title_edit.text():
                save_ax.set_title(self.title_edit.text(), fontsize=12, fontweight='bold')
            
            # Add information panel
            if self._any_info_checked():
                self._add_info_panel_to_figure(save_info_ax)
            
            save_fig.tight_layout()
            save_fig.savefig(file_path, dpi=150, bbox_inches='tight')
            
            self.parent_dock.status_label.setText(f"Plot saved to: {os.path.basename(file_path)}")
            self.accept()
            
        except Exception as e:
            self.parent_dock.status_label.setText(f"Error saving plot: {str(e)}")
    
    def _copy_plot_to_save_figure(self, ax, fig):
        """Copy the plot to the save figure's axes."""
        parent = self.parent_dock
        
        if parent._mode == '1D':
            # Plot measured data
            measured_mask = parent._measured_mask & parent._valid_mask
            if np.any(measured_mask):
                x_measured = parent._scan_values_1[measured_mask]
                y_measured = parent._counts[measured_mask]
                sort_idx = np.argsort(x_measured)
                ax.plot(x_measured[sort_idx], y_measured[sort_idx], 'b-o', 
                       markersize=5, linewidth=1.5, label='Measured')
            
            # Mark impossible points
            impossible_x = parent._scan_values_1[~parent._valid_mask]
            if len(impossible_x) > 0:
                ax.scatter(impossible_x, np.zeros(len(impossible_x)), 
                          marker='x', color='black', s=40, linewidths=2, 
                          label='Impossible', zorder=5)
            
            ax.set_xlabel(parent._get_axis_label(parent._variable_name_1))
            ax.set_ylabel('Counts')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right', fontsize='small')
            
        elif parent._mode == '2D':
            # Calculate extent
            dx = (parent._scan_values_1[-1] - parent._scan_values_1[0]) / (len(parent._scan_values_1) - 1) if len(parent._scan_values_1) > 1 else 1
            dy = (parent._scan_values_2[-1] - parent._scan_values_2[0]) / (len(parent._scan_values_2) - 1) if len(parent._scan_values_2) > 1 else 1
            
            extent = [
                parent._scan_values_1[0] - dx/2, parent._scan_values_1[-1] + dx/2,
                parent._scan_values_2[0] - dy/2, parent._scan_values_2[-1] + dy/2
            ]
            
            # Create heatmap
            im = ax.imshow(parent._counts, cmap='viridis', origin='lower',
                           extent=extent, aspect='auto', interpolation='nearest')
            
            fig.colorbar(im, ax=ax, label='Counts')
            
            # Mark impossible points
            for i, y_val in enumerate(parent._scan_values_2):
                for j, x_val in enumerate(parent._scan_values_1):
                    if not parent._valid_mask[i, j]:
                        rect = Rectangle((x_val - dx/2, y_val - dy/2), dx, dy,
                                        facecolor='black', edgecolor='black')
                        ax.add_patch(rect)
            
            ax.set_xlabel(parent._get_axis_label(parent._variable_name_1))
            ax.set_ylabel(parent._get_axis_label(parent._variable_name_2))
    
    def _add_info_panel_to_figure(self, ax):
        """Add information panel to the save figure."""
        info_lines = []
        meta = self.parent_dock._scan_metadata
        
        if self.info_neutrons_check.isChecked() and 'number_neutrons' in meta:
            n = meta['number_neutrons']
            if n >= 1e6:
                info_lines.append(f"Neutrons: {n:.2e}")
            else:
                info_lines.append(f"Neutrons: {n:,}")
        
        if self.info_ki_kf_check.isChecked() and 'K_fixed' in meta:
            info_lines.append(f"Mode: {meta['K_fixed']}")
        
        if self.info_fixed_e_check.isChecked() and 'fixed_E' in meta:
            info_lines.append(f"Fixed E: {meta['fixed_E']:.3f} meV")
        
        if self.info_collimations_check.isChecked():
            coll_parts = []
            if 'alpha_1' in meta:
                coll_parts.append(f"α1={meta['alpha_1']}")
            if 'alpha_2' in meta:
                coll_parts.append(f"α2={meta['alpha_2']}")
            if 'alpha_3' in meta:
                coll_parts.append(f"α3={meta['alpha_3']}")
            if 'alpha_4' in meta:
                coll_parts.append(f"α4={meta['alpha_4']}")
            if coll_parts:
                info_lines.append("Coll: " + ", ".join(coll_parts))
        
        if self.info_crystals_check.isChecked():
            crystal_parts = []
            if 'monocris' in meta:
                crystal_parts.append(f"Mono={meta['monocris']}")
            if 'anacris' in meta:
                crystal_parts.append(f"Ana={meta['anacris']}")
            if crystal_parts:
                info_lines.append("Crystals: " + ", ".join(crystal_parts))
        
        if self.info_alignment_check.isChecked():
            align_parts = []
            if 'kappa' in meta and meta['kappa'] != 0:
                align_parts.append(f"κ={meta['kappa']:.2f}°")
            if 'psi' in meta and meta['psi'] != 0:
                align_parts.append(f"ψ={meta['psi']:.2f}°")
            if align_parts:
                info_lines.append("Alignment: " + ", ".join(align_parts))
            elif 'kappa' in meta or 'psi' in meta:
                info_lines.append("Alignment: none")
        
        if self.info_q_hkl_check.isChecked():
            if 'sample_frame_mode' in meta and meta['sample_frame_mode'] == 'HKL':
                if all(k in meta for k in ['H', 'K', 'L']):
                    info_lines.append(f"(H,K,L) = ({meta['H']:.3f}, {meta['K']:.3f}, {meta['L']:.3f})")
            else:
                if all(k in meta for k in ['qx', 'qy', 'qz']):
                    info_lines.append(f"Q = ({meta['qx']:.4f}, {meta['qy']:.4f}, {meta['qz']:.4f}) Å⁻¹")
            if 'deltaE' in meta:
                info_lines.append(f"ΔE = {meta['deltaE']:.3f} meV")
        
        if self.info_nmo_vs_check.isChecked():
            nmo_vs_parts = []
            if 'NMO_installed' in meta:
                nmo_vs_parts.append(f"NMO: {meta['NMO_installed']}")
            if 'V_selector_installed' in meta:
                vs_status = "On" if meta['V_selector_installed'] else "Off"
                nmo_vs_parts.append(f"VS: {vs_status}")
            if nmo_vs_parts:
                info_lines.append(" | ".join(nmo_vs_parts))
        
        if info_lines:
            if len(info_lines) <= 4:
                info_text = "  |  ".join(info_lines)
            else:
                mid = (len(info_lines) + 1) // 2
                row1 = "  |  ".join(info_lines[:mid])
                row2 = "  |  ".join(info_lines[mid:])
                info_text = row1 + "\n" + row2
            
            ax.text(0.5, 0.5, info_text, ha='center', va='center',
                    fontsize=9, transform=ax.transAxes,
                    bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.3))


class DisplayDock(BaseDockWidget):
    """Dock widget for real-time plot display during scans."""
    
    # Constants for plot states
    STATE_UNMEASURED = 0  # White - to be measured
    STATE_IMPOSSIBLE = -1  # Black - cannot be measured
    STATE_MEASURED = 1  # Colored by value
    
    def __init__(self, parent=None):
        super().__init__("Display", parent, use_scroll_area=False)
        self.setObjectName("DisplayDock")
        
        # Get the content layout from base class
        main_layout = self.content_layout
        
        # Initialize plot state
        self._mode = None  # '1D' or '2D'
        self._scan_data = None
        self._scan_values_1 = None  # X-axis values
        self._scan_values_2 = None  # Y-axis values (2D only)
        self._variable_name_1 = ""
        self._variable_name_2 = ""
        self._counts = None  # 1D: array, 2D: 2D grid
        self._valid_mask = None  # Which points are valid (not impossible)
        self._measured_mask = None  # Which points have been measured
        self._current_index = -1  # Current scan point being measured
        self._data_folder = None  # Path to scan data folder
        self._scan_metadata = {}  # Store scan metadata for info panel
        self._colorbar = None  # Reference to colorbar for proper cleanup
        
        # Create matplotlib figure and canvas
        self.figure = Figure(figsize=(6, 5), dpi=100)
        self.figure.set_tight_layout(True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Create navigation toolbar
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # Create axes
        self.ax = self.figure.add_subplot(111)
        
        # Status label
        self.status_label = QLabel("No scan data")
        self.status_label.setAlignment(Qt.AlignCenter)
        
        # Save button
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save Plot...")
        self.save_button.clicked.connect(self._on_save_plot)
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addStretch()
        
        # Add widgets to layout
        main_layout.addWidget(self.toolbar)
        main_layout.addWidget(self.canvas, 1)  # Give canvas stretch factor
        main_layout.addWidget(self.status_label)
        main_layout.addLayout(button_layout)
        
        # Initialize empty plot
        self._show_empty_plot()
    
    def _show_empty_plot(self):
        """Show an empty plot with a message."""
        self.ax.clear()
        self.ax.text(0.5, 0.5, "No scan data\nRun a scan or load data to display",
                     ha='center', va='center', transform=self.ax.transAxes,
                     fontsize=12, color='gray')
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw()
        self.status_label.setText("No scan data")
    
    def _get_axis_label(self, variable_name):
        """Get proper axis label with units for a variable."""
        if variable_name in ['qx', 'qy', 'qz']:
            return f'{variable_name} (Å⁻¹)'
        elif variable_name == 'deltaE':
            return 'ΔE (meV)'
        elif variable_name in ['H', 'K', 'L']:
            return f'{variable_name} (r.l.u.)'
        elif variable_name in ['omega', 'chi', 'kappa', 'psi']:
            return f'{variable_name} (°)'
        elif variable_name in ['mtt', 'stt', 'att', 'A1', 'A2', 'A3', 'A4']:
            return f'{variable_name} (°)'
        elif variable_name in ['rhm', 'rvm', 'rha', 'rva']:
            return f'{variable_name} (m)'
        else:
            return variable_name
    
    @Slot(str, list, list, str, str, list)
    def initialize_scan(self, mode, values_1, valid_mask_1, var_name_1, 
                        var_name_2="", values_2=None, valid_mask_2d=None):
        """Initialize the display for a new scan.
        
        Args:
            mode: '1D' or '2D'
            values_1: List of scan values for first variable (x-axis)
            valid_mask_1: For 1D - list of bools indicating if point is reachable
                         For 2D - not used directly (use valid_mask_2d)
            var_name_1: Name of first scan variable
            var_name_2: Name of second scan variable (2D only)
            values_2: List of scan values for second variable (2D only, y-axis)
            valid_mask_2d: For 2D - 2D array of bools (shape: len(values_2) x len(values_1))
        """
        self._mode = mode
        self._variable_name_1 = var_name_1
        self._variable_name_2 = var_name_2
        self._scan_values_1 = np.array(values_1)
        self._current_index = -1
        
        if mode == '1D':
            n_points = len(values_1)
            self._counts = np.full(n_points, np.nan)
            self._valid_mask = np.array(valid_mask_1, dtype=bool)
            self._measured_mask = np.zeros(n_points, dtype=bool)
            self._setup_1d_plot()
        else:  # 2D
            self._scan_values_2 = np.array(values_2)
            n_x = len(values_1)
            n_y = len(values_2)
            self._counts = np.full((n_y, n_x), np.nan)
            if valid_mask_2d is not None:
                self._valid_mask = np.array(valid_mask_2d, dtype=bool)
            else:
                self._valid_mask = np.ones((n_y, n_x), dtype=bool)
            self._measured_mask = np.zeros((n_y, n_x), dtype=bool)
            self._setup_2d_plot()
        
        self.status_label.setText(f"Scan initialized: 0/{self._get_total_valid_points()} points")
        self.canvas.draw()
    
    def _get_total_valid_points(self):
        """Get total number of valid (reachable) points."""
        if self._valid_mask is None:
            return 0
        return int(np.sum(self._valid_mask))
    
    def _get_measured_count(self):
        """Get number of measured points."""
        if self._measured_mask is None:
            return 0
        return int(np.sum(self._measured_mask))
    
    def _setup_1d_plot(self):
        """Set up the 1D line plot."""
        self.ax.clear()
        
        # Plot the valid points that haven't been measured yet (unmeasured)
        valid_unmeasured = self._valid_mask & ~self._measured_mask
        
        # Create the line plot with empty data initially
        self._line, = self.ax.plot([], [], 'b-o', markersize=6, linewidth=1.5, label='Measured')
        
        # Mark impossible points with black X markers at y=0
        impossible_x = self._scan_values_1[~self._valid_mask]
        if len(impossible_x) > 0:
            self.ax.scatter(impossible_x, np.zeros(len(impossible_x)), 
                          marker='x', color='black', s=50, linewidths=2, 
                          label='Impossible', zorder=5)
        
        # Mark valid unmeasured points with hollow circles at y=0
        unmeasured_x = self._scan_values_1[valid_unmeasured]
        if len(unmeasured_x) > 0:
            self._unmeasured_scatter = self.ax.scatter(unmeasured_x, np.zeros(len(unmeasured_x)),
                                                       marker='o', facecolors='none', 
                                                       edgecolors='gray', s=50, linewidths=1.5,
                                                       label='Unmeasured', zorder=4)
        else:
            self._unmeasured_scatter = None
        
        # Current scan marker (vertical dashed line)
        self._current_line = self.ax.axvline(x=self._scan_values_1[0], color='red', 
                                             linestyle='--', linewidth=2, alpha=0.7,
                                             label='Current', visible=False)
        
        # Set axis labels
        self.ax.set_xlabel(self._get_axis_label(self._variable_name_1))
        self.ax.set_ylabel('Counts')
        
        # Set x-axis limits to show full scan range
        x_margin = (self._scan_values_1[-1] - self._scan_values_1[0]) * 0.05
        self.ax.set_xlim(self._scan_values_1[0] - x_margin, self._scan_values_1[-1] + x_margin)
        
        # Y-axis will auto-scale as data comes in
        self.ax.set_ylim(0, 1)  # Initial placeholder
        
        self.ax.legend(loc='upper right', fontsize='small')
        self.ax.grid(True, alpha=0.3)
    
    def _setup_2d_plot(self):
        """Set up the 2D heatmap plot."""
        # Remove existing colorbar if present to prevent duplicates
        if self._colorbar is not None:
            try:
                self._colorbar.remove()
            except (ValueError, AttributeError):
                pass
            self._colorbar = None
        
        self.ax.clear()
        
        # Create custom colormap: NaN -> white, valid data -> viridis
        # We'll use a masked array approach
        
        # Calculate extent for imshow
        dx = (self._scan_values_1[-1] - self._scan_values_1[0]) / (len(self._scan_values_1) - 1) if len(self._scan_values_1) > 1 else 1
        dy = (self._scan_values_2[-1] - self._scan_values_2[0]) / (len(self._scan_values_2) - 1) if len(self._scan_values_2) > 1 else 1
        
        extent = [
            self._scan_values_1[0] - dx/2, self._scan_values_1[-1] + dx/2,
            self._scan_values_2[0] - dy/2, self._scan_values_2[-1] + dy/2
        ]
        
        # Create display data - start with all white (NaN for unmeasured)
        display_data = np.full_like(self._counts, np.nan)
        
        # Create the heatmap
        self._heatmap = self.ax.imshow(display_data, cmap='viridis', origin='lower',
                                        extent=extent, aspect='auto', interpolation='nearest')
        
        # Add colorbar
        self._colorbar = self.figure.colorbar(self._heatmap, ax=self.ax, label='Counts')
        
        # Mark impossible points with black hatching
        self._impossible_patches = []
        for i, y_val in enumerate(self._scan_values_2):
            for j, x_val in enumerate(self._scan_values_1):
                if not self._valid_mask[i, j]:
                    # Draw a black rectangle for impossible points
                    rect = Rectangle((x_val - dx/2, y_val - dy/2), dx, dy,
                                    facecolor='black', edgecolor='black')
                    self.ax.add_patch(rect)
                    self._impossible_patches.append(rect)
        
        # Current scan marker (rectangle with hatching)
        self._current_rect = Rectangle((0, 0), dx, dy, fill=False, 
                                       edgecolor='red', linewidth=2,
                                       linestyle='--', visible=False)
        self.ax.add_patch(self._current_rect)
        
        # Set axis labels
        self.ax.set_xlabel(self._get_axis_label(self._variable_name_1))
        self.ax.set_ylabel(self._get_axis_label(self._variable_name_2))
        
        # Add legend for impossible points
        impossible_patch = mpatches.Patch(facecolor='black', edgecolor='black', label='Impossible')
        unmeasured_patch = mpatches.Patch(facecolor='white', edgecolor='gray', label='Unmeasured')
        current_patch = mpatches.Patch(fill=False, edgecolor='red', linestyle='--', 
                                       linewidth=2, label='Current')
        self.ax.legend(handles=[impossible_patch, unmeasured_patch, current_patch],
                      loc='upper right', fontsize='small')
    
    @Slot(int, float)
    def update_1d_point(self, index, counts):
        """Update a single point in 1D scan.
        
        Args:
            index: Index into the scan values array
            counts: Measured counts at this point
        """
        if self._mode != '1D' or self._counts is None:
            return
        
        if 0 <= index < len(self._counts):
            self._counts[index] = counts
            self._measured_mask[index] = True
            self._current_index = index
            self._update_1d_display()
    
    @Slot(int, int, float)
    def update_2d_point(self, idx_x, idx_y, counts):
        """Update a single point in 2D scan.
        
        Args:
            idx_x: Index into scan_values_1 (x-axis)
            idx_y: Index into scan_values_2 (y-axis)
            counts: Measured counts at this point
        """
        if self._mode != '2D' or self._counts is None:
            return
        
        if 0 <= idx_y < self._counts.shape[0] and 0 <= idx_x < self._counts.shape[1]:
            self._counts[idx_y, idx_x] = counts
            self._measured_mask[idx_y, idx_x] = True
            self._current_index = (idx_x, idx_y)
            self._update_2d_display()
    
    @Slot(int)
    def set_current_scan_index(self, index):
        """Set the current scan index (for showing progress marker).
        
        For 1D: index is a single integer
        For 2D: index is converted to (x_idx, y_idx) based on scan order
        """
        self._current_index = index
        if self._mode == '1D':
            self._update_current_marker_1d(index)
        # For 2D, the marker is updated in update_2d_point
    
    @Slot(int, int)
    def set_current_scan_index_2d(self, idx_x, idx_y):
        """Set the current scan index for 2D scan."""
        self._current_index = (idx_x, idx_y)
        self._update_current_marker_2d(idx_x, idx_y)
    
    def _update_1d_display(self):
        """Update the 1D plot display."""
        if self._counts is None:
            return
        
        # Get measured data
        measured_mask = self._measured_mask & self._valid_mask
        x_measured = self._scan_values_1[measured_mask]
        y_measured = self._counts[measured_mask]
        
        # Sort by x value for proper line plotting
        if len(x_measured) > 0:
            sort_idx = np.argsort(x_measured)
            x_measured = x_measured[sort_idx]
            y_measured = y_measured[sort_idx]
            
            # Update line data
            self._line.set_data(x_measured, y_measured)
            
            # Update y-axis limits
            y_max = np.nanmax(y_measured) if len(y_measured) > 0 else 1
            y_margin = y_max * 0.1 if y_max > 0 else 0.1
            self.ax.set_ylim(0, y_max + y_margin)
        
        # Update unmeasured points scatter
        valid_unmeasured = self._valid_mask & ~self._measured_mask
        if self._unmeasured_scatter is not None:
            unmeasured_x = self._scan_values_1[valid_unmeasured]
            if len(unmeasured_x) > 0:
                self._unmeasured_scatter.set_offsets(np.column_stack([unmeasured_x, np.zeros(len(unmeasured_x))]))
            else:
                self._unmeasured_scatter.set_offsets(np.empty((0, 2)))
        
        # Update current marker
        if isinstance(self._current_index, int) and 0 <= self._current_index < len(self._scan_values_1):
            self._update_current_marker_1d(self._current_index)
        
        # Update status
        self.status_label.setText(f"Scan progress: {self._get_measured_count()}/{self._get_total_valid_points()} points")
        
        self.canvas.draw_idle()
    
    def _update_2d_display(self):
        """Update the 2D heatmap display."""
        if self._counts is None:
            return
        
        # Update heatmap data
        self._heatmap.set_data(self._counts)
        
        # Update color scale based on measured data
        valid_counts = self._counts[self._measured_mask & self._valid_mask]
        if len(valid_counts) > 0:
            vmin = np.nanmin(valid_counts)
            vmax = np.nanmax(valid_counts)
            if vmin == vmax:
                vmax = vmin + 1
            self._heatmap.set_clim(vmin, vmax)
        
        # Update current marker
        if isinstance(self._current_index, tuple):
            idx_x, idx_y = self._current_index
            self._update_current_marker_2d(idx_x, idx_y)
        
        # Update status
        self.status_label.setText(f"Scan progress: {self._get_measured_count()}/{self._get_total_valid_points()} points")
        
        self.canvas.draw_idle()
    
    def _update_current_marker_1d(self, index):
        """Update the current scan marker for 1D plot."""
        if not hasattr(self, '_current_line') or self._scan_values_1 is None:
            return
        
        if 0 <= index < len(self._scan_values_1):
            self._current_line.set_xdata([self._scan_values_1[index], self._scan_values_1[index]])
            self._current_line.set_visible(True)
        else:
            self._current_line.set_visible(False)
        
        self.canvas.draw_idle()
    
    def _update_current_marker_2d(self, idx_x, idx_y):
        """Update the current scan marker for 2D plot."""
        if not hasattr(self, '_current_rect') or self._scan_values_1 is None or self._scan_values_2 is None:
            return
        
        if 0 <= idx_x < len(self._scan_values_1) and 0 <= idx_y < len(self._scan_values_2):
            dx = (self._scan_values_1[-1] - self._scan_values_1[0]) / (len(self._scan_values_1) - 1) if len(self._scan_values_1) > 1 else 1
            dy = (self._scan_values_2[-1] - self._scan_values_2[0]) / (len(self._scan_values_2) - 1) if len(self._scan_values_2) > 1 else 1
            
            x_val = self._scan_values_1[idx_x]
            y_val = self._scan_values_2[idx_y]
            
            self._current_rect.set_xy((x_val - dx/2, y_val - dy/2))
            self._current_rect.set_width(dx)
            self._current_rect.set_height(dy)
            self._current_rect.set_visible(True)
        else:
            self._current_rect.set_visible(False)
        
        self.canvas.draw_idle()
    
    @Slot()
    def scan_complete(self):
        """Called when scan is complete - hide current marker."""
        self._current_index = -1
        
        if self._mode == '1D' and hasattr(self, '_current_line'):
            self._current_line.set_visible(False)
        elif self._mode == '2D' and hasattr(self, '_current_rect'):
            self._current_rect.set_visible(False)
        
        total = self._get_total_valid_points()
        measured = self._get_measured_count()
        self.status_label.setText(f"Scan complete: {measured}/{total} points")
        
        self.canvas.draw_idle()
    
    @Slot()
    def clear_plot(self):
        """Clear the plot and reset state."""
        self._mode = None
        self._scan_data = None
        self._scan_values_1 = None
        self._scan_values_2 = None
        self._variable_name_1 = ""
        self._variable_name_2 = ""
        self._counts = None
        self._valid_mask = None
        self._measured_mask = None
        self._current_index = -1
        self._data_folder = None
        self._scan_metadata = {}
        
        # Remove colorbar if present
        if self._colorbar is not None:
            try:
                self._colorbar.remove()
            except (ValueError, AttributeError):
                pass
            self._colorbar = None
        
        self._show_empty_plot()
    
    def _on_save_plot(self):
        """Handle save plot button click."""
        if self._mode is None:
            return
        
        # Open save dialog with preview
        dialog = SavePlotDialog(self, self)
        dialog.exec()
    
    def set_data_folder(self, folder):
        """Set the data folder path for default save location."""
        self._data_folder = folder
    
    def set_scan_metadata(self, metadata):
        """Set scan metadata for the information panel.
        
        Args:
            metadata: Dictionary with scan parameters like:
                - number_neutrons: int
                - K_fixed: str ('Ki Fixed' or 'Kf Fixed')
                - fixed_E: float (meV)
                - alpha_1, alpha_2, alpha_3, alpha_4: str (collimations)
                - monocris, anacris: str (crystal names)
                - kappa, psi: float (alignment offsets in degrees)
                - qx, qy, qz: float (Q-space coordinates)
                - H, K, L: float (HKL coordinates)
                - deltaE: float (energy transfer in meV)
                - sample_frame_mode: str ('HKL' or 'Q')
                - NMO_installed: str
                - V_selector_installed: bool
        """
        self._scan_metadata = metadata.copy() if metadata else {}
    
    def load_existing_data(self, data_folder, scan_command1, scan_command2="", metadata=None):
        """Load and display existing scan data from a folder.
        
        Args:
            data_folder: Path to the scan data folder
            scan_command1: First scan command string (e.g., "qx 2 2.2 0.1")
            scan_command2: Second scan command string (2D only)
            metadata: Optional dict with scan metadata for info panel
        """
        from tavi.utilities import parse_scan_steps
        from tavi.data_processing import read_1Ddetector_file, read_parameters_from_file
        
        # Store data folder and metadata
        self._data_folder = data_folder
        if metadata:
            self._scan_metadata = metadata.copy()
        
        if not scan_command1:
            self._show_empty_plot()
            self.status_label.setText("No scan commands found in data")
            return
        
        # Parse scan commands
        var_name_1, values_1 = parse_scan_steps(scan_command1)
        var_name_1 = self._normalize_variable_name(var_name_1)
        
        if scan_command2:
            # 2D scan
            var_name_2, values_2 = parse_scan_steps(scan_command2)
            var_name_2 = self._normalize_variable_name(var_name_2)
            
            # Initialize with all points valid (we'll mark measured as we find data)
            valid_mask_2d = np.ones((len(values_2), len(values_1)), dtype=bool)
            self.initialize_scan('2D', list(values_1), [], var_name_1, 
                               var_name_2, list(values_2), valid_mask_2d)
            
            # Load data from folders
            for folder_name in os.listdir(data_folder):
                full_path = os.path.join(data_folder, folder_name)
                if os.path.isdir(full_path) and folder_name.startswith('scan_'):
                    point_params = read_parameters_from_file(full_path)
                    if point_params and var_name_1 in point_params and var_name_2 in point_params:
                        x_val = float(point_params.get(var_name_1, 0))
                        y_val = float(point_params.get(var_name_2, 0))
                        
                        # Find indices
                        idx_x = np.argmin(np.abs(self._scan_values_1 - x_val))
                        idx_y = np.argmin(np.abs(self._scan_values_2 - y_val))
                        
                        # Read counts
                        _, _, counts = read_1Ddetector_file(full_path)
                        if counts is not None:
                            self._counts[idx_y, idx_x] = counts
                            self._measured_mask[idx_y, idx_x] = True
            
            # Mark points without data as impossible (they failed during scan)
            self._valid_mask = self._measured_mask.copy()
            self._update_2d_display()
        else:
            # 1D scan
            # Initialize with all points valid
            valid_mask_1 = [True] * len(values_1)
            self.initialize_scan('1D', list(values_1), valid_mask_1, var_name_1)
            
            # Load data from folders
            for folder_name in os.listdir(data_folder):
                full_path = os.path.join(data_folder, folder_name)
                if os.path.isdir(full_path) and folder_name.startswith('scan_'):
                    point_params = read_parameters_from_file(full_path)
                    if point_params and var_name_1 in point_params:
                        x_val = float(point_params.get(var_name_1, 0))
                        
                        # Find index
                        idx = np.argmin(np.abs(self._scan_values_1 - x_val))
                        
                        # Read counts
                        _, _, counts = read_1Ddetector_file(full_path)
                        if counts is not None:
                            self._counts[idx] = counts
                            self._measured_mask[idx] = True
            
            # Mark points without data as impossible
            self._valid_mask = self._measured_mask.copy()
            self._update_1d_display()
        
        self.scan_complete()
    
    def _normalize_variable_name(self, name):
        """Normalize variable name to canonical form."""
        if not name:
            return name
        name = str(name).strip()
        lower = name.lower()
        if lower in ["h", "k", "l"]:
            return lower.upper()
        if lower in ["a1", "a2", "a3", "a4"]:
            return lower.upper()
        if lower == "deltae":
            return "deltaE"
        if lower in ["qx", "qy", "qz", "rhm", "rvm", "rha", "rva"]:
            return lower
        if lower in ["omega", "chi", "kappa", "psi"]:
            return lower
        return name
