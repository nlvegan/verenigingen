"""Guest endpoint behind the short membership application page (/word-lid).

Security-sensitive: the response, the message log and the Error Log must be identical whether or
not the email belongs to a Member. Only the email that goes out differs.
"""

import json
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, get_url

from verenigingen.api.membership_application import _handle_existing_member
from verenigingen.services.member.application.short_application_validation import (
    validate_short_application,
)
from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

CONFIRM_TOKEN_PURPOSE = "application_email_confirmation"
CONFIRM_PATH = "/word-lid/bevestig"
MAX_AMOUNT = 10000
MAX_FREE_TEXT = 140
CAPPED_TEXT_FIELDS = ("join_reason_other", "referral_source_other")


def build_confirm_url(submission_name: str) -> str:
    token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, submission_name)
    return f"{CONFIRM_PATH}?{urlencode({'submission': submission_name, 'token': token})}"


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=10, seconds=3600)
@public_api(operation_type=OperationType.MEMBER_DATA)
@handle_api_error
def submit_short_application(door: str, **data) -> dict:
    """Store an unconfirmed application and send the confirmation email."""
    success = {"success": True, "message": _("Check your email to confirm your application.")}
    if data.get("website"):
        return success  # honeypot: look like success, store and send nothing
    try:
        cleaned = _validated_payload(door, data)
    except frappe.ValidationError as error:
        message = str(error)
        frappe.clear_messages()  # frappe.throw() queued it; the dict is the only channel
        return {"success": False, "message": message}
    _route(door, cleaned)
    return success


def _validated_payload(door_name, data) -> dict:
    door = _enabled_door(door_name)
    cleaned = validate_short_application(door, _normalise(data))
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


def _normalise(data) -> dict:
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


def _route(door_name, cleaned):
    email = cleaned["email"]
    existing = frappe.db.get_value(
        "Member", {"email": email}, ["name", "status", "application_status"], as_dict=True
    )
    if existing:
        _action, blocked = _handle_existing_member(existing, cleaned)
        if blocked:
            return _send_already_member_email(email)
    submission = frappe.get_doc(
        {
            "doctype": "Membership Application Submission",
            "door": door_name,
            "email": email,
            "payload": json.dumps(cleaned, default=str),
        }
    )
    submission.flags.ignore_permissions = True  # Security: guest write limited to an inert, validated row
    submission.insert()
    _send_confirmation_email(email, submission.name)


def _send_confirmation_email(email, submission_name):
    link = get_url(build_confirm_url(submission_name))
    frappe.sendmail(
        recipients=[email],
        subject=_("Bevestig je aanmelding"),
        message=_(
            "<p>Bedankt voor je aanmelding. Klik op de link hieronder om je aanmelding te bevestigen. "
            "De link is 7 dagen geldig.</p><p><a href='{0}'>Bevestig mijn aanmelding</a></p>"
            "<p>Heb je je niet aangemeld? Dan kun je deze e-mail negeren.</p>"
        ).format(link),
    )


def _send_already_member_email(email):
    frappe.sendmail(
        recipients=[email],
        subject=_("Je aanmelding"),
        message=_(
            "<p>Er is al een lidmaatschap gekoppeld aan dit e-mailadres. "
            "Neem contact met ons op als je hulp nodig hebt.</p>"
        ),
    )
