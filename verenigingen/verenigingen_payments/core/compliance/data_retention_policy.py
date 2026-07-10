"""
Data Retention Policy Manager
Automated data lifecycle management for compliance

Features:
- Configurable retention periods by data category
- Automated data purging
- Legal hold management
- Data anonymization
- Retention policy reporting
"""

import hashlib
import json
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime


class DataCategory(Enum):
    """Categories of data with different retention requirements"""

    PAYMENT_DATA = "payment_data"
    MANDATE_DATA = "mandate_data"  # SEPA Mandate (holds IBAN/BIC/account-holder PII)
    PERSONAL_DATA = "personal_data"
    TRANSACTION_DATA = "transaction_data"
    AUDIT_LOGS = "audit_logs"
    SECURITY_EVENTS = "security_events"
    FINANCIAL_RECORDS = "financial_records"
    CONSENT_RECORDS = "consent_records"
    TEMPORARY_DATA = "temporary_data"


class RetentionAction(Enum):
    """Actions to take when retention period expires"""

    DELETE = "delete"
    ANONYMIZE = "anonymize"
    ARCHIVE = "archive"
    REVIEW = "review"


# Categories whose LIVE (destructive) processing path has been individually
# verified safe and is allowed to run. Everything else is forced to dry-run
# regardless of settings. Kept intentionally minimal:
#   - temporary_data: a clean DELETE of aged webhook_validation Mollie Audit Log
#     rows; verified + integration-tested.
# Excluded (see backlog): audit_logs (archive writes a non-existent field),
# payment_data (anonymizes a submitted Payment Entry -> GL desync risk),
# personal_data (Member delete) — all unverified/known-broken.
LIVE_CAPABLE_CATEGORIES = {DataCategory.TEMPORARY_DATA}


