"""
Expense History Batch Processor

This module provides batch processing for expense claim history updates,
similar to the dues invoicing system. It includes:
- Scheduled tasks for bulk processing
- Event handlers with retry/timeout mechanisms
- Batch processing for large volumes
"""

import json
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now, today


class ExpenseHistoryBatchProcessor:
    """
    Batch processor for updating member expense history.

    Handles bulk updates, retries, and ensures data integrity.
    """

    def __init__(self):
        self.batch_size = 50
        self.max_retries = 3
        self.timeout_minutes = 10

    def process_pending_expense_updates(self):
        """
        Process all pending expense claim updates for members.

        This is the main scheduled task entry point.
        """
        try:
            # Get all approved expense claims that need to be added to member history
            pending_claims = self._get_pending_expense_claims()

            if not pending_claims:
                frappe.logger("expense_batch").info("No pending expense claims to process")
                return

            frappe.logger("expense_batch").info(f"Processing {len(pending_claims)} pending expense claims")

            # Process in batches
            total_processed = 0
            total_errors = 0

            for batch_start in range(0, len(pending_claims), self.batch_size):
                batch = pending_claims[batch_start : batch_start + self.batch_size]
                processed, errors = self._process_batch(batch)
                total_processed += processed
                total_errors += errors

            frappe.logger("expense_batch").info(
                f"Batch processing complete. Processed: {total_processed}, Errors: {total_errors}"
            )

            # Send notification if there were errors
            if total_errors > 0:
                self._notify_administrators_of_errors(total_errors)

        except Exception as e:
            frappe.log_error(
                f"Error in process_pending_expense_updates: {str(e)}",
                "Expense History Batch Processing Error",
            )

    def _get_pending_expense_claims(self) -> List[Dict]:
        """
        Get expense claims (all statuses) that are not yet in member history.

        Returns list of expense claims that need to be processed.
        """
        # Get all expense claims (draft, submitted, approved, rejected)
        all_claims = frappe.get_all(
            "Expense Claim",
            filters={"docstatus": ["in", [0, 1]]},  # Include both draft (0) and submitted (1)
            fields=[
                "name",
                "employee",
                "posting_date",
                "total_claimed_amount",
                "status",
                "approval_status",
                "docstatus",
            ],
        )

        if not all_claims:
            return []

        # Filter out claims that are already in member history
        pending_claims = []

        for claim in all_claims:
            if not self._is_claim_in_member_history(claim.name):
                # Check if this claim is for a volunteer
                member_id = self._get_member_from_employee(claim.employee)
                if member_id:
                    claim["member_id"] = member_id
                    pending_claims.append(claim)

        return pending_claims

    def _is_claim_in_member_history(self, expense_claim_name: str) -> bool:
        """Check if expense claim is already in any member's history"""
        existing = frappe.db.exists("Member Volunteer Expenses", {"expense_claim": expense_claim_name})
        return bool(existing)

    def _get_member_from_employee(self, employee_id: str) -> Optional[str]:
        """Get member ID from employee via volunteer linkage"""
        if not employee_id:
            return None

        volunteer = frappe.db.get_value("Volunteer", {"employee_id": employee_id}, ["name", "member"])

        if volunteer:
            return volunteer[1]  # member field
        return None

    def _process_batch(self, batch: List[Dict]) -> tuple[int, int]:
        """
        Process a batch of expense claims.

        Returns (processed_count, error_count)
        """
        processed = 0
        errors = 0

        for claim in batch:
            try:
                success = self._process_single_claim(claim)
                if success:
                    processed += 1
                else:
                    errors += 1

            except Exception as e:
                errors += 1
                frappe.log_error(
                    f"Error processing expense claim {claim.get('name')}: {str(e)}",
                    "Expense Claim Processing Error",
                )

        return processed, errors

    def _process_single_claim(self, claim: Dict) -> bool:
        """
        Process a single expense claim with retry logic.

        Returns True if successful, False otherwise.
        """
        for attempt in range(self.max_retries):
            try:
                # Get member document
                member = frappe.get_doc("Member", claim["member_id"])

                # Add expense to history using the ExpenseMixin method
                member.add_expense_to_history(claim["name"])

                frappe.logger("expense_batch").info(
                    f"Successfully processed expense claim {claim['name']} for member {claim['member_id']}"
                )
                return True

            except Exception as e:
                if attempt < self.max_retries - 1:
                    frappe.logger("expense_batch").warning(
                        f"Attempt {attempt + 1} failed for claim {claim['name']}: {str(e)}. Retrying..."
                    )
                    continue
                else:
                    frappe.log_error(
                        f"Failed to process expense claim {claim['name']} after {self.max_retries} attempts: {str(e)}",
                        "Expense Claim Processing Failure",
                    )
                    return False

        return False

    def _notify_administrators_of_errors(self, error_count: int):
        """Send notification to administrators about processing errors"""
        try:
            # Get administrators
            admins = frappe.get_all(
                "User", filters={"role_profile_name": "System Manager", "enabled": 1}, fields=["email"]
            )

            if not admins:
                return

            # Send email notification
            subject = f"Expense History Processing Errors - {error_count} failures"
            message = f"""
            The scheduled expense history batch processing encountered {error_count} errors.

            Please check the Error Log for details and resolve any issues.

            Date: {now()}
            """

            for admin in admins:
                if admin.email:
                    frappe.sendmail(recipients=[admin.email], subject=subject, message=message)

        except Exception as e:
            frappe.log_error(
                f"Failed to send error notification: {str(e)}", "Expense Batch Notification Error"
            )


