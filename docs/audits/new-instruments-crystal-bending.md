# Audit — new instruments and crystal bending

> **Status:** live
> **Authority:** the work queue for new instruments and crystal bending; an entry is deleted by the commit that lands it

**Audited:** `d4014742` on 2026-09-12; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability, structural improvement; coverage: `TAVI_PySide6.py`, `TODO.md`, `WIP.md`, `docs/ANALYTIC_ENGINE.md`, `docs/API_SERVER_DESIGN.md`, `docs/API_USER_GUIDE.md`, `docs/CONFIGURABLE_INSTRUMENTS.md`, `docs/CONTROL_FEATURES_DESIGN.md`, `docs/DIRECT_BINARY_INVOCATION.md`, `docs/INSTRUMENT_AUTHORING.md`, `docs/INSTRUMENT_LAYOUT.md`, `docs/audits/new-instruments-crystal-bending.md`, `docs/audits/repro/new-instruments-crystal-bending/_sandbox.py`, `docs/audits/repro/new-instruments-crystal-bending/invalid_nmo_option.py`, `docs/audits/repro/new-instruments-crystal-bending/model_versions.py`, `docs/audits/repro/new-instruments-crystal-bending/multi_radius_patch.py`, `docs/audits/repro/new-instruments-crystal-bending/nonfinite_curvature.py`, `docs/audits/repro/new-instruments-crystal-bending/second_command_count.py`, `docs/audits/repro/new-instruments-crystal-bending/zero_takeoff.py`, `gui/docks/__init__.py`, `gui/docks/instrument_dock.py`, `gui/docks/reciprocal_space_dock.py`, `gui/docks/unified_simulation_dock.py`, `gui/main_window.py`, `instruments/_descriptor_examples.py`, `instruments/builtin.py`, `instruments/contract.py`, `instruments/descriptor.py`, `instruments/in12/MODEL_STATUS.md`, `instruments/in12/README.md`, `instruments/in12/SCIENTIST_REVIEW.md`, `instruments/in12/__init__.py`, `instruments/in12/instrument.json`, `instruments/in12/model.py`, `instruments/in12/plugin.py`, `instruments/in12/references/2016-01-01__schmalzl-in12-upgrade__v01.md`, `instruments/in12/references/2026-07-18__in12-research-dossier__v01.md`, `instruments/in12/references/2026-09-09__ill-in12-web-status__v01.md`, `instruments/in12/references/2026-09-09__in12-literature-round__v02.md`, `instruments/in12/references/SOURCES.md`, `instruments/in8/MODEL_STATUS.md`, `instruments/in8/README.md`, `instruments/in8/SCIENTIST_REVIEW.md`, `instruments/in8/__init__.py`, `instruments/in8/instrument.json`, `instruments/in8/model.py`, `instruments/in8/plugin.py`, `instruments/in8/references/2006-01-01__hiess-in8-performance__v01.md`, `instruments/in8/references/2023-01-01__piovano-ivanov-in8-upgrade__v01.md`, `instruments/in8/references/2026-07-02__vtas-live-crosscheck__v01.md`, `instruments/in8/references/SOURCES.md`, `instruments/package_validation.py`, `instruments/panda/MODEL_STATUS.md`, `instruments/panda/README.md`, `instruments/panda/SCIENTIST_REVIEW.md`, `instruments/panda/__init__.py`, `instruments/panda/instrument.json`, `instruments/panda/model.py`, `instruments/panda/plugin.py`, `instruments/panda/references/2007-01-01__panda-overview__v01.md`, `instruments/panda/references/2007-01-01__panda-table__v01.csv`, `instruments/panda/references/2013-01-01__panda-supermirror-guide__v01.md`, `instruments/panda/references/2026-07-03__vpanda-mcstas__v01.instr`, `instruments/panda/references/2026-07-18__panda-research-dossier__v01.md`, `instruments/panda/references/2026-09-09__mlz-panda-page__v01.md`, `instruments/panda/references/SOURCES.md`, `instruments/puma/MODEL_STATUS.md`, `instruments/puma/README.md`, `instruments/puma/SCIENTIST_REVIEW.md`, `instruments/puma/__init__.py`, `instruments/puma/instrument.json`, `instruments/puma/model.py`, `instruments/puma/plugin.py`, `instruments/puma/references/SOURCES.md`, `instruments/registry.py`, `instruments/resolution_adapter.py`, `instruments/tas_runtime.py`, `instruments/validation.py`, `tavi/deterministic_engine.py`, `tavi/instrument_helpers.py`, `tavi/neutron_conversions.py`, `tavi/reciprocal_interaction.py`, `tavi/resolution.py`, `tavi/sample_library.py`, `tests/test_api_over_limit_latch.py`, `tests/test_api_partial_collimation.py`, `tests/test_api_resolution.py`, `tests/test_api_scan_gui_independence.py`, `tests/test_api_validation_schema.py`, `tests/test_applied_curvature.py`, `tests/test_benchmark.py`, `tests/test_binary_reuse.py`, `tests/test_controller_feedback.py`, `tests/test_controller_is_instrument_agnostic.py`, `tests/test_curvature_autofocus.py`, `tests/test_curvature_command_refusal.py`, `tests/test_curvature_held_scan_named_skip.py`, `tests/test_curvature_limits_effective_axis.py`, `tests/test_curvature_producer.py`, `tests/test_curvature_relative_preflight.py`, `tests/test_curvature_relative_scan_travel.py`, `tests/test_curvature_scan_travel_check.py`, `tests/test_descriptor_validation.py`, `tests/test_deterministic_engine.py`, `tests/test_deterministic_engine_point_curvature.py`, `tests/test_emitted_curvature.py`, `tests/test_executed_feasible_mask.py`, `tests/test_fixed_axis_field_sync.py`, `tests/test_in12_build_tree.py`, `tests/test_in12_plugin.py`, `tests/test_in8_build_tree.py`, `tests/test_in8_plugin.py`, `tests/test_instrument_packages.py`, `tests/test_instrument_registry.py`, `tests/test_instrument_selection.py`, `tests/test_mc_background_point_curvature.py`, `tests/test_panda_build_tree.py`, `tests/test_panda_plugin.py`, `tests/test_parameters_persistence.py`, `tests/test_point_energy_metadata.py`, `tests/test_puma_build_tree.py`, `tests/test_puma_plugin.py`, `tests/test_reciprocal_interaction.py`, `tests/test_record_enrichment.py`, `tests/test_relative_mode_swap.py`, `tests/test_resolution.py`, `tests/test_resolution_adapter.py`, `tests/test_resolution_module_state.py`, `tests/test_resolution_point_curvature.py`, `tests/test_resolution_point_kinematics.py`, `tests/test_resolution_point_sense.py`, `tests/test_rva_gui_axis_policy.py`, `tests/test_sample_library.py`, `tests/test_sign_conventions.py`, `tests/test_step_guards_and_fixed_policy.py`; meter: 5% to 24%; stopped: lanes exhausted, floor waived (widening to direct callers and tests adds no new file)

