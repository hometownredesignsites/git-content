# HTML Assessment Workflow

A reusable Python workflow that downloads customer HTML pages, audits the original HTML/CSS first, then captures desktop and mobile screenshots with **headless Playwright Chromium** for a separate visual review through Cloudflare Workers AI or NVIDIA NIM. It then produces two sequenced revisions. It is designed to run locally or as a one-target-per-job step in GitHub Actions. It never publishes or deploys a page.

## Two-pass review

1. **Pass 1 — Repair:** inspect source code before screenshots, then combine that audit with screenshot evidence and Git Content's deterministic baseline QA. Correct evidence-backed HTML, accessibility, content/action, responsive, visual, and repository-gate defects. Keep changes minimal and preserve the existing page direction. Rerun deterministic QA after repairs. Pass 2 does not start until both the model review and required repository checks pass; otherwise the Pass 1 HTML is saved as a pending candidate.
2. **Pass 2 — Design enhancement:** start from the corrected Pass 1 output and apply restrained improvements informed by UI/UX Pro Max and web-applicable Apple Design principles. Capture fresh screenshots, review the draft, apply supported corrections, and run a final gate.

The local edit applier blocks model edits that add, remove, or change an `<img>` `src` or `srcset`. Image URL changes need a separate asset-validation workflow; this prevents an unverified model suggestion from introducing a broken image. Screenshot review also checks image relevance and alt-text accuracy: a loaded image can still be the wrong subject or be stretched into the wrong role. Git Content's browser QA checks CTA visibility and contrast and reports broken images; unmeasured contrast fails closed. QA subprocesses run without provider credentials.

The selected remote provider performs assessment, prioritization, design direction, and QA. Python downloads source HTML, sends a code-only audit first, then captures local screenshots and requests a visual supplement before prioritization or edits. It validates JSON and exact edit anchors, applies edits, and saves evidence. Source page text, code, and screenshots are treated as untrusted data.

## Providers

- **Cloudflare Workers AI** is the default. `CLOUDFLARE_MODEL` overrides the default `@cf/google/gemma-4-26b-a4b-it`.
- **NVIDIA hosted NIM** uses `nvidia/nemotron-3.5-super-vl-120b-a12b` by default. Override with `NVIDIA_MODEL`.

Both receive the page HTML and screenshots. Screenshot capture is local; the selected API performs inference.

## Requirements

- Python 3.10 or later.
- Network access to the source URL and selected inference API.
- Playwright Python and its Chromium browser for visual mode.
- Credentials for the selected provider.

On Windows, create a project-local virtual environment and install Playwright there:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-playwright.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

Then run the script with `.\.venv\Scripts\python.exe`. This avoids relying on global Python script-launcher setup. On GitHub Actions, use a hosted Python installation and `python -m playwright install --with-deps chromium` on Ubuntu.

On GitHub Actions, install the matching browser dependencies with `python -m playwright install --with-deps chromium` on an Ubuntu runner. Keep the API call step separate from any job that processes untrusted customer code if practical; the browser child process is launched without the provider API key in its environment.

### Credentials

Never put credentials in source code, prompts, or the target JSON. The script does not print credential values.

For Cloudflare, set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, or use a local `~/Documents/CLOUDFLARE_ENV.txt` with those two assignments. The token needs Workers AI Run permission.

For NVIDIA, set `NVIDIA_API_KEY`, or store only the key on one line in `~/Documents/nvidia-api-key.txt`. NVIDIA keys should begin with `nvapi-`; the format check does not validate the key.

Use `--env-file` to select another local credential file. GitHub Actions should use repository or environment secrets instead of checked-in key files.

## Local run

Pass one or more public page URLs. The same two-pass process runs for each page, identified in outputs as `page-1`, `page-2`, and so on.

```powershell
# Cloudflare
python .\html_assessment.py --urls "https://example.com/page/"

# NVIDIA, multiple pages
python .\html_assessment.py --provider nvidia --urls "https://example.com/a" "https://example.com/b"

# Code-only mode skips screenshots and visual review
python .\html_assessment.py --provider nvidia --urls "https://example.com/page/" --code-only

# Resume an existing run with the same provider and model
python .\html_assessment.py --provider nvidia --resume-directory ".\generated\run-YYYYMMDD-HHMMSS"
```

A visual run captures each page and revision at 1440×1000 desktop and 390×844 mobile viewports. It saves desktop hero, a representative content section, and mobile hero screenshots. These snapshots do not establish exhaustive browser, device, keyboard, or assistive-technology behavior.

## Git Content input and candidate output

The script accepts the target-row shape used by `hometownredesignsites/git-content`: `website`, `business`, `category`, and optional `location`. Use a private JSON file for the row; do not commit customer target rows to this project.

```json
{
  "website": "https://example.com/",
  "business": "Example Business",
  "category": "Professional services",
  "location": "Example City"
}
```

Run one target per GitHub Actions job and pass the JSON file plus a candidate output directory:

```powershell
python .\html_assessment.py `
  --provider cloudflare `
  --target-json-file .\private-target.json `
  --candidate-output-dir .\candidate
```

In GitHub Actions, derive the expected `results/<site-slug>/run-<workflow-id>-<attempt>/candidates/<candidate-id>/` path from runner metadata:

```bash
python html_assessment.py \
  --provider cloudflare \
  --target-json-file "$RUNNER_TEMP/html-target.json" \
  --results-root "$PRIVATE_RESULTS_CHECKOUT" \
  --site-slug "$SITE_SLUG"
