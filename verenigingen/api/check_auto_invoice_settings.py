#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def get_auto_invoice_settings():
    """Check current auto-invoice settings"""
    settings = frappe.get_single("Verenigingen Settings")

    return {
        "automate_donation_payment_entries": getattr(settings, "automate_donation_payment_entries", False),
        "auto_submit_membership_invoices": getattr(settings, "auto_submit_membership_invoices", False),
        "settings_doc_name": settings.name,
        "descriptions": {
            "automate_donation_payment_entries": "Skip automatic Payment Entry creation for Donations when marked as paid",
            "auto_submit_membership_invoices": "Automatically submit membership invoices when created",
        },
    }
