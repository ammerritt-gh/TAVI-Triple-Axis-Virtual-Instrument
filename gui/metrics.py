"""Spacing and size tokens for TAVI's docks.

Holds only the values the compact-window change introduced; the older inline
setStyleSheet literals and per-widget setMaximumWidth numbers are not migrated
here yet (named debt). Retune on sight.
"""

# Horizontal gap between a form label and its field, in px.
LABEL_FIELD_GAP = 8

# Content width of the four form docks (Instrument, Sample, Scattering,
# Simulation), in px. Below the minimum the dock scrolls instead of
# compressing; above the cap the spare width shows to the right of the form.
FORM_CONTENT_MIN_WIDTH = 300
FORM_CONTENT_MAX_WIDTH = 520
