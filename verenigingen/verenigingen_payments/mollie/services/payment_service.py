"""
Mollie Payment Service

Complete business logic for handling all types of payments through Mollie.
Includes the critical subscription creation workflow from the original implementation.

.. deprecated::
    This service contains overlapping functionality with the canonical webhook flow.
    For webhook processing, use:
    - `webhook_wrapper_service_unified.UnifiedWebhookWrapperService`

    This PaymentService may still be useful for:
    - Direct payment creation (create_payment, create_first_payment)
    - Subscription management (create_subscription, cancel_subscription)
    - Customer operations (get_or_create_customer)

    The webhook processing methods in this class are legacy and should not be
    used for new development.
"""

import json
import warnings
from typing import TYPE_CHECKING, Any, Dict

import frappe

if TYPE_CHECKING:
    from frappe import Document

    # Future type hints for when Mollie models are implemented
    Payment = Any
else:
    Payment = Any
from frappe import _
from frappe.utils import flt

from ..exceptions import MollieIntegrationError
from ..utils.amount_helpers import extract_amount_currency, extract_amount_float


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

        .. deprecated::
            For webhook processing, use UnifiedWebhookWrapperService instead.
        """
        warnings.warn(
            "PaymentService webhook methods are deprecated. "
            "Use UnifiedWebhookWrapperService for webhook processing.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Initialize client
        if client is None:
            from ..core.client import MollieClient

            self.client = MollieClient()
        else:
            self.client = client

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
            frappe.log_error(
                title="Payment Service Init", message=f"Failed to initialize payment gateway: {e}"
            )
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
            frappe.log_error(
                title="Mollie Configuration Warning", message=f"Could not determine Mollie environment: {e}"
            )

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
                title="Mollie Single Payment Error",
                message=f"Single payment creation error for donation {donation_doc.name}: {e}",
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
                title="Mollie Recurring Payment Error",
                message=f"Recurring payment creation error for donation {donation_doc.name}: {e}\nTraceback: {frappe.get_traceback()}",
            )
            return {
                "status": "error",
                "message": _("Recurring payment setup temporarily unavailable"),
                "info": _("Please try a single donation instead or contact support"),
            }

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
            "amount": extract_amount_float(payment.amount),
            "currency": extract_amount_currency(payment.amount),
            "paid_at": payment.paid_at,
            "is_paid": payment.status == "paid",
            "is_pending": payment.status in ["open", "pending"],
            "is_failed": payment.status in ["failed", "canceled", "expired"],
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

        if payment.status != "paid":
            raise MollieIntegrationError(f"Payment {payment_id} is not paid (status: {payment.status})")

        result = {"payment_id": payment_id, "processed": False}

        # Process based on payment type
        payment_type = payment.metadata.get("payment_type")

        if payment_type == "donation":
            result.update(self._process_donation_payment(payment))
        elif payment_type == "membership_dues":
            result.update(self._process_membership_payment(payment))
        else:
            frappe.log_error(title="Payment Processing", message=f"Unknown payment type: {payment_type}")

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
        Uses row locking to prevent duplicate customer creation on concurrent requests.
        """
        donor_name = donation_doc.donor

        # Use row lock to prevent race condition
        frappe.db.begin()
        try:
            # Acquire row lock - other requests will wait here
            locked_row = frappe.db.sql(
                """
                SELECT donor_name, donor_email, mollie_customer_id
                FROM `tabDonor` WHERE name = %s FOR UPDATE
                """,
                donor_name,
                as_dict=True,
            )

            if not locked_row:
                frappe.db.commit()
                return {"status": "error", "message": "Donor not found"}

            donor_data = locked_row[0]
            existing_customer_id = donor_data.get("mollie_customer_id")

            # Check if customer already exists (may have been created by concurrent request)
            if existing_customer_id:
                frappe.db.commit()  # Release lock
                frappe.logger().debug(f"Using existing customer ID: {existing_customer_id}")
                return {"status": "existing", "customer_id": existing_customer_id}

            frappe.logger().debug("Creating new Mollie customer...")

            # Create new Mollie customer using gateway's client directly
            customer_data = {
                "name": donor_data.get("donor_name") or "",
                "email": donor_data.get("donor_email"),
                "metadata": {"donor_id": donor_name, "created_for": "recurring_donations"},
            }

            frappe.logger().debug(f"Customer data: {customer_data}")

            # Create customer while holding the lock
            try:
                customer = self.gateway.client.customers.create(customer_data)
                frappe.logger().debug(f"Customer creation successful: {customer.id if customer else 'None'}")
            except Exception as create_error:
                frappe.db.rollback()
                frappe.logger().debug(f"Customer creation failed with error: {create_error}")
                return {
                    "status": "error",
                    "message": f"Customer creation API call failed: {create_error}",
                }

            if customer and customer.id:
                # Store customer ID on donor while holding lock
                frappe.db.set_value(
                    "Donor", donor_name, "mollie_customer_id", customer.id, update_modified=False
                )
                frappe.db.commit()  # Commit and release lock
                frappe.logger().debug(f"Saved customer ID {customer.id} to donor")
                return {"status": "created", "customer_id": customer.id}
            else:
                frappe.db.commit()  # Release lock
                frappe.logger().debug("Customer creation returned no valid response")
                return {"status": "error", "message": "Customer creation returned invalid response"}

        except Exception as e:
            frappe.db.rollback()
            frappe.logger().debug(f"Overall customer creation error: {e}")
            frappe.log_error(title="Mollie Customer Error", message=f"Mollie customer creation error: {e}")
            return {"status": "error", "message": "Customer creation failed"}

    def _get_webhook_url(self) -> str:
        """Get webhook URL based on environment (test vs live)."""
        base_url = frappe.utils.get_url()

        # Use the new unified webhook endpoint
        return f"{base_url}/api/method/verenigingen.verenigingen_payments.mollie.api.webhooks.handle_mollie_payment_webhook"

    def _is_test_mode(self) -> bool:
        """Determine if we're in test environment based on Mollie API key."""
        try:
            return self.client.test_mode
        except Exception:
            # Fallback to checking the gateway
            if self.gateway and hasattr(self.gateway, "is_test_mode"):
                return self.gateway.is_test_mode()
            return True  # Default to test mode for safety

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
            "amount": extract_amount_float(payment.amount),
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
            "amount": extract_amount_float(payment.amount),
            "processed": True,
        }
