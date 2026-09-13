# Audit — release 1.3

> **Status:** live
> **Authority:** the work queue for release 1.3 readiness; an entry is deleted by the commit that lands it

**Audited:** `669122d0` on 2026-09-13; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability, structural improvement; coverage: IN8/IN12 packages and evidence, shared TAS runtime and all four model/plugin consumers, `TAVI_PySide6.py` and instrument GUI, API/job/result seams, their caller/test closure, and Windows launch/install wiring; meter: 62% to 68%; stopped: lanes exhausted, floor waived (widening to direct callers and tests adds no new file).

**Blocks release:** the two independently confirmed branch defects below; repair the GUI energy writers first, then the API reference state.
The isolated full suite passed (1,233 tests, no skips, 117.22 seconds wall); IN8/IN12 Al scans compiled and reused binaries with nonzero detector counts, and zero-angle transmission probes transported neutrons. These checks establish runnable paths, not calibrated instrument fidelity.
**Nice to fix:** the existing [geometry-authority consolidation, entry 9](new-instruments-crystal-bending.md#9-p4--bind-instrument-geometry-to-one-authority-before-correcting-arm-lengths); no new optional entry qualified.
**Can fix afterwards:** existing ledger entries 11 (module-fixed applied-value reporting), 12 (test configuration isolation), and 14 (analytic hidden misalignment), under the [current release plan](../../WIP.md). Entry 14 is a correctness limitation: use McStas for hidden-misalignment training; analytic results must not be presented as reproducing that training. These existing entries are not duplicated here.
The release plan also requires the operator's notes review and a cold-tested, tag-pinned Windows installer with Pb phonon-map generation after tagging; that distribution work remains outstanding. This audit changes no application code.

## 1. P1 · Blocks release: GUI energy edits reverse crystal branches

- **Observed at:** `669122d0`
- **Effort:** 1–2 hours; controller energy/wavevector handlers, shared signed angle conversion, and offscreen widget acceptance; no API schema change.
- **Evidence:**
  - `TAVI_PySide6.py:1632` — real widget signals connect to the four energy/wavevector handlers.
  - `TAVI_PySide6.py:3139` — `update_all_variables` derives unsigned mono/analyser angles.
  - `TAVI_PySide6.py:3644` — `on_Ki_changed` derives unsigned mono two-theta.
  - `TAVI_PySide6.py:3678` — `on_Ei_changed` derives unsigned mono two-theta.
  - `TAVI_PySide6.py:3712` — `on_Kf_changed` derives unsigned analyser two-theta.
  - `TAVI_PySide6.py:3746` — `on_Ef_changed` derives unsigned analyser two-theta.
  - `instruments/tas_runtime.py:822` — the backend's corresponding calculation applies the instrument sense.
  - `TAVI_PySide6.py:7360` — the angle-mode template copies the GUI's raw angles.
  - `instruments/tas_runtime.py:1011` — angle-mode execution preserves those raw values.
- **Failure:** Starting from a signed Q-space solution, editing Ei or Ef to 12 meV writes +45.7994 degrees. IN12's monochromator requires -45.7994 degrees (the positive value is outside its declared travel); IN8 and IN12 analysers also require the negative branch. IN8's positive monochromator control passes. The wrong signs persist after the event loop settles and reach angle-mode execution. This is an ordinary control operation, so release notes are insufficient containment.
- **Reproduce with:** `python -B docs/audits/repro/release-1-3/gui_energy_branch.py`
- **Remedy boundary:** Make all energy-derived GUI angle writers use the selected instrument's signed conversion consistently with the runtime. Preserve deliberately entered raw angle scans; cover both mono/analyser directions and the positive-sense control rather than fixing only the Ei handler.
- **Verified:** opus CONFIRMED 2026-09-13 — independently reran the offscreen reproducer, waited through a settled event loop, and traced the resulting angle template into the shared point solve. The wrong command values are established; no quantitative transport consequence is claimed.

## 2. P1 · Blocks release: API angle defaults retain PUMA geometry

- **Observed at:** `669122d0`
- **Effort:** 2–4 hours; widget-free API launch defaults and per-instrument reference-state acceptance; no API field/schema change.
- **Evidence:**
  - `TAVI_PySide6.py:5974` — common defaults hard-code PUMA's mono/sample/analyser branches and sample angle.
  - `TAVI_PySide6.py:2709` — every API launch starts from those defaults before overlaying the request.
  - `TAVI_PySide6.py:747` — `POST /scan` uses this launch builder.
  - `TAVI_PySide6.py:939` — `POST /validate` uses the same launch builder.
  - `TAVI_PySide6.py:823` — infeasible points reject a default submission with HTTP 400.
  - `instruments/in12/plugin.py:370` — IN12 declares negative monochromator travel and its own reference angles.
  - `instruments/in8/plugin.py:246` — IN8 declares positive sample and negative analyser reference angles.
  - `TAVI_PySide6.py:8521` — angle scans execute the unpatched defaults verbatim.
- **Failure:** Submit an otherwise default API angle scan `A3 35 36 1`. IN12 inherits mtt=+41.167, stt=-71.2502, att=+41.167 and rejects both points because A1 is outside [-140, -10] degrees. IN8 accepts the same defaults but executes its sample and analyser on the opposite branches from its declared reference state. The independent four-instrument probe also confirms PANDA rejects these defaults; PUMA is the passing control. GUI state and energy-edit signals are absent from this path, so entry 1 does not repair it.
- **Reproduce with:** `python -B docs/audits/repro/release-1-3/api_angle_defaults.py`
- **Remedy boundary:** Produce a physically consistent reference launch state from the selected instrument, crystals, fixed energy and reference scattering point while retaining API independence from widgets. Do not merely substitute descriptor angle literals without reconciling their corresponding energy/HKL; verify all four instruments and both validation and execution.
- **Verified:** opus CONFIRMED 2026-09-13 — independently reran the two-instrument failure, expanded the probe to all four instruments, and traced default creation through API refusal or raw-angle execution.
