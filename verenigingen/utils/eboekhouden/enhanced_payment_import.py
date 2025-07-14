"""
Enhanced payment import function that replaces the hardcoded implementation.

This module provides the main entry point for processing E-Boekhouden payment
mutations with proper bank account mapping and multi-invoice support.
"""

import frappe
from frappe import _

from verenigingen.utils.eboekhouden.payment_processing import PaymentEntryHandler


def create_enhanced_payment_entry(mutation_detail, company, cost_center, debug_info):
    """
    Create Payment Entry with enhanced bank account mapping and invoice reconciliation.

    This function replaces the hardcoded _create_payment_entry implementation
    with a sophisticated handler that:
    - Maps E-Boekhouden ledger IDs to correct bank accounts
    - Handles multi-invoice payments with comma-separated invoice numbers
    - Allocates payments to specific invoices based on row data
    - Provides comprehensive error handling and logging

    Args:
        mutation_detail: E-Boekhouden mutation data
        company: Company name
        cost_center: Cost center
        debug_info: List to append debug messages

    Returns:
        Payment Entry name if successful, None otherwise
    """
    try:
        # Initialize handler
        handler = PaymentEntryHandler(company, cost_center)

        # Process the payment
        payment_name = handler.process_payment_mutation(mutation_detail)

        # Add handler logs to debug info
        debug_info.extend(handler.get_debug_log())

        if payment_name:
            debug_info.append(f"Successfully created enhanced Payment Entry: {payment_name}")

            # Log statistics
            log_payment_statistics(payment_name, mutation_detail, handler)
        else:
            debug_info.append(f"Failed to create Payment Entry for mutation {mutation_detail.get('id')}")

        return payment_name

    except Exception as e:
        error_msg = f"Enhanced payment creation failed: {str(e)}"
        debug_info.append(f"ERROR: {error_msg}")
        frappe.log_error(error_msg, "Enhanced Payment Import")
        return None


def log_payment_statistics(payment_name, mutation_detail, handler):
    """Log payment processing statistics for monitoring."""
    try:
        pe = frappe.get_doc("Payment Entry", payment_name)

        stats = {
            "payment_entry": payment_name,
            "mutation_id": mutation_detail.get("id"),
            "payment_type": pe.payment_type,
            "amount": pe.paid_amount or pe.received_amount,
            "bank_account": pe.paid_to if pe.payment_type == "Receive" else pe.paid_from,
            "party": pe.party,
            "invoice_count": len(handler._parse_invoice_numbers(mutation_detail.get("invoiceNumber", ""))),
            "references_created": len(pe.references),
            "fully_allocated": sum(ref.allocated_amount for ref in pe.references)
            == (pe.paid_amount or pe.received_amount),
        }

        frappe.logger().info(f"Payment Statistics: {stats}")

        # Track bank account usage
        if not stats["bank_account"].endswith("Kas - NVV"):
            frappe.logger().info(
                f"✓ Payment {payment_name} correctly uses bank account: {stats['bank_account']}"
            )

    except Exception as e:
        frappe.logger().error(f"Error logging payment statistics: {str(e)}")


@frappe.whitelist()
def test_enhanced_payment_processing(mutation_id=None):
    """
    Test the enhanced payment processing with a specific mutation.

    Args:
        mutation_id: E-Boekhouden mutation ID to test

    Returns:
        Dict with test results
    """
    if not mutation_id:
        # Use a known test mutation
        mutation_id = 5473  # Multi-invoice supplier payment

    # Get mutation from API or database
    from verenigingen.utils.eboekhouden.eboekhouden_rest_client import EBoekhoudenRESTClient

    try:
        client = EBoekhoudenRESTClient()
        mutation = client.get_mutation(mutation_id)

        if not mutation:
            return {"success": False, "error": f"Mutation {mutation_id} not found"}

        # Process with enhanced handler
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        debug_info = []

        payment_name = create_enhanced_payment_entry(
            mutation, company, None, debug_info  # Will use default cost center
        )

        if payment_name:
            pe = frappe.get_doc("Payment Entry", payment_name)

            return {
                "success": True,
                "payment_entry": payment_name,
                "bank_account": pe.paid_to if pe.payment_type == "Receive" else pe.paid_from,
                "party": pe.party,
                "amount": pe.paid_amount or pe.received_amount,
                "references": [
                    {"invoice": ref.reference_name, "allocated": ref.allocated_amount}
                    for ref in pe.references
                ],
                "debug_log": debug_info,
            }
        else:
            return {"success": False, "error": "Payment creation failed", "debug_log": debug_info}

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def compare_payment_implementations(limit=10):
    """
    Compare hardcoded vs enhanced payment implementation results.

    Returns comparison data for analysis.
    """
    results = {
        "total_analyzed": 0,
        "bank_account_improvements": 0,
        "reconciliation_improvements": 0,
        "examples": [],
    }

    # Get recent payment mutations
    payments = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.eboekhouden_mutation_nr,
            pe.paid_to,
            pe.paid_from,
            pe.payment_type,
            pe.party,
            COUNT(per.name) as reference_count
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
        WHERE pe.eboekhouden_mutation_nr IS NOT NULL
        AND pe.docstatus = 1
        GROUP BY pe.name
        ORDER BY pe.creation DESC
        LIMIT %s
    """,
        limit,
        as_dict=True,
    )

    for payment in payments:
        results["total_analyzed"] += 1

        # Check if using hardcoded Kas account
        bank_account = payment.paid_to if payment.payment_type == "Receive" else payment.paid_from
        if bank_account and bank_account.endswith("Kas - NVV"):
            results["bank_account_improvements"] += 1

            results["examples"].append(
                {
                    "payment_entry": payment.name,
                    "mutation_id": payment.eboekhouden_mutation_nr,
                    "current_bank": bank_account,
                    "has_references": payment.reference_count > 0,
                    "improvement": "Would map to correct bank account",
                }
            )

        # Check reconciliation
        if payment.reference_count == 0 and payment.party:
            results["reconciliation_improvements"] += 1

    results["improvement_rate"] = {
        "bank_accounts": f"{(results['bank_account_improvements'] / results['total_analyzed'] * 100):.1f}%"
        if results["total_analyzed"] > 0
        else "0%",
        "reconciliation": f"{(results['reconciliation_improvements'] / results['total_analyzed'] * 100):.1f}%"
        if results["total_analyzed"] > 0
        else "0%",
    }

    return results
