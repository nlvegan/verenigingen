"""Approval turns an application into a Member (#1765).

Until approval an application is only a Membership Application Submission. Approving it creates the
Member, or, for a reapplying one, writes what the application supplied onto the Member that exists.
Nothing here commits: the caller wraps it in a savepoint and Frappe's request commit applies.
"""

import json
from contextlib import contextmanager

import frappe
from frappe.utils import get_datetime, now_datetime

from verenigingen.services.member.application.short_application_confirm import to_helper_payload
from verenigingen.services.member.approval.application_helpers import (
    _OVERRIDE_FIELDS,
    _append_chapter_notes,
    _apply_custom_contribution_fee,
    _reset_application_dues_choice,
    _sanitize_application_names,
    create_address_from_application,
    create_member_from_application,
    create_pending_chapter_membership,
    create_volunteer_record,
    map_payment_method,
)
from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context

# Never taken from an application, whatever it carries: identity and status belong to the Member and to
# staff. The last four are the fee: they are written only by the dues helpers, and only where the fee on
# the Member came from an earlier application (_fee_came_from_application), never over a staff override.
PROTECTED_FIELDS = frozenset(
    {
        "email",
        "status",
        "application_status",
        "user",
        "customer",
        "member_id",
        "payment_reference",
        "fee_override_by",
        "fee_override_date",
        "fee_override_reason",
        "dues_rate",
    }
)

# Form keys that are Member fields of the same name, and what an existing Member may take from a
# reapplication. An allowlist, not "every Member field": the Full Form payload is guest-controlled and
# Member carries fields (mollie ids, employee, permission_category, ...) that must never come from it.
# `email` is a form key too, so it is in the candidate set and PROTECTED_FIELDS is what keeps it out.
_PLAIN_FIELDS = (
    "first_name",
    "middle_name",
    "tussenvoegsel",
    "last_name",
    "contact_number",
    "birth_date",
    "pronouns",
    "iban",
    "bic",
    "bank_account_name",
    "selected_membership_type",
    "interested_in_volunteering",
)
# Answers a reapplication REPLACES (blank included), as the short form's confirm did.
_ANSWER_FIELDS = (
    "magazine_delivery",
    "starter_guide_delivery",
    "birth_year",
    "join_reason_other",
    "referral_source",
    "referral_source_other",
    "housemate_of_name",
)
_VOLUNTEER_HINTS = (
    "volunteer_skills",
    "volunteer_interests",
    "volunteer_availability",
    "volunteer_experience_level",
)


def application_data(application) -> dict:
    """The stored payload in the key shape the member helpers read (Ruling C)."""
    payload = json.loads(application.payload)
    if application.source == "Short Form":
        return to_helper_payload(payload, frappe.get_doc("Membership Application Door", application.door))
    return payload


def materialise_member(application):
    """Create the Member for `application`, or update the one that exists, leaving it Pending."""
    data = application_data(application)
    existing = frappe.db.get_value("Member", {"email": application.email})
    if existing is None:
        data["email"] = application.email  # the address the confirm link proved, not a payload's own claim
        if application.source == "Short Form":
            data["opt_out_optional_emails"] = 1  # ruling R14: the short form has no newsletter opt-in
    application_id = application.application_id or None  # unset is NULL, never "" (the field is unique)
    address = create_address_from_application(data)
    with _no_status_mail():
        if existing:
            member = _update_member(application, data, existing, address, application_id)
        else:
            member = create_member_from_application(data, application_id, address)
            _save_answers(member, application)
    _add_volunteer_and_chapter(member, application, data)
    return member


@contextmanager
def _no_status_mail():
    """Insert/save the Member as Pending without the generic "Membership Status Update: Pending" mail.

    MemberEventEmissionService.should_skip_event_emission reads frappe.flags.bulk_member_operations
    (a per-document flag is not consulted there), so that flag is raised for the write and restored.
    The approval itself sends the applicant's one email.
    """
    before = frappe.flags.get("bulk_member_operations")
    frappe.flags.bulk_member_operations = True
    try:
        yield
    finally:
        frappe.flags.bulk_member_operations = before


