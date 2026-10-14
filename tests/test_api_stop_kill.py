"""The ``kill`` field of both stop routes and the ``stop_mode`` result field (API v2, additive).

Offscreen Qt with the real window, controller, ``TaviApiBackend`` and an API
server on an ephemeral port; no McStas.  Scans run on the analytic engine
(``engine: deterministic``).  The analytic engine's per-point call is held by a
gate, so a test stops a job while its first point is in flight, at a known
place, instead of racing a fast scan.  Stop bodies that name no ``api_version``
go through ``_request``, which sends bytes raw; the stop routes never touch the
GUI thread, so calling them from the test thread cannot deadlock.

Wall-time budget for this file: 10 s.  Every wait has a wall-clock deadline
that fails the test rather than hanging it.
"""
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("mcstasscript")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import instruments.builtin  # noqa: F401,E402  (registers built-in instruments)
import TAVI_PySide6 as cm  # noqa: E402
from instruments.registry import available_instruments, get_instrument  # noqa: E402
from tavi import deterministic_engine  # noqa: E402
from tavi.api_server import API_PREFIX, TaviApiServer  # noqa: E402
from tavi.quantities import API_VERSION  # noqa: E402
from test_api_canonical_names import Client  # noqa: E402
from test_api_server import _request  # noqa: E402

DEADLINE_S = 10.0
SCAN = "deltaE 0 14.9 0.1"   # 150 analytic points (the API's default per-job limit is 200)
SHORT = "deltaE 10 20 5"     # 3 points: runs to completion at once
TERMINAL = ("stopped", "done", "failed", "cancelled")


class Gate:
    """Wraps the analytic per-point call; every call waits until ``released`` is set."""

    def __init__(self, real):
        self.real = real
        self.entered = threading.Event()
        self.released = threading.Event()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        if not self.released.wait(DEADLINE_S):
            raise RuntimeError("the test never released the analytic point gate")
        return self.real(*args, **kwargs)


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    instrument = get_instrument("puma")
    window = cm.TAVIMainWindow(
        instrument.descriptor(), instrument_infos=available_instruments(),
        current_instrument_id="puma", save_selection=lambda _id: None)
    controller = cm.TAVIController(window, instrument, api_overrides={"disabled": True})
    controller.output_directory = str(tmp_path_factory.mktemp("stop_kill_output"))
    server = TaviApiServer("127.0.0.1", 0, None, "allow",
                           cm.TaviApiBackend(controller, cm.ApiBridge()))
    server.start()
    base = "http://127.0.0.1:%d%s" % (server._httpd.server_address[1], API_PREFIX)
    try:
        yield controller, Client(app, base), base
    finally:
        server.stop()
        controller.shutdown()
        window.deleteLater()
        app.processEvents()


def pump_until(predicate, what):
    """Pump the Qt loop until ``predicate()``: the scan thread's per-point yield waits on it."""
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("timed out after %.0f s waiting for %s" % (DEADLINE_S, what))


@pytest.fixture
def gate(api, monkeypatch):
    controller, _call, _base = api
    held = Gate(deterministic_engine.evaluate_point)
    monkeypatch.setattr(deterministic_engine, "evaluate_point", held)
    yield held
    held.released.set()
    controller.force_stop_all()
    pump_until(controller.is_idle, "the controller to go idle after the test")


def submit(call, scan=SCAN):
    status, body = call("POST", "/scan", {
        "api_version": API_VERSION, "engine": "deterministic",
        "parameters": {"H": 1.0, "K": 0.0, "L": 0.0, "scan_command1": scan}})
    assert status == 202, body
    return body["job_id"]


def job(call, job_id):
    status, body = call("GET", "/scan/%s" % job_id)
    assert status == 200, body
    return body


def wait_for(call, job_id, states, what):
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end:
        snap = job(call, job_id)
        if snap["state"] in states:
            return snap
        time.sleep(0.01)
    pytest.fail("timed out after %.0f s waiting for %s (job %s)" % (DEADLINE_S, what, job_id))


def stop_mode(snap):
    return (snap.get("result") or {}).get("stop_mode")


def running_job(call, gate, scan=SCAN):
    job_id = submit(call, scan)
    pump_until(gate.entered.is_set, "the first point of job %s" % job_id)
    assert job(call, job_id)["state"] == "running"
    return job_id


def finish(call, gate, job_id):
    gate.released.set()
    return wait_for(call, job_id, TERMINAL, "job %s to end" % job_id)


