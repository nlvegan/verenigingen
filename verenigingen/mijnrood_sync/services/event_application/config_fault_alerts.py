"""Staff alerts for MijnRood sync CONFIGURATION faults (#2309, part 1).

A mapping that points at nothing (a division id no Chapter owns, a Role / Chapter Role / Team that is
gone, a payment period with no dues template) fails the same way for every event it touches, and the
event is consumed with only a message string: MijnRood does not resend. Each fault class has one
registered key; the alert is deduplicated once per 24h per FAULT (not per member), because the fix is one
setting no matter how many members hit it.

These functions only BUILD and SEND. Queueing, the once-a-day Redis claim and the after-commit timing
belong to the orchestrator (``queue_alert`` / ``flush_pending_alerts``, #2199). Every notify_administrators
call keeps its literal ``notification_key`` because the key census greps for it.
"""

import hashlib

import frappe
from frappe.utils import escape_html

DIVISION_UNMAPPED_KEY = "mijnrood_division_unmapped"
ROLE_MAPPING_INVALID_KEY = "mijnrood_role_mapping_invalid"
DUES_TEMPLATE_UNRESOLVED_KEY = "mijnrood_dues_template_unresolved"


def _claim_key(alert_key: str, *parts) -> str:
    """The Redis key that holds the once-a-day claim for one fault of one class."""
    digest = hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return frappe.cache.make_key(f"{alert_key}:{digest}")


def _delivered(result) -> bool:
    result = result or {}
    return (
        bool(result.get("success"))
        and not result.get("skipped")
        and bool(result.get("notifications_created"))
    )


def _first_seen(member_name: str, event_name: str) -> str:
    event = f" (event {escape_html(event_name)})" if event_name else ""
    return f"First seen on member {escape_html(member_name)}{event}."


def division_unmapped_claim(division_id, reason: str) -> str:
    return _claim_key(DIVISION_UNMAPPED_KEY, division_id, reason)


def role_mapping_claim(object_type: str, name: str, reason: str) -> str:
    return _claim_key(ROLE_MAPPING_INVALID_KEY, object_type, name, reason)


def dues_template_claim(payment_period) -> str:
    return _claim_key(DUES_TEMPLATE_UNRESOLVED_KEY, (payment_period or "").strip().lower())


def send_division_unmapped_alert(
    division_id, reason: str, detail: str, member_name: str, event_name: str
) -> bool:
    """True when at least one notification was created."""
    # lazy: callers/tests patch the helper at its source module
    from verenigingen.utils.notification_helpers import notify_administrators

    return _delivered(
        notify_administrators(
            subject=f"MijnRood division {division_id}: {reason}",
            message=(
                f"<p>MijnRood sent a change for division <b>{escape_html(str(division_id))}</b>, but "
                f"{escape_html(detail)}. The event was applied without the chapter step, and MijnRood "
                "will not send it again.</p>"
                f"<p>{_first_seen(member_name, event_name)} "
                "Action required: set the division id on the right Chapter (or create the Chapter), then "
                "assign the affected members by hand. This alert repeats at most once per 24h for the same "
                "division and reason.</p>"
            ),
            notification_key="mijnrood_division_unmapped",  # literal: key discovery greps for it
            event_reference=f"mijnrood_division_unmapped:{division_id}:{reason}",
            # ruling 2026-11-01: staff alerts never go to Administrator
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    )


def send_role_mapping_alert(
    object_type: str, name: str, reason: str, member_name: str, event_name: str
) -> bool:
    # lazy: callers/tests patch the helper at its source module
    from verenigingen.utils.notification_helpers import notify_administrators

    return _delivered(
        notify_administrators(
            subject=f"MijnRood role mapping invalid: {object_type} '{name}' {reason}",
            message=(
                f"<p>The MijnRood role mapping points at {escape_html(object_type)} "
                f"<b>{escape_html(name)}</b>, which {escape_html(reason)}. The event was applied without "
                "that step, and MijnRood will not send it again.</p>"
                f"<p>{_first_seen(member_name, event_name)} "
                "Action required: fix the MijnRood Sync Settings role mapping (or create / reactivate "
                f"the {escape_html(object_type)}), then redo the step for the affected members. This "
                "alert repeats at most once per 24h for the same object and reason.</p>"
            ),
            notification_key="mijnrood_role_mapping_invalid",  # literal: key discovery greps for it
            event_reference=f"mijnrood_role_mapping_invalid:{object_type}:{name}:{reason}",
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    )


def send_dues_template_alert(payment_period, detail: str, member_name: str, event_name: str) -> bool:
    # lazy: callers/tests patch the helper at its source module
    from verenigingen.utils.notification_helpers import notify_administrators

    shown = payment_period or "(empty)"
    return _delivered(
        notify_administrators(
            subject=f"MijnRood payment period '{shown}' has no dues template",
            message=(
                f"<p>A synced member has payment period <b>{escape_html(str(shown))}</b>, and no dues "
                f"schedule template could be resolved for it: {escape_html(detail)}. The dues schedule "
                "was skipped, and MijnRood will not send the member again.</p>"
                f"<p>{_first_seen(member_name, event_name)} "
                "Action required: configure the dues schedule template for this period in Verenigingen "
                "Settings, then create the schedules by hand. This alert repeats at most once per 24h for "
                "the same payment period.</p>"
            ),
            notification_key="mijnrood_dues_template_unresolved",  # literal: key discovery greps for it
            event_reference=f"mijnrood_dues_template_unresolved:{(payment_period or '').strip().lower()}",
            exclude_users=["Administrator"],
            staff_alert=True,
        )
    )
