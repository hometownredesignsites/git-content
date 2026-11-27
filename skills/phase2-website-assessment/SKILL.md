---
name: phase2-website-assessment
description: Perform the daily website assessment and redesign workflow for a strictly assigned worker slot (Slot 1, 2, or 3), using live GitHub assignment data and the latest source website. Use for scheduled daily assessment runs and authorized slot-specific redesign work.
---

# Phase 2 Website Assessment

Run the daily website assessment workflow for the slot supplied by the invoking automation. This is a **shared, slot-agnostic workflow**, not permission to select or change assignments.

## Required invocation context
The caller must identify:
- `assigned_slot`: exactly Slot 1, Slot 2, or Slot 3
- the expected assignment/worker identity, if the caller provides one
- any explicitly authorized repository, branch, output path, or scope restrictions

If assigned slot is missing or ambiguous, stop and report a blocker. Do not guess.

## Standard repository workflow (unless live assignment instructions override with newer verified specifics)
- Repository: `hometownredesignsites/content-post`
- Slot branches: `chatgpt-slot1`, `chatgpt-slot2`, `chatgpt-slot3`
- Slot branch assignment: root-level `todo-today/assignment.json`
- Assigned starting HTML: root-level `todo-today/index.html`
- Authorized return paths: `todo-today/revised/index.html` and `todo-today/revised/metadata.json`
- Metadata must preserve the exact live assignment values for `task_id`, `site_slug`, `batch_id`, `slot`, and `branch`.
- The older `sites/<site-slug>/todo-today/` assignment path is obsolete; do not use it.
- Fetch latest remote branch state before any work. Do not trust a stale local checkout.

## Governing principles
1. **Live data wins.** Fetch current instructions, worker guide, assignment, and source website from their authoritative locations. Do not reuse stale assignment details, research, variables, screenshots, assets, or QA results from earlier runs.
2. **Slot ownership is immutable.** Work only on the assignment belonging to the invoking slot. Never switch slots, claim another slot's task, or treat another slot's completion as this slot's completion.
3. **Idempotent operation.** Establish whether the exact live assignment has already been completed before doing work. Use durable evidence, not assumptions or a stale status.
4. **Scope and safety.** Modify only authorized deliverables. Preserve unrelated files and work. Never force-push, rewrite history, or broadly clean files.
5. **Accuracy first.** The source business website is authoritative for business-specific facts. Do not invent services, locations, certifications, testimonials, awards, prices, or claims.
6. **Quality over expedience.** Produce a polished, responsive, accessible redesign and perform available QA. Do not call incomplete or failed QA successful.
7. **Traceability.** Record the relevant assignment identity, source revision/commit, checks performed, outcome, and blockers in the report.

## Workflow
Follow the steps in order. Detailed requirements are in the reference documents.

### Protected source content and redesign standard
- Treat the assigned source HTML as the starting point and redesign baseline, not merely a list of facts.
- Before editing, identify its strongest existing design assets/components and preserve/elevate them: full-bleed hero, source photography, distinctive layouts, section rhythm, gallery, forms, useful interactions.
- Preserve existing sections, verified facts, services, contact details, working links, form fields/options, project imagery, and useful interactions unless there is a demonstrable defect or explicit direction to change.
- Preserve all image `src` and `srcset` values and their order. Do not remove source photography or replace it with generic images. Keep an existing full-bleed hero full bleed unless the image or layout is demonstrably broken; improve overlay, contrast, crop, focal point and responsive behavior without losing immersion.
- Never remove a contact/inquiry form because it lacks a backend. Preserve fields, labels, options, validation and submit affordance. For a POC with no endpoint, disclose that it is a front-end demo and not connected; any demo confirmation must not transmit/store data or imply actual delivery.
- Keep existing CTA destinations and contact actions. Do not invent endpoints or remove primary conversion paths.
- Design must be a visibly stronger, persuasive premium concept, not conservative cleanup or a generic template. Do not confuse minimalism or fewer sections with quality; avoid filler, empty slogans and repetitive grids when original content supports stronger composition.
- Compare directly against the original source: preserve its strengths and verify the redesign is better in visual hierarchy, image treatment, typography, spacing, responsiveness, conversion clarity and interaction polish. Reject changes that make original strong components less immersive, useful or complete.
- Complete a top-to-bottom preservation review before return: full-bleed hero, original forms and controls, sections, source images, CTA/contact paths.

