"""Tests for three API features: per-job parameter isolation, GET /journal, and
GET /scan/{id}/plot.png.

Pure stdlib + Qt-free, but the plot tests additionally import matplotlib/numpy
(Agg only, no Qt). Like ``test_api_server.py`` / ``test_api_validation_schema.py``
these spin up a real ``TaviApiServer`` on an ephemeral port with a duck-typed
fake backend and drive the HTTP surface.

``tavi.journal.SessionJournal`` and ``tavi.plot_render.render_scan_plot_png`` are
Qt-free and imported/exercised **directly** here, so the journal ring buffer and
the real PNG renderer are covered end to end.

The isolation logic lives in ``TaviApiBackend._submit_scan_on_gui`` inside
``TAVI_PySide6.py``, which imports ``mcstasscript``/PySide6 at module top and
cannot be imported on this machine. As in ``test_api_validation_schema.py``, the
production snapshot/restore contract is reproduced by a fake backend driven over
HTTP; the real method is covered by ``py_compile``. The fake below mirrors the
production restore predicate exactly: restore the pre-patch snapshot when the
submit is isolated (always) OR when it failed.
"""
import json
import urllib.error
import urllib.request

from tavi.api_server import ApiError, TaviApiServer, API_PREFIX
from tavi.journal import SessionJournal, JOURNAL_MAXLEN
from tavi.plot_render import render_scan_plot_png, NoPlotData
from tavi.scan_jobs import JobRegistry, JobState, ScanJob, ScanResult


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

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
        ctype = resp.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        ctype = e.headers.get("Content-Type")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        body = None
    return status, body, raw, ctype


def _start(backend, mode="allow"):
    srv = TaviApiServer(host="127.0.0.1", port=0, token=None, mode=mode,
                        backend=backend)
    srv.start()
    port = srv._httpd.server_address[1]
    base = "http://127.0.0.1:%d%s" % (port, API_PREFIX)
    return srv, base


# ==========================================================================
# SessionJournal (direct, no HTTP)
# ==========================================================================

def test_journal_record_and_read_newest_last():
    j = SessionJournal()
    j.record("job", "j-0001: queued")
    j.record("parameter", "api: set Ei")
    j.record("job", "j-0001: started")
    out = j.read()
    assert out["total_recorded"] == 3
    texts = [e["text"] for e in out["entries"]]
    assert texts == ["j-0001: queued", "api: set Ei", "j-0001: started"]
    # Every entry carries ts/kind/text.
    for e in out["entries"]:
        assert set(e) == {"ts", "kind", "text"}
        assert isinstance(e["ts"], str) and e["ts"]


def test_journal_limit_returns_newest_slice():
    j = SessionJournal()
    for i in range(10):
        j.record("job", "e%d" % i)
    out = j.read(limit=3)
    assert [e["text"] for e in out["entries"]] == ["e7", "e8", "e9"]
    assert out["total_recorded"] == 10


def test_journal_limit_zero_returns_empty_but_total_kept():
    j = SessionJournal()
    j.record("mode", "x")
    out = j.read(limit=0)
    assert out["entries"] == []
    assert out["total_recorded"] == 1


def test_journal_ring_buffer_cap_evicts_oldest():
    j = SessionJournal(maxlen=5)
    for i in range(12):
        j.record("job", "e%d" % i)
    out = j.read(limit=JOURNAL_MAXLEN)
    # Only the last 5 survive; total counts every record ever made.
    assert [e["text"] for e in out["entries"]] == ["e7", "e8", "e9", "e10", "e11"]
    assert out["total_recorded"] == 12


def test_journal_limit_clamped_to_cap():
    j = SessionJournal()
    j.record("job", "x")
    # A huge limit is clamped, not an error.
    out = j.read(limit=10 ** 9)
    assert out["total_recorded"] == 1
    assert len(out["entries"]) == 1


# ==========================================================================
# GET /journal endpoint
# ==========================================================================

class JournalBackend:
    """Fake backend delegating get_journal to a real SessionJournal."""

    def __init__(self):
        self.journal = SessionJournal()

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}

    def get_journal(self, limit=100):
        return self.journal.read(limit)


def test_journal_endpoint_shape():
    backend = JournalBackend()
    backend.journal.record("job", "j-0001: queued (source: api)")
    backend.journal.record("mode", "access mode set to 'allow'")
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/journal")
        assert status == 200
        assert body["total_recorded"] == 2
        assert isinstance(body["entries"], list)
        assert body["entries"][-1]["text"] == "access mode set to 'allow'"
        assert body["entries"][-1]["kind"] == "mode"
    finally:
        srv.stop()


