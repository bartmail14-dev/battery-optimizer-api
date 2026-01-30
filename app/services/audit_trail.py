"""
===============================================================================
AUDIT TRAIL SERVICE
===============================================================================

Volledige audit trail voor alle analyses en berekeningen.

VEREISTEN (professioneel advies):
1. Traceerbaarheid: Elke berekening moet herleidbaar zijn
2. Onveranderlijkheid: Historische records mogen niet worden gewijzigd
3. Volledigheid: Alle inputs en outputs worden vastgelegd
4. Compliance: 7 jaar bewaarplicht voor financieel advies

OPSLAG:
- Development: SQLite lokaal
- Production: PostgreSQL of dedicated audit database

PRIVACY:
- Klantgegevens worden gehashed opgeslagen
- Alleen geautoriseerde consultants kunnen audits bekijken
===============================================================================
"""

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid
import sqlite3
from pathlib import Path

import structlog

logger = structlog.get_logger()


class AuditEventType(str, Enum):
    """Types van audit events."""
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    INPUT_RECEIVED = "input_received"
    CALCULATION_PERFORMED = "calculation_performed"
    REPORT_GENERATED = "report_generated"
    REPORT_EXPORTED = "report_exported"
    PARAMETERS_CHANGED = "parameters_changed"
    CONSULTANT_INPUT_SAVED = "consultant_input_saved"
    DATA_UPLOADED = "data_uploaded"
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"


@dataclass
class AuditEvent:
    """Een audit event record."""
    event_id: str
    timestamp: datetime
    event_type: AuditEventType
    session_id: str
    analysis_id: Optional[str]

    # Context
    consultant_id: Optional[str]
    client_hash: Optional[str]  # Gehashte klantnaam voor privacy

    # Details
    action: str
    details: Dict[str, Any]

    # Metadata
    ip_address: Optional[str]
    user_agent: Optional[str]
    app_version: str

    # Integriteit
    checksum: str  # Hash van alle velden voor tamper detection


@dataclass
class AnalysisRecord:
    """Volledige record van een analyse."""
    analysis_id: str
    session_id: str
    created_at: datetime
    completed_at: Optional[datetime]
    status: str  # 'pending', 'running', 'completed', 'failed'

    # Consultant info
    consultant_name: Optional[str]
    consultant_id: Optional[str]

    # Client info (gehashed)
    client_hash: Optional[str]
    project_reference: Optional[str]

    # Input parameters
    battery_sizes_kwh: List[float]
    input_parameters: Dict[str, Any]

    # Profile info
    profile_hash: str  # Hash van input data
    profile_rows: int
    profile_date_range: Optional[str]

    # Results
    results_summary: Optional[Dict[str, Any]]
    recommendation: Optional[str]

    # Versioning
    app_version: str
    calculation_version: str
    model_parameters: Dict[str, Any]


@dataclass
class AuditSummary:
    """Samenvatting van audit trail."""
    total_analyses: int
    analyses_today: int
    analyses_this_week: int
    unique_consultants: int
    unique_clients: int
    average_battery_size: float
    most_common_recommendation: str
    success_rate: float


