# Duck.ai website generation

This directory contains the Duck.ai prompts, browser runner, checks, and workflow documentation. The shared setup is on `main`. The `duckai` branch adds the Actions worker that accepts private target jobs from the local coordinator in [`git-content-private`](https://github.com/hometownredesignsites/git-content-private).

## Private target flow

1. Edit the CSV in the private repository and run its local coordinator.
2. The coordinator commits the CSV and per-target records to the private repository.
3. For one target at a time, it sets the `DUCKAI_TARGET_ROW_JSON` and `DUCKAI_TARGET_JOB_ID` temporary secrets and pushes an opaque start marker to the public `duckai` branch.
4. The Duck.ai private-queue workflow reads the temporary row, generates candidates, and runs structural and Playwright checks.
5. The worker reads the authoritative job record from private `main`, then commits candidate files, diagnostics, and `files/inlined/index.html` to the private `duckai` branch at `results/<site-slug>/run-<workflow-id>-<attempt>/candidates/`. It does not persist target rows or generated sites on this public repository branch.
6. The coordinator waits for the run, removes the temporary row secrets, and then handles the next target.

The worker aims for three automated passes and stops after at most ten complete candidate attempts. Its progress messages contain attempt/pass counts, and the local coordinator reports the active workflow step and elapsed time. Duck.ai rows remain serial because they share temporary secrets. Publish input batches to private `main` one at a time; after a batch's job records are committed, Duck.ai and future provider workers can write concurrently to their separate result branches.

The public Actions run, timing, and opaque job marker are visible. The target row is temporarily available to the public GitHub Actions runner and is sent to Duck.ai. The `PRIVATE_RESULTS_TOKEN` secret lets the public workflow write results to the private `duckai` branch. Provider-specific row secrets prevent one provider's run from overwriting another provider's active row; the local coordinator still processes each provider's rows serially. Restrict write access to trusted maintainers; workflow changes on the public branch can affect how the secret is used. Do not submit data that cannot be processed by GitHub Actions and Duck.ai. Earlier public CSV and generated run files remain in this repository's Git history; this workflow does not remove them from older commits.

## Fields used by the generation prompt

| CSV column | Required | Use |
| --- | --- | --- |
| `website` | Yes | Source site to inspect and validate citations against. |
| `business` | Yes | Unverified business identification context. |
| `category` | Yes | Unverified industry and design context. |
| `location` | No | Unverified clue; the source site must confirm it before use as fact. |

The private coordinator passes all columns to the worker. The standard prompt uses the fields above; additional columns are exposed as `CSV_FIELD_<HEADER>` variables but do not affect content unless the runner or prompt is updated.

## Candidate process and checks

Each candidate uses a fresh logged-out Duck.ai chat. The runner requests a sourced site assessment, then CSS parts 1–3, an acknowledgment turn, and HTML parts 1–3 in the same chat. It validates the captured chunks, assembles the page, inlines CSS, and checks the exact inlined page in Playwright at desktop and mobile sizes. The structural and browser checks cover required page sections, hero and CTA behavior, mobile navigation, overflow, fonts, and images.

Automated passes are provisional: checks do not establish visual polish, image relevance, or factual accuracy. Review the screenshots and source-derived content in private results before using a page. If Duck.ai requires sign-in or presents a human-verification or usage gate, the candidate stops and records available failure evidence; the workflow does not bypass that gate.

## Documentation

- [`website_request.txt`](website_request.txt): sourcing, content, asset, and output requirements.
- [`design_brief.txt`](design_brief.txt): source-informed visual direction guidance.
- [`docs/workflow.md`](docs/workflow.md): workflow sequence, QA scope, and evidence layout.
