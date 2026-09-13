category: fix
notice: A scan over a focusing axis that the crystal's design fixes is now refused before it starts, where it used to run and quietly defocus the instrument.

An analyser focusing axis that the crystal's design permanently fixes (such as the vertical focus on PANDA or IN12) is now refused if you try to scan it, instead of silently letting the scan override it.
