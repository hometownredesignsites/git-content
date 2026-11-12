"""Restore unambiguously missing source contact-form fields before final QA."""

from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
EXCLUDED_TYPES = {"hidden", "submit", "image", "reset"}
SAFE_INPUT_TYPES = {
    "text", "email", "tel", "url", "number", "date", "time", "datetime-local",
    "month", "week", "search",
}
CONTACT_HINT = re.compile(r"contact|contactus|enquir|inquir|quote|appointment|booking|booknow", re.I)
ARTICLE_PATH_HINT = re.compile(r"/(?:blog|blogs|article|articles|post|posts|news|comment|comments)(?:/|$)", re.I)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?1[\s().-]*)?(?:\(\d{3}\)|\d{3})[\s.-]*\d{3}[\s.-]*\d{4}(?!\d)")


def normalize_form_field(field: dict) -> str:
    raw_label = next((
        str(field.get(key, "")).strip()
        for key in ("label", "aria_label", "name", "placeholder")
        if str(field.get(key, "")).strip()
    ), "")
    raw_label = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_label)
    label = re.sub(r"[^a-z0-9]+", " ", raw_label.lower()).strip()
    words = label.split()
    if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:
        label = " ".join(words[:len(words) // 2])
    field_type = str(field.get("type", "")).lower()
    if field_type == "email" or "email" in label:
        return "email"
    if field_type == "tel" or re.search(r"\b(phone|telephone|mobile|tel)\b", label):
        return "phone"
    if re.search(r"\b(name|first|last)\b", label):
        return "name"
    if field_type == "textarea" or re.search(r"\b(message|details|comment|enquiry|inquiry)\b", label):
        return "message"
    if re.search(r"\b(address|location|city|postcode|zip)\b", label):
        return "property location"
    if re.search(r"\b(service|project type|what do you need)\b", label):
        return "project type"
    return label or field_type


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], start: int, start_end: int, parent: "_Node | None"):
        self.tag = tag
        self.attrs = attrs
        self.start = start
        self.start_end = start_end
        self.close_start: int | None = None
        self.close_end: int | None = None
        self.parent = parent
        self.children: list[_Node] = []
        self.text: list[str] = []

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class _DocumentParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.root = _Node("__root__", {}, 0, 0, None)
        self.stack = [self.root]
        self.nodes: list[_Node] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        if line - 1 >= len(self.line_offsets):
            return len(self.source)
        return min(len(self.source), self.line_offsets[line - 1] + column)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        start = self._offset()
        raw = self.get_starttag_text() or ""
        node = _Node(tag, {str(k).lower(): str(v or "") for k, v in attrs}, start, start + len(raw), self.stack[-1])
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        node = self.nodes[-1]
        node.close_start = node.start_end
        node.close_end = node.start_end
        if self.stack[-1] is node:
            self.stack.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        match_index = next((i for i in range(len(self.stack) - 1, 0, -1) if self.stack[i].tag == tag), None)
        if match_index is None:
            return
        node = self.stack[match_index]
        close_start = self._offset()
        close_match = re.match(r"</\s*" + re.escape(tag) + r"\s*>", self.source[close_start:], re.I)
        node.close_start = close_start
        node.close_end = close_start + len(close_match.group(0)) if close_match else close_start
        del self.stack[match_index:]

    def handle_data(self, data):
        clean = " ".join(data.split())
        if clean:
            for node in self.stack:
                node.text.append(clean)


