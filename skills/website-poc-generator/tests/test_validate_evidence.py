from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_evidence import Audit  # noqa: E402


NOW = "2026-11-22T15:00:00-05:00"
WEIGHTS = {
    "first_screen_impact": 20,
    "business_specificity": 20,
    "typography_hierarchy": 15,
    "image_composition": 15,
    "section_rhythm_spacing": 15,
    "mobile_experience": 10,
    "conversion_clarity": 5,
}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def png_bytes(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00\x28\x60\x80\xff" * width
    pixels = zlib.compress(row * height, level=9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def make_package(root: Path) -> None:
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    base = {"schema_version": "1.0", "run_id": "fixture-run", "created_at": NOW}
    candidate_ids = []
    deliverables = {}
    passing_slots = []
    attempts = []
    assignments = []

    for slot, slug, template in ((1, "forty", "Forty"), (2, "landed", "Landed"), (3, "story", "Story")):
        candidate_id = f"{slug}-attempt-1"
        candidate_ids.append(candidate_id)
        html_path = root / f"candidate-{slug}.html"
        html_path.write_text(
            f'<!doctype html><html lang="en"><head><title>{slug}</title>'
            '<meta name="viewport" content="width=device-width">'
            '<style>:focus-visible { outline: 2px solid; }</style></head><body>'
            '<header><button type="button" class="menu-toggle" aria-controls="mobile-nav" '
            'aria-expanded="false" aria-label="Open navigation">'
            '<span aria-hidden="true"></span><span aria-hidden="true"></span>'
            '<span aria-hidden="true"></span></button><nav id="mobile-nav" hidden></nav></header>'
            '<main><h1>Fixture</h1></main></body></html>',
            encoding="utf-8",
        )
        raw = html_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        relative_html = html_path.relative_to(root).as_posix()
        deliverables[f"candidate-{slug}.html"] = {
            "path": relative_html,
            "bytes": len(raw),
            "sha256": digest,
            "qa_html_sha256": digest,
            "package_status": "PASS",
            "candidate_id": candidate_id,
        }

        folder = evidence / candidate_id
        folder.mkdir()
        screenshots = []
        for viewport, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
            screenshot = folder / f"{viewport}.png"
            screenshot_bytes = png_bytes(width, height)
            screenshot.write_bytes(screenshot_bytes)
            screenshots.append({
                "viewport": viewport,
                "width": width,
                "height": height,
                "path": screenshot.relative_to(root).as_posix(),
                "html_sha256": digest,
                "capture_method": "browser_screenshot",
                "assistant_inspected": True,
                "image_sha256": hashlib.sha256(screenshot_bytes).hexdigest(),
            })

        def record(filename: str, body: dict) -> None:
            write_json(folder / filename, {**base, "candidate_id": candidate_id, **body})

        record("candidate-inputs.json", {
            "record_type": "candidate_inputs", "slot": slot, "template": template,
            "template_signature_id": template.lower(), "palette": {},
            "source_facts_path": "evidence/source-facts.json",
            "generation_context_path": "evidence/generation-context.json",
            "selected_source_assets": [], "selected_fallback_assets": [],
            "contact_and_form_requirements": {"source_contact_form_status": "ABSENT"}, "required_sections": [],
            "output_html_path": relative_html, "input_sha256": "a" * 64,
        })
        for filename, tool in (("static-qa.json", "static"), ("browser-qa.json", "browser")):
            qa = {
                "record_type": "qa_result", "html_path": relative_html,
                "html_sha256": digest, "status": "PASS", "tool": tool,
                "checks": ([
                    {"id": "ids_unique", "status": "PASS", "blocking": True, "summary": "IDs are unique.", "evidence_paths": []},
                    {"id": "fragment_links_resolve", "status": "PASS", "blocking": True, "summary": "Fragments resolve.", "evidence_paths": []},
                    {"id": "contact_form_matches_source", "status": "PASS", "blocking": True, "summary": "No form was sourced or generated.", "evidence_paths": []},
                    {"id": "contact_form_send_cta_present", "status": "NOT_REQUIRED", "blocking": False, "summary": "No source form fields were reproduced.", "evidence_paths": []},
                    {"id": "no_file_upload_controls", "status": "PASS", "blocking": True, "summary": "No upload controls are present.", "evidence_paths": []},
                    {"id": "accessible_mobile_hamburger", "status": "PASS", "blocking": True, "summary": "Three accessible menu bars are present.", "evidence_paths": []},
                ] if filename == "static-qa.json" else []),
                "blocking_failures": [], "advisories": [],
            }
            if filename == "browser-qa.json":
                qa["viewports"] = {
                    "desktop": {"width": 1440, "height": 900},
                    "mobile": {"width": 390, "height": 844},
                }
            record(filename, qa)
        record("repairs.json", {
            "record_type": "repairs", "repairs": [], "html_sha256_before": digest,
            "html_sha256_after": digest, "repair_attempts": 0,
            "remaining_failures": [], "status": "PASS",
        })
        record("image-review.json", {
            "record_type": "image_review", "html_sha256": digest,
            "status": "PASS", "images": [{
                "url": "https://example.test/hero.jpg", "relevant": True,
                "crop_ok": True, "alt_accurate": True, "observed_subject": "Deck",
                "source_width": 2880, "source_height": 1800,
                "requested_width": 2880, "rendered_css_width": 1440,
                "resolution_status": "PASS",
                "resolution_finding": "Source width supports desktop hero at 2x density.",
            }], "missing_image_urls": [], "issues": [],
        })
        scorecard = {
            "is_advisory": True,
            "not_scored": False,
            "weighted_total": 100,
            "scores": {
                key: {"score": 5, "weight": weight, "finding": "Meets criterion."}
                for key, weight in WEIGHTS.items()
            },
        }
        record("visual-review.json", {
            "record_type": "visual_review", "html_sha256": digest,
            "status": "PASS", "checks": {
                key: {"passed": True, "finding": "Reviewed."}
                for key in ("first_screen_hierarchy", "section_rhythm", "typography", "business_specificity", "footer")
            },
            "blocking_defects": [], "screenshots": screenshots,
            "design_scorecard": scorecard,
        })
        record("final-status.json", {
            "record_type": "final_status", "html_path": relative_html,
            "html_bytes": len(raw), "html_sha256": digest,
            "final_status": "PASS", "finalized_at": NOW,
            "static_qa_status": "PASS", "browser_qa_status": "PASS",
            "repair_status": "PASS", "image_review_status": "PASS",
            "visual_review_status": "PASS", "package_checks": [],
            "blocking_failures": [],
        })
        assignments.append({
            "candidate_id": candidate_id, "slot": slot, "template": template,
            "signature_id": template.lower(),
        })
        passing_slots.append({
            "slot": slot, "candidate_id": candidate_id,
            "html_path": relative_html, "html_sha256": digest,
            "final_status": "PASS", "automated_qualified": True,
            "evidence_path": f"evidence/{candidate_id}/final-status.json",
        })
        attempts.append({
            "attempt_number": slot, "batch_number": 1, "batch_attempt_number": slot,
            "candidate_id": candidate_id, "candidate_path": relative_html,
            "slot": slot, "template": template, "template_signature_id": template.lower(),
            "status": "PASS", "qualifies_as_pass": True, "failed_check_ids": [],
            "failure_summary": "", "repair_status": "PASS", "retest_status": "PASS",
            "html_sha256": digest, "evidence_paths": [], "retention": "retained",
        })

    write_json(evidence / "source-facts.json", {
        **base, "record_type": "source_facts", "source_url": "https://example.test",
        "pages_reviewed": [], "facts": [],
    })
    write_json(evidence / "generation-context.json", {
        **base, "record_type": "generation_context", "business_name": "Example",
        "source_url": "https://example.test", "source_facts_path": "evidence/source-facts.json",
        "generation_instructions": "Test fixture", "template_assignments": assignments,
        "palette_tokens": {}, "approved_image_urls": [], "source_contact_schema": [],
        "constraints": [], "context_sha256": "b" * 64,
    })
    (evidence / "index.md").write_text("Test fixture evidence index.", encoding="utf-8")
    write_json(evidence / "candidate-ledger.json", {
        **base, "record_type": "candidate_ledger", "candidate_id": None,
        "execution_mode": "skill", "target_passing_slots": 3,
        "initial_attempt_limit": 3, "continuation_attempt_limit": 3,
        "max_total_attempts": 6, "attempts_used": 3, "batch_attempts": [3, 0],
        "passing_count": 3, "passing_slots": passing_slots, "missing_slots": [],
        "continuation": {"eligible": False, "reason": "All slots passed."},
        "terminal_status": "PASS", "attempts": attempts,
    })
    write_json(evidence / "renderer-preflight.json", {
        **base, "record_type": "renderer_preflight",
        "fixture_sha256": hashlib.sha256(b"probe fixture").hexdigest(),
        "tool": "test fixture", "transfer_method": "fixture test harness",
        "preview_available": True, "exact_byte_binding_evidence": "fixture test harness",
        "exact_saved_bytes_rendered": "PASS",
        "pixels_inspectable_by_assistant": "PASS", "screenshot_saved": "PASS",
        "viewports": {
            "desktop": {"width": 1440, "height": 900},
            "mobile": {"width": 390, "height": 844},
        },
        "images": {}, "measurements": {}, "interactions": {},
        "runtime_errors": [], "evidence_paths": [], "failure_summary": "",
    })
    write_json(evidence / "run.json", {
        **base, "record_type": "run", "execution_mode": "skill",
        "runtime_profile": "full_parity", "output_root": ".",
        "source_url": "https://example.test", "candidate_ids": candidate_ids,
        "deliverables": deliverables, "evidence_index": "evidence/index.md",
        "tool_availability": {}, "failure_summary": "", "status": "PASS",
    })


class ValidateEvidenceTests(unittest.TestCase):
    def run_audit(self, root: Path) -> Audit:
        audit = Audit(root)
        audit.validate()
        return audit

    def test_complete_three_slot_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            self.assertEqual([], self.run_audit(root).errors)

    def test_delivered_digest_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            run_path = root / "evidence" / "run.json"
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["deliverables"]["candidate-forty.html"]["sha256"] = "0" * 64
            write_json(run_path, run)
            self.assertTrue(any("digest mismatch" in e for e in self.run_audit(root).errors))

    def test_scorecard_total_must_match_component_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            review_path = root / "evidence" / "forty-attempt-1" / "visual-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["design_scorecard"]["weighted_total"] = 99
            write_json(review_path, review)
            self.assertTrue(any("weighted_total does not match" in e for e in self.run_audit(root).errors))

    def test_visual_pass_requires_inspected_hash_bound_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            review_path = root / "evidence" / "forty-attempt-1" / "visual-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["screenshots"][0]["assistant_inspected"] = False
            write_json(review_path, review)
            errors = self.run_audit(root).errors
            self.assertTrue(any("visually inspected by the assistant" in e for e in errors), errors)

    def test_unscored_scorecard_allows_null_scores_without_zero_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit = Audit(Path(directory))
            scorecard = {
                "is_advisory": True,
                "not_scored": True,
                "weighted_total": None,
                "scores": {
                    key: {"score": None, "weight": weight, "finding": "UNVERIFIED; no rendered review."}
                    for key, weight in WEIGHTS.items()
                },
            }
            audit.validate_design_scorecard(Path("visual-review.json"), scorecard, "UNVERIFIED")
            self.assertEqual([], audit.errors)

    def test_documented_unidentifiable_form_control_does_not_fail_form_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "candidate.html"
            html_path.write_text(
                '<main><section id="contact"><form><label>Email<input type="email"></label>'
                '<p>Preview only; nothing is sent or stored.</p>'
                '<button type="button">Send inquiry</button></form></section></main>',
                encoding="utf-8",
            )
            inputs_path = root / "candidate-inputs.json"
            inputs = {"contact_and_form_requirements": {
                "source_contact_form_status": "PRESENT",
                "unidentifiable_controls": [{
                    "source_position": "Contact form, control 3",
                    "evidence": "evidence/source-capture.json#contact-form-control-3",
                    "reason": "OMITTED_UNIDENTIFIABLE",
                }],
                "identifiable_fields_preserved": True,
                "exact_full_form_parity": False,
            }}
            qa = {"checks": [
                {"id": "contact_form_matches_source", "status": "PASS"},
                {"id": "contact_form_send_cta_present", "status": "PASS"},
                {"id": "no_file_upload_controls", "status": "PASS"},
                {"id": "accessible_mobile_hamburger", "status": "FAIL"},
            ]}
            audit = Audit(root)
            audit.validate_contact_form_alignment(Path("static-qa.json"), qa, inputs_path, inputs, html_path)
            self.assertEqual([], audit.errors)

    def test_unidentifiable_form_control_requires_position_evidence_and_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "candidate.html"
            html_path.write_text(
                '<main><section id="contact"><form><button type="button">Send</button></form></section></main>',
                encoding="utf-8",
            )
            inputs = {"contact_and_form_requirements": {
                "source_contact_form_status": "PRESENT",
                "unidentifiable_controls": [{"reason": "unknown"}],
            }}
            qa = {"checks": [
                {"id": "contact_form_matches_source", "status": "FAIL"},
                {"id": "contact_form_send_cta_present", "status": "PASS"},
                {"id": "no_file_upload_controls", "status": "PASS"},
                {"id": "accessible_mobile_hamburger", "status": "FAIL"},
            ]}
            audit = Audit(root)
            audit.validate_contact_form_alignment(Path("static-qa.json"), qa, Path("candidate-inputs.json"), inputs, html_path)
            self.assertTrue(any("source_position" in error for error in audit.errors), audit.errors)

    def test_unresolved_source_field_cannot_pass_without_omission_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "candidate.html"
            html_path.write_text(
                '<main><section id="contact"><form><label>Email<input type="email"></label>'
                '<p>Nothing is sent or stored.</p><button type="button">Send inquiry</button></form></section></main>',
                encoding="utf-8",
            )
            inputs = {"contact_and_form_requirements": {
                "source_contact_form_status": "PRESENT",
                "unresolved_field": {"order": 7, "reproduced": False},
            }}
            qa = {"checks": [
                {"id": "contact_form_matches_source", "status": "PASS"},
                {"id": "contact_form_send_cta_present", "status": "PASS"},
                {"id": "no_file_upload_controls", "status": "PASS"},
                {"id": "accessible_mobile_hamburger", "status": "FAIL"},
            ]}
            audit = Audit(root)
            audit.validate_contact_form_alignment(Path("static-qa.json"), qa, Path("candidate-inputs.json"), inputs, html_path)
            self.assertTrue(any("OMITTED_UNIDENTIFIABLE" in error for error in audit.errors), audit.errors)

    def test_slot_template_mapping_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            inputs_path = root / "evidence" / "forty-attempt-1" / "candidate-inputs.json"
            inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
            inputs["template"] = "Landed"
            write_json(inputs_path, inputs)
            self.assertTrue(any("slot 1 must use Forty" in e for e in self.run_audit(root).errors))

    def test_static_qa_pass_requires_anchor_and_unique_id_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            qa_path = root / "evidence" / "forty-attempt-1" / "static-qa.json"
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
            qa["checks"] = [{
                "id": "ids_unique", "status": "PASS", "blocking": True,
                "summary": "IDs are unique.", "evidence_paths": [],
            }]
            write_json(qa_path, qa)
            errors = self.run_audit(root).errors
            self.assertTrue(any("omits required checks:" in e and "fragment_links_resolve" in e for e in errors), errors)

    def test_source_without_form_rejects_contact_form_markup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            html_path = root / "candidate-forty.html"
            html = html_path.read_text(encoding="utf-8")
            html_path.write_text(
                html.replace("</main>", '<section id="contact"><form><label for="email">Email</label>'
                             '<input id="email" type="email"></form></section></main>'),
                encoding="utf-8",
            )
            errors = self.run_audit(root).errors
            self.assertTrue(any("contact_form_matches_source must be FAIL" in error for error in errors), errors)

    def test_source_form_requires_semantic_form_and_visible_noop_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "candidate.html"
            html_path.write_text(
                '<!doctype html><html><body><section id="contact"><form>'
                '<label for="email">Email</label><input id="email" type="email">'
                '<button type="button">Send inquiry</button>'
                '<p>Preview only; nothing is sent or stored.</p></form></section></body></html>',
                encoding="utf-8",
            )
            qa_path = root / "static-qa.json"
            inputs_path = root / "candidate-inputs.json"
            qa = {
                "checks": [
                    {"id": "contact_form_matches_source", "status": "PASS"},
                    {"id": "contact_form_send_cta_present", "status": "PASS"},
                    {"id": "no_file_upload_controls", "status": "PASS"},
                    {"id": "accessible_mobile_hamburger", "status": "FAIL"},
                ]
            }
            inputs = {"contact_and_form_requirements": {"source_contact_form_status": "PRESENT"}}
            audit = Audit(root)
            audit.validate_contact_form_alignment(qa_path, qa, inputs_path, inputs, html_path)
            self.assertEqual([], audit.errors)

    def test_file_upload_control_is_rejected_even_when_source_has_a_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "candidate.html"
            html_path.write_text(
                '<!doctype html><html><body><section id="contact"><form>'
                '<label>Email<input type="email"></label><input type="file">'
                '<button type="button">Send inquiry</button>'
                '<p>Nothing is sent or stored.</p></form></section></body></html>',
                encoding="utf-8",
            )
            qa = {"checks": [
                {"id": "contact_form_matches_source", "status": "PASS"},
                {"id": "contact_form_send_cta_present", "status": "PASS"},
                {"id": "no_file_upload_controls", "status": "PASS"},
                {"id": "accessible_mobile_hamburger", "status": "FAIL"},
            ]}
            inputs = {"contact_and_form_requirements": {"source_contact_form_status": "PRESENT"}}
            audit = Audit(root)
            audit.validate_contact_form_alignment(
                Path("static-qa.json"), qa, Path("candidate-inputs.json"), inputs, html_path
            )
            self.assertTrue(any("file upload controls are prohibited" in e for e in audit.errors), audit.errors)
            self.assertTrue(any("no_file_upload_controls must be FAIL" in e for e in audit.errors), audit.errors)

    def test_ledger_batch_attempts_must_be_two_integer_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            ledger_path = root / "evidence" / "candidate-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["batch_attempts"] = {"initial": 3, "retry": 0}
            write_json(ledger_path, ledger)
            self.assertTrue(any("batch_attempts must be [initial_count, retry_count]" in e for e in self.run_audit(root).errors))

    def test_skill_pass_rejects_undersized_hero_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_package(root)
            review_path = root / "evidence" / "forty-attempt-1" / "image-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["images"][0]["source_width"] = 615
            review["images"][0]["requested_width"] = 615
            write_json(review_path, review)
            self.assertTrue(any("is upscaled (615px source for 1440px" in e for e in self.run_audit(root).errors))

    def test_shared_schema_still_accepts_action_package_contract(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        schema_path = Path(__file__).resolve().parents[1] / "evidence.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        digest = "a" * 64
        run = {
            "schema_version": "1.0", "record_type": "run", "run_id": "workflow-fixture",
            "execution_mode": "workflow", "runtime_profile": "workflow",
            "created_at": NOW, "output_root": "results/run", "source_url": "https://example.test",
            "candidate_ids": ["forty", "landed", "story"],
            "deliverables": {
                f"candidate-{slug}.html": {
                    "path": f"candidate-{slug}.html", "bytes": 1, "sha256": digest,
                    "qa_html_sha256": digest, "package_status": "PASS",
                    "candidate_id": f"{slug}-attempt-1",
                }
                for slug in ("forty", "landed", "story")
            },
            "evidence_index": "evidence/run.json", "tool_availability": {},
            "failure_summary": "", "status": "PASS",
        }
        ledger = {
            "schema_version": "1.0", "record_type": "candidate_ledger",
            "run_id": "workflow-fixture", "created_at": NOW, "candidate_id": None,
            "execution_mode": "workflow", "target_passing_slots": 3,
            "initial_attempt_limit": 12, "continuation_attempt_limit": 12,
            "max_total_attempts": 24, "attempts_used": 24, "batch_attempts": [12, 12],
            "passing_count": 3, "passing_slots": [], "missing_slots": [],
            "continuation": {"eligible": False, "reason": "Complete."},
            "terminal_status": "PASS", "attempts": [],
        }
        for name, record in (("run", run), ("candidate_ledger", ledger)):
            errors = list(Draft202012Validator(schema["$defs"][name]).iter_errors(record))
            self.assertEqual([], errors, f"Action-shaped {name} record rejected: {errors}")


if __name__ == "__main__":
    unittest.main()
