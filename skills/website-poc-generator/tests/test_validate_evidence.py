from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
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
            '<style>:focus-visible { outline: 2px solid; }</style></head>'
            '<body><main><h1>Fixture</h1></main></body></html>',
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
            screenshot.write_bytes(b"test-fixture-image")
            screenshots.append({
                "viewport": viewport,
                "width": width,
                "height": height,
                "path": screenshot.relative_to(root).as_posix(),
                "html_sha256": digest,
            })

        def record(filename: str, body: dict) -> None:
            write_json(folder / filename, {**base, "candidate_id": candidate_id, **body})

        record("candidate-inputs.json", {
            "record_type": "candidate_inputs", "slot": slot, "template": template,
            "template_signature_id": template.lower(), "palette": {},
            "source_facts_path": "evidence/source-facts.json",
            "generation_context_path": "evidence/generation-context.json",
            "selected_source_assets": [], "selected_fallback_assets": [],
            "contact_and_form_requirements": {}, "required_sections": [],
            "output_html_path": relative_html, "input_sha256": "a" * 64,
        })
        for filename, tool in (("static-qa.json", "static"), ("browser-qa.json", "browser")):
            qa = {
                "record_type": "qa_result", "html_path": relative_html,
                "html_sha256": digest, "status": "PASS", "tool": tool,
                "checks": ([
                    {"id": "ids_unique", "status": "PASS", "blocking": True},
                    {"id": "fragment_links_resolve", "status": "PASS", "blocking": True},
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
            qa["checks"] = [{"id": "ids_unique", "status": "PASS", "blocking": True}]
            write_json(qa_path, qa)
            self.assertTrue(any("omits required checks: fragment_links_resolve" in e for e in self.run_audit(root).errors))

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
