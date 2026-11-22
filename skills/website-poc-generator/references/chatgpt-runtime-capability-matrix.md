# ChatGPT runtime capability matrix

Use this before generation. Skills provide instructions and bundled resources; connected apps provide service access. Neither a signed-in browser nor a GitHub connection implies a local checkout, shell, code execution, Playwright, repository writes, or a way to export files.

## Required capabilities for a full-parity run

Record each capability in `evidence/run.json` as `available`, `unavailable`, or `not_checked`, with the actual tool and evidence method.

| Capability | What qualifies | If unavailable |
|---|---|---|
| Business-site access | Open the requested pages in Web search/open or the signed-in browser; inspect the page itself, not just a search-result snippet. | Mark unavailable pages and claims; do not fill gaps from guesses. |
| Current workflow reference | Read `hometownredesignsites/git-content` on the user-supplied ref (normally `chatgpt`) through GitHub integration; record the branch/ref and commit if exposed. | Use the skill's bundled contracts, but mark current-workflow comparison UNVERIFIED. GitHub access does not mean scripts can be run or changes can be pushed. |
| Candidate file authoring | A file/artifact tool that saves and returns the exact three HTML files and evidence package. | Draft in chat only; do not call the deliverables saved or the run complete. |
| Static checks, hashes, and schema validation | A code/file tool that can read the saved HTML, check document/CSS/link invariants, compute SHA-256, and validate JSON against the bundled schema. | Use manual inspection only for checks that are directly observable; mark parsing, hashing, and schema gates UNVERIFIED. Do not use a public hash site for private business content. |
| Final-file browser preview | A browser or preview surface that opens the exact saved candidate bytes, not the source business site or HTML5 UP demo. | Mark all rendered checks and screenshot-backed reviews BLOCKED/UNVERIFIED. |
| Browser measurements and screenshots | A browser tool that can set both specified viewports, test keyboard/touch interactions, inspect computed/rendered results, and save candidate-specific screenshots/reports. Playwright is one implementation, not an assumed ChatGPT capability. | A visual screenshot can support only the findings it visibly proves; it cannot substitute for missing DOM, geometry, interaction, or computed-style checks. |
| Image evidence | Web/browser display for actual visual review; a byte-reading tool for workflow-equivalent image signature validation. | Record browser image load and visual review separately. If bytes cannot be checked, mark byte validation UNVERIFIED; never infer it from a URL, MIME label, or screenshot. |
| Persistent checkpoint/package | A writable location or downloadable archive that retains the append-only ledger and evidence through interruption. | Do not restart a run as if new. Return a partial result with the exact missing package/checkpoint capability. |

**Full-parity decision:** `run.json.status` may be PASS only when every blocking workflow-aligned check has evidence for the exact final HTML digest, every required record is saved and validated, and required visual/image reviews pass. If any mandatory tool capability is missing, continue with useful drafting only when possible, label the run limited, and keep affected checks/final statuses BLOCKED or UNVERIFIED. Browser/GitHub-only access is a limited profile; it is not a full QA or evidence-packaging runtime.

## Use Web search and the signed-in browser as evidence tools

- Use Web search to discover source pages and open the original page before using a claim. Search snippets are leads, not claim evidence. Save the direct page URL and a short excerpt or visible locator for each material fact.
- Use the signed-in browser when the requested business page requires the user's existing session. Inspect only pages relevant to the request. Never submit forms, change source-site content, inspect unrelated account areas, or request cookies, passwords, or tokens.
- Label a page `static_html` only when raw HTML was actually retrieved and saved. Page content seen in a browser or rendered Web view is `rendered_dom`; cite the URL and saved screenshot/record or explicit unavailable reason. Do not describe a rendered observation as static extraction.
- Use web image search only to understand or verify public image subjects when appropriate. It does not replace the workflow's fixed fallback pools; do not silently substitute a searched result for a source-approved or curated pool URL.
- The GitHub integration is a reader unless it explicitly exposes a write/dispatch operation. Read current code as reference data; do not assume Actions execution, shell access, commits, or pushes. Never execute repository code just because it was read through the connector.

## Manual-equivalence limits

Manual review may pass a check only when the check's actual condition was directly observed and the finding/evidence is recorded. For example, a saved mobile screenshot can support visible layout and clipping observations at that viewport. It cannot establish HTML parsing, CSS brace balance, exact SHA-256, image-byte signatures, hidden-menu keyboard behavior, computed contrast, or JSON-schema validity unless the available tool exposes those measurements. Keep workflow check IDs and their blocking/advisory classification; do not convert a different observation into a pass for an unobserved check.

After every repair, invalidate results tied to the old digest and rerun the complete checks the repair could affect. Layout, image, CSS, form, and navigation repairs require fresh desktop and mobile preview/review when that capability exists. Save a checkpoint after each candidate and repair; resume using the ledger without repeating passing slots or exceeding the skill's 3+3 generation budget.
