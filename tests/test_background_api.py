"""Tests for the background API surface (stage 3: API + GUI + persistence).

Pure stdlib + Qt-free, following ``test_engine_dispatch.py``: the real
importable validators are exercised directly, and the routing/status-code
contract is driven through a real ``TaviApiServer`` with a duck-typed fake
backend. The controller-side wiring (``TaviApiBackend.get_background`` /
``set_background``, ``build_api_schema``'s background block, the GUI row) is
Qt-bound -- ``TAVI_PySide6`` imports PySide6 + mcstasscript -- so it is covered
by source scans here, in the same style as ``test_fitting_dock.py``.
"""
import copy
import json
import os
import urllib.error
import urllib.request

import pytest

from tavi import background
from tavi.api_server import (
    ApiError, TaviApiServer, API_PREFIX,
    BACKGROUND_SPEC_KEYS, SCAN_BODY_KEYS, VALIDATE_BODY_KEYS,
    parse_scan_background, parse_scan_engine,
)
from tavi.scan_jobs import ScanJob


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")
SIMULATION_DOCK_PATH = os.path.join(
    REPO_ROOT, "gui", "docks", "unified_simulation_dock.py"
)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ==========================================================================
# parse_scan_background -- the real body validator
# ==========================================================================

def test_background_absent_is_none():
    assert parse_scan_background({}) is None


def test_background_null_is_none():
    # An explicit null means "no override"; the scan uses the configured profile.
    assert parse_scan_background({"background": None}) is None


def test_background_preset_form_accepted():
    spec = {"enabled": True, "preset": "flat_low", "overrides": {}}
    assert parse_scan_background({"background": spec}) == spec


def test_background_frozen_form_accepted():
    spec = {
        "enabled": True,
        "terms": [{"name": "flat", "shape": "flat", "origin": "instrument",
                   "params": {"rate": 1e-10}}],
    }
    assert parse_scan_background({"background": spec}) == spec


def test_background_non_dict_is_400():
    with pytest.raises(ApiError) as ei:
        parse_scan_background({"background": "flat_low"})
    assert ei.value.status == 400
    assert "background" in ei.value.message


def test_background_unknown_field_is_400_with_allowed_list():
    with pytest.raises(ApiError) as ei:
        parse_scan_background({"background": {"preset": "flat_low", "rate": 1.0}})
    err = ei.value
    assert err.status == 400
    assert err.code == "bad_request"
    assert err.details["unknown"] == ["rate"]
    assert err.details["allowed"] == sorted(BACKGROUND_SPEC_KEYS)


def test_background_non_dict_body_is_400():
    with pytest.raises(ApiError) as ei:
        parse_scan_background([1, 2, 3])
    assert ei.value.status == 400


def test_background_shape_check_does_not_resolve_numerics():
    # Deep validation belongs to background.resolve() on the GUI thread; the
    # shape check must not duplicate (and drift from) the preset registry.
    spec = {"enabled": True, "preset": "no_such_preset", "overrides": {}}
    assert parse_scan_background({"background": spec}) == spec
    with pytest.raises(ValueError):
        background.resolve(spec)


def test_background_in_scan_and_validate_body_keys():
    # Validate/submit parity: a body /validate accepts must be submittable.
    assert "background" in SCAN_BODY_KEYS
    assert "background" in VALIDATE_BODY_KEYS


def test_background_spec_keys_match_the_contract():
    assert BACKGROUND_SPEC_KEYS == frozenset(
        {"enabled", "preset", "overrides", "terms"}
    )


# ==========================================================================
# _launch_summary back-compatibility
# ==========================================================================

def _job(launch_state):
    return ScanJob(job_id="j-0001", source="api", launch_state=launch_state)


LEGACY_SUMMARY_KEYS = {
    "scan_command1", "scan_command2", "number_neutrons", "isolated",
    "parameters", "engine", "seed",
}


def test_launch_summary_without_background_is_unchanged():
    summary = _job({
        "vals": {"scan_command1": "H 1 2 0.5", "number_neutrons": 1e8},
        "engine": "deterministic", "seed": 3,
    })._launch_summary()
    assert set(summary) == LEGACY_SUMMARY_KEYS


def test_launch_summary_surfaces_background_when_present():
    spec = {"enabled": True, "preset": "flat_low", "overrides": {}}
    summary = _job({
        "vals": {"scan_command1": "H 1 2 0.5"},
        "engine": "deterministic",
        "background": spec,
        "background_source": "per_scan_override",
    })._launch_summary()
    assert summary["background"] == spec
    assert summary["background_source"] == "per_scan_override"
    json.dumps(summary, allow_nan=False)


# ==========================================================================
# HTTP surface (real server, fake backend)
# ==========================================================================

def _request(url, method="GET", data=None, timeout=5):
    hdrs = {}
    if data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw, status = resp.read(), resp.getcode()
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    return status, (json.loads(raw.decode("utf-8")) if raw else None)


