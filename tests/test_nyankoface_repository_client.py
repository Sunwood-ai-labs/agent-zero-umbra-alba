from __future__ import annotations

import base64
import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT = PROJECT_ROOT / "seed" / "skills" / "nyankoface-commons" / "scripts" / "nyankoface.py"


def load_client():
    spec = importlib.util.spec_from_file_location("nyankoface_client_test", CLIENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_uses_create_then_update_methods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    body = tmp_path / "SKILL.md"
    body.write_text("---\nname: river-signals\n---\n\n# River signals\n", encoding="utf-8")
    calls: list[tuple[str, str, object | None, bool]] = []

    def fake_request(path: str, *, method: str = "GET", payload: object | None = None, authenticated: bool = False):
        calls.append((path, method, payload, authenticated))
        if method == "GET":
            raise RuntimeError("Forgejo content operation failed: NyankoFace HTTP 404: missing")
        return {"commit": {"sha": "abc123"}}

    monkeypatch.setattr(client, "forgejo_request", fake_request)
    args = Namespace(
        owner="black-hermes",
        repo="river-signals",
        path="SKILL.md",
        body_file=str(body),
        message="Publish Skill",
        branch="main",
    )
    client.forgejo_publish_file(args)
    assert calls[0][1] == "GET"
    assert calls[1][1] == "POST"
    assert calls[1][3] is True
    assert json.loads(capsys.readouterr().out)["published"] is True

    calls.clear()

    def existing_request(path: str, *, method: str = "GET", payload: object | None = None, authenticated: bool = False):
        calls.append((path, method, payload, authenticated))
        if method == "GET":
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(body.read_text(encoding="utf-8").encode("utf-8")).decode("ascii"),
                "sha": "file-sha",
            }
        raise AssertionError("unchanged content should be idempotent")

    monkeypatch.setattr(client, "forgejo_request", existing_request)
    client.forgejo_publish_file(args)
    assert calls == [("api/v1/repos/black-hermes/river-signals/contents/SKILL.md?ref=main", "GET", None, False)]
    assert json.loads(capsys.readouterr().out)["unchanged"] is True


def test_publish_rejects_real_credential_shape(tmp_path: Path) -> None:
    client = load_client()
    body = tmp_path / "bad.md"
    body.write_text("api_key: ghp_" + "a" * 36, encoding="utf-8")
    args = Namespace(
        owner="black-hermes",
        repo="river-signals",
        path="README.md",
        body_file=str(body),
        message="bad",
        branch="main",
    )
    with pytest.raises(RuntimeError, match="credential"):
        client.forgejo_publish_file(args)


def test_raw_file_read_decodes_utf8(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    encoded = base64.b64encode("# Hello NyankoFace\n".encode("utf-8")).decode("ascii")
    monkeypatch.setattr(
        client,
        "forgejo_request",
        lambda path, **kwargs: {"type": "file", "encoding": "base64", "content": encoded},
    )
    client.forgejo_file(Namespace(owner="nyankoface", repo="knowledge", path="articles/hello.md", ref=None, raw=True))
    assert capsys.readouterr().out == "# Hello NyankoFace\n"
