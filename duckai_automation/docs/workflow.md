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

Each site run seeks three automated passes. The coordinator normally allows ten complete candidate attempts initially and, when fewer than three pass without an access-gate or source-access failure, one continuation of up to ten more. For bounded diagnostics it can set the initial attempt limit from one to nine. Prior passing candidates carry forward and global candidate numbering continues, for a maximum of twenty attempts. The continuation policy, evidence scan, candidate counting, and inheritance are tested in `duckai_automation/scripts/continuation.py` (`python -m unittest discover -s duckai_automation/tests -v`). Each candidate uses a fresh, logged-out Duck.ai chat. With Web Search enabled, the runner asks for a source assessment, then requests CSS parts 1–3, sends `acknowledged` as a separate user turn, and requests HTML parts 1–3 in that same chat. It validates each response before assembly, creates the inlined HTML, renders desktop and mobile views with Playwright, and runs structural checks. Candidate progress notices report the attempt count and automated passes so far.

A successful automated check does not establish visual polish, image relevance, or factual accuracy. Human review remains necessary. If the guest chat is blocked by sign-in, usage, or human verification, stop the candidate and retain available failure evidence; do not bypass the gate.

## Source assessment

The runner sends the business name, category, and optional location as unverified context, then requests a source assessment. The assessment should cite pages on the requested domain, distinguish observed facts from inferences and unknowns, describe visible brand elements, and identify public logo/photo assets. The runner validates the source domain and any selected design reference before code generation. If source validation fails, that candidate stops.

The source assessment is Duck.ai's cited report, not independent human verification. Separately, the runner fetches up to eight same-domain pages and extracts direct image references from normal and lazy `<img>` attributes, responsive `srcset`, `<picture><source>`, video posters, social image metadata, and inline backgrounds. It keeps only URLs on the source domain or known image CDNs, filters logos/social graphics, and confirms that candidate URLs return image bytes. Responsive variants from the same Wix media asset are deduplicated. Extraction output and errors are saved in `debug/source_images.json`; candidates also retain Duck.ai's cited assessment. The initial generation prompt passes exact validated photos into `VERIFIED_SOURCE_IMAGE_URLS`, with unknown subjects labeled unknown rather than inferred from filenames or alt text. Curated, category-matched URLs are passed separately as `CATEGORY_FALLBACK_IMAGE_URLS` and should be used only when no suitable source image is available for a section. QA requires the hero and all used image URLs to match one of these approved lists, and separately checks image loading and browser rendering. Source-photo usage is reported but does not fail a candidate when suitable source photos are unavailable and category fallbacks are used. Image sourcing mentions do not require a dedicated gallery section; that section is gated only when the request explicitly asks for a gallery or portfolio. Location and other CSV clues must be confirmed by the website before they appear as fact. A template reference is optional; if one is used, preserve required attribution in a non-rendering HTML comment and internal run notes, not visible page content.

## Multi-turn capture and assembly

The runner captures exactly three labeled CSS parts, sends the acknowledgment as its own turn, then captures exactly three labeled HTML parts. Each response must be the newest assistant response in the same chat and have the expected label and code marker. Chunk manifests and response evidence are retained. Stale, incomplete, duplicate, or mislabeled chunks stop the candidate; missing code is not invented.

The assembled files are `files/styles.css` and `files/index.html`. The runner embeds the CSS into `files/inlined/index.html` before browser QA. The inlined page still needs network access for externally hosted images and fonts.

## Automated QA and human review

Playwright checks the inlined page at desktop and mobile viewports. Browser evidence covers rendered sections, a full-width hero, first-screen CTA, mobile menu click/keyboard behavior, horizontal overflow, and browser font/image loading. The structural checker also evaluates the generated markup, including the CTA-arrow rule.

These deterministic checks set `automated_success`; they do not call an AI model and do not approve visual quality or factual correctness. Review candidate screenshots and source assessment in the private results repo. Treat a page as approved only after a human has reviewed the design, imagery, and factual content.

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
        checker_report.json
        inputs.json
        source_assessment.json
        source_assessment.md
        screenshots/
      conversation_turns.json
      run_notes.json
  status.json
```

Partial or failed candidates retain whatever diagnostics were available. The private `duckai` branch maintains the results index and `successful.csv`; successful rows include the pipeline completion time in UTC. Private `main` contains the source CSV and legacy job records, not generated run folders. The Actions runner uses a temporary `duckai-runs/` workspace while processing, then sends the evidence directly to private `duckai`. Each provider writes to its matching private branch (`duckai` or `chatgpt`) to keep concurrent providers from contending on the same result branch. Publishing input batches to private `main` is still a shared single-writer operation; commit one batch at a time before starting its provider runs.
