"""Session journal: a human/LLM-readable narrative ring buffer for the API.

Pure Python, no Qt imports -- this module holds the ``SessionJournal`` used by
the GUI controller and read (without any GUI-thread hop) by the remote API's
``GET /api/v1/journal`` endpoint. It is a bounded ``deque`` guarded by a plain
lock: writers (parameter changes, job-lifecycle transitions, mode changes,
budget rejections) call ``record()`` alongside the existing SSE/activity emits;
readers call ``read()`` from an HTTP handler thread. Reads are cheap and
lock-only, so they never need to marshal onto the GUI thread.

See ``docs/API_USER_GUIDE.md`` (§5 ``GET /journal``).
"""
import datetime
import threading
from collections import deque


# Hard cap on the ``?limit=`` query parameter and the buffer depth.
JOURNAL_MAXLEN = 1000
DEFAULT_LIMIT = 100


def _iso_now():
    """Return the current local time as an ISO-8601 string at second resolution."""
    return datetime.datetime.now().isoformat(timespec="seconds")


class SessionJournal:
    """Thread-safe ring buffer of session-narrative entries.

    Each entry is ``{"ts": <ISO seconds>, "kind": <str>, "text": <str>}``.
    ``kind`` is one of ``"parameter"``, ``"job"``, ``"mode"``, ``"budget"``
    (free-form; the endpoint does not constrain it). The buffer keeps at most
    ``maxlen`` most-recent entries; ``total_recorded`` counts every entry ever
    recorded (including evicted ones) so a reader can detect gaps.
    """

    def __init__(self, maxlen=JOURNAL_MAXLEN):
        self._entries = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._total = 0

    def record(self, kind, text):
        """Append one entry (timestamped now). Thread-safe; never raises."""
        entry = {"ts": _iso_now(), "kind": str(kind), "text": str(text)}
        with self._lock:
            self._entries.append(entry)
            self._total += 1

    def read(self, limit=DEFAULT_LIMIT):
        """Return ``{"entries": [...newest last...], "total_recorded": int}``.

        ``limit`` is clamped to ``[0, JOURNAL_MAXLEN]``; the newest ``limit``
        entries are returned in chronological (oldest-first) order.
        """
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        if limit < 0:
            limit = 0
        if limit > JOURNAL_MAXLEN:
            limit = JOURNAL_MAXLEN
        with self._lock:
            total = self._total
            if limit == 0:
                entries = []
            else:
                entries = list(self._entries)[-limit:]
        # Copy each entry so a caller mutating the result cannot corrupt the
        # buffer (entries are small flat dicts).
        return {"entries": [dict(e) for e in entries], "total_recorded": total}
