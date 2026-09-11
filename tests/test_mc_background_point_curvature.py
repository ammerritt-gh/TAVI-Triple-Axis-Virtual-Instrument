"""Regression: the McStas engine's background sigma widths (``run_simulation``'s
McStas branch, background overlay) must solve the resolution model with THIS
point's own applied curvature radii, not the frozen launch-time ``vals``.

Same defect, same fix, as the deterministic engine's per-point kernel
(``tests/test_deterministic_engine_point_curvature.py``) and ``GET
/resolution`` (``tests/test_resolution_point_curvature.py``): a resolution-
shaped background planted on a point must use that point's own geometry, not
whichever radii the frozen launch dict happened to carry -- otherwise the
neutron simulation can be right while the background planted on top of it is
computed for a different point's curvature.

Static source check, matching this branch's existing test style
(``tests/test_mc_background.py``): the McStas path only exercises real
detector files from a compiled McStas binary, which this suite does not run
(mcstasscript build tools, minutes per case) -- ``test_mc_background.py``'s
own coverage of this exact branch (e.g.
``test_mc_resolution_solve_is_gated_for_elastic_and_powder_sources``) is
string-based for the same reason.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROLLER_PATH = os.path.join(REPO_ROOT, "TAVI_PySide6.py")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _mc_branch(source):
    body = source.split("def run_simulation", 1)[1]
    return body.split("return self._run_scan_deterministic", 1)[1]


def test_background_resolution_solve_uses_this_points_own_applied_radii():
    branch = _mc_branch(_read(CONTROLLER_PATH))
    assert "background_resolution = _resolution(" in branch
    assert "if background_needs_sigma_q or background_needs_sigma_e:" in branch
    call_tail = branch.split(
        "if background_needs_sigma_q or background_needs_sigma_e:", 1
    )[1]
    call_tail = call_tail.split("if background_needs_sigma_q:", 1)[0]

    # Applied radii come from THIS point's own snapshot metadata, not the
    # frozen launch vals -- the same magnitude-preserving overlay the
    # deterministic engine and GET /resolution use.
    assert "metadata[axis]" in call_tail, call_tail
    assert "_vals_with_point_curvature(vals, point_radii)" in call_tail, call_tail

    # The regression this guards: resolution_config's first argument at this
    # call site must never again be the bare frozen ``vals``.
    resolution_config_call = re.search(
        r"self\.instrument\.resolution_config\(\s*(\S+)", call_tail
    )
    assert resolution_config_call is not None, call_tail
    assert resolution_config_call.group(1) != "vals,", call_tail
