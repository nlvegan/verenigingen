"""Server-side validation of the short membership application form (/word-lid).

The client mirrors these rules for UX only; this module is the authority.
"""

import math

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, validate_email_address

from verenigingen.utils.validation.iban_validator import validate_iban

CONSENT_TEXT_VERSION = "2026-10-30"

MAX_JOIN_REASONS = 5
MAX_BIRTH_AGE = 120
FREQUENCIES = ("Monthly", "Annual")
DELIVERY_CHOICES = ("Digitaal", "Papier", "Beide", "Geen")
POSTAL_CHOICES = ("Papier", "Beide")
REQUIRED_FIELDS = {
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "address_line1": "Street",
    "postal_code": "Postal code",
    "city": "City",
    "country": "Country",
}
TEXT_FIELDS = (
    "first_name",
    "tussenvoegsel",
    "last_name",
    "address_line1",
    "postal_code",
    "house_number",
    "house_number_addition",
    "city",
    "country",
    "mobile_no",
    "join_reason_other",
    "referral_source_other",
)
# Each optional question owns the extra free-text field that goes with it.
QUESTION_FIELDS = {
    "mobile_no": ("mobile_no",),
    "birth_year": ("birth_year",),
    "join_reasons": ("join_reasons", "join_reason_other"),
    "referral_source": ("referral_source", "referral_source_other"),
    "magazine_delivery": ("magazine_delivery",),
    "starter_guide_delivery": ("starter_guide_delivery",),
}


def validate_short_application(door, data: dict) -> dict:
    """Return the cleaned payload for ``data`` or raise ``frappe.ValidationError``."""
    hidden = door.hidden()
    cleaned = _clean_identity(data)
    # Snapshot: confirm creates the Member with the type the applicant saw, even if the door changes.
    cleaned["membership_type"] = door.membership_type
    _check_email_field(cleaned)
    cleaned.update(_clean_optional_questions(data, hidden, cleaned))
    postal = _clean_delivery(data, hidden, cleaned)
    if door.form_shape == "Housemate":
        _clean_housemate(data, cleaned)
    else:
        _clean_regular(door, data, cleaned, postal)
    return cleaned


def _text(data, key) -> str:
    value = data.get(key)
    return "" if value is None else str(value).strip()


def _clean_identity(data) -> dict:
    cleaned = {key: _text(data, key) for key in TEXT_FIELDS}
    cleaned["email"] = _text(data, "email").lower()
    for key, label in REQUIRED_FIELDS.items():
        if not cleaned[key]:
            frappe.throw(_("{0} is required.").format(_(label)))
    if not frappe.db.exists("Country", cleaned["country"]):
        frappe.throw(_("Unknown country."))
    return cleaned


def _check_email_field(cleaned):
    if not validate_email_address(cleaned["email"]):
        frappe.throw(_("Enter a valid email address."))


def _clean_optional_questions(data, hidden, cleaned) -> dict:
    """Optional block. Hidden questions are dropped, not validated."""
    result = {}
    for question, keys in QUESTION_FIELDS.items():
        if question in hidden:
            for key in keys:
                cleaned.pop(key, None)
    if "birth_year" not in hidden:
        year = _clean_birth_year(data.get("birth_year"))
        if year:
            result["birth_year"] = year
    if "join_reasons" not in hidden:
        result["join_reasons"] = _clean_join_reasons(data.get("join_reasons"))
    if "referral_source" not in hidden:
        source = _text(data, "referral_source")
        if source and not frappe.db.get_value("Membership Referral Source", {"name": source, "enabled": 1}):
            frappe.throw(_("Unknown referral source."))
        result["referral_source"] = source
    return result


def _clean_birth_year(raw):
    if raw in (None, ""):
        return None
    try:
        year = int(str(raw).strip())
    except ValueError:
        frappe.throw(_("Enter a valid birth year."))
    this_year = getdate(nowdate()).year
    if not this_year - MAX_BIRTH_AGE <= year <= this_year:
        frappe.throw(_("Enter a valid birth year."))
    return year


def _clean_join_reasons(raw) -> list:
    if isinstance(raw, str):
        raw = [raw]
    reasons = [str(r).strip() for r in (raw or []) if str(r).strip()]
    if len(reasons) > MAX_JOIN_REASONS:
        frappe.throw(_("Choose at most {0} reasons.").format(MAX_JOIN_REASONS))
    for reason in reasons:
        if not frappe.db.get_value("Membership Join Reason", {"name": reason, "enabled": 1}):
            frappe.throw(_("Unknown reason for joining."))
    return reasons


def _clean_delivery(data, hidden, cleaned) -> bool:
    """Validate delivery choices; return whether either one is postal (hidden counts as not postal)."""
    postal = False
    for question in ("magazine_delivery", "starter_guide_delivery"):
        if question in hidden:
            continue
        choice = _text(data, question) or "Geen"
        if choice not in DELIVERY_CHOICES:
            frappe.throw(_("Choose a valid delivery option."))
        if choice in POSTAL_CHOICES:
            if cleaned["country"] != "Netherlands":
                frappe.throw(_("Paper delivery is only available for addresses in the Netherlands."))
            postal = True
        cleaned[question] = choice
    return postal


def _clean_housemate(data, cleaned):
    name = _text(data, "housemate_of_name")
    if not name:
        frappe.throw(_("Enter the name of the paying member at your address."))
    if not cint(data.get("housemate_confirmed")):
        frappe.throw(_("Confirm that a paying member lives at your address."))
    cleaned["housemate_of_name"] = name
    cleaned["housemate_confirmed"] = 1


def _clean_regular(door, data, cleaned, postal):
    frequency = _text(data, "frequency")
    template = frequency in FREQUENCIES and door.get_template_for(frequency)
    if not template:
        frappe.throw(_("This payment frequency is not available."))
    amount = _parse_amount(data.get("amount"))
    if amount < door.minimum_for(frequency, postal):
        frappe.throw(_("The amount is below the minimum for this choice."))
    cleaned["iban"] = _clean_iban(data, frequency)
    cleaned["bank_account_name"] = _text(data, "bank_account_name")
    if not cint(data.get("consent")):
        frappe.throw(_("You must accept the terms to apply."))
    cleaned.update(
        frequency=frequency,
        amount=amount,
        selected_dues_schedule=template,
        consent_given_at=str(now_datetime()),
        consent_text_version=CONSENT_TEXT_VERSION,
    )


def _parse_amount(raw) -> float:
    text = _text({"a": raw}, "a").replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        frappe.throw(_("Enter a valid amount."))
    if not math.isfinite(amount) or amount <= 0:
        frappe.throw(_("Enter a valid amount."))
    return flt(amount)


def _clean_iban(data, frequency) -> str:
    iban = _text(data, "iban").replace(" ", "").upper()
    if not iban:
        if frequency == "Monthly":
            frappe.throw(_("Monthly payment requires an IBAN for direct debit."))
        return ""
    result = validate_iban(iban)
    if not result["valid"]:
        frappe.throw(result["message"])
    return iban
