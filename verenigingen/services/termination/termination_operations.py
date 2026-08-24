# File: verenigingen/utils/termination_operations.py
"""
Declarative operation pattern for membership termination execution.

This module provides a structured approach to executing termination operations
with consistent result tracking, error handling, and audit trail integration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List

import frappe

from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

if TYPE_CHECKING:
    from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
        MembershipTerminationRequest,
    )


@dataclass
class TerminationResults:
    """Tracks results of termination operations with structured data"""

    actions_taken: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    # Counters for each subsystem
    sepa_mandates_cancelled: int = 0
    memberships_cancelled: int = 0
    positions_ended: int = 0
    teams_suspended: int = 0
    dues_schedules_cancelled: int = 0
    invoices_updated: int = 0
    invoices_cancelled: int = 0
    invoices_deleted: int = 0
    outstanding_invoices_cancelled: int = 0
    volunteers_terminated: int = 0
    volunteer_expenses_cancelled: int = 0
    employees_terminated: int = 0

    # Boolean flags
    customer_updated: bool = False
    member_updated: bool = False
    user_deactivated: bool = False

    def record_action(self, action: str) -> None:
        """Record a successful action"""
        self.actions_taken.append(action)
        frappe.logger().debug(f"Termination action: {action}")

    def record_error(self, error: str) -> None:
        """Record an error"""
        self.errors.append(error)
        frappe.logger().warning(f"Termination error: {error}")

    def merge(self, other_results: Dict) -> None:
        """Merge results from a subsystem operation dynamically"""
        # Extend list fields
        if "actions_taken" in other_results:
            self.actions_taken.extend(other_results["actions_taken"])
        if "errors" in other_results:
            self.errors.extend(other_results["errors"])

        # Dynamically merge all numeric counters and boolean flags
        for key, value in other_results.items():
            if key in ["actions_taken", "errors"]:
                continue  # Already handled above

            if isinstance(value, int) and hasattr(self, key):
                # Merge integer counters by addition
                setattr(self, key, getattr(self, key, 0) + value)
            elif isinstance(value, bool) and hasattr(self, key):
                # Merge boolean flags with OR logic (any True makes result True)
                setattr(self, key, getattr(self, key, False) or value)

    def to_dict(self) -> Dict:
        """Convert to dictionary for backward compatibility"""
        return {
            "actions_taken": self.actions_taken,
            "errors": self.errors,
            "sepa_mandates_cancelled": self.sepa_mandates_cancelled,
            "memberships_cancelled": self.memberships_cancelled,
            "positions_ended": self.positions_ended,
            "teams_suspended": self.teams_suspended,
            "dues_schedules_cancelled": self.dues_schedules_cancelled,
            "invoices_updated": self.invoices_updated,
            "invoices_cancelled": self.invoices_cancelled,
            "invoices_deleted": self.invoices_deleted,
            "outstanding_invoices_cancelled": self.outstanding_invoices_cancelled,
            "customer_updated": self.customer_updated,
            "member_updated": self.member_updated,
            "volunteers_terminated": self.volunteers_terminated,
            "volunteer_expenses_cancelled": self.volunteer_expenses_cancelled,
            "employees_terminated": self.employees_terminated,
            "user_deactivated": self.user_deactivated,
        }


class TerminationOperation(ABC):
    """Base class for termination operations"""

    def __init__(self, member_name: str, termination_request: "MembershipTerminationRequest"):
        self.member_name = member_name
        self.termination_request = termination_request
        self.enabled = True
        self._member_doc = None  # Lazy-loaded cache

    @property
    def member_doc(self):
        """Lazy-load member document only when needed"""
        if self._member_doc is None:
            self._member_doc = frappe.get_doc("Member", self.member_name)
        return self._member_doc

    @abstractmethod
    def execute(self, results: TerminationResults) -> None:
        """Execute the operation and update results"""
        pass

    @property
    @abstractmethod
    def operation_name(self) -> str:
        """Human-readable name for logging"""
        pass

    def is_enabled(self) -> bool:
        """Check if this operation should run"""
        return self.enabled


class CancelMembershipsOperation(TerminationOperation):
    """Cancel all active memberships for the member"""

    @property
    def operation_name(self) -> str:
        return "Cancel Active Memberships"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import cancel_membership_safe

        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": self.member_name, "status": ["in", ["Active", "Pending"]], "docstatus": 1},
            fields=["name", "membership_type"],
        )

        frappe.logger().info(f"Found {len(active_memberships)} active memberships to cancel")

        for membership_data in active_memberships:
            if cancel_membership_safe(
                membership_data.name,
                self.termination_request.termination_date or today(),
                f"Member terminated - Request: {self.termination_request.name}",
                "Immediate",
            ):
                results.memberships_cancelled += 1
                results.record_action(f"Cancelled membership {membership_data.name}")
            else:
                results.record_error(f"Failed to cancel membership {membership_data.name}")


class CancelSEPAMandatesOperation(TerminationOperation):
    """Cancel all active SEPA mandates if requested"""

    def __init__(self, member_name: str, termination_request: "MembershipTerminationRequest"):
        super().__init__(member_name, termination_request)
        self.enabled = termination_request.cancel_sepa_mandates

    @property
    def operation_name(self) -> str:
        return "Cancel SEPA Mandates"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import cancel_sepa_mandate_safe

        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": self.member_name, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id"],
        )

        frappe.logger().info(f"Found {len(active_mandates)} SEPA mandates to cancel")

        for mandate_data in active_mandates:
            if cancel_sepa_mandate_safe(
                mandate_data.name,
                f"Member terminated - Request: {self.termination_request.name}",
                self.termination_request.termination_date or today(),
            ):
                results.sepa_mandates_cancelled += 1
                results.record_action(f"Cancelled SEPA mandate {mandate_data.mandate_id}")
            else:
                results.record_error(f"Failed to cancel SEPA mandate {mandate_data.mandate_id}")


class EndBoardPositionsOperation(TerminationOperation):
    """End board positions if requested"""

    def __init__(self, member_name: str, termination_request: "MembershipTerminationRequest"):
        super().__init__(member_name, termination_request)
        self.enabled = termination_request.end_board_positions

    @property
    def operation_name(self) -> str:
        return "End Board Positions"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import end_board_positions_safe

        positions_ended = end_board_positions_safe(
            self.member_name,
            self.termination_request.termination_date or today(),
            f"Member terminated - Request: {self.termination_request.name}",
        )
        results.positions_ended = positions_ended
        if positions_ended > 0:
            results.record_action(f"Ended {positions_ended} board position(s)")


class DisableChapterMembershipsOperation(TerminationOperation):
    """Disable all chapter memberships"""

    @property
    def operation_name(self) -> str:
        return "Disable Chapter Memberships"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import disable_chapter_memberships_safe

        memberships_disabled = disable_chapter_memberships_safe(
            self.member_name,
            self.termination_request.termination_date or today(),
            f"Member terminated - Type: {self.termination_request.termination_type}",
        )

        if memberships_disabled > 0:
            results.record_action(f"Disabled {memberships_disabled} chapter membership(s)")


class SuspendTeamMembershipsOperation(TerminationOperation):
    """Suspend all team memberships"""

    @property
    def operation_name(self) -> str:
        return "Suspend Team Memberships"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import suspend_team_memberships_safe

        teams_suspended = suspend_team_memberships_safe(
            self.member_name,
            self.termination_request.termination_date or today(),
            f"Member terminated - Request: {self.termination_request.name}",
        )
        results.teams_suspended = teams_suspended
        if teams_suspended > 0:
            results.record_action(f"Suspended {teams_suspended} team membership(s)")


class DeactivateUserAccountOperation(TerminationOperation):
    """Deactivate the member's user account"""

    @property
    def operation_name(self) -> str:
        return "Deactivate User Account"

    def execute(self, results: TerminationResults) -> None:
        from verenigingen.services.termination.termination_integration import deactivate_user_account_safe

        termination_reason = (
            f"Member terminated - Type: {self.termination_request.termination_type} - "
            f"Request: {self.termination_request.name}"
        )

        if deactivate_user_account_safe(
            self.member_name, self.termination_request.termination_type, termination_reason
        ):
            results.user_deactivated = True
            results.record_action("Deactivated user account")
        else:
            results.user_deactivated = False
            results.record_error("Failed to deactivate user account")


