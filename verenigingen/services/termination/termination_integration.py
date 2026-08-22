# ===== File: verenigingen/utils/termination_integration.py =====
"""Termination helpers: log the failure, return a count, let the caller carry on.

That contract is deliberate -- an admin's termination should not abort because one of
fourteen steps could not reach one chapter -- and it is wrong for exactly two errors.
``NON_RESUMABLE_DB_ERRORS`` (1213 deadlock, 1205 lock-wait timeout) do not describe a
step that failed; they describe a transaction the server has already discarded or left
half-applied. Recording one and carrying on means the writes these helpers go on to make
are issued on state that no longer exists, and the count they return describes writes
that did not survive. So every catch-all here re-raises those two first, before its own
handling. See ``verenigingen/utils/transaction_errors`` for what each one destroys.

Enforced across the whole ``services/termination`` package by
``tests/unit/test_termination_non_resumable_errors.py``: a catch-all added later must
carry the guard, and the guard's body must be a bare ``raise``. What that cannot check is
whether an exemption's stated reason is true, so the four exemptions in
``termination_execution_service`` remain a human claim. #470.
"""

import frappe
from frappe.utils import today

from verenigingen.utils import append_to_text_field
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

# Machine-readable marker written into a Team Member row's `notes` when a
# membership is soft-disabled by suspension. Restoration (unsuspension) only
# re-enables rows carrying this marker, so team rows that were already inactive
# *before* suspension are never wrongly reactivated.
SUSPENSION_TEAM_MARKER = "[SUSPENDED-TEAM-MEMBERSHIP]"


def cancel_membership_safe(
    membership_name, cancellation_date=None, cancellation_reason=None, cancellation_type="Immediate"
):
    """
    Cancel membership safely without modifying ERPNext core
    Uses direct document manipulation
    """
    try:
        if not cancellation_date:
            cancellation_date = today()

        membership = frappe.get_doc("Membership", membership_name)

        # Validate cancellation is allowed
        if membership.status == "Cancelled":
            frappe.logger().info(f"Membership {membership_name} already cancelled")
            return True

        # Set cancellation details
        membership.status = "Cancelled"
        membership.cancellation_date = cancellation_date
        membership.cancellation_reason = cancellation_reason or "Membership cancelled"
        membership.cancellation_type = cancellation_type

        # Cancel associated dues schedule if exists
        # Note: Membership doesn't have a dues_schedule field - query from Membership Dues Schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"membership": membership_name, "status": ["!=", "Cancelled"]}, "name"
        )
        if dues_schedule:
            cancel_dues_schedule_safe(dues_schedule)

        # Save with proper flags
        membership.flags.ignore_validate_update_after_submit = True

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        membership_result = secure_document_operation(
            operation="save",
            doc=membership,
            justification=f"Cancel membership {membership_name} with termination type {cancellation_type}",
            required_permissions=["Membership:write"],
        )

        if not membership_result.success:
            frappe.log_error(
                f"Failed to cancel membership: {'; '.join(membership_result.errors)}",
                "Membership Termination Security",
            )
            return False

        frappe.logger().info(f"Cancelled membership {membership_name}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to cancel membership {membership_name}: {str(e)}")
        return False


def cancel_dues_schedule_safe(dues_schedule_name):
    """
    Cancel dues schedule safely
    Handles edge cases with docstatus and data integrity issues
    """
    try:
        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)

        # Check if already cancelled
        if dues_schedule.status == "Cancelled":
            frappe.logger().info(f"Dues schedule {dues_schedule_name} already cancelled")
            return True

        # Handle edge case: docstatus=2 but status=Active (data inconsistency)
        if dues_schedule.docstatus == 2:
            frappe.logger().warning(
                f"Dues schedule {dues_schedule_name} has docstatus=2 but status={dues_schedule.status}, updating status"
            )
            # Direct update to fix inconsistency. No explicit commit: this function
            # is invoked from within TerminationExecutionService's savepoint block,
            # and a commit here would release that savepoint, causing
            # "SAVEPOINT does not exist" on context-manager exit.
            frappe.db.set_value("Membership Dues Schedule", dues_schedule_name, "status", "Cancelled")
            return True

        # Normal cancellation process
        dues_schedule.flags.ignore_validate_update_after_submit = True
        dues_schedule._skip_membership_validation = True  # Skip active membership check during termination

        try:
            # Update dues schedule status directly
            dues_schedule.status = "Cancelled"

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            dues_result = secure_document_operation(
                operation="save",
                doc=dues_schedule,
                justification=f"Cancel dues schedule {dues_schedule_name} during membership termination",
                required_permissions=["Membership Dues Schedule:write"],
            )

            if not dues_result.success:
                frappe.log_error(
                    f"Failed to cancel dues schedule: {'; '.join(dues_result.errors)}",
                    "Dues Schedule Termination Security",
                )
                return False
            frappe.logger().info(f"Cancelled dues schedule {dues_schedule_name} using standard method")
            return True

        except NON_RESUMABLE_DB_ERRORS:
            raise
        except Exception as cancel_error:
            frappe.logger().warning(
                f"Standard cancellation failed for {dues_schedule_name}: {str(cancel_error)}"
            )

            # Fallback: manual status update (safer approach)
            try:
                # Update status directly through database to avoid validation issues.
                # No explicit commit here either — see the docstatus==2 branch above.
                frappe.db.set_value(
                    "Membership Dues Schedule",
                    dues_schedule_name,
                    {"status": "Cancelled", "end_date": frappe.utils.today()},
                )
                frappe.logger().info(f"Cancelled dues schedule {dues_schedule_name} using fallback method")
                return True

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as fallback_error:
                frappe.logger().error(
                    f"Fallback cancellation also failed for {dues_schedule_name}: {str(fallback_error)}"
                )
                return False

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to cancel dues schedule {dues_schedule_name}: {str(e)}")
        return False


