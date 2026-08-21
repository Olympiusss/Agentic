"""
Database service layer for Sentry Agentic.

Provides high-level database operations for cases, findings, and related entities.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import Session

from database.models import Case, Finding, SketchMapping, AttackLayer, AIDecisionLog, LLMJobDeadLetter, AgentTaskState, case_findings, Client, CaseSLA, ClientApiCredential, User
from database.connection import get_db_manager

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service layer for database operations."""
    
    def __init__(self):
        """Initialize the database service."""
        self.db_manager = get_db_manager()
    
    # ========== Finding Operations ==========
    
    def create_finding(
        self,
        finding_id: str,
        embedding: List[float],
        mitre_predictions: dict,
        anomaly_score: float,
        timestamp: datetime,
        data_source: str,
        **kwargs
    ) -> Optional[Finding]:
        """
        Create a new finding.
        
        Args:
            finding_id: Unique finding ID
            embedding: 768-dimensional embedding vector
            mitre_predictions: MITRE ATT&CK predictions
            anomaly_score: Anomaly score (0-1)
            timestamp: Finding timestamp
            data_source: Data source type
            **kwargs: Additional fields (entity_context, evidence_links, cluster_id, severity, status)
        
        Returns:
            Created Finding object or None if failed
        """
        try:
            with self.db_manager.session_scope() as session:
                finding = Finding(
                    finding_id=finding_id,
                    embedding=embedding,
                    mitre_predictions=mitre_predictions,
                    anomaly_score=anomaly_score,
                    timestamp=timestamp,
                    data_source=data_source,
                    external_id=kwargs.get('external_id'),
                    description=kwargs.get('description'),
                    entity_context=kwargs.get('entity_context'),
                    evidence_links=kwargs.get('evidence_links'),
                    cluster_id=kwargs.get('cluster_id'),
                    severity=kwargs.get('severity'),
                    status=kwargs.get('status', 'new'),
                    client_id=kwargs.get('client_id')
                )
                session.add(finding)
                session.flush()
                session.refresh(finding)
                logger.info(f"Created finding: {finding_id}")
                return finding
        except Exception as e:
            logger.error(f"Error creating finding {finding_id}: {e}")
            return None
    
    def get_finding(self, finding_id: str) -> Optional[Finding]:
        """
        Get a finding by ID.
        
        Args:
            finding_id: Finding ID
        
        Returns:
            Finding object or None if not found
        """
        try:
            with self.db_manager.session_scope() as session:
                finding = session.get(Finding, finding_id)
                if finding:
                    # Detach from session to avoid lazy loading issues
                    session.expunge(finding)
                return finding
        except Exception as e:
            logger.error(f"Error getting finding {finding_id}: {e}")
            return None
    
    def get_findings(
        self,
        severity: Optional[str] = None,
        data_source: Optional[str] = None,
        cluster_id: Optional[str] = None,
        min_anomaly_score: Optional[float] = None,
        status: Optional[str] = None,
        search_query: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
        client_id: Optional[str] = None,
    ) -> List[Finding]:
        """
        Get findings with optional filters, search, and pagination.

        Args:
            severity: Filter by severity
            data_source: Filter by data source
            cluster_id: Filter by cluster ID
            min_anomaly_score: Minimum anomaly score
            status: Filter by status
            search_query: Text search across finding_id, description, entity_context
            limit: Maximum number of results
            offset: Offset for pagination
            sort_by: Column to sort by (timestamp, anomaly_score, severity)
            sort_order: Sort direction (asc, desc)
            client_id: Filter by client (unified-schema foundation, 2026-08-20).
                Callers enforcing role-client scoping must derive this from the
                authenticated user server-side -- see backend/api/findings.py --
                never from a caller-supplied value for that role.

        Returns:
            List of Finding objects
        """
        try:
            with self.db_manager.session_scope() as session:
                query = select(Finding)

                filters = []
                if severity:
                    filters.append(Finding.severity == severity)
                if data_source:
                    filters.append(Finding.data_source == data_source)
                if cluster_id is not None:
                    filters.append(Finding.cluster_id == cluster_id)
                if min_anomaly_score is not None:
                    filters.append(Finding.anomaly_score >= min_anomaly_score)
                if status:
                    filters.append(Finding.status == status)
                if client_id is not None:
                    filters.append(Finding.client_id == client_id)
                if search_query:
                    from sqlalchemy import cast, String
                    search_clauses = [
                        Finding.finding_id.ilike(f"%{search_query}%"),
                        cast(Finding.entity_context, String).ilike(f"%{search_query}%"),
                    ]
                    if hasattr(Finding, 'description'):
                        search_clauses.append(Finding.description.ilike(f"%{search_query}%"))
                    filters.append(or_(*search_clauses))
                
                if filters:
                    query = query.where(and_(*filters))
                
                sort_column_map = {
                    "timestamp": Finding.timestamp,
                    "anomaly_score": Finding.anomaly_score,
                    "severity": Finding.severity,
                    "data_source": Finding.data_source,
                    "status": Finding.status,
                }
                sort_col = sort_column_map.get(sort_by, Finding.timestamp)
                if sort_order == "asc":
                    query = query.order_by(sort_col.asc())
                else:
                    query = query.order_by(sort_col.desc())

                query = query.limit(limit).offset(offset)
                
                findings = session.execute(query).scalars().all()
                
                for finding in findings:
                    session.expunge(finding)
                
                return findings
        except Exception as e:
            logger.error(f"Error getting findings: {e}")
            return []
    
    def count_findings(
        self,
        severity: Optional[str] = None,
        data_source: Optional[str] = None,
        cluster_id: Optional[str] = None,
        min_anomaly_score: Optional[float] = None,
        status: Optional[str] = None,
        search_query: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> int:
        """
        Count findings matching the given filters without loading rows.
        """
        try:
            with self.db_manager.session_scope() as session:
                query = select(func.count()).select_from(Finding)

                filters = []
                if severity:
                    filters.append(Finding.severity == severity)
                if data_source:
                    filters.append(Finding.data_source == data_source)
                if cluster_id is not None:
                    filters.append(Finding.cluster_id == cluster_id)
                if min_anomaly_score is not None:
                    filters.append(Finding.anomaly_score >= min_anomaly_score)
                if status:
                    filters.append(Finding.status == status)
                if client_id is not None:
                    filters.append(Finding.client_id == client_id)
                if search_query:
                    from sqlalchemy import cast, String
                    filters.append(
                        or_(
                            Finding.finding_id.ilike(f"%{search_query}%"),
                            Finding.description.ilike(f"%{search_query}%") if hasattr(Finding, 'description') else Finding.finding_id.ilike(f"%{search_query}%"),
                            cast(Finding.entity_context, String).ilike(f"%{search_query}%"),
                        )
                    )

                if filters:
                    query = query.where(and_(*filters))

                return session.execute(query).scalar() or 0
        except Exception as e:
            logger.error(f"Error counting findings: {e}")
            return 0

    def get_cross_tenant_pattern_classifications(
        self, lookback_hours: int = 72, min_distinct_clients: int = 2
    ) -> set:
        """Coarse v1 approximation of cross-tenant pattern detection for
        the Unified Priority Queue (Analyst Workbench, 2026-08-20) --
        NOT real hash/IP/TTP correlation. capabilities/correlator.py's
        Ariadne only clusters SAME-tenant SentinelOne alerts by
        storylineId/host/classification into unstructured prose inside
        one finding's ai_enrichment blob; it isn't a queryable
        cross-finding structure, and raw Finding.cluster_id values are
        SentinelOne per-tenant GUIDs that will essentially never collide
        across clients. This instead groups on
        entity_context->>'classification' (falling back to
        entity_context->>'alert_name') within a lookback window and
        flags values seen across >= min_distinct_clients distinct
        client_ids.

        Returns:
            Set of classification/alert_name strings seen across
            multiple clients recently.
        """
        try:
            with self.db_manager.session_scope() as session:
                classification_expr = func.coalesce(
                    Finding.entity_context["classification"].astext,
                    Finding.entity_context["alert_name"].astext,
                )
                cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)
                query = (
                    select(classification_expr)
                    .where(
                        classification_expr.isnot(None),
                        Finding.client_id.isnot(None),
                        Finding.timestamp >= cutoff,
                    )
                    .group_by(classification_expr)
                    .having(func.count(func.distinct(Finding.client_id)) >= min_distinct_clients)
                )
                return {row[0] for row in session.execute(query).all()}
        except Exception as e:
            logger.error(f"Error computing cross-tenant pattern classifications: {e}")
            return set()

    def get_priority_queue_candidates(
        self,
        client_id: Optional[str] = None,
        exclude_statuses: Optional[List[str]] = None,
        candidate_limit: int = 2000,
    ) -> List[dict]:
        """Findings the agent has already processed (i.e. have >=1
        AIDecisionLog row) for the Unified Priority Queue (Analyst
        Workbench, 2026-08-20), joined 1:1 to their MOST RECENT decision
        by timestamp (mirrors FindingDetailDialog.tsx's client-side
        `latestDecision` selection), their Client.display_name, and --
        when the decision escalated into a case -- that case's status
        and CaseSLA fields. Findings the agent hasn't touched at all are
        deliberately excluded (v1 scope: this is a queue of AI-drafted
        work, not the raw findings feed -- see get_findings above for
        that). Bounded by candidate_limit (ordered by Finding.timestamp
        desc) rather than true DB-side pagination, because
        priority_score/segment are computed in Python per-row after this
        fetch -- see backend/api/findings.py's get_priority_queue.
        """
        try:
            with self.db_manager.session_scope() as session:
                latest_decision_sq = (
                    select(
                        AIDecisionLog.finding_id.label("finding_id"),
                        AIDecisionLog.decision_id.label("decision_id"),
                        AIDecisionLog.agent_id.label("agent_id"),
                        AIDecisionLog.confidence_score.label("confidence_score"),
                        AIDecisionLog.reasoning.label("reasoning"),
                        AIDecisionLog.decision_action.label("decision_action"),
                        AIDecisionLog.linked_case_id.label("linked_case_id"),
                        AIDecisionLog.timestamp.label("decision_timestamp"),
                        func.row_number().over(
                            partition_by=AIDecisionLog.finding_id,
                            order_by=AIDecisionLog.timestamp.desc(),
                        ).label("rn"),
                    )
                    .where(AIDecisionLog.finding_id.isnot(None))
                    .subquery("latest_decision")
                )
                ld = (
                    select(latest_decision_sq)
                    .where(latest_decision_sq.c.rn == 1)
                    .subquery("ld")
                )

                query = (
                    select(
                        Finding,
                        ld.c.decision_id, ld.c.agent_id, ld.c.confidence_score,
                        ld.c.reasoning, ld.c.decision_action, ld.c.linked_case_id,
                        Client.display_name.label("client_display_name"),
                        Case.status.label("linked_case_status"),
                        CaseSLA.resolution_due, CaseSLA.breached,
                        CaseSLA.resolution_completed_at,
                    )
                    .select_from(Finding)
                    .join(ld, ld.c.finding_id == Finding.finding_id)
                    .outerjoin(Client, Client.client_id == Finding.client_id)
                    .outerjoin(Case, Case.case_id == ld.c.linked_case_id)
                    .outerjoin(CaseSLA, CaseSLA.case_id == ld.c.linked_case_id)
                )

                filters = []
                if client_id is not None:
                    filters.append(Finding.client_id == client_id)
                if exclude_statuses:
                    filters.append(or_(Finding.status.is_(None), Finding.status.notin_(exclude_statuses)))
                if filters:
                    query = query.where(and_(*filters))

                query = query.order_by(Finding.timestamp.desc()).limit(candidate_limit)

                rows = session.execute(query).all()
                results = []
                for row in rows:
                    finding = row[0]
                    session.expunge(finding)
                    d = finding.to_dict()
                    d.update({
                        "decision_id": row.decision_id,
                        "agent_id": row.agent_id,
                        "confidence_score": row.confidence_score,
                        "reasoning": row.reasoning,
                        "decision_action": row.decision_action,
                        "linked_case_id": row.linked_case_id,
                        "client_display_name": row.client_display_name,
                        "linked_case_status": row.linked_case_status,
                        "sla_resolution_due": row.resolution_due.isoformat() if row.resolution_due else None,
                        "sla_breached": row.breached,
                        "sla_resolution_completed_at": (
                            row.resolution_completed_at.isoformat() if row.resolution_completed_at else None
                        ),
                    })
                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"Error getting priority queue candidates: {e}")
            return []

    def get_or_create_client_portal_user(
        self, client_id: str, password_hash: Optional[str] = None, display_name: Optional[str] = None,
    ) -> Optional[User]:
        """Idempotent fetch-or-create of the one role-client User identity
        a client's portal access resolves to (client-portal design spec,
        2026-08-21). Both auth paths -- password login and the
        client-credentials token exchange (backend/api/auth.py) -- log
        the client into this SAME row, so "logged in as Cybervergent" is
        one identity regardless of how they authenticated, not two
        parallel accounts.

        get_current_user (backend/middleware/auth.py) re-fetches the
        User row from the DB by the JWT's user_id rather than trusting
        role_id/client_id from the token claims -- so a real row here is
        required, not optional, for the client-credentials path to work
        at all.

        password_hash: pass a real bcrypt hash (AuthService.hash_password)
        to make/keep this account password-loginable (e.g. the
        Cybervergent test account); omit to leave an existing row's
        password untouched, or -- if creating fresh -- generate one from
        a random, never-communicated secret (this identity is meant to
        be reached via client-token, not password, in that case).
        """
        import secrets as _secrets

        user_id = f"user-client-{client_id}"
        try:
            with self.db_manager.session_scope() as session:
                user = session.get(User, user_id)
                if user is None:
                    from backend.services.auth_service import AuthService

                    user = User(
                        user_id=user_id,
                        username=f"{client_id}-portal",
                        email=f"{client_id}-portal@clients.sentry-agentic.local",
                        password_hash=password_hash or AuthService.hash_password(_secrets.token_urlsafe(24)),
                        full_name=display_name or client_id,
                        role_id="role-client",
                        client_id=client_id,
                        is_active=True,
                        is_verified=True,
                    )
                    session.add(user)
                elif password_hash:
                    user.password_hash = password_hash
                session.flush()
                session.expunge(user)
                return user
        except Exception as e:
            logger.error(f"Error creating/fetching client portal user for {client_id}: {e}")
            return None

    def get_client(self, client_id: str) -> Optional[dict]:
        """Look up one Client row by id -- used to validate a client_id
        exists before issuing it API credentials (backend/api/clients.py)
        or minting a client-token (backend/api/auth.py)."""
        try:
            with self.db_manager.session_scope() as session:
                client = session.get(Client, client_id)
                return client.to_dict() if client else None
        except Exception as e:
            logger.error(f"Error fetching client {client_id}: {e}")
            return None

    def create_client_credential(
        self, client_id: str, client_secret_hash: str, label: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Optional[dict]:
        """Insert a new client-portal API credential row (client-portal
        design spec, 2026-08-21). Caller (backend/api/clients.py) has
        already generated the plaintext secret and hashed it via
        AuthService.hash_password -- this layer only ever sees/stores the
        hash. Returns the created row's to_dict() (never includes the
        hash) or None on failure."""
        import uuid
        try:
            with self.db_manager.session_scope() as session:
                row = ClientApiCredential(
                    credential_id=f"cred-{uuid.uuid4().hex[:20]}",
                    client_id=client_id,
                    client_secret_hash=client_secret_hash,
                    label=label,
                    created_by=created_by,
                )
                session.add(row)
                session.flush()
                d = row.to_dict()
                session.expunge(row)
                return d
        except Exception as e:
            logger.error(f"Error creating client credential for {client_id}: {e}")
            return None

    def get_active_client_credentials(self, client_id: str) -> List[ClientApiCredential]:
        """All active credential rows for one client -- caller (backend/
        api/auth.py's client-token exchange) bcrypt-compares the supplied
        secret against each, since bcrypt hashes aren't directly
        queryable. Small, bounded set per client (rotation-friendly, not
        high-cardinality), so comparing a handful in Python is fine."""
        try:
            with self.db_manager.session_scope() as session:
                query = select(ClientApiCredential).where(
                    ClientApiCredential.client_id == client_id,
                    ClientApiCredential.is_active.is_(True),
                )
                rows = session.execute(query).scalars().all()
                for row in rows:
                    session.expunge(row)
                return list(rows)
        except Exception as e:
            logger.error(f"Error fetching client credentials for {client_id}: {e}")
            return []

    def touch_client_credential_last_used(self, credential_id: str) -> None:
        """Best-effort last_used_at bump on successful token exchange --
        never blocks/raises the auth flow if it fails."""
        try:
            with self.db_manager.session_scope() as session:
                cred = session.get(ClientApiCredential, credential_id)
                if cred:
                    cred.last_used_at = datetime.utcnow()
        except Exception as e:
            logger.debug(f"Non-fatal: failed to update last_used_at for {credential_id}: {e}")

    def get_client_decision_ledger(
        self, client_id: str, limit: int = 100, offset: int = 0,
    ) -> List[dict]:
        """AIDecisionLog rows for one client's findings, newest first --
        the Action Ledger's data source (client-portal design spec,
        2026-08-21, Agentic Operations Center). Autonomy tier is derived
        by the caller (backend/api/portal.py) from decision_type/
        decision_action/confidence_score, not stored here."""
        try:
            with self.db_manager.session_scope() as session:
                query = (
                    select(AIDecisionLog, Finding.entity_context, Finding.severity)
                    .join(Finding, Finding.finding_id == AIDecisionLog.finding_id)
                    .where(Finding.client_id == client_id)
                    .order_by(AIDecisionLog.timestamp.desc())
                    .limit(limit)
                    .offset(offset)
                )
                rows = session.execute(query).all()
                results = []
                for decision, entity_context, severity in rows:
                    d = {
                        "decision_id": decision.decision_id,
                        "agent_id": decision.agent_id,
                        "decision_type": decision.decision_type,
                        "confidence_score": decision.confidence_score,
                        "reasoning": decision.reasoning,
                        "recommended_action": decision.recommended_action,
                        "decision_action": decision.decision_action,
                        "finding_id": decision.finding_id,
                        "timestamp": decision.timestamp.isoformat() if decision.timestamp else None,
                        "entity_context": entity_context,
                        "severity": severity,
                    }
                    results.append(d)
                return results
        except Exception as e:
            logger.error(f"Error getting decision ledger for client {client_id}: {e}")
            return []

    def get_client_decision_scorecard(self, client_id: str) -> dict:
        """Agent Performance Scorecard aggregate for one client
        (client-portal design spec, 2026-08-21). Honest about sparse
        data by design: graded_count tells the caller how many decisions
        actually carry human feedback, so the UI can label rates as
        "based on N graded decisions" rather than presenting an
        always-on number computed from a near-empty sample."""
        try:
            with self.db_manager.session_scope() as session:
                base = (
                    select(AIDecisionLog)
                    .join(Finding, Finding.finding_id == AIDecisionLog.finding_id)
                    .where(Finding.client_id == client_id)
                )
                total = session.execute(
                    select(func.count()).select_from(base.subquery())
                ).scalar() or 0

                graded = (
                    base.where(AIDecisionLog.accuracy_grade.isnot(None))
                )
                graded_rows = session.execute(graded).scalars().all()
                graded_count = len(graded_rows)

                overturned = sum(
                    1 for d in graded_rows
                    if d.decision_action in ("override", "modify")
                )
                avg_accuracy = (
                    round(sum(d.accuracy_grade for d in graded_rows) / graded_count, 2)
                    if graded_count else None
                )
                avg_time_saved = None
                time_saved_values = [d.time_saved_minutes for d in graded_rows if d.time_saved_minutes is not None]
                if time_saved_values:
                    avg_time_saved = round(sum(time_saved_values) / len(time_saved_values), 1)

                return {
                    "total_decisions": total,
                    "graded_count": graded_count,
                    "human_overturn_rate": round(overturned / graded_count, 2) if graded_count else None,
                    "avg_accuracy_grade": avg_accuracy,
                    "avg_time_saved_minutes": avg_time_saved,
                }
        except Exception as e:
            logger.error(f"Error computing decision scorecard for client {client_id}: {e}")
            return {
                "total_decisions": 0, "graded_count": 0, "human_overturn_rate": None,
                "avg_accuracy_grade": None, "avg_time_saved_minutes": None,
            }

    def update_finding(self, finding_id: str, **updates) -> bool:
        """
        Update a finding.
        
        Args:
            finding_id: Finding ID
            **updates: Fields to update
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                finding = session.get(Finding, finding_id)
                if not finding:
                    logger.warning(f"Finding not found: {finding_id}")
                    return False
                
                # Update allowed fields
                for key, value in updates.items():
                    if hasattr(finding, key):
                        setattr(finding, key, value)
                
                finding.updated_at = datetime.utcnow()
                session.flush()
                logger.info(f"Updated finding: {finding_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating finding {finding_id}: {e}")
            return False
    
    def delete_finding(self, finding_id: str) -> bool:
        """
        Delete a finding.
        
        Args:
            finding_id: Finding ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                finding = session.get(Finding, finding_id)
                if not finding:
                    logger.warning(f"Finding not found: {finding_id}")
                    return False
                
                session.delete(finding)
                logger.info(f"Deleted finding: {finding_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting finding {finding_id}: {e}")
            return False
    
    # ========== Case Operations ==========
    
    def create_case(
        self,
        case_id: str,
        title: str,
        finding_ids: List[str],
        **kwargs
    ) -> Optional[Case]:
        """
        Create a new case.
        
        Args:
            case_id: Unique case ID
            title: Case title
            finding_ids: List of finding IDs to link
            **kwargs: Additional fields (description, status, priority, assignee, tags, etc.)
        
        Returns:
            Created Case object or None if failed
        """
        try:
            with self.db_manager.session_scope() as session:
                # Create case
                now = datetime.utcnow()
                case = Case(
                    case_id=case_id,
                    title=title,
                    description=kwargs.get('description', ''),
                    status=kwargs.get('status', 'new'),
                    priority=kwargs.get('priority', 'medium'),
                    assignee=kwargs.get('assignee'),
                    tags=kwargs.get('tags', []),
                    notes=kwargs.get('notes', []),
                    timeline=kwargs.get('timeline', [{'timestamp': now.isoformat() + 'Z', 'event': 'Case created'}]),
                    activities=kwargs.get('activities', []),
                    resolution_steps=kwargs.get('resolution_steps', []),
                    mitre_techniques=kwargs.get('mitre_techniques'),
                )
                session.add(case)
                session.flush()
                
                # Link findings
                if finding_ids:
                    findings = session.execute(
                        select(Finding).where(Finding.finding_id.in_(finding_ids))
                    ).scalars().all()
                    case.findings.extend(findings)
                    session.flush()
                
                session.refresh(case)
                logger.info(f"Created case: {case_id} with {len(finding_ids)} findings")
                return case
        except Exception as e:
            logger.error(f"Error creating case {case_id}: {e}")
            return None
    
    def get_case(self, case_id: str, include_findings: bool = False) -> Optional[Case]:
        """
        Get a case by ID.
        
        Args:
            case_id: Case ID
            include_findings: If True, include full finding objects
        
        Returns:
            Case object or None if not found
        """
        try:
            with self.db_manager.session_scope() as session:
                case = session.get(Case, case_id)
                if case:
                    # Force load findings if needed
                    if include_findings:
                        _ = case.findings  # Trigger lazy load
                    session.expunge(case)
                return case
        except Exception as e:
            logger.error(f"Error getting case {case_id}: {e}")
            return None
    
    def get_cases(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Case]:
        """
        Get cases with optional filters.
        
        Args:
            status: Filter by status
            priority: Filter by priority
            assignee: Filter by assignee
            limit: Maximum number of results
            offset: Offset for pagination
        
        Returns:
            List of Case objects
        """
        try:
            with self.db_manager.session_scope() as session:
                query = select(Case)
                
                # Apply filters
                filters = []
                if status:
                    filters.append(Case.status == status)
                if priority:
                    filters.append(Case.priority == priority)
                if assignee:
                    filters.append(Case.assignee == assignee)
                
                if filters:
                    query = query.where(and_(*filters))
                
                # Apply ordering, limit, and offset
                query = query.order_by(Case.created_at.desc())
                query = query.limit(limit).offset(offset)
                
                cases = session.execute(query).scalars().all()
                
                # Detach from session
                for case in cases:
                    session.expunge(case)
                
                return cases
        except Exception as e:
            logger.error(f"Error getting cases: {e}")
            return []
    
    def update_case(self, case_id: str, **updates) -> bool:
        """
        Update a case.
        
        Args:
            case_id: Case ID
            **updates: Fields to update
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                case = session.get(Case, case_id)
                if not case:
                    logger.warning(f"Case not found: {case_id}")
                    return False
                
                # Update allowed fields
                for key, value in updates.items():
                    if hasattr(case, key):
                        setattr(case, key, value)
                
                case.updated_at = datetime.utcnow()
                session.flush()
                logger.info(f"Updated case: {case_id}")
                return True
        except Exception as e:
            logger.error(f"Error updating case {case_id}: {e}")
            return False
    
    def delete_case(self, case_id: str) -> bool:
        """
        Delete a case.
        
        Args:
            case_id: Case ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                case = session.get(Case, case_id)
                if not case:
                    logger.warning(f"Case not found: {case_id}")
                    return False
                
                session.delete(case)
                logger.info(f"Deleted case: {case_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting case {case_id}: {e}")
            return False
    
    def add_finding_to_case(self, case_id: str, finding_id: str) -> bool:
        """
        Add a finding to a case.
        
        Args:
            case_id: Case ID
            finding_id: Finding ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                case = session.get(Case, case_id)
                finding = session.get(Finding, finding_id)
                
                if not case or not finding:
                    logger.warning(f"Case or finding not found: {case_id}, {finding_id}")
                    return False
                
                if finding not in case.findings:
                    case.findings.append(finding)
                    case.updated_at = datetime.utcnow()
                    session.flush()
                    logger.info(f"Added finding {finding_id} to case {case_id}")
                
                return True
        except Exception as e:
            logger.error(f"Error adding finding to case: {e}")
            return False
    
    def remove_finding_from_case(self, case_id: str, finding_id: str) -> bool:
        """
        Remove a finding from a case.
        
        Args:
            case_id: Case ID
            finding_id: Finding ID
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self.db_manager.session_scope() as session:
                case = session.get(Case, case_id)
                finding = session.get(Finding, finding_id)
                
                if not case or not finding:
                    logger.warning(f"Case or finding not found: {case_id}, {finding_id}")
                    return False
                
                if finding in case.findings:
                    case.findings.remove(finding)
                    case.updated_at = datetime.utcnow()
                    session.flush()
                    logger.info(f"Removed finding {finding_id} from case {case_id}")
                
                return True
        except Exception as e:
            logger.error(f"Error removing finding from case: {e}")
            return False
    
    # ========== Statistics ==========
    
    def get_case_statistics(self) -> Dict[str, Any]:
        """
        Get case statistics.
        
        Returns:
            Dictionary with statistics
        """
        try:
            with self.db_manager.session_scope() as session:
                total = session.query(func.count(Case.case_id)).scalar()
                
                # Count by status
                status_counts = {}
                for status, count in session.query(
                    Case.status, func.count(Case.case_id)
                ).group_by(Case.status).all():
                    status_counts[status] = count
                
                # Count by priority
                priority_counts = {}
                for priority, count in session.query(
                    Case.priority, func.count(Case.case_id)
                ).group_by(Case.priority).all():
                    priority_counts[priority] = count
                
                return {
                    'total': total,
                    'by_status': status_counts,
                    'by_priority': priority_counts
                }
        except Exception as e:
            logger.error(f"Error getting case statistics: {e}")
            return {'total': 0, 'by_status': {}, 'by_priority': {}}
    
    def get_finding_statistics(self) -> Dict[str, Any]:
        """
        Get finding statistics.
        
        Returns:
            Dictionary with statistics
        """
        try:
            with self.db_manager.session_scope() as session:
                total = session.query(func.count(Finding.finding_id)).scalar()
                
                # Count by severity
                severity_counts = {}
                for severity, count in session.query(
                    Finding.severity, func.count(Finding.finding_id)
                ).group_by(Finding.severity).all():
                    severity_counts[severity or 'unknown'] = count
                
                # Count by data source
                data_source_counts = {}
                for data_source, count in session.query(
                    Finding.data_source, func.count(Finding.finding_id)
                ).group_by(Finding.data_source).all():
                    data_source_counts[data_source] = count
                
                return {
                    'total': total,
                    'by_severity': severity_counts,
                    'by_data_source': data_source_counts
                }
        except Exception as e:
            logger.error(f"Error getting finding statistics: {e}")
            return {'total': 0, 'by_severity': {}, 'by_data_source': {}}
    
    # ========== AI Decision Log Operations ==========
    
    def create_ai_decision(
        self,
        decision_id: str,
        agent_id: str,
        decision_type: str,
        confidence_score: float,
        reasoning: str,
        recommended_action: str,
        finding_id: Optional[str] = None,
        case_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        decision_metadata: Optional[dict] = None
    ) -> Optional[AIDecisionLog]:
        """
        Log an AI decision for tracking and feedback.
        
        Args:
            decision_id: Unique decision identifier
            agent_id: ID of the agent making the decision
            decision_type: Type of decision (e.g., 'triage', 'escalate', 'isolate')
            confidence_score: AI's confidence in the decision (0-1)
            reasoning: AI's reasoning for the decision
            recommended_action: Recommended action text
            finding_id: Optional associated finding ID
            case_id: Optional associated case ID
            workflow_id: Optional workflow ID
            decision_metadata: Optional additional metadata
        
        Returns:
            Created AIDecisionLog or None if failed
        """
        try:
            with self.db_manager.session_scope() as session:
                decision = AIDecisionLog(
                    decision_id=decision_id,
                    agent_id=agent_id,
                    decision_type=decision_type,
                    confidence_score=confidence_score,
                    reasoning=reasoning,
                    recommended_action=recommended_action,
                    finding_id=finding_id,
                    case_id=case_id,
                    workflow_id=workflow_id,
                    decision_metadata=decision_metadata,
                    timestamp=datetime.utcnow()
                )
                
                session.add(decision)
                session.flush()
                
                logger.info(f"Created AI decision log: {decision_id} by {agent_id}")
                return decision
        except Exception as e:
            logger.error(f"Error creating AI decision log: {e}")
            return None
    
    def submit_ai_decision_feedback(
        self,
        decision_id: str,
        human_reviewer: str,
        human_decision: str,
        feedback_comment: Optional[str] = None,
        accuracy_grade: Optional[float] = None,
        reasoning_grade: Optional[float] = None,
        action_appropriateness: Optional[float] = None,
        actual_outcome: Optional[str] = None,
        time_saved_minutes: Optional[int] = None
    ) -> Optional[AIDecisionLog]:
        """
        Submit human feedback on an AI decision.
        
        Args:
            decision_id: Decision to provide feedback on
            human_reviewer: Name/ID of reviewer
            human_decision: Human's decision ('agree', 'disagree', 'partial')
            feedback_comment: Optional comment
            accuracy_grade: Grade for accuracy (0-1)
            reasoning_grade: Grade for reasoning quality (0-1)
            action_appropriateness: Grade for action appropriateness (0-1)
            actual_outcome: Actual outcome ('true_positive', 'false_positive', etc.)
            time_saved_minutes: Estimated time saved by AI
        
        Returns:
            Updated AIDecisionLog or None if failed
        """
        try:
            with self.db_manager.session_scope() as session:
                decision = session.query(AIDecisionLog).filter(
                    AIDecisionLog.decision_id == decision_id
                ).first()
                
                if not decision:
                    logger.error(f"AI decision not found: {decision_id}")
                    return None
                
                # Update feedback fields
                decision.human_reviewer = human_reviewer
                decision.human_decision = human_decision
                decision.feedback_comment = feedback_comment
                decision.accuracy_grade = accuracy_grade
                decision.reasoning_grade = reasoning_grade
                decision.action_appropriateness = action_appropriateness
                decision.actual_outcome = actual_outcome
                decision.time_saved_minutes = time_saved_minutes
                decision.feedback_timestamp = datetime.utcnow()
                
                session.flush()
                
                logger.info(f"Updated AI decision feedback: {decision_id} by {human_reviewer}")
                return decision
        except Exception as e:
            logger.error(f"Error submitting AI decision feedback: {e}")
            return None

    def record_decision_action(
        self,
        decision_id: str,
        decision_action: str,
        reviewer: str,
        reason_code: Optional[str] = None,
        fields_changed: Optional[dict] = None,
        comment: Optional[str] = None,
        linked_case_id: Optional[str] = None,
    ) -> Optional[AIDecisionLog]:
        """
        Record a live approve/modify/override/escalate action an analyst
        took on an AI decision (unified-schema foundation, Phase 2,
        2026-08-20). Kept separate from submit_ai_decision_feedback()
        above -- that's the retrospective agree/partial/disagree grading
        flow (a different semantic axis: "was the AI right in hindsight"
        vs. "what did the analyst do about it right now").

        Args:
            decision_id: Decision to act on
            decision_action: 'approve' | 'modify' | 'override' | 'escalate'
            reviewer: Name/ID of the analyst taking the action
            reason_code: Required by the caller (backend/api/ai_decisions.py)
                when decision_action is 'modify' or 'override'
            fields_changed: Exact diff applied, for 'modify' actions --
                {"field": {"from": ..., "to": ...}}
            comment: Optional free-text note
            linked_case_id: Populated when an 'escalate' action creates a
                real case

        Returns:
            Updated AIDecisionLog or None if failed
        """
        try:
            with self.db_manager.session_scope() as session:
                decision = session.query(AIDecisionLog).filter(
                    AIDecisionLog.decision_id == decision_id
                ).first()

                if not decision:
                    logger.error(f"AI decision not found: {decision_id}")
                    return None

                decision.decision_action = decision_action
                decision.reason_code = reason_code
                decision.fields_changed = fields_changed
                decision.linked_case_id = linked_case_id
                decision.human_reviewer = reviewer
                if comment is not None:
                    decision.feedback_comment = comment
                decision.feedback_timestamp = datetime.utcnow()

                session.flush()

                logger.info(
                    f"Recorded decision action: {decision_id} -> {decision_action} by {reviewer}"
                )
                return decision
        except Exception as e:
            logger.error(f"Error recording decision action: {e}")
            return None

    def get_ai_decision(self, decision_id: str) -> Optional[AIDecisionLog]:
        """
        Get an AI decision by ID.
        
        Args:
            decision_id: Decision ID
        
        Returns:
            AIDecisionLog or None if not found
        """
        try:
            with self.db_manager.session_scope() as session:
                return session.query(AIDecisionLog).filter(
                    AIDecisionLog.decision_id == decision_id
                ).first()
        except Exception as e:
            logger.error(f"Error getting AI decision: {e}")
            return None
    
    def list_ai_decisions(
        self,
        agent_id: Optional[str] = None,
        finding_id: Optional[str] = None,
        case_id: Optional[str] = None,
        has_feedback: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AIDecisionLog]:
        """
        List AI decisions with optional filters.
        
        Args:
            agent_id: Filter by agent ID
            finding_id: Filter by finding ID
            case_id: Filter by case ID
            has_feedback: Filter by whether feedback exists
            limit: Maximum number of results
            offset: Offset for pagination
        
        Returns:
            List of AIDecisionLog objects
        """
        try:
            with self.db_manager.session_scope() as session:
                query = session.query(AIDecisionLog)
                
                if agent_id:
                    query = query.filter(AIDecisionLog.agent_id == agent_id)
                
                if finding_id:
                    query = query.filter(AIDecisionLog.finding_id == finding_id)
                
                if case_id:
                    query = query.filter(AIDecisionLog.case_id == case_id)
                
                if has_feedback is not None:
                    if has_feedback:
                        query = query.filter(AIDecisionLog.human_decision.isnot(None))
                    else:
                        query = query.filter(AIDecisionLog.human_decision.is_(None))
                
                decisions = query.order_by(
                    AIDecisionLog.timestamp.desc()
                ).limit(limit).offset(offset).all()
                
                return decisions
        except Exception as e:
            logger.error(f"Error listing AI decisions: {e}")
            return []
    
    def list_llm_dead_letters(
        self,
        finding_id: Optional[str] = None,
        investigation_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LLMJobDeadLetter]:
        """List LLM jobs that exhausted their retry budget (services/llm_worker.py's
        _write_dead_letter). Support-workflow discoverability -- lets an
        operator see failed background LLM jobs without SSH/log-grepping.
        See database/init/17_llm_job_dead_letters.sql."""
        try:
            with self.db_manager.session_scope() as session:
                query = session.query(LLMJobDeadLetter)

                if finding_id:
                    query = query.filter(LLMJobDeadLetter.finding_id == finding_id)

                if investigation_id:
                    query = query.filter(LLMJobDeadLetter.investigation_id == investigation_id)

                return query.order_by(
                    LLMJobDeadLetter.failed_at.desc()
                ).limit(limit).offset(offset).all()
        except Exception as e:
            logger.error(f"Error listing LLM dead letters: {e}")
            return []

    def upsert_task_state(
        self,
        finding_id: str,
        status: str,
        stage: Optional[str] = None,
        error: Optional[str] = None,
        increment_attempts: bool = False,
    ) -> bool:
        """Write a finding-processing checkpoint (daemon/processor.py).
        Best-effort: a checkpoint failure must never block processing
        itself, so callers should treat a False return as log-and-continue,
        not a reason to abort. See database/init/18_agent_task_state.sql."""
        try:
            with self.db_manager.session_scope() as session:
                row = session.get(AgentTaskState, finding_id)
                if row is None:
                    row = AgentTaskState(finding_id=finding_id, attempts=0)
                    session.add(row)
                row.status = status
                if stage is not None:
                    row.stage = stage
                if error is not None:
                    row.last_error = error
                if increment_attempts:
                    row.attempts = (row.attempts or 0) + 1
                row.updated_at = datetime.utcnow()
                return True
        except Exception as e:
            logger.error(f"Error upserting task state for {finding_id}: {e}")
            return False

    def get_stuck_task_states(self, limit: int = 500) -> List[AgentTaskState]:
        """Findings left `in_progress` when the daemon last stopped --
        scanned on startup (daemon/main.py) to resume processing rather
        than silently leaving them incomplete forever."""
        try:
            with self.db_manager.session_scope() as session:
                return (
                    session.query(AgentTaskState)
                    .filter(AgentTaskState.status == "in_progress")
                    .order_by(AgentTaskState.updated_at.asc())
                    .limit(limit)
                    .all()
                )
        except Exception as e:
            logger.error(f"Error fetching stuck task states: {e}")
            return []

    def get_task_state_counts(self) -> dict:
        """Row counts by status -- the admin-UI summary tiles for
        agent_task_state (frontend/src/components/settings/RuntimeHealthPanel.tsx)."""
        try:
            with self.db_manager.session_scope() as session:
                rows = (
                    session.query(AgentTaskState.status, func.count(AgentTaskState.finding_id))
                    .group_by(AgentTaskState.status)
                    .all()
                )
                counts = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
                counts.update({status: count for status, count in rows})
                return counts
        except Exception as e:
            logger.error(f"Error fetching task state counts: {e}")
            return {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}

    def list_task_states(
        self, status: Optional[str] = None, limit: int = 100
    ) -> List[AgentTaskState]:
        """General-purpose read for the admin UI -- unlike
        get_stuck_task_states() (hardcoded to in_progress, used by the
        crash-resume scan), this takes any status filter."""
        try:
            with self.db_manager.session_scope() as session:
                query = session.query(AgentTaskState)
                if status:
                    query = query.filter(AgentTaskState.status == status)
                return (
                    query.order_by(AgentTaskState.updated_at.desc())
                    .limit(limit)
                    .all()
                )
        except Exception as e:
            logger.error(f"Error listing task states: {e}")
            return []

    def get_ai_decision_stats(
        self,
        agent_id: Optional[str] = None,
        days: int = 30
    ) -> dict:
        """
        Get statistics on AI decisions and feedback.
        
        Args:
            agent_id: Optional filter by agent ID
            days: Number of days to look back
        
        Returns:
            Dictionary with statistics
        """
        try:
            from datetime import timedelta
            
            with self.db_manager.session_scope() as session:
                since = datetime.utcnow() - timedelta(days=days)
                
                query = session.query(AIDecisionLog).filter(
                    AIDecisionLog.timestamp >= since
                )
                
                if agent_id:
                    query = query.filter(AIDecisionLog.agent_id == agent_id)
                
                # Total decisions
                total_decisions = query.count()
                
                # Decisions with feedback
                feedback_query = query.filter(AIDecisionLog.human_decision.isnot(None))
                total_with_feedback = feedback_query.count()
                
                # Agreement rate
                agree_count = feedback_query.filter(
                    AIDecisionLog.human_decision == 'agree'
                ).count()
                
                # Average grades
                avg_accuracy = session.query(
                    func.avg(AIDecisionLog.accuracy_grade)
                ).filter(
                    AIDecisionLog.timestamp >= since,
                    AIDecisionLog.accuracy_grade.isnot(None)
                )
                
                if agent_id:
                    avg_accuracy = avg_accuracy.filter(AIDecisionLog.agent_id == agent_id)
                
                avg_accuracy = avg_accuracy.scalar() or 0
                
                # Outcome counts
                outcomes = {}
                for outcome, count in session.query(
                    AIDecisionLog.actual_outcome,
                    func.count(AIDecisionLog.id)
                ).filter(
                    AIDecisionLog.timestamp >= since,
                    AIDecisionLog.actual_outcome.isnot(None)
                ).group_by(AIDecisionLog.actual_outcome).all():
                    outcomes[outcome] = count
                
                # Time saved
                total_time_saved = session.query(
                    func.sum(AIDecisionLog.time_saved_minutes)
                ).filter(
                    AIDecisionLog.timestamp >= since,
                    AIDecisionLog.time_saved_minutes.isnot(None)
                )
                
                if agent_id:
                    total_time_saved = total_time_saved.filter(AIDecisionLog.agent_id == agent_id)
                
                total_time_saved = total_time_saved.scalar() or 0
                
                return {
                    'total_decisions': total_decisions,
                    'total_with_feedback': total_with_feedback,
                    'feedback_rate': round(total_with_feedback / total_decisions, 3) if total_decisions > 0 else 0,
                    'agreement_rate': round(agree_count / total_with_feedback, 3) if total_with_feedback > 0 else 0,
                    'avg_accuracy_grade': round(avg_accuracy, 3),
                    'outcomes': outcomes,
                    'total_time_saved_minutes': int(total_time_saved),
                    'total_time_saved_hours': round(total_time_saved / 60, 1),
                    'period_days': days
                }
        except Exception as e:
            logger.error(f"Error getting AI decision statistics: {e}")
            return {
                'total_decisions': 0,
                'total_with_feedback': 0,
                'feedback_rate': 0,
                'agreement_rate': 0,
                'avg_accuracy_grade': 0,
                'outcomes': {},
                'total_time_saved_minutes': 0,
                'total_time_saved_hours': 0,
                'period_days': days
            }