class AuditTrailService:
    """
    Service voor audit trail management.

    GEBRUIK:
    ```python
    audit = AuditTrailService()

    # Start een sessie
    session_id = audit.start_session(consultant_id="JD001")

    # Start een analyse
    analysis_id = audit.start_analysis(
        session_id=session_id,
        consultant_name="Jan de Vries",
        client_name="Bedrijf BV",
        battery_sizes=[50, 100, 150],
        input_parameters={...}
    )

    # Log een event
    audit.log_event(
        event_type=AuditEventType.CALCULATION_PERFORMED,
        session_id=session_id,
        analysis_id=analysis_id,
        action="Monte Carlo simulation completed",
        details={"simulations": 1000, "duration_seconds": 45}
    )

    # Complete de analyse
    audit.complete_analysis(
        analysis_id=analysis_id,
        results=results,
        recommendation="GO"
    )
    ```
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialiseer audit trail service.

        Args:
            db_path: Pad naar SQLite database (None = default locatie)
        """
        if db_path is None:
            # Default: in app data directory
            data_dir = Path(os.getenv("APP_DATA_DIR", "./data"))
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "audit_trail.db")

        self.db_path = db_path
        self.app_version = os.getenv("APP_VERSION", "1.0.0")
        self.calculation_version = os.getenv("CALC_VERSION", "1.0.0")

        self._init_database()
        logger.info("Audit trail service initialized", db_path=db_path)

    def _init_database(self):
        """Initialiseer database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Audit events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                analysis_id TEXT,
                consultant_id TEXT,
                client_hash TEXT,
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                app_version TEXT NOT NULL,
                checksum TEXT NOT NULL
            )
        """)

        # Analysis records table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_records (
                analysis_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                consultant_name TEXT,
                consultant_id TEXT,
                client_hash TEXT,
                project_reference TEXT,
                battery_sizes_kwh TEXT,
                input_parameters TEXT,
                profile_hash TEXT,
                profile_rows INTEGER,
                profile_date_range TEXT,
                results_summary TEXT,
                recommendation TEXT,
                app_version TEXT NOT NULL,
                calculation_version TEXT NOT NULL,
                model_parameters TEXT
            )
        """)

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                consultant_id TEXT,
                ip_address TEXT,
                user_agent TEXT
            )
        """)

        # Indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON audit_events(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_analysis ON audit_events(analysis_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON audit_events(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_created ON analysis_records(created_at)")

        conn.commit()
        conn.close()

    def _hash_client(self, client_name: str) -> str:
        """Hash klantnaam voor privacy."""
        salt = os.getenv("AUDIT_SALT", "battery-optimizer-2024")
        return hashlib.sha256(f"{salt}:{client_name}".encode()).hexdigest()[:16]

    def _hash_profile(self, profile_data: bytes) -> str:
        """Hash profiel data voor unieke identificatie."""
        return hashlib.sha256(profile_data).hexdigest()[:32]

    def _calculate_checksum(self, event: Dict[str, Any]) -> str:
        """Bereken checksum voor integriteitsverificatie."""
        # Verwijder checksum zelf uit berekening
        event_copy = {k: v for k, v in event.items() if k != 'checksum'}
        content = json.dumps(event_copy, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def start_session(
        self,
        consultant_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """
        Start een nieuwe audit sessie.

        Returns:
            Session ID
        """
        session_id = str(uuid.uuid4())

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO sessions (session_id, started_at, consultant_id, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, datetime.now().isoformat(), consultant_id, ip_address, user_agent))

        conn.commit()
        conn.close()

        self.log_event(
            event_type=AuditEventType.SESSION_STARTED,
            session_id=session_id,
            action="Session started",
            details={"consultant_id": consultant_id}
        )

        return session_id

    def end_session(self, session_id: str):
        """Beeindig een sessie."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sessions SET ended_at = ? WHERE session_id = ?
        """, (datetime.now().isoformat(), session_id))

        conn.commit()
        conn.close()

        self.log_event(
            event_type=AuditEventType.SESSION_ENDED,
            session_id=session_id,
            action="Session ended",
            details={}
        )

    def start_analysis(
        self,
        session_id: str,
        consultant_name: Optional[str] = None,
        consultant_id: Optional[str] = None,
        client_name: Optional[str] = None,
        project_reference: Optional[str] = None,
        battery_sizes: List[float] = None,
        input_parameters: Dict[str, Any] = None,
        profile_data: Optional[bytes] = None,
        profile_rows: int = 0,
        profile_date_range: Optional[str] = None
    ) -> str:
        """
        Start een nieuwe analyse en log alle inputs.

        Returns:
            Analysis ID
        """
        analysis_id = str(uuid.uuid4())
        client_hash = self._hash_client(client_name) if client_name else None
        profile_hash = self._hash_profile(profile_data) if profile_data else None

        record = AnalysisRecord(
            analysis_id=analysis_id,
            session_id=session_id,
            created_at=datetime.now(),
            completed_at=None,
            status="running",
            consultant_name=consultant_name,
            consultant_id=consultant_id,
            client_hash=client_hash,
            project_reference=project_reference,
            battery_sizes_kwh=battery_sizes or [],
            input_parameters=input_parameters or {},
            profile_hash=profile_hash,
            profile_rows=profile_rows,
            profile_date_range=profile_date_range,
            results_summary=None,
            recommendation=None,
            app_version=self.app_version,
            calculation_version=self.calculation_version,
            model_parameters={}
        )

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO analysis_records (
                analysis_id, session_id, created_at, status,
                consultant_name, consultant_id, client_hash, project_reference,
                battery_sizes_kwh, input_parameters, profile_hash, profile_rows,
                profile_date_range, app_version, calculation_version, model_parameters
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.analysis_id, record.session_id, record.created_at.isoformat(),
            record.status, record.consultant_name, record.consultant_id,
            record.client_hash, record.project_reference,
            json.dumps(record.battery_sizes_kwh), json.dumps(record.input_parameters),
            record.profile_hash, record.profile_rows, record.profile_date_range,
            record.app_version, record.calculation_version, json.dumps(record.model_parameters)
        ))

        conn.commit()
        conn.close()

        self.log_event(
            event_type=AuditEventType.ANALYSIS_STARTED,
            session_id=session_id,
            analysis_id=analysis_id,
            consultant_id=consultant_id,
            client_hash=client_hash,
            action="Analysis started",
            details={
                "battery_sizes": battery_sizes,
                "profile_rows": profile_rows,
                "project_reference": project_reference
            }
        )

        logger.info(
            "Analysis started",
            analysis_id=analysis_id,
            session_id=session_id,
            battery_sizes=battery_sizes
        )

        return analysis_id

    def complete_analysis(
        self,
        analysis_id: str,
        results: Dict[str, Any],
        recommendation: Optional[str] = None
    ):
        """Markeer analyse als voltooid en sla resultaten op."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE analysis_records
            SET completed_at = ?, status = ?, results_summary = ?, recommendation = ?
            WHERE analysis_id = ?
        """, (
            datetime.now().isoformat(), "completed",
            json.dumps(results), recommendation, analysis_id
        ))

        # Haal session_id op voor logging
        cursor.execute("SELECT session_id, client_hash FROM analysis_records WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()

        conn.commit()
        conn.close()

        if row:
            session_id, client_hash = row
            self.log_event(
                event_type=AuditEventType.ANALYSIS_COMPLETED,
                session_id=session_id,
                analysis_id=analysis_id,
                client_hash=client_hash,
                action="Analysis completed",
                details={
                    "recommendation": recommendation,
                    "scenarios_analyzed": len(results.get("scenarios", []))
                }
            )

        logger.info(
            "Analysis completed",
            analysis_id=analysis_id,
            recommendation=recommendation
        )

    def fail_analysis(self, analysis_id: str, error: str):
        """Markeer analyse als gefaald."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE analysis_records SET completed_at = ?, status = ? WHERE analysis_id = ?
        """, (datetime.now().isoformat(), "failed", analysis_id))

        cursor.execute("SELECT session_id FROM analysis_records WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()

        conn.commit()
        conn.close()

        if row:
            self.log_event(
                event_type=AuditEventType.ANALYSIS_FAILED,
                session_id=row[0],
                analysis_id=analysis_id,
                action="Analysis failed",
                details={"error": error[:500]}  # Truncate error
            )

    def log_event(
        self,
        event_type: AuditEventType,
        session_id: str,
        action: str,
        details: Dict[str, Any] = None,
        analysis_id: Optional[str] = None,
        consultant_id: Optional[str] = None,
        client_hash: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """Log een audit event."""
        event_id = str(uuid.uuid4())
        timestamp = datetime.now()

        event_dict = {
            "event_id": event_id,
            "timestamp": timestamp.isoformat(),
            "event_type": event_type.value,
            "session_id": session_id,
            "analysis_id": analysis_id,
            "consultant_id": consultant_id,
            "client_hash": client_hash,
            "action": action,
            "details": details or {},
            "ip_address": ip_address,
            "user_agent": user_agent,
            "app_version": self.app_version
        }

        checksum = self._calculate_checksum(event_dict)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO audit_events (
                event_id, timestamp, event_type, session_id, analysis_id,
                consultant_id, client_hash, action, details,
                ip_address, user_agent, app_version, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id, timestamp.isoformat(), event_type.value, session_id,
            analysis_id, consultant_id, client_hash, action,
            json.dumps(details or {}), ip_address, user_agent,
            self.app_version, checksum
        ))

        conn.commit()
        conn.close()

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Haal een analyse record op."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM analysis_records WHERE analysis_id = ?", (analysis_id,))
        row = cursor.fetchone()

        conn.close()

        if not row:
            return None

        columns = [desc[0] for desc in cursor.description]
        record = dict(zip(columns, row))

        # Parse JSON fields
        for field in ['battery_sizes_kwh', 'input_parameters', 'results_summary', 'model_parameters']:
            if record.get(field):
                try:
                    record[field] = json.loads(record[field])
                except json.JSONDecodeError:
                    pass

        return record

    def get_analysis_history(
        self,
        consultant_id: Optional[str] = None,
        client_hash: Optional[str] = None,
        days: int = 30,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Haal analyse historie op.

        Args:
            consultant_id: Filter op consultant
            client_hash: Filter op client
            days: Dagen terug
            limit: Maximum resultaten

        Returns:
            Lijst van analyse records
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        since = (datetime.now() - timedelta(days=days)).isoformat()

        query = "SELECT * FROM analysis_records WHERE created_at >= ?"
        params = [since]

        if consultant_id:
            query += " AND consultant_id = ?"
            params.append(consultant_id)

        if client_hash:
            query += " AND client_hash = ?"
            params.append(client_hash)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        conn.close()

        results = []
        for row in rows:
            record = dict(zip(columns, row))
            for field in ['battery_sizes_kwh', 'input_parameters', 'results_summary']:
                if record.get(field):
                    try:
                        record[field] = json.loads(record[field])
                    except json.JSONDecodeError:
                        pass
            results.append(record)

        return results

    def get_events_for_analysis(self, analysis_id: str) -> List[Dict[str, Any]]:
        """Haal alle events voor een analyse op."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM audit_events WHERE analysis_id = ? ORDER BY timestamp
        """, (analysis_id,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        conn.close()

        results = []
        for row in rows:
            event = dict(zip(columns, row))
            if event.get('details'):
                try:
                    event['details'] = json.loads(event['details'])
                except json.JSONDecodeError:
                    pass
            results.append(event)

        return results

    def get_summary(self, days: int = 30) -> AuditSummary:
        """Haal audit samenvatting op."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        since = (datetime.now() - timedelta(days=days)).isoformat()
        today = datetime.now().date().isoformat()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()

        # Totaal analyses
        cursor.execute("SELECT COUNT(*) FROM analysis_records WHERE created_at >= ?", (since,))
        total = cursor.fetchone()[0]

        # Analyses vandaag
        cursor.execute("SELECT COUNT(*) FROM analysis_records WHERE created_at >= ?", (today,))
        today_count = cursor.fetchone()[0]

        # Analyses deze week
        cursor.execute("SELECT COUNT(*) FROM analysis_records WHERE created_at >= ?", (week_ago,))
        week_count = cursor.fetchone()[0]

        # Unieke consultants
        cursor.execute("SELECT COUNT(DISTINCT consultant_id) FROM analysis_records WHERE created_at >= ? AND consultant_id IS NOT NULL", (since,))
        unique_consultants = cursor.fetchone()[0]

        # Unieke clients
        cursor.execute("SELECT COUNT(DISTINCT client_hash) FROM analysis_records WHERE created_at >= ? AND client_hash IS NOT NULL", (since,))
        unique_clients = cursor.fetchone()[0]

        # Gemiddelde batterij grootte
        cursor.execute("SELECT battery_sizes_kwh FROM analysis_records WHERE created_at >= ?", (since,))
        all_sizes = []
        for row in cursor.fetchall():
            try:
                sizes = json.loads(row[0])
                all_sizes.extend(sizes)
            except (json.JSONDecodeError, TypeError):
                pass
        avg_size = sum(all_sizes) / len(all_sizes) if all_sizes else 0

        # Meest voorkomende aanbeveling
        cursor.execute("""
            SELECT recommendation, COUNT(*) as cnt
            FROM analysis_records
            WHERE created_at >= ? AND recommendation IS NOT NULL
            GROUP BY recommendation
            ORDER BY cnt DESC
            LIMIT 1
        """, (since,))
        row = cursor.fetchone()
        most_common = row[0] if row else "N/A"

        # Succes rate
        cursor.execute("SELECT COUNT(*) FROM analysis_records WHERE created_at >= ? AND status = 'completed'", (since,))
        completed = cursor.fetchone()[0]
        success_rate = completed / total if total > 0 else 0

        conn.close()

        return AuditSummary(
            total_analyses=total,
            analyses_today=today_count,
            analyses_this_week=week_count,
            unique_consultants=unique_consultants,
            unique_clients=unique_clients,
            average_battery_size=round(avg_size, 1),
            most_common_recommendation=most_common,
            success_rate=round(success_rate, 2)
        )

    def verify_integrity(self, analysis_id: str) -> Tuple[bool, List[str]]:
        """
        Verifieer integriteit van audit records.

        Returns:
            Tuple van (is_valid, list of issues)
        """
        issues = []
        events = self.get_events_for_analysis(analysis_id)

        for event in events:
            # Herbereken checksum
            checksum = self._calculate_checksum(event)
            if checksum != event.get('checksum'):
                issues.append(f"Checksum mismatch for event {event['event_id']}")

        return len(issues) == 0, issues


# Singleton instance
_audit_service: Optional[AuditTrailService] = None


def get_audit_service() -> AuditTrailService:
    """Haal singleton audit service op."""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditTrailService()
    return _audit_service
