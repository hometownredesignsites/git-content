from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_candidates import check  # noqa: E402


BASE = '''<!doctype html><html lang="en"><head><title>Demo</title>
<meta name="viewport" content="width=device-width"><style>:focus-visible { outline: 2px solid; }</style></head>
<body><main><h1>Demo</h1><section id="contact"><h2>Contact</h2>
<label for="email">Email</label><input id="email" type="email"></section></main></body></html>'''

MENU = '''<header><button type="button" class="menu-toggle" aria-controls="mobile-nav"
aria-expanded="false" aria-label="Open navigation"><span aria-hidden="true"></span>
<span aria-hidden="true"></span><span aria-hidden="true"></span></button>
<nav id="mobile-nav" hidden></nav></header>'''


class ContactSendButtonTests(unittest.TestCase):
    def validate(self, html: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.html"
            path.write_text(html, encoding="utf-8")
            return check(path)

    def test_source_derived_contact_fields_require_send_button(self) -> None:
        issues = self.validate(BASE)
        self.assertTrue(any("no-op CTA" in issue for issue in issues), issues)

    def test_named_enabled_type_button_passes_cta_check(self) -> None:
        html = BASE.replace(
            "</section>",
            '<p>Preview only: nothing is sent or stored.</p>'
            '<button type="button">Send inquiry</button></section>',
        )
        issues = self.validate(html)
        self.assertFalse(any("no-op CTA" in issue for issue in issues), issues)

    def test_source_derived_contact_fields_require_no_send_disclosure(self) -> None:
        html = BASE.replace(
            "</section>",
            '<button type="button">Send inquiry</button></section>',
        )
        issues = self.validate(html)
        self.assertTrue(any("disclosure" in issue for issue in issues), issues)

    def test_disabled_button_fails_cta_check(self) -> None:
        html = BASE.replace(
            "</section>", '<button type="button" disabled>Send</button></section>'
        )
        issues = self.validate(html)
        self.assertTrue(any("no-op CTA" in issue for issue in issues), issues)

    def test_submit_default_does_not_count_as_safe_demo_button(self) -> None:
        html = BASE.replace("</section>", "<button>Send</button></section>")
        issues = self.validate(html)
        self.assertTrue(any("no-op CTA" in issue for issue in issues), issues)

    def test_accessible_name_without_visible_send_text_is_not_a_visible_cta(self) -> None:
        html = BASE.replace(
            "</section>",
            '<button type="button" aria-label="Send inquiry"><span aria-hidden="true">✉</span></button></section>',
        )
        issues = self.validate(html)
        self.assertTrue(any("no-op CTA" in issue for issue in issues), issues)

    def test_non_contact_page_does_not_require_form_button(self) -> None:
        html = BASE.replace(
            '<section id="contact"><h2>Contact</h2>',
            '<section id="services"><h2>Services</h2>',
        )
        issues = self.validate(html)
        self.assertFalse(any("no-op CTA" in issue for issue in issues), issues)

    def test_file_upload_control_is_always_rejected(self) -> None:
        html = BASE.replace(
            '</section>', '<input type="file" name="project-photo"></section>'
        )
        issues = self.validate(html)
        self.assertTrue(any("File upload controls are prohibited" in issue for issue in issues), issues)

    def test_mobile_menu_matches_browser_runner_selector(self) -> None:
        html = BASE.replace("<body>", f"<body>{MENU}")
        issues = self.validate(html)
        self.assertFalse(any("Mobile menu must use" in issue for issue in issues), issues)

    def test_mobile_menu_with_two_bars_is_rejected(self) -> None:
        two_bars = MENU.replace('<span aria-hidden="true"></span>', '', 1)
        html = BASE.replace("<body>", f"<body>{two_bars}")
        issues = self.validate(html)
        self.assertTrue(any("exactly three direct" in issue for issue in issues), issues)

    def test_mobile_menu_bars_without_aria_hidden_are_rejected(self) -> None:
        unlabeled_bars = MENU.replace(' aria-hidden="true"', '')
        html = BASE.replace("<body>", f"<body>{unlabeled_bars}")
        issues = self.validate(html)
        self.assertTrue(any("exactly three direct" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
