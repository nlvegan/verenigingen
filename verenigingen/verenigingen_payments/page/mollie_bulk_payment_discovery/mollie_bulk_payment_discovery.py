# Copyright (c) 2025, Molecular Bits and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def run_discovery(retrieval_mode="customer", days_back=7, max_members=None, date_offset=0):
    """
    API endpoint for running bulk payment discovery.

    Args:
        retrieval_mode: "customer" or "balance_transactions"
        days_back: Number of days to look back
        max_members: Maximum members to check (customer mode only)
        date_offset: Start lookback N days ago

    Returns:
        dict: Discovery results with payments, orphaned transactions, etc.
    """
    from verenigingen.integrations.mollie.services.bulk_payment_checker import BulkPaymentChecker

    # Convert string parameters to appropriate types
    days_back = int(days_back)
    date_offset = int(date_offset)
    max_members = int(max_members) if max_members else None

    checker = BulkPaymentChecker()

    try:
        result = checker.check_all_customers_for_new_payments(
            days_back=days_back,
            retrieval_mode=retrieval_mode,
            max_members=max_members,
            date_offset=date_offset,
        )

        # Format result for frontend consumption
        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        frappe.log_error(f"Bulk Payment Discovery Error: {e}", "Mollie Bulk Payment Discovery")
        return {
            "success": False,
            "error": str(e),
        }


@frappe.whitelist()
def process_payment(payment_id):
    """
    API endpoint for processing a single payment.

    Args:
        payment_id: Mollie payment ID to process

    Returns:
        dict: Processing result
    """
    from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor

    processor = DuesPaymentProcessor()

    try:
        result = processor.process_dues_payment(payment_id)
        return {
            "success": result.get("status") == "success",
            "data": result,
        }
    except Exception as e:
        frappe.log_error(f"Payment Processing Error: {e}", "Mollie Bulk Payment Discovery")
        return {
            "success": False,
            "error": str(e),
        }
