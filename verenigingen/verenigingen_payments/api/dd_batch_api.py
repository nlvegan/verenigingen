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
from verenigingen.utils.transaction_errors import (
    NON_RESUMABLE_DB_ERRORS,
    release_savepoint_if_present,
    rollback_to_savepoint,
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
        resolutions (list[dict]): Resolution actions to apply. Each dict carries an
            `action` (one of update_mandate, update_iban, exclude_entry,
            consolidate_entries, manual_review) plus that action's parameters --
            `entry_id`, or `invoice` / `mandate_reference` for consolidate_entries.

    Returns:
        dict: {"success": True, "resolution_results": [...], "applied": bool,
               "batch_updated": bool}. `success` reports that the request was
               processed; a remedy that correctly declines is reported per
               resolution, not as a request failure.
    """
    # Validate input
    validate_required_fields({"batch_id": batch_id, "resolutions": resolutions}, ["batch_id", "resolutions"])

    # A whitelisted endpoint reached with a form-encoded body hands this over as a
    # JSON string; iterating it would yield one character per "resolution".
    if isinstance(resolutions, str):
        resolutions = frappe.parse_json(resolutions)

    # Check permissions
    if not can_manage_dd_batches():
        raise PermissionError("You do not have permission to resolve batch conflicts")

    # Get batch document
    batch = frappe.get_doc("Direct Debit Batch", batch_id)

    # One savepoint around the WHOLE call (#614). The child rows are edited and
    # deleted one at a time through independent get_doc().save()/delete_doc()
    # calls, and only afterwards is the parent saved -- and that parent save can
    # throw, because `DirectDebitBatch.validate` throws (validate_invoices always
    # could; validate_no_duplicate_invoices from #606 throws for every save while
    # any duplicate remains). `@handle_api_error` turns that ValidationError into
    # an OperationResult.fail and the request then ends on its SUCCESS path, so
    # Frappe commits the deletions that already happened: the caller is told the
    # operation failed while the rows are gone and entry_count/total_amount still
    # describe the batch as it was. An excluded row committed under a "failed"
    # result is an invoice that is silently never collected.
    #
    # A savepoint rather than frappe.db.begin(): begin() opens a NEW transaction
    # boundary rather than a nested one, and it raises ImplicitCommitError whenever
    # the surrounding transaction has already written (`check_implicit_commit` tests
    # `transaction_writes`). A savepoint nests inside whatever transaction the
    # request or the test runner already has open.
    savepoint = f"dd_conflict_resolutions_{frappe.generate_hash(length=8)}"
    frappe.db.savepoint(savepoint)
    try:
        results = [_apply_one_resolution(batch_id, resolution) for resolution in resolutions]
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
    except NON_RESUMABLE_DB_ERRORS:
        # A 1213 has already rolled the whole transaction back, savepoints
        # included, so rolling back to this one would raise 1305 on top of the
        # real error and hide it. There is nothing left to undo.
        raise
    except Exception:
        rollback_to_savepoint(savepoint)
        raise
    else:
        release_savepoint_if_present(savepoint)

    # `success` stays the request-level flag: the request was processed. What #615
    # is about -- an operator being told a remedy was applied when it was not -- is
    # answered by every resolution now carrying a non-empty message, and by
    # `applied`, which says whether ANY of them changed anything. `batch_updated`
    # was previously hard-coded True even when nothing was touched.
    #
    # `success` deliberately does NOT become `applied`. Two of the advertised
    # remedies correctly decline (`manual_review` has nothing to apply; consolidate
    # refuses an ambiguous duplicate), and a client following the usual
    # `success !== false` convention would render those as "Failed to apply
    # conflict resolutions" and hide the very message the operator needs.
    return {
        "success": True,
        "batch_id": batch_id,
        "resolution_results": results,
        "applied": applied,
        "batch_updated": applied,
    }


def _apply_one_resolution(batch_id, resolution):
    """Apply a single conflict resolution, atomically.

    Its own savepoint (nested inside the caller's) so a resolution that fails
    part-way -- one of several duplicate rows deleted and the next delete refused,
    say -- leaves nothing behind while the other resolutions in the same request
    still apply. Reporting a failure whose partial effects persist is the defect
    this whole function was changed for (#614); it exists at two levels and is
    fixed at both.
    """
    result = {"resolution": resolution, "success": False, "message": ""}

    savepoint = f"dd_conflict_entry_{frappe.generate_hash(length=8)}"
    frappe.db.savepoint(savepoint)
    try:
        result.update(_resolution_outcome(batch_id, resolution))
    except NON_RESUMABLE_DB_ERRORS:
        raise
    except (frappe.ValidationError, ValidationError) as e:
        # A deliberate refusal (a missing entry_id, a row belonging to another
        # batch, a guard on the child row). The message IS the answer, so it goes
        # to the operator without an Error Log row.
        rollback_to_savepoint(savepoint)
        result["success"] = False
        result["message"] = str(e)
    except Exception as e:
        # Anything else is a defect, not a refusal, and this handler is the only
        # thing between it and a returned string: without the log there is no
        # traceback anywhere, and the falsy `success` it produces is load-bearing
        # (it gates the parent save).
        rollback_to_savepoint(savepoint)
        log_error(
            e,
            context={"function": "apply_conflict_resolutions", "batch_id": batch_id},
            module=__name__,
        )
        result["success"] = False
        result["message"] = str(e)
    else:
        release_savepoint_if_present(savepoint)

    return result


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
        raise ValidationError(_("Entry {0} does not belong to batch {1}").format(entry_id, batch_id))
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
    and are left as separate debits.

    `mandate_reference` is accepted as a scope so an existing caller's payload keeps
    working, but only to choose WHICH INVOICES to repair -- the rows of those
    invoices are then loaded without it. Filtering the rows themselves on the
    mandate would hide the canonical duplicate: the pair that duplicates one invoice
    routinely carries DIFFERENT mandate references, because that is how it got there
    (#597/#604 -- a member holding a membership mandate and a donation mandate
    produced two rows for one invoice, each with its own `sm.mandate_id`/`sm.iban`).
    A mandate-filtered query returns one row of that pair, and this function would
    then report "one row per invoice, each once" about a batch that holds two and
    cannot be saved at all.

    Nothing is merged and no field is picked. Two rows for one invoice each already
    carry that invoice's whole amount, so the correct total after de-duplication is
    one of them, not their sum -- all 9 row-producing sites were read and none
    splits an invoice across rows. But the surviving row also carries the IBAN and
    the mandate reference the money moves on, and those are exactly what the
    duplicate pair disagrees about. So the refusal covers every field that decides
    the debit -- amount, iban, mandate_reference -- rather than the amount alone:
    keeping `group[0]` when the pair names two different mandates would collect a
    membership debt on whichever mandate happened to sort first, which is the
    mandate-purpose violation #604/#605/#606 exist to prevent. This repo's precedent
    for an ambiguous financial pick (#567/#578/#584) is to refuse it, not to order
    it, and `exclude_entry` is the operator's way to remove the right row by hand.

    `sequence_type` and `status` are deliberately NOT in that set: neither decides
    where money goes or how much (SEPA generation iterates every row regardless of
    status), so a difference there must not block a repair.
    """
    invoice = resolution.get("invoice")
    mandate_reference = resolution.get("mandate_reference")
    if not invoice and not mandate_reference:
        return {
            "success": False,
            "message": _("consolidate_entries needs an invoice or a mandate_reference to scope it"),
        }

    scope = {"parent": batch_id}
    if invoice:
        scope["invoice"] = invoice
    if mandate_reference:
        scope["mandate_reference"] = mandate_reference

    scoped_invoices = sorted(
        {
            row.invoice
            for row in frappe.get_all("Direct Debit Batch Invoice", filters=scope, fields=["invoice"])
            if row.invoice
        }
    )
    if not scoped_invoices:
        return {"success": False, "message": _("No rows in this batch match that invoice or mandate")}

    rows = frappe.get_all(
        "Direct Debit Batch Invoice",
        filters={"parent": batch_id, "invoice": ["in", scoped_invoices]},
        fields=["name", "invoice", "amount", "iban", "mandate_reference"],
        order_by="idx asc",
    )

    rows_by_invoice = {}
    for row in rows:
        rows_by_invoice.setdefault(row.invoice, []).append(row)

    duplicates = {inv: group for inv, group in rows_by_invoice.items() if len(group) > 1}
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

    disagreements = []
    for inv, group in sorted(duplicates.items()):
        for field in DEBIT_DECIDING_FIELDS:
            values = {_debit_field_value(row, field) for row in group}
            if len(values) > 1:
                disagreements.append("{0} {1}: {2}".format(inv, field, ", ".join(sorted(values))))
    if disagreements:
        return {
            "success": False,
            "message": _(
                "Duplicate rows disagree about what to debit, so none were removed: {0}. "
                "Resolve it by hand (exclude_entry removes one row) -- keeping either "
                "arbitrarily would debit a value or an account nobody chose."
            ).format("; ".join(disagreements)),
        }

    removed = 0
    for group in duplicates.values():
        # Every field that decides the debit is identical across the group by now,
        # so which row survives is immaterial to the money.
        for row in group[1:]:
            frappe.delete_doc("Direct Debit Batch Invoice", row.name)
            removed += 1

    return {
        "success": True,
        "message": _("Removed {0} duplicate row(s) covering {1} invoice(s)").format(removed, len(duplicates)),
    }


# The three child-row fields that decide where the money goes and how much. A
# duplicate pair that disagrees on any of them is refused rather than resolved.
DEBIT_DECIDING_FIELDS = ("amount", "iban", "mandate_reference")


def _debit_field_value(row, field):
    """One duplicate row's value for a debit-deciding field, as a comparable string."""
    if field == "amount":
        return str(flt(row.amount))
    return (row.get(field) or "").strip()


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
