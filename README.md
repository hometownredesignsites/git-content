# Git Content

A shared foundation for source-informed website rebuilds. The repository is organized so provider-specific automation can live on its own branch.

## Branches

- `main` contains the shared Duck.ai project setup, target list, prompts, runner, browser checks, and documentation. It has no GitHub Actions generation workflow and no saved candidate runs.
- `duckai` adds the Duck.ai GitHub Actions workflows and saved candidate evidence. On that branch, pushing a change to `duckai_automation/source_urls.csv` runs the CSV batch; manual dispatch supports a full batch or a single-site override.
- Future provider work, such as ChatGPT, can be developed on a separate branch from this clean base.

See [`duckai_automation/README.md`](duckai_automation/README.md) and [`duckai_automation/docs/workflow.md`](duckai_automation/docs/workflow.md) for the Duck.ai setup and workflow details.
