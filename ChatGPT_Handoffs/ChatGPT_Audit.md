## Audit result

**I would keep both pushes open for a focused closeout.** The core UB and angle mathematics held up well under independent checks, and real McStas runs supported the nominal and tilted scattering paths. There are still several concrete defects and integration gaps that prevent calling the work completely landed.

I identified **nine substantive findings**:

- Three functional or verification gaps introduced during these changes.
- Four inherited functional defects that still affect the new workflows.
- An unfinished downstream migration.
- A documented analytic-engine approximation that becomes more consequential with general UB mounts.

There are also smaller layout and test-maintenance issues. I kept those separate from the functional findings.

The audit is pinned to TAVI commit `97a295b3d6167843b0f4259aa79b284dc55a3857`, with comparisons against the pre-UB and pre-angle implementations. Production files remain unchanged.

### Deliverables

The 15-page report contains the full analysis, pinned source links, historical attribution, and acceptance criteria for each finding.

The evidence archive contains the reproducers, numerical results, test records, GUI screenshots, emitted instrument models, and McStas controls. The experimental results below are preserved there.

TAVI_Audit_Evidence\_[2026-10-12.zip](http://2026-10-12.zip)

## What has actually landed


| Area                                           | Status                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------- |
| UB work, PRs #48–#50                           | Present on audited TAVI main and in published v1.3.2                                        |
| A1–A6 work, U1–U4 / PRs #55–#58                | Present on audited main                                                                     |
| Published release containing the angle work    | The inspected latest release, v1.3.2 from October 7, predates the October 9–10 angle merges |
| ISAR’s UB geometry synchronization             | Landed through ISAR PR #40 on October 1                                                     |
| ISAR’s new angle/API/output-contract migration | Still absent from inspected ISAR main                                                       |
| TAS\_MCP migration                             | Unverified; its source was not accessible here                                              |


There is a useful correction to the existing work record: **ISAR’s UB geometry was synchronized.** The statement in TAVI’s WIP file that this copy had not been updated is stale. The outstanding ISAR work is the subsequent angle and public-contract migration. The U5 handoff already describes that remaining work. [Release](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/releases/tag/v1.3.2) · [ISAR UB synchronization](https://github.com/ammerritt-gh/ISAR/pull/40) · [U5 handoff](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/docs/HANDOFF-scan-command-consumers.md)

## Findings to address

### F1. Parameter updates can report success while silently overwriting explicit requested values

**Inherited defect; high closeout priority.**

The API’s parameter-update path declares a sensible dependency order—lattice, energy, Q/HKL, then angles—but implements it by writing **all requested values first**, followed by **all dependency callbacks**. An earlier callback can therefore overwrite a later explicit input. The response still reports the originally requested value as applied.

Using the actual IN8 controller:


| Requested update                 | Reported outcome        | Actual public state afterward  |
| -------------------------------- | ----------------------- | ------------------------------ |
| `lattice_a_angstrom=4.15`, `h=1` | Both applied; no errors | `h=2.0494`                     |
| `energy_transfer_mev=1`, `A4=40` | Both applied; no errors | `sample_two_theta_deg=69.8827` |
| `h=1`, `A3=35`                   | Both applied; no errors | `sample_rotation_deg=16.9322`  |
| `h=1`, `sample_lower_arc_deg=2`  | Both applied; no errors | `sample_lower_arc_deg=0`       |


The lattice-plus-HKL example is sufficient to establish the problem: updating a lattice and specifying a target reflection together is an ordinary operation. Here, the lattice callback retains the previous Q and recomputes H, discarding the requested `h=1`.

Single-angle writes and a combined A3/A4 update worked as controls. This is a dependency-order problem, rather than a general failure to write parameters. The mechanism is already present before the UB push. [Declared order](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L7813-L7826) · [Implementation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L8066-L8094)

**Repair:** Apply coordinated groups and their derivations in dependency order while preserving subsequent explicit inputs. Contradictory coordinate requests need documented precedence or an explicit refusal.

**Acceptance:** Inspect the final parameter state after each update, including an independent geometry calculation. Checking only the returned `applied` list misses this defect.

### F2. Saving can lose recorded or edited UB observations

**Inherited defect; high closeout priority.**

The dock’s current observations and the UB model’s observation list are not kept synchronized continuously. **Calculate UB** and **Refine Lattice** copy observations into the model; **Save** serializes that model list.

I reproduced this normal workflow:

1. Start IN8.
2. Enter `(2,0,0)` for the first peak.
3. Use **Take Position** and lock the entry.
4. Save parameters and restart.

Before saving, the dock contains a valid observation with its stage angles and `ki=kf=2.6634`. The saved file contains:

```
"peaks": []
```

After restart, the observation is blank and unlocked.

There is also a masking behavior: loading that same file **without restarting** leaves the taken peak visible, because the restore path only replaces dock entries when the saved list is nonempty. The interface reports a successful load even though the file and displayed observations disagree. [Save path](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L5969-L5992) · [Restore path](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L6475-L6488)

**Repair:** Save the current observation snapshot independently of fitting U. Loading must replace the observation list even when it is empty.

**Acceptance:** Cover saving before a first fit, editing/removing/locking observations after a fit, loading an empty list in the same session, and a fresh-process restart. Saving should preserve work without implicitly calculating a new orientation.

### F3. ISAR still cannot correctly consume the current TAVI contract

**Known, planned compatibility window; completion blocker for the integrated workflow.**

There are three distinct remaining problems.

**First, requests lack the required API version.** Current ISAR scan and validation requests do not include `api_version: 2`. Passing their actual constructed bodies through TAVI’s current guard produces `400 api_version_required`. TAVI’s guard is behaving as designed; the consumer migration remains outstanding. [ISAR client](https://github.com/ammerritt-gh/ISAR/blob/e37aa900b2b80ce0cee8b308e6306e095d783bc7/isar/drive/instrument/tavi_client.py#L117-L165)

**Second, the parser silently misinterprets current output.** I generated a test response using TAVI’s production serializers and passed it through ISAR’s actual parser:


| Field                   | TAVI test payload     | ISAR interpretation |
| ----------------------- | --------------------- | ------------------- |
| HKL                     | `(2,1,0)`             | `(0,0,0)`           |
| Scan axis               | `energy_transfer_mev` | Angle               |
| Axis units              | meV                   | Degrees             |
| Scan type               | Energy measurement    | Alignment           |
| Resolution-model energy | 2.5 meV               | 0                   |
| Lattice lengths         | 4.05 Å                | 1 Å defaults        |


The parser still expects legacy field names and treats the unknown canonical energy-axis name as an angle. This can also affect importing a current TAVI scan JSON produced by the GUI or another migrated client. **Adding the API version alone will not complete U5.** [Parser](https://github.com/ammerritt-gh/ISAR/blob/e37aa900b2b80ce0cee8b308e6306e095d783bc7/isar/parsers/tavi.py#L212-L401)

**Third, acquisition planning still predicts the old scan grid.** For a scan from 0 to 1 by 0.4:

- ISAR predicts `[0.0, 0.4, 0.8, 1.2]`.
- Current TAVI executes `[0.0, 0.4, 0.8]`.

That difference reaches grid scoring, deduplication, and fingerprinting. [Grid adapter](https://github.com/ammerritt-gh/ISAR/blob/e37aa900b2b80ce0cee8b308e6306e095d783bc7/isar/drive/acquisition/grid_adapters.py#L89-L123)

**Acceptance:** A live validate → submit → retrieve → parse cycle against pinned current TAVI, with assertions on quantities, units, scan classification, and actual versus predicted coordinates. TAS_MCP’s published interface also needs inspection once its source is available.

### F4. Direct A2/A6 edits leave public Q/HKL describing the previous setting

**Inherited defect; geometry/readout synchronization.**

The crystal-angle handlers update energy, wavevector, energy transfer, and curvature. They do not refresh Q/HKL from the resulting complete motor state.

I exercised actual Qt `editingFinished` signals across:

- All four instruments.
- Both Ki-fixed and Kf-fixed policies.
- Both crystal-angle edits.

All **16 cases** left the previous public Q unchanged, with no stale marker.

For default PUMA followed by `A2=60°`:


| Quantity | Displayed  | From the current motor state |
| -------- | ---------- | ---------------------------- |
| Ei       | 7.2678 meV | 7.267843775 meV              |
| Ef       | 14.7 meV   | 14.699984097 meV             |
| Qx       | 3.1028 Å⁻¹ | 2.642255112 Å⁻¹              |
| Qy       | 0 Å⁻¹      | −0.642682852 Å⁻¹             |
| Qz       | 0 Å⁻¹      | 0 Å⁻¹                        |


The Q discrepancy is **0.79066 Å⁻¹**. HKL remains `(2,0,0)`, and public parameter reads expose the same stale coordinates. [Crystal-angle handlers](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L3857-L3932)

A useful boundary from this check: **Take Position captured ki/kf correctly in all 16 cases**, to the display precision. I did not reproduce stale energies corrupting those observations. The confirmed defect concerns the public coordinate readout.

**Repair:** Recompute Q/HKL after committing direct crystal-angle or linked energy changes, retaining the explicitly selected motors. If any displayed coordinate intentionally remains a target, its status needs to be explicit.

### F5. Explicit zero crystal-angle launches are rejected despite supported transmission semantics

**New regression in angle U3, introduced by** `9476a037`**.**

On PUMA, these launch parameter combinations were accepted before U3:

```
{"A2": 0, "scan_command1": "A3 0 0 1"}
{"A6": 0, "scan_command1": "A3 0 0 1"}
```

The current launch builder rejects them because its new crystal-angle inversion interprets `angle2k(0)` as an actual zero-energy beam, then fails the positive-energy check.

That conflicts with the established transmission contract: a crystal at exactly zero take-off **selects no energy**, so its selected energy is absent. The downstream runtime already represents this correctly, and scans whose motor command itself reaches zero still support the transmission path. Mechanical travel and analytic-engine restrictions continue to apply. [Launch derivation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/TAVI_PySide6.py#L2975-L3072) · [Approved transmission semantics](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/docs/CONFIGURABLE_INSTRUMENTS.md#L1885-L1902)

**Repair:** Distinguish transmission from Bragg energy selection in launch derivation. Preserve the raw zero angle, absent selected energy, and legitimate source settings. Also keep this direct-motor launch out of the later automatic stage-from-Q solve; removing only the positivity check leaves that second problem.

**Acceptance:** Compare held-zero launches with scans that reach zero, under both fixed-energy policies and each instrument’s travel rules.

### F6. The manual tilted-reflection acceptance tool tests a different crystal from the one it describes

**New verification-gate defect during UB truth separation, introduced by** `33a4a753`**.**

The manual tool constructs a crystal rotated 45° and tilted 4°, then describes operator belief as equal to physical truth. It supplies the tilted **belief** mount while leaving the fresh state’s `U_true` **at identity**.

The production separation of truth and belief is correct. This existing caller was not migrated to it.

At the tool’s predicted center, the unmodified setup corresponds to actual TAVI HKL approximately:

\\[ (1.41077,\\,-1.41077,\\,0.13951) \\]

Its intended `(200)` direction misses by **45.14°**. Explicitly initializing the fixture’s physical truth reduces the intended reflection’s lab-Q closure error from **2.38176 Å⁻¹** to approximately **\\(6.94\\times10^{-16}\\) Å⁻¹**.

The tool also prints the old A1/A2/A4 meanings for the take-offs. Those labels need to become A2/A4/A6. [Manual gate](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tools/check_tilted_reflection.py#L153-L176)

**Repair:** Explicitly set the controlled fixture’s physical truth equal to its intended mount before constructing the scan configuration, update the labels, and run its stated acceptance criteria.

The audit’s separately corrected physical control produced **44 detector events at the solved tilted IN8 setting and zero with the arcs zeroed**, at one million histories per point. That supports the production path, while confirming why the existing manual gate needs repair before it can be used for sign-off.

### F7. Negative slit scan gaps are accepted as feasible and emitted to McStas

**Validation gap in the scan surface introduced by U3.**

The command:

```
pre_sample_hgap -1 -1 1
```

is accepted on all four instruments. The runtime emits a negative full gap of **−0.001 m**.

A real PUMA run over −1, 0, and +1 mm confirmed that the negative gap reaches McStas. It runs without a negative-width warning. The stock slit component obtains reversed bounds and consequently absorbs every intersecting ray. Zero width gets its separate closed-slit warning.

A physically impossible negative aperture can therefore produce a plausible-looking closed-beam result. [Planner constraints](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/instruments/rules.py#L371-L407) · [Runtime emission](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/instruments/tas_runtime.py#L1359-L1368)

**Repair:** Validate finite, nonnegative **effective** gaps after relative offsets are applied. Preserve zero as a legitimate closed slit, and cover directly supplied base gaps as well as scanned points.

### F8. Fine scans silently collapse into repeated positions

**Inherited defect retained by the new planner.**

Execution coordinates are rounded to three decimals regardless of their units.

For:

```
h 1 1.001 0.0001
```

the current planner accepts eleven points, but its execution grid contains:

- Six points at `h=1.000`.
- Five points at `h=1.001`.

An equivalent A3 scan from 0 to 0.001 in 0.0001° steps also contains only two distinct positions.

The new finite-value, step-sign, point-count, and non-overshoot checks do not eliminate this quantization. [Grid expansion](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tavi/utilities.py#L96-L141)

**Repair:** Preserve calculation precision through expansion and execution, with rounding reserved for presentation. If a physical step resolution is intended, declare it per quantity and refuse unsupported requests explicitly.

**Acceptance:** Compare requested, validated, and executed coordinates for fine, descending, relative, and non-dividing scans. Coordinate serialization and output naming should be checked alongside this change.

### F9. Analytic convolution still assumes H/K/L correspond to the resolution directions

**Documented, pre-existing scientific approximation.**

This is the most consequential retained scientific limitation.

The new true-HKL **center** conversion is correct. However, the deterministic convolution still scales reciprocal-coordinate offsets by \\(2\\pi/a\\) and contracts them directly with a resolution matrix expressed in:

\\[ (Q\_\\parallel,\\ Q\_\\perp,\\ Q\_\\mathrm{vertical},\\ E). \\]

Phonon gradients likewise receive only the cubic scalar conversion. The per-point transformation from crystal reciprocal coordinates into the instrument resolution basis is missing. [Convolution](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tavi/deterministic_engine.py#L598-L624)

I tested symmetry-equivalent Al radial scans: `(200)` scanned along H, and a remount that makes `(020)` scanned along K physically identical. The mounted Q vectors and solved motor settings agree to numerical precision.

The model nevertheless predicts:


| Radial offset | H-radial mean counts | Equivalent K-radial mean counts |
| ------------- | -------------------- | ------------------------------- |
| 0 r.l.u.      | 100.00000            | 100.00000                       |
| 0.005 r.l.u.  | 90.03329             | 86.90415                        |
| 0.010 r.l.u.  | 65.87509             | 57.19705                        |
| 0.020 r.l.u.  | 19.21594             | 10.94157                        |


The final K-based prediction is **43.1% lower** because a physically radial offset is assigned to the perpendicular resolution direction. These are deterministic model outputs, not experimental intensity measurements.

This limitation predates the pushes and is explicitly acknowledged in the documentation. It means the orientation support in targeting and fitting is broader than the currently justified support for quantitative analytic peak shapes. [Documented approximation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/docs/ANALYTIC_ENGINE.md#L189-L194)

**Repair or scope decision:** Supply the true per-point reciprocal-to-resolution transformation, including B. Transform reflection offsets with that map and gradients with the corresponding inverse transpose. Until that work is done, retain an explicit restriction on quantitative general-mount analytic predictions.

## Fundamental checks that passed

The current angle mapping is consistent across the reviewed public paths:


| Angle | Meaning                            |
| ----- | ---------------------------------- |
| A1    | Monochromator θ, derived from A2/2 |
| A2    | Monochromator 2θ                   |
| A3    | Sample turntable rotation          |
| A4    | Sample 2θ                          |
| A5    | Analyzer θ, derived from A6/2      |
| A6    | Analyzer 2θ                        |


A1/A5 input refusals are intentional, as are the retired correction names and version boundaries. The remaining internal legacy identifiers were explicitly deferred; their presence alone does not indicate a public-contract defect. [Current convention](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/docs/INSTRUMENT_LAYOUT.md#L25-L164)

The independent geometry checks supported:

\\[ Q\_\\mathrm{mount}=UBhkl,\\qquad R\_\\mathrm{stage}=R_y(A3)R_x(sgl)R_z(sgu), \\]

and the emitted local-frame transform:

\\[ R\_\\mathrm{engine}=(R\_\\mathrm{stage}U\_\\mathrm{true})^T. \\]

The checks also supported the positive-sense Friedel handling in the peak inverse paths. The separation between hidden physical truth and operator belief is a substantive improvement over the pre-UB implementation. [Orientation implementation](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tavi/orientation.py)


| Independent check         | Coverage                                             | Result                                                                         |
| ------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| Reciprocal metric         | 300 valid random nonorthogonal cells                 | \\(B^TB=(2\\pi)^2G^{-1}\\); max absolute discrepancy \\(8.24\\times10^{-13}\\) |
| Crossed-arc reachability  | 4,000 random Q vectors                               | Zero disagreements with a separate reachability oracle                         |
| Forward/inverse Q closure | All accepted random points                           | Maximum errors around \\(4.4\\times10^{-15}\\)                                 |
| McStas arm reconstruction | Independent stage and true rotations                 | Maximum matrix-element error \\(9.99\\times10^{-16}\\)                         |
| Two-/multi-peak fitting   | 200 orientations, four lattice families, both senses | Maximum U error \\(1.42\\times10^{-15}\\) / \\(5.33\\times10^{-15}\\)          |
| Lattice refinement        | All seven crystal systems                            | Recovered synthetic lattices to numerical precision                            |
| Plane locking             | 400 random attempts, including unreachable cases     | Reachable planes levelled to numerical precision                               |


These used independent constructions, including a separate rotation implementation and a closed-form reachability condition. They provide meaningful evidence beyond round-tripping the same helper.

## Test and real-engine results

### Repository tests

The complete initial TAVI run returned:

**2,356 passed, 67 failed, 32 errors, 193 skipped.**

I traced **49 failures and all 32 errors** to missing McStas resources. After making McStas 3.4 available in the isolated audit environment, the focused build-tree and parameter-binding rerun passed **all 96 tests**.

The remaining TAVI failures were:

- **16 layout parameterizations**, mixing genuine clipping with overly strict preferred-size checks.
- **Two exact floating-point goldens**, differing by only \\(2.22\\times10^{-16}\\) and \\(3.89\\times10^{-16}\\). Historical and current implementations were bit-identical under the same environment. [Golden comparison](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tests/test_orientation.py#L303-L336)

ISAR’s geometry suite returned **69 passed, one failed**. Its failing golden compares optimizer-selected angles at \\(10^{-9}\\) degrees. The maximum recorded-angle drift was \\(4.47\\times10^{-7}\\) degrees, while current ISAR and TAVI returned **exactly the same angles** on this host. Physical Q closure remained at numerical precision.

These results support numerical-tolerance cleanup. They do not establish geometry drift.

### Actual McStas controls

All four current instrument models generated C, compiled, ran serially, and wrote detector output using the new physical parameter names.

The subsequent one-million-history controls produced:


| Instrument/control                        | Predicted or solved setting       | Displaced control  |
| ----------------------------------------- | --------------------------------- | ------------------ |
| PUMA, nominal `(200)`, sample sense −1    | 214 detector events               | 0 at A3 +2°        |
| IN8, nominal `(200)`, sample sense +1     | 44 detector events                | 0 at A3 +2°        |
| IN8, correctly initialized tilted crystal | 44 detector events at solved arcs | 0 with arcs zeroed |


That is real engine evidence for the nominal sign conventions and the **truth → stage solution → emitted sample orientation → Bragg response** path.

It does not constitute a fitted rocking-curve center check, a completed GUI alignment exercise, MPI validation, or an absolute-intensity benchmark.

## Smaller cleanup and remaining limits

The new inline angle rows can crop leading digits in the tested Linux layout. With `A2=123.4567`, the field contains 57 pixels of text in a 50-pixel control; its A1 readout is also cramped. Stored values remain correct. This layout change belongs to the angle programme. The long runtime estimate and a reflection-table checkbox also clip, while the “Valid Commands” button’s failure is a preferred-size false positive. [Inline layout](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/gui/docks/instrument_dock.py#L72-L97)

There are also stale test fields and comments. In particular, the fingerprint test assigns an obsolete `A3` attribute instead of the real turntable field, weakening that part of its coverage. [Fingerprint test](https://github.com/ammerritt-gh/TAVI-Triple-Axis-Virtual-Instrument/blob/97a295b3d6167843b0f4259aa79b284dc55a3857/tests/test_orientation.py#L1018-L1030)

The material coverage limits are:

- **Windows-specific behavior:** 187 skipped cases; native operator layout remains unverified.
- **Full alignment acceptance:** capture → fit → grade → lock → save/restart was not completed as a single physical GUI exercise.
- **General noncubic transport:** Python geometry was checked, but the real sample controls used cubic Al. Its symmetry limits what intensity alone establishes about component-axis indexing.
- **Other unavailable coverage:** the Pb DFT asset path, external documentation checker, MPI, and TAS_MCP’s source.

## Recommended closeout sequence

I would organize the remaining work into four focused repair groups and one scientific decision:

1. **State and persistence:** F1, F2, and F4. Make acknowledgements, displayed coordinates, saved observations, and actual geometry agree.
2. **Scan correctness:** F5, F7, and F8. Resolve transmission, physical gap domains, and execution precision through the shared planning/runtime path.
3. **Acceptance tooling and presentation:** F6, the obsolete test fields, numerical tolerances, and angle-value clipping.
4. **Consumer completion:** land U5 and verify a real ISAR request-and-parse cycle, then inspect TAS_MCP.
5. **Analytic scope:** implement F9’s frame mapping or explicitly retain its restricted scientific scope.

The mathematical changes have substantial supporting evidence. Closeout should now require the recorded workflow checks alongside the numerical and regression suites, with each remaining defect either repaired or explicitly accepted with its practical limits.