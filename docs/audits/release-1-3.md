# Audit — release 1.3

> **Status:** live
> **Authority:** the work queue for release 1.3 readiness; an entry is deleted by the commit that lands it

**Audited:** `669122d0` on 2026-09-13; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability, structural improvement; coverage: IN8/IN12 packages and evidence, shared TAS runtime and all four model/plugin consumers, `TAVI_PySide6.py` and instrument GUI, API/job/result seams, their caller/test closure, and Windows launch/install wiring; meter: 62% to 68%; stopped: lanes exhausted, floor waived (widening to direct callers and tests adds no new file).

**Blocks release:** none open. The two confirmed branch defects (GUI energy writers reversing crystal branches; API and GUI angle defaults retaining PUMA geometry) landed on branch `worktree-release-1-3-blockers` with per-instrument acceptance tests; the reproducers under `repro/release-1-3/` exit 0.
The isolated full suite passed (1,233 tests, no skips, 117.22 seconds wall); IN8/IN12 Al scans compiled and reused binaries with nonzero detector counts, and zero-angle transmission probes transported neutrons. These checks establish runnable paths, not calibrated instrument fidelity.
**Nice to fix:** the existing [geometry-authority consolidation, entry 9](new-instruments-crystal-bending.md#9-p4--bind-instrument-geometry-to-one-authority-before-correcting-arm-lengths); no new optional entry qualified.
**Can fix afterwards:** existing ledger entries 11 (module-fixed applied-value reporting), 12 (test configuration isolation), and 14 (analytic hidden misalignment), under the [current release plan](../../WIP.md). Entry 14 is a correctness limitation: use McStas for hidden-misalignment training; analytic results must not be presented as reproducing that training. These existing entries are not duplicated here.
The release plan also requires the operator's notes review and a cold-tested, tag-pinned Windows installer with Pb phonon-map generation after tagging; that distribution work remains outstanding. This audit changes no application code.
