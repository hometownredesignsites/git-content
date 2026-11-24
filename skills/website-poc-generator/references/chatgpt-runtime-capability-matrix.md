# ChatGPT-native runtime and QA

This skill runs entirely in the active ChatGPT session. Its required QA is limited to checks that session can perform against the exact saved candidate bytes. Do not retrieve or reconstruct GitHub runner chunks, transfer repository scripts into Python Run, invoke the official 27-check suite, or depend on another person, app, or external service for a passing result.

## One-time session preflight

Before generation, check only the capabilities this run needs:

1. Can this session save the three HTML files and evidence to a downloadable output location?
2. Is Python Run available, and can it read the exact saved bytes and calculate SHA-256?
3. Is Playwright importable, and can it launch an installed Chromium? If the managed browser is missing, try an existing system Chromium executable once. Do not install packages or browsers.
4. Can Chromium accept the exact HTML using `page.set_content()`, set 1440×900 and 390×844 viewports, return measurements, and save screenshots?

Use the active notebook event loop correctly: `await main()` when it is already running; do not call `asyncio.run()` in a running loop. Do not wait for network idle. Record the observed capabilities once in `evidence/native-qa.json`; do not repeat a failed preflight during the same run.

If Python or Chromium is unavailable, continue generation. Run whatever exact-byte static checks the session supports and report browser checks as BLOCKED. Never infer a browser pass from HTML source or screenshots from another session.

## Native QA implementation

Write a compact Python cell in the active session using standard-library HTML parsing and installed Playwright. The cell must consume the exact saved HTML bytes, verify their hash before and after QA, and emit per-candidate results. It must not import repository scripts or require files from Codex. The complete required check set is in [QA requirements](qa-requirements.md).

Use `page.set_content(exact_html)` when it works. If the environment cannot render the exact bytes, report rendered checks unavailable; do not silently test a reconstructed or different file. Capture and save one desktop and one mobile screenshot for every candidate when supported. Inspect screenshot pixels only when the session actually exposes them. Missing-remote-image screenshots are layout evidence only.

## Known Wix image limitation

This ChatGPT runtime has previously discovered Wix image URLs but failed to display or load their pixels through the tested image-open and Chromium paths. Follow [image policy](image-policy.md): do not repeat thumbnail, DNS, HTTP, APIRequestContext, or Chromium image probes for the same runtime profile unless capabilities materially change or the user asks for a diagnostic. Do not ask the user to reconfirm this limitation. Keep canonical source URLs in production HTML, use alt text and source context only as relevance hints, and report image-content status as UNVERIFIED. This does not block the native structural/layout QA pass.

## Result vocabulary

- `native_qa_status: PASS`: all required exact-byte static checks and all available required desktop/mobile browser checks pass for all three final files.
- `native_qa_status: FAIL`: an executed required check fails after the allowed repair/retest cycle.
- `native_qa_status: PARTIAL`: generation and static checks pass, but a required browser capability is unavailable.
- `native_qa_status: BLOCKED`: exact candidate bytes cannot be read or the required checks cannot be run at all.
- `image_content_status: UNVERIFIED`: image pixels, relevance, crop, original resolution, or reuse terms were not established. This is informational and never blocks native QA.

Do not report a separate official-suite, full-parity, or external-review status. Those checks are outside this skill's ChatGPT-native QA scope.
