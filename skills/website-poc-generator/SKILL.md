---
name: website-poc-generator
description: Generate three source-grounded standalone HTML website proof-of-concept pages for a small business and assess them with static checks and browser QA available in the active ChatGPT session.
---

# Website POC Generator

## Goal
Given an existing business website URL, create exactly three independent files:
- `candidate-forty.html`
- `candidate-landed.html`
- `candidate-story.html`

Each file is a complete HTML5 document with all CSS in one embedded `<style>` element. Keep this standalone output format; do not emit HTML/CSS chunks, separate stylesheets, build steps, or shared runtime dependencies. Standalone packaging must meet the source, design, evidence, asset, and ChatGPT-native QA requirements below.

## Inputs
Required: existing business website URL. If absent, ask only for the URL before proceeding.

Optional: business name when unclear; additional source URLs or user facts; output directory or naming preference. Reuse facts already provided in the conversation; do not ask the user to repeat them.

## Workflow

Use the following compact sequence. Open linked references at the phase where they apply; do not load every detailed reference before preflight.

### 0. Preflight and execution profile

This skill targets an unattended ChatGPT session. Read [the runtime capability matrix](references/chatgpt-runtime-capability-matrix.md) and preflight Python, Chromium/Playwright, exact-byte rendering, writable downloadable output, and screenshots once before source research. Use a fresh run-specific output directory and verify write/read/delete access with a canary before doing generation work. Use Playwright's `async with` lifecycle and the active notebook loop correctly; see the runtime matrix. Perform only the in-session QA defined in [QA requirements](references/qa-requirements.md), using a compact Python cell written in this session. Validate the QA code before trusting its results: safely construct HTML strings, CSS, and JavaScript; make missing geometry explicit; stop after any failed cell; and distinguish harness errors from candidate check failures. Do not repeat deterministic failures without changing the harness or inputs. Do not fetch GitHub runner chunks, transfer repository scripts into Python Run, invoke workflow validators, or attempt the official 27-check suite. Test exact saved bytes at 1440×900 and 390×844; also measure contact layout at 768×900. Tie every result and screenshot to its SHA-256. When a contact form exists, capture and inspect focused desktop and mobile contact screenshots. If a capability is unavailable, continue generation and report only the checks that depend on it as BLOCKED; do not repeatedly retry a failed preflight.

Image prefetch is not a prerequisite for generation or native QA. For Wix, preserve the discovered rendition URL in evidence and canonicalize its observed `/media/<asset-id>/v1/...` path to `/media/<asset-id>` in production HTML; never embed image bytes. Do not repeat known Wix retrieval probes for this runtime profile. Keep image-content status UNVERIFIED when pixels are unavailable, but do not let this block static, layout, geometry, contrast, or interaction QA. Screenshots with missing images are layout-only and cannot support claims about image relevance, crop, resolution, or alt accuracy. Never request credentials, submit a business form, or change the source site.

The skill lifecycle is 3 initial slot attempts plus at most 3 targeted retries, one per failed slot.

### 1. Establish verified business inputs

Follow [source research and contact rules](references/source-research.md) and [image policy](references/image-policy.md). Inventory source image references with discovered and canonical URLs, alt text, source page/section, and any dimensions encoded in a CDN rendition. Use canonical Wix original URLs in candidate HTML; do not embed image bytes. Image metadata can guide placement but does not verify unseen pixels. Preserve fact-level provenance and form fields, and never invent claims. Remote image retrieval, pixel review, image-relevance review, source resolution, and reuse-term verification are outside this skill's native QA; report them as UNVERIFIED without probing the known Wix limitation or asking for an external handoff.

### 2. Assign design directions and generate

Create exactly one candidate per fixed slot in order: Forty, Landed, Story. Read [template specifications](references/template-specifications.md) and [candidate design/generation guidance](references/design-system.md). Preserve each template's signature, use complete bundled assets as references, and do not carry demo filler into business output.

### Mobile navigation control

Every candidate with responsive navigation must use one real `<button type="button">` menu control with a valid `aria-controls` reference to the mobile `<nav>`, `aria-expanded="false"` initially, and an accessible name such as `aria-label="Open navigation"`. Its three visible hamburger bars must be three direct child spans, each marked `aria-hidden="true"`; use this structure because the in-session Chromium check locates and measures exactly those three spans:

```html
<button type="button" class="menu-toggle" aria-controls="primary-menu"
        aria-expanded="false" aria-label="Open navigation">
  <span aria-hidden="true"></span>
  <span aria-hidden="true"></span>
  <span aria-hidden="true"></span>
</button>
```

