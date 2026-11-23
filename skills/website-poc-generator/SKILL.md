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

This skill targets the ChatGPT UI. A connected GitHub app supplies repository access, not a shell, Playwright, screenshot export, or file-writing capability. Read [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md), run its bundled renderer preflight in this same target session before source research, and record each capability with observed evidence. The bundled probe tests native HTML Preview separately from exact-byte identity, pixel visibility, viewport control, screenshot capture, image loading, geometry, JavaScript, and interactions. When Python code-block Run is available and can receive the exact saved files, run the bundled validators for fast static/digest/evidence feedback; do not wait for a GitHub Actions round trip. Use HTML code-block Preview only when the preflight verifies the exact candidate input and the preview is available for genuine inspection; record its limited scope. Neither capability alone proves full desktop/mobile browser QA. Choose `full_parity` only when all required capabilities are available and used; otherwise use the appropriate limited profile. If the preflight cannot establish an in-session renderer, use limited mode: save useful standalone drafts and run every available static/file check, but mark browser QA and visual review BLOCKED, leave the overall run BLOCKED, and list the smallest missing runtime capability. Do not promote static DOM inspection or preview success text to rendered QA. GitHub access is for reading unless the user separately requests a repository write. Do not infer file writing, browser automation, screenshot capture, or image-byte validation from a signed-in browser or GitHub connection. Never request credentials, submit a business form, or change the source site.

The skill lifecycle is 3 initial slot attempts plus at most 3 targeted retries, one per failed slot. It is intentionally independent of the Action's workflow-specific 12+12 lifecycle.

### 1. Establish verified business inputs

Follow [source research and contact rules](references/source-research.md) and [image policy](references/image-policy.md). Preserve fact-level provenance and form fields, never invent claims, and keep image load/byte validation separate from visual relevance and license evidence.

### 2. Assign design directions and generate

Create exactly one candidate per fixed slot in order: Forty, Landed, Story. Read [template specifications](references/template-specifications.md) and [candidate design/generation guidance](references/design-system.md). Preserve each template's signature, use complete bundled assets as references, and do not carry demo filler into business output.

### 3. Validate, review, and repair

Apply [QA requirements](references/qa-requirements.md) to each candidate and exact final bytes. Repair every safe, independently verifiable static failure before packaging, even when unrelated browser or image gates remain blocked. Apply only bounded repairs and slot-specific retries as defined in [recovery procedures](references/recovery-procedures.md). A changed HTML file invalidates its prior digest-bound checks and reviews; rerun all affected gates.

For browser screenshot QA, first build a disposable copy of each exact production candidate with every external image reference embedded as a `data:` URI. Collect `img`/`source` `src` and `srcset`, lazy image attributes, posters, inline styles, and embedded CSS backgrounds. Fetch the exact referenced assets, verify successful HTTP responses and recognized image bytes, then have Chromium decode each embedded image and record its natural dimensions and SHA-256. Never replace or rewrite the production candidate; keep the embedded copy outside the deliverable/package and exclude it from any GitHub commit. If any referenced asset cannot be fetched, validated, embedded, or decoded at either viewport, mark the image gate and browser visual QA BLOCKED. Screenshots may be retained as layout diagnostics but cannot count as image or visual review evidence.

### 4. Package and decide completion

Follow [the standalone deliverable and evidence contract](references/evidence-contracts.md). Run `validate_candidates.py` and `validate_evidence.py` when code execution is available. A structural PASS is not a browser, accessibility, image, or visual PASS. Return drafts with explicit BLOCKED/UNVERIFIED gates when the session cannot produce or inspect exact saved bytes; do not imply full completion.

### 5. Save and report

Save exactly the three named, independently verified standalone HTML files in the requested directory, or the current task output location if none was specified. Report per-file existence, byte count, SHA-256, standalone/dependency status, checks actually run against exact bytes, template conformance, source evidence, image/form limitations, desktop/mobile findings, repairs, and evidence paths. Identify unrun checks and unresolved failures.

## Completion gate

Do not call the task complete or feature-parity compliant unless all three named files exist, are nonempty independent HTML documents with their CSS embedded, pass standalone and per-file validity audits, and every required design, source-evidence, template, final-file QA, and structured-evidence gate passes against the exact delivered bytes. The run index and candidate records must agree on candidate IDs and final HTML digests. Any post-QA edit invalidates that file's final QA status until rerun. Missing tools, evidence, references, or assets must be disclosed as BLOCKED/UNVERIFIED; never present an inspired substitute as template-compliant.

## Safe output rule

Do not commit, publish, deploy, or overwrite a business website. The skill creates local POC files only unless the user separately requests a repository write or deployment.
