#!/usr/bin/env python3
"""Load one private CSV row into GitHub Actions environment variables."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from private_queue_api import read_private_json


ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def write_env(handle, name: str, value: str) -> None:
    delimiter = f"GIT_CONTENT_{uuid.uuid4().hex}"
    while delimiter in value:
        delimiter = f"GIT_CONTENT_{uuid.uuid4().hex}"
    handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> None:
    batch_id = os.environ.get("BATCH_ID", "")
    site_id = os.environ.get("SITE_ID", "")
    if not ID_PATTERN.fullmatch(batch_id) or not ID_PATTERN.fullmatch(site_id):
        raise RuntimeError("The private queue target ID is invalid.")
    target = read_private_json(
        f"private_automation/queue/batches/{batch_id}/targets/{site_id}.json"
    )
    required = {"website", "business", "category"}
    if not required.issubset(target):
        raise RuntimeError("The private target is missing a required CSV field.")
    for key in required:
        value = target.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("The private target contains an empty required CSV field.")
    website = target["website"].strip()
    business = target["business"].strip()
    category = target["category"].strip()
    location = str(target.get("location", "")).strip()
    parsed = urlparse(website)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or any(char.isspace() for char in website):
        raise RuntimeError("The private target has an invalid website URL.")
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        raise RuntimeError("GITHUB_ENV is not available.")
    with Path(env_path).open("a", encoding="utf-8") as handle:
        write_env(handle, "BATCH_ID", batch_id)
        write_env(handle, "PRIVATE_SITE_ID", site_id)
        write_env(handle, "SOURCE_URL", website)
        write_env(handle, "BUSINESS_NAME", business)
        write_env(handle, "INDUSTRY_CATEGORY", category)
        write_env(handle, "LOCATION", location)
    print("Loaded one private target into the runner environment.")


if __name__ == "__main__":
    main()
