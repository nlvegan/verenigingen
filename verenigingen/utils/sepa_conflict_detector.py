"""
SEPA Batch Conflict Detection System

Advanced conflict detection mechanisms for overlapping SEPA batches,
duplicate invoice detection, and business rule validation.

Implements Week 3 Day 1-2 requirements from the SEPA billing improvements project.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now, today

from verenigingen.utils.error_handling import SEPAError, ValidationError, handle_api_error
from verenigingen.utils.performance_utils import performance_monitor


class ConflictSeverity(Enum):
    """Severity levels for detected conflicts"""

    CRITICAL = "critical"  # Block operation
    WARNING = "warning"  # Allow with warning
    INFO = "info"  # Informational only


@dataclass
class ConflictResult:
    """Result of conflict detection"""

    severity: ConflictSeverity
    conflict_type: str
    message: str
    affected_resources: List[str]
    suggested_action: str
    details: Dict[str, Any]


class SEPAConflictDetector:
    """
    Advanced conflict detection for SEPA batch operations

    Detects various types of conflicts including:
    - Invoice duplicates across batches
    - Schedule overlaps
    - Date conflicts
    - Business rule violations
    - Resource contention
    """

    def __init__(self):
        self.conflict_cache = {}
        self.cache_ttl = 300  # 5 minutes

    @performance_monitor(threshold_ms=1000)
    def detect_batch_creation_conflicts(self, batch_data: Dict[str, Any]) -> List[ConflictResult]:
        """
        Comprehensive conflict detection for batch creation

        Args:
            batch_data: Batch creation data including invoices, date, type

        Returns:
            List of detected conflicts
        """
        conflicts = []

        # Extract invoice information
        invoice_list = batch_data.get("invoice_list", [])
        batch_date = batch_data.get("batch_date")
        batch_type = batch_data.get("batch_type", "CORE")

        if not invoice_list:
            return [
                ConflictResult(
                    severity=ConflictSeverity.CRITICAL,
                    conflict_type="empty_batch",
                    message="No invoices provided for batch creation",
                    affected_resources=[],
                    suggested_action="Add invoices to the batch",
                    details={},
                )
            ]

        # 1. Invoice duplicate detection
        conflicts.extend(self._detect_invoice_duplicates(invoice_list))

        # 2. Cross-batch invoice conflicts
        conflicts.extend(self._detect_cross_batch_conflicts(invoice_list))

        # 3. Schedule overlap detection
        conflicts.extend(self._detect_schedule_overlaps(invoice_list, batch_date))

        # 4. Date-based conflicts
        conflicts.extend(self._detect_date_conflicts(batch_date, batch_type))

        # 5. Business rule conflicts
        conflicts.extend(self._detect_business_rule_conflicts(batch_data))

        # 6. SEPA mandate conflicts
        conflicts.extend(self._detect_mandate_conflicts(invoice_list))

        # 7. Amount reconciliation conflicts
        conflicts.extend(self._detect_amount_conflicts(invoice_list))

        # Sort conflicts by severity
        conflicts.sort(key=lambda x: self._get_severity_priority(x.severity), reverse=True)

        return conflicts

    def _detect_invoice_duplicates(self, invoice_list: List[Dict[str, Any]]) -> List[ConflictResult]:
        """Detect duplicate invoices within the same batch"""
        conflicts = []
        seen_invoices = set()

        for i, invoice in enumerate(invoice_list):
            invoice_id = invoice.get("invoice")
            if not invoice_id:
                continue

            if invoice_id in seen_invoices:
                conflicts.append(
                    ConflictResult(
                        severity=ConflictSeverity.CRITICAL,
                        conflict_type="duplicate_invoice",
                        message=f"Duplicate invoice in batch: {invoice_id}",
                        affected_resources=[invoice_id],
                        suggested_action="Remove duplicate invoice from batch",
                        details={"invoice_id": invoice_id, "position": i},
                    )
                )
            else:
                seen_invoices.add(invoice_id)

        return conflicts

    def _detect_cross_batch_conflicts(self, invoice_list: List[Dict[str, Any]]) -> List[ConflictResult]:
        """Detect invoices already in other active batches"""
        conflicts = []
        invoice_names = [inv.get("invoice") for inv in invoice_list if inv.get("invoice")]

        if not invoice_names:
            return conflicts

        try:
            # Query for existing batch assignments
            existing_assignments = frappe.db.sql(
                """
                SELECT
                    ddi.invoice,
                    ddb.name as batch_name,
                    ddb.status as batch_status,
                    ddb.batch_date,
                    ddb.batch_type,
                    ddb.creation,
                    ddb.total_amount
                FROM `tabDirect Debit Batch Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                WHERE ddi.invoice IN %(invoices)s
                AND ddb.docstatus != 2  -- Not cancelled
                AND ddb.status NOT IN ('Failed', 'Cancelled', 'Rejected')
                ORDER BY ddb.creation DESC
            """,
                {"invoices": invoice_names},
                as_dict=True,
            )

            # Group by invoice for detailed analysis
            invoice_conflicts = {}
            for assignment in existing_assignments:
                invoice_id = assignment.invoice
                if invoice_id not in invoice_conflicts:
                    invoice_conflicts[invoice_id] = []
                invoice_conflicts[invoice_id].append(assignment)

            # Analyze each conflict
            for invoice_id, assignments in invoice_conflicts.items():
                # Most recent assignment
                recent_assignment = assignments[0]

                # Determine conflict severity based on batch status
                if recent_assignment.batch_status in ["Draft", "Generated"]:
                    severity = ConflictSeverity.CRITICAL
                    action = f"Remove invoice from batch {recent_assignment.batch_name} or cancel that batch"
                elif recent_assignment.batch_status in ["Submitted", "Processing"]:
                    severity = ConflictSeverity.CRITICAL
                    action = "Cannot include invoice - already being processed"
                else:
                    severity = ConflictSeverity.WARNING
                    action = "Review invoice history before proceeding"

                conflicts.append(
                    ConflictResult(
                        severity=severity,
                        conflict_type="cross_batch_conflict",
                        message=f"Invoice {invoice_id} already in batch {recent_assignment.batch_name} (status: {recent_assignment.batch_status})",
                        affected_resources=[invoice_id, recent_assignment.batch_name],
                        suggested_action=action,
                        details={
                            "invoice_id": invoice_id,
                            "conflicting_batch": recent_assignment.batch_name,
                            "batch_status": recent_assignment.batch_status,
                            "batch_date": str(recent_assignment.batch_date),
                            "assignment_count": len(assignments),
                        },
                    )
                )

        except Exception as e:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.WARNING,
                    conflict_type="detection_error",
                    message=f"Error detecting cross-batch conflicts: {str(e)}",
                    affected_resources=invoice_names[:5],  # First 5 for context
                    suggested_action="Review batch manually for conflicts",
                    details={"error": str(e)},
                )
            )

        return conflicts

    def _detect_schedule_overlaps(
        self, invoice_list: List[Dict[str, Any]], batch_date: str
    ) -> List[ConflictResult]:
        """Detect conflicts with membership dues schedules"""
        conflicts = []

        if not batch_date:
            return conflicts

        try:
            # Get membership dues schedules for invoices
            invoice_names = [inv.get("invoice") for inv in invoice_list if inv.get("invoice")]
            if not invoice_names:
                return conflicts

            schedule_conflicts = frappe.db.sql(
                """
                SELECT
                    si.name as invoice,
                    si.custom_membership_dues_schedule as schedule_id,
                    mds.member,
                    mds.next_invoice_date,
                    mds.billing_frequency,
                    mds.status as schedule_status,
                    mem.full_name as member_name
                FROM `tabSales Invoice` si
                LEFT JOIN `tabMembership Dues Schedule` mds ON si.custom_membership_dues_schedule = mds.name
                LEFT JOIN `tabMember` mem ON mds.member = mem.name
                WHERE si.name IN %(invoices)s
                AND mds.name IS NOT NULL
                AND mds.status = 'Active'
            """,
                {"invoices": invoice_names},
                as_dict=True,
            )

            batch_date_obj = getdate(batch_date)

            for schedule in schedule_conflicts:
                if not schedule.next_due_date:
                    continue

                next_due = getdate(schedule.next_due_date)
                days_diff = (batch_date_obj - next_due).days

                # Check for schedule timing conflicts
                if days_diff < -30:  # Batch more than 30 days early
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.WARNING,
                            conflict_type="early_collection",
                            message=f"Invoice {schedule.invoice} scheduled for collection too early (next due: {schedule.next_due_date})",
                            affected_resources=[schedule.invoice, schedule.member],
                            suggested_action="Consider adjusting batch date or removing invoice",
                            details={
                                "invoice": schedule.invoice,
                                "member": schedule.member_name,
                                "next_due_date": str(schedule.next_due_date),
                                "batch_date": batch_date,
                                "days_early": abs(days_diff),
                            },
                        )
                    )
                elif days_diff > 90:  # Batch more than 90 days late
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.WARNING,
                            conflict_type="late_collection",
                            message=f"Invoice {schedule.invoice} overdue by {days_diff} days",
                            affected_resources=[schedule.invoice, schedule.member],
                            suggested_action="Review member status and collection policy",
                            details={
                                "invoice": schedule.invoice,
                                "member": schedule.member_name,
                                "next_due_date": str(schedule.next_due_date),
                                "batch_date": batch_date,
                                "days_overdue": days_diff,
                            },
                        )
                    )

        except Exception as e:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.INFO,
                    conflict_type="schedule_check_error",
                    message=f"Could not verify schedule overlaps: {str(e)}",
                    affected_resources=[],
                    suggested_action="Manually verify schedule conflicts",
                    details={"error": str(e)},
                )
            )

        return conflicts

    def _detect_date_conflicts(self, batch_date: str, batch_type: str) -> List[ConflictResult]:
        """Detect date-related conflicts"""
        conflicts = []

        if not batch_date:
            return [
                ConflictResult(
                    severity=ConflictSeverity.CRITICAL,
                    conflict_type="missing_date",
                    message="Batch date is required",
                    affected_resources=[],
                    suggested_action="Provide a valid batch date",
                    details={},
                )
            ]

        try:
            batch_date_obj = getdate(batch_date)
            today_obj = getdate(today())

            # Check for weekend collection
            if batch_date_obj.weekday() >= 5:  # Saturday = 5, Sunday = 6
                conflicts.append(
                    ConflictResult(
                        severity=ConflictSeverity.WARNING,
                        conflict_type="weekend_collection",
                        message=f"Batch date falls on weekend: {batch_date_obj.strftime('%A, %Y-%m-%d')}",
                        affected_resources=[batch_date],
                        suggested_action="Consider moving to next business day",
                        details={"day_of_week": batch_date_obj.strftime("%A")},
                    )
                )

            # Check for very early collection
            if batch_date_obj < today_obj:
                conflicts.append(
                    ConflictResult(
                        severity=ConflictSeverity.CRITICAL,
                        conflict_type="past_date",
                        message=f"Batch date is in the past: {batch_date}",
                        affected_resources=[batch_date],
                        suggested_action="Use a future date for collection",
                        details={"days_ago": (today_obj - batch_date_obj).days},
                    )
                )
            elif batch_date_obj > add_days(today_obj, 30):
                conflicts.append(
                    ConflictResult(
                        severity=ConflictSeverity.WARNING,
                        conflict_type="far_future_date",
                        message=f"Batch date is more than 30 days in future: {batch_date}",
                        affected_resources=[batch_date],
                        suggested_action="Consider using a nearer date",
                        details={"days_ahead": (batch_date_obj - today_obj).days},
                    )
                )

            # Check for existing batches on same date
            existing_batches = frappe.db.sql(
                """
                SELECT name, status, batch_type, total_amount, entry_count
                FROM `tabDirect Debit Batch`
                WHERE batch_date = %s
                AND docstatus != 2
                AND status NOT IN ('Failed', 'Cancelled')
            """,
                (batch_date,),
                as_dict=True,
            )

            for existing_batch in existing_batches:
                if existing_batch.status in ["Draft", "Generated"]:
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.WARNING,
                            conflict_type="same_date_batch",
                            message=f"Another batch exists for {batch_date}: {existing_batch.name} (€{existing_batch.total_amount})",
                            affected_resources=[batch_date, existing_batch.name],
                            suggested_action="Consider consolidating batches or using different date",
                            details={
                                "existing_batch": existing_batch.name,
                                "existing_status": existing_batch.status,
                                "existing_amount": existing_batch.total_amount,
                                "existing_count": existing_batch.entry_count,
                            },
                        )
                    )

        except Exception as e:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.WARNING,
                    conflict_type="date_validation_error",
                    message=f"Error validating batch date: {str(e)}",
                    affected_resources=[batch_date],
                    suggested_action="Verify date format and try again",
                    details={"error": str(e)},
                )
            )

        return conflicts

    def _detect_business_rule_conflicts(self, batch_data: Dict[str, Any]) -> List[ConflictResult]:
        """Detect business rule violations"""
        conflicts = []

        invoice_list = batch_data.get("invoice_list", [])
        batch_type = batch_data.get("batch_type", "CORE")

        # Check batch size limits
        if len(invoice_list) > 10000:  # SEPA limit
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.CRITICAL,
                    conflict_type="batch_size_limit",
                    message=f"Batch size exceeds SEPA limit of 10,000 transactions ({len(invoice_list)})",
                    affected_resources=[],
                    suggested_action="Split batch into smaller batches",
                    details={"batch_size": len(invoice_list), "limit": 10000},
                )
            )

        # Check total amount limits
        total_amount = sum(float(inv.get("amount", 0)) for inv in invoice_list)
        if total_amount > 999999999.99:  # SEPA amount limit
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.CRITICAL,
                    conflict_type="amount_limit",
                    message=f"Batch total amount exceeds SEPA limit (€{total_amount:,.2f})",
                    affected_resources=[],
                    suggested_action="Split batch or reduce amounts",
                    details={"total_amount": total_amount, "limit": 999999999.99},
                )
            )

        # Check for zero-amount invoices
        zero_amount_invoices = [
            inv.get("invoice") for inv in invoice_list if float(inv.get("amount", 0)) <= 0
        ]
        if zero_amount_invoices:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.WARNING,
                    conflict_type="zero_amount",
                    message=f"Found {len(zero_amount_invoices)} zero-amount invoices",
                    affected_resources=zero_amount_invoices,
                    suggested_action="Review zero-amount invoices",
                    details={"zero_amount_invoices": zero_amount_invoices},
                )
            )

        # Check batch type compatibility
        if batch_type == "B2B":
            # B2B requires special handling
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.INFO,
                    conflict_type="b2b_requirements",
                    message="B2B batch type requires additional validation",
                    affected_resources=[],
                    suggested_action="Ensure all debtors are businesses",
                    details={"batch_type": batch_type},
                )
            )

        return conflicts

    def _detect_mandate_conflicts(self, invoice_list: List[Dict[str, Any]]) -> List[ConflictResult]:
        """Detect SEPA mandate conflicts"""
        conflicts = []

        # Group invoices by mandate reference
        mandate_groups = {}
        for invoice in invoice_list:
            mandate_ref = invoice.get("mandate_reference")
            if mandate_ref:
                if mandate_ref not in mandate_groups:
                    mandate_groups[mandate_ref] = []
                mandate_groups[mandate_ref].append(invoice)

        if not mandate_groups:
            return conflicts

        try:
            # Validate mandate statuses
            mandate_refs = list(mandate_groups.keys())
            mandate_data = frappe.db.sql(
                """
                SELECT
                    mandate_id,
                    status,
                    valid_from,
                    valid_until,
                    member,
                    iban,
                    sign_date,
                    usage_count
                FROM `tabSEPA Mandate`
                WHERE mandate_id IN %(mandates)s
            """,
                {"mandates": mandate_refs},
                as_dict=True,
            )

            mandate_lookup = {m.mandate_id: m for m in mandate_data}

            for mandate_ref, invoices in mandate_groups.items():
                mandate = mandate_lookup.get(mandate_ref)

                if not mandate:
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="mandate_not_found",
                            message=f"SEPA mandate not found: {mandate_ref}",
                            affected_resources=[inv.get("invoice") for inv in invoices],
                            suggested_action="Verify mandate reference or create mandate",
                            details={"mandate_reference": mandate_ref, "affected_invoices": len(invoices)},
                        )
                    )
                    continue

                # Check mandate status
                if mandate.status != "Active":
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="inactive_mandate",
                            message=f"Mandate {mandate_ref} is not active (status: {mandate.status})",
                            affected_resources=[inv.get("invoice") for inv in invoices],
                            suggested_action="Activate mandate before processing",
                            details={"mandate_reference": mandate_ref, "status": mandate.status},
                        )
                    )

                # Check mandate expiry
                if mandate.valid_until and getdate(mandate.valid_until) < getdate(today()):
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="expired_mandate",
                            message=f"Mandate {mandate_ref} has expired (valid until: {mandate.valid_until})",
                            affected_resources=[inv.get("invoice") for inv in invoices],
                            suggested_action="Renew mandate before processing",
                            details={
                                "mandate_reference": mandate_ref,
                                "valid_until": str(mandate.valid_until),
                            },
                        )
                    )

                # Check for excessive usage on same mandate
                if len(invoices) > 50:  # Arbitrary business rule
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.WARNING,
                            conflict_type="high_mandate_usage",
                            message=f"High usage for mandate {mandate_ref}: {len(invoices)} invoices in batch",
                            affected_resources=[mandate_ref],
                            suggested_action="Review mandate usage pattern",
                            details={"mandate_reference": mandate_ref, "usage_count": len(invoices)},
                        )
                    )

        except Exception as e:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.WARNING,
                    conflict_type="mandate_check_error",
                    message=f"Error checking mandate conflicts: {str(e)}",
                    affected_resources=list(mandate_groups.keys()),
                    suggested_action="Manually verify mandate statuses",
                    details={"error": str(e)},
                )
            )

        return conflicts

    def _detect_amount_conflicts(self, invoice_list: List[Dict[str, Any]]) -> List[ConflictResult]:
        """Detect amount reconciliation conflicts"""
        conflicts = []

        invoice_names = [inv.get("invoice") for inv in invoice_list if inv.get("invoice")]
        if not invoice_names:
            return conflicts

        try:
            # Get current outstanding amounts from database
            db_amounts = frappe.db.sql(
                """
                SELECT name, outstanding_amount, status
                FROM `tabSales Invoice`
                WHERE name IN %(invoices)s
                AND docstatus = 1
            """,
                {"invoices": invoice_names},
                as_dict=True,
            )

            db_amount_lookup = {inv.name: inv for inv in db_amounts}

            for invoice in invoice_list:
                invoice_id = invoice.get("invoice")
                requested_amount = float(invoice.get("amount", 0))

                db_invoice = db_amount_lookup.get(invoice_id)
                if not db_invoice:
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="invoice_not_found",
                            message=f"Invoice missing from database: {invoice_id}",
                            affected_resources=[invoice_id],
                            suggested_action="Verify invoice exists and is submitted",
                            details={"invoice_id": invoice_id},
                        )
                    )
                    continue

                db_amount = float(db_invoice.outstanding_amount or 0)
                amount_diff = abs(requested_amount - db_amount)

                # Check for significant amount differences
                if amount_diff > 0.01:  # More than 1 cent difference
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="amount_mismatch",
                            message=f"Amount mismatch for invoice {invoice_id}: requested €{requested_amount}, outstanding €{db_amount}",
                            affected_resources=[invoice_id],
                            suggested_action="Use current outstanding amount",
                            details={
                                "invoice_id": invoice_id,
                                "requested_amount": requested_amount,
                                "outstanding_amount": db_amount,
                                "difference": amount_diff,
                            },
                        )
                    )

                # Check invoice status
                if db_invoice.status not in ["Unpaid", "Overdue"]:
                    conflicts.append(
                        ConflictResult(
                            severity=ConflictSeverity.CRITICAL,
                            conflict_type="invalid_status",
                            message=f"Invoice {invoice_id} is not unpaid (status: {db_invoice.status})",
                            affected_resources=[invoice_id],
                            suggested_action="Remove invoice from batch",
                            details={"invoice_id": invoice_id, "status": db_invoice.status},
                        )
                    )

        except Exception as e:
            conflicts.append(
                ConflictResult(
                    severity=ConflictSeverity.WARNING,
                    conflict_type="amount_check_error",
                    message=f"Error checking amount conflicts: {str(e)}",
                    affected_resources=invoice_names[:5],
                    suggested_action="Manually verify invoice amounts",
                    details={"error": str(e)},
                )
            )

        return conflicts

    def _get_severity_priority(self, severity: ConflictSeverity) -> int:
        """Get numeric priority for severity sorting"""
        priorities = {ConflictSeverity.CRITICAL: 3, ConflictSeverity.WARNING: 2, ConflictSeverity.INFO: 1}
        return priorities.get(severity, 0)

    def generate_conflict_report(self, conflicts: List[ConflictResult]) -> Dict[str, Any]:
        """Generate a comprehensive conflict report"""
        if not conflicts:
            return {
                "has_conflicts": False,
                "can_proceed": True,
                "summary": "No conflicts detected",
                "conflicts": [],
            }

        # Categorize conflicts
        critical_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]
        warning_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.WARNING]
        info_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.INFO]

        can_proceed = len(critical_conflicts) == 0

        summary_parts = []
        if critical_conflicts:
            summary_parts.append(f"{len(critical_conflicts)} critical conflicts")
        if warning_conflicts:
            summary_parts.append(f"{len(warning_conflicts)} warnings")
        if info_conflicts:
            summary_parts.append(f"{len(info_conflicts)} informational items")

        summary = f"Found {', '.join(summary_parts)}"

        return {
            "has_conflicts": True,
            "can_proceed": can_proceed,
            "summary": summary,
            "critical_count": len(critical_conflicts),
            "warning_count": len(warning_conflicts),
            "info_count": len(info_conflicts),
            "conflicts": [
                {
                    "severity": c.severity.value,
                    "type": c.conflict_type,
                    "message": c.message,
                    "affected_resources": c.affected_resources,
                    "suggested_action": c.suggested_action,
                    "details": c.details,
                }
                for c in conflicts
            ],
        }


# API Functions


@frappe.whitelist()
@handle_api_error
def detect_batch_conflicts(**batch_data) -> Dict[str, Any]:
    """
    API endpoint to detect conflicts for batch creation

    Args:
        **batch_data: Batch creation parameters

    Returns:
        Conflict detection report
    """
    detector = SEPAConflictDetector()
    conflicts = detector.detect_batch_creation_conflicts(batch_data)
    return detector.generate_conflict_report(conflicts)


@frappe.whitelist()
@handle_api_error
def validate_batch_with_conflicts(**batch_data) -> Dict[str, Any]:
    """
    API endpoint to validate batch and return detailed conflict analysis

    Args:
        **batch_data: Batch creation parameters

    Returns:
        Validation result with conflict details
    """
    detector = SEPAConflictDetector()
    conflicts = detector.detect_batch_creation_conflicts(batch_data)
    conflict_report = detector.generate_conflict_report(conflicts)

    return {
        "validation_passed": conflict_report["can_proceed"],
        "conflict_report": conflict_report,
        "recommendations": _generate_recommendations(conflicts),
        "next_steps": _generate_next_steps(conflicts),
    }


def _generate_recommendations(conflicts: List[ConflictResult]) -> List[str]:
    """Generate recommendations based on detected conflicts"""
    recommendations = []

    critical_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]

    if critical_conflicts:
        recommendations.append("Resolve all critical conflicts before proceeding")

        # Specific recommendations
        conflict_types = {c.conflict_type for c in critical_conflicts}

        if "duplicate_invoice" in conflict_types:
            recommendations.append("Remove duplicate invoices from the batch")

        if "cross_batch_conflict" in conflict_types:
            recommendations.append("Check other batches and remove conflicting invoices")

        if "amount_mismatch" in conflict_types:
            recommendations.append("Refresh invoice data to get current amounts")

        if "inactive_mandate" in conflict_types or "expired_mandate" in conflict_types:
            recommendations.append("Review and update SEPA mandates before processing")

    return recommendations


def _generate_next_steps(conflicts: List[ConflictResult]) -> List[str]:
    """Generate next steps based on conflict analysis"""
    next_steps = []

    critical_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.CRITICAL]
    warning_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.WARNING]

    if critical_conflicts:
        next_steps.append("1. Address all critical conflicts listed above")
        next_steps.append("2. Re-run conflict detection to verify resolution")
        next_steps.append("3. Proceed with batch creation once all critical issues are resolved")
    elif warning_conflicts:
        next_steps.append("1. Review warnings and determine if they can be ignored")
        next_steps.append("2. Consider adjusting batch parameters to reduce warnings")
        next_steps.append("3. Proceed with caution if warnings are acceptable")
    else:
        next_steps.append("1. No critical conflicts detected - batch can be created")
        next_steps.append("2. Proceed with batch creation")

    return next_steps
