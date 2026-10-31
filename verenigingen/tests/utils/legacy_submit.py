"""Stand-in for the Member that ``submit_application`` used to create (#1765).

``submit_application`` now stages a Membership Application Submission and creates no Member; approval
creates it. A test whose subject is what happens AFTER a Member exists (approval, invoices, chapter
rosters, the volunteer record) still needs a Pending one, so ``submit_and_materialise`` runs the real
endpoint, follows the emailed confirm link, and then calls the real ``materialise_member`` -- the step
approval runs first, without the approval core. It is a fixture, not a claim about the approval flow;
Task 9 of #1765 deletes it once those tests approve through ``approve_application``.
"""

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.api.membership_application import submit_application
from verenigingen.services.member.application.application_materialiser import materialise_member
from verenigingen.services.member.application.application_record import confirm_application
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.utils.application_helpers import parse_application_data
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

SUBMISSION = "Membership Application Submission"


def submit_and_materialise(*args, **kwargs):
    """Call the real endpoint; on success also confirm the application and create (or update) the Member."""
    response = submit_application(*args, **kwargs)
    if not response.get("success"):
        return response
    email = str(parse_application_data(kwargs.get("data", kwargs)).get("email", "")).strip().lower()
    name = frappe.db.get_value(
        SUBMISSION,
        {"status": "Unconfirmed", "source": "Full Form", "email": email},
        "name",
        order_by="creation desc",
    )
    if not name:  # routed to the "already a member" mail: nothing was staged
        return response
    _follow_confirm_link(name)
    application = frappe.get_doc(SUBMISSION, name)
    member = materialise_member(application)
    frappe.delete_doc(SUBMISSION, name, force=True, ignore_permissions=True)
    response["data"] = {
        "application_id": member.application_id,
        "applicant_id": member.application_id,
        "member_record": member.name,
        "status": "pending_review",
    }
    return response


def _follow_confirm_link(name):
    """Follow the emailed link: a POST with the token."""
    token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
    previous = getattr(frappe.local, "request", None)
    frappe.local.request = Request(EnvironBuilder(method="POST").get_environ())
    try:
        confirmed = confirm_application(name, token)
    finally:
        frappe.local.request = previous
    if not confirmed.get("success"):
        frappe.throw(f"legacy_submit could not confirm {name}: {confirmed}")
