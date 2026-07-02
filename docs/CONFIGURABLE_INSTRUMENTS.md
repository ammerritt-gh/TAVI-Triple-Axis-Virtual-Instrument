# Configurable Instruments — Research & Plan

**Status:** Design decided; Phase-0 drafted; review §15 folded in (§16);
pre-implementation audit done and Phase 1 + 1.5 fully specified (§17). Ready to
implement.
**Author:** initial draft 2026-06-18; design decisions locked 2026-06-18; review
incorporated 2026-06-18; audit + implementation spec 2026-07-02.
**Decision summary:** Instruments are Python modules (imperative `build()` +
structured GUI descriptor + physics hooks), selected at startup and fixed per
session. Per-instrument libraries. First two instruments: PUMA, then IN8 (ILL).
JSON/YAML definitions are a non-goal. Full rationale in §4; all framing questions
resolved in §12. Phase-1 additions (2026-07-02): Phases 1 and 1.5 land together;
startup picker = CLI flag first, dialog only when >1 instrument registered;
contract tests are pytest in `tests/`; the contract's `new_state` is split into
`default_state()` + `scan_config(...)` (see §5 and §17.2).
**Goal:** Turn TAVI from a PUMA-only simulator into a *general-purpose* triple-axis
spectrometer (TAS) simulator, where new instruments are added through a
consistent, documented format that other researchers can author without rewriting
the GUI or the scan engine.

