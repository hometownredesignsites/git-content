# ChatGPT content-generation dashboard

The public `git-content` Actions workflow builds this private report on the `chatgpt` branch of `git-content-private` at `observability/chatgpt/index.html`. It uses the existing `PRIVATE_RESULTS_TOKEN` secret for the matching private repository only. The workflow does not use `LEAD_OPERATIONS_TOKEN`.

The workflow refreshes hourly, on manual dispatch, and after ChatGPT private queue/high-site runs complete. The output includes a self-contained HTML report, a JSON snapshot, and CSV exports for content batches and jobs.

Batch manifests, private job records, and per-site result status files provide queue state, attempts, pass counts, and available failure classifications. Public Actions run metadata supplies run links and durations. A site reaches the content completion gate after three passing candidates; an Actions success alone does not count as a completed site.

Download `observability/chatgpt/index.html` from the private content branch and open it locally. GitHub's file viewer displays HTML source instead of running the report as a private website.
