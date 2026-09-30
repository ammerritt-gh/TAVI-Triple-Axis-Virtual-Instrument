category: fix
notice: TAVI now runs 4 MPI processes per point unless you raise it under Config → MPI processes.

Simulations on Linux and macOS computers with fewer than 30 cores no longer fail out of the box: the number of MPI processes per point now starts at 4. It is set from the new Config menu and remembered on this computer; on a machine with fewer than 4 physical cores, lower it there.
