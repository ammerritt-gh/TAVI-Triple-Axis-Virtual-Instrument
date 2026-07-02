"""The shared, instrument-independent sample library.

Samples are physical objects that move between instruments, so their specs are
not owned by any one instrument: every registered instrument mounts this table
by default (``samples=default_sample_library()`` in its descriptor) and may
filter or extend it. Design record ``docs/CONFIGURABLE_INSTRUMENTS.md`` §19;
supersedes the earlier "owned per-instrument" disposition (§6).

Import rules: this module must stay import-light (stdlib +
``instruments.descriptor`` only) because instrument plugins import it at module
level and the registry's lazy-listing guarantee forbids anything heavy there.
The ``tavi -> instruments.descriptor`` edge is cycle-safe: the descriptor
module imports only the stdlib.

``SampleSpec.lattice`` records the sample's own lattice constants
(a, b, c, alpha, beta, gamma); the GUI adopts them into the lattice fields when
the user selects the sample, so the computed instrument angles match the
component's internal crystal (Phonon_DFT bakes a=4.03893 -- driving it with the
default Al 4.05 lattice misses its Bragg condition entirely).
"""
from __future__ import annotations

from instruments.descriptor import SampleSpec

_AL_LATTICE = (4.05, 4.05, 4.05, 90.0, 90.0, 90.0)


def default_sample_library() -> tuple[SampleSpec, ...]:
    """Return the shared sample specs (the "no sample" entry first)."""
    return (
        SampleSpec("none", "No sample", None),
        SampleSpec(
            "Al_rod_phonon", "AL: acoustic phonon", "Phonon_simple_SCATTER",
            properties={
                "radius": 5e-3, "yheight": 30e-3,
                "sigma_abs": 0.0, "sigma_inc": 0.0,
                "a": 4.05, "b": 345, "M": 27, "c": 4, "DW": 1, "T": 200,
                "target_index": 2, "focus_aw": 5, "focus_ah": 15,
            },
            split=10, extend="if(!SCATTERED) ABSORB;",
            lattice=_AL_LATTICE,
        ),
        SampleSpec(
            "Al_rod_phonon_optic", "Al: optic phonon", "Optic_Phonon_simple",
            properties={
                "radius": 5e-3, "yheight": 30e-3,
                "sigma_abs": 0, "sigma_inc": 0,
                "a": 3.14, "b": 345, "M": 27, "c": 4, "DW": 1, "T": 300,
                "zero_energy": 4, "maximum_energy": 1,
                "target_index": 2, "focus_aw": 5, "focus_ah": 15,
            },
            split=10, extend="if(!SCATTERED) ABSORB;",
            lattice=(3.14, 3.14, 3.14, 90.0, 90.0, 90.0),
        ),
        SampleSpec(
            "Al_bragg", "AL: Bragg", "Single_crystal",
            properties={
                "reflections": '"Al.lau"', "radius": 5e-3, "yheight": 30e-3,
                "mosaic": 5, "sigma_inc": -1,
            },
            split=10,
            component_name="Al_Bragg",  # legacy McStas instance capitalization
            lattice=_AL_LATTICE,
        ),
        SampleSpec(
            "Al_phonon_DFT", "Al: Phonon DFT", "Phonon_DFT",
            properties={
                "reflections": '"Al_mp-134_symmetrized.laz"',
                "delta_d_d": 1.45e-3, "barns": 1,
                "dispersion": '"Al_test_phonons_centered.dat"',
                "tessellate": 1, "phonon_e_steps": 50,
                "radius": 5e-3, "yheight": 30e-3,
                "a": 4.03893, "sigma_abs": 0, "sigma_inc": 0.0,
                "debye_waller": 1, "T": 200,
                "p_interact": 1.0, "p_phonon": 0.95, "phonon_gamma": 0.2,
                "target_index": 2, "focus_aw": 5.0, "focus_ah": 15.0,
            },
            split=10,
            lattice=(4.03893, 4.03893, 4.03893, 90.0, 90.0, 90.0),
        ),
    )