**Audited:** `c66f9f21` on 2026-09-12; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability; coverage: shared TAS curvature/geometry/snapshot and resolution adapter, PUMA/IN8/IN12/PANDA model/plugin seams, GUI/API curvature policy and validation, point-result consumers, and their tests; stopped: lanes exhausted

The shared curvature producer consistently carries instrument-specific optics into the tested point paths.
All 389 selected instrument and curvature tests passed in 19.69 seconds wall time, including real offscreen Qt widgets.
The 9 verified entries concern accepted inputs, inconsistent interface state, model identification, and remaining competing or obsolete authorities.
Start with invalid PUMA module options and the batched-radius PATCH; application code is unchanged by this audit.

## 9. P4 · Bind instrument geometry to one authority before correcting arm lengths

- **Observed at:** `d4014742`
- **Effort:** 2–4 hours; four model constructors, descriptor geometry constants, and parity assertions; no field/schema change. Preserve mutable runtime state and instrument-specific optical overrides.
- **Evidence:**
  - `instruments/puma/model.py:49` — state arm lengths have independent literals.
  - `instruments/puma/plugin.py:135` — descriptor-side copies of those lengths.
  - `instruments/in8/model.py:50` — state arm lengths have independent literals.
  - `instruments/in8/plugin.py:59` — descriptor-side copies of those lengths.
  - `instruments/in12/model.py:83` — state arm lengths have independent literals.
  - `instruments/in12/plugin.py:85` — descriptor-side copies of those lengths.
  - `instruments/panda/model.py:53` — state arm lengths have independent literals.
  - `instruments/panda/plugin.py:75` — descriptor-side copies of those lengths.
  - `instruments/in12/plugin.py:226` — sample diagnostic position uses the descriptor-side `_L2`.
  - `instruments/in12/model.py:309` — sample placement uses state `L2`.
  - `instruments/tas_runtime.py:482` — autofocus object distances use state arm lengths.
  - `tests/test_in12_plugin.py:144` — the test named for descriptor/state geometry agreement compares state to literals instead.
