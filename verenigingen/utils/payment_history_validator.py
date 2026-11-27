#!/usr/bin/env python3
"""
Payment History Validator - Scheduled Task for Data Integrity

This module provides scheduled validation and repair of payment history entries
to ensure invoices generated through bulk operations are properly synced.

Key Features:
- Detects invoices missing from payment history
- Automatically enqueues per-member drain jobs to repair missing entries
- Provides detailed logging and reporting
- Designed to catch edge cases where bulk payment history updates fail
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, now_datetime, today

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api

# Scan window for the reconciliation (#3190). 90 days covers the longest short
# billing cycle (quarterly) plus a full cycle of grace, so a lost drain after a
# payment on a quarterly invoice is still caught on its next cycle; it was 7.
# Annual invoices outside it are not scanned: the cost is one more row per member
# per period, and no measurement here shows lost drains clustering later.
RECONCILIATION_WINDOW_DAYS = 90

# MemberFinancialHistoryManager._trim_history keeps at most this many payment
# history rows per member (get_payment_history_manager's max_entries), keeping the
# newest by posting_date (#3240). An invoice older than a full member's 30th-newest
# row is re-dropped by every drain, so it would read as "missing" every hour: a
# member already at the cap is skipped rather than repaired (#3190 review).
PAYMENT_HISTORY_MAX_ROWS = 30

# Upper bound on drain jobs enqueued per hourly run, so a wide window with many
# gaps cannot flood the short queue. The remainder is picked up by later runs
# (most recent invoices first); a drained member stops being a gap.
MAX_MEMBER_DRAINS_PER_RUN = 200


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_and_repair_payment_history():
    """
    Scheduled validation and repair of payment history entries.

    This function:
    1. Checks for recent invoices missing from payment history
    2. Enqueues a per-member drain job (deduplicated by job_id) for each member with a gap
    3. Logs detailed information for monitoring
    4. Returns summary statistics

    Designed to run every few hours as a safety net for the bulk processing system.
    """

    try:
        cutoff_date = add_days(today(), -RECONCILIATION_WINDOW_DAYS)

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
                si.docstatus,
                si.creation,
                si.modified,
                m.name as member_name,
                mph.name as history_row,
                mph.outstanding_amount as history_outstanding,
                mph.status as history_status,
                mph.payment_status as history_payment_status,
                mph.paid_amount as history_paid_amount
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

        # Partition on the pre-joined columns -- no further queries needed.
        missing_invoices = _drop_unplaceable_missing([row for row in recent_invoices if not row.history_row])
        stale_invoices = [row for row in recent_invoices if row.history_row and _is_stale_row(row)]
        gap_invoices = missing_invoices + stale_invoices
        validated_count = len(recent_invoices) - len(gap_invoices)

        # Log summary statistics
        frappe.logger("payment_history_validator").info(
            f"Payment history validation: {validated_count} verified, {len(missing_invoices)} missing, "
            f"{len(stale_invoices)} stale"
        )

        # Reconcile against source-of-truth: drive the real drain job once per
        # member with a gap (deduplicated by job_id), instead of the circular
        # member_doc.add_invoice_to_payment_history() re-enqueue, which merely
        # re-queues through the batch processor and always returns True without
        # verifying a row ever lands.
        members_with_gaps = {}
        for invoice_data in sorted(gap_invoices, key=lambda r: r.creation, reverse=True):
            members_with_gaps.setdefault(invoice_data.member_name, invoice_data.customer)

        deferred_members = max(len(members_with_gaps) - MAX_MEMBER_DRAINS_PER_RUN, 0)
        members_with_gaps = dict(list(members_with_gaps.items())[:MAX_MEMBER_DRAINS_PER_RUN])

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
        if len(gap_invoices) > 10:  # Alert threshold
            _create_payment_history_alert(len(gap_invoices), success_count, error_count)

        return {
            "success": True,
            "total_invoices": len(recent_invoices),
            "validated": validated_count,
            "missing_found": len(missing_invoices),
            "stale_found": len(stale_invoices),
            "deferred_members": deferred_members,
            "repaired": success_count,
            "errors": error_count,
            "timestamp": now_datetime(),
        }

    except Exception as e:
        frappe.logger("payment_history_validator").error(f"Payment history validation failed: {e}")
        frappe.log_error(str(e), "Payment History Validator Critical Error")
        return {"success": False, "error": str(e), "timestamp": now_datetime()}


def _drop_unplaceable_missing(missing_rows):
    """Drop 'missing' invoices of members already at the history row cap.

    A member at PAYMENT_HISTORY_MAX_ROWS rows has had older rows trimmed away on
    purpose; draining again only re-trims, so the invoice would be re-reported
    every hour. One grouped query over the members concerned.
    """
    members = sorted({row.member_name for row in missing_rows})
    if not members:
        return missing_rows
    at_cap = {
        r[0]
        for r in frappe.db.sql(
            """
            SELECT parent FROM `tabMember Payment History`
            WHERE parenttype = 'Member' AND parent IN %s
            GROUP BY parent HAVING COUNT(*) >= %s
            """,
            (members, PAYMENT_HISTORY_MAX_ROWS),
        )
    }
    return [row for row in missing_rows if row.member_name not in at_cap]


def _is_stale_row(row):
    """True when an existing history row disagrees with its Sales Invoice (#3190).

    Compares outstanding amount, invoice status and the derived payment status.
    The payment status is derived exactly as the row writer derives it (same
    util, the row's own paid_amount), so an up-to-date row never compares stale.
    """
    from frappe.utils import flt

    from verenigingen.utils import determine_payment_status

    if flt(row.history_outstanding) != flt(row.outstanding_amount):
        return True
    # A row written by the last-resort `_minimal_entry` fallback carries no status at
    # all; comparing it would flag that row stale on every run, forever.
    if row.history_status and row.history_status != (row.status or ""):
        return True
    invoice_shim = frappe._dict(
        docstatus=row.docstatus,
        status=row.status,
        outstanding_amount=flt(row.outstanding_amount),
        grand_total=flt(row.grand_total),
    )
    expected = determine_payment_status(invoice_shim, flt(row.history_paid_amount))
    return (row.history_payment_status or "") != expected


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