> This document is the working design record. It captures (a) what is already
> instrument-agnostic, (b) exactly where PUMA is hard-coded, (c) the format
> options for defining an instrument and the recommended one, and (d) a phased
> roadmap. Update it as decisions are made. Open decisions are tracked in
> [§12](#12-open-questions--decisions-needed).

---

## 1. Objective and Success Criteria

A "configurable instrument" build is successful when:

1. **PUMA is one instrument among many**, defined by the same mechanism any
   third-party instrument would use — i.e. PUMA stops being privileged.
2. **Adding an instrument requires no edits to `gui/`, `TAVI_PySide6.py`, or the
   scan engine.** A new instrument is dropped in as a definition (+ any custom
   McStas components/data) and appears in an instrument picker.
3. **The GUI adapts to the selected instrument**: available monochromator/analyzer
   crystals, collimation slots, optional modules (NMO, velocity selector…),
   slits, sample environment, and diagnostic monitors all come from the
   instrument definition rather than hard-coded widget contents.
4. **The format is documented and stable**, with validation and clear error
   messages, so a researcher can build an instrument from a template + reference.
5. **Scans still avoid recompilation** where the current PUMA path does
   (scannable values stay McStas parameters — see `docs/MCSTAS_PARAMETERS.md`).
6. **Existing PUMA behavior and outputs are preserved** (regression-safe migration).

Non-goals (for now): supporting non-TAS instrument classes (e.g. time-of-flight),
a visual instrument builder GUI, or arbitrary user C code beyond McStas components.

---

## 2. Current Architecture: What Is General vs PUMA-Specific

### 2.1 Already instrument-agnostic (reuse as-is or lightly generalize)

| Module | Role | Notes |
|---|---|---|
| `TAS_Instrument` base class (`instruments/PUMA_instrument_definition.py:131`) | Generic TAS state + angle math (`calculate_angles`, `calculate_q_and_deltaE`, sample orientation, L1–L4, A1–A4) | Already the right abstraction layer. The *math* is general; it only takes crystal d-spacings as input. |
| `tavi/tas_geometry.py` | `solve_instrument_angles`, `q_instrument_from_angles`, Q↔angle conversions | General TAS geometry. Comments reference "PUMA convention" but the math is not PUMA-specific. |
| `tavi/sample_mount.py`, `tavi/ub_matrix.py`, `tavi/reciprocal_space.py`, `tavi/space_groups.py` | Sample/reciprocal-space/UB | Fully general; no instrument coupling. |
| `tavi/data_processing.py` | Detector file parsing, scan writing, plotting helpers | Reads `detector.dat`; assumes a single 1-D `Monitor` named `detector` (see §10.3). Otherwise general. |
| `tavi/runtime_tracker.py` | Runtime estimates | **Already keyed by `instrument_name`** (`record_run(..., instrument_name)`, `get_record_count(name)`). Just needs the controller to pass the real instrument name instead of the literal `"PUMA"`. |
| `tavi/mcstas_config.py` | McStas path + MPI launcher resolution | General. |
| `gui/main_window.py`, `gui/docks/base_dock.py` | Dock layout & persistence | General; layout persistence keys off stable `objectName()`s. New instrument-driven widgets must keep stable object names. |

### 2.2 Hard-coded to PUMA (the work surface)

**A. The instrument component tree — the core problem.**
`build_PUMA_instrument()` → `configure_component_tree()`
(`instruments/PUMA_instrument_definition.py:859`–`1659`) is ~800 lines of
imperative McStasScript that bakes in *everything*:

- Fixed arm geometry: `L1=2.150, L2=2.290, L3=0.880, L4=0.750` and many literal
  `AT=[...]` offsets (collimator/slit/monitor positions in metres along each arm).
- Source: `Source_div_Maxwellian_v2`, with focus computed from monochromator size.
- Collimators: `Collimator_linear` instances gated on `alpha_1`, the `alpha_2`
  list (`30/40/60'` at hard-coded z-positions and apertures), `alpha_3`, `alpha_4`.
- Slits: `postmono_slit`, `sample_slit`, `detector_slit`, `exit_beam_tube`,
  `NMO_slit` — fixed positions and dimensions.
- NMO optics: two `FlatEllipse_finite_mirror_optimized` units with PUMA-specific
  geometry, m-value files, rotation logic (`PUMA_instrument_definition.py:1094`–`1267`).
- Velocity selector: `V_selector` block gated on `V_selector_installed`.
- Monochromator & analyzer: `Monochromator_curved`, dimensions from
  `mono_ana_crystals_setup()`.
- Sample orientation arm hierarchy (`sample_gonio`/`sample_chi_arm`/
  `sample_cradle`/`sample_mount`) — this part is *generic TAS* and worth keeping.
- Sample component: a hard-coded `if sample_key == ...` ladder of 4 Al samples
  (`PUMA_instrument_definition.py:1400`–`1486`).
- ~19 diagnostic monitors, each gated on a `diagnostic_settings` key, at fixed
  positions.
- The fixed McStas **parameter set** (`A1_param`, `A2_param`, … `dbl_hgap_param`,
  sample-orientation params) defined at `:878` and `:1324`.

**B. Crystal library.** `mono_ana_crystals_setup()`
(`PUMA_instrument_definition.py:68`) hard-codes only `PG[002]` (+ a "test"
variant) with inline dict literals. Duplicated again inside `validate_angles()`
(`:1687`).

**C. Instrument-specific physics constants.** `PUMA_Instrument.__init__`
(`:375`) sets arm lengths, slit gaps, NMO/selector flags, source type.
`calculate_crystal_bending()` (`:426`) encodes PUMA focusing formulas and minimum
radii (`rhm>=2.0`, `rvm>=0.5`, `rha>=2.0`, `rva=0.8` fixed). `_get_v_selector_frequency`
(`:480`) hard-codes selector geometry.

**D. Per-point parameter snapshot.** `build_puma_point_params()` (`:524`) and
`compute_scan_snapshot()` (`:557`) emit exactly the PUMA parameter dict. The keys
must match the parameters declared in the builder.

**E. Run/execute layer.** `run_PUMA_point()` (`:765`), `PUMARunExecutionState`,
and `_resolve_materialized_binary_path()` assume the instrument name
`"PUMA_McScript"` and the binary `PUMA_McScript.exe`. The logic
(first-run compile → direct-binary reuse) is general and worth keeping.

**F. GUI hard-coding.**
- `gui/docks/instrument_dock.py`: crystal dropdowns (`PG[002]`,
  `PG[002] test`) `:123`–`:128`; NMO options `:138`; velocity-selector checkbox
  `:141`; collimation option lists `:193`–`:226`; slit labels `:232`–`:267`;
  source types `:26`. All static.
- `gui/dialogs/diagnostic_config_dialog.py`: a literal `DIAGNOSTIC_OPTIONS` list
  of 19 PUMA monitor names (`:14`).
- `gui/docks/unified_sample_dock.py`: a literal `sample_map` of 4 Al samples
  (`:104`).

**G. Controller plumbing.** `TAVI_PySide6.py` hard-codes
`self.PUMA = PUMA_Instrument()` (`:85`), constructs `PUMA_Instrument()` for
validation (`:1863`, `:1999`, `:3020`), sets `instrument_name = "PUMA"`
(`:1744`, `:3136`), calls `build_PUMA_instrument`/`run_PUMA_point`/
`compute_scan_snapshot` directly, and references `PUMA_McScript.instr/.c`
filenames (`:3312`, `:3326`). The GUI→config mapping in
`_build_scan_puma_config()` (`:649`) hard-codes every PUMA field.

### 2.3 Summary of the coupling

The good news: **all the genuinely hard physics (Q↔angle, UB, sample mount,
detector parsing, runtime tracking, the compile-once/run-direct execution loop)
is already general or trivially generalizable.** The coupling is concentrated in:
(1) the imperative component-tree builder, (2) three hard-coded "libraries"
(crystals, samples, monitors) and the GUI lists that mirror them, and (3) the
literal `"PUMA"` names threaded through the controller.

---

## 3. Requirements for the Instrument Definition Format

A general TAS instrument definition must express:

1. **Metadata** — display name, id/slug, version, author, description, units.
2. **Global geometry** — arm lengths L1–L4 (and any extra fixed distances).
3. **A component chain** — an ordered list of McStas components, each with:
   - a McStas component *type* (e.g. `Collimator_linear`, `Monochromator_curved`),
   - a unique name (stable, for layout/object identity),
   - placement: `AT`, `ROTATED`, `RELATIVE` (relative to a named arm/component),
   - properties (literal values, references to scannable parameters, or
     expressions in parameters/geometry).
4. **Arms / reference frames** — the rotating frames (`mono_cradle`, `sample_arm`,
   `analyzer_arm`, `detector_arm`, sample-orientation hierarchy) that downstream
   components attach to.
5. **Scannable parameters** — the McStas parameter set + how each maps to a
   computed per-point value (angles, bending, slit gaps, selector freq…).
6. **Conditional / optional modules** — collimation slots, NMO, velocity selector,
   filters: present/absent based on user config, and *recompile vs not*.
7. **Crystal library** — selectable mono/analyzer crystals with d-spacing,
   slab geometry, mosaic, reflectivity files.
8. **Sample slots** — selectable sample environments/components.
9. **Diagnostic monitors** — optional monitors with positions and settings.
10. **Per-point computed physics** — crystal bending formulas, source focus,
    selector frequency, energy/parameter derivations. *This is the hard part:* it
    is real code today, not data.

The tension: items 1, 2, 6–9 are genuinely **data the GUI must read** (the
"knobs"); items 3–4 (the component tree's placement) and item 10 (computed
physics) are naturally **imperative Python** whose only consumer is McStasScript.
The key realization (see §4) is that **the GUI never needs the component tree** —
it needs the knobs. That lets us keep the tree as plain Python and still drive the
GUI from data.

---

## 4. Design Decision: Python Instruments + Structured Descriptor

**Decided (2026-06-18):** instruments are **Python modules**, not data files. Each
instrument supplies an imperative `build(config)` (today's
`build_PUMA_instrument`, formalized behind a contract) plus a small **structured
descriptor** that exposes only the GUI-facing knobs. JSON/YAML definitions are an
explicit **non-goal**.

### Why not a declarative data format

We considered a JSON/YAML component tree walked by a generic engine, and a hybrid
(data tree + Python hooks). Both were rejected for this project's reality:

- **The data format only pays off for non-programmer authoring or sharing
  untrusted instruments as data.** Neither applies: there are few TAS instruments,
  authors are experts, and the work realistically lands on the maintainer. JSON
  just round-trips back into Python with nothing gained.
- **A data/spec tree imposes an expressiveness ceiling** — the engine must already
  support every McStas feature an instrument reaches for (`SPLIT`, `EXTEND`,
  `GROUP`/`WHEN`/`JUMP`, arm chains, Union components, the NMO rotation logic). The
  moment something isn't modeled, you extend the engine instead of building the
  instrument. A Python `build()` has **no ceiling**: it can emit any McStasScript.
- The computed physics (bending + min-radii clamps, source focus, selector
  frequency) is real code today; forcing it into a string expression language
  would reinvent Python badly.

If a future need appears (third parties sharing instruments as data, or a visual
builder), the structured descriptor below is already serialization-friendly, so a
JSON *export* could be added then without redesign. We just don't build it now.

### The chosen shape

An instrument = **one Python module** with three parts:

1. **`descriptor` (structured data — a dataclass).** The only part the GUI binds
   to: metadata, geometry constants (L1–L4), the crystal library, sample library,
   monitor list, optional-module toggles, collimation slots, and the scannable
   parameter list. This is the "GUI → component parameter map" — it deliberately
   does **not** describe where `postmono_slit` sits; the GUI doesn't care.
2. **`build(config)` (imperative Python).** Hand-written McStasScript using shared
   helpers, exactly like PUMA today. It **reads its library values from the same
   `descriptor`** the GUI populated from, so the two cannot drift. Uniform,
   repetitive categories (monitors, collimator slots) should be authored as small
   lists that `build()` *loops over* rather than copy-pasted `if` blocks — a
   code-cleanliness choice inside `build()`, not a format.
3. **`compute_snapshot` / `run_point` / physics hooks.** Per-point parameter
   derivation and the compile-once/run-direct execution loop, lifted from today's
   PUMA functions behind the contract.

The "generic engine" is therefore **a registry + a contract + shared helpers** —
never a tree interpreter. PUMA becomes the first module conforming to it.

### Two-stage rollout (so the app always works)

- **Stage 1 — registry + contract, PUMA as a plugin.** Introduce the registry and
  `InstrumentPlugin` contract; wrap PUMA's existing imperative `build/compute/run`
  behind it; route the controller/GUI through "the active instrument" and delete
  the `"PUMA"` literals. Lowest risk; delivers genuine multi-instrument support.
- **Stage 2 — structured descriptor drives the GUI.** Extract the
  crystal/sample/monitor/module knobs into the descriptor and make
  `InstrumentDock`, the diagnostic dialog, and the sample dock render from it.
  After this, adding a crystal/sample/monitor is a descriptor edit, and a new
  instrument is "copy PUMA's module, edit `descriptor` + `build()`."

---

## 5. The Instrument Contract (Stage 1 target)

> **Realized in Phase-0 draft** — see `instruments/contract.py`. The protocol is
> named `InstrumentPlugin` (not `TASInstrument`) to avoid confusion with the
> existing `TAS_Instrument` physics/config base class (review §16.1).
>
> **Adjusted 2026-07-02** after the pre-implementation audit (§17.2): the drafted
> `new_state(gui_values)` could not express how the controller actually builds a
> scan config, so it is replaced by `default_state()` + `scan_config(...)`, and a
> *transitional* `crystal_info(...)` hook is added. The opaque state alias is
> renamed `InstrumentConfig` → `InstrumentState`.

A registered instrument exposes:

```
InstrumentState = Any   # opaque per-session/per-run state
                        # (today: PUMA_Instrument, a TAS_Instrument subclass)

class InstrumentPlugin(Protocol):
    id: str                         # "puma", "in8", ...
    display_name: str               # "PUMA (FRM-II)"

    def descriptor(self) -> InstrumentDescriptor: ...
        # The GUI-facing knobs: crystals_mono/ana, samples, monitors,
        # modules, collimation, slits, source_types, scannable_parameters,
        # geometry (L1..L4 + senses), axis_limits, detector contract.

    def default_state(self) -> InstrumentState: ...
        # Fresh state with the instrument's defaults. Used for (a) the
        # controller's live per-session state at startup and (b) throwaway
        # states for scan-point validation prepasses.

    def scan_config(self, base_state, gui_values, sample_key,
                    diagnostic_settings, sample_mount) -> InstrumentState: ...
        # Frozen scan-launch config: deep-copies base_state *inside the
        # plugin*, then applies the instrument's GUI-value mapping (replaces
        # the controller's hand-written _build_scan_puma_config).

    def crystal_info(self, mono_label, ana_label) -> tuple[dict, dict]: ...
        # TRANSITIONAL (Phase 1 only): crystal dicts shaped like
        # mono_ana_crystals_setup()'s output. Phase 2 replaces this with
        # descriptor CrystalSpec lookups.

    def build(self, config, diagnostic_mode, diagnostic_settings, ncount) -> ms.McStas_instr: ...
    def compute_snapshot(self, ...) -> dict: ...     # per-point params
    def run_point(self, instrument, snapshot, ...) -> (data, flags, info): ...
```

Why the `new_state` split (audit, §17.2): the scan config is a
`copy.deepcopy(self.PUMA)` of **live session state**, not a pure function of GUI
values — hidden training misalignments (`mis_omega`/`mis_chi`) are set on the
live object from a hash and are deliberately absent from `gui_values`; a
`gui_values -> config` constructor would silently drop them and change
training-exercise physics. `sample_mount` is an explicit argument because
`_build_sample_mount` depends on the controller's `ub_matrix` (session state
built from generic `tavi/` modules) — passing it in keeps the plugin free of UB
coupling. The three controller sites that need a bare state to poke generic TAS
fields into for validation get `default_state()`; the fields they set
(`monocris/anacris/K_fixed/fixed_E/sample_mount`) are `TAS_Instrument`
*base-class* attributes, so setting them directly is instrument-agnostic.

