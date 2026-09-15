category: qol

The Windows installer no longer needs Visual Studio or the Microsoft MPI SDK. The C compiler is installed together with everything else, and the installer compiles and runs a test instrument before it finishes so a broken compiler is caught at install time, not at your first scan.