class TerminateVolunteerRecordsOperation(TerminationOperation):
    """Terminate all volunteer records"""

    @property
    def operation_name(self) -> str:
        return "Terminate Volunteer Records"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import terminate_volunteer_records_safe

        termination_reason = (
            f"Member terminated - Type: {self.termination_request.termination_type} - "
            f"Request: {self.termination_request.name}"
        )

        volunteer_results = terminate_volunteer_records_safe(
            self.member_name,
            self.termination_request.termination_type,
            self.termination_request.termination_date or today(),
            termination_reason,
        )

        results.merge(volunteer_results)


class TerminateEmployeeRecordsOperation(TerminationOperation):
    """Terminate all employee records"""

    @property
    def operation_name(self) -> str:
        return "Terminate Employee Records"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import terminate_employee_records_safe

        termination_reason = (
            f"Member terminated - Type: {self.termination_request.termination_type} - "
            f"Request: {self.termination_request.name}"
        )

        employee_results = terminate_employee_records_safe(
            self.member_name,
            self.termination_request.termination_type,
            self.termination_request.termination_date or today(),
            termination_reason,
        )

        results.merge(employee_results)


class UpdateCustomerRecordOperation(TerminationOperation):
    """Update customer record with termination note"""

    def is_enabled(self) -> bool:
        """Only enabled if member has a customer record"""
        return bool(self.member_doc.customer)

    @property
    def operation_name(self) -> str:
        return "Update Customer Record"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import update_customer_safe

        if not self.enabled:
            return

        termination_note = (
            f"Member terminated on {self.termination_request.termination_date or today()} - "
            f"Type: {self.termination_request.termination_type} - "
            f"Request: {self.termination_request.name}"
        )

        # Never disable customer - Member status already indicates termination
        disable_customer = False

        if update_customer_safe(self.member_doc.customer, termination_note, disable_customer):
            results.customer_updated = True
            results.record_action("Updated customer record")
        else:
            results.record_error("Failed to update customer record")


