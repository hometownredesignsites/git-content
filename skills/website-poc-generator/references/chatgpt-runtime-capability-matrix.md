# ChatGPT-native runtime and QA

This skill runs entirely in the active ChatGPT session. Its required QA is limited to checks that session can perform against the exact saved candidate bytes. Do not retrieve or reconstruct GitHub runner chunks, transfer repository scripts into Python Run, invoke the official 27-check suite, or depend on another person, app, or external service for a passing result.

## One-time session preflight

Before generation, check only the capabilities this run needs:

1. Can this session save the three HTML files and evidence to a downloadable output location? The first Python cell must be an isolated output preflight only; do not combine directory creation with imports or candidate-generation logic that could continue after a failure. Check the established downloadable root, create a fresh run-specific child directory and its `evidence/` subdirectory inside `try`, then create, read back, compare, and delete a canary file inside `evidence/`. Catch `OSError`/`PermissionError` from both `mkdir` and canary operations and print the blocked status to the chat; never try to write an error JSON into the denied directory. Do not reuse earlier run folders or try multiple sibling paths when the same root is denied. Use another path only if the runtime documents it as downloadable; never assume `/tmp` or the working directory is downloadable. If the exact artifact directory is not writable, stop before source research or candidate generation because the deliverables cannot be saved.

Use this shape, substituting only the runtime's documented downloadable root:

```python
from pathlib import Path
from uuid import uuid4

download_root = Path(DOCUMENTED_DOWNLOAD_ROOT)
run_dir = download_root / f"website-poc-{uuid4().hex[:12]}"
evidence_dir = run_dir / "evidence"
try:
    if not download_root.is_dir():
        raise OSError(f"Download root is unavailable: {download_root}")
    evidence_dir.mkdir(parents=True, exist_ok=False)
    canary = evidence_dir / ".write-canary"
    canary.write_bytes(b"website-poc-output-preflight")
    if canary.read_bytes() != b"website-poc-output-preflight":
        raise OSError("Output canary read-back mismatch")
    canary.unlink()
except OSError as exc:
    output_storage_ok = False
    print({"output_storage": "BLOCKED", "path": str(evidence_dir),
           "error_type": type(exc).__name__, "error": str(exc)})
else:
    output_storage_ok = True
    print({"output_storage": "PASS", "path": str(run_dir)})
```

Do not execute the source-research or generation cells unless `output_storage_ok` is `True`.
2. Is Python Run available, and can it read the exact saved bytes and calculate SHA-256?
3. Is Playwright importable, and can it launch an installed Chromium? If the managed browser is missing, try an existing system Chromium executable once. Do not install packages or browsers.
4. Can Chromium accept the exact HTML using `page.set_content()`, set 1440×900 and 390×844 viewports for the full check set, measure contact layout at 768×900, and save screenshots?

Use the active notebook event loop correctly: `await main()` when it is already running; do not call `asyncio.run()` in a running loop. Prefer `async with async_playwright() as p:` so the Playwright manager is cleaned up by its context manager. Close the browser in a `finally` block, but do not additionally call `p.stop()` from that pattern. Read `browser.version` as the documented string property, without calling or awaiting it. Do not wait for network idle. Record the observed capabilities once in `evidence/native-qa.json`; do not repeat a failed preflight during the same run.

If Python or Chromium is unavailable, continue generation when output storage is available. Run whatever exact-byte static checks the session supports and report browser checks as BLOCKED. If output storage is blocked, stop before source research and generation. Never infer a browser pass from HTML source or screenshots from another session.

## Native QA implementation

Write a compact Python cell in the active session using standard-library HTML parsing and installed Playwright. The cell must consume the exact saved HTML bytes, verify their hash before and after QA, and emit per-candidate results. It must not import repository scripts or require files from Codex. The complete required check set is in [QA requirements](qa-requirements.md).

### Cell construction and harness failure rules

