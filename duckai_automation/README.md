# Duck.ai website generation

This directory contains the Duck.ai prompts, runner, browser checks, and documentation. The shared setup is on `main`; the tested Actions workflow and current public CSV are on `duckai`. Each candidate uses a fresh logged-out Duck.ai chat. The runner first asks Duck.ai to assess the source site, then requests CSS, an acknowledgment turn, and HTML in the same chat before assembling the page and inlining the CSS.

## Run paths

### Public CSV workflow

On `duckai`, a push that changes [`source_urls.csv`](source_urls.csv) starts a full public batch for every valid row. Its `website`, `business`, `category`, and optional `location` values are public in Git history. Generated candidate files and QA evidence are committed under `duckai-runs/` on the public branch. A full batch seeks three automated passes per row, stopping after six candidates.

### Private CSV workflow

For private rows and outputs, use the local coordinator in [`git-content-private`](https://github.com/hometownredesignsites/git-content-private). The local script commits the CSV and private row records to that repository, sets one temporary `PRIVATE_TARGET_ROW_JSON` secret and one opaque job ID secret in this repository, then commits a start marker under `.private-queue/start/` to `duckai`. The private queue workflow runs one site, stores all candidate outputs and the inlined preview in the private repository, and the local script removes the temporary row secrets before it starts the next row.

This branch's private worker uses the static `PRIVATE_RESULTS_TOKEN` Actions secret to commit output to `git-content-private`. It does not fetch a private queue, does not need a private-repo read token, and does not commit the private row or candidate files to this public branch. Setup, permissions, and privacy limits are documented in the private repo README.

The private workflow uses a shared pair of temporary secrets, so rows must run serially. Its public Actions run and timing remain visible. The public runner receives the row temporarily, and the row is sent to Duck.ai; this does not protect data from GitHub Actions or Duck.ai. Anyone who can modify this public workflow could change how those secrets are used, so keep write access limited to trusted maintainers.

The private flow passes every CSV column as part of the row JSON and exports additional columns as `CSV_FIELD_<HEADER>` environment variables. The current generation prompt uses `website`, `business`, `category`, and `location`; a new column will not affect generated content unless the runner or prompts are explicitly updated to use it.

## Fields currently used by the prompt

| CSV column | Required | Use |
| --- | --- | --- |
| `website` | Yes | Source site to inspect and the domain used to validate source citations. |
| `business` | Yes | Unverified business identification context. |
| `category` | Yes | Unverified industry and design context. |
| `location` | No | Unverified location clue; the source site must confirm it before use as fact. |

The website remains authoritative for factual claims. The CSV on `duckai` currently contains 21 public targets.

- [`website_request.txt`](website_request.txt): reusable sourcing, content, asset, and output requirements.
- [`design_brief.txt`](design_brief.txt): guidance for deriving a visual direction from the source site's brand.
- [`source_urls.csv` on `duckai`](https://github.com/hometownredesignsites/git-content/blob/duckai/duckai_automation/source_urls.csv): public target list for direct CSV runs.
- [`docs/workflow.md`](docs/workflow.md): detailed workflow, QA checks, and output layout.

The YAML declares `workflow_dispatch` inputs, but these workflows exist only on `duckai` while `main` remains the default branch. GitHub requires a workflow file on the default branch for manual dispatch from the Actions interface. The currently supported triggers are the CSV push for the public batch and opaque start-marker push for the private worker. See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

## Candidate attempts and QA

One workflow run makes up to six complete candidate attempts to obtain three automated passes. The private workflow handles one site per run; the public CSV workflow creates one serialized job per row. Each successful candidate has a CSS file, raw HTML, an inlined HTML preview at `files/inlined/index.html`, and automated browser/checker evidence. The public path commits these under `duckai-runs/`; the private path commits them under `results/<job-id>/` in the private repo. Failures retain available diagnostics.

Playwright checks page structure and rendered behavior at desktop and mobile sizes, including requested sections, hero layout, CTA visibility, mobile navigation, overflow, fonts, images, and CTA labels/icons. These checks do not judge visual polish, image relevance, or factual accuracy. Three automated passes are not human approval.

The separate **Duck.ai Rendered Website QA** action rechecks saved public candidate files without starting new Duck.ai chats. The private worker captures browser QA during generation and stores the evidence privately.

## Safety and access

The browser stays logged out. If Duck.ai requires sign-in or presents a human-verification or usage gate, the candidate stops and saves its failure evidence; the workflow does not try to bypass the gate.
