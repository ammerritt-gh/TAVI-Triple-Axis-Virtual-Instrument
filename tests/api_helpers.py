"""Shared by the HTTP API tests: every mutating or validating request carries api_version."""
from tavi.quantities import API_VERSION

_VERSIONED = ("/parameters", "/scan", "/validate", "/background")


def with_version(url, method, data):
    """``data`` plus the ``api_version`` the write routes require; any other request is unchanged."""
    path = url.split("?")[0].rstrip("/")
    if method != "GET" and isinstance(data, dict) and path.endswith(_VERSIONED):
        return {"api_version": API_VERSION, **data}
    return data
