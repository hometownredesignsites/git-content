from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

AUTOMATION = Path(__file__).resolve().parents[1]
REPO = AUTOMATION.parent
sys.path.insert(0, str(AUTOMATION))
from run_duckai import (
    MAX_INITIAL_PROMPT_CHARS,
    _verified_source_assets,
    assigned_design_reference,
    build_initial_prompt,
    build_quality_prompt,
    validate_source_assessment,
)
from scripts.summarize_candidate_failure import summarize
from scripts.site_quality import assess_website
from scripts.template_scaffolds import scaffold_context
from scripts.browser_qa import _selected_template_profile


class PromptAndWorkflowTests(unittest.TestCase):
    def test_browser_qa_requires_selected_template_audit_and_uses_its_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            debug = run_dir / "debug"
            debug.mkdir()
            (debug / "source_assessment.json").write_text(
                '{"design_reference": null}', encoding="utf-8"
            )
            (debug / "design_reference.json").write_text(
                '{"status":"selected","design_reference":{"slot":2,"name":"Landed","template_url":"https://html5up.net/landed"}}',
                encoding="utf-8",
            )

            profile, evidence = _selected_template_profile(run_dir)

            self.assertEqual(profile, "landed")
            self.assertEqual(evidence["status"], "pending")
            self.assertEqual(evidence["signature_id"], "landed-alternating-spotlights")

    def test_browser_qa_fails_closed_when_selected_template_audit_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            profile, evidence = _selected_template_profile(Path(folder))

        self.assertIsNone(profile)
        self.assertEqual(evidence["status"], "fail")
        self.assertFalse(evidence["pass"])

    def test_candidate_indices_cycle_the_three_html5up_templates(self):
        references = [assigned_design_reference(index) for index in range(1, 4)]
        self.assertEqual([item["name"] for item in references], ["Forty", "Landed", "Story"])
        for item in references:
            prompt = build_initial_prompt("Redesign this site.", "Use source-led visuals.", design_reference=item)
            self.assertIn(item["name"], prompt)
            self.assertIn(item["template_url"], prompt)
            self.assertIn("REQUIRED LAYOUT SIGNATURE", prompt)

    def test_story_scaffold_uses_paper_backed_hero_direction(self):
        context = scaffold_context(assigned_design_reference(3))
        self.assertIn("paper-backed copy beside the photo", context)
        self.assertIn("on mobile stack a short photo above the text and CTA", context)
        self.assertIn("solid paper panel beside the photo", assigned_design_reference(3)["fit_summary"])
        self.assertIn("dark ink over bright flooring", assigned_design_reference(3)["fit_summary"])
        self.assertIn("keep the CTA on the first screen", assigned_design_reference(3)["fit_summary"])

    def test_quality_prompt_uses_the_same_verified_asset_allowlist_as_generation(self):
        prompt = build_quality_prompt(
            "Redesign the flooring company website.",
            "VERIFIED_SOURCE_ASSET_URLS:\n- https://example.com/verified-photo.jpg\n\n"
            "VERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/shortlisted-photo.jpg\n\n"
            "VERIFIED_CATEGORY_FALLBACK_IMAGE_URLS:\n- https://images.example.com/floor.jpg",
        )

        self.assertIn("VERIFIED_SOURCE_ASSET_URLS:\n- https://example.com/verified-photo.jpg", prompt)
        self.assertIn("VERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/shortlisted-photo.jpg", prompt)
        self.assertIn("VERIFIED_CATEGORY_FALLBACK_IMAGE_URLS:\n- https://images.example.com/floor.jpg", prompt)

    def test_quality_prompt_receives_verified_contact_fields(self):
        prompt = build_quality_prompt(
            "Redesign this site.",
            "CONTACT FORM (preserve exact fields and supplied attributes):\n"
            "- Email (type=email; required=true) (source: https://example.com/contact/)\n\n"
            "VERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/photo.jpg",
        )
        self.assertIn("A contact form is required", prompt)
        self.assertIn("VERIFIED INQUIRY FIELD DEFINITIONS:", prompt)
        self.assertIn("Email (type=email; required=true)", prompt)

        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp)
            (candidate / "files").mkdir()
            (candidate / "files" / "index.html").write_text(
                "<!doctype html><html><head><link href=\"styles.css\"></head>"
                "<body><main><h1>Flooring</h1><form><label>Email</label></form></main>"
                "<footer>Contact us for flooring projects and details.</footer></body></html>",
                encoding="utf-8",
            )
            (candidate / "files" / "styles.css").write_text("body{color:#111}", encoding="utf-8")
            report = assess_website(prompt, candidate)
            self.assertIs(report["checks"]["requested_form_present"], True)
            (candidate / "files" / "index.html").write_text(
                "<!doctype html><html><head><link href=\"styles.css\"></head>"
                "<body><main><h1>Flooring</h1></main>"
                "<footer>Contact us for flooring projects and details.</footer></body></html>",
                encoding="utf-8",
            )
            report = assess_website(prompt, candidate)
            self.assertIs(report["checks"]["requested_form_present"], False)

    def test_quality_prompt_does_not_require_a_form_without_verified_fields(self):
        prompt = build_quality_prompt(
            "If verified inquiry fields exist, include them. Otherwise, omit the inquiry interface.",
            "VERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/photo.jpg",
        )
        self.assertNotIn("CONTACT FORM", prompt)
        self.assertNotIn("contact form", prompt.lower())
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp)
            (candidate / "files").mkdir()
            (candidate / "files" / "index.html").write_text(
                "<!doctype html><html><head><link href=\"styles.css\"></head>"
                "<body><main><h1>Flooring</h1></main><footer>Contact us for flooring projects and details.</footer></body></html>",
                encoding="utf-8",
            )
            (candidate / "files" / "styles.css").write_text("body{color:#111}", encoding="utf-8")
            report = assess_website(prompt, candidate)
            self.assertNotIn("requested_form_present", report["checks"])

    def test_source_assessment_accepts_a_cited_natural_language_access_status(self):
        assessment = {
            "access_status": (
                "Homepage accessible. Commercial Services page surfaced in search. "
                "About and Contact pages were not verified."
            ),
            "pages_reviewed": [{"url": "https://codyflooring.wordpress.com/"}],
            "sources": ["https://codyflooring.wordpress.com/"],
        }
        validate_source_assessment(assessment, "https://codyflooring.wordpress.com/")

    def test_source_assessment_rejects_an_explicit_access_failure(self):
        assessment = {
            "access_status": "Could not access the homepage.",
            "pages_reviewed": [{"url": "https://example.com/"}],
            "sources": ["https://example.com/"],
        }
        with self.assertRaisesRegex(RuntimeError, "could not confirm it accessed"):
            validate_source_assessment(assessment, "https://example.com/")

    def test_source_assessment_still_requires_a_page_on_the_requested_domain(self):
        assessment = {
            "access_status": "Homepage accessible.",
            "pages_reviewed": [{"url": "https://other.example/"}],
            "sources": ["https://other.example/"],
        }
        with self.assertRaisesRegex(RuntimeError, "requested source domain"):
            validate_source_assessment(assessment, "https://example.com/")

    def test_generation_prompt_keeps_verified_facts_but_stays_bounded(self):
        prompt = build_initial_prompt(
            "Redesign the flooring company website.",
            "Use a warm, clear visual direction. " * 500,
            "https://example.com/",
            {"name": "Landed", "url": "https://html5up.net/landed", "license_url": "https://html5up.net/license", "patterns_to_adapt": ["split image sections"]},
            "Example Floors",
            "Flooring",
            "Denver",
            "SERVICES: installation (source: https://example.com/services/)\nVERIFIED_SOURCE_IMAGE_URLS:\n- https://example.com/photo.jpg",
            "Primary CTA contrast measured 2.1:1; required 4.5:1.",
        )
        self.assertLessEqual(len(prompt), MAX_INITIAL_PROMPT_CHARS)
        self.assertIn("installation (source: https://example.com/services/)", prompt)
        self.assertIn("https://example.com/photo.jpg", prompt)
        self.assertIn("4.5:1", prompt)
        self.assertLessEqual(len(" ".join(prompt.split())), MAX_INITIAL_PROMPT_CHARS)

    def test_generation_prompt_fails_closed_above_budget(self):
        with self.assertRaisesRegex(ValueError, "Compact generation prompt"):
            build_initial_prompt("x" * 12000, "brief")

    def test_compacted_prompt_fits_with_max_brief_retry_and_template_notes(self):
        prompt = build_initial_prompt(
            (REPO / "duckai_automation" / "website_request.txt").read_text(encoding="utf-8"),
            (REPO / "duckai_automation" / "design_brief.txt").read_text(encoding="utf-8"),
            "https://example.com/",
            {"name": "Landed", "url": "https://html5up.net/landed", "license_url": "https://html5up.net/license",
             "patterns_to_adapt": ["pattern " + "x" * 500 for _ in range(5)]},
            "Example Business", "Category", "Somewhere",
            "x" * 4800,
            "y" * 1800,
        )
        self.assertLessEqual(len(prompt), MAX_INITIAL_PROMPT_CHARS)

    def test_workflow_checkpoints_each_candidate_on_private_duckai_branch(self):
        workflow = (REPO / ".github" / "workflows" / "duckai-private-queue.yml").read_text(encoding="utf-8")
        self.assertIn('CANDIDATE_ATTEMPT_LIMIT:-12', workflow)
        self.assertIn('candidate_attempt_limit <= 12', workflow)
        self.assertIn('prior_attempts not in (12, 24)', workflow)
        self.assertIn('--expected-attempts "$PRIOR_ATTEMPTS"', workflow)
        self.assertIn('PRIVATE_SOURCE_ROOT:-private-source', workflow)
        self.assertIn('path: private-source-live', workflow)
        self.assertNotIn('ten-attempt bounds', workflow)
        self.assertIn("checkpoint_candidate \"$run_dir\"", workflow)
        self.assertIn('HEAD:refs/heads/duckai', workflow)
        self.assertIn("continuation.py inherit", workflow)
        self.assertIn("continuation.py status", workflow)
        continuation = (AUTOMATION / "scripts" / "continuation.py").read_text(encoding="utf-8")
        self.assertIn("continuation_eligible", continuation)
        self.assertIn("MAX_TOTAL_ATTEMPTS = 36", continuation)
        self.assertNotIn("refs/heads/fallback", workflow)
        self.assertLess(workflow.index("Check out private Duck.ai evidence branch before generation"), workflow.index("Generate candidate sites"))

    def test_queue_only_private_checkouts_use_blob_filter_and_sparse_paths(self):
        workflow = (REPO / ".github" / "workflows" / "duckai-private-queue.yml").read_text(encoding="utf-8")
        queue_checkout_names = (
            "Check out private input records",
            "Check out legacy private input records",
            "Check out private input records for live checkpoints",
        )
        for name in queue_checkout_names:
            step = workflow.split(f"- name: {name}", 1)[1].split("\n      - name:", 1)[0]
            self.assertIn("filter: blob:none", step, name)
            self.assertIn("sparse-checkout: private_automation/queue/", step, name)
        evidence_checkout = workflow.split("- name: Check out private Duck.ai evidence branch before generation", 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("fetch-depth: 0", evidence_checkout)
        self.assertNotIn("sparse-checkout:", evidence_checkout)

    def test_source_audit_and_generation_use_separate_clean_profiles(self):
        runner = (AUTOMATION / "run_duckai.py").read_text(encoding="utf-8")
        self.assertIn("duckai-source-audit-profile-", runner)
        self.assertIn("duckai-generation-profile-", runner)
        self.assertIn('"source_audit_chat_url"', runner)
        self.assertIn('"generation_chat_url"', runner)

    def test_source_asset_urls_must_pass_image_byte_validation(self):
        assets = {
            "source_assets": [
                {"url": "https://example.com/good.jpg", "type": "photo"},
                {"url": "https://example.com/broken.jpg", "type": "photo"},
            ]
        }
        with patch("run_duckai._image_loads_ok", side_effect=lambda url: url.endswith("good.jpg")):
            self.assertEqual(_verified_source_assets(assets), [assets["source_assets"][0]])

    def test_failure_summary_uses_non_sensitive_category(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp)
            (candidate / "run_notes.json").write_text('{"failure_category":"access_gate","failure_reason":"secret detail"}', encoding="utf-8")
            self.assertEqual(summarize(candidate), "Duck.ai guest chat was gated or unavailable")


if __name__ == "__main__":
    unittest.main()
