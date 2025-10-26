"""
SEPA Mandate Repository

Centralized data access layer for SEPA Mandate operations.
Extracts SEPA mandate management from member.py (lines 3279-3343).

Architecture:
- Repository Pattern (data access abstraction)
- Type-safe with explicit return types
- Comprehensive error handling and logging
- Security-aware with permission checks on mutations
- SQL injection prevention through parameterized queries

Error Handling Strategy:
- **Read operations**: Return None/[]/False on errors, log internally
- **Mutation operations**: Return MandateOperationResult with detailed error info
- **Batch operations**: Return dict mapping mandate_name -> result

Transaction Management:
- All database operations let Frappe framework manage transaction boundaries
- No manual frappe.db.commit() calls - calling code controls atomicity

Usage:
    from verenigingen.repositories.sepa_mandate_repository import SEPAMandateRepository

    repo = SEPAMandateRepository()
    mandates = repo.get_active_mandates_for_member("MEM-001")
    result = repo.deactivate_mandate_batch(
        mandate_names=["SEPA-001", "SEPA-002"],
        reason="IBAN changed"
    )
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import frappe
from frappe.utils import now, today


@dataclass
class MandateInfo:
    """Type-safe SEPA mandate information container"""

    name: str
    member: str
    iban: str
    status: str
    is_active: int
    mandate_id: Optional[str] = None
    sign_date: Optional[str] = None
    cancelled_date: Optional[str] = None
    cancellation_reason: Optional[str] = None


@dataclass
class MandateOperationResult:
    """Result of mandate mutation operation"""

    success: bool
    mandate_name: str
    message: str
    method_used: str
    errors: Optional[List[str]] = None


class SEPAMandateRepository:
    """Repository for SEPA Mandate data access operations"""

    def __init__(self):
        self.doctype = "SEPA Mandate"

    # ===== FIELD SETS FOR OPTIMIZED QUERIES =====

    BASIC_FIELDS = [
        "name",
        "member",
        "iban",
        "status",
        "is_active",
    ]

    FULL_FIELDS = BASIC_FIELDS + [
        "mandate_id",
        "sign_date",
        "cancelled_date",
        "cancellation_reason",
    ]

    # ===== HELPER METHODS =====

    def _create_mandate_info(self, data: Dict) -> MandateInfo:
        """Convert dict to type-safe MandateInfo"""
        return MandateInfo(
            name=data.get("name"),
            member=data.get("member"),
            iban=data.get("iban"),
            status=data.get("status"),
            is_active=data.get("is_active", 0),
            mandate_id=data.get("mandate_id"),
            sign_date=data.get("sign_date"),
            cancelled_date=data.get("cancelled_date"),
            cancellation_reason=data.get("cancellation_reason"),
        )

    # ===== QUERY METHODS =====

    def get_active_mandates_for_member(
        self, member_name: str, fields: Optional[List[str]] = None
    ) -> List[MandateInfo]:
        """
        Get all active SEPA mandates for a member.

        Replaces member.py pattern: frappe.get_all("SEPA Mandate", filters={...})

        Args:
            member_name: Member document name
            fields: Optional field list (defaults to BASIC_FIELDS)

        Returns:
            List of MandateInfo objects (empty list if none found)
        """
        if not member_name:
            return []

        query_fields = fields or self.BASIC_FIELDS

        try:
            mandates = frappe.get_all(
                self.doctype,
                filters={
                    "member": member_name,
                    "is_active": 1,
                    "status": "Active",
                },
                fields=query_fields,
            )

            return [self._create_mandate_info(m) for m in mandates]

        except Exception as e:
            frappe.logger().error(f"Error retrieving active mandates for {member_name}: {str(e)}")
            return []

    def get_mandate_by_name(
        self, mandate_name: str, fields: Optional[List[str]] = None
    ) -> Optional[MandateInfo]:
        """
        Get a specific SEPA mandate by name.

        Args:
            mandate_name: SEPA Mandate document name
            fields: Optional field list

        Returns:
            MandateInfo or None if not found
        """
        if not mandate_name:
            return None

        query_fields = fields or self.FULL_FIELDS

        try:
            mandate = frappe.db.get_value(self.doctype, mandate_name, query_fields, as_dict=True)

            if not mandate:
                return None

            return self._create_mandate_info(mandate)

        except Exception as e:
            frappe.logger().error(f"Error retrieving mandate {mandate_name}: {str(e)}")
            return None

    # ===== MUTATION METHODS =====

    def deactivate_mandate(
        self, mandate_name: str, reason: str, cancellation_date: Optional[str] = None
    ) -> MandateOperationResult:
        """
        Deactivate a single SEPA mandate.

        Sets status to 'Cancelled', is_active to 0, records reason and date.

        Args:
            mandate_name: SEPA Mandate document name
            reason: Cancellation reason (for audit trail)
            cancellation_date: Optional cancellation date (defaults to today)

        Returns:
            MandateOperationResult with success status and details
        """
        if not mandate_name:
            return MandateOperationResult(
                success=False,
                mandate_name="",
                message="No mandate name provided",
                method_used="none",
                errors=["Empty mandate_name parameter"],
            )

        try:
            # ✅ SECURITY: Check write permission before modifying
            if not frappe.has_permission(self.doctype, "write", mandate_name):
                return MandateOperationResult(
                    success=False,
                    mandate_name=mandate_name,
                    message=f"Insufficient permissions to deactivate mandate {mandate_name}",
                    method_used="none",
                    errors=["Permission denied: user lacks write access to SEPA Mandate"],
                )

            # Check if already cancelled (idempotency)
            current_status = frappe.db.get_value(self.doctype, mandate_name, "status")
            if current_status == "Cancelled":
                return MandateOperationResult(
                    success=True,
                    mandate_name=mandate_name,
                    message="Mandate was already cancelled",
                    method_used="already_cancelled",
                )

            # Prepare update data
            cancel_date = cancellation_date or today()
            modified_time = now()
            modified_by = frappe.session.user

            # ✅ SECURITY: Use parameterized query to prevent SQL injection
            frappe.db.sql(
                """
                UPDATE `tabSEPA Mandate`
                SET status = 'Cancelled',
                    is_active = 0,
                    cancelled_date = %s,
                    cancellation_reason = %s,
                    modified = %s,
                    modified_by = %s
                WHERE name = %s
                """,
                (cancel_date, reason, modified_time, modified_by, mandate_name),
            )

            frappe.logger().info(f"Deactivated SEPA mandate {mandate_name}: {reason}")

            return MandateOperationResult(
                success=True,
                mandate_name=mandate_name,
                message=f"Mandate deactivated: {reason}",
                method_used="direct_sql_update",
            )

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Failed to deactivate mandate {mandate_name}: {error_msg}")
            return MandateOperationResult(
                success=False,
                mandate_name=mandate_name,
                message="Exception during deactivation",
                method_used="none",
                errors=[f"Exception: {error_msg}"],
            )

    # ===== BATCH OPERATIONS =====

    def deactivate_mandate_batch(
        self, mandate_names: List[str], reason: str, cancellation_date: Optional[str] = None
    ) -> Dict[str, MandateOperationResult]:
        """
        Batch deactivation of multiple SEPA mandates.

        Replaces member.py:3279-3343 IBAN change batch deactivation.

        All operations execute within caller's transaction context.
        Partial failures are logged but don't stop processing.

        Args:
            mandate_names: List of SEPA Mandate document names
            reason: Cancellation reason applied to all mandates
            cancellation_date: Optional cancellation date (defaults to today)

        Returns:
            Dict mapping mandate_name -> MandateOperationResult
            Check each result.success to identify failures

        Example:
            >>> repo = SEPAMandateRepository()
            >>> results = repo.deactivate_mandate_batch(
            ...     mandate_names=["SEPA-001", "SEPA-002"],
            ...     reason="IBAN changed from NL91... to NL47..."
            ... )
            >>> failed = [name for name, r in results.items() if not r.success]
            >>> if failed:
            ...     frappe.msgprint(f"Failed to deactivate: {', '.join(failed)}")
        """
        results = {}

        if not mandate_names:
            return results

        for mandate_name in mandate_names:
            result = self.deactivate_mandate(mandate_name, reason, cancellation_date)
            results[mandate_name] = result

            if not result.success:
                frappe.logger().warning(f"Batch deactivation: {mandate_name} failed - {result.message}")

        return results

    def deactivate_mandates_for_member_iban_change(
        self, member_name: str, old_iban: str, new_iban: str
    ) -> Dict[str, MandateOperationResult]:
        """
        Deactivate all active mandates for a member due to IBAN change.

        This is a specialized batch operation that:
        1. Finds all active mandates for the member
        2. Deactivates each with a detailed reason including old/new IBAN
        3. Returns results for each mandate

        Replaces member.py:3279-3343 update_iban_deactivate_old_mandates pattern.

        Args:
            member_name: Member document name
            old_iban: Previous IBAN (for audit trail)
            new_iban: New IBAN (for audit trail)

        Returns:
            Dict mapping mandate_name -> MandateOperationResult
            Empty dict if no active mandates found

        Example:
            >>> repo = SEPAMandateRepository()
            >>> results = repo.deactivate_mandates_for_member_iban_change(
            ...     member_name="MEM-001",
            ...     old_iban="NL91 ABNA 0417 1643 00",
            ...     new_iban="NL47 RABO 0300 0652 64"
            ... )
            >>> success_count = sum(1 for r in results.values() if r.success)
            >>> frappe.msgprint(f"Deactivated {success_count} mandates due to IBAN change")
        """
        # Get active mandates for member
        mandates = self.get_active_mandates_for_member(member_name, fields=["name", "iban"])

        if not mandates:
            frappe.logger().info(f"No active mandates found for {member_name}, skipping deactivation")
            return {}

        # Build detailed reason with IBAN information
        results = {}
        for mandate in mandates:
            # Use mandate's actual IBAN in case it differs from old_iban parameter
            reason = f"IBAN changed from {mandate.iban} to {new_iban}"
            result = self.deactivate_mandate(mandate.name, reason)
            results[mandate.name] = result

        return results
