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

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
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

        # Single batched query: every in-window submitted, member-linked invoice,
        # LEFT JOINed against Member Payment History so "missing from payment
        # history" is a plain NULL check -- no per-invoice get_value/get_doc calls.
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
                m.full_name as member_full_name,
                mph.name as history_row
            FROM `tabSales Invoice` si
            LEFT JOIN `tabMember` m ON si.customer = m.customer
            LEFT JOIN `tabMember Payment History` mph
                ON mph.parenttype = 'Member'
                AND mph.parent = m.name
                AND mph.invoice = si.name
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

        # Partition on the pre-joined NULL check -- no further queries needed.
        missing_invoices = [row for row in recent_invoices if not row.history_row]
        validated_count = len(recent_invoices) - len(missing_invoices)

        # Log summary statistics
        frappe.logger("payment_history_validator").info(
            f"Payment history validation: {validated_count} verified, {len(missing_invoices)} missing"
        )

        # Reconcile against source-of-truth: drive the real drain job once per
        # member with a gap (deduplicated by job_id), instead of the circular
        # member_doc.add_invoice_to_payment_history() re-enqueue, which merely
        # re-queues through the batch processor and always returns True without
        # verifying a row ever lands.
        members_with_gaps = {}
        for invoice_data in missing_invoices:
            members_with_gaps.setdefault(invoice_data.member_name, invoice_data.customer)

        success_count = 0
        error_count = 0

        for member_name, customer in members_with_gaps.items():
            try:
                frappe.enqueue(
                    "verenigingen.utils.background_jobs.drain_member_payment_history",
                    queue="short",
                    job_id=f"fin_history_payment_{member_name}",
                    deduplicate=True,
                    member=member_name,
                    customer=customer,
                )

                success_count += 1
                frappe.logger("payment_history_validator").info(
                    f"Queued payment history drain for member {member_name}"
                )

            except Exception as e:
                error_count += 1
                frappe.logger("payment_history_validator").error(
                    f"Failed to queue payment history drain for member {member_name}: {e}"
                )
                frappe.log_error(
                    f"Payment history repair failed for member {member_name}: {str(e)}",
                    "Payment History Validator Error",
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
            # System Alert has no "subject" field -- only alert_type + message. Put the
            # summary line at the top of message so it is actually persisted and
            # searchable (previously written to a non-existent subject -> dropped).
            alert_doc.message = f"""
Payment History Sync Issues Detected ({missing_count} missing entries)

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
@high_security_api(operation_type=OperationType.REPORTING)
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

        # Get member-linked invoices that have at least one payment history entry
        # in the same period. We count DISTINCT invoices (not raw payment history
        # rows) and require the invoice's customer to map to a Member, so this
        # value is directly comparable to invoices_with_members and the resulting
        # sync_rate can never exceed 100%.
        payment_history_entries = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT si.name) as count
            FROM `tabMember Payment History` mph
            INNER JOIN `tabSales Invoice` si ON mph.invoice = si.name
            INNER JOIN `tabMember` m ON si.customer = m.customer
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
