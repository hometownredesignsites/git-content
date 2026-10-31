# Git Content

Git Content is a public workspace for source-informed website rebuilds. The repository uses `main` as the clean shared base and keeps provider-specific automation on separate branches.

## Branches

- [`main`](https://github.com/hometownredesignsites/git-content/tree/main) contains the shared Duck.ai setup: prompts, runner, browser checks, and documentation. It has no target CSV, GitHub Actions pipeline, or saved run files.
- [`duckai`](https://github.com/hometownredesignsites/git-content/tree/duckai) adds the target CSV, Duck.ai workflows, and saved candidate evidence under `duckai-runs/`. The CSV is tracked only on this branch. Pushing a change to `duckai_automation/source_urls.csv` starts a batch for every valid CSV row.
- A ChatGPT provider branch is planned; it has not been created yet.

## Duck.ai pipeline

Each CSV row supplies a business name, category, optional location, and source website. For each website, the pipeline attempts up to six complete candidates to obtain three automated passes. With the 21-row CSV on `duckai`, a full batch can create up to 126 candidate folders. Generated HTML, including the CSS-inlined preview at `files/inlined/index.html`, and QA evidence are committed to `duckai`.

Automated passes cover structural and browser checks. They do not replace human review of visual quality, image relevance, or factual accuracy.

### Manual dispatch availability

The workflow files currently exist only on `duckai`, while `main` is the default branch. GitHub requires a workflow to exist on the default branch before it can be manually dispatched from the Actions interface, so the declared `workflow_dispatch` inputs are not currently available there. The working trigger is a push to `duckai` that changes `duckai_automation/source_urls.csv`. See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

See [`duckai_automation/README.md`](duckai_automation/README.md) and [`duckai_automation/docs/workflow.md`](duckai_automation/docs/workflow.md) for the workflow details.
