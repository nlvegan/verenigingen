"""
Immutable Audit Trail System
Comprehensive audit logging for financial compliance

Features:
- Cryptographic integrity verification
- Chain of custody tracking
- Regulatory compliance logging
- Tamper-evident storage
- Query and reporting capabilities
"""

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


class AuditEventType(Enum):
    """Types of audit events"""

    # Security events
    API_KEY_ROTATION = "api_key_rotation"
    WEBHOOK_VALIDATION = "webhook_validation"
    ENCRYPTION_OPERATION = "encryption_operation"

    # Financial events
    PAYMENT_CREATED = "payment_created"
    PAYMENT_UPDATED = "payment_updated"
    SETTLEMENT_PROCESSED = "settlement_processed"
    BALANCE_CHECKED = "balance_checked"
    CHARGEBACK_RECEIVED = "chargeback_received"

    # Compliance events
    DATA_EXPORT = "data_export"
    DATA_DELETION = "data_deletion"
    CONSENT_UPDATED = "consent_updated"
    REPORT_GENERATED = "report_generated"

    # System events
    CONFIGURATION_CHANGED = "configuration_changed"
    ERROR_OCCURRED = "error_occurred"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"


class AuditSeverity(Enum):
    """Severity levels for audit events"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ImmutableAuditTrail:
    """
    Immutable audit trail with cryptographic integrity

    Provides:
    - Write-once audit entries
    - Cryptographic chaining
    - Integrity verification
    - Compliance reporting
    """

    def __init__(self):
        """Initialize audit trail system"""
        self.chain_lock = threading.RLock()
        self.buffer = []
        self.buffer_size = 100
        self.last_hash = self._get_last_hash()

    def log_event(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        user: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> str:
        """
        Log an audit event

        Args:
            event_type: Type of event
            severity: Event severity
            description: Human-readable description
            details: Additional event details
            user: User who triggered event
            entity_type: Related entity type (e.g., 'Payment')
            entity_id: Related entity ID

        Returns:
            str: Event hash for reference
        """
        with self.chain_lock:
            # Create audit entry
            audit_entry = {
                "event_type": event_type.value,
                "severity": severity.value,
                "description": description,
                "details": details or {},
                "user": user or frappe.session.user,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "timestamp": now_datetime().isoformat(),
                "sequence": self._get_next_sequence(),
                "previous_hash": self.last_hash,
            }

            # Add system context
            audit_entry["context"] = self._get_system_context()

            # Calculate entry hash
            entry_hash = self._calculate_entry_hash(audit_entry)
            audit_entry["hash"] = entry_hash

            # Store in buffer
            self.buffer.append(audit_entry)

            # Update last hash for chaining
            self.last_hash = entry_hash

            # Flush buffer if needed
            if len(self.buffer) >= self.buffer_size:
                self._flush_buffer()

            return entry_hash

    def _calculate_entry_hash(self, entry: Dict[str, Any]) -> str:
        """
        Calculate cryptographic hash for audit entry

        Args:
            entry: Audit entry dictionary

        Returns:
            str: SHA-256 hash
        """
        # Create deterministic string representation
        hash_input = json.dumps(
            {
                "event_type": entry["event_type"],
                "severity": entry["severity"],
                "description": entry["description"],
                "timestamp": entry["timestamp"],
                "sequence": entry["sequence"],
                "previous_hash": entry["previous_hash"],
                "user": entry["user"],
            },
            sort_keys=True,
        )

        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    def _get_system_context(self) -> Dict[str, Any]:
        """
        Get system context for audit entry

        Returns:
            Dict with system information
        """
        context = {
            "site": frappe.local.site,
            "session_id": frappe.session.sid if hasattr(frappe.session, "sid") else None,
        }

        # Add request context if available
        if frappe.local.request:
            context.update(
                {
                    "ip_address": frappe.local.request.environ.get("REMOTE_ADDR"),
                    "user_agent": frappe.local.request.environ.get("HTTP_USER_AGENT"),
                    "request_method": frappe.local.request.method,
                    "request_path": frappe.local.request.path,
                }
            )

        return context

    def _get_next_sequence(self) -> int:
        """
        Get next sequence number

        Returns:
            int: Next sequence number
        """
        # Get max sequence from database
        max_seq = frappe.db.sql(
            """
            SELECT MAX(CAST(sequence AS UNSIGNED)) as max_seq
            FROM `tabMollie Audit Log`
        """,
            as_dict=True,
        )

        if max_seq and max_seq[0].get("max_seq"):
            return max_seq[0]["max_seq"] + 1
        return 1

    def _get_last_hash(self) -> Optional[str]:
        """
        Get hash of last audit entry

        Returns:
            str: Last entry hash or None
        """
        last_entry = frappe.db.sql(
            """
            SELECT integrity_hash
            FROM `tabMollie Audit Log`
            ORDER BY creation DESC
            LIMIT 1
        """,
            as_dict=True,
        )

        if last_entry:
            return last_entry[0]["integrity_hash"]
        return None

    def _flush_buffer(self):
        """Flush audit buffer to database"""
        if not self.buffer:
            return

        try:
            for entry in self.buffer:
                # Create Mollie Audit Log document
                audit_log = frappe.new_doc("Mollie Audit Log")
                audit_log.action = entry["event_type"]
                audit_log.status = entry["severity"]
                audit_log.details = json.dumps(
                    {
                        "description": entry["description"],
                        "details": entry["details"],
                        "entity_type": entry["entity_type"],
                        "entity_id": entry["entity_id"],
                        "context": entry["context"],
                    }
                )
                audit_log.user = entry["user"]
                audit_log.timestamp = entry["timestamp"]
                audit_log.sequence = str(entry["sequence"])
                audit_log.previous_hash = entry["previous_hash"]
                audit_log.integrity_hash = entry["hash"]

                # Save with system permissions
                audit_log.flags.ignore_permissions = True
                audit_log.insert()

            # Clear buffer after successful flush
            self.buffer = []

        except Exception as e:
            frappe.log_error(f"Failed to flush audit buffer: {str(e)}", "Audit Trail")

    def verify_integrity(
        self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> Tuple[bool, List[str]]:
        """
        Verify audit trail integrity

        Args:
            start_date: Start of verification period
            end_date: End of verification period

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Get audit entries in order
        filters = {}
        if start_date:
            filters["timestamp"] = [">=", start_date]
        if end_date:
            if "timestamp" in filters:
                filters["timestamp"] = ["between", [start_date, end_date]]
            else:
                filters["timestamp"] = ["<=", end_date]

        entries = frappe.get_all(
            "Mollie Audit Log",
            filters=filters,
            fields=["name", "integrity_hash", "previous_hash", "sequence", "details", "timestamp"],
            order_by="sequence asc",
        )

        if not entries:
            return True, []

        # Verify chain integrity
        for i, entry in enumerate(entries):
            # Verify hash linkage
            if i > 0:
                expected_previous = entries[i - 1]["integrity_hash"]
                if entry["previous_hash"] != expected_previous:
                    errors.append(
                        f"Chain broken at sequence {entry['sequence']}: "
                        f"expected previous hash {expected_previous}, got {entry['previous_hash']}"
                    )

            # Verify individual entry integrity
            doc = frappe.get_doc("Mollie Audit Log", entry["name"])
            if not doc.verify_integrity():
                errors.append(f"Integrity check failed for entry {entry['name']}")

        return len(errors) == 0, errors

    def query_events(
        self,
        event_types: Optional[List[AuditEventType]] = None,
        severities: Optional[List[AuditSeverity]] = None,
        user: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query audit events

        Args:
            event_types: Filter by event types
            severities: Filter by severities
            user: Filter by user
            entity_type: Filter by entity type
            entity_id: Filter by entity ID
            start_date: Start date filter
            end_date: End date filter
            limit: Maximum results

        Returns:
            List of audit events
        """
        # Flush buffer first to include recent events
        self._flush_buffer()

        # Build filters
        filters = {}

        if event_types:
            filters["action"] = ["in", [et.value for et in event_types]]

        if severities:
            filters["status"] = ["in", [s.value for s in severities]]

        if user:
            filters["user"] = user

        if start_date:
            filters["timestamp"] = [">=", start_date]

        if end_date:
            if "timestamp" in filters:
                filters["timestamp"] = ["between", [start_date, end_date]]
            else:
                filters["timestamp"] = ["<=", end_date]

        # Execute query
        results = frappe.get_all(
            "Mollie Audit Log", filters=filters, fields=["*"], order_by="timestamp desc", limit=limit
        )

        # Parse and filter by entity if needed
        filtered_results = []
        for result in results:
            if result.get("details"):
                try:
                    details = json.loads(result["details"])

                    # Filter by entity
                    if entity_type and details.get("entity_type") != entity_type:
                        continue
                    if entity_id and details.get("entity_id") != entity_id:
                        continue

                    # Add parsed details to result
                    result["parsed_details"] = details
                    filtered_results.append(result)
                except:
                    filtered_results.append(result)
            else:
                filtered_results.append(result)

        return filtered_results

    def generate_compliance_report(
        self, start_date: datetime, end_date: datetime, report_type: str = "summary"
    ) -> Dict[str, Any]:
        """
        Generate compliance report

        Args:
            start_date: Report start date
            end_date: Report end date
            report_type: Type of report (summary/detailed)

        Returns:
            Dict with report data
        """
        # Verify integrity first
        is_valid, errors = self.verify_integrity(start_date, end_date)

        # Query events
        events = self.query_events(start_date=start_date, end_date=end_date, limit=10000)

        # Generate statistics
        stats = {
            "total_events": len(events),
            "integrity_valid": is_valid,
            "integrity_errors": errors,
            "events_by_type": {},
            "events_by_severity": {},
            "events_by_user": {},
            "critical_events": [],
        }

        # Analyze events
        for event in events:
            # Count by type
            event_type = event.get("action", "unknown")
            stats["events_by_type"][event_type] = stats["events_by_type"].get(event_type, 0) + 1

            # Count by severity
            severity = event.get("status", "unknown")
            stats["events_by_severity"][severity] = stats["events_by_severity"].get(severity, 0) + 1

            # Count by user
            user = event.get("user", "unknown")
            stats["events_by_user"][user] = stats["events_by_user"].get(user, 0) + 1

            # Collect critical events
            if severity == AuditSeverity.CRITICAL.value:
                stats["critical_events"].append(
                    {
                        "timestamp": event.get("timestamp"),
                        "action": event_type,
                        "user": user,
                        "description": event.get("parsed_details", {}).get("description", ""),
                    }
                )

        report = {
            "report_type": report_type,
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "generated_at": datetime.now().isoformat(),
            "statistics": stats,
        }

        # Add detailed events if requested
        if report_type == "detailed":
            report["events"] = events[:1000]  # Limit to prevent huge reports

        # Log report generation
        self.log_event(
            AuditEventType.REPORT_GENERATED,
            AuditSeverity.INFO,
            f"Compliance report generated for {start_date} to {end_date}",
            details={"report_type": report_type, "event_count": len(events)},
        )

        return report


# Global audit trail instance
_audit_trail = None


def get_audit_trail() -> ImmutableAuditTrail:
    """
    Get global audit trail instance

    Returns:
        ImmutableAuditTrail singleton
    """
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = ImmutableAuditTrail()
    return _audit_trail
