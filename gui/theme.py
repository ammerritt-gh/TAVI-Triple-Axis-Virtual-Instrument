"""Colour and stroke tokens for the scan-field marks.

Holds only the mark tokens: the two command accents, the set-per-point outline
and badge text, and the quiet note text. The older inline setStyleSheet colour
literals across the docks are not migrated here yet (named debt). Retune on sight.
"""

# Command 1 blue, command 2 orange: distinct under colour-blindness, and every
# mark also carries its number, so colour is never the only channel.
COMMAND_COLORS = {1: "#1f5fbf", 2: "#b35c00"}

# Outline of a field set at each point, and the badge text of a set mark.
DERIVED_OUTLINE = "#5a5a5a"
BADGE_TEXT = "#5a5a5a"

# Legend and group-note text.
NOTE_TEXT = "#444444"

# Outline widths in px: a scanned field is dashed, a set one solid with a
# heavier bottom edge.
SCANNED_PEN_WIDTH = 2
SET_PEN_WIDTH = 1
SET_BOTTOM_EDGE_WIDTH = 2