`build` / `compute_snapshot` / `run_point` are exactly today's
`build_PUMA_instrument` / `compute_scan_snapshot` / `run_PUMA_point`, lifted
behind the contract. `PUMARunExecutionState` generalizes to
`RunExecutionState` (verified field-for-field identical; the PUMA module keeps
`PUMARunExecutionState` as an alias until Phase 3). The PUMA-specific
binary-name assumption lives only in `_resolve_materialized_binary_path`'s
*fallback* — the primary path already derives `<input_path>/<instrument.name>.exe`;
the fallback derives from a new `MCSTAS_NAME` module constant.

**Registry.** `instruments/registry.py` exposes `get_instrument(id)` and
`available_instruments()`. Discovery is a simple explicit registry dict to
start (no dynamic import magic), upgraded to entry-point/plugin discovery later.

---

## 6. Library Registries (crystals, samples, monitors, optics)

These are the three hard-coded lists that the GUI mirrors. Generalize each into a
data-driven registry that the instrument descriptor references:

- **Crystals** — replace `mono_ana_crystals_setup()` and its duplicate in
  `validate_angles()` with a crystal table (id → d-spacing, slab w/h, ncols/nrows,
  gap, mosaic, r0, reflect/transmit files). **Owned per-instrument** (crystals,
  slab geometry, and reflectivity files vary a lot between instruments): each
  instrument's descriptor carries its own crystal table. A shared
  `tavi/crystal_library.py` of common crystals (PG[002], Cu[220], Si[111],
  Ge[311], Heusler…) may exist purely as a convenience an instrument can copy
  from, but it is not the source of truth.
- **Samples** — replace the `if sample_key == ...` ladder + `unified_sample_dock`
  `sample_map` with a sample registry (id → component type + properties). Keep the
  "no sample" path. **Owned per-instrument** as well; a shared sample library is an
  optional convenience the descriptor can draw from, not a global list.
- **Monitors / diagnostics** — replace the literal `DIAGNOSTIC_OPTIONS` with a
  per-instrument list of monitor descriptors (name, McStas type, AT/RELATIVE,
  settings). The dialog renders from that list. Quick-select groups ("sample
  region", etc.) become tags on the monitor descriptors.
- **Optional modules** — NMO, velocity selector, filters: declared per-instrument
  with their recompile-on-change semantics, so the GUI can show/hide them.

---

## 7. GUI Configurability

The GUI must become **descriptor-driven**:

1. **Instrument picker** — the active instrument is chosen **at startup** and is
   **fixed for the session** (decided; see §12). Switching instruments starts a
   *new session* (re-init the controller/GUI) rather than live-swapping widgets
   while state is loaded. This deliberately avoids the "run a scan → pick a
   different instrument → run again" path, which is bug-prone and not needed.
   **Picker UX decided 2026-07-02:** a `--instrument <id>` CLI flag always wins;
   a picker dialog appears **only** when more than one instrument is registered
   and no flag was given. With a single registered instrument (PUMA today),
   startup is identical to the current app — no dialog. An unknown id prints the
   available ids to stderr and exits with code 2 before any Qt window is
   created. Selection reads `available_instruments()`.
2. **InstrumentDock** — crystal combos, NMO/optional-module controls, collimation
   slots, slit fields, and source types are populated from the descriptor rather
   than literals. Widgets that don't apply to an instrument are hidden.
3. **Diagnostic dialog** — `DIAGNOSTIC_OPTIONS` comes from the descriptor.
4. **Sample dock** — `sample_map` comes from the sample registry (optionally
   filtered by the instrument).
5. **Layout persistence** — keep `objectName()`s stable. Dynamically built widgets
   need deterministic object names derived from the descriptor (e.g.
   `collimation_slot_<id>`), so `view_layout.json` keeps working. Because the
   instrument is fixed per session, saved GUI values are scoped to the active
   instrument id (one file/block per instrument); on load, validate-and-default any
   missing fields. No mid-session migration needed.

The cleanest pattern: a thin "descriptor → widgets" binding layer so each dock
asks the active instrument descriptor what to show. This keeps `TAVIController`
out of the business of knowing PUMA's specific fields (today `get_gui_values()`
and `_build_scan_puma_config()` enumerate them by hand).

---

## 8. Controller & Plumbing Changes (de-PUMA-ify)

Concrete edits to `TAVI_PySide6.py` for Stage 1:

- Replace `self.PUMA = PUMA_Instrument()` (`:85`) with
  `self.instrument = get_instrument(active_id)` and
  `self.config = self.instrument.new_state(...)`.
- Route `build/compute_snapshot/run_point` through `self.instrument` instead of
  importing PUMA functions directly (`:18`–`:26`, `:3166`, `:3279`).
- Replace `instrument_name = "PUMA"` (`:1744`, `:3136`) with
  `self.instrument.id` for runtime tracking (the tracker is already keyed by name).
- Generalize the `.instr/.c/.exe` filename references (`:3312`, `:3326`) to the
  instrument's McStas name.
