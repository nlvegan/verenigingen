"""MijnRoodApplicationSyncService — applies membership-application events to application records.

Extracted from event_application_service.py as Phase 1, PR #3 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

An application is a Membership Application Submission (MAS), exactly as for the web forms
(#1765); no Member exists for it until it is approved (#1855).

The service owns:
- Application creation (admin_membership_application → MAS in Pending Review)
- Application update (changed application data, while still Pending Review)
- Application approval (correlator-synthesized Approved event)
- Application → Member promotion: ``approve_application``, then MijnRood's own data on top
  (shared by the Approved path + apply-time safety net invoked from member_sync_service)
- MAS lookup for approved events

It calls peer services (member_sync, related_records) directly via
their ``get_xxx_service()`` accessors.
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.mijnrood_sync.field_mapping import get_active_status_ids
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.utils import safe_int, safe_json_load
from verenigingen.services.member.application.application_record import (
    record_external_application,
    update_pending_application,
)
from verenigingen.services.member.application.short_application_confirm import _type_is_active
from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="event_application.application_sync")


SUBMISSION = "Membership Application Submission"
SOURCE = "MijnRood"
APPLICATION_ID_PREFIX = "MR-APP-"
DISABLED_TYPE_ALERT_KEY = "mijnrood_disabled_default_type"
DISABLED_TYPE_REALERT_SECONDS = 24 * 3600


def disabled_type_alert_claim_key(membership_type: str) -> str:
    """The Redis key that holds the once-a-day claim for the disabled-type alert of one type."""
    return frappe.cache.make_key(f"{DISABLED_TYPE_ALERT_KEY}:{membership_type}")


# MijnRood row columns -> the application payload keys the member helpers read (the full form's shape).
_PAYLOAD_FIELDS = (
    "first_name",
    "tussenvoegsel",
    "last_name",
    "email",
    "contact_number",
    "birth_date",
    "address_line1",
    "city",
    "postal_code",
    "country",
    "iban",
)


def _release_claim(claim: str) -> None:
    """Drop the once-a-day claim. A Redis error here must not undo the staging either."""
    try:
        frappe.cache.delete(claim)
    except Exception:
        frappe.log_error(
            title="MijnRood disabled-type alert claim not released", message=frappe.get_traceback()
        )


def _send_disabled_type_alert(membership_type: str, application_name: str) -> bool:
    """Raise the staff alert; True when at least one notification was actually created."""
    from frappe.utils import escape_html

    from verenigingen.utils.notification_helpers import notify_administrators

    result = notify_administrators(
        subject=f"MijnRood applications use a disabled membership type: {membership_type}",
        message=(
            f"<p>A MijnRood application ({escape_html(application_name)}) was staged with the membership "
            f"type <b>{escape_html(membership_type)}</b>, the default set in Verenigingen Settings. "
            "That type is disabled or no longer exists.</p>"
            "<p>Action required: choose a valid membership type when you approve the application, and "
            "change the default membership type in Verenigingen Settings. This alert repeats at most once "
            "a day while the setting stays wrong.</p>"
        ),
        notification_key="mijnrood_disabled_default_type",  # literal: key discovery greps for it
        document_type=SUBMISSION,
        document_name=application_name,
        # ruling 2026-11-01: staff alerts never go to Administrator
        exclude_users=["Administrator"],
        staff_alert=True,
    )
    result = result or {}
    return (
        bool(result.get("success"))
        and not result.get("skipped")
        and bool(result.get("notifications_created"))
    )


class MijnRoodApplicationSyncService:
    """Applies MijnRood membership-application events to Membership Application Submissions."""

    def __init__(self):
        self.logger = logger

    def _application_payload(self, row_data: dict, division_id=None, membership_type=None) -> dict:
        """The stored payload for an application row, in the full form's key shape.

        Carries what review and approval read: identity, address, the chosen chapter, and the
        contribution the applicant chose (so approval builds the dues schedule MijnRood bills).
        """
        payload = {key: row_data[key] for key in _PAYLOAD_FIELDS if row_data.get(key)}
        payload["email"] = (payload.get("email") or "").strip()
        if "accepts_optional_communications" in row_data:
            payload["opt_out_optional_emails"] = 0 if row_data["accepts_optional_communications"] else 1

        chapter = self._division_chapter(division_id)
        if chapter:
            payload["selected_chapter"] = chapter

        # The type the applicant is approved into is known only from the member row (promotion).
        # Until then a reviewer who approves locally gets the site's default type, not "the first one".
        payload["selected_membership_type"] = (
            membership_type
            or frappe.db.get_single_value("Verenigingen Settings", "default_membership_type")
            or None
        )
        if row_data.get("dues_rate"):
            payload["custom_contribution_fee"] = row_data["dues_rate"]
            payload["uses_custom_amount"] = 1
            payload["custom_amount_reason"] = "Contribution chosen at MijnRood"
            template = self._dues_template(row_data)
            if template:
                payload["selected_dues_schedule"] = template
        return payload

    def _dues_template(self, row_data: dict):
        """The dues template for MijnRood's payment period, or None to take the type's own (the CSV
        import's rule: an unmapped period falls back rather than blocks)."""
        if not row_data.get("payment_period"):
            return None
        from verenigingen.utils.csv.data_transformers import get_dues_schedule_template_from_payment_period

        try:
            return get_dues_schedule_template_from_payment_period(row_data)
        except frappe.ValidationError as e:
            self.logger.warning("No dues template for payment period %r: %s", row_data["payment_period"], e)
            return None

    def _division_chapter(self, division_id):
        division_id = safe_int(division_id)
        if not division_id:
            return None
        return get_mapping_service().resolve_division_id(division_id)

    def _find_application(self, old_data: dict, new_data: dict, row_data: dict) -> Optional[str]:
        """Locate the MAS for an event.

        Order:
          1. application_id = f'MR-APP-{id}': the id MijnRood gave the application row, which is
             the Approved event's ``old_data.id`` and the New/Changed event's ``new_data.id``.
          2. The Pending Review MijnRood application of the same email.
        """
        for app_id in (old_data.get("id"), new_data.get("id")):
            if app_id is None:
                continue
            match = frappe.db.get_value(SUBMISSION, {"application_id": f"{APPLICATION_ID_PREFIX}{app_id}"})
            if match:
                return match
        return self._pending_application_by_email(row_data.get("email"))

    def _pending_application_by_email(self, email) -> Optional[str]:
        email = (email or "").strip().lower()
        if not email:
            return None
        return frappe.db.get_value(SUBMISSION, {"email": email, "source": SOURCE, "status": "Pending Review"})

    def apply_new_membership_application(self, event) -> dict:
        """Stage a MijnRood application as a Membership Application Submission in Pending Review.

        The same record and review as both web forms (#1855). No Member is created: approval
        (locally, or by MijnRood's own approval reaching promote_application_member) does that.
        """
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = get_mapping_service().map_member_fields(new_data)
        application_id = f"{APPLICATION_ID_PREFIX}{new_data.get('id', event.name)}"

        existing_application = frappe.db.get_value(SUBMISSION, {"application_id": application_id})
        if existing_application:
            return {
                "success": True,
                "message": _("Application {0} already exists ({1})").format(
                    existing_application, application_id
                ),
            }

        refusal = self._refuse_if_member_blocks(event, row_data)
        if refusal:
            return refusal

        payload = self._application_payload(row_data, new_data.get("preferred_division_id"))
        name = record_external_application(SOURCE, payload["email"], payload, application_id)
        self.logger.info("Staged application %s from MijnRood row %s", name, new_data.get("id"))
        self._alert_if_type_disabled(payload, name)
        return {
            "success": True,
            "message": _("Application created as {0} (pending review)").format(name),
        }

    def _refuse_if_member_blocks(self, event, row_data: dict) -> Optional[dict]:
        """A Member of this email that may not reapply means there is nothing to stage."""
        from verenigingen.api.membership_application import _handle_existing_member

        email = (row_data.get("email") or "").strip()
        existing = frappe.db.get_value(
            "Member", {"email": email}, ["name", "status", "application_status"], as_dict=True
        )
        if not (email and existing):
            return None
        _action, blocked = _handle_existing_member(existing, {})
        if not blocked:
            return None
        event.linked_member = existing.name
        return {
            "success": True,
            "message": _("Member {0} already exists (email={1})").format(existing.name, email),
        }

    def apply_changed_membership_application(self, event) -> dict:
        """Update a Pending Review application from changed MijnRood data.

        Replaces the stored payload (and the chapter derived from it) while the application is
        still Pending Review; a decided application is left alone.
        """
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = get_mapping_service().map_member_fields(new_data)
        application_name = self._find_application({}, new_data, row_data)
        if not application_name:
            return {
                "success": False,
                "message": _("No application found for MijnRood application ID {0}").format(
                    new_data.get("id")
                ),
            }

        # Guard: don't overwrite data on an already-approved/rejected application. The locking read
        # makes this the status as of now, not as of this transaction's snapshot.
        application = frappe.get_doc(SUBMISSION, application_name, for_update=True)
        if application.status != "Pending Review":
            return {
                "success": True,
                "message": _("Application {0} already {1}, skipping update").format(
                    application_name, application.status
                ),
            }

        payload = self._application_payload(row_data, new_data.get("preferred_division_id"))
        update_pending_application(application, payload)
        self._alert_if_type_disabled(payload, application_name)
        return {"success": True, "message": _("Application {0} updated").format(application_name)}

    def _alert_if_type_disabled(self, payload: dict, application_name: str) -> None:
        """Tell staff once a day when the application sits on a membership type that is no longer active (#2094).

        The type is the site's default (``_application_payload``), so it is the setting that is wrong, not
        the applicant: the application is staged anyway (maintainer ruling) and the reviewer picks a valid
        type at approval. A blank type is not "disabled" and is left alone. The alert must never undo the
        staging, so a failure here is logged and swallowed.
        """
        membership_type = payload.get("selected_membership_type")
        if not membership_type or _type_is_active(membership_type):
            return
        claim = disabled_type_alert_claim_key(membership_type)
        try:
            # SETNX with an expiry, not the key's per-recipient cooldown: that is admin-editable (0 = off).
            if not frappe.cache.set(claim, "1", ex=DISABLED_TYPE_REALERT_SECONDS, nx=True):
                return
            delivered = _send_disabled_type_alert(membership_type, application_name)
        except Exception:
            frappe.log_error(title="MijnRood disabled-type alert failed", message=frappe.get_traceback())
            _release_claim(claim)  # so the next application tries again
            return
        if not delivered:
            _release_claim(claim)  # key off or nobody to tell: do not hold the alert back for a day

    def promote_application_member(
        self,
        old_data: dict,
        new_data: dict,
        row_data: dict,
        event,
        application_name: str,
    ) -> dict:
        """Approve a MijnRood-approved application locally, then lay MijnRood's own data over the Member.

        Shared by:
        - apply_approved (correlator-driven path, preferred)
        - try_promote_application (apply-time cross-run safety net)

        The approval is ``approve_application``, the one every approval goes through, so the
        membership, dues schedule, first invoice, chapter activation, user account and approval mail
        are the core's (maintainer ruling, #1855), and the approver is the staff member applying this
        sync event (their chapter scope applies). The dues schedule is built from the contribution
        MijnRood reports. Then the member row's data (the new
        member_id, Mollie ids, address) is applied through MemberImportService, and the standard
        related records are synced as for any MijnRood member.

        Idempotent: an application already Approved (a retry after a failed sync, or approved
        locally first) skips the approval and applies MijnRood's data to its Member.
        """
        status_id = safe_int(new_data.get("current_membership_status_id"))
        if status_id is not None and status_id not in get_active_status_ids():
            return {
                "success": False,
                "message": _(
                    "Promotion event {0} carries MijnRood status id {1}, which is not an active status; "
                    "application {2} was not approved"
                ).format(event.name, status_id, application_name),
            }

        approval = self._approve_pending_application(application_name, old_data, new_data, row_data, event)
        if approval.get("failure"):
            return {"success": False, "message": approval["failure"]}
        member_name = approval["member"]

        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        status, updated_name = get_member_import_service().create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )
        if status not in ("created", "updated"):
            # `status` already reads "failed: <reason>" — don't say "failed" twice. The approval stands;
            # re-applying the event syncs the data.
            return {
                "success": False,
                "message": _("Application {0} approved as {1}; applying MijnRood data {2}").format(
                    application_name, member_name, status
                ),
            }

        event.linked_member = updated_name
        related_msgs = get_related_records_orchestrator()._create_related_records(
            updated_name, row_data, event
        )
        messages = [
            _("Application {0} promoted to {1} (id {2} → member_id {3})").format(
                application_name, updated_name, old_data.get("id"), new_data.get("id")
            )
        ]
        messages.extend(related_msgs)
        return {"success": True, "message": "; ".join(messages)}

    def _approve_pending_application(self, application_name, old_data, new_data, row_data, event) -> dict:
        """{"member": name} once the application is approved, or {"failure": message}."""
        from verenigingen.api.membership_application_review import approve_application
        from verenigingen.utils.csv.data_transformers import determine_membership_type_for_csv_import

        application = frappe.get_doc(SUBMISSION, application_name, for_update=True)
        if application.status == "Approved":
            return {"member": application.member}
        if application.status != "Pending Review":
            return {
                "failure": _(
                    "MijnRood approved application {0}, but it is {1} here; resolve it manually"
                ).format(application_name, application.status)
            }

        membership_type = determine_membership_type_for_csv_import(row_data)
        payload = self._application_payload(row_data, row_data.get("chapter"), membership_type)
        update_pending_application(application, payload)
        notes = (
            f"Approved via MijnRood (event {event.name}). "
            f"Application id {old_data.get('id')} → member_id {new_data.get('id')}."
        )
        result = approve_application(application_name, membership_type=membership_type, notes=notes)
        if not result.get("success"):
            return {"failure": result.get("message") or _("Approval of {0} failed").format(application_name)}
        return {"member": result["member"]}

    def try_promote_application(self, event, row_data: dict) -> Optional[dict]:
        """Handle MijnRood application->member promotion (apply-time safety net).

        This runs when the correlator didn't pair events at poll time (rare:
        cross-run split or low-confidence match). Detection: a Pending Review MijnRood
        application of the same email. Promotion is delegated to promote_application_member.
        """
        application_name = self._pending_application_by_email(row_data.get("email"))
        if not application_name:
            return None

        old_member_id = frappe.db.get_value(SUBMISSION, application_name, "application_id")
        new_member_id = row_data.get("member_id")

        self.logger.info(
            "Promoting application %s (%s → member_id %s) via event %s (apply-time fallback)",
            application_name,
            old_member_id,
            new_member_id,
            event.name,
        )

        # Build minimal old_data + new_data stubs — apply-time path doesn't
        # have the original application row handy. new_data needs
        # current_membership_status_id for the status check, default to
        # 1 (active) which is correct for a promotion.
        old_data_stub = {"id": (old_member_id or "").removeprefix(APPLICATION_ID_PREFIX)}
        new_data_stub = {"id": new_member_id, "current_membership_status_id": 1}

        return self.promote_application_member(
            old_data_stub, new_data_stub, row_data, event, application_name
        )

    def apply_approved(self, event) -> dict:
        """Apply an Approved event synthesized by the approval correlator.

        The event's old_data is the deleted application row; new_data is the
        newly-created admin_member row. We locate the application that was staged
        when the application row first synced, then delegate to
        promote_application_member.
        """
        new_data = safe_json_load(event.new_data)
        old_data = safe_json_load(event.old_data) or {}
        if not new_data:
            return {"success": False, "message": _("No new data in approved event")}

        row_data = get_mapping_service().map_member_fields(new_data)

        application_name = self._find_application(old_data, {}, row_data)
        if not application_name:
            # MijnRood approved an applicant this site never saw as an application (its New event was
            # not applied first): there is no application to approve, so the row is a member like any
            # other admin_member row.
            self.logger.warning(
                "Approved event %s could not locate an application; falling through to apply_new_member",
                event.name,
            )
            from verenigingen.mijnrood_sync.services.event_application.member_sync_service import (
                get_member_sync_service,
            )

            return get_member_sync_service().apply_new_member(event)

        return self.promote_application_member(old_data, new_data, row_data, event, application_name)


_service_instance: Optional[MijnRoodApplicationSyncService] = None


def get_application_sync_service() -> MijnRoodApplicationSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodApplicationSyncService()
    return _service_instance
