"""Task scheduler for periodic daemon operations."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field

from daemon.config import SchedulerConfig

logger = logging.getLogger(__name__)


def _sandbox_poll_enabled() -> bool:
    import os

    return os.getenv("SANDBOX_AUTO_SUBMIT", "false").strip().lower() in ("1", "true", "yes", "on")


def _sandbox_poll_interval() -> int:
    import os

    try:
        return max(30, int(os.getenv("SANDBOX_POLL_INTERVAL", "60")))
    except ValueError:
        return 60


@dataclass
class ScheduledTask:
    """Represents a scheduled task."""
    name: str
    func: Callable
    interval: int  # seconds
    last_run: Optional[datetime] = None
    enabled: bool = True
    run_on_start: bool = False


class TaskScheduler:
    """Manages periodic tasks for the SOC daemon."""
    
    def __init__(self, config: SchedulerConfig):
        self.config = config
        self._tasks: List[ScheduledTask] = []
        
        # Services (lazy loaded)
        self._data_service = None
        self._claude_service = None
        
        # Stats
        self.stats = {
            "tasks_run": 0,
            "threat_hunts": 0,
            "reports_generated": 0,
            "cleanups_run": 0,
            "errors": 0
        }
        
        # Register default tasks
        self._register_default_tasks()
    
    def _register_default_tasks(self):
        """Register default scheduled tasks."""
        if self.config.threat_hunt_enabled:
            self._tasks.append(ScheduledTask(
                name="threat_hunt",
                func=self._run_threat_hunt,
                interval=self.config.threat_hunt_interval,
                enabled=True,
                run_on_start=False
            ))
        
        if self.config.themis_sweep_enabled:
            self._tasks.append(ScheduledTask(
                name="themis_sweep",
                func=self._run_themis_sweep,
                interval=self.config.themis_sweep_interval,
                enabled=True,
                run_on_start=True,
            ))

        if self.config.argus_sweep_enabled:
            self._tasks.append(ScheduledTask(
                name="argus_sweep",
                func=self._run_argus_sweep,
                interval=self.config.argus_sweep_interval,
                enabled=True,
                run_on_start=False,  # dashboard cache needs its own first refresh before there's anything to verify
            ))

        if self.config.report_generation_enabled:
            self._tasks.append(ScheduledTask(
                name="weekly_report",
                func=self._generate_report,
                interval=self.config.report_interval,
                enabled=True,
                run_on_start=False
            ))
        
        if self.config.cleanup_enabled:
            self._tasks.append(ScheduledTask(
                name="cleanup",
                func=self._run_cleanup,
                interval=self.config.cleanup_interval,
                enabled=True,
                run_on_start=False
            ))
        
        # Health check task (every 5 minutes)
        self._tasks.append(ScheduledTask(
            name="health_check",
            func=self._run_health_check,
            interval=300,
            enabled=True,
            run_on_start=True
        ))

        # Sandbox poller — only runs when auto-submit is enabled
        if _sandbox_poll_enabled():
            self._tasks.append(ScheduledTask(
                name="sandbox_poll",
                func=self._run_sandbox_poll,
                interval=_sandbox_poll_interval(),
                enabled=True,
                run_on_start=False,
            ))

        # Threat-feed poller — only runs when the Cloudforce One integration is enabled.
        try:
            from daemon.threat_feed_poller import ThreatFeedPoller
            if ThreatFeedPoller.is_enabled():
                self._tasks.append(ScheduledTask(
                    name="threat_feed_poll",
                    func=self._run_threat_feed_poll,
                    interval=ThreatFeedPoller.poll_interval_seconds(),
                    enabled=True,
                    run_on_start=True,
                ))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Threat feed poller unavailable: {e}")

        # SentinelOne environment memory cache refresh — only runs when the
        # sentinelone MCP server is configured and an environment map exists
        # (Phase 2 Milestone 6). Cheap and local: re-reads environment_map.yaml,
        # never queries the live tenant on its own.
        try:
            from services.sentinelone_environment_cache_service import (
                SentinelOneEnvironmentCacheService,
            )
            if SentinelOneEnvironmentCacheService.is_enabled():
                self._tasks.append(ScheduledTask(
                    name="sentinelone_environment_cache_refresh",
                    func=self._run_sentinelone_environment_cache_refresh,
                    interval=SentinelOneEnvironmentCacheService.refresh_interval_seconds(),
                    enabled=True,
                    run_on_start=True,
                ))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SentinelOne environment cache refresh unavailable: {e}")

        # SentinelOne endpoint->site (client name) map refresh -- bug found
        # live 2026-08-18: capabilities/synergy.py's client-name resolution
        # (get_site_for_endpoint) reads services/sentinelone_dashboard_service.py's
        # module-level _endpoint_site_map cache, but that cache is only ever
        # populated by that service's own refresh_snapshot()/background
        # refresh loop -- which nothing in this process (soc-daemon runs as
        # a SEPARATE process from backend, with its own Python module state)
        # ever called. Every real alert notification the daemon sent showed
        # "Client: unknown client" as a result, even for endpoints that do
        # have a real site in SentinelOne. Registered unconditionally (same
        # style as the poller itself) since it's a live SentinelOne call
        # that should simply no-op/log a warning if not configured, not a
        # separate enable flag.
        self._tasks.append(ScheduledTask(
            name="sentinelone_client_map_refresh",
            func=self._run_sentinelone_client_map_refresh,
            interval=300,
            enabled=True,
            run_on_start=True,
        ))

        # Resident 24h brief (Hermes/reporter, capabilities/brief.py) --
        # built 2026-08-03, never wired into this scheduler until now. Off
        # by default and requires an explicit owner, per the capability's
        # own guardrail ("confirm the owner, format, and delivery channel
        # before enabling it") -- see DAEMON_BRIEF_ENABLED/DAEMON_BRIEF_OWNER
        # in daemon/config.py. Persists its result to system_config only
        # (same pattern as Themis/Argus sweeps below); does NOT email or
        # notify anyone on its own -- wiring that up is a separate decision.
        if self.config.brief_enabled and self.config.brief_owner:
            self._tasks.append(ScheduledTask(
                name="resident_brief",
                func=self._run_brief,
                interval=self.config.brief_interval_hours * 3600,
                enabled=True,
                run_on_start=False,
            ))
        elif self.config.brief_enabled and not self.config.brief_owner:
            logger.warning(
                "DAEMON_BRIEF_ENABLED=true but DAEMON_BRIEF_OWNER is unset -- "
                "resident brief task NOT registered (owner confirmation is required)"
            )

    def _init_services(self):
        """Initialize required services."""
        try:
            from services.database_data_service import DatabaseDataService
            self._data_service = DatabaseDataService()
            logger.info("Database service initialized for scheduler")
        except Exception as e:
            logger.error(f"Failed to initialize database service: {e}")
        
        try:
            from services.claude_service import ClaudeService
            self._claude_service = ClaudeService()
            logger.info("Claude service initialized for scheduler")
        except Exception as e:
            logger.warning(f"Failed to initialize Claude service: {e}")
    
    async def run(self, shutdown_event: asyncio.Event):
        """Run the scheduler loop."""
        logger.info("Task scheduler starting...")
        self._init_services()
        
        # Run startup tasks
        for task in self._tasks:
            if task.run_on_start and task.enabled:
                try:
                    await task.func()
                    task.last_run = datetime.utcnow()
                except Exception as e:
                    logger.error(f"Startup task {task.name} failed: {e}")
        
        # Main scheduling loop
        while not shutdown_event.is_set():
            now = datetime.utcnow()
            
            for task in self._tasks:
                if not task.enabled:
                    continue
                
                # Check if task should run
                should_run = (
                    task.last_run is None or
                    (now - task.last_run).total_seconds() >= task.interval
                )
                
                if should_run:
                    try:
                        logger.info(f"Running scheduled task: {task.name}")
                        await task.func()
                        task.last_run = now
                        self.stats["tasks_run"] += 1
                    except Exception as e:
                        logger.error(f"Scheduled task {task.name} failed: {e}")
                        self.stats["errors"] += 1
            
            # Check every minute
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                pass
        
        logger.info("Task scheduler stopped")
    
    async def _run_threat_hunt(self):
        """Execute periodic threat hunting queries."""
        logger.info("Starting scheduled threat hunt...")
        self.stats["threat_hunts"] += 1
        
        if not self._data_service:
            logger.warning("Data service not available for threat hunt")
            return
        
        # Get recent findings for analysis
        findings = self._data_service.get_findings()
        if not findings:
            logger.info("No findings to analyze for threat hunt")
            return
        
        # Analyze patterns in recent findings
        analysis = await self._analyze_finding_patterns(findings)
        
        # Look for indicators of compromise across data
        iocs = self._extract_iocs(findings)
        
        # Query for related activity (if Splunk is available)
        await self._hunt_for_iocs(iocs)
        
        # Generate threat hunt summary
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "findings_analyzed": len(findings),
            "patterns_detected": analysis.get("patterns", []),
            "iocs_found": len(iocs),
            "recommendations": analysis.get("recommendations", [])
        }
        
        logger.info(f"Threat hunt complete: {summary}")
        return summary
    
    async def _analyze_finding_patterns(self, findings: List[Dict]) -> Dict[str, Any]:
        """Analyze patterns in findings."""
        patterns = []
        recommendations = []
        
        # Group by MITRE technique
        technique_counts = {}
        for finding in findings:
            mitre = finding.get("mitre_predictions", {})
            for technique in mitre.keys():
                technique_counts[technique] = technique_counts.get(technique, 0) + 1
        
        # Identify common techniques
        for technique, count in sorted(technique_counts.items(), key=lambda x: -x[1])[:5]:
            if count >= 3:
                patterns.append({
                    "type": "common_technique",
                    "technique": technique,
                    "count": count
                })
                recommendations.append(f"Review defenses for {technique} (seen {count} times)")
        
        # Group by severity
        severity_counts = {}
        for finding in findings:
            sev = finding.get("severity", "unknown")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        critical_count = severity_counts.get("critical", 0)
        high_count = severity_counts.get("high", 0)
        
        if critical_count > 5:
            patterns.append({
                "type": "severity_spike",
                "severity": "critical",
                "count": critical_count
            })
            recommendations.append(f"Investigate spike in critical findings ({critical_count})")
        
        return {
            "patterns": patterns,
            "severity_distribution": severity_counts,
            "technique_distribution": technique_counts,
            "recommendations": recommendations
        }
    
    def _extract_iocs(self, findings: List[Dict]) -> Dict[str, List[str]]:
        """Extract IOCs from findings."""
        iocs = {
            "ips": set(),
            "domains": set(),
            "hashes": set(),
            "users": set()
        }
        
        for finding in findings:
            context = finding.get("entity_context", {})
            
            for ip in context.get("src_ips", []):
                if ip and not ip.startswith(("10.", "192.168.", "172.")):
                    iocs["ips"].add(ip)
            
            for ip in context.get("dest_ips", []):
                if ip and not ip.startswith(("10.", "192.168.", "172.")):
                    iocs["ips"].add(ip)
            
            for domain in context.get("domains", []):
                iocs["domains"].add(domain)
            
            for hash_val in context.get("file_hashes", []):
                iocs["hashes"].add(hash_val)
            
            for user in context.get("usernames", []):
                iocs["users"].add(user)
        
        return {k: list(v) for k, v in iocs.items()}
    
    async def _hunt_for_iocs(self, iocs: Dict[str, List[str]]):
        """Hunt for IOCs in connected systems."""
        # This would query Splunk/SIEM for IOC matches
        # For now, just log
        total_iocs = sum(len(v) for v in iocs.values())
        logger.info(f"Hunting for {total_iocs} IOCs across systems")
    
    async def _run_themis_sweep(self):
        """Themis's standing 24/7 system-health sweep (explicit user
        request: the compliance agent should be checking in on the other
        agents' performance continuously, not only when a specific
        finding triggers capabilities/synergy.py's per-finding review).
        Delegates the actual analysis to capabilities/synergy.py's
        run_themis_sweep, which persists its verdict to system_config."""
        logger.info("Running Themis's system-health sweep...")
        try:
            from capabilities.synergy import run_themis_sweep

            result = await run_themis_sweep()
            if result.kind == "answered":
                logger.info(
                    f"Themis sweep: {result.findings_reviewed} finding(s) reviewed, "
                    f"{len(result.systemic_issues)} note(s): {result.systemic_issues}"
                )
            else:
                logger.warning(f"Themis sweep failed: {result.error}")
            return result
        except Exception as e:  # noqa: BLE001
            logger.error(f"Themis sweep errored: {e}")
            self.stats["errors"] += 1

    async def _run_argus_sweep(self):
        """Argus's standing fact-check sweep (explicit user request,
        2026-08-05: a sub agent that verifies a subagent response against
        what is actually on the solution). Re-checks the dashboard
        snapshot's key reported numbers against fresh live SentinelOne
        queries and persists the result to system_config, same pattern as
        Themis's sweep, so the dashboard/chat can surface "last verified"
        state without re-running the check on every page load."""
        logger.info("Running Argus's verification sweep...")
        try:
            from capabilities.verification import verify_against_dashboard
            from dataclasses import asdict
            from datetime import datetime, timezone

            results = await verify_against_dashboard()
            mismatches = [r for r in results if r.kind == "mismatch"]
            if mismatches:
                logger.warning(f"Argus sweep: {len(mismatches)} mismatch(es) found: {[r.claim_type for r in mismatches]}")
            else:
                logger.info(f"Argus sweep: {len(results)} claim(s) checked, all matched (or nothing cached yet)")

            try:
                from database.config_service import get_config_service

                get_config_service().set_system_config(
                    "argus.verification_results",
                    {
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "results": [asdict(r) for r in results],
                    },
                    description="Argus's periodic fact-check sweep (capabilities/verification.py)",
                    config_type="monitoring",
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Argus sweep: failed to persist result: {e}")

            return results
        except Exception as e:  # noqa: BLE001
            logger.error(f"Argus sweep errored: {e}")
            self.stats["errors"] += 1

    async def _generate_report(self):
        """Generate periodic summary report."""
        logger.info("Generating scheduled report...")
        self.stats["reports_generated"] += 1
        
        if not self._data_service:
            logger.warning("Data service not available for report generation")
            return
        
        # Gather data for report
        findings = self._data_service.get_findings()
        cases = self._data_service.get_cases()
        
        # Calculate time range (last week)
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        
        # Filter to recent findings
        recent_findings = [
            f for f in findings
            if self._parse_timestamp(f.get("timestamp")) >= week_ago
        ]
        
        # Build report
        report = {
            "generated_at": now.isoformat(),
            "period_start": week_ago.isoformat(),
            "period_end": now.isoformat(),
            "summary": {
                "total_findings": len(recent_findings),
                "total_cases": len(cases),
                "critical_findings": len([f for f in recent_findings if f.get("severity") == "critical"]),
                "high_findings": len([f for f in recent_findings if f.get("severity") == "high"]),
            },
            "top_techniques": self._get_top_techniques(recent_findings, 5),
            "data_sources": self._get_data_source_breakdown(recent_findings)
        }
        
        logger.info(f"Report generated: {report['summary']}")
        
        # Could send report via email/Slack here
        return report
    
    def _parse_timestamp(self, ts: Any) -> datetime:
        """Parse timestamp to datetime."""
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
            except ValueError:
                pass
        return datetime.min
    
    def _get_top_techniques(self, findings: List[Dict], limit: int) -> List[Dict]:
        """Get top MITRE techniques from findings."""
        technique_counts = {}
        for finding in findings:
            mitre = finding.get("mitre_predictions", {})
            for technique in mitre.keys():
                technique_counts[technique] = technique_counts.get(technique, 0) + 1
        
        sorted_techniques = sorted(technique_counts.items(), key=lambda x: -x[1])[:limit]
        return [{"technique": t, "count": c} for t, c in sorted_techniques]
    
    def _get_data_source_breakdown(self, findings: List[Dict]) -> Dict[str, int]:
        """Get finding counts by data source."""
        source_counts = {}
        for finding in findings:
            source = finding.get("data_source", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
        return source_counts
    
    async def _run_cleanup(self):
        """Clean up old data."""
        logger.info("Running scheduled cleanup...")
        self.stats["cleanups_run"] += 1
        
        # Calculate cutoff date
        cutoff = datetime.utcnow() - timedelta(days=self.config.cleanup_retention_days)
        
        # For now, just log what would be cleaned
        # In production, would delete old findings/processed events
        logger.info(f"Cleanup would remove data older than {cutoff.isoformat()}")
        
        # Dedup sets are pruned by RedisDedupSet itself (TTL + size cap)

        return {"cutoff_date": cutoff.isoformat()}
    
    async def _run_sandbox_poll(self):
        """Advance pending sandbox submissions to completed reports."""
        try:
            from daemon.sandbox_poller import SandboxPoller
        except Exception as e:
            logger.warning(f"Sandbox poller unavailable: {e}")
            return

        poller = SandboxPoller(data_service=self._data_service)
        stats = await poller.run_once()
        if stats.get("completed") or stats.get("expired") or stats.get("errors"):
            logger.info(f"Sandbox poll: {stats}")
        return stats

    async def _run_threat_feed_poll(self):
        """Pull Cloudforce One STIX/TAXII indicators into threat_indicators."""
        try:
            from daemon.threat_feed_poller import ThreatFeedPoller
        except Exception as e:
            logger.warning(f"Threat feed poller unavailable: {e}")
            return
        if not ThreatFeedPoller.is_enabled():
            return
        poller = ThreatFeedPoller()
        return await poller.run_once()

    async def _run_sentinelone_environment_cache_refresh(self):
        """Refresh the SentinelOne environment memory cache (Phase 2
        Milestone 6). Reads environment_map.yaml only; does not call the
        live tenant."""
        try:
            from services.sentinelone_environment_cache_service import (
                SentinelOneEnvironmentCacheService,
            )
        except Exception as e:
            logger.warning(f"SentinelOne environment cache unavailable: {e}")
            return
        if not SentinelOneEnvironmentCacheService.is_enabled():
            return
        try:
            cache = SentinelOneEnvironmentCacheService.refresh()
            logger.info(
                f"SentinelOne environment cache refreshed: "
                f"{len(cache.sites)} site(s), {len(cache.groups)} group(s)"
            )
            return cache
        except FileNotFoundError as e:
            logger.warning(f"SentinelOne environment cache refresh skipped: {e}")

    async def _run_sentinelone_client_map_refresh(self):
        """Refresh services/sentinelone_dashboard_service.py's endpoint->site
        map in THIS process (see the registration comment above for why this
        is needed) -- a real, live SentinelOne inventory call, same one the
        dashboard service already makes every 5 minutes for the backend
        process. Best-effort: any failure just means the next alert's
        client name stays "unknown client" until the next successful
        refresh, never blocks polling."""
        try:
            from services.sentinelone_dashboard_service import refresh_snapshot
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SentinelOne client map refresh unavailable: {e}")
            return
        try:
            snapshot = await refresh_snapshot()
            logger.info(
                f"SentinelOne client map refreshed: {len(snapshot.sites)} site(s) known for client-name resolution"
            )
            return snapshot
        except Exception as e:  # noqa: BLE001
            logger.warning(f"SentinelOne client map refresh failed: {e}")

    async def _run_brief(self):
        """Run the resident 24h brief (Hermes/reporter) and persist its
        result to system_config, same pattern as Themis/Argus sweeps --
        the frontend/API can read the last brief without re-running it on
        every request. Does not send email/Telegram; capabilities/brief.py's
        run_brief() is reporting-only and has no delivery side effect."""
        logger.info(
            "Running resident brief (owner=%s)...", self.config.brief_owner
        )
        try:
            from capabilities.brief import run_brief

            outcome = await run_brief(window_hours=self.config.brief_interval_hours)
            if outcome.kind != "answered":
                logger.warning(f"Resident brief failed: {outcome.error}")
                self.stats["errors"] += 1
                return outcome

            logger.info(
                f"Resident brief generated at {outcome.generated_at} "
                f"({len(outcome.evidence)} evidence item(s))"
            )

            try:
                from database.config_service import get_config_service
                from dataclasses import asdict

                get_config_service().set_system_config(
                    "brief.last_run",
                    {"owner": self.config.brief_owner, **asdict(outcome)},
                    description="Resident 24h brief (daemon/scheduler.py, capabilities/brief.py)",
                    config_type="monitoring",
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Resident brief: failed to persist result: {e}")

            return outcome
        except Exception as e:  # noqa: BLE001
            logger.error(f"Resident brief errored: {e}")
            self.stats["errors"] += 1

    async def _run_health_check(self):
        """Run system health check."""
        logger.info("Running health check...")
        
        health = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "healthy",
            "components": {}
        }
        
        # Check database
        try:
            if self._data_service:
                findings = self._data_service.get_findings()
                health["components"]["database"] = {
                    "status": "healthy",
                    "findings_count": len(findings) if findings else 0
                }
            else:
                health["components"]["database"] = {"status": "unavailable"}
        except Exception as e:
            health["components"]["database"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"
        
        # Check Claude service
        try:
            if self._claude_service:
                health["components"]["claude"] = {"status": "healthy"}
            else:
                health["components"]["claude"] = {"status": "unavailable"}
        except Exception as e:
            health["components"]["claude"] = {"status": "error", "error": str(e)}
        
        logger.info(f"Health check: {health['status']}")
        return health
