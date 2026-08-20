"""Unit tests for capabilities/session_export.py (Phase 3, Milestone 6)."""

import json

import pytest

from capabilities import session_export

GROUNDING_LINE = "Source: SentinelOne Alerts · Client: CyberVergent Ltd"
SECTIONS = [("Evidence", f"Alert xyz has severity HIGH.\n\n{GROUNDING_LINE}"), ("Assessment", "Verdict: true positive")]


@pytest.mark.unit
class TestExportSession:
    def test_unsupported_format_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", SECTIONS, "yaml")
        assert result.kind == "execution_error"
        assert "unsupported format" in result.error

    def test_no_sections_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", [], "markdown")
        assert result.kind == "execution_error"

    def test_markdown_preserves_grounding_line_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", SECTIONS, "markdown")
        assert result.kind == "answered"
        content = result.output_path.read_text(encoding="utf-8")
        assert GROUNDING_LINE in content

    def test_json_preserves_grounding_line_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", SECTIONS, "json")
        assert result.kind == "answered"
        data = json.loads(result.output_path.read_text(encoding="utf-8"))
        assert any(GROUNDING_LINE in s["body"] for s in data["sections"])

    def test_pdf_is_a_real_openable_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", SECTIONS, "pdf")
        assert result.kind == "answered"
        assert result.output_path.exists()
        assert result.output_path.stat().st_size > 0
        assert result.output_path.read_bytes()[:4] == b"%PDF"

    def test_docx_is_a_real_openable_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(session_export, "REPORTS_DIR", tmp_path)
        result = session_export.export_session("Test Report", SECTIONS, "docx")
        assert result.kind == "answered"

        import docx

        document = docx.Document(str(result.output_path))
        full_text = "\n".join(p.text for p in document.paragraphs)
        assert "Evidence" in full_text
        assert "true positive" in full_text
