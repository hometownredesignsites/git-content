# Duck.ai website generation

This directory contains the shared Duck.ai prompts, runner, browser checks, and documentation. The target CSV is tracked only on `duckai`; `main` contains setup without target data or GitHub Actions workflows, while `duckai` adds the workflows and saves their outputs. Each candidate uses a fresh logged-out Duck.ai chat. The CSV supplies a website URL, business name, category, and optional location. Duck.ai receives the metadata as unverified context, assesses the live site in that same chat, and uses the audit as its factual source.

## Run it

On branch `duckai`, a push that changes [`source_urls.csv`](source_urls.csv) starts a batch for every valid row in the file. The CSV requires `business`, `category`, and `website` columns; `location` is optional. Changes to the reusable request or design brief alone do not start a generation run.

The workflow YAML defines `workflow_dispatch` inputs for full batches, one-site overrides, and a one-candidate CSV smoke mode. However, the workflow files currently exist only on `duckai`, while `main` is the default branch. GitHub requires the workflow to be present on the default branch for manual dispatch from the Actions interface, so those inputs are not currently available there. The supported trigger in this branch layout is the CSV push. A one-row CSV push still uses full-batch behavior for that row and seeks three automated passes; it is not the one-candidate smoke mode. See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

### CSV fields currently used

| Column | Required | Use in the workflow |
| --- | --- | --- |
| `website` | Yes | The target site Duck.ai assesses and the domain used to validate its source audit. |
| `business` | Yes | Identifies the intended business; sent to Duck.ai as unverified context. |
| `category` | Yes | Primary industry cue; sent to Duck.ai as unverified design context. |
| `location` | No | Sent as unverified location context; use as a fact only if the source site confirms it. |

Only these four columns are read. Other columns in a CSV are ignored. The website is authoritative for factual claims; business, category, and optional location help Duck.ai identify the target and guide design. The `duckai` branch CSV currently contains 21 websites.

- [`website_request.txt`](website_request.txt): reusable content, sourcing, asset, and output requirements.
- [`design_brief.txt`](design_brief.txt): reusable guidance for deriving a brand-specific visual direction from the source.
- [`source_urls.csv` on `duckai`](https://github.com/hometownredesignsites/git-content/blob/duckai/duckai_automation/source_urls.csv): one row per website target; the business and category fields are sent to Duck.ai.

Keep the request and brief separate: the request defines what to learn and build; the brief translates the source site's brand into a design, using industry cues as a secondary guide rather than assuming a preset palette. The runner combines them in the same prompt, so this separation does not add a chat turn.

The workflow uses Ubuntu, a pinned Playwright Python container, and headed Chromium under Xvfb for Duck.ai. It asks for CSS parts 1–3, sends `acknowledged` as a separate user turn, and then asks for HTML parts 1–3 in the same chat. It verifies and assembles those captured parts, creates an inlined-CSS version, and renders the result for browser QA. The documented end-to-end sequence and output layout are in [`docs/workflow.md`](docs/workflow.md).

One workflow execution validates the CSV and creates one matrix job per website. Those jobs run one at a time. Each site job generates full candidates in a loop until it has three automated passes or has made six attempts; it does not start three separate workflow executions. Thus each site can take 3–6 candidate runs, and the current 21-row CSV can produce up to 126 attempts. Each site job has a 35-minute limit. Every attempted candidate is saved to `duckai-runs/` and committed to `duckai`, including failures, so reports can be inspected. Generated-output commits use `[skip ci]` and do not start another generation run. The separate **Duck.ai Rendered Website QA** action reruns browser and structural checks for every website in a saved batch without opening new Duck.ai chats.

The declared `smoke_test` mode runs one complete source assessment, CSS/acknowledgment/HTML capture, assembly, and browser QA for one selected CSV row and one candidate attempt. It requires one automated pass. It is currently unavailable through the Actions interface because the workflow file is not on the default branch. A CSV push test instead follows the normal three-pass target for each row in the pushed CSV.

## What the checks mean

The automated checks require captured files and expected structure, then use Playwright to inspect the rendered page at desktop and mobile sizes. They check requested sections, hero sizing, first-screen CTA placement, mobile menu behavior, horizontal overflow, fonts and images, and CTA labels/icons for arrows. These checks do not judge whether the design is attractive or whether an image subject is appropriate.

`automated_success: true` means the structural and browser checks passed. Image relevance and screenshot-based visual design review are separate human checks; they remain pending unless a reviewer records that evidence. The workflow does not claim that three candidates have received human approval.

The CTA rule is part of both the generation prompt and structural checker: CTA buttons and button-style links should use clear action text without arrow glyphs or directional icons, including chevrons. The checker reports `cta_buttons_no_arrows` and fails the automated candidate if it finds one.

## Safety and access

The browser stays logged out. If Duck.ai requires sign-in or presents a human-verification or usage gate, the candidate stops and saves its failure evidence; the workflow does not try to bypass the gate. Keep the CSV limited to the fields the workflow uses because it is committed to Git history. The action needs permission to write candidate evidence to the branch.

## Multi-turn smoke test

The separate **Duck.ai Multi-turn Smoke Test** checks two related questions in one guest chat and saves the captured conversation as JSON and Markdown under `duckai-runs/`. It is wired to pushes that change `smoke_test.json`, `run_smoke_test.py`, or its workflow file. Its declared manual trigger is likewise unavailable in the Actions interface until that workflow exists on the default branch. See [`smoke_test.json`](smoke_test.json) for its prompts.
