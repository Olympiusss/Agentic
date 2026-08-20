"""Unit tests for capabilities/triage.py (Phase 3, Milestone 1).

Mocks both the MCP client (FakeMCPClient, same pattern as
test_sentinelone_recipe_executor.py) and the LLM gateway's submit_triage --
proves the capability's own composition/chaining logic and error handling,
without depending on a live tenant or a live Redis/ARQ worker.
"""

import json

import pytest

from capabilities import triage


def _ok(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"error": False, "content": [{"type": "text", "text": text}]}


class FakeMCPClient:
    def __init__(self, responses, connected=True):
        self._responses = dict(responses)
        self.calls = []
        self._connected = connected

    def get_connection_status(self):
        return {"sentinelone": self._connected}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        self.calls.append(tool_name)
        entry = self._responses.get(tool_name)
        if entry is None:
            return {"error": True, "content": [{"type": "text", "text": f"no fake response for {tool_name}"}]}
        value = entry.pop(0) if isinstance(entry, list) else entry
        return _ok(value)


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


class FakeGateway:
    """Mirrors the REAL, live-verified shape of submit_triage's return value
    -- a content-block dict ({'content': ..., 'type': 'text'}), not a bare
    string despite the gateway's Optional[str] type hint. An earlier
    version of this fixture returned a bare string, which accidentally hid
    a real bug (capabilities/triage.py stringified the whole dict instead
    of extracting its 'content') -- always mock the shape actually
    observed, not the documented/assumed one."""

    def __init__(self, response_text):
        self.response_text = response_text
        self.received_prompts = []

    async def submit_triage(self, prompt, **kwargs):
        self.received_prompts.append(prompt)
        return {"content": self.response_text, "type": "text"}


def _patch_gateway(monkeypatch, fake_gateway):
    import services.llm_gateway as llm_gateway_module

    async def _get():
        return fake_gateway

    monkeypatch.setattr(llm_gateway_module, "get_llm_gateway", _get)


_FAKE_VERDICT = """EVIDENCE:
Alert abc: severity=CRITICAL, status=RESOLVED.

ASSESSMENT:
Verdict: true positive
Severity confirmation: CRITICAL, consistent with the evidence
Blast radius: 3 alerts in the storyline
Confidence: 85
Reasoning: analyst already confirmed true positive and mitigation succeeded."""


ALERT_ID = "019fc64e-b780-7c21-8573-9bcf7ad7fb81"
STORYLINE_ID = "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"


@pytest.mark.unit
class TestTriageHappyPath:
    @pytest.mark.asyncio
    async def test_composes_threat_detail_and_storyline_pivot_when_storyline_present(self, monkeypatch):
        alert_detail = {
            "id": ALERT_ID,
            "severity": "CRITICAL",
            "status": "RESOLVED",
            "analystVerdict": "TRUE_POSITIVE_UNDEFINED",
            "classification": "MALWARE",
            "storylineId": STORYLINE_ID,
            "asset": {"name": "host-1"},
        }
        history = {"edges": [], "totalCount": 0}
        storyline_alerts = {"edges": [{"node": {"id": "a1"}}, {"node": {"id": "a2"}}, {"node": {"id": "a3"}}]}

        fake_client = FakeMCPClient(
            {"get_alert": alert_detail, "get_alert_history": history, "search_alerts": storyline_alerts}
        )
        _patch_client(monkeypatch, fake_client)
        fake_gateway = FakeGateway(_FAKE_VERDICT)
        _patch_gateway(monkeypatch, fake_gateway)

        outcome = await triage.run_triage(ALERT_ID)

        assert outcome.kind == "answered"
        assert "search_alerts" in fake_client.calls  # storyline_pivot's tool
        assert len(outcome.evidence) == 2  # threat_detail + storyline_pivot
        assert "Verdict: true positive" in outcome.assessment
        assert len(fake_gateway.received_prompts) == 1
        # The synthesis prompt must contain the real retrieved evidence, not
        # a fabricated summary.
        assert "CRITICAL" in fake_gateway.received_prompts[0]

    @pytest.mark.asyncio
    async def test_no_storyline_skips_storyline_pivot(self, monkeypatch):
        alert_detail = {
            "id": ALERT_ID,
            "severity": "LOW",
            "status": "NEW",
            "analystVerdict": "UNDEFINED",
            "classification": "MANUAL",
            "storylineId": None,
        }
        fake_client = FakeMCPClient({"get_alert": alert_detail, "get_alert_history": {"edges": []}})
        _patch_client(monkeypatch, fake_client)
        _patch_gateway(monkeypatch, FakeGateway(_FAKE_VERDICT))

        outcome = await triage.run_triage(ALERT_ID)

        assert outcome.kind == "answered"
        assert "search_alerts" not in fake_client.calls  # storyline_pivot never invoked
        assert len(outcome.evidence) == 1


@pytest.mark.unit
class TestTriageErrorHandling:
    @pytest.mark.asyncio
    async def test_threat_detail_execution_error_short_circuits_before_llm_call(self, monkeypatch):
        fake_client = FakeMCPClient({})  # every tool call errors ("no fake response")
        _patch_client(monkeypatch, fake_client)
        fake_gateway = FakeGateway(_FAKE_VERDICT)
        _patch_gateway(monkeypatch, fake_gateway)

        outcome = await triage.run_triage(ALERT_ID)

        assert outcome.kind == "execution_error"
        assert fake_gateway.received_prompts == []  # never reached the LLM call

    @pytest.mark.asyncio
    async def test_llm_call_failure_is_caught_not_raised(self, monkeypatch):
        alert_detail = {"id": ALERT_ID, "severity": "HIGH", "status": "NEW"}
        _patch_client(monkeypatch, FakeMCPClient({"get_alert": alert_detail, "get_alert_history": {"edges": []}}))

        class RaisingGateway:
            async def submit_triage(self, prompt, **kwargs):
                raise RuntimeError("worker unreachable")

        import services.llm_gateway as llm_gateway_module

        async def _get():
            return RaisingGateway()

        monkeypatch.setattr(llm_gateway_module, "get_llm_gateway", _get)

        outcome = await triage.run_triage(ALERT_ID)
        assert outcome.kind == "execution_error"
        assert "synthesis call failed" in outcome.error
