from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT = PROJECT_ROOT / "seed" / "skills" / "nyankoface-commons" / "scripts" / "nyankoface.py"


def load_client():
    spec = importlib.util.spec_from_file_location("nyankoface_mcp_client_test", CLIENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_reports_dedicated_mcp_file_without_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    token = "mcp-secret-that-must-not-be-printed"
    token_file = tmp_path / "nyankoface-mcp-token"
    token_file.write_text(token + "\n", encoding="utf-8")
    client.MCP_TOKEN_FILE = str(token_file)
    client.MCP_URL = "https://nyankoface.example/mcp"

    client.source(Namespace())

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["mcp_client_token_configured"] is True
    assert payload["mcp_token_file"] == str(token_file)
    assert token not in output


def test_mcp_check_runs_initialize_and_read_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    token = "mcp-secret-that-must-not-be-printed"
    token_file = tmp_path / "nyankoface-mcp-token"
    token_file.write_text(token + "\n", encoding="utf-8")
    client.MCP_TOKEN_FILE = str(token_file)
    client.MCP_URL = "https://nyankoface.example/mcp"
    calls: list[tuple[str, str, int | None]] = []

    def fake_request(supplied: str, method: str, *, request_id: int | None = None, params=None):
        assert supplied == token
        calls.append((supplied, method, request_id))
        if method == "initialize":
            return 200, "text/event-stream", {"result": {"protocolVersion": "2025-06-18"}}
        if method == "notifications/initialized":
            return 202, "", {}
        if method == "tools/list":
            return 200, "text/event-stream", {"result": {"tools": [{"name": "search_catalog"}]}}
        if method == "resources/list":
            return 200, "text/event-stream", {"result": {"resources": [{"name": "OpenAPI"}]}}
        raise AssertionError(method)

    monkeypatch.setattr(client, "mcp_request", fake_request)
    client.mcp_check(Namespace())

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["initialize"]["status"] == 200
    assert payload["tools_list"]["count"] == 1
    assert payload["resources_list"]["count"] == 1
    assert [method for _, method, _ in calls] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "resources/list",
    ]
    assert token not in output


def test_mcp_check_reports_missing_token_without_faking_health(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = load_client()
    client.MCP_TOKEN_FILE = str(tmp_path / "missing-token")
    client.MCP_URL = "https://nyankoface.example/mcp"

    with pytest.raises(SystemExit) as error:
        client.mcp_check(Namespace())

    assert error.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["mcp_client_token_configured"] is False
    assert "fallback" in payload["error"]


def test_compose_loads_mcp_token_from_a_separate_file() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "NYANKOFACE_MCP_TOKEN_FILE: /opt/data/nyankoface-mcp-token" in compose
    assert "NYANKOFACE_MCP_TOKEN=\"$$(cat" in compose
    assert "Forgejo fallback remains available" in compose
    assert "NYANKOFACE_FORGEJO_TOKEN_FILE" in compose
