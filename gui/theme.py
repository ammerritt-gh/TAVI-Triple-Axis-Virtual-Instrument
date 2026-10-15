"""Colour and stroke tokens for the scan-field marks, the folding-group flag and the warning state.

Holds the mark tokens (the two command accents, the set-per-point outline
and badge text, the quiet note text and the command chip text), the group
flag text and the warning fill of a control. The older inline setStyleSheet colour
literals across the docks are not migrated here yet (named debt). Retune on sight.
"""

# Command 1 blue, command 2 orange: distinct under colour-blindness, and every
# mark also carries its number, so colour is never the only channel.
COMMAND_COLORS = {1: "#1f5fbf", 2: "#b35c00"}

# Outline of a field set at each point, and the badge text of a set mark.
DERIVED_OUTLINE = "#5a5a5a"
BADGE_TEXT = "#333333"

# Legend and group-note text.
NOTE_TEXT = "#444444"

# Text on the filled command chips "1" and "2".
CHIP_TEXT = "#ffffff"

# Group header flag: muted dark amber, AA on the panel, apart from the command colours.
FLAG_TEXT = "#7a5c00"

# Outline widths in px: a scanned field is dashed, a set one solid with a
# heavier bottom edge.
SCANNED_PEN_WIDTH = 2
SET_PEN_WIDTH = 1
SET_BOTTOM_EDGE_WIDTH = 2

# A control in its warning state: the Fitting dock's CEN "Go" when the fit
# converged with warnings or points were measured since it; its tooltip says why.
WARNING_FILL = "#e8a33d"
WARNING_TEXT = "#202020"
