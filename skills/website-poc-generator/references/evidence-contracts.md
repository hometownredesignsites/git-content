### 6.5 Assemble and verify the three final standalone deliverables

The skill creates the three named standalone HTML files directly and packages them with their evidence. It does not need to reproduce the Action's two-HTML/two-CSS response chunking, chunk manifest, source stylesheet link, or CSS-inlining step; those are workflow-specific assembly checks. Both modes share the delivered-file contract and all applicable final-byte gates.

**Final file set — blocking**

- Produce exactly these three independent files:
  - `candidate-forty.html`
  - `candidate-landed.html`
  - `candidate-story.html`
- Before delivery, verify that all three paths exist, are regular files, and contain non-whitespace content. Record each exact path and byte size. A missing, empty, duplicated, or misnamed candidate blocks completion; do not silently substitute one template or return fewer files.
- Each file must contain its own complete HTML5 document, including doctype, `html`, `head`, `body`, and closing document tags. Each must independently declare its language, nonempty title, viewport metadata, and exactly one main landmark and one nonempty H1.
- Each file must contain its complete page CSS in its own embedded `<style>` block(s). Verify the embedded CSS is nonempty and syntactically balanced. Do not rely on a sibling `.css` file, a shared stylesheet, or styles embedded only in another candidate.
- If a temporary external CSS source was used during authoring, apply all intended CSS—including the selected palette and any form-control repairs—before packaging. Then inline it into that candidate's HTML and verify the resulting delivered file. Temporary source CSS may be retained as debug evidence, but it is not a runtime dependency and must not be required to render the page.

**Standalone dependency audit — blocking**

Inspect each final HTML file, not just the authoring source:

- No stylesheet `<link rel="stylesheet">`, CSS `@import`, external CSS bundle, or unresolved local stylesheet reference may be required for layout or styling.
- No external JavaScript file, bundler, package manager, framework build, transpilation, or generated runtime bundle may be required for the page's core presentation or navigation. Do not leave script references to missing local files or chunk artifacts.
- No unresolved references to intermediate HTML/CSS chunks, assembly manifests, temporary paths, or files outside that candidate's delivered package may remain.
- Check local `src`, `href`, `poster`, CSS `url(...)`, fragment, and form-action references. Every required local target must exist and resolve within that candidate's output. Verified external business links, approved remote image URLs, and intentional contact links (`mailto:`/`tel:`) are permitted; they are content/runtime references, not build dependencies. Record external font or other remote runtime resources separately rather than describing them as build dependencies.
- A standalone file may still use approved externally hosted images. “Standalone” means no external build or page-style dependency; it does not mean all image bytes are embedded in the HTML. Preserve the existing image provenance, byte-validation, browser-load, and human relevance checks.
- Confirm that the page does not require a server-side build step or a sibling asset directory to display its core layout. If a genuinely required local asset remains, either package and verify it as part of that candidate's explicit deliverable set or remove the dependency; do not claim a single-file standalone result while omitting it.

**Per-file independent validity — blocking**

Open and validate each of the three files independently, in isolation from the other candidates and from temporary authoring files:

1. Parse the final HTML and run all applicable static/document checks from §6.1 against that exact file.
2. Confirm its embedded CSS is the CSS actually used by that file; do not validate an external source stylesheet and assume the inlined copy is identical.
3. Verify the assigned template attribution comments and palette tokens survived packaging, and that there is no visible template credit.
4. Recheck contact form controls after all form repairs: labels, names/types, required/optional state, and source-field preservation must still pass. A repair or packaging step must not silently remove or alter captured fields.
5. Confirm all local links, fragment targets, image references, and interactive controls resolve as intended in the isolated file.
6. Record a per-file package result with file name, bytes, embedded-style status, external build-dependency status, local-reference status, parse/document status, and PASS/FAIL/BLOCKED/UNVERIFIED.

**Final QA must target the exact delivered bytes — blocking**