def cancel_sepa_mandate_safe(mandate_id, reason=None, cancellation_date=None):
    """
    Cancel SEPA mandate safely
    """
    try:
        if not cancellation_date:
            cancellation_date = today()

        mandate = frappe.get_doc("SEPA Mandate", mandate_id)

        # Update mandate status
        mandate.status = "Cancelled"
        mandate.is_active = 0
        mandate.cancelled_date = cancellation_date
        mandate.cancellation_reason = reason or "Mandate cancelled"

        # Add cancellation note
        cancellation_note = f"Cancelled on {cancellation_date}"
        if reason:
            cancellation_note += f" - Reason: {reason}"

        append_to_text_field(mandate, "notes", cancellation_note)

        # Save the mandate
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        mandate_result = secure_document_operation(
            operation="save",
            doc=mandate,
            justification=f"Cancel SEPA mandate {mandate_id} during member termination - {reason or 'Standard termination'}",
            required_permissions=["SEPA Mandate:write"],
        )

        if not mandate_result.success:
            frappe.log_error(
                f"Failed to cancel SEPA mandate: {'; '.join(mandate_result.errors)}",
                "SEPA Mandate Termination Security",
            )
            return False

        frappe.logger().info(f"Cancelled SEPA mandate {mandate.mandate_id}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to cancel SEPA mandate {mandate_id}: {str(e)}")
        return False


def update_customer_safe(customer_name, termination_note, disable_for_disciplinary=False):
    """
    Update customer record safely without modifying ERPNext core
    """
    try:
        customer = frappe.get_doc("Customer", customer_name)

        # Add to customer details field (standard ERPNext field)
        if hasattr(customer, "customer_details"):
            if customer.customer_details:
                customer.customer_details += f"\n\n{termination_note}"
            else:
                customer.customer_details = termination_note

        # For disciplinary terminations, disable the customer
        if disable_for_disciplinary:
            customer.disabled = 1

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=customer,
            justification=f"Update customer {customer_name} during member termination process - member lifecycle management",
            required_permissions=["Customer:write"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to update customer {customer_name} during termination: {'; '.join(result.errors)}"
            )
            return False

        frappe.logger().info(f"Updated customer {customer_name}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to update customer {customer_name}: {str(e)}")
        return False


def update_invoice_safe(invoice_name, termination_note):
    """
    Update invoice with termination note safely
    """
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        # Add to invoice remarks (standard ERPNext field)
        append_to_text_field(invoice, "remarks", termination_note)

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        # Note: preserve ignore_validate_update_after_submit for business requirement
        invoice.flags.ignore_validate_update_after_submit = True
        result = secure_document_operation(
            operation="save",
            doc=invoice,
            justification=f"Update invoice {invoice_name} with termination note - member termination documentation",
            required_permissions=["Sales Invoice:write"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to update invoice {invoice_name} during termination: {'; '.join(result.errors)}"
            )
            return False

        frappe.logger().info(f"Updated invoice {invoice_name}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to update invoice {invoice_name}: {str(e)}")
        return False


def cancel_outstanding_invoices_safe(customer_name, termination_reason=None):
    """
    Cancel all outstanding invoices for a customer
    WARNING: This operation cannot be undone
    """
    try:
        results = {
            "invoices_cancelled": 0,
            "invoices_deleted": 0,
            "errors": [],
        }

        # Find all outstanding invoices
        outstanding_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer_name,
                "docstatus": ["!=", 2],  # Not already cancelled
                "status": ["in", ["Unpaid", "Overdue", "Partially Paid"]],
            },
            fields=["name", "docstatus", "grand_total", "outstanding_amount"],
        )

        frappe.logger().info(
            f"Found {len(outstanding_invoices)} outstanding invoice(s) to cancel for {customer_name}"
        )

        for invoice_data in outstanding_invoices:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_data.name)

                # Add cancellation reason to remarks
                if termination_reason:
                    cancellation_note = f"Cancelled due to membership termination: {termination_reason}"
                    append_to_text_field(invoice, "remarks", cancellation_note)

                if invoice_data.docstatus == 1:
                    # Submitted invoice - cancel it
                    invoice.cancel()
                    results["invoices_cancelled"] += 1
                    frappe.logger().info(
                        f"Cancelled invoice {invoice_data.name} (Amount: {invoice_data.grand_total})"
                    )

                elif invoice_data.docstatus == 0:
                    # Draft invoice - delete it
                    invoice.delete()
                    results["invoices_deleted"] += 1
                    frappe.logger().info(
                        f"Deleted draft invoice {invoice_data.name} (Amount: {invoice_data.grand_total})"
                    )

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                error_msg = f"Failed to cancel invoice {invoice_data.name}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to cancel outstanding invoices for {customer_name}: {str(e)}")
        return {"invoices_cancelled": 0, "invoices_deleted": 0, "errors": [str(e)]}


