category: fix

The installer no longer stops with "Cannot uninstall shiboken6" or starts TAVI with a Qt DLL error afterwards. Every Python package now comes from the same conda-forge channel, an existing environment is rebuilt instead of patched, and the installer checks that the GUI toolkit loads before it finishes.
