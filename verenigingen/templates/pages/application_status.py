"""Status page of a membership application (#1765).

An application is a Membership Application Submission until it is approved, so the page reads that
record and never a Member. It is a GUEST page, so it is an existence oracle: the HMAC return token
minted when the application was confirmed is checked before any database access, which makes a wrong
token, an unknown name and a token minted for another application cost and look the same.
"""

import frappe
from frappe import _
from frappe.utils import format_datetime

from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token

SUBMISSION = "Membership Application Submission"

# Namespaces the token minted in the confirmation response (confirm_application) for the status link.
# Distinct from every other page's purpose so it cannot be replayed against another guest-return check.
# The token has no expiry (#1205): the page shows the status, the application id and, once rejected,
# the reason the reviewer gave, and the link is only ever handed to the applicant who just confirmed.
APPLICATION_STATUS_TOKEN_PURPOSE = "application_status"

REASON_LABEL = "\nReason: "
# The labels that follow the reason in review_notes, as written by _rejection_review_notes.
INTERNAL_LABEL = "\nInternal Notes: "
TEMPLATE_LABEL = "\nEmail Template Used: "


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Application Status")
    context.application = _application_for(frappe.form_dict.get("id"), frappe.form_dict.get("token"))
    return context


def _application_for(name, token):
    """The applicant-visible fields of the application, or None: refused and unknown look the same."""
    name = name if isinstance(name, str) else ""
    token = token if isinstance(token, str) else ""
    if not verify_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, name, token):
        return None
    row = frappe.db.get_value(
        SUBMISSION,
        name,
        ["status", "application_id", "confirmed_on", "creation", "review_notes"],
        as_dict=True,
    )
    if not row:
        return None
    return frappe._dict(
        status=row.status,
        application_id=row.application_id,
        applied_on=format_datetime(row.confirmed_on or row.creation),
        reason=applicant_visible_reason(row.review_notes) if row.status == "Rejected" else "",
    )


def applicant_visible_reason(review_notes) -> str:
    """Only the reason. review_notes also carries the category, the template name and the reviewer's
    internal notes, which are staff-only; the reason is what the rejection mail tells the applicant too.
    Anything that does not look like what _rejection_review_notes writes shows nothing."""
    notes = review_notes or ""
    _head, found, rest = notes.partition(REASON_LABEL)
    if not found:
        return ""
    if INTERNAL_LABEL in rest:
        return rest.split(INTERNAL_LABEL, 1)[0].strip()
    return rest.rpartition(TEMPLATE_LABEL)[0].strip()
