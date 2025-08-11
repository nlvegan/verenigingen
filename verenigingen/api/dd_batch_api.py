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

# Import security and error handling
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
@high_security_api(operation_type=OperationType.SEPA_BATCH)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def get_batch_list_with_security(filters=None):
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
@high_security_api(operation_type=OperationType.SEPA_BATCH)
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
@high_security_api(operation_type=OperationType.SEPA_BATCH)
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
        elif "iban" in (entry.error_message or "").lower():
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

    # Check for duplicate mandates in batch
    duplicate_mandates = frappe.db.sql(
        """
        SELECT mandate_reference, COUNT(*) as count
        FROM `tabDirect Debit Batch Invoice`
        WHERE parent = %s AND mandate_reference IS NOT NULL
        GROUP BY mandate_reference
        HAVING count > 1
    """,
        (batch_id,),
        as_dict=True,
    )

    for dup in duplicate_mandates:
        conflicts.append(
            {
                "type": "duplicate_mandate",
                "mandate_reference": dup.mandate_reference,
                "count": dup.count,
                "error": f"Mandate {dup.mandate_reference} appears {dup.count} times in batch",
                "resolution_options": [
                    {"action": "consolidate_entries", "label": "Consolidate duplicate entries"},
                    {"action": "exclude_duplicates", "label": "Exclude duplicate entries"},
                ],
            }
        )

    return {"success": True, "batch_id": batch_id, "conflicts": conflicts, "total_conflicts": len(conflicts)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.SEPA_BATCH)
@handle_api_error
@performance_monitor(threshold_ms=2000)
def get_eligible_invoices(filters=None):
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
            sm.mandate_reference,
            sm.iban,
            sm.status as mandate_status
        FROM `tabSales Invoice` si
        LEFT JOIN `tabMember` mem ON si.customer = mem.name
        LEFT JOIN `tabSEPA Mandate` sm ON mem.name = sm.member AND sm.status = 'Active'
        WHERE {' AND '.join(conditions)}
        AND sm.mandate_reference IS NOT NULL
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
@critical_api(operation_type=OperationType.SEPA_BATCH)
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
            if resolution["action"] == "update_mandate":
                # Update mandate information
                entry = frappe.get_doc("Direct Debit Batch Invoice", resolution["entry_id"])
                if resolution.get("new_mandate_reference"):
                    entry.mandate_reference = resolution["new_mandate_reference"]
                if resolution.get("new_iban"):
                    entry.iban = resolution["new_iban"]
                entry.status = "Pending"
                entry.error_message = ""
                entry.save()
                result["success"] = True
                result["message"] = "Mandate updated successfully"

            elif resolution["action"] == "exclude_entry":
                # Remove entry from batch
                entry = frappe.get_doc("Direct Debit Batch Invoice", resolution["entry_id"])
                entry.status = "Excluded"
                entry.save()
                result["success"] = True
                result["message"] = "Entry excluded from batch"

            elif resolution["action"] == "consolidate_entries":
                # Consolidate duplicate entries
                mandate_ref = resolution["mandate_reference"]
                entries = frappe.get_all(
                    "Direct Debit Batch Invoice",
                    filters={"parent": batch_id, "mandate_reference": mandate_ref},
                    fields=["name", "amount"],
                )

                if len(entries) > 1:
                    # Keep first entry, sum amounts, remove others
                    total_amount = sum(flt(e.amount) for e in entries)
                    first_entry = frappe.get_doc("Direct Debit Batch Invoice", entries[0].name)
                    first_entry.amount = total_amount
                    first_entry.save()

                    # Remove other entries
                    for i in range(1, len(entries)):
                        frappe.delete_doc("Direct Debit Batch Invoice", entries[i].name)

                    result["success"] = True
                    result["message"] = f"Consolidated {len(entries)} entries into one"

        except Exception as e:
            result["message"] = str(e)

        results.append(result)

    # Recalculate batch totals
    batch.calculate_totals()
    batch.save()

    return {"success": True, "batch_id": batch_id, "resolution_results": results, "batch_updated": True}


@frappe.whitelist()
@critical_api(operation_type=OperationType.SEPA_BATCH)
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
        filters={"role": ["in", ["System Manager", "Verenigingen Administrator"]]},
        fields=["parent as user"],
    )

    recipients = [user.user for user in admin_users]

    if recipients:
        frappe.sendmail(
            recipients=recipients,
            subject=f"Direct Debit Batch Conflicts - {batch_id}",
            message=escalation_message,
            delayed=False,
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
    required_roles = [
        "System Manager",
        "Verenigingen Administrator",
        "Accounts Manager",
        "SEPA Administrator",
    ]

    return any(role in user_roles for role in required_roles)


def can_create_dd_batches():
    """Check if current user can create direct debit batches"""
    user_roles = frappe.get_roles(frappe.session.user)
    required_roles = [
        "System Manager",
        "Verenigingen Administrator",
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