def test_journal_endpoint_limit_param():
    backend = JournalBackend()
    for i in range(20):
        backend.journal.record("job", "e%d" % i)
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/journal?limit=4")
        assert status == 200
        assert [e["text"] for e in body["entries"]] == ["e16", "e17", "e18", "e19"]
        assert body["total_recorded"] == 20
    finally:
        srv.stop()


def test_journal_endpoint_invalid_limit_400():
    backend = JournalBackend()
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/journal?limit=abc")
        assert status == 400
        assert body["error"]["code"] == "bad_request"
    finally:
        srv.stop()


def test_journal_endpoint_allowed_in_readonly():
    backend = JournalBackend()
    backend.journal.record("job", "hi")
    srv, base = _start(backend, mode="readonly")
    try:
        status, body, _raw, _ct = _request(base + "/journal")
        assert status == 200
        assert body["total_recorded"] == 1
    finally:
        srv.stop()


def test_journal_endpoint_post_405():
    backend = JournalBackend()
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/journal", method="POST",
                                            data={})
        assert status == 405
        assert body["error"]["code"] == "method_not_allowed"
    finally:
        srv.stop()


# ==========================================================================
# render_scan_plot_png (direct)
# ==========================================================================

def _result_1d(counts):
    return {
        "mode": "1D", "variable_1": "H", "variable_2": None,
        "scan_values_1": [1.99, 2.0, 2.01, 2.02, 2.03],
        "scan_values_2": None,
        "valid_mask_1": [True] * 5, "valid_mask_2d": None,
        "counts": counts, "counts_grid": None,
    }


def _result_2d(grid):
    return {
        "mode": "2D", "variable_1": "H", "variable_2": "K",
        "scan_values_1": [1.0, 2.0, 3.0],
        "scan_values_2": [0.0, 0.5],
        "valid_mask_1": None, "valid_mask_2d": [[True] * 3] * 2,
        "counts": None, "counts_grid": grid,
    }


def test_render_1d_returns_png_bytes():
    png = render_scan_plot_png(_result_1d([5.0, 12.0, 31.0, 18.0, 7.0]), "j-0004")
    assert isinstance(png, (bytes, bytearray))
    assert png[:8] == _PNG_MAGIC


def test_render_1d_with_missing_points_still_renders():
    # Skipped/unmeasured points are absent (None); the rest must still plot.
    png = render_scan_plot_png(_result_1d([None, 12.0, None, 18.0, None]), "j-1")
    assert png[:8] == _PNG_MAGIC


def test_render_2d_returns_png_bytes():
    grid = [[1.0, 5.0, 2.0], [3.0, 9.0, 4.0]]  # [row=y=K][col=x=H]
    png = render_scan_plot_png(_result_2d(grid), "j-0007")
    assert png[:8] == _PNG_MAGIC


def test_render_2d_with_holes_renders():
    grid = [[None, 5.0, None], [3.0, None, 4.0]]
    png = render_scan_plot_png(_result_2d(grid), "j-2")
    assert png[:8] == _PNG_MAGIC


def test_render_no_result_raises_nodata():
    try:
        render_scan_plot_png(None, "j-9")
    except NoPlotData:
        pass
    else:
        raise AssertionError("expected NoPlotData")


def test_render_all_none_1d_raises_nodata():
    try:
        render_scan_plot_png(_result_1d([None, None, None, None, None]), "j-9")
    except NoPlotData:
        pass
    else:
        raise AssertionError("expected NoPlotData")


def test_render_all_none_2d_raises_nodata():
    try:
        render_scan_plot_png(_result_2d([[None, None, None], [None, None, None]]),
                             "j-9")
    except NoPlotData:
        pass
    else:
        raise AssertionError("expected NoPlotData")


def test_render_png_is_512_square():
    # figsize 5.12 x 5.12 @ dpi 100 -> 512x512. Parse the PNG IHDR dims.
    png = render_scan_plot_png(_result_1d([1.0, 2.0, 3.0, 4.0, 5.0]), "j-1")
    # IHDR width/height are big-endian uint32 at byte offsets 16 and 20.
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (width, height) == (512, 512)


# ==========================================================================
# GET /scan/{id}/plot.png endpoint
# ==========================================================================