def source_contact_form(source_facts: dict) -> dict:
    """Select one actual source contact form; never treat article comments as contact forms."""
    candidates = []
    contact_page_seen = False
    ignored_noncontact_forms = 0
    for page_index, page in enumerate(source_facts.get("pages_reviewed", [])):
        page_url = str(page.get("url", ""))
        page_path = urlsplit(page_url).path or "/"
        page_title = str(page.get("title", ""))
        is_contact_page = bool(CONTACT_HINT.search(page_path) or CONTACT_HINT.search(page_title))
        contact_page_seen = contact_page_seen or is_contact_page
        is_article_page = bool(ARTICLE_PATH_HINT.search(page_path))
        for form_index, form in enumerate(page.get("forms", [])):
            form_fields = [
                field for field in form.get("fields", [])
                if str(field.get("type", "")).lower() not in EXCLUDED_TYPES
            ]
            if not form_fields:
                continue
            categories = {normalize_form_field(field) for field in form_fields}
            contact_shape = (
                ("email" in categories and bool(categories & {"name", "message", "phone"}))
                or categories == {"phone"}
            )
            comment_form = any(
                re.search(r"\b(?:comment|reply|leave a reply)\b", " ".join(
                    str(field.get(key, "")) for key in ("name", "label", "aria_label", "placeholder")
                ), re.I)
                for field in form_fields
            )
            if is_contact_page:
                score = 100
            elif not is_article_page and not comment_form and contact_shape:
                score = 40
            else:
                ignored_noncontact_forms += 1
                continue
            score += 10 * len(categories & {"name", "email", "message", "phone"})
            candidates.append((score, -page_index, -form_index, page_url, form, form_fields))

    if not candidates:
        return {
            "status": "not_found",
            "page_url": "",
            "fields": [],
            "form": None,
            "contact_page_seen": contact_page_seen,
            "ignored_noncontact_forms": ignored_noncontact_forms,
        }

    _, _, _, page_url, form, fields = max(candidates, key=lambda item: item[:3])
    deduplicated = {}
    for field in fields:
        key = normalize_form_field(field)
        if key and key not in {"text", "select"}:
            existing = deduplicated.get(key)
            if existing is None or (field.get("required") and not existing.get("required")):
                deduplicated[key] = field
    return {
        "status": "captured",
        "page_url": page_url,
        "fields": list(deduplicated.values()),
        "form": form,
        "contact_page_seen": contact_page_seen,
        "ignored_noncontact_forms": ignored_noncontact_forms,
    }


def source_contact_channels(source_facts: dict) -> dict:
    """Return verified email and phone details found on the source contact page."""
    pages = [
        page for page in source_facts.get("pages_reviewed", [])
        if CONTACT_HINT.search(urlsplit(str(page.get("url", ""))).path)
        or CONTACT_HINT.search(str(page.get("title", "")))
    ]
    if not pages:
        pages = source_facts.get("pages_reviewed", [])[:1]
    text = " ".join(str(page.get("text", "")) for page in pages)
    emails = sorted({match.group(0).lower() for match in EMAIL_PATTERN.finditer(text)})
    phones = []
    seen_phone_digits = set()
    for match in PHONE_PATTERN.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 10:
            normalized = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            normalized = "+" + digits
        else:
            continue
        if normalized not in seen_phone_digits:
            seen_phone_digits.add(normalized)
            phones.append(normalized)
    return {"emails": emails, "phones": phones}


def _source_fields(source_facts: dict) -> tuple[list[dict], dict | None]:
    """Compatibility wrapper used by repair code and existing callers."""
    selected = source_contact_form(source_facts)
    return selected["fields"], selected["form"]


def _field_metadata(node: _Node, label_by_id: dict[str, str]) -> dict:
    tag = node.tag
    field_type = node.attrs.get("type", "text").lower() if tag == "input" else tag
    label = node.attrs.get("aria-label", "") or label_by_id.get(node.attrs.get("id", ""), "")
    return {
        "tag": tag,
        "type": field_type,
        "name": node.attrs.get("name", ""),
        "label": label,
        "placeholder": node.attrs.get("placeholder", ""),
        "required": "required" in node.attrs,
    }


def _inventory(source: str):
    parser = _DocumentParser(source)
    parser.feed(source)
    parser.close()
    labels = {}
    for node in parser.nodes:
        if node.tag == "label" and node.attrs.get("for"):
            labels[node.attrs["for"]] = " ".join(node.text)
    controls = [node for node in parser.nodes if node.tag in {"input", "textarea", "select"}]
    fields = []
    for node in controls:
        if node.tag == "input" and node.attrs.get("type", "text").lower() in EXCLUDED_TYPES:
            continue
        metadata = _field_metadata(node, labels)
        wrapping_label = node.parent
        while wrapping_label is not None and wrapping_label.tag != "label":
            wrapping_label = wrapping_label.parent
        if not metadata["label"] and wrapping_label is not None:
            metadata["label"] = " ".join(wrapping_label.text)
        fields.append((node, metadata))
    return parser, fields


