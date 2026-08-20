"""Unit tests for capabilities/reporter.py (Phase 3, Milestone 6)."""

import pytest

from capabilities import reporter


@pytest.mark.unit
class TestAssembleReport:
    def test_drops_empty_sections(self):
        outcome = reporter.assemble_report(
            "Case Report", [("Triage", "Verdict: true positive"), ("Investigator", ""), ("Correlator", None)]
        )
        assert outcome.kind == "answered"
        assert len(outcome.sections) == 1
        assert outcome.sections[0][0] == "Triage"

    def test_no_sections_is_execution_error(self):
        outcome = reporter.assemble_report("Empty Report", [("Triage", "")])
        assert outcome.kind == "execution_error"

    def test_preserves_grounding_line_verbatim(self):
        text = "Alert xyz.\n\nSource: SentinelOne Alerts · Client: CyberVergent Ltd"
        outcome = reporter.assemble_report("Report", [("Triage", text)])
        assert outcome.sections[0][1] == text  # byte-for-byte, not paraphrased


@pytest.mark.unit
class TestExportReport:
    @pytest.mark.asyncio
    async def test_export_report_assembles_then_exports(self, tmp_path, monkeypatch):
        from capabilities import session_export

        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = await reporter.export_report("Case Report", [("Triage", "Verdict: true positive")], "markdown")
        assert result.kind == "answered"
        assert "true positive" in result.output_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_export_report_refuses_empty_input_before_touching_disk(self, tmp_path, monkeypatch):
        from capabilities import session_export

        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = await reporter.export_report("Empty", [("Triage", "")], "markdown")
        assert result.kind == "execution_error"
        assert list(tmp_path.iterdir()) == []
