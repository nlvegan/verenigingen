"""
Direct Debit Batch API

This module provides secure API endpoints for managing SEPA direct debit batches
in the Verenigingen association management system. It handles the complete lifecycle
of direct debit processing including batch creation, validation, SEPA file generation,
and status tracking.

Key Features:
    - Secure batch management with role-based access control
    - SEPA-compliant direct debit processing
    - Batch validation and error handling
    - Performance monitoring and optimization
    - Comprehensive audit logging
    - Real-time status tracking and notifications

Business Process:
    1. Batch Creation: Create batches from membership dues schedules
    2. Validation: Validate member mandates and payment details
    3. SEPA Generation: Generate SEPA XML files for bank submission
    4. Processing: Track bank processing status and handle returns
    5. Reconciliation: Match bank confirmations with batch entries

Security Model:
    - High-security API endpoints for financial operations
    - SEPA-specific operation type validation
    - Permission-based access control
    - Input sanitization and validation
    - Comprehensive audit logging

Compliance:
    - SEPA Direct Debit Core Scheme compliance
    - Dutch banking standards (IBAN, BIC validation)
    - Data protection (GDPR) compliance
    - Financial audit trail requirements

Integration Points:
    - Bank file upload/download systems
    - eBoekhouden accounting software
    - Member mandate management
    - Notification and communication systems

Performance Considerations:
    - Batch processing for large member sets
    - Database optimization for frequent queries
    - Caching for mandate validation
    - Background job processing for heavy operations

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.communication.email_service import get_email_service

# Import security and error handling
from verenigingen.utils.constants import Roles
from verenigingen.utils.error_handling import (
    PermissionError,
    ValidationError,
    handle_api_error,
    log_error,
    validate_required_fields,
)
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def get_batch_list_with_security(filters: dict | None = None):
    """
    Retrieve a secured list of direct debit batches with comprehensive metadata.

    This function provides authorized users with access to direct debit batch information,
    applying security filters and performance optimizations. It's the primary endpoint
    for batch management interfaces and reporting systems.

    Args:
        filters (dict, optional): Optional filtering criteria for batch selection.
                                 Supported filters:
                                 - status (str): Batch status (Draft, Submitted, Processed, etc.)
                                 - from_date (str): Start date for batch_date range (YYYY-MM-DD)
                                 - to_date (str): End date for batch_date range (YYYY-MM-DD)

    Returns:
        dict: Comprehensive batch information with the following structure:
            {
                'success': True,
                'batches': [
                    {
                        'name': 'DD-BATCH-2024-001',
                        'batch_date': '2024-08-02',
                        'status': 'Processed',
                        'total_amount': 2500.00,
                        'entry_count': 25,
                        'owner': 'admin@example.com',
                        'creation': '2024-08-01 10:30:00',
                        'modified': '2024-08-02 14:15:00',
                        'sepa_file_generated': 1,
                        'pending_count': 0,
                        'processed_count': 23,
                        'failed_count': 2
                    }
                ],
                'total_batches': 1
            }

    Raises:
        PermissionError: If user lacks direct debit batch management permissions
        ValidationError: If filter parameters are invalid or malformed

    Security:
        - Validates user permissions for direct debit batch operations
        - Uses SEPA-specific security operation type
        - Excludes cancelled batches from results
        - Limits results to prevent performance issues

    Performance:
        - Monitoring threshold: 1000ms
        - Result limit: 100 batches maximum
        - Optimized queries with proper indexing
        - Efficient status count aggregation

    Business Logic:
        - Filters out cancelled batches (docstatus = 2)
        - Orders by batch date (descending) then creation time
        - Enhances results with entry status counts
        - Provides comprehensive batch metadata

    Database Access:
        - Reads from: tabDirect Debit Batch, tabDirect Debit Batch Invoice
        - Indexes used: batch_date, status, docstatus
        - Query optimization: Selective field retrieval, count aggregation
    """
    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to view direct debit batches")

    # Set default filters
    if not filters:
        filters = {}

    # Build query filters
    query_filters = {"docstatus": ["!=", 2]}  # Exclude cancelled batches

    # Apply user-provided filters
    if filters.get("status"):
        query_filters["status"] = filters["status"]

    if filters.get("from_date"):
        query_filters["batch_date"] = [">=", filters["from_date"]]

    if filters.get("to_date"):
        if "batch_date" in query_filters:
            query_filters["batch_date"] = ["between", [filters["from_date"], filters["to_date"]]]
        else:
            query_filters["batch_date"] = ["<=", filters["to_date"]]

    # Get batches
    batches = frappe.get_all(
        "Direct Debit Batch",
        filters=query_filters,
        fields=[
            "name",
            "batch_date",
            "status",
            "total_amount",
            "entry_count",
            "owner",
            "creation",
            "modified",
            "sepa_file_generated",
        ],
        order_by="batch_date desc, creation desc",
        limit=100,  # Limit for performance
    )

    # Enhance with additional information
    for batch in batches:
        # Add summary counts
        batch["pending_count"] = frappe.db.count(
            "Direct Debit Batch Invoice", {"parent": batch.name, "status": "Pending"}
        )

        batch["processed_count"] = frappe.db.count(
            "Direct Debit Batch Invoice", {"parent": batch.name, "status": "Processed"}
        )

        batch["failed_count"] = frappe.db.count(
            "Direct Debit Batch Invoice", {"parent": batch.name, "status": "Failed"}
        )

    return {"success": True, "batches": batches, "total_batches": len(batches)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=500)
def get_batch_details_with_security(batch_id):
    """
    Get detailed information about a specific batch.

    Args:
        batch_id (str): ID of the batch

    Returns:
        dict: Detailed batch information
    """
    # Validate input
    validate_required_fields({"batch_id": batch_id}, ["batch_id"])

    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to view batch details")

    # Check if batch exists
    if not frappe.db.exists("Direct Debit Batch", batch_id):
        raise ValidationError(f"Batch {batch_id} does not exist")

    # Get batch document
    batch = frappe.get_doc("Direct Debit Batch", batch_id)

    # Get batch entries
    entries = frappe.get_all(
        "Direct Debit Batch Invoice",
        filters={"parent": batch_id},
        fields=[
            "name",
            "member",
            "member_name",
            "amount",
            "status",
            "result_message",
            "mandate_reference",
            "iban",
        ],
        order_by="idx",
    )

    # Calculate summary statistics
    summary = {
        "total_entries": len(entries),
        "total_amount": sum(flt(entry.amount) for entry in entries),
        "pending_entries": len([e for e in entries if e.status == "Pending"]),
        "processed_entries": len([e for e in entries if e.status == "Processed"]),
        "failed_entries": len([e for e in entries if e.status == "Failed"]),
        "pending_amount": sum(flt(e.amount) for e in entries if e.status == "Pending"),
        "processed_amount": sum(flt(e.amount) for e in entries if e.status == "Processed"),
        "failed_amount": sum(flt(e.amount) for e in entries if e.status == "Failed"),
    }

    return {"success": True, "batch": batch.as_dict(), "entries": entries, "summary": summary}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=500)
def get_batch_conflicts(batch_id):
    """
    Get conflicts and issues for a specific batch.

    Args:
        batch_id (str): ID of the batch

    Returns:
        dict: List of conflicts and resolution suggestions
    """
    # Validate input
    validate_required_fields({"batch_id": batch_id}, ["batch_id"])

    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to view batch conflicts")

    # Check if batch exists
    if not frappe.db.exists("Direct Debit Batch", batch_id):
        raise ValidationError(f"Batch {batch_id} does not exist")

    conflicts = []

    # Get entries with errors
    failed_entries = frappe.get_all(
        "Direct Debit Batch Invoice",
        filters={"parent": batch_id, "status": "Failed"},
        fields=["name", "member", "member_name", "amount", "result_message", "mandate_reference", "iban"],
    )

    for entry in failed_entries:
        conflict = {
            "entry_id": entry.name,
            "member": entry.member,
            "member_name": entry.member_name,
            "amount": entry.amount,
            "error": entry.result_message,
            "type": "processing_error",
            "resolution_options": [],
        }

        # Suggest resolution options based on error type
        if "mandate" in (entry.result_message or "").lower():
            conflict["resolution_options"].extend(
                [
                    {"action": "update_mandate", "label": "Update SEPA mandate"},
                    {"action": "exclude_entry", "label": "Exclude from batch"},
                ]
            )
        elif "iban" in (entry.result_message or "").lower():
            conflict["resolution_options"].extend(
                [
                    {"action": "update_iban", "label": "Update IBAN"},
                    {"action": "exclude_entry", "label": "Exclude from batch"},
                ]
            )
        else:
            conflict["resolution_options"].append(
                {"action": "manual_review", "label": "Manual review required"}
            )

        conflicts.append(conflict)

    # Duplicate INVOICE rows, not duplicate mandate references (#626).
    #
    # This grouped on `mandate_reference` and reported "Mandate X appears N times
    # in batch" as a conflict. That is the ORDINARY case: a member with two unpaid
    # invoices has two rows on one mandate, which is one debtor and two legitimate
    # collections. Offering "consolidate" for it is what made an operator merge two
    # distinct invoices into a single debit that reconciles only the first --
    # `batch_processing_service.mark_batch_invoices_as_paid` iterates the surviving
    # child rows, so the deleted row's invoice is never in the loop, gets no Payment
    # Entry, and stays Unpaid while its amount has been collected.
    #
    # The row set that really is a defect is two rows naming ONE invoice: each child
    # row becomes one transaction in the SEPA XML, so that is two debits for one
    # debt. `DirectDebitBatch.validate_no_duplicate_invoices` (#606) rejects such a
    # batch on save, so what reaches this endpoint is a batch that predates that
    # guard or whose rows were written standalone -- exactly the population that
    # needs a repair path, since it can no longer be saved at all.
    duplicate_invoices = frappe.db.sql(
        """
        SELECT invoice, COUNT(*) as count
        FROM `tabDirect Debit Batch Invoice`
        WHERE parent = %s AND invoice IS NOT NULL
        GROUP BY invoice
        HAVING count > 1
    """,
        (batch_id,),
        as_dict=True,
    )

    for dup in duplicate_invoices:
        conflicts.append(
            {
                "type": "duplicate_invoice",
                "invoice": dup.invoice,
                "count": dup.count,
                "error": f"Invoice {dup.invoice} appears {dup.count} times in batch, "
                f"which would debit the member {dup.count} times for one debt",
                # Only remedies apply_conflict_resolutions actually implements are
                # offered (#615). "exclude_duplicates" used to sit here with no
                # branch and no `else`, so selecting it was a silent no-op reported
                # inside a successful response; what it named ("delete every row but
                # one for the duplicated invoice") is what consolidate_entries does.
                "resolution_options": [
                    {"action": "consolidate_entries", "label": "Remove duplicate rows for this invoice"},
                ],
            }
        )

    return {"success": True, "batch_id": batch_id, "conflicts": conflicts, "total_conflicts": len(conflicts)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=2000)
def get_eligible_invoices(filters: dict | None = None):
    """
    Get invoices eligible for direct debit processing.

    Args:
        filters (dict): Filter criteria for invoice selection

    Returns:
        dict: List of eligible invoices
    """
    # Check permissions
    if not can_create_dd_batches():
        raise PermissionError("You do not have permission to create direct debit batches")

    # Set default filters
    if not filters:
        filters = {}

    # Build query conditions
    conditions = ["si.docstatus = 1", "si.outstanding_amount > 0"]
    values = []

    # Filter by due date
    due_date_limit = filters.get("due_date") or today()
    conditions.append("si.due_date <= %s")
    values.append(due_date_limit)

    # Filter by customer type (member)
    if filters.get("member_type"):
        conditions.append("mem.selected_membership_type = %s")
        values.append(filters["member_type"])

    # Filter by amount range
    if filters.get("amount_min"):
        conditions.append("si.outstanding_amount >= %s")
        values.append(flt(filters["amount_min"]))

    if filters.get("amount_max"):
        conditions.append("si.outstanding_amount <= %s")
        values.append(flt(filters["amount_max"]))

    # Query for eligible invoices
    query = f"""
        SELECT
            si.name,
            si.customer,
            si.customer_name,
            si.posting_date,
            si.due_date,
            si.outstanding_amount,
            si.grand_total,
            mem.name as member_id,
            mem.full_name as member_name,
            sm.mandate_id as mandate_reference,
            sm.iban,
            sm.status as mandate_status
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMember` mem ON mem.customer = si.customer
        -- Purpose filter (#597). Without it this join produced one row PER
        -- Active mandate, so a member with a membership mandate and a donation
        -- mandate yielded TWO rows for ONE invoice -- and `sm.mandate_id`/`sm.iban`
        -- become the Direct Debit Batch child row, i.e. two debits. There is no
        -- per-member dedup after this query.
        LEFT JOIN `tabSEPA Mandate` sm
            ON mem.name = sm.member
            AND sm.status = 'Active'
            AND sm.used_for_memberships = 1
        WHERE {' AND '.join(conditions)}
        AND sm.mandate_id IS NOT NULL
        ORDER BY si.due_date ASC, si.outstanding_amount DESC
        LIMIT 500
    """

    eligible_invoices = frappe.db.sql(query, values, as_dict=True)

    # Filter invoices that are not already in pending batches
    filtered_invoices = []
    for invoice in eligible_invoices:
        # Check if invoice is already in a pending batch
        existing_entry = frappe.db.exists(
            "Direct Debit Batch Invoice",
            {
                "invoice": invoice.name,
                "docstatus": ["!=", 2],  # Not cancelled
                "status": ["in", ["Pending", "Processing"]],
            },
        )

        if not existing_entry:
            # Add additional computed fields
            invoice["days_overdue"] = (getdate(today()) - getdate(invoice.due_date)).days
            invoice["eligibility_score"] = calculate_eligibility_score(invoice)
            filtered_invoices.append(invoice)

    return {
        "success": True,
        "invoices": filtered_invoices,
        "total_invoices": len(filtered_invoices),
        "filters_applied": filters,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=3000)
def apply_conflict_resolutions(batch_id, resolutions):
    """
    Apply conflict resolutions to a batch.

    Args:
        batch_id (str): ID of the batch
        resolutions (dict): Resolution actions to apply

    Returns:
        dict: Result of resolution application
    """
    # Validate input
    validate_required_fields({"batch_id": batch_id, "resolutions": resolutions}, ["batch_id", "resolutions"])

    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to resolve batch conflicts")

    # Get batch document
    batch = frappe.get_doc("Direct Debit Batch", batch_id)

    results = []

    # Process each resolution
    for resolution in resolutions:
        result = {"resolution": resolution, "success": False, "message": ""}
        try:
            result.update(_resolution_outcome(batch_id, resolution))
        except Exception as e:
            result["message"] = str(e)
        results.append(result)

    applied = any(result["success"] for result in results)

    # Only save the parent when something actually changed. A batch holding a
    # duplicate cannot be saved AT ALL until the duplicate is gone (#606), so
    # saving after a resolution that refused would replace every per-resolution
    # message with that ValidationError -- the operator would never learn WHY
    # the remedy declined, which is the one thing they need in order to act.
    # There is also nothing to recalculate when no row moved.
    if applied:
        # Reload to pick up the child-row edits/deletions made above via
        # independent get_doc().save()/delete_doc() calls. Without this, save()
        # below would re-sync the child table from the stale in-memory snapshot
        # loaded before the resolutions ran, silently reverting them.
        batch.reload()

        # Recalculate batch totals
        batch.calculate_totals()
        batch.save()

    # `success` reports whether anything was applied, not merely that the request
    # was processed (#615). It used to be a hard-coded True, so a resolution that
    # matched no branch -- leaving success False and an EMPTY message inside
    # resolution_results -- came back inside a successful response, and the client
    # (public/js/dd_batch_management_enhanced.js:1047 tests `success !== false`)
    # reported "Conflict resolutions applied successfully" for a no-op.
    return {
        "success": applied,
        "batch_id": batch_id,
        "resolution_results": results,
        "batch_updated": applied,
    }


def _resolution_outcome(batch_id, resolution):
    """Dispatch one resolution action; return {"success": bool, "message": str}."""
    action = resolution.get("action")

    if action in ("update_mandate", "update_iban"):
        # One branch for both names: `get_batch_conflicts` offers update_iban for
        # an IBAN-flavoured failure and update_mandate for a mandate-flavoured
        # one, but the remedy is the same write and only update_mandate had a
        # branch -- so an operator correcting a wrong IBAN was told "success" by
        # the wrapper while the batch still debited the old account (#615, the
        # sibling of the exclude_duplicates gap that issue names).
        entry = _batch_child_row(batch_id, resolution["entry_id"])
        if resolution.get("new_mandate_reference"):
            entry.mandate_reference = resolution["new_mandate_reference"]
        if resolution.get("new_iban"):
            entry.iban = resolution["new_iban"]
        entry.status = "Pending"
        entry.result_message = ""
        entry.save()
        return {"success": True, "message": _("Mandate details updated successfully")}

    if action == "exclude_entry":
        # Remove the entry from the batch entirely. SEPA generation iterates
        # every child row regardless of status, so merely flagging an entry
        # would NOT stop it being debited; the row must be deleted (mirrors
        # the consolidate path below).
        #
        # Resolved through _batch_child_row first: frappe.delete_doc defaults to
        # ignore_missing=True, so deleting an entry_id that does not exist
        # returned silently and this reported "Entry excluded from batch" for a
        # row that was never in the batch -- the same false report as an
        # unimplemented action (#615), reached through an implemented one.
        entry = _batch_child_row(batch_id, resolution["entry_id"])
        frappe.delete_doc("Direct Debit Batch Invoice", entry.name)
        return {"success": True, "message": _("Entry excluded from batch")}

    if action == "consolidate_entries":
        return _remove_duplicate_invoice_rows(batch_id, resolution)

    if action == "manual_review":
        # Offered by get_batch_conflicts for an error it cannot classify. There
        # is deliberately nothing to apply, but it must SAY so: silence here is
        # what #615 is about.
        return {
            "success": False,
            "message": _("This conflict has no automated remedy and must be resolved by hand"),
        }

    # No silent fall-through. Every action this endpoint does not implement now
    # reports itself; previously an unhandled action left success=False with an
    # empty message inside an overall {"success": True} response, so an operator
    # choosing an advertised remedy got a no-op that read as applied (#615).
    return {"success": False, "message": _("Unknown resolution action: {0}").format(action)}


def _batch_child_row(batch_id, entry_id):
    """Load a Direct Debit Batch Invoice row, refusing one from another batch.

    Every resolution names an `entry_id` and the endpoint names a `batch_id`, and
    nothing tied the two together: an entry_id belonging to a different batch was
    edited or deleted there while this batch's totals were recalculated. Both
    branches that take an entry_id go through here.
    """
    row = frappe.get_doc("Direct Debit Batch Invoice", entry_id)
    if row.parent != batch_id:
        raise ValidationError(f"Entry {entry_id} does not belong to batch {batch_id}")
    return row


def _remove_duplicate_invoice_rows(batch_id, resolution):
    """Collapse rows that name the SAME invoice; never merge different invoices.

    Consolidation used to group by `mandate_reference` alone and sum the group
    into its first row, which is wrong in both directions:

    * two rows for ONE invoice became one row at 2x the amount, so the member was
      still debited twice for one debt -- once, at double value -- and the batch
      then passed `validate_no_duplicate_invoices` because there was genuinely one
      row per invoice afterwards. The remedy offered for a duplicate produced the
      defect the guard exists to catch, in a shape the guard cannot see (#613);
    * two rows for DIFFERENT invoices on one mandate -- a member with two unpaid
      invoices, the ordinary case -- were merged into a single row naming only the
      first invoice. The SEPA XML then debits the sum while
      `batch_processing_service.mark_batch_invoices_as_paid` iterates the surviving
      rows, so the second invoice gets no Payment Entry, no
      `_mark_mandate_usage_collected`, and stays Unpaid with its amount already
      collected (#626).

    So the key is the invoice. Rows naming different invoices are different debts
    and are left as separate debits. `mandate_reference` is still accepted as a
    scope so an existing caller's payload keeps working: it narrows WHICH rows are
    considered, it no longer decides what gets merged.

    Amounts are not summed. Two rows for one invoice each already carry that
    invoice's amount, so the correct total after de-duplication is one of them,
    not their sum. Where the duplicates disagree about the amount the rows are
    left alone and the disagreement is reported -- picking one would debit a
    number nobody chose, and this repo's own precedent for an ambiguous financial
    pick (#567/#578/#584) is to refuse it rather than order it.
    """
    filters = {"parent": batch_id}
    if resolution.get("invoice"):
        filters["invoice"] = resolution["invoice"]
    if resolution.get("mandate_reference"):
        filters["mandate_reference"] = resolution["mandate_reference"]

    if len(filters) == 1:
        return {
            "success": False,
            "message": _("consolidate_entries needs an invoice or a mandate_reference to scope it"),
        }

    rows = frappe.get_all(
        "Direct Debit Batch Invoice",
        filters=filters,
        fields=["name", "invoice", "amount"],
        # Explicit "asc": Frappe appends the direction to a bare field name, so
        # order_by="idx" would sort DESC and keep the LAST row instead of the first.
        order_by="idx asc",
    )

    rows_by_invoice = {}
    for row in rows:
        rows_by_invoice.setdefault(row.invoice, []).append(row)

    duplicates = {invoice: group for invoice, group in rows_by_invoice.items() if len(group) > 1}
    if not duplicates:
        return {
            "success": False,
            "message": _(
                "Nothing to consolidate: {0} row(s) name {1} distinct invoice(s), each once. "
                "Rows for different invoices are separate debts and are never merged -- "
                "merging them would collect one invoice's amount while leaving that invoice "
                "unpaid."
            ).format(len(rows), len(rows_by_invoice)),
        }

    disagreeing = {
        invoice: group for invoice, group in duplicates.items() if len({flt(r.amount) for r in group}) > 1
    }
    if disagreeing:
        listed = "; ".join(
            "{0} ({1})".format(invoice, ", ".join(str(flt(r.amount)) for r in group))
            for invoice, group in sorted(disagreeing.items())
        )
        return {
            "success": False,
            "message": _(
                "Duplicate rows disagree about the amount owed, so none were removed: {0}. "
                "Correct the amounts by hand -- keeping one arbitrarily would debit a value "
                "nobody chose."
            ).format(listed),
        }

    removed = 0
    for group in duplicates.values():
        for row in group[1:]:
            frappe.delete_doc("Direct Debit Batch Invoice", row.name)
            removed += 1

    return {
        "success": True,
        "message": _("Removed {0} duplicate row(s) covering {1} invoice(s)").format(removed, len(duplicates)),
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def escalate_conflicts(batch_id, conflicts):
    """
    Escalate unresolved conflicts to administrators.

    Args:
        batch_id (str): ID of the batch
        conflicts (list): List of conflicts to escalate

    Returns:
        dict: Result of escalation
    """
    # Validate input
    validate_required_fields({"batch_id": batch_id, "conflicts": conflicts}, ["batch_id", "conflicts"])

    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to escalate batch conflicts")

    # Get batch document
    batch = frappe.get_doc("Direct Debit Batch", batch_id)

    # Create escalation notification
    escalation_message = f"""
    Direct Debit Batch Conflicts Escalation

    Batch: {batch_id}
    Batch Date: {batch.batch_date}
    Total Conflicts: {len(conflicts)}

    Conflicts requiring attention:
    """

    for i, conflict in enumerate(conflicts, 1):
        escalation_message += f"""
    {i}. Member: {conflict.get('member_name', 'Unknown')}
       Error: {conflict.get('error', 'No error message')}
       Type: {conflict.get('type', 'Unknown')}
    """

    # Send notification to administrators
    admin_users = frappe.get_all(
        "Has Role",
        filters={"role": ["in", list(Roles.ADMIN_PAIR)]},
        fields=["parent as user"],
    )

    recipients = [user.user for user in admin_users]

    if recipients:
        email_service = get_email_service()
        email_service.send_simple_email(
            recipients=recipients,
            subject=f"Direct Debit Batch Conflicts - {batch_id}",
            message=escalation_message,
            delayed=False,
            notification_key="sepa_batch_error",
        )

    # Update batch status
    batch.add_comment("Comment", f"Conflicts escalated by {frappe.session.user}")

    return {
        "success": True,
        "batch_id": batch_id,
        "escalated_conflicts": len(conflicts),
        "notifications_sent": len(recipients),
    }


def can_manage_dd_batches():
    """Check if current user can manage direct debit batches"""
    user_roles = frappe.get_roles(frappe.session.user)
    required_roles = list(Roles.ADMIN_PAIR) + [
        "Accounts Manager",
        "SEPA Administrator",
    ]

    return any(role in user_roles for role in required_roles)


def can_create_dd_batches():
    """Check if current user can create direct debit batches"""
    user_roles = frappe.get_roles(frappe.session.user)
    required_roles = list(Roles.ADMIN_PAIR) + [
        "Accounts Manager",
        "SEPA Administrator",
        "Accounts User",
    ]

    return any(role in user_roles for role in required_roles)


def calculate_eligibility_score(invoice):
    """Calculate eligibility score for an invoice"""
    score = 0

    # Score based on days overdue
    days_overdue = (getdate(today()) - getdate(invoice.due_date)).days
    if days_overdue > 30:
        score += 50
    elif days_overdue > 7:
        score += 30
    elif days_overdue >= 0:
        score += 20

    # Score based on amount
    amount = flt(invoice.outstanding_amount)
    if amount > 100:
        score += 30
    elif amount > 50:
        score += 20
    elif amount > 0:
        score += 10

    # Score based on mandate status
    if invoice.mandate_status == "Active":
        score += 40

    return score
