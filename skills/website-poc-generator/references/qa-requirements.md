# ChatGPT-native QA requirements

This document defines the complete QA scope for this skill. Run only the exact-byte static checks and in-session Python/Chromium checks below. Do not invoke repository workflow scripts, the official 27-check suite, an external image reviewer, or a separate service. No external result is needed for a successful native QA pass.

## Exact-byte static checks

Run against each final saved HTML file and retain its byte count and SHA-256:

- Complete HTML5 document with doctype, `html`, `head`, `body`, closing tags, language, nonempty title, viewport metadata, exactly one `main`, exactly one nonempty `h1`, and a nonempty embedded stylesheet.
- No required external stylesheet, script, build step, sibling asset, or unresolved local file reference. IDs are unique and same-page fragments resolve.
- Required Forty, Landed, or Story template structure is present. Candidate CSS uses its assigned palette tokens. No visible template demo copy remains.
- All buttons have an accessible name. Every form field has a label or accessible name. The mobile menu uses one real `type="button"`, valid `aria-controls`/`aria-expanded`, and three direct `span[aria-hidden="true"]` bars.
- Contact-form presence and identifiable fields match captured source evidence. A source-absent form remains absent. A source-present form preserves identifiable non-upload fields and uses a clearly disclosed non-submitting demo Send control.
- No candidate offers file upload: reject file inputs, upload/attachment labels or controls, drop zones, and file-picker UI. Record each omitted source upload as `POLICY_NO_FILE_UPLOAD` with source position and evidence.
- Every Wix production image URL is canonicalized to the observed original `/media/<asset-id>` URL. Preserve the discovered transformed URL and source location in evidence. Do not embed image bytes.

A failed static check is a candidate failure. Never mark an unchecked static condition as PASS.

Validate the QA harness before using it for candidate decisions. A Python exception during candidate construction, JavaScript syntax error, or exception in the evaluator is a `harness_error`, not a candidate pass or candidate failure. Stop dependent cells, fix the harness, and rerun every affected check against the exact saved bytes. Make evaluator helpers tolerate unavailable computed colors and missing element rectangles; report an explicit unmeasurable or missing result instead of dereferencing `None` and aborting the run. A missing required page element is a candidate failure only after the evaluator returns that result cleanly. Keep errors/results isolated by candidate and viewport. Do not rerun a deterministic harness exception unchanged; correct and smoke-test the harness first.

Keep static-check construction simple: store template markers in a separate mapping, compute `template_signature_ok` for the current slot, then add that boolean to the checks dictionary. Avoid deeply nested inline dictionaries and generator expressions inside the main check dictionary; an unbalanced grouping delimiter can prevent the entire cell from running.

When building the static result, calculate each value before creating the result mapping. For example, select the current slot's marker list, compute `signature_ok = all(marker in html for marker in markers[slot])`, then use the plain `"template_signature": signature_ok` entry. Do not embed the three-slot signature mapping inside a large dict literal. If a Python syntax error occurs, that cell did not execute and none of its intended outputs are valid.

Before candidate rendering, both compile and execute the complete JavaScript measurement expression on a minimal fixture. A JavaScript syntax check alone does not catch runtime mistakes such as returning an undefined shorthand property (`cta` when only `ctas` exists). Assert that the returned object has the expected keys and that optional/missing elements and unparseable colors yield explicit missing/unavailable values instead of exceptions. Any evaluator exception is a harness error; repair it and rerun all affected candidate/viewport checks.

An `asyncio.CancelledError` or notebook-level cancellation means the QA matrix was interrupted. Record it as incomplete, not as a candidate pass/failure. Close browser resources in `finally`, do not present partial outputs as complete evidence, and resume only with a bounded clean rerun after addressing the interruption cause.

## In-session Chromium checks

Preflight Chromium once, then run the full browser check set on the exact final HTML bytes at **1440×900** and **390×844**. Also render at **768×900** for the contact/form fit measurements below, near a common layout breakpoint. Use `page.set_content()` when supported and do not wait for network idle.

At desktop and mobile viewports, measure and record:

- Hero, main, and required section geometry; viewport-edge hero width; and horizontal overflow.
- Hero media coverage. Landed `#banner` media must cover the full hero rectangle within 2 CSS pixels on all edges at both viewports. A partial-width image or uncovered band fails.
- Visibility and placement of the H1 and primary CTA; the CTA must fit in the first viewport.
- Computed text/background contrast for every detected visible CTA, including the header/navigation **Contact** link, at **4.5:1 or higher**. Unmeasurable contrast fails. Dark text on a light surface or white text on a sufficiently dark fill are acceptable.
- Header navigation counts and link limit; mobile menu initial hidden state, open/close by click, Enter and Space, Escape close, focus return, and visible focus indicator.
- CTA arrow absence, form non-submission behavior, and console/runtime errors relevant to the candidate.
- Contact layout at all three widths: measure the contact container, form, labels, and controls; confirm no horizontal clipping, overlap, or unexpected narrow columns. If a two-column form grid is active, each input must be at least 160 CSS pixels wide; otherwise the form fields must stack. Do not allow nested section/container padding to collapse the form's usable width. Record the form and field-grid dimensions in evidence.

Capture a desktop and mobile viewport PNG per candidate when supported, plus a focused contact-section screenshot at desktop and mobile sizes whenever the source has a contact form. Record browser/version, viewport size, screenshot path, and candidate digest. Inspect the contact screenshots for cramped controls, doubled gutters, clipped labels, and awkward stacking. If the session cannot expose saved PNG pixels, say screenshot pixel inspection was unavailable; geometry and interaction measurements may still pass independently.

## Remote images and screenshots

Remote Wix image retrieval and image-pixel inspection are not required QA checks in this runtime. Do not retry the known Wix limitation on every run, and do not treat missing remote image loads as candidate layout failures. If Chromium reports image elements incomplete, record `remote_images: UNAVAILABLE_KNOWN_RUNTIME_LIMIT` and classify the screenshots `layout_only_missing_remote_images`. Do not claim image relevance, crop, alt accuracy, decoded dimensions, resolution, or reuse terms were visually approved. Keep `image_content_status: UNVERIFIED`; it does not block `native_qa_status`.

Use image URLs and observed alt text only as source-grounded placement hints. Do not invent substitute assets, embed image bytes, or create an external review request unless the user specifically asks for one.

## Pass rule and repair loop

`native_qa_status: PASS` requires every static check and every executable browser check above to pass for all three exact final HTML digests. If browser preflight fails, deliver the generated files and report `PARTIAL`; static results do not imply rendered QA. If a check fails, make a narrow evidence-backed repair, recompute the digest, and rerun the affected static checks and both viewports for that candidate. Do not repeat identical repairs or claim results for superseded bytes.
