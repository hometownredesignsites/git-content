# Assignment Validation, Slot Isolation, Idempotency, and Benchmarking

## Repository and branch discovery
For the current `content-post` workflow:
- Repository: `hometownredesignsites/content-post`
- Branch is slot-specific: `chatgpt-slot1`, `chatgpt-slot2`, or `chatgpt-slot3`
- Fetch latest remote state before any read/decision that depends on branch state.
- Assignment record is root `todo-today/assignment.json`.
- Assigned starting HTML is root `todo-today/index.html`.
- Do not use the legacy `sites/<site-slug>/todo-today/` path.
- Validate source_path in assignment against the actual starting source; verify it matches the assignment and is consistent with root source HTML.

## Required assignment identity
Capture and validate exact values:
`task_id`, `site_slug`, `batch_id`, `slot`, `branch`, `source_path`.
Slot must match the automation's immutable assigned slot; branch must be the corresponding slot branch. Missing, malformed, conflicting, wrong-slot, wrong-branch, or missing/inconsistent source is a blocker.

## Assignment continuity
- A valid assignment remains active until the authoritative orchestrator changes it or the assigned slot completes its return.
- Do not reject an assignment solely because its date/timestamp is old, it is unchanged since a prior scheduled run, or another assignment is queued upstream.
- Never infer a replacement assignment from the queue, other slot branches, folder names, or schedule firing.
- Work the exact valid live assignment if not completed. Never substitute another task/business.

## Completion evidence: strict rule
Completion (`ALREADY_COMPLETED`) requires matching ALL of:
- task_id
- batch_id
- site_slug
- slot
- branch

And evidence that BOTH authorized return paths exist/are committed for that identity:
1. `todo-today/revised/index.html`
2. `todo-today/revised/metadata.json`

Evidence may be:
- current matching metadata plus matching revised HTML, or
- a prior commit on the target branch demonstrably adding/updating both exact files for that assignment identity.

A scheduled trigger, unchanged assignment, old timestamp, source HTML, task record, unrelated commit, metadata alone, HTML alone, or another slot's completed revision does not establish completion. If metadata is absent, explicitly inspect branch history for a matching two-file return before deciding.

## Conflicting return files
If current metadata identifies another assignment, do not overwrite blindly. Inspect branch history and authoritative orchestration state. Proceed only if safe ownership/current assignment is established; otherwise stop with a precise conflict report.

## Same-day cross-slot quality benchmark (operational procedure)
Only perform this when the current assignment's live instructions require a benchmark. For Slot 2, the intended benchmark is Slot 1; follow the invocation's named benchmark slot if it differs.

1. Fetch the latest remote state of the benchmark slot's exact branch (for Slot 1: `chatgpt-slot1`) before inspecting files. Do not use a stale local checkout or old screenshots/artifacts.
2. Read the benchmark branch's live root `todo-today/assignment.json`. Verify its `task_id`, `batch_id`, and `site_slug` match the current worker assignment, and verify the benchmark assignment's `slot` and `branch` identify the expected other slot. Also verify its `source_path` is consistent with its branch's root `todo-today/index.html`.
3. Read `todo-today/revised/metadata.json` and confirm its `task_id`, `batch_id`, `site_slug`, `slot`, and `branch` match that benchmark assignment. Confirm `todo-today/revised/index.html` exists and that completion/commit evidence is current on the fetched remote branch. Do not treat an assignment file alone, metadata alone, or an uncommitted/local candidate as a completed benchmark.
4. Inspect the actual returned revised HTML (not just a summary or screenshot) read-only. Review and compare design hierarchy/art direction, hero/image selection and crop, typography, responsive behavior, motion, interaction states, accessibility, and implementation quality. Capture fresh screenshots only if the runtime supports it and only as QA evidence for this run.
5. Record the benchmark slot, exact matching assignment identifiers, branch/head or commit inspected, files inspected, comparison findings, and the specific improvements planned for the current worker. Use the benchmark to match or exceed quality while intentionally choosing a distinct composition/typography/color/layout direction; do not copy its design or assets wholesale.
6. Never edit, stage, commit, push, or otherwise change the benchmark slot. Benchmark access is read-only.

If any identity field mismatches, the benchmark return is incomplete, the branch cannot be fetched, or its current completion cannot be verified, treat it as unavailable. Do not fall back to prior-day or other-business material. State the exact reason and continue to the premium quality standard without claiming a comparison.

## Strict scope
Slot owns only its branch and assignment. No edits to other slots or branches. Read-only cross-slot benchmark access is allowed only when explicitly required and assignment identifiers match.


## Slot 2 exact completion evidence (current automation-specific rule)
For Slot 2, do not mark an assignment ALREADY ASSESSED based on a source candidate, assignment file, scheduled run, unrelated commit, other-slot return, or absence/presence of metadata alone. Require exact identity match for `task_id`, `batch_id`, `site_slug`, `slot=2`, and `branch=chatgpt-slot2` with one of:
1. `todo-today/revised/metadata.json` matching all identity fields **and** `todo-today/revised/index.html` present; or
2. a prior commit on `chatgpt-slot2` demonstrably adding/updating **both exact return paths** for that same identity.

If matching completion evidence does not exist and the live assignment/source are valid, proceed. A valid assignment remains active even if its date is older; do not stop because the assignment is unchanged, a newer task is queued upstream, or the scheduled trigger ran again.