- Run the complete static/document and asset QA from §6.1 on each final named file after all CSS inlining, palette application, form repairs, and packaging changes are complete.
- Run the complete Chromium/browser QA from §6.2 separately on each final file at desktop 1440×900 and mobile 390×844. Use the actual delivered file path or an identical byte-for-byte copy; do not test an earlier draft, a separate CSS source, or a pre-repair version.
- Capture and associate the desktop/mobile screenshots, browser report, static report, and human visual/image review evidence with the matching candidate filename. Do not reuse one candidate's passing report or screenshots for another.
- Compute and record a SHA-256 digest for each final delivered HTML file after the last change. The digest identifies the bytes that were tested and returned. If any file changes after QA—even a CSS, form, metadata, or link edit—rerun the applicable static and browser checks for that file, regenerate its screenshots/reviews, and update its digest.
- A missing file, incomplete embedded CSS, unresolved required dependency, invalid standalone document, or failed final QA check blocks that candidate. If any one candidate is blocked or fails, the three-file set is not complete. Browser tooling unavailable means browser checks remain BLOCKED/UNVERIFIED; do not infer final-file validity from static inspection alone.

### 6.6 Structured evidence package and review records

Use the machine-readable JSON Schema at `skills/website-poc-generator/evidence.schema.json` as the structural contract for normalized records. The Action emits this record set through `chatgpt_automation/scripts/package_website_poc.py` after workflow-specific assembly, and preserves native debug reports as raw evidence. Run `validate_evidence.py <output-root>` for skill runs to add cross-record digest, identity, and completion checks. It reports JSON Schema validation as UNVERIFIED when the optional `jsonschema` package is unavailable; its standard-library semantic checks still run. The Action packaging step currently validates each normalized record against the shared schema; do not claim it runs the skill's additional cross-record validator unless the workflow invokes it.

Use one deterministic output root for every skill run. Store the three deliverable HTML files at the root and normalized evidence in candidate-specific folders so reports and screenshots cannot be accidentally shared across candidates. Always write `evidence/index.md` as a concise manifest of run status, the three deliverables and digests, candidate evidence folders, and validators actually run. Set `run.json.evidence_index` to exactly `evidence/index.md` and verify that the path exists. The Action packages equivalent normalized records in its private result structure; its candidate assembly paths and intermediate checks remain workflow-specific. Do not make the skill imitate those intermediate chunk/CSS assembly steps.

```text
website-poc-output/
  candidate-forty.html
  candidate-landed.html
  candidate-story.html
  evidence/
    index.md
    run.json
    candidate-ledger.json
    source-facts.json
    source-capture.json
    generation-context.json
    generation-context.md
    forty-attempt-1/
      candidate-inputs.json
      static-qa.json
      browser-qa.json
      repairs.json
      image-review.json
      visual-review.json
      final-status.json
      raw/debug/
        checker_report.json
        browser_qa.json
        screenshots/desktop.png
        screenshots/mobile.png
    landed-attempt-1/
      [same normalized files and candidate-specific raw evidence]
    story-attempt-1/
      [same normalized files and candidate-specific raw evidence]
```

If the environment requires a different root, preserve this relative layout and record the actual root in `run.json`. Do not put candidate-specific records in a shared folder. Use unique attempt IDs such as `forty-attempt-1` so failed and superseded attempts retain their own records; the final deliverable slots remain `forty`, `landed`, and `story`. Keep saved source observations, design references, original QA reports, repair logs, and screenshots alongside this normalized package; normalized records summarize and link to those files rather than replacing them. Use UTF-8 JSON, valid JSON objects, and paths that resolve from the output root. Validate against this schema when a validator is available; the Action's validator does not imply that the skill runtime has one. Do not fabricate unavailable evidence: use explicit `null`, empty arrays, and `BLOCKED`/`UNVERIFIED` statuses with a reason.

**Common record rules**

- Every JSON record includes `schema_version: "1.0"`, `record_type`, `run_id`, `candidate_id` (null only for run-level records), `created_at` as an ISO-8601 timestamp with timezone, and `status` where applicable.
- Status values are `PASS`, `FAIL`, `BLOCKED`, or `UNVERIFIED`; use `NOT_REQUIRED` only for a clearly documented non-applicable check. Never convert missing or unreadable evidence into PASS.
- Each check is an object with `id`, `status`, `blocking`, `summary`, and `evidence_paths` (array). Add `details` for measured values, observed defects, or error text. Keep blocking and advisory checks distinct.
- Paths must point to real saved files. Do not claim a screenshot, report, source capture, or repair artifact exists unless it was saved and verified. Include viewport dimensions and candidate ID in screenshot metadata or filenames.
- Preserve the final HTML SHA-256 in all candidate-level QA/review/final records. If the HTML changes, invalidate its QA and review statuses until rerun and update the digest.

