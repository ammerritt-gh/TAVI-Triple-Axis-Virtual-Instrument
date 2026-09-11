# Configurable Instruments — Research & Plan

**Status:** Design decided; Phase-0 drafted; review §15 folded in (§16);
Phase 1 + 1.5 IMPLEMENTED (2026-07-02, spec §17). **Phase 2 IMPLEMENTED
(2026-07-02, spec §18):** the GUI renders from the descriptor (instrument dock,
sample dock, diagnostic dialog), the descriptor is the single source for
crystal/sample/monitor data, snapshots are typed (`PointSnapshot`),
`config/parameters.json` is namespaced per instrument with a schema version,
and ChangeImpact + `build_fingerprint` groundwork is in place. **Cross-scan
binary reuse IMPLEMENTED (2026-07-02, §18.5)** along with two direct-execution
fixes that were masking it. **Phase 3 IMPLEMENTED (2026-07-02, spec §19):**
build() emits monitors/samples/collimators/crystals through shared helpers in
`tavi/instrument_helpers.py`, the sample library is instrument-independent
(`tavi/sample_library.py` — samples move between instruments), the two §18.4
monitor-sizing bugs are fixed, and sample selection adopts the sample's own
lattice into the GUI. **Phase 4 IMPLEMENTED (2026-07-02, spec §20):** IN8 is
the second registered instrument — scattering senses threaded through the
angle solvers (vTAS-verified for IN8: +1/+1/−1), crystal/point-param dispatch
through the instrument state, `instruments/in8/plugin.py` +
`instruments/in8/model.py` built on the shared helpers,
branch-signed crystal bending, startup picker active, end-to-end McStas smoke
produces a real Bragg peak. 144 tests pass. `docs/INSTRUMENT_AUTHORING.md` is
the authoring guide; the IN8 modules are the living template. The a3
convention for the flipped sample sense is vTAS-verified too (Friedel/-Q
branch; §20.5).
**Unified packages IMPLEMENTED (2026-07-18):** runnable PUMA and IN8 code,
plain-language documentation, evidence status, scientist review, and immutable
references now live together under `instruments/<id>/`. PANDA and IN12,
research-only until 2026-09-09, are runnable too. Shared TAS state/snapshot/execution moved to
`instruments/tas_runtime.py`, and `python -m instruments.package_validation`
enforces the package contract. Sections below retain historical implementation
context; current paths and authoring policy are in `docs/INSTRUMENT_AUTHORING.md`.
**IN12 IMPLEMENTED (2026-09-09, record §21):** registered the same day
as PANDA; both put the monochromator on the negative branch
(`sense_mono = −1`). Built entirely from public documentation — its team never
sent files — but a literature round the same day resolved its scattering senses
to `(−1, +1, −1)` on three independent sources, so its kinematics are verified
(§21.2). What remains provisional is intensity and resolution: the incident
spectrum above all (§21.3).
**Author:** initial draft 2026-06-18; design decisions locked 2026-06-18; review
incorporated 2026-06-18; audit + implementation spec 2026-07-02; implemented
2026-07-02.
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
| `TAS_Instrument` base class (`instruments/tas_runtime.py`) | Generic TAS state + angle math (`calculate_angles`, `calculate_q_and_deltaE`, sample orientation, L1–L4, A1–A4) | Shared by every runnable TAS package. |
| `tavi/tas_geometry.py` | `solve_instrument_angles`, `q_instrument_from_angles`, Q↔angle conversions | General TAS geometry. Comments reference "PUMA convention" but the math is not PUMA-specific. |
| `tavi/sample_mount.py`, `tavi/ub_matrix.py`, `tavi/reciprocal_space.py`, `tavi/space_groups.py` | Sample/reciprocal-space/UB | Fully general; no instrument coupling. |
| `tavi/data_processing.py` | Detector file parsing, scan writing, plotting helpers | Reads `detector.dat`; assumes a single 1-D `Monitor` named `detector` (see §10.3). Otherwise general. |
| `tavi/runtime_tracker.py` | Runtime estimates | **Already keyed by `instrument_name`** (`record_run(..., instrument_name)`, `get_record_count(name)`). Just needs the controller to pass the real instrument name instead of the literal `"PUMA"`. |
| `tavi/mcstas_config.py` | McStas path + MPI launcher resolution | General. |
| `gui/main_window.py`, `gui/docks/base_dock.py` | Dock layout & persistence | General; layout persistence keys off stable `objectName()`s. New instrument-driven widgets must keep stable object names. |

### 2.2 Hard-coded to PUMA (the work surface)

**A. The instrument component tree — the core problem.**
`build_PUMA_instrument()` → `configure_component_tree()`
(`instruments/puma/model.py:859`–`1659`) is ~800 lines of
imperative McStasScript that bakes in *everything*:

- Fixed arm geometry: `L1=2.150, L2=2.290, L3=0.880, L4=0.750` and many literal
  `AT=[...]` offsets (collimator/slit/monitor positions in metres along each arm).
- Source: `Source_div_Maxwellian_v2`, with focus computed from monochromator size.
- Collimators: `Collimator_linear` instances gated on `alpha_1`, the `alpha_2`
  list (`30/40/60'` at hard-coded z-positions and apertures), `alpha_3`, `alpha_4`.
- Slits: `postmono_slit`, `sample_slit`, `detector_slit`, `exit_beam_tube`,
  `NMO_slit` — fixed positions and dimensions.
- NMO optics: two `FlatEllipse_finite_mirror_optimized` units with PUMA-specific
  geometry, m-value files, rotation logic (historical PUMA definition lines 1094–1267).
- Velocity selector: `V_selector` block gated on `V_selector_installed`.
- Monochromator & analyzer: `Monochromator_curved`, dimensions from
  `mono_ana_crystals_setup()`.
- Sample orientation arm hierarchy (`sample_gonio`/`sample_chi_arm`/
  `sample_cradle`/`sample_mount`) — this part is *generic TAS* and worth keeping.
- Sample component: a hard-coded `if sample_key == ...` ladder of 4 Al samples
  (historical PUMA definition lines 1400–1486).
- ~19 diagnostic monitors, each gated on a `diagnostic_settings` key, at fixed
  positions.
- The fixed McStas **parameter set** (`A1_param`, `A2_param`, … `dbl_hgap_param`,
  sample-orientation params) defined at `:878` and `:1324`.

**B. Crystal library.** `mono_ana_crystals_setup()`
(the historical PUMA definition at line 68) hard-codes only `PG[002]` (+ a "test"
variant) with inline dict literals. Duplicated again inside `validate_angles()`
(`:1687`).

**C. Instrument-specific physics constants.** `PUMA_Instrument.__init__`
(`:375`) sets arm lengths, slit gaps, NMO/selector flags, source type.
`calculate_crystal_bending()` (`:426`) encodes PUMA focusing formulas and minimum
radii (`rhm>=2.0`, `rvm>=0.5`, `rha>=2.0`, `rva=0.8` fixed) — historical Phase-0
state; the method no longer exists, replaced by the one shared producer,
`TAS_Instrument.ideal_curvature` (`instruments/tas_runtime.py`), driven by each
crystal's declared `CurvatureAxis` (`docs/INSTRUMENT_AUTHORING.md`).
`_get_v_selector_frequency`
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
        # the controller's hand-written _build_scan_puma_config). The complete
        # returned object graph is independently owned and deepcopy-safe: no
        # Qt objects, callbacks, generators, locks, open handles, or mutable
        # references into controller/session state.

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
The shared queue deep-copies the complete launch state once more before
registry insertion. A plugin that returns an object graph which cannot be
deep-copied therefore fails scan submission closed; live resources belong
behind plugin-owned identifiers or reconstruction logic, never inside the
scan configuration.

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
  "no sample" path. ~~**Owned per-instrument** as well; a shared sample library is an
  optional convenience the descriptor can draw from, not a global list.~~
  **Amended 2026-07-02 (Phase 3, §19):** samples are INSTRUMENT-INDEPENDENT —
  physical objects moved between instruments. The shared table lives in
  `tavi/sample_library.py` and every descriptor mounts it by default.
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