def cancel_future_invoices_safe(customer_name, termination_date):
    """
    Cancel invoices whose coverage period starts after the termination date
    Member shouldn't be invoiced for periods they won't be a member
    """
    try:
        from frappe.utils import getdate

        # Validate required custom fields exist (per CLAUDE.md guidelines)
        if not frappe.db.exists(
            "Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_coverage_start_date"}
        ):
            frappe.logger().warning(
                "Custom field 'custom_coverage_start_date' not found on Sales Invoice - skipping future invoice cancellation"
            )
            return {
                "invoices_cancelled": 0,
                "invoices_deleted": 0,
                "errors": ["Custom coverage fields not configured"],
            }

        if not termination_date:
            termination_date = today()

        termination_date = getdate(termination_date)

        results = {
            "invoices_cancelled": 0,
            "invoices_deleted": 0,
            "errors": [],
        }

        # Find invoices with coverage start date after termination
        future_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer_name,
                "custom_coverage_start_date": [">", termination_date],
                "docstatus": ["!=", 2],  # Not already cancelled
            },
            fields=[
                "name",
                "docstatus",
                "custom_coverage_start_date",
                "custom_coverage_end_date",
                "grand_total",
            ],
        )

        frappe.logger().info(
            f"Found {len(future_invoices)} invoice(s) with coverage starting after {termination_date}"
        )

        for invoice_data in future_invoices:
            try:
                invoice = frappe.get_doc("Sales Invoice", invoice_data.name)

                if invoice_data.docstatus == 1:
                    # Submitted invoice - cancel it directly (can't modify submitted docs)
                    invoice.cancel()

                    results["invoices_cancelled"] += 1
                    frappe.logger().info(
                        f"Cancelled invoice {invoice_data.name} (coverage: {invoice_data.custom_coverage_start_date} to {invoice_data.custom_coverage_end_date})"
                    )

                elif invoice_data.docstatus == 0:
                    # Draft invoice - delete it
                    invoice.delete()

                    results["invoices_deleted"] += 1
                    frappe.logger().info(
                        f"Deleted draft invoice {invoice_data.name} (coverage: {invoice_data.custom_coverage_start_date} to {invoice_data.custom_coverage_end_date})"
                    )

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                error_msg = f"Failed to cancel invoice {invoice_data.name}: {str(e)}"
                results["errors"].append(error_msg)
                frappe.logger().error(error_msg)

        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to cancel future invoices for {customer_name}: {str(e)}")
        return {"invoices_cancelled": 0, "invoices_deleted": 0, "errors": [str(e)]}


def update_member_status_safe(member_name, termination_type, termination_date, termination_request=None):
    """
    Update member status safely using standard fields
    """
    try:
        member = frappe.get_doc("Member", member_name)

        # Map termination types to valid member status values
        # Note: Suspension has its own separate workflow - this is TERMINATION
        status_mapping = {
            "Voluntary": "Quit",  # Member chose to leave
            "Non-payment": "Quit",  # Termination for non-payment
            "Deceased": "Deceased",  # Special status for deceased members
            "Policy Violation": "Quit",  # Terminated for policy violation
            "Disciplinary Action": "Quit",  # Terminated for disciplinary reasons
            "Expulsion": "Banned",  # Permanent ban from organization
            "Administrative": "Quit",  # Administrative termination
        }

        target_status = status_mapping.get(termination_type, "Quit")

        # Update member status
        if hasattr(member, "status"):
            member.status = target_status

        # Set member end date
        if hasattr(member, "member_end_date"):
            member.member_end_date = termination_date

        # Clear next_invoice_date - terminated members shouldn't be invoiced
        if hasattr(member, "next_invoice_date"):
            member.next_invoice_date = None

        # Add termination information to notes (standard field)
        termination_note = f"Membership terminated on {termination_date} - Type: {termination_type}"
        if termination_request:
            termination_note += f" - Request: {termination_request}"

        append_to_text_field(member, "notes", termination_note)

        # CRITICAL: Set flag to prevent status being overridden by Membership hooks
        # When Membership.cancel() triggers member.save(), this flag prevents the status
        # from being changed from "Deceased" to "Quit" by membership validation logic
        member._termination_in_progress = True
        member._termination_final_status = target_status

        # Save the member with concurrency handling
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        member_result = secure_document_operation(
            operation="save",
            doc=member,
            justification=f"Update member {member_name} termination status to {status_mapping.get(termination_type, 'Quit')}",
            required_permissions=["Member:write"],
        )

        if not member_result.success:
            # Handle concurrency - reload and retry once
            try:
                member.reload()
                target_status = status_mapping.get(termination_type, "Quit")

                # Only update if status not already set (may have succeeded despite error)
                if member.status != target_status:
                    member.status = target_status

                # Only add note if not already present
                if termination_note not in (member.notes or ""):
                    append_to_text_field(member, "notes", termination_note)

                retry_result = secure_document_operation(
                    operation="save",
                    doc=member,
                    justification=f"Retry member {member_name} termination status update after reload",
                    required_permissions=["Member:write"],
                )

                if not retry_result.success:
                    frappe.log_error(
                        f"Failed to update member termination status (retry): {'; '.join(retry_result.errors)}",
                        "Member Termination Security",
                    )
                    return False
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.log_error(
                    f"Failed member termination status update: {str(e)}", "Member Termination Security"
                )
                return False

        frappe.logger().info(f"Updated member {member_name} status to {member.status}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to update member {member_name}: {str(e)}")
        return False


def end_board_positions_safe(member_name, end_date, reason):
    """
    End board positions safely by updating through parent Chapter document
    Child table records must be saved through their parent, not directly
    """
    try:
        # Get volunteer records for this member
        volunteer_records = frappe.get_all("Volunteer", filters={"member": member_name}, fields=["name"])

        positions_ended = 0
        chapters_to_save = {}  # Track chapters that need saving

        for volunteer_record in volunteer_records:
            # Get active board positions
            board_positions = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_record.name, "is_active": 1},
                fields=["name", "parent", "chapter_role", "from_date"],
            )

            for position in board_positions:
                try:
                    # Get the parent Chapter document (child tables must be saved through parent)
                    chapter_name = position.parent

                    # Load chapter only once per chapter
                    if chapter_name not in chapters_to_save:
                        chapters_to_save[chapter_name] = frappe.get_doc("Chapter", chapter_name)

                    chapter_doc = chapters_to_save[chapter_name]

                    # Find the board member in the child table
                    for board_member in chapter_doc.board_members:
                        if board_member.name == position.name:
                            board_member.is_active = 0
                            board_member.to_date = end_date

                            # Add reason to notes if field exists
                            append_to_text_field(board_member, "notes", f"Ended: {reason}")

                            positions_ended += 1
                            frappe.logger().info(
                                f"Marked board position {position.chapter_role} at {chapter_name} for ending"
                            )
                            break

                except NON_RESUMABLE_DB_ERRORS:
                    raise
                except Exception as e:
                    frappe.logger().error(f"Failed to end board position {position.name}: {str(e)}")

        # Save all modified chapters
        for chapter_name, chapter_doc in chapters_to_save.items():
            try:
                chapter_doc.save()
                frappe.logger().info(f"Saved Chapter {chapter_name} with ended board positions")
            except frappe.PermissionError as pe:
                frappe.logger().error(f"Permission denied saving Chapter {chapter_name}: {str(pe)}")
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.logger().error(f"Failed to save Chapter {chapter_name}: {str(e)}")

        return positions_ended

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to end board positions for {member_name}: {str(e)}")
        return 0


