"""Unit tests for capabilities/notifier.py (Phase 3, Milestone 7 extension)."""

import pytest

from capabilities import notifier


@pytest.mark.unit
class TestTelegramNotConfigured:
    @pytest.mark.asyncio
    async def test_missing_token_gracefully_no_ops(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = await notifier.notify_telegram("test message")
        assert result.kind == "not_configured"
        assert result.channel == "telegram"


@pytest.mark.unit
class TestEmailNotConfigured:
    def test_missing_smtp_gracefully_no_ops(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        result = notifier.notify_email("subject", "body", ["a@b.com"])
        assert result.kind == "not_configured"
        assert result.channel == "email"


@pytest.mark.unit
class TestNotifyNewThreat:
    @pytest.mark.asyncio
    async def test_fans_out_to_all_channels_without_raising(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)

        results = await notifier.notify_new_threat("Alert xyz: CRITICAL malware detected", to_email_addresses=["soc@example.com"])

        channels = {r.channel for r in results}
        assert channels == {"telegram", "email"}
        assert all(r.kind == "not_configured" for r in results)  # neither configured in this test env
