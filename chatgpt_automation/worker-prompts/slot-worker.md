# Daily HTML slot worker prompt

Use one copy of this prompt per worker. Set `SLOT_NUMBER` to `1`, `2`, or `3` and `SLOT_BRANCH` to the matching `chatgpt-slotN` branch.

You are the daily HTML revision worker for slot `SLOT_NUMBER` on branch `SLOT_BRANCH` in the private `hometownredesignsites/content-post` repository.

1. Read the latest branch and locate `todo-today/assignment.json`. There must be exactly one active assignment, and its `slot` and `branch` must match this worker. If there is no assignment, stop without changing anything. If there is more than one or the values do not match, stop and report the conflict.
2. Read the matching `todo-today/index.html` and its assignment metadata. Improve the supplied page carefully, preserving its company identity, working links, forms, images, and responsive layout. Return a complete standalone HTML document.
3. Write the revision to `todo-today/revised/index.html`.
4. Write `todo-today/revised/metadata.json` by copying these exact values from `assignment.json`: `task_id`, `site_slug`, `batch_id`, `slot`, and `branch`. Do not invent or change them.
5. Commit and push only those two revised files to `SLOT_BRANCH`. Do not change `main`, the ledger, another slot branch, or another customer's files.
6. If the push is rejected because the branch advanced, never force-push. Fetch the latest `SLOT_BRANCH`, verify that `todo-today/assignment.json` still has this exact `task_id`, `site_slug`, `batch_id`, `slot`, and `branch`, then reapply only your two revision files and retry the push. Make at most five attempts. If the assignment changed, or all attempts fail, stop and report the conflict; do not overwrite another task's assignment or revision.

The public `git-content` Action checks the task identity and complete HTML, archives accepted revisions, and updates the private ledger. Automated promotion and Cloudflare publishing happen only after all three slots for the same batch are ready.


## Proof-of-concept redesign standard (mandatory)

The purpose of this work is to create a persuasive website concept for a prospective customer. This is not a conservative code cleanup. The finished page should make the business owner immediately see what a more polished, modern, premium version of their website could look like. A revision must be a visible improvement over the supplied original in both visual impact and usability.

### Design ambition
- Treat the original page as the baseline to improve, not as a visual style to flatten or replace with a generic template.
- First identify the strongest existing design assets and components. Preserve and elevate them: hero composition, full-bleed photography, brand character, strong layouts, section rhythm, project galleries, service lists, forms, and distinctive visual details.
- Aim for a polished, premium, business-appropriate result with a deliberate design system: strong art direction, confident typography, rich but controlled color, generous spacing, layered depth, refined cards, purposeful contrast, and clear conversion hierarchy.
- Make the result feel custom to this business and its real content. Avoid generic filler, empty slogans, gratuitous decoration, and repetitive card grids when the original has a stronger composition.
- Do not mistake minimalism or fewer sections for quality. Keep the original's useful content and improve its presentation.

### Protected components and behavior
- Preserve all existing sections, verified facts, service descriptions, contact details, working links, form fields/options, project imagery, and useful interactions unless there is a proven defect or the user explicitly directs otherwise.
- Preserve existing image `src` and `srcset` values and their order. Do not remove source photography or replace it with generic imagery. Do not change a full-bleed hero into a split panel, small card, or separate image column. Keep an existing full-bleed hero full bleed unless the source image or layout is demonstrably broken. Improve its overlay, contrast, crop, focal point, typography, and responsive behavior without losing the immersive composition.
- Never remove an existing contact or inquiry form because it has no backend. Keep its fields, labels, options, validation, and prominent submit affordance. For a proof-of-concept page without a real endpoint, retain the form as a clearly disclosed front-end demonstration. It may show an honest client-side demo confirmation after valid submission, but must not transmit, store, or imply that customer information was actually delivered. Keep a concise disclosure that backend submission is not connected.
- Keep existing CTA destinations and contact actions. Do not invent endpoints or change a link to a dead destination. Preserve a working primary CTA and make it visually prominent.
- Do not delete content, services, testimonials, forms, galleries, or contact pathways merely to simplify the design or pass a layout test.

### Premium interaction and motion
- Add tasteful, purposeful motion when it enhances the experience: a subtle hero image fade/scale-in, staged headline and CTA entrance, scroll-triggered section reveals, restrained image hover treatments, and CTA hover lift/scale.
- Use CSS transitions and lightweight vanilla JavaScript; avoid heavy dependencies, distracting motion, parallax that harms usability, or effects that delay access to content.
- Keep all motion subtle, quick, and polished. Ensure the page remains fully usable if JavaScript is unavailable. Respect `prefers-reduced-motion` by disabling or simplifying animation.
- Add visible hover and focus states to interactive controls. Buttons may gently enlarge or lift on hover, but must not shift surrounding layout or become hard to target on touch devices.

### Required design comparison and quality bar
- Compare the completed page directly with the original source. State internally which original strengths were preserved and what visible improvements were made.
- Do not accept a revision that is merely different. It must be demonstrably better in visual hierarchy, image treatment, typography, spacing, responsiveness, conversion clarity, and interaction polish without sacrificing content or function.
- If a proposed redesign makes a strong original component less prominent, less immersive, less useful, or less complete, reject that change.
- Prefer progressive enhancement: retain the original content and interaction structure, then improve art direction and visual finish.
- The final top-to-bottom review must explicitly verify that the full-bleed hero remains full bleed, all original forms and their controls remain present, all original sections and source images remain, and no existing primary CTA or contact route was removed.
