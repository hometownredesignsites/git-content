# Orchestration, repositories, and slot handoffs

## Repository roles
- `hometownredesignsites/git-content` (`chatgpt`): public generation workflow, validation, staging, hourly orchestrator. Public logs must not expose customer identifiers or HTML.
- `hometownredesignsites/git-content-private`: private customer/job inputs and generation evidence.
- `hometownredesignsites/content-post` (private): slot branches, live assignments, worker returns, authoritative `automation/slot-ledger.json` on `main`, promotion and publishing.
The worker revises only its slot assignment. It does not select a company, edit the ledger, promote, or deploy.

## Handoff shape
- Each slot branch (`chatgpt-slot1`, `chatgpt-slot2`, `chatgpt-slot3`) has a live root `todo-today/assignment.json` and `todo-today/index.html`.
- The return consists of `todo-today/revised/index.html` and `todo-today/revised/metadata.json`.
- Metadata must copy exact `task_id`, `site_slug`, `batch_id`, `slot`, `branch` from the live assignment.
- The orchestrator validates/archives accepted returns and reconciles promotion progress. Promotion/publishing is downstream and must not be triggered by the worker.

## Assignment schedule and same-day benchmark
The documented orchestrator runs hourly at minute 17 UTC, and at most one new batch is assigned per Eastern calendar day. Workers should run after the assignment cycle (documented recommendation: after 12:17 UTC; verify live schedule before deployment). Slots 1-3 are iterations for the same business in a given daily batch; the customer/business changes across batches.

A benchmark from another slot is eligible only after validating its assignment identifiers against the same current batch/task business. Prefer a completed revision from the same-day batch, and inspect read-only. If the match cannot be established, do not benchmark; report unavailable and continue with premium design quality standards. Never use prior-day work as the benchmark or source facts.

## README/worker-guide caveat
The `content-post` README documents manual promotion instructions in one section, while the current `git-content` orchestration README describes automatic promotion after a same-batch set is complete. This skill follows the worker's strict scope: never promote or publish. For operational scheduling or promotion questions, verify the latest workflow and orchestrator instructions rather than assuming the README sections are fully synchronized.

## Conflict retry policy
The shared worker guide describes up to five push attempts after re-fetching and confirming exact task identity. The current Slot 2 automation contains a stricter authoritative reliability rule limiting retries to one safe retry after refreshing remote state and revalidating. Invocation-specific rules take precedence; for Slot 2, do not exceed one safe retry.