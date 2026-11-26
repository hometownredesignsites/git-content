# ChatGPT worker queue core

This branch contains the queue state implementation and the worker-to-skill handoff contract. The private production job contract is in `git-content-private:chatgpt-worker` at `private_automation/queue/generation/schemas/job.schema.json`. The test-only input contract is in `private_automation/queue/generation/simulation/job.schema.json` and is not imported by queue reconciliation.

## Reconcile locally

The reconciler imports only source records explicitly marked `provider: "chatgpt-worker"`. Legacy `chatgpt` and other provider jobs are ignored. Existing generation job IDs are preserved, so repeated scans do not create duplicates.

```sh
python chatgpt_worker/scripts/reconcile_queue.py `
  --source-jobs <private-main>/private_automation/queue/jobs `
  --generation-jobs <private-chatgpt-worker>/private_automation/queue/generation/jobs
```

The command is dry-run by default. Add `--apply` to write new per-job JSON records into a local private checkout. It does not push, schedule Actions, connect external workers, or touch `content-post`.

## State transitions

`queue.py` provides idempotent import, claim, heartbeat, expiry/requeue, and completion functions. A 60-minute lease can be renewed while active. Expiry preserves the job and attempt history, clears the old claim, and allows a new claim with a higher `claim_epoch`. New claims contain no token material. Completion requires a `PASS` record for exactly the three named candidates with byte counts and SHA-256 values.

`git_store.py` adds the Git-backed persistence adapter. Each update uses a fresh clone of the private branch, changes only the target job record, and pushes a fast-forward commit. Git rejects a stale competing push; the store rereads the newest branch and recomputes the transition with bounded retries. A rejected push with no remote-head change is treated as an operational error. Credentials are supplied by the Git credential helper or runner environment, not stored in job data. Workers may treat a claim as owned only after `update_job()` returns successfully.

## Manual coordinator

`queue_manager.py` connects the private store to manual operations. Set `GIT_CONTENT_PRIVATE_REMOTE` if the remote URL differs from the default, and authenticate with the configured Git credential helper.

```sh
python chatgpt_worker/scripts/queue_manager.py reconcile-intake
python chatgpt_worker/scripts/queue_manager.py list
python chatgpt_worker/scripts/queue_manager.py claim-next --worker-id operator-1
```

`claim-next` writes the claim to the private branch using a fast-forward compare-and-swap push and returns the job with its `claim_epoch`, `worker_id`, and lease. The successful Git push is the claim point. `worker_id` is an audit label and mismatch guard, not a secret or authentication factor. Use a unique ID for each scheduled invocation and retain the job ID, epoch, and worker ID in that invocation's active context. Do not write them to Git as a separate checkpoint. If the container or claim response is lost, do not guess or resume the claim: leave it for lease expiry, then run `recover-expired` and claim the next epoch. The returned job contains customer details and must be handled as private data.

```sh
python chatgpt_worker/scripts/queue_manager.py heartbeat --job-id JOB_UUID --claim-epoch EPOCH_NUMBER --worker-id INVOCATION_ID
python chatgpt_worker/scripts/queue_manager.py heartbeat-loop --job-id JOB_UUID --claim-epoch EPOCH_NUMBER --worker-id INVOCATION_ID
python chatgpt_worker/scripts/queue_manager.py complete --job-id JOB_UUID --claim-epoch EPOCH_NUMBER --worker-id INVOCATION_ID --result-json result-record.json
python chatgpt_worker/scripts/queue_manager.py recover-expired
```

`heartbeat-loop` renews the lease every 15 minutes by default; stop it when the
work completes or is abandoned. It requires the job ID, epoch, and worker ID
from the current invocation. If those values are unavailable after a restart,
wait for lease expiry and claim a new epoch.

Completion reads the three candidate files from `results/<site-slug>/...` on the private branch and verifies exact byte counts and SHA-256 values before recording the result. `scripts/publish_result.py` is the worker-side publisher: it accepts only a `native_qa_status: PASS` package whose `job_id` and `claim_epoch` match the current claim and whose three candidate digests match, commits candidate HTML and all evidence to private `chatgpt-worker`, then completes the fenced job. It never writes artifacts to public `git-content`.

After completion, `scripts/handoff_content_post.py --job-id JOB_UUID` reserves a stable numeric-numeric content-post batch ID in the private job, stages the three HTML files and matching metadata on the existing private `content-post` branches `chatgpt-slot1`, `chatgpt-slot2`, and `chatgpt-slot3`, then marks the private handoff `handed_off`. The adapter does not write `content-post/main` or its ledger. The existing hourly orchestrator discovers the complete immutable queue snapshots and continues to assign the slots and update its ledger. If a push stops part-way through, rerunning the handoff command reuses the reserved batch ID and verifies already-pushed snapshots before continuing. Git credentials for private `git-content-private` and `content-post` must be available through the worker's Git credential helper.

```sh
python chatgpt_worker/scripts/publish_result.py --job-id JOB_UUID --claim-epoch EPOCH_NUMBER --worker-id INVOCATION_ID --skill-output <skill-output-folder>
python chatgpt_worker/scripts/handoff_content_post.py --job-id JOB_UUID
```

The content-post `site_slug` uses the existing host-based rule from the previous publisher, while the private result path uses the queue's `result_slug`.

## Generator handoff and safe simulation

[`GENERATION_WORKER_CONTRACT.md`](GENERATION_WORKER_CONTRACT.md) maps a claimed private job to the `website-poc-generator` skill and defines the exact deliverable and QA record expected by queue completion. A simulation uses the private simulation schema, a reachable non-customer business URL, and a local-only output directory. It must not reconcile or claim the production queue, dispatch the legacy Action, write candidate files to either repository, or modify `content-post`. Require `native_qa_status: PASS` and verify the three final file digests before considering the generator simulation successful.

The simulation checks skill execution and QA only. It does not validate a Git-backed production artifact push, private content-post handoff, or the High-site poller.

## High-site intake poller

The manual-only workflow [`.github/workflows/chatgpt-worker-high-poll.yml`](../.github/workflows/chatgpt-worker-high-poll.yml) reads completed High leads from the lead-operations `git-chatgpt` branch and applies the confidence, delivery-ready exception, score-ordering, and worker-queue duplicate rules. Existing legacy previews and candidate runs do not affect eligibility: this queue represents the initial candidate-generation phase. It checks the `chatgpt-worker` source and generation queues for duplicates, then writes source job records only to `git-content-private:chatgpt-worker`.

The default-branch registration workflow checks out this branch's poller code and runs it with `max_sites=1` for an initial controlled intake. The poller workflow then calls the Git-backed `reconcile-intake` operation, so a successful run leaves the new job immediately claimable in the generation queue. If intake persisted but reconciliation failed, rerunning safely reconciles the source record without creating another job. The workflow has no schedule and does not invoke the legacy candidate generator.

Run the local tests with:

```sh
python -m unittest discover -s chatgpt_worker/tests -v
```
