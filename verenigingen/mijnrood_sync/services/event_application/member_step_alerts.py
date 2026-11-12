"""Staff alerts for MijnRood sync PER-MEMBER step failures (#2309, part 2).

A step that fails for one member (address, Mollie, membership, dues schedule, volunteer, role, board seat,
team seat, account creation) is reported only as a message string in an event that is still marked Applied,
and MijnRood does not resend. Two registered keys carry it: ``mijnrood_sync_step_failed`` (admin pair) and
``mijnrood_sync_money_step_failed`` (admin pair plus Verenigingen Financial Manager, set by the registry's
``recipient_roles``) for the steps that touch money: Mollie, membership and dues.

Deduplicated once per 24h per MEMBER + STEP + REASON (the same member failing the same step the same way
on the next event stays quiet). Account creation is folded in here because the Account Creation Request
pipeline only writes an Error Log row on failure (``mark_failed``, #2066): it never alerts staff.
"No Volunteer record" cascades are deliberately NOT alerted (maintainer ruling, #2309): where the mapping has
``create_volunteer`` the cascade follows a volunteer-creation failure that is alerted. That does NOT hold for a
board add on a mapping WITHOUT ``create_volunteer`` (the settings validator requires it for team and role but
not for the board): that member is never seated, on every event, and nothing alerts it (filed separately).

Queueing, the claim and the after-commit timing belong to the orchestrator (``queue_alert`` /
``flush_pending_alerts``, #2199). Both notify_administrators calls keep a literal ``notification_key``
because the key census greps for it.
"""

import hashlib

import frappe
from frappe.utils import escape_html

from verenigingen.mijnrood_sync.services.event_application.config_fault_alerts import _delivered

STEP_FAILED_KEY = "mijnrood_sync_step_failed"
MONEY_STEP_FAILED_KEY = "mijnrood_sync_money_step_failed"

MONEY_STEPS = {
    "mollie": "Mollie sync",
    "membership": "membership creation",
    "dues_backfill": "dues schedule backfill",
    "dues_update": "dues schedule rate update",
}
MEMBER_STEPS = {
    "address": "address creation",
    "volunteer": "volunteer creation",
    "role": "role assignment",
    "board": "chapter board addition",
    "team": "team addition",
    "account": "account creation",
}


def key_for(step: str) -> str:
    """The notification key a step reports under. An unknown step is a programming error, not a quiet default."""
    if step in MONEY_STEPS:
        return MONEY_STEP_FAILED_KEY
    if step in MEMBER_STEPS:
        return STEP_FAILED_KEY
    raise ValueError(f"Unknown MijnRood sync step {step!r}")


def step_failed_claim(step: str, member_name: str, reason: str) -> str:
    """The Redis key that holds the once-a-day claim for one member's one step failing for one reason."""
    parts = (key_for(step), step, member_name, (reason or "").strip())
    digest = hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]
    return frappe.cache.make_key(f"{key_for(step)}:{digest}")


def _body(label: str, member_name: str, reason: str, money: bool) -> str:
    finance = " Finance has been told as well." if money else ""
    return (
        f"<p>The MijnRood sync could not complete <b>{escape_html(label)}</b> for member "
        f"<b>{escape_html(member_name)}</b>. The event was applied without that step, and MijnRood will "
        f"not send it again.{finance}</p>"
        f"<p>Reason: {escape_html(reason)}</p>"
        "<p>Action required: fix the cause and do the step by hand. This alert repeats at most once per "
        "24h for the same member, step and reason.</p>"
    )


def send_step_failed_alert(step: str, member_name: str, reason: str) -> bool:
    """True when at least one notification was created."""
    # lazy: callers/tests patch the helper at its source module
    from verenigingen.utils.notification_helpers import notify_administrators

    money = step in MONEY_STEPS
    label = (MONEY_STEPS if money else MEMBER_STEPS)[step]
    subject = f"MijnRood sync: {label} failed for {member_name}"
    message = _body(label, member_name, reason, money)
    event_reference = f"{key_for(step)}:{member_name}:{step}"
    if money:
        result = notify_administrators(
            subject=subject,
            message=message,
            notification_key="mijnrood_sync_money_step_failed",  # literal: key discovery greps for it
            event_reference=event_reference,
            # ruling 2026-11-01: staff alerts never go to Administrator
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    else:
        result = notify_administrators(
            subject=subject,
            message=message,
            notification_key="mijnrood_sync_step_failed",  # literal: key discovery greps for it
            event_reference=event_reference,
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    return _delivered(result)
