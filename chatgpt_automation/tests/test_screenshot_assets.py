from __future__ import annotations

import base64
from email.message import Message
import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_automation.scripts.screenshot_assets import build_embedded_screenshot_html
from chatgpt_automation.scripts.site_quality import _browser_qa_result


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (2).to_bytes(4, "big") + (3).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class FakeResponse:
    def __init__(self, data: bytes, url: str, status: int = 200, content_type: str = "image/png"):
        self.data = data
        self.url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def read(self, _limit=-1):
        return self.data


class ScreenshotAssetsTests(unittest.TestCase):
    def test_embeds_img_src_srcset_picture_inline_and_stylesheet_images(self):
        html = '''<!doctype html><html><head><style>.hero{background-image:url("/hero.png")}</style></head>
        <body><picture><source srcset="/small.png 480w, /large.png 1200w"><img src="/photo.png" data-src="/lazy.png" alt="Car"></picture>
        <div style="background:url('/inline.png')"></div></body></html>'''.encode()
        requested = []

        def opener(request, timeout=15):
            requested.append((request.full_url, timeout))
            return FakeResponse(PNG, request.full_url)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tmp" / "candidate.html"
            result = build_embedded_screenshot_html(html, "https://example.test/page/", output, opener)
            embedded = output.read_text(encoding="utf-8")

        self.assertEqual("pass", result["status"])
        self.assertEqual(6, result["reference_count"])
        self.assertEqual(6, result["embedded_count"])
        self.assertEqual(6, len(requested))
        self.assertEqual(1, len({item["sha256"] for item in result["images"]}))
        self.assertTrue(all(item["bytes"] == len(PNG) for item in result["images"]))
        self.assertEqual(6, embedded.count("data:image/png;base64," + base64.b64encode(PNG).decode()))
        self.assertIn("srcset=", embedded)

    def test_failed_download_blocks_and_never_writes_partial_embedded_html(self):
        html = b'<html><body><img src="https://example.test/photo.png"></body></html>'

        def opener(_request, timeout=15):
            raise OSError("Temporary failure in name resolution")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.html"
            result = build_embedded_screenshot_html(html, "", output, opener)
            self.assertEqual("blocked", result["status"])
            self.assertFalse(output.exists())
            self.assertIn("example.test/photo.png", result["failed_urls"][0])

    def test_unresolvable_relative_asset_blocks(self):
        html = b'<html><body><img src="../images/car.webp"></body></html>'

        def opener(_request, timeout=15):
            raise AssertionError("unresolvable URL must not be fetched")

        with tempfile.TemporaryDirectory() as directory:
            result = build_embedded_screenshot_html(html, "", Path(directory) / "candidate.html", opener)
        self.assertEqual("blocked", result["status"])
        self.assertIn("relative image URL", result["images"][0]["error"])

    def test_quality_gate_rejects_browser_pass_without_image_integrity(self):
        checks = {
            "rendered_sections_visible_desktop_and_mobile",
            "hero_spans_viewport_desktop_and_mobile",
            "hero_media_covers_hero_desktop_and_mobile",
            "hero_image_loads_desktop_and_mobile",
            "image_tile_overlays_do_not_hide_photos",
            "visible_content_images_load_in_browser",
            "cta_arrows_absent_desktop_and_mobile",
            "cta_visible_first_screen_desktop_and_mobile",
            "desktop_navigation_has_single_visible_menu",
            "header_navigation_link_limit",
            "mobile_navigation_hidden_until_opened",
            "mobile_navigation_is_only_visible_menu_when_open",
            "mobile_menu_clicks_work",
            "mobile_menu_control_visible",
            "mobile_menu_focus_indicator_visible",
            "mobile_menu_keyboard_works",
            "mobile_has_no_horizontal_overflow",
            "critical_content_within_viewport_desktop_and_mobile",
            "contact_email_ctas_grouped",
            "contact_channel_ctas_aligned",
            "contact_ctas_readable_desktop_and_mobile",
            "primary_ctas_readable_desktop_and_mobile",
            "image_card_labels_readable_desktop_and_mobile",
            "hero_ctas_readable_desktop_and_mobile",
            "fonts_load_in_browser",
            "images_load_in_browser",
            "template_layout_signature_matches",
        }
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "debug").mkdir()
            report = {"status": "pass", "checks": {name: True for name in checks}, "image_gate": {"status": "blocked"}, "screenshots_visual_qa_eligible": False}
            (run / "debug" / "browser_qa.json").write_text(json.dumps(report), encoding="utf-8")
            status, _checks, _report = _browser_qa_result(run)
        self.assertEqual("blocked", status)


if __name__ == "__main__":
    unittest.main()
