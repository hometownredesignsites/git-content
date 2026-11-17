# Git Content HTML Assessment workflow

The public `chatgpt` branch runs this project from `.github/workflows/html-assessment.yml`. Start the workflow manually once per candidate with an opaque job ID from Git Content's existing private queue, the private source run ID, a private source candidate ID, and a provider choice. Wait for the current workflow to finish before starting another candidate for the same job. The source run ID is required because candidate IDs are reused across runs. The workflow reads the private job record for `business`, `category`, and optional `location`, then uses the selected candidate's private `files/inlined/index.html` as the actual source HTML. The existing `result-slugs.json` maps the configured website to its private result folder. The selected candidate's `debug/inputs.json` supplies the page URL used as the browser asset base and must match the target website's host. The workflow does not fetch live page HTML.

Each workflow attempt updates the selected candidate in place and writes distinct evidence under its `debug/assessment-runs/run-<assessment-workflow-id>-<attempt>/` directory. The existing source candidate remains in the same private results branch and retains its original location:

```text
results/<configured-site-slug>/run-<original-workflow-id>-<original-attempt>/candidates/<source-candidate-id>/
```

The first assessment saves the exact selected source bytes as `files/inlined/index-old.html`. The revised page replaces `files/inlined/index.html` (and its compatibility copy at `files/index.html`); later workflow attempts keep the original `index-old.html` and save each attempt's source, screenshots, manifest, reports, and before/after diffs in its own evidence archive. The candidate remains pending until deterministic QA and the existing image and visual reviews complete. No canonical customer HTML is modified.

After assessment, `run_html_assessment_qa.py` invokes Git Content's existing `browser_qa.py` and `check_website.py`. The model's final pass does not set `automated_success`; that field reflects repository QA only. `final_success` remains false while image and desktop/mobile visual review are pending. The private review templates use the repository's existing review schema. If the existing HTML5 UP-specific QA cannot establish that an existing page meets a criterion, the candidate stays unsuccessful and reviewable.

The public ChatGPT generation workflow no longer dispatches `content-post` immediately. After all three candidates in a run have assessment QA and final image/visual review, the private review workflow refreshes the existing `successful-passes/` files and sends the same `chatgpt_content_ready` event to `content-post`. Configure `CONTENT_POST_DISPATCH_TOKEN` in the private results repository for automatic dispatch; without it, maintainers can run the existing content-post workflow manually after review.

## Credentials and isolation

- The selected provider key is read from GitHub Actions secrets: `NVIDIA_API_KEY`, or `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`.
- Provider keys are present only in the inference step environment. Chromium is launched with credential-related environment variables removed, and provider error details redact the key.
- Customer target JSON is written to the runner's temporary directory. Source and output HTML, screenshots, prompts, logs, and reports are saved only to the private results branch. The workflow uploads no public Actions artifacts.
- The original candidate path is intentionally revised in place for the existing publisher. Each assessment attempt has its own evidence directory, and assessment never changes the private run-level completion status or canonical customer files.
