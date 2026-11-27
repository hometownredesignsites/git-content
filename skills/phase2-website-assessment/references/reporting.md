# Standardized Report

Provide a concise report with:
- Outcome status: `COMPLETED`, `ALREADY_COMPLETED`, `BLOCKED`, or `PARTIAL`.
- Assigned slot and exact assignment identity (`task_id`, `batch_id`, `site_slug`, `slot`, `branch`, and source path where applicable).
- Business/source URL and source revision/commit.
- Deliverables and exact paths.
- QA evidence: each item `PASS`, `FAIL`, `NOT CHECKED`, or `FALLBACK`, with brief evidence or limitation; distinguish static and browser/runtime checks.
- Benchmark outcome and verified identity/commit, or reason unavailable.
- Publication/remote verification and commit SHA, or remaining blocker.

Never state successful completion or QA without evidence. Clearly separate actions performed from unverified or proposed work.
