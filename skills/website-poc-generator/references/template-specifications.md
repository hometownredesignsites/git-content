### 4. Select the real HTML5 UP scaffold, layout signature, and palette

Use the complete HTML5 UP packages bundled with this skill and the workflow's scaffold-selection implementation as the source of truth. Do not recreate the templates from memory or use a generic interpretation of their names. The bundle contains the full official template downloads, including HTML pages, CSS, scripts, fonts, images, and license/readme files; the workflow's `index.html`, `assets/css/main.css`, `LICENSE.txt`, and `README.txt` are preserved in the corresponding skill folders. These reference assets make template inspection self-contained; generated deliverables must still meet the standalone-output requirements below.

**Reference sources**

- Complete template packages: `assets/html5up/forty/`, `assets/html5up/landed/`, and `assets/html5up/story/`. Read the selected package's `index.html`, `assets/css/main.css`, `LICENSE.txt`, and `README.txt`; inspect its matching `assets/` resources when needed. The bundled four canonical files match the workflow source bundle at the time this skill package was synchronized. `assets/html5up/SOURCE.md` records bundle provenance and synchronization details.
- Fixed fallback URLs and category mappings: `references/fallback-image-pools.json`; do not reconstruct these from memory.
- When GitHub integration exposes `hometownredesignsites/git-content`, normally on ref `chatgpt`, use it to compare the current `.github/workflows/chatgpt-website.yml`, `chatgpt_automation/scripts/template_scaffolds.py`, `palette.py`, `prepare_candidate_context.py`, `fetch_source_facts.py`, `website_chunks.py`, `site_quality.py`, `browser_qa.py`, repair scripts, `package_website_poc.py`, and `skills/website-poc-generator/evidence.schema.json`. Record the actual ref/commit. GitHub source access is for reading and comparison; it does not execute these scripts. Do not claim a script ran merely because its source was read. The slot signatures and palette table below are the self-contained fallback when repo access is unavailable.
- The official reference/demo/license URLs in the workflow manifest are: Forty `https://html5up.net/forty`, Landed `https://html5up.net/landed`, Story `https://html5up.net/story`; demos are under `https://html5up.net/uploads/demos/<slug>/`, and the license reference is `https://html5up.net/license`.
- The bundled template demo imagery and scripts are reference materials. Do not carry demo filler text, demo images, or template JavaScript into a generated business page unless its content and use are independently appropriate and validated. Generated pages must follow this skill's dependency and interaction limits.

**Candidate-to-template assignment and selection**

Create exactly one candidate for each supported scaffold, in this stable slot order: slot 1 = Forty, slot 2 = Landed, slot 3 = Story. If an upstream design plan is supplied, validate that it contains exactly these three supported template references (one each) using their `template_url` values. If the plan is absent, incomplete, duplicated, or contains an unsupported template, use the complete supported set in the stable order; do not silently replace a supported template. Choose the business-fit notes and section content from the verified source brief, but do not change the assigned template signature. Record the selected slot, template name/slug, official reference URL, demo URL, signature ID, and palette in the design/evidence report.

**Exact source-backed layout signatures**

Use these signatures as minimum structural and rendered-layout requirements. Preserve the recognizable component geometry and section rhythm while replacing demo copy, images, and branding with source-grounded business content.

1. **Forty — slot 1; signature ID `forty-image-tiles`.**
   - Source marker tags: `id="banner" class="major"`, `id="one" class="tiles"`, an `<article>` tile, `id="contact"`, and `id="footer"`.
   - Source sequence: `<header id="header">` → `<section id="banner" class="major">` → `<main id="main"><section id="one" class="tiles"><article>…</article></section>` → `<section id="two">` → `<section id="contact">` → `<footer id="footer">`.
   - Preserve a two-column desktop grid of at least three image-backed article tiles, with copy overlaid on the images; use the `.tiles`, `.tiles article`, `.tiles article header`, and `.tiles article .image` patterns. Follow the tile grid with a separate text/story section and a contact band. The shared hero must remain a full-screen photographic hero; it does not replace the tile-grid signature.
   - Source CSS selectors used by the scaffold: `.tiles`, `.tiles article`, `.tiles article header`, `.tiles article .image`.

2. **Landed — slot 2; signature ID `landed-alternating-spotlights`.**
   - Source marker tags: `id="one" class="spotlight style1 bottom"`, `id="two" class="spotlight style2 right"`, `id="three" class="spotlight style3 left"`, and `id="four" class="wrapper style1 special fade-up"`.
   - Source sequence: `<section id="banner">` → spotlight `#one` (`style1 bottom`) → spotlight `#two` (`style2 right`) → spotlight `#three` (`style3 left`) → `#four.wrapper.style1.special.fade-up` → `#five.wrapper.style2.special.fade` → footer.
   - Preserve at least three substantial, wide split feature bands with image and copy columns, alternating image sides left/right/left (or the reverse), followed by a compact feature grid and a distinct contact band. Keep the `.spotlight`, `.spotlight .content`, `.spotlight .image`, `.style1/.style2/.style3`, `.left/.right`, and `.wrapper` patterns. A stack of generic cards is not equivalent.
   - Source CSS selectors used by the scaffold: `.spotlight`, `.spotlight .content`, `.spotlight .image`, `.wrapper`.

