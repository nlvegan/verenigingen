"""MijnRoodMemberSyncService — applies MijnRood member events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #2 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns the New-Member and Changed-Member event paths plus the
existing-member-or-conflict lookup. It delegates back to the calling
event-application orchestrator for cross-cutting helpers
(create_related_records, process_member_roles, try_promote_application,
check_and_handle_termination, handle_division_field_change) that have
not yet been extracted into their own services. The `orchestrator`
parameter on the public methods will be removed once all of those are
moved to their own services in later PRs.
"""

import logging
from typing import Optional

import frappe
from frappe import _

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
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

    def apply_new_member(self, event, orchestrator) -> dict:
        """Create a new Member from MijnRood admin_member data.

        Transitional `orchestrator` parameter exposes the not-yet-extracted
        cross-cutting helpers (_try_promote_application,
        _create_related_records, _process_member_roles). This parameter
        will be removed once those helpers are extracted in later PRs.
        """
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
                promotion_result = orchestrator._try_promote_application(event, row_data)
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

            related_msgs = orchestrator._create_related_records(member_name, row_data, event)
            role_msgs = orchestrator._process_member_roles(member_name, new_data, event=event)
            related_msgs.extend(role_msgs)

            messages = [_("Member {0} {1}").format(member_name, status)]
            messages.extend(related_msgs)
            return {"success": True, "message": "; ".join(messages)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}


_service_instance: Optional[MijnRoodMemberSyncService] = None


def get_member_sync_service() -> MijnRoodMemberSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMemberSyncService()
    return _service_instance
