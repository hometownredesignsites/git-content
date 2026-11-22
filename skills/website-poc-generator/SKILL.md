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

This skill targets ChatGPT UI. A connected GitHub app supplies repository access, not a shell, code runner, Playwright, screenshot export, or file-writing capability. Read [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md), inventory the tools actually exposed, and record capability evidence before source research. Choose `full_parity` only when all required capabilities are available and used; otherwise use the appropriate limited profile. Missing blocking tools mean draft-only work and a BLOCKED/UNVERIFIED completion state. GitHub access is for reading unless the user separately requests a repository write. Do not infer code execution, file writing, browser automation, screenshot capture, or image-byte validation from a signed-in browser or GitHub connection. Never request credentials, submit a business form, or change the source site.

The skill lifecycle is 3 initial slot attempts plus at most 3 targeted retries, one per failed slot. It is intentionally independent of the Action's workflow-specific 12+12 lifecycle.

### 1. Establish verified business inputs

Follow [source research and contact rules](references/source-research.md) and [image policy](references/image-policy.md). Preserve fact-level provenance and form fields, never invent claims, and keep image load/byte validation separate from visual relevance and license evidence.

### 2. Assign design directions and generate

Create exactly one candidate per fixed slot in order: Forty, Landed, Story. Read [template specifications](references/template-specifications.md) and [candidate design/generation guidance](references/design-system.md). Preserve each template's signature, use complete bundled assets as references, and do not carry demo filler into business output.

### 3. Validate, review, and repair

Apply [QA requirements](references/qa-requirements.md) to each candidate and exact final bytes. Apply only safe, bounded repairs and slot-specific retries as defined in [recovery procedures](references/recovery-procedures.md). A changed HTML file invalidates its prior digest-bound checks and reviews; rerun all affected gates.

### 4. Package and decide completion

Follow [the standalone deliverable and evidence contract](references/evidence-contracts.md). Run `validate_candidates.py` and `validate_evidence.py` when code execution is available. A structural PASS is not a browser, accessibility, image, or visual PASS. Return drafts with explicit BLOCKED/UNVERIFIED gates when the session cannot produce or inspect exact saved bytes; do not imply full completion.

### 5. Save and report

Save exactly the three named, independently verified standalone HTML files in the requested directory, or the current task output location if none was specified. Report per-file existence, byte count, SHA-256, standalone/dependency status, checks actually run against exact bytes, template conformance, source evidence, image/form limitations, desktop/mobile findings, repairs, and evidence paths. Identify unrun checks and unresolved failures.

## Completion gate

Do not call the task complete or feature-parity compliant unless all three named files exist, are nonempty independent HTML documents with their CSS embedded, pass standalone and per-file validity audits, and every required design, source-evidence, template, final-file QA, and structured-evidence gate passes against the exact delivered bytes. The run index and candidate records must agree on candidate IDs and final HTML digests. Any post-QA edit invalidates that file's final QA status until rerun. Missing tools, evidence, references, or assets must be disclosed as BLOCKED/UNVERIFIED; never present an inspired substitute as template-compliant.

## Safe output rule

Do not commit, publish, deploy, or overwrite a business website. The skill creates local POC files only unless the user separately requests a repository write or deployment.
