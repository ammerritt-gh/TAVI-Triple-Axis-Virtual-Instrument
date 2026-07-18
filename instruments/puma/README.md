# PUMA (FRM-II)

PUMA is a thermal triple-axis spectrometer at MLZ. TAVI models it as a chain
from a configurable neutron source through the monochromator, sample,
analyser, and one ideal detector.

The source illuminates a curved PG monochromator. Optional source-side
collimation and a test velocity selector may be inserted. After the
monochromator, selectable collimators and slits shape the beam before the
sample. TAVI can also insert the experimental nested mirror optics (NMO)
model. A curved PG analyser selects the final energy before the detector.

The runnable implementation is split between [plugin.py](plugin.py), which
describes GUI choices and maps them to state, and [model.py](model.py), which
contains PUMA focusing physics and the McStas component tree. Shared TAS
geometry and execution live in `instruments/tas_runtime.py`.

TAVI currently simplifies the detector as an ideal monitor and includes
experimental modules that are not ordinary installed PUMA hardware. See
[MODEL_STATUS.md](MODEL_STATUS.md) for provenance and uncertainty. If you are
reviewing the instrument for us, you only need
[SCIENTIST_REVIEW.md](SCIENTIST_REVIEW.md).

McStas components and data remain in the repository-level `components/`
folder. PUMA uses the NMO component and the two `PUMA_NMO_*Focusing.txt`
tables from that central location.