class UpdateOutstandingInvoicesOperation(TerminationOperation):
    """Update outstanding invoices with termination note"""

    def is_enabled(self) -> bool:
        """Only enabled if member has a customer record"""
        return bool(self.member_doc.customer)

    @property
    def operation_name(self) -> str:
        return "Update Outstanding Invoices"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import update_invoice_safe

        if not self.enabled:
            return

        outstanding_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": self.member_doc.customer,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partially Paid"]],
            },
            fields=["name"],
        )

        termination_note = (
            f"Member terminated on {self.termination_request.termination_date or today()} - "
            f"Request: {self.termination_request.name}"
        )

        for invoice_data in outstanding_invoices:
            if update_invoice_safe(invoice_data.name, termination_note):
                results.invoices_updated += 1
            else:
                results.record_error(f"Failed to update invoice {invoice_data.name}")

        if results.invoices_updated > 0:
            results.record_action(f"Updated {results.invoices_updated} outstanding invoice(s)")


class CancelOutstandingInvoicesOperation(TerminationOperation):
    """Cancel outstanding invoices if requested (WARNING: Cannot be undone)"""

    def is_enabled(self) -> bool:
        """Only enabled if requested and member has customer record"""
        return self.termination_request.cancel_outstanding_invoices and bool(self.member_doc.customer)

    @property
    def operation_name(self) -> str:
        return "Cancel Outstanding Invoices"

    def execute(self, results: TerminationResults) -> None:
        from verenigingen.services.termination.termination_integration import cancel_outstanding_invoices_safe

        if not self.enabled:
            return

        termination_reason = (
            f"Member terminated - Type: {self.termination_request.termination_type} - "
            f"Request: {self.termination_request.name}"
        )

        outstanding_cancel_results = cancel_outstanding_invoices_safe(
            self.member_doc.customer, termination_reason
        )

        results.outstanding_invoices_cancelled = outstanding_cancel_results.get(
            "invoices_cancelled", 0
        ) + outstanding_cancel_results.get("invoices_deleted", 0)

        if results.outstanding_invoices_cancelled > 0:
            results.record_action(
                f"Cancelled {results.outstanding_invoices_cancelled} outstanding invoice(s)"
            )

        for error in outstanding_cancel_results.get("errors", []):
            results.record_error(error)


class CancelFutureInvoicesOperation(TerminationOperation):
    """Cancel invoices with coverage starting after termination date"""

    def is_enabled(self) -> bool:
        """Only enabled if member has a customer record"""
        return bool(self.member_doc.customer)

    @property
    def operation_name(self) -> str:
        return "Cancel Future Invoices"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import cancel_future_invoices_safe

        if not self.enabled:
            return

        future_invoice_results = cancel_future_invoices_safe(
            self.member_doc.customer, self.termination_request.termination_date or today()
        )

        results.invoices_cancelled = future_invoice_results.get("invoices_cancelled", 0)
        results.invoices_deleted = future_invoice_results.get("invoices_deleted", 0)

        if results.invoices_cancelled > 0:
            results.record_action(
                f"Cancelled {results.invoices_cancelled} future invoice(s) with coverage after termination"
            )
        if results.invoices_deleted > 0:
            results.record_action(
                f"Deleted {results.invoices_deleted} draft invoice(s) with coverage after termination"
            )

        for error in future_invoice_results.get("errors", []):
            results.record_error(error)


