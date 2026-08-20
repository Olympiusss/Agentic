"""Tests for the deterministic (non-LLM) parts of capabilities/synergy.py's
alert-notification rewrite (explicit user request, 2026-08-18: client-aware
Phase 1 notification + templated Phase 2 investigative report).

Covers only what's pure/deterministic per the approved implementation plan:
- _map_hash_reputation / _map_digital_signature (verdict/raw-string -> the
  user's exact template enum values)
- services.sentinelone_dashboard_service.get_site_for_endpoint (in-memory
  dict lookup, no I/O)

Narrative synthesis (LLM-backed) and the live SentinelOne/AlienVault/Shodan
calls are explicitly out of scope for unit tests -- covered by live probes
during implementation instead, per this project's established discipline
for LLM-backed and third-party-API paths.
"""

from capabilities.notifier import NotifyResult
from capabilities.synergy import (
    _any_channel_sent,
    _map_digital_signature,
    _map_hash_reputation,
    _parse_narrative_sections,
    _short_activity_label,
)


class TestMapHashReputation:
    def test_clean_maps_to_known(self):
        assert _map_hash_reputation("clean") == "Known"

    def test_suspicious_maps_to_unknown(self):
        assert _map_hash_reputation("suspicious") == "Unknown"

    def test_malicious_maps_to_malicious(self):
        assert _map_hash_reputation("malicious") == "Malicious"

    def test_unconfigured_and_missing_verdicts_default_to_unknown(self):
        for verdict in ("not_configured", "not_found", "execution_error", "unknown", None, ""):
            assert _map_hash_reputation(verdict) == "Unknown"


class TestMapDigitalSignature:
    def test_none_or_empty_is_not_available(self):
        assert _map_digital_signature(None) == "not available"
        assert _map_digital_signature("") == "not available"

    def test_signed_variants_map_to_signed_valid(self):
        for raw in ("signed", "Signed", "Signed and Verified", "valid", "trusted", "verified"):
            assert _map_digital_signature(raw) == "SIGNED_VALID"

    def test_invalid_variants_map_to_signed_invalid(self):
        for raw in ("invalid", "expired", "revoked", "untrusted"):
            assert _map_digital_signature(raw) == "SIGNED_INVALID"

    def test_unsigned_variants_map_to_unsigned(self):
        for raw in ("unsigned", "not signed", "none", "None"):
            assert _map_digital_signature(raw) == "UNSIGNED"

    def test_unrecognized_raw_value_is_returned_as_is_not_guessed(self):
        assert _map_digital_signature("some_unmapped_future_value") == "some_unmapped_future_value"


class TestShortActivityLabel:
    def test_uses_title_when_present(self):
        assert _short_activity_label("Ransomware activity", "a long description", "host-1") == "Ransomware activity"

    def test_falls_back_to_first_sentence_of_description_when_no_title(self):
        # Real bug found via a live end-to-end run 2026-08-18: a null title
        # previously fell through to the FULL raw description (often
        # several sentences) getting embedded in the subject/greeting.
        description = "Detects modifications to package manager configs. Adversaries may modify these files."
        assert _short_activity_label(None, description, "host-1") == "Detects modifications to package manager configs"

    def test_truncates_long_first_sentence_without_cutting_mid_word(self):
        description = "This is a very long single sentence with no period anywhere near the end of it at all so it must be truncated safely without a period"
        label = _short_activity_label(None, description, "host-1")
        assert label.endswith("...")
        assert len(label) <= 104  # 100-char cap + "..."
        assert not label[:-3].endswith(" ")  # no dangling space before the ellipsis

    def test_falls_back_to_generic_label_when_neither_title_nor_description(self):
        assert _short_activity_label(None, None, "host-1") == "Detection on host-1"
        assert _short_activity_label("", "", "host-1") == "Detection on host-1"


