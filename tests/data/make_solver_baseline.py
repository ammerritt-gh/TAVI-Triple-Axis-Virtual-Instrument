"""Regenerate tests/data/solver_baseline.json from today's solver. Run by hand, not by pytest.

    micromamba run -n tavi-dev python tests\\data\\make_solver_baseline.py

Writes nothing if any case fails to solve (see solver_baseline_cases.build_cases).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Before any tavi import: the baseline must never depend on the operator's config/.
os.environ["TAVI_CONFIG_DIR"] = tempfile.mkdtemp(prefix="tavi-solver-baseline-")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import solver_baseline_cases as cases  # noqa: E402


def main():
    recorded = {}
    for label in cases.PLUGINS:
        for name, (note, snap) in cases.build_cases(label).items():
            recorded[f"{label}/{name}"] = {"note": note, **cases.record(snap)}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    document = {
        "source_commit": commit,
        "generator": "tests/data/make_solver_baseline.py",
        "tolerance": 1e-9,
        "cases": {key: recorded[key] for key in sorted(recorded)},
    }
    out = HERE / "solver_baseline.json"
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=1)
        handle.write("\n")
    print(f"wrote {len(recorded)} cases to {out} at {commit[:12]}")


if __name__ == "__main__":
    main()
