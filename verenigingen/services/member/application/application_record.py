"""A membership application is its own record and touches no Member until it is approved (#1765).

Both forms stage the application here as a Membership Application Submission. Confirming the email
moves it to Pending Review and suggests a chapter; it creates and changes nothing else. That closes
#1740: an anonymous submission used to overwrite an existing member's name and IBAN.

Security-sensitive: what a Guest sees (the response, the message log, the Error Log) must be the same
whether or not the email belongs to a Member. Only the email that goes out differs.
"""

import hashlib
import json
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.utils import add_days, get_url, now_datetime

from verenigingen.api.membership_application import _handle_existing_member, _only_if_selectable_chapter
from verenigingen.services.member.application.short_application_confirm import (
    CONFIRM_TOKEN_PURPOSE,
    EXPIRY_DAYS,
    PURGE_DAYS,
    SUBMISSION,
    confirmable_submission,
    expire,
    refusal,
    submitted_template_still_valid,
    success,
    to_helper_payload,
)
from verenigingen.services.member.approval.application_helpers import (
    determine_chapter_from_application,
    generate_application_id,
)
from verenigingen.templates.pages.application_status import APPLICATION_STATUS_TOKEN_PURPOSE
from verenigingen.utils.secure_operations import get_system_user_for_operation, secure_user_context
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

CONFIRM_PATH = "/word-lid/bevestig"
STATUS_PATH = "/application_status"
# Rows in these states are finished with and hold nothing the association must keep. Approved is kept
# (it is the record of what the member submitted) and so is Pending Review (a reviewer still needs it).
PURGEABLE_STATUSES = ["Unconfirmed", "Expired", "Rejected", "Superseded"]
# Mails the forms send to one address per day, so they cannot be used to flood a mailbox.
MAX_MAILS_PER_ADDRESS_PER_DAY = 3

# (doctype, field holding the referenced doctype, field holding the referenced name): rows that point at an
# application by value, not by a Link field, so nothing blocks or cascades the delete.
REFERENCES_TO_DELETE = (
    ("Comment", "reference_doctype", "reference_name"),
    ("Version", "ref_doctype", "docname"),
    ("ToDo", "reference_type", "reference_name"),
    ("DocShare", "share_doctype", "share_name"),
    ("Document Follow", "ref_doctype", "ref_docname"),
    ("Notification Log", "document_type", "document_name"),
    ("View Log", "reference_doctype", "reference_name"),
    ("Activity Log", "reference_doctype", "reference_name"),
    ("Activity Log", "timeline_doctype", "timeline_name"),
    ("Error Log", "reference_doctype", "reference_name"),
    ("Email Unsubscribe", "reference_doctype", "reference_name"),
)


def stage_application(source: str, email: str, payload: dict, door: str | None = None) -> None:
    """Store an Unconfirmed application and mail the confirmation link, or mail "already a member".

    Returns nothing in every case, so the caller's response cannot depend on who owns the email.
    """
    email = email.strip().lower()
    if not _within_daily_mail_cap(email):
        return  # same response as a sent mail, so the cap says nothing about the address
    existing = frappe.db.get_value(
        "Member", {"email": email}, ["name", "status", "application_status"], as_dict=True
    )
    if existing:
        _action, blocked = _handle_existing_member(existing, payload)
        if blocked:
            return _send_already_member_email(email)
    submission = frappe.get_doc(
        {
            "doctype": SUBMISSION,
            "door": door,
            "email": email,
            "source": source,
            "payload": json.dumps(payload, default=str),
        }
    )
    submission.flags.ignore_permissions = True  # Security: guest write limited to an inert, validated row
    submission.insert()
    _send_confirmation_email(email, submission.name)


