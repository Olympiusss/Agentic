-- 17_llm_job_dead_letters.sql
-- Dead-letter record for ARQ LLM jobs that exhausted their retry budget
-- (services/llm_worker.py). Runtime-hardening gap fixed 2026-08-18:
-- previously, llm_call/llm_call_raw caught every exception internally
-- and returned an error dict, so ARQ (retry_jobs=True, max_tries=3)
-- always saw the job as "successful" and never retried it, and an
-- exhausted job simply vanished into the logs -- no dead-letter queue
-- existed anywhere in the codebase. Read via a dedicated backend API
-- endpoint so a failed job is discoverable without SSH/log-grepping.

CREATE TABLE IF NOT EXISTS llm_job_dead_letters (
    id              BIGSERIAL PRIMARY KEY,
    job_id          VARCHAR(255),
    function_name   VARCHAR(64)  NOT NULL,        -- 'llm_call' | 'llm_call_raw'
    error           TEXT         NOT NULL,
    attempts        INTEGER      NOT NULL,
    -- Correlation back to what triggered the job -- nullable, since not
    -- every caller has one or the other (or either) in scope.
    finding_id      VARCHAR(50),
    investigation_id VARCHAR(50),
    agent_id        VARCHAR(100),
    -- Small, non-secret context only (model, message count, session_id) --
    -- never the raw message/prompt content, which may carry sensitive
    -- finding data and has no reason to be duplicated into a second table.
    context         JSONB,
    failed_at       TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_job_dead_letters_failed_at
    ON llm_job_dead_letters (failed_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_job_dead_letters_finding_id
    ON llm_job_dead_letters (finding_id);

CREATE INDEX IF NOT EXISTS idx_llm_job_dead_letters_investigation_id
    ON llm_job_dead_letters (investigation_id);
