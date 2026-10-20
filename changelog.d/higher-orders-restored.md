category: fix
notice: Results from PANDA and IN12 on v1.3.0 to v1.4.0 lack higher-order contamination; 1.4.1 restores it.

From v1.3.0 through v1.4.0, PANDA and IN12 reflected first order only at both crystals, so their simulated results on those versions lack higher-order (harmonic) contamination. Version 1.4.1 restores it, as PUMA and IN8 always had; the filters, guides and velocity selector that reduce that contamination on the real instruments are not modelled, so the simulated contamination is larger than the real instrument's.
