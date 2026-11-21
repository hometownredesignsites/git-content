# Git Content HTML Assessment workflow

The public `chatgpt` branch contains `.github/workflows/html-assessment.yml` using NVIDIA NIM, but the workflow has been manually disabled in GitHub Actions for now. Do not dispatch it unless it is re-enabled. The remaining notes in this file describe the previous assessment integration.

Each workflow attempt updates the selected candidate in place and writes distinct evidence under its `debug/assessment-runs/run-<assessment-workflow-id>-<attempt>/` directory. The existing source candidate remains in the same private results branch and retains its original location:

```text
results/<configured-site-slug>/run-<original-workflow-id>-<original-attempt>/candidates/<source-candidate-id>/
```

The first assessment saves the exact selected source bytes as `files/inlined/index-old.html`. The revised page replaces `files/inlined/index.html` (and its compatibility copy at `files/index.html`); later workflow attempts keep the original `index-old.html` and save each attempt's source, screenshots, manifest, reports, and before/after diffs in its own evidence archive. Dispatch input `revision_mode=repair` (default) for evidence-backed minimal edits or `revision_mode=full_rebuild` to let Nemotron rebuild the complete HTML/CSS page. Full rebuild still preserves exact image `src`/`srcset`, anchor destinations, form contracts, and the extracted stylesheet link; output violating those contracts falls back to the source/current candidate and stays pending if QA does not pass. Passing the Pass 1 gate and deterministic repository QA completes approval; final model visual QA is advisory. A failed Pass 1 gate or unmeasurable repository check leaves the candidate pending. No canonical customer HTML is modified.

Before repair priorities are generated, Git Content's existing structural and browser QA runs against an isolated copy of the original inline HTML. The same QA runs again after Pass 1. Its structural blockers, desktop/mobile CTA contrast details, and failed image URLs are passed to the repair states. Pass 2 runs only after both the provider's final Pass 1 review and deterministic QA pass. Bounded repair exhaustion saves the current Pass 1 HTML and evidence as pending, with Pass 2 skipped. These intermediate QA subprocesses do not receive provider credentials.

The current ChatGPT generation workflow sends three generation-approved inline HTML files to `content-post` slot branches and preserves each candidate in a batch queue folder. A scheduled Action in the public `git-content` repository checks out private `content-post`, updates `automation/slot-ledger.json`, and assigns one company batch to all three slot branches. Workers read `todo-today/index.html` and return `todo-today/revised/index.html` with matching task metadata. Hourly reconciliation validates and archives these results to `sites/<site-slug>/revised/`; the central ledger records each slot's state. The private promotion Action promotes a completed same-batch revision set to `main` and triggers Cloudflare only after all three candidates are ready.

Pushing `ready-for-cloudflare.json` to `content-post/main` triggers the publisher workflow. That workflow verifies all three candidate files and their shared batch ID before building the Pages deployment. The generator needs `CONTENT_POST_DISPATCH_TOKEN`, scoped to `hometownredesignsites/content-post` with Contents read/write permission, to stage drafts on the slot branches.

## Credentials and isolation

- The NVIDIA API key is read only from the public Git Content repository's `NVIDIA_API_KEY` Actions secret.
- `NVIDIA_API_KEY` is present only in the NVIDIA inference step environment. Chromium is launched with credential-related environment variables removed, and provider error details redact the key.
- Customer target JSON is written to the runner's temporary directory. Source and output HTML, screenshots, prompts, logs, and reports are saved only to the private results branch. The workflow uploads no public Actions artifacts.
- The original candidate path is intentionally revised in place for the existing publisher. Each assessment attempt has its own evidence directory, and assessment never changes the private run-level completion status or canonical customer files.
