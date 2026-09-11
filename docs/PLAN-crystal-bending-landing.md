# Landing plan v2 — crystal-bending-generality

Goals file: the repository has neither DESIGN_GOALS.md nor WIP.md. Standing
statements: AGENTS.md Key Design Decision 3 (no duplicated physics in GUI
code) and the handoff's settled rulings. This plan adds no curvature policy
and reopens no ruling. GUI Run-button scans stay unblocked by the API's
per-point *feasibility* validation; a curvature *travel refusal* is a
different gate and already applies to GUI Run for absolute commands.

## Envelope
Outcome: branch merged to main with every defect below fixed or pinned with
a reason, the client contract documented, and a PR body a reviewer can
check. Non-goals: new behaviour; reopening rulings; ISAR changes; history
rewriting; anything in M1 entering the PR.
Budget: 8 branch slices + 1 main commit; per slice one executor, one
review_files, up to two critique rounds. Program ceiling: 4 Codex calls
(2 used: draft, critique; 2 remain for per-slice review/critique), 3 panels (3 used: brainstorm, council, final
council). Further seat needs go to chat.

## Defects confirmed this session (each verified by reading the code; D13 by a red test)
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

## Slices (branch), landing order
L1 One ideal-radii function (D13). `_ideal_bending_from_modules(...,
   requested_axes)`; both API callers pass the AUTOFOCUS set exactly as
   compute_scan_snapshot does; `_compute_ideal_bending_values` = widget
   reads + one call, its own focusing_known filter deleted.
   Acceptance: probe tests promoted to tests/test_in12_plugin.py, red on
   HEAD, green after; parametrised over the five refresh triggers with
   Heusler rva HELD; existing Heusler refusal test unchanged; suite green.
   Stop: a locked-to-ideal axis with focusing_known=False reachable in GUI
   state.
L2 split per the final council: L2a helper (D14, D22); L2b one commit each for D20 and D21, independent of L2a, landed after it.
   One curvature-travel check for scan commands (D14, D20, D21, D22).
   Decision made, not left open: extract validate_scan_launch_state's
   `_curvature_violation` (expand a command, relative or absolute, from a
   base value; check each endpoint with curvature_command_error) into one
   module-level helper in instruments/tas_runtime.py; validate_scan_command's
   literal absolute check is DELETED and replaced by a call to that helper
   with the base value from the field (GUI) or vals (API); the manifest
   calls the same helper. Base value for a relative command is the launch
   value of that axis (for AUTOFOCUS that is the last ideal; the scan makes
   it SCANNED, so that is the defined base). A non-numeric field with a
   relative command on that axis is a hard issue naming the field.
   run_simulation's lone-command-2 swap also swaps the relative flags (D20).
   `_held_curvature_issues` and the API HELD loop skip any axis named by a
   non-empty scan command (D21), reading the command variable through
   normalize_scan_variable. D22's test is rewritten to assert the preflight
   now refuses.
   Entry-point regression (Pro review): run_simulation_thread with the
   enqueue intercepted; the out-of-travel relative scan never queues, an
   in-travel one does.
   Acceptance, all red-first on the real controller: PUMA rhm 2.5 relative
   "rhm -1.9 -1.5 0.1" refused by _preflight_scan_validation with the travel
   sentence; relative "rhm 0.5 1.0 0.5" at 2.5 accepted; command-2-only
   relative executes the same values validation saw (assert the expanded
   scan values in the result metadata); unlocked rhm 1.0 with absolute
   "rhm 3.0 4.0 0.5" accepted on GUI and API; API behaviour for absolute
   commands unchanged (existing test_curvature_command_refusal.py green).
   The fixed-axis refusal (a scanned axis an NMO holds fixed) stays ahead
   of the helper and is not gated on relative; the acceptance includes
   that case unchanged.
   Codex critique adopted: the helper checks EVERY expanded value, not the
   endpoints (PUMA absolute "rhm 0 2 1" has legal endpoints and an illegal
   1 m interior point); absolute and relative versions of that case are in
   the acceptance. Also adopted: an axis a scan command names is excluded
   from the launch-time ideal refresh (API defaults keep rva AUTOFOCUS until
   the snapshot promotes it, so a Heusler rva scan with no rva patch is
   refused today); acceptance case: API IN12 Heusler, scan "rva 0.3 0.6 0.1",
   no rva parameter, accepted.
   Stop: if the helper cannot serve both without a mode flag that changes
   semantics, stop and report; that is a new twin.
L2c Point kinematics reach the resolution model (D23). The overlay helper
   becomes `_vals_with_point_state`, applying the snapshot's Ei/Ki/Ef/Kf and
   deltaE alongside the radii, in all three consumers: the deterministic
   kernel, the McStas background widths, and compute_resolution (which
   solves its own point and sets the energies from that solve).
   Acceptance, red-first: PANDA angle-scan snapshot, A1 = -74.332, A4 = +50,
   Kf-fixed 4.97845 meV: the resolution config's kfix equals the point's
   own Kf and its incident energy is positive; the same for an A1 scan
   under Ki-fixed; an HKL/energy scan's config unchanged (existing
   test_resolution_point_curvature.py green). Both consumers spied.
