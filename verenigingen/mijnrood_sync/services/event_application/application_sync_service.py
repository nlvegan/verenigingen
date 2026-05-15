"""MijnRoodApplicationSyncService — applies membership-application events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #3 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns:
- Application creation (admin_membership_application → Pending Member)
- Application update (changed application data)
- Application approval (correlator-synthesized Approved event)
- Application → Member promotion (shared by Approved path + apply-time
  safety net invoked from PR #2's member_sync_service)
- Field-by-field Member update from MijnRood data
- Linked-Member lookup for approved events

It delegates back to the calling event-application orchestrator for
cross-cutting helpers (create_related_records, assign_chapter_from_division,
handle_division_field_change, apply_new_member fallback) that have not
yet been extracted. The `orchestrator` parameter on public methods will
be removed once those are moved to their own services in later PRs.
"""

import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import get_active_status_ids
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_int, safe_json_load

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.application_sync")


class MijnRoodApplicationSyncService:
    """Applies MijnRood membership-application events to Member rows."""

    _APPLICATION_FIELDS = {
        "member_id": "member_id",
        "first_name": "first_name",
        "tussenvoegsel": "tussenvoegsel",
        "last_name": "last_name",
        "email": "email",
        "contact_number": "contact_number",
        "birth_date": "birth_date",
        "iban": "iban",
        "dues_rate": "dues_rate",
        "accepts_optional_communications": "accepts_optional_communications",
    }

    def __init__(self):
        self.logger = logger

    def _set_application_fields(self, member, row_data: dict, is_new: bool = False) -> bool:
        """Apply mapped MijnRood fields to a Member document.

        Handles member_id stringification and payment method inference.

        Args:
            is_new: If True, infer payment_method from IBAN when not already set.

        Returns:
            True if any field was changed.
        """
        changed = False
        for row_key, member_field in self._APPLICATION_FIELDS.items():
            val = row_data.get(row_key)
            if val is None or val == "":
                continue
            if row_key == "member_id":
                val = str(val)
            current = member.get(member_field)
            if str(val).strip() != str(current or "").strip():
                member.set(member_field, val)
                changed = True

        # For new applications, infer payment method from IBAN
        if is_new and member.iban and not member.payment_method:
            member.payment_method = "Bank Transfer"

        # Mollie overrides payment method for both new and changed
        mollie_id = row_data.get("custom_mollie_customer_id")
        if mollie_id and mollie_id != member.mollie_customer_id:
            member.mollie_customer_id = mollie_id
            member.payment_method = "Mollie"
            changed = True

        return changed

    def _locate_application_member(
        self, old_data: dict, new_data: dict, linked_member: Optional[str]
    ) -> Optional[str]:
        """Locate the local Pending Member for an Approved event.

        Order:
          1. event.linked_member (set by the correlator).
          2. Lookup by application_id = f'MR-APP-{old_data.id}' — matches
             what apply_new_membership_application stamps onto the Member.
          3. Lookup by normalized email.
          4. None → caller falls through.
        """
        if linked_member:
            return linked_member

        app_id = old_data.get("id")
        if app_id is not None:
            match = frappe.db.get_value(
                "Member",
                {"application_id": f"MR-APP-{app_id}"},
                "name",
            )
            if match:
                return match

        email = (new_data.get("email") or old_data.get("email") or "").strip()
        if email:
            match = frappe.db.get_value("Member", {"email": email}, "name")
            if match:
                return match

        return None

    def apply_new_membership_application(self, event, orchestrator=None) -> dict:
        """Create a pending membership application from MijnRood data.

        Creates a Member document with application_status=Pending so it
        enters the normal membership application review workflow.

        Transitional `orchestrator` parameter exposes the not-yet-extracted
        cross-cutting helpers (_find_existing_member_or_conflict via the
        god-class shim, _assign_chapter_from_division).
        """
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = get_mapping_service().map_member_fields(new_data)

        # Idempotency — member_id is authoritative, email is fallback.
        # _find_existing_member_or_conflict is still a shim on the god-class
        # (PR #2 left it there because _apply_changed_membership_application
        # still calls it via self). Use the orchestrator to honour the shim.
        existing_name, existing_result = orchestrator._find_existing_member_or_conflict(
            row_data.get("member_id"), row_data.get("email")
        )
        if existing_result is not None:
            if existing_name:
                event.linked_member = existing_name
            return existing_result

        # Create Member document as a pending application
        member = frappe.new_doc("Member")
        member.flags.ignore_workflow = True
        member._system_update = True
        member._csv_import = True
        member.application_id = f"MR-APP-{new_data.get('id', event.name)}"
        member.application_status = "Pending"
        member.status = "Pending"
        member.application_date = new_data.get("registration_time") or today()
        member.review_notes = f"Imported from MijnRood application (event {event.name})"

        self._set_application_fields(member, row_data, is_new=True)

        # Security: system-driven import from authenticated MijnRood sync
        # event; no end-user permission context applies.
        member.insert(ignore_permissions=True)
        frappe.db.commit()

        # Assign to preferred chapter (orchestrator helper, not yet extracted)
        preferred_div_id = safe_int(new_data.get("preferred_division_id"))
        if preferred_div_id:
            orchestrator._assign_chapter_from_division(member.name, preferred_div_id, event)

        event.linked_member = member.name
        self.logger.info(
            "Created membership application %s from MijnRood row %s",
            member.name,
            new_data.get("id"),
        )
        return {
            "success": True,
            "message": _("Application created as {0} (pending review)").format(member.name),
        }

    def apply_changed_membership_application(self, event, orchestrator=None) -> dict:
        """Update a pending membership application from changed MijnRood data.

        Finds the linked Member (application) and updates fields that changed.
        Handles preferred_division_id changes as chapter reassignment.

        Transitional `orchestrator` parameter: see apply_new_membership_application.
        """
        new_data = safe_json_load(event.new_data)
        changed_fields = safe_json_load(event.changed_fields, default=[])

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Find the linked member — event link first, then member_id, then email
        member_name = event.linked_member
        if not member_name:
            mijnrood_id = str(new_data.get("id", ""))
            existing_name, existing_result = orchestrator._find_existing_member_or_conflict(
                mijnrood_id, new_data.get("email")
            )
            if existing_result and not existing_result.get("success"):
                return existing_result  # Conflict
            member_name = existing_name

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for application MijnRood ID {0}").format(
                    new_data.get("id")
                ),
            }

        # Guard: don't overwrite data on already-approved/rejected applications
        app_status = frappe.db.get_value("Member", member_name, "application_status")
        if app_status and app_status not in ("Pending", ""):
            return {
                "success": True,
                "message": _("Application {0} already {1}, skipping update").format(member_name, app_status),
            }

        # Chapter reassignment if preferred_division_id changed
        chapter_msg = orchestrator._handle_division_field_change(
            member_name, changed_fields, event, field_name="preferred_division_id"
        )

        row_data = get_mapping_service().map_member_fields(new_data)
        member = frappe.get_doc("Member", member_name)
        member.flags.ignore_workflow = True
        member._system_update = True

        changed_something = self._set_application_fields(member, row_data)

        if changed_something:
            # Security: system-initiated update from authoritative MijnRood data
            member.save(ignore_permissions=True)
            frappe.db.commit()

        messages = []
        if chapter_msg:
            messages.append(chapter_msg)
        messages.append(_("Application {0} updated").format(member_name))

        event.linked_member = member_name
        return {"success": True, "message": "; ".join(messages)}

    def promote_application_member(
        self,
        old_data: dict,
        new_data: dict,
        row_data: dict,
        event,
        orchestrator,
    ) -> dict:
        """Promote a local Pending Member to Approved/Active using MijnRood data.

        Shared by:
        - apply_approved (correlator-driven path, preferred)
        - try_promote_application (apply-time cross-run safety net)
        - PR #2's member_sync_service.apply_new_member (via orchestrator)

        Handles:
        1. Field sync via MemberImportService.create_or_update_member
        2. Flipping application_status to Approved AND member.status to Active
        3. Running the standard related-records side effects via orchestrator

        The target Member is resolved by MemberImportService's own cascade
        lookup (member_id → email) from `row_data`. Callers should still
        run their own lookup beforehand to decide whether to invoke this
        method versus falling through to apply_new_member, but the
        resolved name is not threaded through — it would be ignored.

        Transitional `orchestrator` parameter exposes _create_related_records.
        """
        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        service = get_member_import_service()
        status, updated_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )
        if status not in ("created", "updated"):
            return {
                "success": False,
                "message": _("Application promotion failed: {0}").format(status),
            }

        old_member_id = old_data.get("id")
        new_member_id = new_data.get("id")

        updates = {
            "application_status": "Approved",
            "review_notes": (
                f"Approved via MijnRood (event {event.name}). "
                f"Application id {old_member_id} → member_id {new_member_id}."
            ),
        }

        status_id = safe_int(new_data.get("current_membership_status_id"))
        if status_id is not None and status_id in get_active_status_ids():
            updates["status"] = "Active"
        elif status_id is not None:
            self.logger.warning(
                "Promotion event %s carries unexpected MijnRood status id %s for member %s; "
                "leaving member.status unchanged",
                event.name,
                status_id,
                updated_name,
            )

        frappe.db.set_value("Member", updated_name, updates, update_modified=False)

        event.linked_member = updated_name

        related_msgs = orchestrator._create_related_records(updated_name, row_data, event)

        messages = [
            _("Application {0} promoted (id {1} → member_id {2})").format(
                updated_name, old_member_id, new_member_id
            )
        ]
        messages.extend(related_msgs)
        return {"success": True, "message": "; ".join(messages)}

    def try_promote_application(self, event, row_data: dict, orchestrator=None) -> Optional[dict]:
        """Handle MijnRood application->member promotion (apply-time safety net).

        This runs when the correlator didn't pair events at poll time (rare:
        cross-run split or low-confidence match). Detection: email match
        where the existing member has application_status=Pending.
        Promotion is delegated to promote_application_member.
        """
        email = row_data.get("email")
        match = frappe.db.get_value(
            "Member",
            {"email": email},
            ["name", "member_id", "application_status"],
            as_dict=True,
        )
        if not match or match.application_status != "Pending":
            return None

        old_member_id = match.member_id
        new_member_id = row_data.get("member_id")

        self.logger.info(
            "Promoting application %s (member_id %s → %s) via event %s (apply-time fallback)",
            match.name,
            old_member_id,
            new_member_id,
            event.name,
        )

        # Build minimal old_data + new_data stubs — apply-time path doesn't
        # have the original application row handy. promote_application_member
        # only uses old_data["id"] for the log message; new_data needs
        # current_membership_status_id for the status-flip path, default to
        # 1 (active) which is correct for a promotion.
        old_data_stub = {"id": old_member_id}
        new_data_stub = {"id": new_member_id, "current_membership_status_id": 1}

        return self.promote_application_member(old_data_stub, new_data_stub, row_data, event, orchestrator)

    def apply_approved(self, event, orchestrator=None) -> dict:
        """Apply an Approved event synthesized by the approval correlator.

        The event's old_data is the deleted application row; new_data is the
        newly-created admin_member row. We locate the local Pending Member
        that was created when the application first synced, then delegate to
        promote_application_member.

        Transitional `orchestrator` parameter exposes _apply_new_member
        (god-class shim into PR #2's member_sync_service) for fallback.
        """
        new_data = safe_json_load(event.new_data)
        old_data = safe_json_load(event.old_data)
        if not new_data:
            return {"success": False, "message": _("No new data in approved event")}

        row_data = get_mapping_service().map_member_fields(new_data)

        member_name = self._locate_application_member(old_data or {}, new_data, event.linked_member)
        if not member_name:
            # Defensive fallback — shouldn't happen in practice because the
            # application event already created a Pending Member that the
            # correlator linked to this event.
            self.logger.warning(
                "Approved event %s could not locate a Pending Member; falling " "through to apply_new_member",
                event.name,
            )
            return orchestrator._apply_new_member(event)

        return self.promote_application_member(old_data or {}, new_data, row_data, event, orchestrator)


_service_instance: Optional[MijnRoodApplicationSyncService] = None


def get_application_sync_service() -> MijnRoodApplicationSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodApplicationSyncService()
    return _service_instance
