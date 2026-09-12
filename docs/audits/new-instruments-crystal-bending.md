# Audit — new instruments and crystal bending

> **Status:** live
> **Authority:** the work queue for new instruments and crystal bending; an entry is deleted by the commit that lands it

**Audited:** `d4014742` on 2026-09-12; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability, structural improvement; coverage: `TAVI_PySide6.py`, `TODO.md`, `WIP.md`, `docs/ANALYTIC_ENGINE.md`, `docs/API_SERVER_DESIGN.md`, `docs/API_USER_GUIDE.md`, `docs/CONFIGURABLE_INSTRUMENTS.md`, `docs/CONTROL_FEATURES_DESIGN.md`, `docs/DIRECT_BINARY_INVOCATION.md`, `docs/INSTRUMENT_AUTHORING.md`, `docs/INSTRUMENT_LAYOUT.md`, `docs/audits/new-instruments-crystal-bending.md`, `docs/audits/repro/new-instruments-crystal-bending/_sandbox.py`, `docs/audits/repro/new-instruments-crystal-bending/invalid_nmo_option.py`, `docs/audits/repro/new-instruments-crystal-bending/model_versions.py`, `docs/audits/repro/new-instruments-crystal-bending/multi_radius_patch.py`, `docs/audits/repro/new-instruments-crystal-bending/nonfinite_curvature.py`, `docs/audits/repro/new-instruments-crystal-bending/second_command_count.py`, `docs/audits/repro/new-instruments-crystal-bending/zero_takeoff.py`, `gui/docks/__init__.py`, `gui/docks/instrument_dock.py`, `gui/docks/reciprocal_space_dock.py`, `gui/docks/unified_simulation_dock.py`, `gui/main_window.py`, `instruments/_descriptor_examples.py`, `instruments/builtin.py`, `instruments/contract.py`, `instruments/descriptor.py`, `instruments/in12/MODEL_STATUS.md`, `instruments/in12/README.md`, `instruments/in12/SCIENTIST_REVIEW.md`, `instruments/in12/__init__.py`, `instruments/in12/instrument.json`, `instruments/in12/model.py`, `instruments/in12/plugin.py`, `instruments/in12/references/2016-01-01__schmalzl-in12-upgrade__v01.md`, `instruments/in12/references/2026-07-18__in12-research-dossier__v01.md`, `instruments/in12/references/2026-09-09__ill-in12-web-status__v01.md`, `instruments/in12/references/2026-09-09__in12-literature-round__v02.md`, `instruments/in12/references/SOURCES.md`, `instruments/in8/MODEL_STATUS.md`, `instruments/in8/README.md`, `instruments/in8/SCIENTIST_REVIEW.md`, `instruments/in8/__init__.py`, `instruments/in8/instrument.json`, `instruments/in8/model.py`, `instruments/in8/plugin.py`, `instruments/in8/references/2006-01-01__hiess-in8-performance__v01.md`, `instruments/in8/references/2023-01-01__piovano-ivanov-in8-upgrade__v01.md`, `instruments/in8/references/2026-07-02__vtas-live-crosscheck__v01.md`, `instruments/in8/references/SOURCES.md`, `instruments/package_validation.py`, `instruments/panda/MODEL_STATUS.md`, `instruments/panda/README.md`, `instruments/panda/SCIENTIST_REVIEW.md`, `instruments/panda/__init__.py`, `instruments/panda/instrument.json`, `instruments/panda/model.py`, `instruments/panda/plugin.py`, `instruments/panda/references/2007-01-01__panda-overview__v01.md`, `instruments/panda/references/2007-01-01__panda-table__v01.csv`, `instruments/panda/references/2013-01-01__panda-supermirror-guide__v01.md`, `instruments/panda/references/2026-07-03__vpanda-mcstas__v01.instr`, `instruments/panda/references/2026-07-18__panda-research-dossier__v01.md`, `instruments/panda/references/2026-09-09__mlz-panda-page__v01.md`, `instruments/panda/references/SOURCES.md`, `instruments/puma/MODEL_STATUS.md`, `instruments/puma/README.md`, `instruments/puma/SCIENTIST_REVIEW.md`, `instruments/puma/__init__.py`, `instruments/puma/instrument.json`, `instruments/puma/model.py`, `instruments/puma/plugin.py`, `instruments/puma/references/SOURCES.md`, `instruments/registry.py`, `instruments/resolution_adapter.py`, `instruments/tas_runtime.py`, `instruments/validation.py`, `tavi/deterministic_engine.py`, `tavi/instrument_helpers.py`, `tavi/neutron_conversions.py`, `tavi/reciprocal_interaction.py`, `tavi/resolution.py`, `tavi/sample_library.py`, `tests/test_api_over_limit_latch.py`, `tests/test_api_partial_collimation.py`, `tests/test_api_resolution.py`, `tests/test_api_scan_gui_independence.py`, `tests/test_api_validation_schema.py`, `tests/test_applied_curvature.py`, `tests/test_benchmark.py`, `tests/test_binary_reuse.py`, `tests/test_controller_feedback.py`, `tests/test_controller_is_instrument_agnostic.py`, `tests/test_curvature_autofocus.py`, `tests/test_curvature_command_refusal.py`, `tests/test_curvature_held_scan_named_skip.py`, `tests/test_curvature_limits_effective_axis.py`, `tests/test_curvature_producer.py`, `tests/test_curvature_relative_preflight.py`, `tests/test_curvature_relative_scan_travel.py`, `tests/test_curvature_scan_travel_check.py`, `tests/test_descriptor_validation.py`, `tests/test_deterministic_engine.py`, `tests/test_deterministic_engine_point_curvature.py`, `tests/test_emitted_curvature.py`, `tests/test_executed_feasible_mask.py`, `tests/test_fixed_axis_field_sync.py`, `tests/test_in12_build_tree.py`, `tests/test_in12_plugin.py`, `tests/test_in8_build_tree.py`, `tests/test_in8_plugin.py`, `tests/test_instrument_packages.py`, `tests/test_instrument_registry.py`, `tests/test_instrument_selection.py`, `tests/test_mc_background_point_curvature.py`, `tests/test_panda_build_tree.py`, `tests/test_panda_plugin.py`, `tests/test_parameters_persistence.py`, `tests/test_point_energy_metadata.py`, `tests/test_puma_build_tree.py`, `tests/test_puma_plugin.py`, `tests/test_reciprocal_interaction.py`, `tests/test_record_enrichment.py`, `tests/test_relative_mode_swap.py`, `tests/test_resolution.py`, `tests/test_resolution_adapter.py`, `tests/test_resolution_module_state.py`, `tests/test_resolution_point_curvature.py`, `tests/test_resolution_point_kinematics.py`, `tests/test_resolution_point_sense.py`, `tests/test_rva_gui_axis_policy.py`, `tests/test_sample_library.py`, `tests/test_sign_conventions.py`, `tests/test_step_guards_and_fixed_policy.py`; meter: 5% to 24%; stopped: lanes exhausted, floor waived (widening to direct callers and tests adds no new file)

