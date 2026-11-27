# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Dunning on a failed SEPA collection (#3347).

A bank return on a dues collection moves the member's Membership Dues Schedule through
the dunning states that ``DuesScheduleLifecycleService.ALLOWED_TRANSITIONS`` declares:

* 1st failure: Grace Period, ``grace_period_until`` = today + ``default_grace_period_days``
  (30 when empty).
* 3rd consecutive failure: Suspended when ``Verenigingen Settings.grace_period_auto_apply``
  is on, otherwise the Grace Period is extended.

``consecutive_failures`` goes back to 0 (and a Grace Period schedule back to Active) only
once a collection has gone ``SEPA_RETURN_WINDOW_DAYS`` without being returned, by the daily
``reset_failures_after_clean_window`` sweep. It is NOT reset when a Payment Entry is booked:
the Payment Entry exists before the bank can return the debit, so every retry cycle would
reset the counter and the 3rd failure could never be reached (maintainer ruling, #3347).
"""

from typing import Optional

import frappe
from frappe.utils import add_days, cint, getdate, now_datetime, today

from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint

# How long a collection must survive without a return before it counts as successful.
# SEPA Core R-transactions for the technical reasons this app maps (AC01/AC04/AC06, AM04,
# MS03, MD01/MD02, ...) reach the creditor within 5 TARGET2 business days of the settlement
# date (about 7 calendar days over a weekend). Staff import the bank's return file by hand,
# so a few more days are allowed for it to be processed. 14 days is therefore the shortest
# window that still lets a return land before the collection is called successful. Refund
# claims (MD06, 8 weeks) and unauthorised-debit claims (13 months) arrive later and simply
# count as a new failure; they do not wait for the window.
SEPA_RETURN_WINDOW_DAYS = 14

SUSPEND_AFTER_FAILURES = 3
DEFAULT_GRACE_PERIOD_DAYS = 30

# Return reason codes (ISO 20022 / SEPA, ``SEPA_RETURN_REASON_CODES``) that are the DEBTOR's
# fault and therefore dun (maintainer ruling, #3347 part 4). Every other code (bank,
# creditor, mandate and technical reasons) is logged and never dunned; a code that cannot
# be classified confidently stays out of this set. Classification of all 35 codes is in the
# PR body.
DEBTOR_FAULT_RETURN_CODES = frozenset({"AC04", "AC06", "AM04", "MS02", "MS03"})

COUNTED = "counted"
DUPLICATE = "duplicate"
IGNORED = "ignored"
FAILED = "failed"

_DUNNING_STATES = ("Active", "Grace Period", "Suspended")


def record_failed_collection(
    invoice_name: str, return_key: str, reason: str = "", reason_code: str = ""
) -> str:
    """Count one failed SEPA collection of ``invoice_name`` against its dues schedule.

    ``return_key`` identifies THIS return (the cancelled Payment Entry, or the return file
    hash plus invoice) and is stored on the schedule: the same key is never counted twice.
    Only a debtor-fault ``reason_code`` counts; anything else is logged and ignored.

    Returns COUNTED, DUPLICATE, IGNORED (no schedule, not a debtor-fault code, or a schedule
    status dunning cannot leave) or FAILED. A failure to write the schedule is logged and
    rolled back to its own savepoint, and reported as FAILED so the caller can tell staff:
    the reversal that called this is already done and must not become an "error" result.
    """
    schedule_name = frappe.db.get_value("Sales Invoice", invoice_name, "membership_dues_schedule_display")
    if not schedule_name:
        return IGNORED
    if (reason_code or "").strip().upper() not in DEBTOR_FAULT_RETURN_CODES:
        frappe.log_error(
            title="SEPA Return Not Dunned",
            message=(
                f"Return {return_key} of invoice {invoice_name} carries reason code "
                f"'{reason_code or 'none'}' ({reason or 'no description'}), which is not a "
                f"debtor-fault code; dues schedule {schedule_name} was not dunned."
            ),
        )
        return IGNORED

    savepoint = "sepa_return_dunning"
    frappe.db.savepoint(savepoint)
    try:
        outcome = _count_failure(schedule_name, return_key, reason)
        frappe.db.release_savepoint(savepoint)
        return outcome
    except NON_RESUMABLE_DB_ERRORS:
        raise
    # The reversal is already done; the cause goes to the Error Log.
    except Exception:  # swallow-ok: best-effort
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title="SEPA Return Dunning Failed",
            message=(
                f"Could not record the failed SEPA collection of invoice {invoice_name} "
                f"(return {return_key}) on dues schedule {schedule_name}.\n\n{frappe.get_traceback()}"
            ),
        )
        return FAILED


def _count_failure(schedule_name: str, return_key: str, reason: str) -> str:
    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name, for_update=True)
    if any(row.return_key == return_key for row in schedule.counted_returns):
        return DUPLICATE
    if schedule.status not in _DUNNING_STATES:
        # Paused, Cancelled, Payment Plan Active ...: dunning has no transition from there.
        return IGNORED

    schedule.consecutive_failures = cint(schedule.consecutive_failures) + 1
    schedule.last_failure_on = now_datetime()
    schedule.append("counted_returns", {"return_key": return_key, "counted_on": schedule.last_failure_on})
    _apply_dunning_status(schedule)
    schedule.save()
    schedule.add_comment(
        "Info",
        f"SEPA return {return_key} counted: failure #{schedule.consecutive_failures}"
        + (f" ({reason})" if reason else ""),
    )
    return COUNTED


def _apply_dunning_status(schedule) -> None:
    settings = frappe.get_single("Verenigingen Settings")
    grace_days = cint(settings.default_grace_period_days) or DEFAULT_GRACE_PERIOD_DAYS

    if schedule.consecutive_failures >= SUSPEND_AFTER_FAILURES and settings.grace_period_auto_apply:
        _set_status(schedule, "Suspended")
        schedule.grace_period_until = None
    elif schedule.status != "Suspended":
        _set_status(schedule, "Grace Period")
        schedule.grace_period_until = add_days(today(), grace_days)


def _set_status(schedule, new_status: str) -> None:
    """Change status only along ``ALLOWED_TRANSITIONS`` (save() re-validates it as well)."""
    from verenigingen.services.billing.dues_schedule_lifecycle_service import (
        DuesScheduleLifecycleService,
    )

    if schedule.status == new_status:
        return
    allowed = DuesScheduleLifecycleService.ALLOWED_TRANSITIONS.get(schedule.status, [])
    if new_status not in allowed:
        frappe.throw(f"Dues schedule {schedule.name}: {schedule.status} -> {new_status} is not allowed")
    schedule.status = new_status


def reset_failures_after_clean_window() -> int:
    """Daily sweep: reset the counter of schedules with a collection that was never returned.

    A schedule qualifies when a submitted SEPA Direct Debit Payment Entry of one of its
    invoices was booked after the schedule's latest counted failure and at least
    ``SEPA_RETURN_WINDOW_DAYS`` ago. A returned collection has its Payment Entry cancelled,
    so it never qualifies. Idempotent: a schedule at 0 failures is not selected.
    Returns the number of schedules reset.
    """
    reset = 0
    for schedule_name in frappe.get_all(
        "Membership Dues Schedule", filters={"consecutive_failures": [">", 0]}, pluck="name"
    ):
        if _has_clean_collection_since(schedule_name, _last_failure_on(schedule_name)):
            reset += _reset_schedule(schedule_name)
    return reset


def _last_failure_on(schedule_name: str):
    """``last_failure_on``; for a counter set by hand (no timestamp) fall back to ``modified``.

    Such a schedule is logged once and backfilled, so the next sweep finds a timestamp.
    """
    last_failure, modified = frappe.db.get_value(
        "Membership Dues Schedule", schedule_name, ["last_failure_on", "modified"]
    )
    if last_failure:
        return last_failure
    frappe.log_error(
        title="SEPA Return Dunning Unknown Failure Date",
        message=(
            f"Dues schedule {schedule_name} has consecutive_failures > 0 but no last_failure_on; "
            f"using its last modification ({modified}) as the failure date."
        ),
    )
    frappe.db.set_value(
        "Membership Dues Schedule", schedule_name, "last_failure_on", modified, update_modified=False
    )
    return modified


def _has_clean_collection_since(schedule_name: str, last_failure) -> bool:
    cutoff = add_days(today(), -SEPA_RETURN_WINDOW_DAYS)
    rows = frappe.db.sql(
        """
        SELECT pe.name
        FROM `tabPayment Entry` pe
        INNER JOIN `tabPayment Entry Reference` ref
            ON ref.parent = pe.name AND ref.reference_doctype = 'Sales Invoice'
        INNER JOIN `tabSales Invoice` si ON si.name = ref.reference_name
        WHERE si.membership_dues_schedule_display = %(schedule)s
            AND pe.docstatus = 1
            AND pe.mode_of_payment = 'SEPA Direct Debit'
            AND pe.creation > %(last_failure)s
            AND DATE(pe.creation) <= %(cutoff)s
        LIMIT 1
        """,
        {"schedule": schedule_name, "last_failure": last_failure, "cutoff": getdate(cutoff)},
    )
    return bool(rows)


def _reset_schedule(schedule_name: str) -> int:
    savepoint = "sepa_return_dunning_reset"
    frappe.db.savepoint(savepoint)
    try:
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name, for_update=True)
        if not cint(schedule.consecutive_failures):
            frappe.db.release_savepoint(savepoint)
            return 0
        schedule.consecutive_failures = 0
        if schedule.status == "Grace Period":
            _set_status(schedule, "Active")
            schedule.grace_period_until = None
        schedule.save()
        schedule.add_comment(
            "Info",
            f"SEPA collection went {SEPA_RETURN_WINDOW_DAYS} days without a return: failure count reset",
        )
        frappe.db.release_savepoint(savepoint)
        return 1
    except NON_RESUMABLE_DB_ERRORS:
        raise
    # One schedule must not stop the sweep; the cause goes to the Error Log.
    except Exception:  # swallow-ok: best-effort
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title="SEPA Return Dunning Reset Failed",
            message=f"Could not reset dues schedule {schedule_name}.\n\n{frappe.get_traceback()}",
        )
        return 0
