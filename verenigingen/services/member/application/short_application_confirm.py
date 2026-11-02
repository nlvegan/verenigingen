"""Checks and housekeeping around confirming a membership application.

The refusal answer, the locked-row and 7-day-expiry check and the submitted-template check. Staging,
confirming and the daily expire/purge job live in ``application_record``; confirming creates no Member.
"""

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token

SUBMISSION = "Membership Application Submission"
CONFIRM_TOKEN_PURPOSE = "application_email_confirmation"
EXPIRY_DAYS = 7
PURGE_DAYS = 30


def refusal() -> dict:
    """The one answer for every way a confirmation can fail."""
    return {"success": False, "message": _("This confirmation link is invalid or has expired.")}


def success() -> dict:
    return {"success": True, "message": _("Thank you, your application is received and will be reviewed.")}


def confirmable_submission(submission_name, token):
    """Return the locked, still-valid submission, or None. Token is always checked, on the supplied name."""
    name = submission_name if isinstance(submission_name, str) else ""
    token_ok = verify_guest_return_token(CONFIRM_TOKEN_PURPOSE, name, token if isinstance(token, str) else "")
    if not (token_ok and frappe.db.exists(SUBMISSION, name)):
        return None
    submission = frappe.get_doc(SUBMISSION, name, for_update=True)
    if submission.status != "Unconfirmed":
        return None
    if get_datetime(submission.creation) < get_datetime(add_days(now_datetime(), -EXPIRY_DAYS)):
        _set_status(name, "Expired")
        return None
    return submission


def submitted_template_still_valid(source, payload) -> bool:
    """The submitted template must still be a template of the type snapshotted at submit, and of
    the frequency the applicant chose. The full form carries no template: its type must still exist."""
    if source == "Full Form":
        chosen = payload.get("selected_membership_type")
        return not chosen or bool(frappe.db.exists("Membership Type", chosen))
    template = payload.get("selected_dues_schedule")
    if not template:  # Housemate: no template, approval falls back to the type's own
        return bool(payload.get("membership_type"))
    row = frappe.db.get_value(
        "Membership Dues Schedule",
        template,
        ["is_template", "membership_type", "billing_frequency"],
        as_dict=True,
    )
    return bool(
        row
        and row.is_template
        and row.membership_type == payload.get("membership_type")
        and row.billing_frequency == payload.get("frequency")
    )


def expire(name):
    _set_status(name, "Expired")


def _set_status(name, status):
    frappe.db.set_value(SUBMISSION, name, "status", status, update_modified=False)


def to_helper_payload(cleaned: dict, door) -> dict:
    """Map the cleaned short payload onto the keys the old application helpers read."""
    street = " ".join(
        part
        for part in (
            cleaned.get("address_line1"),
            cleaned.get("house_number"),
            cleaned.get("house_number_addition"),
        )
        if part
    )
    data = {
        "selected_membership_type": cleaned["membership_type"],  # the submit-time snapshot (R15)
        "application_source": door.slug,
        "email": cleaned["email"],
        "first_name": cleaned["first_name"],
        "tussenvoegsel": cleaned.get("tussenvoegsel", ""),
        "last_name": cleaned["last_name"],
        "contact_number": cleaned.get("mobile_no", ""),
        "address_line1": street,
        "postal_code": cleaned.get("postal_code"),
        "city": cleaned.get("city"),
        "country": cleaned.get("country"),
    }
    if cleaned.get("amount"):  # Housemates carry none: approval falls back to the type's template
        iban = cleaned.get("iban") or ""
        data.update(
            selected_dues_schedule=cleaned.get("selected_dues_schedule"),
            custom_contribution_fee=cleaned["amount"],
            uses_custom_amount=1,
            custom_amount_reason=f"Bedrag gekozen bij aanmelding ({door.title})",  # stored text, not UI
            payment_method="sepa_direct_debit" if iban else "bank_transfer",
            iban=iban,
            bank_account_name=cleaned.get("bank_account_name", ""),
        )
    return data
