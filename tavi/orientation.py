"""Crystal orientation core: sample angles <-> the crystal's Q in the mount frame.

Frames: the mount frame is the McStas sample frame (x, z horizontal, y up);
``U @ B @ hkl`` lives there. Sample sense follows the vTAS Friedel convention
verified live on IN8 (2026-07-02): a setting on the +1 branch puts ``-U B hkl``
on the lab scattering vector, the -1 branch puts ``+U B hkl`` there.

Imports nothing from ``instruments/`` and nothing Qt: ISAR vendors this file.
"""
from tavi.tas_geometry import instrument_q_to_component_q, q_instrument_from_angles


def q_mount_from_legacy_angles(sth, saz, stt, ki, kf, sense_sample):
    """Return ``U @ B @ hkl`` (mount frame) measured at a legacy sample setting.

    ``(sth, saz, stt)`` is the legacy triple in degrees: turntable, the
    beam-fixed tilt under it, and the signed sample two-theta. The raw inverse
    of a +1-branch setting recovers the Friedel partner ``-Q``; the sign is
    undone here so every caller gets the crystal's own Q.
    """
    q_mount = instrument_q_to_component_q(q_instrument_from_angles(sth, saz, stt, ki, kf))
    return -q_mount if sense_sample > 0 else q_mount
