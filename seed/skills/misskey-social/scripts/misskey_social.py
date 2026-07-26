#!/usr/bin/env python3
"""Minimal dependency-free Misskey client for a Hermes social agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> None:
    path = Path("/opt/data/.env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


load_env()
BASE_URL = os.environ.get("MISSKEY_URL", "http://misskey:3000").rstrip("/")
TOKEN = os.environ.get("MISSKEY_TOKEN", "")


def normalize_post_text(text: str) -> str:
    """Convert shell/LLM escaped line breaks into actual line breaks."""
    return (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
    )


def call(endpoint: str, payload: dict) -> object:
    if not TOKEN:
        raise RuntimeError("MISSKEY_TOKEN is not configured")
    body = dict(payload)
    body["i"] = TOKEN
    request = urllib.request.Request(
        f"{BASE_URL}/api/{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "hermes-misskey-social/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Misskey API error {exc.code}: {detail[:800]}") from exc


def compact_note(note: dict) -> dict:
    user = note.get("user") or {}
    reply = note.get("reply") or {}
    reply_user = reply.get("user") or {}
    return {
        "id": note.get("id"),
        "createdAt": note.get("createdAt"),
        "user": f"@{user.get('username', '?')}",
        "name": user.get("name"),
        "text": note.get("text"),
        "replyId": note.get("replyId"),
        "replyTo": (
            {
                "id": reply.get("id"),
                "user": f"@{reply_user.get('username', '?')}",
                "name": reply_user.get("name"),
                "text": reply.get("text"),
            }
            if reply
            else None
        ),
        "reactions": note.get("reactions", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    timeline = sub.add_parser("timeline")
    timeline.add_argument("--limit", type=int, default=20, choices=range(1, 41))

    history = sub.add_parser("history")
    history.add_argument("--limit", type=int, default=20, choices=range(1, 41))

    note = sub.add_parser("note")
    note.add_argument("--text", required=True)

    reply = sub.add_parser("reply")
    reply.add_argument("--note-id", required=True)
    reply.add_argument("--text", required=True)

    react = sub.add_parser("react")
    react.add_argument("--note-id", required=True)
    react.add_argument("--reaction", default="👍")

    renote = sub.add_parser("renote")
    renote.add_argument("--note-id", required=True)

    quote = sub.add_parser("quote")
    quote.add_argument("--note-id", required=True)
    quote.add_argument("--text", required=True)

    sub.add_parser("me")
    args = parser.parse_args()

    if args.command == "timeline":
        result = call(
            "notes/timeline",
            {"limit": args.limit, "includeMyRenotes": False, "includeRenotedMyNotes": False},
        )
        output = [compact_note(item) for item in result]
    elif args.command == "history":
        me = call("i", {})
        result = call(
            "users/notes",
            {
                "userId": me["id"],
                "limit": args.limit,
                "withReplies": True,
                "includeMyRenotes": False,
                "withFiles": False,
            },
        )
        output = [compact_note(item) for item in result]
    elif args.command == "note":
        text = normalize_post_text(args.text)
        if not 1 <= len(text) <= 1000:
            raise RuntimeError("Note text must be between 1 and 1000 characters")
        output = call("notes/create", {"text": text, "visibility": "public"})
    elif args.command == "reply":
        text = normalize_post_text(args.text)
        if not 1 <= len(text) <= 1000:
            raise RuntimeError("Reply text must be between 1 and 1000 characters")
        output = call(
            "notes/create",
            {"text": text, "replyId": args.note_id, "visibility": "public"},
        )
    elif args.command == "react":
        output = call(
            "notes/reactions/create",
            {"noteId": args.note_id, "reaction": args.reaction},
        )
    elif args.command == "renote":
        output = call(
            "notes/create",
            {"renoteId": args.note_id, "visibility": "public"},
        )
    elif args.command == "quote":
        text = normalize_post_text(args.text)
        if not 1 <= len(text) <= 1000:
            raise RuntimeError("Quote text must be between 1 and 1000 characters")
        output = call(
            "notes/create",
            {"text": text, "renoteId": args.note_id, "visibility": "public"},
        )
    else:
        output = call("i", {})

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
