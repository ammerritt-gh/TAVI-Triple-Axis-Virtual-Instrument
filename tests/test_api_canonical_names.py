"""The API on canonical names, end to end: real controller, real server, real GUI-thread bridge.

A client gets canonical IDs out and may send canonical IDs or registry aliases in; a name
that means nothing now (a retired correction, an old slit name, a derived quantity), or
two names for one quantity, refuses the whole request with nothing changed. The trap is
the A-number flip: A2 is now the mono 2theta and A4 the sample 2theta.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi.api_server import API_PREFIX, TaviApiServer  # noqa: E402
from tavi.quantities import API_VERSION  # noqa: E402

OLD_NAMES = {
    "mtt", "stt", "omega", "att", "sgl", "sgu", "H", "K", "L", "qx", "qy", "qz", "deltaE",
    "Ki", "Ei", "Kf", "Ef", "rhm", "rvm", "rha", "rva", "slits_mm",
    "lattice_a", "lattice_b", "lattice_c", "lattice_alpha", "lattice_beta", "lattice_gamma",
}
SCAN = {"scan_command1": "deltaE 0 1 1"}


class Client:
    """HTTP calls from a worker thread while the main thread serves the GUI-thread bridge."""

    def __init__(self, app, base):
        self.app, self.base = app, base
        self.pool = ThreadPoolExecutor(max_workers=1)

    def __call__(self, method, path, body=None):
        future = self.pool.submit(self._send, method, path, body)
        while not future.done():
            self.app.processEvents()
            time.sleep(0.002)
        return future.result()

    def _send(self, method, path, body):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=20)
            return response.getcode(), json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("puma")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id="puma", save_selection=lambda _id: None)
    controller = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    controller.output_directory = str(tmp_path_factory.mktemp("api_output"))
    bridge = cm.ApiBridge()
    server = TaviApiServer("127.0.0.1", 0, None, "allow", cm.TaviApiBackend(controller, bridge))
    server.start()
    base = "http://127.0.0.1:%d%s" % (server._httpd.server_address[1], API_PREFIX)
    try:
        yield controller, Client(app, base)
    finally:
        server.stop()
        controller.shutdown()
        window.deleteLater()
        app.processEvents()


@pytest.fixture
def fresh(api):
    controller, call = api
    controller.set_default_parameters()
    return controller, call


def _state(call):
    """Everything a refused write must leave alone."""
    return (call("GET", "/parameters"), call("GET", "/jobs"), call("GET", "/background"))


def _patch(call, body):
    return call("PATCH", "/parameters?force=1", {"api_version": API_VERSION, **body})


def test_get_parameters_returns_canonical_ids_only(fresh):
    _controller, call = fresh
    status, parameters = call("GET", "/parameters")
    assert status == 200
    assert not OLD_NAMES & set(parameters), sorted(OLD_NAMES & set(parameters))
    assert {"mono_two_theta_deg", "sample_two_theta_deg", "sample_rotation_deg",
            "analyzer_two_theta_deg", "sample_lower_arc_deg", "sample_upper_arc_deg",
            "h", "k", "l", "energy_transfer_mev", "q_instrument_x_inv_angstrom",
            "incident_energy_mev", "final_wavevector_inv_angstrom",
            "mono_horizontal_radius_m", "analyzer_vertical_radius_m",
            "lattice_a_angstrom", "lattice_gamma_deg",
            "slit.post_mono.horizontal_gap_mm", "slit.pre_sample.vertical_gap_mm",
            "slit.detector.horizontal_gap_mm"} <= set(parameters)
    # The read-only policy is keyed by canonical radius too; PUMA has no other instrument's slits.
    assert set(parameters["curvature_modes"]) == {
        "mono_horizontal_radius_m", "mono_vertical_radius_m",
        "analyzer_horizontal_radius_m", "analyzer_vertical_radius_m"}
    assert not any(k.startswith("slit.virtual_source") for k in parameters)


def test_schema_lists_canonical_ids_and_carries_the_version(fresh):
    _controller, call = fresh
    status, schema = call("GET", "/schema")
    assert status == 200 and schema["api_version"] == API_VERSION
    names = {f["name"] for f in schema["fields"]}
    assert not OLD_NAMES & names, sorted(OLD_NAMES & names)
    assert {"mono_two_theta_deg", "sample_two_theta_deg", "slit.pre_sample.horizontal_gap_mm",
            "curvature_modes", "lock_stale"} <= names
    assert "mono_two_theta_deg" in schema["scan_variables"]


def test_schema_scan_variables_hold_only_the_slits_this_instrument_can_scan(fresh):
    # A slit scans only through a plugin binding; advertising another instrument's gap
    # invites a request the plan then refuses.
    controller, call = fresh
    _status, schema = call("GET", "/schema")
    slits = {v for v in schema["scan_variables"] if v.startswith("slit.")}
    bound = {q for q in controller.instrument.capabilities().bindings if q.startswith("slit.")}
    assert slits == bound and slits
    assert "slit.sample_exit.vertical_gap_mm" not in slits


def test_a4_sets_the_sample_two_theta_and_a2_the_mono_two_theta(fresh):
    """The flip: under the old numbering A2 was the sample 2theta and A4 the analyzer's."""
    controller, call = fresh
    idock = controller.window.instrument_dock
    mono, analyzer = float(idock.mtt_edit.text()), float(idock.att_edit.text())

    status, reply = _patch(call, {"A4": 40.0})
    assert status == 200, reply
    assert reply["applied"] == ["sample_two_theta_deg"]
    assert float(idock.stt_edit.text()) == pytest.approx(40.0)
    assert float(idock.mtt_edit.text()) == pytest.approx(mono)

    status, reply = _patch(call, {"A2": 40.0})
    assert status == 200, reply
    assert reply["applied"] == ["mono_two_theta_deg"]
    assert float(idock.mtt_edit.text()) == pytest.approx(40.0)
    assert float(idock.att_edit.text()) == pytest.approx(analyzer)


