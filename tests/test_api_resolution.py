"""Unit tests for GET /resolution routing + the launch.parameters enrichment.

Pure stdlib, no Qt. Follows the fake-backend pattern from
``tests/test_api_server.py``: a real ``TaviApiServer`` on an ephemeral port with a
duck-typed backend exposing ``get_resolution``. The real GUI backend
(``TaviApiBackend.get_resolution``) needs Qt/mcstasscript and is not exercised
here. The launch.parameters pass-through is checked against the Qt-free
``ScanJob._launch_summary`` (see ``tests/test_scan_jobs.py``).
"""
import json
import urllib.error
import urllib.request

import pytest

from tavi.api_server import ApiError, TaviApiServer, API_PREFIX
from tavi.scan_jobs import ScanJob


# A representative serialized ResolutionResult (as get_resolution would return).
CANNED_RESOLUTION = {
    "ok": True,
    "reason": None,
    "method": "cooper_nathans",
    "cn_valid": True,
    "warnings": [],
    "invalidations": [],
    "r0": None,
    "matrix": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
               [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
    "fwhm": {"dq_par": 0.03, "dq_perp": 0.02, "dq_z": 0.05, "dE": 0.9},
    "bragg": {"dq_par": 0.01, "dq_perp": 0.01, "dq_z": 0.02, "dE": 0.4},
    "principal_axes": {"eigenvalues": [1.0], "fwhm": [2.35], "eigenvectors": [[1, 0, 0, 0]]},
    "vanadium_fwhm_meV": 0.9,
    "projections": {},
    "basis": ["dQ_par", "dQ_perp", "dQ_z", "dE"],
    "config": {"provenance": {"senses": {"sm": 1, "ss": -1, "sa": 1}}},
    "provenance": {"matrix_convention": "FWHM-normalized precision"},
}


class ResolutionBackend:
    """Duck-typed backend with a canned get_resolution + recorded calls."""

    def __init__(self):
        self.calls = []

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}

    def get_resolution(self, query):
        self.calls.append(("get_resolution", query))
        return dict(CANNED_RESOLUTION)


class NotSupportedBackend(ResolutionBackend):
    """Backend whose instrument has no resolution_config -> clean ok:false."""

    def get_resolution(self, query):
        self.calls.append(("get_resolution", query))
        return {"ok": False, "reason": "resolution not supported for this instrument"}


class NoResolutionBackend:
    """Backend lacking get_resolution entirely -> 501 not_implemented."""

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}


def _start_server(backend=None, token=None, mode="allow"):
    backend = backend if backend is not None else ResolutionBackend()
    server = TaviApiServer(
        host="127.0.0.1", port=0, token=token, mode=mode, backend=backend,
    )
    server.start()
    port = server._httpd.server_address[1]
    base = "http://127.0.0.1:%d%s" % (port, API_PREFIX)
    return server, base


def _request(url, method="GET", data=None, headers=None, timeout=5):
    hdrs = dict(headers or {})
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.getcode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        body = None
    return status, body


@pytest.fixture
def server():
    srv, base = _start_server()
    try:
        yield srv, base, srv.backend
    finally:
        srv.stop()


# ==========================================================================
# Routing + query parsing
# ==========================================================================

def test_resolution_routes_to_backend_and_returns_dict(server):
    _srv, base, backend = server
    status, body = _request(
        base + "/resolution?H=2&K=0&L=0&deltaE=1.5&method=cooper_nathans")
    assert status == 200
    assert body == CANNED_RESOLUTION
    # The backend saw parsed floats + the method string.
    assert backend.calls == [("get_resolution", {
        "H": 2.0, "K": 0.0, "L": 0.0, "deltaE": 1.5, "method": "cooper_nathans"})]


def test_resolution_defaults_when_params_absent(server):
    _srv, base, backend = server
    status, body = _request(base + "/resolution")
    assert status == 200
    # Omitted floats -> None (backend fills GUI defaults); method -> "auto".
    assert backend.calls == [("get_resolution", {
        "H": None, "K": None, "L": None, "deltaE": None, "method": "auto"})]