L3 GET /resolution carries module state (D15). compute_resolution applies
   vals['modules'] to check_state through the plugin's scan_config mapping
   (reuse, not a new map). Acceptance: red-first, PUMA nmo="Vertical",
   point_radii rhm == rvm == 0.0 and the matrix matches a no-curvature run;
   without NMO unchanged.
L4 Fixed-axis field sync for all four axes (D16). One loop in
   update_ideal_bending_buttons: any axis whose resolved policy is not
   driven is synced to its resolved radius and disabled; rva's special
   clause becomes the general one. Acceptance: offscreen-Qt test, PUMA,
   locks off, select NMO: rhm/rvm fields read 0.000 and are disabled,
   _held_curvature_issues empty; deselect: editable again.
L5 Small twins and weak tests (D17, D18, D19, D24, D25). D24: a point
   guaranteed infeasible, None at its exact index, neighbours intact. D25:
   a stubbed McStas execution result exercising the recording boundary. curvature_limits through
   effective_curvature_axis; rhmfac/rvmfac in build_PUMA_instrument wired to
   the resolved axis or deleted, doc paragraph corrected; both stubs
   delegate to the real controller's methods. Acceptance: suite green,
   package_validation clean.
L6 Client contract (G1). API_USER_GUIDE.md and API_SERVER_DESIGN.md:
   applied_curvature (signed, metres, index-parallel, None for skipped,
   row-major for 2D), magnitudes on input, sign from the actual take-off
   angle, curvature_modes read-only and derived, why copying returned
   parameters is not an exact replay. Acceptance: examples checked against
   a serialized ScanResult produced in a test.
L7 Session records committed: one docs-only commit, last on the branch, so
   the code diff is readable without it. Workspace convention keeps
   transcripts in the discussed repo.
L8 FENCED: the external reader has returned; its findings are D14, D20,
   D21, D15, D22 above, all assigned to slices. No further external round
   before L9. Nothing open-ended remains in this slice.
M1 On main, T1, never in the PR: test-infra doc hygiene (concurrent-suite
   warning names the persistence tests and config/parameters.json in
   TODO.md, AGENTS.md step 3, tests/README.md; absolute micromamba path for
   Git Bash; `-ra` in the documented command and the Pb-map hardlink step
   for worktrees; AGENTS.md test-count line dated). Off-limits to the branch.
L9 Final evidence at the final SHA: serial suite with wall-clock and a
   180 s kill, package_validation, the four compiled smoke runs with
   install_no_window_guard() (numbers into the PR beside the existing
   table); review_files base=main; reviewer role on the landing commits;
   external reader on the pushed branch (one round, findings dispositioned
   in chat, not a new slice unless P0/P1). Handoff corrected (H1; closure claims restated with the D-list). PR body: base/head SHAs, the
   defect map D1-D22 with the layer each lived in, the two sign contracts,
   the rulings, smoke tables, ISAR numerical-change notice with the SHA to
   pin, pinned follow-ups, handoff block, `main: clean/dirty`. Merge is the
   operator's.

## Decision for the operator (Tier 1)
Handoff file: leave on the branch (recommended; lands at merge, the PR is
where a session on main finds it) or add a main-owned copy per the floor
rule (Codex draft) and merge main into the branch.

## Pinned (TODO.md rows at L9)
ISAR ingestion of applied_curvature checked from ISAR's side; campaign
manifest pinning the TAVI SHA; PUMA arm lengths provisional; IN12 mono
minima and IN12/PANDA analyser vertical radius unsourced; non-numeric GUI
radius silently blocks the run (partly addressed by L2 for relative scans);
angle-dependent bender travel; bender slew cost (virtual clock);
TAVI-wt-before worktree removed at closeout.

## Seat dispositions so far
- review_files base=main: Major 1 (compute_scan_snapshot try/except)
  REJECT-because: unreachable from GUI (button disabled), refused at API
  submission, and a raise becomes a PrepFailure with a message; the test
  asserts the raise on purpose. Major 2 = D13, FIX (L1).
- reviewer role: P1 D14 FIX (L2); P2 D15 FIX (L3); P2 D16 FIX (L4); P3 D17,
  D18, D19 FIX (L5); P4 stub getter FIX (L5).
- External reader: P1 D14, P1 D20, P2 D21, P2 D15, P3 D22: all FIX (L2/L3).
- Codex draft: L01 main-owned handoff DEFER to operator; L02 = M1 adopted;
  L03 = L1 adopted incl. "no catch-and-continue in compute_scan_snapshot";
  L04 test-strengthening adopted into L2/L6 acceptance (serialized result);
  L05 = L6 adopted; L06 evidence shape adopted into L9; open questions 1-2
  pinned.
- Brainstorm: differential GUI/API test idea folded into L2/L4 acceptance
  rather than a separate sweep (the sweep would be a fifth policy surface
  to maintain); before/after fixture = existing pinned-table tests + smoke
  table; structural deletion adopted where a twin could be deleted (L1, L2).
- Council: nay on open-ended L8 ADOPTED (fenced); nay on L7 in the PR
  REJECT-because the workspace convention places transcripts in the repo
  and it is a docs-only last commit; nay on leaving D14's home open ADOPTED
  (decided: one helper, literal check deleted); L6 optional REJECT-because
  a contract another repo reads with zero documentation is a defect, not a
  preference.
