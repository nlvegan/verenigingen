"""
Membership Dues Schedule Repository

Centralized data access layer for Membership Dues Schedule queries.
Eliminates duplication across 40+ query patterns in 159 files.

Architecture:
- Repository Pattern (data access abstraction)
- Type-safe with explicit return types
- Comprehensive error handling and logging
- Performance optimized with field-specific queries
- Security-aware with permission checks on mutations

Error Handling Strategy:
- **Read operations** (get_*, has_*): Return None/[]/False on errors, log internally
  - Callers check for None/empty without catching exceptions
  - Errors logged for debugging but don't bubble up
- **Mutation operations** (cancel_*, pause_*): Return CancellationResult with detailed error info
  - Success flag, message, method used, optional error list
  - Callers check result.success and handle accordingly
- **Simple updates** (update_*): Return bool for success/failure
  - True = success, False = failure (logged internally)

Transaction Management:
- All database operations let Frappe framework manage transaction boundaries
- No manual frappe.db.commit() calls - calling code controls atomicity
- Ensures proper rollback on errors in larger workflows

Usage:
    from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository

    repo = DuesScheduleRepository()
    schedule = repo.get_active_schedule("MEM-001")
    if schedule:
        print(f"Dues rate: €{schedule.dues_rate}")

Replaces patterns in:
- contribution_amendment_request.py (7+ instances)
- membership.py (6+ instances)
- member.py (4+ instances)
- member_utils.py (3 partial abstractions)
- 155 other files

Line reduction: ~840 lines across 159 files
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import today


class ScheduleStatus(Enum):
    """Schedule status enumeration for type safety"""

    ACTIVE = "Active"
    PAUSED = "Paused"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"
    DRAFT = "Draft"


@dataclass
class ScheduleInfo:
    """Type-safe schedule information container.

    All fields have defaults to allow partial data from queries that only
    fetch specific fields.
    """

    name: str = ""
    member: str = ""
    status: str = ""
    dues_rate: float = 0.0
    billing_frequency: str = ""
    next_invoice_date: Optional[str] = None
    last_invoice_date: Optional[str] = None
    membership_type: Optional[str] = None
    is_template: int = 0
    contribution_mode: Optional[str] = None
    uses_custom_amount: int = 0

    @classmethod
    def from_dict(cls, data: Dict) -> "ScheduleInfo":
        """Create from database dict - handles partial data gracefully"""
        if not data:
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class CancellationResult:
    """Result object for schedule cancellation operations"""

    success: bool
    schedule_name: str
    message: str
    method_used: str  # "standard", "fallback", "already_cancelled"
    errors: Optional[List[str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class DuesScheduleRepository:
    """
    Repository for Membership Dues Schedule data access.

    Consolidates 40+ duplicated query patterns from:
    - contribution_amendment_request.py (7+ patterns)
    - membership.py (6+ patterns)
    - member.py (4+ patterns)
    - member_utils.py (3 partial abstractions)
    - 155 other files

    Query Optimization:
    - Minimal field retrieval by default
    - Optional field expansion for complex operations
    - Single-query operations where possible

    Error Handling:
    - Returns None for not-found scenarios (no exceptions)
    - Logs errors for database issues
    - Type-safe return values
    """

    # Standard field sets for common queries
    BASIC_FIELDS = ["name", "member", "status"]
    FINANCIAL_FIELDS = ["name", "member", "status", "dues_rate", "billing_frequency"]
    FULL_FIELDS = [
        "name",
        "member",
        "status",
        "dues_rate",
        "billing_frequency",
        "next_invoice_date",
        "last_invoice_date",
        "membership_type",
        "contribution_mode",
        "uses_custom_amount",
        "is_template",
    ]

    def __init__(self):
        """Initialize repository"""
        self.doctype = "Membership Dues Schedule"

    # ===== HELPER METHODS =====

    def _create_schedule_info(self, data: Dict) -> ScheduleInfo:
        """Convert dict to type-safe ScheduleInfo"""
        return ScheduleInfo.from_dict(data)

    # ===== QUERY METHODS =====

    def get_active_schedule(
        self, member_name: str, fields: Optional[List[str]] = None
    ) -> Optional[ScheduleInfo]:
        """
        Get active dues schedule for a member.

        Replaces Pattern 1 (13+ instances):
        - contribution_amendment_request.py:206-210
        - membership.py:635
        - dues_schedule_health_manager.py:197
        - member_utils.py:989
        - 9+ more locations

        Args:
            member_name: Member document name
            fields: Optional field list (defaults to FINANCIAL_FIELDS)

        Returns:
            ScheduleInfo object if found, None otherwise

        Examples:
            >>> repo = DuesScheduleRepository()
            >>> schedule = repo.get_active_schedule("MEM-001")
            >>> if schedule:
            ...     print(f"Rate: €{schedule.dues_rate}/{schedule.billing_frequency}")
        """
        if not member_name:
            frappe.logger().warning("get_active_schedule called with empty member_name")
            return None

        fields = fields or self.FINANCIAL_FIELDS

        try:
            data = frappe.db.get_value(
                self.doctype,
                {"member": member_name, "status": "Active", "is_template": 0},
                fields,
                as_dict=True,
            )
            return ScheduleInfo.from_dict(data) if data else None

        except Exception as e:
            frappe.logger().error(f"Error retrieving active schedule for {member_name}: {str(e)}")
            return None

    def get_active_or_paused_schedule(
        self, member_name: str, fields: Optional[List[str]] = None
    ) -> Optional[ScheduleInfo]:
        """
        Get active OR paused schedule for a member.

        Replaces Pattern 2 (8+ instances):
        - contribution_amendment_request.py:640-643 (3 instances)
        - member.py:4079
        - member_utils.py:911 (existing helper, low adoption)
        - services/member/debug/member_debug_service.py:80
        - 2+ more locations

        Use case: Amendments and cancellations can operate on paused schedules

        Args:
            member_name: Member document name
            fields: Optional field list (defaults to FINANCIAL_FIELDS)

        Returns:
            ScheduleInfo object if found (Active or Paused), None otherwise

        Examples:
            >>> schedule = repo.get_active_or_paused_schedule("MEM-001")
            >>> if schedule and schedule.status == "Paused":
            ...     # Can still amend paused schedules
            ...     repo.update_schedule_amount(schedule.name, 25.0, "Amendment")
        """
        if not member_name:
            frappe.logger().warning("get_active_or_paused_schedule called with empty member_name")
            return None

        fields = fields or self.FINANCIAL_FIELDS

        try:
            data = frappe.db.get_value(
                self.doctype,
                {
                    "member": member_name,
                    "status": ["in", [ScheduleStatus.ACTIVE.value, ScheduleStatus.PAUSED.value]],
                    "is_template": 0,
                },
                fields,
                as_dict=True,
            )
            return ScheduleInfo.from_dict(data) if data else None

        except Exception as e:
            frappe.logger().error(f"Error retrieving active/paused schedule for {member_name}: {str(e)}")
            return None

    def get_schedule_by_name(
        self, schedule_name: str, fields: Optional[List[str]] = None
    ) -> Optional[ScheduleInfo]:
        """
        Get schedule by document name.

        Args:
            schedule_name: Schedule document name
            fields: Optional field list (defaults to FULL_FIELDS)

        Returns:
            ScheduleInfo object if found, None otherwise
        """
        if not schedule_name:
            return None

        fields = fields or self.FULL_FIELDS

        try:
            data = frappe.db.get_value(self.doctype, schedule_name, fields, as_dict=True)
            return ScheduleInfo.from_dict(data) if data else None

        except Exception as e:
            frappe.logger().error(f"Error retrieving schedule {schedule_name}: {str(e)}")
            return None

    def has_active_schedule(self, member_name: str) -> bool:
        """
        Check if member has active schedule (boolean).

        Replaces Pattern 4 (10+ instances):
        - member_utils.py:964-989 (existing helper)
        - Duplicate detection across multiple files

        Args:
            member_name: Member document name

        Returns:
            True if active schedule exists, False otherwise

        Examples:
            >>> if repo.has_active_schedule("MEM-001"):
            ...     print("Member has active billing")
        """
        if not member_name:
            return False

        try:
            return bool(
                frappe.db.exists(self.doctype, {"member": member_name, "status": "Active", "is_template": 0})
            )
        except Exception as e:
            frappe.logger().error(f"Error checking active schedule existence for {member_name}: {str(e)}")
            return False

    def get_template_for_membership_type(self, membership_type: str) -> Optional[ScheduleInfo]:
        """
        Get template schedule for a membership type.

        Replaces Pattern 5 (8+ instances):
        - api/membership_application_review.py:2025, 2038
        - Template lookup in various files

        Args:
            membership_type: Membership Type document name

        Returns:
            ScheduleInfo for template, None if not found

        Examples:
            >>> template = repo.get_template_for_membership_type("Regular Member")
            >>> if template:
            ...     print(f"Standard rate: €{template.dues_rate}")
        """
        if not membership_type:
            return None

        try:
            data = frappe.db.get_value(
                self.doctype,
                {"membership_type": membership_type, "is_template": 1, "status": "Active"},
                self.FULL_FIELDS,
                as_dict=True,
            )
            return ScheduleInfo.from_dict(data) if data else None

        except Exception as e:
            frappe.logger().error(f"Error retrieving template for {membership_type}: {str(e)}")
            return None

    def get_all_active_schedules(
        self, filters: Optional[Dict] = None, fields: Optional[List[str]] = None, limit: Optional[int] = None
    ) -> List[ScheduleInfo]:
        """
        Get all active schedules with optional filters.

        Replaces Pattern 6 (5+ instances):
        - utils/invoice_management.py:257
        - Report generators
        - Batch operations

        Args:
            filters: Additional filter dict (merged with status=Active, is_template=0)
            fields: Optional field list (defaults to FINANCIAL_FIELDS)
            limit: Optional result limit

        Returns:
            List of ScheduleInfo objects

        Examples:
            >>> # Get all active schedules ready for invoicing
            >>> schedules = repo.get_all_active_schedules(
            ...     filters={"auto_generate": 1},
            ...     fields=["name", "member", "next_invoice_date"]
            ... )
        """
        fields = fields or self.FINANCIAL_FIELDS
        base_filters = {"status": "Active", "is_template": 0}

        if filters:
            base_filters.update(filters)

        try:
            results = frappe.get_all(self.doctype, filters=base_filters, fields=fields, limit=limit)
            return [ScheduleInfo.from_dict(data) for data in results]

        except Exception as e:
            frappe.logger().error(f"Error retrieving active schedules: {str(e)}")
            return []

    # ===== MUTATION METHODS =====

    def cancel_schedule(
        self, schedule_name: str, reason: str, use_secure_operations: bool = False
    ) -> CancellationResult:
        """
        Cancel a dues schedule with robust error handling.

        Replaces Pattern 3 (6+ instances):
        - contribution_amendment_request.py:774-791, 912-928
        - termination_integration.py:62-135 (complex fallback logic)
        - membership.py:278-289

        Implements multi-tier cancellation strategy:
        1. Check if already cancelled (idempotent)
        2. Handle docstatus=2 inconsistency
        3. Standard document save
        4. Fallback to direct db.set_value

        Args:
            schedule_name: Schedule document name
            reason: Cancellation reason (for audit trail)
            use_secure_operations: Whether to use secure_document_operation (default False)

        Returns:
            CancellationResult with success status, message, and method used

        Examples:
            >>> result = repo.cancel_schedule(
            ...     "SCH-001",
            ...     "Member terminated membership"
            ... )
            >>> if result.success:
            ...     print(f"Cancelled using {result.method_used}")
        """
        if not schedule_name:
            return CancellationResult(
                success=False,
                schedule_name="",
                message="No schedule name provided",
                method_used="none",
                errors=["Empty schedule_name parameter"],
            )

        try:
            # ✅ SECURITY: Check write permission before modifying
            if not frappe.has_permission(self.doctype, "write", schedule_name):
                return CancellationResult(
                    success=False,
                    schedule_name=schedule_name,
                    message=f"Insufficient permissions to cancel schedule {schedule_name}",
                    method_used="none",
                    errors=["Permission denied: user lacks write access to Membership Dues Schedule"],
                )

            schedule = frappe.get_doc(self.doctype, schedule_name)

            # Idempotency: Already cancelled
            if schedule.status == "Cancelled":
                frappe.logger().info(f"Schedule {schedule_name} already cancelled")
                return CancellationResult(
                    success=True,
                    schedule_name=schedule_name,
                    message="Schedule was already cancelled",
                    method_used="already_cancelled",
                )

            # Handle docstatus=2 inconsistency (data integrity issue)
            if schedule.docstatus == 2:
                frappe.logger().warning(
                    f"Schedule {schedule_name} has docstatus=2 but status={schedule.status}, "
                    f"fixing inconsistency"
                )
                frappe.db.set_value(self.doctype, schedule_name, "status", "Cancelled")
                # ✅ TRANSACTION SAFETY: Let Frappe framework manage transaction boundaries
                # Calling code controls commit/rollback for proper atomicity
                return CancellationResult(
                    success=True,
                    schedule_name=schedule_name,
                    message="Fixed docstatus inconsistency and set status to Cancelled",
                    method_used="docstatus_fix",
                )

            # Standard cancellation
            schedule.flags.ignore_validate_update_after_submit = True
            schedule._skip_membership_validation = True
            schedule.status = "Cancelled"

            # Add cancellation comment for audit trail
            comment_text = f"Cancelled: {reason}"

            # Try standard save first
            try:
                schedule.save()
                schedule.add_comment(text=comment_text)
                frappe.logger().info(f"Cancelled schedule {schedule_name} using standard save")
                return CancellationResult(
                    success=True,
                    schedule_name=schedule_name,
                    message=f"Schedule cancelled successfully: {reason}",
                    method_used="standard_save",
                )

            except Exception as save_error:
                frappe.logger().warning(
                    f"Standard save failed for {schedule_name}: {str(save_error)}, trying fallback"
                )

            # Fallback: Direct database update
            try:
                frappe.db.set_value(
                    self.doctype,
                    schedule_name,
                    {"status": "Cancelled", "end_date": today()},
                    update_modified=True,
                )
                # ✅ TRANSACTION SAFETY: Let Frappe framework manage transaction boundaries
                # Calling code controls commit/rollback for proper atomicity

                # Add comment manually for audit trail
                # SECURITY JUSTIFICATION: ignore_permissions=True is acceptable here because:
                # 1. Write permission already verified at line 431 (frappe.has_permission)
                # 2. This is only for creating an audit Comment document, not modifying data
                # 3. Fallback path used only when standard add_comment() fails
                # 4. Comment records cancellation reason for compliance audit trail
                # Security: Adding audit comment to cancelled schedule.
                # Comments are system-generated audit trail, not user content.
                # Repository method called from service layer with proper authorization.
                frappe.get_doc(
                    {
                        "doctype": "Comment",
                        "comment_type": "Info",
                        "reference_doctype": self.doctype,
                        "reference_name": schedule_name,
                        "content": comment_text,
                    }
                ).insert(
                    ignore_permissions=True
                )  # Security: See justification at line 505

                frappe.logger().info(f"Cancelled schedule {schedule_name} using fallback method")
                return CancellationResult(
                    success=True,
                    schedule_name=schedule_name,
                    message=f"Schedule cancelled using fallback method: {reason}",
                    method_used="fallback_db_update",
                )

            except Exception as fallback_error:
                error_msg = str(fallback_error)
                frappe.logger().error(f"Fallback cancellation failed for {schedule_name}: {error_msg}")
                return CancellationResult(
                    success=False,
                    schedule_name=schedule_name,
                    message="All cancellation methods failed",
                    method_used="none",
                    errors=[f"Fallback error: {error_msg}"],
                )

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Failed to cancel schedule {schedule_name}: {error_msg}")
            return CancellationResult(
                success=False,
                schedule_name=schedule_name,
                message="Exception during cancellation",
                method_used="none",
                errors=[f"Exception: {error_msg}"],
            )

    def pause_schedule(self, schedule_name: str, reason: str) -> CancellationResult:
        """
        Pause a dues schedule (similar to cancel but status=Paused).

        Args:
            schedule_name: Schedule document name
            reason: Pause reason

        Returns:
            CancellationResult (reused for pause operations)
        """
        if not schedule_name:
            return CancellationResult(
                success=False,
                schedule_name="",
                message="No schedule name provided",
                method_used="none",
                errors=["Empty schedule_name parameter"],
            )

        try:
            # ✅ SECURITY: Check write permission before modifying
            if not frappe.has_permission(self.doctype, "write", schedule_name):
                return CancellationResult(
                    success=False,
                    schedule_name=schedule_name,
                    message=f"Insufficient permissions to pause schedule {schedule_name}",
                    method_used="none",
                    errors=["Permission denied: user lacks write access to Membership Dues Schedule"],
                )

            schedule = frappe.get_doc(self.doctype, schedule_name)

            if schedule.status == "Paused":
                return CancellationResult(
                    success=True,
                    schedule_name=schedule_name,
                    message="Schedule was already paused",
                    method_used="already_paused",
                )

            schedule.flags.ignore_validate_update_after_submit = True
            schedule._skip_membership_validation = True
            schedule.status = "Paused"
            schedule.save()
            schedule.add_comment(text=f"Paused: {reason}")

            return CancellationResult(
                success=True,
                schedule_name=schedule_name,
                message=f"Schedule paused: {reason}",
                method_used="standard",
            )

        except Exception as e:
            frappe.logger().error(f"Failed to pause schedule {schedule_name}: {str(e)}")
            return CancellationResult(
                success=False,
                schedule_name=schedule_name,
                message=str(e),
                method_used="none",
                errors=[str(e)],
            )

    def update_next_invoice_date(self, schedule_name: str, new_date: str) -> bool:
        """
        Update next_invoice_date (lightweight operation).

        Replaces Pattern 7 direct db.set_value calls.

        Args:
            schedule_name: Schedule document name
            new_date: New invoice date (YYYY-MM-DD format)

        Returns:
            True if successful, False otherwise
        """
        if not schedule_name or not new_date:
            frappe.logger().error("update_next_invoice_date called with empty parameters")
            return False

        try:
            # ✅ SECURITY: Check write permission before modifying
            if not frappe.has_permission(self.doctype, "write", schedule_name):
                frappe.logger().error(
                    f"Permission denied: user lacks write access to update schedule {schedule_name}"
                )
                return False

            frappe.db.set_value(
                self.doctype, schedule_name, "next_invoice_date", new_date, update_modified=False
            )
            return True
        except Exception as e:
            frappe.logger().error(f"Failed to update next_invoice_date for {schedule_name}: {str(e)}")
            return False

    def update_schedule_for_type_change(
        self,
        schedule_name: str,
        new_membership_type: str,
        new_dues_rate: float,
        new_billing_frequency: str,
        reason: str,
    ) -> CancellationResult:
        """
        Update a dues schedule for membership type change.

        Instead of cancelling and recreating, this updates the existing schedule
        with new rate and billing frequency from the new membership type.
        The change takes effect at the next billing cycle.

        Args:
            schedule_name: Schedule document name
            new_membership_type: New membership type name
            new_dues_rate: New dues rate amount
            new_billing_frequency: New billing frequency
            reason: Reason for the change (for audit trail)

        Returns:
            CancellationResult with success status and details
        """
        if not schedule_name:
            return CancellationResult(
                success=False,
                schedule_name="",
                message="No schedule name provided",
                method_used="none",
                errors=["No schedule name provided"],
            )

        try:
            # Check write permission
            if not frappe.has_permission(self.doctype, "write", schedule_name):
                return CancellationResult(
                    success=False,
                    schedule_name=schedule_name,
                    message="Permission denied: no write access to schedule",
                    method_used="none",
                    errors=["Permission denied"],
                )

            # Get the schedule document
            schedule = frappe.get_doc(self.doctype, schedule_name)

            # Store old values for logging
            old_membership_type = schedule.membership_type
            old_dues_rate = schedule.dues_rate
            old_billing_frequency = schedule.billing_frequency

            # Update the schedule
            schedule.membership_type = new_membership_type
            schedule.dues_rate = new_dues_rate
            # Only update billing frequency if a new one is provided
            # (billing_period is optional on membership type)
            if new_billing_frequency:
                schedule.billing_frequency = new_billing_frequency
            old_freq = old_billing_frequency or "unchanged"
            new_freq = new_billing_frequency or old_freq
            schedule.notes = f"{schedule.notes or ''}\n[{today()}] Type change: {old_membership_type} -> {new_membership_type}. Rate: {old_dues_rate} -> {new_dues_rate}. Freq: {old_freq} -> {new_freq}. Reason: {reason}".strip()

            schedule.save()

            frappe.logger().info(
                f"Updated schedule {schedule_name} for type change: "
                f"{old_membership_type} -> {new_membership_type}, "
                f"rate {old_dues_rate} -> {new_dues_rate}"
            )

            return CancellationResult(
                success=True,
                schedule_name=schedule_name,
                message=f"Schedule updated for membership type change to {new_membership_type}",
                method_used="update",
                errors=[],
            )

        except Exception as e:
            frappe.logger().error(f"Failed to update schedule {schedule_name} for type change: {str(e)}")
            return CancellationResult(
                success=False,
                schedule_name=schedule_name,
                message=str(e),
                method_used="none",
                errors=[str(e)],
            )

    # ===== BATCH OPERATIONS =====

    def get_schedules_for_members(
        self, member_names: List[str], fields: Optional[List[str]] = None
    ) -> List[ScheduleInfo]:
        """
        Batch retrieval of active schedules for multiple members.

        Performance: O(1) query instead of O(N) queries.
        Uses SQL IN clause for efficient bulk lookup.

        Args:
            member_names: List of member document names
            fields: Optional field list (defaults to BASIC_FIELDS)

        Returns:
            List of ScheduleInfo objects (may be fewer than input if some members have no schedule)

        Example:
            >>> member_names = ["MEM-001", "MEM-002", "MEM-003"]
            >>> schedules = repo.get_schedules_for_members(member_names)
            >>> # Single query instead of 3 separate queries
            >>> for schedule in schedules:
            ...     print(f"{schedule.member}: €{schedule.dues_rate}")
        """
        if not member_names:
            return []

        query_fields = fields or self.FINANCIAL_FIELDS

        try:
            schedules = frappe.get_all(
                self.doctype,
                filters={
                    "member": ["in", member_names],
                    "status": "Active",
                    "docstatus": ["!=", 2],
                },
                fields=query_fields,
            )

            return [self._create_schedule_info(s) for s in schedules]

        except Exception as e:
            frappe.logger().error(f"Error retrieving schedules for {len(member_names)} members: {str(e)}")
            return []

    def cancel_multiple_schedules(
        self, schedule_names: List[str], reason: str
    ) -> Dict[str, CancellationResult]:
        """
        Batch cancellation of multiple schedules.

        All operations execute within caller's transaction context.
        Partial failures are logged but don't stop processing.

        Args:
            schedule_names: List of schedule document names to cancel
            reason: Cancellation reason applied to all schedules

        Returns:
            Dict mapping schedule_name -> CancellationResult
            Check each result.success to identify failures

        Example:
            >>> results = repo.cancel_multiple_schedules(
            ...     ["SCH-001", "SCH-002", "SCH-003"],
            ...     "Chapter dissolution"
            ... )
            >>> failed = [name for name, r in results.items() if not r.success]
            >>> if failed:
            ...     print(f"Failed to cancel: {failed}")
        """
        results = {}

        if not schedule_names:
            return results

        for schedule_name in schedule_names:
            result = self.cancel_schedule(schedule_name, reason)
            results[schedule_name] = result

            if not result.success:
                frappe.logger().warning(f"Batch cancellation: {schedule_name} failed - {result.message}")

        return results

    def pause_multiple_schedules(
        self, schedule_names: List[str], reason: str
    ) -> Dict[str, CancellationResult]:
        """
        Batch pausing of multiple schedules.

        Similar to cancel_multiple_schedules but sets status to Paused.

        Args:
            schedule_names: List of schedule document names to pause
            reason: Pause reason applied to all schedules

        Returns:
            Dict mapping schedule_name -> CancellationResult
        """
        results = {}

        if not schedule_names:
            return results

        for schedule_name in schedule_names:
            result = self.pause_schedule(schedule_name, reason)
            results[schedule_name] = result

            if not result.success:
                frappe.logger().warning(f"Batch pause: {schedule_name} failed - {result.message}")

        return results
