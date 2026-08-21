"""Client-portal API (Security Insights Platform design spec, 2026-08-21).

Every endpoint here resolves client_id from the authenticated caller's
own user record (current_user.client_id) -- never from a caller-supplied
query param -- and fails closed (empty/zeroed response, not an
unscoped view) when the caller has no client_id. Same posture as
backend/api/findings.py's role-client scoping, just applied
unconditionally here rather than only for role-client users, since
every route in this router is portal-only by definition.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from database.models import User

router = APIRouter(prefix="/api/portal", tags=["portal"])
logger = logging.getLogger(__name__)

_SEVERITY_WEIGHT = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _require_client_id(current_user: User) -> str:
    if not current_user.client_id:
        raise HTTPException(
            status_code=403,
            detail="This account has no client associated with it yet.",
        )
    return current_user.client_id


# ---------------------------------------------------------------------------
# Home — Executive Overview
# ---------------------------------------------------------------------------


@router.get("/home")
async def get_portal_home(current_user: User = Depends(get_current_user)):
    """Posture headline, coverage strip, and top findings for one client
    (Section 3.1 of the design spec). Reuses
    services/strategic_insights_service.py's priority-findings logic
    (client_id-scoped) rather than a parallel implementation."""
    client_id = _require_client_id(current_user)

    from database.service import DatabaseService
    from services.strategic_insights_service import get_strategic_insights

    db_service = DatabaseService()
    client = db_service.get_client(client_id)
    insights = get_strategic_insights(window_hours=168, client_id=client_id)

    coverage = None
    if client and client.get("s1_site_name"):
        from services.sentinelone_dashboard_service import get_site_summary

        summary = await get_site_summary(client["s1_site_name"])
        if summary.kind == "found":
            coverage = {
                "endpoint_count": summary.endpoint_count,
                "agents_offline": summary.agents_offline,
                "agents_online": max(0, summary.endpoint_count - summary.agents_offline),
            }

    vb = insights.verdict_breakdown
    if insights.findings_analyzed == 0:
        headline = "No new findings were analyzed in your environment over the past 7 days."
    elif vb.malicious > 0:
        headline = (
            f"{vb.malicious} malicious finding(s) were identified in your environment this week "
            "-- see Priority Findings below."
        )
    elif vb.suspicious > 0:
        headline = (
            f"Your environment posture looks stable this week -- {vb.suspicious} suspicious "
            "finding(s) under review, none confirmed malicious."
        )
    else:
        headline = (
            f"Your environment posture is clean this week -- {insights.findings_analyzed} "
            "finding(s) analyzed, none malicious or suspicious."
        )

    top_findings = [
        {
            "finding_id": f.finding_id,
            "title": f.title,
            "verdict": f.verdict,
            "reasoning": f.reasoning,
            "hosts": f.hosts,
        }
        for f in insights.top_priority_findings[:5]
    ]

    return {
        "client_id": client_id,
        "client_display_name": (client or {}).get("display_name") or client_id,
        "headline": headline,
        "coverage": coverage,
        "top_findings": top_findings,
        "findings_analyzed": insights.findings_analyzed,
        "estimated_hours_saved": insights.estimated_hours_saved,
        "window_hours": 168,
    }


# ---------------------------------------------------------------------------
# Agentic Operations Center
# ---------------------------------------------------------------------------


def _autonomy_tier(decision: dict) -> str:
    """Derived label (design spec: Enriched -> Recommended -> Executed
    (pre-approved) -> Executed (autonomous) -> Escalated), computed from
    existing decision_type/decision_action/confidence_score rather than
    a new stored column -- v1 heuristic, refinable later without another
    migration."""
    action = decision.get("decision_action")
    if action == "escalate":
        return "Escalated to human"
    if action in ("approve", "modify", "override"):
        return "Executed (pre-approved)"
    confidence = decision.get("confidence_score") or 0.0
    if confidence >= 0.9:
        return "Recommended"
    return "Enriched"


def _is_declined(decision: dict) -> bool:
    """A 'declined' entry is the agent's OWN verdict, not a human
    action -- capabilities/synergy.py's zeus_pipeline write already
    encodes this unconditionally via recommended_action=f"verdict=
    {highest_verdict}" for every finding it processes (clean/unknown
    included), so this is a pure filter over existing data, not a new
    write path."""
    recommended = (decision.get("recommended_action") or "")
    return recommended in ("verdict=clean", "verdict=unknown") and not decision.get("decision_action")


@router.get("/action-ledger")
async def get_action_ledger(
    segment: Optional[str] = Query(None, description="Filter: 'declined' for Decisions Declined only"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    """Action Ledger (Section 3.2). segment=declined surfaces the
    Decisions Declined view -- deliberately the same underlying data,
    not a separate table, per the design spec's own framing of it as a
    trust signal about agent judgment, not a distinct action type."""
    client_id = _require_client_id(current_user)

    from database.service import DatabaseService

    db_service = DatabaseService()
    rows = db_service.get_client_decision_ledger(client_id, limit=500)

    for r in rows:
        r["autonomy_tier"] = _autonomy_tier(r)
        r["declined"] = _is_declined(r)

    if segment == "declined":
        rows = [r for r in rows if r["declined"]]

    total = len(rows)
    page = rows[offset: offset + limit]
    return {"entries": page, "total": total, "offset": offset, "limit": limit, "has_more": (offset + limit) < total}


@router.get("/scorecard")
async def get_scorecard(current_user: User = Depends(get_current_user)):
    """Agent Performance Scorecard (Section 3.2). Honest about sparse
    feedback data by construction -- see
    DatabaseService.get_client_decision_scorecard's docstring."""
    client_id = _require_client_id(current_user)

    from database.service import DatabaseService

    return DatabaseService().get_client_decision_scorecard(client_id)


# ---------------------------------------------------------------------------
# Agentic Operations Center — Pending Approvals
# ---------------------------------------------------------------------------


class PortalRejectRequest(BaseModel):
    reason: str = Field(..., description="Required justification for denying this action.")


@router.get("/approvals")
async def list_portal_approvals(current_user: User = Depends(get_current_user)):
    """Client-scoped Pending Approvals (Section 3.2). Reuses the same
    ApprovalService the internal /api/approvals router already uses --
    this is a client-scoped view over the same table, not a fork."""
    client_id = _require_client_id(current_user)

    from services.approval_service import ActionStatus, get_approval_service

    service = get_approval_service()
    actions = service.list_actions(status=ActionStatus.PENDING, client_id=client_id)
    return {"actions": [a.__dict__ for a in actions]}


def _get_owned_action(action_id: str, client_id: str):
    from services.approval_service import get_approval_service

    service = get_approval_service()
    action = service.get_action(action_id)
    if not action or action.client_id != client_id:
        # 404, not 403 -- don't confirm the action_id exists for another
        # client to a caller who guessed it.
        raise HTTPException(status_code=404, detail="Action not found")
    return service, action


@router.post("/approvals/{action_id}/approve")
async def approve_portal_action(action_id: str, current_user: User = Depends(get_current_user)):
    client_id = _require_client_id(current_user)
    service, _ = _get_owned_action(action_id, client_id)
    result = service.approve_action(action_id, approved_by=current_user.username)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to approve action")
    return result.__dict__


@router.post("/approvals/{action_id}/reject")
async def reject_portal_action(
    action_id: str, body: PortalRejectRequest, current_user: User = Depends(get_current_user),
):
    client_id = _require_client_id(current_user)
    service, _ = _get_owned_action(action_id, client_id)
    result = service.reject_action(action_id, reason=body.reason, rejected_by=current_user.username)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to reject action")
    return result.__dict__
