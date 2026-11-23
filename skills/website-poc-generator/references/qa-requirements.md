### 6. Apply workflow-aligned QA with available tools

The workflow has two distinct automated layers. Keep its check IDs and severity classification. Run the actual repo scripts only when a code runner has the corresponding checkout/files and dependencies; GitHub integration can show script contents but cannot run them. Otherwise use browser/Web and manual inspection only for checks whose condition is directly observable, record the method and evidence, and mark all unmeasured or tool-dependent checks BLOCKED/UNVERIFIED. Follow the capability matrix: screenshots, search results, and code inspection cannot stand in for parser results, byte checks, computed browser measurements, or hashes.

**Authoritative implementations**

- Static/document and asset checks: `chatgpt_automation/scripts/site_quality.py`.
- Real Chromium rendering, viewport geometry, navigation interaction, computed contrast, resource loading, and template geometry: `chatgpt_automation/scripts/browser_qa.py`.
- Supporting repair behavior: `chatgpt_automation/scripts/repair_candidate_quality.py`, `chatgpt_automation/scripts/repair_generated_visuals.py`, and the contact-form/local-link repair scripts.
- The workflow runs browser QA against the final inlined file: `files/inlined/index.html`, not merely an earlier source draft. For this skill's standalone output, run equivalent checks against each final delivered HTML file with its CSS embedded.

Use the exact check names below in the evidence report, with one of PASS, FAIL, BLOCKED, or UNVERIFIED. A static inspection cannot pass a rendered-browser check. A browser screenshot cannot substitute for byte-level image validation. Do not claim exact workflow execution unless the actual workflow scripts were run.

#### 6.1 Blocking static/document checks — `site_quality.py`

Every check in this subsection is part of the workflow's blocking `structural_gate_checks` unless explicitly identified as advisory later in this section.

The Action checks its separate authoring files before CSS inlining. For a skill candidate authored directly as one standalone HTML file, `css_file_present` and `styles_css_linked` describe workflow intermediates and must be recorded as `NOT_REQUIRED`; instead require and verify one complete embedded `<style>` block under the standalone/package checks. Do not create fake CSS files or mark an inapplicable assembly check PASS.

**Document integrity and semantics**

- `html_file_present`: final HTML exists and is nonempty.
- `css_file_present`: the workflow's separate CSS source exists and is nonempty before inlining; `NOT_REQUIRED` for the skill's direct standalone authoring path (see above).
- `document_has_main`: exactly one `<main>`.
- `document_has_h1`: exactly one nonempty `<h1>`.
- `html_language_declared`: `<html lang>` matches a language-tag form of 2–3 letters with optional hyphenated alphanumeric subtags.
- `document_title_present`: nonempty `<title>`.
- `viewport_meta_present`: nonempty viewport meta content.
- `document_closed`: closing `</body>` followed by `</html>` (optional trailing HTML comments are allowed).
- `css_braces_balanced`: CSS exists; braces are balanced while ignoring braces in comments and strings; no unterminated comment/string or unmatched closing brace.
- `ids_unique`: no duplicate IDs.
- `fragment_links_resolve`: every same-document fragment link/form target resolves to an existing ID.
- `local_routes_resolve`: every same-origin relative path resolves to a file in the candidate output; root and `/index.html` are accepted for the single-page site.
- `styles_css_linked`: the workflow source document links to `styles.css` before inlining; `NOT_REQUIRED` for the skill's direct standalone authoring path. Verify instead that the single embedded style block is present and complete.
- `interactive_buttons_named`: every button has visible text, an accessible name, or valid `aria-labelledby` references.
- `form_controls_labeled`: every non-hidden/non-submit/non-reset form control has a label, `aria-label`, or valid `aria-labelledby`.
- `contact_form_matches_source`: compare the explicit `source_contact_form_status` in candidate inputs with final markup. When `ABSENT`, require no `<form>` element and no inquiry controls in the contact section. When `PRESENT`, require a source-based form and every identifiable captured field. A control that cannot be identified may be omitted only when candidate inputs record its source position, evidence locator/path, and `OMITTED_UNIDENTIFIABLE` reason; preserve all identifiable fields and set `exact_full_form_parity` false. This documented omission alone does not fail the form gate and must not be reported as full parity. When `UNVERIFIED`, do not generate a form or inquiry controls and keep this check UNVERIFIED. This check is blocking.
- `contact_form_send_cta_present`: when source-derived inquiry fields are reproduced, the contact group includes a visibly rendered, enabled, accessibly named Send/Send inquiry/Send message/Submit control. For a preview without a working endpoint, use an explicit `<button type="button">` so it cannot accidentally submit; place the clear “nothing is sent or stored” disclosure beside the form. The bundled static validator checks markup presence/name/type/disabled and inline-hidden states; actual rendered visibility is still a browser gate.

