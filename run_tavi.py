#!/usr/bin/env python3
"""
TAVI - Triple-Axis Virtual Instrument

New MVVM-based application entry point.
This script launches the refactored TAVI application with the new
modular architecture.

For the legacy application, use McScript_Runner.py instead.
"""
import sys
import os

# Add the repository root to the path
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from tavi import Application, main

if __name__ == "__main__":
    main()
