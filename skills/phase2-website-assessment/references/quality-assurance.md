# Quality Assurance Checklist and Evidence

Perform practical static QA before commit. Browser-test desktop and mobile when available. Never claim a check that did not actually run.

## Evidence status vocabulary
For every checklist item below, record exactly one status:
- **PASS**: the check was actually performed and met the criterion; include brief evidence (e.g. command/result, observation, viewport, or file/source location).
- **FAIL**: the check was performed and did not meet the criterion; state the finding and whether it was corrected/retested.
- **NOT CHECKED**: it was not performed; state why (capability unavailable, time/scope blocker, or not applicable with reason).
- **FALLBACK**: the preferred check was unavailable, but a documented lower-confidence alternative was used; identify that alternative and its limitations. Do not represent fallback as a full pass of the preferred test.

Static source inspection and browser/runtime testing are separate evidence. Fresh screenshots are optional only when screenshot capability is unavailable; never reuse screenshots from prior runs. Do not infer a test result from source code alone if it requires runtime interaction.

## Static QA checklist (record status and concise evidence for each)
- [ ] Document structure: doctype, language, title/description, semantic landmarks, one primary H1, valid nesting.
- [ ] Content fidelity: verified business facts, meaningful sections, service information, contact details, claims, and links preserved; additions supported.
- [ ] Images: source URLs/order preserved where required, alt text appropriate, no broken/unnecessary placeholder source, and no avoidable image dependency.
- [ ] Hero: responsive dimensions, loading/presentation, `object-fit`, intentional `object-position`/crop, overlay/readability treatment.
- [ ] Contact/CTA links: correct targets, protocols, labels, and usable destinations; no invented endpoint.
- [ ] Forms: all relevant fields/options preserved; no fabricated backend; disconnected demo disclosure present; no unintended data transmission/storage.
- [ ] Internal anchors: targets exist and resolve; no invalid or empty anchors.
- [ ] IDs: unique IDs; no duplicate IDs.
- [ ] Responsive source: viewport/meta and breakpoint handling; layouts adapt at intended mobile/tablet/desktop widths.
- [ ] Mobile navigation: accessible control, `aria-expanded`/`aria-controls` state, correct open/close behavior in source and runtime if browser-tested.
- [ ] Accessibility: keyboard focus visible, sensible tab order, button/link semantics, contrast/readability reviewed, accessible labels and descriptive alt text.
- [ ] Reduced motion: `prefers-reduced-motion: reduce` honored and essential content/functionality remains available without animation.
- [ ] Scroll reveal: progressive enhancement; content remains visible without JS; no essential content hidden or flicker.
- [ ] CTA states: hover, focus-visible, active/pressed; intended enlargement/lift and smooth transitions without layout shifts.
- [ ] Navigation effects: hover/focus treatment and transitions; no interaction dependent solely on hover.
- [ ] Cards/images: intended hover/focus image zoom/elevation, restrained motion and no overflow.
- [ ] Placeholder/claims scan: no lorem ipsum, unverified claims, invented reviews/credentials/awards/guarantees/stats, or unsupported endpoints.
- [ ] Visible copy: no em dashes (—) if required by the current brief.
- [ ] Scope: only the exact authorized return files changed; diff reviewed.

## Browser/runtime QA matrix (when a browser is available)
Use fresh browser state for the current run. Test representative desktop and narrow mobile viewport sizes; record exact viewport dimensions and browser/runtime if known. Mark every item separately PASS, FAIL, NOT CHECKED, or FALLBACK:
- [ ] Desktop layout and visual hierarchy at a representative wide viewport.
- [ ] Mobile layout at a narrow viewport; navigation and content are usable.
- [ ] Horizontal overflow: inspect/document viewport scroll width or visually verify no unintended horizontal scrolling.
- [ ] Console/runtime errors and warnings relevant to the page; record errors (do not suppress them merely to pass).
- [ ] Image loading: verify visible images actually load; note any failures and whether they are source-site/network limitations.
- [ ] Hero crop/readability at desktop and mobile, including object position and overlay.
- [ ] Mobile menu open/close, aria state, links, escape/close behavior if implemented, and touch usability.
- [ ] CTA/link navigation: targets and behavior; avoid submitting live forms or sending real data.
- [ ] Forms: field usability and validation if safely testable; do not transmit real or fabricated customer data.
- [ ] Keyboard navigation: tab through key controls, visible focus, activation, and logical order.
- [ ] Reduced-motion: enable the browser/system preference and confirm motion is reduced/disabled while content remains visible and usable.
- [ ] Scroll reveals and card/image interactions: observe behavior, no hidden content/flicker, and focus usability.
- [ ] Responsive transitions at intermediate widths if practical (not only desktop and phone endpoints).

If browser automation is unavailable, mark each browser item NOT CHECKED (or FALLBACK when an actual alternative check was performed), specify the unavailable capability, and provide static/source checks only. Never imply browser testing.

## Evidence record
Produce a compact QA evidence table in the run report with columns **Check**, **Status**, **Evidence / finding**. Include all static items and browser items, or group them only when their results and evidence are identical and grouping remains clear. Screenshots must be freshly captured in this run and from the stated environment. Static source inspection is not equivalent to browser testing. Don't fabricate screenshots, test outputs, or pass status.