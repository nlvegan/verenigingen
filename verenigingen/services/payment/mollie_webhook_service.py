"""
Mollie Webhook Management Service

Provides webhook URL management for Mollie subscriptions, including:
- Fetching current webhook URLs from active subscriptions
- Bulk updating webhook URLs across multiple subscriptions
- Retrieving default webhook URLs from settings
"""

from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService


class MollieWebhookService:
    """
    Service for managing Mollie subscription webhook URLs.

    This service provides capabilities for:
    - Retrieving active subscriptions with their webhook URLs
    - Bulk updating webhook URLs across subscriptions
    - Getting default webhook configuration from settings
    """

    ALLOWED_ROLES = [
        "System Manager",
        "Administrator",
        "Verenigingen Administrator",
        "Verenigingen Staff",
    ]

    def __init__(self):
        self._debug_service: Optional[MollieDebugService] = None

    @property
    def debug_service(self) -> MollieDebugService:
        """Lazy-load the debug service."""
        if self._debug_service is None:
            self._debug_service = MollieDebugService()
        return self._debug_service

    def has_admin_access(self) -> bool:
        """Check if current user has access to webhook management functions."""
        user_roles = frappe.get_roles(frappe.session.user)
        return any(role in self.ALLOWED_ROLES for role in user_roles)

    def get_default_webhook_url(self) -> Dict[str, Any]:
        """
        Get the default webhook URL from Mollie Settings based on current mode.

        Returns:
            Dict with webhook_url, test_mode, and mode_label
        """
        mollie_settings = frappe.get_single("Mollie Settings")
        test_mode = mollie_settings.test_mode

        if test_mode:
            webhook_url = mollie_settings.testing_webhook_url
        else:
            webhook_url = mollie_settings.live_webhook_url

        return {
            "webhook_url": webhook_url,
            "test_mode": test_mode,
            "mode_label": "Test" if test_mode else "Live",
        }

    def get_active_subscriptions_with_webhooks(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch all active Mollie subscriptions with their current webhook URLs.

        Args:
            progress_callback: Optional callback(message, progress_percent) for updates

        Returns:
            Dict with subscriptions list, errors, counts, and default webhook info
        """
        self._report_progress(progress_callback, "Fetching active subscriptions...", 10)

        # Get all members with active Mollie subscriptions
        members_with_subscriptions = frappe.get_all(
            "Member",
            filters={
                "mollie_customer_id": ["is", "set"],
                "mollie_subscription_id": ["is", "set"],
                "subscription_status": "Active",
            },
            fields=[
                "name",
                "full_name",
                "mollie_customer_id",
                "mollie_subscription_id",
            ],
        )

        subscriptions = []
        errors = []

        total = len(members_with_subscriptions)
        for idx, member in enumerate(members_with_subscriptions):
            try:
                # Get subscription details from Mollie
                result = self.debug_service.debug_subscription(
                    member.mollie_subscription_id,
                    member.mollie_customer_id,
                )

                if result.get("subscription_found"):
                    sub_data = result.get("subscription_data", {})
                    subscriptions.append(
                        {
                            "member_id": member.name,
                            "member_name": member.full_name or member.name,
                            "customer_id": member.mollie_customer_id,
                            "subscription_id": member.mollie_subscription_id,
                            "status": sub_data.get("status"),
                            "current_webhook_url": sub_data.get("webhook_url"),
                            "amount": sub_data.get("amount"),
                            "interval": sub_data.get("interval"),
                        }
                    )
                elif result.get("error"):
                    errors.append(
                        {
                            "member_id": member.name,
                            "subscription_id": member.mollie_subscription_id,
                            "error": result.get("error"),
                        }
                    )

            except Exception as e:
                errors.append(
                    {
                        "member_id": member.name,
                        "subscription_id": member.mollie_subscription_id,
                        "error": str(e),
                    }
                )

            # Update progress
            if (idx + 1) % 10 == 0 or idx == total - 1:
                progress = int(10 + (idx + 1) / total * 80)
                self._report_progress(
                    progress_callback,
                    f"Processed {idx + 1}/{total} members...",
                    progress,
                )

        # Get default webhook URL for comparison
        default_info = self.get_default_webhook_url()

        self._report_progress(progress_callback, "Complete!", 100)

        return {
            "subscriptions": subscriptions,
            "errors": errors,
            "total_found": len(subscriptions),
            "total_errors": len(errors),
            "default_webhook_url": default_info["webhook_url"],
            "test_mode": default_info["test_mode"],
        }

    def bulk_update_webhooks(
        self,
        subscriptions: List[Dict[str, str]],
        new_webhook_url: str,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Update webhook URLs for multiple subscriptions.

        Args:
            subscriptions: List of dicts with customer_id and subscription_id
            new_webhook_url: The new webhook URL to set
            progress_callback: Optional callback(message, progress_percent) for updates

        Returns:
            Dict with results list, summary counts, and new webhook URL

        Raises:
            ValueError: If webhook URL is missing or invalid
        """
        if not new_webhook_url:
            raise ValueError(_("Webhook URL is required"))

        if not new_webhook_url.startswith("https://"):
            raise ValueError(_("Webhook URL must use HTTPS"))

        if not subscriptions:
            raise ValueError(_("No subscriptions provided"))

        results = []
        success_count = 0
        error_count = 0

        total = len(subscriptions)
        for idx, sub in enumerate(subscriptions):
            customer_id = sub.get("customer_id")
            subscription_id = sub.get("subscription_id")

            result = {
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "status": "pending",
                "error": None,
            }

            try:
                update_result = self.debug_service.update_subscription_webhook(
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                    webhook_url=new_webhook_url,
                    reason="Bulk webhook URL update via audit page",
                )

                if update_result.get("status") == "success":
                    result["status"] = "success"
                    result["old_webhook_url"] = update_result.get("old_webhook_url")
                    success_count += 1
                else:
                    result["status"] = "error"
                    result["error"] = update_result.get("message", "Unknown error")
                    error_count += 1

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                error_count += 1

            results.append(result)

            # Update progress
            if (idx + 1) % 5 == 0 or idx == total - 1:
                progress = int((idx + 1) / total * 100)
                self._report_progress(
                    progress_callback,
                    f"Updated {idx + 1}/{total}...",
                    progress,
                )

        return {
            "results": results,
            "summary": {
                "total": total,
                "success": success_count,
                "errors": error_count,
            },
            "new_webhook_url": new_webhook_url,
        }

    def _report_progress(
        self,
        callback: Optional[Callable[[str, int], None]],
        message: str,
        progress: int,
    ) -> None:
        """Report progress via callback if provided."""
        if callback:
            callback(message, progress)


# Convenience function
def get_mollie_webhook_service() -> MollieWebhookService:
    """Get a MollieWebhookService instance."""
    return MollieWebhookService()
