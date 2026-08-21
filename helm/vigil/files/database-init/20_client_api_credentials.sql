-- 20_client_api_credentials.sql
-- Client-portal API credentials: client_id + secret -> bearer token
-- (client-portal design spec, 2026-08-21). This is the "external
-- clients not on our security solution... config with their own token
-- or client id" auth path -- a client already provisioned with a
-- Client row (19_clients.sql) can be issued one or more rotatable
-- API credentials, verified by POST /api/auth/client-token.
--
-- Runs after 19_clients.sql (20 > 19 lexicographically), so unlike
-- users.client_id / findings.client_id, the FK to clients(client_id)
-- is safe to declare directly here -- no ordering hazard.
--
-- Only the bcrypt hash is ever stored; the plaintext secret is
-- generated and returned exactly once by
-- backend/api/clients.py::create_client_credential().

CREATE TABLE IF NOT EXISTS client_api_credentials (
    credential_id        VARCHAR(64)  PRIMARY KEY,
    client_id             VARCHAR(64)  NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    client_secret_hash    VARCHAR(200) NOT NULL,
    label                 VARCHAR(200),
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMP    NOT NULL DEFAULT NOW(),
    created_by            VARCHAR(100),
    last_used_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_client_api_credentials_client_id
    ON client_api_credentials (client_id);
