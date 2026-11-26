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
pass; follow the skill's harness recovery steps and inspect returned values
before classifying a smoke-test failure. Do not complete the
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

## Production result publication

For a production job, use the returned `job_id`, `claim_epoch`, and `worker_id`
only in the current scheduled invocation. The private job record and successful
fast-forward Git push hold the claim state; no token or local checkpoint is
used. Treat `worker_id` as an audit label, not a credential. Start
`queue_manager.py heartbeat-loop --job-id <job-id> --claim-epoch <epoch> --worker-id <invocation-id>`
while the skill is working. It renews the lease every 15 minutes by default. If
the container ends or the claim response is lost, do not recover an old claim
from Git. Let the lease expire; the next invocation must recover the expired
claim and claim a new epoch. The epoch fences writes from stale invocations.
After the skill has a `PASS` result, run
`chatgpt_worker/scripts/publish_result.py` with the skill output folder, using
`--job-id`, `--claim-epoch`, and `--worker-id` from the current invocation. The
skill must write the exact `job_id` and integer `claim_epoch` it received into
`evidence/native-qa.json`. The publisher rejects missing or mismatched values
before accessing the private store. The publisher also requires
`native_qa_status: PASS`,
three candidate records identified as Forty, Landed, and Story (a mapping keyed
by `forty`/`landed`/`story` or an array with a `template`, `slot`, or `slot_id`
field), and matching filenames, byte counts, and SHA-256 values. It accepts the
skill's detailed `candidate_results` array when `candidates` is absent, but
requires `finished_checks: true`, PASS status for all three candidates, empty
static error and failure lists, passing desktop/tablet/mobile viewport checks,
and passing exact-byte/static, browser interaction, and rendered-credit checks.
Each entry may call its path `filename`, `final_path`, or `path`, and its byte
count `bytes` or `byte_count`. If candidate entries include `qa_status` or
`status`, each must be `PASS`. The publisher rereads the
exact candidate bytes, commits all files in `evidence/` and the three HTML files
under `results/<result_slug>/run-<job-id>-epoch-<claim-epoch>/` on the private
`chatgpt-worker` branch, and then completes the queue job. The current worker ID, epoch, and lease are checked against the branch head before artifacts are written. If the publisher loses its response after completion, rerun it in the same invocation with the same output and epoch; it confirms the recorded digests and returns without rewriting the job. A new invocation without the original claim context must wait for expiry and use a new epoch.

The persisted result record is built from exact bytes:

```json
{
  "run_path": "results/<result_slug>/<run-id>",
  "qa_status": "PASS",
  "artifact_commit": "<40-character private branch commit>",
  "qa_evidence": {"filename": "evidence/native-qa.json", "bytes": 1, "sha256": "<64 lowercase hex>"},
  "candidates": {
    "forty": {"filename": "candidate-forty.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"},
    "landed": {"filename": "candidate-landed.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"},
    "story": {"filename": "candidate-story.html", "bytes": 1, "sha256": "<64 lowercase hex>", "qa_status": "PASS"}
  }
}
```

Replace the illustrative placeholders only with measured values. The publisher
performs this operation automatically. Never put customer rows, HTML, or
screenshots in public logs or the public repository.

## Existing content-post handoff

After publication completes, run
`chatgpt_worker/scripts/handoff_content_post.py --job-id <job-id>`. It reserves
one stable numeric-numeric batch ID in the private job before pushing any slot.
It writes the established paths and metadata shape on the three private
`content-post` slot branches, preserving immutable queue snapshots. Only after
all three branches are verified does it change the generation job's handoff
state from `pending` to `handed_off`. It does not write the content-post ledger,
assign a worker, or change the existing orchestrator or repair workflow.
For downstream compatibility, `site_slug` is derived from the website host by
the same rule used by the legacy publisher; it is not copied from the private
results folder's `result_slug`.
