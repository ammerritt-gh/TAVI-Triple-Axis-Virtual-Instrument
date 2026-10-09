"""The quantity registry: aliases resolve, refusals name their replacement, the check rejects bad tables."""
import pytest

from tavi.quantities import (QUANTITIES, Quantity, QuantityRefused, UnknownQuantity, by_id,
                             index_table, resolve, SLIT_SCAN_REFUSAL)

SCAN_AND_WRITE = [
    ("A2", "mono_two_theta_deg"), ("mtt", "mono_two_theta_deg"),
    ("A3", "sample_rotation_deg"), ("sth", "sample_rotation_deg"), ("OMEGA", "sample_rotation_deg"),
    ("psi", "sample_rotation_deg"),
    ("a4", "sample_two_theta_deg"), ("stt", "sample_two_theta_deg"), ("2theta", "sample_two_theta_deg"),
    ("A6", "analyzer_two_theta_deg"), ("att", "analyzer_two_theta_deg"),
    ("sgl", "sample_lower_arc_deg"), ("sgu", "sample_upper_arc_deg"),
    ("H", "h"), ("K", "k"), ("L", "l"),
    ("qx", "q_instrument_x_inv_angstrom"), ("qy", "q_instrument_y_inv_angstrom"),
    ("qz", "q_instrument_z_inv_angstrom"),
    ("deltaE", "energy_transfer_mev"),
    ("rhm", "mono_horizontal_radius_m"), ("rvm", "mono_vertical_radius_m"),
    ("rha", "analyzer_horizontal_radius_m"), ("rva", "analyzer_vertical_radius_m"),
]
WRITE_ONLY = [
    ("Ei", "incident_energy_mev"), ("Ef", "final_energy_mev"),
    ("Ki", "incident_wavevector_inv_angstrom"), ("Kf", "final_wavevector_inv_angstrom"),
    ("post_mono_hgap", "slit.post_mono.horizontal_gap_mm"),
    ("post_mono_vgap", "slit.post_mono.vertical_gap_mm"),
    ("pre_sample_hgap", "slit.pre_sample.horizontal_gap_mm"),
    ("pre_sample_vgap", "slit.pre_sample.vertical_gap_mm"),
    ("detector_hgap", "slit.detector.horizontal_gap_mm"),
    ("detector_vgap", "slit.detector.vertical_gap_mm"),
    ("virtual_source_hgap", "slit.virtual_source.horizontal_gap_mm"),
    ("virtual_source_vgap", "slit.virtual_source.vertical_gap_mm"),
    ("sample_exit_hgap", "slit.sample_exit.horizontal_gap_mm"),
    ("sample_exit_vgap", "slit.sample_exit.vertical_gap_mm"),
    ("a", "lattice_a_angstrom"), ("B", "lattice_b_angstrom"), ("c", "lattice_c_angstrom"),
    ("Alpha", "lattice_alpha_deg"), ("beta", "lattice_beta_deg"), ("gamma", "lattice_gamma_deg"),
]
SLIT_NAMES = [name for name, canonical in WRITE_ONLY if canonical.startswith("slit.")]
OLD_SLITS = [
    ("vbl_hgap", "post_mono_hgap"), ("pbl_hgap", "pre_sample_hgap"), ("pbl_vgap", "pre_sample_vgap"),
    ("dbl_hgap", "detector_hgap"), ("sbl_wgap", "pre_sample_hgap"), ("sbl_hgap", "pre_sample_vgap"),
    ("ms1_wgap", "virtual_source_hgap"), ("ss1_wgap", "pre_sample_hgap"),
    ("ss1_hgap", "pre_sample_vgap"), ("ss2_wgap", "sample_exit_hgap"), ("ss2_hgap", "sample_exit_vgap"),
]


@pytest.mark.parametrize("name, canonical", SCAN_AND_WRITE)
def test_alias_resolves_in_both_contexts(name, canonical):
    assert resolve(name, "scan").id == canonical
    assert resolve(name, "write").id == canonical


@pytest.mark.parametrize("name, canonical", WRITE_ONLY)
def test_write_only_alias_resolves_for_write(name, canonical):
    assert resolve(name, "write").id == canonical


@pytest.mark.parametrize("name, canonical", WRITE_ONLY)
def test_write_only_alias_refused_as_scan(name, canonical):
    with pytest.raises(QuantityRefused):
        resolve(name, "scan")


@pytest.mark.parametrize("q", QUANTITIES, ids=lambda q: q.id)
def test_canonical_id_resolves_case_insensitively(q):
    if q.writable:
        assert resolve(q.id.upper(), "write") is q
    if q.scannable:
        assert resolve(q.id.upper(), "scan") is q


@pytest.mark.parametrize("name, expected", [
    ("A1", "not modelled yet"), ("mth", "not modelled yet"),
    ("A5", "not modelled yet"), ("ath", "not modelled yet"),
])
def test_derived_theta_refused_with_rocking_message(name, expected):
    with pytest.raises(QuantityRefused, match=expected):
        resolve(name, "scan")