def disable_chapter_memberships_safe(member_name, leave_date, reason):
    """
    Disable all chapter memberships for terminated member.

    Updates both:
    1. Chapter Member child table (on Chapter doc) - sets enabled=0, status='Inactive'
    2. Member.chapter_membership_history (via ChapterMembershipHistoryManager) - sets end_date, status='Quit'

    Note: Chapter Member doesn't have a chapter_leave_date field - leave tracking is handled
    via Member.chapter_membership_history.end_date instead.

    Transaction Safety:
    - Uses savepoint for atomicity - if any chapter save fails, all changes are rolled back
    - History updates happen after chapter saves succeed, but Chapter.handle_member_changes()
      hook also updates history during save, providing redundant protection

    Idempotency:
    - Safe to call multiple times - both Chapter Member and history updates are idempotent
    """
    from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager

    try:
        # Get all active chapter memberships for this member
        chapter_memberships = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["name", "parent", "chapter_join_date"],
        )

        if not chapter_memberships:
            frappe.logger().info(f"No active chapter memberships found for {member_name}")
            return 0

        memberships_disabled = 0
        chapters_to_save = {}  # Track chapters that need saving
        history_updates = []  # Track history updates for explicit backup call

        for membership in chapter_memberships:
            try:
                chapter_name = membership.parent

                # Load chapter only once per chapter
                if chapter_name not in chapters_to_save:
                    chapters_to_save[chapter_name] = frappe.get_doc("Chapter", chapter_name)

                chapter_doc = chapters_to_save[chapter_name]

                # Find the member in the chapter's members child table
                for chapter_member in chapter_doc.members:
                    if chapter_member.name == membership.name:
                        # Validate field exists before setting (defensive coding)
                        if not hasattr(chapter_member, "status"):
                            frappe.logger().warning(
                                f"Chapter Member {chapter_member.name} missing status field - skipping status update"
                            )
                        else:
                            chapter_member.status = "Inactive"

                        chapter_member.enabled = 0
                        chapter_member.leave_reason = reason

                        # Queue history update as backup (Chapter.handle_member_changes hook
                        # will also update history during save, but this provides redundancy)
                        history_updates.append(
                            {
                                "chapter_name": chapter_name,
                                "assignment_type": "Member",
                            }
                        )

                        memberships_disabled += 1
                        frappe.logger().info(
                            f"Marked chapter membership at {chapter_name} for {member_name} as disabled (status=Inactive)"
                        )
                        break

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.logger().error(f"Failed to disable chapter membership {membership.name}: {str(e)}")

        # Use savepoint for transaction safety - rollback all on failure
        try:
            frappe.db.savepoint("disable_chapter_memberships")

            # Save all modified chapters within savepoint
            for chapter_name, chapter_doc in chapters_to_save.items():
                chapter_doc.save()
                frappe.logger().info(f"Saved Chapter {chapter_name} with disabled memberships")

            frappe.db.release_savepoint("disable_chapter_memberships")

        except frappe.PermissionError as pe:
            frappe.db.rollback_to_savepoint("disable_chapter_memberships")
            frappe.logger().error(f"Permission denied saving chapters, rolled back: {str(pe)}")
            return 0
        except NON_RESUMABLE_DB_ERRORS:
            # Ahead of the rollback, not just ahead of the return: a 1213 has already
            # discarded this savepoint along with the rest of the transaction, so
            # rollback_to_savepoint raises 1305 on top of the real error -- and the outer
            # catch-all then swallows THAT, losing both. There is nothing left to undo.
            raise
        except Exception as e:
            frappe.db.rollback_to_savepoint("disable_chapter_memberships")
            frappe.logger().error(f"Failed to save chapters, rolled back: {str(e)}")
            return 0

        # Explicit history update as backup - Chapter.handle_member_changes() hook should have
        # already updated history during save, but this call is idempotent and provides redundancy
        # in case the hook was bypassed or failed silently
        for update in history_updates:
            try:
                success = ChapterMembershipHistoryManager.terminate_chapter_membership(
                    member_id=member_name,
                    chapter_name=update["chapter_name"],
                    assignment_type=update["assignment_type"],
                    end_date=leave_date,
                    reason=reason,
                )
                if success:
                    frappe.logger().debug(
                        f"Verified/updated chapter membership history for {member_name} in {update['chapter_name']}"
                    )
                # Note: success=False is expected if hook already terminated it - not an error
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.logger().error(
                    f"Failed to update chapter membership history for {member_name} in {update['chapter_name']}: {str(e)}"
                )

        return memberships_disabled

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to disable chapter memberships for {member_name}: {str(e)}")
        return 0


