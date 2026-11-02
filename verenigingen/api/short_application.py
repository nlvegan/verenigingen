"""Guest endpoint behind the short membership application page (/word-lid).

Security-sensitive: the response, the message log and the Error Log must be identical whether or
not the email belongs to a Member. Only the email that goes out differs.
"""

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint

from verenigingen.services.member.application.application_record import (
    confirm_application,
    stage_application,
)
from verenigingen.services.member.application.short_application_validation import (
    validate_short_application,
)
from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.security.api_security_framework import OperationType, public_api

MAX_AMOUNT = 10000
MAX_FREE_TEXT = 140
CAPPED_TEXT_FIELDS = ("join_reason_other", "referral_source_other")
# A name browser autofill leaves alone; "website" was filled in for real applicants.
HONEYPOT_FIELD = "leave_this_empty"


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=10, seconds=3600)
@public_api(operation_type=OperationType.MEMBER_DATA)
@handle_api_error
def submit_short_application(door: str, **data) -> dict:
    """Store an unconfirmed application and send the confirmation email."""
    success = {"success": True, "message": _("Check your email to confirm your application.")}
    if data.get(HONEYPOT_FIELD):
        return success  # honeypot: look like success, store and send nothing
    try:
        cleaned = _validated_payload(door, data)
    except frappe.ValidationError as error:
        message = str(error)
        frappe.clear_messages()  # frappe.throw() queued it; the dict is the only channel
        return {"success": False, "message": message}
    stage_application("Short Form", cleaned["email"], cleaned, door)
    return success


def _validated_payload(door_name, data) -> dict:
    door = _enabled_door(door_name)
    cleaned = validate_short_application(door, _clean_submission_input(data))
    if (cleaned.get("amount") or 0) > MAX_AMOUNT:
        frappe.throw(_("Enter a valid amount."))
    return cleaned


def _enabled_door(door_name):
    # Same refusal for unknown and disabled: nothing about door configuration leaks.
    if not isinstance(door_name, str) or not frappe.db.get_value(
        "Membership Application Door", {"name": door_name, "enabled": 1}
    ):
        frappe.throw(_("This application form is not available."))
    return frappe.get_doc("Membership Application Door", door_name)


def _clean_submission_input(data) -> dict:
    """Coerce raw request input into the shapes the validator expects."""
    data = dict(data)
    for field in CAPPED_TEXT_FIELDS:
        if isinstance(data.get(field), str):
            data[field] = data[field].strip()[:MAX_FREE_TEXT]
    data["join_reasons"] = _join_reasons(data.get("join_reasons"))
    for field in ("consent", "housemate_confirmed"):
        data[field] = cint(data.get(field))
    return data


def _join_reasons(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            raw = None
    if raw is None or not isinstance(raw, list) or not all(isinstance(r, str) for r in raw):
        frappe.throw(_("Unknown reason for joining."))
    return raw


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=30, seconds=3600)
@public_api(operation_type=OperationType.MEMBER_DATA)
@handle_api_error
def confirm_short_application(submission: str, token: str) -> dict:
    """Confirm an application from the emailed link. POST only; every refusal looks the same."""
    return confirm_application(submission, token)
