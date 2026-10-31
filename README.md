# Git Content

Git Content holds shared prompts and tooling for rebuilding business websites with Duck.ai. The current branch contents contain no target CSV or generated customer-site output; private input data and current generated results live in [`git-content-private`](https://github.com/hometownredesignsites/git-content-private). Earlier public CSVs and generated run files remain accessible in Git history because history has not been rewritten. Earlier public Actions run records may also remain visible.

## Branches

- [`main`](https://github.com/hometownredesignsites/git-content/tree/main) is the clean shared setup and default branch. It contains the reusable Duck.ai runner, prompts, browser checks, and documentation. It intentionally has no GitHub Actions workflow, target list, queue markers, or saved runs.
- [`duckai`](https://github.com/hometownredesignsites/git-content/tree/duckai) adds the Duck.ai GitHub Actions worker. It accepts opaque start markers from the private repo's local coordinator, processes one private target per run, and writes generated candidates and evidence to the private repo's `duckai` results branch. It does not commit target rows or generated site files here.
- [`chatgpt`](https://github.com/hometownredesignsites/git-content/tree/chatgpt) is an experimental provider branch; its end-to-end pipeline has not been validated. Its intended private destination is the paired `chatgpt` branch in `git-content-private`.

## Private Duck.ai workflow

Edit the CSV in `git-content-private` and run its local coordinator. The coordinator commits the CSV and target records privately on private `main`, sets Duck.ai-specific temporary Actions secrets for one row, and pushes an opaque marker to public `duckai`. The public GitHub Actions worker reads the authoritative job record from private `main`, then writes candidate evidence and inlined HTML to private `duckai` at `results/<site-slug>/run-<workflow-id>-<attempt>/`. Three automated passes are sought, with up to ten candidate attempts. The private `chatgpt` branch is reserved as the destination for a future ChatGPT worker. Provider branches keep their result commits separate; rows within a provider are processed serially by the local coordinator.

The public Actions run, timing, and opaque marker are visible. During processing, the target row is temporarily available to GitHub Actions and is sent to Duck.ai. Generated site files are persisted only in the private repository. Limit write access to trusted maintainers and only process data that may be handled by GitHub Actions and Duck.ai. See the private repository README for local setup and token permissions.

Automated browser and structural checks do not establish visual quality or factual accuracy; review generated pages before use.

## Documentation

- [`duckai_automation/README.md`](duckai_automation/README.md): provider setup, private workflow, inputs, and checks.
- [`duckai_automation/docs/workflow.md`](duckai_automation/docs/workflow.md): generation sequence, evidence, and private output layout.
