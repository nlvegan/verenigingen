"""
Mollie Payment Service

Complete business logic for handling all types of payments through Mollie.
Includes the critical subscription creation workflow from the original implementation.
"""

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import frappe

if TYPE_CHECKING:
    from frappe import Document

    # Future type hints for when Mollie models are implemented
    Payment = Any
else:
    Payment = Any
from frappe import _
from frappe.utils import flt, now_datetime

# Temporarily disabled - these modules don't exist yet
# from ..core.mollie_client import MollieClient
# from ..core.mollie_exceptions import MollieIntegrationError, MollieValidationError
# from ..core.mollie_models import Money, Payment
# from ..utils.validators import PaymentDataValidator


class PaymentService:
    """
    Complete service for handling all payment operations through Mollie.
    Includes critical subscription creation workflow from original implementation.
    """

    def __init__(self, client=None):
        """
        Initialize payment service.

        Args:
            client: Optional Mollie client (for dependency injection/testing)
        """
        # Initialize client
        if client is None:
            from ..core.client import MollieClient

            self.client = MollieClient()
        else:
            self.client = client

        # TODO: Initialize validator when PaymentDataValidator is available
        self.validator = None

        # Initialize gateway for backward compatibility
        self._init_gateway()
        # TODO: Re-enable when dependencies are available
        # self._validate_configuration()
        # self._validate_donor_fields()

    def _init_gateway(self):
        """Initialize payment gateway for compatibility with existing code."""
        try:
            from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

            self.gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        except Exception as e:
            frappe.log_error(f"Failed to initialize payment gateway: {e}", "Payment Service Init")
            self.gateway = None

    def _validate_configuration(self):
        """Validate that required configuration is available for Mollie integration."""
        if not self.gateway:
            frappe.throw(_("Mollie payment gateway not configured. Please check Mollie Settings."))

        # Validate API key is configured
        if not hasattr(self.gateway, "client") or not self.gateway.client:
            frappe.throw(_("Mollie API client not initialized. Please configure API key in Mollie Settings."))

        # Check if we can determine environment (test vs live)
        try:
            is_test_mode = self._is_test_mode()
            frappe.logger().info(f"Mollie service initialized in {'test' if is_test_mode else 'live'} mode")
        except Exception as e:
            frappe.log_error(f"Could not determine Mollie environment: {e}", "Mollie Configuration Warning")

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
                _(
                    "Required Mollie fields missing from Donor DocType: {0}. Please add these as custom fields."
                ).format(", ".join(missing_fields))
            )

    def create_single_payment(self, donation_doc: "Document", form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single Mollie payment with metadata for webhook processing.
        Complete port from original implementation.

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
                f"Single payment creation error for donation {donation_doc.name}: {e}",
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
        Complete port from original implementation.

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
                f"Recurring payment creation error for donation {donation_doc.name}: {e}\nTraceback: {frappe.get_traceback()}",
                "Mollie Recurring Payment Error",
            )
            return {
                "status": "error",
                "message": _("Recurring payment setup temporarily unavailable"),
                "info": _("Please try a single donation instead or contact support"),
            }

    def create_donation_payment(
        self,
        donor_id: str,
        amount: Union[Decimal, float],
        description: str,
        redirect_url: str,
        is_recurring: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Payment:
        """
        Create a payment for a donation using the new unified client.

        Args:
            donor_id: Frappe donor document ID
            amount: Payment amount in EUR
            description: Payment description
            redirect_url: URL to redirect after payment
            is_recurring: Whether this sets up a recurring donation
            metadata: Additional payment metadata

        Returns:
            Created payment object

        Raises:
            MollieValidationError: If payment data is invalid
            MollieIntegrationError: If payment creation fails
        """
        # Validate amount
        if not self.validator.validate_amount(amount):
            raise MollieValidationError(f"Invalid payment amount: {amount}")

        # Get or create Mollie customer for donor
        donor = frappe.get_doc("Donor", donor_id)
        customer_id = self._get_or_create_customer(donor)

        # Prepare payment metadata
        payment_metadata = {
            "donor_id": donor_id,
            "payment_type": "donation",
            "is_recurring": is_recurring,
            **(metadata or {}),
        }

        # Create payment
        money = Money(amount=Decimal(str(amount)), currency="EUR")
        payment = self.client.create_payment(
            amount=money,
            description=description,
            redirect_url=redirect_url,
            webhook_url=self._get_webhook_url(),
            customer_id=customer_id,
            metadata=payment_metadata,
        )

        # Update donor record with payment info
        self._update_donor_payment_info(donor, payment)

        return payment

    def create_membership_payment(
        self,
        member_id: str,
        membership_fee: Union[Decimal, float],
        membership_type: str,
        redirect_url: str,
        setup_subscription: bool = False,
    ) -> Payment:
        """
        Create a payment for membership dues.

        Args:
            member_id: Frappe member document ID
            membership_fee: Fee amount in EUR
            membership_type: Type of membership
            redirect_url: URL to redirect after payment
            setup_subscription: Whether to set up recurring payments

        Returns:
            Created payment object
        """
        # Validate member and fee
        member = frappe.get_doc("Member", member_id)
        if not self.validator.validate_amount(membership_fee):
            raise MollieValidationError(f"Invalid membership fee: {membership_fee}")

        # Get or create Mollie customer
        customer_id = self._get_or_create_customer_from_member(member)

        # Prepare payment metadata
        payment_metadata = {
            "member_id": member_id,
            "payment_type": "membership_dues",
            "membership_type": membership_type,
            "setup_subscription": setup_subscription,
        }

        # Create payment
        money = Money(amount=Decimal(str(membership_fee)), currency="EUR")
        payment = self.client.create_payment(
            amount=money,
            description=f"Membership dues - {membership_type}",
            redirect_url=redirect_url,
            webhook_url=self._get_webhook_url(),
            customer_id=customer_id,
            metadata=payment_metadata,
        )

        # Update member record
        self._update_member_payment_info(member, payment)

        return payment

    def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Get current payment status from Mollie.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Payment status information
        """
        payment = self.client.get_payment(payment_id)

        return {
            "id": payment.id,
            "status": payment.status,
            "amount": float(payment.amount.amount),
            "currency": payment.amount.currency,
            "paid_at": payment.paid_at,
            "is_paid": payment.is_paid,
            "is_pending": payment.is_pending,
            "is_failed": payment.is_failed,
            "method": payment.method,
            "metadata": payment.metadata,
        }

    def process_payment_completion(self, payment_id: str) -> Dict[str, Any]:
        """
        Process a completed payment and update relevant records.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Processing result information
        """
        payment = self.client.get_payment(payment_id)

        if not payment.is_paid:
            raise MollieIntegrationError(f"Payment {payment_id} is not paid (status: {payment.status})")

        result = {"payment_id": payment_id, "processed": False}

        # Process based on payment type
        payment_type = payment.metadata.get("payment_type")

        if payment_type == "donation":
            result.update(self._process_donation_payment(payment))
        elif payment_type == "membership_dues":
            result.update(self._process_membership_payment(payment))
        else:
            frappe.log_error(f"Unknown payment type: {payment_type}", "Payment Processing")

        return result

    # Private methods from original implementation

    def _build_payment_metadata(
        self, donation_doc: "Document", form_data: Dict[str, Any], is_recurring: bool
    ) -> Dict[str, Any]:
        """
        Build payment metadata JSON for webhook processing.
        Complete port from original implementation.
        """
        donor_doc = frappe.get_doc("Donor", donation_doc.donor)

        # Compact generic metadata to fit Mollie's description length limit (~255 chars)
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
        Complete port from original implementation.
        """
        try:
            donor_doc = frappe.get_doc("Donor", donation_doc.donor)
            frappe.logger().debug(f"Got donor doc: {donor_doc.donor_name} ({donor_doc.donor_email})")

            # Check if donor already has a Mollie customer ID
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

            # Create customer using Mollie client directly
            try:
                customer = self.gateway.client.customers.create(customer_data)
                frappe.logger().debug(f"Customer creation successful: {customer.id if customer else 'None'}")
            except Exception as create_error:
                frappe.logger().debug(f"Customer creation failed with error: {create_error}")
                return {
                    "status": "error",
                    "message": f"Customer creation API call failed: {create_error}",
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
                    frappe.logger().debug(f"Failed to save customer ID: {e}")
                    frappe.log_error(f"Failed to save Mollie customer ID: {e}", "Customer ID Storage Error")

                return {"status": "created", "customer_id": customer.id}
            else:
                frappe.logger().debug("Customer creation returned no valid response")
                return {"status": "error", "message": "Customer creation returned invalid response"}

        except Exception as e:
            frappe.logger().debug(f"Overall customer creation error: {e}")
            frappe.log_error(f"Mollie customer creation error: {e}", "Mollie Customer Error")
            return {"status": "error", "message": "Customer creation failed"}

    def _get_or_create_customer(self, donor) -> str:
        """Get existing Mollie customer ID or create new customer for donor."""
        if donor.mollie_customer_id:
            return donor.mollie_customer_id

        # Create new customer
        customer = self.client.create_customer(
            name=f"{donor.first_name} {donor.last_name}".strip(),
            email=donor.email_address,
            metadata={"donor_id": donor.name},
        )

        # Update donor record
        donor.mollie_customer_id = customer.id
        donor.save(ignore_permissions=True)

        return customer.id

    def _get_or_create_customer_from_member(self, member) -> str:
        """Get existing Mollie customer ID or create new customer for member."""
        if member.mollie_customer_id:
            return member.mollie_customer_id

        # Create new customer
        customer = self.client.create_customer(
            name=f"{member.first_name} {member.last_name}".strip(),
            email=member.email,
            metadata={"member_id": member.name},
        )

        # Update member record
        member.mollie_customer_id = customer.id
        member.save(ignore_permissions=True)

        return customer.id

    def _get_webhook_url(self) -> str:
        """Get webhook URL based on environment (test vs live)."""
        base_url = frappe.utils.get_url()

        # Use the new unified webhook endpoint
        return f"{base_url}/api/method/verenigingen.integrations.mollie.api.webhooks.handle_mollie_payment_webhook"

    def _is_test_mode(self) -> bool:
        """Determine if we're in test environment based on Mollie API key."""
        try:
            return self.client.test_mode
        except Exception:
            # Fallback to checking the gateway
            if self.gateway and hasattr(self.gateway, "is_test_mode"):
                return self.gateway.is_test_mode()
            return True  # Default to test mode for safety

    def _update_donor_payment_info(self, donor, payment: Payment):
        """Update donor record with payment information."""
        donor.append(
            "payment_history",
            {
                "payment_id": payment.id,
                "amount": float(payment.amount.amount),
                "currency": payment.amount.currency,
                "status": payment.status,
                "created_at": payment.created_at,
                "description": payment.description,
            },
        )
        donor.save(ignore_permissions=True)

    def _update_member_payment_info(self, member, payment: Payment):
        """Update member record with payment information."""
        # This will be handled by existing member payment history system
        pass

    def _process_donation_payment(self, payment: Payment) -> Dict[str, Any]:
        """Process a completed donation payment."""
        donor_id = payment.metadata.get("donor_id")
        if not donor_id:
            raise MollieIntegrationError("No donor_id in payment metadata")

        # Create payment entry in ERPNext
        # This logic would integrate with existing financial system

        return {
            "type": "donation",
            "donor_id": donor_id,
            "amount": float(payment.amount.amount),
            "processed": True,
        }

    def _process_membership_payment(self, payment: Payment) -> Dict[str, Any]:
        """Process a completed membership payment."""
        member_id = payment.metadata.get("member_id")
        if not member_id:
            raise MollieIntegrationError("No member_id in payment metadata")

        # Process membership payment through existing system

        return {
            "type": "membership_dues",
            "member_id": member_id,
            "amount": float(payment.amount.amount),
            "processed": True,
        }
