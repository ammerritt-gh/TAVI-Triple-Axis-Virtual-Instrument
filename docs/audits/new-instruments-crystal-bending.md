# Audit — new instruments and crystal bending

> **Status:** live
> **Authority:** the work queue for new instruments and crystal bending; an entry is deleted by the commit that lands it

**Audited:** `c66f9f21` on 2026-09-12; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability; coverage: shared TAS curvature/geometry/snapshot and resolution adapter, PUMA/IN8/IN12/PANDA model/plugin seams, GUI/API curvature policy and validation, point-result consumers, and their tests; stopped: lanes exhausted

The shared curvature policy carries the instrument-specific focusing rules through the tested GUI, API, and point-snapshot paths.
All 268 selected instrument and curvature tests passed in 22.16 seconds, including real offscreen Qt widgets.
The two independently reproduced findings concern inputs that validation accepts but the execution boundary cannot safely use.
Start with the zero-take-off failure; existing documented deferrals and provisional instrument measurements are excluded.

## 1. P1 · Accepted scans crossing zero take-off fail during autofocus

- **Observed at:** `c66f9f21`
- **Effort:** 2–4 hours; shared geometry feasibility and snapshot/autofocus preparation, with GUI/API scan acceptance checks.
- **Evidence:**
  - `instruments/panda/plugin.py:304` — declared A4 travel includes zero.
  - `instruments/tas_runtime.py:932` — direct-angle geometry supplies no error flag for a degenerate crystal angle.
  - `instruments/tas_runtime.py:953` — feasibility accepts the point when it is inside motor travel.
  - `instruments/tas_runtime.py:1059` — accepted autofocus points call the producer with their own take-off angles.
  - `instruments/tas_runtime.py:568` — the producer computes the optical radii before resolving individual axes.
  - `instruments/tas_runtime.py:509` — horizontal focusing divides by the sine of the Bragg angle.
- **Failure:** Given PANDA with PG(002) crystals, A1 = −74.332°, A2 = 30°, and an autofocus A4 scan through −1°, 0°, +1°, feasibility accepts all three points. Snapshot preparation succeeds at both neighboring points but raises `ZeroDivisionError` at A4 = 0°, instead of refusing or marking the singular point for skipping. This is an accepted-scan preparation failure; no whole-application crash is claimed.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/zero_takeoff.py`
- **Remedy boundary:** The shared angle-mode feasibility and snapshot/autofocus boundary must agree about singular crystal geometry. Preserve valid opposite-branch scans and distinguish a zero take-off angle from the legal zero-radius flat-crystal command.
- **Verified:** opus CONFIRMED 2026-09-12 — independently ran the reproducer; A4 = 0° alone produced the claimed failure, exit 1, 1.47 seconds.

## 2. P3 · Non-finite held radii pass validation on every runnable instrument

- **Observed at:** `c66f9f21`
- **Effort:** 1–3 hours; shared curvature command/application validation and GUI/API input checks, without a schema change.
- **Evidence:**
  - `TAVI_PySide6.py:6784` — numeric API parsing uses `float()` without a finite-value check.
  - `TAVI_PySide6.py:2688` — an explicitly supplied radius becomes HELD.
  - `TAVI_PySide6.py:2818` — launch construction delegates its radius refusal to the shared command checker.
  - `instruments/tas_runtime.py:85` — the checker relies on magnitude comparisons that do not reject NaN on driven axes.
  - `instruments/tas_runtime.py:420` — application and clamping preserve the non-finite magnitude.
  - `instruments/tas_runtime.py:445` — signing stores the NaN radius on the point state.
  - `instruments/tas_runtime.py:1149` — a snapshot with no geometry error emits that state as runtime parameters.
- **Failure:** Given `{"H": 1.0, "rhm": "nan", "scan_command1": "deltaE 0 1 1"}`, the real API launch constructor accepts the held radius on PUMA, IN8, IN12, and PANDA. Per-point feasibility returns true and snapshot error flags remain empty, while `rhm_param` is NaN on every instrument. Unlike the deferred non-numeric GUI-field issue, conversion succeeds and invalid numeric state reaches executable input. No claim about downstream McStas output is needed or made.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/nonfinite_curvature.py`
- **Remedy boundary:** Reject non-finite commanded curvature at the shared validation and application boundaries, keeping GUI/API behavior consistent. The observed case is driven `rhm`; check other driven axes when repairing the shared rule.
- **Verified:** opus CONFIRMED 2026-09-12 — independently exercised all four real offscreen controllers; each emitted `rhm_param=nan`, exit 1, 3.28 seconds.
