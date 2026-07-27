"""MijnRoodTerminationSyncService — routes terminated-status transitions.

Extracted from event_application_service.py as Phase 1, PR #5 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns one method: _check_and_handle_termination. When a
MijnRood admin_member row transitions from an active to a terminated
status, it creates a Membership Termination Request and delegates
execution to TerminationExecutionService.
"""

from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import (
    get_active_status_ids,
    get_terminated_status_ids,
    get_termination_type_map,
)
from verenigingen.mijnrood_sync.utils import safe_int
from verenigingen.utils.service_logger import get_service_logger

logger = get_service_logger("verenigingen.mijnrood_sync", prefix="event_application.termination_sync")


class MijnRoodTerminationSyncService:
    """Routes terminated-status transitions to MTR + TerminationExecutionService."""

    def __init__(self):
        self.logger = logger

    def _check_and_handle_termination(
        self,
        event,
        old_data: dict,
        new_data: dict,
        changed_fields: list,
    ) -> Optional[dict]:
        """Check if this change involves a status transition to terminated.

        If so, creates a Membership Termination Request using the existing
        workflow instead of directly setting the member status.

        Returns:
            Result dict if termination was handled, None otherwise
        """
        # Find the status field change
        status_change = None
        for change in changed_fields:
            if change.get("field") == "current_membership_status_id":
                status_change = change
                break

        if not status_change:
            return None

        old_status_id = safe_int(status_change.get("old"))
        new_status_id = safe_int(status_change.get("new"))

        # Only handle transitions FROM active TO terminated
        if new_status_id not in get_terminated_status_ids():
            return None
        if old_status_id not in get_active_status_ids():
            # Already in a non-active state, just update the status field
            return None

        # Find the linked member
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
                "message": _(
                    "Cannot create termination request: no linked member for MijnRood ID {0}"
                ).format(new_data.get("id")),
            }

        member_doc = frappe.get_doc("Member", member_name)

        # Skip if member is already in a terminal state
        if member_doc.status in ("Quit", "Banned", "Deceased"):
            return {
                "success": True,
                "message": _("Member {0} already has status {1}, skipping termination").format(
                    member_name, member_doc.status
                ),
            }

        # Create Membership Termination Request
        termination_type = get_termination_type_map().get(new_status_id, "Administrative")

        termination_doc = frappe.new_doc("Membership Termination Request")
        termination_doc.member = member_name
        termination_doc.termination_type = termination_type
        termination_doc.termination_reason = (
            f"Detected via MijnRood sync (event {event.name}): " f"status changed to {new_status_id}"
        )
        termination_doc.request_date = today()
        termination_doc.termination_date = today()
        termination_doc.notes = (
            f"Auto-created from MijnRood sync event {event.name}. "
            f"MijnRood status changed from {old_status_id} to {new_status_id}."
        )

        # For Voluntary and Deceased, set member_request_date
        if termination_type in ("Voluntary", "Deceased"):
            termination_doc.member_request_date = today()

        # Pre-approve since this is a sync from the authoritative system
        termination_doc.status = "Approved"
        termination_doc._csv_import = True  # Bypass workflow validation
        termination_doc.flags.skip_termination_validation = (
            True  # System-initiated, skip commitment/doc checks
        )

        # Security: System-initiated termination from authoritative MijnRood data
        termination_doc.insert(ignore_permissions=True)
        self.logger.info(
            "Created termination request %s for member %s (type=%s)",
            termination_doc.name,
            member_name,
            termination_type,
        )

        # Auto-execute: MijnRood is authoritative, termination already happened there
        from verenigingen.services.termination import TerminationExecutionService

        try:
            TerminationExecutionService().execute(termination_doc)
            self.logger.info(
                "Executed termination %s for member %s",
                termination_doc.name,
                member_name,
            )
        except Exception as e:
            self.logger.error(
                "Termination request %s created but execution failed: %s",
                termination_doc.name,
                e,
            )
            frappe.log_error(
                frappe.get_traceback(),
                f"MijnRood Termination Execution Failed: {termination_doc.name}",
            )
            return {
                "success": False,
                "message": _("Termination request {0} created but execution failed: {1}").format(
                    termination_doc.name, str(e)
                ),
            }

        return {
            "success": True,
            "message": _("Termination request {0} executed for member {1} (type: {2})").format(
                termination_doc.name, member_name, termination_type
            ),
        }


_service_instance: Optional[MijnRoodTerminationSyncService] = None


def get_termination_sync_service() -> MijnRoodTerminationSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodTerminationSyncService()
    return _service_instance
