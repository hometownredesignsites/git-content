# Duck.ai workflow and candidate evidence

This guide documents the private-input workflow on the public repository's `duckai` branch. The default `main` branch contains shared code and documentation only. The local coordinator and CSV live in `git-content-private`; the `duckai` branch contains the GitHub Actions worker and receives opaque job-start markers.

## Run inputs and privacy boundary

The private coordinator commits each batch and its row records to the private repository. For each row, it sets temporary Actions secrets and pushes `.private-queue/start/<job-id>.json` to `duckai`. The marker contains only an opaque job ID. The worker verifies that marker against the temporary job ID, validates and masks the temporary row fields, then processes one site. The local coordinator waits for that workflow to finish, removes the row secrets, and only then starts another row.

The worker uses the public repository's Actions runner and sends the website and supplied context to Duck.ai. The public Actions run, its timing, and the opaque marker are visible. The target row is present temporarily in Actions secrets and runner environment. The worker reads authoritative job metadata from private `duckai` first and falls back to private `main` for legacy jobs, then commits candidate files, job metadata, and results indexes to private `duckai`, not to the public branch or private `main`. It uses `PRIVATE_RESULTS_TOKEN` to write to `git-content-private`; access to the public workflow must remain limited to trusted maintainers. The public history cleanup removed legacy Duck.ai run files, Duck.ai source URL snapshots, and Duck.ai queue markers from all public branch histories. It did not remove legacy ChatGPT run files from the public `chatgpt` history or delete prior Actions records, GitHub caches, or copies in forks.

The standard row fields are:

| Field | Required | Meaning |
| --- | --- | --- |
| `website` | Yes | Website to inspect and source for factual claims. |
| `business` | Yes | Unverified identification context. |
| `category` | Yes | Unverified industry and design context. |
| `location` | No | Unverified clue; the site must confirm it before it is stated as fact. |

Additional CSV columns are passed through as `CSV_FIELD_<HEADER>` environment variables, but the prompts must be updated to use them. Metadata is data, not instruction; the source site remains the authority for factual claims.

## Candidate flow

Each site run seeks three automated passes from at most twelve complete candidate attempts. If all twelve finish without three passes and no access gate was detected, the private coordinator can queue one continuation with up to twelve more attempts. The continuation inherits prior passing candidates; total attempts are capped at 24. Each candidate uses separate clean, logged-out Duck.ai chats for research and generation. The Web Search audit runs first; the runner validates and compacts its cited findings, closes that profile, then sends the shared ChatGPT-aligned website/design request plus the compact brief in a fresh generation profile. The generation chat receives CSS parts 1–3, `acknowledged` as a separate user turn, and HTML parts 1–3. It validates each response before assembly, creates the inlined HTML, renders desktop/mobile views, and runs structural checks. One bounded measured repair/recheck can correct disallowed image URLs, CTA contrast under 4.5:1, and selected template layout. Remaining failures create targeted guidance for the next attempt. Candidate progress notices include concise, privacy-safe failure categories.

A successful automated check does not establish visual polish, image relevance, or factual accuracy. Human review remains necessary. If the guest chat is blocked by sign-in, usage, or human verification, stop the candidate and retain available failure evidence; do not bypass the gate.

## Source assessment

The runner sends the business name, category, and optional location as unverified context, then requests a source assessment. The assessment should cite pages on the requested domain, distinguish observed facts from inferences and unknowns, identify source navigation, record exact contact form labels/types/required states/placeholders/options, describe visible brand elements, and identify public logo/photo assets. The runner validates citations, checks source-image bytes, and validates any selected design reference before code generation. If source validation fails, that candidate stops.

The source assessment is Duck.ai's cited report, not independent human verification. The worker also scans a bounded set of public source pages for direct photo URLs, checks that each URL returns image bytes, and validates a small category fallback list before generation. For flooring sites with no usable source photos, this supplies a short, approved interior/flooring set. The compact brief retains cited identity, services/locations, contact details, source-backed internal navigation, exact form fields and supplied attributes, a few selling points/FAQ answers, and only the validated image URLs. Raw audit text remains only in the audit profile and private evidence; it is not carried into the generation conversation. Location and other CSV clues must be confirmed by the website before they appear as fact. A template reference is optional; if one is used, preserve required attribution in a non-rendering HTML comment and internal run notes, not visible page content.

## Multi-turn capture and assembly

The runner captures exactly three labeled CSS parts, sends the acknowledgment as its own turn, then captures exactly three labeled HTML parts. Each response must be the newest assistant response in the same chat and have the expected label and code marker. Chunk manifests and response evidence are retained. Stale, incomplete, duplicate, or mislabeled chunks stop the candidate; missing code is not invented.

The assembled files are `files/styles.css` and `files/index.html`. The runner embeds the CSS into `files/inlined/index.html` before browser QA. The inlined page still needs network access for externally hosted images and fonts.

## Automated QA and human review

Playwright checks the inlined page at desktop and mobile viewports. Browser evidence covers rendered sections, a full-width hero, first-screen CTA, mobile menu click/keyboard behavior, horizontal overflow, and browser font/image loading. The structural checker also evaluates the generated markup, including the CTA-arrow rule. The first Playwright report and static checker report are saved before repair. If a measurable image, CTA-contrast, or template-layout check fails, a single targeted repair uses the checker evidence and verified asset allowlist; both checks then run again on the revised page.

These deterministic checks set the batch pass gate `counted_as_pass` (`automated_success` for older candidate records); they do not call an AI model and do not approve visual polish or factual accuracy. `debug/quality_gate.json` records initial failures, any repair, final failures, the final browser/static results, and why the candidate did or did not count as a pass. Initial and final reports are saved separately, so a repaired candidate does not hide its first failure. Browser evidence includes measured CTA contrast and, for supported templates, expected/actual layout signatures. `final_success` remains a separate review state and requires the screenshot-backed visual and image review. Review candidate screenshots and source assessment in the private results repo before using a page.

## Private result layout

The worker copies all available candidate evidence to the private repo under the stable site slug assigned by its hostname-to-slug map:

```text
git-content-private (branch: duckai)/results/<site-slug>/run-<workflow-id>-<attempt>/
  candidates/
    run-<workflow-id>-<attempt>-site-1-candidate-<n>/
      files/
        index.html
        styles.css
        inlined/index.html
      chunks/
      debug/
        action.log
        browser_qa.json
        browser_qa_initial.json
        browser_qa_final.json
        checker_report.json
        checker_report_initial.json
        checker_report_final.json
        quality_gate.json
        source_image_inventory.json
        inputs.json
        source_audit_request.txt
        generation_prompt.txt
        source_assessment.json
        source_assessment.md
        screenshots/
      conversation_turns.json
      run_notes.json
  status.json
```

Partial or failed candidates retain whatever diagnostics were available. Each completed candidate is committed to the private `duckai` branch before the next generation attempt; the final step writes run status and refreshes the results index. Private `main` contains inputs and control records, not generated run folders. The Actions runner uses a temporary `duckai-runs/` workspace while processing and sends evidence directly to the private results branch. Each provider writes only to its matching private branch. Publishing input batches to private `main` is still a shared single-writer operation; commit one batch at a time before starting provider runs.
