"""The shared documentation checker, run as a test so documentation drift fails the suite.

The checker (Agentic-Control-Scheme/bin/doc_check.py) is stdlib-only and lives outside
this repository. Its path comes from the DOC_CHECK environment variable, falling back to
the maintainer's checkout. Where neither resolves to a file the test skips with the reason
printed (the suite runs with -ra), because a fresh clone of the public mirror must not go
red for an environmental reason. See tests/README.md.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

DEFAULT_CHECKER = Path(r"C:\Users\AMM\Documents\Github\Agentic-Control-Scheme\bin\doc_check.py")
ROOT = Path(__file__).resolve().parents[1]


def _checker() -> Path:
    override = os.environ.get("DOC_CHECK")
    candidate = Path(override) if override else DEFAULT_CHECKER
    if not candidate.is_file():
        pytest.skip(f"shared doc checker not found at {candidate}; set DOC_CHECK to run this test")
    return candidate


def test_documentation_does_not_drift():
    checker = _checker()
    result = subprocess.run(
        [sys.executable, str(checker), "--root", str(ROOT)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