class PlotBackend:
    """Fake backend rendering real PNGs off stored ScanResult arrays."""

    def __init__(self):
        self.registry = JobRegistry()

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return {}

    def _add_job(self, result):
        job = ScanJob(job_id=self.registry.next_id(), source="api",
                      launch_state={"vals": {}})
        job.result = result
        self.registry.add(job)
        return job

    def add_1d(self, counts):
        return self._add_job(ScanResult(
            mode="1D", variable_1="H", variable_2=None,
            scan_values_1=[1.99, 2.0, 2.01, 2.02, 2.03], scan_values_2=None,
            valid_mask_1=[True] * 5, valid_mask_2d=None,
            counts=counts, counts_grid=None,
        ))

    def add_2d(self, grid):
        return self._add_job(ScanResult(
            mode="2D", variable_1="H", variable_2="K",
            scan_values_1=[1.0, 2.0, 3.0], scan_values_2=[0.0, 0.5],
            valid_mask_1=None, valid_mask_2d=[[True] * 3] * 2,
            counts=None, counts_grid=grid,
        ))

    def add_empty(self):
        job = ScanJob(job_id=self.registry.next_id(), source="api",
                      launch_state={"vals": {}})
        # Queued job: no result yet.
        self.registry.add(job)
        return job

    def get_job_plot_png(self, job_id):
        job = self.registry.get(job_id)
        if job is None:
            raise ApiError(404, "unknown_job", "Unknown job id: %s" % job_id)
        snap = job.snapshot(include_data=True)
        result = snap.get("result")
        try:
            return render_scan_plot_png(result, job_id)
        except NoPlotData as exc:
            raise ApiError(409, "no_data", str(exc))


def test_plot_endpoint_1d_returns_png():
    backend = PlotBackend()
    job = backend.add_1d([5.0, 12.0, 31.0, 18.0, 7.0])
    srv, base = _start(backend)
    try:
        status, _body, raw, ctype = _request(base + "/scan/%s/plot.png" % job.job_id)
        assert status == 200
        assert ctype == "image/png"
        assert raw[:8] == _PNG_MAGIC
    finally:
        srv.stop()


def test_plot_endpoint_2d_returns_png():
    backend = PlotBackend()
    job = backend.add_2d([[1.0, 5.0, 2.0], [3.0, 9.0, 4.0]])
    srv, base = _start(backend)
    try:
        status, _body, raw, ctype = _request(base + "/scan/%s/plot.png" % job.job_id)
        assert status == 200
        assert ctype == "image/png"
        assert raw[:8] == _PNG_MAGIC
    finally:
        srv.stop()


def test_plot_endpoint_unknown_job_404():
    backend = PlotBackend()
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/scan/nope/plot.png")
        assert status == 404
        assert body["error"]["code"] == "unknown_job"
    finally:
        srv.stop()


def test_plot_endpoint_no_data_409():
    backend = PlotBackend()
    job = backend.add_empty()
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/scan/%s/plot.png" % job.job_id)
        assert status == 409
        assert body["error"]["code"] == "no_data"
    finally:
        srv.stop()


def test_plot_endpoint_allowed_in_readonly():
    backend = PlotBackend()
    job = backend.add_1d([5.0, 12.0, 31.0, 18.0, 7.0])
    srv, base = _start(backend, mode="readonly")
    try:
        status, _body, raw, ctype = _request(base + "/scan/%s/plot.png" % job.job_id)
        assert status == 200
        assert raw[:8] == _PNG_MAGIC
    finally:
        srv.stop()


def test_plot_endpoint_post_405():
    backend = PlotBackend()
    job = backend.add_1d([1.0, 2.0, 3.0, 4.0, 5.0])
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(base + "/scan/%s/plot.png" % job.job_id,
                                            method="POST", data={})
        assert status == 405
    finally:
        srv.stop()


# ==========================================================================
# Per-job parameter isolation (contract reproduction)
# ==========================================================================

class FakeGuiController:
    """Minimal stand-in for TAVIController's parameter surface.

    ``widgets`` is the simulated live GUI state; ``apply_parameters`` mutates it
    and ``get_gui_values`` reads it, exactly like the production controller's
    contract that ``_submit_scan_on_gui`` relies on.
    """

    def __init__(self, values):
        self.widgets = dict(values)
        self.messages = []

    def get_gui_values(self):
        return dict(self.widgets)

    def apply_parameters(self, patch):
        applied, errors = {}, {}
        for k, v in patch.items():
            if k == "BAD":
                errors[k] = "invalid value"
                continue
            self.widgets[k] = v
            applied[k] = v
        return applied, errors

    def print_to_message_center(self, msg):
        self.messages.append(msg)


