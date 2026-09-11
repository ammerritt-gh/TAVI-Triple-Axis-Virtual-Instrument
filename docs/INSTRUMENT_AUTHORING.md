# Instrument Packages and Authoring

Every instrument has one directory under `instruments/<id>/`. The directory is
both its TAVI implementation package and the review bundle that can be sent to
an instrument scientist.

There are two deliberately different roles:

- **Instrument scientists** only need `SCIENTIST_REVIEW.md`. They may comment
  anywhere, in any format, and may add source files under `references/`. Their
  comments are evidence; they never alter executable settings automatically.
- **TAVI maintainers** reconcile comments and sources, update
  `MODEL_STATUS.md`, implement descriptor/model changes, bump the model version
  in `instrument.json`, and run validation before registration.

The living runnable template is IN8:

- `instruments/in8/plugin.py` — descriptor + `InstrumentPlugin` (import-light)
- `instruments/in8/model.py` — state class + McStas `build()`
- `instruments/in8/README.md` — plain-language component description
- `instruments/in8/MODEL_STATUS.md` — evidence comparison and gaps
- `instruments/in8/SCIENTIST_REVIEW.md` — low-effort scientist handoff

PUMA (`instruments/puma/plugin.py`, `instruments/puma/model.py`) is the fuller
runtime example: modules, stacked collimators, and 19 monitors. IN12
(`instruments/in12/plugin.py`) is the worked example of an instrument built
from public documentation alone, with no instrument-scientist input: its
monochromator sits on the negative branch (`sense_mono = -1`, as PANDA's
does), and its `references/` shows the pattern that made that possible — a
broad research dossier, then a targeted literature round before registration,
each frozen as its own dated snapshot. That second round is what settled
IN12's scattering senses and corrected its analyser topology, so budget for it
rather than treating the first dossier as final. PANDA
(`instruments/panda/`) is the worked example of the *evidence* side: a package
promoted from research to runnable, whose `MODEL_STATUS.md` records a source
per field, a disposition per known defect in its historical McStas file, and a
reason per deliberate gap. A research-only package must not be registered
until it is runnable.

Run `python -m instruments.package_validation` before and after package work.
It validates metadata, required documents, references, status/registration,
and runtime descriptor identity.

## Package files and versioning

`instrument.json` is maintainer-owned. It records schema version, stable id,
display name, facility, status (`runnable`, `research`, or `retired`), semantic
model version, and model date. A model version changes only when executable
simulation behavior changes: patch for corrected values, minor for compatible
new capabilities, and major for an incompatible model contract/topology.

External evidence snapshots are immutable and use
`YYYY-MM-DD__source-id__vNN.ext`. If only a publication year is known, use
January 1 and say explicitly in `references/SOURCES.md` that the day is
normalized. If the upstream date is unknown, use the repository capture date.
Never overwrite a captured source; add the next `vNN` and mark supersession in
`SOURCES.md`.

All built-in McStas components and data remain in the central `components/`
tree. An instrument README names its dependencies; packages do not duplicate
assets. The descriptor retains `component_path` compatibility for external
plugins, but built-in packages use the central path.

---

## The 8 steps

1. **Descriptor** — write `<id>_descriptor()` returning an
   `InstrumentDescriptor` (`instruments/descriptor.py`): geometry + senses,
   crystals, `samples=default_sample_library()`, scannable parameters,
   monitors, collimation, slits, source types, axis limits.
   Two `CrystalSpec` fields are easy to miss and both belong to the *crystal*,
   not the instrument: `mosaic_v` for an anisotropic mosaic (the emitter then
   writes McStas's `mosaich`/`mosaicv` pair instead of the single `mosaic`),
   and `curvature`, a mapping of the crystal's curvature axes (`"rhm"`/`"rvm"`
   for a monochromator, `"rha"`/`"rva"` for an analyser) to `CurvatureAxis`
   declarations (`instruments/descriptor.py`) — driven or fixed
   (`fixed_radius_m`), mechanical travel (`min_radius_m`/`max_radius_m`), and
   whether a focusing model is established at all (`focusing_known`). A fixed
   axis makes the scan-command validator refuse a scan over it. `provenance`
   is **required** on every axis that declares a radius (fixed or clamped) —
   it is read by a person in a GUI dialog and by a campaign client in an API
   error body, so it must say where the number came from. Declare fixedness
   only where it is evidenced for that crystal — two analysers on one
   instrument can differ, and pinning a value in `scan_config` without
   declaring it lets a scan silently defeat the pin.