### 1. Load current instructions and identify the slot
- Read the shared worker prompt and workflow README when the invoking environment or live instructions specify them; treat these as authoritative for shared worker behavior and handoff.
- The workflow crosses distinct repositories: `git-content` coordinates generation/validation and assignment; private `content-post` owns assignments, slot returns, ledger, promotion and publication. Workers revise only their assigned slot and do not choose businesses or operate the ledger.
- The orchestrator assigns the same daily business batch to Slots 1-3. The batch and task identifiers—not just the business name—must be used to establish same-day benchmark eligibility. See `references/orchestration-handoff.md`.
- Schedule worker runs after the orchestrator's assignment update (documented as 12:17 UTC; verify live schedule before deployment).
- Retrieve the latest worker guide and relevant repository instructions.
- Read the live assignment source and confirm the caller's assigned slot.
- Identify and capture the exact `task_id`, `site_slug`, `batch_id`, `slot`, `branch`, and `source_path`, plus business, source URL, allowed output files, and completion protocol. Validate that root `todo-today/index.html` matches the assigned `source_path` and is the actual starting input.
- Validate that assignment and worker identity match. See `references/assignment-validation.md`.
- If assignment data is missing, inconsistent, or inaccessible, stop safely and report exactly what is blocked.

### 2. Establish a fresh run
- Use a new run context. Do not reuse artifacts, browser state, screenshots, candidate HTML, image bytes, extracted source content, or QA results from a previous run unless the live workflow explicitly calls for it and identifies them as current inputs.
- Keep temporary artifacts in the prescribed run directory. Follow storage and naming rules from the live guide.
- Capture the assignment identity and relevant source commit/revision for traceability.

### 3. Check idempotency
- Capture the full live assignment identity: `task_id`, `batch_id`, `site_slug`, `slot`, `branch`, and `source_path`.
- Inspect `todo-today/revised/metadata.json` and corresponding `todo-today/revised/index.html` if present, and inspect recent branch history for prior commits/archived return evidence.
- **Completion requires exact identity evidence** matching all of `task_id`, `batch_id`, `site_slug`, `slot`, and `branch`, and both return files: either current metadata + HTML are present and consistent, or a prior branch commit demonstrably added/updated both exact return paths for that same identity.
- A scheduled run, source candidate, assignment timestamp/date, task unchanged since yesterday, unrelated commit, or another slot's return is NOT completion evidence.
- If the exact assignment has completed-return evidence, no-op: no edits, commit, or push. Report `ALREADY_COMPLETED` with matching identifiers and evidence.
- If the live assignment is valid, source is consistent, and exact completion evidence is absent, proceed. Do not call a valid active assignment stale just because it is unchanged or older than one day; it remains actionable until completed or authoritative orchestration changes it.
- If current return metadata belongs to a different assignment, inspect authoritative state and history. Do not overwrite it unless ownership/current-run safety is established. If conflict remains unresolved, report `BLOCKED`.
- Never infer a new task from queue/folder contents or switch to a different assignment/business.

### 4. Read-only same-day cross-slot benchmark
- If the current assignment's guide requires benchmarking, inspect the best available completed revision from another slot, read-only only.
- Fetch the latest remote benchmark branch before inspection; verify its live assignment identity, expected slot/branch, source path, and returned metadata. Confirm the actual revised HTML exists and its completion is verifiable on the fetched remote branch. Do not benchmark an uncommitted candidate, prior-day material, or mismatched task.
- Inspect the actual returned HTML read-only. Compare art direction, hero/image treatment, typography, responsive behavior, motion, interaction, accessibility, and technical quality. Record matching identifiers, branch/commit, files inspected, findings, and planned improvements. Create a meaningfully distinct design direction rather than copying.
- Never modify, commit, or push another slot. If the correct same-day benchmark cannot be identified or accessed, state the specific reason and proceed to the premium quality standard. See the operational procedure in `references/assignment-validation.md`.
- See `references/assignment-validation.md`.

