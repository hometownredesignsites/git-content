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

The production ChatGPT scheduled worker publishes with its GitHub integration,
not the local Git-clone publisher CLI. Before claiming, confirm the integration
can read and write `git-content-private:chatgpt-worker`, read files back from
that branch, and make conflict-checked branch updates. Confirm the skill output
directory remains accessible to the worker after QA. Do not acquire a lease if
these prerequisites are unavailable.

Use the returned `job_id`, `claim_epoch`, and `worker_id` only in the current
scheduled invocation. The private job record is the durable claim state; no
token or local checkpoint is used. Treat `worker_id` as an audit label, not a
credential. Start lease heartbeats before invoking the skill and renew at least
every 15 minutes through a fenced update using the GitHub integration. Each
heartbeat must re-read the latest job and confirm the same worker ID and epoch
and an unexpired lease; write with the latest file/branch version so a
concurrent update is detected. Do not keep working after a heartbeat conflict
or expired lease. If the container or claim response is lost, do not recover
an old claim from Git. Let the lease expire; the next invocation must recover
the expired claim and claim a new epoch. The epoch fences writes from stale
invocations.

The skill writes one run-specific output directory. Pass the exact
`job_id`, integer `claim_epoch`, source row, and output directory into the
skill; do not rebuild or edit candidate HTML after QA. The skill must write
the exact `job_id` and `claim_epoch` into `evidence/native-qa.json`. Publish
only if `native_qa_status` is `PASS`, the source host matches the claimed job,
and all candidate digests match the saved bytes. The report must contain three
candidate records identified as Forty, Landed, and Story, with
`finished_checks: true`, passing static checks, empty static error and failure
lists, desktop/tablet/mobile viewport results, and the required exact-byte,
browser-interaction, and rendered-credit check names. See the skill's
publisher-compatible evidence contract for the exact JSON shape.

Using the GitHub integration, re-read the latest job immediately before
publishing and verify its status, worker ID, epoch, and unexpired lease. Write
the three HTML files and all evidence under
`results/<result_slug>/run-<job-id>-epoch-<claim-epoch>/` on the private
`chatgpt-worker` branch without changing their bytes. Read the remote files
back and verify their byte counts and SHA-256 values. Then conditionally update
the job JSON with the artifact commit, result digests, and completed status,
using the latest job-file or branch version so concurrent claim changes fail
closed. Prefer one multi-file commit against the expected branch head. If the
integration only supports per-file commits, use the epoch-specific path, make
each write idempotent, and update the job record last. On a conflict, re-read
the latest branch and retry only if the same claim is still current. Never
force-push, mark the job completed after a partial upload, or replace a result
from another epoch. The existing `publish_result.py` remains a local Git
publisher/validator; it is not the production scheduled-runner write path.

The persisted result record is built from exact bytes:

```json
{
  "run_path": "results/<result_slug>/run-<job-id>-epoch-<claim-epoch>",
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

After publication completes, hand off the candidates to the three private
`content-post` slot branches using the GitHub integration or a separately
available Git-backed adapter. The current
`chatgpt_worker/scripts/handoff_content_post.py` uses local Git subprocesses;
it cannot be assumed to work in a scheduled runner that exposes only the
GitHub integration. Reserve one stable numeric-numeric batch ID in the private
job before writing slots, preserve the established paths and metadata, and
verify all three immutable queue snapshots before marking the generation job
`handed_off`. This handoff does not write the content-post ledger, assign a
worker, or change the existing orchestrator or repair workflow. For
downstream compatibility, `site_slug` is derived from the website host by the
same rule used by the legacy publisher; it is not copied from the private
results folder's `result_slug`.
