"""
Mollie Payment Service

Handles payment creation for both single and recurring donations with proper
metadata encoding for webhook-driven donation creation.
"""

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

if TYPE_CHECKING:
    from frappe.model.document import Document


class MolliePaymentService:
    """
    Service for creating Mollie payments with proper metadata for webhook processing.

    Supports both single payments and first payments for subscription setup.
    """

    def __init__(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        self.gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        self._validate_donor_fields()

    def _validate_donor_fields(self):
        """Validate that Donor DocType has required Mollie fields."""
        donor_meta = frappe.get_meta("Donor")
        mollie_fields = ["mollie_customer_id", "mollie_mandate_id", "mollie_subscription_id"]

        missing_fields = []
        for field in mollie_fields:
            if not donor_meta.has_field(field):
                missing_fields.append(field)

        if missing_fields:
            frappe.throw(
                frappe._(
                    "Required Mollie fields missing from Donor DocType: {0}. Please add these as custom fields."
                ).format(", ".join(missing_fields))
            )

    def create_single_payment(self, donation_doc: "Document", form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single Mollie payment with metadata for webhook processing.

        Args:
            donation_doc: Non-submittable Donation document (draft state)
            form_data: Form data from donation submission

        Returns:
            Dict with payment_url, payment_id, and metadata for user redirect
        """
        try:
            # Create payment metadata for webhook processing
            payment_metadata = self._build_payment_metadata(donation_doc, form_data, is_recurring=False)

            # Set description to JSON metadata for webhook processing
            form_data_with_metadata = form_data.copy()
            form_data_with_metadata["description_override"] = json.dumps(
                payment_metadata, separators=(",", ":")
            )

            # Use gateway's process_payment method
            result = self.gateway.process_payment(donation_doc, form_data_with_metadata)

            if result.get("status") == "redirect_required":
                return {
                    "status": "redirect_required",
                    "payment_url": result["payment_url"],
                    "payment_id": result["payment_id"],
                    "message": _("Redirecting to Mollie for secure payment"),
                    "expires_at": result.get("expires_at"),
                }
            else:
                return {
                    "status": "error",
                    "message": result.get("message", _("Payment creation failed")),
                    "info": _("Please try again or contact support"),
                }

        except Exception as e:
            frappe.log_error(
                f"Single payment creation error for donation {donation_doc.name}: {str(e)}",
                "Mollie Single Payment Error",
            )
            return {
                "status": "error",
                "message": _("Payment setup temporarily unavailable"),
                "info": _("Please try again later or use a different payment method"),
            }

    def create_recurring_first_payment(
        self, donation_doc: "Document", form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create the first payment for a recurring donation to establish mandate.

        Args:
            donation_doc: Non-submittable Donation document (draft state)
            form_data: Form data including subscription interval

        Returns:
            Dict with payment_url, payment_id for mandate establishment
        """
        try:
            frappe.logger().debug(f"Starting recurring payment creation for donation {donation_doc.name}")

            # Create payment metadata for webhook processing
            payment_metadata = self._build_payment_metadata(donation_doc, form_data, is_recurring=True)
            frappe.logger().debug("Payment metadata created successfully")

            # Create or get customer first for recurring payments
            customer_result = self._create_or_get_mollie_customer(donation_doc, form_data)
            frappe.logger().debug(f"Customer result status: {customer_result.get('status')}")

            if not customer_result.get("customer_id"):
                frappe.logger().debug(f"Customer creation failed: {customer_result}")
                return {
                    "status": "error",
                    "message": _("Failed to create customer for recurring payment"),
                    "info": customer_result.get("message", "Customer creation failed"),
                }

            # Prepare form data for subscription setup
            form_data_with_metadata = form_data.copy()
            form_data_with_metadata.update(
                {
                    "description_override": json.dumps(payment_metadata, separators=(",", ":")),
                    "subscription_setup": True,  # Flag for sequenceType: "first"
                    "customer_id": customer_result["customer_id"],
                    "subscription_interval": form_data.get("subscription_interval", "1 month"),
                }
            )

            frappe.logger().debug(f"Form data prepared with customer_id: {customer_result['customer_id']}")

            # Use gateway's process_payment method
            result = self.gateway.process_payment(donation_doc, form_data_with_metadata)
            frappe.logger().debug(f"Gateway result status: {result.get('status')}")

            if result.get("status") == "redirect_required":
                return {
                    "status": "subscription_redirect_required",
                    "payment_url": result["payment_url"],
                    "payment_id": result["payment_id"],
                    "customer_id": customer_result["customer_id"],
                    "message": _("Setting up recurring donation"),
                    "info": _("After this payment, you'll be charged automatically each period"),
                    "expires_at": result.get("expires_at"),
                }
            else:
                frappe.logger().debug(
                    f"Gateway returned non-redirect status: {result.get('status')} - {result.get('message')}"
                )
                return {
                    "status": "error",
                    "message": result.get("message", _("Recurring payment setup failed")),
                    "info": _("Please try a single donation instead or contact support"),
                }

        except Exception as e:
            frappe.log_error(
                f"Recurring payment creation error for donation {donation_doc.name}: {str(e)}\nTraceback: {frappe.get_traceback()}",
                "Mollie Recurring Payment Error",
            )
            return {
                "status": "error",
                "message": _("Recurring payment setup temporarily unavailable"),
                "info": _("Please try a single donation instead or contact support"),
            }

    def _build_payment_metadata(
        self, donation_doc: "Document", form_data: Dict[str, Any], is_recurring: bool
    ) -> Dict[str, Any]:
        """
        Build payment metadata JSON for webhook processing.

        This metadata will be stored in the Mollie payment description and used
        by the webhook processor to create the final donation and payment records.
        """
        donor_doc = frappe.get_doc("Donor", donation_doc.donor)

        # Compact generic metadata to fit Mollie's description length limit (~255 chars)
        # Priority: type field first (most important for webhook processing)
        metadata = {
            "type": "recurring" if is_recurring else "single",
            "record_id": donation_doc.name,
            "customer_id": donor_doc.name,
            "amount": flt(donation_doc.amount),
        }

        # Add only essential recurring info to stay under length limit
        if is_recurring:
            interval = form_data.get("subscription_interval", "1 month")
            # Abbreviate some intervals but keep "day" as "day" since Mollie requires it
            interval_abbrev = interval.replace("month", "m").replace("week", "w")
            # Don't abbreviate "day" - Mollie API requires "1 day" format, not "1 d"
            metadata["interval"] = interval_abbrev

        return metadata

    def _create_or_get_mollie_customer(
        self, donation_doc: "Document", form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create or get existing Mollie customer for recurring payments.
        """
        try:
            donor_doc = frappe.get_doc("Donor", donation_doc.donor)
            frappe.logger().debug(f"Got donor doc: {donor_doc.donor_name} ({donor_doc.donor_email})")

            # Check if donor already has a Mollie customer ID
            # Field existence validated in __init__, so direct access is safe
            existing_customer_id = donor_doc.mollie_customer_id

            if existing_customer_id:
                frappe.logger().debug(f"Using existing customer ID: {existing_customer_id}")
                return {"status": "existing", "customer_id": existing_customer_id}

            frappe.logger().debug("Creating new Mollie customer...")
            # Create new Mollie customer using gateway's client directly
            customer_data = {
                "name": donor_doc.donor_name,
                "email": donor_doc.donor_email,
                "metadata": {"donor_id": donor_doc.name, "created_for": "recurring_donations"},
            }

            # Add phone if available
            if hasattr(donor_doc, "phone") and donor_doc.phone:
                customer_data["phone"] = donor_doc.phone

            frappe.logger().debug(f"Customer data: {customer_data}")
            frappe.logger().debug(f"Gateway client type: {type(self.gateway.client)}")

            # Create customer using Mollie client directly
            try:
                customer = self.gateway.client.customers.create(customer_data)
                frappe.logger().debug(f"Customer creation successful: {customer.id if customer else 'None'}")
            except Exception as create_error:
                frappe.logger().debug(f"Customer creation failed with error: {str(create_error)}")
                return {
                    "status": "error",
                    "message": f"Customer creation API call failed: {str(create_error)}",
                }

            if customer and customer.id:
                # Store customer ID on donor (handle guest user permissions for public donations)
                try:
                    donor_doc.mollie_customer_id = customer.id
                    # PUBLIC DONATION FLOW: Allow guest users to update donor with Mollie customer ID
                    donor_doc.flags.ignore_permissions = True
                    donor_doc.save()
                    frappe.db.commit()
                    frappe.logger().debug(f"Saved customer ID {customer.id} to donor")
                except Exception as e:
                    frappe.logger().debug(f"Failed to save customer ID: {str(e)}")
                    frappe.log_error(
                        f"Failed to save Mollie customer ID: {str(e)}", "Customer ID Storage Error"
                    )

                return {"status": "created", "customer_id": customer.id}
            else:
                frappe.logger().debug("Customer creation returned no valid response")
                return {"status": "error", "message": "Customer creation returned invalid response"}

        except Exception as e:
            frappe.logger().debug(f"Overall customer creation error: {str(e)}")
            frappe.log_error(f"Mollie customer creation error: {str(e)}", "Mollie Customer Error")
            return {"status": "error", "message": "Customer creation failed"}

    def _get_redirect_url(self, donation_id: str, result_type: str) -> str:
        """Get redirect URL for after payment completion."""
        base_url = frappe.utils.get_url()
        return f"{base_url}/donation-result?donation_id={donation_id}&result={result_type}"

    def _get_webhook_url(self) -> str:
        """Get webhook URL based on environment (test vs live)."""
        base_url = frappe.utils.get_url()

        # Determine if this is test or live environment
        # You might want to check Mollie settings or environment variables
        is_test_environment = self._is_test_environment()

        if is_test_environment:
            return f"{base_url}/api/method/verenigingen.api.mollie_payment_webhook.handle_mollie_payment_webhook?env=test"
        else:
            return f"{base_url}/api/method/verenigingen.api.mollie_payment_webhook.handle_mollie_payment_webhook?env=live"

    def _is_test_environment(self) -> bool:
        """Determine if we're in test environment based on Mollie API key."""
        try:
            # Check if Mollie API key starts with 'test_'
            mollie_settings = frappe.get_single("Mollie Settings")
            api_key = getattr(mollie_settings, "api_key", "")
            return api_key.startswith("test_")
        except Exception:
            # Default to test for safety
            return True

    def create_refund(
        self, payment_id: str, amount: Optional[float] = None, description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a refund for a Mollie payment.

        Args:
            payment_id: Mollie payment ID
            amount: Optional amount to refund (defaults to full payment amount)
            description: Optional refund description

        Returns:
            Dict with refund status and details
        """
        try:
            # Validate inputs
            if not payment_id:
                return {"status": "error", "message": _("Payment ID is required for refunds")}

            # Build refund data
            refund_data = {}

            if amount is not None:
                # Convert amount to Decimal for precise monetary calculations
                amount_decimal = Decimal(str(amount))
                if amount_decimal <= 0:
                    return {"status": "error", "message": _("Refund amount must be positive")}
                refund_data["amount"] = {"currency": "EUR", "value": f"{amount_decimal:.2f}"}

            if description:
                refund_data["description"] = description[:255]  # Mollie description limit

            # Create refund via Mollie API
            try:
                refund = self.gateway.client.payment_refunds.create(payment_id, refund_data)

                if refund and refund.id:
                    return {
                        "status": "success",
                        "refund_id": refund.id,
                        "amount": refund.amount.value if refund.amount else amount,
                        "currency": refund.amount.currency if refund.amount else "EUR",
                        "description": refund.description,
                        "refund_status": refund.status,
                        "created_at": refund.created_at.isoformat() if refund.created_at else None,
                        "message": _("Refund created successfully"),
                    }
                else:
                    return {"status": "error", "message": _("Refund creation returned invalid response")}

            except Exception as api_error:
                # Handle specific Mollie API errors
                error_message = str(api_error)
                if "payment is not paid" in error_message.lower():
                    return {"status": "error", "message": _("Cannot refund unpaid payment")}
                elif "insufficient" in error_message.lower():
                    return {"status": "error", "message": _("Insufficient funds available for refund")}
                elif "already refunded" in error_message.lower():
                    return {"status": "error", "message": _("Payment has already been fully refunded")}
                else:
                    frappe.log_error(
                        f"Mollie refund API error for payment {payment_id}: {error_message}",
                        "Mollie Refund API Error",
                    )
                    return {"status": "error", "message": _("Refund request failed - please try again")}

        except Exception as e:
            frappe.log_error(
                f"Refund creation error for payment {payment_id}: {str(e)}", "Mollie Refund Error"
            )
            return {"status": "error", "message": _("Refund processing temporarily unavailable")}

    def create_subscription(self, member, amount, interval, description=None):
        """
        Create a Mollie subscription for a member

        Args:
            member: Member document or name
            amount: Subscription amount
            interval: Payment interval (e.g., "1 month")
            description: Optional description

        Returns:
            Dict with subscription creation result
        """
        try:
            # Get member document if name provided
            if isinstance(member, str):
                member = frappe.get_doc("Member", member)

            # Validate member has required fields
            if not hasattr(member, "email") or not member.email:
                return {"success": False, "error": "Member must have email address"}

            # Create or get Mollie customer
            customer_result = self._create_or_get_mollie_customer(
                member.email, member.get_full_name(), {"member_id": member.name}
            )

            if not customer_result.get("success"):
                return customer_result

            customer_id = customer_result["customer_id"]

            # Create actual Mollie subscription
            subscription_data = {
                "amount": {"currency": "EUR", "value": f"{float(amount):.2f}"},
                "interval": interval,
                "description": description or f"Membership subscription for {member.get_full_name()}",
                "webhookUrl": f"{frappe.utils.get_url()}/api/method/verenigingen.api.mollie_payment_webhook",
                "metadata": {"member_id": member.name, "member_name": member.get_full_name()},
            }

            # Create subscription via Mollie API
            subscription = self.gateway.client.customer_subscriptions.with_parent_id(customer_id).create(
                subscription_data
            )
            subscription_id = subscription.id

            # Update member with Mollie information
            member.mollie_customer_id = customer_id
            member.mollie_subscription_id = subscription_id
            member.subscription_status = "active"
            member.next_payment_date = frappe.utils.add_days(frappe.utils.today(), 30)  # Monthly
            member.payment_method = "Mollie"
            member.save()

            # Log subscription creation
            frappe.logger().info(f"Mollie subscription created for member {member.name}: {subscription_id}")

            return {
                "success": True,
                "mollie_customer_id": customer_id,
                "subscription_id": subscription_id,
                "status": "active",
                "next_payment_date": member.next_payment_date,
                "member_updated": True,
            }

        except Exception as e:
            frappe.log_error(f"Subscription creation error: {str(e)}", "Mollie Subscription Error")
            return {"success": False, "error": str(e)}

    def update_subscription_amount(self, member, new_amount):
        """
        Update subscription amount for a member

        Args:
            member: Member document or name
            new_amount: New subscription amount

        Returns:
            Dict with update result
        """
        try:
            # Get member document if name provided
            if isinstance(member, str):
                member = frappe.get_doc("Member", member)

            # Validate member has subscription
            if not member.mollie_subscription_id:
                return {"success": False, "error": "Member does not have an active subscription"}

            # Update actual Mollie subscription
            subscription_id = member.mollie_subscription_id

            # Update subscription amount via Mollie API
            self.gateway.client.customer_subscriptions.with_parent_id(
                member.mollie_customer_id
            ).update(subscription_id, {"amount": {"currency": "EUR", "value": f"{float(new_amount):.2f}"}})

            # Log the successful update
            frappe.logger().info(
                f"Successfully updated Mollie subscription {subscription_id} amount to {new_amount}"
            )

            # Update member record after successful API call
            member.add_comment("Comment", f"Subscription amount updated to {new_amount}")
            member.save()

            return {
                "success": True,
                "subscription_id": subscription_id,
                "old_amount": member.get("subscription_amount", 0),
                "new_amount": new_amount,
                "updated_at": frappe.utils.now(),
                "member_name": member.name,
            }

        except Exception as e:
            frappe.log_error(f"Subscription update error: {str(e)}", "Mollie Subscription Error")
            return {"success": False, "error": str(e)}

    def cancel_subscription(self, member):
        """
        Cancel a member's subscription

        Args:
            member: Member document

        Returns:
            Dict with cancellation result
        """
        try:
            # Validate member and subscription
            if not member:
                frappe.logger().warning("Cancel subscription called with no member")
                return {"success": False, "error": "Member document is required"}

            if not hasattr(member, "mollie_subscription_id") or not member.mollie_subscription_id:
                frappe.logger().warning(f"Member {member.name} has no active subscription to cancel")
                return {"success": False, "error": "No active subscription found for member"}

            subscription_id = member.mollie_subscription_id
            frappe.logger().info(f"Cancelling subscription {subscription_id} for member {member.name}")

            # Cancel subscription via Mollie API
            self.gateway.client.customer_subscriptions.with_parent_id(
                member.mollie_customer_id
            ).delete(subscription_id)

            # Update member record
            old_status = member.subscription_status
            member.subscription_status = "cancelled"
            member.subscription_cancelled_at = frappe.utils.now()
            member.next_payment_date = None
            member.save()

            frappe.logger().info(
                f"Successfully cancelled subscription {subscription_id} for member {member.name}"
            )

            return {
                "success": True,
                "subscription_id": subscription_id,
                "old_status": old_status,
                "new_status": "cancelled",
                "cancelled_at": member.subscription_cancelled_at,
                "member_name": member.name,
            }

        except Exception as e:
            frappe.log_error(f"Subscription cancellation error: {str(e)}", "Mollie Subscription Error")
            frappe.logger().error(
                f"Failed to cancel subscription for member {member.name if member else 'unknown'}: {str(e)}"
            )
            return {"success": False, "error": str(e)}