**Required section structure and substance**

Infer required sections from the actual redesign request, not from scraped source text. Hero, contact, and footer are always required. Add services, process, testimonials, location, hours, about, FAQ, pricing, team, and gallery only when explicitly requested by the brief (respect conditional and optional wording).

For every required section, preserve both checks:
- `section_<name>`: a matching named/semantic container exists.
- `section_<name>_complete`: at least one matching container has a heading (hero requires its H1; footer is exempt from a heading) and at least 30 visible text characters plus at least three descendant elements or a form.
- `required_sections_complete`: all required section completeness checks pass.

The section matcher uses the alias dictionary in `site_quality.py`; use its aliases rather than assuming only literal IDs count. Browser QA separately confirms the rendered required sections are actually visible at both viewports.

**Navigation, CTA, footer, and contact semantics**

- `no_visible_template_credit`: do not expose HTML5 UP/template attribution as visible page copy or visible links; keep required credits in source comments.
- `template_attribution_comment` and `template_attribution_css_comment`: when a scaffold is selected, both the HTML comment and CSS comment must contain the selected template name, official template URL, license URL, and an “adapted”/“adaptation” statement; selected slot must match the maintained reference plan. If no template is selected, these checks are not required.
- `cta_buttons_no_arrows`: CTA labels/icons contain no arrow glyphs or arrow/chevron icons.
- `telephone_cta_labels_identify_call`: a telephone link with alphabetic text must use a call-specific label (for example, “Call” or “Call us”), not a vague CTA label.
- `accessible_mobile_hamburger`: a button has an accessible name, references an existing controlled navigation ID, has `aria-expanded=true|false`, a menu/nav class, and exactly three direct visual bars; its visible label must not be a redundant “menu”.
- `header_navigation_link_limit`: at least one header navigation exists and every header nav contains no more than five links.
- `footer_has_substance`: footer visible text is at least 45 characters and contains at least two useful links.

**Assigned palette**

When a template was selected, require all three:
- `palette_tokens_match_assigned_slot`: all nine root token values exactly match the assigned palette.
- `palette_tokens_used_in_stylesheet`: the required `ink`, `paper`, and `accent` tokens are actually referenced.
- `palette_text_contrast_adequate`: the six palette contrast pairs each meet 4.5:1, as defined by `palette.py`.

**Images, source evidence, and contact preservation**

- `hero_has_image`: hero markup or hero CSS declares photographic image media.
- `hero_images_load_ok`: every unique image URL identified in the hero resolves to plausible image bytes. `site_quality.py` checks HTTP(S) or embedded data URLs, follows relative URLs against the source base URL, requires a 2xx response, and inspects bytes (not just MIME claims); remote reads time out after 8 seconds and inspect up to 65,536 bytes.
- `all_images_load_ok`: every unique image asset discovered in HTML and CSS passes the same byte plausibility check. This is advisory in the workflow's final classification; still report failures.
- `image_alt_text_present`: every `<img>` has an `alt` attribute (an empty alt is allowed for decorative images).
- `image_resolution_suitable` (skill review gate): for every used image, compare actual source pixel dimensions with its largest rendered image box and requested CDN transform. A full-bleed hero at the 1440px desktop viewport needs at least 1440 source pixels across after accounting for the chosen crop; prefer 2880px when the source supports it. A URL that explicitly requests only `w_615` is capped at 615px and must not be used as a full-width desktop hero. Preserve source image identity while selecting the workflow-canonical original URL for Wix assets. If no image metadata, original dimension, or actual browser measurement is available, this check is UNVERIFIED, not PASS. A clearly insufficient source is FAIL; choose another approved image or a validated higher-resolution variant and repeat load, crop, and visual review.
- `image_coverage`: count distinct successfully loaded image URLs after URL normalization/deduplication. Require at least **three** when the original redesign request calls for imagery/images/photos/a photo gallery/image gallery; otherwise at least one. Report the exact distinct URLs and which passed byte validation. Three references to one image do not count as three.
- `images_use_source_or_category_assets`: when approved source/fallback assets are provided, every external page image must come from that approved set.
- `hero_uses_source_or_category_asset`: when approved assets are provided, the hero must use one of them.
- When verified source images were extracted, additionally report `source_site_hero_photo_used`, `source_site_photos_used` (at least `min(2, available verified source images)` distinct source photos used), and `source_site_photos_load_ok`. These three are advisory, not blocking, in the workflow's classification; do not misstate them as mandatory when the source has no usable photos.
- `source_contact_channels_preserved`: every verified source email and phone number has a corresponding `mailto:` or `tel:` link, normalized for phone punctuation and optional leading country code 1.
- Record `source_contact_form_status` as PRESENT, ABSENT, or UNVERIFIED in each candidate's `contact_and_form_requirements`. If PRESENT, require `source_contact_form_present`, `source_contact_form_fields_preserved`, and `source_contact_form_required_fields_preserved`. Preserve the captured field identities/types, file-field count, and required/optional state. File fields are counted separately; do not add excluded upload fields if the source brief explicitly excludes them. If ABSENT, require no generated form or inquiry fields.
- When those source fields are reproduced as a no-endpoint demo, also require `contact_form_send_cta_present`; a field-only contact mockup is incomplete even if its field schema is preserved.
- `generated_contact_form_has_source_basis`: if a form is generated, captured source form fields must provide its basis; a fabricated form with no source form evidence fails.

