"""
SEPA Batch Integration with Bank Reconciliation
Phase 1: Conservative Approach + Phase 2: Enhanced Processing
"""

import json

import frappe
from frappe.utils import add_days, flt, getdate

from verenigingen.api.sepa_duplicate_prevention import (
    acquire_processing_lock,
    check_batch_processing_status,
    create_payment_entry_with_duplicate_check,
    release_processing_lock,
    validate_batch_mandates,
)

# ========================
# PHASE 1: CONSERVATIVE APPROACH
# ========================


@frappe.whitelist()
def identify_sepa_transactions():
    """Find bank transactions that might be from SEPA batches"""
    try:
        # Get unprocessed bank transactions from last 30 days
        unprocessed_transactions = frappe.get_all(
            "Bank Transaction",
            filters={
                "date": [">=", add_days(getdate(), -30)],
                "docstatus": ["!=", 2],
                "custom_sepa_batch": ["is", "not set"],
                "deposit": [">", 0],  # Only incoming transactions
            },
            fields=["name", "date", "description", "deposit", "reference_number", "bank_account"],
        )

        potential_sepa_matches = []

        for txn in unprocessed_transactions:
            # Look for SEPA-related keywords in description
            sepa_keywords = ["sepa", "dd", "direct debit", "incasso", "lastschrift", "batch"]
            description_lower = txn.description.lower()

            if any(keyword in description_lower for keyword in sepa_keywords):
                # Try to find matching SEPA batch
                matching_batches = find_matching_sepa_batches(txn)

                if matching_batches:
                    potential_sepa_matches.append(
                        {
                            "bank_transaction": txn.name,
                            "transaction_amount": txn.deposit,
                            "description": txn.description,
                            "matching_batches": matching_batches,
                        }
                    )

        return {
            "success": True,
            "potential_matches": potential_sepa_matches,
            "total_found": len(potential_sepa_matches),
        }

    except Exception as e:
        frappe.log_error(f"Error identifying SEPA transactions: {str(e)}")
        return {"success": False, "error": str(e)}


def find_matching_sepa_batches(bank_transaction):
    """Find SEPA Direct Debit Batches that might match this bank transaction"""

    # Search for batches within 7 days of transaction date
    date_range_start = add_days(bank_transaction.date, -7)
    date_range_end = add_days(bank_transaction.date, 3)

    potential_batches = frappe.get_all(
        "SEPA Direct Debit Batch",
        filters={
            "batch_date": ["between", [date_range_start, date_range_end]],
            "docstatus": 1,  # Submitted batches only
            "status": ["in", ["Submitted", "Processed"]],
        },
        fields=["name", "batch_date", "total_amount", "status", "entry_count"],
    )

    matches = []
    for batch in potential_batches:
        # Check for amount match (exact or close)
        amount_difference = abs(flt(bank_transaction.deposit) - flt(batch.total_amount))

        if amount_difference == 0:
            matches.append(
                {
                    "batch_name": batch.name,
                    "match_type": "exact_amount",
                    "confidence": "high",
                    "batch_amount": batch.total_amount,
                    "difference": 0,
                }
            )
        elif amount_difference <= flt(batch.total_amount) * 0.1:  # Within 10%
            matches.append(
                {
                    "batch_name": batch.name,
                    "match_type": "approximate_amount",
                    "confidence": "medium",
                    "batch_amount": batch.total_amount,
                    "difference": amount_difference,
                }
            )

    return matches


@frappe.whitelist()
def process_sepa_transaction_conservative(bank_transaction_name, sepa_batch_name):
    """Process SEPA transaction with conservative approach and duplicate prevention"""

    # Acquire processing lock to prevent concurrent processing
    if not acquire_processing_lock("sepa_batch", sepa_batch_name):
        return {"success": False, "error": "Another process is currently working on this SEPA batch"}

    try:
        # Check if batch has already been processed
        check_batch_processing_status(sepa_batch_name, bank_transaction_name)

        # Validate batch mandates before processing
        sepa_batch = frappe.get_doc("SEPA Direct Debit Batch", sepa_batch_name)
        batch_validation = validate_batch_mandates({"invoices": sepa_batch.invoices})

        if not batch_validation["valid"]:
            return {
                "success": False,
                "error": "Batch contains items without valid SEPA mandates",
                "missing_mandates": batch_validation["missing_mandates"],
            }

        # Continue with original processing logic
        return _process_sepa_transaction_conservative_internal(bank_transaction_name, sepa_batch_name)

    finally:
        # Always release the lock
        release_processing_lock("sepa_batch", sepa_batch_name)


