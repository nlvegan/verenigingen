"""
Unified Payment Entry Creator

This module provides a single, consistent way to create Payment Entries for both
regular payments and refunds, ensuring proper idempotency and preventing duplicates.

Replaces the separate refund processing logic with unified logic that reuses
the main payment processing patterns.
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, getdate


def create_unified_payment_entry(
    donation_doc,
    mollie_payment_id: str,
    amount: float,
    payment_type: str = "Receive",
    reference_suffix: str = "",
    refund_date: Optional[str] = None,
    description: str = "",
) -> Optional[Any]:
    """
    Create a Payment Entry using unified logic for both payments and refunds.

    Args:
        donation_doc: Donation document
        mollie_payment_id: Mollie payment ID (e.g., tr_xxxxx)
        amount: Payment amount (positive for payments, positive for refunds too)
        payment_type: "Receive" for payments, "Pay" for refunds
        reference_suffix: Suffix for reference_no (e.g., "_refund_re_xxxxx")
        refund_date: Date for refunds (if None, uses today)
        description: Additional description for remarks

    Returns:
        Payment Entry document or None if failed
    """
    try:
        # Get the customer from donor (reuse logic from main payment processing)
        donor_doc = frappe.get_doc("Donor", donation_doc.donor)
        customer = donor_doc.customer

        if not customer:
            frappe.logger().info(f"🔄 No customer linked to donor {donation_doc.donor}, creating one...")
            # Auto-create customer from donor
            customer = donor_doc.get_or_create_customer()
            if not customer:
                frappe.logger().error(f"❌ Failed to create customer for donor {donation_doc.donor}")
                return None
            frappe.logger().info(f"✅ Created customer {customer} for donor {donation_doc.donor}")

        # Build reference number with suffix for refunds
        reference_no = mollie_payment_id + reference_suffix

        # Check if Payment Entry already exists (UNIFIED IDEMPOTENCY)
        existing_pe = frappe.db.get_value(
            "Payment Entry",
            {"payment_type": payment_type, "reference_no": reference_no, "party": customer},
            "name",
        )

        if existing_pe:
            frappe.logger().info(f"⚠️ Payment Entry already exists: {existing_pe}")
            return frappe.get_doc("Payment Entry", existing_pe)

        # Get company and accounts (reuse logic from main payment processing)
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.company or frappe.defaults.get_global_default("company")

        # Get donation receivable account
        donation_account = settings.donation_receivable_account
        if not donation_account:
            donation_account = frappe.get_value("Company", company, "default_receivable_account")

        # Get bank account (Mollie) - prefer settings, fallback to named account, then default
        bank_account = settings.mollie_bank_account
        if not bank_account:
            bank_account = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
        if not bank_account:
            bank_account = frappe.get_value("Company", company, "default_bank_account")

        # Validate required accounts
        if not donation_account or not bank_account:
            frappe.logger().error(f"❌ Missing accounts - donation: {donation_account}, bank: {bank_account}")
            return None

        # Get customer display name
        customer_doc = frappe.get_doc("Customer", customer)
        display_name = customer_doc.customer_name or donor_doc.donor_name or "Unknown"

        # Set cost center using shared resolver
        from verenigingen.verenigingen_payments.mollie.services.shared import get_cost_center_for_donation

        cost_center = get_cost_center_for_donation(donation_doc, company)

        # Set accounts based on payment type
        if payment_type == "Receive":
            # Regular payment: money flows FROM receivable TO bank
            paid_from = donation_account
            paid_to = bank_account
            mode_of_payment = "Mollie"
            base_title = f"{display_name} - {donation_doc.name}"
            base_remarks = f"Payment for {donation_doc.name} via Mollie - {donor_doc.donor_name}"
        else:
            # Refund: money flows FROM bank TO receivable (reverse direction)
            paid_from = bank_account
            paid_to = donation_account
            mode_of_payment = "Mollie Refund"
            base_title = f"REFUND {display_name} - {donation_doc.name}"
            base_remarks = f"Refund for {donation_doc.name} via Mollie - {donor_doc.donor_name}"

        # Add description if provided
        if description:
            base_remarks += f" - {description}"

        # Use refund date or today for both posting and reference dates
        transaction_date = getdate(refund_date) if refund_date else getdate()

        # Determine reversal type and original payment ID for custom fields
        reversal_type_value = None
        original_payment_id = None

        if payment_type == "Pay" and reference_suffix:
            # This is a reversal - extract type from suffix
            if "_refund_" in reference_suffix:
                reversal_type_value = "Refund"
                original_payment_id = mollie_payment_id
            elif "_chargeback_" in reference_suffix:
                reversal_type_value = "Chargeback"
                original_payment_id = mollie_payment_id

        # Create Payment Entry using unified pattern
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": payment_type,
                "posting_date": transaction_date,  # CRITICAL: Set posting date to actual transaction date
                "party_type": "Customer",
                "party": customer,
                "paid_amount": flt(amount),
                "received_amount": flt(amount),
                "reference_no": reference_no,
                "reference_date": transaction_date,
                "company": company,
                "paid_from": paid_from,
                "paid_to": paid_to,
                "mode_of_payment": mode_of_payment,
                "cost_center": cost_center,
                "title": base_title,
                "remarks": base_remarks,
                # Custom fields for reversal tracking
                "custom_reversal_type": reversal_type_value,
                "custom_original_payment_id": original_payment_id,
            }
        )

        # Insert and submit using proper webhook user permissions
        pe.insert()
        pe.submit()

        frappe.logger().info(f"✅ Created {payment_type} Payment Entry: {pe.name}")
        return pe

    except Exception as e:
        frappe.logger().error(f"❌ Failed to create {payment_type} Payment Entry: {str(e)}")
        frappe.log_error(
            f"Unified Payment Entry creation failed for {donation_doc.name}: {str(e)}",
            "Unified Payment Entry Creation",
        )
        return None


def create_refund_payment_entry(
    donation_doc,
    mollie_payment_id: str,
    refund_id: str,
    refund_amount: float,
    refund_date: Optional[str] = None,
) -> Optional[Any]:
    """
    Create a refund Payment Entry using unified logic.

    This is a convenience wrapper around create_unified_payment_entry
    specifically for refunds.
    """
    return create_unified_payment_entry(
        donation_doc=donation_doc,
        mollie_payment_id=mollie_payment_id,
        amount=refund_amount,
        payment_type="Pay",
        reference_suffix=f"_refund_{refund_id}",
        refund_date=refund_date,
        description=f"Refund {refund_id} of €{refund_amount:.2f}",
    )