2. **Validate** — `validate_descriptor(d, runnable=True)` must return `[]`.
   Startup calls `assert_valid_descriptor(runnable=True)` and exits on
   failure. Run `python -m instruments._descriptor_examples` for a printout.
3. **State class** — subclass `TAS_Instrument`
   (`instruments/tas_runtime.py`): set L1–L4, the senses, and
   instrument fields in `__init__`; implement `crystal_info()` and
   `build_point_params()`. Crystal bending is shared policy, not something
   each instrument implements: `TAS_Instrument.ideal_curvature` is the one
   producer, and an instrument overrides `curvature_object_distances` only
   when its optics are not the default point-source (L_in, L_out) pair — or
   `optical_radii` directly for an optic whose focusing law isn't that pair
   at all.
4. **`build_<ID>_instrument()`** — the McStas component tree, in beam order,
   through the shared emitters of `tavi/instrument_helpers.py` wherever a
   category exists there. `add_parameter` names must match the descriptor's
   `scannable_parameters` 1:1 (build-tree test).
5. **Plugin** — `<ID>Plugin` in `instruments/<id>/plugin.py`, implementing
   `instruments/contract.py`:
   `default_state`, `scan_config` (the GUI→state mapping), `crystal_info`,
   `build_fingerprint`, and function-local delegations for
   `build`/`compute_snapshot`/`run_point`.
6. **Register** — only after the package is runnable-valid, add one
   `register(...)` line in `instruments/builtin.py`. The
   startup picker appears automatically once more than one instrument is
   registered; `config/parameters.json` grows a namespaced block on first
   save.
7. **Tests** — copy the IN8 test patterns: plugin conformance
   (`tests/test_in8_plugin.py`), object-level build tree
   (`tests/test_in8_build_tree.py`), angle goldens
   (`tests/test_sign_conventions.py`). Extend the lazy-import test's banned
   list with your heavy module.
8. **Baselines + smoke** — capture `.instr` baselines through the plugin path
   before refactors; compile and run one elastic Bragg point end-to-end and
   check the detector actually counts (see §Gotchas — the bending sign was
   found only this way). Record the result in `MODEL_STATUS.md` with the
   configuration it validates, and **re-run it when the emitted tree changes** —
   a smoke recorded against a tree the model no longer emits validates nothing.
   Generated `.instr`/`.exe` are build products and belong in `.gitignore`.

   A smoke script runs *outside* pytest, so it does not get the repo-root
   `conftest.py` guard: call `install_no_window_guard()` from it before
   touching McStasScript, or every instrument construction opens a console
   window on the operator's screen (see `tests/README.md`).

---

## The import-light rule

The plugin module's top level may import nothing heavier than
`instruments.descriptor` and `tavi.sample_library` — **no mcstasscript, no
PySide6, no instrument-definition module**. Every reference to the heavy
module is function-local. This keeps listing instruments (and the picker)
instant. Enforced by
`tests/test_instrument_registry.py::test_listing_is_lazy_no_mcstas_import`,
which bans every registered package's `model` module by name — add yours.

Duplicate the McStas name as a plugin constant (`IN8_MCSTAS_NAME`) and assert
it equals the definition module's `MCSTAS_NAME` in a heavy test.

## Validator: what "runnable" requires

Structural rules always apply (slug ids, unique names, C-identifier parameter
names, `detector.dat`/`1d_monitor` detector contract, module/collimation
defaults in options, L2–L4 finite > 0, axis-limit ordering, senses are
`Sense` members). `runnable=True` additionally requires:

| Rule | Detail |
|---|---|
| L1 | `l1_source_mono` finite and > 0 |
| Parameter defaults | every non-None default finite |
| Crystal completeness | all of slab_width/height, n_columns/n_rows, gap, mosaic, r0, reflect_file, transmit_file **non-None**; the numerics finite > 0 |
| No reflectivity file? | use the McStas sentinel string `"NULL"` (constant r0) — a non-None string satisfies the validator and `Monochromator_curved` treats it as "no file" |
| mcstas_name | set, valid C identifier |
| component_path | must exist **if set**; `None` is fine (build passes `input_path` itself) |
| Non-empty | mono/ana crystals, samples, source_types, scannable_parameters. `monitors`/`modules`/`collimation`/`slits` MAY be empty |