class _BackgroundBackend:
    """Fake backend reproducing the production background contract."""

    def __init__(self):
        self.spec = {"enabled": False, "preset": "none", "overrides": {}}

    def get_health(self):
        return {"status": "ok"}

    def _state(self):
        resolved = background.resolve(self.spec)
        return {
            "spec": copy.deepcopy(self.spec),
            "resolved": background.metadata_block(resolved, "config_default"),
        }

    def get_background(self):
        return self._state()

    def set_background(self, body):
        try:
            background.resolve(body)
        except ValueError as exc:
            raise ApiError(400, "invalid_background", str(exc))
        self.spec = copy.deepcopy(body)
        return self._state()

    def submit_scan(self, body, idempotency_key=None):
        parse_scan_engine(body)
        spec = parse_scan_background(body)
        return {
            "job_id": "j-0001", "state": "queued", "position": 0,
            "background": spec,
            "background_source": (
                "per_scan_override" if spec is not None else "config_default"
            ),
        }

    def submit_validate(self, body):
        spec = parse_scan_background(body)
        resolved = background.resolve(spec if spec is not None else self.spec)
        return {
            "would_queue": True,
            "blockers": [],
            "background": {
                "enabled": bool(resolved.enabled),
                "source": (
                    "per_scan_override" if spec is not None else "config_default"
                ),
                "profile_fingerprint": background.profile_fingerprint(resolved),
                "effective_fingerprint": background.effective_fingerprint(
                    resolved, None, ()
                ),
                "sample_scale": None,
                "skipped_terms": [],
            },
        }

    def get_schema(self):
        return {
            "instrument": "puma",
            "scan_body_fields": [
                {"name": "background", "type": "object", "default": None},
            ],
            "endpoints": [
                {"method": "GET", "path": "/background"},
                {"method": "PUT", "path": "/background"},
            ],
            "background": {
                "background_schema": background.BACKGROUND_SCHEMA,
                "preset_registry_version": background.PRESET_REGISTRY_VERSION,
                "presets": background.preset_catalog(),
                "shapes": list(background.SHAPES),
                "origins": list(background.ORIGINS),
                "methods": {"analytic": "implemented", "simulated": "reserved"},
            },
        }


class _BareBackend:
    """Backend without the background methods (pre-stage-3 server)."""

    def get_health(self):
        return {"status": "ok"}


def _start(backend, mode="allow"):
    srv = TaviApiServer(host="127.0.0.1", port=0, token=None, mode=mode,
                        backend=backend)
    srv.start()
    port = srv._httpd.server_address[1]
    return srv, "http://127.0.0.1:%d%s" % (port, API_PREFIX)


def test_get_put_background_round_trip():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/background")
        assert status == 200
        assert body["spec"]["preset"] == "none"
        assert body["resolved"]["enabled"] is False

        spec = {"enabled": True, "preset": "flat_low", "overrides": {}}
        status, body = _request(base + "/background", method="PUT", data=spec)
        assert status == 200
        assert body["spec"] == spec
        assert body["resolved"]["enabled"] is True
        assert body["resolved"]["terms"][0]["shape"] == "flat"
        fingerprint = body["resolved"]["profile_fingerprint"]

        status, body = _request(base + "/background")
        assert status == 200
        assert body["spec"] == spec
        assert body["resolved"]["profile_fingerprint"] == fingerprint
    finally:
        srv.stop()


def test_put_background_rejects_unknown_top_level_key():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(
            base + "/background", method="PUT",
            data={"enabled": True, "preset": "flat_low", "rate": 1.0},
        )
        assert status == 400
        assert body["error"]["details"]["unknown"] == ["rate"]
    finally:
        srv.stop()


def test_put_background_rejects_unknown_preset_400():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/background", method="PUT",
                                data={"enabled": True, "preset": "nope"})
        assert status == 400
        assert body["error"]["code"] == "invalid_background"
    finally:
        srv.stop()


def test_put_background_readonly_is_403():
    srv, base = _start(_BackgroundBackend(), mode="readonly")
    try:
        status, body = _request(base + "/background", method="PUT",
                                data={"enabled": True, "preset": "flat_low"})
        assert status == 403
        assert body["error"]["code"] == "read_only"
        # The read stays available in read-only mode.
        assert _request(base + "/background")[0] == 200
    finally:
        srv.stop()


def test_background_methods_missing_is_501():
    srv, base = _start(_BareBackend())
    try:
        assert _request(base + "/background")[0] == 501
        assert _request(base + "/background", method="PUT",
                        data={"enabled": False})[0] == 501
    finally:
        srv.stop()


def test_background_wrong_method_is_405():
    srv, base = _start(_BackgroundBackend())
    try:
        status, _ = _request(base + "/background", method="POST",
                             data={"enabled": False})
        assert status == 405
    finally:
        srv.stop()


def test_scan_accepts_background_body_key():
    srv, base = _start(_BackgroundBackend())
    try:
        spec = {"enabled": True, "preset": "strong_elastic", "overrides": {}}
        status, body = _request(base + "/scan", method="POST",
                                data={"engine": "deterministic",
                                      "background": spec})
        assert status == 202
        assert body["background"] == spec
        assert body["background_source"] == "per_scan_override"
    finally:
        srv.stop()


