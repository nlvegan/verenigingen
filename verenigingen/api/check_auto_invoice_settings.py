#!/usr/bin/env python3

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def get_auto_invoice_settings():
    """Check current auto-invoice settings"""
    settings = frappe.get_single("Verenigingen Settings")

    return {
        "automate_donation_payment_entries": getattr(settings, "automate_donation_payment_entries", False),
        "auto_submit_membership_invoices": getattr(settings, "auto_submit_membership_invoices", True),
        "settings_doc_name": settings.name,
        "descriptions": {
            "automate_donation_payment_entries": "Skip automatic Payment Entry creation for Donations when marked as paid",
            "auto_submit_membership_invoices": "Automatically submit membership invoices when created (uncheck to keep as drafts)",
        },
    }