## Scattering senses and signed bending

- `Geometry.sense_mono/sample/ana`: the value IS the numeric sign of that
  axis' two-theta readout (LEFT = +1, RIGHT = −1; equals vTAS sm/ss/sa). The
  state class sets the same numbers in `__init__`; the shared
  `calculate_angles` applies them. TAVI's historical convention is
  (+1, −1, +1) (PUMA); IN8's verified senses are (+1, +1, −1).
- Verify against reality before trusting a source: IN8's senses were
  confirmed with a **live vTAS run** — the vTAS repository XML had them
  stale/mirrored. Lock the verified angles as goldens in
  `tests/test_sign_conventions.py`.
- **Crystal bending radii are SIGNED by branch**: `Monochromator_curved`
  needs the curvature center on the take-off side. A positive radius on a
  negative take-off branch defocuses by ~7 orders of magnitude in peak
  intensity (measured). The sign is derived from the take-off angle in one
  place, `TAS_Instrument.ideal_curvature`/`set_crystal_bending`
  (`instruments/tas_runtime.py`) — never applied per plugin. The GUI, the API,
  and `vals` all carry magnitudes only; `tavi/resolution.py` applies the same
  branch sense itself when it reads those magnitudes back
  (`monorh = radius_cm(cfg.rhm) * sm`), so a signed value reaching that
  surface would be signed twice.

## The scans-array contract

`compute_scan_snapshot` (shared) consumes per-point `scans` lists with a
fixed layout: indices 0–3 are mode-specific (qx/qy/qz/ΔE, H/K/L/ΔE, or
A1–A4), 4–7 are rhm/rvm/rha/rva, 8–10 are chi/kappa/psi. Every instrument's
`build_point_params()` must return exactly the descriptor's parameter names.

## What the shared helpers cover vs what stays literal

| Category | Helper (`tavi/instrument_helpers.py`) |
|---|---|
| Diagnostic monitors | `emit_monitors` (+ `size_overrides` for crystal-sized ones) |
| Mono/analyzer assemblies | `emit_crystal_assembly` (cradle Arm + `Monochromator_curved` from the crystal-info dict) |
| Sample | `emit_sample` (shared library lookup in build()) |
| Orientation hierarchy | `emit_sample_orientation_arms` (gonio→chi→cradle→mount; pairs with the 10 orientation parameters) |
| Slits | `emit_slit` (`rotated=None` omits the ROTATED clause) |
| Collimators | `emit_collimator` (divergence 0 = open aperture) |
| Crystal dicts | `crystal_spec_to_info` / `find_crystal_spec` / `crystal_info_from_descriptor` |

Stays literal per instrument: the source block, the axis arms
(`sample_arm`/`analyzer_arm`/`detector_arm`), filters, the detector, and any
instrument-specific optics (PUMA's NMO/velocity selector). If a third
instrument repeats the source pattern, that is the signal to extract it.

## Component files and data

Shared custom components live in `components/` (the build passes it as
`input_path`). Built-in instruments add new assets there and document their
use in the package README and evidence record. Reflectivity data referenced by
stock names (`HOPG.rfl`) resolves from the McStas data directory.

## Gotchas (each of these cost real debugging time)

- **Emission text is byte-sensitive**: McStasScript renders AT/ROTATED with
  `str()`, so int `0` vs float `0.0` differ; the helpers coerce
  (`_mcstas_number`). Passing vs omitting ROTATED is also visible.
- **McStas `--dir` creates the leaf output folder itself** and aborts if it
  exists; the parent must exist. Don't pre-create the leaf.
- **Component order is physics.** The helpers emit at your call site; nothing
  reorders. Keep the tree in beam order.
- **Peak statistics are spiky**: elastic Bragg intensity rides on rare
  giant-weight events; at 2e6 neutrons two identical runs can differ by 100×.
  Smoke-check at 1e7.
- **`Monitor` (the detector) writes a single-value `detector.dat`** — read the
  `# values: I ERR N` header, not the data columns.