#### 6.2 Blocking rendered Chromium checks — `browser_qa.py`

Run a real browser at **desktop 1440×900** and **mobile 390×844** for each candidate. The script uses Chromium/Playwright, waits for DOM content, gives the page an initial 800 ms settle, then waits up to 12 seconds for image decode and 8 seconds for `document.fonts.ready`. It records viewport screenshots at both sizes. Test the final inlined/standalone file using a disposable screenshot copy with the exact referenced image bytes embedded as data URIs. The production HTML is never rewritten.

**Mandatory image-integrity gate:** before browser rendering, collect external image references in `img`/`source` `src` and `srcset`, lazy image attributes, `poster`, inline `style`, and embedded CSS `url(...)`. Resolve relative URLs only against the recorded source page. Fetch each distinct URL and require a successful HTTP response, nonempty bounded bytes, recognized image signature, and a matching image MIME type when supplied. Embed the verified bytes in a temporary copy; do not alter the production HTML or substitute another asset. Chromium must decode every embedded asset and report nonzero natural width and height; at both viewports, all DOM images and visible content images must also load. Save URL, HTTP status, MIME type, byte count, byte SHA-256, decoded dimensions, and per-viewport result in `debug/image_embed_manifest.json` and `browser_qa.json`. If retrieval, integrity validation, embedding, or decoding fails—or no browser is available—the image gate is BLOCKED, overall browser QA is BLOCKED, and screenshots are marked `layout_diagnostic_only`. They cannot support a PASS visual review. Temporary embedded HTML and its byte payload must not be packaged or committed.

All 27 boolean checks below are required fields in `debug/browser_qa.json`. The following 25 are explicitly in the workflow's blocking set:

