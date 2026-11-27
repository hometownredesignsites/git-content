# Public ChatGPT website worker

The `chatgpt` branch contains the public code for generating and validating website candidates. Production runs start only when the private coordinator adds an opaque marker under `.private-queue/start/`; ordinary code pushes and manual URL dispatches do not start a production run.

The worker receives the active task through temporary GitHub Actions secrets, uses an anonymous ChatGPT browser session, and stores candidate HTML and evidence in the private `git-content-private` repository. This public repository stores workflow code and sanitized status information, not customer source records or candidate HTML.

The workflow produces candidates and applies deterministic HTML, accessibility, and rendered-browser checks before handing successful candidates to the private results repository. The separate NVIDIA HTML assessment workflow is disabled.

## Documentation

- [`skills/website-poc-generator/`](skills/website-poc-generator/SKILL.md) — generate three standalone website POC candidates and run candidate validation/browser QA.
- [`skills/phase2-website-assessment/`](skills/phase2-website-assessment/SKILL.md) — slot-assigned Phase 2 assessment/redesign workflow; follows generation and assessment handoffs.

- [`chatgpt_automation/README.md`](chatgpt_automation/README.md) — workflow, privacy boundaries, candidate generation, validation, and repository handoffs.
- [`chatgpt_automation/html_assessment/README.md`](chatgpt_automation/html_assessment/README.md) — the separate assessment workflow and its current disabled status.

## Retired legacy content

The standalone FastAPI inference service, its generic request-processing workflow, and their generated request/response artifacts have been removed from the active `chatgpt` branch. Earlier commits may still contain those files; this cleanup changes the current branch tree and does not rewrite Git history.
