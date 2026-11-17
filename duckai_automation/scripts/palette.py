"""Apply and validate the fixed color palette assigned to a design slot."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PALETTES = {
    1: {
        "name": "charcoal-ivory-rust",
        "ink": "#292521",
        "ink-soft": "#665e55",
        "paper": "#f6f1e9",
        "surface": "#fffdfa",
        "accent": "#a34e34",
        "accent-dark": "#713923",
        "accent-soft": "#e6c1ad",
        "accent-warm": "#96502f",
        "line": "#ddd1c4",
    },
    2: {
        "name": "forest-sage-brass",
        "ink": "#202b29",
        "ink-soft": "#52615c",
        "paper": "#f4f6f1",
        "surface": "#ffffff",
        "accent": "#285144",
        "accent-dark": "#1a352d",
        "accent-soft": "#adc0a7",
        "accent-warm": "#795f25",
        "line": "#d3ddd4",
    },
    3: {
        "name": "navy-coolgray-copper",
        "ink": "#202b38",
        "ink-soft": "#526272",
        "paper": "#f2f5f8",
        "surface": "#ffffff",
        "accent": "#285678",
        "accent-dark": "#183a55",
        "accent-soft": "#b8cad8",
        "accent-warm": "#91442e",
        "line": "#d0dae3",
    },
}

TOKEN_NAMES = (
    "ink", "ink-soft", "paper", "surface", "accent", "accent-dark",
    "accent-soft", "accent-warm", "line",
)

# Normalize common template-specific names to the same palette tokens so each
# HTML5 UP anchor receives the assigned colors without rewriting its layout.
TOKEN_ALIASES = {
    "text": "ink",
    "foreground": "ink",
    "color-text": "ink",
    "muted": "ink-soft",
    "text-muted": "ink-soft",
    "color-muted": "ink-soft",
    "background": "paper",
    "bg": "paper",
    "color-background": "paper",
    "cream": "surface",
    "color-surface": "surface",
    "olive": "accent",
    "forest": "accent",
    "brand": "accent",
    "primary": "accent",
    "primary-color": "accent",
    "color-primary": "accent",
    "color-accent": "accent",
    "olive-dark": "accent-dark",
    "forest-dark": "accent-dark",
    "brand-dark": "accent-dark",
    "primary-dark": "accent-dark",
    "color-primary-dark": "accent-dark",
    "sage": "accent-soft",
    "sand": "accent-soft",
    "tint": "accent-soft",
    "copper": "accent-warm",
    "rust": "accent-warm",
    "brass": "accent-warm",
    "border": "line",
    "color-border": "line",
}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return round((light + 0.05) / (dark + 0.05), 2)


def _normalize_token_names(css: str) -> str:
    aliases = {**TOKEN_ALIASES, **{f"color-{name}": name for name in TOKEN_NAMES}}
    for alias in sorted(aliases, key=len, reverse=True):
        css = re.sub(
            rf"--{re.escape(alias)}(?![\w-])",
            f"--{aliases[alias]}",
            css,
            flags=re.IGNORECASE,
        )
    return css


def _write_root_tokens(css: str, palette: dict[str, str]) -> str:
    declarations = "\n".join(f"  --{name}: {palette[name]};" for name in TOKEN_NAMES)
    root_pattern = re.compile(r"(:root\s*\{)([^{}]*)(\})", re.IGNORECASE)
    match = root_pattern.search(css)
    if not match:
        return f":root {{\n{declarations}\n}}\n\n{css}"

    body = match.group(2)
    for name in TOKEN_NAMES:
        body = re.sub(rf"--{re.escape(name)}\s*:\s*[^;{{}}]+;?", "", body, flags=re.IGNORECASE)
    body = body.rstrip()
    replacement = f"{match.group(1)}{body}\n{declarations}\n{match.group(3)}"
    return css[:match.start()] + replacement + css[match.end():]


def apply_palette(css: str, slot: int) -> tuple[str, dict]:
    if isinstance(slot, bool) or slot not in PALETTES:
        raise ValueError("palette slot must be 1, 2, or 3")
    palette = PALETTES[slot]
    normalized_css = _normalize_token_names(css)
    normalized_css = _write_root_tokens(normalized_css, palette)

    token_values = {
        name: bool(re.search(rf"--{re.escape(name)}\s*:\s*{re.escape(palette[name])}\s*;", normalized_css, re.IGNORECASE))
        for name in TOKEN_NAMES
    }
    usage_css = re.sub(r"/\*[\s\S]*?\*/", " ", normalized_css)
    usage = {
        name: len(re.findall(rf"var\(\s*--{re.escape(name)}\s*(?:,|\))", usage_css, re.IGNORECASE))
        for name in ("ink", "paper", "accent")
    }
    contrast = {
        "ink_on_paper": contrast_ratio(palette["ink"], palette["paper"]),
        "ink_on_soft_accent": contrast_ratio(palette["ink"], palette["accent-soft"]),
        "muted_on_paper": contrast_ratio(palette["ink-soft"], palette["paper"]),
        "white_on_accent": contrast_ratio("#ffffff", palette["accent"]),
        "white_on_accent_dark": contrast_ratio("#ffffff", palette["accent-dark"]),
        "white_on_warm_accent": contrast_ratio("#ffffff", palette["accent-warm"]),
    }
    contrast_passed = all(value >= 4.5 for value in contrast.values())
    report = {
        "status": "passed" if all(token_values.values()) and all(count > 0 for count in usage.values()) and contrast_passed else "failed",
        "slot": slot,
        "palette": palette["name"],
        "tokens": {name: palette[name] for name in TOKEN_NAMES},
        "token_values_match": all(token_values.values()),
        "token_values": token_values,
        "required_token_usage": usage,
        "required_tokens_used": all(count > 0 for count in usage.values()),
        "contrast_ratio": contrast,
        "minimum_text_contrast": 4.5,
        "contrast_passed": contrast_passed,
        "repairs": ["normalized recognized template color variables", "set the assigned root palette tokens"],
    }
    return normalized_css, report


def repair_candidate(candidate: Path) -> dict:
    candidate = candidate.resolve()
    css_path = candidate / "files" / "styles.css"
    reference_path = candidate / "debug" / "design_reference.json"
    report_path = candidate / "debug" / "palette.json"
    if not css_path.is_file():
        raise RuntimeError("candidate CSS is missing")
    if not reference_path.is_file():
        report = {"status": "skipped", "reason": "design reference slot is unavailable"}
    else:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        if reference.get("status") != "selected":
            report = {"status": "skipped", "reason": "no verified design anchor was selected"}
        else:
            slot = reference.get("template_slot")
            if isinstance(slot, bool) or slot not in PALETTES:
                raise RuntimeError("candidate has an invalid design reference slot")
            css, report = apply_palette(css_path.read_text(encoding="utf-8"), slot)
            css_path.write_text(css, encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_folder", type=Path)
    args = parser.parse_args()
    repair_candidate(args.candidate_folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