def _contact_container(parser: _DocumentParser) -> _Node | None:
    candidates = []
    for node in parser.nodes:
        if node.tag not in {"section", "div", "article", "main"} or node.close_start is None:
            continue
        marker = " ".join((node.attrs.get("id", ""), node.attrs.get("class", ""), node.attrs.get("aria-label", "")))
        if not CONTACT_HINT.search(marker):
            continue
        has_form = any(child.tag == "form" for child in node.descendants())
        exact_id = bool(re.fullmatch(r"(?:contact|contact-us|contactus)", node.attrs.get("id", ""), re.I))
        tag_score = 2 if node.tag == "section" else 1 if node.tag in {"main", "article"} else 0
        score = (4 if has_form else 0) + (3 if exact_id else 0) + tag_score
        text_length = len(" ".join(node.text))
        candidates.append((score, -text_length, node))
    return max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "contact-field"


def _add_required(raw_start: str) -> str:
    trimmed = raw_start.rstrip()
    if trimmed.endswith("/>"):
        return trimmed[:-2] + " required/>"
    if trimmed.endswith(">"):
        return trimmed[:-1] + " required>"
    return raw_start


def _render_field(field: dict, used_ids: set[str]) -> str | None:
    label = " ".join(str(field.get("label") or field.get("aria_label") or field.get("placeholder") or field.get("name") or "").split())
    if not label:
        return None
    source_tag = str(field.get("tag", "input")).lower()
    source_type = str(field.get("type", "text")).lower()
    if source_type in {"checkbox", "radio", "select"} or source_tag == "select":
        return None
    if source_tag == "textarea" or normalize_form_field(field) == "message":
        tag, field_type = "textarea", "textarea"
    else:
        tag = "input"
        if normalize_form_field(field) == "email":
            field_type = "email"
        elif normalize_form_field(field) == "phone":
            field_type = "tel"
        elif normalize_form_field(field) in {"website", "url"}:
            field_type = "url"
        else:
            field_type = source_type if source_type in SAFE_INPUT_TYPES else "text"
    name = str(field.get("name", "")).strip() or _slug(label).replace("-", "_")
    base_id = _slug(str(field.get("id", "") or name or label))
    field_id = f"contact-source-{base_id}"
    suffix = 2
    while field_id in used_ids:
        field_id = f"contact-source-{base_id}-{suffix}"
        suffix += 1
    used_ids.add(field_id)
    required = " required" if field.get("required") is True else ""
    placeholder = str(field.get("placeholder", "")).strip()
    placeholder_attr = f' placeholder="{escape(placeholder, quote=True)}"' if placeholder else ""
    field_attrs = f'id="{field_id}" name="{escape(name, quote=True)}"'
    if tag == "textarea":
        control = f"<textarea {field_attrs}{placeholder_attr}{required}></textarea>"
    else:
        control = f'<input type="{field_type}" {field_attrs}{placeholder_attr}{required}>'
    return f'<div class="source-contact-field"><label for="{field_id}">{escape(label)}</label>{control}</div>'


