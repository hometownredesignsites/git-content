# ChatGPT worker queue core

This branch contains the queue state implementation and the worker-to-skill handoff contract. The private production job contract is in `git-content-private:chatgpt-worker` at `private_automation/queue/generation/schemas/job.schema.json`. The test-only input contract is in `private_automation/queue/generation/simulation/job.schema.json` and is not imported by queue reconciliation.

## Reconcile locally

The reconciler imports only source records explicitly marked `provider: "chatgpt-worker"`. Legacy `chatgpt` and other provider jobs are ignored. Existing generation job IDs are preserved, so repeated scans do not create duplicates.

```powershell
python chatgpt_worker/scripts/reconcile_queue.py `
  --source-jobs <private-main>/private_automation/queue/jobs `
  --generation-jobs <private-chatgpt-worker>/private_automation/queue/generation/jobs
```

The command is dry-run by default. Add `--apply` to write new per-job JSON records into a local private checkout. It does not push, schedule Actions, connect external workers, or touch `content-post`.

## State transitions

`queue.py` provides idempotent import, claim, heartbeat, expiry/requeue, and completion functions. A 60-minute lease can be renewed while active. Expiry preserves the job and attempt history, clears the old claim, and allows a new claim with a higher `claim_epoch`. Claim tokens are stored as SHA-256 digests. Completion requires a `PASS` record for exactly the three named candidates with byte counts and SHA-256 values.

`git_store.py` adds the Git-backed persistence adapter. Each update uses a fresh clone of the private branch, changes only the target job record, and pushes a fast-forward commit. Git rejects a stale competing push; the store rereads the newest branch and recomputes the transition with bounded retries. A rejected push with no remote-head change is treated as an operational error. Credentials are supplied by the Git credential helper or runner environment, not stored in job data. Workers may treat a claim as owned only after `update_job()` returns successfully.

## Manual coordinator

`queue_manager.py` connects the private store to manual operations. Set `GIT_CONTENT_PRIVATE_REMOTE` if the remote URL differs from the default, and authenticate with the configured Git credential helper.

```powershell
python chatgpt_worker/scripts/queue_manager.py reconcile-intake
python chatgpt_worker/scripts/queue_manager.py list
python chatgpt_worker/scripts/queue_manager.py claim-next --worker-id operator-1
```

`claim-next` returns the job and one-time claim token only after the private branch commit succeeds. Treat its output as private because it includes the customer row and claim token. Store the token securely in `CHATGPT_WORKER_CLAIM_TOKEN` for later transitions; do not place it in shell history or public logs.

```powershell
$env:CHATGPT_WORKER_CLAIM_TOKEN = "CLAIM_TOKEN_FROM_OUTPUT"
python chatgpt_worker/scripts/queue_manager.py heartbeat --job-id JOB_UUID --claim-epoch EPOCH_NUMBER
python chatgpt_worker/scripts/queue_manager.py complete --job-id JOB_UUID --claim-epoch EPOCH_NUMBER --result-json result-record.json
python chatgpt_worker/scripts/queue_manager.py recover-expired
```

Completion reads the three candidate files from `results/<site-slug>/...` on the private branch and verifies exact byte counts and SHA-256 values before recording the result. Intake reconciliation, leases, claim tokens, and candidate artifacts remain in the private repository. These are manual operations; no hourly Action or external worker endpoint is enabled yet.

## Generator handoff and safe simulation

[`GENERATION_WORKER_CONTRACT.md`](GENERATION_WORKER_CONTRACT.md) maps a claimed private job to the `website-poc-generator` skill and defines the exact deliverable and QA record expected by queue completion. A simulation uses the private simulation schema, a reachable non-customer business URL, and a local-only output directory. It must not reconcile or claim the production queue, dispatch the legacy Action, write candidate files to either repository, or modify `content-post`. Require `native_qa_status: PASS` and verify the three final file digests before considering the generator simulation successful.

The simulation checks skill execution and QA only. It does not validate a Git-backed production artifact push or the not-yet-implemented High-site poller.

Run the local tests with:

```powershell
python -m unittest discover -s chatgpt_worker/tests -v
```