def test_resolution_partial_params(server):
    _srv, base, backend = server
    status, _body = _request(base + "/resolution?H=1.0&deltaE=3")
    assert status == 200
    assert backend.calls == [("get_resolution", {
        "H": 1.0, "K": None, "L": None, "deltaE": 3.0, "method": "auto"})]


def test_resolution_bad_float_400(server):
    _srv, base, _b = server
    status, body = _request(base + "/resolution?H=notanumber")
    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_resolution_bad_method_400(server):
    _srv, base, _b = server
    status, body = _request(base + "/resolution?method=bogus")
    assert status == 400
    assert body["error"]["code"] == "bad_request"


def test_resolution_wrong_method_405(server):
    _srv, base, _b = server
    status, body = _request(base + "/resolution", method="POST", data={})
    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"


# ==========================================================================
# Access-mode matrix (read-only allowed; auth-locked blocked)
# ==========================================================================

def test_resolution_allowed_in_readonly_mode():
    # /resolution never mutates -> allowed in read-only mode (like /state).
    srv, base = _start_server(mode="readonly")
    try:
        status, body = _request(base + "/resolution?H=2")
        assert status == 200
        assert body["ok"] is True
    finally:
        srv.stop()


def test_resolution_blocked_when_auth_locked():
    # A token-locked server (API access effectively "off" without the token)
    # rejects /resolution with 401 before reaching the backend.
    srv, base = _start_server(token="s3cret")
    try:
        status, body = _request(base + "/resolution?H=2")
        assert status == 401
        assert body["error"]["code"] == "unauthorized"
        # With the bearer token it goes through.
        status2, _b = _request(
            base + "/resolution?H=2", headers={"Authorization": "Bearer s3cret"})
        assert status2 == 200
    finally:
        srv.stop()


# ==========================================================================
# ok:false paths (refusal / not-supported) stay HTTP 200
# ==========================================================================

def test_resolution_not_supported_returns_ok_false_200():
    srv, base = _start_server(backend=NotSupportedBackend())
    try:
        status, body = _request(base + "/resolution?H=2")
        assert status == 200
        assert body["ok"] is False
        assert body["reason"] == "resolution not supported for this instrument"
    finally:
        srv.stop()


def test_resolution_absent_backend_method_501():
    srv, base = _start_server(backend=NoResolutionBackend())
    try:
        status, body = _request(base + "/resolution?H=2")
        assert status == 501
        assert body["error"]["code"] == "not_implemented"
    finally:
        srv.stop()


# ==========================================================================
# launch.parameters enrichment pass-through (Qt-free, via ScanJob summary)
# ==========================================================================

def test_launch_summary_passes_new_resolution_parameter_keys():
    # The GUI-side enrichment injects these flat keys into the frozen vals; here
    # we verify they survive _serializable_params into the launch summary that
    # every job's JSON exposes to downstream consumers (ISAR).
    enriched_vals = {
        "scan_command1": "H 1.9 2.1 0.05",
        "number_neutrons": 1e6,
        "eta_m": 30.0, "eta_a": 30.0, "eta_s": 30.0,
        "sense_m": 1, "sense_s": -1, "sense_a": 1,
        "beta_1": 120.0, "beta_2": 120.0, "beta_3": 120.0, "beta_4": 120.0,
        "sample_key": "Al_phonon_DFT",
        "temperature": 300.0,
    }
    job = ScanJob(job_id="j-0001", source="api",
                  launch_state={"vals": enriched_vals})
    params = job.snapshot()["launch"]["parameters"]
    for key, value in enriched_vals.items():
        assert params[key] == value
    # Whole snapshot must remain strict JSON (no NaN/Inf, no leaked objects).
    json.dumps(job.snapshot(), allow_nan=False)


def test_launch_summary_tolerates_none_temperature():
    # temperature is None when the sample carries no 'T' property; it must still
    # serialize cleanly (null) rather than being dropped.
    job = ScanJob(job_id="j-0002", source="api",
                  launch_state={"vals": {"temperature": None, "eta_m": 25.0}})
    params = job.snapshot()["launch"]["parameters"]
    assert params["temperature"] is None
    assert params["eta_m"] == 25.0
