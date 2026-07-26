#!/usr/bin/env python3
"""Verify internal Hermes APIs and Misskey skill distribution without leaking keys."""

import json
import os
import urllib.request


key = os.environ["HERMES_API_SERVER_KEY"]
for index in range(1, 11):
    agent = f"agent{index:02d}"
    with urllib.request.urlopen(f"http://{agent}:8642/health", timeout=10) as response:
        health = json.loads(response.read())
    if health.get("status") != "ok":
        raise RuntimeError(f"{agent} health failed: {health}")

    request = urllib.request.Request(
        f"http://{agent}:8642/v1/skills",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read())
    skills = payload.get("data", []) if isinstance(payload, dict) else payload
    names = {skill.get("name") for skill in skills}
    if "misskey-social" not in names:
        raise RuntimeError(f"{agent} does not expose misskey-social")

print("Verified 10 authenticated Hermes APIs and misskey-social on every agent.")
