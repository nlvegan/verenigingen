"""
Payment Processing Recovery Utilities

Provides idempotency checks, failure detection, and recovery tools for Mollie payment processing.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def get_payment_processing_status(payment_id: str) -> Dict[str, any]:
    """
    Check the processing status of a Mollie payment.

    Returns:
        dict: {
            "payment_id": str,
            "has_bank_transaction": bool,
            "bank_transaction": str or None,
            "has_payment_entry": bool,
            "payment_entry": str or None,
            "has_sales_invoice": bool,
            "sales_invoice": str or None,
            "member": str or None,
            "status": "complete" | "partial" | "unprocessed",
            "missing_documents": list
        }
    """
    status = {
        "payment_id": payment_id,
        "has_bank_transaction": False,
        "bank_transaction": None,
        "has_payment_entry": False,
        "payment_entry": None,
        "has_sales_invoice": False,
        "sales_invoice": None,
        "member": None,
        "status": "unprocessed",
        "missing_documents": [],
    }

    # Check for Bank Transaction
    bt = frappe.db.get_value(
        "Bank Transaction", {"reference_number": payment_id}, ["name", "party"], as_dict=True
    )

    if bt:
        status["has_bank_transaction"] = True
        status["bank_transaction"] = bt.name

        # Try to get member from party
        if bt.party:
            member = frappe.db.get_value("Member", {"customer": bt.party}, "name")
            if member:
                status["member"] = member

    # Check for Payment Entry (can be linked via BT or standalone)
    pe = None
    if bt:
        # Check if PE is linked to BT
        pe_link = frappe.db.get_value(
            "Bank Transaction Payments",
            {"parent": bt.name, "payment_document": "Payment Entry"},
            "payment_entry",
        )
        if pe_link:
            pe = pe_link

    # Also check for PE with matching reference (must be submitted, not cancelled)
    if not pe:
        pe = frappe.db.get_value("Payment Entry", {"reference_no": payment_id, "docstatus": 1}, "name")

    if pe:
        status["has_payment_entry"] = True
        status["payment_entry"] = pe

        # Get member from PE if we don't have it yet
        if not status["member"]:
            pe_party = frappe.db.get_value("Payment Entry", pe, "party")
            if pe_party:
                member = frappe.db.get_value("Member", {"customer": pe_party}, "name")
                if member:
                    status["member"] = member

    # Check for Sales Invoice (linked via PE or standalone)
    sinv = None
    if pe:
        # Check PE references
        sinv_ref = frappe.db.get_value(
            "Payment Entry Reference", {"parent": pe, "reference_doctype": "Sales Invoice"}, "reference_name"
        )
        if sinv_ref:
            sinv = sinv_ref

    # If no linked SINV but we have a member and BT with date, check by coverage period
    # This handles invoices created independently (e.g., by Membership Dues Schedules)
    if not sinv and status["member"] and bt:
        from verenigingen.services.billing.coverage_calculator import calculate_coverage_for_payment_date

        # Get payment date from Bank Transaction
        bt_date = frappe.db.get_value("Bank Transaction", bt.name, "date")
        if bt_date:
            # Calculate coverage based on member's billing frequency
            coverage_start, coverage_end = calculate_coverage_for_payment_date(status["member"], bt_date)

            # Look for invoice matching coverage period with outstanding balance
            member = frappe.get_doc("Member", status["member"])
            if member.customer:
                existing_invoice = frappe.db.get_value(
                    "Sales Invoice",
                    filters={
                        "customer": member.customer,
                        "custom_coverage_start_date": coverage_start,
                        "custom_coverage_end_date": coverage_end,
                        "docstatus": 1,  # Only submitted invoices
                        "outstanding_amount": [">", 0],  # Only unpaid invoices
                    },
                    fieldname="name",
                )
                if existing_invoice:
                    sinv = existing_invoice
                    status["sinv_unlinked"] = True  # Flag for linking later

    if sinv:
        status["has_sales_invoice"] = True
        status["sales_invoice"] = sinv

    # Check if BT is linked to PE (critical for proper reconciliation)
    bt_pe_linked = False
    if status["has_bank_transaction"] and status["has_payment_entry"]:
        bt_pe_link = frappe.db.exists(
            "Bank Transaction Payments",
            {"parent": status["bank_transaction"], "payment_entry": status["payment_entry"]},
        )
        bt_pe_linked = bool(bt_pe_link)
        status["bt_pe_linked"] = bt_pe_linked

    # Determine overall status
    if status["has_bank_transaction"] and status["has_payment_entry"] and status["has_sales_invoice"]:
        # Check if SINV is actually linked to PE or just exists unlinked
        if status.get("sinv_unlinked"):
            status["status"] = "partial"
            status["missing_documents"].append("Sales Invoice Link")  # SINV exists but not linked
        # Check if BT is linked to PE (required for proper reconciliation)
        elif not bt_pe_linked:
            status["status"] = "partial"
            status["missing_documents"].append("Bank Transaction → Payment Entry Link")
        else:
            status["status"] = "complete"
    elif status["has_bank_transaction"] or status["has_payment_entry"] or status["has_sales_invoice"]:
        status["status"] = "partial"
        if not status["has_bank_transaction"]:
            status["missing_documents"].append("Bank Transaction")
        if not status["has_payment_entry"]:
            status["missing_documents"].append("Payment Entry")
        if not status["has_sales_invoice"]:
            status["missing_documents"].append("Sales Invoice")
    else:
        status["status"] = "unprocessed"
        status["missing_documents"] = ["Bank Transaction", "Payment Entry", "Sales Invoice"]

    return status


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_incomplete_payments(payment_ids: Union[List[str], str, None] = None) -> Dict[str, any]:
    """
    Find payments that are partially processed (missing one or more documents).

    Uses the orchestrator's status check for consistency with process_payment().

    Args:
        payment_ids: Optional list of payment IDs to check. If None, checks all recent payments.

    Returns:
        dict: {
            "total_checked": int,
            "complete": int,
            "partial": int,
            "unprocessed": int,
            "incomplete_payments": list[dict]
        }
    """
    if isinstance(payment_ids, str):
        import json

        payment_ids = json.loads(payment_ids)

    result = {
        "total_checked": 0,
        "complete": 0,
        "partial": 0,
        "unprocessed": 0,
        "incomplete_payments": [],
        "timestamp": frappe.utils.now(),
    }

    if not payment_ids:
        # Get all payment IDs from Bank Transactions (oldest first)
        payment_ids = frappe.db.sql_list(
            """
            SELECT DISTINCT reference_number
            FROM `tabBank Transaction`
            WHERE reference_number LIKE 'tr_%%'
            ORDER BY creation ASC
            LIMIT 5000
        """
        )

    # Use orchestrator's status check for consistency with process_payment()
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        get_payment_orchestrator,
    )

    orchestrator = get_payment_orchestrator()

    for payment_id in payment_ids:
        # Use orchestrator's status check - same logic as process_payment() uses
        status = orchestrator.get_processing_status(payment_id)
        result["total_checked"] += 1

        if status.status == "complete":
            result["complete"] += 1
        elif status.status == "partial":
            result["partial"] += 1
            result["incomplete_payments"].append(status.to_dict())
        else:
            result["unprocessed"] += 1
            result["incomplete_payments"].append(status.to_dict())

    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def complete_partial_payments(
    payment_ids: Union[List[str], str, None] = None,
    dry_run: bool = True,
    max_payments: int = None,
    process_orphans: bool = False,
) -> Dict[str, any]:
    """
    Complete partially processed payments by creating missing documents.

    Args:
        payment_ids: List of payment IDs to complete. If None, finds all incomplete payments automatically.
        dry_run: If True, only report what would be done without making changes
        max_payments: Maximum number of payments to process. If None, processes all found payments (up to query limit).
        process_orphans: If True, creates invoices for orphaned payments (no member match) using
                        a fallback "Orphaned Payments" customer. These invoices are clearly marked
                        as requiring manual review. Default: False (orphans are skipped).

    Returns:
        dict: Processing results
    """
    # Check permissions before processing (only when not dry_run)
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() == "true"

    if not dry_run:
        missing_permissions = []

        # Check Bank Transaction permissions (create and write for reconciliation)
        if not frappe.has_permission("Bank Transaction", "create"):
            missing_permissions.append("Bank Transaction: create")
        if not frappe.has_permission("Bank Transaction", "write"):
            missing_permissions.append("Bank Transaction: write (for reconciliation)")

        # Check Sales Invoice permissions (create and submit)
        if not frappe.has_permission("Sales Invoice", "create"):
            missing_permissions.append("Sales Invoice: create")
        if not frappe.has_permission("Sales Invoice", "submit"):
            missing_permissions.append("Sales Invoice: submit")

        # Check Payment Entry permissions (create and submit)
        if not frappe.has_permission("Payment Entry", "create"):
            missing_permissions.append("Payment Entry: create")
        if not frappe.has_permission("Payment Entry", "submit"):
            missing_permissions.append("Payment Entry: submit")

        # If any permissions are missing, stop execution
        if missing_permissions:
            error_message = (
                f"Insufficient permissions to execute complete_partial_payments. "
                f"User {frappe.session.user} is missing the following permissions:\n"
                + "\n".join(f"  - {perm}" for perm in missing_permissions)
            )
            frappe.throw(error_message, title="Permission Denied")

    if isinstance(payment_ids, str):
        import json

        payment_ids = json.loads(payment_ids)

    if isinstance(max_payments, str):
        max_payments = int(max_payments)

    if isinstance(process_orphans, str):
        process_orphans = process_orphans.lower() == "true"

    result = {
        "total_requested": 0,
        "completed": 0,
        "skipped": 0,
        "errors": 0,
        "orphans_processed": 0,
        "results": [],
        "dry_run": dry_run,
        "max_payments": max_payments,
        "process_orphans": process_orphans,
        "timestamp": frappe.utils.now(),
    }

    # If no payment_ids provided, find incomplete payments automatically
    if not payment_ids:
        frappe.logger().info("No payment_ids provided, finding incomplete payments automatically...")
        incomplete_result = get_incomplete_payments()

        if incomplete_result["incomplete_payments"]:
            payment_ids = [p["payment_id"] for p in incomplete_result["incomplete_payments"]]
            frappe.logger().info(f"Found {len(payment_ids)} incomplete payments to process")
        else:
            result["message"] = "No incomplete payments found"
            return result

    # Apply max_payments limit if specified
    if max_payments and len(payment_ids) > max_payments:
        original_count = len(payment_ids)
        payment_ids = payment_ids[:max_payments]
        frappe.logger().info(f"Limiting processing to {max_payments} payments (found {original_count} total)")
        result["limited"] = True
        result["total_found"] = original_count

    result["total_requested"] = len(payment_ids)

    # Mollie payment ID format: tr_ followed by alphanumeric characters
    import re

    mollie_payment_pattern = re.compile(r"^tr_[a-zA-Z0-9]+$")

    # Use the orchestrator for processing (recovery mode with create_missing_invoice=True)
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        get_payment_orchestrator,
    )

    orchestrator = get_payment_orchestrator()

    for payment_id in payment_ids:
        # Validate payment ID format before processing
        if not mollie_payment_pattern.match(payment_id):
            result["results"].append(
                {
                    "payment_id": payment_id,
                    "status": "skipped",
                    "reason": "Invalid payment ID format (not a Mollie payment ID)",
                }
            )
            result["skipped"] += 1
            frappe.logger().warning(f"Skipping invalid payment ID: {payment_id[:50]}...")
            continue

        if dry_run:
            # Use orchestrator's status check for dry run
            status = orchestrator.get_processing_status(payment_id)
            result["results"].append(
                {
                    "payment_id": payment_id,
                    "status": "dry_run",
                    "current_status": status.status,
                    "would_create": status.missing_documents,
                    "member": status.member,
                }
            )
            continue

        # Process using orchestrator with create_missing_invoice=True (recovery mode)
        processing_result = orchestrator.process_payment(
            payment_id=payment_id,
            create_missing_invoice=True,  # Recovery mode: create invoice if not found
        )

        # If member not found and process_orphans is enabled, try orphan processing
        if (
            processing_result.status == "error"
            and processing_result.error == "Cannot determine member for payment"
            and process_orphans
        ):
            # Try to process as orphaned payment with fallback customer
            processing_result = orchestrator.process_orphaned_payment_with_invoice(
                payment_id=payment_id,
            )
            if processing_result.status == "success":
                result["orphans_processed"] += 1

        # Convert orchestrator result to legacy format
        payment_result = {
            "payment_id": payment_id,
            "status": (
                "completed"
                if processing_result.status == "success"
                else "skipped"
                if processing_result.status in ["already_processed", "skipped"]
                else processing_result.status
            ),
            "actions_taken": processing_result.actions_taken,
            "error": processing_result.error,
            "member": processing_result.member,
            "bank_transaction": processing_result.bank_transaction,
            "payment_entry": processing_result.payment_entry,
            "sales_invoice": processing_result.sales_invoice,
        }

        if processing_result.skipped_reason:
            payment_result["reason"] = processing_result.skipped_reason

        result["results"].append(payment_result)

        # Update counters based on orchestrator result
        if processing_result.status == "success":
            result["completed"] += 1
        elif processing_result.status in ["already_processed", "skipped"]:
            result["skipped"] += 1
        elif processing_result.status == "error":
            result["errors"] += 1

    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def analyze_payment_gaps() -> Dict[str, any]:
    """
    Analyze all Bank Transactions to find gaps in processing.

    Returns comprehensive statistics about missing documents.
    """
    # Get all BT payment IDs (oldest first for consistent processing order)
    bt_payment_ids = frappe.db.sql_list(
        """
        SELECT DISTINCT reference_number
        FROM `tabBank Transaction`
        WHERE reference_number LIKE 'tr_%%'
        ORDER BY creation ASC
    """
    )

    analysis = {
        "total_bank_transactions": len(bt_payment_ids),
        "missing_invoices": 0,
        "missing_payment_entries": 0,
        "missing_both": 0,
        "complete": 0,
        "gap_details": [],
        "timestamp": frappe.utils.now(),
    }

    for payment_id in bt_payment_ids:
        status = get_payment_processing_status(payment_id)

        if status["status"] == "complete":
            analysis["complete"] += 1
        else:
            gap = {
                "payment_id": payment_id,
                "member": status["member"],
                "missing": status["missing_documents"],
            }

            has_sinv = status["has_sales_invoice"]
            has_pe = status["has_payment_entry"]

            if not has_sinv:
                analysis["missing_invoices"] += 1
            if not has_pe:
                analysis["missing_payment_entries"] += 1
            if not has_sinv and not has_pe:
                analysis["missing_both"] += 1

            analysis["gap_details"].append(gap)

    return analysis


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def repair_invoices_missing_gl_entries(
    invoice_names: Union[List[str], str, None] = None, dry_run: bool = True
) -> Dict[str, any]:
    """
    Repair Sales Invoices that are submitted but missing GL entries.

    This can happen when invoices were submitted without a valid Fiscal Year.
    The function ensures the fiscal year exists, then cancels and re-submits
    the invoice to regenerate proper GL entries.

    Args:
        invoice_names: List of Sales Invoice names to repair. If None, finds all problematic invoices.
        dry_run: If True, only report what would be done without making changes.

    Returns:
        dict: Processing results
    """
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() == "true"

    if isinstance(invoice_names, str):
        import json

        invoice_names = json.loads(invoice_names)

    result = {
        "total_checked": 0,
        "repaired": 0,
        "skipped": 0,
        "errors": 0,
        "results": [],
        "dry_run": dry_run,
        "timestamp": frappe.utils.now(),
    }

    # If no invoice_names provided, find all submitted invoices without GL entries
    if not invoice_names:
        # Find submitted invoices (docstatus=1) that have no GL entries
        invoices_without_gl = frappe.db.sql(
            """
            SELECT si.name, si.posting_date, si.customer, si.grand_total, si.outstanding_amount
            FROM `tabSales Invoice` si
            LEFT JOIN `tabGL Entry` gle ON gle.voucher_no = si.name AND gle.voucher_type = 'Sales Invoice'
            WHERE si.docstatus = 1
            AND gle.name IS NULL
            ORDER BY si.posting_date
            """,
            as_dict=True,
        )
        invoice_names = [inv.name for inv in invoices_without_gl]
        frappe.logger().info(f"Found {len(invoice_names)} invoices without GL entries")

    result["total_checked"] = len(invoice_names)

    from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

    for invoice_name in invoice_names:
        inv_result = {
            "invoice": invoice_name,
            "status": "pending",
            "actions": [],
            "error": None,
        }

        try:
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # Check if GL entries already exist
            gl_count = frappe.db.count(
                "GL Entry",
                {"voucher_type": "Sales Invoice", "voucher_no": invoice_name},
            )

            if gl_count > 0:
                inv_result["status"] = "skipped"
                inv_result["actions"].append(f"Already has {gl_count} GL entries")
                result["skipped"] += 1
                result["results"].append(inv_result)
                continue

            inv_result["actions"].append(f"Invoice missing GL entries (posting_date: {invoice.posting_date})")

            if dry_run:
                inv_result["status"] = "dry_run"
                inv_result["actions"].append("Would ensure fiscal year and re-submit")
                result["results"].append(inv_result)
                continue

            # Get company for fiscal year check
            company = invoice.company

            # Ensure fiscal year exists for the posting date
            fiscal_year = ensure_fiscal_year_exists(invoice.posting_date, company)
            inv_result["actions"].append(f"Ensured Fiscal Year: {fiscal_year}")

            # Store original values we need to preserve
            original_posting_date = invoice.posting_date
            original_due_date = invoice.due_date
            original_coverage_start = invoice.custom_coverage_start_date
            original_coverage_end = invoice.custom_coverage_end_date

            # Cancel the invoice
            invoice.cancel()
            inv_result["actions"].append("Cancelled invoice")

            # Amend (create new version from cancelled)
            amended_invoice = frappe.copy_doc(invoice)
            amended_invoice.docstatus = 0
            amended_invoice.amended_from = invoice.name

            # Restore dates (they might be reset during copy)
            amended_invoice.posting_date = original_posting_date
            amended_invoice.due_date = original_due_date
            amended_invoice.set_posting_time = 1
            amended_invoice.custom_coverage_start_date = original_coverage_start
            amended_invoice.custom_coverage_end_date = original_coverage_end

            # Insert and submit
            amended_invoice.insert()
            amended_invoice.submit()

            inv_result["actions"].append(f"Created amended invoice: {amended_invoice.name}")
            inv_result["new_invoice"] = amended_invoice.name
            inv_result["status"] = "repaired"
            result["repaired"] += 1

            # Verify GL entries were created
            new_gl_count = frappe.db.count(
                "GL Entry",
                {"voucher_type": "Sales Invoice", "voucher_no": amended_invoice.name},
            )
            inv_result["actions"].append(f"New invoice has {new_gl_count} GL entries")

        except Exception as e:
            inv_result["status"] = "error"
            inv_result["error"] = str(e)
            result["errors"] += 1
            frappe.log_error(
                f"Error repairing invoice {invoice_name}: {e}",
                "Invoice Repair Error",
            )

        result["results"].append(inv_result)

    return result