def _repair_contact_channels(html_path: Path, source_facts: dict) -> dict:
    channels = source_contact_channels(source_facts)
    result = {"status": "not_needed", "added": [], "missing": [], "inserted_into": ""}
    if not html_path.is_file() or not any(channels.values()):
        return result
    original = html_path.read_text(encoding="utf-8", errors="replace")
    additions = []
    for email in channels["emails"]:
        if re.search(rf"href\s*=\s*(['\"])mailto:{re.escape(email)}(?:[?#][^'\"]*)?\1", original, re.I):
            continue
        additions.append(f'<a class="button" href="mailto:{escape(email, quote=True)}">Email Us</a>')
        result["added"].append({"type": "email", "value": email})
    linked_phones = {
        re.sub(r"\D", "", value)
        for value in re.findall(r"href\s*=\s*['\"]tel:([^'\"]+)['\"]", original, re.I)
    }
    linked_phones |= {value[1:] for value in list(linked_phones) if len(value) == 11 and value.startswith("1")}
    for phone in channels["phones"]:
        digits = re.sub(r"\D", "", phone)
        comparable = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        if comparable in linked_phones or digits in linked_phones:
            continue
        local_digits = comparable[-10:]
        display = f"({local_digits[:3]}) {local_digits[3:6]}-{local_digits[6:]}"
        additions.append(f'<a class="button" href="tel:{escape(phone, quote=True)}">Call {display}</a>')
        result["added"].append({"type": "phone", "value": phone})
    if not additions:
        return result
    parser, _ = _inventory(original)
    target = _contact_container(parser)
    if target is None or target.close_start is None:
        result["status"] = "needs_manual_repair"
        result["missing"] = result["added"][:]
        result["added"] = []
        return result
    action_groups = [
        node for node in target.descendants()
        if node.close_start is not None
        and "contact-actions" in node.attrs.get("class", "").split()
    ]
    if action_groups:
        # Keep repaired channels in the same flex/grid action group as the
        # generated phone and quote buttons. Appending them after the contact
        # layout creates a third grid item aligned to the section's far left.
        destination = min(action_groups, key=lambda node: len(list(node.descendants())))
        block = "\n" + "\n".join(additions) + "\n"
        result["inserted_into"] = "contact-actions"
    else:
        panels = [
            node for node in target.descendants()
            if node.close_start is not None
            and set(node.attrs.get("class", "").split()) & {"contact-panel", "contact-copy"}
        ]
        destination = next(
            (node for node in panels if "contact-panel" in node.attrs.get("class", "").split()),
            panels[0] if panels else target,
        )
        block = (
            '\n<div class="source-contact-channels contact-actions" '
            'style="display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-top:18px">'
            + "\n".join(additions)
            + "</div>\n"
        )
        result["inserted_into"] = (
            "contact-panel" if "contact-panel" in destination.attrs.get("class", "").split()
            else "contact-copy" if "contact-copy" in destination.attrs.get("class", "").split()
            else "contact-section"
        )
    if destination.close_start is None:
        result["status"] = "needs_manual_repair"
        result["missing"] = result["added"][:]
        result["added"] = []
        result["inserted_into"] = ""
        return result
    updated = original[:destination.close_start] + block + original[destination.close_start:]
    if updated != original:
        html_path.write_text(updated, encoding="utf-8")
        result["status"] = "repaired"
    return result


