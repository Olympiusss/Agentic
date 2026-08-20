"""Data source polling for the SOC daemon.

Two modes coexist here:

* **Legacy per-source loops** (``_poll_<source>_loop``) — driven by env-var
  intervals in :class:`daemon.config.PollingConfig`. These predate federation
  and remain the path used when the global federation toggle is off.
* **Federation runner** (:class:`daemon.federation.runner.FederationRunner`) —
  spawned alongside the legacy loops. When ``federation.settings.enabled`` is
  true and a source has a ``federation_sources`` row enabled, the legacy loop
  for that source defers (skips that tick) so federation owns the pull.

This co-existence keeps existing deployments working unchanged while the new
opt-in feature is under MVP. Once federation is the default path we can
delete the legacy loops in a follow-up.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

from daemon.config import PollingConfig
from daemon.dedup import RedisDedupSet
from daemon.federation.runner import FederationRunner

logger = logging.getLogger(__name__)


@dataclass
class PollState:
    """Per-source polling cursor.

    Deduplication lives in ``RedisDedupSet`` (see ``DataPoller``);
    this dataclass tracks only the last-poll timestamp used to compute
    query windows.
    """
    last_poll_time: Optional[datetime] = None


class DataPoller:
    """Polls various data sources for new security findings."""
    
    def __init__(self, config: PollingConfig):
        self.config = config
        self._output_queue: Optional[asyncio.Queue] = None

        # Federation runner — owns pull for sources with a federation_sources
        # row when the global federation.settings toggle is on. Always
        # constructed; idle while federation is off.
        self._federation = FederationRunner(output_queue=None)

        # Polling cursors for each source
        self._splunk_state = PollState()
        self._crowdstrike_state = PollState()
        self._sentinelone_state = PollState()
        self._azure_sentinel_state = PollState()
        self._aws_security_hub_state = PollState()
        self._microsoft_defender_state = PollState()
        self._elastic_state = PollState()
        self._generic_state = PollState()

        # Durable per-source dedup sets (Redis-backed)
        self._splunk_dedup = RedisDedupSet("poller:splunk")
        self._crowdstrike_dedup = RedisDedupSet("poller:crowdstrike")
        self._sentinelone_dedup = RedisDedupSet("poller:sentinelone")
        self._azure_sentinel_dedup = RedisDedupSet("poller:azure_sentinel")
        self._aws_security_hub_dedup = RedisDedupSet("poller:aws_security_hub")
        self._microsoft_defender_dedup = RedisDedupSet("poller:microsoft_defender")
        self._elastic_dedup = RedisDedupSet("poller:elastic")
        self._webhook_dedup = RedisDedupSet("poller:webhook")

        # Services (lazy loaded)
        self._splunk_service = None
        self._crowdstrike_service = None
        self._data_service = None
        self._azure_sentinel_service = None
        self._aws_security_hub_service = None
        self._microsoft_defender_service = None
        self._elastic_service = None

        # Stats
        self.stats = {
            "splunk_polls": 0,
            "splunk_findings": 0,
            "crowdstrike_polls": 0,
            "crowdstrike_findings": 0,
            "sentinelone_polls": 0,
            "sentinelone_findings": 0,
            "azure_sentinel_polls": 0,
            "azure_sentinel_findings": 0,
            "aws_security_hub_polls": 0,
            "aws_security_hub_findings": 0,
            "microsoft_defender_polls": 0,
            "microsoft_defender_findings": 0,
            "elastic_polls": 0,
            "elastic_findings": 0,
            "webhook_findings": 0,
            "errors": 0
        }
    
    def set_output_queue(self, queue: asyncio.Queue):
        """Set the output queue for processed findings."""
        self._output_queue = queue
        self._federation.set_output_queue(queue)
    
    def _init_services(self):
        """Initialize data source services."""
        try:
            from core.config import get_integration_config, is_integration_enabled
            
            # Initialize Splunk service if configured
            if is_integration_enabled('splunk'):
                try:
                    from services.splunk_service import SplunkService
                    splunk_config = get_integration_config('splunk')
                    self._splunk_service = SplunkService(
                        server_url=splunk_config.get('server_url', ''),
                        username=splunk_config.get('username', ''),
                        password=splunk_config.get('password', ''),
                        verify_ssl=splunk_config.get('verify_ssl', False)
                    )
                    logger.info("Splunk service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Splunk service: {e}")
            
            # Initialize CrowdStrike service if configured
            if is_integration_enabled('crowdstrike'):
                try:
                    from services.crowdstrike_service import CrowdStrikeService
                    cs_config = get_integration_config('crowdstrike')
                    self._crowdstrike_service = CrowdStrikeService(
                        client_id=cs_config.get('client_id', ''),
                        client_secret=cs_config.get('client_secret', ''),
                        base_url=cs_config.get('base_url', 'https://api.crowdstrike.com')
                    )
                    logger.info("CrowdStrike service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize CrowdStrike service: {e}")
            
            # Initialize Azure Sentinel service if configured
            if is_integration_enabled('azure_sentinel'):
                try:
                    from services.azure_sentinel_ingestion import AzureSentinelIngestion
                    self._azure_sentinel_service = AzureSentinelIngestion()
                    logger.info("Azure Sentinel service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Azure Sentinel service: {e}")
            
            # Initialize AWS Security Hub service if configured
            if is_integration_enabled('aws_security_hub'):
                try:
                    from services.aws_security_hub_ingestion import AWSSecurityHubIngestion
                    self._aws_security_hub_service = AWSSecurityHubIngestion()
                    logger.info("AWS Security Hub service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize AWS Security Hub service: {e}")
            
            # Initialize Microsoft Defender service if configured
            if is_integration_enabled('microsoft_defender'):
                try:
                    from services.microsoft_defender_ingestion import MicrosoftDefenderIngestion
                    self._microsoft_defender_service = MicrosoftDefenderIngestion()
                    logger.info("Microsoft Defender service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Microsoft Defender service: {e}")

            # Initialize Elastic Security service if configured
            if is_integration_enabled('elastic-siem'):
                try:
                    from services.elastic_ingestion import ElasticIngestion
                    self._elastic_service = ElasticIngestion()
                    logger.info("Elastic Security service initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Elastic Security service: {e}")

            # Initialize data service for database access
            from services.database_data_service import DatabaseDataService
            self._data_service = DatabaseDataService()
            
        except Exception as e:
            logger.error(f"Error initializing services: {e}")
    
    async def run(self, shutdown_event: asyncio.Event):
        """Run the polling loop."""
        logger.info("Data poller starting...")
        self._init_services()

        # Create polling tasks
        tasks = []

        # Federation runner is always spawned. It self-gates on the global
        # federation.settings toggle and per-source rows; idle while disabled.
        tasks.append(asyncio.create_task(self._federation.run(shutdown_event)))

        if self._splunk_service:
            tasks.append(asyncio.create_task(
                self._poll_splunk_loop(shutdown_event)
            ))
        
        if self._crowdstrike_service:
            tasks.append(asyncio.create_task(
                self._poll_crowdstrike_loop(shutdown_event)
            ))

        # SentinelOne has no bespoke REST service class (it goes through the
        # shared purple-mcp MCP client, same as the chat-side recipe
        # executor and dashboard service) -- always spawned, same as the
        # federation runner, and self-gates each cycle: if the MCP server
        # isn't configured/connected, _poll_sentinelone logs at debug level
        # and returns quietly rather than erroring the loop.
        tasks.append(asyncio.create_task(
            self._poll_sentinelone_loop(shutdown_event)
        ))

        if self._azure_sentinel_service:
            tasks.append(asyncio.create_task(
                self._poll_azure_sentinel_loop(shutdown_event)
            ))
        
        if self._aws_security_hub_service:
            tasks.append(asyncio.create_task(
                self._poll_aws_security_hub_loop(shutdown_event)
            ))
        
        if self._microsoft_defender_service:
            tasks.append(asyncio.create_task(
                self._poll_microsoft_defender_loop(shutdown_event)
            ))

        if self._elastic_service:
            tasks.append(asyncio.create_task(
                self._poll_elastic_loop(shutdown_event)
            ))

        if self.config.webhook_enabled:
            tasks.append(asyncio.create_task(
                self._run_webhook_server(shutdown_event)
            ))
        
        if not tasks:
            logger.warning("No data sources configured for polling")
            # Just wait for shutdown
            await shutdown_event.wait()
            return
        
        # Wait for all tasks or shutdown
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Polling tasks cancelled")
    
    async def _poll_splunk_loop(self, shutdown_event: asyncio.Event):
        """Poll Splunk for new alerts on interval."""
        logger.info(f"Splunk polling loop started (interval: {self.config.splunk_interval}s)")
        
        while not shutdown_event.is_set():
            try:
                await self._poll_splunk()
                self._splunk_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"Splunk polling error: {e}")
                self.stats["errors"] += 1
            
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self.config.splunk_interval
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling
    
    async def _poll_splunk(self):
        """Poll Splunk for new security alerts."""
        if not self._splunk_service:
            return
        if self._federation.is_active_for("splunk"):
            return  # Federation owns this source while globally + per-source enabled
        
        self.stats["splunk_polls"] += 1
        logger.debug("Polling Splunk for new alerts...")
        
        # Calculate time range
        lookback_minutes = max(self.config.splunk_interval // 60 + 1, 5)
        earliest_time = f"-{lookback_minutes}m"
        
        # Query for notable events / security alerts
        queries = [
            'index=notable | head 100',
            'index=security sourcetype=*:alert* | head 100',
            '`notable` | head 100'
        ]
        
        findings = []
        for query in queries:
            try:
                results = self._splunk_service.search(
                    query=query,
                    earliest_time=earliest_time,
                    latest_time="now",
                    max_count=100
                )
                if results:
                    findings.extend(results)
                    break  # Use first successful query
            except Exception as e:
                logger.debug(f"Splunk query failed: {query} - {e}")
                continue
        
        # Process findings
        new_count = 0
        for event in findings:
            finding = self._splunk_event_to_finding(event)
            if finding and not await self._splunk_dedup.is_processed(finding['finding_id']):
                await self._enqueue_finding(finding, "splunk")
                await self._splunk_dedup.mark_processed(finding['finding_id'])
                new_count += 1
        
        if new_count > 0:
            logger.info(f"Polled {new_count} new findings from Splunk")
            self.stats["splunk_findings"] += new_count
    
    def _splunk_event_to_finding(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert Splunk event to finding format."""
        import uuid
        
        # Extract key fields
        event_id = event.get('_cd') or event.get('event_id') or str(uuid.uuid4())
        finding_id = f"splunk-{event_id[:32]}"
        
        # Determine severity
        severity_raw = event.get('urgency') or event.get('severity') or 'medium'
        severity_map = {
            'critical': 'critical', 'high': 'high', 'medium': 'medium',
            'low': 'low', 'info': 'low', 'informational': 'low'
        }
        severity = severity_map.get(severity_raw.lower(), 'medium')
        
        # Extract entity context
        entity_context = {
            'src_ips': [],
            'dest_ips': [],
            'hostnames': [],
            'usernames': []
        }
        
        for ip_field in ['src_ip', 'src', 'source_ip']:
            if event.get(ip_field):
                entity_context['src_ips'].append(event[ip_field])
        
        for ip_field in ['dest_ip', 'dest', 'destination_ip']:
            if event.get(ip_field):
                entity_context['dest_ips'].append(event[ip_field])
        
        for host_field in ['host', 'hostname', 'src_host', 'dest_host']:
            if event.get(host_field):
                entity_context['hostnames'].append(event[host_field])
        
        for user_field in ['user', 'username', 'src_user']:
            if event.get(user_field):
                entity_context['usernames'].append(event[user_field])
        
        return {
            'finding_id': finding_id,
            'data_source': 'splunk',
            'timestamp': event.get('_time') or datetime.utcnow().isoformat(),
            'severity': severity,
            'status': 'new',
            'title': event.get('search_name') or event.get('rule_name') or 'Splunk Alert',
            'description': event.get('description') or event.get('_raw', '')[:500],
            'entity_context': entity_context,
            'raw_event': event,
            'anomaly_score': 0.5,  # Default score
            'mitre_predictions': {},
            'embedding': []
        }
    
    async def _poll_crowdstrike_loop(self, shutdown_event: asyncio.Event):
        """Poll CrowdStrike for new detections on interval."""
        logger.info(f"CrowdStrike polling loop started (interval: {self.config.crowdstrike_interval}s)")
        
        while not shutdown_event.is_set():
            try:
                await self._poll_crowdstrike()
                self._crowdstrike_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"CrowdStrike polling error: {e}")
                self.stats["errors"] += 1
            
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self.config.crowdstrike_interval
                )
                break
            except asyncio.TimeoutError:
                pass
    
    async def _poll_crowdstrike(self):
        """Poll CrowdStrike for new detections."""
        if not self._crowdstrike_service:
            return
        if self._federation.is_active_for("crowdstrike"):
            return
        
        self.stats["crowdstrike_polls"] += 1
        logger.debug("Polling CrowdStrike for new detections...")
        
        try:
            # Get recent detections
            lookback_minutes = max(self.config.crowdstrike_interval // 60 + 1, 5)
            since = datetime.utcnow() - timedelta(minutes=lookback_minutes)
            
            detections = self._crowdstrike_service.get_detections(
                filter_query=f"created_timestamp:>='{since.isoformat()}Z'",
                limit=100
            )
            
            if not detections:
                return
            
            new_count = 0
            for detection in detections:
                finding = self._crowdstrike_detection_to_finding(detection)
                if finding and not await self._crowdstrike_dedup.is_processed(finding['finding_id']):
                    await self._enqueue_finding(finding, "crowdstrike")
                    await self._crowdstrike_dedup.mark_processed(finding['finding_id'])
                    new_count += 1
            
            if new_count > 0:
                logger.info(f"Polled {new_count} new detections from CrowdStrike")
                self.stats["crowdstrike_findings"] += new_count
                
        except Exception as e:
            logger.error(f"CrowdStrike API error: {e}")
            raise
    
    def _crowdstrike_detection_to_finding(self, detection: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert CrowdStrike detection to finding format."""
        detection_id = detection.get('detection_id', '')
        if not detection_id:
            return None
        
        finding_id = f"cs-{detection_id[:32]}"
        
        # Map severity
        severity_raw = detection.get('max_severity_displayname', 'Medium')
        severity_map = {
            'Critical': 'critical', 'High': 'high', 'Medium': 'medium',
            'Low': 'low', 'Informational': 'low'
        }
        severity = severity_map.get(severity_raw, 'medium')
        
        # Extract behaviors and tactics
        behaviors = detection.get('behaviors', [])
        mitre_predictions = {}
        for behavior in behaviors:
            tactic = behavior.get('tactic')
            technique = behavior.get('technique')
            if technique:
                mitre_predictions[technique] = 0.9  # High confidence from EDR
        
        # Entity context
        device = detection.get('device', {})
        entity_context = {
            'src_ips': [device.get('local_ip')] if device.get('local_ip') else [],
            'hostnames': [device.get('hostname')] if device.get('hostname') else [],
            'usernames': [detection.get('user_name')] if detection.get('user_name') else [],
            'device_id': device.get('device_id')
        }
        
        return {
            'finding_id': finding_id,
            'data_source': 'crowdstrike',
            'timestamp': detection.get('created_timestamp') or datetime.utcnow().isoformat(),
            'severity': severity,
            'status': 'new',
            'title': detection.get('scenario') or 'CrowdStrike Detection',
            'description': detection.get('description', ''),
            'entity_context': entity_context,
            'raw_event': detection,
            'anomaly_score': detection.get('max_confidence', 50) / 100.0,
            'mitre_predictions': mitre_predictions,
            'embedding': []
        }
    
    async def _poll_sentinelone_loop(self, shutdown_event: asyncio.Event):
        """Poll SentinelOne for new alerts on interval."""
        interval = self.config.sentinelone_interval
        logger.info(f"SentinelOne polling loop started (interval: {interval}s)")

        while not shutdown_event.is_set():
            try:
                await self._poll_sentinelone()
            except Exception as e:
                logger.error(f"SentinelOne polling error: {e}")
                self.stats["errors"] += 1

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling

    async def _poll_sentinelone(self):
        """Poll SentinelOne (via the shared purple-mcp MCP client -- same
        client services/sentinelone_recipe_executor.py and
        services/sentinelone_dashboard_service.py use) for alerts within a
        rolling lookback window, converts each to a Finding, and fires a
        new-threat notification per newly-ingested alert.

        Rewritten 2026-08-19 from cursor-based incremental polling to a
        fixed rolling window (explicit user request, after live-confirming
        the cursor design's fundamental limitation): SentinelOne's alert
        pipeline has a genuine, multi-hour, VARIABLE-length lag between an
        alert's detectedAt and when it becomes filterable via ANY
        datetime field at all (confirmed live 2026-08-19 -- not a
        filter-field choice; see the field-comparison note in
        data/knowledge/sentinelone/mcp_tools.md). A cursor that only ever
        advances forward can never self-heal from that: once the cursor
        passes an alert's eventual index time, that alert is excluded
        from every future query, permanently, by construction -- this
        already caused confirmed, real alert loss earlier the same day.
        A fixed rolling window (`now - sentinelone_lookback_hours` to
        `now`) re-covers the ENTIRE lookback period on every single
        cycle, so a slow-to-index alert gets caught on whichever cycle it
        finally becomes visible, not just the one immediately after
        detection. Re-fetching the same ~N hours of data every interval
        is intentional, not wasteful -- alert-ID-based dedup (daemon/
        dedup.py's RedisDedupSet, backed by services/ingestion_service.py's
        DB-layer idempotency check) makes the overlap safe; most alerts
        in most cycles are expected, routine re-fetches of already-
        processed data, not a bug.

        Self-gating, same style as _status_count/_vuln_severity_count in
        the dashboard service: any MCP error (not configured, not
        connected, tool error) is logged and the cycle is skipped quietly
        rather than raising -- this loop is always spawned regardless of
        whether SentinelOne is configured in this environment (mirrors
        the federation runner's "always spawned, self-gates" pattern)."""
        import json as _json

        from services import sentinelone_recipe_executor as executor

        self.stats["sentinelone_polls"] += 1

        since_dt = datetime.utcnow() - timedelta(hours=self.config.sentinelone_lookback_hours)
        since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        start_ms, err = await executor._call("iso_to_unix_timestamp", {"iso_datetime": since_iso})
        if err:
            # Bug found 2026-08-18: this was logged at .debug() while
            # DAEMON_LOG_LEVEL defaults to INFO, so a real, repeating
            # per-cycle failure here was completely invisible in
            # production logs -- the live daemon polled every 20s for
            # over an hour without ever ingesting a real alert (including
            # two CRITICAL ransomware detections) and nothing showed up
            # in `docker logs` to explain why. Every failure path in this
            # function is raised to .warning() for the same reason.
            logger.warning(f"SentinelOne poll skipped (iso_to_unix_timestamp failed): {err}")
            return
        try:
            start_ms = int(start_ms)
        except (TypeError, ValueError):
            logger.warning(f"SentinelOne poll skipped: iso_to_unix_timestamp returned non-numeric {start_ms!r}")
            return

        # Full pagination within one cycle (explicit user request): a
        # fixed multi-hour window at real alert volumes can genuinely
        # exceed the API's first=100-per-page cap (confirmed live during
        # the original 9-day-stale-cursor backlog catch-up, total=657 in
        # one window) -- unlike the old cursor design, there's no "next
        # cycle naturally covers the rest" fallback here, since the
        # window doesn't advance; every cycle must fetch everything in
        # its own window or silently under-cover it forever. Paginates
        # via the last edge's own `cursor` field, not `pageInfo`
        # (confirmed live 2026-08-19: pageInfo comes back empty from this
        # API; the edge-level cursor does work for `after`).
        all_rows: list[dict] = []
        after_cursor: Optional[str] = None
        total = 0
        for _ in range(20):  # hard ceiling -- never loop forever on a pathological response
            params = {
                "filters": _json.dumps([{"fieldId": "lastSeenAt", "filterType": "datetime_range", "start": start_ms}]),
                "first": 100,
            }
            if after_cursor:
                params["after"] = after_cursor
            result, err = await executor._call("search_alerts", params)
            if err or not isinstance(result, dict):
                logger.warning(f"SentinelOne search_alerts failed: {err!r} (result type: {type(result).__name__})")
                break
            total = executor._total_count(result) or 0
            raw_edges = result.get("edges") or []
            all_rows.extend(executor._edges(result))
            if len(all_rows) >= total or not raw_edges:
                break
            last_cursor = raw_edges[-1].get("cursor") if isinstance(raw_edges[-1], dict) else None
            if not last_cursor:
                break
            after_cursor = last_cursor

        if total > len(all_rows):
            logger.warning(
                f"SentinelOne poll: {total} alert(s) in the {self.config.sentinelone_lookback_hours}h rolling "
                f"window, only fetched {len(all_rows)} after pagination -- consider a shorter lookback or interval"
            )

        if all_rows:
            logger.info(
                f"SentinelOne poll: {len(all_rows)} row(s) fetched this cycle "
                f"(rolling {self.config.sentinelone_lookback_hours}h window)"
            )

        new_count = 0
        for alert in all_rows:
            alert_id_for_log = alert.get("id")
            finding = self._sentinelone_alert_to_finding(alert)
            if not finding:
                logger.warning(f"SentinelOne poll: alert {alert_id_for_log!r} -> _sentinelone_alert_to_finding returned None, skipping")
                continue
            already_processed = await self._sentinelone_dedup.is_processed(finding["finding_id"])
            if already_processed:
                # Expected and routine under the rolling-window design --
                # most of every window overlaps the last cycle's window,
                # so logging this per-alert would flood the logs for no
                # diagnostic value (unlike the old cursor design, where
                # this branch firing was itself a meaningful signal).
                continue
            try:
                await self._enqueue_finding(finding, "sentinelone")
                await self._sentinelone_dedup.mark_processed(finding["finding_id"])
                logger.info(f"SentinelOne poll: {finding['finding_id']} enqueued and dedup-marked successfully")
            except Exception as e:  # noqa: BLE001
                logger.error(f"SentinelOne poll: {finding['finding_id']} enqueue/dedup-mark FAILED: {e}", exc_info=True)
                continue
            new_count += 1

            # Two-phase notification (explicit user request, 2026-08-05):
            # Phase 1 fires HERE, immediately, straight off the raw alert
            # dict -- no Deep Visibility, no reputation lookups, nothing
            # that takes real time, so the user hears about a new alert in
            # well under a second. Phase 2 (the full investigative report)
            # fires from inside the synergy pipeline once Venus/Athena
            # finish -- capabilities/synergy.py's _notify_investigative_report
            # needs their hash/process/reputation artifacts, which don't
            # exist yet at raw ingestion. Both fire-and-forget so neither
            # blocks the polling loop.
            from capabilities.synergy import notify_new_alert_immediate

            asyncio.create_task(notify_new_alert_immediate(finding["finding_id"], alert))
            asyncio.create_task(self._dispatch_synergy_pipeline(
                finding["finding_id"], finding["entity_context"].get("storyline_id"), alert.get("id"),
                alert.get("detectedAt"),
            ))

        if new_count > 0:
            logger.info(f"Polled {new_count} new alerts from SentinelOne")
            self.stats["sentinelone_findings"] += new_count

    def _sentinelone_alert_to_finding(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a SentinelOne Alert (search_alerts edge/node shape --
        confirmed live: id, severity, status, name, description, detectedAt,
        classification, confidenceLevel, detectionSource{product,vendor},
        asset{id,name,type}, storylineId) to the finding dict shape shared
        by every poller source in this file."""
        alert_id = alert.get("id")
        if not alert_id:
            return None

        finding_id = f"s1-{alert_id}"

        severity_raw = (alert.get("severity") or "MEDIUM").upper()
        severity_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        severity = severity_map.get(severity_raw, "medium")

        confidence_raw = (alert.get("confidenceLevel") or "").upper()
        confidence_score_map = {"MALICIOUS": 0.95, "SUSPICIOUS": 0.6, "N/A": 0.4}
        anomaly_score = confidence_score_map.get(confidence_raw, 0.5)

        asset = alert.get("asset") or {}
        detection_source = alert.get("detectionSource") or {}
        entity_context = {
            "hostnames": [asset["name"]] if asset.get("name") else [],
            "device_id": asset.get("id"),
            "storyline_id": alert.get("storylineId"),
            "classification": alert.get("classification"),
            "detection_engine": detection_source.get("product"),
            # Bug found live 2026-08-18: Finding has no `title` column at
            # all (database/models.py) -- the "title" key set below on the
            # returned finding dict is silently discarded on ingest, so
            # every downstream reader (capabilities/synergy.py's Phase 2
            # report included) always saw title=None and fell back to the
            # long, verbose `description` text as the report subject/
            # greeting, even though SentinelOne's own alert.name is a
            # short, clean label (confirmed live: "Potential PowerShell
            # Encoded Command" vs. the multi-sentence description).
            # entity_context IS a real persisted JSONB column, so storing
            # it here (redundant with "title" below, but actually
            # retrievable after a DB round-trip) is the fix that doesn't
            # require a schema migration.
            "alert_name": alert.get("name"),
        }

        return {
            "finding_id": finding_id,
            "data_source": "sentinelone",
            "timestamp": alert.get("detectedAt") or alert.get("firstSeenAt") or datetime.utcnow().isoformat(),
            "severity": severity,
            "status": "new",
            "title": alert.get("name") or "SentinelOne Alert",
            "description": alert.get("description") or "",
            "entity_context": entity_context,
            "raw_event": alert,
            "anomaly_score": anomaly_score,
            "mitre_predictions": {},
            "embedding": [],
        }

    async def _dispatch_synergy_pipeline(
        self, finding_id: str, storyline_id: Optional[str], alert_id: Optional[str], detected_at: Optional[str] = None,
    ) -> None:
        """Waits for FindingProcessor to actually persist the Finding row
        (it stores first, then triages/enriches -- see daemon/processor.py
        _process_finding) before running Zeus's synergy chain, since the
        chain's blackboard writes (capabilities/synergy.py's
        _write_blackboard) need a real row to attach ai_enrichment to.
        Bounded retry, not a fixed sleep -- processing time varies with
        queue depth. Polls every 0.5s, not 2s (explicit user request,
        2026-08-05: full investigative report within at most 3 minutes of
        the alert -- catching the persisted row sooner on average matters
        against that budget), same ~30s ceiling. Gives up quietly after
        that (the finding still gets triaged normally by the existing
        pipeline either way; it just won't have the deeper synergy
        analysis attached). `detected_at` (the alert's own detection
        time, passed through to the phase-2 notifier for SLA logging)."""
        from services.database_data_service import DatabaseDataService
        from capabilities.synergy import run_synergy_pipeline

        svc = DatabaseDataService()
        for _ in range(60):
            await asyncio.sleep(0.5)
            if svc.get_finding(finding_id):
                break
        else:
            logger.warning(f"Synergy pipeline skipped for {finding_id}: finding row never appeared within 30s")
            return

        try:
            outcome = await run_synergy_pipeline(finding_id, storyline_id, alert_id, detected_at)
            logger.info(
                f"Synergy pipeline complete for {finding_id}: verdict={outcome.highest_verdict}, "
                f"{len(outcome.steps)} step(s), {len(outcome.compliance_notes)} compliance note(s)"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Synergy pipeline failed for {finding_id}: {e}")

    async def _run_webhook_server(self, shutdown_event: asyncio.Event):
        """Run a simple webhook server for external ingestion."""
        from aiohttp import web
        
        async def handle_webhook(request: web.Request) -> web.Response:
            """Handle incoming webhook data."""
            try:
                data = await request.json()
                
                # Support batch or single finding
                findings = data if isinstance(data, list) else [data]
                
                count = 0
                for finding_data in findings:
                    finding_id = finding_data.get('finding_id')
                    if not finding_id:
                        import uuid
                        finding_id = f"webhook-{uuid.uuid4().hex[:16]}"
                        finding_data['finding_id'] = finding_id
                    
                    if not await self._webhook_dedup.is_processed(finding_id):
                        finding_data['data_source'] = finding_data.get('data_source', 'webhook')
                        await self._enqueue_finding(finding_data, "webhook")
                        await self._webhook_dedup.mark_processed(finding_id)
                        count += 1
                
                self.stats["webhook_findings"] += count
                return web.json_response({"status": "ok", "ingested": count})
            
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return web.json_response({"error": str(e)}, status=400)
        
        async def health_check(request: web.Request) -> web.Response:
            """Health check endpoint."""
            return web.json_response({"status": "healthy", "stats": self.stats})
        
        app = web.Application()
        app.router.add_post('/ingest', handle_webhook)
        app.router.add_post('/webhook', handle_webhook)
        app.router.add_get('/health', health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.config.webhook_port)
        
        logger.info(f"Webhook server starting on port {self.config.webhook_port}")
        await site.start()
        
        # Wait for shutdown
        await shutdown_event.wait()
        
        await runner.cleanup()
        logger.info("Webhook server stopped")
    
    async def _enqueue_finding(self, finding: Dict[str, Any], source: str):
        """Add finding to output queue for processing."""
        if self._output_queue:
            await self._output_queue.put({
                "type": "finding",
                "source": source,
                "data": finding,
                "timestamp": datetime.utcnow().isoformat()
            })
            logger.debug(f"Enqueued finding {finding.get('finding_id')} from {source}")
        else:
            # No queue, store directly
            if self._data_service:
                try:
                    from services.ingestion_service import IngestionService
                    ingestion = IngestionService()
                    ingestion.ingest_finding(finding)
                except Exception as e:
                    logger.error(f"Failed to store finding: {e}")
    
    async def _poll_azure_sentinel_loop(self, shutdown_event: asyncio.Event):
        """Poll Azure Sentinel for new incidents on interval."""
        interval = self.config.splunk_interval  # Use same interval as Splunk
        logger.info(f"Azure Sentinel polling loop started (interval: {interval}s)")
        
        while not shutdown_event.is_set():
            try:
                await self._poll_azure_sentinel()
                self._azure_sentinel_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"Azure Sentinel polling error: {e}")
                self.stats["errors"] += 1
            
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling
    
    async def _poll_azure_sentinel(self):
        """Poll Azure Sentinel for new incidents."""
        if not self._azure_sentinel_service:
            return
        if self._federation.is_active_for("azure_sentinel"):
            return
        
        self.stats["azure_sentinel_polls"] += 1
        logger.debug("Polling Azure Sentinel for new incidents...")
        
        try:
            # Use ingestion service
            result = self._azure_sentinel_service.ingest_alerts(limit=100)
            
            if result.get("success"):
                ingested = result.get("ingested", 0)
                self.stats["azure_sentinel_findings"] += ingested
                logger.info(f"Azure Sentinel: ingested {ingested} incidents")
            else:
                logger.error(f"Azure Sentinel ingestion failed: {result.get('errors')}")
        except Exception as e:
            logger.error(f"Error polling Azure Sentinel: {e}")
    
    async def _poll_aws_security_hub_loop(self, shutdown_event: asyncio.Event):
        """Poll AWS Security Hub for new findings on interval."""
        interval = self.config.splunk_interval  # Use same interval as Splunk
        logger.info(f"AWS Security Hub polling loop started (interval: {interval}s)")
        
        while not shutdown_event.is_set():
            try:
                await self._poll_aws_security_hub()
                self._aws_security_hub_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"AWS Security Hub polling error: {e}")
                self.stats["errors"] += 1
            
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling
    
    async def _poll_aws_security_hub(self):
        """Poll AWS Security Hub for new findings."""
        if not self._aws_security_hub_service:
            return
        if self._federation.is_active_for("aws_security_hub"):
            return
        
        self.stats["aws_security_hub_polls"] += 1
        logger.debug("Polling AWS Security Hub for new findings...")
        
        try:
            # Use ingestion service
            result = self._aws_security_hub_service.ingest_alerts(limit=100)
            
            if result.get("success"):
                ingested = result.get("ingested", 0)
                self.stats["aws_security_hub_findings"] += ingested
                logger.info(f"AWS Security Hub: ingested {ingested} findings")
            else:
                logger.error(f"AWS Security Hub ingestion failed: {result.get('errors')}")
        except Exception as e:
            logger.error(f"Error polling AWS Security Hub: {e}")
    
    async def _poll_microsoft_defender_loop(self, shutdown_event: asyncio.Event):
        """Poll Microsoft Defender for new alerts on interval."""
        interval = self.config.splunk_interval  # Use same interval as Splunk
        logger.info(f"Microsoft Defender polling loop started (interval: {interval}s)")
        
        while not shutdown_event.is_set():
            try:
                await self._poll_microsoft_defender()
                self._microsoft_defender_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"Microsoft Defender polling error: {e}")
                self.stats["errors"] += 1
            
            # Wait for interval or shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Continue polling
    
    async def _poll_microsoft_defender(self):
        """Poll Microsoft Defender for new alerts."""
        if not self._microsoft_defender_service:
            return
        if self._federation.is_active_for("microsoft_defender"):
            return
        
        self.stats["microsoft_defender_polls"] += 1
        logger.debug("Polling Microsoft Defender for new alerts...")
        
        try:
            # Use ingestion service
            result = self._microsoft_defender_service.ingest_alerts(limit=100)
            
            if result.get("success"):
                ingested = result.get("ingested", 0)
                self.stats["microsoft_defender_findings"] += ingested
                logger.info(f"Microsoft Defender: ingested {ingested} alerts")
            else:
                logger.error(f"Microsoft Defender ingestion failed: {result.get('errors')}")
        except Exception as e:
            logger.error(f"Error polling Microsoft Defender: {e}")

    async def _poll_elastic_loop(self, shutdown_event: asyncio.Event):
        """Poll Elastic Security for new detection alerts on interval."""
        interval = self.config.splunk_interval  # Use same interval as Splunk
        logger.info(f"Elastic Security polling loop started (interval: {interval}s)")

        while not shutdown_event.is_set():
            try:
                await self._poll_elastic()
                self._elastic_state.last_poll_time = datetime.utcnow()
            except Exception as e:
                logger.error(f"Elastic Security polling error: {e}")
                self.stats["errors"] += 1

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    async def _poll_elastic(self):
        """Poll Elastic Security for new detection alerts."""
        if not self._elastic_service:
            return
        if self._federation.is_active_for("elastic"):
            return

        self.stats["elastic_polls"] += 1
        logger.debug("Polling Elastic Security for new alerts...")

        try:
            lookback_minutes = max(self.config.splunk_interval // 60 + 1, 5)
            start_time = datetime.utcnow() - timedelta(minutes=lookback_minutes)

            alerts = await self._elastic_service.fetch_alerts(
                start_time=start_time, limit=100
            )

            new_count = 0
            for alert in alerts:
                finding = self._elastic_service.transform_alert_to_finding(alert)
                if finding and not await self._elastic_dedup.is_processed(finding["finding_id"]):
                    await self._enqueue_finding(finding, "elastic")
                    await self._elastic_dedup.mark_processed(finding["finding_id"])
                    new_count += 1

            if new_count > 0:
                logger.info(f"Polled {new_count} new findings from Elastic Security")
                self.stats["elastic_findings"] += new_count

        except Exception as e:
            logger.error(f"Elastic Security API error: {e}")
            raise
