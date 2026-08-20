"""Notification dispatch for the resident brief and event-driven alerts
(Phase 3, Milestone 7 extension -- explicit user request, 2026-08-03: "for
every new threat on the env, notify the user via telegram or email").

Deliberately reporting-only: this module tells a human that something
happened. It never isolates a host, kills a process, opens a ticket, or
changes any state in the environment -- that boundary (Objective 2,
Responder role) stays out per the Capabilities Brief's own explicit,
repeated scope rule. Sending a message is the same category as the
24-hour brief (scheduled reporting, an intelligence output), just
event-triggered instead of time-scheduled.

Both channels gracefully no-op (log a warning, return False) when not
configured -- mirrors services/email_service.py's own established pattern
-- rather than raise and break the underlying detection work.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NotifyResult:
    kind: str  # "sent" | "not_configured" | "execution_error"
    channel: str
    error: Optional[str] = None


def _telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


async def notify_telegram(text: str) -> NotifyResult:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram notification skipped -- TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured")
        return NotifyResult(kind="not_configured", channel="telegram")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            response.raise_for_status()
        return NotifyResult(kind="sent", channel="telegram")
    except Exception as e:  # noqa: BLE001
        logger.error("Telegram notification failed: %s", e, exc_info=True)
        return NotifyResult(kind="execution_error", channel="telegram", error=str(e))


def notify_email(subject: str, body_text: str, to_addresses: list[str]) -> NotifyResult:
    from services.email_service import EmailService

    service = EmailService()
    if not service.enabled:
        logger.warning("Email notification skipped -- SMTP not configured")
        return NotifyResult(kind="not_configured", channel="email")

    try:
        sent = service.send_email(to_addresses=to_addresses, subject=subject, body_text=body_text)
        return NotifyResult(kind="sent" if sent else "execution_error", channel="email")
    except Exception as e:  # noqa: BLE001
        logger.error("Email notification failed: %s", e, exc_info=True)
        return NotifyResult(kind="execution_error", channel="email", error=str(e))


async def notify_new_threat(
    alert_summary: str,
    to_email_addresses: Optional[list[str]] = None,
    subject: str = "Hermes <Reporter>: New threat detected",
    telegram_lead: str = "Hermes <Reporter> -- new threat detected:",
) -> list[NotifyResult]:
    """Fan out one notification to every configured channel. Never raises
    -- a channel failure is reported in its own NotifyResult, not
    propagated to fail the others.

    Subject/lead line attributes Hermes <Reporter> explicitly (explicit
    user request, 2026-08-05: name and highlight the notification agent
    so recipients know who's informing them and can address follow-up
    questions to it). `subject`/`telegram_lead` are overridable (explicit
    user request, 2026-08-05: two distinct notifications per alert now --
    an immediate raw-alert one and a follow-up investigative-report one --
    each needs its own distinguishable subject line, not two emails both
    titled identically)."""
    results: list[NotifyResult] = []

    telegram_result = await notify_telegram(f"{telegram_lead}\n\n{alert_summary}")
    results.append(telegram_result)

    if to_email_addresses:
        email_result = notify_email(subject=subject, body_text=alert_summary, to_addresses=to_email_addresses)
        results.append(email_result)

    return results