@pytest.mark.parametrize("name, pointer", [("A1", "scan A2"), ("mth", "scan A2"),
                                           ("A5", "scan A6"), ("ath", "scan A6")])
def test_derived_theta_points_to_two_theta(name, pointer):
    with pytest.raises(QuantityRefused, match=pointer):
        resolve(name, "scan")
    with pytest.raises(QuantityRefused):
        resolve(name, "write")


@pytest.mark.parametrize("name", ["applied_mono_horizontal_radius_m", "applied_mono_vertical_radius_m",
                                  "applied_analyzer_horizontal_radius_m",
                                  "applied_analyzer_vertical_radius_m"])
@pytest.mark.parametrize("context", ["scan", "write"])
def test_applied_radius_refused(name, context):
    with pytest.raises(QuantityRefused):
        resolve(name, context)


@pytest.mark.parametrize("name, hint", [("chi", "sgl"), ("phi", "phi"), ("kappa", "kappa")])
@pytest.mark.parametrize("context", ["scan", "write"])
def test_unmodelled_axes_refused(name, hint, context):
    with pytest.raises(QuantityRefused, match=hint):
        resolve(name, context)


@pytest.mark.parametrize("old, new", OLD_SLITS)
@pytest.mark.parametrize("context", ["scan", "write"])
def test_old_slit_name_refused_with_millimetre_replacement(old, new, context):
    with pytest.raises(QuantityRefused) as info:
        resolve(old, context)
    assert new in str(info.value)
    assert "millimetres" in str(info.value)


def test_in8_sbl_hgap_names_pre_sample_vgap():
    with pytest.raises(QuantityRefused, match="pre_sample_vgap"):
        resolve("sbl_hgap", "write")


@pytest.mark.parametrize("name", SLIT_NAMES)
def test_slit_scan_refused_with_point_plan_message(name):
    with pytest.raises(QuantityRefused) as info:
        resolve(name, "scan")
    assert str(info.value) == SLIT_SCAN_REFUSAL


@pytest.mark.parametrize("name", ["Ei", "Ki"])
def test_fixed_energy_and_wavevector_writable_not_scannable(name):
    assert resolve(name, "write").writable
    with pytest.raises(QuantityRefused):
        resolve(name, "scan")


@pytest.mark.parametrize("name", ["a", "alpha"])
def test_lattice_alias_refused_as_scan(name):
    with pytest.raises(QuantityRefused, match="API"):
        resolve(name, "scan")


@pytest.mark.parametrize("name", ["nonsense", "A7"])
def test_unknown_name_refused_naming_it(name):
    with pytest.raises(QuantityRefused, match=name):
        resolve(name, "scan")


def test_angle_labels_use_registry_wording():
    assert by_id("mono_theta_deg").label == "Mono θ — A1 (°)"
    assert by_id("analyzer_two_theta_deg").label == "Analyzer 2θ — A6 (°)"
    assert by_id("sample_lower_arc_deg").label == "Lower arc sgl (°)"
    assert "sample θ" not in by_id("sample_rotation_deg").label.casefold()


def _q(name, *aliases, **flags):
    return Quantity(name, "", "", "", "", aliases=aliases, **flags)


def test_check_rejects_alias_collision_case_insensitively():
    with pytest.raises(ValueError):
        index_table([_q("x_one", "A"), _q("x_two", "a")])


def test_check_rejects_alias_equal_to_other_canonical_id():
    with pytest.raises(ValueError):
        index_table([_q("x_one"), _q("x_two", "X_ONE")])


def test_check_rejects_canonical_id_collision():
    with pytest.raises(ValueError):
        index_table([_q("x"), _q("X")])


def test_check_rejects_duplicate_alias_within_one_quantity():
    with pytest.raises(ValueError):
        index_table([_q("x", "a", "A")])


def test_check_accepts_alias_equal_to_own_canonical_id():
    assert index_table([_q("h", "H")])["h"].id == "h"


def test_a_name_in_no_row_is_unknown_but_a_refused_one_is_not():
    """The GUI suggests spellings for an unknown name and quotes the registry for a refused one."""
    with pytest.raises(UnknownQuantity):
        resolve("xyz", "scan")
    for refused in ("chi", "A1", "pre_sample_hgap", "Ei"):
        with pytest.raises(QuantityRefused) as caught:
            resolve(refused, "scan")
        assert not isinstance(caught.value, UnknownQuantity), refused


def test_every_angle_names_its_nicos_motor():
    """The docks' tooltips read the NICOS name from the registry, arcs included."""
    from tavi.quantities import QUANTITIES
    nicos = {q.id: q.nicos for q in QUANTITIES if q.ill or q.id.endswith("_arc_deg")}
    assert all(nicos.values()), nicos
    assert nicos["sample_lower_arc_deg"] == "sgl" and nicos["sample_upper_arc_deg"] == "sgu"
