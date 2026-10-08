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

# First start (and View > Reset to Default Layout) picks the layout from the
# screen's available width in logical px: 2 columns below LAYOUT_TWO_COLUMNS_BELOW,
# else 3; Wide from LAYOUT_WIDE_FROM up, else Narrow. 4 columns is never picked.
LAYOUT_TWO_COLUMNS_BELOW = 1400
LAYOUT_WIDE_FROM = 2000

# A layout preset gives each column's short docks their content height, but
# never more than this share of the column; the column's elastic dock (the one
# that scrolls, or the plot) takes the rest.
SPLIT_CONTENT_MAX_SHARE = 0.5

# In the 2-column layout at the laptop size (1108x851) the Display plot canvas
# keeps at least this visible area, in px.
DISPLAY_CANVAS_MIN_WIDTH = 300
DISPLAY_CANVAS_MIN_HEIGHT = 250