**Candidate ledger and bounded retry contract**

The skill runs in a generation session, not the GitHub Actions dialog-rendering path. Do not copy the workflow's 12-attempt initial batch or 12-attempt continuation batch; those limits compensate for a workflow-specific failure mode and are not the skill's retry budget.

Use a small, slot-based retry policy:
- Generate one initial candidate for each required slot (Forty, Landed, Story): 3 generation attempts maximum in the initial pass.
- Run the required QA and repair loop on each initial candidate. A deterministic repair does not consume a generation attempt; it must still be followed by the applicable static checks and complete desktop/mobile browser QA.
- If a slot still fails a blocking gate after its repair/retest opportunity, allow at most one targeted regeneration for that slot. This is one retry per failed slot, up to 3 additional generation attempts; the hard ceiling is 6 generation attempts for the run.
- Do not regenerate a slot that already has a passing candidate. Keep that candidate and its evidence. A retry replaces the slot's selected deliverable only if the retry independently passes all required gates; otherwise retain the prior attempt record and report the slot as unresolved.
- Before a retry, summarize the exact failed check IDs, measured findings, repair outcomes, and remaining defect. Use those findings to change the candidate-specific brief or implementation. Do not repeat the same generation instructions unchanged. Preserve the slot's assigned template and signature; retries are not permission to switch templates.
- Stop early when all three distinct slots pass. Do not use a continuation batch, open-ended retry loop, or automatic retry beyond the per-slot retry. If a run is interrupted, resume from its ledger without repeating completed passing slots; this is resumption, not a new retry allowance.
- If a slot remains failing, blocked, or unverified after its one retry, stop and report the exact missing slot and evidence. Do not claim a complete three-candidate set.

`evidence/candidate-ledger.json` is the authoritative append-only attempt history. Include the common record fields plus `execution_mode: "skill"`, `target_passing_slots: 3`, `initial_attempt_limit: 3`, `continuation_attempt_limit: 3`, `max_total_attempts: 6`, `attempts_used`, `batch_attempts` as a two-integer array `[initial_attempt_count, targeted_retry_count]` (for example `[3, 0]`), `passing_count`, `passing_slots` (slot, candidate ID, HTML path/digest, final status, evidence path), `missing_slots`, `continuation` (eligible boolean and reason; eligible only while a failed slot has not used its retry), `terminal_status`, and ordered `attempts`. Each attempt records `attempt_number`, `batch_number` (1 initial, 2 targeted retry), `batch_attempt_number`, `candidate_id`, `candidate_path`, `slot`, `template`, `template_signature_id`, `status`, `qualifies_as_pass`, `failed_check_ids`, `failure_summary`, `repair_status`, `retest_status`, `html_sha256`, `evidence_paths`, and `retention` (`retained`, `surplus_pass`, `failed`, or `superseded`). Keep every attempt; never reuse an attempt number or overwrite an earlier record. Count generation attempts—not repair edits—in `attempts_used`. The terminal status is PASS only with three distinct passing slots; otherwise use INCOMPLETE, BLOCKED, or FAIL with missing slots and reason. The Action writes the workflow form of this normalized ledger with 12+12 limits while retaining its Action-specific raw reports.

**Required record contracts**