- Do not apply Python `str.format()` or an f-string to raw CSS or JavaScript templates containing braces. CSS/JS braces are interpreted as formatting fields and can raise `KeyError` or silently corrupt the source. Prefer plain string literals plus explicit, narrowly scoped sentinel replacement (for example, replace a unique `__PALETTE__` token), or build CSS/JS with a safe dedicated serializer. Assert each sentinel occurs exactly once before replacement and none remain afterward.
- Build long HTML fragments with triple-quoted templates or small functions that return complete fragments; avoid giant single-quoted concatenations where ordinary apostrophes in business copy can terminate a string. When source code itself is assembled as text for `exec`, call `compile(source, filename, "exec")` before executing it. On a `SyntaxError`, stop before writing candidate files and repair the quoting in the generator.
- If a Python helper is held inside an outer triple-quoted source string for `compile()`, write the quotes intended for the generated source literally; do not leave escaped quote sequences such as `\\\"` in the compiled text. Prefer defining helpers directly in a normal Python cell when source-string compilation is unnecessary. Smoke-test compiled helper source before using it in candidate QA.
- Build and validate all three candidate strings before writing any candidate file. If generation raises, stop dependent cells; do not continue with stale notebook variables or partial files. After fixing the failing cell, rerun generation from a clean state and confirm all three candidates were created in the current run before QA.
- Treat an exact-string patch with zero matches as stale input, not as a candidate failure. Do not keep retrying a replacement map copied from an earlier run. Re-read the current source-derived asset inventory, compare actual URLs and IDs, then regenerate the mapping from those observed values. If an expected URL is absent or ambiguous, stop that patch and resolve the current mapping before changing HTML.
- Treat the QA harness as code that must be validated too. Construct the browser evaluator as one complete JavaScript expression, run a syntax smoke check (for example, `new Function("return (" + expression + ")")`) before the viewport loop, and test its measurement helpers on a minimal fixture. Only then run the full candidate matrix.
- Make computed-style parsing defensive. Color parsing, luminance, and contrast helpers must return an explicit unavailable result for unsupported, transparent, or malformed colors; never dereference a null parse result. An unmeasurable required contrast check is a check failure, but it must be reported as such rather than crashing the evaluator.
- Make geometry helpers defensive too. A missing element or unavailable rectangle must return an explicit `missing`/`unmeasurable` result; never subscript or destructure `None`. The check layer then classifies a missing required element as a candidate failure and an optional/unmeasurable metric as blocked, with selector and reason recorded.
- Catch and record errors per candidate and viewport so one bad evaluation does not erase earlier results. Distinguish `harness_error` (Python/JavaScript construction, syntax, or evaluator exception) from `candidate_check_failure` (a successfully executed check that found a violation). A harness error is not evidence that a candidate failed or passed. Repair the harness and rerun every affected candidate/viewport check before assigning the final QA status.
- If a cell fails, stop the dependent workflow at that point. Never present output from a later cell that relied on missing, stale, or partially initialized variables as current-run evidence. Do not rerun the same deterministic failure unchanged; inspect the traceback and inputs, change the harness or correct the stale input, syntax-check/smoke-test the change, then rerun the affected checks. If the same harness exception persists, stop instead of repeating it.

Use `page.set_content(exact_html)` when it works. If the environment cannot render the exact bytes, report rendered checks unavailable; do not silently test a reconstructed or different file. Capture and save one desktop and one mobile viewport screenshot for every candidate when supported, plus focused contact-section screenshots when a source form exists. Inspect screenshot pixels only when the session actually exposes them. Missing-remote-image screenshots are layout evidence only.

## Known Wix image limitation

This ChatGPT runtime has previously discovered Wix image URLs but failed to display or load their pixels through the tested image-open and Chromium paths. Follow [image policy](image-policy.md): do not repeat thumbnail, DNS, HTTP, APIRequestContext, or Chromium image probes for the same runtime profile unless capabilities materially change or the user asks for a diagnostic. Do not ask the user to reconfirm this limitation. Keep canonical source URLs in production HTML, use alt text and source context only as relevance hints, and report image-content status as UNVERIFIED. This does not block the native structural/layout QA pass.

## Result vocabulary

- `native_qa_status: PASS`: all required exact-byte static checks and all available required desktop, tablet contact-layout, and mobile browser checks pass for all three final files.
- `native_qa_status: FAIL`: an executed required check fails after the allowed repair/retest cycle.
- `native_qa_status: PARTIAL`: generation and static checks pass, but a required browser capability is unavailable.
- `native_qa_status: BLOCKED`: exact candidate bytes cannot be read or the required checks cannot be run at all.
- `image_content_status: UNVERIFIED`: image pixels, relevance, crop, original resolution, or reuse terms were not established. This is informational and never blocks native QA.

Do not report a separate official-suite, full-parity, or external-review status. Those checks are outside this skill's ChatGPT-native QA scope.