- **Payoff:** The copies agree today, but a plausible IN12 descriptor correction `_L2: 1.80 → 1.90` moves the sample energy monitor from 1.79 to 1.89 m while the sample and focusing calculation remain at 1.80 m. The monitor still precedes the sample in component order but sits 0.09 m downstream physically. One geometry authority makes an accepted scientist correction reach construction, focusing, and diagnostics together, and a real parity assertion exposes drift.
- **Reproduce with:** none — opportunity
- **Remedy boundary:** Bind each default model's arm lengths and its descriptor/diagnostic coordinates to one package-owned geometry authority. Retain PANDA's virtual-source offset and PUMA's parallel-beam focusing override; analytic-resolution spatial defaults are outside this finding.
- **Verified:** opus CONFIRMED 2026-09-12 — independently traced both consumers and perturbed only the IN12 descriptor in memory inside a temporary copy; monitor moved to 1.89 m while state `L2` and mono focusing distances stayed 1.80 m.

## 11. P3 · A module-fixed axis reports a commanded radius it did not apply

- **Observed at:** `c99b67a9`
- **Effort:** 1–2 hours; the reporting seam between `apply_parameters`' accepted-value list and the resolved curvature policy; no change to the policy itself.
- **Evidence:**
  - `TAVI_PySide6.py` `_sync_curvature_fields` — the non-driven branch writes the resolved fixed radius unconditionally, regardless of lock state, which is correct for hardware that genuinely cannot bend.
  - `instruments/puma/model.py:125` — a fitted nested mirror optic pins both monochromator planes flat.
  - `TAVI_PySide6.py` `apply_parameters` — reports every parsed field in `applied`, including a radius the resolved policy then overrides.
- **Failure:** With a module fitted that fixes an axis flat, a PATCH naming that axis reports the commanded value as applied while the field ends at the fixed radius. The override is right; the report is wrong. Carried forward deliberately: the original audit's entry 3 named this as "the deferred module-fixed reporting mismatch" and explicitly scoped itself away from it, so deleting entry 3 with PR #33 would otherwise have erased the only record of it.
- **Reproduce with:** none yet — inherited from the deleted entry 3 and re-raised by PR #33's pre-PR review; not independently reproduced by this session.
- **Remedy boundary:** Make the reported `applied` set agree with what the resolved curvature policy actually stored. Do not weaken the override — a module-fixed axis must keep being pinned to its declared radius; only the reporting should stop claiming otherwise.
- **Verified:** NOT independently reproduced — structurally traced only. Reproduce before scheduling the fix.

## 12. P2 · The suite inherits the operator's saved GUI state

- **Observed at:** `c99b67a9`
- **Effort:** 1–3 hours; one conftest fixture plus whatever `test_parameters_persistence.py` needs to keep exercising the real path deliberately; no application change.
- **Evidence:**
  - `TAVI_PySide6.py:5601` — the controller reads `config/parameters.json` by RELATIVE path during construction, so it resolves against the run's working directory.
  - `.gitignore:370` — `config/` is ignored, so the file exists on a developer's machine and never in a fresh clone or worktree.
  - `conftest.py` — guards only against console windows (`MCSTAS`, `CREATE_NO_WINDOW`). Nothing isolates `config/`.
  - `tests/test_curvature_command_refusal.py`, `tests/test_curvature_held_scan_named_skip.py` — two tests were built on a real controller and asserted against the Ideal-lock state without establishing it; fixed at `c99b67a9` by establishing the precondition, which is the symptom, not the cause.
- **Failure:** Every test that constructs a real `TAVIController` silently inherits whatever GUI state the operator last saved. Measured 2026-09-12: with `"rhm_ideal_locked": true` in the operator's `config/parameters.json`, the two tests above failed on the main checkout and passed in a fresh worktree, from identical source — and the suite therefore reported 1187 passed / 1 skipped in the worktree and 1186 passed / 2 failed on main at the same commit. The direction is what makes it a defect rather than a nuisance: the *unset* machine is the one that passes, so a green CI or fresh-clone run is the weaker evidence, and a real regression can hide behind a developer's saved state either way.
- **Reproduce with:** none yet — move `config/parameters.json` aside, run any controller-constructing test, and compare against a run with a file containing `"rhm_ideal_locked": true`.
- **Remedy boundary:** Point the tests' `config/` at a temporary directory for the session, so a run cannot read or write the operator's saved state. Preserve `test_parameters_persistence.py`'s deliberate exercise of the real read/write path, and preserve the existing serial-run rule — the file is also why that test must not run beside a full suite. Do not "fix" this by making the application path absolute; the relative path is what lets the launcher and the tests each have their own working directory.
- **Verified:** opus CONFIRMED 2026-09-12 — moved the operator's `config/parameters.json` aside and re-ran the two tests unchanged: 2 failed with the file present, 2 passed with it absent, same commit, same environment. File restored afterwards.

