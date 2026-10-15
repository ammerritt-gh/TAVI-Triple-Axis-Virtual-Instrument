category: minor
notice: TAVI now keeps a crash log, output/tavi-crash.log; please attach it when you report a crash.

Each launch adds a line naming the operating system, the Python, PySide6 and matplotlib versions, and the display session, followed by anything that goes wrong: uncaught errors from the panels, plots and scan threads, Qt's own warnings, and on Linux and macOS the Python stack of every thread on a hard crash. The console prints the file's path at startup; one session writes at most 1 MB, and the next launch starts a fresh file once it is past that size.
