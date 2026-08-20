"""Unit tests for services/sentinelone_entity_extraction.py.

Pure regex/keyword functions -- no mocking required. Every function must
return None (never a guess) when its pattern doesn't match, since callers
treat None on a required input as "ask the user," not "proceed anyway."
"""

import pytest

from services import sentinelone_entity_extraction as extract


@pytest.mark.unit
class TestExtractCveId:
    def test_finds_cve(self):
        assert extract.extract_cve_id("which endpoints are affected by CVE-2024-12345") == "CVE-2024-12345"

    def test_uppercases(self):
        assert extract.extract_cve_id("check cve-2024-1234 please") == "CVE-2024-1234"

    def test_no_match_returns_none(self):
        assert extract.extract_cve_id("what critical vulnerabilities do we have") is None


@pytest.mark.unit
class TestExtractUuid:
    def test_finds_uuid(self):
        text = "reconstruct the attack chain for storyline c5355307-0aa5-fad0-0424-cf1bb8f1d06a"
        assert extract.extract_uuid(text) == "c5355307-0aa5-fad0-0424-cf1bb8f1d06a"

    def test_no_match_returns_none(self):
        assert extract.extract_uuid("tell me about the latest threats") is None


@pytest.mark.unit
class TestExtractHostnameSubstring:
    def test_quoted_string_preferred(self):
        assert extract.extract_hostname_substring('what do we know about "WIN-ABC123"') == "WIN-ABC123"

    def test_keyword_pattern(self):
        assert extract.extract_hostname_substring("what do we know about host WIN-ABC123") == "WIN-ABC123"

    def test_keyword_pattern_strips_trailing_punctuation(self):
        assert extract.extract_hostname_substring("tell me about hostname WIN-ABC123?") == "WIN-ABC123"

    def test_no_match_returns_none_never_guesses(self):
        assert extract.extract_hostname_substring("how many endpoints do we have") is None


@pytest.mark.unit
class TestExtractTimeWindow:
    def test_days(self):
        assert extract.extract_time_window("how many threats in the last 7 days") == ("days", 7)

    def test_weeks(self):
        assert extract.extract_time_window("threats over the last 2 weeks") == ("weeks", 2)

    def test_months(self):
        assert extract.extract_time_window("last 1 month") == ("months", 1)

    def test_hours_no_space(self):
        # The real production bug this covers: "how many threats has
        # occurred in the last 24hrs?" silently fell back to an unwindowed
        # count because no hour unit was recognized at all.
        assert extract.extract_time_window("threats in the last 24hrs") == ("hours", 24)

    def test_hours_with_space_and_full_word(self):
        assert extract.extract_time_window("in the last 24 hours") == ("hours", 24)

    def test_hr_abbreviation_with_space(self):
        assert extract.extract_time_window("in the past 3 hr") == ("hours", 3)

    def test_past_synonym(self):
        assert extract.extract_time_window("threats in the past 7 days") == ("days", 7)

    def test_no_match_returns_none(self):
        assert extract.extract_time_window("how many threats exist") is None


@pytest.mark.unit
class TestExtractSeverity:
    def test_finds_severity(self):
        assert extract.extract_severity("what are our critical vulnerabilities") == "CRITICAL"

    def test_case_insensitive(self):
        assert extract.extract_severity("show me high severity issues") == "HIGH"

    def test_no_match_returns_none(self):
        assert extract.extract_severity("what vulnerabilities do we have") is None


@pytest.mark.unit
class TestExtractConnectivityFilter:
    def test_offline_maps_to_disconnected(self):
        assert extract.extract_connectivity_filter("which agents are offline") == "disconnected"

    def test_connected(self):
        assert extract.extract_connectivity_filter("which agents are connected") == "connected"

    def test_infected(self):
        assert extract.extract_connectivity_filter("show me infected endpoints") == "infected"

    def test_no_match_returns_none(self):
        assert extract.extract_connectivity_filter("show me all agents") is None


@pytest.mark.unit
class TestExtractHash:
    def test_finds_sha256(self):
        h = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"[:64]
        assert extract.extract_hash(f"analyze this hash: {h}") == h

    def test_finds_sha1(self):
        h = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"[:40]
        assert extract.extract_hash(f"check sha1 {h} please") == h

    def test_finds_md5(self):
        h = "5d41402abc4b2a76b9719d911017c592"[:32]
        assert extract.extract_hash(f"md5 is {h}") == h

    def test_lowercases(self):
        h = "B94D27B9934D3E08A52E52D7DA7DABFAC484EFE37A5380EE9088F7ACE2EFCDE9"[:64]
        assert extract.extract_hash(h) == h.lower()

    def test_prefers_sha256_over_shorter_substring(self):
        # A 64-char SHA256 also contains 40- and 32-char runs -- must not
        # be reported as a shorter hash type.
        h = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"[:64]
        assert extract.extract_hash(h) == h

    def test_no_match_returns_none(self):
        assert extract.extract_hash("tell me about the latest threats") is None
