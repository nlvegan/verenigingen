"""Stand-in for the Member that ``submit_application`` used to create (#1765).

``submit_application`` now stages a Membership Application Submission and creates no Member; the
Member is created at approval (a later task of #1765). A test whose subject is what happens AFTER a
Member exists (approval, invoices, chapter rosters, the volunteer record) still needs one, so
``submit_and_materialise`` runs the real endpoint (validation, eligibility, amount, staging) and then
builds the Member from the staged payload with the same helpers, in the same order, that the old
endpoint called. It is a fixture, not a claim about the approval flow; once approval materialises the
Member those tests should call it instead and this module goes away.
"""

import json

import frappe

from verenigingen.api.membership_application import (
    _only_if_selectable_chapter,
    _save_suggested_chapter,
    submit_application,
)
from verenigingen.utils.application_helpers import (
    create_address_from_application,
    create_member_from_application,
    create_pending_chapter_membership,
    create_volunteer_record,
    determine_chapter_from_application,
    generate_application_id,
    parse_application_data,
    update_member_from_reapplication,
)

SUBMISSION = "Membership Application Submission"


def submit_and_materialise(*args, **kwargs):
    """Call the real endpoint; on success also create (or, for a reapplication, update) the Member."""
    response = submit_application(*args, **kwargs)
    if not response.get("success"):
        return response
    email = str(parse_application_data(kwargs.get("data", kwargs)).get("email", "")).strip().lower()
    row = frappe.get_all(
        SUBMISSION,
        {"status": "Unconfirmed", "source": "Full Form", "email": email},
        ["name", "email", "payload"],
        order_by="creation desc",
        limit=1,
    )
    if not row:  # routed to the "already a member" mail: nothing was staged
        return response
    data = json.loads(row[0].payload)
    existing = frappe.db.get_value("Member", {"email": row[0].email})
    application_id = generate_application_id()
    address = create_address_from_application(data)
    if existing:
        member = update_member_from_reapplication(existing, data, application_id, address)
    else:
        member = create_member_from_application(data, application_id, address)
    suggested = _only_if_selectable_chapter(determine_chapter_from_application(data))
    if suggested:
        _save_suggested_chapter(member, suggested, application_id)
    if data.get("interested_in_volunteering"):
        create_volunteer_record(member)
    if suggested:
        create_pending_chapter_membership(member, suggested)
    frappe.delete_doc(SUBMISSION, row[0].name, force=True, ignore_permissions=True)
    response["data"] = {
        "application_id": application_id,
        "applicant_id": getattr(member, "application_id", None),
        "member_record": member.name,
        "status": "pending_review",
    }
    return response