def _process_sepa_transaction_conservative_internal(bank_transaction_name, sepa_batch_name):
    """Conservative processing: Link transaction to batch but handle reconciliation carefully"""
    try:
        bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
        sepa_batch = frappe.get_doc("SEPA Direct Debit Batch", sepa_batch_name)

        # Link bank transaction to SEPA batch
        bank_transaction.custom_sepa_batch = sepa_batch_name
        bank_transaction.custom_processing_status = "SEPA Identified"

        received_amount = flt(bank_transaction.deposit)
        expected_amount = flt(sepa_batch.total_amount)

        if received_amount == expected_amount:
            # Full success - reconcile all items
            result = reconcile_full_sepa_batch(bank_transaction, sepa_batch)
            bank_transaction.custom_processing_status = "Fully Reconciled"

        elif received_amount < expected_amount:
            # Partial success - hold for manual review
            result = handle_partial_sepa_batch(bank_transaction, sepa_batch)
            bank_transaction.custom_processing_status = "Partial - Manual Review Required"

        else:
            # Received more than expected - unusual case
            result = handle_excess_sepa_payment(bank_transaction, sepa_batch)
            bank_transaction.custom_processing_status = "Excess - Manual Review Required"

        bank_transaction.save()

        return {
            "success": True,
            "processing_result": result,
            "status": bank_transaction.custom_processing_status,
        }

    except Exception as e:
        frappe.log_error(f"Error processing SEPA transaction: {str(e)}")
        return {"success": False, "error": str(e)}


def reconcile_full_sepa_batch(bank_transaction, sepa_batch):
    """Reconcile all items in SEPA batch when full amount received"""

    # Get all batch items
    batch_items = frappe.get_all(
        "SEPA Direct Debit Batch Item",
        filters={"parent": sepa_batch.name},
        fields=["name", "sales_invoice", "amount", "customer", "idx"],
    )

    reconciled_items = []

    for item in batch_items:
        try:
            # Create payment entry with duplicate prevention
            payment_data = {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": item.customer,
                "posting_date": bank_transaction.date,
                "paid_amount": item.amount,
                "received_amount": item.amount,
                "target_exchange_rate": 1,
                "source_exchange_rate": 1,
                "reference_no": bank_transaction.reference_number,
                "reference_date": bank_transaction.date,
                "mode_of_payment": "SEPA Direct Debit",
                "custom_bank_transaction": bank_transaction.name,
                "custom_sepa_batch": sepa_batch.name,
                "custom_sepa_batch_item": item.name,
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": item.sales_invoice,
                        "total_amount": item.amount,
                        "outstanding_amount": item.amount,
                        "allocated_amount": item.amount,
                    }
                ],
            }

            payment_result = create_payment_entry_with_duplicate_check(
                item.sales_invoice, item.amount, payment_data
            )

            reconciled_items.append(
                {
                    "invoice": item.sales_invoice,
                    "amount": item.amount,
                    "payment_entry": payment_result.get("payment_entry"),
                    "status": "success",
                }
            )

        except Exception as e:
            reconciled_items.append(
                {"invoice": item.sales_invoice, "amount": item.amount, "status": "failed", "error": str(e)}
            )

    return {
        "type": "full_reconciliation",
        "total_items": len(batch_items),
        "reconciled_count": len([item for item in reconciled_items if item["status"] == "success"]),
        "failed_count": len([item for item in reconciled_items if item["status"] == "failed"]),
        "details": reconciled_items,
    }


def handle_partial_sepa_batch(bank_transaction, sepa_batch):
    """Handle partial SEPA batch success - create manual review task"""

    received_amount = flt(bank_transaction.deposit)
    expected_amount = flt(sepa_batch.total_amount)
    failed_amount = expected_amount - received_amount

    # Create manual review task
    task = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": """
SEPA Batch Partial Success - Manual Review Required

Batch: {sepa_batch.name}
Expected Amount: €{expected_amount:,.2f}
Received Amount: €{received_amount:,.2f}
Failed Amount: €{failed_amount:,.2f}

Bank Transaction: {bank_transaction.name}
Transaction Date: {bank_transaction.date}