def confirm_application(name, token) -> dict:
    """Confirm from the emailed link. POST only; every refusal looks the same."""
    if getattr(frappe.request, "method", None) != "POST":
        return refusal()
    submission = confirmable_submission(name, token)
    if not submission:
        return refusal()
    payload = json.loads(submission.payload)
    if not submitted_template_still_valid(submission.source, payload):  # ruling R15: the door changed
        expire(submission.name)
        return refusal()
    existing = frappe.db.get_value(
        "Member", {"email": submission.email}, ["name", "status", "application_status"], as_dict=True
    )
    if existing:
        _action, blocked = _handle_existing_member(existing, payload)
        if blocked:  # ruling R10: became un-applyable since submit; same refusal, nothing created
            expire(submission.name)
            return refusal()
    _record_confirmation(submission, payload)
    supersede_older(submission.email, keep=submission.name)
    return {**success(), "status_url": build_status_url(submission.name)}


def supersede_older(email: str, keep: str) -> int:
    """Every other Pending Review application of this email is replaced by `keep`."""
    # One locking read of every row of this email, in name order, so two confirms for the same email take
    # the locks in the same order and the second sees the first's result. The status comes from that
    # locked read: staff may have approved or rejected a row since it was staged, and that row is skipped.
    rows = frappe.db.sql(
        f"SELECT name, status FROM `tab{SUBMISSION}` WHERE email = %s ORDER BY name FOR UPDATE",
        (email,),
        as_dict=True,
    )
    superseded = 0
    for row in rows:
        if row.name == keep or row.status != "Pending Review":
            continue
        older = frappe.get_doc(SUBMISSION, row.name)
        older.set_status("Superseded")
        older.db_set("superseded_by", keep)
        superseded += 1
    return superseded


def _record_confirmation(submission, payload):
    submission.db_set(
        {
            "applicant_name": _applicant_name(payload),
            "membership_type": _chosen_membership_type(submission.source, payload),
            "chapter": _suggested_chapter(submission, payload),
            "application_id": generate_application_id(),
            "confirmed_on": now_datetime(),
        }
    )
    submission.set_status("Pending Review")


def expire_and_purge_applications() -> dict:
    """Daily job: expire Unconfirmed rows older than EXPIRY_DAYS, delete finished rows untouched for PURGE_DAYS.

    "Finished" is PURGEABLE_STATUSES; Approved and Pending Review are kept whatever their age. Expiry
    counts from `creation`, the purge from `modified`: a rejection or replacement starts its own 30 days,
    while Expired keeps the row's old `modified` because _set_status does not touch it. Cut-offs come from
    now_datetime() (site clock, same as the columns). The only Link field pointing at an application is
    another submission's `superseded_by`, which points at a newer row; everything else that references one
    (Comment, Communication, Email Queue, File, Version, ...) is removed with it by _delete_dependents. The
    scheduler commits after the job.
    """
    now = now_datetime()
    deleted = _delete_untouched_since(add_days(now, -PURGE_DAYS))
    expired = _expire_created_before(add_days(now, -EXPIRY_DAYS))
    return {"expired": expired, "deleted": deleted}


def _delete_untouched_since(cutoff) -> int:
    names = frappe.get_all(
        SUBMISSION, {"status": ["in", PURGEABLE_STATUSES], "modified": ["<", cutoff]}, pluck="name"
    )
    if names:
        _delete_dependents(names)
        frappe.db.delete(SUBMISSION, {"name": ["in", names]})
    return len(names)


def _delete_dependents(names):
    """Remove everything attached to these applications: a retention rule that left the applicant's email
    and the staff's request text behind on a dangling name would defeat itself.

    `frappe.delete_doc` is not used for the application: it only UNLINKS Communications (the row stays,
    with the recipient and the text), parks a full copy of the row in Deleted Document unless told not to,
    and defers the rest of its cleanup to a job after commit. Instead each reference is swept explicitly;
    the set was found by asking information_schema which tables hold the name (see
    test_purging_a_rejected_application_removes_what_the_information_request_attached).
    """
    _delete_attached_files(names)
    _delete_communications(names)
    _delete_email_queue(names)
    for doctype, doctype_field, name_field in REFERENCES_TO_DELETE:
        frappe.db.delete(doctype, {doctype_field: SUBMISSION, name_field: ["in", names]})
    frappe.db.delete("Communication Link", {"link_doctype": SUBMISSION, "link_name": ["in", names]})


