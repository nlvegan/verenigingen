#!/usr/bin/env python3
"""
Payment History Validator - Scheduled Task for Data Integrity

This module provides scheduled validation and repair of payment history entries
to ensure invoices generated through bulk operations are properly synced.

Key Features:
- Detects invoices missing from payment history
- Automatically repairs missing entries using atomic operations
- Provides detailed logging and reporting
- Designed to catch edge cases where bulk payment history updates fail
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, now_datetime, today


@frappe.whitelist()
def validate_and_repair_payment_history():
    """
    Scheduled validation and repair of payment history entries.

    This function:
    1. Checks for recent invoices missing from payment history
    2. Automatically repairs missing entries
    3. Logs detailed information for monitoring
    4. Returns summary statistics

    Designed to run every few hours as a safety net for the bulk processing system.
    """

    try:
        # Check invoices from the last 7 days to catch any missed entries
        cutoff_date = add_days(today(), -7)

        # Get all submitted invoices that should be in payment history
        recent_invoices = frappe.db.sql(
            """
            SELECT
                si.name as invoice_name,
                si.customer,
                si.posting_date,
                si.grand_total,
                si.outstanding_amount,
                si.status,
                si.creation,
                si.modified,
                m.name as member_name,
                m.full_name as member_full_name
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.customer = m.customer
            WHERE si.creation >= %s
            AND si.docstatus = 1
            AND m.name IS NOT NULL
            ORDER BY si.creation DESC
        """,
            (cutoff_date,),
            as_dict=True,
        )

        frappe.logger("payment_history_validator").info(
            f"Validating payment history for {len(recent_invoices)} recent invoices"
        )

        # Check which invoices are missing from payment history
        missing_invoices = []
        validated_count = 0

        for invoice_data in recent_invoices:
            # Check if this invoice exists in the member's payment history
            existing = frappe.db.get_value(
                "Member Payment History",
                {"parent": invoice_data.member_name, "invoice": invoice_data.invoice_name},
                "name",
            )

            if not existing:
                missing_invoices.append(invoice_data)
            else:
                validated_count += 1

        # Log summary statistics
        frappe.logger("payment_history_validator").info(
            f"Payment history validation: {validated_count} verified, {len(missing_invoices)} missing"
        )

        # Repair missing entries
        success_count = 0
        error_count = 0

        for invoice_data in missing_invoices:
            try:
                # Get the member document
                member_doc = frappe.get_doc("Member", invoice_data.member_name)

                # Use the atomic add method to prevent conflicts
                member_doc.add_invoice_to_payment_history(invoice_data.invoice_name)

                success_count += 1
                frappe.logger("payment_history_validator").info(
                    f"Repaired payment history: Added {invoice_data.invoice_name} for {invoice_data.member_full_name}"
                )

            except Exception as e:
                error_count += 1
                frappe.logger("payment_history_validator").error(
                    f"Failed to repair payment history for {invoice_data.invoice_name} (member: {invoice_data.member_full_name}): {e}"
                )
                frappe.log_error(
                    f"Payment history repair failed for invoice {invoice_data.invoice_name}, member {invoice_data.member_name}: {str(e)}",
                    "Payment History Validator Error",
                )

        # Commit successful repairs
        if success_count > 0:
            frappe.db.commit()
            frappe.logger("payment_history_validator").info(
                f"Payment history validation complete: {success_count} repairs committed"
            )

        # Create alert if significant issues found
        if len(missing_invoices) > 10:  # Alert threshold
            _create_payment_history_alert(len(missing_invoices), success_count, error_count)

        return {
            "success": True,
            "total_invoices": len(recent_invoices),
            "validated": validated_count,
            "missing_found": len(missing_invoices),
            "repaired": success_count,
            "errors": error_count,
            "timestamp": now_datetime(),
        }

    except Exception as e:
        frappe.logger("payment_history_validator").error(f"Payment history validation failed: {e}")
        frappe.log_error(str(e), "Payment History Validator Critical Error")
        return {"success": False, "error": str(e), "timestamp": now_datetime()}


def _create_payment_history_alert(missing_count, repaired_count, error_count):
    """
    Create an alert when significant payment history issues are detected.

    This helps administrators monitor the health of the payment history system.
    """
    try:
        # Check if we have an alert system in place
        if frappe.db.exists("DocType", "System Alert"):
            alert_doc = frappe.new_doc("System Alert")
            alert_doc.alert_type = "Warning"
            alert_doc.subject = f"Payment History Sync Issues Detected ({missing_count} missing entries)"
            alert_doc.message = f"""
Payment History Validator found {missing_count} missing entries during scheduled validation.

Repair Results:
- Successfully repaired: {repaired_count}
- Repair errors: {error_count}
- Remaining issues: {missing_count - repaired_count}

This may indicate issues with the bulk invoice generation payment history updates.
Please review the Payment History Validator logs for details.
            """.strip()

            alert_doc.insert()
            frappe.db.commit()

    except Exception as e:
        frappe.logger("payment_history_validator").error(f"Failed to create payment history alert: {e}")


@frappe.whitelist()
def get_payment_history_validation_stats():
    """
    Get statistics about payment history validation over the past week.

    Useful for monitoring the effectiveness of the validation system.
    """
    try:
        cutoff_date = add_days(today(), -7)

        # Get total recent invoices
        total_invoices = frappe.db.count(
            "Sales Invoice", filters={"creation": (">=", cutoff_date), "docstatus": 1}
        )

        # Get invoices with member associations
        invoices_with_members = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.customer = m.customer
            WHERE si.creation >= %s
            AND si.docstatus = 1
            AND m.name IS NOT NULL
        """,
            (cutoff_date,),
        )[0][0]

        # Get payment history entries created in the same period
        payment_history_entries = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMember Payment History` mph
            LEFT JOIN `tabSales Invoice` si ON mph.invoice = si.name
            WHERE si.creation >= %s
            AND si.docstatus = 1
        """,
            (cutoff_date,),
        )[0][0]

        return {
            "success": True,
            "period_days": 7,
            "total_invoices": total_invoices,
            "invoices_with_members": invoices_with_members,
            "payment_history_entries": payment_history_entries,
            "sync_rate": round((payment_history_entries / max(invoices_with_members, 1)) * 100, 2),
            "timestamp": now_datetime(),
        }

    except Exception as e:
        frappe.logger("payment_history_validator").error(f"Failed to get validation stats: {e}")
        return {"success": False, "error": str(e), "timestamp": now_datetime()}


def validate_payment_history_integrity():
    """
    Scheduled task wrapper for payment history validation.

    This is the function that should be called by the scheduler.
    It includes additional error handling and logging for scheduled execution.
    """
    try:
        frappe.logger("payment_history_validator").info("Starting scheduled payment history validation")

        result = validate_and_repair_payment_history()

        if result["success"]:
            frappe.logger("payment_history_validator").info(
                f"Scheduled validation complete: {result['repaired']} repairs, {result['errors']} errors"
            )
        else:
            frappe.logger("payment_history_validator").error(
                f"Scheduled validation failed: {result.get('error', 'Unknown error')}"
            )

    except Exception as e:
        frappe.logger("payment_history_validator").error(f"Scheduled payment history validation crashed: {e}")
        frappe.log_error(str(e), "Payment History Validator Scheduler Error")
