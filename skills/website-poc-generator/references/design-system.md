### 5. Generate candidates
Create three distinct complete documents from the same verified source brief. Each must include:
- `<!doctype html>`, `<html>`, `<head>`, and `<body>`; useful title and meta description; semantic sections and logical heading hierarchy.
- Exactly one embedded `<style>` element; no external CSS or build dependencies. Inline, dependency-free JavaScript is permitted only for the accessible mobile navigation, a clearly disclosed non-submitting form demonstration, or small progressive-enhancement motion. Keep content and core navigation usable without JavaScript, honor reduced-motion preferences, and do not add external scripts, analytics, storage, or network submission behavior.
- A full-bleed photographic hero: edge-to-edge across the viewport, using a validated source photo or approved validated fallback; deliberate `cover` crop and focal positioning; readable contrast overlay/treatment; and the primary CTA visible in the first viewport on desktop and mobile. Do not use a split-column hero or CSS-only artwork in place of the photo.
- The verified source logo when available, with sensible sizing and preserved proportions.
- The source-grounded copy, validated images, contact details, and form schema required by the source brief.
- Primary CTA labels and icons without arrow glyphs or arrow icons. CTA contrast must be sufficient against its background.
- Responsive navigation. When navigation collapses on mobile, implement a working accessible hamburger/menu interaction (inline, dependency-free JavaScript is allowed for this interaction). Use a real button with an accessible name, `aria-controls`, and synchronized `aria-expanded`; start with the menu hidden/collapsed; support keyboard activation and touch; allow closing by the toggle and Escape; return focus appropriately; preserve visible focus; and ensure menu links work. Do not create inert controls. A no-script alternative is acceptable only if it provides equivalent discoverable open/close and keyboard behavior and passes the same browser checks.
- Responsive layout, accessible labels, visible keyboard focus, and reduced-motion support.
- Meaningful layout and content differences that satisfy each template's defining structure—not merely different colors or typography.

Never include fictional contact information or a placeholder that could be mistaken for real information. Avoid adding interactive controls that do not work. Do not use CSS visuals as substitutes for required photography.
