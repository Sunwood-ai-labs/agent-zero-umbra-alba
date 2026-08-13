from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT = PROJECT_ROOT / "seed" / "skills" / "nyankoface-commons" / "scripts" / "nyankoface.py"


def load_client():
    spec = importlib.util.spec_from_file_location("nyankoface_preflight_test", CLIENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_write_environment(client, tmp_path: Path) -> None:
    token_file = tmp_path / "forgejo-token"
    token_file.write_text("forgejo-secret-value\n", encoding="utf-8")
    agent_key_file = tmp_path / "agent-key"
    agent_key_file.write_text("of_agent_secret-value\n", encoding="utf-8")
    client.BASE_URL = "https://madesk.tail8be30.ts.net"
    client.FORGEJO_URL = "https://madesk.tail8be30.ts.net/git"
    client.MCP_URL = "https://madesk.tail8be30.ts.net/mcp"
    client.FORGEJO_TOKEN = ""
    client.FORGEJO_TOKEN_FILE = str(token_file)
    client.FORGEJO_USER = "black-hermes"
    client.AGENT_KEY = ""
    client.AGENT_KEY_FILE = str(agent_key_file)
    client.AGENT_SLUG = "black-hermes"


def test_write_preflight_accepts_canonical_paths_without_printing_secrets(tmp_path: Path) -> None:
    client = load_client()
    configure_write_environment(client, tmp_path)

    summary = client._runtime_preflight("write")

    assert summary["ok"] is True
    serialized = json.dumps(summary, ensure_ascii=False)
    assert "forgejo-secret-value" not in serialized
    assert "of_agent_secret-value" not in serialized
    assert summary["canonical_commands"]["client"].endswith("nyankoface.py")


def test_preflight_rejects_documentation_or_repository_paths(tmp_path: Path) -> None:
    client = load_client()
    configure_write_environment(client, tmp_path)
    client.FORGEJO_URL = "https://192.168.11.22:8443/git/api/swagger"

    summary = client._runtime_preflight("write")

    assert summary["ok"] is False
    assert any("NYANKOFACE_FORGEJO_URL" in error for error in summary["errors"])
    assert any("/api/swagger" in error for error in summary["errors"])


def test_preflight_command_exits_nonzero_when_write_identity_is_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    client.BASE_URL = "https://madesk.tail8be30.ts.net"
    client.FORGEJO_URL = "https://madesk.tail8be30.ts.net/git"
    client.MCP_URL = "https://madesk.tail8be30.ts.net/mcp"
    client.FORGEJO_USER = ""
    client.FORGEJO_TOKEN = ""
    client.FORGEJO_TOKEN_FILE = str(tmp_path / "missing-token")
    client.AGENT_SLUG = "black-hermes"

    with pytest.raises(SystemExit) as error:
        client.preflight(type("Args", (), {"mode": "write"})())

    assert error.value.code == 2
    output = capsys.readouterr().out
    assert "Forgejo content token is missing" in output
    assert "NYANKOFACE_FORGEJO_USER is required" in output
