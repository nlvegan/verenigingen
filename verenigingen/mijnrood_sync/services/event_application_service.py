"""
MijnRood Event Application Service

Applies approved sync events to Verenigingen data. Handles:
- New members: creates Member documents
- Changed members: updates existing Member fields
- Status changes to terminated: creates Membership Termination Requests
  (uses the existing termination workflow rather than directly setting status)
- Deleted rows: flagged for review, never auto-applied

Reuses existing patterns from:
- MemberImportService for field mapping and member creation
- MemberLookupService for member matching
- Membership Termination Request workflow for termination handling
"""

import json
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from verenigingen.mijnrood_sync.field_mapping import (
    ACTIVE_STATUS_IDS,
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    STATUS_ID_TO_TERMINATION_TYPE,
    TERMINATED_STATUS_IDS,
)
from verenigingen.services.infrastructure.base_service import StatefulService


class MijnRoodEventApplicationService(StatefulService):
    """Applies approved MijnRood Sync Events to Verenigingen data."""

    def __init__(self):
        super().__init__(service_name="MijnRoodEventApplicationService")

    def apply_event(self, event_name: str) -> dict:
        """Apply a single approved sync event.

        Args:
            event_name: Name of the MijnRood Sync Event document

        Returns:
            Dict with success status and message
        """
        event = frappe.get_doc("MijnRood Sync Event", event_name)

        if event.status != "Approved":
            return {"success": False, "message": _("Only Approved events can be applied")}

        try:
            if event.event_type == "New":
                result = self._apply_new(event)
            elif event.event_type == "Changed":
                result = self._apply_changed(event)
            elif event.event_type == "Deleted":
                result = self._apply_deleted(event)
            else:
                result = {"success": False, "message": _("Unknown event type: {0}").format(event.event_type)}

            if result["success"]:
                event.status = "Applied"
                event.applied_at = now_datetime()
                event.error_message = None
            else:
                event.error_message = result.get("message", "")[:500]

            # Security: System-internal sync event status update, not user-facing
            event.save(ignore_permissions=True)
            frappe.db.commit()
            return result

        except Exception as e:
            error_msg = str(e)[:500]
            self.logger.error("Failed to apply event %s: %s", event_name, error_msg)
            frappe.log_error(frappe.get_traceback(), f"MijnRood Event Application Failed: {event_name}")

            event.reload()
            event.error_message = error_msg
            # Security: System-internal error recording on sync event
            event.save(ignore_permissions=True)
            frappe.db.commit()

            return {"success": False, "message": error_msg}

    def _apply_new(self, event) -> dict:
        """Apply a 'New' event — create a new Member from MijnRood data.

        Uses MemberImportService patterns for field mapping and creation.
        """
        if event.mijnrood_table != "admin_member":
            return {
                "success": True,
                "message": _("Non-member table '{0}' — recorded for reference only").format(
                    event.mijnrood_table
                ),
            }

        new_data = json.loads(event.new_data) if event.new_data else {}
        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        row_data = self._map_mijnrood_to_member_fields(new_data)

        # Check if member already exists (idempotency)
        existing = frappe.db.get_value("Member", {"member_id": row_data.get("member_id")}, "name")
        if existing:
            return {
                "success": True,
                "message": _("Member {0} already exists (member_id={1})").format(
                    existing, row_data.get("member_id")
                ),
            }

        # Use MemberImportService for consistent creation logic
        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, member_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status in ("created", "updated"):
            # Link the event to the member
            event.linked_member = member_name
            return {"success": True, "message": _("Member {0} {1}").format(member_name, status)}
        else:
            return {"success": False, "message": _("Member creation {0}").format(status)}

    def _apply_changed(self, event) -> dict:
        """Apply a 'Changed' event — update existing Member fields.

        For status changes to terminated statuses, creates a Membership
        Termination Request rather than directly modifying the member,
        since termination involves multiple documents (membership, mandates,
        user accounts, etc.) managed by the termination workflow.
        """
        if event.mijnrood_table != "admin_member":
            return {
                "success": True,
                "message": _("Non-member table '{0}' — recorded for reference only").format(
                    event.mijnrood_table
                ),
            }

        new_data = json.loads(event.new_data) if event.new_data else {}
        old_data = json.loads(event.old_data) if event.old_data else {}
        changed_fields = json.loads(event.changed_fields) if event.changed_fields else []

        if not new_data:
            return {"success": False, "message": _("No new data in event")}

        # Check for status change to a terminated status
        termination_result = self._check_and_handle_termination(event, old_data, new_data, changed_fields)
        if termination_result is not None:
            return termination_result

        # Apply non-termination field changes to the member
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _("No linked member found for MijnRood ID {0}").format(new_data.get("id")),
            }

        row_data = self._map_mijnrood_to_member_fields(new_data)

        from verenigingen.services.csv_import.member_import_service import get_member_import_service

        service = get_member_import_service()
        status, updated_name = service.create_or_update_member(
            row_data=row_data,
            import_doc_name=f"MijnRood Sync: {event.name}",
        )

        if status in ("created", "updated"):
            event.linked_member = updated_name
            return {"success": True, "message": _("Member {0} updated").format(updated_name)}
        else:
            return {"success": False, "message": _("Member update {0}").format(status)}

    def _apply_deleted(self, event) -> dict:
        """Handle a 'Deleted' event.

        Deleted rows are never auto-applied — they are recorded for
        reference. The user must manually handle member deletion/archiving.
        """
        return {
            "success": True,
            "message": _("Deleted event recorded. Member deletion requires manual review."),
        }

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
            if change.get("field") == "currentMembershipStatus_id":
                status_change = change
                break

        if not status_change:
            return None

        old_status_id = self._safe_int(status_change.get("old"))
        new_status_id = self._safe_int(status_change.get("new"))

        # Only handle transitions FROM active TO terminated
        if new_status_id not in TERMINATED_STATUS_IDS:
            return None
        if old_status_id not in ACTIVE_STATUS_IDS:
            # Already in a non-active state, just update the status field
            return None

        # Find the linked member
        member_name = event.linked_member
        if not member_name:
            member_name = frappe.db.get_value("Member", {"member_id": new_data.get("id")}, "name")

        if not member_name:
            return {
                "success": False,
                "message": _(
                    "Cannot create termination request: no linked member for MijnRood ID {0}"
                ).format(new_data.get("id")),
            }

        member_doc = frappe.get_doc("Member", member_name)

        # Skip if member is already in a terminal state
        if member_doc.status in ("Terminated", "Banned", "Deceased"):
            return {
                "success": True,
                "message": _("Member {0} already has status {1}, skipping termination").format(
                    member_name, member_doc.status
                ),
            }

        # Create Membership Termination Request
        termination_type = STATUS_ID_TO_TERMINATION_TYPE.get(new_status_id, "Administrative")

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

        # Security: System-initiated termination from authoritative MijnRood data
        termination_doc.insert(ignore_permissions=True)
        self.logger.info(
            "Created termination request %s for member %s (type=%s)",
            termination_doc.name,
            member_name,
            termination_type,
        )

        return {
            "success": True,
            "message": _("Termination request {0} created for member {1} (type: {2})").format(
                termination_doc.name, member_name, termination_type
            ),
        }

    def _map_mijnrood_to_member_fields(self, mijnrood_data: dict) -> dict:
        """Map MijnRood database row to intermediate field names.

        These intermediate names match what MemberImportService.update_member_fields()
        expects (same names as csv_data_validator.py FIELD_MAPPING values).
        """
        from verenigingen.mijnrood_sync.field_mapping import (
            CONTRIBUTION_PERIOD_MAP,
            MIJNROOD_STATUS_ID_MAP,
        )

        row_data = {}
        for mijnrood_col, member_field in MIJNROOD_TO_MEMBER_FIELD_MAP.items():
            value = mijnrood_data.get(mijnrood_col)
            if value is not None and value != "":
                row_data[member_field] = value

        # Convert status ID to membership type string
        status_id = self._safe_int(mijnrood_data.get("currentMembershipStatus_id"))
        if status_id and status_id in MIJNROOD_STATUS_ID_MAP:
            row_data["membership_type"] = MIJNROOD_STATUS_ID_MAP[status_id]

        # Convert contribution amount from cents to euros
        cents = self._safe_int(mijnrood_data.get("contributionPerPeriodInCents"))
        if cents:
            row_data["dues_rate"] = cents / 100.0

        # Convert contribution period
        period = mijnrood_data.get("contributionPeriod")
        if period:
            row_data["payment_period"] = CONTRIBUTION_PERIOD_MAP.get(str(period).lower(), str(period))

        return row_data

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        """Safely convert a value to int, returning None on failure."""
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


