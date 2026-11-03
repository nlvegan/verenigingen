"""Record staff alerts, and whether each one reached anyone (#1979 phase 1).

Write-ahead: ``begin_event`` inserts a ``Pending`` Staff Alert Event BEFORE delivery, the Notification
Log rows carry its name in ``source_name``, and ``finish_event`` classifies the result afterwards. The
table is MyISAM, so the row outlives a caller that rolls back or dies, and a row still ``Pending`` is
itself the evidence that the send raised or the process was killed.

Nothing here may break or change an alert: every public function swallows its own failure (logged
with ``frappe.log_error``) and returns ``None``.

"Reached" (ruling 6) means a Notification Log row joined exactly on ``source_name``, for a user who
is an enabled User and is not Administrator and is not listed in Verenigingen Email Configuration
``staff_alert_uncounted_users`` (ruling 7: who counts as "someone" is configurable).
"""

import hashlib
import re

import frappe
from frappe.utils import now_datetime

DOCTYPE = "Staff Alert Event"
CONFIG_DOCTYPE = "Verenigingen Email Configuration"
ALWAYS_UNCOUNTED = ("administrator",)


def begin_event(
    notification_key, subject, source, reference_doctype=None, reference_name=None, requires_action=None
):
    """Insert (or re-open) the ``Pending`` event for this alert. Returns its name, or None on failure."""
    try:
        key = notification_key or "(none)"
        dedupe_key = _dedupe_key(key, reference_doctype, reference_name)
        if requires_action is None:
            from verenigingen.notification_registry import REQUIRES_ACTION_KEYS

            requires_action = key in REQUIRES_ACTION_KEYS
        now = now_datetime()
        try:
            frappe.get_doc(
                {
                    "doctype": DOCTYPE,
                    "dedupe_key": dedupe_key,
                    "notification_key": key,
                    "source": source,
                    "subject": (subject or "")[:255],
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "requires_action": 1 if requires_action else 0,
                    "action_status": "Open" if requires_action else "",
                    "outcome": "Pending",
                    "attempts": 1,
                    "raised_at": now,
                    "last_attempt_at": now,
                }
            ).insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            _reattempt(dedupe_key, subject, now)
        return dedupe_key
    except Exception:
        _log_recorder_failure("begin")
        return None


def finish_event(event, result=None, error=None):
    """Classify the delivery outcome onto ``event``. ``error`` is an exception the send raised."""
    if not event:
        return
    try:
        reached = count_reached(event)
        outcome, detail = _outcome_for(result, error, reached)
        values = {
            "outcome": outcome,
            "recipient_count": reached,
            "detail": detail,
            "last_attempt_at": now_datetime(),
        }
        if outcome == "Delivered" and not frappe.db.get_value(DOCTYPE, event, "delivered_at"):
            values["delivered_at"] = now_datetime()
        frappe.db.set_value(DOCTYPE, event, values, update_modified=False)
    except Exception:
        _log_recorder_failure("finish")


def count_reached(event):
    """Distinct counted users with a Notification Log for ``event`` (exact ``source_name`` join)."""
    users = frappe.get_all(
        "Notification Log",
        filters={"source_doctype": DOCTYPE, "source_name": event},
        pluck="for_user",
    )
    if not users:
        return 0
    uncounted = _uncounted_users()
    reached = set()
    for row in frappe.get_all(
        "User", filters={"name": ["in", list(set(users))], "enabled": 1}, fields=["name", "email"]
    ):
        if row.name.lower() in uncounted or (row.email or "").lower() in uncounted:
            continue
        reached.add(row.name)
    return len(reached)


def _outcome_for(result, error, reached):
    """Return ``(outcome, detail)``. Reached users win: the record says whether the alert got to anyone."""
    if reached:
        return "Delivered", (f"Last attempt raised: {error}" if error else "")[:1000]
    if error is not None:
        return "Failed", f"{type(error).__name__}: {error}"[:1000]
    result = result or {}
    code = result.get("reason_code")
    if result.get("skipped"):
        return _skip_outcome(code, result)
    if code in ("no_recipients", "no_valid_recipients"):
        return "No recipient", str(result.get("error") or "")
    if result.get("notifications_created"):
        return "No counted recipient", (
            "Notification Logs were created, but only for Administrator, a user configured as not counting, "
            "or a user who is not enabled."
        )
    return "Failed", str(result.get("errors") or result.get("error") or "no notification was created")[:1000]


def _skip_outcome(code, result):
    detail = str(result.get("reason") or "")
    if code == "email_disabled":
        return "Skipped - email off", detail
    key = result.get("notification_key")
    from verenigingen.notification_registry import NOTIFICATION_KEYS

    if key and key not in NOTIFICATION_KEYS:
        return "Skipped - key not in registry", detail
    if key and not _has_config_row(key):
        return "Skipped - key not seeded", detail
    return "Skipped - key disabled", detail


def _has_config_row(key):
    from verenigingen.services.communication.email_configuration_service import (
        get_email_configuration_service,
    )

    return bool(get_email_configuration_service().get_notification_config(key))


def _dedupe_key(key, reference_doctype, reference_name):
    """Same problem, same name. An alert with no reference identifies nothing, so each is its own event."""
    if reference_doctype and reference_name:
        return hashlib.sha1(f"{key}|{reference_doctype}|{reference_name}".encode()).hexdigest()
    return frappe.generate_hash(length=40)


def _reattempt(dedupe_key, subject, now):
    """A second attempt for the same problem. Atomic: no read-modify-write of ``attempts``."""
    table = frappe.qb.DocType(DOCTYPE)
    (
        frappe.qb.update(table)
        .set(table.attempts, table.attempts + 1)
        .set(table.outcome, "Pending")
        .set(table.last_attempt_at, now)
        .set(table.subject, (subject or "")[:255])
        .where(table.name == dedupe_key)
    ).run()
    # A problem that came back after someone marked it done is open again.
    (
        frappe.qb.update(table)
        .set(table.action_status, "Open")
        .where((table.name == dedupe_key) & (table.action_status == "Done"))
    ).run()


def _uncounted_users():
    names = set(ALWAYS_UNCOUNTED)
    try:
        configured = frappe.db.get_single_value(CONFIG_DOCTYPE, "staff_alert_uncounted_users")
    except Exception:
        configured = None  # column not migrated yet: only the built-in exclusion applies
    for item in re.split(r"[,;\n]+", configured or ""):
        if item.strip():
            names.add(item.strip().lower())
    return names


def _log_recorder_failure(stage):
    frappe.log_error(
        title=f"Staff Alert Event could not be recorded ({stage})", message=frappe.get_traceback()
    )
