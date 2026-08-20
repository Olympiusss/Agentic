# Regression fixture: Reporter capability + session export (Milestone 6)

Encodes Milestone 6's acceptance bar: *"Reporter assembles a grounded
report, and a session exports faithfully in all four formats with the
grounding preserved."*

## Case: assembling a report from other capabilities' outputs

- **expected_behavior**: `assemble_report(title, [(name, text), ...])`
  drops any section whose text is empty/None (never renders a blank
  heading), and otherwise passes text through completely verbatim --
  including grounding lines (`Source:`/`Client:`) already present, never
  re-summarized or dropped.

## Case: exporting to all four formats

- **expected_behavior**: `export_session` produces a real file under
  `outputs/reports/` for each of `markdown`, `json`, `pdf`, `docx`. The
  Markdown and JSON outputs contain the exact grounding-line text
  verbatim (byte-for-byte substring match); PDF/DOCX are valid,
  non-empty binary files (verified by opening the PDF at the page level
  and the DOCX via python-docx, not just checking the file exists).

## Pass criteria (`tests/unit/test_reporter_capability.py` +
`tests/unit/test_session_export.py`)

1. `assemble_report` never fabricates a section -- output section count
   never exceeds the number of non-empty inputs given.
2. An unsupported format string is refused with `execution_error`, never
   silently coerced to a different format.
3. Markdown/JSON exports preserve the grounding line text exactly.
4. PDF/DOCX exports are real, openable files (not just non-empty bytes).