# Module-level singleton accessor
_service_instance: Optional[MijnRoodEventApplicationService] = None


def get_event_application_service() -> MijnRoodEventApplicationService:
    """Get singleton instance of MijnRoodEventApplicationService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodEventApplicationService()
    return _service_instance


# ─────────────────────────────────────────────────────────────────────
# Whitelisted API methods for batch operations from list view
# ─────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def batch_approve(event_names: str | list) -> dict:
    """Approve multiple sync events at once.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    approved = 0
    errors = []
    for name in event_names:
        try:
            event = frappe.get_doc("MijnRood Sync Event", name)
            if event.status == "Pending":
                event.approve()
                approved += 1
        except Exception as e:
            errors.append(f"{name}: {str(e)[:100]}")

    frappe.db.commit()
    return {"approved": approved, "errors": errors}


@frappe.whitelist()
def batch_apply(event_names: str | list) -> dict:
    """Apply multiple approved sync events.

    Args:
        event_names: JSON string or list of event names
    """
    if isinstance(event_names, str):
        event_names = json.loads(event_names)

    service = get_event_application_service()
    applied = 0
    errors = []
    for name in event_names:
        result = service.apply_event(name)
        if result.get("success"):
            applied += 1
        else:
            errors.append(f"{name}: {result.get('message', 'Unknown error')}")

    return {"applied": applied, "errors": errors}
