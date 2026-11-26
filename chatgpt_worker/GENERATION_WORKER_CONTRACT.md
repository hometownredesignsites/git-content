# Generation worker handoff contract

This contract connects one claimed `chatgpt-worker` queue job to the
`website-poc-generator` skill. A single worker handles all three candidates for
one customer. This flow creates local proof-of-concept files; it does not deploy
a site or modify `content-post`.

## Map a claimed job to the skill

The private queue claim is authoritative. Use the `job.row` fields as follows:

| Queue field | Skill input |
| --- | --- |
| `website` | Required source website URL |
| `business` | Optional business name when the site identity is unclear |
| `category` | Unverified context only; verify any facts against the source |
| `location` | Unverified context only; use as a fact only if confirmed by the site |

Run the installed `website-poc-generator` skill in the active ChatGPT session.
Do not translate this contract into GitHub Actions or call the legacy
`chatgpt` generator. The skill must produce exactly these independent files:

- `candidate-forty.html`
- `candidate-landed.html`
- `candidate-story.html`
- `evidence/native-qa.json`

Use the skill's exact-byte static and Chromium QA requirements. A candidate is
eligible only when its exact saved bytes pass the skill's required checks. A
transient runtime interruption or harness error is not a candidate failure or
pass; follow the skill's checkpoint and recovery rules. Do not complete the
queue job when the aggregate native QA status is `PARTIAL`, `FAIL`, or
`BLOCKED`.

## Simulation mode

Simulation jobs use the private contract at
`git-content-private:chatgpt-worker/private_automation/queue/generation/simulation/job.schema.json`.
They are local-only inputs, never placed in
`private_automation/queue/jobs/`, and are never imported by queue reconciliation.
Do not call `claim-next`, `complete`, the High-site poller, the legacy Action, or
any `content-post` operation for a simulation. Keep generated files under the
task's output directory and report the QA evidence in the task; do not push
simulation artifacts to either repository.

The simulation proves the skill invocation and QA contract only. Existing
Git-backed queue tests cover the claim and persistence mechanics. It does not
prove the GitHub poller or the future production artifact push.

## Production result handoff (not enabled by this simulation)

For a later production job, preserve the claimed `job_id`, `claim_epoch`, and
one-time claim token privately. After the skill has a `PASS` result, store its
three final HTML files and evidence beneath
`results/<result_slug>/<run-id>/` on the private `chatgpt-worker` branch. Commit
those files first. Build the queue result record from the exact committed bytes:

```json
{
  "run_path": "results/<result_slug>/<run-id>",
  "qa_status": "PASS",
  "candidates": {
    "forty": {"filename": "candidate-forty.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"},
    "landed": {"filename": "candidate-landed.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"},
    "story": {"filename": "candidate-story.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"}
  }
}
```

Replace every placeholder with values measured from the saved files. Then run
the private-branch `queue_manager.py complete` command using the current claim
token and epoch. The Git-backed store verifies each file's byte count and
SHA-256 before it records completion. Never put the claim token, customer row,
HTML, or screenshots in public logs or the public repository.