class IsolationBackend:
    """Fake backend reproducing the production isolated-submit contract.

    Mirrors ``TaviApiBackend._submit_scan_on_gui``'s snapshot/restore predicate:
    snapshot exactly the patched fields, apply the patch, (maybe) fail, and in a
    ``finally`` restore the snapshot when ``isolated`` OR the submit failed. A
    successful non-isolated submit leaves the patch applied. ``force_fail`` in
    the body simulates a post-patch validation/budget rejection.
    """

    def __init__(self, controller):
        self.controller = controller
        self.registry = JobRegistry()

    def get_health(self):
        return {"status": "ok"}

    def get_state(self):
        return {"state": "idle"}

    def get_parameters(self):
        return self.controller.get_gui_values()

    def submit_scan(self, body, idempotency_key=None):
        controller = self.controller
        patch = body.get("parameters") or {}
        isolated = bool(body.get("isolated", False))
        force_fail = bool(body.get("force_fail", False))

        saved = None
        if patch:
            current = controller.get_gui_values()
            saved = {k: current[k] for k in patch if k in current}

        success = False
        try:
            if patch:
                applied, errors = controller.apply_parameters(patch)
                if errors:
                    raise ApiError(400, "invalid_parameters", "bad field",
                                   details={"errors": errors})
            if force_fail:
                raise ApiError(400, "scan_validation", "simulated failure")

            job = ScanJob(job_id=self.registry.next_id(), source="api",
                          launch_state={"vals": dict(controller.widgets),
                                        "isolated": isolated})
            self.registry.add(job)
            success = True
            return {"job_id": job.job_id, "state": "queued",
                    "isolated": isolated}
        finally:
            if saved is not None and (isolated or not success):
                controller.apply_parameters(saved)


_BASE_VALUES = {"H": 2.0, "K": 0.0, "L": 0.0, "Ei": 14.0}


def test_isolated_success_restores_widgets():
    controller = FakeGuiController(_BASE_VALUES)
    backend = IsolationBackend(controller)
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(
            base + "/scan", method="POST",
            data={"parameters": {"H": 3.0}, "isolated": True})
        assert status == 202
        assert body["isolated"] is True
        # Widget restored to pre-patch value.
        assert controller.widgets["H"] == 2.0
        # Job was queued with the patched frozen launch state.
        job = backend.registry.get(body["job_id"])
        assert job.launch_state["vals"]["H"] == 3.0
        assert job.snapshot()["launch"]["isolated"] is True
    finally:
        srv.stop()


def test_isolated_failure_restores_widgets():
    controller = FakeGuiController(_BASE_VALUES)
    backend = IsolationBackend(controller)
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(
            base + "/scan", method="POST",
            data={"parameters": {"H": 3.0}, "isolated": True,
                  "force_fail": True})
        assert status == 400
        assert body["error"]["code"] == "scan_validation"
        assert controller.widgets["H"] == 2.0  # restored despite failure
        assert backend.registry.recent() == []
    finally:
        srv.stop()


def test_non_isolated_failure_restores_patch():
    # The documented bug fix: a FAILED non-isolated submit must NOT leave the
    # inline patch applied.
    controller = FakeGuiController(_BASE_VALUES)
    backend = IsolationBackend(controller)
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(
            base + "/scan", method="POST",
            data={"parameters": {"H": 3.0}, "force_fail": True})
        assert status == 400
        assert controller.widgets["H"] == 2.0  # patch rolled back on failure
    finally:
        srv.stop()


def test_non_isolated_success_keeps_patch():
    # Back-compat: a SUCCESSFUL non-isolated submit keeps global mutation.
    controller = FakeGuiController(_BASE_VALUES)
    backend = IsolationBackend(controller)
    srv, base = _start(backend)
    try:
        status, body, _raw, _ct = _request(
            base + "/scan", method="POST",
            data={"parameters": {"H": 3.0}})
        assert status == 202
        assert body["isolated"] is False
        assert controller.widgets["H"] == 3.0  # patch remains applied
        job = backend.registry.get(body["job_id"])
        assert job.snapshot()["launch"]["isolated"] is False
    finally:
        srv.stop()
