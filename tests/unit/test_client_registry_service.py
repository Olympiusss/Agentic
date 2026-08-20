"""Unit tests for services/client_registry_service.py's name-normalization
and EDR/SIEM matching logic. Both are pure functions -- no I/O, no mocking
required -- exercised here with representative real client-name shapes
(the AlienVault Central deployment names confirmed live 2026-08-12, plus
plausible SentinelOne site-name variants of the same clients).
"""

import pytest

from services.client_registry_service import _match, _normalize


@pytest.mark.unit
class TestNormalize:
    def test_lowercases(self):
        assert _normalize("TrustBanc") == "trustbanc"

    def test_strips_usm_sensor_suffix(self):
        assert _normalize("TrustBanc - USM Sensor") == "trustbanc"

    def test_strips_sensor_suffix(self):
        assert _normalize("Xpresspayment Sensor") == "xpresspayment"

    def test_strips_punctuation(self):
        assert _normalize("Zone-Network!!") == "zone network"

    def test_collapses_whitespace(self):
        assert _normalize("Kuda   MFB") == "kuda mfb"

    def test_bare_suffix_word_normalizes_empty(self):
        assert _normalize("Sensor") == ""

    def test_empty_string(self):
        assert _normalize("") == ""


@pytest.mark.unit
class TestMatch:
    def test_exact_match(self):
        records = _match(["trustbanc"], ["trustbanc"])
        assert len(records) == 1
        r = records[0]
        assert r.has_edr and r.has_siem
        assert r.match_confidence == "exact"

    def test_fuzzy_match_via_suffix_stripping(self):
        records = _match(["TrustBanc - USM Sensor"], ["TrustBanc"])
        assert len(records) == 1
        r = records[0]
        assert r.has_edr and r.has_siem
        assert r.match_confidence == "exact"  # both normalize to "trustbanc"

    def test_fuzzy_substring_match(self):
        records = _match(["Xpresspayment Nigeria Ltd"], ["xpresspayment"])
        assert len(records) == 1
        r = records[0]
        assert r.has_edr and r.has_siem
        assert r.match_confidence == "fuzzy"

    def test_edr_only_unmatched(self):
        records = _match(["Cybervergent"], ["trustbanc"])
        names = {r.name: r for r in records}
        assert names["Cybervergent"].has_edr and not names["Cybervergent"].has_siem
        assert names["Cybervergent"].match_confidence is None

    def test_siem_only_unmatched(self):
        records = _match([], ["kudamfb"])
        assert len(records) == 1
        r = records[0]
        assert r.has_siem and not r.has_edr
        assert r.s1_site_name is None
        assert r.av_deployment_name == "kudamfb"

    def test_no_false_match_across_distinct_clients(self):
        records = _match(["TrustBanc"], ["Kudamfb"])
        assert len(records) == 2
        for r in records:
            assert not (r.has_edr and r.has_siem)

    def test_empty_inputs(self):
        assert _match([], []) == []

    def test_sorted_by_name(self):
        records = _match(["Zonenetwork", "Etranzact2"], [])
        assert [r.name for r in records] == ["Etranzact2", "Zonenetwork"]

    def test_each_av_name_matches_at_most_one_site(self):
        # Two S1 sites that both loosely resemble one AV deployment --
        # the AV name must not be double-consumed.
        records = _match(["Trustbanc East", "Trustbanc West"], ["Trustbanc"])
        matched = [r for r in records if r.has_edr and r.has_siem]
        assert len(matched) == 1


@pytest.mark.unit
class TestMatchOverrides:
    """Real gap found live 2026-08-15: SentinelOne's formal display names
    and AlienVault's slug-style deployment names sometimes share no
    substring at all despite being the same client -- no heuristic
    closes this, only an admin-confirmed pairing does."""

    def test_override_bridges_unrelated_names(self):
        records = _match(
            ["Zone Payment Network Limited"], ["zonenetwork"],
            overrides={"Zone Payment Network Limited": "zonenetwork"},
        )
        assert len(records) == 1
        r = records[0]
        assert r.has_edr and r.has_siem
        assert r.match_confidence == "manual"
        assert r.name == "Zone Payment Network Limited"

    def test_override_wins_over_automatic_match(self):
        # trustbanc would auto-match "TrustBanc" via exact normalization --
        # an override pointing it at a different AV name must win instead.
        records = _match(
            ["TrustBanc"], ["trustbanc", "trustbanc-secondary"],
            overrides={"TrustBanc": "trustbanc-secondary"},
        )
        matched = {r.s1_site_name: r.av_deployment_name for r in records if r.has_edr and r.has_siem}
        assert matched == {"TrustBanc": "trustbanc-secondary"}
        # The now-unclaimed "trustbanc" AV deployment surfaces as SIEM-only,
        # not silently dropped.
        siem_only = [r for r in records if r.has_siem and not r.has_edr]
        assert len(siem_only) == 1
        assert siem_only[0].av_deployment_name == "trustbanc"

    def test_stale_override_falls_through_to_normal_matching(self):
        # Override references a site name that no longer exists (renamed
        # or removed) -- must not crash, and both real names still get a
        # fair shot at automatic matching.
        records = _match(
            ["TrustBanc"], ["trustbanc"],
            overrides={"Some Renamed Site": "trustbanc"},
        )
        assert len(records) == 1
        assert records[0].match_confidence == "exact"

    def test_no_overrides_is_equivalent_to_none(self):
        assert _match(["A"], ["a"], overrides={}) == _match(["A"], ["a"])
