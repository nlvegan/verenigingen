# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Payment Entry Service

The single creator of ERPNext Payment Entries for Ponto Payment Links.

Called by the webhook handler when a payment link reaches Executed, and by the
Ponto Payment Link controller when a payment is processed from the desk.

Usage:
    from verenigingen.verenigingen_payments.ponto.services.payment_entry_service import (
        create_ponto_payment_entry,
    )

    pe_name = create_ponto_payment_entry(payment_link_doc, invoice_name)
"""

from typing import Optional

import frappe


def create_ponto_payment_entry(payment_link_doc, invoice_name: str) -> Optional[str]:
    """
    Create a Payment Entry for a Ponto payment.

    Args:
        payment_link_doc: Ponto Payment Link document
        invoice_name: Sales Invoice to allocate payment to

    Returns:
        Payment Entry name if created, None otherwise
    """
    from frappe.utils import flt, getdate, today

    try:
        # Get invoice document
        invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)

        # A draft (docstatus 0) does NOT carry outstanding_amount == 0 - it carries its
        # full grand_total (calculate_outstanding_amount runs on every save that is not
        # cancelled). So this must be checked BEFORE the outstanding_amount <= 0 "already
        # paid" branch below, or a draft falls through as a normal unpaid invoice and is
        # handed to the allocator, which ERPNext then refuses at Payment Entry submit
        # time ("... must be submitted", payment_entry.py:725-727). #856/#209.
        if invoice_doc.docstatus != 1:
            frappe.logger().warning(
                f"Sales Invoice {invoice_name} is not submitted (docstatus: "
                f"{invoice_doc.docstatus}) - refusing to allocate a payment, needs manual review"
            )
            return None

        if invoice_doc.outstanding_amount <= 0:
            frappe.logger().info(
                f"Sales Invoice {invoice_name} already paid (outstanding: {invoice_doc.outstanding_amount})"
            )
            return None

        # Get settings
        settings = frappe.get_single("Verenigingen Settings")
        company = invoice_doc.company or settings.company

        # Get Ponto bank account from settings. ponto_bank_account_parent lives
        # on Verenigingen Payments Settings.
        from verenigingen.utils.settings_utils import get_payments_settings

        ponto_bank_account = getattr(get_payments_settings(), "ponto_bank_account_parent", None)
        # The setting is labelled "Ponto Bank Account Parent Group" and is described as
        # the group under which Ponto accounts are created, so it is a GROUP account.
        # Nothing on the way in rejects one: get_default_bank_cash_account()
        # (erpnext journal_entry.py) skips its default-resolution block entirely when
        # handed an explicit `account` and no mode_of_payment - which is this path, since
        # get_bank_cash_account passes the SALES INVOICE's mode_of_payment, not the
        # Payment Entry's - and returns that account's currency and type without ever
        # checking is_group, company or account_type. It then becomes paid_to. The group
        # is not refused until GLEntry.validate ("Account ... is a group account") -
        # i.e. inside on_submit, after the Payment Entry row already exists. Fall
        # through to the non-group lookups below instead.
        if ponto_bank_account and frappe.get_cached_value("Account", ponto_bank_account, "is_group"):
            frappe.logger().warning(
                f"ponto_bank_account_parent ({ponto_bank_account}) is a group account and "
                "cannot receive a payment; falling back to a concrete Ponto account"
            )
            ponto_bank_account = None
        if not ponto_bank_account:
            # Try to find a Ponto account
            ponto_bank_account = frappe.db.get_value(
                "Account",
                {"company": company, "account_name": ["like", "%Ponto%"], "is_group": 0},
                "name",
            )
        if not ponto_bank_account:
            ponto_bank_account = frappe.get_cached_value("Company", company, "default_bank_account")

        if not ponto_bank_account:
            frappe.logger().error(f"No Ponto bank account configured for company {company}")
            return None

        # Calculate allocation amount. Capped at what the invoice still owes: ERPNext
        # rejects a reference allocating more than the outstanding amount.
        amount = flt(payment_link_doc.amount)
        allocation_amount = min(amount, flt(invoice_doc.outstanding_amount))

        # Delegate to PaymentEntryCreationService so this path shares one payment-entry
        # contract with the rest of the app. The service sets custom_remarks alongside
        # the remarks text, without which Payment Entry.validate() regenerates the field
        # and the payment-link reference below never reaches the saved document.
        from decimal import Decimal

        from verenigingen.verenigingen_payments.services.payment import payment_entry_service

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice_name,
            amount=Decimal(str(allocation_amount)),
            posting_date=getdate(today()),
            reference_no=payment_link_doc.ponto_request_id or payment_link_doc.name,
            reference_date=getdate(today()),
            mode_of_payment="Bank Transfer",
            bank_account=ponto_bank_account,
            remarks=(
                f"Ponto payment via payment link {payment_link_doc.name}. "
                f"Description: {payment_link_doc.description or 'N/A'}"
            ),
            custom_fields=({"custom_member": payment_link_doc.member} if payment_link_doc.member else None),
        )

        frappe.logger().info(
            f"Created Payment Entry {payment_entry.name} for Ponto Payment Link {payment_link_doc.name} "
            f"(amount: {allocation_amount}, invoice: {invoice_name})"
        )

        return payment_entry.name

    except Exception as e:
        frappe.logger().error(f"Failed to create Payment Entry for {payment_link_doc.name}: {e}")
        frappe.log_error(
            title=f"Ponto Payment Entry creation failed: {payment_link_doc.name}",
            message=str(e),
        )
        return None
