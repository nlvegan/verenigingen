#!/usr/bin/env python3

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def get_auto_invoice_settings() -> OperationResult[Dict[str, Any]]:
    """Check current auto-invoice settings"""
    try:
        settings = frappe.get_single("Verenigingen Settings")

        data = {
            "automate_donation_payment_entries": getattr(
                settings, "automate_donation_payment_entries", False
            ),
            "auto_submit_membership_invoices": getattr(settings, "auto_submit_membership_invoices", True),
            "settings_doc_name": settings.name,
            "descriptions": {
                "automate_donation_payment_entries": _(
                    "Skip automatic Payment Entry creation for Donations when marked as paid"
                ),
                "auto_submit_membership_invoices": _(
                    "Automatically submit membership invoices when created (uncheck to keep as drafts)"
                ),
            },
        }

        return OperationResult.ok(data, message=_("Auto-invoice settings retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Auto Invoice Settings Check Failed"),
            message=traceback.format_exc(),
        )
        return OperationResult.fail(
            _("Failed to retrieve auto-invoice settings"),
            errors=[str(e)],
            context={"traceback": traceback.format_exc()},
        )
