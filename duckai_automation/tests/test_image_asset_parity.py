from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from duckai_automation.run_duckai import build_initial_prompt, build_quality_prompt
from duckai_automation.scripts.site_quality import (
    _PageInventory,
    _category_fallback_image_urls_from_prompt,
    _image_asset_approval,
    _required_sections,
    _source_image_urls_from_prompt,
    _urls_from_srcset,
)
from duckai_automation.scripts.source_images import (
    _SourcePageParser,
    _srcset_urls,
    collect_source_images,
)


class ImageAssetParityTests(unittest.TestCase):
    def test_initial_prompt_passes_source_photos_and_category_fallbacks(self):
        prompt = build_initial_prompt(
            "Rebuild the site",
            "Use a strong image-led hero",
            "https://source.example",
            business_name="Example Fence Co.",
            industry_category="Fence Companies",
            source_assessment={
                "source_assets": [
                    {"type": "photo", "url": "https://source.example/work.jpg", "visible_subject": "wood fence"},
                    {"type": "logo", "url": "https://source.example/logo.png"},
                ]
            },
        )
        self.assertIn("VERIFIED_SOURCE_IMAGE_URLS:\n- https://source.example/work.jpg", prompt)
        self.assertIn("CATEGORY_FALLBACK_IMAGE_URLS:", prompt)
        self.assertNotIn("- https://source.example/logo.png", prompt)

    def test_initial_prompt_accepts_directly_extracted_source_photos(self):
        prompt = build_initial_prompt(
            "Rebuild this fence site",
            "Keep the design image-led",
            "https://source.example",
            industry_category="Fence Companies",
            source_image_records=[{
                "type": "photo",
                "url": "https://cdn.example/source-fence.webp",
                "visible_subject": "unknown",
                "where_it_appears": "https://source.example/work",
                "discovery_method": "data-srcset",
            }],
        )
        self.assertIn("https://cdn.example/source-fence.webp", prompt)
        self.assertIn('"visible_subject": "unknown"', prompt)

    def test_prompt_markers_expose_source_and_category_images_to_qa(self):
        prompt = """VERIFIED_SOURCE_IMAGE_URLS:
- https://source.example/images/fence.jpg

CATEGORY_FALLBACK_IMAGE_URLS:
- https://images.example/fallback.jpg

Rest of prompt"""
        self.assertEqual(
            _source_image_urls_from_prompt(prompt),
            ["https://source.example/images/fence.jpg"],
        )
        self.assertEqual(
            _category_fallback_image_urls_from_prompt(prompt),
            ["https://images.example/fallback.jpg"],
        )

    def test_quality_prompt_carries_allowlists_without_generation_contract(self):
        generation_prompt = """VERIFIED_SOURCE_IMAGE_URLS:
- https://source.example/fence.jpg

CATEGORY_FALLBACK_IMAGE_URLS:
- https://images.example/fence.jpg

Long generation-only design contract"""
        quality_prompt = build_quality_prompt("Rebuild the fence contractor site.", generation_prompt)
        self.assertEqual(
            _source_image_urls_from_prompt(quality_prompt),
            ["https://source.example/fence.jpg"],
        )
        self.assertEqual(
            _category_fallback_image_urls_from_prompt(quality_prompt),
            ["https://images.example/fence.jpg"],
        )
        self.assertNotIn("Long generation-only", quality_prompt)

    def test_image_sourcing_mentions_do_not_require_a_gallery_section(self):
        request = "Use distinct photos from the existing site and category-matched imagery where needed."
        self.assertNotIn("gallery", _required_sections(request))
        self.assertIn("gallery", _required_sections("Include a portfolio/gallery section of completed work."))

    def test_all_images_must_be_approved_and_hero_must_use_approved_photo(self):
        approved = [
            "https://source.example/photos/work.jpg",
            "https://images.example/fence.jpg",
        ]
        all_ok, hero_ok = _image_asset_approval(
            ["https://source.example/photos/work.jpg", "https://images.example/fence.jpg"],
            ["https://images.example/fence.jpg"],
            approved,
        )
        self.assertTrue(all_ok)
        self.assertTrue(hero_ok)

        all_ok, hero_ok = _image_asset_approval(
            ["https://unrelated.example/photo.jpg"],
            ["https://unrelated.example/photo.jpg"],
            approved,
        )
        self.assertFalse(all_ok)
        self.assertFalse(hero_ok)

    def test_inventory_finds_lazy_srcsets_and_inline_backgrounds(self):
        parser = _PageInventory()
        parser.feed("""
            <section class="hero">
              <picture><source type="image/webp" data-lazy-srcset="https://cdn.example/hero-small.webp 640w, https://cdn.example/hero-large.webp 1600w"></picture>
              <img alt="Fence work" data-lazy-src="https://source.example/work.jpg">
            </section>
            <div style="background-image:url('https://source.example/garden.jpg')"></div>
        """)
        self.assertIn("https://cdn.example/hero-large.webp", parser.all_image_urls)
        self.assertIn("https://source.example/work.jpg", parser.all_image_urls)
        self.assertIn("https://source.example/garden.jpg", parser.all_image_urls)
        self.assertIn("https://cdn.example/hero-large.webp", parser.hero_image_urls)
        self.assertTrue(parser.hero_image_present)

    def test_srcset_prefers_largest_image_first_but_keeps_all_unique_urls(self):
        self.assertEqual(
            _urls_from_srcset("small.jpg 640w, large.jpg 1600w, medium.jpg 1024w"),
            ["large.jpg", "medium.jpg", "small.jpg"],
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
            patch("duckai_automation.scripts.source_images._assert_public_http_url", side_effect=lambda url: urlsplit(url)),
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
