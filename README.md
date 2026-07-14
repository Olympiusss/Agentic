# Sentry Agentic

> **AI-Powered Security Operations Centre** — autonomous threat detection, investigation, and response.

---

## Overview

Sentry Agentic is an enterprise SOC platform that combines AI-driven agent orchestration with full-stack security tooling. The system integrates with your existing security stack and uses Claude (claude-sonnet-4-5) as the core agent brain — reasoning over findings, invoking tools, and delivering actionable intelligence to analysts.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend  (React + Vite + TypeScript + MUI)            │
│  Dashboard · Cases · Findings · Analytics · AI Chat     │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼────────────────────────────────┐
│  Backend  (FastAPI + Uvicorn)                           │
│  REST API · Auth (JWT/2FA) · Streaming · Agent runner  │
└──────────┬──────────────────────┬───────────────────────┘
           │                      │
┌──────────▼──────────┐  ┌────────▼───────────────────────┐
│  PostgreSQL DB      │  │  Agent (Claude tool_use)       │
│  Findings · Cases   │  │  + MCP tool servers            │
│  Users · Events     │  │  sentry-findings · approval    │
└─────────────────────┘  │  attack-layer · sentry-flow    │
                         └────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Daemon  (async Python poller)                         │
│  SentinelOne threats + application risks · Kafka · ARQ │
└─────────────────────────────────────────────────────────┘
```

## Integrations (39 total)

### EDR / SIEM
- SentinelOne (threats + application vulnerability risks)
- CrowdStrike Falcon · Microsoft Defender · Carbon Black
- Splunk · Elastic Security · Azure Sentinel · GCP Chronicle

### Threat Intelligence
- VirusTotal · Shodan · AlienVault OTX · MISP
- Joe Sandbox · Hybrid Analysis · AnyRun · CAPE Sandbox

### Identity & Cloud
- Okta · Azure AD (Entra) · AWS Security Hub
- GCP Security Command Centre · Cloudflare

### Ticketing & Collaboration
- Jira · PagerDuty · Slack · Microsoft Teams

### Internal MCP Servers
- `sentry-findings` — query findings/vulnerabilities DB
- `sentry-flow` — workflow orchestration
- `approval` — human-in-the-loop approvals
- `attack-layer` — MITRE ATT&CK mapping
- `mempalace` — persistent agent memory

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, TypeScript, MUI v5 |
| Backend | FastAPI, Uvicorn, SQLAlchemy, Alembic |
| Database | PostgreSQL, Redis (ARQ job queue) |
| AI | Anthropic Claude (claude-sonnet-4-5) |
| Agent tools | MCP (Model Context Protocol) |
| Observability | Prometheus, Sentry, OpenTelemetry |
| Deployment | Docker, Kubernetes + Helm |

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker (for PostgreSQL + Redis)
- Anthropic API key

### Setup

```bash
# 1. Clone
git clone https://github.com/Olympiusss/Agentic.git
cd Agentic

# 2. Backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ./sentry-core
pip install -e ./mcp-servers
pip install -r requirements.txt

# 3. Database
cp env.example .env  # fill in your values
python -m alembic upgrade head

# 4. Frontend
cd frontend && npm install

# 5. Run
# Terminal 1 — backend
uvicorn backend.main:app --host 127.0.0.1 --port 6987

# Terminal 2 — daemon
python -m daemon.main

# Terminal 3 — frontend
cd frontend && npm run dev
```

### Environment Variables (key ones)

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://user:pass@localhost:5432/sentry_agentic_soc
SENTINELONE_CONSOLE_URL=https://your-tenant.sentinelone.net
SENTINELONE_API_TOKEN=your-token
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

This product includes code derived from the Vigil project (Apache 2.0).  
See [NOTICES](NOTICES) for full attribution.

---

*Built by Cybervergent Ltd.*
