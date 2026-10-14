category: minor
notice: TAVI now keeps a crash log, output/tavi-crash.log; please attach it when you report a crash.

Each launch adds a line naming the operating system, the Python, PySide6 and matplotlib versions, and the display session, followed by anything that goes wrong: the Python stack of every thread on a hard crash, uncaught errors from the panels, plots and scan threads, and Qt's own warnings. The console prints the file's path at startup, and the log starts fresh once it passes 1 MB.
