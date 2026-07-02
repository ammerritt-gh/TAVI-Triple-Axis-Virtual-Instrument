"""The shared, instrument-independent sample library (design record §19).

Samples move between instruments, so the specs live in
``tavi/sample_library.py`` and instruments mount them by reference.
"""
from instruments.puma_plugin import puma_descriptor
from tavi.sample_library import default_sample_library


def test_no_sample_entry_first():
    library = default_sample_library()
    assert library[0].id == "none"
    assert library[0].component_type is None
    assert library[0].lattice is None


def test_ids_unique_and_nonempty():
    ids = [s.id for s in default_sample_library()]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_al_bragg_keeps_legacy_component_name():
    bragg = next(s for s in default_sample_library() if s.id == "Al_bragg")
    assert bragg.component_name == "Al_Bragg"


def test_lattices_match_component_internals():
    by_id = {s.id: s for s in default_sample_library()}
    assert by_id["Al_phonon_DFT"].lattice[0] == 4.03893  # Phonon_DFT internal a
    assert by_id["Al_rod_phonon_optic"].lattice[0] == 3.14
    assert by_id["Al_bragg"].lattice == (4.05, 4.05, 4.05, 90.0, 90.0, 90.0)
    for spec in default_sample_library():
        if spec.lattice is not None:
            assert len(spec.lattice) == 6
            # lattice constant matches the component's own 'a' when it has one
            if "a" in spec.properties:
                assert spec.lattice[0] == spec.properties["a"]


def test_puma_mounts_the_shared_library():
    assert puma_descriptor().samples == default_sample_library()
