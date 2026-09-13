category: fix
notice: An API scan must now supply its own scan command; unsent text in a GUI scan box is ignored, and a queued scan's settings are frozen at submission.

Submitting a scan or validation request through the remote API no longer depends on whatever is sitting in the GUI's scan boxes, and a scan already queued or running is no longer affected by later changes in the GUI.