1. `evidence/run.json` — run identity and package index:
   Include `execution_mode` (`skill` or `workflow`), `runtime_profile` (`full_parity`, `browser_github_limited`, `limited`, or `workflow`), and each deliverable as an object with relative `path`, positive `bytes`, lowercase SHA-256 in `sha256`, `qa_html_sha256`, `package_status`, and `candidate_id`. `qa_html_sha256` must identify the exact same delivered bytes as `sha256`; `package_status` must agree with the final candidate record. Use the keys `candidate-forty.html`, `candidate-landed.html`, and `candidate-story.html`. Record `tool_availability` as a map from each capability to `{ "status": "available|unavailable|not_checked", "tool": "...", "evidence": "..." }`; include the verified GitHub ref/commit when available and the run-level failure summary. A skill run may use `runtime_profile: "full_parity"` only if every full-parity capability in the matrix was present and used; set run status to PASS only when all three candidate final-status records pass.

2. `evidence/source-facts.json` — source-grounded business facts and provenance. Store `source_url`, `pages_reviewed` (each page has `url`, `capture_method` = `static_html` or `rendered_dom`, `captured_at`, and saved evidence path or explicit unavailable reason), `facts` (each item has `fact`, `source_url`, `capture_method`, `evidence_excerpt_or_locator`, `evidence_path`, and `confidence`), `contact`, `logo`, `form_schema` (each observed form carries its source URL, capture method, and evidence path), `source_assets` (each image carries its source page, discovery method, capture method, and evidence path), `user_supplied_facts`, and `unsupported_or_missing`. Keep raw source captures under `evidence/source-capture.json` and make evidence paths resolve within the run package. Distinguish static evidence, rendered observations, and user-provided facts. Represent each user-supplied fact as an object with `fact`, `provided_by`, and `evidence_path`; keep comparison-only mappings in `generation-context.json`, not as business facts. Do not store credentials, hidden fields, tracking values, or private implementation details.

3. `evidence/generation-context.json` — exact generation inputs and design references. Include `business_name`, `source_url`, `source_facts_path`, `generation_instructions` (the actual prompt/brief or a saved path plus SHA-256), `template_assignments` (one entry per candidate with slot, template name, signature ID, official reference URL, demo URL, license URL), `palette_tokens`, `approved_image_urls`, `source_contact_schema`, `constraints`, and `context_sha256`. Record actual values used; do not merely say “see conversation.” Do not include secrets or unrelated user data.

4. Per-candidate `candidate-inputs.json` — candidate-specific input snapshot. Include `candidate_id`, `slot`, `template`, `template_signature_id`, `palette`, `source_facts_path`, `generation_context_path`, `selected_source_assets` (URL, source page, discovery method, validation status, intended section), `selected_fallback_assets` (exact URL, pool key/label, byte/load-only validation status, and explicit statement that licensing/reuse terms were not checked), `contact_and_form_requirements`, `required_sections`, `output_html_path`, and `input_sha256`. Include the exact candidate-specific prompt/brief or a saved path and digest.

5. Per-candidate `static-qa.json` and `browser-qa.json` — normalized results plus the original raw reports when available. Each contains `candidate_id`, `html_path`, `html_sha256`, `started_at`, `completed_at`, `tool`, `status`, `checks` (common check objects), `blocking_failures`, `advisories`, `evidence_paths`, and `failure_summary`. Browser QA additionally records `viewports` with exact width/height, browser/engine and version when known, screenshot paths, and per-viewport results. Static QA records document/CSS/dependency validation and asset-byte results. Keep the workflow's original detailed check names and values in the raw report; do not flatten away diagnostics. If the official checker cannot be run, a custom subset may report its individually executed checks, but the overall `static-qa.json` status must be `UNVERIFIED` unless every required static gate was independently executed; never label a selected subset PASS. In particular, execute and record `ids_unique` and `fragment_links_resolve` against the exact delivered file.

6. Per-candidate `repairs.json` — repair history. Include `candidate_id`, `html_sha256_before`, `html_sha256_after`, and ordered `repairs`. Each repair has `repair_id`, `triggering_check_ids`, `file_or_region`, `problem`, `change_made`, `result` (`APPLIED`, `NOT_NEEDED`, `FAILED`, `BLOCKED`), `evidence_paths`, and `retest_check_ids`. Include `repair_attempts`, `remaining_failures`, and `status`. A no-op repair record must say `NOT_NEEDED`; do not invent a repair to fill the file.

