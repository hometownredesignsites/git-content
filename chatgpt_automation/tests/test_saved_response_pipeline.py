"""Exercise capture, assembly, inlining, and the structural gate offline."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from chatgpt_automation.scripts.website_chunks import WebsiteTurnError, _part_prompt, run_website_chunks
from chatgpt_automation.scripts.normalize_cta_arrows import normalize
from chatgpt_file_playwright_anonymous_ci import inspect_chatgpt_page_state
from playwright_runner.browser_session import response_generation_active


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "chatgpt_automation" / "fixtures" / "saved_responses"
SCRIPTS = ROOT / "chatgpt_automation" / "scripts"
CHAT_ID = "fixture-candidate"
RUN_TOKEN = "fixture-run-token"
REQUEST = (
    "Create a source-grounded sample website with a hero, services section, "
    "contact form, and footer. Source website: https://fixture.invalid/"
)


class SavedResponsePipelineTest(unittest.TestCase):
    def test_css_three_is_not_a_supported_generation_stage(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-css-stage-") as temporary:
            with self.assertRaisesRegex(ValueError, "stop_after must be one of css-1, css-2, html-1, html-2"):
                run_website_chunks(
                    run_folder=Path(temporary) / "candidate",
                    chat_id=CHAT_ID,
                    source_facts_and_design_brief="Synthetic brief.",
                    exchange=lambda _prompt: self.fail("Unsupported stage must fail before generation."),
                    stop_after="css-4",
                )

    def test_cta_arrow_normalizer_removes_only_glyphs_inside_ctas(self):
        source = (
            '<a class="button" href="/estimate" aria-label="Estimate &rarr;">Get an Estimate →</a>'
            '<button aria-label="Call us">Call &rarr; now ↓</button>'
            '<p>Direction: → keep this arrow</p>'
            '<a href="/story">Story →</a>'
        )
        output, removed = normalize(source)
        self.assertEqual(removed, 4)
        self.assertEqual(
            output,
            '<a class="button" href="/estimate" aria-label="Estimate ">Get an Estimate </a>'
            '<button aria-label="Call us">Call  now </button>'
            '<p>Direction: → keep this arrow</p>'
            '<a href="/story">Story →</a>',
        )
        self.assertEqual(normalize(output), (output, 0))

    def test_cta_arrow_normalizer_removes_decorative_arrow_elements(self):
        source = (
            '<a class="button" href="/estimate">Get an Estimate '
            '<span class="button-arrow" aria-hidden="true"><i>→</i></span></a>'
            '<a class="button" href="tel:555">Call <span class="phone-icon"></span></a>'
        )
        output, removed = normalize(source)
        self.assertEqual(removed, 1)
        self.assertEqual(
            output,
            '<a class="button" href="/estimate">Get an Estimate </a>'
            '<a class="button" href="tel:555">Call <span class="phone-icon"></span></a>',
        )
        self.assertEqual(normalize(output), (output, 0))

    def test_chatgpt_aria_stop_control_is_recognized_as_active_generation(self):
        class Locator:
            def __init__(self, visible):
                self.visible = visible

            def count(self):
                return 1 if self.visible else 0

            def nth(self, _index):
                return self

            def is_visible(self):
                return self.visible

        class Page:
            def locator(self, selector):
                return Locator(selector == "button[aria-label='Stop generating']")

        self.assertTrue(response_generation_active(Page()))

    def test_generation_contract_has_two_css_parts_then_two_html_fragments(self):
        css = _part_prompt("css", 1, RUN_TOKEN, "fixture design brief", None)
        css2 = _part_prompt("css", 2, RUN_TOKEN, "fixture design brief", ("css", 1))
        html = _part_prompt("html", 1, RUN_TOKEN, "fixture design brief", ("css", 2), css_reference=".hero { color: black; }")
        instructions = (ROOT / "chatgpt_automation" / "website_request.txt").read_text(encoding="utf-8")
        self.assertIn("CSS PART 1 OF 2", css)
        self.assertIn("CSS PART 2 OF 2", css2)
        html2 = _part_prompt("html", 2, RUN_TOKEN, "fixture design brief", ("html", 1))
        self.assertIn("HTML PART 1 OF 2", html)
        self.assertIn("HTML PART 2 OF 2", html2)
        self.assertIn("ACCEPTED CSS REFERENCE", html)
        self.assertIn("close body and html", html2)
        for text in (css, css2, html):
            self.assertIn("exactly one fenced code block", text)
        self.assertIn("two ordered CSS parts", instructions)
        self.assertIn("Define the reusable class names", css)
        self.assertIn("actual selectors and declarations", css)
        self.assertIn("reduced-motion support", css2)
        self.assertNotIn("SOURCE FACTS AND DESIGN BRIEF", css2)
        self.assertIn("Do not produce a source audit", css)
        self.assertIn("do not include research notes, a source audit", instructions)
        self.assertIn("two CSS parts", html)
        self.assertIn("two ordered HTML chunks in the same guest conversation", instructions)
        self.assertNotIn("final acknowledgment", html.lower())
        self.assertNotIn("eight labeled parts", instructions)
        self.assertIn("literal source text inside a `text` code fence", html)
        self.assertIn("Do not use an HTML/rendered preview", html)

    def test_html_preview_fence_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-html-fence-") as temporary:
            root = Path(temporary)
            run = root / "candidate"
            run.mkdir()
            response = root / "response.txt"
            response.write_text(
                "RUN TOKEN: fixture-run-token\nHTML PART 1 OF 4\n"
                "```html\n<!-- HTML PART 1 OF 4 -->\n<p>partial document</p>\n```\n",
                encoding="utf-8",
            )
            result = subprocess.run([
                sys.executable,
                str(SCRIPTS / "capture_chunk.py"),
                str(run), str(response), "--kind", "html", "--part", "1",
                "--chat-id", CHAT_ID, "--run-token", RUN_TOKEN,
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected a text fence", result.stderr)

    def test_empty_response_retries_same_chunk_once(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-empty-retry-") as temporary:
            run = Path(temporary) / "candidate"
            prompts = []

            def exchange(prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    raise WebsiteTurnError(
                        "empty_response",
                        "No assistant response was captured.",
                        {"classification": "ready"},
                    )
                return (FIXTURES / "css-1.txt").read_text(encoding="utf-8")

            result = run_website_chunks(
                run_folder=run,
                chat_id=CHAT_ID,
                source_facts_and_design_brief="Synthetic retry brief.",
                exchange=exchange,
                run_token=RUN_TOKEN,
                context_mode="minimal",
                stop_after="css-1",
            )

            self.assertEqual(result["accepted_parts"], ["css-1"])
            self.assertEqual(len(prompts), 2)
            self.assertIn("Now produce exactly CSS PART 1 OF 2", prompts[0])
            self.assertIn("produced no capturable response", prompts[1])
            transcript = [
                json.loads(line)
                for line in (run / "conversation_transcript.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([turn["metadata"]["attempt"] for turn in transcript if turn["role"] == "user"], [1, 2])

    def test_saved_responses_assemble_inline_and_pass_structural_gate(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-fixture-") as temporary:
            run = Path(temporary) / "candidate"
            captured = run / "debug" / "captured_responses"
            captured.mkdir(parents=True)
            (run / "debug" / "website_quality_request.txt").write_text(REQUEST, encoding="utf-8")
            (run / "debug" / "source_facts.json").write_text(json.dumps({
                "pages_reviewed": [{
                    "url": "https://fixture.invalid/contact",
                    "forms": [{"fields": [
                        {"type": "text", "name": "name", "label": "Name", "required": True},
                        {"type": "tel", "name": "phone", "label": "Phone", "required": True},
                        {"type": "email", "name": "email", "label": "Email", "required": False},
                        {"type": "textarea", "name": "message", "label": "Project details", "required": False},
                    ]}],
                }],
            }, indent=2), encoding="utf-8")

            parts = [("css", number) for number in range(1, 3)] + [("html", number) for number in range(1, 3)]
            for kind, number in parts:
                response = FIXTURES / f"{kind}-{number}.txt"
                self.assertTrue(response.is_file(), f"missing saved fixture {response.name}")
                captured_response = captured / response.name
                captured_response.write_bytes(response.read_bytes())
                subprocess.run([
                    sys.executable,
                    str(SCRIPTS / "capture_chunk.py"),
                    str(run),
                    str(captured_response),
                    "--kind", kind,
                    "--part", str(number),
                    "--chat-id", CHAT_ID,
                    "--run-token", RUN_TOKEN,
                ], check=True, capture_output=True, text=True, encoding="utf-8")

            subprocess.run([sys.executable, str(SCRIPTS / "assemble_chunks.py"), str(run)],
                           check=True, capture_output=True, text=True, encoding="utf-8")
            html_file = run / "files" / "index.html"
            css_file = run / "files" / "styles.css"
            inlined_file = run / "files" / "inlined" / "index.html"
            subprocess.run([sys.executable, str(SCRIPTS / "inline_css.py"), str(html_file), str(css_file), str(inlined_file)],
                           check=True, capture_output=True, text=True, encoding="utf-8")

            self.assertIn('.menu-toggle > span[aria-hidden="true"]', css_file.read_text(encoding="utf-8"))
            browser_checks = {
                "rendered_sections_visible_desktop_and_mobile": True,
                "hero_spans_viewport_desktop_and_mobile": True,
                "hero_media_covers_hero_desktop_and_mobile": True,
                "cta_visible_first_screen_desktop_and_mobile": True,
                "mobile_menu_clicks_work": True,
                "mobile_menu_control_visible": True,
                "mobile_menu_focus_indicator_visible": True,
                "mobile_menu_keyboard_works": True,
                "mobile_has_no_horizontal_overflow": True,
                "fonts_load_in_browser": True,
                "images_load_in_browser": True,
            }
            (run / "debug" / "browser_qa.json").write_text(json.dumps({
                "status": "pass", "checks": browser_checks,
                "mobile_menu": {"escape_closes": True},
            }), encoding="utf-8")

            result = subprocess.run([
                sys.executable,
                str(SCRIPTS / "check_website.py"),
                str(run),
                REQUEST,
            ], check=True, capture_output=True, text=True, encoding="utf-8")
            report = json.loads(result.stdout)
            self.assertTrue(report["automated_success"], report["blocking_failures"])
            browser_checks["mobile_menu_control_visible"] = False
            (run / "debug" / "browser_qa.json").write_text(json.dumps({
                "status": "fail", "checks": browser_checks,
                "mobile_menu": {"escape_closes": True},
            }), encoding="utf-8")
            failed_gate = subprocess.run([
                sys.executable,
                str(SCRIPTS / "check_website.py"),
                str(run),
                REQUEST,
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(failed_gate.returncode, 2)
            failed_report = json.loads(failed_gate.stdout)
            self.assertIn("browser_mobile_menu_control_visible", failed_report["blocking_failures"])
            browser_checks["mobile_menu_control_visible"] = True
            browser_checks["cta_visible_first_screen_desktop_and_mobile"] = False
            (run / "debug" / "browser_qa.json").write_text(json.dumps({
                "status": "fail", "checks": browser_checks,
                "mobile_menu": {"escape_closes": True},
            }), encoding="utf-8")
            failed_cta_gate = subprocess.run([
                sys.executable,
                str(SCRIPTS / "check_website.py"),
                str(run),
                REQUEST,
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(failed_cta_gate.returncode, 2)
            failed_cta_report = json.loads(failed_cta_gate.stdout)
            self.assertIn("browser_cta_visible_first_screen_desktop_and_mobile", failed_cta_report["blocking_failures"])
            self.assertEqual(len(json.loads((run / "chunks" / "capture_manifest.json").read_text(encoding="utf-8"))["parts"]), 4)
            self.assertEqual(css_file.read_text(encoding="utf-8").count("CSS PART "), 2)
            self.assertTrue(inlined_file.is_file())
            self.assertIn("<style>", inlined_file.read_text(encoding="utf-8"))
            self.assertNotIn('href="styles.css"', inlined_file.read_text(encoding="utf-8"))

    def test_incremental_ladder_keeps_checkpoint_and_starts_html_chat(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-ladder-") as temporary:
            run = Path(temporary) / "candidate"
            brief = "Bounded synthetic source facts and design brief."
            calls = []

            def exchange(prompt):
                import re

                match = re.search(r"(?:Now produce exactly|previous response for) (CSS|HTML) PART (\d+) OF", prompt, re.IGNORECASE)
                self.assertIsNotNone(match, prompt)
                kind, number = match.group(1).lower(), int(match.group(2))
                calls.append((kind, number))
                return (FIXTURES / f"{kind}-{number}.txt").read_text(encoding="utf-8")

            common = {
                "run_folder": run,
                "chat_id": CHAT_ID,
                "source_facts_and_design_brief": brief,
                "exchange": exchange,
                "conversation_url": lambda: "https://chatgpt.com/uc/fixture-conversation",
                "run_token": RUN_TOKEN,
                "context_mode": "minimal",
            }
            first = run_website_chunks(**common, stop_after="css-1")
            self.assertEqual(first["accepted_parts"], ["css-1"])
            self.assertEqual(first["staged_until"], "css-1")

            css_done = run_website_chunks(**common, stop_after="css-2")
            self.assertEqual(css_done["accepted_parts"], ["css-1", "css-2"])
            self.assertEqual(css_done["staged_until"], "css-2")

            html_done = run_website_chunks(**common, stop_after="html-2")
            self.assertEqual(html_done["accepted_parts"], ["css-1", "css-2", "html-1", "html-2"])
            self.assertEqual(calls, [("css", 1), ("css", 2), ("html", 1), ("html", 2)])
            self.assertEqual(html_done["conversation_url"], "https://chatgpt.com/uc/fixture-conversation")
            self.assertEqual(html_done["css_conversation_url"], html_done["html_conversation_url"])
            self.assertFalse(html_done.get("complete", False))
            transcript = [json.loads(line) for line in (run / "conversation_transcript.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertIn("DIAGNOSTIC CONTEXT", transcript[0]["text"])

            with self.assertRaisesRegex(RuntimeError, "context mode differs"):
                run_website_chunks(**{**common, "context_mode": "source"}, stop_after="html-2")

    def test_minimal_context_does_not_require_or_include_csv_business_facts(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-minimal-context-") as temporary:
            folder = Path(temporary)
            output = folder / "website_context.md"
            inputs = folder / "inputs.json"
            subprocess.run([
                sys.executable,
                str(SCRIPTS / "prepare_candidate_context.py"),
                "--mode", "minimal",
                "--output", str(output),
                "--inputs-output", str(inputs),
                "--site-index", "1",
            ], check=True, capture_output=True, text=True, encoding="utf-8")
            context = output.read_text(encoding="utf-8")
            metadata = json.loads(inputs.read_text(encoding="utf-8"))
            self.assertIn("fictional", context)
            self.assertNotIn("josh", context.lower())
            self.assertEqual(metadata["context_mode"], "minimal")
            self.assertEqual(metadata["source_pages_fetched"], 0)

    def test_prepared_context_has_a_hard_size_cap_and_keeps_form_evidence(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-context-") as temporary:
            folder = Path(temporary)
            source_facts = folder / "source_facts.json"
            design = folder / "design_brief.txt"
            output = folder / "website_context.md"
            inputs = folder / "inputs.json"
            pages = []
            for number in range(8):
                pages.append({
                    "url": "https://fixture.invalid/" if number == 0 else f"https://fixture.invalid/service-{number}/",
                    "title": f"Source page {number}",
                    "headings": [f"Heading {i}" for i in range(20)],
                    "text": "Source copy with verified service facts. " * 800,
                    "forms": [{"fields": [{"type": "tel", "label": "Phone", "required": True}]}] if number == 0 else [],
                })
            source_facts.write_text(json.dumps({
                "requested_url": "https://fixture.invalid/",
                "source_domain": "fixture.invalid",
                "business_metadata_unverified": {"business": "Fixture Studio", "category": "Workshop"},
                "pages_reviewed": pages,
                "source_assets": [{"url": f"https://fixture.invalid/image-{i}.jpg", "alt": f"Sample {i}"} for i in range(80)],
                "navigation_links": [{"href": f"/service-{i}/", "text": f"Service {i}"} for i in range(120)],
            }, ensure_ascii=False), encoding="utf-8")
            design.write_text("Use source-supported facts only. " * 80, encoding="utf-8")
            subprocess.run([
                sys.executable,
                str(SCRIPTS / "prepare_candidate_context.py"),
                "--source-facts", str(source_facts),
                "--design-brief", str(design),
                "--output", str(output),
                "--inputs-output", str(inputs),
                "--site-index", "1",
            ], check=True, capture_output=True, text=True, encoding="utf-8")
            context = output.read_text(encoding="utf-8")
            metadata = json.loads(inputs.read_text(encoding="utf-8"))
            self.assertLessEqual(len(context), metadata["generation_context_maximum_characters"])
            self.assertIn('"label":"Phone"', context)
            self.assertIn('"required":true', context)
            self.assertIn("fixture.invalid/", context)
            self.assertIn("Source copy with verified service facts.", context)
            self.assertNotIn("Fixture Studio", context)
            self.assertLess(len(context), 4000)
            self.assertNotIn('"text_excerpt"', context)
            self.assertNotIn('"type":"tel"', context)


class _FakeLocator:
    def __init__(self, *, attrs=None, text="", visible=False, items=None):
        self.attrs = attrs or {}
        self.text = text
        self.visible = visible
        self.items = items or []

    def get_attribute(self, name):
        return self.attrs.get(name)

    def inner_text(self, timeout=None):
        return self.text

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    def is_visible(self):
        return self.visible


class _FakePage:
    url = "https://chatgpt.com/"

    def __init__(self, *, gated=False, dialog_text="", captcha=False):
        self.root = _FakeLocator(attrs={"data-conversation-auth-gated": ""} if gated else {})
        self.body = _FakeLocator(text=dialog_text)
        dialog = _FakeLocator(text=dialog_text, visible=bool(dialog_text))
        challenge = _FakeLocator(visible=captcha)
        self.dialogs = [dialog] if dialog_text else []
        self.challenges = [challenge] if captcha else []

    def title(self):
        return "ChatGPT"

    def locator(self, selector):
        if selector == "html":
            return self.root
        if selector == "body":
            return self.body
        if selector.startswith("iframe["):
            return _FakeLocator(items=self.challenges)
        if selector == '[role="dialog"], dialog[open]':
            return _FakeLocator(items=self.dialogs)
        return _FakeLocator()


class ChatGPTPageStateTest(unittest.TestCase):
    def test_auth_and_captcha_states_are_classified_without_interaction(self):
        auth = inspect_chatgpt_page_state(_FakePage(gated=True))
        captcha = inspect_chatgpt_page_state(_FakePage(captcha=True))
        ready = inspect_chatgpt_page_state(_FakePage())
        self.assertEqual(auth["classification"], "login_required")
        self.assertEqual(captcha["classification"], "captcha_required")
        self.assertEqual(ready["classification"], "ready")

    def test_chatgpt_connection_failure_text_in_page_body_is_classified(self):
        page = _FakePage()
        page.body = _FakeLocator(
            text=(
                "Chat stopped unexpectedly. No internet. Unable to connect. "
                "ChatGPT is temporarily experiencing issues. We're working to restore service."
            )
        )

        observation = inspect_chatgpt_page_state(page)

        self.assertEqual(observation["classification"], "service_error")
        self.assertIn("visible ChatGPT connection", observation["signals"][0])
        self.assertIn("Unable to connect", observation["visible_text_excerpt"])

    def test_access_failure_class_and_observation_are_checkpointed(self):
        with tempfile.TemporaryDirectory(prefix="chatgpt-access-state-") as temporary:
            run = Path(temporary) / "candidate"

            def gated_exchange(_prompt):
                raise WebsiteTurnError(
                    "login_required",
                    "ChatGPT requires login.",
                    {"classification": "login_required", "signals": ["visible login dialog"]},
                )

            with self.assertRaisesRegex(WebsiteTurnError, "requires login"):
                run_website_chunks(
                    run_folder=run,
                    chat_id=CHAT_ID,
                    source_facts_and_design_brief="Short diagnostic brief.",
                    exchange=gated_exchange,
                    run_token=RUN_TOKEN,
                    context_mode="minimal",
                    stop_after="css-1",
                )
            checkpoint = json.loads((run / "chunks" / "sequence_checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["last_error"]["classification"], "login_required")
            self.assertEqual(checkpoint["last_error"]["page_observation"]["signals"], ["visible login dialog"])


if __name__ == "__main__":
    unittest.main()
