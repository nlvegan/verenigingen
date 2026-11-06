"""The staff alert for a /word-lid door that can offer no payment plan (#2127 ruling).

The page keeps its "cannot be used right now" message and a disabled submit; staff are also told, once
a day per door and reason while the problem lasts, so a misconfigured door is not found by an applicant.

Two things are deliberate here. A Guest GET is rolled back by the framework unless the request asks to
commit, so the alert asks (``frappe.local.flags.commit``) and delivers in the request: a queued job would
need a worker, which a fresh install and CI do not run. And the once-a-day claim lives in Redis (SETNX with
an expiry), not in the key's per-recipient cooldown, which is per key and would swallow a SECOND door's
alert in the same window.
"""

import hashlib

import frappe
from frappe.utils import escape_html

from verenigingen.utils.notification_helpers import notify_administrators

NOTIFICATION_KEY = "door_unavailable"
REALERT_SECONDS = 24 * 3600
NO_PLANS = "the door has no payment plan"


def alert_if_door_unusable(door, plans, problems):
    """Alert staff when a Regular door offers nothing. ``problems`` is why each plan was left out."""
    if plans or door.form_shape != "Regular":
        return
    reason = "; ".join(problems) or NO_PLANS
    claim = _claim(door.name, reason)
    if not claim:
        return
    frappe.local.flags.commit = True  # a Guest GET is otherwise rolled back, taking the alert with it
    try:
        result = notify_administrators(
            subject=f"Application form {door.title or door.name} cannot be used right now",
            message=_alert_message(door, reason),
            notification_key=NOTIFICATION_KEY,  # literal: key discovery greps for it
            document_type=door.doctype,
            document_name=door.name,
            # ruling 2026-11-01: staff alerts never go to Administrator (the delivery layer also excludes it)
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    except Exception:
        frappe.cache.delete(claim)  # so the next visit tries again
        frappe.log_error(title="Door unavailable alert failed", message=frappe.get_traceback())
        return
    if not _was_delivered(result):
        frappe.cache.delete(claim)  # dropped (key off, nobody to tell): do not hold the alert back for a day


def _was_delivered(result) -> bool:
    """notify_administrators returns success False for no recipient, skipped True for a disabled key or
    email, and notifications_created 0 when nothing was written."""
    result = result or {}
    return (
        bool(result.get("success"))
        and not result.get("skipped")
        and bool(result.get("notifications_created"))
    )


def _claim(door_name, reason):
    """The Redis key if this call is the first for (door, reason) within a day, else None."""
    digest = hashlib.sha256(reason.encode()).hexdigest()[:16]
    key = frappe.cache.make_key(f"{NOTIFICATION_KEY}:{door_name}:{digest}")
    try:
        return key if frappe.cache.set(key, "1", ex=REALERT_SECONDS, nx=True) else None
    except Exception:  # swallow-ok: best-effort; the page must render, and the failure is in the Error Log
        frappe.log_error(title="Door unavailable alert not deduplicated", message=frappe.get_traceback())
        return None


def _alert_message(door, reason):
    return (
        f"<p>The application form <b>{escape_html(door.title or door.name)}</b> "
        f"(/word-lid/{escape_html(door.slug)}) cannot be used right now: it offers applicants no payment plan.</p>"
        f"<p>Membership type: {escape_html(door.membership_type)}</p>"
        f"<p>Reason: {escape_html(reason)}</p>"
        "<p>Action required: fix the door's payment plans or the dues templates they use. "
        "This alert repeats at most once a day while the problem lasts.</p>"
    )
