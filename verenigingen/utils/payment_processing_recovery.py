"""
Payment Processing Recovery Utilities

Provides idempotency checks, failure detection, and recovery tools for Mollie payment processing.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import frappe


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

    # Also check for PE with matching reference
    if not pe:
        pe = frappe.db.get_value("Payment Entry", {"reference_no": payment_id}, "name")

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
def get_incomplete_payments(payment_ids: List[str] = None) -> Dict[str, any]:
    """
    Find payments that are partially processed (missing one or more documents).

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
        # Get all payment IDs from Bank Transactions
        payment_ids = frappe.db.sql_list(
            """
            SELECT DISTINCT reference_number
            FROM `tabBank Transaction`
            WHERE reference_number LIKE 'tr_%%'
            ORDER BY creation DESC
            LIMIT 2500
        """
        )

    for payment_id in payment_ids:
        status = get_payment_processing_status(payment_id)
        result["total_checked"] += 1

        if status["status"] == "complete":
            result["complete"] += 1
        elif status["status"] == "partial":
            result["partial"] += 1
            result["incomplete_payments"].append(status)
        else:
            result["unprocessed"] += 1
            result["incomplete_payments"].append(status)

    return result


@frappe.whitelist()
def complete_partial_payments(
    payment_ids: List[str] = None, dry_run: bool = True, max_payments: int = None
) -> Dict[str, any]:
    """
    Complete partially processed payments by creating missing documents.

    Args:
        payment_ids: List of payment IDs to complete. If None, finds all incomplete payments automatically.
        dry_run: If True, only report what would be done without making changes
        max_payments: Maximum number of payments to process. If None, processes all found payments (up to query limit).

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

    from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor

    dues_processor = DuesPaymentProcessor()

    result = {
        "total_requested": 0,
        "completed": 0,
        "skipped": 0,
        "errors": 0,
        "results": [],
        "dry_run": dry_run,
        "max_payments": max_payments,
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

    for payment_id in payment_ids:
        payment_result = {"payment_id": payment_id, "status": "pending", "actions_taken": [], "error": None}

        # Validate payment ID format before processing
        if not mollie_payment_pattern.match(payment_id):
            payment_result["status"] = "skipped"
            payment_result["reason"] = "Invalid payment ID format (not a Mollie payment ID)"
            result["skipped"] += 1
            result["results"].append(payment_result)
            frappe.logger().warning(f"Skipping invalid payment ID: {payment_id[:50]}...")
            continue

        try:
            # Check current status
            status = get_payment_processing_status(payment_id)

            if status["status"] == "complete":
                payment_result["status"] = "skipped"
                payment_result["reason"] = "Already complete"
                result["skipped"] += 1
                result["results"].append(payment_result)
                continue

            if not status["member"]:
                payment_result["status"] = "error"
                payment_result["error"] = "Cannot determine member for payment"
                result["errors"] += 1
                result["results"].append(payment_result)
                continue

            if dry_run:
                payment_result["status"] = "dry_run"
                payment_result["would_create"] = status["missing_documents"]
                result["results"].append(payment_result)
                continue

            # Get payment date and amount from Bank Transaction if it exists
            # Otherwise fetch from Mollie (needed for PE/BT creation anyway)
            payment = None
            if status["has_bank_transaction"]:
                bt_doc = frappe.get_doc("Bank Transaction", status["bank_transaction"])
                payment_date = bt_doc.date
                payment_amount = abs(bt_doc.unallocated_amount or bt_doc.deposit)

            # Fetch payment from Mollie if we need it for PE or BT creation
            if not status["has_payment_entry"] or not status["has_bank_transaction"]:
                payment = dues_processor.mollie_client.sdk_client.payments.get(payment_id)

                # If we didn't get date/amount from BT, get from payment
                if not status["has_bank_transaction"]:
                    # Handle both dict and object responses from Mollie
                    if isinstance(payment, dict):
                        payment_date = datetime.strptime(
                            payment.get("createdAt", payment.get("created_at"))[:10], "%Y-%m-%d"
                        ).date()
                        payment_amount = float(payment["amount"]["value"])
                    else:
                        payment_date = datetime.strptime(payment.created_at[:10], "%Y-%m-%d").date()
                        payment_amount = float(payment.amount.value)

            # Ensure fiscal year exists for the payment date (required for invoice/PE creation)
            from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            company = verenigingen_settings.company or frappe.defaults.get_global_default("company")
            try:
                fiscal_year = ensure_fiscal_year_exists(payment_date, company)
                if fiscal_year:
                    payment_result["actions_taken"].append(f"Ensured Fiscal Year: {fiscal_year}")
            except Exception as fy_error:
                frappe.logger().warning(f"Could not ensure fiscal year for {payment_date}: {fy_error}")
                # Continue anyway - will fail later if truly missing

            # Create missing documents
            if not status["has_sales_invoice"]:
                # Check for overlapping coverage before creating invoice
                from verenigingen.services.billing.coverage_calculator import (
                    calculate_coverage_for_payment_date,
                )
                from verenigingen.services.billing.coverage_overlap_detector import check_coverage_overlap

                # Calculate coverage based on member's billing frequency
                coverage_start, coverage_end = calculate_coverage_for_payment_date(
                    status["member"], payment_date
                )

                member = frappe.get_doc("Member", status["member"])
                if member.customer:
                    # Use proper overlap detection (not just exact match)
                    overlap_result = check_coverage_overlap(
                        customer=member.customer,
                        proposed_start=coverage_start,
                        proposed_end=coverage_end,
                        exclude_cancelled=True,
                    )

                    if overlap_result.has_overlap:
                        if overlap_result.exact_match:
                            # Exact match found - can link to it
                            payment_result["actions_taken"].append(
                                f"Found existing Sales Invoice: {overlap_result.exact_match}"
                            )
                            status["sales_invoice"] = overlap_result.exact_match
                            status["has_sales_invoice"] = True
                        else:
                            # Overlapping but not exact match - flag for manual review
                            overlapping_names = [inv["name"] for inv in overlap_result.overlapping_invoices]
                            payment_result["status"] = "needs_review"
                            payment_result["error"] = (
                                f"Coverage overlap detected: proposed {coverage_start} to {coverage_end} "
                                f"overlaps with existing invoice(s): {', '.join(overlapping_names)}. "
                                f"Manual review required."
                            )
                            payment_result["overlapping_invoices"] = overlapping_names
                            result["errors"] += 1
                            result["results"].append(payment_result)
                            continue  # Skip this payment - needs manual intervention
                    else:
                        # No overlap - safe to create new invoice
                        sinv = dues_processor._get_or_create_historical_invoice(
                            status["member"], payment_date, payment_amount
                        )
                        if sinv:
                            payment_result["actions_taken"].append(f"Created Sales Invoice: {sinv}")
                            status["sales_invoice"] = sinv
                            status["has_sales_invoice"] = True

            if not status["has_payment_entry"] and payment:
                # Create PE (needs payment object)
                pe = dues_processor._create_payment_entry_for_dues(status["member"], payment)
                if pe:
                    payment_result["actions_taken"].append(f"Created Payment Entry: {pe}")
                    status["payment_entry"] = pe
                    status["has_payment_entry"] = True

            if not status["has_bank_transaction"] and payment:
                # Double-check before creating BT to minimize race condition window
                # Re-query database immediately before creation attempt
                existing_bt_check = frappe.db.get_value(
                    "Bank Transaction", {"reference_number": payment_id}, "name"
                )

                if existing_bt_check:
                    # BT was created by another process between status check and now
                    frappe.logger().info(
                        f"⏭️ Bank Transaction {existing_bt_check} created by another process for {payment_id}"
                    )
                    payment_result["actions_taken"].append(
                        f"Bank Transaction already exists: {existing_bt_check}"
                    )
                    status["bank_transaction"] = existing_bt_check
                    status["has_bank_transaction"] = True
                else:
                    # Create BT (needs payment object)
                    # Handle race condition where another process creates BT concurrently
                    try:
                        bt_result = dues_processor.process_dues_payment(
                            payment_id, payment, creation_mode="Bank Transaction"
                        )
                        if bt_result.get("status") == "success":
                            payment_result["actions_taken"].append(
                                f"Created Bank Transaction: {bt_result['bank_transaction']}"
                            )
                            status["bank_transaction"] = bt_result["bank_transaction"]
                            status["has_bank_transaction"] = True
                        elif bt_result.get("status") == "already_processed":
                            # BT already existed (race condition or concurrent webhook)
                            payment_result["actions_taken"].append(
                                f"Bank Transaction already exists: {bt_result.get('bank_transaction', 'unknown')}"
                            )
                            status["bank_transaction"] = bt_result.get("bank_transaction")
                            status["has_bank_transaction"] = True
                    except (frappe.UniqueValidationError, frappe.DuplicateEntryError) as e:
                        # Another process created the Bank Transaction between our check and insert
                        # This is expected in concurrent webhook scenarios
                        frappe.logger().info(
                            f"⏭️ Bank Transaction race condition for {payment_id}: {str(e)[:100]}"
                        )
                        # Re-check for existing Bank Transaction
                        existing_bt = frappe.db.get_value(
                            "Bank Transaction", {"reference_number": payment_id}, "name"
                        )
                        if existing_bt:
                            payment_result["actions_taken"].append(
                                f"Bank Transaction exists (race condition): {existing_bt}"
                            )
                            status["bank_transaction"] = existing_bt
                            status["has_bank_transaction"] = True
                        else:
                            # Unexpected: duplicate error but can't find the document
                            raise

            # Link BT to PE if needed (handles both newly created and pre-existing documents)
            # This ensures proper reconciliation even if documents were created separately
            if status["has_bank_transaction"] and status["has_payment_entry"]:
                # Check if already linked (idempotent check)
                existing_link = frappe.db.exists(
                    "Bank Transaction Payments",
                    {"parent": status["bank_transaction"], "payment_entry": status["payment_entry"]},
                )

                if not existing_link:
                    bt_doc = frappe.get_doc("Bank Transaction", status["bank_transaction"])
                    pe_doc = frappe.get_doc("Payment Entry", status["payment_entry"])

                    # Use ERPNext's standard reconciliation pattern (same as Bank Reconciliation Tool)
                    # This properly handles submitted Bank Transactions
                    voucher = {
                        "payment_doctype": "Payment Entry",
                        "payment_name": status["payment_entry"],
                    }
                    bt_doc.add_payment_entries([voucher])  # Adds with allocated_amount=0
                    bt_doc.validate_duplicate_references()
                    bt_doc.allocate_payment_entries()  # Calculates actual allocation
                    bt_doc.update_allocated_amount()
                    bt_doc.set_status()
                    bt_doc.save()

                    # Reload to get updated status after save hooks run
                    bt_doc.reload()

                    # Get actual allocated amount for logging
                    allocated_amount = 0
                    for pe in bt_doc.payment_entries:
                        if pe.payment_entry == status["payment_entry"]:
                            allocated_amount = pe.allocated_amount
                            break

                    # Set clearance date on PE if not already set
                    if not pe_doc.clearance_date and bt_doc.date:
                        pe_doc.db_set("clearance_date", bt_doc.date, update_modified=False)
                        payment_result["actions_taken"].append(
                            f"Linked BT to PE and set clearance_date={bt_doc.date} (BT status: {bt_doc.status})"
                        )
                    else:
                        payment_result["actions_taken"].append(
                            f"Linked BT to PE (BT status: {bt_doc.status})"
                        )

                    frappe.logger().info(
                        f"✅ Linked Bank Transaction {bt_doc.name} to Payment Entry {pe_doc.name} "
                        f"(allocated: {allocated_amount}, status: {bt_doc.status})"
                    )
                else:
                    frappe.logger().debug(
                        f"BT {status['bank_transaction']} already linked to PE {status['payment_entry']}"
                    )

            # Link Sales Invoice to Payment Entry and reconcile if needed
            if status["has_payment_entry"] and status["has_sales_invoice"]:
                pe_doc = frappe.get_doc("Payment Entry", status["payment_entry"])

                # Check if SINV already linked
                existing_sinv_link = frappe.db.exists(
                    "Payment Entry Reference",
                    {"parent": pe_doc.name, "reference_name": status["sales_invoice"]},
                )

                if not existing_sinv_link:
                    # Get SINV details for linking
                    sinv_doc = frappe.get_doc("Sales Invoice", status["sales_invoice"])
                    outstanding = sinv_doc.outstanding_amount

                    if outstanding > 0:
                        allocated = min(outstanding, pe_doc.unallocated_amount)

                        pe_doc.append(
                            "references",
                            {
                                "reference_doctype": "Sales Invoice",
                                "reference_name": sinv_doc.name,
                                "total_amount": sinv_doc.grand_total,
                                "outstanding_amount": outstanding,
                                "allocated_amount": allocated,
                            },
                        )

                        # Update PE unallocated amount
                        pe_doc.unallocated_amount = pe_doc.unallocated_amount - allocated

                        # Submit PE if it's still in draft and fully allocated
                        if pe_doc.docstatus == 0 and pe_doc.unallocated_amount == 0:
                            pe_doc.submit()
                            payment_result["actions_taken"].append("Linked PE to SINV and submitted PE")
                        else:
                            pe_doc.save()
                            payment_result["actions_taken"].append("Linked PE to SINV")

                        # Reload SINV to check if now paid
                        sinv_doc.reload()
                        if sinv_doc.outstanding_amount == 0:
                            payment_result["actions_taken"].append(f"Reconciled SINV {sinv_doc.name} (paid)")
                    else:
                        payment_result["actions_taken"].append(f"SINV {sinv_doc.name} already paid")
                else:
                    payment_result["actions_taken"].append("PE already linked to SINV")

            payment_result["status"] = "completed"
            result["completed"] += 1

        except Exception as e:
            payment_result["status"] = "error"
            payment_result["error"] = str(e)
            result["errors"] += 1
            # Truncate payment_id in title to stay under 140 char limit
            short_id = payment_id[:30] + "..." if len(payment_id) > 30 else payment_id
            frappe.log_error(
                message=f"Error completing payment {payment_id}: {e}",
                title=f"Payment Recovery Error: {short_id}",
            )

        result["results"].append(payment_result)

    return result


@frappe.whitelist()
def analyze_payment_gaps() -> Dict[str, any]:
    """
    Analyze all Bank Transactions to find gaps in processing.

    Returns comprehensive statistics about missing documents.
    """
    # Get all BT payment IDs
    bt_payment_ids = frappe.db.sql_list(
        """
        SELECT DISTINCT reference_number
        FROM `tabBank Transaction`
        WHERE reference_number LIKE 'tr_%%'
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
def repair_invoices_missing_gl_entries(
    invoice_names: List[str] = None, dry_run: bool = True
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
