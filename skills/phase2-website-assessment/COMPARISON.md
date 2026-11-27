# Feature-parity comparison: current Slot 2 automation, shared worker guide, and README

## Source snapshots retrieved for this review
- `content-post/README.md` branch `chatgpt-slot2`, blob SHA `3e7d7949c319c4d73d05f09fd6ff321cd39a826b`
- `git-content/chatgpt_automation/worker-prompts/slot-worker.md` branch `chatgpt`, blob SHA `56749ba5b03ba5165006549138213b6d37f998ee`
- `git-content/chatgpt_automation/README.md` branch `chatgpt`, blob SHA `61c9b563abeb9433d7b4f60961f294eb63645a17`
- The separately named `worker-guide.md` at the Slot 2 root was not found; shared worker instructions are the `slot-worker.md` file above.

## Feature coverage after update
| Feature | Current Slot 2 automation / shared guide | Local skill |
|---|---|---|
| Exact slot/branch identity | Mandatory | Included |
| Live root assignment and input HTML | Mandatory | Included |
| Metadata fields copied exact | task_id, site_slug, batch_id, slot, branch; task identity also captures source_path | Included |
| Return paths exactly two | revised/index.html + metadata.json | Included |
| Strict no-other-slot/ledger/main changes | Mandatory | Included |
| Stale assignment continuity | Active valid assignment persists; no date-based stale inference | Included |
| Idempotency exact identity | Exact five identity values plus task/source validation; Slot 2 automation requires completion evidence in metadata+HTML or two-path prior commit | Included, but deployment validation should preserve the exact Slot 2 evidence predicate |
| Same-day same-business benchmarking | Same-batch verified only; read-only; prior day disallowed | Included |
| Original content/form preservation | Preserve sections, facts, contact, links, forms, fields/options, image sources/order | Included |
| Full-bleed hero preservation | Do not split or shrink a valid full-bleed hero | Included |
| POC form disclosure | Disconnected form disclosed; no data transmission or storage | Included |
| Premium quality and motion | Purposeful design, progressive enhancement, reduced motion, visible focus | Included |
| Required Slot 2 visual effects | Hero presentation, CTA lift/scale, nav transitions, scroll reveals, card/image hover | Included |
| Static QA | Detailed checklist including IDs, anchors, mobile nav, reduced motion, image, forms, placeholders, punctuation | Included |
| Browser QA disclosure | Browser testing only when available; don't claim if not run | Included |
| Push safety | No force-push, revalidate task before retry | Included |
| Retry limit | Shared prompt: up to 5; Slot 2 automation authoritative override: max 1 safe retry | Documented as invocation-specific; Slot 2 cap is one |
| Autonomous actions | Slot 2 automation explicitly authorizes routine scoped GitHub work without prompts | Included in prior draft |
| Never promote/deploy | Worker scope prohibits | Included |

## Discrepancies and cautions
1. `content-post` README contains manual promotion steps while the orchestration README describes automated same-batch promotion. Worker scope is unambiguous: do not promote or publish.
2. Shared worker prompt permits up to five push attempts; current Slot 2 automation explicitly limits retries to one safe retry. The stricter Slot 2 rule wins for Slot 2 invocations.
3. The main draft previously lacked source preservation, exact forms/image constraints, same-batch benchmark logic, retry conflict resolution, and architecture/handoff. These have now been added.
4. The local skill remains a draft. Full parity against Slot 1 and Slot 3 prompts has not yet been established, and simulated slot invocation testing remains to be done.

## Overall assessment
Local skill now covers the current Slot 2 workflow and the retrieved shared worker/README requirements at the documented level. Treat it as **near-parity draft**, not deployment-approved: verify the exact live Slot 2 completion-evidence rule during slot simulation and compare Slot 1 and Slot 3 automation prompts before replacing their triggers.


## Four refinements requested after Slot 2 comparison (implemented in local draft)
1. **Benchmark procedure:** expanded into a concrete read-only fetch and identity-validation procedure. Fetch the current benchmark branch, validate its assignment and return metadata against current task/batch/site and expected slot/branch, confirm revised HTML and remote completion, inspect actual HTML, document comparison evidence, and explicitly fall back when unavailable.
2. **QA evidence recording:** mandatory per-item status vocabulary `PASS`, `FAIL`, `NOT CHECKED`, or `FALLBACK`, with evidence or reason, and a run-report QA evidence table.
3. **Browser QA scope:** expanded checklist covering desktop/mobile viewport dimensions, overflow, console/runtime errors, images, hero crop, mobile menu state/behavior, links/CTAs, safe form behavior, keyboard/focus, reduced motion, scroll reveals, card/image interaction, and intermediate widths.
4. **Retry precedence:** clarified invocation-specific retry limits override shared guide allowances; Slot 2's cap remains one safe retry, and one safe retry is the conservative default when no cap is provided.

These edits update the local skill draft only. Slot automations were not changed, and the draft has not been published or migrated.