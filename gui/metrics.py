"""Spacing and size tokens for TAVI's docks.

Holds only the values the compact-window change introduced; the older inline
setStyleSheet literals and per-widget setMaximumWidth numbers are not migrated
here yet (named debt). Retune on sight.
"""

# Horizontal gap between a form label and its field, in px.
LABEL_FIELD_GAP = 8

# The four form docks (Instrument, Sample, Scattering, Simulation) lay their
# group boxes out as fixed-width blocks: one column in Narrow, two in Wide
# where the dock is wide enough. Every block's content fits BLOCK_WIDTH, and
# BLOCK_GAP separates blocks both ways. A one-column dock goes two-up only
# past two blocks plus the hysteresis, so a splitter drag at the boundary
# does not flicker. All in px.
BLOCK_WIDTH = 300
BLOCK_GAP = 8
BLOCK_REFLOW_HYSTERESIS = 16

# Choosing Wide sizes the form docks two blocks wide only when the window
# still leaves the plot at least this wide; otherwise they stay one block.
WIDE_PLOT_MIN_WIDTH = 400

# A field holding an (h k l) triple, such as the Sample dock's mounting plane, in px.
HKL_TRIPLE_FIELD_WIDTH = 100
