"""Explicit member consent to the SEPA mandate text (#2464).

A member signing a mandate sees the mandate text and ticks a consent box. The server
refuses without it, and records when, what text, and from which address.

Design choices worth knowing before changing this file:

* The text lives in ``Verenigingen Settings.sepa_mandate_consent_text``. It is PLAIN
  TEXT (rendered escaped, newlines kept) with no placeholders. An empty field falls
  back to ``DEFAULT_MANDATE_CONSENT_TEXT`` in code, because a Single's JSON default is
  never applied to an existing site's ``tabSingles`` and a migrate patch could not
  cover an admin clearing the field later.
* The snapshot is a copy of the string (``str``), never a reference to Settings.
* The client sends the hash of the text it displayed; if the Settings text changed in
  between, the server refuses rather than recording consent to text the member never saw.
* The IP comes from ``get_client_ip_or_none`` (trusted-proxy aware, #1769), never the
  leftmost X-Forwarded-For.
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.client_ip import get_client_ip_or_none

SOURCE_MEMBER = "Member consent"
SOURCE_STAFF = "Staff entered"

DEFAULT_MANDATE_CONSENT_TEXT = (
    "By signing this mandate form, you authorise (A) the association to send instructions to "
    "your bank to debit your account and (B) your bank to debit your account in accordance with "
    "the instructions from the association.\n"
    "As part of your rights, you are entitled to a refund from your bank under the terms and "
    "conditions of your agreement with your bank. A refund must be claimed within 8 weeks "
    "starting from the date on which your account was debited.\n"
    "I have read the mandate text above and I agree to it."
)


def get_mandate_consent_text() -> str:
    """The text members agree to: the Settings value, or the shipped default when empty."""
    configured = frappe.db.get_single_value("Verenigingen Settings", "sepa_mandate_consent_text")
    configured = (configured or "").strip()
    return configured or DEFAULT_MANDATE_CONSENT_TEXT


def hash_consent_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_consent_given(value) -> bool:
    """Strict reading of a client-supplied consent flag. Anything but an explicit yes is no."""
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip().lower() in ("1", "true")


def consent_refusal() -> dict:
    """One response for every refusal reason, so missing and false are indistinguishable."""
    return {
        "success": False,
        "consent_required": True,
        "error": _("Please read the mandate text and tick the consent box to continue."),
    }


def stale_text_refusal() -> dict:
    return {
        "success": False,
        "consent_required": True,
        "error": _("The mandate text has changed. Please reload the page and read it again."),
    }


def check_member_consent(consent, consent_text_hash):
    """Return ``(text, None)`` when the member consented to the current text, else ``(None, refusal)``."""
    if not is_consent_given(consent):
        return None, consent_refusal()
    text = get_mandate_consent_text()
    if consent_text_hash != hash_consent_text(text):
        return None, stale_text_refusal()
    return text, None


def record_member_consent(mandate, text: str) -> None:
    """Stamp a not-yet-inserted mandate with the consent record and mark it server-verified."""
    mandate.consent_source = SOURCE_MEMBER
    mandate.consent_timestamp = now_datetime()
    mandate.consent_text = str(text)
    mandate.consent_ip = get_client_ip_or_none()
    mandate.flags.member_consent_verified = True


def user_is_staff() -> bool:
    return bool(Roles.ADMIN_ROLES.intersection(frappe.get_roles()))


def enforce_consent_provenance(mandate) -> None:
    """On insert: a mandate carries either a server-verified member consent or a staff marker.

    Closes the direct-insert bypass: a plain ``Verenigingen Member`` holds create permission
    on SEPA Mandate, so without this a member (or a donor reaching the payment hook) could
    insert a mandate over REST that never showed any text.
    """
    if not mandate.is_new() or mandate.flags.get("member_consent_verified"):
        return
    if not user_is_staff():
        frappe.throw(
            _("A SEPA mandate can only be created with the member's explicit consent."),
            frappe.PermissionError,
        )
    mandate.consent_source = SOURCE_STAFF
    mandate.consent_timestamp = None
    mandate.consent_text = None
    mandate.consent_ip = None