def suspend_team_memberships_safe(member_name, termination_date, reason):
    """
    Soft-disable all active team memberships for a suspended/terminated member.

    Rows are marked inactive (and stamped with a suspension marker in `notes`)
    rather than deleted, so `restore_team_memberships_safe` can re-enable them on
    unsuspension. Returns the number of memberships affected.
    """
    try:
        if not termination_date:
            termination_date = today()

        teams_affected = 0

        # Get all active team memberships for this member
        # First get the volunteer linked to this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")

        team_memberships = []
        if volunteer_name:
            team_memberships = frappe.get_all(
                "Team Member",
                filters={
                    "volunteer": volunteer_name,
                    "docstatus": ["!=", 2],  # Not cancelled
                },
                fields=["name", "parent", "volunteer", "role"],
            )

        for team_membership in team_memberships:
            try:
                # Team Member is a child table (istable=1, never submittable) so rows are
                # always docstatus=0. We SOFT-disable (not delete) the row so that an
                # unsuspension can restore it — mirroring how user-account suspension
                # toggles `enabled` rather than deleting the User. Already-inactive rows
                # are skipped so we never count or re-stamp them.
                if not frappe.db.get_value("Team Member", team_membership.name, "is_active"):
                    continue

                try:
                    existing_notes = frappe.db.get_value("Team Member", team_membership.name, "notes")
                    suspension_note = f"{SUSPENSION_TEAM_MARKER} Suspended on {termination_date} - {reason}"
                    new_notes = f"{existing_notes}\n{suspension_note}" if existing_notes else suspension_note
                    frappe.db.set_value(
                        "Team Member",
                        team_membership.name,
                        {
                            "is_active": 0,
                            "status": "Inactive",
                            "to_date": termination_date,
                            "notes": new_notes,
                        },
                        update_modified=False,
                    )
                    teams_affected += 1
                    frappe.logger().info(
                        f"Suspended team membership for {team_membership.volunteer} in team {team_membership.parent}"
                    )
                except frappe.PermissionError as pe:
                    frappe.logger().error(
                        f"Permission denied for team membership suspension {team_membership.name}: {str(pe)}"
                    )
                    continue

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.logger().error(f"Failed to suspend team membership {team_membership.name}: {str(e)}")

        # Also check if member has any team leadership roles and remove those
        user_email = frappe.db.get_value("Member", member_name, "user")
        if user_email:
            teams_led = frappe.get_all(
                "Team", filters={"team_lead": user_email}, fields=["name", "team_lead"]
            )

            for team in teams_led:
                try:
                    team_doc = frappe.get_doc("Team", team.name)
                    team_doc.team_lead = None

                    # Add note about leadership change
                    termination_note = f"Team lead removed on {termination_date} - {reason}"
                    if hasattr(team_doc, "description"):
                        if team_doc.description:
                            team_doc.description += f"\n\n{termination_note}"
                        else:
                            team_doc.description = termination_note

                    try:
                        team_doc.save()
                    except frappe.PermissionError as pe:
                        frappe.logger().error(
                            f"Permission denied for team leadership update {team_doc.name}: {str(pe)}"
                        )
                        continue

                    frappe.logger().info(f"Removed team leadership from team {team.name}")

                except NON_RESUMABLE_DB_ERRORS:
                    raise
                except Exception as e:
                    frappe.logger().error(f"Failed to remove team leadership from {team.name}: {str(e)}")

        return teams_affected

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to suspend team memberships for {member_name}: {str(e)}")
        return 0


def restore_team_memberships_safe(member_name, restoration_reason):
    """
    Restore team memberships that were soft-disabled by a prior suspension.

    Counterpart to `suspend_team_memberships_safe`. Only re-enables rows that
    carry the suspension marker in their `notes` (written when suspended), so
    team rows that were already inactive before suspension are left untouched.
    Returns the number of memberships restored.
    """
    try:
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        if not volunteer_name:
            return 0

        teams_restored = 0

        suspended_memberships = frappe.get_all(
            "Team Member",
            filters={
                "volunteer": volunteer_name,
                "is_active": 0,
                "notes": ["like", f"%{SUSPENSION_TEAM_MARKER}%"],
                "docstatus": ["!=", 2],
            },
            fields=["name", "parent", "notes"],
        )

        for membership in suspended_memberships:
            try:
                restoration_note = f"Team membership restored on {today()} - {restoration_reason}"
                new_notes = (
                    f"{membership.notes}\n{restoration_note}" if membership.notes else restoration_note
                )
                frappe.db.set_value(
                    "Team Member",
                    membership.name,
                    {
                        "is_active": 1,
                        "status": "Active",
                        "to_date": None,
                        "notes": new_notes,
                    },
                    update_modified=False,
                )
                teams_restored += 1
                frappe.logger().info(
                    f"Restored team membership for volunteer {volunteer_name} in team {membership.parent}"
                )
            except frappe.PermissionError as pe:
                frappe.logger().error(
                    f"Permission denied for team membership restoration {membership.name}: {str(pe)}"
                )
                continue
            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as e:
                frappe.logger().error(f"Failed to restore team membership {membership.name}: {str(e)}")

        return teams_restored

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to restore team memberships for {member_name}: {str(e)}")
        return 0


def deactivate_user_account_safe(member_name, termination_type, reason, suspend_only=False):
    """
    Deactivate or suspend backend user account for terminated member
    """
    try:
        # Get the user associated with this member
        user_email = frappe.db.get_value("Member", member_name, "user")
        if not user_email:
            frappe.logger().info(f"No user account found for member {member_name}")
            return True

        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.logger().info(f"User {user_email} does not exist")
            return True

        user_doc = frappe.get_doc("User", user_email)

        # Determine action based on termination type and parameter
        disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]
        should_disable = termination_type in disciplinary_types and not suspend_only

        if should_disable:
            # Permanent disable for disciplinary actions
            user_doc.enabled = 0
            action_taken = "disabled"
            frappe.logger().info(f"Disabled user account {user_email} due to disciplinary termination")
        else:
            # For voluntary/non-payment, just disable to prevent login but preserve data
            user_doc.enabled = 0
            action_taken = "suspended"
            frappe.logger().info(f"Suspended user account {user_email}")

        # Add termination note to user bio/about
        termination_note = f"Account {action_taken} on {today()} - {reason}"
        append_to_text_field(user_doc, "bio", termination_note)

        # Clear user roles except basic ones for audit trail
        if should_disable and hasattr(user_doc, "roles"):
            # Keep only essential roles for audit purposes
            essential_roles = ["Guest"]
            user_doc.roles = [role for role in user_doc.roles if role.role in essential_roles]

        # Save user changes
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        user_result = secure_document_operation(
            operation="save",
            doc=user_doc,
            justification=f"{action_taken.capitalize()} user account {user_email} for member {member_name} - {reason}",
            required_permissions=["User:write"],
        )

        if not user_result.success:
            frappe.log_error(
                f"Failed to {action_taken} user account: {'; '.join(user_result.errors)}",
                "User Account Termination Security",
            )
            return False

        frappe.logger().info(f"Successfully {action_taken} user account {user_email}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to deactivate user account for {member_name}: {str(e)}")
        return False


