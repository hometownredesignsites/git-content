# Pass 2: Design enhancement rubric

This concise, original rubric defines **Pass 2: design enhancement**. The selected inference provider applies it to the corrected HTML and headless Playwright screenshots. The skill repositories are reference material only; the script does not invoke Claude or fetch external guidance at run time.

- **ENH-01 — Distinct design direction:** Propose a coherent direction for this page. Preserve its existing strengths and identity.
- **ENH-02 — Design-system fit:** Consider page pattern, color roles, type pairing, spacing, imagery, and interaction as one system. Tie recommendations to the supplied customer category and the content actually present.
- **ENH-03 — Clear hierarchy:** Make the primary message, supporting information, and next action easy to scan.
- **ENH-04 — Intentional visual treatment:** Improve composition, whitespace, typography, color, and imagery only where screenshots or source evidence support a change.
- **ENH-05 — Responsive behavior:** Keep the page readable and usable at the supplied desktop and mobile viewports.
- **ENH-06 — Restraint and accessibility:** Preserve content, functioning links, and Pass 1 fixes. Do not add unsupported claims or functionality; maintain visible focus and respect reduced-motion preferences where motion exists.

For every proposed enhancement, provide `criterion_id`, `priority`, `design_rationale`, `evidence`, `user_benefit`, `change`, and `confidence`. Keep the current direction if it works. Do not force Apple branding, Liquid Glass, a shared palette, or any ungrounded design pattern.

This rubric is a curated paraphrase for customer HTML pages. It does not copy skill datasets, install their tooling, apply Apple platform conventions, or assume a particular design system.