@pytest.mark.parametrize("alias, field, canonical", [
    ("mtt", "mtt_edit", "mono_two_theta_deg"), ("STT", "stt_edit", "sample_two_theta_deg"),
    ("psi", "omega_edit", "sample_rotation_deg"), ("A6", "att_edit", "analyzer_two_theta_deg"),
])
def test_aliases_keep_their_physical_meaning(fresh, alias, field, canonical):
    controller, call = fresh
    status, reply = _patch(call, {alias: 12.0})
    assert status == 200, reply
    assert reply["applied"] == [canonical]
    assert float(getattr(controller.window.instrument_dock, field).text()) == pytest.approx(12.0)


@pytest.mark.parametrize("body, name", [
    ({"kappa": 0.5}, "kappa"),                                     # a retired correction
    ({"chi": 1.0}, "chi"),
    ({"slits_mm": {"pbl": [50, 50]}}, "slits_mm"),                 # the old slit object
    ({"vbl_hgap": 0.088}, "vbl_hgap"),                             # an old slit name
    ({"lattice_a": 4.0}, "lattice_a"),                             # the old lattice spelling
    ({"A1": 20.0}, "A1"),                                          # derived only
    ({"analyzer_theta_deg": 20.0}, "analyzer_theta_deg"),
    ({"applied_mono_horizontal_radius_m": 1.0}, "applied_mono_horizontal_radius_m"),
    ({"nonsense": 1.0}, "nonsense"),
    ({"curvature_modes": {}}, "curvature_modes"),                  # read-only
    ({"slit.sample_exit.horizontal_gap_mm": 10.0}, "slit.sample_exit.horizontal_gap_mm"),
])
def test_a_name_that_means_nothing_now_refuses_the_whole_request(fresh, body, name):
    _controller, call = fresh
    before = _state(call)

    status, reply = _patch(call, {**body, "H": 1.5})   # a valid field beside it is not applied either

    assert status == 400, reply
    assert reply["error"]["details"]["applied"] == []
    assert name in reply["error"]["details"]["errors"]
    assert _state(call) == before


def test_the_replacement_is_named(fresh):
    _controller, call = fresh
    _status, reply = _patch(call, {"A1": 20.0})
    assert "set A2" in reply["error"]["details"]["errors"]["A1"]
    _status, reply = _patch(call, {"lattice_a": 4.0})
    assert "lattice_a_angstrom" in reply["error"]["details"]["errors"]["lattice_a"]
    _status, reply = _patch(call, {"vbl_hgap": 0.088})
    assert "post_mono_hgap" in reply["error"]["details"]["errors"]["vbl_hgap"]


