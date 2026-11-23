#!/usr/bin/env python3
"""Validate a Website POC evidence package and its cross-record invariants.

Usage: python validate_evidence.py <website-poc-output-root>

The JSON Schema checks record shape when `jsonschema` is installed. This script
always checks the file, digest, candidate, QA, review, and ledger relationships
that JSON Schema cannot express across separate files.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


RECORD_TYPES = {
    "run", "source_facts", "generation_context", "candidate_inputs",
    "qa_result", "repairs", "image_review", "visual_review",
    "final_status", "candidate_ledger",
}
REQUIRED_CANDIDATE_FILES = {
    "candidate-inputs.json": "candidate_inputs",
    "static-qa.json": "qa_result",
    "browser-qa.json": "qa_result",
    "repairs.json": "repairs",
    "image-review.json": "image_review",
    "visual-review.json": "visual_review",
    "final-status.json": "final_status",
}
SCORE_WEIGHTS = {
    "first_screen_impact": 20,
    "business_specificity": 20,
    "typography_hierarchy": 15,
    "image_composition": 15,
    "section_rhythm_spacing": 15,
    "mobile_experience": 10,
    "conversion_clarity": 5,
}
SCHEMA_DEFINITIONS = {
    "run": "run",
    "source_facts": "source_facts",
    "generation_context": "generation_context",
    "candidate_inputs": "candidate_inputs",
    "qa_result": "qa",
    "repairs": "repairs",
    "image_review": "image_review",
    "visual_review": "visual_review",
    "final_status": "final_status",
    "candidate_ledger": "candidate_ledger",
}
PASS_STATES = {"PASS"}


class Audit:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.records: list[tuple[Path, dict[str, Any]]] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def load_records(self) -> None:
        evidence = self.root / "evidence"
        if not evidence.is_dir():
            self.error("Missing evidence/ directory")
            return
        for path in sorted(evidence.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self.error(f"{self.rel(path)}: invalid or unreadable JSON: {exc}")
                continue
            if isinstance(value, dict) and value.get("record_type") in RECORD_TYPES:
                self.records.append((path, value))

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    def resolve_record_path(self, value: Any, label: str, must_exist: bool = True) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            self.error(f"{label}: expected a non-empty relative path")
            return None
        p = Path(value)
        if p.is_absolute():
            self.error(f"{label}: path must be relative to output root: {value}")
            return None
        target = (self.root / p).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            self.error(f"{label}: path escapes output root: {value}")
            return None
        if must_exist and not target.is_file():
            self.error(f"{label}: referenced file does not exist: {value}")
            return None
        return target

    def check_json_schema(self) -> None:
        schema_path = Path(__file__).with_name("evidence.schema.json")
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.error(f"Cannot load evidence schema: {exc}")
            return
        try:
            from jsonschema import Draft202012Validator  # type: ignore[import-not-found]
        except ImportError:
            self.warn("jsonschema is unavailable; per-record JSON Schema checks are UNVERIFIED")
            return
        # Validate each record against its named definition while retaining the
        # root `$defs` context so nested local references (for example the
        # design-score item schema) resolve correctly.
        for path, record in self.records:
            definition = SCHEMA_DEFINITIONS.get(str(record.get("record_type")))
            if definition is None:
                self.error(f"{self.rel(path)}: no JSON Schema definition for record_type {record.get('record_type')!r}")
                continue
            record_schema = {
                "$schema": schema["$schema"],
                "$defs": schema["$defs"],
                "$ref": f"#/$defs/{definition}",
            }
            validator = Draft202012Validator(record_schema)
            issues = sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))
            for issue in issues:
                where = ".".join(map(str, issue.absolute_path)) or "$"
                self.error(f"{self.rel(path)}:{where}: {issue.message}")

    def records_of(self, record_type: str) -> list[tuple[Path, dict[str, Any]]]:
        return [(p, r) for p, r in self.records if r.get("record_type") == record_type]

    def evidence_paths_exist(self, value: Any, label: str) -> None:
        if isinstance(value, list):
            for i, item in enumerate(value):
                self.evidence_paths_exist(item, f"{label}[{i}]")
            return
        if not isinstance(value, str) or not value:
            return
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
            return
        self.resolve_record_path(value, label)

    def inspect_path_fields(self, value: Any, label: str) -> None:
        """Resolve evidence and deliverable paths without mistaking URLs for files."""
        if isinstance(value, dict):
            for key, child in value.items():
                key_label = f"{label}.{key}"
                if key in {"path", "html_path", "output_html_path", "evidence_path", "source_facts_path", "generation_context_path"}:
                    if isinstance(child, str) and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", child):
                        self.resolve_record_path(child, key_label)
                elif key == "evidence_paths":
                    self.evidence_paths_exist(child, key_label)
                else:
                    self.inspect_path_fields(child, key_label)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                self.inspect_path_fields(child, f"{label}[{i}]")

    @staticmethod
    def digest(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def validate(self) -> None:
        self.load_records()
        self.check_json_schema()
        runs = self.records_of("run")
        if len(runs) != 1:
            self.error(f"Expected exactly one run record; found {len(runs)}")
            return
        run_path, run = runs[0]
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            self.error(f"{self.rel(run_path)}: missing run_id")
        for path, record in self.records:
            if record is run:
                continue
            if record.get("run_id") != run_id:
                self.error(f"{self.rel(path)}: run_id does not match evidence/run.json")
        for record_type, label in (("source_facts", "source-facts"), ("generation_context", "generation-context"), ("candidate_ledger", "candidate-ledger")):
            matches = self.records_of(record_type)
            if len(matches) != 1:
                self.error(f"Expected exactly one {label} record; found {len(matches)}")
        if run.get("evidence_index"):
            self.resolve_record_path(run.get("evidence_index"), "run evidence_index")
        else:
            self.error("evidence/run.json: missing evidence_index")

        deliverables = run.get("deliverables")
        if not isinstance(deliverables, dict):
            self.error("evidence/run.json: deliverables must be an object")
            deliverables = {}
        digest_by_candidate: dict[str, tuple[str, Path]] = {}
        for name, item in deliverables.items():
            if not isinstance(item, dict):
                self.error(f"run deliverable {name!r} must be an object")
                continue
            dpath = self.resolve_record_path(item.get("path"), f"run deliverable {name}.path")
            if dpath is None:
                continue
            actual_digest = self.digest(dpath)
            expected_digest = item.get("sha256") or item.get("html_sha256")
            if expected_digest != actual_digest:
                self.error(f"run deliverable {name}: digest mismatch (recorded {expected_digest!r}, actual {actual_digest})")
            if item.get("bytes") != dpath.stat().st_size and item.get("html_bytes") != dpath.stat().st_size:
                self.error(f"run deliverable {name}: byte count mismatch")
            if item.get("qa_html_sha256") != actual_digest:
                self.error(f"run deliverable {name}: qa_html_sha256 must identify the tested HTML bytes")
            cid = item.get("candidate_id")
            if not isinstance(cid, str) or not cid:
                self.error(f"run deliverable {name}: missing candidate_id")
            else:
                digest_by_candidate[cid] = (actual_digest, dpath)
                if run.get("status") == "PASS" and item.get("package_status") != "PASS":
                    self.error(f"run deliverable {name}: a passing run requires package_status=PASS")
        if run.get("execution_mode") != "skill":
            self.error("validate_evidence.py performs skill-run cross-record checks; workflow runs use package_website_poc.py schema validation")
            return
        run_candidate_ids = run.get("candidate_ids")
        selected_candidate_ids = set(run_candidate_ids) if isinstance(run_candidate_ids, list) else set()
        if run.get("status") == "PASS" and selected_candidate_ids != set(digest_by_candidate):
            self.error("skill run.json candidate_ids do not match candidate IDs in deliverables")

        by_candidate: dict[str, dict[str, list[tuple[Path, dict[str, Any]]]]] = {}
        for path, record in self.records:
            cid = record.get("candidate_id")
            if isinstance(cid, str) and cid:
                by_candidate.setdefault(cid, {}).setdefault(str(record.get("record_type")), []).append((path, record))
            self.evidence_paths_exist(record.get("evidence_paths"), f"{self.rel(path)}.evidence_paths")
            self.inspect_path_fields(record, self.rel(path))

        final_passes: dict[str, dict[str, Any]] = {}
        final_files = self.records_of("final_status")
        for path, final in final_files:
            cid = final.get("candidate_id")
            if not isinstance(cid, str):
                continue
            fpath = self.resolve_record_path(final.get("html_path"), f"{self.rel(path)}.html_path")
            if fpath is None:
                continue
            digest = self.digest(fpath)
            if final.get("html_sha256") != digest:
                self.error(f"{self.rel(path)}: final HTML digest does not match delivered bytes")
            if final.get("html_bytes") != fpath.stat().st_size:
                self.error(f"{self.rel(path)}: final HTML byte count does not match delivered bytes")
            if cid in digest_by_candidate and digest_by_candidate[cid][0] != digest:
                self.error(f"{self.rel(path)}: digest disagrees with run.json deliverable")
            elif cid in digest_by_candidate and digest_by_candidate[cid][1] != fpath:
                self.error(f"{self.rel(path)}: output path disagrees with run.json deliverable")
            if final.get("final_status") == "PASS":
                if cid in selected_candidate_ids:
                    final_passes[cid] = final
                elif run.get("status") == "PASS":
                    self.error(f"{self.rel(path)}: passing candidate is not selected in run.json candidate_ids")
                for filename, rec_type in REQUIRED_CANDIDATE_FILES.items():
                    matches = [(rp, rec) for rp, rec in by_candidate.get(cid, {}).get(rec_type, [])
                               if rp.name == filename]
                    if len(matches) != 1:
                        self.error(f"candidate {cid}: PASS requires exactly one {filename}; found {len(matches)}")
                if final.get("static_qa_status") != "PASS" or final.get("browser_qa_status") != "PASS":
                    self.error(f"candidate {cid}: PASS requires static and browser QA PASS")
                for key in ("repair_status", "image_review_status", "visual_review_status"):
                    if final.get(key) not in {"PASS", "NOT_REQUIRED"}:
                        self.error(f"candidate {cid}: PASS has non-passing {key}={final.get(key)!r}")
                candidate_records = by_candidate.get(cid, {})
                inputs = [(rp, rec) for rp, rec in candidate_records.get("candidate_inputs", []) if rp.name == "candidate-inputs.json"]
                if len(inputs) == 1:
                    input_path, inputs_record = inputs[0]
                    slot = inputs_record.get("slot")
                    template = inputs_record.get("template")
                    expected = {1: ("Forty", "candidate-forty.html"), 2: ("Landed", "candidate-landed.html"), 3: ("Story", "candidate-story.html")}
                    if run.get("execution_mode") == "skill":
                        if slot not in expected:
                            self.error(f"{self.rel(input_path)}: skill slot must be 1, 2, or 3")
                        else:
                            expected_template, expected_file = expected[slot]
                            if template != expected_template:
                                self.error(f"{self.rel(input_path)}: slot {slot} must use {expected_template}")
                            if final.get("html_path") != expected_file:
                                self.error(f"{self.rel(path)}: slot {slot} must deliver {expected_file}")
                for filename, record_type in REQUIRED_CANDIDATE_FILES.items():
                    found = [(rp, rec) for rp, rec in candidate_records.get(record_type, []) if rp.name == filename]
                    if len(found) != 1:
                        continue
                    rec_path, rec = found[0]
                    if rec.get("run_id") != run_id:
                        self.error(f"{self.rel(rec_path)}: run_id mismatch")
                    if filename in {"static-qa.json", "browser-qa.json"}:
                        if rec.get("status") != "PASS":
                            self.error(f"{self.rel(rec_path)}: PASS candidate requires QA status PASS")
                        if rec.get("html_sha256") != digest:
                            self.error(f"{self.rel(rec_path)}: QA digest does not match delivered bytes")
                        if rec.get("html_path") != final.get("html_path"):
                            self.error(f"{self.rel(rec_path)}: QA html_path disagrees with final-status")
                        if rec.get("blocking_failures"):
                            self.error(f"{self.rel(rec_path)}: PASS candidate QA record has blocking_failures")
                        for check in rec.get("checks", []):
                            if isinstance(check, dict) and check.get("blocking") and check.get("status") != "PASS":
                                self.error(f"{self.rel(rec_path)}: PASS candidate has non-passing blocking check {check.get('id')!r}")
                        if filename == "browser-qa.json":
                            viewports = rec.get("viewports", {})
                            expected_viewports = {"desktop": (1440, 900), "mobile": (390, 844)}
                            for viewport, size in expected_viewports.items():
                                item = viewports.get(viewport) if isinstance(viewports, dict) else None
                                if not isinstance(item, dict):
                                    self.error(f"{self.rel(rec_path)}: PASS browser QA requires {viewport} viewport evidence")
                                elif (item.get("width"), item.get("height")) != size:
                                    self.error(f"{self.rel(rec_path)}: {viewport} viewport must be {size[0]}x{size[1]}")
                    if filename == "repairs.json":
                        after = rec.get("html_sha256_after")
                        if after and after != digest:
                            self.error(f"{self.rel(rec_path)}: repair after-digest does not match delivered bytes")
                        if rec.get("status") != final.get("repair_status"):
                            self.error(f"{self.rel(rec_path)}: repair status disagrees with final-status")
                    if filename == "image-review.json" and rec.get("status") != "PASS":
                        self.error(f"{self.rel(rec_path)}: PASS candidate requires image-review status PASS")
                    if filename == "image-review.json" and rec.get("missing_image_urls"):
                        self.error(f"{self.rel(rec_path)}: PASS candidate image review lists missing image URLs")
                    if filename == "image-review.json" and rec.get("status") != final.get("image_review_status"):
                        self.error(f"{self.rel(rec_path)}: image-review status disagrees with final-status")
                    if filename == "image-review.json" and run.get("execution_mode") == "skill":
                        for image in rec.get("images", []):
                            if not isinstance(image, dict):
                                continue
                            if final.get("final_status") == "PASS":
                                for field in ("relevant", "crop_ok", "alt_accurate"):
                                    if image.get(field) is not True:
                                        self.error(f"{self.rel(rec_path)}: PASS skill candidate image {image.get('url')!r} requires {field}=true")
                                if image.get("resolution_status") != "PASS":
                                    self.error(f"{self.rel(rec_path)}: PASS skill candidate image {image.get('url')!r} requires resolution_status=PASS")
                                source_width = image.get("source_width")
                                rendered_width = image.get("rendered_css_width")
                                if not isinstance(source_width, (int, float)) or not isinstance(rendered_width, (int, float)):
                                    self.error(f"{self.rel(rec_path)}: PASS skill candidate image {image.get('url')!r} requires verified source_width and rendered_css_width")
                                elif source_width < rendered_width:
                                    self.error(f"{self.rel(rec_path)}: PASS skill candidate image {image.get('url')!r} is upscaled ({source_width}px source for {rendered_width}px rendered width)")
                    if filename == "visual-review.json":
                        if rec.get("status") != "PASS":
                            self.error(f"{self.rel(rec_path)}: PASS candidate requires visual-review status PASS")
                        viewports = {x.get("viewport") for x in rec.get("screenshots", []) if isinstance(x, dict)}
                        if viewports != {"desktop", "mobile"}:
                            self.error(f"{self.rel(rec_path)}: PASS visual review requires desktop and mobile screenshots")
                        if rec.get("blocking_defects"):
                            self.error(f"{self.rel(rec_path)}: PASS visual review has blocking defects")
                        for check_id, item in rec.get("checks", {}).items():
                            if isinstance(item, dict) and item.get("passed") is not True:
                                self.error(f"{self.rel(rec_path)}: visual check {check_id!r} did not pass")
                        for shot in rec.get("screenshots", []):
                            if isinstance(shot, dict):
                                self.evidence_paths_exist(shot.get("path"), f"{self.rel(rec_path)} screenshot")
                                if shot.get("html_sha256") != digest:
                                    self.error(f"{self.rel(rec_path)}: screenshot digest does not match delivered bytes")
                                expected_size = {"desktop": (1440, 900), "mobile": (390, 844)}.get(shot.get("viewport"))
                                if expected_size and (shot.get("width"), shot.get("height")) != expected_size:
                                    self.error(f"{self.rel(rec_path)}: {shot.get('viewport')} screenshot must be {expected_size[0]}x{expected_size[1]}")
                        if rec.get("status") != final.get("visual_review_status"):
                            self.error(f"{self.rel(rec_path)}: visual-review status disagrees with final-status")
                    if filename == "final-status.json" and rec.get("final_status") != "PASS":
                        self.error(f"{self.rel(rec_path)}: final-status record must be PASS")
                if final.get("blocking_failures"):
                    self.error(f"candidate {cid}: PASS has blocking_failures")
                for check in final.get("package_checks", []):
                    if isinstance(check, dict) and check.get("blocking") and check.get("status") != "PASS":
                        self.error(f"candidate {cid}: PASS has a failed/blocking package check {check.get('id')!r}")

            # Every digest-bound record for this candidate must identify these delivered bytes.
            for rec_type in ("qa_result", "image_review", "visual_review"):
                for rp, rec in by_candidate.get(cid, {}).get(rec_type, []):
                    if rec.get("html_sha256") != digest:
                        self.error(f"{self.rel(rp)}: HTML digest does not match final delivered bytes for {cid}")
            for rp, rec in by_candidate.get(cid, {}).get("repairs", []):
                after = rec.get("html_sha256_after")
                if after and after != digest:
                    self.error(f"{self.rel(rp)}: repair after-digest does not match final delivered bytes for {cid}")

            # Skill visual reviews require the seven-point weighted advisory scorecard.
            if run.get("execution_mode") == "skill":
                reviews = by_candidate.get(cid, {}).get("visual_review", [])
                for rp, review in reviews:
                    scorecard = review.get("design_scorecard")
                    if not isinstance(scorecard, dict):
                        self.error(f"{self.rel(rp)}: skill visual review is missing design_scorecard")
                        continue
                    scores = scorecard.get("scores")
                    if not isinstance(scores, dict):
                        self.error(f"{self.rel(rp)}: design_scorecard.scores must be an object")
                        continue
                    points = 0.0
                    for key, weight in SCORE_WEIGHTS.items():
                        entry = scores.get(key)
                        if not isinstance(entry, dict):
                            self.error(f"{self.rel(rp)}: missing score {key}")
                            continue
                        score = entry.get("score")
                        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 5:
                            self.error(f"{self.rel(rp)}: {key}.score must be from 0 to 5")
                            continue
                        if entry.get("weight") != weight:
                            self.error(f"{self.rel(rp)}: {key}.weight must be {weight}")
                        points += weight * score / 5
                    if abs(float(scorecard.get("weighted_total", -999)) - points) > 0.02:
                        self.error(f"{self.rel(rp)}: weighted_total does not match component scores ({points:.2f})")
                    if scorecard.get("is_advisory") is not True:
                        self.error(f"{self.rel(rp)}: design scorecard must be explicitly advisory")

        ledger_records = self.records_of("candidate_ledger")
        if len(ledger_records) != 1:
            self.error(f"Expected exactly one candidate ledger; found {len(ledger_records)}")
        else:
            ledger_path, ledger = ledger_records[0]
            if ledger.get("execution_mode") != run.get("execution_mode"):
                self.error(f"{self.rel(ledger_path)}: execution_mode differs from run.json")
            if run.get("execution_mode") == "skill":
                expected = (3, 3, 6)
                observed = (ledger.get("initial_attempt_limit"), ledger.get("continuation_attempt_limit"), ledger.get("max_total_attempts"))
                if observed != expected:
                    self.error(f"{self.rel(ledger_path)}: skill attempt limits must be 3+3 (max 6); found {observed}")
                attempts = ledger.get("attempts", [])
                numbers = [x.get("attempt_number") for x in attempts if isinstance(x, dict)]
                if len(numbers) != len(set(numbers)):
                    self.error(f"{self.rel(ledger_path)}: attempt_number values must be unique")
                if len(attempts) > 6 or ledger.get("attempts_used") != len(attempts):
                    self.error(f"{self.rel(ledger_path)}: attempts_used must match the unique ledger entries and be at most 6")
            passing_slots = ledger.get("passing_slots", [])
            if ledger.get("passing_count") != len(passing_slots):
                self.error(f"{self.rel(ledger_path)}: passing_count does not equal passing_slots length")
            slot_nums = [x.get("slot") for x in passing_slots if isinstance(x, dict)]
            if len(slot_nums) != len(set(slot_nums)):
                self.error(f"{self.rel(ledger_path)}: duplicate passing slots")
            for item in passing_slots:
                if not isinstance(item, dict):
                    continue
                cid = item.get("candidate_id")
                if cid not in final_passes:
                    self.error(f"{self.rel(ledger_path)}: ledger passing slot {item.get('slot')} has no PASS final-status record")
                    continue
                final = final_passes[cid]
                if item.get("html_sha256") != final.get("html_sha256") or item.get("html_path") != final.get("html_path"):
                    self.error(f"{self.rel(ledger_path)}: passing slot disagrees with final status for {cid}")
            if ledger.get("terminal_status") == "PASS" and (len(passing_slots) != 3 or set(slot_nums) != {1, 2, 3}):
                self.error(f"{self.rel(ledger_path)}: terminal PASS requires three distinct slots (1, 2, 3)")
            if ledger.get("terminal_status") == "PASS" and run.get("status") != "PASS":
                self.error(f"{self.rel(ledger_path)}: ledger PASS requires run.json status PASS")

        if run.get("status") == "PASS":
            if run.get("execution_mode") == "skill" and run.get("runtime_profile") != "full_parity":
                self.error("run PASS in skill mode requires runtime_profile=full_parity")
            if len(final_passes) != 3:
                self.error(f"run PASS requires three passing candidate records; found {len(final_passes)}")
            if len(digest_by_candidate) != 3:
                self.error(f"run PASS requires three candidate deliverables; found {len(digest_by_candidate)}")
            if len(deliverables) != 3:
                self.error(f"run PASS requires exactly three deliverable entries; found {len(deliverables)}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: validate_evidence.py <website-poc-output-root>")
        return 2
    root = Path(argv[0])
    if not root.is_dir():
        print(f"FAIL: output root is not a directory: {root}")
        return 2
    audit = Audit(root)
    audit.validate()
    for warning in audit.warnings:
        print(f"UNVERIFIED: {warning}")
    for error in audit.errors:
        print(f"FAIL: {error}")
    if audit.errors:
        print(f"Evidence validation failed with {len(audit.errors)} error(s).")
        return 1
    print(f"PASS: cross-record evidence checks passed ({len(audit.records)} normalized record(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