1. `rendered_sections_visible_desktop_and_mobile`: every brief-required section is visibly rendered at both viewports; an element must have nonzero geometry and not be hidden by display, visibility, opacity, or `aria-hidden`.
2. `hero_spans_viewport_desktop_and_mobile`: the H1's containing hero reaches within 2 CSS pixels of both viewport edges at desktop and mobile.
3. `hero_media_covers_hero_desktop_and_mobile`: at least one visible image/background/pseudo-element in the hero has geometry covering the entire hero rectangle within 2 CSS pixels on all four edges. A decorative split column or narrow side image does not qualify.
4. `hero_image_loads_desktop_and_mobile`: every distinct image URL found on visible hero elements and their pseudo-elements loads successfully; each image load has a 10-second timeout.
5. `image_tile_overlays_do_not_hide_photos`: no Forty-style `.tiles article a.tile-link` overlay may cover at least 90% of its card in both dimensions with a background alpha of 0.95 or greater.
6. `visible_content_images_load_in_browser`: at each viewport, at least one distinct visible image/background asset is detected and every detected visible asset loads.
7. `cta_arrows_absent_desktop_and_mobile`: no visible CTA has arrow glyphs, arrow/chevron SVG/classes, image backgrounds, masks, pseudo-element arrow content, or CSS-drawn arrow borders; also recheck CTAs in the open mobile menu.
8. `cta_visible_first_screen_desktop_and_mobile`: at least one identified CTA is fully inside the initial viewport (top/left at or beyond zero; bottom/right within viewport).
9. `desktop_navigation_has_single_visible_menu`: exactly one header nav is visible on desktop and the controlled mobile nav is hidden.
10. `header_navigation_link_limit`: every header nav has at most five links at desktop and mobile; mobile controlled menu also stays within five.
11. `mobile_navigation_hidden_until_opened`: controlled mobile navigation is initially hidden before user interaction.
12. `mobile_navigation_is_only_visible_menu_when_open`: after opening, exactly one header nav is visible.
13. `mobile_menu_clicks_work`: clicking the menu control opens it and a second click closes it; `aria-expanded` and rendered visibility must agree.
14. `mobile_menu_control_visible`: the menu button is visible and at least 32×32 CSS pixels; it has exactly three visible bars, each at least 10 pixels wide and 1 pixel high with a visible color.
15. `mobile_menu_focus_indicator_visible`: the menu control has a visible CSS outline or box shadow when focused.
16. `mobile_menu_keyboard_works`: the control is reachable by Tab, Enter opens, Space toggles closed, Escape closes, and Escape returns focus to the menu control.
17. `mobile_has_no_horizontal_overflow`: mobile document scroll width is no more than viewport width + 1 pixel.
18. `critical_content_within_viewport_desktop_and_mobile`: visible H1 and CTA text lines are not clipped by any ancestor with hidden/clip/scroll/auto horizontal overflow at either viewport.
19. `contact_email_ctas_grouped`: visible email CTA buttons inside contact sections are grouped in a contact-actions/actions/CTA/button group and not misplaced inside contact-detail grids.
20. `contact_channel_ctas_aligned`: if there are two or more visible phone/email CTA buttons, they share one action group using flex/inline-flex, `align-items:center`, and `justify-content:center`.
21. `contact_ctas_readable_desktop_and_mobile`: every visible CTA in the contact section has computed foreground/background text contrast at least 4.5:1. If the rendered background cannot be measured reliably, it fails rather than being assumed readable.
22. `primary_ctas_readable_desktop_and_mobile`: at least one visible primary CTA exists and each detected primary CTA has measured foreground/background contrast of at least 4.5:1.
23. `image_card_labels_readable_desktop_and_mobile`: visible `.tiles article .eyebrow` labels have a computed text luminance of at least 0.8 and a background alpha of at least 0.65.
24. `hero_ctas_readable_desktop_and_mobile`: every detected visible CTA in the hero has measured text contrast of at least 4.5:1.
25. `template_layout_signature_matches`: actual desktop rendered geometry matches the selected scaffold's signature (see exact profiles below). Story additionally requires its hero media to cover the full hero at both desktop and mobile.

**Two browser checks are advisory under the workflow's exact severity classification** (still report them; do not silently omit them):
- `fonts_load_in_browser`: both viewports have `document.fonts.status === "loaded"`, zero failed FontFace entries, and no failed font resource responses.
- `images_load_in_browser`: all `document.images` have completed with `naturalWidth > 0` at both viewports and no failed image resource responses. This is broader than the blocking visible-image and hero-image checks.

**Exact template-specific rendered geometry**

Measure the actual rendered DOM on desktop, not class names alone. `browser_qa.py` uses these checks:

- **Forty:** hero is `#banner.major`; `main` contains `.tiles`; at least 3 direct-child `article` tiles; at least 3 tiles contain media; tile container computes to `grid` or `flex`; at least 2 desktop columns are measured from `gridTemplateColumns` (grid) or distinct article positions (flex). Report the measured tile count, media-tile count, layout mode, and column count.
- **Landed:** hero is `#banner`; at least 3 `.spotlight` sections; all three source styles `.style1`, `.style2`, and `.style3` occur; media is detected in each measured spotlight with width at least 18% of the section; image-side alternation count is at least 2 (left/right/left or right/left/right). Report spotlight count, measured sides, and alternation count.
- **Story:** hero has both `.banner` and `.fullscreen`; at least 2 spotlight sections; both `.orient-left` and `.orient-right` exist; a `.gallery` or `.items` module exists; at least one media-side alternation is measured; page has `.divided` or `#wrapper.divided`; hero media must cover the hero at both viewport sizes. Report divided-page flag, gallery/items flag, orientations, spotlight media count, and alternation count.

**Additional browser measurements to preserve in evidence**

For each viewport record: hero rectangle (left/right/width/height), viewport width, coverage result and loaded hero URLs; visible navigation count and nav link counts; first-screen CTA label, href, tag and bottom coordinate; clipping issue list; document scroll width vs viewport width; contact CTA grouping/alignment; all measured contrast ratios and unmeasurable cases; image-card label count/issues; visible media distinct/loaded counts and failures; all `<img>` loaded/natural dimensions; font status/loaded/failed face counts; and resource request/response errors for image/font resources.