**Audited:** `c66f9f21` on 2026-09-12; lanes covered: duplicate authority, error and recovery paths, cross-interface twins, tests that reassure falsely, invariants bypassed, dead or vestigial architecture, agent maintainability; coverage: shared TAS curvature/geometry/snapshot and resolution adapter, PUMA/IN8/IN12/PANDA model/plugin seams, GUI/API curvature policy and validation, point-result consumers, and their tests; stopped: lanes exhausted

The shared curvature producer consistently carries instrument-specific optics into the tested point paths.
All 389 selected instrument and curvature tests passed in 19.69 seconds wall time, including real offscreen Qt widgets.
The 9 verified entries concern accepted inputs, inconsistent interface state, model identification, and remaining competing or obsolete authorities.
Start with invalid PUMA module options and the batched-radius PATCH; application code is unchanged by this audit.

## 1. P1 · Invalid PUMA mirror options silently build inconsistent optics

- **Observed at:** `d4014742`
- **Effort:** 1–2 hours; existing API module parser and PUMA launch/build regression, without adding fields or changing supported options.
- **Evidence:**
  - `instruments/puma/plugin.py:287` — the NMO choice declares `None`, `Vertical`, `Horizontal`, and `Both`.
  - `TAVI_PySide6.py:6805` — `p_dict` checks only the container type.
  - `TAVI_PySide6.py:6907` — the modules field uses that parser.
  - `instruments/puma/plugin.py:350` — the launch snapshot copies the raw NMO value.
  - `instruments/puma/model.py:125` — every non-`None` value makes both monochromator planes fixed-flat.
  - `instruments/puma/model.py:461` — the same broad predicate installs the NMO aperture.
  - `instruments/puma/model.py:479` — the vertical mirror requires an exact supported choice.
  - `instruments/puma/model.py:517` — the horizontal mirror likewise requires an exact supported choice.