## 13. P2 · A direct-beam point invents an energy pair, and no simple fix is available

> **Operator decision pending.** This entry is a DESIGN question, not a ready
> slice. It is pinned for a fresh session (see WIP.md); do not start it as an
> ordinary fix.

- **Observed at:** `cba504e4`
- **Effort:** unknown until the convention is chosen; the two candidate
  remedies differ by roughly an order of magnitude in blast radius.
- **Evidence:**
  - `tavi/neutron_conversions.py:27` — `angle2k(0, d)` returns `0` from its
    own else-branch.
  - `instruments/tas_runtime.py` `nominal_energies_from_angles` — guards with
    `if ki <= 0 or kf <= 0: return None`, discarding the ENTIRE `(Ei, Ef)`
    pair at a zero analyser take-off even though `A1` still determines `Ei`.
  - `instruments/tas_runtime.py` `e0_param_value` — therefore skips its "take
    Ei from the crystals" branch and falls back to `fixed_E` arithmetic.
  - `instruments/tas_runtime.py` `point_energy_metadata` — likewise falls back
    to the `K_fixed` branch and records an invented fixed-mode `(Ei, Ef)`.
  - `TAVI_PySide6.py:141` `_background_q_magnitude` — in angle mode
    `qx/qy/qz` are `None` by construction, so `|Q|` comes from `Ki`/`Kf`/`stt`.
  - `TAVI_PySide6.py:7998` — the deterministic engine computes that `|Q|` for
    EVERY point and feeds it to `resolution_config`; `:8962` does the same for
    a real McStas run when background is enabled.
- **Failure:** On IN8 with a Mono source, `fixed_E = 14.68`, and an `A1`
  selecting `Ei = 20 meV`, an angle-mode A4 scan through zero records
  `E0_param = 20.0000` at A4 = ±1° and `E0_param = 14.6800` at A4 = 0 — the
  source energy jumps to `fixed_E` at the one point where the analyser selects
  nothing, and the recorded `(Ei, Ef)` there is an invented fixed-mode pair.
  The neighbours are no better in kind: at A4 = ±1° the recorded `Ef` is
  `23859.5294 meV`, because inverting Bragg near zero take-off diverges. So
  the affected region is a NEIGHBOURHOOD of zero, not a single point.
- **Why there is no simple fix:** the obvious remedy — record `Ei` and omit
  the undetermined `Ef` — was implemented and then withdrawn. `Ef = None`
  propagates into `_background_q_magnitude`, which needs a number:
  `float(None)` raises `TypeError`, and that helper feeds the per-point
  resolution kernel for every deterministic-engine point. Confirmed directly:
  `_background_q_magnitude({'qx': None, ..., 'Ki': 2.66, 'Kf': None, 'stt': 30.0})`
  raises `TypeError`. So the honest recording makes the direct-beam point
  CRASH the engine, on exactly the point the operator's ruling says must run.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/direct_beam_energy.py`
- **Remedy boundary — two candidate conventions, operator to choose:**
  - **B, omit what is undetermined.** Record `Ei`, leave `Ef`/`Kf` absent, and
    teach `|Q|` and the resolution kernel to handle a point with no
    determined outgoing energy — that point then runs with no resolution
    kernel and no `|Q|`-keyed background. Honest, but it is real new
    machinery and yields a simulation datum with no resolution attached.
  - **C, an elastic convention for a transmitting analyser.** At zero take-off
    the analyser diffracts nothing and transmits, so the detector sees
    neutrons at the incident energy: `Ef = Ei`, `deltaE = 0`,
    `|Q| = 2·ki·sin(θs)`. Everything downstream works with no absent values.
    Weaker as a RECORD (it asserts an `Ef` the instrument never selected), but
    it has a physical story rather than being an accident of `fixed_E`
    arithmetic, and it must be documented at the point of use if chosen.
  Whichever is chosen should also address the divergent `Ef` in the
  neighbourhood of zero, not only the exact-zero point.
- **Verified:** opus CONFIRMED 2026-09-12 — ran the reproducer on `cba504e4`
  (E0_param 14.68 at A4 = 0 against 20.0 at both neighbours, exit 1, 1.53 s),
  and separately confirmed the `TypeError` that rules out the simple remedy.
