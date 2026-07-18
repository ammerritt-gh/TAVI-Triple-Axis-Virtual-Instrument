# IN8 (ILL)

IN8 is a high-flux thermal triple-axis spectrometer at the ILL. TAVI currently
models the single-analyser ThermES configuration: a virtual source illuminates
a doubly focusing monochromator, the beam reaches the sample through optional
collimation and a slit, and a focusing analyser selects the final energy before
one detector.

The model offers PG(002) and provisional Cu(200) monochromators with a PG(002)
analyser. It does not yet model the bent-perfect silicon faces, FlatCone, IMPS,
the Be-filter mode, or the full filter switching arrangement.

The runnable implementation is [plugin.py](plugin.py) plus
[model.py](model.py). Its component and data dependencies remain in the
repository-level `components/` folder. The detailed evidence comparison is in
[MODEL_STATUS.md](MODEL_STATUS.md). Instrument scientists only need to comment
in [SCIENTIST_REVIEW.md](SCIENTIST_REVIEW.md).
