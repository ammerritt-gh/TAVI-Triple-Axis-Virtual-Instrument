"""The quantity registry: aliases resolve, refusals name their replacement, the check rejects bad tables."""
import pytest

from tavi.quantities import (QUANTITIES, Quantity, QuantityRefused, UnknownQuantity, by_id,
                             index_table, normalize_write_names, public_applied_radii,
                             public_values, resolve, to_internal, to_public, SLIT_SCAN_REFUSAL)

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


@pytest.mark.parametrize("name, pointer", [("A1", "set A2"), ("mth", "set A2"),
                                           ("A5", "set A6"), ("ath", "set A6")])
def test_derived_theta_write_refusal_says_set_not_scan(name, pointer):
    with pytest.raises(QuantityRefused, match=pointer) as caught:
        resolve(name, "write")
    assert "scan" not in str(caught.value)


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


# --- the API write boundary: internal names, key resolution, public views -----------------

def test_every_writable_non_slit_quantity_has_an_internal_name_and_back():
    for q in QUANTITIES:
        if q.writable and not q.id.startswith("slit."):
            assert to_public(to_internal(q.id)) == q.id, q.id
    assert to_internal("sample_two_theta_deg") == "stt"
    assert to_internal("mono_two_theta_deg") == "mtt"       # not the old "A1"/"A2" arithmetic
    assert to_public("K") == "k" and to_public("K_fixed") == "K_fixed"


ACCEPT = {"mono_two_theta_deg", "sample_two_theta_deg", "sample_rotation_deg", "h",
          "slit.pre_sample.horizontal_gap_mm", "K_fixed", "scan_command1", "curvature_modes"}


def test_names_resolve_to_the_keys_they_write():
    keys, errors = normalize_write_names(
        ["A2", "STT", "psi", "H", "pre_sample_hgap", "K_fixed", "scan_command1"], ACCEPT)
    assert errors == {}
    assert keys == {"A2": "mono_two_theta_deg", "STT": "sample_two_theta_deg",
                    "psi": "sample_rotation_deg", "H": "h",
                    "pre_sample_hgap": "slit.pre_sample.horizontal_gap_mm",
                    "K_fixed": "K_fixed", "scan_command1": "scan_command1"}


@pytest.mark.parametrize("names, bad", [
    (["stt", "A4"], {"stt", "A4"}),
    (["A4", "sample_two_theta_deg"], {"A4", "sample_two_theta_deg"}),
    (["omega", "psi", "sth"], {"omega", "psi", "sth"}),
    (["A1"], {"A1"}),                                       # derived only
    (["kappa"], {"kappa"}),                                 # retired
    (["slits_mm"], {"slits_mm"}),
    (["lattice_a"], {"lattice_a"}),                         # the old spelling
    (["nonsense"], {"nonsense"}),
    (["Ei"], {"Ei"}),                                       # a quantity this caller lacks
    (["slit.detector.horizontal_gap_mm"], {"slit.detector.horizontal_gap_mm"}),
])
def test_a_name_that_cannot_be_written_is_reported_under_its_own_spelling(names, bad):
    _keys, errors = normalize_write_names(names + ["h"], ACCEPT)
    assert set(errors) == bad


def test_each_refusal_names_what_to_use_instead():
    _keys, errors = normalize_write_names(
        ["A1", "slits_mm", "lattice_a", "vbl_hgap", "stt", "A4"], ACCEPT | {"x"})
    assert "set A2" in errors["A1"]
    assert "slit.<stable_id>.horizontal_gap_mm" in errors["slits_mm"]
    assert "lattice_a_angstrom" in errors["lattice_a"]
    assert "post_mono_hgap" in errors["vbl_hgap"]
    assert "assigned twice" in errors["stt"] and "assigned twice" in errors["A4"]


class _Slit:
    def __init__(self, id, stable_id, has_height):
        self.id, self.stable_id, self.has_height = id, stable_id, has_height


def test_public_values_renames_quantities_flattens_slits_and_keeps_the_rest():
    vals = {"mtt": 40.0, "stt": 70.0, "K": 1.0, "Ei": 14.7, "K_fixed": "Kf Fixed",
            "lattice_a": 3.9, "scan_command1": "A4 1 2 1", "eta_m": 30.0,
            "curvature_modes": {"rhm": "autofocus", "rva": "held"},
            "slits_mm": {"pbl": (100.0, 90.0), "dbl_hgap": 50.0, "gone": 1.0}}
    slits = [_Slit("pbl", "pre_sample", True), _Slit("dbl_hgap", "detector", False)]

    public = public_values(vals, slits)

    assert public == {
        "mono_two_theta_deg": 40.0, "sample_two_theta_deg": 70.0, "k": 1.0,
        "incident_energy_mev": 14.7, "K_fixed": "Kf Fixed", "lattice_a_angstrom": 3.9,
        "scan_command1": "A4 1 2 1", "eta_m": 30.0,
        "curvature_modes": {"mono_horizontal_radius_m": "autofocus",
                            "analyzer_vertical_radius_m": "held"},
        "slit.pre_sample.horizontal_gap_mm": 100.0, "slit.pre_sample.vertical_gap_mm": 90.0,
        "slit.detector.horizontal_gap_mm": 50.0,
    }
    assert "mtt" in vals                                    # the input is not modified


def test_applied_radii_take_their_derived_canonical_ids():
    assert public_applied_radii({"rhm": -3.0, "rva": 0.0}) == {
        "applied_mono_horizontal_radius_m": -3.0, "applied_analyzer_vertical_radius_m": 0.0}


def test_clamped_axes_take_the_canonical_radius_ids_of_their_modes():
    public = public_values({"curvature_modes": {"rhm": "scanned"}, "curvature_clamped": ["rhm"]})
    assert public["curvature_clamped"] == ["mono_horizontal_radius_m"]
    assert public["curvature_modes"] == {"mono_horizontal_radius_m": "scanned"}