def reactivate_user_account_safe(member_name, reason):
    """
    Reactivate user account (for appeal reversals)
    """
    try:
        user_email = frappe.db.get_value("Member", member_name, "user")
        if not user_email or not frappe.db.exists("User", user_email):
            return True

        user_doc = frappe.get_doc("User", user_email)
        user_doc.enabled = 1

        # Add reactivation note
        reactivation_note = f"Account reactivated on {today()} - {reason}"
        append_to_text_field(user_doc, "bio", reactivation_note)

        try:
            user_doc.save()
        except frappe.PermissionError as pe:
            frappe.logger().error(f"Permission denied for user reactivation {user_email}: {str(pe)}")
            return False

        frappe.logger().info(f"Reactivated user account {user_email}")
        return True

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to reactivate user account for {member_name}: {str(e)}")
        return False


def suspend_member_safe(
    member_name, suspension_reason, suspension_date=None, suspend_user=True, suspend_teams=True
):
    """
    Suspend a member (temporary, reversible action)
    """
    try:
        if not suspension_date:
            suspension_date = today()

        member = frappe.get_doc("Member", member_name)

        results = {
            "success": True,
            "actions_taken": [],
            "errors": [],
            "member_suspended": False,
            "user_suspended": False,
            "teams_suspended": 0,
        }

        # Check if member is already suspended
        if member.status == "Suspended":
            results["actions_taken"].append(f"Member {member_name} is already suspended")
            return results

        # 1. Update member status to Suspended
        original_status = member.status
        member.status = "Suspended"

        # Add suspension note (include original status for unsuspension reference)
        suspension_note = f"Member suspended on {suspension_date} - Reason: {suspension_reason}\n(Pre-suspension status: {original_status})"
        append_to_text_field(member, "notes", suspension_note)

        try:
            member.save()
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            member.reload()
            member.status = "Suspended"
            append_to_text_field(member, "notes", suspension_note)
            member.save()
        except frappe.PermissionError as pe:
            results["success"] = False
            results["errors"].append(f"Permission denied for member suspension: {str(pe)}")
            return results

        results["member_suspended"] = True
        results["actions_taken"].append(f"Member status changed from {original_status} to Suspended")

        # 2. Suspend user account if requested
        if suspend_user:
            # Check both the linked user field and for a user with the same email address
            user_from_link = frappe.db.get_value("Member", member_name, "user")
            member_email = frappe.db.get_value("Member", member_name, "email")

            # Try to find user by link field first, then by email
            user_email = None
            if user_from_link and frappe.db.exists("User", user_from_link):
                user_email = user_from_link
            elif member_email and frappe.db.exists("User", member_email):
                user_email = member_email

            if user_email:
                user_doc = frappe.get_doc("User", user_email)
                user_doc.enabled = 0

                # Add suspension note to user
                user_suspension_note = f"Account suspended on {suspension_date} - {suspension_reason}"
                append_to_text_field(user_doc, "bio", user_suspension_note)

                try:
                    user_doc.save()
                except frappe.PermissionError as pe:
                    results["errors"].append(f"Permission denied for user suspension: {str(pe)}")
                    # Continue with other operations even if user suspension fails
                    pass

                results["user_suspended"] = True
                results["actions_taken"].append(f"User account suspended ({user_email})")

        # 3. Suspend team memberships if requested
        if suspend_teams:
            teams_suspended = suspend_team_memberships_safe(
                member_name, suspension_date, f"Member suspended - {suspension_reason}"
            )
            results["teams_suspended"] = teams_suspended
            if teams_suspended > 0:
                results["actions_taken"].append(f"Suspended {teams_suspended} team membership(s)")

        frappe.logger().info(f"Successfully suspended member {member_name}")
        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to suspend member {member_name}: {str(e)}")
        return {"success": False, "error": str(e), "actions_taken": [], "errors": [str(e)]}


