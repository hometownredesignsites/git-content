# ChatGPT worker queue core

This branch contains the first queue-state implementation. The private job contract is in `git-content-private:chatgpt-worker` at `private_automation/queue/generation/schemas/job.schema.json`.

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

The hourly Action and the external worker claim endpoint are intentionally not part of this milestone. The adapter assumes the caller can authenticate to the private repository and pass its remote URL; it does not schedule work or reveal customer data to public logs.

Run the local tests with:

```powershell
python -m unittest discover -s chatgpt_worker/tests -v
```