def test_plain_stop_is_graceful_and_keeps_its_shape(api, gate):
    _controller, call, _base = api
    job_id = running_job(call, gate)
    status, reply = call("POST", "/scan/%s/stop" % job_id)     # no body, no api_version
    assert status == 200
    assert reply["state"] == "running"                          # recorded, not yet done
    assert set(reply) == set(job(call, job_id)) - {"eta"}       # same snapshot shape as GET
    done = finish(call, gate, job_id)
    assert done["state"] == "stopped" and stop_mode(done) == "graceful"


def test_repeated_plain_stop_never_escalates(api, gate):
    _controller, call, _base = api
    job_id = running_job(call, gate)
    for _ in range(2):
        assert call("POST", "/scan/%s/stop" % job_id)[0] == 200
    done = finish(call, gate, job_id)
    assert done["state"] == "stopped" and stop_mode(done) == "graceful"


def test_kill_on_running_job_records_kill(api, gate):
    _controller, call, _base = api
    job_id = running_job(call, gate)
    assert call("POST", "/scan/%s/stop" % job_id, {"kill": True})[0] == 200
    done = finish(call, gate, job_id)
    assert done["state"] == "stopped" and stop_mode(done) == "kill"


def test_kill_after_graceful_stop_escalates(api, gate):
    _controller, call, _base = api
    job_id = running_job(call, gate)
    assert call("POST", "/scan/%s/stop" % job_id)[0] == 200
    assert call("POST", "/scan/%s/stop" % job_id, {"kill": True})[0] == 200
    done = finish(call, gate, job_id)
    assert stop_mode(done) == "kill"


def test_kill_on_queued_job_cancels_with_no_stop_mode(api, gate):
    _controller, call, _base = api
    first = running_job(call, gate)
    second = submit(call)
    status, reply = call("POST", "/scan/%s/stop" % second, {"kill": True})
    assert status == 200 and reply["state"] == "cancelled"
    assert stop_mode(job(call, second)) is None
    call("POST", "/scan/%s/stop" % first, {"kill": True})
    finish(call, gate, first)


def test_kill_on_finished_job_is_409(api, gate):
    _controller, call, _base = api
    gate.released.set()
    job_id = submit(call, SHORT)
    wait_for(call, job_id, TERMINAL, "the short job to finish")
    for body in ({"kill": True}, None):
        status, reply = call("POST", "/scan/%s/stop" % job_id, body)
        assert status == 409 and reply["error"]["code"] == "job_finished", reply


def test_stop_all_with_clear_queue_and_kill(api, gate):
    _controller, call, _base = api
    first = running_job(call, gate)
    second = submit(call)
    status, reply = call("POST", "/stop", {"clear_queue": True, "kill": True})
    assert status == 200
    assert reply == {"stopped": first, "cancelled": [second]}
    assert job(call, second)["state"] == "cancelled"
    done = finish(call, gate, first)
    assert done["state"] == "stopped" and stop_mode(done) == "kill"


def test_invalid_kill_is_400_and_changes_nothing(api, gate):
    controller, call, _base = api
    job_id = running_job(call, gate)
    for path, bad in (("/scan/%s/stop" % job_id, "true"), ("/scan/%s/stop" % job_id, 1),
                      ("/stop", 1), ("/stop", "false")):
        status, reply = call("POST", path, {"kill": bad})
        assert status == 400, (path, bad, reply)
        assert reply["error"]["code"] == "bad_request" and "kill" in reply["error"]["message"]
    assert job(call, job_id)["state"] == "running"
    assert not controller.stop_event.is_set()
    call("POST", "/scan/%s/stop" % job_id)
    finish(call, gate, job_id)


def test_scan_stop_ignores_every_other_body_shape(api, gate):
    _controller, call, base = api
    job_id = running_job(call, gate)
    url = base + "/scan/%s/stop" % job_id
    for raw in (b"not json", b"[1, 2]", b'{"api_version": 2, "bogus": 1}', b""):
        status, reply, _ = _request(url, method="POST", data=raw,
                                    headers={"Content-Type": "application/json"})
        assert status == 200 and reply["state"] == "running", (raw, reply)
    done = finish(call, gate, job_id)
    assert stop_mode(done) == "graceful"


def test_schema_names_kill_clear_queue_and_stop_mode(api):
    _controller, call, _base = api
    status, schema = call("GET", "/schema")
    assert status == 200 and schema["api_version"] == API_VERSION
    endpoints = {(e["method"], e["path"]): e["description"] for e in schema["endpoints"]}
    assert "'kill'" in endpoints[("POST", "/scan/{id}/stop")]
    assert "'kill'" in endpoints[("POST", "/stop")] and "'clear_queue'" in endpoints[("POST", "/stop")]
    assert "stop_mode" in endpoints[("GET", "/scan/{id}")]