```

The candidate export follows Git Content's file layout. Its initial `run_notes.json` explicitly marks assessment complete but repo QA pending; it does not set `automated_success` until Git Content's existing checker passes. `files/inlined/index-old.html` preserves the exact source selected from the private repository, while the revised HTML is written to `files/inlined/index.html`. The assessor runs the same repository QA on isolated baseline and Pass 1 snapshots under `audit/repository-qa/`; those blockers are included in repair prompts, and model QA cannot override them.

```text
candidate/
  files/
    index.html
    styles.css
    inlined/index-old.html  # exact source HTML from the private candidate
    inlined/index.html      # revised assessment output
  debug/assessment-run.zip  # full source, screenshots, reports, diffs, and manifest
  debug/screenshots/desktop.png
  debug/screenshots/mobile.png
  run_notes.json
  status.json             # duplicate compatibility alias
```

`run_notes.json` from the standalone exporter uses `assessment_complete_pending_repo_qa` or `automated_failed`, with `model_review_passed`, `automated_success`, `final_success`, `human_visual_review_status`, and `image_relevance_review_status` fields. In the Git Content Actions workflow, its adapter runs the existing structural and browser checks and sets `automated_success` and `final_success` from those deterministic results. `status.json` duplicates the candidate state for adapter consumers. `files/inlined/index.html` is the compatibility entry point for the final HTML. It preserves stylesheet and asset references from the source page; it is not a fully bundled offline site. `styles.css` contains CSS embedded in `<style>` elements. External stylesheets and other assets remain referenced from their original URLs. The script writes only to the requested candidate path. With `--results-root` and `--site-slug`, it derives the private results path from the GitHub run metadata; the caller remains responsible for committing that candidate to the private results branch.

The Python script does not commit to GitHub or publish candidate pages. The Git Content Actions workflow reads a configured target and private source candidate, updates only that candidate's inline HTML, and commits the result to the private results branch. It does not upload customer HTML, screenshots, or prompts as public Actions artifacts.

## GitHub Actions sequence

The public `chatgpt` branch now provides `.github/workflows/html-assessment.yml`, which uses NVIDIA NIM. Dispatch it once per candidate with an opaque private job ID, the private source run ID, and a private source candidate ID. Wait for each candidate workflow to finish before starting another candidate for that job. The source run ID disambiguates candidate names reused across separate runs. The workflow reads `files/inlined/index.html` from that candidate in the private results checkout; the configured job row supplies context, `result-slugs.json` locates the private customer folder, and the candidate's `debug/inputs.json` supplies the matching page URL used for asset loading. It does not fetch live page HTML. It:

- Reads the selected job's authoritative private target row and verifies that the selected candidate belongs to that customer's configured result slug.
- Installs Python, Playwright, and headless Chromium.
- Runs the two-pass assessment with `NVIDIA_API_KEY` from Actions secrets.
- Runs Git Content's existing `browser_qa.py` and `check_website.py`, recording reports and optional review templates.
- Preserves the original as `files/inlined/index-old.html`, then updates that candidate's `files/inlined/index.html`; each workflow attempt keeps separate evidence under `debug/assessment-runs/`.
- Sets `final_success` only when the Pass 1 gate and Git Content's deterministic structural and browser QA pass; the final model visual review remains advisory and no separate human review is required for publication.

Capture and inference occur in the Actions runner; screenshots are produced by headless Playwright and attached to the NVIDIA API request. Chromium does not inherit provider keys. The model's visual pass is advisory; only passing deterministic structural and rendered browser checks can approve a candidate. CTA contrast and broken image checks are blocking, and checks that cannot measure an issue reliably fail closed for review.

The original ChatGPT generation workflow does not post to Cloudflare before assessment. Once at least three candidates in the latest successful run pass deterministic repository QA, the assessment workflow refreshes `successful-passes/` and dispatches the unchanged `content-post` workflow. Configure `CONTENT_POST_DISPATCH_TOKEN` in the public Git Content repository; otherwise, start the existing publisher manually.

## API retries

The API client makes up to five attempts for HTTP `429`, `500`, `502`, `503`, and `504`, plus transient connection timeouts and resets. It honors numeric or HTTP-date `Retry-After` (capped at 60 seconds); otherwise it waits 1, 2, 4, and 8 seconds for transient failures. It retries one TLS connection/certificate error with verification enabled. Other HTTP errors fail immediately. Retries do not bypass persistent quota or permission errors.

## Outputs

Each run creates a timestamped folder under `generated/` unless `--output-root` is specified. It contains source HTML, screenshots, per-state assessments and QA, edit responses, unified before/after diffs, a manifest, and a summary. Final HTML files are named `page-1.html`, `page-2.html`, etc.; repaired Pass 1 files use `page-1-pass1.html`.

## Guidance files

- `workflow-prompt.md` defines inference states, schemas, evidence rules, and pass gates.
- `assessment-rubric.md` defines Pass 1 repair criteria.
- `enhancement-rubric.md` defines Pass 2 design criteria.
- `assessment-rubric.json` records pinned guidance-source versions.

The workflow does not invoke Claude or fetch design skills at run time. SWAN is intentionally excluded. It does not invent business claims or add unconfigured forms, and model edits must cite a criterion and match an exact unique source snippet.

## Operational limits

A run can stop on provider quota/API errors, malformed model output, invalid edit anchors, incomplete HTML, screenshot capture failure, or an unsuccessful Pass 1 gate. The run directory retains intermediate files for diagnosis and resumption where supported. Final QA is model-reviewed and based on supplied source and rendered screenshots; it does not prove every interaction works at runtime. Review pages before publishing.
