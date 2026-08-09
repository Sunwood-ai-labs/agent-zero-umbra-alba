#!/usr/bin/env python3
"""Verify Hermes APIs and the bundled Misskey/NyankoFace skill distribution."""

import json
import os
import time
import urllib.error
import urllib.request


key = os.environ["HERMES_API_SERVER_KEY"]
agents = [
    item.strip()
    for item in os.getenv("AGENTS", "agent01,agent02,agent03,agent04,agent05,agent06,agent07,agent08,agent09,agent10").split(",")
    if item.strip()
]
if not agents:
    raise RuntimeError("AGENTS must contain at least one Hermes service")


def wait_for_health(agent: str, timeout_seconds: int = 90) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{agent}:8642/health", timeout=10) as response:
                health = json.loads(response.read())
            if health.get("status") == "ok":
                return health
            last_error = RuntimeError(f"unexpected health payload: {health}")
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"{agent} health did not become ready: {last_error}")


for agent in agents:
    wait_for_health(agent)

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
    if "nyankoface-commons" not in names:
        raise RuntimeError(f"{agent} does not expose nyankoface-commons")

print(f"Verified {len(agents)} authenticated Hermes APIs with misskey-social and nyankoface-commons on every agent.")