- **Failure:** Given `{"H":1.0,"scan_command1":"deltaE 0 1 1","modules":{"nmo":"vertical","v_selector":false}}`, the API launch constructor accepts the lowercase, unsupported option. The resulting PUMA build contains `NMO_slit`, no focusing mirror, and `rhm = rvm = 0`. It silently constructs optics inconsistent with its own installed-module curvature policy instead of refusing the option. This was verified through launch construction and the McStasScript component tree; no neutron-output claim or PATCH claim is made.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/invalid_nmo_option.py`
- **Remedy boundary:** Validate supplied module values against the selected instrument's existing module descriptors before constructing launch state. Preserve all supported PUMA choices and keep their curvature policy and component topology consistent.
- **Verified:** opus CONFIRMED 2026-09-12 — independently ran the isolated real-controller/build reproducer; unsupported option accepted, flat mono planes and aperture without mirrors, exit 1, 2.88 seconds.

## 2. P1 · Accepted scans crossing zero take-off fail during autofocus

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

## 3. P1 · A batched radius PATCH overwrites an explicitly commanded radius

- **Observed at:** `d4014742`
- **Effort:** 2–4 hours; controller batch application and curvature-lock refresh, with both key orders checked on all four instruments; no API shape change.
- **Evidence:**
  - `TAVI_PySide6.py:6841` — each radius callback unlocks its own axis and then refreshes every curvature field.
  - `TAVI_PySide6.py:6899` — radius setters have separate callbacks.
  - `TAVI_PySide6.py:7075` — all parsed setters run before callbacks.
  - `TAVI_PySide6.py:7088` — callbacks then run sequentially.
  - `TAVI_PySide6.py:3288` — refresh overwrites any axis whose ideal lock remains set.
- **Failure:** With both monochromator axes in AUTOFOCUS, `apply_parameters({"rhm":9.0,"rvm":8.0})` reports both values applied with no errors, but the first callback overwrites the still-locked second axis before that axis is unlocked. All four instruments finish with both axes HELD and `rvm` at its ideal value rather than 8.0; reversing the key order instead loses `rhm = 9.0`. For IN8 the two outcomes are `(9.0, 0.8353)` and `(6.7576, 8.0)`. The same explicit values survive direct API launch construction, so PATCH and launch disagree. These are legal driven axes, distinct from the deferred module-fixed reporting mismatch.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/multi_radius_patch.py`
- **Remedy boundary:** Treat explicitly commanded curvature fields as one batch at the parameter-application/lock-refresh boundary. A refresh must not replace another field's accepted value while that field still carries its previous lock state.
- **Verified:** opus CONFIRMED 2026-09-12 — independently exercised both key orders on all four real offscreen controllers; all eight cases lost one requested radius, exit 1, 3.31 seconds.

## 4. P2 · A scan entered only in command box 2 previews zero points

- **Observed at:** `d4014742`
- **Effort:** 1–2 hours; controller preview/count normalization and simulation-dock label formatting, with a real offscreen widget check.
- **Evidence:**
  - `TAVI_PySide6.py:4500` — preview reads both command boxes without normalization.
  - `TAVI_PySide6.py:4668` — counting handles command 1 alone.
  - `TAVI_PySide6.py:4681` — counting handles both commands, leaving command 2 alone with zero counters.
  - `gui/docks/unified_simulation_dock.py:494` — any nonempty second box takes the two-dimensional label path.
  - `TAVI_PySide6.py:8212` — execution instead moves a lone second command and its relative flags into the first slot.
