"""Every mutating or validating request must carry ``"api_version": 2`` (Qt-free, fake backend).

The A-number flip (A2 is now the mono 2theta, A4 the sample 2theta) is only safe if an
old client is refused rather than reinterpreted, so a missing or different version is a
400 before the backend sees the request: nothing is applied, queued or replaced.
"""
import json
import urllib.error
import urllib.request

import pytest

from tavi.api_server import API_PREFIX, TaviApiServer
from tavi.quantities import API_VERSION

WRITES = [
    ("PATCH", "/parameters", {"mono_two_theta_deg": 40.0}),
    ("POST", "/scan", {"parameters": {"scan_command1": "A4 10 20 1"}}),
    ("POST", "/validate", {"parameters": {"scan_command1": "A4 10 20 1"}}),
    ("PUT", "/background", {"catalog_version": 2, "enabled": False, "sources": {}}),
]


class RecordingBackend:
    """Duck-typed backend that records what reached it."""

    def __init__(self):
        self.calls = []

    def patch_parameters(self, patch, force):
        self.calls.append(("patch_parameters", patch))
        return {"applied": list(patch), "errors": {}}

    def submit_scan(self, body, idempotency_key=None):
        self.calls.append(("submit_scan", body))
        return {"job_id": "j-0001", "state": "queued"}

    def submit_validate(self, body):
        self.calls.append(("submit_validate", body))
        return {"would_queue": True, "blockers": []}

    def set_background(self, body):
        self.calls.append(("set_background", body))
        return {"spec": body, "resolved": {}}

    def get_resolution(self, query):
        self.calls.append(("get_resolution", query))
        return {"ok": True}


@pytest.fixture
def served():
    backend = RecordingBackend()
    server = TaviApiServer(host="127.0.0.1", port=0, token=None, mode="allow", backend=backend)
    server.start()
    base = "http://127.0.0.1:%d%s" % (server._httpd.server_address[1], API_PREFIX)
    try:
        yield base, backend
    finally:
        server.stop()


def _send(base, method, path, body):
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode("utf-8"), method=method,
        headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(request, timeout=5)
        return response.getcode(), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


@pytest.mark.parametrize("method, path, body", WRITES, ids=[w[1] for w in WRITES])
@pytest.mark.parametrize("version", [None, 1, 3, "2", 2.0, True])
def test_a_missing_or_other_version_is_refused_before_the_backend(served, method, path, body, version):
    base, backend = served
    sent = dict(body) if version is None else {"api_version": version, **body}

    status, reply = _send(base, method, path, sent)

    assert status == 400, reply
    assert reply["error"]["code"] == "api_version_required"
    message = reply["error"]["message"]
    assert '"api_version": 2' in message and "names changed" in message
    assert "mono_two_theta_deg" in message
    assert backend.calls == []


@pytest.mark.parametrize("method, path, body", WRITES, ids=[w[1] for w in WRITES])
def test_the_right_version_passes_and_is_not_a_parameter(served, method, path, body):
    base, backend = served

    status, _reply = _send(base, method, path, {"api_version": API_VERSION, **body})

    assert status in (200, 202)
    (_name, received), = backend.calls
    assert "api_version" not in received          # the version is no parameter field
    assert received == body


def test_a_get_needs_no_version(served):
    base, backend = served
    request = urllib.request.Request(base + "/resolution?h=1", method="GET")
    assert urllib.request.urlopen(request, timeout=5).getcode() == 200
    assert backend.calls == [("get_resolution", {
        "h": 1.0, "k": None, "l": None, "energy_transfer_mev": None, "method": "auto"})]
