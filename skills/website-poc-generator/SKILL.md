---
name: website-poc-generator
description: Generate three source-grounded standalone HTML website proof-of-concept pages for a small business, matching the website workflow's source preparation, design brief, template structure, and QA gates.
---

# Website POC Generator

## Goal
Given an existing business website URL, create exactly three independent files:
- `candidate-forty.html`
- `candidate-landed.html`
- `candidate-story.html`

Each file is a complete HTML5 document with all CSS in one embedded `<style>` element. Keep this standalone output format; do not emit HTML/CSS chunks, separate stylesheets, build steps, or shared runtime dependencies. Standalone packaging does not relax any workflow design, evidence, asset, or QA requirement below.

## Inputs
Required: existing business website URL. If absent, ask only for the URL before proceeding.

Optional: business name when unclear; additional source URLs or user facts; output directory or naming preference. Reuse facts already provided in the conversation; do not ask the user to repeat them.

## Workflow

Use the following compact sequence. Open linked references at the phase where they apply; do not load every detailed reference before preflight.

### 0. Preflight and execution profile

This skill targets an unattended ChatGPT session. Read [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md) and preflight the target session before source research. The preferred native QA path is the single-file `chatgpt_automation/scripts/browser_qa_standalone.py` runner: retrieve that exact file from the selected GitHub ref in this same ChatGPT session, record its commit/blob SHA, pass its exact source and the three final HTML strings into ChatGPT's Python Run, and invoke `run_chatgpt_candidates(...)`. This runs the existing 27 browser checks, image retrieval/validation/embedding, and both viewports without a checkout, sibling files, Codex-created assets, or a Codex-to-ChatGPT transfer. The runner stores the unchanged production HTML, candidate-specific JSON reports, image manifests, and screenshots in the Python session's output directory. Inspect the saved screenshot pixels when the Python surface makes them available. Never use an offline ZIP or earlier screenshots as a substitute for this in-session run.

Before relying on the runner, establish that Python Run is available, Playwright imports, Chromium launches, the output directory is writable, and saved PNGs can be inspected in this same target session. Compile the retrieved source before executing it. The standalone runner may import only Python standard-library modules and `playwright.sync_api`; it must not fetch code or imports from sibling repository files. Run it with the exact final HTML strings authored in that session, plus the source URL and original request. Its own image gate retrieves and verifies every exact referenced image, embeds a disposable copy, and blocks visual QA if retrieval or browser decode fails. If a required capability is missing, continue with useful drafts when possible but mark browser checks and visual review BLOCKED and the overall run BLOCKED. Preview preflight can provide additional evidence, but Preview success alone never establishes browser QA. Choose `full_parity` only when all required capabilities are available and used. GitHub remains read-only unless the user separately requests a repository write. Never request credentials, submit a business form, or change the source site.

The skill lifecycle is 3 initial slot attempts plus at most 3 targeted retries, one per failed slot. It is intentionally independent of the Action's workflow-specific 12+12 lifecycle.

### 1. Establish verified business inputs

Follow [source research and contact rules](references/source-research.md) and [image policy](references/image-policy.md). Preserve fact-level provenance and form fields, never invent claims, and keep image load/byte validation separate from visual relevance and license evidence.

### 2. Assign design directions and generate

Create exactly one candidate per fixed slot in order: Forty, Landed, Story. Read [template specifications](references/template-specifications.md) and [candidate design/generation guidance](references/design-system.md). Preserve each template's signature, use complete bundled assets as references, and do not carry demo filler into business output.

### 3. Validate, review, and repair

Apply [QA requirements](references/qa-requirements.md) to each candidate and exact final bytes. Repair every safe, independently verifiable static failure before packaging, even when unrelated browser or image gates remain blocked. Apply only bounded repairs and slot-specific retries as defined in [recovery procedures](references/recovery-procedures.md). A changed HTML file invalidates its prior digest-bound checks and reviews; rerun all affected gates.

For browser screenshot QA, run the retrieved, commit-pinned `browser_qa_standalone.py` source in ChatGPT Python Run. Pass the exact final candidate strings through `run_chatgpt_candidates`, rather than staging a repository checkout or transferring files from another application. The runner captures the exact production bytes and SHA-256, then creates a disposable copy with every external image reference embedded as a `data:` URI. It collects `img`/`source` `src` and `srcset`, lazy image attributes, posters, inline styles, and embedded CSS backgrounds; fetches the exact assets; verifies successful HTTP responses, image signatures/MIME, byte counts, and SHA-256; and confirms Chromium decode dimensions and image loading at desktop and mobile sizes. If retrieval fails in this target session, do not substitute another image source or accept a separately prepared bundle as proof of this automated workflow: mark image integrity and browser visual QA BLOCKED. Never replace or rewrite the production candidate; keep the embedded copy temporary. Screenshots from a failed image gate are layout diagnostics only.

### 4. Package and decide completion

Follow [the standalone deliverable and evidence contract](references/evidence-contracts.md). Run `validate_candidates.py` and `validate_evidence.py` when code execution is available. A structural PASS is not a browser, accessibility, image, or visual PASS. Return drafts with explicit BLOCKED/UNVERIFIED gates when the session cannot produce or inspect exact saved bytes; do not imply full completion.

### 5. Save and report

Save exactly the three named, independently verified standalone HTML files in the requested directory, or the current task output location if none was specified. Report per-file existence, byte count, SHA-256, standalone/dependency status, checks actually run against exact bytes, template conformance, source evidence, image/form limitations, desktop/mobile findings, repairs, and evidence paths. Identify unrun checks and unresolved failures.

## Completion gate

Do not call the task complete or feature-parity compliant unless all three named files exist, are nonempty independent HTML documents with their CSS embedded, pass standalone and per-file validity audits, and every required design, source-evidence, template, final-file QA, and structured-evidence gate passes against the exact delivered bytes. The run index and candidate records must agree on candidate IDs and final HTML digests. Any post-QA edit invalidates that file's final QA status until rerun. Missing tools, evidence, references, or assets must be disclosed as BLOCKED/UNVERIFIED; never present an inspired substitute as template-compliant.

## Safe output rule

Do not commit, publish, deploy, or overwrite a business website. The skill creates local POC files only unless the user separately requests a repository write or deployment.