3. **Story — slot 3; signature ID `story-fullbleed-divided-panels-gallery`.**
   - Source marker tags: `id="wrapper" class="divided"`, a `banner style1 orient-left content-align-left image-position-right fullscreen`, a `spotlight style1 orient-right`, a `gallery style2 medium`, and an `items style1 medium` component.
   - Source sequence: `<div id="wrapper" class="divided">` → full-screen `.banner.style1` → alternating `.spotlight.style1.orient-right` / `.spotlight.style1.orient-left` panels → centered `.gallery.style2.medium` and/or `.items.style1.medium` module → contact.
   - Preserve the divided editorial rhythm: at least two broad alternating image/text spotlight panels, then a separate image gallery or compact items band and contact. Keep `.banner`, `.spotlight`, `.orient-left/.orient-right`, `.gallery` or `.items`, and `.divided`. Its hero must still be a validated business-relevant photo covering the full viewport edge-to-edge and top-to-bottom on desktop and mobile; use an opaque, readable headline/CTA panel. Do not turn it into a half-width hero image or narrow mobile image rail.
   - Source CSS selectors used by the scaffold: `.banner.style1`, `.spotlight.style1`, `.gallery.style2`, `.items.style1`.

**Exact slot palettes**

Apply the palette assigned to the candidate slot, not a palette chosen ad hoc for the business. Define these nine CSS custom properties in `:root` and use them throughout the page:

| Token | Forty · slot 1 | Landed · slot 2 | Story · slot 3 |
|---|---|---|---|
| `--ink` | `#292521` | `#202b29` | `#202b38` |
| `--ink-soft` | `#665e55` | `#52615c` | `#526272` |
| `--paper` | `#f6f1e9` | `#f4f6f1` | `#f2f5f8` |
| `--surface` | `#fffdfa` | `#ffffff` | `#ffffff` |
| `--accent` | `#a34e34` | `#285144` | `#285678` |
| `--accent-dark` | `#713923` | `#1a352d` | `#183a55` |
| `--accent-soft` | `#e6c1ad` | `#adc0a7` | `#b8cad8` |
| `--accent-warm` | `#96502f` | `#795f25` | `#91442e` |
| `--line` | `#ddd1c4` | `#d3ddd4` | `#d0dae3` |

Normalize recognized template color-variable aliases to these tokens rather than allowing the original template's color names to bypass the assigned palette. The workflow's `palette.py` aliases include text/foreground → `ink`; muted/text-muted → `ink-soft`; background/bg → `paper`; cream → `surface`; olive/forest/brand/primary → `accent`; olive-dark/forest-dark/brand-dark/primary-dark → `accent-dark`; sage/sand/tint → `accent-soft`; copper/rust/brass → `accent-warm`; and border → `line` (including the corresponding `color-*` aliases defined in that script).

Verify that all nine root token values match the assigned palette and that `ink`, `paper`, and `accent` are actually referenced by the stylesheet. Check the same contrast pairs as `palette.py`: ink on paper, ink on soft accent, muted ink on paper, white on accent, white on dark accent, and white on warm accent. Each must be at least 4.5:1. Record token values, token usage, all six contrast ratios, and the result in the candidate evidence. If a pair fails, repair the palette usage/foreground treatment without changing the assigned palette, then rerun the check. Do not claim palette validation if the calculation was not performed.

**Attribution and license handling**

The bundled HTML5 UP templates carry the Creative Commons Attribution 3.0 Unported license. Read and preserve the selected template's bundled `LICENSE.txt`; retain the original copyright/license notices and include a reasonable attribution with the template name, HTML5 UP as the template source/author attribution where supplied by the source, the official template URL, the license name and URL (`https://creativecommons.org/licenses/by/3.0/`), and a clear statement that the template has been modified. Keep attribution comments in both the HTML and CSS portions of the generated source (for this standalone format, use an HTML comment in the document and a CSS comment inside the embedded `<style>`). Do not imply HTML5 UP endorses the business or generated site. Include or link the license with the delivered file when practical, and do not remove notices from the bundled source. If source attribution details differ in a bundled file, follow that file and its license rather than inventing an author or title.

**Reference integrity and blocked state**

Before generation, confirm that the selected bundled template directory contains `index.html`, `assets/css/main.css`, and `LICENSE.txt`; confirm that all configured source markers exist in the HTML; confirm that at least two configured CSS selector rules can be extracted; and confirm that the license file contains the expected Creative Commons Attribution 3.0 notice. Use the actual source opening tags and CSS excerpts from that directory to guide the candidate. If GitHub access is available, compare these canonical files with the workflow bundle and note any mismatch; do not silently replace a bundled file with a remote copy. If a required reference is unavailable or fails these checks, report the exact path/marker/selector that failed and mark template parity BLOCKED. Do not invent a scaffold excerpt or call an “inspired” design compliant.