### 5. Research and assess the business
- Open the assigned source website and inspect the relevant pages.
- Establish verified business name, location(s), services, contact information, brand cues, and available imagery.
- Note weaknesses and opportunities in the current website experience, without making unsupported factual claims.
- Do not transfer research between businesses or assignments.
- See `references/redesign-brief.md`.

### 6. Create the redesign deliverable
- Follow the current assignment's required file format, destination, and content scope.
- Use a distinct, purposeful design direction; avoid generic template output.
- Ensure the result communicates the business's verified offering and includes clear conversion paths.
- Implement appropriate visual hierarchy, typography, spacing, navigation, responsive behavior, and interaction states.
- See `references/visual-effects.md`.

### 7. Quality assurance
- Perform the available QA appropriate to the runtime and deliverable.
- Test responsive layouts, content accuracy, links/CTA destinations, accessibility basics, and visual integrity.
- Record every QA checklist item with **PASS / FAIL / NOT CHECKED / FALLBACK**, plus concise evidence or the reason it was not checked. Static checks and browser/runtime checks must be distinguished.
- If browser testing is available, explicitly test desktop and narrow mobile layout, overflow, console/runtime errors, image loading, hero crop/readability, mobile navigation, links/CTAs and safe form behavior, keyboard navigation/focus, reduced-motion, scroll reveal, card interactions, and intermediate responsive widths. Record viewport sizes and environment.
- If a browser or capability is unavailable, disclose the limitation, mark relevant checks NOT CHECKED or FALLBACK, and use only permitted alternative checks. Do not fabricate screenshots, browser checks, or test success.
- See `references/quality-assurance.md`.

### 8. Commit and publish, if authorized
- Confirm the exact target branch and permitted files from live instructions.
- Review diffs and status; ensure unrelated changes are excluded.
- Commit only authorized deliverables with a clear message.
- Push only through the prescribed workflow and only if explicitly authorized by the live instructions.
- Verify remote state after publishing; a local commit or attempted push is not proof of remote success.
- See `references/git-safety.md`.

### 9. Report
Return a concise standardized report using `references/reporting.md`.
Include the slot, assignment identity, business, branch, source commit/revision, status, deliverables, QA, publication verification, and any blocker.
Do not claim success unless the evidence supports it.

## Autonomous execution and reliability
- Scheduled runs are pre-authorized to complete routine read-only GitHub inspection, scoped file creation, commit, and push when connected integration permissions and live instructions authorize them. Do not request routine confirmations.
- If access is disconnected, credentials fail, or the platform blocks a required action for approval, stop and report the specific blocker; don't repeatedly prompt.
- Keep operations bounded. Avoid indefinite waits. On a required operation stall/failure, stop with last verified state. Use at most one safe retry after refreshing remote state and revalidating the exact assignment. Never force-push.
- Always return a final outcome: completed and remotely verified, already completed with exact evidence, blocked with reason, or partial with remaining steps.

## Status values
- `COMPLETED`: deliverable created, required QA passed or explicitly accepted limitations, and required publication verified.
- `ALREADY_COMPLETED`: exact live assignment already completed and evidence verified; no duplicate work performed.
- `BLOCKED`: cannot safely proceed due to missing, contradictory, inaccessible, or failed prerequisite.
- `PARTIAL`: meaningful authorized work completed, but a required step remains incomplete. Clearly state what remains.

## Explicit return contract
- Save complete revised HTML only at `todo-today/revised/index.html`.
- Save assignment metadata only at `todo-today/revised/metadata.json`.
- Verify exact metadata identity values.
- Do not edit ledgers, other slots, other assignments, `main`, unrelated branches, publishing/deployment state, or promote candidates.
- Verify the only modified paths are the two authorized return files.
- After push, verify remote branch head/commit and both files exist. Attempted push/local commit is not proof of remote publication.

## References
- `references/orchestration-handoff.md`
- `references/assignment-validation.md`
- `references/redesign-brief.md`
- `references/visual-effects.md`
- `references/quality-assurance.md`
- `references/git-safety.md`
- `references/reporting.md`