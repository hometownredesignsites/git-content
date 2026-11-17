from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from duckai_automation.scripts.source_images import (
    _SourcePageParser,
    _srcset_urls,
    collect_source_images,
)


class ImageAssetParityTests(unittest.TestCase):
    def test_srcset_preserves_candidate_order(self):
        self.assertEqual(
            _srcset_urls("small.jpg 640w, large.jpg 1600w, medium.jpg 1024w"),
            ["small.jpg", "large.jpg", "medium.jpg"],
        )

    def test_source_parser_finds_lazy_responsive_and_metadata_images(self):
        parser = _SourcePageParser()
        parser.feed("""
            <meta property="og:image" content="/media/og-fence.jpg">
            <picture><source type="image/webp" srcset="https://static.wixstatic.com/media/fence-small.webp/v1/fill/w_640,h_400,al_c/fence.webp 640w, https://static.wixstatic.com/media/fence-large.webp/v1/fill/w_1600,h_1000,al_c/fence.webp 1600w">
              <img src="/media/placeholder.gif" data-src="/media/project.jpg" alt="">
            </picture>
            <div style="background-image:url('/media/fence-background.jpg')"></div>
            <video poster="/media/fence-poster.jpg"></video>
        """)
        found = {image["url"] for image in parser.images}
        self.assertIn("/media/og-fence.jpg", found)
        self.assertIn("/media/project.jpg", found)
        self.assertIn("https://static.wixstatic.com/media/fence-large.webp/v1/fill/w_1600,h_1000,al_c/fence.webp", found)
        self.assertIn("/media/fence-background.jpg", found)
        self.assertIn("/media/fence-poster.jpg", found)

    def test_direct_extractor_filters_logo_and_deduplicates_wix_resizes(self):
        homepage = _SourcePageParser()
        homepage.feed("""
            <a href="/work" aria-label="Our Work">Our Work</a>
            <img src="https://static.wixstatic.com/media/fence-logo.png" alt="logo">
            <img srcset="https://static.wixstatic.com/media/asset~mv2.jpg/v1/fill/w_500,h_300,al_c/photo.jpg 500w, https://static.wixstatic.com/media/asset~mv2.jpg/v1/fill/w_1000,h_600,al_c/photo.jpg 1000w" alt="">
        """)
        work = _SourcePageParser()
        work.feed('<img src="https://static.wixstatic.com/media/second~mv2.jpg/v1/fill/w_900,h_600/photo.jpg" alt="Completed fence project">')
        with (
            patch("duckai_automation.scripts.source_images._assert_public_http_url", side_effect=urlsplit),
            patch("duckai_automation.scripts.source_images._fetch_page", side_effect=[("https://example.com/", homepage), ("https://example.com/work", work)]),
            patch("duckai_automation.scripts.source_images._image_loads_ok", return_value=True),
        ):
            result = collect_source_images("https://example.com/")
        self.assertEqual(len(result["source_assets"]), 2)
        self.assertTrue(all("logo" not in asset["url"] for asset in result["source_assets"]))
        resized_asset = next(asset for asset in result["source_assets"] if "asset~mv2" in asset["url"])
        self.assertIn("w_1000", resized_asset["url"])


if __name__ == "__main__":
    unittest.main()
