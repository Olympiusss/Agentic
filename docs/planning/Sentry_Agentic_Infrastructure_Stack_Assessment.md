# SENTRY AGENTIC INFRASTRUCTURE STACK ASSESSMENT

**Current Setup, Limitations, and Recommended Path**
Sentry Agentic — Security Operations Centre
Technical Reference — 2026-08-20

---

## 1. Purpose

This document is the technical companion to the infrastructure request email: what Sentry Agentic runs on today, exactly what that setup limits or blocks, and what we recommend moving to. Every claim below is grounded in what has actually been observed running this system, not a general best-practice assumption.

---

## 2. Current Stack Setup

Sentry Agentic runs as **six containerised services**, orchestrated with Docker Compose:

| Component | Technology | Role |
|---|---|---|
| Database | PostgreSQL 16 | Primary datastore — findings, cases, investigations, audit history |
| Cache / Queue | Redis | Job queue, caching, deduplication |
| LLM Gateway | Bifrost | Routes every LLM call, tracks cost and usage per call |
| Backend API | FastAPI (Python) | REST API and web application server |
| SOC Daemon | Python (custom) | The autonomous 24/7 process — polls SentinelOne, triages, enriches, notifies |
| LLM Worker | Python (ARQ background worker) | Executes the daemon's queued LLM calls |

**Reasoning engine**: Claude (Anthropic), reached through Bifrost. For SentinelOne questions specifically, a dedicated retrieval/grounding layer answers most questions from tested, proven data paths before Claude is asked to reason at all — this is described in the separate SentinelOne Intelligence Layer reports.

**Where it runs today**: all six containers, on **Docker Desktop on a Windows development laptop**, using Docker Desktop's WSL2 backend. This was always a development environment, not a production one — it was never intended to carry 24/7 client-facing monitoring.

**What's already built but not yet switched on**:
- A full observability stack (OpenTelemetry collector, Prometheus, Grafana, Jaeger) — built, tested working end-to-end, but not started by default; it is opt-in.
- A Kubernetes/Helm deployment path, alongside the Docker Compose path — built and mostly complete, with one known gap (the LLM gateway is not yet included in the Kubernetes chart).

---

## 3. Limitations of the Current Setup

Each item below is something we have directly observed, not a theoretical risk.

### 3.1 No real 24/7 availability
Docker Desktop's Windows/WSL2 layer has crashed outright multiple times, taking all six containers down with it at once — not a single-container failure, the whole platform. Each time, every client's alert monitoring stops until a person notices and manually restarts the environment. A laptop that also gets closed, put to sleep, or rebooted for unrelated reasons cannot be the platform a production security monitoring service runs on.

