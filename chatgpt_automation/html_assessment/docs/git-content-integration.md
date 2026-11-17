# Git Content HTML Assessment workflow

The public `chatgpt` branch runs this project from `.github/workflows/html-assessment.yml` using NVIDIA NIM. Start the workflow manually once per candidate with an opaque job ID from Git Content's existing private queue, the private source run ID, and a private source candidate ID. Wait for the current workflow to finish before starting another candidate for the same job. The source run ID is required because candidate IDs are reused across runs. The workflow reads the private job record for `business`, `category`, and optional `location`, then uses the selected candidate's private `files/inlined/index.html` as the actual source HTML. The existing `result-slugs.json` maps the configured website to its private result folder. The selected candidate's `debug/inputs.json` supplies the page URL used as the browser asset base and must match the target website's host. The workflow does not fetch live page HTML.

Each workflow attempt updates the selected candidate in place and writes distinct evidence under its `debug/assessment-runs/run-<assessment-workflow-id>-<attempt>/` directory. The existing source candidate remains in the same private results branch and retains its original location:

```text
results/<configured-site-slug>/run-<original-workflow-id>-<original-attempt>/candidates/<source-candidate-id>/
```

The first assessment saves the exact selected source bytes as `files/inlined/index-old.html`. The revised page replaces `files/inlined/index.html` (and its compatibility copy at `files/index.html`); later workflow attempts keep the original `index-old.html` and save each attempt's source, screenshots, manifest, reports, and before/after diffs in its own evidence archive. Passing deterministic repository QA completes approval; model visual QA is advisory. A failed or unmeasurable repository check leaves the candidate unsuccessful for review. No canonical customer HTML is modified.

After assessment, `run_html_assessment_qa.py` invokes Git Content's existing `browser_qa.py` and `check_website.py`. The model's final pass does not set `automated_success` or `final_success`; both fields reflect repository QA only. When repository QA passes, the assessment workflow rebuilds `successful-passes/` and dispatches the unchanged `content-post` publisher once at least three candidates in the latest run pass. Existing review templates remain available as optional audit aids. If the existing HTML5 UP-specific QA cannot establish that a page meets a criterion, the candidate stays unsuccessful and reviewable.

The public ChatGPT generation workflow does not dispatch `content-post` before assessment. After three or more candidates in the latest successful run pass deterministic repository QA, the public assessment workflow refreshes `successful-passes/` and sends the existing `chatgpt_content_ready` event to `content-post`. Configure `CONTENT_POST_DISPATCH_TOKEN` in the public Git Content repository; without it, maintainers can run the existing publisher manually.

## Credentials and isolation

- The NVIDIA API key is read only from the public Git Content repository's `NVIDIA_API_KEY` Actions secret.
- `NVIDIA_API_KEY` is present only in the NVIDIA inference step environment. Chromium is launched with credential-related environment variables removed, and provider error details redact the key.
- Customer target JSON is written to the runner's temporary directory. Source and output HTML, screenshots, prompts, logs, and reports are saved only to the private results branch. The workflow uploads no public Actions artifacts.
- The original candidate path is intentionally revised in place for the existing publisher. Each assessment attempt has its own evidence directory, and assessment never changes the private run-level completion status or canonical customer files.
