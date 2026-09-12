"""Changed executable bending models must differ from pre-change manifest versions."""
import json
from pathlib import Path
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
repo = Path(__file__).resolve().parents[4]
before = "0528b4c8~1"  # Before the shared curvature producer/applier changes.
start = time.monotonic()


def git(*args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


assert git("merge-base", "--is-ancestor", "63e2422d", "HEAD") == ""
changed = git("diff", "--name-only", before, "HEAD", "instruments/tas_runtime.py")
assert "instruments/tas_runtime.py" in changed, "Curvature implementation no longer differs"
stale = []
for name in ("puma", "in8", "in12", "panda"):
    manifest = f"instruments/{name}/instrument.json"
    prior = json.loads(git("show", f"{before}:{manifest}"))
    with (repo / manifest).open(encoding="utf-8", newline="") as stream:
        current = json.load(stream)
    print(f"{name}: before={prior['model_version']} ({prior['model_date']}); "
          f"current={current['model_version']} ({current['model_date']})")
    if current["model_version"] == prior["model_version"]:
        stale.append(name)
print(f"Elapsed {time.monotonic()-start:.2f}s; only git reads and manifest reads")
assert not stale, f"Post-bending models retain pre-change manifest version: {stale}"
