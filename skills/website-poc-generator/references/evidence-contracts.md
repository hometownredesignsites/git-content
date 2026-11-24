# ChatGPT-native deliverables and evidence

This evidence contract is limited to what the active ChatGPT session can create and verify. Do not require the workflow's normalized full-parity schema, repository validators, official 27-check suite, external image-review request, or other-app handoff.

## Deliverables

Save these independent files at the output root:

- `candidate-forty.html`
- `candidate-landed.html`
- `candidate-story.html`

Include `evidence/native-qa.json`, `evidence/index.md`, and candidate-specific QA artifacts. A ZIP may package these deliverables for download. Do not include temporary HTML copies, image payloads, debug transfer chunks, or unverified runner source.

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
    landed/desktop.png
    landed/mobile.png
    story/desktop.png
    story/mobile.png
```

Only list files that were actually written and verified. Use the user's requested output folder when specified; otherwise use the session's downloadable output location.

## `native-qa.json`

Record:

- `schema_version`, `run_id`, `created_at`, `source_url`, `runtime_profile: "chatgpt_native"`, and `native_qa_status` (`PASS`, `FAIL`, `PARTIAL`, or `BLOCKED`).
- One candidate entry per template with final path, byte count, SHA-256, static check results, browser/version when available, desktop/mobile measurements, interaction results, screenshot paths/classifications, failures, and repairs.
- Session capability results for Python, Playwright, Chromium, exact-byte rendering, viewport control, screenshot capture, and screenshot pixel inspection.
- `image_content_status: "UNVERIFIED"` with a short reason when images could not be inspected. This is informational and not a candidate blocking check.

Each check reports `PASS`, `FAIL`, `BLOCKED`, or `UNVERIFIED`, a short result, and evidence such as a selector, measured value, file path, or runtime error. Do not include official-suite fields or claim repository validator execution.

## Final consistency

Re-read each delivered HTML file as bytes after QA and confirm its byte count and SHA-256 still match the report. If a file changed, rerun affected checks and replace stale screenshots. Confirm all three files exist and that every evidence path resolves. `native_qa_status: PASS` means only the static and in-session layout/geometry/interaction checks in [QA requirements](qa-requirements.md) passed; it does not imply image-content approval.