@pytest.mark.parametrize("body", [
    {"stt": 40.0, "A4": 41.0},
    {"A4": 40.0, "sample_two_theta_deg": 41.0},
    {"omega": 10.0, "psi": 11.0},
    {"H": 1.0, "h": 1.0},
])
def test_two_names_for_one_quantity_are_refused_with_nothing_applied(fresh, body):
    _controller, call = fresh
    before = _state(call)

    status, reply = _patch(call, body)

    assert status == 400, reply
    assert set(reply["error"]["details"]["errors"]) == set(body)
    assert "assigned twice" in next(iter(reply["error"]["details"]["errors"].values()))
    assert reply["error"]["details"]["applied"] == []
    assert _state(call) == before


@pytest.mark.parametrize("path, key", [("/scan", "parameters"), ("/validate", "parameters")])
def test_the_same_refusals_guard_a_scan_body(fresh, path, key):
    _controller, call = fresh
    before = _state(call)
    for names in ({"stt": 40.0, "A4": 41.0}, {"kappa": 0.5}, {"A1": 20.0}, {"slits_mm": {}}):
        status, reply = call("POST", path, {
            "api_version": API_VERSION, key: {**SCAN, **names}})
        assert status == 400, (names, reply)
        assert _state(call) == before


@pytest.mark.parametrize("method, path, body", [
    ("PATCH", "/parameters?force=1", {"mono_two_theta_deg": 40.0}),
    ("POST", "/scan", {"parameters": SCAN}),
    ("POST", "/validate", {"parameters": SCAN}),
    ("PUT", "/background", {"catalog_version": 2, "enabled": False, "sources": {}}),
])
@pytest.mark.parametrize("version", [None, 1])
def test_a_request_without_version_2_changes_nothing(fresh, method, path, body, version):
    _controller, call = fresh
    before = _state(call)
    sent = dict(body) if version is None else {"api_version": version, **body}

    status, reply = call(method, path, sent)

    assert status == 400 and reply["error"]["code"] == "api_version_required", reply
    assert "names changed" in reply["error"]["message"]
    assert _state(call) == before


def test_a_job_reports_canonical_ids_and_the_version(fresh):
    controller, call = fresh
    status, reply = call("POST", "/scan", {
        "api_version": API_VERSION,
        "parameters": {"scan_command1": "A4 30 31 1", "number_neutrons": 1000},
        "engine": "deterministic", "noiseless": True})
    assert status == 202, reply
    job_id = reply["job_id"]
    for _ in range(600):
        status, job = call("GET", "/scan/%s/data" % job_id)
        if job["state"] in ("done", "failed", "cancelled", "stopped"):
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    assert job["api_version"] == API_VERSION
    assert job["result"]["variable_1"] == "sample_two_theta_deg"
    metadata = job["result"]["metadata"]
    assert metadata["api_version"] == API_VERSION
    assert "sample_two_theta_deg" in metadata and not OLD_NAMES & set(metadata)
    assert not OLD_NAMES & set(job["launch"]["parameters"])
    assert {"mono_horizontal_radius_m", "mono_vertical_radius_m"} <= set(
        job["launch"]["parameters"]["curvature_modes"])
    applied = job["result"]["applied_curvature"]
    assert applied and all(set(point) == {
        "applied_mono_horizontal_radius_m", "applied_mono_vertical_radius_m",
        "applied_analyzer_horizontal_radius_m", "applied_analyzer_vertical_radius_m"}
        for point in applied if point is not None)


def test_resolution_answers_at_the_requested_point_not_the_guis(fresh):
    controller, call = fresh
    query = "/resolution?h=2&k=0&l=0&energy_transfer_mev=2&method=cooper_nathans"
    status, there = call("GET", query)
    assert status == 200 and there["ok"], there
    status, aliased = call("GET", "/resolution?H=2&K=0&L=0&deltaE=2&method=cooper_nathans")
    assert aliased == there

    status, here = call("GET", "/resolution?method=cooper_nathans")   # the GUI's own point
    assert status == 200 and here["ok"], here
    assert here["fwhm"] != there["fwhm"]

    # Moving the GUI to the requested point gives the same answer as asking for it.
    status, _reply = _patch(call, {"h": 2.0, "k": 0.0, "l": 0.0, "energy_transfer_mev": 2.0})
    assert status == 200
    status, moved = call("GET", "/resolution?method=cooper_nathans")
    assert moved["fwhm"] == there["fwhm"]


@pytest.mark.parametrize("query", ["H=1&h=1", "deltaE=1&energy_transfer_mev=1", "nonsense=1", "Ei=14"])
def test_resolution_refuses_duplicate_and_unknown_names(fresh, query):
    _controller, call = fresh
    status, reply = call("GET", "/resolution?" + query)
    assert status == 400 and reply["error"]["code"] == "bad_request"
