"""Unit tests for services.llm_worker.

Covers ``_adapt_router_result_to_raw`` — its ``stop_reason`` must reflect
whether the router returned tool_calls, otherwise AgentRunner's tool-use
loop drops every tool invocation from router-dispatched providers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from services.llm_worker import (
    _MAX_TRIES,
    _adapt_router_result_to_raw,
    _backoff_seconds,
    _is_transient_llm_error,
)

pytestmark = pytest.mark.unit


class _FakeStatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"status {status_code}")


class TestIsTransientLlmError:
    def test_429_is_transient(self):
        assert _is_transient_llm_error(_FakeStatusError(429)) is True

    def test_5xx_is_transient(self):
        assert _is_transient_llm_error(_FakeStatusError(500)) is True
        assert _is_transient_llm_error(_FakeStatusError(503)) is True

    def test_4xx_other_than_429_is_not_transient(self):
        assert _is_transient_llm_error(_FakeStatusError(400)) is False
        assert _is_transient_llm_error(_FakeStatusError(401)) is False
        assert _is_transient_llm_error(_FakeStatusError(404)) is False

    def test_rate_limit_class_name_is_transient_without_status_code(self):
        class RateLimitError(Exception):
            pass

        assert _is_transient_llm_error(RateLimitError("too fast")) is True

    def test_timeout_and_connection_class_names_are_transient(self):
        class APITimeoutError(Exception):
            pass

        class APIConnectionError(Exception):
            pass

        assert _is_transient_llm_error(APITimeoutError("slow")) is True
        assert _is_transient_llm_error(APIConnectionError("no route")) is True

    def test_bad_request_and_auth_class_names_are_not_transient(self):
        class BadRequestError(Exception):
            pass

        class AuthenticationError(Exception):
            pass

        assert _is_transient_llm_error(BadRequestError("bad")) is False
        assert _is_transient_llm_error(AuthenticationError("nope")) is False

    def test_unrecognized_error_defaults_to_not_transient(self):
        # Explicit design requirement: an unknown error type must NOT
        # retry indefinitely burning cost -- default to surfacing it via
        # the dead-letter path instead.
        assert _is_transient_llm_error(ValueError("something else")) is False


class TestBackoffSeconds:
    def test_exponential_growth(self):
        assert _backoff_seconds(1) == 2.0
        assert _backoff_seconds(2) == 4.0
        assert _backoff_seconds(3) == 8.0

    def test_capped_at_max(self):
        assert _backoff_seconds(10) == 30.0

    def test_max_tries_worth_of_delays_never_exceed_cap(self):
        for attempt in range(1, _MAX_TRIES + 1):
            assert _backoff_seconds(attempt) <= 30.0


def test_adapt_router_result_emits_tool_use_stop_reason_when_tool_calls_present():
    router_result = {
        "content": "I'll list findings now.",
        "tool_calls": [
            {"id": "tool_1", "name": "list_findings", "input": {"limit": 5}}
        ],
        "input_tokens": 100,
        "output_tokens": 20,
        "provider": "anthropic",
        "path": "anthropic-direct",
    }

    adapted = _adapt_router_result_to_raw(router_result)

    assert adapted["stop_reason"] == "tool_use"
    tool_blocks = [b for b in adapted["content"] if b["type"] == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0]["name"] == "list_findings"
    assert tool_blocks[0]["input"] == {"limit": 5}


def test_adapt_router_result_emits_end_turn_when_no_tool_calls():
    router_result = {
        "content": "Investigation complete.",
        "tool_calls": None,
        "input_tokens": 50,
        "output_tokens": 10,
    }

    adapted = _adapt_router_result_to_raw(router_result)

    assert adapted["stop_reason"] == "end_turn"
    assert all(b["type"] != "tool_use" for b in adapted["content"])


def test_adapt_router_result_emits_end_turn_when_tool_calls_empty_list():
    router_result = {
        "content": "Nothing to do.",
        "tool_calls": [],
        "input_tokens": 5,
        "output_tokens": 5,
    }

    adapted = _adapt_router_result_to_raw(router_result)

    assert adapted["stop_reason"] == "end_turn"


def test_adapt_router_result_preserves_thinking_block():
    router_result = {
        "content": "Result text.",
        "thinking": "Reasoning content here.",
        "tool_calls": [],
        "input_tokens": 1,
        "output_tokens": 1,
    }

    adapted = _adapt_router_result_to_raw(router_result)

    thinking_blocks = [b for b in adapted["content"] if b["type"] == "thinking"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0]["thinking"] == "Reasoning content here."


def test_adapt_router_result_normalizes_missing_tool_input():
    router_result = {
        "content": "",
        "tool_calls": [{"id": "t1", "name": "do_thing", "input": None}],
    }

    adapted = _adapt_router_result_to_raw(router_result)

    tool_blocks = [b for b in adapted["content"] if b["type"] == "tool_use"]
    assert tool_blocks[0]["input"] == {}
    assert adapted["stop_reason"] == "tool_use"