#### 6.3 Blocking/advisory classification — preserve the workflow distinction

- **Blocking:** all `site_quality.py` structural gate checks, except the explicitly advisory checks listed below; all 25 blocking browser checks above; approved source/category asset provenance checks when an approved asset set exists; template attribution and palette checks when a scaffold is selected; source contact channel/form parity when those facts were captured; and screenshot-backed human design review before final completion.
- **Advisory (not a candidate hard-fail by itself):** `all_images_load_ok`; `source_site_hero_photo_used`; `source_site_photos_used`; `source_site_photos_load_ok`; and the two browser checks `fonts_load_in_browser` and `images_load_in_browser`. Also, any `browser_*` check not in the explicit 25-name blocking set is advisory. The workflow still records these and includes them in its browser report.
- `visual_design_review_passed` is deliberately excluded from the automated structural score, but it is a separate final human-review gate—not a disposable advisory. The review JSON must have `status: "pass"`, all five checks true (`first_screen_hierarchy`, `section_rhythm`, `typography`, `business_specificity`, `footer`), an empty `blocking_defects` list, and valid desktop/mobile PNG screenshot evidence inside `debug/`. Desktop screenshot viewport must be at least 1024×700 and landscape; mobile declared viewport must be 320–600 pixels wide and at least 600 high, with portrait PNG pixels no wider than 1200 and at least 600 high.
- Per-image human review is a distinct gate when images exist: `debug/image_review.json` must cover every unique used image URL and each image must have `relevant: true`, `crop_ok: true`, `alt_accurate: true`, `resolution_status: "PASS"`, and a nonempty `observed_subject`; overall status must be `pass`. Missing review is pending, not passed. For skill completion, resolution is part of this image gate; load success alone does not establish usable sharpness.
- If `debug/browser_qa.json` is missing, unreadable, or lacks any of the 27 required boolean checks, report browser QA as BLOCKED/INVALID. A failed required boolean is FAIL. Never infer a pass from a screenshot or static source inspection.
- Keep blocking failures and advisory findings in separate report lists. The workflow's candidate qualification uses the automated structural checks; the screenshot-backed visual review remains pending until separately completed. Do not average a blocking failure away with a high percentage score.

#### 6.4 Repair and rerun

When a blocking check fails, identify the exact check, viewport, selector/element, and evidence. Repair the underlying cause (not just the report), then rerun the affected static and browser checks against the final file at both viewports. After any layout, image, CSS, or navigation change, rerun both desktop and mobile browser QA because the change can affect shared geometry. Preserve before/after reports and screenshots. Do not turn an untestable check into PASS; use BLOCKED or UNVERIFIED and explain the missing capability.

If the target-session preflight finds no supported renderer, use limited mode: run only the static checks that can actually be executed, mark every browser-dependent check and visual review BLOCKED, and keep the overall run BLOCKED. The minimum capability for full rendered QA is an in-session browser engine that accepts the exact saved file bytes, exposes controllable desktop/mobile viewports, allows assistant inspection of rendered pixels, and saves candidate-bound screenshots; computed geometry, resource/network state, and interactions are additionally required for the corresponding automated gates. Mark all browser-dependent checks BLOCKED/UNVERIFIED, including hero coverage, rendered template geometry, visible navigation/menu interaction, computed contrast, clipping/overflow, font/image browser loading, and screenshot review. Do not claim workflow-equivalent automated QA.
## Visual design quality scorecard (skill runs)

Alongside the blocking template, source, accessibility, interaction, and browser checks above, score each visually reviewed skill candidate on a 0–5 scale. Convert each score to weighted points with `score / 5 × weight`; sum to a 0–100 total. Include a concise finding for every criterion in `visual-review.json`.

| Criterion | Weight |
| --- | ---: |
| First-screen visual impact | 20 |
| Business-specific design | 20 |
| Typography and hierarchy | 15 |
| Image selection and composition | 15 |
| Section rhythm and spacing | 15 |
| Mobile experience | 10 |
| Conversion clarity | 5 |
| **Total** | **100** |

The scorecard is explicitly advisory. It supplements the required blocking gates and cannot turn a failed or unverified check into PASS. Record a specific defect as a blocking defect only when it violates an existing blocking requirement; otherwise keep it as a scorecard finding or advisory. Do not use an arbitrary total-score threshold to waive existing QA requirements.
