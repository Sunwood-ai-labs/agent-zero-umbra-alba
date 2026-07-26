#!/usr/bin/env python3
"""Render Misskey configuration without exposing secrets in Compose output."""

import os
from pathlib import Path


source = Path("/template/default.yml").read_text(encoding="utf-8")
replacements = {
    "__MISSKEY_URL__": os.environ["MISSKEY_URL"].rstrip("/"),
    "__POSTGRES_DB__": os.environ["POSTGRES_DB"],
    "__POSTGRES_USER__": os.environ["POSTGRES_USER"],
    "__POSTGRES_PASSWORD__": os.environ["POSTGRES_PASSWORD"],
    "__MISSKEY_SETUP_PASSWORD__": os.environ["MISSKEY_SETUP_PASSWORD"],
}
for marker, value in replacements.items():
    if "\n" in value or "\r" in value:
        raise ValueError(f"Invalid newline in value for {marker}")
    source = source.replace(marker, value)

destination = Path("/runtime/misskey-config/default.yml")
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(source, encoding="utf-8")
print("Rendered Misskey configuration.")
