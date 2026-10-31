#!/usr/bin/env python3
"""Read a batch or target from the private coordinator repository."""

from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PRIVATE_REPOSITORY = "hometownredesignsites/git-content-private"
API_ROOT = "https://api.github.com"


def read_private_json(path: str) -> dict:
    token = os.environ.get("PRIVATE_REPO_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not configured.")
    encoded_path = quote(path, safe="/")
    request = Request(
        f"{API_ROOT}/repos/{PRIVATE_REPOSITORY}/contents/{encoded_path}?ref=main",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError("Could not read the private queue. Check PRIVATE_REPO_TOKEN and the private queue path.") from None
    try:
        content = base64.b64decode(payload["content"], validate=False).decode("utf-8")
        value = json.loads(content)
    except (KeyError, ValueError, UnicodeDecodeError, TypeError):
        raise RuntimeError("The private queue file is missing or invalid JSON.") from None
    if not isinstance(value, dict):
        raise RuntimeError("The private queue file must contain a JSON object.")
    return value