Action Required:
1. Identify which member payments failed
2. Update invoice statuses accordingly
3. Process individual reconciliations
4. Follow up on failed payments
        """,
            "priority": "High",
            "status": "Open",
            "reference_type": "SEPA Direct Debit Batch",
            "reference_name": sepa_batch.name,
            "assigned_by": frappe.session.user,
        }
    )
    task.insert()

    # Mark bank transaction as processed but not reconciled
    bank_transaction.custom_manual_review_task = task.name

    return {
        "type": "partial_success_review",
        "expected_amount": expected_amount,
        "received_amount": received_amount,
        "failed_amount": failed_amount,
        "review_task": task.name,
        "action": "Manual review task created",
    }


def handle_excess_sepa_payment(bank_transaction, sepa_batch):
    """Handle cases where more money was received than expected"""

    received_amount = flt(bank_transaction.deposit)
    expected_amount = flt(sepa_batch.total_amount)
    excess_amount = received_amount - expected_amount

    # Create investigation task
    task = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": """
SEPA Batch Excess Payment - Investigation Required

Batch: {sepa_batch.name}
Expected Amount: €{expected_amount:,.2f}
Received Amount: €{received_amount:,.2f}
Excess Amount: €{excess_amount:,.2f}

Possible Causes:
- Multiple batches combined by bank
- Additional payments included
- Currency conversion differences
- Bank processing fees refunded

Action Required: Investigate source of excess payment
        """,
            "priority": "Medium",
            "status": "Open",
            "reference_type": "SEPA Direct Debit Batch",
            "reference_name": sepa_batch.name,
            "assigned_by": frappe.session.user,
        }
    )
    task.insert()

    return {
        "type": "excess_payment_investigation",
        "expected_amount": expected_amount,
        "received_amount": received_amount,
        "excess_amount": excess_amount,
        "investigation_task": task.name,
    }


# ========================
# PHASE 2: ENHANCED PROCESSING
# ========================


@frappe.whitelist()
def process_sepa_return_file(file_content, file_type="csv"):
    """Process SEPA return file with failure details"""
    try:
        if file_type.lower() == "csv":
            return_items = parse_sepa_return_csv(file_content)
        elif file_type.lower() == "xml":
            return_items = parse_sepa_return_xml(file_content)
        else:
            return {"success": False, "error": "Unsupported file type"}

        processed_returns = []

        for return_item in return_items:
            result = process_individual_return(return_item)
            processed_returns.append(result)

        return {
            "success": True,
            "processed_returns": processed_returns,
            "total_processed": len(processed_returns),
        }

    except Exception as e:
        frappe.log_error(f"Error processing SEPA return file: {str(e)}")
        return {"success": False, "error": str(e)}


def parse_sepa_return_csv(csv_content):
    """Parse CSV return file"""
    import csv
    import io

    returns = []
    csv_reader = csv.DictReader(io.StringIO(csv_content))

    for row in csv_reader:
        returns.append(
            {
                "member_reference": row.get("Member_ID", row.get("Reference", "")),
                "amount": flt(row.get("Amount", 0)),
                "return_reason": row.get("Return_Reason", row.get("Reason", "")),
                "return_code": row.get("Return_Code", ""),
                "transaction_date": row.get("Transaction_Date", ""),
                "mandate_reference": row.get("Mandate_Reference", ""),
            }
        )

    return returns


def parse_sepa_return_xml(xml_content):
    """Parse XML return file (SEPA PAIN format)"""
    # Simplified XML parsing - would need proper SEPA PAIN parser in production
    returns = []

    # This is a simplified version - real implementation would use proper XML parsing
    # for SEPA PAIN.002 return files

    return returns


def process_individual_return(return_item):
    """Process a single returned payment"""
    try:
        # Find the member and related invoice
        member = None
        invoice = None

        # Try to find member by reference
        if return_item.get("member_reference"):
            member = frappe.db.get_value(
                "Member", {"member_id": return_item["member_reference"]}, ["name", "customer"]
            )

        # Find the invoice by amount and member
        if member:
            invoice = frappe.db.get_value(
                "Sales Invoice",
                {
                    "customer": member[1],
                    "grand_total": return_item["amount"],
                    "status": ["in", ["Paid", "Partly Paid"]],
                },
                ["name", "outstanding_amount"],
            )

        if invoice:
            # Reverse the payment entry
            reverse_failed_sepa_payment(invoice[0], return_item)

            # Create failed payment record
            create_failed_payment_record(member[0], invoice[0], return_item)

            # Notify member of failed payment
            notify_member_of_failed_payment(member[0], invoice[0], return_item)

            return {
                "member_reference": return_item.get("member_reference"),
                "invoice": invoice[0],
                "status": "processed",
                "action": "Payment reversed and member notified",
            }
        else:
            return {
                "member_reference": return_item.get("member_reference"),
                "status": "not_found",
                "action": "Could not identify member/invoice",
            }

    except Exception as e:
        return {"member_reference": return_item.get("member_reference"), "status": "error", "error": str(e)}


def reverse_failed_sepa_payment(invoice_name, return_item):
    """Reverse payment entry for failed SEPA payment"""

    # Find the payment entry to reverse
    payment_entries = frappe.get_all(
        "Payment Entry Reference",
        filters={"reference_name": invoice_name, "reference_doctype": "Sales Invoice"},
        fields=["parent"],
    )

    for pe_ref in payment_entries:
        payment_entry = frappe.get_doc("Payment Entry", pe_ref.parent)

        # Check if this was a SEPA payment
        if payment_entry.mode_of_payment == "SEPA Direct Debit" and payment_entry.docstatus == 1:
            # Create cancellation entry
            cancellation_entry = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",  # Reverse direction
                    "party_type": "Customer",
                    "party": payment_entry.party,
                    "posting_date": getdate(),
                    "paid_amount": payment_entry.paid_amount,
                    "received_amount": payment_entry.received_amount,
                    "reference_no": f"SEPA RETURN - {payment_entry.reference_no}",
                    "reference_date": getdate(),
                    "mode_of_payment": "SEPA Direct Debit Return",
                    "custom_original_payment": payment_entry.name,
                    "custom_return_reason": return_item.get("return_reason", ""),
                    "references": [
                        {
                            "reference_doctype": "Sales Invoice",
                            "reference_name": invoice_name,
                            "total_amount": payment_entry.paid_amount,
                            "outstanding_amount": 0,
                            "allocated_amount": payment_entry.paid_amount,
                        }
                    ],
                }
            )

            cancellation_entry.insert()
            cancellation_entry.submit()

            return cancellation_entry.name

    return None


def create_failed_payment_record(member_name, invoice_name, return_item):
    """Create a record of the failed payment for tracking"""

    failed_payment = frappe.get_doc(
        {
            "doctype": "Comment",  # Using Comment as a simple tracking method
            "comment_type": "Info",
            "reference_doctype": "Member",
            "reference_name": member_name,
            "content": """