class TestParseNarrativeSections:
    def test_clean_plain_markers_parse_correctly(self):
        text = (
            "VERIFICATION:\nThis is a legitimate signed application.\n\n"
            "NOTE:\nDual-use context paragraph here.\n\n"
            "RECOMMENDATIONS:\n* First bullet.\n* Second bullet."
        )
        verification, note, recs = _parse_narrative_sections(text)
        assert verification == "This is a legitimate signed application."
        assert note == "Dual-use context paragraph here."
        assert recs == ["* First bullet.", "* Second bullet."]

    def test_bolded_markers_leave_no_stray_asterisks(self):
        # Reproduces the exact real-world response shape from the
        # 2026-08-18 end-to-end run: the model bolded its own markers
        # ("**NOTE:**" instead of "NOTE:"), which previously leaked a
        # trailing "**" onto the end of the preceding section.
        text = (
            "**VERIFICATION:**\n\nThe process is a legitimate system shell.\n\n"
            "**NOTE:**\n\nConfiguration file changes are high-value targets.\n\n"
            "**RECOMMENDATIONS:**\n* Verify the change was authorized.\n* Review the config file."
        )
        verification, note, recs = _parse_narrative_sections(text)
        assert not verification.endswith("*")
        assert verification == "The process is a legitimate system shell."
        assert not note.endswith("*")
        assert note == "Configuration file changes are high-value targets."
        assert recs == ["* Verify the change was authorized.", "* Review the config file."]

    def test_bogus_trailing_content_after_recommendations_is_excluded(self):
        # Reproduces the exact bug: the model appended a sign-off and a
        # duplicate bold-markdown "Event Details" recap after the real
        # bullets. None of that should end up in recommendation_lines.
        text = (
            "**VERIFICATION:**\n\nVerification text.\n\n"
            "**NOTE:**\n\nNote text.\n\n"
            "**RECOMMENDATIONS:**\n"
            "* Verify the change was authorized.\n"
            "* Review the config file.\n"
            "**Hermes**\n"
            "*Event Details:*\n"
            "**Hostname:** ip-172-31-1-35\n"
            "**Process Name:** dash\n"
        )
        _, _, recs = _parse_narrative_sections(text)
        assert recs == ["* Verify the change was authorized.", "* Review the config file."]
        assert not any("Hermes" in r or "Hostname" in r for r in recs)

    def test_no_recommendation_bullets_falls_back_to_generic_line(self):
        text = "VERIFICATION:\nSomething.\n\nNOTE:\nSomething else.\n\nRECOMMENDATIONS:\nNo bullets here, just prose."
        _, _, recs = _parse_narrative_sections(text)
        assert recs == ["Review the Event Details above and confirm authorization directly with the client."]


class TestAnyChannelSent:
    def test_true_when_at_least_one_channel_sent(self):
        results = [
            NotifyResult(kind="not_configured", channel="telegram"),
            NotifyResult(kind="sent", channel="email"),
        ]
        assert _any_channel_sent(results) is True

    def test_false_when_nothing_sent(self):
        results = [
            NotifyResult(kind="not_configured", channel="telegram"),
            NotifyResult(kind="execution_error", channel="email", error="boom"),
        ]
        assert _any_channel_sent(results) is False

    def test_false_on_empty_results(self):
        assert _any_channel_sent([]) is False

    def test_a_prior_failed_attempt_does_not_look_like_success(self):
        # Explicit design requirement: not_configured/execution_error must
        # NOT be treated as "already sent" -- a genuine retry (e.g. after
        # fixing SMTP config) must still be allowed through.
        results = [NotifyResult(kind="not_configured", channel="email")]
        assert _any_channel_sent(results) is False


class TestGetSiteForEndpoint:
    def test_known_endpoint_resolves_to_its_site(self, monkeypatch):
        from services import sentinelone_dashboard_service as svc

        monkeypatch.setattr(svc, "_endpoint_site_map", {"3-LAP-546": "3line Limited"})
        assert svc.get_site_for_endpoint("3-LAP-546") == "3line Limited"

    def test_unknown_endpoint_returns_none(self, monkeypatch):
        from services import sentinelone_dashboard_service as svc

        monkeypatch.setattr(svc, "_endpoint_site_map", {"3-LAP-546": "3line Limited"})
        assert svc.get_site_for_endpoint("some-other-host") is None

    def test_empty_cache_returns_none(self, monkeypatch):
        from services import sentinelone_dashboard_service as svc

        monkeypatch.setattr(svc, "_endpoint_site_map", {})
        assert svc.get_site_for_endpoint("anything") is None