def _writable_values(application, member) -> dict:
    """{fieldname: value} an existing Member takes from this application: supplied, non-blank, not protected.

    `additional_notes` is never written to the Member (Ruling R): it stays on the application, which is
    kept and linked by `member`.

    The address, the replace-on-reapply answers and the dues choice are applied by materialise_member
    next to this, so the preview of a reapplication adds them (Task 6).
    """
    data = application_data(application)
    first, middle, tussenvoegsel, last = _sanitize_application_names(data)
    names = {"first_name": first, "middle_name": middle, "tussenvoegsel": tussenvoegsel, "last_name": last}
    values = {field: data.get(field) for field in (*_PLAIN_FIELDS, "email")}
    values.update(names)
    if data.get("payment_method"):
        values["payment_method"] = map_payment_method(data["payment_method"])
    if "opt_out_optional_emails" in data:  # inverted: the Member stores an opt-in
        values["accepts_optional_communications"] = 0 if data["opt_out_optional_emails"] else 1
    return {
        field: value
        for field, value in values.items()
        if field not in PROTECTED_FIELDS and value is not None and value != ""
    }


def _update_member(application, data, member_name, address, application_id):
    member = frappe.get_doc("Member", member_name)
    for field, value in _writable_values(application, member).items():
        member.set(field, value)
    if address:
        member.primary_address = address.name
    member.status = "Pending"  # so the approval core's preconditions hold
    member.application_status = "Pending"
    member.application_date = now_datetime()
    member.application_id = application_id
    for hint in _VOLUNTEER_HINTS:  # in-memory only: create_volunteer_record reads them
        if data.get(hint):
            setattr(member, hint, data[hint])
    _append_chapter_notes(member, application.chapter, label="Selected Chapter (Reapplication)")
    member._suppress_customer_messages = True
    _set_dues_choice(member, data)
    _set_answers(member, application)
    with _as_system_user(f"Update member {member.name} from application {application.name}"):
        member.save()
    return member


def _set_dues_choice(member, data):
    """What a reapplication does to the dues choice (#1730): reset an application's own, then apply."""
    _reset_application_dues_choice(member, data)
    _apply_custom_contribution_fee(member, data, context_label="reapplication")


def _save_answers(member, application):
    _set_answers(member, application)
    with _as_system_user(f"Application answers for {member.name}"):
        member.save()


def _set_answers(member, application):
    """Overwrite the answers the short form asks, as its confirm did (a reapplication replaces them)."""
    if application.source != "Short Form":
        return
    payload = json.loads(application.payload)
    for field in _ANSWER_FIELDS:
        member.set(field, payload.get(field) or None)
    member.set("join_reasons", [{"join_reason": reason} for reason in payload.get("join_reasons") or []])
    member.application_dues_schedule = payload.get("selected_dues_schedule") or None
    if not payload.get("amount"):  # Housemate: approval falls back to the type's template
        for field in (*_OVERRIDE_FIELDS, "application_custom_fee"):
            member.set(field, None)
    member.application_door = application.door
    member.application_consent_version = payload.get("consent_text_version")
    consent = payload.get("consent_given_at")
    member.application_consent_at = get_datetime(consent) if consent else None


def _add_volunteer_and_chapter(member, application, data):
    """A Volunteer for an interested applicant (an email's earlier Volunteer is re-linked, never doubled:
    create_volunteer_record does that) and the Pending Chapter Member row approval activates."""
    if data.get("interested_in_volunteering"):
        create_volunteer_record(member)
    if application.chapter:
        with _as_system_user(f"Pending chapter membership for application {application.name}"):
            create_pending_chapter_membership(member, application.chapter)


def _as_system_user(description):
    return secure_user_context(get_system_user_for_operation("member_update_during_application"), description)