SEPA Payment Failed
Invoice: {invoice_name}
Amount: €{return_item.get('amount', 0):,.2f}
Return Reason: {return_item.get('return_reason', 'Unknown')}
Return Code: {return_item.get('return_code', '')}
Date: {getdate()}

Action Required: Follow up with member for alternative payment method
        """,
        }
    )
    failed_payment.insert()

    return failed_payment.name


def notify_member_of_failed_payment(member_name, invoice_name, return_item):
    """Send notification to member about failed payment"""

    member = frappe.get_doc("Member", member_name)
    frappe.get_doc("Sales Invoice", invoice_name)

    # Create email notification (simplified) - unused
    # email_content = """
    # Dear {member.first_name or member.full_name},

    # We were unable to process your membership payment via direct debit.

    # Invoice: {invoice_name}
    # Amount: €{return_item.get('amount', 0):,.2f}
    # Reason: {return_item.get('return_reason', 'Bank declined the payment')}

    # Please update your payment method or contact us to resolve this issue.

    # Best regards,
    # Membership Team
    # """

    # Create a task for follow-up rather than sending email directly
    # (Email sending would need proper template setup)
    task = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": f"Follow up with {member.full_name} - Failed SEPA payment {invoice_name}",
            "priority": "High",
            "status": "Open",
            "reference_type": "Member",
            "reference_name": member_name,
        }
    )
    task.insert()

    return task.name


@frappe.whitelist()
def correlate_return_transactions():
    """Look for return transactions and correlate with SEPA batches"""
    try:
        # Find recent outgoing transactions that might be returns
        recent_returns = frappe.get_all(
            "Bank Transaction",
            filters={
                "date": [">=", add_days(getdate(), -14)],
                "withdrawal": [">", 0],
                "custom_sepa_batch": ["is", "not set"],
            },
            fields=["name", "date", "description", "withdrawal", "reference_number"],
        )

        correlated_returns = []

        for return_txn in recent_returns:
            # Look for SEPA-related keywords
            description_lower = return_txn.description.lower()
            sepa_keywords = ["return", "reject", "failed", "sepa", "dd", "direct debit"]

            if any(keyword in description_lower for keyword in sepa_keywords):
                # Try to find the original SEPA batch
                original_batch = find_original_sepa_batch_for_return(return_txn)

                if original_batch:
                    correlated_returns.append(
                        {
                            "return_transaction": return_txn.name,
                            "amount": return_txn.withdrawal,
                            "original_batch": original_batch["batch_name"],
                            "confidence": original_batch["confidence"],
                        }
                    )

        return {
            "success": True,
            "correlated_returns": correlated_returns,
            "total_found": len(correlated_returns),
        }

    except Exception as e:
        frappe.log_error(f"Error correlating return transactions: {str(e)}")
        return {"success": False, "error": str(e)}


