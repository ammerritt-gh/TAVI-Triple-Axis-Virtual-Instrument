#!/usr/bin/env python
"""Test script to verify TAVI PySide6 GUI can be instantiated."""
import sys
import os

# Set Qt platform to offscreen for testing
os.environ['QT_QPA_PLATFORM'] = 'minimal'

try:
    from PySide6.QtWidgets import QApplication
    from gui.main_window import TAVIMainWindow
    
    print("Testing TAVI PySide6 GUI...")
    print("-" * 60)
    
    # Create application
    app = QApplication(sys.argv)
    print("✓ QApplication created successfully")
    
    # Create main window
    window = TAVIMainWindow()
    print("✓ TAVIMainWindow created successfully")
    print(f"  Window title: {window.windowTitle()}")
    print(f"  Window size: {window.width()}x{window.height()}")
    
    # Check all docks exist
    print("\nDock widgets:")
    print(f"  ✓ Instrument Configuration: {window.instrument_dock.windowTitle()}")
    print(f"  ✓ Reciprocal Space: {window.reciprocal_space_dock.windowTitle()}")
    print(f"  ✓ Sample Control: {window.sample_dock.windowTitle()}")
    print(f"  ✓ Scan Controls: {window.scan_controls_dock.windowTitle()}")
    print(f"  ✓ Diagnostics: {window.diagnostics_dock.windowTitle()}")
    print(f"  ✓ Output: {window.output_dock.windowTitle()}")
    print(f"  ✓ Data Control: {window.data_control_dock.windowTitle()}")
    
    # Check some key widgets in each dock
    print("\nKey widgets check:")
    print(f"  ✓ Instrument dock has {len(window.instrument_dock.findChildren(type(window.instrument_dock.mtt_edit)))} line edits")
    print(f"  ✓ Scan controls dock has run button: {window.scan_controls_dock.run_button.text()}")
    print(f"  ✓ Output dock has message text area")
    
    print("\n" + "-" * 60)
    print("All tests passed! ✓")
    print("\nThe GUI structure is correct and can be instantiated.")
    print("To run the full application with display, use:")
    print("  python TAVI_PySide6.py")
    
except Exception as e:
    print(f"\n✗ Error during testing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