7. Per-candidate `image-review.json` — one entry for every unique image URL used in the final HTML, including hero and CSS-background images. Each entry includes `url`, `source_type`, `source_page_or_pool`, `observed_subject`, `intended_section`, `relevant` (boolean), `crop_ok` (boolean), `alt_accurate` (boolean), `alt_text`, `reviewer_or_method`, `evidence_path`, and `notes`. For skill runs also record `discovered_url`, `canonical_url`, `source_width`, `source_height`, `requested_width`, `rendered_css_width`, `resolution_status` (`PASS`, `FAIL`, `BLOCKED`, or `UNVERIFIED`), and a concise `resolution_finding`; use `null` for dimensions that could not be verified. Top-level fields include `candidate_id`, `html_sha256`, `status`, `images`, `missing_image_urls`, and `issues`. For a source image not actually inspected, use `UNVERIFIED` and leave observed subject empty; byte validation is not visual review. A skill image-review PASS requires each used image's relevance, crop, alt, and resolution checks to pass with evidence. For fixed fallback images, never claim a subject observation, license, or reuse permission without direct evidence.

8. Per-candidate `visual-review.json` — human/visual design review. Include `candidate_id`, `html_sha256`, `status`, `checks` for `first_screen_hierarchy`, `section_rhythm`, `typography`, `business_specificity`, and `footer` (`passed` boolean or null only when unverified, plus a concise finding), `blocking_defects`, `screenshots` (viewport, width, height, path, and HTML digest), `reviewer_or_method`, `reviewed_at`, and `issues`. Skill records additionally include `design_scorecard` with exactly `is_advisory: true`, `not_scored`, `weighted_total`, and `scores`. `scores` must be keyed exactly by `first_screen_impact`, `business_specificity`, `typography_hierarchy`, `image_composition`, `section_rhythm_spacing`, `mobile_experience`, and `conversion_clarity`; each item contains `score`, the exact `weight` from `qa-requirements.md`, and a finding. When rendered visual review did not occur, set `not_scored: true`, every score and `weighted_total` to null, preserve the exact keys and weights, and explain UNVERIFIED in each finding. When scored, use numeric 0–5 scores and calculate `weighted_total` from 0–100. Never use `criteria` or zero placeholders for an unscored review. The scorecard is advisory and never overrides a blocking check. Require desktop and mobile screenshot evidence tied to the exact candidate digest. If no genuine visual inspection occurred, status is UNVERIFIED; do not infer review from generated markup or successful browser loading.

9. Per-candidate `final-status.json` — authoritative completion decision. Include `candidate_id`, `html_path`, `html_bytes`, `html_sha256`, `package_checks`, `static_qa_status`, `browser_qa_status`, `repair_status`, `image_review_status`, `visual_review_status`, `blocking_failures`, `advisories`, `failure_summary`, `evidence_paths`, `final_status`, and `finalized_at`. The final status is PASS only if the file/package checks and every required blocking QA and review gate pass for the same HTML digest. Any missing required record or digest mismatch is BLOCKED; any failed blocking check is FAIL. Keep advisory findings visible without overriding a blocking failure.

**Run and candidate completion rules**

- Write evidence incrementally: source capture and facts first; generation context and candidate inputs before generation; repair records whenever a repair is attempted; QA and screenshot records after each test; image and visual review records after actual review; final status last.
- Maintain a concise failure summary for every unsuccessful candidate, listing failed check IDs, the observed reason, attempted repairs, and what remains unresolved. Do not discard failed candidates' evidence when a later candidate succeeds.
- The three final HTML files and their evidence records must agree on candidate ID, output path, and SHA-256. Verify that agreement before reporting completion.
- Run `python validate_evidence.py <output-root>` after the records and deliverables are final. It checks digest and byte-count agreement, candidate/run identity, required records for passing candidates, QA/review linkage, score arithmetic, and the three-slot PASS rule. Resolve every reported FAIL before claiming completion; a missing optional schema library is reported as UNVERIFIED and does not mean the cross-record checks were skipped.
- If a requested evidence artifact cannot be created in the current environment, record it as BLOCKED/UNVERIFIED with the reason and identify which parity gate remains unmet. Do not claim the workflow's structured evidence parity merely because a prose summary was returned.