The click handler must keep `aria-expanded` and mobile-nav visibility in sync, open on Enter/Space, close on Escape, and return focus to the menu button after Escape. Give the button a visible `:focus-visible` indicator and make the bars at least 10px wide and 1px high. Do not use two bars, nested bar spans, or CSS pseudo-elements in place of the three measured spans. Run both the static hamburger check and browser interaction checks on the exact final HTML.

### CTA contrast and hero coverage

Treat both requirements as hard, blocking rules on the exact final HTML at desktop and mobile viewports:

- Every visible CTA must have measured text contrast of at least **4.5:1** against its rendered background. This includes the **Contact** CTA in the header/navigation, even when it is styled as a nav link rather than a button. On a light surface use dark text; use white text only on a sufficiently dark fill. Do not infer contrast from the assigned palette—use the browser's computed colors and fail when the background cannot be measured reliably.
- The **Landed** `#banner` hero media layer must cover the complete hero rectangle at both desktop and mobile sizes, within the runner's 2 CSS pixel edge tolerance. Size and position the media layer to fill the hero and use an intentional `cover` crop. A partial-width image or uncovered band fails. Rerun the geometry check after any repair.

### Contact-form controls

Mirror whether the source site has a contact form: if the source has none, do not add a form or inquiry fields; if it has one, include a source-grounded form and preserve its identifiable non-upload fields. **No candidate may offer file upload in any form.** Never include a file picker (`<input type="file">`), upload/attachment button, drop zone, or upload label; remove both the source file input and its associated visible label/control. Keep the source-based contact form and all other identifiable non-upload fields. Record each omitted source upload in candidate evidence (`reason: "POLICY_NO_FILE_UPLOAD"`, with source position and evidence locator); exclude it from required field parity and set `exact_full_form_parity: false` when any source control is excluded. Keep the form's no-op CTA and “nothing is sent or stored” disclosure. The blocking static check `no_file_upload_controls` must fail for any file input or remaining upload/attachment option or label anywhere in the candidate.

### 3. Validate, review, and repair

Apply [QA requirements](references/qa-requirements.md) to each candidate and exact final bytes. Repair every safe, independently verifiable native QA failure before packaging, even when image pixels are unavailable. Apply only bounded repairs and slot-specific retries as defined in [recovery procedures](references/recovery-procedures.md). A changed HTML file invalidates its prior digest-bound checks; rerun all affected native checks.

Run only the native static and Chromium checks in [QA requirements](references/qa-requirements.md), against the exact final candidate bytes. Do not retrieve or execute the official workflow runner or produce a separate image-review request. Use canonical Wix original URLs in production HTML and retain discovered renditions as provenance. Do not replace unavailable remote images with unrelated or guessed assets. If they do not load, mark remote images as unavailable under the known runtime limitation and classify screenshots as layout-only; continue geometry, contrast, navigation, interaction, and static checks.

### 4. Package and decide completion

Follow [the ChatGPT-native deliverable and evidence contract](references/evidence-contracts.md). Run the in-session static checks and available Chromium checks from [QA requirements](references/qa-requirements.md); do not run repository validators. Report one `native_qa_status` for the actual ChatGPT QA scope, plus the informational `image_content_status`. `native_qa_status: PASS` means the exact final files passed every required static and executable browser check in this skill; it does not claim image pixels were reviewed. If browser capability is unavailable, deliver the candidates with `native_qa_status: PARTIAL` when static checks pass and rendered checks are blocked. Use `BLOCKED` only when exact candidate bytes or basic QA execution are unavailable; use `FAIL` for an executed required check that remains failed.

### 5. Save and report

Save exactly the three named standalone HTML files and `evidence/native-qa.json` in the requested directory or the current task output location. Report per-file byte count and SHA-256, static and browser checks actually run, template conformance, source/form evidence, desktop/mobile measurements, screenshot classification, repairs, and evidence paths. State that image content remains UNVERIFIED when it was not visible. Identify any native check that could not run; do not list the official 27-check suite or external review as a required missing step.

## Completion gate

The task is complete for this skill when all three named files exist, are independent standalone HTML documents, and pass the ChatGPT-native static and available desktop, tablet contact-layout, and mobile Chromium checks against their exact final digests. Any post-QA edit invalidates affected results until rerun. Missing image pixels do not block this result; record `image_content_status: UNVERIFIED` and do not claim image approval. If browser QA is unavailable, deliver the files with a `PARTIAL` result and identify the unavailable checks. Do not report or imply workflow/official-suite QA.

## Safe output rule

Do not commit, publish, deploy, or overwrite a business website. The skill creates local POC files only unless the user separately requests a repository write or deployment.
