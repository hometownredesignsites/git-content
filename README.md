# Git Content

Git Content holds shared prompts and tooling for rebuilding business websites with Duck.ai. The repository is public, so it contains no target CSV or generated customer-site output. Private input data and generated results live in [`git-content-private`](https://github.com/hometownredesignsites/git-content-private).

## Branches

- [`main`](https://github.com/hometownredesignsites/git-content/tree/main) is the clean shared setup and default branch. It contains the reusable Duck.ai runner, prompts, browser checks, and documentation. It intentionally has no Actions runner, target list, queue markers, or saved runs.
- [`duckai`](https://github.com/hometownredesignsites/git-content/tree/duckai) adds the Duck.ai GitHub Actions worker. It accepts opaque start markers from the private repo's local coordinator, processes one private target per run, and writes generated candidates and evidence to the private repo. It does not commit target rows or generated site files here.
- [`chatgpt`](https://github.com/hometownredesignsites/git-content/tree/chatgpt) is an experimental provider branch; its end-to-end pipeline has not been validated.

## Private Duck.ai workflow

Edit the CSV in `git-content-private` and run its local coordinator. The coordinator commits the CSV and target records privately, sets temporary Actions secrets for one row, and pushes an opaque marker to `duckai`. The public GitHub Actions worker then processes that one row and commits candidate evidence and inlined HTML to `git-content-private/results/<site-slug>/run-<workflow-id>-<attempt>/`. Three automated passes are sought, with up to ten candidate attempts. Rows are processed serially because the temporary row secrets are shared.

The public Actions run, timing, and opaque marker are visible. During processing, the target row is temporarily available to GitHub Actions and is sent to Duck.ai. Generated site files are persisted only in the private repository. Limit write access to trusted maintainers and only process data that may be handled by GitHub Actions and Duck.ai. See the private repository README for local setup and token permissions.

Automated browser and structural checks do not establish visual quality or factual accuracy; review generated pages before use.

## Documentation

- [`duckai_automation/README.md`](duckai_automation/README.md): provider setup, private workflow, inputs, and checks.
- [`duckai_automation/docs/workflow.md`](duckai_automation/docs/workflow.md): generation sequence, evidence, and private output layout.