def _delete_attached_files(names):
    # delete_doc, not a table delete: it also removes the file on disk
    for file_name in frappe.get_all(
        "File", {"attached_to_doctype": SUBMISSION, "attached_to_name": ["in", names]}, pluck="name"
    ):
        # Security: the scheduler runs as Administrator-less system code; these files belong to a row the retention rule deletes
        frappe.delete_doc("File", file_name, force=True, ignore_permissions=True, delete_permanently=True)


def _delete_communications(names):
    filters = {"reference_doctype": SUBMISSION, "reference_name": ["in", names]}
    communications = frappe.get_all("Communication", filters, pluck="name")
    if communications:
        frappe.db.delete("Communication Link", {"parent": ["in", communications]})
        frappe.db.delete("Communication", {"name": ["in", communications]})


def _delete_email_queue(names):
    filters = {"reference_doctype": SUBMISSION, "reference_name": ["in", names]}
    queued = frappe.get_all("Email Queue", filters, pluck="name")
    if queued:
        frappe.db.delete("Email Queue Recipient", {"parent": ["in", queued]})
        frappe.db.delete("Email Queue", {"name": ["in", queued]})


def _expire_created_before(cutoff) -> int:
    names = frappe.get_all(SUBMISSION, {"status": "Unconfirmed", "creation": ["<", cutoff]}, pluck="name")
    for name in names:
        expire(name)
    return len(names)


def _applicant_name(payload) -> str:
    parts = (payload.get("first_name"), payload.get("tussenvoegsel"), payload.get("last_name"))
    return " ".join(part.strip() for part in parts if part and part.strip())


def _chosen_membership_type(source, payload):
    key = "membership_type" if source == "Short Form" else "selected_membership_type"
    return payload.get(key) or None


def _suggested_chapter(submission, payload):
    """Suggesting a chapter needs rights a Guest lacks, so it runs as the system user. The name may come
    straight from the anonymous request, hence the selectable check (#1731); the short form never had one."""
    if submission.source == "Short Form":
        data = to_helper_payload(payload, frappe.get_doc("Membership Application Door", submission.door))
    else:
        data = payload
    # Helpers queue notices in message_log; the guest must only see our own response.
    kept_messages = len(frappe.local.message_log)
    try:
        system_user = get_system_user_for_operation("member_update_during_application")
        with secure_user_context(system_user, f"Chapter suggestion for application {submission.name}"):
            return _only_if_selectable_chapter(determine_chapter_from_application(data))
    finally:
        del frappe.local.message_log[kept_messages:]


def build_status_url(submission_name: str) -> str:
    """The link to the status page, minted for the one applicant who just confirmed (never emailed)."""
    token = generate_guest_return_token(APPLICATION_STATUS_TOKEN_PURPOSE, submission_name)
    return f"{STATUS_PATH}?{urlencode({'id': submission_name, 'token': token})}"


def build_confirm_url(submission_name: str) -> str:
    token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, submission_name)
    return f"{CONFIRM_PATH}?{urlencode({'submission': submission_name, 'token': token})}"


def _within_daily_mail_cap(email) -> bool:
    digest = hashlib.sha256(email.encode()).hexdigest()
    key = frappe.cache.make_key(f"short_application_mails:{digest}")
    count = frappe.cache.incrby(key, 1)
    if frappe.cache.ttl(key) == -1:  # first mail, or a request that died before setting it
        frappe.cache.expire(key, 24 * 3600)
    return count <= MAX_MAILS_PER_ADDRESS_PER_DAY


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
