# Design and implementation review rubric

This concise, original rubric defines **Pass 1: repair**. The selected inference provider performs every page assessment and recommendation. No Claude model is called and no GitHub service is contacted at run time.

## Review criteria

For each finding, name one criterion ID, provide observable evidence from the supplied HTML or screenshot, explain the user impact, and give a focused recommendation. Do not manufacture findings to fill categories. Say when evidence is insufficient.

### Baseline quality checks

- **ART-01 — Existing page identity:** Record the visual direction to preserve. Do not propose new styling in Pass 1.
- **ART-02 — Existing concept consistency:** Record concrete breaks in the page's own current visual system only when they look like defects, such as a visibly broken component or inconsistent state.
- **VIS-01 — Hierarchy and legibility defects:** Flag content that is clipped, obscured, unreadable, or missing from the supplied viewports. Do not recommend decorative redesign.
- **VIS-02 — Image correctness:** Flag broken or clearly mismatched images supported by source or screenshot evidence. State uncertainty where subject matter cannot be confirmed.
- **VIS-03 — Existing component defects:** Flag broken or conflicting components only when they impair understanding or use.

### Usability, conversion, and responsive behavior

- **UX-01 — Truthful, working next step:** Does each prominent call to action describe what it actually does and lead to a valid destination? Never imply a form, quote submission, or service exists unless the HTML establishes it.
- **UX-02 — Navigation and interaction:** Are links and controls represented with suitable semantics and clear labels? Can visitors understand their destinations and use them by keyboard or touch?
- **RESP-01 — Responsive layout:** In the supplied desktop and mobile screenshots, look for clipping, overlap, awkward wrapping, unreadable text, cramped controls, or lost content. Do not claim full device coverage from two viewport captures.
- **MOTION-01 — Motion comfort:** When motion is present in code, check whether reduced-motion preferences are respected. Do not infer animation behavior from a static screenshot.

### Accessibility and implementation quality

- **A11Y-01 — Semantics and alternatives:** Inspect heading order, landmarks, image alternatives, link names, and control names where visible in source. Prefer native HTML semantics before ARIA.
- **A11Y-02 — Keyboard and focus:** Inspect focus styling and keyboard-relevant code. Screenshots can confirm visible focus only when a focused state was captured; otherwise state that runtime behavior was not verified.
- **A11Y-03 — Contrast:** Flag likely contrast problems supported by source colors or screenshots. Do not claim WCAG conformance without measured color values and an appropriate calculation.
- **CODE-01 — Robust markup and links:** Look for malformed or redundant markup, empty containers, broken in-page fragment targets, missing image dimensions, and other concrete source issues. Distinguish a static source check from a tested browser result.
- **CODE-02 — Maintainability and performance:** Recommend code or loading changes only when supported by this page's source and likely user impact. Avoid speculative optimization.

## Priority definitions

- **High:** Blocks a primary task, hides important content, creates a serious accessibility barrier, or makes a prominent action misleading or unusable.
- **Medium:** Causes meaningful friction or weakens comprehension, trust, responsive behavior, or accessibility for a plausible group of visitors.
- **Low:** A polish issue with limited impact.

Use the fewest useful findings. Pass 1 fixes defects and omissions; it does not add visual flourishes, change the design direction, or introduce new sections. Each finding must include `criterion_id`, `priority`, `finding`, `evidence`, `user_impact`, `recommendation`, and `confidence` (`high`, `medium`, or `low`). Keep observed facts separate from hypotheses.

## Pinned reference sources

- Anthropic Claude Code `frontend-design` skill, pinned at commit [`10a5141d2d12b5a089a5fbb5f24af3fd345a34d2`](https://github.com/anthropics/claude-code/tree/10a5141d2d12b5a089a5fbb5f24af3fd345a34d2/plugins/frontend-design/skills/frontend-design). Informs deliberate art direction, contextual visual choices, and concept identity.
- Vercel Labs `web-design-guidelines` skill, pinned at commit [`ba46938889d4e58635362fb8f618e1178ac3ec46`](https://github.com/vercel-labs/agent-skills/tree/ba46938889d4e58635362fb8f618e1178ac3ec46/skills/web-design-guidelines). Its referenced [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/4ecfb9fb8d1d3b7009674869b3aaee2f904042e1/command.md) are pinned at commit [`4ecfb9fb8d1d3b7009674869b3aaee2f904042e1`](https://github.com/vercel-labs/web-interface-guidelines/commit/4ecfb9fb8d1d3b7009674869b3aaee2f904042e1) and inform accessibility, semantics, interaction, motion, responsive behavior, imagery, and performance criteria.

This is a curated paraphrase for Pass 1 on static marketing pages. Framework-specific guidance and rules that cannot be observed from source or supplied screenshots are excluded.