**Phase 1 — Registry + contract, PUMA as a plugin (routing only). ✅ IMPLEMENTED 2026-07-02.**
> **Fully specified in §17** (2026-07-02): file-by-file change list, controller
> edit groups, commit sequencing, and verification checklist. The bullets below
> remain the intent; §17 is the executable spec and supersedes them where they
> differ (notably: `new_state` split per §5, and the Phase-0 example descriptor
> must gain 8 missing sample-orientation/mount parameters).
> **Implementation verified** (§17.8): 54 pytest tests pass; the `.instr`
> generated through the full plugin path (`default_state` → `scan_config` →
> `build`) is byte-identical to the pre-change baseline modulo McStasScript's
> `* Date:` header stamp; the GUI launch matrix (no flag / `--instrument puma` /
> `--instrument nope`) behaves as specified; the real `config/runtimes.json`
> (63 "PUMA" records) migrates to `"puma"` on load.
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

**Phase 1.5 — Descriptor validator (review §16.2, do alongside Phase 1). ✅ IMPLEMENTED 2026-07-02.**
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

**Phase 2 — Structured descriptor + descriptor-driven GUI. ✅ IMPLEMENTED 2026-07-02 (spec + record: §18).**
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

- Component tree builder: `instruments/puma/model.py:859`–`1659`.
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
| senses sm/ss/sa | +1 / +1 / −1 (live vTAS run; the repository XML's −1/+1 for ss/sa is stale — §20.1) | implicit / fixed |
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
4. **Lazy-import blocker.** The former PUMA definition module imported
   `mcstasscript` at module level (`:3`). Therefore: registration stores only
   `(id, display_name, factory)`; `instruments/puma/plugin.py` keeps **all**
   references to the heavy module function-local; a subprocess-based test
   asserts listing pulls in neither `mcstasscript`, `PySide6`, nor
   `instruments.puma.model`.
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
   function-local `from instruments.puma.model import …` lines
   in the controller.

### 17.3 Pre-existing defects found (preserved verbatim in Phase 1)

Byte-identical rule: none of these are fixed in the routing pass; they are
recorded here so later phases pick them up deliberately.

1. `validate_angles` (historical PUMA definition line 1661) duplicates the
   crystal table with **divergent values** (mono slabwidth 0.018 vs 0.0202;
   analyzer ncolumns/nrows swapped: 5/21 vs 21/5). Fix belongs to Phase 2's
   single crystal source.
2. `TAVI_PySide6.py:2626` calls `set_misalignment(omega_m, chi_m, psi_m)` (3
   args) against a 2-parameter signature
   (`set_misalignment(mis_omega=None, mis_chi=None)`,
   historical PUMA definition line 186); the `TypeError` is caught at `:2635`,
   so misalignment-hash restore from `parameters.json` silently fails today.
3. `update_monocris_info`/`update_anacris_info` are each defined **twice** in
   the controller (`:577`/`:584` and `:1494`/`:1501`; the later definitions win
   at runtime). Route all four through `crystal_info`; do not dedupe.
4. Environment: at audit time (2026-07-02, morning) `run-tavi-dev.bat` targeted a
   nonexistent env. *Superseded during implementation:* the dev machine was
   rebuilt — the working micromamba env is now **`tavi-dev`** (Python 3.11,
   mcstasscript, PySide6; McStas resources at
   `%USERPROFILE%\AppData\Roaming\mamba\envs\tavi-dev\share\mcstas\resources`,
   which the launcher exports as `MCSTAS`), so the launcher is correct again.
   Verification uses `micromamba run -n tavi-dev …`. The launcher gained a `%*`
   passthrough so `run-tavi-dev.bat --instrument puma` works.

### 17.4 New files

| File | Purpose |
|---|---|
| `tavi/neutron_conversions.py` | K↔E/angle converters moved verbatim from the PUMA module (+ constants they use); PUMA re-exports |
| `instruments/puma/plugin.py` | `PUMAPlugin` (import-light; heavy imports function-local); `puma_descriptor()` moves here with the 8 added params; `scan_config` gets the verbatim `_build_scan_puma_config` body |
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
- **`instruments/puma/model.py`** (mechanical only): delete the
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
collimation, slits (**exceptions:** `SampleSpec.id`, `MonitorSpec.id`, and
`SourceType.id` keep legacy strings — non-empty + unique only); per-list id
uniqueness; parameter names unique and valid C identifiers; `primary_detector`
non-empty; v1 detector contract exactly `detector.dat`/`1d_monitor`; module
`CHOICE` default ∈ options / `TOGGLE` default is bool; collimation default ∈
allowed; L2/L3/L4 finite > 0 (`l1_source_mono` exempt — vTAS omits it);
axis limits `lower ≤ default ≤ upper`, finite; senses are `Sense` members.

*Amendments found during implementation (2026-07-02):* (a) `SourceType.id`
joined the legacy-string exceptions — PUMA's ids are the GUI combo strings
`"Maxwellian"`/`"Mono"`, wired 1:1 like sample keys; Phase 2 revisits. (b) a
`multi_select` collimation slot may default to `""` = nothing pre-selected
(PUMA's `alpha_2` checkboxes); single-select slots must default to an allowed
value.

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
  `mcstasscript`, `PySide6`, or `instruments.puma.model`.
- **Validator:** PUMA runnable-valid; IN8 example-valid / runnable-invalid
  (assert error substrings); parametrized negatives via `dataclasses.replace`;
  **source-scan:** regex `add_parameter\(\s*"(\w+)"` over the PUMA module ==
  the 25 descriptor parameter names.
- **Plugin:** `isinstance(PUMAPlugin(), InstrumentPlugin)`; id/display/mcstas
  name consistency; `default_state()` matches legacy defaults and returns fresh
  objects; `scan_config` applies the full GUI mapping (`alpha_2` list, base not
  mutated, hidden `mis_omega` propagates) and passes curvature through as
  magnitudes — `rva == 0.8` is PUMA's PG(002) declaring that axis fixed, and
  NMO ⇒ flat monochromator is `PUMA_Instrument.effective_curvature_axis`
  (folding the fitted NMO into rhm/rvm's resolved policy for every consumer:
  the applier, the scan-command validator, the ideal-radius producer, and
  (since the crystal-bending-generality branch) `GET /resolution`'s
  `compute_resolution`, which used to read a module-blind throwaway state);
  it is neither `scan_config`'s nor `optical_radii`'s to decide any more, and
  `build_PUMA_instrument`'s former `rhmfac`/`rvmfac` build-time zeroing —
  a second, independent copy of the same NMO-flat rule — is deleted: it was
  dead weight, never read by anything that reaches McStas (`rhm_param` comes
  straight from `PUMA.rhm`, already zeroed by `set_crystal_bending`);
  **snapshot `params.keys()` == descriptor parameter names**;
  `PUMARunExecutionState is RunExecutionState`; binary fallback ends with
  `PUMA_McScript.exe` and `SimpleNamespace(input_path=tmp, name="Foo")` →
  `Foo.exe`; `crystal_info` equals `mono_ana_crystals_setup`.
- **Controller source-scan:** no case-sensitive `"PUMA"`, no
  the heavy PUMA model module, and positive presence of
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

Verification checklist (env is `tavi-dev` — see §17.3.4):

1. `micromamba run -n tavi-dev python -m py_compile <all changed .py files>`.
2. `micromamba run -n tavi-dev python -m pip install -r requirements-dev.txt`
   (once), then `micromamba run -n tavi-dev python -m pytest tests -q` from the
   repo root.
3. `micromamba run -n tavi-dev python -m instruments._descriptor_examples` —
   PUMA runnable-valid; IN8 example-valid / runnable-invalid.
4. Launch matrix: no flag → no picker, identical startup; `--instrument puma` →
   identical; `--instrument nope` → stderr lists `puma`, exit 2, no window.
5. **Byte-identical scan check:** rerun the Step-0 scan;
   `PUMA_McScript.instr` must be byte-identical to the baseline (detector
   counts are Monte-Carlo stochastic and are *not* expected to match);
   `scan_parameters.txt` identical except timestamps/counts; "Direct run
   armed" still appears on point 2 (direct-invocation path intact).
6. `config/runtimes.json`: records under `"puma"` with legacy `"PUMA"` merged;
   pre-scan estimate non-empty (history survived the migration).

**Executed 2026-07-02.** All checks ran green, with two practical adaptations:

- The baseline/regression `.instr` was generated deterministically via
  `McStas_instr.write_full_instrument()` (a script driving
  `default_state → scan_config → build` through the registry) rather than a
  live GUI scan — that is the same file a scan's first point writes, without a
  McStas run. McStasScript stamps a `* Date:` line in the header, so
  "byte-identical" is asserted modulo that single line; everything else matched
  byte-for-byte both after the mechanical Steps 1–2 and after the full
  switch-over.
- Results: 54 pytest tests pass (42 new); descriptor examples validate as
  specified; launch matrix verified by starting the real GUI (process up, no
  traceback) for the no-flag and `--instrument puma` cases and exit-2 for
  `nope`; the real `runtimes.json` (63 `"PUMA"` records) migrates to `"puma"`
  on load. A live multi-point McStas scan (checklist item 5's "Direct run
  armed" console check and `scan_parameters.txt` diff) has not been re-run in
  this pass — recommended as a final manual smoke test.

---

## 18. Phase 2 Implementation Record — 2026-07-02

Phase 2 (descriptor-driven GUI + library single-source) implemented on branch
`instrument-selection`, five commits, app verified working after each. Guiding
decision from the maintainer mid-implementation: **forward-facing only** — PUMA
moves to the new formats with no migration of old data or control schemes.

### 18.1 What changed

1. **Descriptor completed (single source of truth).** 19 `MonitorSpec` entries
   (ids = the exact `diagnostic_settings` gate strings; placements computed
   numerically from PUMA geometry; `component_name` records the McStas instance
   name; `sample_region` tags drive the dialog quick-select). Sample specs
   corrected and completed (notably `Al_rod_phonon_optic` is
   `Optic_Phonon_simple`, T=300, with `zero_energy`/`maximum_energy`; every
   `properties` dict now lists all build() properties; `extend` recorded).
   `pg002_test` mono crystal added (d-spacing 2.355). Collimation slot defaults
   mirror the GUI reset values (α1 40, α2 {40}, α3/α4 30).
2. **Crystal single-source.** `mono_ana_crystals_setup` is a thin adapter over
   the descriptor `CrystalSpec`s (id-keyed; re-adds the embedded quotes on
   reflect/transmit that build() emits verbatim). Dead `validate_angles`
   deleted — only `archive/` referenced it, and its divergent duplicate crystal
   values were assigned-but-never-read, so removal is behaviorally inert.
3. **Typed snapshots (§16.6 resolved).** `PointSnapshot` dataclass +
   `PrepFailure` sentinel in `instruments/contract.py`; producer, run loop,
   `run_PUMA_point`, and tests all cut over in one commit. `PointSnapshot` is
   non-frozen with a pre-created `timing` dict because the prep thread stamps
   timings onto the queued instance after `put()` (shared-reference semantics).
   `metadata` stays a plain dict (it is `**`-spread into scan_parameters.txt).
4. **Descriptor-driven GUI.** `main()` → `TAVIMainWindow(descriptor)` →
   `InstrumentDock(self, descriptor)` / `UnifiedSampleDock(self, descriptor)`;
   population precedes `load_parameters()` (avoids the `setCurrentText` no-op
   trap). Module/collimation/slit rows are GENERATED from
   `ModuleSpec`/`CollimationSlot`/`SlitSpec` with deterministic objectNames
   (`module_<id>`, `collimation_<id>`, `slit_<id>_width/height`); accessor
   methods replace attribute access for generated widgets. Live-linked widgets
   (angles/energies/crystal combos/bending) keep attribute names + signal
   wiring; the NMO↔bending coupling guards on widget existence. Crystal/source
   combos carry ids as item data; ids travel through vals/state/persistence,
   labels are display-only. `get_gui_values()` exposes generic containers
   (`modules`, `collimation`, `slits_mm` — mm; the plugin converts to m);
   `PUMAPlugin.scan_config` owns the mapping onto its state fields.
5. **Persistence namespaced (§16.8 resolved).** `config/parameters.json` is
   `{"<instrument_id>": {"_schema": 1, ...}}`; save preserves other
   instruments' blocks and discards non-schema content; load reads only the
   active block with per-field defaults. **No legacy migration** (forward-facing
   decision): old flat files are ignored — defaults load, first save rewrites.
6. **ChangeImpact + fingerprint groundwork (§16-Q4 resolved: added in Phase 2).**
   `ChangeImpact` enum (BUILD/RUNTIME) on crystal/sample/source/collimation/
   slit/module specs (`ModuleSpec.requires_recompile` replaced);
   `PUMAPlugin.build_fingerprint(config)` hashes the build-time state. No
   consumer yet — see §18.5.
7. **Removed transitional/legacy code:** `PUMARunExecutionState` alias, crystal
   display-label lookups, `sample_label_var`, factor-based bending fallback
   (`rhmfac_var` era), duplicate shadowed `update_monocris_info`/
   `update_anacris_info` pair.

### 18.2 Deliberate behavior changes (everything else verified identical)

- Sample entry label "None" → "No sample" (descriptor display name); sample
  restore is by id.
- Velocity-selector checkbox label is now the `ModuleSpec.display_name`
  ("Velocity selector", was "Enable velocity selector (Use in Ki fixed mode)").
- Window title includes the instrument display name.
- Saved crystal/source values are ids; `parameters.json` is namespaced; old
  files load as defaults (no migration).
- `vals` reshape: `modules`/`collimation`/`slits_mm` containers (slits in mm).

### 18.3 Verified

`.instr` generated through the full path (registry → `default_state` →
`scan_config` → `build`) is byte-identical to the pre-Phase-2 baseline modulo
the `* Date:` stamp, checked after the crystal-adapter step and again after the
GUI/persistence steps. 65 pytest tests pass (incl. new anti-drift source-scans:
monitor ids == build() gates, sample ids == build() ladder, add_parameter ==
descriptor params; crystal-adapter golden-dict parity; persistence round-trips).
GUI launched and ran cleanly after the switch-over. Recommended manual check:
one short scan + a diagnostic-mode run with a few monitors enabled.

### 18.4 Known build() debts (deferred to Phase 3, recorded in the descriptor)

All three were paid in Phase 3 (§19):

- Two copy-paste sizing bugs in build(): the 'Postmono Emonitor' and
  'Post-analyzer EMonitor' blocks set the WRONG component's xwidth/yheight
  (premono/preanalyzer respectively). The `MonitorSpec.settings` record the
  INTENDED sizes; Phase 3's monitor loop fixes the emission. ✅
- build() still contains the literal monitor/collimator/sample blocks the
  descriptor now mirrors; anti-drift source-scan tests hold them together until
  Phase 3 makes build() loop over the descriptor tables. ✅
- `analyzer.r0` is set twice in build() (harmless duplicate assignment). ✅

### 18.5 Cross-scan binary reuse — IMPLEMENTED (2026-07-02)

Previously every scan's first point ran `backengine()` with
`force_compile=True` (fresh scan-local `RunExecutionState`), so every scan paid
a McStas compile even when nothing build-relevant changed.

**Implementation.** The controller keeps `self._binary_reuse_cache`
(`{fingerprint, instrument, execution_state, instr_path}`) across scans. At
scan start it computes `plugin.build_fingerprint(scan_config, diagnostic_mode,
effective_diagnostic_settings)` — the fingerprint now hashes the same
*effective* inputs `build()` receives (the diagnostic args were previously read
off the config, where they never live). Decision logic is in two Qt-free static
methods (`tests/test_binary_reuse.py`):

- `_can_reuse_binary`: reuse iff fingerprint matches, the cached state
  compiled successfully, the binary file still exists, and the scan is NOT
  diagnostic-mode (its first point needs backengine McStasData for plots).
- `_updated_binary_cache`: a scan that compiled replaces the cache (it owns
  the on-disk binary — builds share one `input_path/<name>.exe`); a reused or
  aborted-before-compile scan leaves the previous entry valid.

On reuse the scan skips `plugin.build()` entirely and its first point goes
straight to direct invocation. Since direct runs write no `.instr` into the
scan folder, the point-0 archive copy falls back to the compiling scan's
archived `.instr` (`instr_path`).

**Two pre-existing bugs found by the two-scan verification** (direct mode had
in fact never worked — all 2026-07-02 GUI scans logged 0 direct points):

1. `tavi/mcstas_config.py` read `MPIRUN` only from the top level of
   `mccode_config.json`; conda-packaged McStas 3.4.65 nests it under a section
   (`{"run": {"MPIRUN": "mpiexec"}}`) → launcher resolved to `[]` → every
   point fell back to mcrun/backengine. Now nested sections are searched and a
   bare launcher name is resolved against PATH.
2. `_run_puma_point_direct` pre-created the leaf output folder; McStas `--dir`
   aborts if it exists (`mcuse_dir`) → every direct run returned rc -1. Now
   only the parent folder is ensured.

**Verified headless** (plugin path, exact controller helpers): scan A =
[backengine 3.0s, direct 1.7s]; scan B (identical settings) = [direct 1.7s] —
no compile; changed collimation or diagnostic mode → no reuse. Note
`runtimes.json` records from reused scans have `compilation_time ≈ 0`, which
will drag the historical compile estimate down — acceptable, revisit if
pre-scan estimates matter.

## 19. Phase 3 Implementation Record (2026-07-02)

Phase 3 (§11 "build() cleanup + shared helpers") is implemented, plus the
user-directed scope addition: **samples are instrument-independent**. Eight
commits; 95 pytest tests.

### 19.1 What changed

- **`tavi/instrument_helpers.py` (new):** instrument-agnostic emitters —
  `emit_monitors`, `emit_sample`, `emit_sample_orientation_arms`,
  `emit_crystal_assembly`, `emit_slit`, `emit_collimator`, plus
  `_mcstas_number` (int-coerces integral floats so AT/ROTATED text matches
  legacy; McStasScript renders them with `str()`). No mcstasscript import; the
  `instrument` argument is duck-typed. Callers invoke emitters at the exact
  insertion points of their tree — component order is physics and stays in
  statement order.
- **`tavi/sample_library.py` (new):** `default_sample_library()` — the shared,
  instrument-independent sample table (samples move between instruments;
  supersedes §6's "owned per-instrument" disposition). Every descriptor mounts
  it (`samples=default_sample_library()`); an instrument may filter/extend.
  `SampleSpec` gains `component_name` (the `Al_bragg` spec keeps the legacy
  `"Al_Bragg"` McStas instance name) and `lattice` (a,b,c,α,β,γ).
- **`build_PUMA_instrument()` rewrite of the repetitive categories:** the 19
  monitor gate blocks became 10 `emit_monitors` call sites reading
  `_PUMA_MONITORS`; crystal-sized monitors get their extents from the SELECTED
  crystal via `size_overrides` (identical to the descriptor numerics for the
  current crystals — the build-tree test asserts that equality and will alarm
  if a crystal with different slab geometry lands). The alpha_2 collimators
  loop over a PUMA-local `_ALPHA2_COLLIMATORS` geometry table (build-only data;
  `CollimationSlot` stays GUI-facing). Slits/collimators/crystal assemblies/
  orientation arms go through the shared emitters. The sample ladder is a
  shared-library lookup + `emit_sample`. ~120 lines of commented-out
  exploration code deleted.
- **Lattice sync (user-locked):** selecting a sample adopts
  `SampleSpec.lattice` into the GUI lattice fields
  (`TAVIController._adopt_sample_lattice`) — driving Phonon_DFT (internal
  a=4.03893) with the default 4.05 lattice misses its Bragg condition entirely
  (found the hard way, 2026-07-02). `load_parameters` applies saved lattice
  values AFTER the sample restore so hand-edited lattices survive reload.

### 19.2 Deliberate behavior changes

- The two §18.4 monitor-sizing bugs are FIXED: `postmono_Emonitor` and
  `postanalyzer_Emonitor` now get their own mono/analyzer extents
  (0.2626×0.162 and 0.21×0.1475 for PG[002]); the latent NameError (post-
  monitor enabled while its pre- partner was off) is gone.
- Six monitors that legacy added without an explicit ROTATED now emit a
  cosmetic `ROTATED (0, 0, 0)` line in the diagnostic `.instr` (`source_PSD`,
  `source_DSD`, `postcollimation_PSD`, `postcollimation_DSD`,
  `premono_Emonitor`, `detector_PSD`) — physically zero rotation.
- Duplicate `analyzer.r0` assignment gone; `try/except` around the phonon
  samples' `append_EXTEND` dropped (never raised; silent-swallow anti-pattern).
- Non-diagnostic builds are byte-identical throughout.

### 19.3 Verified

Baselines B1 (defaults/no sample), B2a–d (one per sample), B3 (all three
alpha_2 collimators), B4 (diagnostic, all 19 monitors), B5 (NMO Both +
v-selector) captured via the full plugin path and re-compared after every
commit (modulo `* Date:`). B1/B2/B3/B5 byte-identical end-to-end; B4's diff is
exactly the enumerated §19.2 lines (two size fixes + six ROTATED cosmetics),
then frozen as the new diagnostic baseline. The two anti-drift source-scans
were replaced by object-level build-tree tests (`tests/test_puma_build_tree.py`
— construction only, no McStas compile/run): monitor presence/order/settings
against `_PUMA_MONITORS`, per-monitor gating, per-sample emission against the
library specs, alpha_2 collimator selection/order, table↔descriptor sync.

### 19.4 Follow-ups

- `SampleSpec.lattice` could also drive a space-group default per sample.
- IN8 (Phase 4) should build its backbone from `tavi/instrument_helpers.py`;
  anything it cannot express is the signal to extend the helpers.

---

## 20. Phase 4 implementation record (2026-07-02)

Six commits: PUMA sign goldens; sense threading; state dispatch; the IN8
modules; registration (+ vTAS-verified goldens + branch-signed bending); this
record + `docs/INSTRUMENT_AUTHORING.md`. Gates held throughout: full pytest
after every commit (95 → 143), PUMA `.instr` baselines B1–B5 byte-identical
after every PUMA-touching commit, and an end-to-end IN8 McStas compile+run
smoke before registration was declared done.

### 20.1 Scattering senses (§16.7 resolved)

- `Sense` semantics are now defined precisely: **the value IS the numeric sign
  of that axis' two-theta readout** (LEFT = +1 = McStas +y rotation; equals
  vTAS's sm/ss/sa convention). `stt_from_q_norm`/`solve_sample_angles`/
  `solve_instrument_angles` take `sense_sample` (default −1 = the historical
  baked branch, bit-for-bit identical); `TAS_Instrument` carries
  `sense_mono/sense_sample/sense_ana` and `calculate_angles` applies them.
  `calculate_q_and_deltaE` removes mono/analyzer readout senses before inverse
  Bragg conversion, so negative-sense inelastic round trips recover Q and ΔE.
- **PUMA's descriptor was self-inconsistent** — it declared
  `sense_sample=LEFT` while the code has always produced stt < 0. Corrected to
  `RIGHT`; TAVI's existing behavior is the contract (whether the physical PUMA
  hall matches is an open instrument-scientist question).
- **IN8's senses are (+1, +1, −1), verified against a live vTAS run
  (2026-07-02)**: all four reference cases (elastic/inelastic (2,0,0),
  skew-Q (1,1,0), Cu200 + ki-fixed) matched within 0.02°, with a4 positive and
  a6 negative. This OVERRIDES the vTAS repository XML (`ss="-1" sa="1"`) and
  the §14 table derived from it — the live readout wins. Locked as goldens in
  `tests/test_sign_conventions.py`.
- **Flipped-branch sample rotation follows the Friedel/vTAS convention**
  (second live vTAS check, same day): for `sense_sample=+1` the solvers align
  the Friedel partner −Q with the scattered-side Q_lab (implemented as
  solving for −q on the positive-stt branch, sth normalized to (−180, 180],
  saz flipping with −q). The user's live a3(V3) = 69.337 matches TAVI's sth
  to three decimals; their a3(V1) = 125.647 is TAVI's +35.647 plus exactly
  90.000 — vTAS displayed the cubic-equivalent (0,2,0) setting for that
  point. The raw inverse of a +1-branch solution recovers −Q;
  `calculate_q_and_deltaE` negates it back, so instrument-level round trips
  return +Q exactly. Same Bragg planes either way (verified in the McStas
  smoke: the −Q branch gives an equally real peak).

### 20.2 Shared-code generalization

`TAS_Instrument.calculate_angles`/`calculate_q_and_deltaE` resolve crystals
via `self.crystal_info()` (was: module-level `mono_ana_crystals_setup`, hard-
wired to `puma_descriptor()`); `compute_scan_snapshot` builds per-point params
via `state.build_point_params(deltaE)` and `state.point_energy_metadata(...)`.
`crystal_spec_to_info`/`find_crystal_spec`/`crystal_info_from_descriptor` are
public in `tavi/instrument_helpers.py`. `update_diagnostic_settings` and the
E0/energy-metadata logic moved onto the base class. `run_tas_point` aliases
the (already binary-name-agnostic) run layer. All value-identical for PUMA.

### 20.3 IN8 (`instruments/in8/plugin.py` + `instruments/in8/model.py`)

- **Data provenance:** arm lengths are ILL-current Thermes values
  (L1..L4 = 2.28/2.48/1.05/0.70 m) — a deliberate deviation from the vTAS
  values in §14 (2.5/1.35/0.65): distances never affect angles, and the
  simulation should match today's hardware. Axis limits from vTAS; crystal
  faces from the 2006/2023 papers + the ILL page.
- **Crystals v1:** mono PG002 (11×11 of 25×17 mm, mosaic 30′) + Cu200 (same
  face; no stock reflectivity data → constant r0=0.7 with the McStas `"NULL"`
  sentinel — validator-legal since reflect/transmit must be non-None strings,
  not real files); ana PG002 (~180×140 mm Thermes). Si111/Si311 bent-perfect
  faces deferred — not representable by the mosaic `Monochromator_curved`.
- **Build backbone** entirely from `tavi/instrument_helpers.py` (monitors,
  crystal assemblies, collimators, slits, sample + orientation arms). Literal
  remainder: source block, axis arms, PG filter, detector — exactly the §19.4
  prediction; **no helper extensions were needed**. The source block is the
  first helper candidate if a third instrument repeats it.
- **Branch-signed crystal bending (found in the smoke run):**
  `Monochromator_curved` needs the curvature center on the take-off side, so
  the bending radii carry the sign of the branch. IN8's
  `calculate_crystal_bending` (historical name; the one shared producer today
  is `TAS_Instrument.ideal_curvature`) returned signed radii (point-source
  formulas on BOTH sides — the virtual source is a real focal point, unlike
  PUMA's guide). The sign is no longer applied per plugin: `scan_config` passes
  magnitudes straight through, and `TAS_Instrument.set_crystal_bending` derives
  the branch from the **actual local take-off angle** at the point being
  measured — never from the declared scattering sense, because a direct-angle
  scan can legitimately put a crystal on the opposite branch (PANDA's declared
  A4 range spans both signs). Measured cost of the wrong sign: **~7 orders of
  magnitude** in elastic peak intensity. PUMA's take-offs are all on the
  positive branch, which is why a sign error there is invisible and why the
  tests that guard this use IN12 or PANDA.
- Minimal six-monitor diagnostic set; collimation slots α2/α3/α4
  (20/30/40/60′, default open); no modules (FlatCone/IMPS deferred, §14).
  PLACEHOLDER values (positions, apertures, Cu200 mosaic/r0, analyzer
  subdivision, hvs height, single vs double PG filter, no bending clamps) are
  marked in-line in both modules. The old `rva magnitude 0.31` placeholder is
  gone: IN8's Thermes analyser is variable double-focusing and the hardware
  tracks it, so `rva` is declared driven and follows kf. The full inventory
  of missing/placeholder data, with provenance and a priority order for the
  next data pass, is `instruments/in8/MODEL_STATUS.md`.

### 20.4 Verified

- 143 pytest tests; PUMA baselines B1–B5 byte-identical end-to-end (sense
  threading and dispatch are runtime-value changes only).
- vTAS live cross-check of the four IN8 angle cases (magnitudes ±0.02°, signs
  exact) — recorded in `tests/test_sign_conventions.py`.
- End-to-end smoke: IN8 built through the plugin, compiled, and ran one
  elastic Al (2,0,0) point at kf=2.662 with the Phonon_DFT sample —
  I = 0.043 ± 0.030 at 1e7 neutrons (same rare-giant-weight-event character
  as PUMA's Bragg peak). Unsigned bending gives 2e-8; PUMA-sense angles on the
  same tree give 1.2e-7 — the A/B that isolated the bending sign.
- GUI matrix: `--instrument in8`, `--instrument puma`, and no flag (picker)
  all launch clean; startup runnable-validation now gates both descriptors.

### 20.5 Accepted couplings and follow-ups

- **Resolved 2026-07-18:** IN8 and PUMA import
  `compute_scan_snapshot`/`run_tas_point`/`TAS_Instrument` from the neutral
  `instruments/tas_runtime.py`; neither model owns another instrument's runtime.
- **Resolved (crystal-bending-generality branch):** `TAVIController._compute_ideal_bending_values`
  used to reuse PUMA's parallel-beam mono formula and unsigned magnitudes for
  the advisory "Ideal:" labels regardless of the selected instrument. It is
  now a thin caller of the one shared producer, `TAS_Instrument.ideal_curvature`,
  passed the GUI's actual crystal selection, and returns absolute magnitudes
  (`docs/INSTRUMENT_AUTHORING.md`).
- **a3 convention: RESOLVED** (user's second live vTAS run). The raw readings
  a3(V1)=125.647 / a3(V3)=69.337 initially suggested a −56.31° difference
  (mirror of the baked branch), but decode exactly as TAVI's Friedel-branch
  values +35.647/+69.337 with vTAS showing the cubic-equivalent +90° setting
  for V1 — in one symmetry setting the difference is +33.69°, as computed.
  The solvers now implement this convention for `sense_sample=+1` (§20.1);
  goldens updated. When comparing a3 against vTAS on cubic samples, expect
  ±90° symmetry-setting jumps between points.
- Si bent-perfect crystals, FlatCone/IMPS, and the §20.3 placeholders await
  instrument-scientist input.

## 21. IN12 implementation record (2026-09-09)

IN12 (ILL, cold TAS on guide H144) is the third registered instrument. It is
the first one built with **no instrument-scientist input at all** — the team
never sent files — so the record below is as much about what the model does
*not* know as about what it does.

Evidence: a 2026-07-18 research dossier assembled from the 2016 Schmalzl
upgrade paper, the current ILL pages, the historical `ILL_H142_IN12` McStas
example, a 2001 IN12 raw scan header and the 2010 vTAS instrument repository;
plus a 2026-09-09 re-check of the live ILL pages before registration. Both are
immutable snapshots under `instruments/in12/references/`. The re-check
contradicted nothing.

### 21.1 The first negative-branch monochromator

IN12 is the first TAVI instrument with `sense_mono = −1`. ILL publishes its
monochromator two-theta travel as **−140°…−10°** — entirely negative — because
the 2012 upgrade moved the new 11 × 11 PG(002) assembly onto the clockwise
branch. The sense threading from §20.1 already supported this; IN12 is the
first exerciser of it, forward and inverse (`calculate_q_and_deltaE` divides
the mono readout by `sense_mono` before the inverse Bragg conversion — a path
no previous instrument reached with a negative sense).

Consequently **all three driven curvature radii are negative** in
`IN12Plugin.scan_config`: the mono takes off negative *and* so does the
analyser. §20's branch-sign rule generalises without change.

### 21.2 Senses — resolved, and the model was right

`(−1, +1, −1)` — the **W configuration**, monochromator and analyser on the
clockwise branch, sample counter-clockwise. Confirmed 2026-09-09 by a
literature round (`instruments/in12/references/2026-09-09__in12-literature-round__v02.md`)
after the model had already been built on it as a provisional assignment. Three
independent lines agree:

1. ILL publishes the monochromator two-theta travel as −140°…−10°, entirely
   negative. Strong, but not proof alone: a motor coordinate and the logical
   sense metadata need not share a sign, since software may apply offsets or
   inversions.
2. ILL's own public **Takin** resolution preset
   (`data/instruments/in12_pg002_pg002.taz`) stores `mono_scatter_sense = 0`,
   `sample_scatter_sense = 1`, `ana_scatter_sense = 0` — mono and analyser
   together, sample opposite.
3. H. Trepka's 2022 Stuttgart dissertation reports a post-upgrade IN12
   configuration explicitly as `SM = −1, SS = +1, SA = −1`.

The one apparently contradictory source is not: Brüning's IN12 RESCAL table
gives `+1, −1, +1`, but legacy ResCal defines +1 = right, the reverse of the
SICS/raw-file convention. Normalised, it is the same geometry — a reminder that
a sense triple is meaningless without naming its convention.

The goldens in `tests/test_sign_conventions.py` remain self-generated (nobody
ran the instrument for us), but they now freeze a verified geometry rather than
a hypothesis. `test_in12_plugin.py` additionally asserts the *structural* half —
mono and analyser on the same branch, sample opposite — so a partial regression
cannot hide behind the triple.

### 21.3 Model boundary and what was deliberately left out

- **Source** = an effective 20 × 140 mm aperture at the H144 guide exit, 1.8 m
  from the monochromator. The exit *is* the instrument's virtual source (2016);
  the ~115 m of guide above it is not modeled, and with it the velocity
  selector (>36 m upstream) and the transmission polarising cavity (~35 m).
  A bare source at 115 m without the guide would not reproduce the incident
  phase space, so the compact interpretation is the only honest one available.
- **No velocity selector, no Be filter.** Both are higher-order suppressors.
  The source emits a narrow band around E0, so there are no higher orders to
  remove and either component would only attenuate. McCode's `Be.trm` — a
  transmission curve measured *on IN12* at 80 K — is available the day a
  broadband source model lands.
- **No IN12-UFO** — but it was built, which the first pass got wrong. The 2016
  CRG annual report describes commissioning the fifteen-channel
  multi-analyser/multi-detector, with neutron tests performed and
  mechanical-stability and background problems corrected; a 2018 JCNS
  contribution calls it "currently in a commissioning phase"; and a 2023 ECNS
  instrument-status contribution describes it in the present tense as
  interchangeable with the standard secondary spectrometer. What could not be
  found is any peer-reviewed paper stating its data were taken with UFO, or
  evidence of routine user operation — so ILL's surviving "will be equipped
  with" web wording is stale rather than accurate. Excluding it is still right:
  multi-analyser secondaries are out of scope for v1 (§14), the same call made
  for IN8's FlatCone/IMPS, and it belongs in a separate descriptor if ever
  modeled. It should simply not be described as never built.
- **No polarisation.** The Heusler(111) analyser IS offered, because its
  d-spacing (3.44 Å) genuinely moves A4; everything else about polarised
  operation is outside TAVI's model.
- **L3 modeled at 1.30 m**, which is one setting of a genuinely variable arm,
  not the arm length: ILL says "a variable sample-to-analyser distance of about
  1.3 m" and ILL's own Takin preset uses 1.46 m. The travel limits are
  unpublished; with them L3 could become a descriptor-level choice.

### 21.4 Derived, not measured — and one correction

No source publishes IN12's **monochromator** crystal dimensions. The descriptor
divides the published 200 × 160 mm face by eleven and removes a nominal 1.5 mm
gap. The tests assert the *face* those slabs reconstruct, not the slab sizes,
so the derivation stays visible as a derivation.

The **analyser** was initially modeled as 11 × 1 and vertically flat, inherited
from the historical `ILL_H142_IN12` McStas wrapper (`NHA = 11`, `NVA = 1`) on
the argument that the 2012 upgrade left the secondary spectrometer alone. That
argument was right and the conclusion was wrong. W. Schmidt and B. Fåk, "New
focusing analyser on IN12", **ILL Annual Report 1998**, describes the assembly
as built: eleven vertical lamellae of **11 mm** width, motorised variable
*horizontal* focusing, and a **fixed vertical focus produced by tilting the top
and bottom crystal rows** (its Fig. 1 says the tilt is visible), mosaic ~0.5°.

Tilting a top and bottom row requires at least three rows, so the analyser is
now **11 × 3**. Its geometry is also derived the other way round from the
monochromator's: the 11 mm lamella width is published, eleven of them span 121
of the 122 mm active face, so the crystals are effectively butted and the
**gap** (0.1 mm) is the derived quantity. That is the right direction whenever
a real dimension exists.

The fixed vertical radius is **1.40 m**, from ILL's public Takin preset
(`pop_ana_curvv = 140`, `pop_ana_use_curvv = 1`) — a resolution parameter, not
a mechanical drawing. It is deliberately far from the point-source Rowland
radius for L3/L4 (~0.43 m at a typical take-off), which is exactly what a
*fixed* focus looks like: right at one setting only. A test asserts it is not
tracking the arms, so a later "improvement" cannot quietly turn it into a
computed radius.

Published mechanical bending limits (horizontal ≥ 1.7 m, vertical ≥ 0.5 m) are
declared as `min_radius_m` on the mono's `CurvatureAxis` entries and clamped by
`TAS_Instrument.ideal_curvature`. With L1 = L2 = 1.8 m the horizontal
limit never binds; the vertical one does, above about |A1| = 32°. Neither limit
could be re-confirmed in the literature round — ILL says only that both axes
are variable.

### 21.5 Verification

- Descriptor runnable-valid; `python -m instruments.package_validation` clean.
- Full suite green: 683 passed / 47 skipped under Python 3.12 (no
  mcstasscript), and every mcstasscript-gated instrument test passed under the
  `tavi-dev` environment.
- **McStas compile + run smoke**, elastic Al (2,0,0) at ki = kf = 2.0 Å⁻¹, the
  descriptor's default axes (A1 −55.834, A2 +101.737, A4 −55.834), 1e7
  neutrons: `detector_I = 7.47e-07 ± 1.73e-08`, N = 10055 detector events.
- The **wrong-branch A/B** — the identical tree with all three radii
  sign-flipped — gives `5.32e-08 ± 4.34e-09`, N = 498: a factor ~10 in
  intensity and ~16 in statistics. Smaller than IN8's ~1e7 collapse, as
  expected: IN12's mono is only weakly focused (RH = 3.84 m across a 20 cm
  face) where IN8's analyser is strongly bent, so there is less focusing to
  lose. The sign is confirmed by an order of magnitude, which is the point of
  the run.
- The **analyser correction A/B**: the same point through the original 11 × 1
  vertically-flat analyser gave `5.19e-07 ± 1.36e-08`, N = 7785. Restoring the
  real fixed vertical focus is worth **+44 % in intensity** and +29 % in
  events — the right direction, and a useful independent check that the 1998
  description was read correctly rather than merely differently.

### 21.6 Follow-ups

- The senses are settled (§21.2), so **everything** left in
  `instruments/in12/MODEL_STATUS.md` is intensity or resolution. The largest
  single item is the incident spectrum: 2016 says the guide was calculated in
  McStas and the primary spectrometer in SIMRES, but neither model is public
  and no MCPL file or exit phase space exists in the public record.
- Two claims in the first pass were **wrong and are corrected here**: the
  analyser topology (§21.4) and IN12-UFO's status (§21.3). A third suggested
  correction — that the McStas transmission table measured on IN12 is
  `BeO.trm` rather than `Be.trm` — was checked against the installed McStas 3.x
  resources and **rejected**: the shipped file is `data/Be.trm`, header "Be
  transmission, as measured on IN12. T=80 K … B. Fåk (CEA/ILL)", and no
  `BeO.trm` exists in that tree.
- The **velocity-selector detail** in the 2026-07-18 dossier (60 blades, 23.9°
  helix, 25 % resolution, 83 % transmission at 4 Å) could not be confirmed for
  the IN12 unit; published Astrium figures at that level of detail belong to
  different 72-blade devices. Treat it as unsourced. Nothing in the model
  depends on it, since the selector is outside the model boundary.
- `tests/test_instrument_registry.py` now imports `instruments.builtin` at
  module scope: its snapshot/restore fixture used to snapshot an *empty*
  registry and wipe the built-in registrations for every later test file in the
  same process. Latent since Phase 4; surfaced by running the registry file
  before `test_instrument_packages.py`.
- The two research dossiers (IN12, PANDA) were renamed to the
  `YYYY-MM-DD__source-id__vNN.ext` reference convention; they had been failing
  `package_validation` on `main`.

---

## 22. Crystal curvature: design record (landed 2026-09-11, PR #32)

Moved here at closeout from the retired `docs/HANDOFF-crystal-bending.md`
and `docs/PLAN-crystal-bending-landing.md`; the branch
`crystal-bending-generality` merged as `38aa33fa`. The client contract is
`docs/API_USER_GUIDE.md`, "Crystal curvature". Open follow-ups are TODO.md
rows that point at §22.10.

### 22.1 What landed

A monochromator or analyser crystal has up to four curvature axes (`rhm`/`rvm`
on the monochromator, `rha`/`rva` on the analyser). Before PR #32 the radii
that actually reached the simulation came from **two hard-coded copies of PUMA's
parallel-beam focusing formula**, plus PUMA's minimum-radius clamps, in the GUI
controller and the widget-free API equivalent. Each instrument's own focusing
method had **zero production callers**. The fourth axis, `rva`, had no widget and
no key in the values dict, so three call sites read PUMA's fixed 0.8 m as a
universal default.

Now: a crystal assembly declares what each axis can do; one producer
(`TAS_Instrument.ideal_curvature`) computes an ideal radius from the
instrument's own optics; one applier (`set_crystal_bending`) enforces policy and
signs; a per-axis mode (AUTOFOCUS / HELD / SCANNED) travels in launch state and
is honoured per point; an explicitly commanded out-of-travel radius is refused at
submission rather than clamped; the analytic resolution model receives `rva`; and
each scan result records the curvature each point actually ran with.

### 22.2 The one thing to know before touching this area

**The recurring defect is a rule implemented in one path and not its twin.** It
was found **twelve times** through the two external reviews, at nearly every
layer the consolidation touches: the producer, the applier, the GUI, the API,
the resolution model, the scan validator, the persistence layer, and once
inside a *test fixture* — a stub controller whose `normalize_scan_variable`
and variable-index map had silently diverged from the real controller's,
which made a green suite mean less than it appeared to.

**Corrected: the count is now twenty-five, not twelve.** A landing session
found thirteen more (`D13`-`D25`, §22.9)
asking the identical question of the same code, in three further layers the
original twelve had not yet shown: a *test itself* asserting the wrong
behaviour, not merely a fixture silently diverging from production
(`D22` pinned the GUI preflight's blindness to a relative out-of-travel
command as if it were correct); a partial twin inside one overlay function
rather than across two functions (`D23` — the resolution-model overlay copied
a point's radii but not its own Ei/Ki/Ef/Kf, so the two halves of "this
point's state" disagreed with each other inside the same call); and a check
that exists and is correct but that production never actually reaches with
the input that matters (`D14` — `validate_scan_launch_state`'s
`_curvature_violation` was "authoritative" only for callers that force
`relative=False`, so a relative GUI scan never reached it in practice). This
was not a coincidence the first twelve times and is not one now: it is the
shape of the original defect (one formula in two copies) reproducing itself
wherever the consolidation lands, including into weaker forms once the
literal duplicate-code instances had been swept up. **Assume a
twenty-sixth exists.** Two review passes returned clean on code where an
external reader then found three, and a landing session found thirteen more
after that.

Practical consequence: when you fix something here, ask what its twin is before
you write the fix, and prefer deleting a copy to adding a rule.

### 22.3 Two contracts that are deliberately different

Getting these backwards is how the worst bug on this branch happened.

- **Operator / API / descriptor values are MAGNITUDES.** How tightly the crystal
  is bent is what a person types and an API client sends.
- **Emitted McStas geometry and `ScanResult.applied_curvature` are SIGNED.**
  Which side it bends toward is instrument geometry, derived at the physical
  boundary from the *actual local take-off angle* — never from the declared
  scattering sense, because a direct-angle scan can legitimately put a crystal on
  the opposite branch (PANDA's declared A4 range spans both signs) where the
  wrong sign costs ~7 orders of magnitude.

`tavi/resolution.py` applies the scattering sense *itself*
(`monorh = radius_cm(cfg.rhm) * sm`), so a signed radius reaching it is signed
twice. That was live for three commits and cost ~1.6% on energy resolution and
roughly a factor of two on both momentum components, while the emitted McStas
geometry stayed correct — so nothing visible broke and no test caught it.

### 22.4 Settled rulings — do not re-open

- Curvature policy belongs on `CrystalSpec`: here a "crystal" is the crystal
  **plus its mount**, as an installed package. Two reviews raised a mount/assembly
  objection; the operator closed it on that ground.
- **Autofocus tracks during the measurement.** Operator ruling: scanning drives
  an axis point by point, setting holds it, autofocus follows. That it had not
  been doing so was a failure, not a design choice.
- IN8's `rva` is **driven** — its Thermes analyser is variable double-focusing and
  the hardware tracks it.
- **Zero means flat**, always legal, never clamped up to a minimum. An unbent
  crystal is real hardware; a minimum radius bounds how tightly a bender may
  bend, not whether it may be straight.
- IN8 and PANDA declare **no** mechanical travel and therefore refuse nothing.
  Theirs are genuinely unknown — PANDA's confirmed absent from the literature —
  and inventing limits would be the defect.
- PUMA's bending limits and its fixed 0.8 m analyser radius were **reviewed
  against internal instrument documentation and confirmed with the instrument
  scientist** (operator, 2026-09-11). Not independently citable, not a guarantee,
  and explicitly **not** covering PUMA's arm lengths, which stay provisional.
- `curvature_modes` is **read-only** on the API. Modes derive from the Ideal locks
  and from which axes a scan command names; a second way to set them would be
  another twin.

### 22.5 Review history, and what each round found

The branch went through two external pre-PR reviews, plus a per-slice review on
every commit and one whole-branch pass. That history is the most useful thing
here, because of *what* the later rounds found.

**First external review** — would not merge. Four functional findings, three of
which were one defect at three call sites: the deterministic engine, the
`GET /resolution` backend, and the McStas background sigma widths all still
built the analytic resolution from the frozen launch values after curvature had
become per-point. Plus relative scans evading the out-of-travel refusal.

**Second external review** — would still not merge. Four more, three again the
same class: PUMA's nested-mirror-optic rule living in two places with a SCANNED
axis escaping both; `focusing_known=False` being per-axis in the schema but
whole-crystal in the producer; and the resolution model rebuilding branch signs
from the static descriptor while the applier used the point's own angle. Plus a
regression the *previous* round's fix had introduced — the false-accept repair
had created its mirror-image false-reject.

All eight are fixed (as are `D13`-`D25`, found afterward — see the corrected
`State:` line above). **Both external readers found defects that a per-slice
review and a whole-branch review had passed clean on the same code.** That is
the single most transferable fact in this document: in this area, one tool's
silence is not evidence. The landing session's own thirteen are the same
lesson from a different angle: they were found by *rereading the existing
code against the plan's defect-hunting question*, not by a new tool — nothing
about the review machinery changed, only the willingness to keep asking.

### 22.6 Compiled McStas smoke runs

Step 8 of `docs/INSTRUMENT_AUTHORING.md`, production path, Al (2,0,0) elastic,
1e7 neutrons, collimators open, ideal focusing. **Call
`install_no_window_guard()` from any script outside pytest** or every instrument
construction opens a console window on the operator's screen — this has buried
his desktop before. Results on the branch, 2026-09-11, each verified against the
detector files:

| | before | after |
|---|---|---|
| PUMA | none | 2.09475e-07 / 4973 (first baseline) |
| IN8 | 3.33e-07 / 4908 | 5.07902e-07 / 11455 |
| IN12 | 4.21e-07 / 4334 | 5.44329e-07 / 6901 |
| PANDA | 7.99e-08 / 1462 | 2.07537e-07 / 7663 |

**Corrected (H1):** "every instrument gained flux" overstates PUMA, which has
no *before* number in the table above — the parallel-beam assumption this
branch replaces was PUMA's own pre-existing formula, so there is nothing on
PUMA to compare "after" against; its row is a first baseline, not a measured
gain. IN8, IN12, and PANDA each have a real before/after pair, and all three
gained flux there, far outside Monte-Carlo scatter, in the direction expected
once the monochromator images the real virtual source at L1 instead of
assuming a beam from infinity. Each takes ~3 s on this machine with 30 MPI
processes.

Repeated at `534c2140` (final code commit) before the PR: PUMA 2.85757e-07 /
4791, IN8 5.71118e-07 / 10782, IN12 4.60709e-07 / 7152, PANDA 2.46073e-07 /
7883 — every ratio within 1.4x of the table above, ordinary Monte-Carlo
scatter, signs on every axis as §22.3 predicts.

### 22.7 Downstream

PR #32 changes numbers the sibling campaign repo (ISAR) consumes, three
ways: emitted curvature on IN8/IN12/PANDA; the analytic resolution for every
instrument once `rva` reaches it; and the sign correction on negative-branch
instruments. A campaign run against PR #32 or later will **not** reproduce one run
against `main`. That is intended, not drift. The reader confirmed no API *shape*
break — ISAR's client is a permissive JSON wrapper and its parser ignores unknown
members.

### 22.8 Deferred on purpose

- A non-numeric radius typed into a GUI field blocks the run but tells the
  operator nothing — the run quietly does nothing. Pre-existing, unrelated to
  curvature.
- IN12's provisional 1.7 / 0.5 m monochromator minima, and PANDA's and IN12's
  analyser vertical *radius*, remain unsourced and still need an instrument
  scientist. Recorded as such, not closed.
- No angle-dependent bender travel. `curvature_limits` is the seam; nothing needs
  it yet.

### 22.9 Defect ledger D13-D28 (landing session 09bdc537)
D13 API refuses an IN12 Heusler request that names rva (no requested_axes
    in build_api_launch_state / _default_parameter_values). GUI accepts.
D14 A RELATIVE curvature scan on the GUI Run path is never travel-checked:
    validate_scan_command skips relative commands and points at
    validate_scan_launch_state, which only the API backend and the
    benchmark stage call, both with relative flags forced False. Per point,
    set_crystal_bending clamps silently; curvature_clamped records AUTOFOCUS
    axes only. PUMA, rhm 2.5, Relative-1, "rhm -1.9 -1.5 0.1" runs at a
    constant 2.0 m while the record says 0.6-1.0.
D20 run_simulation's lone-command-2 swap moves the text but not
    relative_mode_1/2 (TAVI_PySide6.py ~8016); validate_scan_launch_state
    swaps both. Command 2 "rhm 0.5 1.0 0.5" with Relative-2 at rhm 2.5 is
    validated as 3.0-3.5 m and executed as 0.5-1.0 m absolute, clamped.
D21 HELD refusal runs before an axis named by the scan command is promoted
    to SCANNED, GUI (_held_curvature_issues, ~6466) and API (~2756) alike:
    unlocked rhm field 1.0 plus a legal absolute "rhm 3.0 4.0 0.5" is refused
    for a value the scan never uses.
D15 GET /resolution's throwaway check_state never receives module state:
    PUMA with NMO fitted returns a bent-mono resolution while the scan emits
    rhm=rvm=0.
D16 update_ideal_bending_buttons syncs a fixed axis's field only for rva;
    PUMA+NMO with locks off hard-blocks Run on stale non-zero rhm/rvm fields
    with no GUI cue.
D17 (P3) curvature_limits reads raw CrystalSpec.curvature, bypassing
    effective_curvature_axis, against that method's own docstring.
D18 (P3) build_PUMA_instrument keeps rhmfac = rvmfac = 0 as a copy of the
    NMO-flat rule; CONFIGURABLE_INSTRUMENTS.md claims full folding.
D19 (P3/P4) test stubs: test_api_over_limit_latch _StubController lacks
    relative_1/2; test_curvature_relative_scan_travel stub's current-value
    getter is not name-canonicalising.
D22 (P3) tests/test_curvature_relative_preflight.py pins the GUI preflight's
    blindness as intended behaviour (asserts hard == [] for the relative
    out-of-travel command).
D23 (P1, operator's Pro review, verified by reading) Direct-angle scans:
    the three analytic-resolution consumers overlay only the point's RADII
    onto the frozen launch vals (`_vals_with_point_curvature`), while
    resolution_adapter._kfix prefers vals['Ki']/vals['Kf'], the launch
    values. The snapshot metadata already carries the point's own
    Ei/Ki/Ef/Kf (tas_runtime ~641). An A4 scan under Kf-fixed feeds Popovici
    a per-point energy transfer against the launch Kf; the reviewer's PANDA
    A4=+50 example yields a negative implied incident energy.
D24 (P3) test_deterministic_engine_leaves_skipped_point_as_none never
    requires a skipped point; it passes with every entry a full dict.
D25 (P3) applied_curvature recording on the McStas job-result path is
    "verified by reading", not by a test.
H1  Handoff overstatement: "every instrument gained flux" is unsupported for
    PUMA, which has no before value; it is a first baseline.
G1  applied_curvature and curvature_modes appear in no client-facing doc.

### 22.10 Landing commits and pinned follow-ups

Landed on the branch, in order: eaafbcde plan; de8ec5d7 + 0290eda5 L1 (D13);
714e77a5 L2a (D14, D22); a2779021 (D20); 5da82e85 (D21); aaa25d8b L2c (D23);
ebf0368b L3 (D15); acb4ceb9 L4 (D16); 8c242a9e L5 (D17, D18, D19, D24, D25);
534c2140 per-slice review fix (rva lookup with live modules); 73ab6c9f L6 (G1,
H1). M1 landed on main as c868f080. Every code commit shown red first; suite
1102 passed serial after 534c2140; four compiled smoke runs repeated at
534c2140 within Monte-Carlo scatter of the handoff's table (PUMA 2.86e-07/4791,
IN8 5.71e-07/10782, IN12 4.61e-07/7152, PANDA 2.46e-07/7883).

Pre-PR seats (reviewer role, external reader, review_files per slice) found
and this session fixed:
D26 (P1) the travel helper ran before the zero-step and step-sign guards, so
    `rhm 2 4 0` typed mid-keystroke raised ZeroDivisionError in a Qt slot and
    the same body on the API was a 500. Guards now run first.
D27 (P2) update_ideal_bending_buttons returned early when no ideal could be
    computed (degenerate take-off angle), skipping the fixed-axis field sync;
    one `_sync_curvature_fields` loop now runs in both branches.
D28 (P3) a test asserting absolute semantics under a docstring claiming the
    validator cannot expand a relative command (deleted); stale module
    docstring in test_curvature_relative_scan_travel.py, puma/model.py's
    effective_curvature_axis and descriptor.py's fixed_curvature corrected.

Deferred, pinned (TODO.md at merge):
- A zero-step or wrong-sign step returns (var, message) from the validator
  and `_scan_command_issues` files it as neither hard nor soft (only "⚠"
  messages are soft), so the Run gate does not block it; the dock's live
  annotation shows it. Pre-existing, not curvature-specific.
- `curvature_modes` in GET /state and result.metadata reports the launch
  policy (autofocus/held) for an axis the scan command names; only the
  per-point snapshot says "scanned". applied_curvature carries the truth.
- PATCH /parameters on a module-fixed axis (PUMA rhm with NMO) returns
  applied: the requested value while the field syncs to the resolved 0.
- The Ideal label block indexes ideal['rhm'/'rvm'/'rha'] unconditionally;
  a future driven mono/rha axis with focusing_known=False would KeyError.
- test_api_over_limit_latch's _ManifestController still re-implements
  normalize_scan_variable as identity.
- IN12 `ana_vertical_is_fixed()` reads raw fixed_curvature; zero callers.
- The "40-field" parameter-table count is stale (43) in four documents.
- curvature_limits' docstring points at an angle-dependent extension that
  effective_curvature_axis cannot serve without the angle; the seam stays
  as recorded under "angle-dependent bender travel".
