-- 18_agent_task_state.sql
-- Checkpoint table for finding processing (daemon/processor.py), so a
-- daemon crash mid-triage/enrichment doesn't silently drop the finding
-- forever. Runtime-hardening gap, 2026-08-20: a finding that reached
-- _store_finding() before a crash is already dedup-guarded by
-- IngestionService.ingest_finding() (checks existing finding_id, skips
-- re-ingest) -- which means the normal poll-and-ingest path can never
-- naturally reprocess it, since it "already exists" as far as ingestion
-- is concerned. This table tracks *processing* status distinct from
-- ingestion status, so daemon startup can find anything left mid-flight
-- (status='in_progress') and re-queue just the processing step
-- (triage/enrich/evaluate-for-response), not re-ingestion.

CREATE TABLE IF NOT EXISTS agent_task_state (
    finding_id      VARCHAR(50)  PRIMARY KEY,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',  -- pending | in_progress | completed | failed
    stage           VARCHAR(30),                              -- last stage reached: started | stored | triaged | enriched | evaluated
    attempts        INTEGER      NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_task_state_status
    ON agent_task_state (status);