class CancelDuesSchedulesOperation(TerminationOperation):
    """Cancel all active membership dues schedules"""

    @property
    def operation_name(self) -> str:
        return "Cancel Dues Schedules"

    def execute(self, results: TerminationResults) -> None:
        from verenigingen.services.termination.termination_integration import cancel_dues_schedule_safe

        active_dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": self.member_name,
                "status": ["in", ["Active", "Past Due"]],
            },
            fields=["name"],
        )

        frappe.logger().info(f"Found {len(active_dues_schedules)} dues schedules to cancel")

        for dues_data in active_dues_schedules:
            if cancel_dues_schedule_safe(dues_data.name):
                results.dues_schedules_cancelled += 1
                results.record_action(f"Cancelled dues schedule {dues_data.name}")
            else:
                results.record_error(f"Failed to cancel dues schedule {dues_data.name}")


class UpdateMemberStatusOperation(TerminationOperation):
    """Update member status to Terminated - FINAL COMMIT POINT"""

    @property
    def operation_name(self) -> str:
        return "Update Member Status (FINAL)"

    def execute(self, results: TerminationResults) -> None:
        from frappe.utils import today

        from verenigingen.services.termination.termination_integration import update_member_status_safe

        if update_member_status_safe(
            self.member_name,
            self.termination_request.termination_type,
            self.termination_request.termination_date or today(),
            self.termination_request.name,
        ):
            results.member_updated = True
            results.record_action("Updated member status to Terminated")
            frappe.logger().info(f"Member {self.member_name} status updated to Terminated as final step")

            # Recalculate total membership duration after termination
            try:
                member_doc = frappe.get_doc("Member", self.member_name)
                member_doc.calculate_cumulative_membership_duration()
                member_doc.save(ignore_permissions=False)
                results.record_action("Recalculated total membership duration")
                frappe.logger().info(
                    f"Total membership duration recalculated for {self.member_name}: "
                    f"{member_doc.cumulative_membership_duration}"
                )
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as duration_error:
                error_msg = f"Failed to recalculate membership duration: {str(duration_error)}"
                results.record_error(error_msg)
                frappe.logger().error(f"Member {self.member_name} duration calculation failed: {error_msg}")
        else:
            results.record_error("Failed to update member status")
            frappe.logger().error(
                f"CRITICAL: Failed to update member {self.member_name} status - termination incomplete"
            )


class TerminationExecutor:
    """Executes a sequence of termination operations"""

    def __init__(self, operations: List[TerminationOperation]):
        self.operations = operations
        self._validate_operation_order()

    def _validate_operation_order(self) -> None:
        """Ensure UpdateMemberStatusOperation is the final operation (commit point)"""
        if not self.operations:
            return

        last_operation = self.operations[-1]
        if not isinstance(last_operation, UpdateMemberStatusOperation):
            frappe.throw(
                "UpdateMemberStatusOperation must be the final operation to ensure "
                "proper two-phase commit pattern. Member status change is the commit point "
                "and must occur after all other operations complete."
            )

        # Ensure UpdateMemberStatusOperation only appears once (at the end)
        for i, operation in enumerate(self.operations[:-1]):
            if isinstance(operation, UpdateMemberStatusOperation):
                frappe.throw(
                    f"UpdateMemberStatusOperation found at position {i}, but it must only "
                    "appear as the final operation (position {len(self.operations) - 1})"
                )

    def execute(self) -> Dict:
        """Execute all operations in sequence and return results"""
        results = TerminationResults()

        for operation in self.operations:
            if not operation.is_enabled():
                frappe.logger().debug(f"Skipping disabled operation: {operation.operation_name}")
                continue

            frappe.logger().info(f"Executing: {operation.operation_name}")

            try:
                operation.execute(results)
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                error_msg = f"{operation.operation_name} failed: {str(e)}"
                results.record_error(error_msg)
                frappe.logger().error(error_msg)
                # Continue with next operation - allow partial execution

        frappe.logger().info(
            f"Termination execution completed: {len(results.actions_taken)} actions, "
            f"{len(results.errors)} errors"
        )

        return results.to_dict()
