# Handoff — facility moderator source (Source_Maxwell_direct)

> **Status:** live
> **Authority:** the frontier of the source rework, rewritten at every closeout

**End condition:** job j0236ccacd89b lands on main (or the operator cancels it).
**Board entry:** Facility moderator source: Source_Maxwell_direct (job j0236ccacd89b)

## Frontier
- Landed: nothing on main yet; the branch carries all three units (component, `instruments/source.py`, TAVI integration) and amendment 5's strip of the per-run source stamp; frontier at `d432fef81dc6`.
- Verified: acceptance suite on `d432fef8`, 3277 passed, 5 skipped (dispersion map without the Pb data file, the absent shared doc checker, 3 `test_api_stage_solve`); acceptance fragment passed on `94ea6a09`; build and verify seats complete, no open attempt, no undecided finding (slice coordinator's report, 2026-10-16).

## Next
Bind the handoff, then launch a fresh slice coordinator from `acs-job next --job j0236ccacd89b` for refine: `slice_refine` and `lens_refine` (tell the design_fit lens seat its "component version and file hash" clause is superseded by amendment 5; the gui lens needs offscreen Qt with real widgets, so a leaf that can run Python).

## Where
- Job: j0236ccacd89b, handoff `acafe92c009780824edfac7c9f3ba00cb300d8d7b330f3dba760edc4aa72d2c2`, bound with `acs-job.bat bind --handoff acafe92c009780824edfac7c9f3ba00cb300d8d7b330f3dba760edc4aa72d2c2 --session <id> --host claude`
- Branch: `acs/j0236ccacd89b`; upstream ahead 53, behind 46 (local branch, not pushed)
- Worktree: `C:\Users\AMM\Documents\Github\Science\.jobs\TAVI\source-rework-source`
- PR: none

## Verify before trusting
1. The branch is still open: `git fetch --prune`, then `gh pr view acs/j0236ccacd89b --json state` (no PR exists yet; `acs-job.bat show --job j0236ccacd89b` names the stage). If it merged since this was written, do not resume it: close the job and continue from main.
2. `git -C C:\Users\AMM\Documents\Github\Science\.jobs\TAVI\source-rework-source log --oneline -1` prints `d432fef8`, and `git status --short` there is empty.
3. `acs-job.bat show --job j0236ccacd89b` shows stage refine, no open attempts.

## Decisions since the plan
none (amendment 5, the operator's strip of the per-run component stamp and rebuild hash, and the starting-mode and model-version rulings are built on the branch and recorded on the job)

## Open items
- After refine: `external_slice` on ChatGPT Pro (receipt r6e5022d9aca7), `external_verdict`, the PR for the operator to see before landing, `land`.
- Deferred P4 a724d25870322-1: `components/README.md:134` on the branch still claims exact `Source_gen` equivalence (one clause); fold into the next repair touching that README section, else list in the PR body.
- When it lands: `docs/HANDOFF-spaced-profile-install.md:149` names `source_type`/`source_dE` in `gui_values`; update it on main. `TODO.md:140` (slit bindings) was keyed to this contract bump.
