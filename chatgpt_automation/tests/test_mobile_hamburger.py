from __future__ import annotations

import unittest

from chatgpt_automation.scripts.site_quality import _PageInventory


GOOD_MENU = '''<header><button type="button" class="menu-toggle" aria-controls="mobile-nav"
aria-expanded="false" aria-label="Open navigation"><span aria-hidden="true"></span>
<span aria-hidden="true"></span><span aria-hidden="true"></span></button>
<nav id="mobile-nav" hidden></nav></header>'''


class AccessibleMobileHamburgerTests(unittest.TestCase):
    def has_hamburger(self, markup: str) -> bool:
        parser = _PageInventory()
        parser.feed(markup)
        parser.close()
        return parser.has_accessible_mobile_hamburger()

    def test_three_direct_aria_hidden_bars_pass(self) -> None:
        self.assertTrue(self.has_hamburger(GOOD_MENU))

    def test_two_bars_fail(self) -> None:
        self.assertFalse(self.has_hamburger(GOOD_MENU.replace('<span aria-hidden="true"></span>', '', 1)))

    def test_bars_without_aria_hidden_fail(self) -> None:
        self.assertFalse(self.has_hamburger(GOOD_MENU.replace(' aria-hidden="true"', '')))

    def test_nested_bars_fail(self) -> None:
        nested = GOOD_MENU.replace(
            '<span aria-hidden="true"></span>',
            '<span class="bars"><span aria-hidden="true"></span></span>',
            1,
        )
        self.assertFalse(self.has_hamburger(nested))

    def test_menu_button_must_explicitly_be_non_submit(self) -> None:
        self.assertFalse(self.has_hamburger(GOOD_MENU.replace('type="button" ', '')))


if __name__ == "__main__":
    unittest.main()