- **Failure:** On IN8, leave command box 1 empty and enter `rva 1 1.2 0.1` in box 2. The real preview says `0 × 3 = 0 points (0 valid / 0 invalid)`, while shared runtime expansion prepares a one-dimensional scan with three feasible points at 1.0, 1.1, and 1.2. The same text in box 1 previews three valid points. This is a preview/count discrepancy; the reproducer intercepts the deterministic engine after shared scan expansion and makes no simulated-count claim.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/second_command_count.py`
- **Remedy boundary:** Preview and execution must use the same lone-command normalization, including relative-mode flags. The dock must format that normalized scan as one-dimensional.
- **Verified:** opus CONFIRMED 2026-09-12 — independently compared real widget text, both command placements, and runtime expansion; preview `(0, 0)` versus prepared `(3, 0)`, exit 1, 2.70 seconds.

## 5. P3 · All four model manifests retain their pre-bending versions

- **Observed at:** `d4014742`
- **Effort:** 0.5–1 hour; version/date metadata in the four instrument manifests, following the existing authoring contract; no physics or API change.
- **Evidence:**
  - `docs/INSTRUMENT_AUTHORING.md:12` — descriptor/model changes require a model-version bump.
  - `docs/INSTRUMENT_AUTHORING.md:48` — executable behavior determines model-version changes.
  - `instruments/puma/instrument.json:7` — version remains `1.0.0`, dated 2026-07-18.
  - `instruments/in8/instrument.json:7` — version remains `1.0.0`, dated 2026-07-18.
  - `instruments/in12/instrument.json:7` — version remains `1.0.0`, dated 2026-09-09.
  - `instruments/panda/instrument.json:7` — version remains `1.0.0`, dated 2026-09-09.
  - `instruments/package_validation.py:64` — manifest validation checks version syntax, not correspondence with executable changes.
- **Failure:** The four manifests are unchanged from before the shared producer/applier migration, although `c93e2442` replaced copied focusing behavior and IN8's literal `rva = -0.31`, and `63e2422d` introduced per-point autofocus, including PUMA. A scientist holding a package labeled `1.0.0` with the same model date cannot distinguish the old bending behavior from the corrected executable model by its declared model version. Git revisions distinguish them; this finding concerns the explicit package-version contract, not runtime/API provenance.
- **Reproduce with:** `python -B docs/audits/repro/new-instruments-crystal-bending/model_versions.py`
- **Remedy boundary:** Update the four changed packages' model version/date metadata according to the existing authoring rules. No new version-tracking infrastructure is needed.
- **Verified:** opus CONFIRMED 2026-09-12 — independently read the behavior-changing diffs and ran the read-only manifest comparison; all four retain their previous version/date, exit 1, 0.16 seconds.

## 7. P4 · Remove focusing-factor fields that no longer affect curvature

- **Observed at:** `d4014742`
- **Effort:** 0.25–0.5 hours; twelve inert assignments and their misleading comments in four model constructors; no behavior, schema, or interface change.
- **Evidence:**
  - `instruments/puma/model.py:65` — assigns `rhmfac`, `rvmfac`, and `rhafac` beside the real radii.
  - `instruments/in8/model.py:74` — claims factors of 1 mean optimal focusing, then assigns the inert factors.
  - `instruments/in12/model.py:109` — repeats that claim and the assignments.
  - `instruments/panda/model.py:82` — repeats that claim and the assignments.
  - `instruments/tas_runtime.py:488` — the shared optical producer uses object distances and angles, not these factors.
- **Payoff:** No named or reflective live consumer remains in TAVI, ISAR, or TAS_MCP after deletion of the old per-model producer. The comments still present these fields as tuning controls, so an executor can change a factor while emitted curvature stays unchanged. Removing the obsolete fields closes that misleading implementation path and makes the actual producer easier to find.
- **Reproduce with:** none — opportunity
- **Remedy boundary:** Remove only the inert factors and factor-specific claims from the four constructors. Preserve real `rhm`, `rvm`, `rha`, and `rva` fields, the flat-radius explanation, and historical reference assets.
- **Verified:** opus CONFIRMED 2026-09-12 — independently searched live named/reflective consumers, persistence callers, generated parameter records, and the two external consumers; only the twelve assignments remain in live source.

## 8. P4 · Align the promised sample-extension contract with the builders

- **Observed at:** `d4014742`
- **Effort:** 2–4 hours; sample lookup in four builders, descriptor/library contract documentation, and sample-catalogue/build assertions; no new registry or GUI/API field.
- **Evidence:**
  - `tavi/sample_library.py:5` — instruments may filter or extend their descriptor's shared sample list.
  - `instruments/descriptor.py:205` — repeats the extension contract.
  - `docs/CONFIGURABLE_INSTRUMENTS.md:1344` — records that permission as the design.
  - `gui/docks/unified_sample_dock.py:110` — selection lists descriptor samples.
  - `TAVI_PySide6.py:6824` — API sample choices also come from the descriptor.
  - `instruments/puma/model.py:590` — build instead searches the unextended default library.
  - `instruments/in8/model.py:251` — repeats that independent lookup.
  - `instruments/in12/model.py:314` — repeats that independent lookup.
  - `instruments/panda/model.py:295` — repeats that independent lookup.
  - `tests/test_in12_plugin.py:64` — exact catalogue equality rejects a descriptor extension rather than checking that the builder consumes it.
- **Payoff:** Current built-in catalogues agree, but following the documented extension path by adding an IN12-only sample ID makes it selectable and descriptor-valid while the builder emits no sample component and prints its existing warning. Replacing descriptor `Al_bragg` with a mosaic of 60 instead emits the shared library's mosaic of 5. Aligning the extension promise, catalogue tests, and build lookup prevents a package author from making a valid-looking sample change that execution ignores. This is an extension-contract opportunity, not a claim that current standard samples are broken.
- **Reproduce with:** none — opportunity
- **Remedy boundary:** Make selection and build agree on the supported sample authority, and state the supported extension boundary consistently in the design and authoring documents. Resolve the older GUI-only descriptor wording explicitly if retaining the documented extension promise; preserve instrument-independent shared defaults and the supported no-sample path.
- **Verified:** opus CONFIRMED 2026-09-12 — independently applied a descriptor-only extension in a temporary copy and built IN12: new ID emitted no sample; replacement mosaic 60 emitted 5, exit 0, 1.66 seconds. A separate temporary suite run exposed the exact-equality guard, confirming the contract mismatch.

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
