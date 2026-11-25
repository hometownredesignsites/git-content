# ChatGPT-native deliverables and evidence

This evidence contract is limited to what the active ChatGPT session can create and verify. Do not require the workflow's normalized full-parity schema, repository validators, official 27-check suite, external image-review request, or other-app handoff.

## Deliverables

Save these independent files at the output root:

- `candidate-forty.html`
- `candidate-landed.html`
- `candidate-story.html`

Include `evidence/native-qa.json`, `evidence/index.md`, and candidate-specific QA artifacts. A ZIP may package these deliverables for download. Do not include temporary HTML copies, image payloads, debug transfer chunks, or unverified runner source.

Also maintain `evidence/run-state.json` as a resumable checkpoint. Update it after each completed phase and each candidate write/QA batch with the run ID, phase statuses, last completed candidate/viewport, artifact paths, and verified SHA-256 values. On a transient Python/analysis-service interruption, resume in the same output directory from this checkpoint after re-hashing referenced artifacts. This checkpoint records progress only; interrupted or unrun checks must never be represented as passing.

For source-present forms, also include focused `contact-desktop.png` and `contact-mobile.png` screenshots under each candidate's evidence directory. Omit these two files when the source has no contact form.

```text
website-poc-output/
  candidate-forty.html
  candidate-landed.html
  candidate-story.html
  evidence/
    index.md
    native-qa.json
    forty/desktop.png
    forty/mobile.png
    forty/contact-desktop.png
    forty/contact-mobile.png
    landed/desktop.png
    landed/mobile.png
    landed/contact-desktop.png
    landed/contact-mobile.png
    story/desktop.png
    story/mobile.png
    story/contact-desktop.png
    story/contact-mobile.png
```

Only list files that were actually written and verified. Use the user's requested output folder when specified; otherwise use a fresh run-specific directory in the session's documented downloadable output location. Verify that both the output root and `evidence/` are writable by creating, reading, comparing, and deleting a canary file before generation. Catch filesystem errors. If output storage is denied, report `output_storage: BLOCKED` in the response and stop; the denied location cannot hold an error JSON, and no evidence package may be claimed.

## `native-qa.json`

Record:

- `schema_version`, `run_id`, `created_at`, `source_url`, `runtime_profile: "chatgpt_native"`, and `native_qa_status` (`PASS`, `FAIL`, `PARTIAL`, or `BLOCKED`).
- One candidate entry per template with final path, byte count, SHA-256, static check results, browser/version when available, desktop/tablet/mobile measurements, interaction results, desktop/mobile viewport screenshots, focused contact-section screenshots when a source form exists, failures, and repairs.
- Session capability results for Python, Playwright, Chromium, exact-byte rendering, viewport control, screenshot capture, and screenshot pixel inspection.
- `image_content_status: "UNVERIFIED"` with a short reason when images could not be inspected. This is informational and not a candidate blocking check.

Each check reports `PASS`, `FAIL`, `BLOCKED`, or `UNVERIFIED`, a short result, and evidence such as a selector, measured value, file path, or runtime error. Do not include official-suite fields or claim repository validator execution.

## Final consistency

Re-read each delivered HTML file as bytes after QA and confirm its byte count and SHA-256 still match the report. If a file changed, rerun affected checks and replace stale screenshots. Confirm all three files exist and that every evidence path resolves. `native_qa_status: PASS` means only the static and in-session layout/geometry/interaction checks in [QA requirements](qa-requirements.md) passed; it does not imply image-content approval.
