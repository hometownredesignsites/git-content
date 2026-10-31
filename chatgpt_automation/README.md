# ChatGPT website redesign workflow

This branch keeps the ChatGPT smoke-test path and adds a separate, CSV-triggered website workflow. A pilot push runs one real business through a single logged-out ChatGPT conversation, captures exactly four CSS chunks followed by eight HTML chunks, assembles the files, creates a standalone inlined HTML preview, and saves browser and source-audit evidence.

## Run and outputs

Edit [`source_urls.csv`](source_urls.csv) on the `chatgpt` branch. The current one-row pilot matches the first business used in the Duck.ai batch. The CSV and resulting artifacts are public in this repository. A change to that CSV starts [`.github/workflows/chatgpt-website.yml`](../.github/workflows/chatgpt-website.yml).

Each run is saved under `chatgpt-runs/website-run-<run-id>-<attempt>/candidate-1/` and committed to `chatgpt`. The candidate includes:

- `chunks/` with the twelve accepted response blocks, their source responses, and a SHA-256 capture manifest;
- `files/index.html` and `files/styles.css` assembled from the verified chunks;
- `files/inlined/index.html`, a self-contained stylesheet-inlined preview;
- `debug/` with the source audit, ChatGPT failure snapshots when needed, desktop/mobile screenshots, browser QA, and structural checks;
- `conversation_turns.json` and `run_notes.json` as a transcript and run record.

The generator stays in one ChatGPT conversation for all twelve parts. Each accepted part is saved before the next request is submitted. It checks the new rendered code block, response label, exact in-code marker, part order, output language, and conversation URL. A malformed part gets at most three attempts. If sign-in, usage, Cloudflare, or human-verification gates appear, the run stops and records available evidence; it does not attempt to get around the gate.

The source audit fetches the target homepage and a small number of linked contact/booking pages as static HTML. JavaScript-rendered content may not be visible to that audit, so unresolved source contact-form status remains a review item. The prompt treats source text as factual evidence, and location/category CSV values as unverified clues.

## Review status

The generated preview is a candidate, not an approved redesign. Automated browser checks cover desktop and mobile layout behavior, navigation, image loading, fonts, sections, and overflow. Structural checks cover document completeness, images, source-site assets, and content requirements. Neither machine checks nor the creation of the HTML preview verify image relevance or visual quality. `run_notes.json` therefore leaves `final_success` false and visual review pending.

Review `debug/screenshots/desktop.png` and `mobile.png`, inspect every distinct image actually used, and record the review before treating a candidate as approved. A successful smoke test that returns a short text answer only verifies chat submission and response extraction; it does not verify the twelve-part website workflow.
