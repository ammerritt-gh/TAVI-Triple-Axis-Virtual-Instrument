# IN12 (ILL)

IN12 is a cold-neutron triple-axis spectrometer at the ILL, operated as CRG-B by
Forschungszentrum Jülich with CEA Grenoble. TAVI models the conventional
post-2012 configuration: the H144 supermirror guide delivers neutrons to a
virtual source at its exit, 1.8 m from a large doubly focusing 11 × 11 PG(002)
monochromator; the beam reaches the sample through optional Soller collimation
and a slit; a horizontally focusing analyser selects the final energy before one
vertical ³He detector tube.

Two analysers are selectable: the conventional PG(002) assembly and the
Heusler(111) used for polarisation analysis. TAVI does not model polarisation,
so choosing Heusler changes the kinematics (its d-spacing sets the analyser
angle) and nothing else.

Not modeled, deliberately: the ~115 m of H144 above the guide exit, and with it
the velocity selector and the transmission polarising cavity that sit 35–36 m
upstream; the optional cooled beryllium filter; and IN12-UFO, the fifteen-channel
multi-analyser option, which reached neutron commissioning but has no published
routine science use. The reasons are in [MODEL_STATUS.md](MODEL_STATUS.md),
which also lists what the model guesses and what it knows.

The scattering senses are **(−1, +1, −1)** — the "W" configuration, with the
monochromator and analyser on the clockwise branch and the sample
counter-clockwise. This was confirmed from three independent sources, so IN12's
angles are trustworthy. What the model still guesses at is intensity and
resolution: the incident spectrum above all, then the individual crystal
dimensions, which nobody publishes. Those questions are in
[SCIENTIST_REVIEW.md](SCIENTIST_REVIEW.md), the only file an instrument
scientist needs to open.

The runnable implementation is [plugin.py](plugin.py) plus [model.py](model.py).
Its component and data dependencies remain in the repository-level `components/`
folder.
