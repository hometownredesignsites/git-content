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

These are pure state transitions, not a distributed lock by themselves. Every mutation in a live coordinator must use compare-and-swap against the current private branch head: read the remote revision, compute the update, commit only the job record, and push only if that revision is still current. On a conflict, reread and retry the transition; never treat an unpushed local claim as ownership. The remote Git persistence adapter and hourly Action are intentionally not part of this milestone.

Run the local tests with:

```powershell
python -m unittest discover -s chatgpt_worker/tests -v
```
