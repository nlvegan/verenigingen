"""Turn a confirmed short-application submission into a Pending Member.

Mirrors the order of ``api.membership_application.submit_application`` (existing-member routing,
address, create or update the Member, chapter suggestion) and reuses its helpers unchanged.
Everything that can fail runs behind one savepoint, so a failure leaves no Address or Member behind
and the submission stays Unconfirmed. No commit here: Frappe's request commit applies (ruling R4).
"""

import json
import random
import string

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from verenigingen.api.membership_application import (
    _create_pending_chapter_membership_safe,
    _handle_existing_member,
    _save_suggested_chapter,
)
from verenigingen.services.member.approval.application_helpers import (
    create_address_from_application,
    create_member_from_application,
    determine_chapter_from_application,
    generate_application_id,
    update_member_from_reapplication,
)
from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context
from verenigingen.utils.security.guest_return_tokens import verify_guest_return_token
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS, rollback_to_savepoint

SUBMISSION = "Membership Application Submission"
CONFIRM_TOKEN_PURPOSE = "application_email_confirmation"
EXPIRY_DAYS = 7
PURGE_DAYS = 30


def refusal() -> dict:
    """The one answer for every way a confirmation can fail."""
    return {"success": False, "message": _("This confirmation link is invalid or has expired.")}


def success() -> dict:
    return {"success": True, "message": _("Thank you, your application is received and will be reviewed.")}


def confirm_submission(submission_name, token) -> dict:
    if getattr(frappe.request, "method", None) != "POST":
        return refusal()
    submission = _confirmable_submission(submission_name, token)
    if not submission:
        return refusal()
    payload = json.loads(submission.payload)
    if not _submitted_template_still_valid(payload):  # ruling R15: the door changed since submit
        _set_status(submission.name, "Expired")
        return refusal()
    existing = frappe.db.get_value(
        "Member", {"email": submission.email}, ["name", "status", "application_status"], as_dict=True
    )
    if existing:
        _action, blocked = _handle_existing_member(existing, payload)
        if blocked:  # ruling R10: became un-applyable since submit; same refusal, nothing created
            _set_status(submission.name, "Expired")
            return refusal()
    door = frappe.get_doc("Membership Application Door", submission.door)
    member = _create_member_with_savepoint(submission, door, payload, existing)
    if not member:
        return refusal()
    frappe.db.set_value(
        SUBMISSION,
        submission.name,
        {"status": "Confirmed", "confirmed_on": now_datetime(), "member": member.name},
    )
    return success()


def _confirmable_submission(submission_name, token):
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


def _submitted_template_still_valid(payload) -> bool:
    """The submitted template must still be a template of the type snapshotted at submit."""
    template = payload.get("selected_dues_schedule")
    if not template:  # Housemate: no template, approval falls back to the type's own
        return bool(payload.get("membership_type"))
    row = frappe.db.get_value(
        "Membership Dues Schedule", template, ["is_template", "membership_type"], as_dict=True
    )
    return bool(row and row.is_template and row.membership_type == payload.get("membership_type"))


def expire_and_purge_submissions() -> dict:
    """Daily job: expire Unconfirmed rows past EXPIRY_DAYS, delete Unconfirmed/Expired rows past PURGE_DAYS.

    Cut-offs come from now_datetime() (site clock, same as `creation`). Confirmed rows are
    kept whatever their age: they are the record of what the member submitted. Nothing links
    to a submission, so a set-based delete is safe; the scheduler commits after the job.
    """
    now = now_datetime()
    purge_before = add_days(now, -PURGE_DAYS)
    expire_before = add_days(now, -EXPIRY_DAYS)
    deleted = _delete_older_than(purge_before)
    expired = _expire_older_than(expire_before)
    return {"expired": expired, "deleted": deleted}