def repair(candidate: Path) -> dict:
    candidate = candidate.resolve()
    html_path = candidate / "files" / "index.html"
    facts_path = candidate / "debug" / "source_facts.json"
    report_path = candidate / "debug" / "contact_form_repair.json"
    result = {
        "status": "not_needed",
        "changed": False,
        "fields_added": [],
        "required_fields_repaired": [],
        "unrepairable_fields": [],
        "contact_channels": {"status": "not_checked", "added": [], "missing": []},
        "reason": "",
    }
    if not html_path.is_file() or not facts_path.is_file():
        result.update(status="unavailable", reason="Generated HTML or source facts are missing.")
    else:
        source_facts = json.loads(facts_path.read_text(encoding="utf-8"))
        expected, source_form = _source_fields(source_facts)
        if not expected:
            result["reason"] = "Source facts contain no unambiguous source contact-form fields."
        else:
            original = html_path.read_text(encoding="utf-8")
            parser, actual = _inventory(original)
            actual_by_key: dict[str, list[tuple[_Node, dict]]] = {}
            for node, field in actual:
                key = normalize_form_field(field)
                if key:
                    actual_by_key.setdefault(key, []).append((node, field))

            expected_by_key = {normalize_form_field(field): field for field in expected}
            required_repairs = []
            replacements = []
            for key, source_field in expected_by_key.items():
                if source_field.get("required") is not True:
                    continue
                candidates = actual_by_key.get(key, [])
                if any(field.get("required") is True for _, field in candidates):
                    continue
                if candidates:
                    node, _ = candidates[0]
                    raw_start = original[node.start:node.start_end]
                    replacement = _add_required(raw_start)
                    if replacement != raw_start:
                        replacements.append((node.start, node.start_end, replacement))
                        required_repairs.append(key)
            for start, end, replacement in sorted(replacements, reverse=True):
                original = original[:start] + replacement + original[end:]
            parser, actual = _inventory(original)
            actual_keys = {normalize_form_field(field) for _, field in actual}
            actual_required = {normalize_form_field(field) for _, field in actual if field.get("required") is True}
            missing = [field for field in expected if normalize_form_field(field) not in actual_keys]
            missing_required = [field for field in expected if field.get("required") is True and normalize_form_field(field) not in actual_required]
            result["required_fields_repaired"] = required_repairs
            result["fields_added"] = []

            if missing or missing_required:
                target = _contact_container(parser)
                if target is None:
                    result.update(status="needs_manual_repair", reason="No contact section or contact form could be identified safely.")
                    if original != html_path.read_text(encoding="utf-8"):
                        html_path.write_text(original, encoding="utf-8")
                        result["changed"] = True
                else:
                    used_ids = {node.attrs.get("id", "") for node in parser.nodes if node.attrs.get("id")}
                    additions = []
                    for field in missing:
                        rendered = _render_field(field, used_ids)
                        if rendered is None:
                            result["unrepairable_fields"].append(normalize_form_field(field))
                        else:
                            additions.append(rendered)
                            result["fields_added"].append(normalize_form_field(field))
                    # If the selected contact section already has a form, add
                    # the controls to that form. Otherwise create one from the
                    # captured source action and method, when available.
                    target_forms = [node for node in target.descendants() if node.tag == "form" and node.close_start is not None]
                    if additions and target_forms:
                        form = target_forms[0]
                        insert_at = form.close_start
                        insertion = "\n" + "\n".join(additions) + "\n"
                    elif additions:
                        insert_at = target.close_start
                        method = str((source_form or {}).get("method", "get")).lower()
                        if method not in {"get", "post"}:
                            method = "get"
                        action = str((source_form or {}).get("action", "")).strip()
                        if action and urlsplit(action).scheme.lower() not in {"", "http", "https"}:
                            action = ""
                        action_attr = f' action="{escape(action, quote=True)}"' if action else ""
                        insertion = (
                            f'\n<form class="source-preserved-contact-form" aria-label="Contact form" method="{method}"{action_attr}>'
                            + "\n" + "\n".join(additions)
                            + '\n<button type="submit">Submit</button>\n</form>\n'
                        )
                    else:
                        insert_at = None
                        insertion = ""
                    if insert_at is not None and insertion:
                        original = original[:insert_at] + insertion + original[insert_at:]
                    if result["unrepairable_fields"]:
                        result.update(status="partial", reason="Some source fields require options or markup not captured by source facts.")
                    else:
                        result["status"] = "repaired" if (result["fields_added"] or required_repairs) else "not_needed"
                        result["reason"] = "Missing source fields were inserted before the normal checks ran." if result["status"] == "repaired" else "All source fields are already present."
                    if original != html_path.read_text(encoding="utf-8"):
                        html_path.write_text(original, encoding="utf-8")
                        result["changed"] = True
            elif result["required_fields_repaired"]:
                html_path.write_text(original, encoding="utf-8")
                result.update(status="repaired", changed=True, reason="Required source fields were marked required before QA.")
            else:
                result["reason"] = "All source fields and required states are already present."
        result["contact_channels"] = _repair_contact_channels(html_path, source_facts)
        if result["contact_channels"].get("missing"):
            result["status"] = "needs_manual_repair"
            result["reason"] = "Verified source contact links could not be inserted safely."
            result["changed"] = result["changed"] or bool(result["fields_added"] or result["required_fields_repaired"])
        elif result["contact_channels"].get("status") == "repaired":
            result["changed"] = True
            if result["status"] in {"not_needed", "repaired"}:
                result["status"] = "repaired"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_folder", type=Path)
    args = parser.parse_args()
    result = repair(args.candidate_folder)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
