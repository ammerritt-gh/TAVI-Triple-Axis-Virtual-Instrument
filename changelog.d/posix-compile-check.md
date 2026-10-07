category: qol
notice: On macOS and Linux the installer now stops when McStas cannot run a test simulation with two MPI processes, which includes a single-core machine and installing as root.

The macOS and Linux installer now compiles and runs a small test instrument with two MPI processes before it finishes, so a missing compiler or a broken MPI setup stops the install with the reason and a log, instead of failing at your first scan. Like the rest of that script, this check has not yet been run on either platform.