# Scheduled task functions
@frappe.whitelist()
def process_pending_expense_history_updates():
    """
    Scheduled task to process pending expense history updates.

    Should be called daily from scheduler.
    """
    processor = ExpenseHistoryBatchProcessor()
    processor.process_pending_expense_updates()


@frappe.whitelist()
def validate_expense_history_integrity():
    """
    Scheduled task to validate expense history integrity.

    Checks for missing entries and data inconsistencies.
    Should be called weekly from scheduler.
    """
    try:
        # Check for approved expense claims missing from member history
        missing_claims = frappe.db.sql(
            """
            SELECT ec.name, ec.employee, ec.posting_date, v.member
            FROM `tabExpense Claim` ec
            JOIN `tabVolunteer` v ON v.employee_id = ec.employee
            LEFT JOIN `tabMember Volunteer Expenses` mve ON mve.expense_claim = ec.name
            WHERE ec.docstatus = 1
            AND ec.approval_status = 'Approved'
            AND mve.name IS NULL
        """,
            as_dict=True,
        )

        if missing_claims:
            frappe.logger("expense_integrity").warning(
                f"Found {len(missing_claims)} approved expense claims missing from member history"
            )

            # Auto-fix by processing them
            for claim in missing_claims:
                try:
                    member = frappe.get_doc("Member", claim.member)
                    member.add_expense_to_history(claim.name)
                    frappe.logger("expense_integrity").info(f"Auto-fixed missing expense claim {claim.name}")
                except Exception as e:
                    frappe.log_error(
                        f"Failed to auto-fix missing expense claim {claim.name}: {str(e)}",
                        "Expense History Auto-Fix Error",
                    )
        else:
            frappe.logger("expense_integrity").info("Expense history integrity check passed")

    except Exception as e:
        frappe.log_error(
            f"Error in validate_expense_history_integrity: {str(e)}", "Expense History Integrity Check Error"
        )


@frappe.whitelist()
def cleanup_orphaned_expense_history():
    """
    Cleanup orphaned expense history entries.

    Removes entries where the expense claim no longer exists or is not approved.
    Should be called monthly from scheduler.
    """
    try:
        # Find orphaned entries
        orphaned = frappe.db.sql(
            """
            SELECT mve.name, mve.expense_claim, mve.parent
            FROM `tabMember Volunteer Expenses` mve
            LEFT JOIN `tabExpense Claim` ec ON ec.name = mve.expense_claim
            WHERE ec.name IS NULL
            OR ec.docstatus != 1
            OR ec.approval_status != 'Approved'
        """,
            as_dict=True,
        )

        if orphaned:
            frappe.logger("expense_cleanup").info(
                f"Found {len(orphaned)} orphaned expense history entries to clean up"
            )

            for entry in orphaned:
                frappe.delete_doc("Member Volunteer Expenses", entry.name)

            frappe.db.commit()

            frappe.logger("expense_cleanup").info(
                f"Cleaned up {len(orphaned)} orphaned expense history entries"
            )
        else:
            frappe.logger("expense_cleanup").info("No orphaned expense history entries found")

    except Exception as e:
        frappe.log_error(
            f"Error in cleanup_orphaned_expense_history: {str(e)}", "Expense History Cleanup Error"
        )
