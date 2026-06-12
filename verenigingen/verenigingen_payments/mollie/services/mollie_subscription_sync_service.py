"""
Mollie Subscription Sync Service

Handles synchronization of Mollie subscriptions when membership amendments are applied.
Implements event-driven architecture for loose coupling between amendment system and Mollie.
"""

from typing import Dict, Optional, Tuple

import frappe
from frappe import _

from ..core.client import MollieClient
from ..exceptions import MollieIntegrationError
from ..utils.amount_helpers import extract_amount_float
from ..utils.common_helpers import format_mollie_amount
from .subscription_description import get_member_subscription_description
from .subscription_service import SubscriptionService

# Billing interval mapping to Mollie format
BILLING_INTERVAL_TO_MOLLIE_FORMAT = {
    "Monthly": "1 month",
    "Quarterly": "3 months",
    "Semi-Annually": "6 months",
    "Annually": "12 months",
}


class MollieSubscriptionSyncService:
    """
    Service for syncing Mollie subscriptions with membership amendments.

    Handles the complete workflow of canceling old subscriptions and creating
    new ones when membership terms change, with verification and retry logic.
    """

    def __init__(self, client: Optional[MollieClient] = None):
        """Initialize sync service."""
        self.client = client or MollieClient()
        self.subscription_service = SubscriptionService(self.client)

    def sync_subscription_for_amendment(self, amendment_doc) -> Dict[str, any]:
        """
        Sync Mollie subscription when amendment is applied.

        Args:
            amendment_doc: ContributionAmendmentRequest document

        Returns:
            Dict with sync result status and details
        """
        frappe.logger().info(f"🔄 Starting Mollie subscription sync for amendment {amendment_doc.name}")

        try:
            # Get membership and member
            membership = frappe.get_doc("Membership", amendment_doc.membership)
            member = frappe.get_doc("Member", membership.member)

            # SECURITY: Validate user has permission to modify member subscriptions
            if not frappe.has_permission("Member", "write", member.name):
                frappe.logger().warning(
                    f"⚠️ User {frappe.session.user} does not have permission to modify subscriptions for member {member.name}"
                )
                return {
                    "status": "error",
                    "reason": "permission_denied",
                    "message": "User does not have permission to modify member subscriptions",
                }

            # Check if member has Mollie subscription
            if not member.mollie_customer_id:
                frappe.logger().info(f"⚠️ Member {member.name} has no Mollie customer ID, skipping sync")
                return {
                    "status": "skipped",
                    "reason": "no_mollie_customer",
                    "message": "Member does not have Mollie customer ID",
                }

            if not member.mollie_subscription_id:
                frappe.logger().info(f"⚠️ Member {member.name} has no Mollie subscription, skipping sync")
                return {
                    "status": "skipped",
                    "reason": "no_mollie_subscription",
                    "message": "Member does not have active Mollie subscription",
                }

            # Store old subscription ID for cancellation
            old_subscription_id = member.mollie_subscription_id

            # Get subscription details from Mollie to preserve billing cycle
            old_subscription = self.subscription_service.get_subscription_status(
                member.mollie_customer_id, old_subscription_id
            )

            # Determine new subscription parameters from amendment
            new_amount, new_interval = self._get_subscription_parameters(amendment_doc, membership)

            # Amount-only change: PATCH the live subscription in place.
            # The subscription id stays stable; drifted description/webhook
            # values are repaired in the same call.
            if new_interval == old_subscription.get("interval"):
                return self._patch_subscription_amount(member, amendment_doc, old_subscription, new_amount)

            # Interval changed: replacement path. Validate the mandate that
            # the NEW subscription will charge against. The live subscription
            # is the authoritative mandate source; the Member field is only a
            # fallback (it was historically never populated).
            replacement_mandate_id = self._mandate_id_for_replacement(member, old_subscription)
            if replacement_mandate_id:
                try:
                    raw_mollie_client = self.client._get_mollie_client()
                    customer_obj = raw_mollie_client.customers.get(member.mollie_customer_id)
                    mandate = customer_obj.mandates.get(replacement_mandate_id)
                    if mandate.status not in ["valid", "pending"]:
                        return {
                            "status": "error",
                            "reason": "invalid_mandate",
                            "message": f"SEPA mandate is {mandate.status}. Cannot create new subscription. Please renew mandate first.",
                            "requires_admin_review": True,
                        }
                except Exception as mandate_error:
                    return {
                        "status": "error",
                        "reason": "mandate_validation_failed",
                        "message": f"Could not validate SEPA mandate: {str(mandate_error)}",
                        "requires_admin_review": True,
                    }

            # TRANSACTION SAFETY: Create new subscription first, then cancel old one
            # This prevents leaving member without active subscription if creation fails
            new_subscription = None

            try:
                # Step 1: Create new subscription with future start_date (preserves billing cycle)
                frappe.logger().info(
                    f"✨ Creating new subscription for member {member.name} with amount {new_amount}, interval {new_interval}"
                )

                new_subscription = self._create_replacement_subscription(
                    member=member,
                    amount=new_amount,
                    interval=new_interval,
                    start_date=old_subscription.get("next_payment_date"),  # Preserve billing cycle
                    amendment_name=amendment_doc.name,
                    previous_subscription_id=old_subscription_id,
                )

                frappe.logger().info(
                    f"✅ New subscription {new_subscription.id} created, will start on {old_subscription.get('next_payment_date')}"
                )

                # Step 2: Cancel old subscription (safe now that new one exists)
                frappe.logger().info(
                    f"🗑️ Canceling old subscription {old_subscription_id} for member {member.name}"
                )
                self.subscription_service.cancel_subscription(
                    member.mollie_customer_id,
                    old_subscription_id,
                    reason=f"Amendment {amendment_doc.name}: {amendment_doc.amendment_type} - Replaced by {new_subscription.id}",
                )

                # Step 3: Update member with new subscription ID
                member.db_set("mollie_subscription_id", new_subscription.id, update_modified=False)

            except Exception as sync_error:
                # ROLLBACK LOGIC: If new subscription was created, we need to cancel it
                frappe.logger().error(
                    f"❌ Subscription sync failed for member {member.name}: {str(sync_error)}"
                )

                if new_subscription:
                    # New subscription created but cancellation or member update failed
                    # We need to decide: keep new subscription or roll it back?

                    # Check if old subscription was cancelled
                    try:
                        old_sub_status = self.subscription_service.get_subscription_status(
                            member.mollie_customer_id, old_subscription_id
                        )
                        old_sub_cancelled = old_sub_status.get("status") == "canceled"
                    except:
                        old_sub_cancelled = False

                    if old_sub_cancelled:
                        # Old subscription cancelled, new one created - just need to fix member record
                        frappe.logger().warning(
                            f"⚠️ Subscriptions swapped successfully but member record update failed for {member.name}"
                        )

                        try:
                            member.reload()
                            member.db_set(
                                "mollie_subscription_id", new_subscription.id, update_modified=False
                            )

                            return {
                                "status": "warning",
                                "subscription_id": new_subscription.id,
                                "old_subscription_id": old_subscription_id,
                                "message": "Subscription swap successful but member record update initially failed. Retry successful.",
                                "requires_admin_review": True,
                            }

                        except Exception as update_retry_error:
                            frappe.log_error(
                                f"Subscription swap successful but member record update failed for {member.name}\n"
                                f"New subscription: {new_subscription.id}\n"
                                f"Old subscription: {old_subscription_id} (cancelled)\n"
                                f"Error: {str(update_retry_error)}",
                                "Mollie Subscription Member Update Failure",
                            )

                            return {
                                "status": "error",
                                "subscription_id": new_subscription.id,
                                "old_subscription_id": old_subscription_id,
                                "message": f"Subscription swap successful but member record shows old subscription {old_subscription_id}. Manual update to {new_subscription.id} required.",
                                "requires_admin_review": True,
                            }

                    else:
                        # Old subscription still active, new one created - need to cancel new one
                        frappe.logger().warning(
                            f"⚠️ New subscription {new_subscription.id} created but old subscription cancellation failed. Rolling back."
                        )

                        try:
                            self.subscription_service.cancel_subscription(
                                member.mollie_customer_id,
                                new_subscription.id,
                                reason=f"Rollback after failed amendment {amendment_doc.name}",
                            )

                            frappe.logger().info(
                                f"✅ Rolled back new subscription {new_subscription.id}. Member {member.name} still has original subscription {old_subscription_id}"
                            )

                            return {
                                "status": "error",
                                "message": f"Subscription swap failed, rollback successful. Member still has original subscription: {str(sync_error)}",
                                "requires_admin_review": True,
                                "rollback_successful": True,
                            }

                        except Exception as rollback_error:
                            frappe.log_error(
                                f"🚨 CRITICAL: Failed to rollback new subscription {new_subscription.id} for member {member.name}\n"
                                f"Original error: {str(sync_error)}\n"
                                f"Rollback error: {str(rollback_error)}\n"
                                f"Member now has TWO active subscriptions:\n"
                                f"- Old: {old_subscription_id}\n"
                                f"- New: {new_subscription.id}\n"
                                f"Manual cancellation of one subscription required.",
                                "Mollie Subscription Sync Critical Failure",
                            )

                            return {
                                "status": "error",
                                "message": f"CRITICAL: Member has two active subscriptions ({old_subscription_id} and {new_subscription.id}). Manual intervention required to cancel one.",
                                "requires_admin_review": True,
                                "rollback_successful": False,
                                "critical_failure": True,
                                "duplicate_subscriptions": [old_subscription_id, new_subscription.id],
                            }

                else:
                    # New subscription creation failed before completion - safe state
                    frappe.logger().info(
                        f"New subscription creation failed for member {member.name}. Original subscription {old_subscription_id} still active."
                    )

                    return {
                        "status": "error",
                        "message": f"Failed to create new subscription. Original subscription unchanged: {str(sync_error)}",
                        "requires_admin_review": True,
                    }

                # Re-raise for outer exception handler if not handled above
                raise

            frappe.logger().info(f"✅ Created new subscription {new_subscription.id} for member {member.name}")

            # Verify subscription amount matches dues schedule
            verification_result = self._verify_subscription_amount(
                member, membership, new_subscription.id, new_amount, retry_on_mismatch=True
            )

            if not verification_result["verified"]:
                return {
                    "status": "warning",
                    "subscription_id": new_subscription.id,
                    "old_subscription_id": old_subscription_id,
                    "message": verification_result["message"],
                    "requires_admin_review": True,
                }

            return {
                "status": "success",
                "subscription_id": new_subscription.id,
                "old_subscription_id": old_subscription_id,
                "amount": float(new_amount),
                "interval": new_interval,
                "next_payment_date": old_subscription.get("next_payment_date"),
                "message": "Subscription synced successfully",
            }

        except MollieIntegrationError as e:
            frappe.log_error(
                f"Mollie subscription sync failed for amendment {amendment_doc.name}: {str(e)}",
                "Mollie Subscription Sync Error",
            )
            return {
                "status": "error",
                "message": f"Mollie API error: {str(e)}",
                "requires_admin_review": True,
            }

        except Exception as e:
            frappe.log_error(
                f"Unexpected error during subscription sync for amendment {amendment_doc.name}: {str(e)}",
                "Mollie Subscription Sync Error",
            )
            return {
                "status": "error",
                "message": f"Unexpected error: {str(e)}",
                "requires_admin_review": True,
            }

    def _patch_subscription_amount(self, member, amendment_doc, live_subscription, new_amount):
        """PATCH the live subscription's amount, repairing drifted
        description/webhookUrl in the same call. Returns a sync-result dict."""
        payload = self._build_amount_patch_payload(member, live_subscription, new_amount)
        subscription_id = live_subscription["id"]

        try:
            updated = self.client.update_subscription(member.mollie_customer_id, subscription_id, payload)
        except Exception as patch_error:
            return {
                "status": "error",
                "reason": "patch_failed",
                "subscription_id": subscription_id,
                "message": f"Mollie PATCH failed: {str(patch_error)}",
                "requires_admin_review": True,
            }

        updated_amount = extract_amount_float(updated.amount)
        if abs(updated_amount - float(new_amount)) > 0.005:
            return {
                "status": "warning",
                "subscription_id": subscription_id,
                "message": (
                    f"PATCH returned amount {updated_amount}, expected {new_amount}. "
                    "Manual verification required."
                ),
                "requires_admin_review": True,
            }

        member.db_set(
            {
                "subscription_status": updated.status,
                "next_payment_date": getattr(updated, "next_payment_date", None),
            },
            update_modified=False,
        )

        repaired = [key for key in ("description", "webhookUrl") if key in payload]
        frappe.logger().info(
            f"✅ PATCHed subscription {subscription_id} for amendment {amendment_doc.name}: "
            f"amount -> {new_amount}" + (f", repaired drifted {', '.join(repaired)}" if repaired else "")
        )
        return {
            "status": "success",
            "subscription_id": subscription_id,
            "patched_fields": list(payload.keys()),
            "message": f"Subscription amount updated to {new_amount} via PATCH",
        }

    def _build_amount_patch_payload(self, member, live_subscription, new_amount) -> dict:
        """Amount always; description/webhookUrl only when the live values
        differ from the canonical ones (drift repair)."""
        payload = {"amount": format_mollie_amount(new_amount, "EUR")}

        canonical_description = get_member_subscription_description(member)
        if (live_subscription.get("description") or "") != canonical_description:
            payload["description"] = canonical_description

        canonical_webhook = frappe.get_single("Mollie Settings").get_subscription_webhook_url()
        if (live_subscription.get("webhook_url") or "") != canonical_webhook:
            payload["webhookUrl"] = canonical_webhook

        return payload

    def _mandate_id_for_replacement(self, member, live_subscription):
        """The live subscription's mandate is authoritative; the Member
        field is a fallback for subscriptions Mollie reports without one."""
        return live_subscription.get("mandate_id") or member.mollie_mandate_id

    def _create_replacement_subscription(
        self,
        member,
        amount,
        interval: str,
        start_date,
        amendment_name: str,
        previous_subscription_id: str,
    ):
        """
        Create the replacement Mollie subscription for an applied amendment.

        Builds the payload in the shape ``MollieClient.create_subscription``
        expects - a ``(customer_id, subscription_data)`` call where
        ``subscription_data`` is a dict. ``start_date``, when given, preserves
        the member's existing billing cycle.

        Args:
            member: Member document (provides customer id, name, full name)
            amount: Subscription amount in EUR
            interval: Mollie interval string (e.g. "1 month", "3 months")
            start_date: Optional ISO date for the first charge (billing cycle)
            amendment_name: Contribution Amendment Request name (metadata)
            previous_subscription_id: The subscription being replaced (metadata)

        Returns:
            The created Mollie subscription object

        Raises:
            MolliePaymentError: When the subscription cannot be created
        """
        subscription_data = {
            "amount": format_mollie_amount(amount, "EUR"),
            "interval": interval,
            "description": get_member_subscription_description(member),
            "webhookUrl": self._get_webhook_url(),
            "metadata": {
                "member_id": member.name,
                "subscription_type": "membership_dues",
                "amendment_id": amendment_name,
                "previous_subscription_id": previous_subscription_id,
            },
        }
        if start_date:
            subscription_data["startDate"] = start_date

        return self.client.create_subscription(member.mollie_customer_id, subscription_data)

    def _get_subscription_parameters(
        self, amendment_doc: "frappe.model.document.Document", membership: "frappe.model.document.Document"
    ) -> Tuple[float, str]:
        """
        Extract subscription parameters from amendment based on amendment type.

        Handles three amendment types with different parameter sources:
        1. Fee Change: New amount from amendment, interval from current dues schedule
        2. Membership Type Change: Amount and interval from requested membership type's template
        3. Billing Interval Change: Interval from amendment, amount from current dues schedule

        Args:
            amendment_doc: Contribution Amendment Request document containing:
                - amendment_type: Type of change being made
                - requested_amount: New billing amount (Fee Change, Type Change)
                - new_billing_interval: New billing frequency (Billing Interval Change)
                - requested_membership_type: Target membership type (Type Change)
            membership: Active Membership document for the member

        Returns:
            Tuple of (amount, interval) where:
                - amount (float): Monthly/quarterly/annual amount in EUR
                - interval (str): Mollie format ("1 month", "3 months", etc.)

        Raises:
            frappe.DoesNotExistError: If referenced membership type or template doesn't exist
        """
        # Handle different amendment types
        if amendment_doc.amendment_type == "Fee Change":
            # Fee Change: Keep interval same, only change amount
            amount = amendment_doc.requested_amount

            # Get interval from current dues schedule
            dues_schedule = self._get_membership_dues_schedule(membership.member)
            if dues_schedule:
                interval = BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(dues_schedule.billing_frequency, "1 month")
            else:
                interval = "1 month"

        elif amendment_doc.amendment_type == "Membership Type Change":
            # Membership Type Change: Get interval from new membership type, use requested_amount
            amount = amendment_doc.requested_amount

            # Get interval from the requested membership type's dues schedule template
            if amendment_doc.requested_membership_type:
                new_type_doc = frappe.get_doc("Membership Type", amendment_doc.requested_membership_type)

                if new_type_doc.dues_schedule_template:
                    template = frappe.get_doc("Membership Dues Schedule", new_type_doc.dues_schedule_template)
                    interval = BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(template.billing_frequency, "1 month")
                else:
                    # Fallback to monthly if no template
                    frappe.logger().warning(
                        f"⚠️ Membership Type {amendment_doc.requested_membership_type} has no dues schedule template, defaulting to monthly"
                    )
                    interval = "1 month"
            else:
                # Shouldn't happen, but fallback
                interval = "1 month"

        elif amendment_doc.amendment_type == "Billing Interval Change":
            # Billing Interval Change: Use requested interval
            interval = BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(amendment_doc.new_billing_interval, "1 month")

            # Get amount from current dues schedule
            dues_schedule = self._get_membership_dues_schedule(membership.member)
            amount = dues_schedule.dues_rate if dues_schedule else 0

        else:
            # Fallback for other amendment types
            dues_schedule = self._get_membership_dues_schedule(membership.member)
            amount = dues_schedule.dues_rate if dues_schedule else 0
            interval = (
                BILLING_INTERVAL_TO_MOLLIE_FORMAT.get(dues_schedule.billing_frequency, "1 month")
                if dues_schedule
                else "1 month"
            )

        return amount, interval

    def _verify_subscription_amount(
        self, member, membership, subscription_id: str, expected_amount: float, retry_on_mismatch: bool = True
    ) -> Dict[str, any]:
        """
        Verify subscription amount matches dues schedule.

        Args:
            member: Member document
            membership: Membership document
            subscription_id: Mollie subscription ID
            expected_amount: Expected subscription amount
            retry_on_mismatch: Whether to retry with fresh data if amounts don't match

        Returns:
            Dict with verification status and details
        """
        # Fetch current subscription from Mollie
        subscription_status = self.subscription_service.get_subscription_status(
            member.mollie_customer_id, subscription_id
        )

        mollie_amount = subscription_status.get("amount", 0)

        # Check if amounts match (within 0.01 EUR tolerance for rounding)
        if abs(mollie_amount - expected_amount) < 0.01:
            frappe.logger().info(
                f"✅ Subscription amount verified: {mollie_amount} EUR matches expected {expected_amount} EUR"
            )
            return {
                "verified": True,
                "mollie_amount": mollie_amount,
                "expected_amount": expected_amount,
                "message": "Subscription amount verified successfully",
            }

        frappe.logger().warning(
            f"⚠️ Subscription amount mismatch: Mollie reports {mollie_amount} EUR, expected {expected_amount} EUR"
        )

        # Retry with fresh data if requested
        if retry_on_mismatch:
            frappe.logger().info("🔄 Retrying verification with fresh data...")

            # Fetch fresh dues schedule
            dues_schedule = self._get_membership_dues_schedule(membership.member)
            if dues_schedule:
                fresh_expected_amount = dues_schedule.dues_rate

                # Check if fresh data matches Mollie
                if abs(mollie_amount - fresh_expected_amount) < 0.01:
                    frappe.logger().info(
                        f"✅ Retry successful: Subscription amount {mollie_amount} EUR matches fresh dues rate {fresh_expected_amount} EUR"
                    )
                    return {
                        "verified": True,
                        "mollie_amount": mollie_amount,
                        "expected_amount": fresh_expected_amount,
                        "message": "Subscription amount verified after retry",
                    }

        # Verification failed even after retry
        error_message = (
            f"Subscription amount mismatch: Mollie reports {mollie_amount} EUR, "
            f"but dues schedule shows {expected_amount} EUR. Requires administrator review."
        )

        frappe.log_error(
            f"Subscription amount mismatch for member {member.name}, subscription {subscription_id}\n"
            f"Mollie amount: {mollie_amount} EUR\n"
            f"Expected amount: {expected_amount} EUR\n"
            f"Membership: {membership.name}",
            "Mollie Subscription Amount Mismatch",
        )

        return {
            "verified": False,
            "mollie_amount": mollie_amount,
            "expected_amount": expected_amount,
            "message": error_message,
        }

    def _get_membership_dues_schedule(self, member_id: str):
        """Get active membership dues schedule for member."""
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_id, "docstatus": 1, "status": ["in", ["Active", "Scheduled"]]},
            fields=["name", "dues_rate", "billing_frequency"],
            order_by="creation desc",
            limit=1,
        )

        if schedules:
            return frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        return None

    def _get_webhook_url(self) -> str:
        """Canonical subscription webhook URL (Mollie Settings owns it)."""
        return frappe.get_single("Mollie Settings").get_subscription_webhook_url()
