# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Event Emission Service

Handles emitting events when member status changes occur.
Extracted from Member DocType's on_update() method.

This service:
- Checks if event emission should be skipped (bulk ops, imports, tests)
- Emits application status change events
- Emits membership status change events
- Triggers status change notifications
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberEventEmissionService(StatelessService):
    """Service for emitting member status change events."""

    def should_skip_event_emission(self) -> bool:
        """Check if event emission should be skipped.

        Event emission is skipped during:
        - Bulk member operations
        - CSV/bulk imports
        - Test runs

        Returns:
            bool: True if events should be skipped
        """
        return (
            getattr(frappe.flags, "bulk_member_operations", False)
            or getattr(frappe.flags, "in_bulk_import", False)
            or getattr(frappe.flags, "in_test", False)
        )

    def emit_status_change_events(self, member_doc: "Document") -> dict:
        """Emit events for status changes on a member document.

        Args:
            member_doc: The Member document that was updated

        Returns:
            dict: Summary of events emitted
        """
        result = {
            "skipped": False,
            "application_status_event": False,
            "membership_status_event": False,
            "notification_sent": False,
            "errors": [],
        }

        try:
            # Check if we should skip
            if self.should_skip_event_emission():
                result["skipped"] = True
                return result

            # Handle application status changes
            if member_doc.has_value_changed("application_status"):
                self._emit_application_status_event(member_doc)
                result["application_status_event"] = True

            # Handle membership status changes
            if member_doc.has_value_changed("status"):
                self._emit_membership_status_event(member_doc)
                result["membership_status_event"] = True

                # Send notification for membership status changes
                self._send_status_notification(member_doc)
                result["notification_sent"] = True

        except Exception as e:
            # Event emission should never block member updates
            frappe.log_error(
                f"Failed to emit member events for {member_doc.name}: {str(e)}",
                "Member Event Emission Error",
            )
            result["errors"].append(str(e))

        return result

    def _emit_application_status_event(self, member_doc: "Document") -> None:
        """Emit event for application status change.

        Args:
            member_doc: The Member document
        """
        from verenigingen.events.member_events import emit_member_status_changed

        old_status = member_doc.get_db_value("application_status")
        new_status = member_doc.application_status

        frappe.logger().info(
            f"Member {member_doc.name} application status changed: {old_status} -> {new_status}"
        )

        emit_member_status_changed(
            member_doc.name,
            {"old_status": old_status, "new_status": new_status, "status_type": "application"},
        )

    def _emit_membership_status_event(self, member_doc: "Document") -> None:
        """Emit event for membership status change.

        Args:
            member_doc: The Member document
        """
        from verenigingen.events.member_events import emit_member_lifecycle_changed

        old_status = member_doc.get_db_value("status")
        new_status = member_doc.status

        frappe.logger().info(f"Member {member_doc.name} status changed: {old_status} -> {new_status}")

        emit_member_lifecycle_changed(
            member_doc.name,
            {"old_status": old_status, "new_status": new_status, "status_type": "membership"},
        )

    def _send_status_notification(self, member_doc: "Document") -> None:
        """Send notification for membership status change.

        Args:
            member_doc: The Member document
        """
        old_status = member_doc.get_db_value("status")
        new_status = member_doc.status

        # Delegate to member's notification method (which uses MemberStatusNotificationService)
        member_doc._send_member_status_notification(old_status, new_status)


# Module-level singleton accessor
_service_instance: Optional[MemberEventEmissionService] = None


def get_member_event_emission_service() -> MemberEventEmissionService:
    """Get or create the MemberEventEmissionService singleton.

    Returns:
        MemberEventEmissionService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberEventEmissionService()
    return _service_instance
