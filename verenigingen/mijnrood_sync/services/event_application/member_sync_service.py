"""MijnRoodMemberSyncService — applies MijnRood member events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #2 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the New-Member and Changed-Member event paths plus the
existing-member-or-conflict lookup. It calls peer services
(application_sync, related_records, volunteer_sync, termination_sync)
directly via their ``get_xxx_service()`` accessors.
"""

import logging
from typing import Optional

import frappe
from frappe import _

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.mijnrood_sync.utils import safe_json_load

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.member_sync")


class MijnRoodMemberSyncService:
    """Applies MijnRood member events to Member rows.

    Stateful only insofar as it is a singleton — no per-instance state.
    """

    def find_existing_member_or_conflict(self, mijnrood_id, email) -> tuple[Optional[str], Optional[dict]]:
        """Look up existing member by member_id (authoritative) then email.

        Returns:
            (member_name, result_dict) — found or conflict
            (None, None) — no match
        """
        if mijnrood_id:
            existing = frappe.db.get_value("Member", {"member_id": str(mijnrood_id)}, "name")
            if existing:
                return existing, {
                    "success": True,
                    "message": _("Member {0} already exists (member_id={1})").format(existing, mijnrood_id),
                }
        if email:
            match = frappe.db.get_value("Member", {"email": email}, ["name", "member_id"], as_dict=True)
            if match:
                if match.member_id and mijnrood_id and str(match.member_id) != str(mijnrood_id):
                    return None, {
                        "success": False,
                        "message": _(
                            "Email {0} already used by {1} (member_id={2}), " "conflicts with MijnRood ID {3}"
                        ).format(email, match.name, match.member_id, mijnrood_id),
                    }
                return match.name, {
                    "success": True,
                    "message": _("Member {0} already exists (email={1})").format(match.name, email),
                }
        return None, None

    def apply_new_member(self, event) -> dict:
        """Create a new Member from MijnRood admin_member data."""
        new_data = safe_json_load(event.new_data)
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = get_mapping_service().map_member_fields(new_data)

        # Idempotency — member_id is authoritative, email is fallback
        existing_name, existing_result = self.find_existing_member_or_conflict(
            row_data.get("member_id"), row_data.get("email")
        )
        if existing_result is not None:
            # Check for application→member promotion: MijnRood deletes the
            # application row and creates a new member row with a different ID.
            # find_existing_member_or_conflict sees this as a conflict (email
            # match, member_id mismatch). If the existing member is a pending
            # application, this is actually a promotion, not a conflict.
            if not existing_result.get("success") and row_data.get("email"):
                from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
                    get_application_sync_service,
                )

                promotion_result = get_application_sync_service().try_promote_application(event, row_data)
                if promotion_result:
                    return promotion_result

            if existing_name:
                event.linked_member = existing_name
            return existing_result

        # Use MemberImportService for consistent creation logic
        from verenigingen.services.csv_import.member_import_service import (
            get_member_import_service,
        )

        service = get_member_import_service()
        status, member_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status in ("created", "updated"):
            event.linked_member = member_name

            related_msgs = get_related_records_orchestrator()._create_related_records(
                member_name, row_data, event
            )
            role_msgs = get_volunteer_sync_service()._process_member_roles(member_name, new_data, event=event)
            related_msgs.extend(role_msgs)

            messages = [_("Member {0} {1}").format(member_name, status)]
            messages.extend(related_msgs)
            return {"success": True, "message": "; ".join(messages)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}

    def apply_changed_member(self, event) -> dict:
        """Update existing Member fields from MijnRood admin_member data.

        For status changes to terminated statuses, delegates to the
        termination_sync service which creates a Membership Termination
        Request rather than directly modifying the member.
        """
        new_data = safe_json_load(event.new_data)
        old_data = safe_json_load(event.old_data)
        changed_fields = safe_json_load(event.changed_fields, default=[])

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Check for status change to a terminated status — short-circuits the rest
        termination_result = get_termination_sync_service()._check_and_handle_termination(
            event, old_data, new_data, changed_fields
        )
        if termination_result is not None:
            return termination_result

        # Resolve linked member: event link → member_id → old email
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")
        if not member_name:
            old_email = (old_data or {}).get("email")
            if old_email:
                member_name = frappe.db.get_value("Member", {"email": old_email}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for MijnRood ID {0}").format(new_data.get("id")),
            }

        # Chapter transfer if division_id changed
        chapter_result = get_related_records_orchestrator()._handle_division_field_change(
            member_name, changed_fields, event, field_name="division_id"
        )

        row_data = get_mapping_service().map_member_fields(new_data)

        messages = []
        if chapter_result:
            messages.append(chapter_result)

        # Role-only events (e.g. synthetic division contact changes) carry only
        # managed_division_ids / roles — no mappable member fields. Skip the
        # member create/update path and go straight to role processing.
        if row_data:
            from verenigingen.services.csv_import.member_import_service import (
                get_member_import_service,
            )

            service = get_member_import_service()
            status, updated_name = service.create_or_update_member(
                row_data=row_data,
                import_doc_name=f"MijnRood Sync: {event.name}",
            )

            if status in ("created", "updated"):
                event.linked_member = updated_name
                member_name = updated_name
                messages.append(_("Member {0} updated").format(updated_name))

                messages.extend(
                    get_related_records_orchestrator()._create_related_records(updated_name, row_data, event)
                )
            else:
                return {"success": False, "message": _("Member update {0}").format(status)}

        role_msgs = get_volunteer_sync_service()._process_member_roles(
            member_name, new_data, old_data=old_data, event=event
        )
        messages.extend(role_msgs)

        return {
            "success": True,
            "message": "; ".join(messages) if messages else _("No changes applied"),
        }


_service_instance: Optional[MijnRoodMemberSyncService] = None


def get_member_sync_service() -> MijnRoodMemberSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMemberSyncService()
    return _service_instance