We applied one mitigation (capping WSL2's memory usage, which was previously unbounded and a suspected contributor) — it has **not fully resolved the problem**; the crash has recurred since. There is at least one more contributing factor in the Docker Desktop/WSL2 layer itself that we have not been able to isolate further, which is itself evidence this needs to move off that layer rather than continue to be patched.

### 3.2 A crash goes unnoticed until someone manually restarts it
There is currently no monitoring or alerting layer watching whether the service is actually up. We have hardened the *application* itself so that a finding interrupted mid-processing by a crash is automatically detected and reprocessed on the next restart — so a crash no longer means silently losing work in progress. But nothing today tells us a crash **happened** in the first place; that detection has to live at the infrastructure level, and it doesn't exist on a laptop.

### 3.3 No resilience at the data layer
PostgreSQL and Redis each run as a single container with no replication. Even once moved off the laptop, a single VM is still one point of failure for the database — a host-level issue (hardware fault, forced maintenance reboot) still takes the whole platform down, just less often than today. This is a known, separate tier above the immediate fix (see the Kubernetes/multi-node note in Section 4).

### 3.4 Testing gets interrupted by the same instability
The instability described above hasn't only affected production-style monitoring — it has directly interrupted agentic testing sessions mid-process, requiring re-runs and slowing validation work.

### 3.5 The AlienVault extended integration cannot proceed on this stack
Scope has been received for extended agentic action on AlienVault, but the current tech stack setup does not support proceeding with that integration. This is one of the concrete, current-dated reasons the infrastructure move is now blocking product roadmap, not just a reliability concern.

### 3.6 Observability exists but isn't running
The tracing/metrics stack (OpenTelemetry, Prometheus, Grafana, Jaeger) is fully built and has been verified working end-to-end — but it sits behind an opt-in flag and isn't part of the default running stack. On the current laptop-based setup there has been no reason to run it continuously; in a real production environment it should be on by default so an incident can actually be diagnosed after the fact.

### 3.7 Alert notifications go out through a personal email account
Every automated alert and investigative-finding email currently sends through a personal Gmail account, because no dedicated mailbox has been provisioned for the product. This is not sustainable as usage grows past internal testing — a production security notification channel should not depend on one person's personal inbox.

### 3.8 Secrets and credentials are bridged from a developer's machine, not provisioned
Credentials (SentinelOne, Anthropic, SMTP, etc.) are stored in an encrypted local vault on the development laptop and bridged into the containers via a file-system mount. This works for one developer's machine; it is not a real credential-provisioning model for a production environment with a team around it.

### 3.9 Slow, drifting cold-starts for the SentinelOne connector
The SentinelOne MCP server's own dependency chain is not fully version-pinned upstream, so it can take 90 seconds or more to become ready after a restart, and that startup time can drift further as its dependencies update over time. A persistent cache mitigates this partially; it does not eliminate it. This is a real but secondary issue — worth tracking, not currently blocking.

---

## 4. Recommended Stack Setup

**The fix**: move off Docker Desktop on a laptop onto a dedicated Linux environment, running the same containers through native Docker Engine and Docker Compose. This removes the specific layer that is failing (Docker Desktop/WSL2) rather than continuing to patch around it.

### 4.1 Environment

| | Minimum | Recommended (production) |
|---|---|---|
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| CPU | 4 vCPU | 8 vCPU |
| RAM | 8 GB | 16 GB |
| Storage | 50 GB SSD | 100 GB persistent SSD |
| Networking | Static/reserved address, outbound access to SentinelOne, AlienVault, Anthropic, SMTP | Same |

### 4.2 What must be provisioned alongside the VM

- Persistent block storage for PostgreSQL and Redis, so a restart doesn't lose findings or case history.
- Backup coverage for both application data and the encrypted credentials store.
- SSH/remote administration access for the team.
- **VM-level monitoring with auto-restart on failure** — the piece that directly closes the "crash goes unnoticed" gap in Section 3.2.
- Secure, durable provisioning of SentinelOne, AlienVault, Anthropic, and SMTP credentials on the new environment (replacing the developer-machine bridge in Section 3.8).
- A dedicated SOC Agentic email account, replacing the personal account in Section 3.7.
- Ports 6987, 6988, 6989, and 9091 reachable; 5432 (PostgreSQL), 6379 (Redis), and 8080 (Bifrost) kept internal-only.
- TLS/reverse proxy if the environment becomes reachable outside the internal network.

### 4.3 What this unblocks

- Removes the specific failure mode causing repeated outages (3.1) and testing interruptions (3.4).
- Gives the AlienVault extended integration (3.5) a stack it can actually be built on.
- Makes it practical to run the observability stack (3.6) continuously rather than as an opt-in.
- Closes the crash-detection gap (3.2), once VM-level monitoring is in place.

### 4.4 What this does not yet solve, by design

A single VM is a large reliability improvement over a laptop, but it is still a single point of failure at the infrastructure level (Section 3.3). We are deliberately not asking for a multi-node, replicated setup right now — a Kubernetes/Helm deployment path already exists in the codebase and is the natural next step once the platform's client load or an agreed uptime target justifies it, rather than committing to that scope before it's needed. The one piece of that path not yet finished is adding the LLM gateway (Bifrost) to the Kubernetes chart — small, known, not currently blocking.

---

## 5. Summary

| | Current | Recommended |
|---|---|---|
| Runs on | Windows laptop, Docker Desktop/WSL2 | Dedicated Ubuntu Linux VM |
| Availability | Crashes repeatedly, unnoticed until manually restarted | VM-level monitoring + auto-restart |
| Data resilience | Single container, no replication | Single VM (still no replication — see 4.4) |
| Credentials | Bridged from a developer's machine | Provisioned directly on the environment |
| Alert notifications | Personal email account | Dedicated SOC Agentic mailbox |
| Observability | Built, verified, not running by default | Running by default |
| AlienVault extended integration | Blocked | Unblocked |
| Path to full HA | Not applicable | Kubernetes/Helm, staged for when justified |
