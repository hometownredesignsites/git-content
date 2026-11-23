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

This skill targets an unattended ChatGPT session. Read [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md) and preflight the target session before source research. For official browser QA, assemble the runner from eight small, ordered text chunks in `chatgpt_automation/scripts/browser_qa_payload_chunks/`, described by `browser_qa_payload_manifest.json`. Retrieve the manifest and chunks from one selected GitHub commit in the same ChatGPT session, place each data-only chunk into a separate Python Run cell, verify every chunk/payload/source digest, then compile the complete runner and call `run_chatgpt_candidates(...)` with exact candidate bytes. This runs the existing 27 browser checks without a checkout, sibling files, or cross-application customer-file transfer. If the GitHub-to-Python bridge still cannot transfer chunk text, stop retrying and use the limited native assessment in [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md). That path checks exact saved candidate bytes, document structure, template geometry, interactions, and desktop/mobile rendering with Python and Chromium while treating unreachable remote images as a separately pending review. It may earn a `native_limited_status: PASS`; it is not the official 27-check suite or full image-aware visual approval. Never use an offline ZIP or earlier screenshots as a substitute for the current in-session run. The compact single-file wrapper remains a shorter-transfer alternative when Python Run accepts it intact.

Before relying on the official runner, establish that Python Run is available, Playwright imports, Chromium launches (use the system executable fallback if Playwright's managed browser is absent), the output directory is writable, and saved PNGs can be inspected in this same target session. Reassemble and verify the ordered runner chunks before compiling the exact runner source. Run it with the exact final HTML bytes authored or saved in that same session, plus the source URL and original request. Image prefetch is not a prerequisite for generating candidates or earning a native limited pass. Preserve the source image URLs in production HTML and record exact URL/alt/source-location metadata; do not claim that alt text establishes the unseen image's content. If image retrieval fails, render the exact candidate at both viewports anyway, record image requests/decode as unavailable, and assess only the structure, measurable layout, interactions, and visible non-image content that the runtime can verify. Never count a screenshot with missing images as image or full visual approval. If exact files or Chromium are unavailable, report only the capability that is actually blocked; do not make image-network failure invalidate successful generation or static checks. Use `native_limited_status: PASS` only when all required limited checks pass for all three exact candidate digests, and keep image-content review `EXTERNAL_PENDING` until an external image-capable reviewer supplies digest-bound evidence. Choose `full_parity` only when every required capability is available and used. GitHub remains read-only unless the user separately requests a repository write. Never request credentials, submit a business form, or change the source site.

The skill lifecycle is 3 initial slot attempts plus at most 3 targeted retries, one per failed slot. It is intentionally independent of the Action's workflow-specific 12+12 lifecycle.

### 1. Establish verified business inputs

Follow [source research and contact rules](references/source-research.md) and [image policy](references/image-policy.md). Before generation, inventory source image references and their metadata (URL, alt text, source page/section, and dimensions encoded in a CDN rendition when available). Image metadata may guide candidate placement but does not prove the photograph's subject. Preserve fact-level provenance and form fields, never invent claims, and keep URL discovery, HTTP/byte validation, pixel inspection, visual relevance, and license evidence separate. Image network failure does not block candidate generation; it leaves image-byte and image-content review pending and triggers the external-review handoff described in the runtime matrix.

### 2. Assign design directions and generate

Create exactly one candidate per fixed slot in order: Forty, Landed, Story. Read [template specifications](references/template-specifications.md) and [candidate design/generation guidance](references/design-system.md). Preserve each template's signature, use complete bundled assets as references, and do not carry demo filler into business output.

### 3. Validate, review, and repair

Apply [QA requirements](references/qa-requirements.md) to each candidate and exact final bytes. Repair every safe, independently verifiable static failure before packaging, even when image retrieval or external image-content review is pending. Apply only bounded repairs and slot-specific retries as defined in [recovery procedures](references/recovery-procedures.md). A changed HTML file invalidates its prior digest-bound checks and reviews; rerun all affected gates.

For browser QA, first attempt the commit-pinned 27-check runner when its source can be transferred and verified. If that is unavailable, use the bounded native limited assessment in the runtime matrix against exact candidate bytes. Do not require image downloads for that limited assessment. Keep production image URLs intact; do not replace failed remote images with unrelated or guessed assets. Screenshots captured while images are unavailable support only layout/structure findings. Produce an `external-image-review-request.json` containing each final HTML SHA-256 and its unique image URLs, alt text, source-page provenance, intended section, and known rendition dimensions; this lets a separate network-enabled process check the same candidate and assets. The handoff is a request, not verification. Do not claim external image checks until results tied to the exact candidate digest have been received.

### 4. Package and decide completion

Follow [the standalone deliverable and evidence contract](references/evidence-contracts.md). Run `validate_candidates.py` and `validate_evidence.py` when code execution is available. Report separate statuses for (a) candidate generation and native structure/layout assessment, (b) official full-parity QA, and (c) external image-content review. A `native_limited_status: PASS` means the exact HTML files passed the stated static and available Chromium structure/layout checks; it does not mean the image assets loaded, were visually inspected, or passed full workflow QA. Use BLOCKED only for a capability needed by the specific status being reported. If exact saved bytes or basic parsing are unavailable, generation/structure cannot pass. If Chromium is unavailable, structure may still pass while rendered-layout remains BLOCKED. Do not imply full completion from a limited pass.

### 5. Save and report

Save exactly the three named, independently verified standalone HTML files in the requested directory, or the current task output location if none was specified. Report per-file existence, byte count, SHA-256, standalone/dependency status, checks actually run against exact bytes, template conformance, source evidence, image/form limitations, desktop/mobile findings, repairs, and evidence paths. Identify unrun checks and unresolved failures.

## Completion gate

Do not call the task full-parity complete unless all three named files exist, are nonempty independent HTML documents with their CSS embedded, pass standalone and per-file validity audits, and every required design, source-evidence, template, final-file QA, and structured-evidence gate passes against the exact delivered bytes. The run index and candidate records must agree on candidate IDs and final HTML digests. Any post-QA edit invalidates that file's digest-bound checks until rerun. A limited run may report `native_limited_status: PASS` and be considered a successful generation/structure assessment when all limited checks pass, while recording `official_27_check_status: UNVERIFIED` and `external_image_content_status: EXTERNAL_PENDING`. Never convert the limited pass into an overall full-parity PASS or describe unavailable image content as reviewed. Missing tools or evidence should block only the status that depends on them.

## Safe output rule

Do not commit, publish, deploy, or overwrite a business website. The skill creates local POC files only unless the user separately requests a repository write or deployment.