def unsuspend_member_safe(member_name, unsuspension_reason, restore_teams=True):
    """
    Unsuspend a member (restore from suspension)
    """
    try:
        member = frappe.get_doc("Member", member_name)

        results = {
            "success": True,
            "actions_taken": [],
            "errors": [],
            "member_unsuspended": False,
            "user_unsuspended": False,
            "teams_restored": 0,
        }

        # Check if member is actually suspended
        if member.status != "Suspended":
            return {
                "success": False,
                "error": f"Member {member_name} is not suspended (current status: {member.status})",
                "actions_taken": [],
                "errors": ["Member is not suspended"],
            }

        # 1. Restore member status
        # Try to extract pre-suspension status from notes (stored during suspension)
        restore_status = "Active"  # Default fallback
        if member.notes and "(Pre-suspension status:" in member.notes:
            import re

            match = re.search(r"\(Pre-suspension status: (\w+)\)", member.notes)
            if match:
                restore_status = match.group(1)
        member.status = restore_status

        # Add unsuspension note
        unsuspension_note = f"Member unsuspended on {today()} - Reason: {unsuspension_reason}"
        append_to_text_field(member, "notes", unsuspension_note)

        try:
            member.save()
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            member.reload()
            member.status = restore_status
            append_to_text_field(member, "notes", unsuspension_note)
            member.save()
        except frappe.PermissionError as pe:
            results["success"] = False
            results["errors"].append(f"Permission denied for member unsuspension: {str(pe)}")
            return results

        results["member_unsuspended"] = True
        results["actions_taken"].append(f"Member status restored to {restore_status}")

        # 2. Reactivate user account
        # Check both the linked user field and for a user with the same email address
        user_from_link = frappe.db.get_value("Member", member_name, "user")
        member_email = frappe.db.get_value("Member", member_name, "email")

        # Try to find user by link field first, then by email
        user_email = None
        if user_from_link and frappe.db.exists("User", user_from_link):
            user_email = user_from_link
        elif member_email and frappe.db.exists("User", member_email):
            user_email = member_email

        if user_email:
            user_doc = frappe.get_doc("User", user_email)

            # Only reactivate if it was disabled (not if it was disabled for other reasons)
            if not user_doc.enabled:
                user_doc.enabled = 1

                # Add unsuspension note
                user_unsuspension_note = f"Account unsuspended on {today()} - {unsuspension_reason}"
                append_to_text_field(user_doc, "bio", user_unsuspension_note)

                try:
                    user_doc.save()
                except frappe.PermissionError as pe:
                    results["errors"].append(f"Permission denied for user reactivation: {str(pe)}")
                    # Continue with other operations even if user reactivation fails

                results["user_unsuspended"] = True
                results["actions_taken"].append(f"User account reactivated ({user_email})")

        # 3. Restore team memberships that suspension soft-disabled. Suspension
        # records each disabled row with a marker in its `notes`, so this only
        # re-enables rows that suspension itself disabled (not ones that were
        # already inactive beforehand).
        if restore_teams:
            teams_restored = restore_team_memberships_safe(member_name, unsuspension_reason)
            results["teams_restored"] = teams_restored
            if teams_restored > 0:
                results["actions_taken"].append(f"Restored {teams_restored} team membership(s)")

        frappe.logger().info(f"Successfully unsuspended member {member_name}")
        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to unsuspend member {member_name}: {str(e)}")
        return {"success": False, "error": str(e), "actions_taken": [], "errors": [str(e)]}


def terminate_volunteer_records_safe(member_name, termination_type, termination_date, reason):
    """
    Terminate or update volunteer records associated with a member
    """
    try:
        if not termination_date:
            termination_date = today()

        results = {
            "volunteers_terminated": 0,
            "expense_claims_flagged": 0,
            "actions_taken": [],
            "errors": [],
        }

        # Get all volunteer records for this member
        volunteer_records = frappe.get_all(
            "Volunteer",
            filters={"member": member_name},
            fields=["name", "volunteer_name", "status"],
        )

        frappe.logger().info(f"Found {len(volunteer_records)} volunteer record(s) for member {member_name}")

        for volunteer_data in volunteer_records:
            try:
                volunteer_doc = frappe.get_doc("Volunteer", volunteer_data.name)

                # Update volunteer status based on termination type
                disciplinary_types = ["Policy Violation", "Disciplinary Action", "Expulsion"]

                # Update volunteer status (inactive_reason field doesn't exist,
                # so we store the reason in the note field instead)
                volunteer_doc.status = "Inactive"

                # Build termination note with reason
                if termination_type == "Deceased":
                    inactive_reason = "Deceased"
                elif termination_type in disciplinary_types:
                    inactive_reason = f"Member terminated - {termination_type}"
                else:
                    inactive_reason = f"Member terminated - {termination_type}"

                # Add termination note to the note field (not notes - that field doesn't exist)
                # Note: Volunteer DocType only has start_date, not end_date - termination date is recorded in note
                termination_note = f"Volunteer record updated on {termination_date} - {reason}\nInactive reason: {inactive_reason}"
                if volunteer_doc.note:
                    volunteer_doc.note += f"\n\n{termination_note}"
                else:
                    volunteer_doc.note = termination_note

                try:
                    volunteer_doc.save()
                except frappe.PermissionError as pe:
                    frappe.logger().error(
                        f"Permission denied for volunteer record termination {volunteer_doc.name}: {str(pe)}"
                    )
                    continue

                results["volunteers_terminated"] += 1
                results["actions_taken"].append(f"Updated volunteer record {volunteer_data.volunteer_name}")

                # Handle pending expense claims via HRMS Expense Claim (linked through employee_id)
                # Note: Volunteer Expense DocType was deprecated in favor of HRMS Expense Claim
                if volunteer_doc.employee_id:
                    pending_claims = frappe.get_all(
                        "Expense Claim",
                        filters={
                            "employee": volunteer_doc.employee_id,
                            "docstatus": 0,  # Draft status
                            "status": ["in", ["Draft", "Unpaid"]],
                        },
                        fields=["name"],
                    )

                    for claim in pending_claims:
                        try:
                            claim_doc = frappe.get_doc("Expense Claim", claim.name)
                            # Add note about volunteer termination - don't auto-reject as this needs HR review
                            termination_note = (
                                f"Note: Associated volunteer terminated on {termination_date} - {reason}"
                            )
                            if claim_doc.remark:
                                claim_doc.remark += f"\n\n{termination_note}"
                            else:
                                claim_doc.remark = termination_note
                            try:
                                claim_doc.save()
                                results["expense_claims_flagged"] += 1
                                results["actions_taken"].append(
                                    f"Flagged expense claim {claim.name} for review"
                                )
                            except frappe.PermissionError as pe:
                                results["errors"].append(
                                    f"Permission denied for expense claim update {claim.name}: {str(pe)}"
                                )
                        except NON_RESUMABLE_DB_ERRORS:
                            raise
                        except Exception as claim_error:
                            results["errors"].append(
                                f"Failed to flag expense claim {claim.name}: {str(claim_error)}"
                            )

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as volunteer_error:
                results["errors"].append(
                    f"Failed to update volunteer record {volunteer_data.name}: {str(volunteer_error)}"
                )

        frappe.logger().info(
            f"Terminated {results['volunteers_terminated']} volunteer record(s) for member {member_name}"
        )
        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to terminate volunteer records for {member_name}: {str(e)}")
        return {
            "volunteers_terminated": 0,
            "expense_claims_flagged": 0,
            "actions_taken": [],
            "errors": [str(e)],
        }


