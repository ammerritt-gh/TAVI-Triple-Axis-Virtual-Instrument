"""A PANDA A4 scan crossing zero must reject or skip its singular point."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from _sandbox import run


def check():
    from instruments.panda.plugin import PANDAPlugin
    plugin = PANDAPlugin()
    state = plugin.default_state()
    state.monocris = state.anacris = "pg002"
    vals = {"deltaE": 0.0, "chi": 0.0,
            "curvature_modes": {axis: "autofocus" for axis in ("rhm", "rvm", "rha", "rva")}}
    failures = []
    for att in (-1.0, 0.0, 1.0):
        scans = [-74.332, 30.0, 0.0, att, 0, 0, 0, 0, 0, 0, 0]
        feasible, reason = plugin.check_point_feasibility(state, "angle", scans, vals)
        print(f"A4={att}: feasibility={feasible}, reason={reason}")
        if att != 0:
            assert feasible, f"Non-singular control point was refused: {reason}"
        if feasible:
            try:
                snapshot = plugin.compute_snapshot(
                    (scans, 0), 0, "angle", state, vals, str(Path.cwd()), variable_name1="A4")
                print(f"A4={att}: snapshot errors={snapshot.error_flags}")
                if att == 0:
                    assert snapshot.error_flags, "Singular point was neither refused nor marked for skipping"
                else:
                    assert not snapshot.error_flags, "Non-singular control point failed"
            except ZeroDivisionError as exc:
                print(f"A4={att}: snapshot raised {type(exc).__name__}: {exc}")
                failures.append(att)
    assert not failures, f"Preflight accepted {failures}, but autofocus divides by zero instead of skipping/refusing"


if __name__ == "__main__":
    run(check)
