"""
System/support-workflow endpoints.

Runtime-hardening gap fixed 2026-08-19: services/llm_worker.py's
dead-letter queue (database/init/17_llm_job_dead_letters.sql) exists to
answer "why did this background LLM job fail" without SSH/log-grepping --
this router is what actually makes that discoverable from the app.

Extended 2026-08-20 with task-state (crash-resume checkpoint) and
observability-status endpoints, so the admin UI can show what was
previously only visible via `docker logs`/direct DB query: whether the
daemon has anything stuck mid-processing, and whether LLM tracing is
actually turned on.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database.service import DatabaseService

logger = logging.getLogger(__name__)

router = APIRouter()


class LLMDeadLetterResponse(BaseModel):
    id: int
    job_id: Optional[str]
    function_name: str
    error: str
    attempts: int
    finding_id: Optional[str]
    investigation_id: Optional[str]
    agent_id: Optional[str]
    context: Optional[dict]
    failed_at: Optional[str]


@router.get("/dead-letters", response_model=List[LLMDeadLetterResponse])
async def list_dead_letters(
    finding_id: Optional[str] = Query(None, description="Filter by finding ID"),
    investigation_id: Optional[str] = Query(None, description="Filter by investigation ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List background LLM jobs that exhausted their retry budget --
    surfaces exactly what services/llm_worker.py's retry/backoff logic
    gave up on, most recent first."""
    db_service = DatabaseService()
    dead_letters = db_service.list_llm_dead_letters(
        finding_id=finding_id, investigation_id=investigation_id, limit=limit, offset=offset,
    )
    return [LLMDeadLetterResponse(**d.to_dict()) for d in dead_letters]


class TaskStateResponse(BaseModel):
    finding_id: str
    status: str
    stage: Optional[str]
    attempts: int
    last_error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class TaskStateSummaryResponse(BaseModel):
    counts: dict
    stuck: List[TaskStateResponse]
    recent_failed: List[TaskStateResponse]


@router.get("/task-state", response_model=TaskStateSummaryResponse)
async def get_task_state_summary():
    """Crash-resume checkpoint state (database/init/18_agent_task_state.sql)
    -- counts by status, plus anything currently stuck (in_progress, a live
    crash-resume candidate) or recently failed. Previously only visible via
    direct DB query."""
    from services.database_data_service import DatabaseDataService

    data_service = DatabaseDataService()
    counts = data_service.get_task_state_counts()
    stuck = data_service.list_task_states(status="in_progress", limit=50)
    recent_failed = data_service.list_task_states(status="failed", limit=50)
    return TaskStateSummaryResponse(
        counts=counts,
        stuck=[TaskStateResponse(**s) for s in stuck],
        recent_failed=[TaskStateResponse(**f) for f in recent_failed],
    )


class ObservabilityStatusResponse(BaseModel):
    otel_enabled: bool
    jaeger_port: int
    grafana_port: int
    prometheus_port: int
    note: str


@router.get("/observability-status", response_model=ObservabilityStatusResponse)
async def get_observability_status():
    """Whether LLM/agent tracing is actually turned on right now, and
    where to find the trace/metrics UIs -- otel-collector/jaeger/prometheus/
    grafana are opt-in (docker-compose.yml's `observability` profile) and
    VIGIL_OTEL_ENABLED defaults off, so this answers "is this actually
    running" rather than "does the code support it"."""
    otel_enabled = os.environ.get("VIGIL_OTEL_ENABLED", "").strip().lower() in (
        "true", "1", "yes",
    )
    return ObservabilityStatusResponse(
        otel_enabled=otel_enabled,
        jaeger_port=16686,
        grafana_port=3001,
        prometheus_port=9095,
        note=(
            "Tracing is active and being exported."
            if otel_enabled
            else "Tracing code is instrumented but not currently enabled -- "
            "set VIGIL_OTEL_ENABLED=true and run with --profile observability."
        ),
    )
