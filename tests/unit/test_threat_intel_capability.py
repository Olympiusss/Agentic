"""Unit tests for capabilities/threat_intel.py (Phase 3, Milestone 5)."""

import json

import pytest

from capabilities import threat_intel

REAL_SHAPE_CVE_RECORD = {
    "dataType": "CVE_RECORD",
    "cveMetadata": {"cveId": "CVE-2026-2800", "datePublished": "2026-02-24T13:33:29.312Z"},
    "containers": {
        "cna": {
            "descriptions": [{"lang": "en", "value": "Spoofing issue in the WebAuthn component."}],
        },
        "adp": [
            {
                "metrics": [
                    {"cvssV3_1": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}},
                ]
            }
        ],
    },
}


class FakeMCPClient:
    def __init__(self, responses):
        self._responses = dict(responses)

    def get_connection_status(self):
        return {"sentinelone": True}

    async def call_tool(self, server_name, tool_name, arguments, timeout=30.0):
        entry = self._responses.get(tool_name)
        if entry is None:
            return {"error": True, "content": [{"type": "text", "text": f"no fake response for {tool_name}"}]}
        text = entry if isinstance(entry, str) else json.dumps(entry)
        return {"error": False, "content": [{"type": "text", "text": text}]}


def _patch_client(monkeypatch, fake_client):
    import services.mcp_client as mcp_client_module

    monkeypatch.setattr(mcp_client_module, "get_mcp_client", lambda: fake_client)


def _patch_synthesis(monkeypatch, text):
    async def _fake(prompt, **kwargs):
        return text, None

    monkeypatch.setattr("capabilities.synthesis.synthesize", _fake)


@pytest.mark.unit
class TestExtractCveFacts:
    def test_parses_real_nested_shape(self):
        description, score, severity = threat_intel._extract_cve_facts(REAL_SHAPE_CVE_RECORD)
        assert description == "Spoofing issue in the WebAuthn component."
        assert score == 9.8
        assert severity == "CRITICAL"

    def test_missing_metrics_returns_none_not_exception(self):
        sparse = {"containers": {"cna": {"descriptions": []}, "adp": []}}
        description, score, severity = threat_intel._extract_cve_facts(sparse)
        assert description is None
        assert score is None
        assert severity is None

    def test_completely_empty_dict_does_not_crash(self):
        assert threat_intel._extract_cve_facts({}) == (None, None, None)


@pytest.mark.unit
class TestRunThreatIntel:
    @pytest.mark.asyncio
    async def test_happy_path_composes_cve_lookup_and_traversal(self, monkeypatch):
        cve_hits = {
            "edges": [{"node": {"id": "v1"}}, {"node": {"id": "v2"}}],
            "total_count": 2,
        }
        _patch_client(
            monkeypatch,
            FakeMCPClient({"cve_search_by_id": REAL_SHAPE_CVE_RECORD, "search_vulnerabilities": cve_hits}),
        )
        _patch_synthesis(monkeypatch, "EVIDENCE:\n...\n\nASSESSMENT:\nReputation/severity: CRITICAL, CVSS 9.8")

        outcome = await threat_intel.run_threat_intel("CVE-2026-2800")

        assert outcome.kind == "answered"
        assert any("CVSS base score: 9.8" in e for e in outcome.evidence)
        assert "CRITICAL" in outcome.assessment

    @pytest.mark.asyncio
    async def test_cve_search_failure_is_execution_error(self, monkeypatch):
        _patch_client(monkeypatch, FakeMCPClient({}))
        outcome = await threat_intel.run_threat_intel("CVE-2026-9999")
        assert outcome.kind == "execution_error"
