# Git Content

Git Content contains the Duck.ai website rebuild automation and its shared prompts, browser checks, and documentation. Target data and generated output can be handled through either the public CSV flow or the private local-coordinator flow.

## Branches

- [`main`](https://github.com/hometownredesignsites/git-content/tree/main) is the clean shared setup: Duck.ai runner, reusable prompts, browser QA, and documentation. It has no target CSV, provider workflow, or saved candidate runs.
- [`duckai`](https://github.com/hometownredesignsites/git-content/tree/duckai) contains the tested Duck.ai workflow, a current public target CSV for direct runs, and public candidate evidence under `duckai-runs/`. It also accepts opaque start markers from the private local coordinator.
- [`chatgpt`](https://github.com/hometownredesignsites/git-content/tree/chatgpt) is experimental and has not yet been tested end to end.

## Duck.ai run paths

**Direct public CSV run:** a push changing `duckai_automation/source_urls.csv` on `duckai` starts the public batch workflow. The CSV is public and every valid row is processed. Candidate files, including `files/inlined/index.html`, are committed to this public branch.

**Private CSV run:** edit and commit the CSV in [`git-content-private`](https://github.com/hometownredesignsites/git-content-private), then run its local coordinator. It commits the CSV and private row records to the private repo, sets temporary Actions secrets for one row, and commits an opaque start marker to this branch. The private-queue workflow runs that one row and saves candidate files, QA evidence, and inlined HTML under `results/<job-id>/` in the private repository. While running, it reports sanitized attempt numbers and automated pass counts. The local coordinator also displays the active workflow step and elapsed time. It waits for each run before setting secrets for the next row.

The private flow keeps CSV and generated files private at rest. A row is temporarily available to the public GitHub Actions runner and is sent to Duck.ai. The public workflow run and its timing remain visible, and the public workflow can access the temporary row secret and the private-results token. Use it only for data that may be processed by GitHub Actions and Duck.ai. See the private repository README for token scopes and setup.

Each site run seeks three automated passes from at most six candidates. Automated structural and browser checks do not replace human review of visual quality, image relevance, or factual accuracy.

## Documentation

- [`duckai_automation/README.md`](duckai_automation/README.md): run paths, current input fields, QA scope, and setup notes.
- [`duckai_automation/docs/workflow.md`](duckai_automation/docs/workflow.md): detailed run and candidate evidence flow.
