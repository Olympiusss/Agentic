-- 19_clients.sql
-- The real, minimal per-tenant anchor (unified-schema foundation,
-- 2026-08-20). Before this table, services/client_registry_service.py's
-- EDR/SIEM name-matcher was the only "client" concept anywhere in the
-- codebase -- explicitly visibility-only per its own docstring
-- ("no RBAC/data-isolation changes"), in-memory only, never persisted,
-- no FK to findings/cases/users. This table is that matcher's real,
-- queryable, joinable counterpart, populated by reusing its existing
-- matching logic (services/client_registry_service.py::_sync_clients_table()),
-- not a separate mechanism.
--
-- client_id is a stable string slug (e.g. "cybervergent"), not a bigger
-- multi-account hierarchy than the platform needs right now.
--
-- users.client_id is added here too (for role-client scoping), but
-- WITHOUT a foreign-key constraint to clients -- 06_auth_tables.sql
-- (which creates `users`) runs before this file in docker-compose's
-- lexicographic init order, so a FK here would fail on a fresh stack.
-- Same reasoning already documented in 15_federation.sql for the
-- analogous findings/external_id case. A real FK for both users and
-- findings is added separately via scripts/migrate_schema.py, which
-- controls its own step ordering and can safely reference a table it
-- just created moments earlier in the same run.

CREATE TABLE IF NOT EXISTS clients (
    client_id           VARCHAR(64)  PRIMARY KEY,
    display_name        VARCHAR(200) NOT NULL,
    s1_site_name         VARCHAR(200),
    av_deployment_name   VARCHAR(200),
    av_deployment_fqdn   VARCHAR(200),
    match_confidence     VARCHAR(20),   -- 'exact' | 'fuzzy' | 'manual' | NULL
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clients_s1_site_name
    ON clients (s1_site_name);

CREATE INDEX IF NOT EXISTS idx_clients_av_deployment_name
    ON clients (av_deployment_name);

-- users already exists (06_auth_tables.sql); add the scoping column here,
-- deliberately with no FK constraint (see header comment above).
ALTER TABLE users ADD COLUMN IF NOT EXISTS client_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_user_client_id ON users (client_id);