- Replace the hand-written `_build_scan_puma_config()` (`:649`) and
  `get_gui_values()` field-by-field mapping with descriptor-driven collection
  (Stage 2; Stage 1 can keep PUMA's mapping inside the PUMA plugin).
- Validation paths that spin up a throwaway `PUMA_Instrument()` (`:1863`,
  `:1999`, `:3020`) call `self.instrument.new_state(...)` instead.

Keep the threading boundary and pipeline (`Queue(maxsize=2)`, `stop_event` drain
semantics) unchanged — they are instrument-agnostic already.

---

## 9. Output, Runtime Tracking & Persistence

- **Output naming** — per-point folders (`scan_XXXX/`) are generic. The copied
  `PUMA_McScript.instr` (`:3311`) generalizes to `<instr_name>.instr`. Consider
  writing the instrument id into scan metadata/`scan_parameters.txt` so saved
  scans record which instrument produced them.
- **Runtime tracker** — already multi-instrument; just feed the real id.
  `config/runtimes.json` will naturally grow per-instrument record sets.
  **Legacy-key migration (decided 2026-07-02):** existing history is keyed by the
  literal `"PUMA"`; switching the controller to `instrument.id` (`"puma"`) would
  orphan it. `RuntimeTracker._load()` gains a one-time legacy-key map
  (`{"PUMA": "puma"}`) that merges old records into the new key on load (legacy
  records first) and drops the old key on the next save. A permanent
  read-both-keys fallback was rejected — it leaves two spellings forever. The
  migration must land in the **same commit** as the controller id switch.
- **Config files** — `config/parameters.json` currently stores a flat PUMA GUI
  state. Plan: namespace by instrument id **with a per-block schema version**
  (`{"puma": {"_schema": 1, ...}}`) so descriptor changes can migrate, default, or
  deliberately discard stale values (review §16.8). Default-fill missing fields on
  load. Since the active instrument is fixed per session (§7), this is just "load
  the block for the session's instrument" — no live migration. Use instrument-
  prefixed dynamic `objectName()`s where the same logical widget id could mean
  different things across instruments. `config/view_layout.json` is layout-only.

---

## 10. McStas Component Dependencies & Distribution

- **Custom components.** PUMA pulls custom assets from `components/`
  (NMO `FlatEllipse_finite_mirror_optimized`, phonon components, m-value `.txt`
  files, `.laz`/`.lau`/`.dat` data). A third-party instrument needs a way to ship
  its own components/data. Plan: allow an instrument to declare a components/data
  search path (its own folder), added to McStasScript's `input_path`. Document the
  expected on-disk layout (e.g. `instruments/<id>/{__init__.py (descriptor +
  build), components/, data/}`).
- **Component availability.** Instruments reference McStas component *types* by
  name. We should validate that referenced components resolve (either built-in to
  the McStas install or present in the instrument's component path) and produce a
  clear error if not.
- **Detector contract (`tavi/data_processing.py`).** Parsing assumes a single
  1-D monitor written to `detector.dat`. The descriptor makes this explicit
  (review §16.9): `primary_detector` (component), `detector_output_file`
  (`"detector.dat"`), and `detector_parser` (`"1d_monitor"`). v1 only permits that
  combination; multi-detector / other parser kinds are deferred but the fields give
  a forward-compatible seam.

---

## 11. Phased Implementation Roadmap

**Phase 0 — Contract sketch & scaffolding. ✅ DRAFTED 2026-06-18.**
Sketched the `InstrumentPlugin` contract, `InstrumentDescriptor` dataclasses, and
the registry interface as importable scaffolding (no wiring, no behavior change).
Validated against PUMA **and** IN8 via example descriptors. Draft files:
- `instruments/descriptor.py` — `InstrumentDescriptor` + spec dataclasses
  (`Geometry` with per-axis `Sense`, `CrystalSpec`, `SampleSpec`, `MonitorSpec`,
  `ModuleSpec`, `CollimationSlot`, `SlitSpec`, `SourceType`, `ParameterSpec`,
  `AxisLimits`). Includes the explicit detector-output contract (§16.9).
- `instruments/contract.py` — `InstrumentPlugin` Protocol (`descriptor`,
  `new_state`, `build`, `compute_snapshot`, `run_point`) + generalised
  `RunExecutionState`.
- `instruments/registry.py` — `register` / `available_instruments` / `get_instrument`
  (factory-based, lazy, startup-fixed selection).
- `instruments/_descriptor_examples.py` — illustrative `puma_descriptor()` (full)
  and `in8_descriptor()` (kinematic skeleton + `TODO`s). Run with
  `python -m instruments._descriptor_examples`.

Key validation result: the per-axis `Sense` field carries IN8's sample sense = −1
vs PUMA's implicit +1, and IN8's `l1_source_mono` is `nan` (TODO from the
instrument scientist) — confirming the contract is not PUMA-shaped. Next: review
the draft, then Phase 1 wires PUMA behind it.

> **Protect the Phase 1/2 boundary (review §16, overall).** Phase 1 is a *thin
> routing change* only — PUMA runs through the registry/contract with byte-identical
> behavior. Phase 2 is descriptor-driven GUI generation. Do **not** mix
> widget-from-descriptor work into the first de-PUMA pass, or a PUMA regression
> becomes hard to attribute.

**Phase 1 — Registry + contract, PUMA as a plugin (routing only).**
> **Fully specified in §17** (2026-07-02): file-by-file change list, controller
> edit groups, commit sequencing, and verification checklist. The bullets below
> remain the intent; §17 is the executable spec and supersedes them where they
> differ (notably: `new_state` split per §5, and the Phase-0 example descriptor
> must gain 8 missing sample-orientation/mount parameters).
- Introduce `instruments/registry.py` + `InstrumentPlugin` contract.
- Wrap PUMA's existing `build/compute_snapshot/run_point` behind the contract;
  rename `PUMARunExecutionState`→`RunExecutionState` and de-hardcode the binary
  name (derive from `instrument.name`).
- Give PUMA a `descriptor()` (it can return the Phase-0 example) and register it via
  one explicit built-in registration module (review §16.10) — no autodiscovery.
- Replace `"PUMA"` literals and direct imports in `TAVI_PySide6.py` with
  registry/`self.instrument` calls; feed `instrument.id` to the runtime tracker and
  let `instrument.mcstas_name` drive `.instr/.c/.exe` filenames.
- Add an instrument picker to the GUI (single entry = PUMA initially).
- **Contract tests (review §16.11):** list instruments without importing/building
  McStas; PUMA descriptor validates; PUMA snapshot `params.keys()` ⊆ descriptor
  `scannable_parameters`; runtime tracking receives `instrument.id`; mcstas_name
  drives filenames; no controller path hard-codes `"PUMA"` except the PUMA plugin.
- **Exit criterion:** PUMA runs identically; nothing in the controller says
  "PUMA" except the plugin id.

**Phase 1.5 — Descriptor validator (review §16.2, do alongside Phase 1).**
- Add `validate_descriptor(d)` checking: unique ids across each list; ids match
  `[a-z0-9_]`; no duplicate McStas parameter names; `primary_detector` present;
  module/collimation defaults are within their options; runnable instruments have
  complete crystal data and **no `nan` placeholders**; component/data paths exist.
- Examples may keep `TODO`/`nan`; a *registered runnable* instrument may not.
- Run it against the Phase-0 examples; use its error messages to drive Phase 2.
- **Decided 2026-07-02:** ships together with Phase 1 as
  `instruments/validation.py`; full rule list (structural vs runnable-only) in
  §17.6. The snapshot-subset rule (`params.keys()` ⊆ `scannable_parameters`)
  lives in the pytest contract tests, not the validator, because it requires
  instantiating instrument state.

**Phase 2 — Structured descriptor + descriptor-driven GUI.**
- Promote PUMA's `descriptor()` to the real source (libraries no longer literal).
- Extract crystal/sample/monitor libraries to data + registries; remove the
  duplicate crystal table in `validate_angles`.
- Make `InstrumentDock`, the diagnostic dialog, and the sample dock render from
  the active descriptor instead of literal lists.
- Introduce a `PointSnapshot` dataclass (review §16.6) replacing the raw snapshot
  dict, so keys (`params`/`metadata`/`indices`/`error_flags`) can't silently drift.
- Namespace `config/parameters.json` per instrument **with a schema-version field**
  (review §16.8); use instrument-prefixed `objectName()`s for dynamic widgets.
- **Exit criterion:** all GUI lists come from the descriptor; adding a crystal,
  sample, or monitor is a descriptor/library edit, not a GUI edit.

**Phase 3 — `build()` cleanup + shared helpers.**
- Refactor PUMA's `build()` so repetitive/optional categories (monitors,
  collimator slots) loop over descriptor lists instead of copy-pasted `if` blocks.
- Factor reusable McStas-tree helpers (arms, mono/ana placement, sample
  orientation hierarchy, slit/collimator emit) into `tavi/instrument_helpers.py`
  so a second instrument reuses them.
- **Exit criterion:** PUMA's `build()` is short and reads from its descriptor; the
  shared helpers cover the common TAS backbone.

**Phase 4 — Authoring kit + IN8.**
- Per-instrument component/data path support, descriptor validation with friendly
  errors, a template instrument module, and `docs/INSTRUMENT_AUTHORING.md`
  (review §16.12): one minimal runnable template, one PUMA-derived example, the
  validation rules, and the expected component/data folder layout — written
  *before* inviting third-party instruments.
- **Golden sign-convention tests FIRST (review §16.7 — highest-risk migration).**
  Before wiring IN8: lock PUMA baseline (HKL/Q → angle) points, add IN8 reference
  angle cases (sourced from vTAS runs or the instrument scientist — see §16 note),
  and round-trip through `solve_instrument_angles()` / `q_instrument_from_angles()`
  with explicit per-axis `Sense` handling. Sign errors look correct in the GUI
  while producing wrong angles, so these tests gate IN8.
- Build **IN8 (ILL)** as the second instrument — a thermal TAS deliberately
  different from PUMA (geometry, optics, crystals, sample sense −1), with the
  instrument scientist as ground-truth contact. IN8 is the test that the contract
  isn't secretly PUMA-shaped; expect it to surface where module logic diverges.

Each phase leaves a shippable app. Phases 1–2 deliver the user-visible
multi-instrument configurability; 3–4 make authoring a new instrument a
copy-edit-PUMA exercise.

---

## 12. Open Questions — Decisions Needed

All seven framing questions are resolved (decisions dated 2026-06-18):

1. ~~Instrument format: declarative vs Python.~~ **Python modules** (imperative
   `build()` + structured descriptor); JSON/YAML is a non-goal. See §4.
2. ~~Hook delivery / sandboxing.~~ Plain Python functions in the instrument
   module; trusted by design (authors are maintainers).
3. ~~Instrument switching at runtime.~~ **Fixed per session, chosen at startup.**
   Switching = new session (re-init), not a live widget swap. We explicitly do
   *not* support run-scan → change-instrument → run-again. See §7.1.
4. ~~Where crystal/sample libraries live.~~ **Per-instrument** (they vary a lot).
   Optional shared convenience tables only; the descriptor is the source of truth.
   See §6.
5. ~~How much PUMA realism is "the contract".~~ **Module-local.** Min-radii clamps,
   `rva=0.8`, selector geometry are PUMA's business, not framework rules. The
   contract must accommodate instruments whose per-point physics differs
   substantially — IN8 will stress this; revisit the hook surface then.
6. ~~Multi-detector output.~~ **Single `detector.dat` for v1.** Descriptor names
   the primary detector; multi-detector is deferred.
7. ~~Second instrument.~~ **IN8 (ILL)** — instrument scientist available for
   ground-truth validation. See Phase 4.

**Carry-forward design risk (not blocking):** §12.5 — some instruments need
genuinely different module logic. The Python-`build()` choice is what absorbs
this, but the *contract* (`compute_snapshot`/hook signatures, the per-point
parameter dict shape) must be general enough not to bake in PUMA's parameter set.
Design the contract against PUMA **and** a sketch of IN8 before finalizing it in
Phase 1.

---

## 13. Appendix — Key Source References

- Component tree builder: `instruments/PUMA_instrument_definition.py:859`–`1659`.
- Crystal library: `…:68` (and duplicate at `…:1687`).
- Crystal bending / focus / selector: `…:426`, `…:480`, `…:524`.
- Per-point snapshot: `…:524`, `…:557`.
- Run/execute layer: `…:717`–`856`.
- Controller wiring: `TAVI_PySide6.py:18`, `:85`, `:649`, `:1744`, `:3136`,
  `:3166`, `:3279`, `:3311`.
- GUI lists: `gui/docks/instrument_dock.py:123`,
  `gui/dialogs/diagnostic_config_dialog.py:14`,
  `gui/docks/unified_sample_dock.py:104`.
- Already-general modules: `tavi/tas_geometry.py`, `tavi/sample_mount.py`,
  `tavi/ub_matrix.py`, `tavi/runtime_tracker.py`, `tavi/data_processing.py`.
- Phase-0 draft scaffolding: `instruments/descriptor.py`, `instruments/contract.py`,
  `instruments/registry.py`, `instruments/_descriptor_examples.py`.
- Phase-1/1.5 implementation spec: §17 (new/modified file lists, controller edit
  groups, validator rules, contract tests, sequencing, verification).
- IN8 reference data: `examples/vtas_reference/instruments_repository.xml` (ILL vTAS).

---

## 14. IN8 Reference Data — extracted from ILL vTAS

**Source.** ILL's *vTAS* simulator (Java, v4.8, 2018). The `examples/` launcher
files (`vTAS-JNLP.dmg`, `vTAS.jnlp`) only bootstrap Java Web Start; the real data
lives in `vTAS.jar`, downloaded from
`https://www.ill.eu/fileadmin/user_upload/ILL/3_Users/Support_labs_infrastructure/Software-tools/vTAS/vTAS.jar`.
Extracted reference copies are kept in `examples/vtas_reference/`
(`instruments_repository.xml`, `samples_repository.xml`,
`sampleType_repository.xml`, `vtasConstants.properties`). The jar itself was not
retained (10.6 MB; re-downloadable).

**What vTAS is (and isn't).** vTAS is a *kinematic / resolution* TAS simulator: it
solves axis angles, draws the instrument footprint, computes resolution
ellipsoids, and checks shielding-wall collisions. It is **not** a Monte-Carlo
ray-tracer — no source spectrum, slits, collimator divergences, focusing
curvature, monitors, or McStas components. So its repository is an authoritative
reference for the **kinematic skeleton + axis limits + multiplex options**, but
TAVI still needs the McStas "flesh" (source, slits, collimators, focusing, sample,
detector) from IN8 instrument docs / the instrument scientist.

**vTAS instrument schema (a real cross-instrument minimal set).** Each
`<instrument>` carries:
- distances: `srr` = mono→sample (DMS), `arr` = sample→ana (DSA), `drr` = ana→det
  (DAD); some add `atr` (analyser-table radius), `dtw`/`dtl` (detector tube w/l).
  vTAS does **not** model source→mono (PUMA's L1) — irrelevant to angles, but
  TAVI's McStas source needs it from elsewhere.
- scattering senses: `sm`, `ss`, `sa` = ±1 for mono / sample / analyser.
- per-axis limits: `<a2|a4|a6 ll df ul>` = lower / default / upper (deg) for mono
  take-off (a2), sample 2θ (a4), analyser take-off (a6).
- crystals: `<monochromator D=…>`, `<analyser D=…>` — d-spacing in Å only (no named
  crystal library; PG002 = 3.355).
- options: `flatcone` / `imps` / `ufo` / `multiflexx` booleans + sub-geometry
  blocks for the multiplexed-analyser arrays.
- `<walls>` floor-plan polygon (footprint/collision; not physics).

This maps almost one-to-one onto the `InstrumentDescriptor` of §4 — independent
confirmation that a small declarative struct really does capture cross-instrument
variation.

**IN8 concrete parameters (`ILL IN8`):**

| Quantity | IN8 (vTAS) | PUMA (TAVI) |
|---|---|---|
| mono→sample | 2.5 m | 2.290 (L2) |
| sample→ana | 1.35 m | 0.880 (L3) |
| ana→det | 0.65 m | 0.750 (L4) |
| source→mono | not modeled | 2.150 (L1) |
| mono D / ana D | 3.355 / 3.355 Å (PG002) | 3.355 / 3.355 |
| senses sm/ss/sa | +1 / −1 / +1 | implicit / fixed |
| a2 (mono 2θ) ll/df/ul | −40 / 77.256 / 110° | — |
| a4 (sample 2θ) ll/df/ul | −120 / −111.08 / 120° | — |
| a6 (ana 2θ) ll/df/ul | −120 / 83.957 / 120° | — |
| sample-table radius `str` | 0.3 m | — |

IN8 has no multiplex option by default, but `ILL IN8-IMPS` (a 9-blade IMPS
multi-analyser + 8-blade collimator) is in the repository, and FlatCone "can be
installed on IN8, IN14 and IN20."

**PUMA → IN8 deltas the contract must absorb (feeds §12.5):**
1. **Scattering senses (sm/ss/sa).** PUMA bakes a fixed handedness into its arm
   rotations; IN8 has `ss = −1`. The descriptor must carry per-axis senses and the
   angle solve / `build()` must honor them rather than assuming PUMA's signs. This
   is the most likely hidden PUMA assumption — verify against `tas_geometry`'s
   "positive A3 rotates +x toward −z" convention and `compute_scan_snapshot`.
2. **Different arm lengths** (notably longer sample→ana). Pure data — already
   parameterized as L2/L3/L4.
3. **Multiplexed analysers (IMPS / FlatCone on IN8).** Multiple analyser channels +
   multiple detectors — breaks the single-`detector.dat` v1 assumption (§12.6) and
   is genuinely different module logic. **v1 target = plain IN8** (single
   analyser/detector); IMPS/FlatCone explicitly deferred but now scoped.
4. **Missing "flesh."** vTAS has no L1, source spectrum, guide/collimation, slit, or
   focusing detail — all must come from IN8 docs / the instrument scientist.

**Also in the jar (not extracted, FYI):** compiled geometry classes
(`model/instruments/{Instrument,FlatCone,IMPS,UFO}.class`) and
`view/.../McStasFlatConeProcess.class` — vTAS apparently emits McStas for FlatCone
resolution. Re-downloadable if we ever want to decompile the multiplex geometry
math (needs a Java decompiler; the available decompiler MCP is .NET-only).

---

## 15. Review Feedback - 2026-06-18

Overall, this is a strong direction. The most important architectural choice is
the right one: keep the McStas component tree and instrument-specific physics in
Python, and expose only the stable GUI/configuration surface through a structured
descriptor. That keeps the project from building a fragile mini-language while
still giving TAVI the thing it actually needs for multi-instrument support:
discoverable instruments, validated per-instrument options, and a controller that
does not know PUMA by name.

My main recommendation is to protect the Phase 1/2 boundary. Phase 1 should be a
thin routing change that makes PUMA run through the registry/contract with
identical behavior. Phase 2 should be the GUI descriptor extraction. Avoid mixing
descriptor-driven widget generation into the first de-PUMA pass; otherwise any
PUMA regression will be harder to attribute.

Concrete feedback:

1. **Rename the runtime state object to avoid type confusion.** The current plan
   uses both `TAS_Instrument` (existing physics/config state) and `TASInstrument`
   (new plugin protocol). That is very easy to misread. Consider naming the
   protocol `InstrumentPlugin` or `TASInstrumentPlugin`, and the existing
   per-run object `InstrumentState` / `TASState` over time.

2. **Make descriptor validation a first-class Phase 1.5 step.** Before the GUI is
   generated from descriptors, add a validator that checks unique ids, legal
   object-name characters, duplicate McStas parameter names, matching
   `primary_detector`, valid default options, complete crystal data for runnable
   instruments, and component/data paths. The examples can contain TODOs, but a
   registered runnable instrument should not contain `nan` placeholders.

3. **Use stable ids distinct from display labels.** Values like `PG[002]` are good
   labels but awkward ids for config keys, filenames, and object names. Prefer ids
   like `pg002` with `display_name="PG[002]"`. The same applies to samples,
   monitors, modules, and collimation options.

4. **Define compile-time vs runtime-change semantics per setting.** The document
   mentions optional modules requiring recompilation, but this distinction should
   exist for every descriptor-controlled setting that affects McStas topology or
   component parameters. This will matter for saved configurations, UI locking
   during scans, and future "new session with instrument/config" flows.

5. **Be careful that monitor descriptors do not become a second component-tree
   format by accident.** It is fine for PUMA's `build()` to loop over a monitor
   table, but decide whether monitor placement belongs in the public descriptor or
   in the instrument module's private build data. If the descriptor is promised as
   "GUI-facing only", placement fields are a small exception worth documenting.

6. **Give snapshots and run results typed shapes soon.** The proposed
   `compute_snapshot()` dict mirrors today's PUMA code, which is useful for the
   migration. But after Phase 1, a `PointSnapshot` dataclass (or at least a
   validator) would prevent silent drift in keys like `params`, `metadata`,
   `indices`, and `error_flags`. Also validate that `params.keys()` is a subset of
   the descriptor's `scannable_parameters`.

7. **Treat sign conventions as the highest-risk physics migration.** IN8's sample
   sense is exactly the kind of difference that can look correct in the GUI while
   producing wrong angles. Add golden tests before wiring IN8: PUMA baseline
   points, IN8 vTAS reference angle cases, and round trips through
   `solve_instrument_angles()` / `q_instrument_from_angles()` with explicit
   sense handling.

8. **Namespace persistence by both instrument id and schema version.** The plan to
   store `{"puma": {...}, "in8": {...}}` is good. Add a small version field inside
   each instrument block so future descriptor changes can default, migrate, or
   discard stale values deliberately. Use instrument-prefixed dynamic
   `objectName()`s where the same logical widget id could mean different things
   across instruments.

9. **Make the detector contract slightly more explicit.** `primary_detector` names
   the component, but `data_processing.py` also assumes an output file shape
   (`detector.dat`, 1-D monitor data). Put the expected output filename and parser
   kind in the descriptor, even if v1 only permits `detector.dat` / `1d_monitor`.

10. **Keep registration explicit and lazy.** The registry sketch is good. For the
    first implementation, use an explicit built-in registration module rather than
    package scanning or import side effects. That keeps startup predictable and
    avoids importing McStasScript/PySide-heavy instrument modules just to populate
    the picker.

11. **Add contract tests that lock in "PUMA is not special."** Useful tests:
    available instruments can be listed without importing/building McStas,
    PUMA descriptor validates, PUMA snapshot parameter keys match descriptor
    parameters, runtime tracking receives `instrument.id`, generated McStas names
    drive `.instr/.c/.exe` filenames, and no controller path contains hard-coded
    `"PUMA"` except in the PUMA plugin/descriptor.

12. **Document the authoring surface separately from this design record.** This
    document is doing its job as the design record. Before inviting new
    instruments, create a shorter `INSTRUMENT_AUTHORING.md` with one minimal
    runnable template, one PUMA-derived example, validation rules, and the expected
    component/data folder layout.

Suggested immediate next step: implement Phase 1 with PUMA only, plus a descriptor
validator that can run against the Phase 0 examples. Once PUMA's behavior is
unchanged through the registry path, use the validator's error messages to guide
the descriptor-driven GUI work in Phase 2.

---

## 16. Review Disposition — 2026-06-18

The review (§15) was folded into the plan and Phase-0 drafts. Status legend:
**Done** = applied to the draft code/doc now; **Planned** = written into the
roadmap; **Decided** = a judgement call made here (noted for override).

| # | Topic | Disposition | Where |
|---|---|---|---|
| — | Protect Phase 1/2 boundary | **Planned** | §11 callout: Phase 1 = routing only; Phase 2 = descriptor-driven GUI |
| 1 | Name collision `TAS_Instrument` vs protocol | **Done** | Protocol renamed `TASInstrument`→`InstrumentPlugin` in `contract.py`/`registry.py`/§5. Renaming the *state* object (`TAS_Instrument`→`TASState`) **deferred** — it's load-bearing in PUMA; do it during Phase 1+ (see open Q1) |
| 2 | Descriptor validator as first-class step | **Planned** | New **Phase 1.5** with explicit rule list |
| 3 | Stable ids ≠ display labels | **Done** | Crystal ids `PG[002]`→`pg002` in examples; id convention documented in `descriptor.py`. Sample ids intentionally keep the existing `sample_key` strings |
| 4 | Compile-time vs runtime per setting | **Decided (partial)** | Principle documented (settings that map to a `ParameterSpec` = runtime/no-recompile; topology/component-set changes = build-time/recompile, per `docs/MCSTAS_PARAMETERS.md`). A per-field `ChangeImpact` enum is **deferred to Phase 2** rather than bloating every dataclass now (open Q4) |
| 5 | Monitors as a second tree format | **Decided** | Keep placement in `MonitorSpec` as the **one documented exception** to "GUI-facing only", justified by anti-drift (one def feeds GUI toggle + `build()` loop). Documented in `descriptor.py` (open Q2) |
| 6 | Typed snapshot/result shapes | **Planned** | `PointSnapshot` dataclass in Phase 2; `params.keys() ⊆ scannable_parameters` added to the Phase 1.5 validator |
| 7 | Sign conventions = highest risk | **Planned** | Golden angle tests gate IN8 in Phase 4 (note: IN8 reference angles must be sourced from vTAS runs or the scientist — open Q3) |
| 8 | Persistence: id + schema version | **Planned** | §9 updated (`_schema` field; instrument-prefixed `objectName()`s) |
| 9 | Explicit detector output contract | **Done** | `detector_output_file` + `detector_parser` added to `InstrumentDescriptor`; §10 updated |
| 10 | Explicit + lazy registration | **Planned** | Phase 1 uses one built-in registration module; registry is already factory-based/lazy |
| 11 | "PUMA is not special" contract tests | **Planned** | Listed as Phase 1 exit tests |
| 12 | Separate `INSTRUMENT_AUTHORING.md` | **Planned** | Phase 4, with template + PUMA example + validation rules + folder layout |

**Agreement with the framing.** The review's core point — Phase 1 must be a thin,
behavior-identical routing change, with GUI generation held to Phase 2 — is
correct and now the load-bearing constraint of the roadmap. The validator-first
suggestion is adopted as Phase 1.5.

**Open questions back to the reviewer / maintainer:**
1. **Rename the state object too?** `TAS_Instrument` (per-run physics/config) could
   become `TASState`/`InstrumentState`. *Recommend deferring* — it's referenced
   throughout PUMA and the controller; rename it as a dedicated step once Phase 1
   routing is stable, not mixed into it.
   *Partially resolved 2026-07-02:* the `TAS_Instrument` **class** rename stays
   deferred, but Phase 1 does rename the contract's opaque alias
   (`InstrumentConfig` → `InstrumentState`) and the controller's attribute
   (`self.PUMA` → `self.instrument_state`) — the latter is required by the
   Phase-1 exit criterion anyway.
2. **Confirm the monitor-placement decision (#5).** I kept placement inside
   `MonitorSpec` (anti-drift) rather than splitting GUI vs build tables. Override if
   you'd rather the public descriptor be strictly GUI-only.
3. **Source of IN8 golden angles (#7).** The golden sign tests need trusted
   (HKL,E)→(A1,A2,A4) reference points for IN8. Options: run vTAS for known
   reflections, or get a few from the instrument scientist. Which do you prefer?
4. **Per-setting `ChangeImpact` (#4).** I documented the recompile-vs-runtime
   principle but deferred a per-field enum to Phase 2. OK, or do you want it on the
   dataclasses from the start?

---

## 17. Pre-Implementation Audit & Phase 1/1.5 Spec — 2026-07-02

A full audit of the PUMA module, controller, and GUI surfaces was done
immediately before implementation, together with three scope decisions from the
maintainer. This section is the executable spec for Phases 1 + 1.5; where it
differs from the sketch-level bullets in §11, this section wins.

### 17.1 Locked decisions (2026-07-02)

1. **Scope:** Phase 1 and Phase 1.5 land together (validator + pytest contract
   tests alongside the routing change).
2. **Startup picker:** `--instrument <id>` CLI flag always wins; picker dialog
   only when >1 instrument is registered and no flag given (see §7.1). With only
   PUMA registered, startup is byte-identical to today.
3. **Tests:** pytest in `tests/` — infrastructure already exists
   (`tests/test_tas_geometry.py`). pytest itself is **not installed** in the
   working micromamba env (`tavi`); add `requirements-dev.txt` with `pytest`.

### 17.2 Audit findings that changed the design

1. **`new_state` split (§5 updated).** `_build_scan_puma_config()`
   (`TAVI_PySide6.py:649`) deep-copies **live session state** (`self.PUMA`) —
   which carries hidden training misalignments set from a hash (`:2626`,
   `:2677`) that never appear in `gui_values` — before applying ~22 GUI fields.
   Hence `default_state()` + `scan_config(base_state, gui_values, sample_key,
   diagnostic_settings, sample_mount)`, with the deepcopy inside the plugin.
2. **`sample_mount` is an explicit `scan_config` argument.**
   `_build_sample_mount` (`:684`) depends on the controller's `ub_matrix`
   (session state from generic `tavi/` modules); passing the built `SampleMount`
   in keeps UB coupling out of the plugin. `_build_sample_mount` stays in the
   controller.
3. **Transitional `crystal_info()` hook.** The controller needs
   `monocris_info['dm']` / `anacris_info['da']` for seven live-calculation
   handlers plus init. Phase 1 delegates to the existing
   `mono_ana_crystals_setup()` via the plugin (same dicts, zero drift); Phase 2
   replaces it with descriptor lookups.
4. **Lazy-import blocker.** `PUMA_instrument_definition.py` imports
   `mcstasscript` at module level (`:3`). Therefore: registration stores only
   `(id, display_name, factory)`; `instruments/puma_plugin.py` keeps **all**
   references to the heavy module function-local; a subprocess-based test
   asserts listing pulls in neither `mcstasscript`, `PySide6`, nor
   `instruments.PUMA_instrument_definition`.
5. **The Phase-0 example descriptor is 8 parameters short.** The real instrument
   declares **25** McStas parameters (`:878–893` + `:1324–1333`), matching
   `build_puma_point_params` (`:524`). Missing from `_PUMA_PARAMS`: `chi_param`,
   `kappa_param`, `mis_chi_param`, `psi_param`, `mis_omega_param`,
   `mount_rx_param`, `mount_ry_param`, `mount_rz_param`. They join the shared
   core set (generic sample-orientation hierarchy → IN8 inherits them too).
6. **Already general (less work than §2.2 implied):**
   `_resolve_materialized_binary_path` (`:717`) already derives
   `<input_path>/<instrument.name>.exe` — only its *fallback* (`:724`)
   hard-codes `PUMA_McScript.exe`; `add_record(...)` at `TAVI_PySide6.py:3537`
   already passes a variable (the literals are at `:1744`, `:2354`, `:3136`).
7. **Dead import:** the controller imports `validate_angles` (`:24`) but never
   calls it — the import is simply dropped.
8. **K↔E converters are instrument-independent** (`k2angle`, `angle2k`,
   `k2energy`, `energy2k`, `energy2lambda` at `:41–66` take d-spacing as an
   argument). They move to a new `tavi/neutron_conversions.py`; the PUMA module
   re-exports them for backward compatibility. This also removes the seven
   function-local `from instruments.PUMA_instrument_definition import …` lines
   in the controller.

### 17.3 Pre-existing defects found (preserved verbatim in Phase 1)

Byte-identical rule: none of these are fixed in the routing pass; they are
recorded here so later phases pick them up deliberately.

1. `validate_angles` (`PUMA_instrument_definition.py:1661`) duplicates the
   crystal table with **divergent values** (mono slabwidth 0.018 vs 0.0202;
   analyzer ncolumns/nrows swapped: 5/21 vs 21/5). Fix belongs to Phase 2's
   single crystal source.
2. `TAVI_PySide6.py:2626` calls `set_misalignment(omega_m, chi_m, psi_m)` (3
   args) against a 2-parameter signature
   (`set_misalignment(mis_omega=None, mis_chi=None)`,
   `PUMA_instrument_definition.py:186`); the `TypeError` is caught at `:2635`,
   so misalignment-hash restore from `parameters.json` silently fails today.
3. `update_monocris_info`/`update_anacris_info` are each defined **twice** in
   the controller (`:577`/`:584` and `:1494`/`:1501`; the later definitions win
   at runtime). Route all four through `crystal_info`; do not dedupe.
4. Environment: `run-tavi-dev.bat` targets micromamba env `tavi-dev`, which does
   not exist on the dev machine (envs: `base`, `mcstas`, `tavi`). Verification
   uses `micromamba run -n tavi …`. Fixing the launcher is out of scope except
   an optional `%*` passthrough for `--instrument`.

### 17.4 New files

| File | Purpose |
|---|---|
| `tavi/neutron_conversions.py` | K↔E/angle converters moved verbatim from the PUMA module (+ constants they use); PUMA re-exports |
| `instruments/puma_plugin.py` | `PUMAPlugin` (import-light; heavy imports function-local); `puma_descriptor()` moves here with the 8 added params; `scan_config` gets the verbatim `_build_scan_puma_config` body |
| `instruments/builtin.py` | Explicit lazy registration: `register("puma", "PUMA (FRM-II)", PUMAPlugin)` |
| `instruments/validation.py` | `validate_descriptor` / `assert_valid_descriptor` (§17.6) |
| `gui/dialogs/instrument_picker_dialog.py` | Minimal QDialog; only shown when >1 registered; `objectName("instrument_picker_dialog")` |
| `tests/test_instrument_registry.py` | Registry roundtrip/duplicates/errors + subprocess lazy-import test |
| `tests/test_descriptor_validation.py` | Validator positive/negative cases + `add_parameter` source-scan (25 names == descriptor) |
| `tests/test_puma_plugin.py` | Protocol/defaults/scan_config/snapshot-⊆-descriptor/alias/binary-fallback/crystal_info tests |
| `tests/test_controller_is_instrument_agnostic.py` | Source scan: no `"PUMA"`, no direct PUMA import, routing calls present |
| `tests/test_runtime_tracker_legacy_key.py` | Legacy `"PUMA"`→`"puma"` migration tests |
| `requirements-dev.txt` | `pytest` |

### 17.5 Modified files

- **`instruments/contract.py`** — adjusted contract per §5 (alias rename,
  `default_state`/`scan_config`/`crystal_info`); `RunExecutionState`, `build`,
  `compute_snapshot`, `run_point` unchanged from the draft.
- **`instruments/PUMA_instrument_definition.py`** (mechanical only): delete the
  `PUMARunExecutionState` dataclass → import `RunExecutionState` from the
  contract, keep `PUMARunExecutionState = RunExecutionState` alias (remove in
  Phase 3); add `MCSTAS_NAME = "PUMA_McScript"` used at `:874` and in the `:724`
  fallback; replace converter definitions with `tavi.neutron_conversions`
  re-exports. Nothing else — not `validate_angles`, not
  `mono_ana_crystals_setup`, not `compute_scan_snapshot`.
- **`instruments/_descriptor_examples.py`** — re-import `puma_descriptor` from
  the plugin; add the 8 params to `_CORE_PARAMS`; `__main__` also runs the
  validator on both examples and prints results.
- **`instruments/registry.py`** — doc comments only ("Phase-0 DRAFT" → live).
- **`tavi/runtime_tracker.py`** — legacy-key migration in `_load()` (§9); same
  commit as the controller id switch.
- **`TAVI_PySide6.py`** — edit groups:
  - **G1 imports:** delete the PUMA import block (`:18–26`, incl. dead
    `validate_angles`); add `RunExecutionState` + converter imports. Keep
    `import mcstasscript as ms` (`:12` — used at `:488`, instrument-agnostic).
  - **G2 constructor:** `__init__(self, window, instrument)`;
    `self.instrument = instrument`;
    `self.instrument_state = instrument.default_state()` (was `self.PUMA`);
    `self._mcstas_name = instrument.descriptor().mcstas_name`; crystal init via
    `self.instrument.crystal_info("PG[002]", "PG[002]")`.
  - **G3 rename:** `self.PUMA` → `self.instrument_state` (22 occurrences;
    preserve the 3-arg `set_misalignment` call at `:2626` as-is).
  - **G4 crystal info:** 4 `mono_ana_crystals_setup` call sites
    (`:581/:588/:1498/:1505`) → `self.instrument.crystal_info(...)`.
  - **G5 converters:** delete the 7 function-local import lines.
  - **G6 scan config:** delete `_build_scan_puma_config` (body → plugin); call
    `self.instrument.scan_config(self.instrument_state, vals, sample_key,
    diagnostic_settings, self._build_sample_mount(vals))`; rename
    `scan_puma_config` locals → `scan_config`.
  - **G7 throwaway states:** `PUMA_Instrument()` at `:1863/:1999/:3020` →
    `self.instrument.default_state()`; attribute pokes unchanged.
  - **G8 pipeline routing:** `:2894` → `self.instrument.compute_snapshot`;
    `:3166` → `self.instrument.build`; `:3172` → `RunExecutionState()`;
    `:3279` → `self.instrument.run_point`. Queue/`stop_event` pipeline
    untouched.
  - **G9 names/filenames:** `:1744/:3136` → `self.instrument.id`; `:2354` →
    `get_record_count(self.instrument.id)`; `:3312–3313/:3326` →
    `f"{self._mcstas_name}.instr"` / `.c`.
  - **G10 `main()`:** `argparse.parse_known_args()` **before** `QApplication`
    (leftover args go to Qt); `import instruments.builtin`; unknown id → stderr
    + exit 2 pre-Qt; flag → use; elif exactly 1 registered → auto-select; else
    picker dialog (after `QApplication`, Cancel → exit 0); then
    `assert_valid_descriptor(plugin.descriptor(), runnable=True)` fail-fast;
    `TAVIController(window, plugin)`.
  - **G11 comment sweep:** reword remaining "PUMA" comments/docstrings so the
    case-sensitive source-scan test passes.
- **`run-tavi-dev.bat`** (optional): append `%*` for flag passthrough.

### 17.6 `validate_descriptor` rules

`validate_descriptor(d, *, runnable=False) -> list[str]` (empty = valid) plus
`assert_valid_descriptor` raising `DescriptorValidationError`.

**Structural (always — examples must pass):** instrument id slug
(`^[a-z0-9_]+$`) + non-empty display name; slug ids for crystals, modules,
collimation, slits, source types (**exceptions:** `SampleSpec.id` and
`MonitorSpec.id` keep legacy strings — non-empty + unique only); per-list id
uniqueness; parameter names unique and valid C identifiers; `primary_detector`
non-empty; v1 detector contract exactly `detector.dat`/`1d_monitor`; module
`CHOICE` default ∈ options / `TOGGLE` default is bool; collimation default ∈
allowed; L2/L3/L4 finite > 0 (`l1_source_mono` exempt — vTAS omits it);
axis limits `lower ≤ default ≤ upper`, finite; senses are `Sense` members.

**Runnable-only (registered instruments must pass; examples may fail):** no
`nan`/`inf` anywhere (incl. `l1_source_mono` > 0); crystal specs complete (all
optional fields non-None, numerics finite/positive); `mcstas_name` set and a
valid C identifier; `component_path` exists on disk if set; non-empty libraries
(≥1 mono crystal, ana crystal, sample, source type, scannable parameter).

Expected results: fixed `puma_descriptor()` → `[]` at `runnable=True`;
`in8_descriptor()` → `[]` at `runnable=False`, and at `runnable=True` errors
naming at least `l1_source_mono`, crystal completeness, and `source_types`.

### 17.7 Contract tests (pytest; heavy tests `pytest.importorskip("mcstasscript")`)

Key assertions per file (see §17.4 for the file list):

- **Registry:** roundtrip with `_FACTORIES` snapshot/restore fixture; duplicate
  id raises; unknown-id error lists available ids; `instruments.builtin`
  registers puma; **subprocess lazy test** — listing must not import
  `mcstasscript`, `PySide6`, or `instruments.PUMA_instrument_definition`.
- **Validator:** PUMA runnable-valid; IN8 example-valid / runnable-invalid
  (assert error substrings); parametrized negatives via `dataclasses.replace`;
  **source-scan:** regex `add_parameter\(\s*"(\w+)"` over the PUMA module ==
  the 25 descriptor parameter names.
- **Plugin:** `isinstance(PUMAPlugin(), InstrumentPlugin)`; id/display/mcstas
  name consistency; `default_state()` matches legacy defaults and returns fresh
  objects; `scan_config` applies the full GUI mapping (incl. `rva == 0.8`,
  NMO ⇒ `rhm = rvm = 0`, `alpha_2` list, base not mutated, hidden `mis_omega`
  propagates); **snapshot `params.keys()` == descriptor parameter names**;
  `PUMARunExecutionState is RunExecutionState`; binary fallback ends with
  `PUMA_McScript.exe` and `SimpleNamespace(input_path=tmp, name="Foo")` →
  `Foo.exe`; `crystal_info` equals `mono_ana_crystals_setup`.
- **Controller source-scan:** no case-sensitive `"PUMA"`, no
  `"PUMA_instrument_definition"`, and positive presence of
  `self.instrument.build(` / `.compute_snapshot(` / `.run_point(`.
- **Runtime tracker:** legacy `"PUMA"` records migrate/merge to `"puma"`;
  MAX_RECORDS trim still applies.

### 17.8 Sequencing & verification

One commit per step; the app launches and scans identically after each:

0. **Baseline capture** — short 3-point scan in env `tavi`; keep the output
   folder (deterministic `PUMA_McScript.instr` + per-point
   `scan_parameters.txt`) as the golden reference.
1. `tavi/neutron_conversions.py` + PUMA re-export.
2. Contract adjustments + PUMA module mechanics (alias, `MCSTAS_NAME`).
3. Plugin + `builtin.py` + `validation.py` + example fixes (nothing app-facing
   imports these yet); registry/validator/plugin tests pass.
4. **Switch-over commit** — all controller groups G1–G11 + picker dialog +
   runtime-tracker migration. Phase-1 exit criterion.
5. Remaining tests (controller scan, tracker migration) + docs +
   `requirements-dev.txt`.

Verification checklist:

1. `micromamba run -n tavi python -m py_compile <all changed .py files>`.
2. `micromamba run -n tavi python -m pip install pytest` (once), then
   `micromamba run -n tavi python -m pytest tests -q` from the repo root.
3. `micromamba run -n tavi python -m instruments._descriptor_examples` — PUMA
   runnable-valid; IN8 example-valid / runnable-invalid.
4. Launch matrix: no flag → no picker, identical startup; `--instrument puma` →
   identical; `--instrument nope` → stderr lists `puma`, exit 2, no window.
5. **Byte-identical scan check:** rerun the Step-0 scan;
   `PUMA_McScript.instr` must be byte-identical to the baseline (detector
   counts are Monte-Carlo stochastic and are *not* expected to match);
   `scan_parameters.txt` identical except timestamps/counts; "Direct run
   armed" still appears on point 2 (direct-invocation path intact).
6. `config/runtimes.json`: records under `"puma"` with legacy `"PUMA"` merged;
   pre-scan estimate non-empty (history survived the migration).