def find_original_sepa_batch_for_return(return_transaction):
    """Find the original SEPA batch that this return transaction relates to"""

    # Look for SEPA batches in the 2 weeks before this return
    search_start = add_days(return_transaction.date, -14)
    search_end = add_days(return_transaction.date, -1)

    potential_batches = frappe.get_all(
        "SEPA Direct Debit Batch",
        filters={"batch_date": ["between", [search_start, search_end]], "docstatus": 1},
        fields=["name", "batch_date", "total_amount", "entry_count"],
    )

    # Look for amount matches within the batch items
    for batch in potential_batches:
        batch_items = frappe.get_all(
            "SEPA Direct Debit Batch Item",
            filters={"parent": batch.name},
            fields=["amount", "customer", "sales_invoice"],
        )

        # Check if any batch item amount matches the return amount
        for item in batch_items:
            if abs(flt(item.amount) - flt(return_transaction.withdrawal)) < 0.01:
                return {"batch_name": batch.name, "confidence": "high", "matching_item": item}

    return None


# ========================
# UTILITY FUNCTIONS
# ========================


@frappe.whitelist()
def get_sepa_reconciliation_dashboard():
    """Get dashboard data for SEPA reconciliation status"""
    try:
        # Recent SEPA batches
        recent_batches = frappe.get_all(
            "SEPA Direct Debit Batch",
            filters={"batch_date": [">=", add_days(getdate(), -30)], "docstatus": 1},
            fields=["name", "batch_date", "total_amount", "status", "entry_count"],
        )

        # Bank transactions with SEPA links
        linked_transactions = frappe.get_all(
            "Bank Transaction",
            filters={"custom_sepa_batch": ["is", "set"], "date": [">=", add_days(getdate(), -30)]},
            fields=["name", "date", "deposit", "custom_sepa_batch", "custom_processing_status"],
        )

        # Manual review tasks
        pending_reviews = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": "SEPA Direct Debit Batch",
                "status": "Open",
                "creation": [">=", add_days(getdate(), -30)],
            },
            fields=["name", "description", "reference_name", "creation"],
        )

        return {
            "success": True,
            "recent_batches": recent_batches,
            "linked_transactions": linked_transactions,
            "pending_reviews": pending_reviews,
            "summary": {
                "total_batches": len(recent_batches),
                "total_linked_transactions": len(linked_transactions),
                "pending_reviews": len(pending_reviews),
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def manual_sepa_reconciliation(bank_transaction_name, batch_items_json):
    """Manually reconcile specific items from a SEPA batch"""
    try:
        bank_transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
        batch_items = json.loads(batch_items_json)

        reconciled_items = []

        for item in batch_items:
            if item.get("reconcile", False):
                # Create payment entry for this specific item
                result = create_manual_payment_entry(bank_transaction, item)
                reconciled_items.append(result)

        # Update bank transaction status
        bank_transaction.custom_processing_status = "Manually Reconciled"
        bank_transaction.save()

        return {
            "success": True,
            "reconciled_items": reconciled_items,
            "total_reconciled": len(reconciled_items),
        }

    except Exception as e:
        frappe.log_error(f"Error in manual SEPA reconciliation: {str(e)}")
        return {"success": False, "error": str(e)}


def create_manual_payment_entry(bank_transaction, batch_item):
    """Create payment entry for manually selected batch item"""

    payment_entry = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": batch_item["customer"],
            "posting_date": bank_transaction.date,
            "paid_amount": batch_item["amount"],
            "received_amount": batch_item["amount"],
            "reference_no": bank_transaction.reference_number,
            "reference_date": bank_transaction.date,
            "mode_of_payment": "SEPA Direct Debit",
            "custom_bank_transaction": bank_transaction.name,
            "custom_manual_reconciliation": 1,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": batch_item["sales_invoice"],
                    "total_amount": batch_item["amount"],
                    "outstanding_amount": batch_item["amount"],
                    "allocated_amount": batch_item["amount"],
                }
            ],
        }
    )

    payment_entry.insert()
    payment_entry.submit()

    return {
        "invoice": batch_item["sales_invoice"],
        "amount": batch_item["amount"],
        "payment_entry": payment_entry.name,
        "status": "success",
    }