def test_scan_without_background_reports_config_default():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"engine": "deterministic"})
        assert status == 202
        assert body["background"] is None
        assert body["background_source"] == "config_default"
    finally:
        srv.stop()


def test_scan_rejects_malformed_background():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/scan", method="POST",
                                data={"background": "flat_low"})
        assert status == 400
        assert body["error"]["code"] == "bad_request"

        status, body = _request(base + "/scan", method="POST",
                                data={"background": {"rate": 1.0}})
        assert status == 400
        assert body["error"]["details"]["unknown"] == ["rate"]
    finally:
        srv.stop()


def test_validate_accepts_background_and_reports_the_block():
    srv, base = _start(_BackgroundBackend())
    try:
        spec = {"enabled": True, "preset": "flat_low", "overrides": {}}
        status, body = _request(base + "/validate", method="POST",
                                data={"background": spec})
        assert status == 200
        block = body["background"]
        assert block["enabled"] is True
        assert block["source"] == "per_scan_override"
        assert set(block) >= {
            "profile_fingerprint", "effective_fingerprint",
            "sample_scale", "skipped_terms", "enabled",
        }
    finally:
        srv.stop()


def test_validate_rejects_malformed_background():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/validate", method="POST",
                                data={"background": {"rate": 1.0}})
        assert status == 400
        assert body["error"]["details"]["unknown"] == ["rate"]
    finally:
        srv.stop()


def test_schema_advertises_the_background_block():
    srv, base = _start(_BackgroundBackend())
    try:
        status, body = _request(base + "/schema")
        assert status == 200
        block = body["background"]
        assert block["background_schema"] == "tavi.background/1"
        assert block["methods"] == {"analytic": "implemented",
                                    "simulated": "reserved"}
        # Presets carry full numerics, so a client can freeze one.
        flat_low = block["presets"]["flat_low"]["terms"][0]
        assert flat_low["params"]["rate"] > 0.0
        assert set(block["shapes"]) == set(background.SHAPES)
        names = {f["name"] for f in body["scan_body_fields"]}
        assert "background" in names
        routes = {(e["method"], e["path"]) for e in body["endpoints"]}
        assert ("GET", "/background") in routes
        assert ("PUT", "/background") in routes
    finally:
        srv.stop()


# ==========================================================================
# Qt-bound wiring: source scans (see module docstring)
# ==========================================================================

def test_controller_schema_declares_the_background_block():
    source = _read(CONTROLLER_PATH)
    assert '"background": {' in source
    assert '"preset_registry_version": _background.PRESET_REGISTRY_VERSION' in source
    assert '"presets": _background.preset_catalog()' in source
    assert '"simulated": "reserved"' in source
    assert '"sample": "counts = N * diffuse_background * rate"' in source
    assert '{"method": "PUT", "path": "/background"' in source


def test_controller_injects_background_into_both_launch_builders():
    source = _read(CONTROLLER_PATH)
    # GUI builder: configured profile, config_default tag.
    assert "'background': copy.deepcopy(self.background_profile)" in source
    assert "'background_source': 'config_default'," in source
    # API builder: the shared stamping helper, alongside engine/seed/noiseless.
    assert "self._apply_background_to_launch_state(controller, launch_state, background)" in source
    assert "'per_scan_override' if background is not None else 'config_default'" in source


def test_submit_runs_the_same_background_check_as_validate():
    """Validate/submit parity: a doomed background must never reach the queue."""
    source = _read(CONTROLLER_PATH)
    submit = source.split("def _submit_scan_on_gui", 1)[1].split(
        "def submit_validate", 1)[0]
    assert "self._background_validation(" in submit
    assert 'background_block["error"]["id"]' in submit
    # The refusal is raised before the job is enqueued.
    assert submit.index("_background_validation") < submit.index(
        "controller.submit_scan_job"
    )


def test_controller_setter_and_validation_are_wired():
    source = _read(CONTROLLER_PATH)
    assert "def set_background_profile(self, spec):" in source
    assert "def background_profile_state(self):" in source
    assert "def _background_sample_scale(self, sample_key):" in source
    assert "sample_background_scale_unavailable" in source
    assert "def get_background(self):" in source
    assert "def set_background(self, body):" in source
    assert 'raise ApiError(400, "invalid_background", str(exc))' in source


def test_simulation_dock_has_the_background_row():
    source = _read(SIMULATION_DOCK_PATH)
    assert "from tavi.background import PRESETS as BACKGROUND_PRESETS" in source
    assert "self.background_enable_check" in source
    assert "self.background_preset_combo" in source
    assert "self.background_summary_label" in source
    assert "def get_background_spec(self)" in source
    assert "def set_background_display(self" in source
    # GUI edits never carry overrides -- that channel is API-only.
    assert '"overrides": {},' in source