def _delete_older_than(cutoff) -> int:
    filters = {"status": ["in", ["Unconfirmed", "Expired"]], "creation": ["<", cutoff]}
    count = frappe.db.count(SUBMISSION, filters)
    frappe.db.delete(SUBMISSION, filters)
    return count


def _expire_older_than(cutoff) -> int:
    names = frappe.get_all(SUBMISSION, {"status": "Unconfirmed", "creation": ["<", cutoff]}, pluck="name")
    for name in names:
        _set_status(name, "Expired")
    return len(names)


def _set_status(name, status):
    frappe.db.set_value(SUBMISSION, name, "status", status, update_modified=False)


def _create_member_with_savepoint(submission, door, payload, existing):
    """Address + Member + answers + chapter behind one savepoint; None (and a log row) on failure."""
    savepoint = "".join(random.sample(string.ascii_lowercase, 10))
    frappe.db.savepoint(savepoint)
    # Helpers queue their errors/notices in message_log (frappe.throw appends before raising) and a
    # rollback does not undo that; the guest must only see our own response.
    kept_messages = len(frappe.local.message_log)
    try:
        return _write_member(door, payload, existing)
    except NON_RESUMABLE_DB_ERRORS:
        raise  # the server already discarded the transaction, and the savepoint with it
    except Exception:  # swallow-ok: caller-checks
        # Logged below; confirm_submission turns the None into the generic refusal.
        rollback_to_savepoint(savepoint)
        frappe.log_error(
            title="Short application confirm failed",
            message=f"Submission {submission.name}\n{frappe.get_traceback()}",
        )
        return None
    finally:
        del frappe.local.message_log[kept_messages:]


def _write_member(door, payload, existing):
    data = to_helper_payload(payload, door)
    application_id = generate_application_id()
    address = create_address_from_application(data)
    if existing:
        member = update_member_from_reapplication(existing.name, data, application_id, address)
    else:
        member = create_member_from_application(data, application_id, address)
    _set_answers(member, payload, door)
    _link_chapter(member, data, application_id)
    return member


def _link_chapter(member, data, application_id):
    """Suggesting a chapter and saving its roster need rights a Guest lacks, so those steps run as the
    system user. _save_suggested_chapter opens its own context and contexts must not nest."""
    with _as_system_user(f"Chapter suggestion for application {application_id}"):
        suggested_chapter = determine_chapter_from_application(data)
    if suggested_chapter:
        _save_suggested_chapter(member, suggested_chapter, application_id)
        with _as_system_user(f"Pending chapter membership for application {application_id}"):
            _create_pending_chapter_membership_safe(member, suggested_chapter)


def _as_system_user(description):
    return secure_user_context(get_system_user_for_operation("member_update_during_application"), description)


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


def _set_dues_fields(member, payload):
    """The reapplication helper never reads the template and keeps the old fee; take the new payload's."""
    member.application_dues_schedule = payload.get("selected_dues_schedule") or None
    if not payload.get("amount"):  # Housemate: approval falls back to the type's template
        for field in (
            "dues_rate",
            "application_custom_fee",
            "fee_override_reason",
            "fee_override_date",
            "fee_override_by",
        ):
            member.set(field, None)


def _set_answers(member, payload, door):
    """Overwrite the new Member fields with the latest answers (a reapplication replaces them)."""
    for field in (
        "magazine_delivery",
        "starter_guide_delivery",
        "birth_year",
        "join_reason_other",
        "referral_source",
        "referral_source_other",
        "housemate_of_name",
    ):
        member.set(field, payload.get(field) or None)
    member.set("join_reasons", [{"join_reason": reason} for reason in payload.get("join_reasons") or []])
    _set_dues_fields(member, payload)
    member.application_door = door.name
    member.application_consent_version = payload.get("consent_text_version")
    consent = payload.get("consent_given_at")
    member.application_consent_at = get_datetime(consent) if consent else None
    with secure_user_context(
        get_system_user_for_operation("member_update_during_application"), "short application answers"
    ):
        member.save()