def terminate_employee_records_safe(member_name, termination_type, termination_date, reason):
    """
    Terminate or update employee records associated with a member
    """
    try:
        if not termination_date:
            termination_date = today()

        results = {"employees_terminated": 0, "actions_taken": [], "errors": []}

        # Get user email to find employee records
        user_email = frappe.db.get_value("Member", member_name, "user")

        # Method 1: Find employee records linked via user_id - enhanced detection
        employee_records = []
        if user_email:
            # Try user_id field first
            employee_records = frappe.get_all(
                "Employee",
                filters={"user_id": user_email, "status": ["in", ["Active", "On Leave"]]},
                fields=["name", "employee_name", "status", "relieving_date"],
            )

            # If no results with user_id, try alternative field names
            if not employee_records:
                # Try with personal_email field
                employee_records = frappe.get_all(
                    "Employee",
                    filters={"personal_email": user_email, "status": ["in", ["Active", "On Leave"]]},
                    fields=["name", "employee_name", "status", "relieving_date"],
                )

                # Try with company_email field
                if not employee_records:
                    employee_records = frappe.get_all(
                        "Employee",
                        filters={"company_email": user_email, "status": ["in", ["Active", "On Leave"]]},
                        fields=["name", "employee_name", "status", "relieving_date"],
                    )

        # Method 2: Check direct employee link from Member doctype
        direct_employee_link = frappe.db.get_value("Member", member_name, "employee")
        if direct_employee_link and frappe.db.exists("Employee", direct_employee_link):
            employee_status = frappe.db.get_value("Employee", direct_employee_link, "status")
            if employee_status in ["Active", "On Leave"]:
                # Check if this employee is already in the list to avoid duplicates
                already_included = any(emp.name == direct_employee_link for emp in employee_records)
                if not already_included:
                    direct_employee = frappe.get_doc("Employee", direct_employee_link)
                    # Must be a frappe._dict (not a plain dict): the rows from
                    # frappe.get_all above are _dicts and the loop below uses
                    # attribute access (employee_data.name). A plain dict would
                    # raise "'dict' object has no attribute 'name'", silently
                    # leaving a directly-linked employee un-terminated.
                    employee_records.append(
                        frappe._dict(
                            {
                                "name": direct_employee.name,
                                "employee_name": direct_employee.employee_name,
                                "status": direct_employee.status,
                                "relieving_date": getattr(direct_employee, "relieving_date", None),
                            }
                        )
                    )

        frappe.logger().info(
            f"Found {len(employee_records)} active employee record(s) for member {member_name}"
        )

        for employee_data in employee_records:
            try:
                employee_doc = frappe.get_doc("Employee", employee_data.name)

                # Update employee status based on termination type
                if termination_type == "Deceased":
                    employee_doc.status = "Left"
                    employee_doc.relieving_date = termination_date
                    employee_doc.reason_for_leaving = "Deceased"
                elif termination_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]:
                    employee_doc.status = "Left"
                    employee_doc.relieving_date = termination_date
                    employee_doc.reason_for_leaving = "Quit"
                else:
                    employee_doc.status = "Left"
                    employee_doc.relieving_date = termination_date
                    employee_doc.reason_for_leaving = "Resignation"

                # Add termination note to remarks
                termination_note = (
                    f"Employee record updated on {termination_date} due to member termination - {reason}"
                )
                append_to_text_field(employee_doc, "remarks", termination_note)

                try:
                    employee_doc.save()
                except frappe.PermissionError as pe:
                    results["errors"].append(
                        f"Permission denied for employee record termination {employee_doc.name}: {str(pe)}"
                    )
                    continue

                results["employees_terminated"] += 1
                results["actions_taken"].append(f"Updated employee record {employee_data.employee_name}")

            except NON_RESUMABLE_DB_ERRORS:
                raise
            except Exception as employee_error:
                results["errors"].append(
                    f"Failed to update employee record {employee_data.name}: {str(employee_error)}"
                )

        frappe.logger().info(
            f"Terminated {results['employees_terminated']} employee record(s) for member {member_name}"
        )
        return results

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to terminate employee records for {member_name}: {str(e)}")
        return {"employees_terminated": 0, "actions_taken": [], "errors": [str(e)]}


def get_member_suspension_status(member_name):
    """
    Get current suspension status of a member
    """
    try:
        member = frappe.get_doc("Member", member_name)

        is_suspended = member.status == "Suspended"

        # Get user account status
        user_suspended = False
        user_email = frappe.db.get_value("Member", member_name, "user")
        if user_email and frappe.db.exists("User", user_email):
            user_doc = frappe.get_doc("User", user_email)
            user_suspended = not user_doc.enabled

        # Check for active team memberships
        active_teams = 0
        if user_email:
            # Get volunteer linked to the user/member
            volunteer_name = frappe.db.get_value("Volunteer", {"user": user_email}, "name")
            if volunteer_name:
                active_teams = frappe.db.count("Team Member", {"volunteer": volunteer_name, "docstatus": 1})

        # Extract pre-suspension status from notes if available
        pre_suspension_status = None
        if is_suspended and member.notes and "(Pre-suspension status:" in member.notes:
            import re

            match = re.search(r"\(Pre-suspension status: (\w+)\)", member.notes)
            if match:
                pre_suspension_status = match.group(1)

        return {
            "is_suspended": is_suspended,
            "member_status": member.status,
            "user_suspended": user_suspended,
            "active_teams": active_teams,
            "pre_suspension_status": pre_suspension_status,
            "can_unsuspend": is_suspended,
        }

    except NON_RESUMABLE_DB_ERRORS:
        raise
    except Exception as e:
        frappe.logger().error(f"Failed to get suspension status for {member_name}: {str(e)}")
        return {"error": str(e), "is_suspended": False, "can_unsuspend": False}