class DataRetentionPolicy:
    """
    Comprehensive data retention policy management

    Provides:
    - Policy definition and enforcement
    - Automated data lifecycle management
    - Legal hold support
    - Compliance reporting

    NOTE (orphan scaffolding): as of 2026-07, this class has NO callers — it is
    not registered in any ``scheduler_events`` hook, exposed by any whitelisted
    API, nor instantiated by production code. It is compliance scaffolding kept
    correct-by-construction. Before relying on it, wire it into a scheduler job
    and finalize the PROVISIONAL retention periods/actions (notably the SEPA
    Mandate ones added below). Tracked in
    ``docs/testing/test-remediation/backlog-missing-coverage.md``.
    """

    # Default retention periods in days
    DEFAULT_RETENTION_PERIODS = {
        DataCategory.PAYMENT_DATA: 2555,  # 7 years for financial records
        # PROVISIONAL period for SEPA mandates. The concrete SEPA/GDPR rule
        # (mandates must be retained for ~14 months after their last collection,
        # then the IBAN PII anonymized) is deferred; 7 years is used as a safe
        # upper-bound placeholder so the plumbing is wired without under-retaining.
        DataCategory.MANDATE_DATA: 2555,
        DataCategory.PERSONAL_DATA: 1095,  # 3 years for personal data
        DataCategory.TRANSACTION_DATA: 2555,  # 7 years for transactions
        DataCategory.AUDIT_LOGS: 2555,  # 7 years for audit trails
        DataCategory.SECURITY_EVENTS: 365,  # 1 year for security events
        DataCategory.FINANCIAL_RECORDS: 2555,  # 7 years for financial
        DataCategory.CONSENT_RECORDS: 1095,  # 3 years for consent
        DataCategory.TEMPORARY_DATA: 30,  # 30 days for temporary data
    }

    # Default actions when retention expires
    DEFAULT_RETENTION_ACTIONS = {
        DataCategory.PAYMENT_DATA: RetentionAction.ANONYMIZE,
        # Anonymize (not delete): the mandate row is a legal/audit artifact, but
        # its IBAN/BIC PII must be scrubbed once retention expires. Concrete
        # anonymization specifics are deferred (see period comment above).
        DataCategory.MANDATE_DATA: RetentionAction.ANONYMIZE,
        DataCategory.PERSONAL_DATA: RetentionAction.DELETE,
        DataCategory.TRANSACTION_DATA: RetentionAction.ARCHIVE,
        DataCategory.AUDIT_LOGS: RetentionAction.ARCHIVE,
        DataCategory.SECURITY_EVENTS: RetentionAction.DELETE,
        DataCategory.FINANCIAL_RECORDS: RetentionAction.ARCHIVE,
        DataCategory.CONSENT_RECORDS: RetentionAction.ARCHIVE,
        DataCategory.TEMPORARY_DATA: RetentionAction.DELETE,
    }

    def __init__(self):
        """Initialize data retention policy manager"""
        self.retention_periods = self.DEFAULT_RETENTION_PERIODS.copy()
        self.retention_actions = self.DEFAULT_RETENTION_ACTIONS.copy()
        self.category_live_flags: Dict[DataCategory, bool] = {}
        self.legal_holds = {}
        self._load_custom_policies()

    def _load_custom_policies(self):
        """Load custom retention policies from the Data Retention Settings singleton.

        Robust to pre-migrate / absent DocType / empty table / unknown category
        strings — any of which leaves the code defaults in place.
        """
        # A Single DocType has no table of its own (stored in tabSingles), so
        # check for the DocType's METADATA, not a table.
        if not frappe.db.exists("DocType", "Data Retention Settings"):
            return
        try:
            settings = frappe.get_single("Data Retention Settings")
            rows = settings.get("category_policies") or []
        except Exception:
            # Child table tabData Retention Category Policy may not exist yet
            # (pre-migrate) -> keep code defaults.
            return

        by_value = {c.value: c for c in DataCategory}
        for row in rows:
            category = by_value.get(row.category)
            if category is None:
                frappe.logger("retention").warning(
                    f"Unknown retention category '{row.category}' in settings; skipping"
                )
                continue
            if row.retention_days:
                self.retention_periods[category] = int(row.retention_days)
            if row.action:
                try:
                    self.retention_actions[category] = RetentionAction(row.action)
                except ValueError:
                    frappe.logger("retention").warning(
                        f"Unknown retention action '{row.action}' for {row.category}; skipping"
                    )
            self.category_live_flags[category] = bool(row.live_enabled)

    def apply_retention_policies(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Apply retention policies to all data categories

        Args:
            dry_run: If True, only simulate without actual changes

        Returns:
            Dict with retention results
        """
        results = {
            "timestamp": now_datetime().isoformat(),
            "dry_run": dry_run,
            "categories_processed": [],
            "total_records_affected": 0,
            "errors": [],
        }

        for category in DataCategory:
            try:
                category_result = self._process_category(category, dry_run)
                results["categories_processed"].append(category_result)
                results["total_records_affected"] += category_result["records_affected"]
            except Exception as e:
                results["errors"].append({"category": category.value, "error": str(e)})

        # Log retention policy execution
        self._log_retention_execution(results)

        return results

    def _effective_dry_run(self, category: "DataCategory", dry_run: bool) -> bool:
        """Layered live-execution gate.

        A category runs LIVE only when the global dry_run is off AND the
        category is flagged live in settings AND it is in the code-level
        LIVE_CAPABLE_CATEGORIES allowlist. Monotonic: can only ever be MORE
        conservative than the raw dry_run.
        """
        is_live = (
            not dry_run
            and self.category_live_flags.get(category, False)
            and category in LIVE_CAPABLE_CATEGORIES
        )
        return not is_live

    def _process_category(self, category: DataCategory, dry_run: bool) -> Dict[str, Any]:
        """
        Process retention policy for a specific category

        Args:
            category: Data category to process
            dry_run: If True, only simulate

        Returns:
            Dict with category processing results
        """
        retention_days = self.retention_periods[category]
        retention_action = self.retention_actions[category]
        cutoff_date = add_days(now_datetime(), -retention_days)
        effective_dry_run = self._effective_dry_run(category, dry_run)

        result = {
            "category": category.value,
            "retention_days": retention_days,
            "action": retention_action.value,
            "cutoff_date": cutoff_date.isoformat(),
            "records_affected": 0,
            "records_held": 0,
        }

        # Process based on category
        if category == DataCategory.PAYMENT_DATA:
            result["records_affected"] = self._process_payment_data(
                cutoff_date, retention_action, effective_dry_run
            )

        elif category == DataCategory.PERSONAL_DATA:
            result["records_affected"] = self._process_personal_data(
                cutoff_date, retention_action, effective_dry_run
            )

        elif category == DataCategory.AUDIT_LOGS:
            result["records_affected"] = self._process_audit_logs(
                cutoff_date, retention_action, effective_dry_run
            )

        elif category == DataCategory.TEMPORARY_DATA:
            result["records_affected"] = self._process_temporary_data(
                cutoff_date, retention_action, effective_dry_run
            )

        # Check for legal holds
        held_records = self._check_legal_holds(category, cutoff_date)
        result["records_held"] = len(held_records)

        return result

    def _process_payment_data(self, cutoff_date: datetime, action: RetentionAction, dry_run: bool) -> int:
        """Process payment data retention"""

        # Find payment records older than cutoff
        old_payments = frappe.db.sql(
            """
            SELECT name, party, paid_amount, reference_no
            FROM `tabPayment Entry`
            WHERE creation < %s
                AND docstatus = 1
        """,
            cutoff_date,
            as_dict=True,
        )

        if dry_run:
            return len(old_payments)

        for payment in old_payments:
            if not self._is_on_legal_hold("Payment Entry", payment["name"]):
                if action == RetentionAction.ANONYMIZE:
                    self._anonymize_payment(payment)
                elif action == RetentionAction.DELETE:
                    self._delete_record("Payment Entry", payment["name"])
                elif action == RetentionAction.ARCHIVE:
                    self._archive_record("Payment Entry", payment)

        return len(old_payments)

    def _process_personal_data(self, cutoff_date: datetime, action: RetentionAction, dry_run: bool) -> int:
        """Process personal data retention"""

        # Find personal data records older than cutoff
        # This would process Member records and related personal information
        old_records = frappe.db.sql(
            """
            SELECT name, first_name, last_name, email, contact_number
            FROM `tabMember`
            WHERE creation < %s
                AND membership_status = 'Inactive'
        """,
            cutoff_date,
            as_dict=True,
        )

        if dry_run:
            return len(old_records)

        for record in old_records:
            if not self._is_on_legal_hold("Member", record["name"]):
                if action == RetentionAction.DELETE:
                    self._delete_personal_data(record)
                elif action == RetentionAction.ANONYMIZE:
                    self._anonymize_personal_data(record)

        return len(old_records)

    def _process_audit_logs(self, cutoff_date: datetime, action: RetentionAction, dry_run: bool) -> int:
        """Process audit log retention"""

        # Count audit logs older than cutoff
        count = frappe.db.count("Mollie Audit Log", {"timestamp": ["<", cutoff_date]})

        if dry_run or action != RetentionAction.ARCHIVE:
            return count

        # Archive old audit logs
        old_logs = frappe.db.sql(
            """
            SELECT *
            FROM `tabMollie Audit Log`
            WHERE timestamp < %s
        """,
            cutoff_date,
            as_dict=True,
        )

        for log in old_logs:
            if not self._is_on_legal_hold("Mollie Audit Log", log["name"]):
                self._archive_audit_log(log)

        return count

    def _process_temporary_data(self, cutoff_date: datetime, action: RetentionAction, dry_run: bool) -> int:
        """Process temporary data cleanup"""

        # Clean up temporary webhook data, cache, etc.
        temp_records = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMollie Audit Log`
            WHERE action = 'webhook_validation'
                AND timestamp < %s
        """,
            cutoff_date,
            as_dict=True,
        )[0]["count"]

        if not dry_run and action == RetentionAction.DELETE:
            frappe.db.sql(
                """
                DELETE FROM `tabMollie Audit Log`
                WHERE action = 'webhook_validation'
                    AND timestamp < %s
            """,
                cutoff_date,
            )

        return temp_records

    def _anonymize_payment(self, payment: Dict[str, Any]):
        """Anonymize payment data while preserving structure"""

        # Generate consistent anonymous ID
        anon_id = self._generate_anonymous_id(payment["name"])

        frappe.db.set_value(
            "Payment Entry",
            payment["name"],
            {
                "party": f"ANON_{anon_id}",
                "reference_no": f"REF_{anon_id}",
                "remarks": "Anonymized for data retention compliance",
            },
        )

    def _anonymize_personal_data(self, record: Dict[str, Any]):
        """Anonymize personal information"""

        anon_id = self._generate_anonymous_id(record["name"])

        frappe.db.set_value(
            "Member",
            record["name"],
            {
                "first_name": "Anonymous",
                "last_name": anon_id[:8],
                "email": f"anon_{anon_id}@example.com",
                "phone": "000-000-0000",
                "address": "Anonymized",
            },
        )

    def _delete_personal_data(self, record: Dict[str, Any]):
        """Delete personal data record"""

        # Check for dependencies before deletion
        dependencies = self._check_dependencies("Member", record["name"])

        if not dependencies:
            frappe.delete_doc("Member", record["name"], force=True)
        else:
            # If dependencies exist, anonymize instead
            self._anonymize_personal_data(record)

    def _archive_record(self, doctype: str, record: Dict[str, Any]):
        """Archive record to long-term storage"""

        # Create archive entry (would be stored in custom DocType)
        archive_data = {  # noqa: F841
            "doctype": doctype,
            "record_id": record.get("name"),
            "archived_date": now_datetime(),
            "data": json.dumps(record),
            "checksum": self._calculate_checksum(record),
        }

        # Store in archive table (would be custom DocType)
        # For now, just log the archival
        frappe.logger("retention").info(f"Archived {doctype} {record.get('name')}")

    def _archive_audit_log(self, log: Dict[str, Any]):
        """Archive audit log entry"""

        # Create compressed archive
        archive_entry = {
            "original_id": log["name"],
            "timestamp": log["timestamp"],
            "action": log["action"],
            "status": log["status"],
            "details": log.get("details"),
            "integrity_hash": log.get("integrity_hash"),
        }

        # Store in archive
        self._archive_record("Mollie Audit Log", archive_entry)

        # Do not delete audit logs - mark as archived instead
        frappe.db.set_value("Mollie Audit Log", log["name"], "archived", 1)

    def _delete_record(self, doctype: str, name: str):
        """Safely delete a record"""

        try:
            frappe.delete_doc(doctype, name, force=True)
        except Exception as e:
            frappe.logger("retention").error(f"Failed to delete {doctype} {name}: {str(e)}")

    def add_legal_hold(
        self,
        hold_id: str,
        doctype: str,
        filters: Optional[Dict[str, Any]] = None,
        reason: str = "",
        expiry_date: Optional[datetime] = None,
    ):
        """
        Add legal hold on records

        Args:
            hold_id: Unique identifier for the hold
            doctype: DocType to hold
            filters: Filters to identify records
            reason: Reason for legal hold
            expiry_date: When hold expires
        """
        self.legal_holds[hold_id] = {
            "doctype": doctype,
            "filters": filters or {},
            "reason": reason,
            "created_date": now_datetime(),
            "expiry_date": expiry_date,
            "created_by": frappe.session.user,
        }

        # Log legal hold creation
        self._log_legal_hold_event("created", hold_id)

    def remove_legal_hold(self, hold_id: str):
        """Remove legal hold"""

        if hold_id in self.legal_holds:
            del self.legal_holds[hold_id]
            self._log_legal_hold_event("removed", hold_id)

    def _is_on_legal_hold(self, doctype: str, name: str) -> bool:
        """Check if record is on legal hold"""

        for hold in self.legal_holds.values():
            if hold["doctype"] != doctype:
                continue

            # Check if hold has expired
            if hold.get("expiry_date") and get_datetime(hold["expiry_date"]) < now_datetime():
                continue

            # Check if record matches hold filters
            if self._matches_filters(doctype, name, hold["filters"]):
                return True

        return False

    def _check_legal_holds(self, category: DataCategory, cutoff_date: datetime) -> List[str]:
        """Get list of records on legal hold"""

        held_records = []

        # Check each legal hold
        for hold_id, hold in self.legal_holds.items():
            # Map category to DocType
            doctype = self._category_to_doctype(category)
            if doctype != hold["doctype"]:
                continue

            # Find matching records
            records = frappe.get_all(doctype, filters=hold["filters"], pluck="name")
            held_records.extend(records)

        return held_records

    def _category_to_doctype(self, category: DataCategory) -> str:
        """Map data category to DocType"""

        mapping = {
            DataCategory.PAYMENT_DATA: "Payment Entry",
            DataCategory.MANDATE_DATA: "SEPA Mandate",
            DataCategory.PERSONAL_DATA: "Member",
            DataCategory.TRANSACTION_DATA: "Sales Invoice",
            DataCategory.AUDIT_LOGS: "Mollie Audit Log",
            DataCategory.FINANCIAL_RECORDS: "Journal Entry",
        }

        return mapping.get(category, "")

    def _matches_filters(self, doctype: str, name: str, filters: Dict[str, Any]) -> bool:
        """Check if record matches filter criteria"""

        if not filters:
            return False

        # Build query with filters
        filters["name"] = name
        count = frappe.db.count(doctype, filters)

        return count > 0

    def _check_dependencies(self, doctype: str, name: str) -> List[Dict[str, str]]:
        """Check for record dependencies"""

        dependencies = []

        # Get linked doctypes
        links = frappe.get_all(
            "DocField", filters={"options": doctype, "fieldtype": "Link"}, fields=["parent", "fieldname"]
        )

        for link in links:
            # Check if any records reference this one
            count = frappe.db.count(link["parent"], {link["fieldname"]: name})
            if count > 0:
                dependencies.append({"doctype": link["parent"], "field": link["fieldname"], "count": count})

        return dependencies

    def _generate_anonymous_id(self, original_id: str) -> str:
        """Generate consistent anonymous ID"""

        # Use SHA256 to generate consistent but irreversible ID
        return hashlib.sha256(original_id.encode()).hexdigest()[:16]

    def _calculate_checksum(self, data: Any) -> str:
        """Calculate data checksum"""

        if isinstance(data, dict):
            data = json.dumps(data, sort_keys=True)

        return hashlib.sha256(str(data).encode()).hexdigest()

    def _log_retention_execution(self, results: Dict[str, Any]):
        """Log retention policy execution"""

        from .audit_trail import AuditEventType, AuditSeverity, get_audit_trail

        audit_trail = get_audit_trail()
        audit_trail.log_event(
            AuditEventType.DATA_DELETION if not results["dry_run"] else AuditEventType.REPORT_GENERATED,
            AuditSeverity.INFO,
            f"Data retention policy {'executed' if not results['dry_run'] else 'simulated'}",
            details=results,
        )

    def _log_legal_hold_event(self, action: str, hold_id: str):
        """Log legal hold events"""

        from .audit_trail import AuditEventType, AuditSeverity, get_audit_trail

        audit_trail = get_audit_trail()
        audit_trail.log_event(
            AuditEventType.CONFIGURATION_CHANGED,
            AuditSeverity.WARNING,
            f"Legal hold {action}: {hold_id}",
            details={"hold_id": hold_id, "action": action},
        )

    def get_retention_report(self) -> Dict[str, Any]:
        """Generate retention policy compliance report"""

        report = {
            "generated_at": now_datetime().isoformat(),
            "policies": {},
            "legal_holds": [],
            "statistics": {},
        }

        # Report on each category
        for category in DataCategory:
            report["policies"][category.value] = {
                "retention_days": self.retention_periods[category],
                "action": self.retention_actions[category].value,
                "record_count": self._count_category_records(category),
            }

        # Report on legal holds
        for hold_id, hold in self.legal_holds.items():
            report["legal_holds"].append(
                {
                    "id": hold_id,
                    "doctype": hold["doctype"],
                    "reason": hold["reason"],
                    "created_date": (
                        hold["created_date"].isoformat()
                        if isinstance(hold["created_date"], datetime)
                        else hold["created_date"]
                    ),
                    "expiry_date": hold["expiry_date"].isoformat() if hold.get("expiry_date") else None,
                }
            )

        # Calculate statistics
        report["statistics"] = {
            "total_categories": len(DataCategory),
            "active_legal_holds": len(self.legal_holds),
            "next_retention_run": self._get_next_retention_run(),
        }

        return report

    def _count_category_records(self, category: DataCategory) -> int:
        """Count records in category"""

        doctype = self._category_to_doctype(category)
        if doctype:
            return frappe.db.count(doctype)
        return 0

    def _get_next_retention_run(self) -> str:
        """Get next scheduled retention run"""

        # Would check actual schedule
        return add_days(now_datetime(), 1).isoformat()


