"""
SEPA Mandate Lifecycle Service

This service handles SEPA mandate lifecycle management and status transitions.
Extracted from SEPA Mandate controller for better separation of concerns.
"""

from typing import Dict, Optional

import frappe
from frappe import _
from frappe.utils import getdate, today


class SEPAMandateLifecycleService:
    """Service for SEPA mandate lifecycle management and status transitions"""

    def __init__(self):
        pass

    def set_status_based_on_dates(self, mandate_doc) -> str:
        """
        Set mandate status based on validity dates and current date.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Calculated status based on dates
        """
        try:
            current_date = getdate()

            # If no dates are set, keep current status or default to Draft
            if not mandate_doc.sign_date and not mandate_doc.expiry_date:
                return mandate_doc.status or "Draft"

            # Check if mandate is not yet valid (sign date in future)
            if mandate_doc.sign_date and getdate(mandate_doc.sign_date) > current_date:
                return "Pending"

            # Check if mandate has expired
            if mandate_doc.expiry_date and getdate(mandate_doc.expiry_date) < current_date:
                return "Expired"

            # If we're within the valid period, only auto-activate if status is currently None/empty
            # Preserve explicitly set statuses like Draft, Suspended, etc.
            if not mandate_doc.status:
                return "Active"

            # For terminal states, don't change them
            if mandate_doc.status in ["Cancelled", "Rejected", "Expired"]:
                return mandate_doc.status

            # For other statuses (Draft, Suspended, etc.), preserve them
            # unless they need to be auto-expired
            return mandate_doc.status

        except Exception as e:
            frappe.log_error(f"Error in set_status_based_on_dates: {str(e)}", "SEPA Mandate Lifecycle")
            return mandate_doc.status or "Draft"

    def sync_status_and_active_flag(self, mandate_doc) -> None:
        """
        Synchronize status and is_active flag for consistency.

        Args:
            mandate_doc: SEPA Mandate document
        """
        try:
            # Ensure is_active flag matches status
            if mandate_doc.status == "Active":
                mandate_doc.is_active = 1
            else:
                mandate_doc.is_active = 0

        except Exception as e:
            frappe.log_error(f"Error in sync_status_and_active_flag: {str(e)}", "SEPA Mandate Lifecycle")

    def handle_status_transition(self, mandate_doc, old_status: Optional[str] = None) -> Dict[str, any]:
        """
        Handle status transitions with business rule validation.

        Args:
            mandate_doc: SEPA Mandate document
            old_status: Previous status for transition validation

        Returns:
            Dictionary with transition results
        """
        transition_result = {"success": True, "warnings": [], "errors": [], "notifications_sent": []}

        try:
            new_status = mandate_doc.status

            # Validate transition is allowed
            if old_status and not self._is_valid_status_transition(old_status, new_status):
                transition_result["errors"].append(
                    _("Invalid status transition from {0} to {1}").format(old_status, new_status)
                )
                transition_result["success"] = False
                return transition_result

            # Handle specific status transitions
            if new_status == "Active":
                self._handle_activation(mandate_doc, transition_result)
            elif new_status == "Cancelled":
                self._handle_cancellation(mandate_doc, transition_result)
            elif new_status == "Expired":
                self._handle_expiration(mandate_doc, transition_result)

            # Sync flags
            self.sync_status_and_active_flag(mandate_doc)

            return transition_result

        except Exception as e:
            frappe.log_error(f"Error in handle_status_transition: {str(e)}", "SEPA Mandate Lifecycle")
            transition_result["errors"].append(f"Status transition error: {str(e)}")
            transition_result["success"] = False
            return transition_result

    def process_mandate_cancellation(self, mandate_doc, reason: str = None) -> Dict[str, any]:
        """
        Process mandate cancellation with proper workflow.

        Args:
            mandate_doc: SEPA Mandate document
            reason: Optional cancellation reason

        Returns:
            Dictionary with cancellation results
        """
        cancellation_result = {"success": True, "warnings": [], "errors": [], "notifications_sent": []}

        try:
            # Validate cancellation is allowed
            if mandate_doc.status in ["Cancelled", "Expired"]:
                cancellation_result["warnings"].append(
                    _("Mandate is already {0}").format(mandate_doc.status.lower())
                )
                return cancellation_result

            # Set cancellation fields
            old_status = mandate_doc.status
            mandate_doc.status = "Cancelled"
            mandate_doc.is_active = 0
            mandate_doc.cancellation_date = today()
            if reason:
                mandate_doc.cancellation_reason = reason

            # Handle member integration
            self._update_member_mandate_status(mandate_doc, "Cancelled")

            # Send notifications if configured
            try:
                from verenigingen.verenigingen_payments.utils.sepa_notifications import (
                    SEPAMandateNotificationManager,
                )

                notification_manager = SEPAMandateNotificationManager()
                notification_manager.send_mandate_status_notification(mandate_doc, old_status, "Cancelled")
                cancellation_result["notifications_sent"].append("status_change")
            except Exception as e:
                cancellation_result["warnings"].append(f"Failed to send notification: {str(e)}")

            cancellation_result["warnings"].append(_("Mandate cancelled successfully"))
            return cancellation_result

        except Exception as e:
            frappe.log_error(f"Error in process_mandate_cancellation: {str(e)}", "SEPA Mandate Lifecycle")
            cancellation_result["errors"].append(f"Cancellation error: {str(e)}")
            cancellation_result["success"] = False
            return cancellation_result

    def _is_valid_status_transition(self, old_status: str, new_status: str) -> bool:
        """
        Validate if status transition is allowed.

        Args:
            old_status: Current status
            new_status: Target status

        Returns:
            True if transition is valid
        """
        # Define valid status transitions
        valid_transitions = {
            "Draft": ["Pending", "Active", "Cancelled"],
            "Pending": ["Active", "Cancelled", "Rejected"],
            "Active": ["Cancelled", "Expired"],
            "Cancelled": [],  # Terminal state
            "Expired": ["Cancelled"],  # Can only be cancelled after expiration
            "Rejected": ["Draft", "Cancelled"],  # Can be revised or cancelled
        }

        allowed_statuses = valid_transitions.get(old_status, [])
        return new_status in allowed_statuses

    def _handle_activation(self, mandate_doc, result: Dict) -> None:
        """Handle mandate activation workflow"""
        try:
            # Ensure required fields are present
            if not mandate_doc.mandate_id:
                result["errors"].append(_("Mandate ID is required for activation"))
                result["success"] = False
                return

            if not mandate_doc.iban:
                result["errors"].append(_("IBAN is required for activation"))
                result["success"] = False
                return

            # Update member integration
            self._update_member_mandate_status(mandate_doc, "Active")

            result["warnings"].append(_("Mandate activated successfully"))

        except Exception as e:
            result["errors"].append(f"Activation error: {str(e)}")
            result["success"] = False

    def _handle_cancellation(self, mandate_doc, result: Dict) -> None:
        """Handle mandate cancellation workflow"""
        try:
            # Set cancellation date if not already set
            if not mandate_doc.cancellation_date:
                mandate_doc.cancellation_date = today()

            # Update member integration
            self._update_member_mandate_status(mandate_doc, "Cancelled")

            result["warnings"].append(_("Mandate cancelled successfully"))

        except Exception as e:
            result["errors"].append(f"Cancellation error: {str(e)}")
            result["success"] = False

    def _handle_expiration(self, mandate_doc, result: Dict) -> None:
        """Handle mandate expiration workflow"""
        try:
            # Update member integration
            self._update_member_mandate_status(mandate_doc, "Expired")

            result["warnings"].append(_("Mandate expired"))

        except Exception as e:
            result["errors"].append(f"Expiration error: {str(e)}")
            result["success"] = False

    def _update_member_mandate_status(self, mandate_doc, status: str) -> None:
        """
        Update mandate status in member's mandate table.

        Args:
            mandate_doc: SEPA Mandate document
            status: New status to set
        """
        try:
            if not mandate_doc.member:
                return

            # This will be enhanced in Phase 2 with the member integration service
            # For now, just log the status change
            frappe.logger().info(
                f"Mandate {mandate_doc.name} status changed to {status} for member {mandate_doc.member}"
            )

        except Exception as e:
            frappe.log_error(f"Error updating member mandate status: {str(e)}", "SEPA Mandate Lifecycle")

    def handle_mandate_creation(self, mandate_doc) -> Dict[str, any]:
        """
        Handle mandate creation event with notifications.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with event handling results
        """
        event_result = {"success": True, "notifications_sent": [], "errors": []}

        try:
            # Update member's SEPA mandates child table first
            from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
                sepa_mandate_member_integration_service,
            )

            member_result = sepa_mandate_member_integration_service.update_member_mandate_relationship(
                mandate_doc
            )
            if not member_result["success"]:
                event_result["errors"].extend(member_result["errors"])

            # Send notifications if mandate is active
            if mandate_doc.status == "Active":
                try:
                    from verenigingen.verenigingen_payments.utils.sepa_notifications import (
                        SEPAMandateNotificationManager,
                    )

                    notification_manager = SEPAMandateNotificationManager()
                    notification_manager.send_mandate_created_notification(mandate_doc)
                    event_result["notifications_sent"].append("mandate_created")
                except Exception as e:
                    event_result["errors"].append(f"Notification failed: {str(e)}")

            return event_result

        except Exception as e:
            frappe.log_error(f"Error handling mandate creation: {str(e)}", "SEPA Mandate Lifecycle")
            event_result["errors"].append(str(e))
            event_result["success"] = False
            return event_result

    def handle_mandate_update(self, mandate_doc) -> Dict[str, any]:
        """
        Handle mandate update event with status change detection.

        Args:
            mandate_doc: SEPA Mandate document

        Returns:
            Dictionary with event handling results
        """
        event_result = {"success": True, "notifications_sent": [], "status_changed": False, "errors": []}

        try:
            # Check for status changes
            if mandate_doc.has_value_changed("status"):
                old_status = (
                    mandate_doc.get_doc_before_save().status if mandate_doc.get_doc_before_save() else None
                )
                event_result["status_changed"] = True

                # Handle status transition
                transition_result = self.handle_status_transition(mandate_doc, old_status)
                if not transition_result["success"]:
                    event_result["errors"].extend(transition_result["errors"])

                # Send notifications based on status changes
                try:
                    from verenigingen.verenigingen_payments.utils.sepa_notifications import (
                        SEPAMandateNotificationManager,
                    )

                    notification_manager = SEPAMandateNotificationManager()

                    if mandate_doc.status == "Active" and old_status != "Active":
                        # Mandate activated
                        notification_manager.send_mandate_created_notification(mandate_doc)
                        event_result["notifications_sent"].append("mandate_activated")
                    elif mandate_doc.status == "Cancelled" and old_status != "Cancelled":
                        # Mandate cancelled
                        reason = mandate_doc.cancellation_reason or "Cancelled by member request"
                        notification_manager.send_mandate_cancelled_notification(mandate_doc, reason)
                        event_result["notifications_sent"].append("mandate_cancelled")
                except Exception as e:
                    event_result["errors"].append(f"Notification failed: {str(e)}")

            # Always update member's SEPA mandates child table when mandate is updated
            if mandate_doc.member:
                from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
                    sepa_mandate_member_integration_service,
                )

                member_result = sepa_mandate_member_integration_service.update_member_mandate_relationship(
                    mandate_doc
                )
                if not member_result["success"]:
                    event_result["errors"].extend(member_result["errors"])

            return event_result

        except Exception as e:
            frappe.log_error(f"Error handling mandate update: {str(e)}", "SEPA Mandate Lifecycle")
            event_result["errors"].append(str(e))
            event_result["success"] = False
            return event_result


# Singleton instance for global use
sepa_mandate_lifecycle_service = SEPAMandateLifecycleService()
