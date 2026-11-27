# Git Safety, Scope, Commit, Push, and Recovery

## Authorized return contract
For the current content-post workflow, only these paths may be changed and committed:
- `todo-today/revised/index.html`
- `todo-today/revised/metadata.json`

Metadata must contain exact live assignment values: `task_id`, `site_slug`, `batch_id`, `slot`, and `branch`. No ledger, other slot, other assignment, `main`, unrelated branch, publishing/deployment state, or candidate promotion may be modified.

## Authorization
The current scheduled workflow is pre-authorized for routine read-only inspection, creation of these two return files, commit, and push through connected GitHub access, provided integration access is working and live instructions permit it. Do not ask for routine approvals. If disconnected, authentication fails, capability is missing, or platform requires approval, stop and report the precise issue. Do not request credentials or retry user prompts endlessly.

## Before commit
- Fetch latest target branch; confirm repository, branch, assignment identity and allowed files.
- Review status and diff.
- Verify exact metadata values and source/task consistency.
- Verify only the two authorized paths are modified.
- Stage explicit paths, not broad `git add .`.
- Do not overwrite unrelated or other-agent work.

## Commit and push
Commit and push only the two authorized return paths to the slot's exact branch when authorized. No force-push, history rewrite, broad cleanup, branch switching to another slot, ledger edits, promotion, or publishing.

## Rejected push / safe retry and invocation precedence
If push is rejected:
1. Fetch latest remote.
2. Re-read assignment and revalidate the same exact identity.
3. Inspect new remote changes and safely reapply only the authorized two-file return if assignment remains unchanged and scope is clear.
4. Retry only within the retry limit explicitly set by the invoking automation/task. The shared worker guide's allowance of up to five attempts is a ceiling, not a default; stricter slot/task limits override it. For the current Slot 2 automation, the authoritative limit is **at most one safe retry** after refresh and revalidation.
5. If no invocation-specific retry cap is provided, use at most one safe retry as the conservative default. Never force-push or blindly overwrite.
6. If identity changes, conflict remains, or the permitted retry limit is exhausted, stop and report.

## Verify publication
After push, verify remote branch contains commit and both exact paths. Local commit or push attempt is not success. Report remote commit SHA, paths, and verification evidence.

## Slot worker return contract
For the current Slot 2 workflow, only these two paths may be changed and committed:
- `todo-today/revised/index.html`
- `todo-today/revised/metadata.json`

Metadata must copy exact live assignment values: `task_id`, `site_slug`, `batch_id`, `slot`, `branch`. Do not edit assignment source, ledger, draft, another slot, promotion, or publishing state. Confirm only those two paths are changed before commit, then verify remote commit and both files after push.

## Push-rejection handling
Never force-push. Fetch the latest branch, revalidate the same exact assignment identity, and reapply only the two authorized return files. Retry count is governed by the invoking automation's specific policy: the shared worker guide allows up to five attempts, but the current Slot 2 automation has an authoritative stricter cap of one safe retry. Follow the stricter invocation-specific limit. If identity changes or the retry cap is exhausted, stop and report the verified blocker.