def run_scheduled_retention_policies() -> Dict[str, Any]:
    """Weekly scheduler entrypoint: gated, dry-run-by-default retention run.

    Registered in hooks/scheduler.py under "weekly". Does nothing unless
    Data Retention Settings.enabled is on. Never raises out of the scheduler
    tick — failures are logged and recorded into last_run_summary.
    """
    settings = frappe.get_single("Data Retention Settings")
    if not settings.enabled:
        return {"skipped": True}

    dry_run = bool(settings.dry_run_only)
    try:
        policy = DataRetentionPolicy()
        results = policy.apply_retention_policies(dry_run=dry_run)
        summary = _summarize_retention_results(results)
        frappe.db.set_single_value(
            "Data Retention Settings",
            {"last_run": now_datetime(), "last_run_summary": summary},
            update_modified=False,
        )
        # The audit-trail logger buffers in memory; flush so the compliance
        # record is actually persisted for this low-frequency job.
        try:
            from .audit_trail import get_audit_trail

            get_audit_trail()._flush_buffer()
        except Exception:
            frappe.logger("retention").warning("audit-trail flush failed", exc_info=True)
        frappe.db.commit()
        return results
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Data retention run failed")
        frappe.db.set_single_value(
            "Data Retention Settings",
            {"last_run": now_datetime(), "last_run_summary": f"ERROR: {e}"},
            update_modified=False,
        )
        frappe.db.commit()
        return {"skipped": False, "error": str(e)}


def _summarize_retention_results(results: Dict[str, Any]) -> str:
    """Compact per-category summary for the settings singleton."""
    lines = [f"dry_run={results.get('dry_run')} total={results.get('total_records_affected', 0)}"]
    for cat in results.get("categories_processed", []):
        lines.append(f"{cat['category']}: {cat['records_affected']} ({cat['action']})")
    if results.get("errors"):
        lines.append(f"errors: {len(results['errors'])}")
    return "\n".join(lines)[:1000]
