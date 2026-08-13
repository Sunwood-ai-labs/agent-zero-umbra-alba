"""Offline checks for scheduler quota backoff behavior."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scheduler"))
import random_scheduler as scheduler  # noqa: E402


def test_rate_limit_error_detection() -> None:
    assert scheduler.is_provider_backoff_error("RuntimeError: HTTP 429: quota")
    assert scheduler.is_provider_backoff_error("RateLimitError: provider quota")
    assert scheduler.is_provider_backoff_error("RemoteDisconnected: closed")
    assert not scheduler.is_provider_backoff_error("TimeoutError: timed out")


def test_scheduler_submission_capacity_matches_executor(monkeypatch) -> None:
    monkeypatch.setattr(scheduler, "MAX_CONCURRENT_REQUESTS", 3)
    assert scheduler.has_submission_capacity(0)
    assert scheduler.has_submission_capacity(2)
    assert not scheduler.has_submission_capacity(3)


def test_recover_inflight_state_marks_only_stale_requests(monkeypatch) -> None:
    saved = []
    state = {
        "agents": {
            "running": {"lastStatus": "running", "lastError": None, "nextAt": 2000},
            "ok": {"lastStatus": "ok", "lastError": None, "nextAt": 2000},
        }
    }
    monkeypatch.setattr(scheduler, "save_state", lambda value: saved.append(value))

    scheduler.recover_inflight_state(state)

    assert state["agents"]["running"]["lastStatus"] == "interrupted"
    assert state["agents"]["running"]["nextAt"] == 2000
    assert state["agents"]["ok"]["lastStatus"] == "ok"
    assert len(saved) == 1



def test_provider_cooldown_staggers_pending_agents(monkeypatch) -> None:
    state = {
        "agents": {
            "a": {"nextAt": 0, "nextAtIso": None},
            "b": {"nextAt": 0, "nextAtIso": None},
        },
        "providerCooldownUntil": 0,
    }
    monkeypatch.setattr(scheduler, "RATE_LIMIT_BACKOFF_SECONDS", 60)
    monkeypatch.setattr(scheduler, "RATE_LIMIT_STAGGER_SECONDS", 10)
    monkeypatch.setattr(scheduler.random, "randint", lambda _low, _high: 5)

    until = scheduler.apply_provider_cooldown(state, now=1000)

    assert until == 1060
    assert state["providerCooldownUntilIso"] == scheduler.iso(1060)
    assert state["agents"]["a"]["nextAt"] == 1065
    assert state["agents"]["b"]["nextAt"] == 1065


def test_prompt_requires_evidence_backed_agent_cycle() -> None:
    assert "当事者サイクル" in scheduler.PROMPT
    assert "観察→選択→実行→記録" in scheduler.PROMPT
    assert "結果のないサイクルを自由に消費することではありません" in scheduler.PROMPT
    assert "background=true" in scheduler.PROMPT
    assert "CTFd正規ID契約" in scheduler.PROMPT
    assert "NyankoFaceのowner/repoやctfd-b-s3-* slug" in scheduler.PROMPT
